"""Validation runs: generate the clips of the validation set with named configs, score them against their hand-made
scripts, and compare runs (CLI: `validate`, `compare-runs`).

The clips, their groups and the configs are listed in validation.toml. A run lives in out/runs/NAME/:
  run.json            code version and settings of the run
  results.json        scores per config and clip (rewritten after every job, so an interrupted run keeps them)
  CONFIG/CLIP.*       the funscript, debug data and plot, and the generate log
  code/funscript_gen  a copy of the package the jobs run: editing src/ during a run changes nothing, and the run
                      can be traced later
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import shlex
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from funscript_gen.evaluate import compare, drop_wiggles, simple_extrema
from funscript_gen.export.funscript import Action, Funscript

MANIFEST = Path("validation.toml")
# Alias -> real clip name ([clips]), next to the manifest; private, in .gitignore.
PRIVATE_NAMES = "deidentify.local.toml"
RUNS_DIR = Path("out/runs")
VIDEO_SUFFIXES = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v")
# Scenes whose output follows (or mirrors) the hand-made script at least this well count for the direction tally.
SIGN_MIN_R = 0.3


@dataclass
class Clip:
    name: str
    group: str
    video: Path
    reference: Path


def load_manifest(path: Path = MANIFEST) -> dict:
    """The manifest, plus the real file names of its clips (`clip_files`) from the private names file next to it: the
    committed files call the clips by aliases only, and the names file is never committed."""
    with open(path, "rb") as f:
        manifest = tomllib.load(f)
    names = path.parent / PRIVATE_NAMES
    if names.exists():
        with open(names, "rb") as f:
            manifest["clip_files"] = tomllib.load(f).get("clips", {})
    return manifest


def _find(directory: Path, name: str, suffixes: tuple[str, ...]) -> Path | None:
    """The file named `name` or `name-<anything>` with one of `suffixes` (local clips carry the position in their
    name, e.g. A01-口交.mp4; the second test host uses the short name)."""
    hits = sorted(p for p in directory.iterdir()
                  if p.suffix.lower() in suffixes and (p.stem == name or p.stem.startswith(name + "-")))
    return hits[0] if hits else None


def clips(manifest: dict, selection: str = "", base: Path = Path(".")) -> list[Clip]:
    """The clips named by `selection`: comma-separated group names ("dev", "test"), clip names, or "all"; empty: the
    manifest's default_clips (the held-out group is left out of everyday runs), or all of them."""
    groups: dict[str, list[str]] = manifest["groups"]
    group_of = {c: g for g, names in groups.items() for c in names}
    selection = selection or ",".join(manifest.get("default_clips", ["all"]))
    wanted: list[str] = []
    for item in (s.strip() for s in selection.split(",")):
        if not item:
            continue
        names = list(group_of) if item == "all" else groups.get(item, [item])
        for n in names:
            if n not in group_of:
                raise ValueError(f"unknown clip or group: {n} (groups: {', '.join(groups)})")
            if n not in wanted:
                wanted.append(n)
    directory = base / manifest.get("clips_dir", "vaild")
    files = manifest.get("clip_files", {})
    out, missing = [], []
    for n in wanted:
        video = _find(directory, files.get(n, n), VIDEO_SUFFIXES)
        reference = _find(directory, files.get(n, n), (".funscript",))
        if video is None or reference is None:
            missing.append(n)
        else:
            out.append(Clip(n, group_of[n], video, reference))
    if missing:
        raise ValueError(f"no video or hand-made script in {directory} for: {', '.join(missing)}")
    return out


def config_args(manifest: dict, name: str) -> list[str]:
    configs = manifest.get("configs", {})
    if name not in configs:
        raise ValueError(f"unknown config: {name} (configs: {', '.join(configs)})")
    return [str(a) for a in configs[name]]


def _clean(v):
    if isinstance(v, float):
        return None if not math.isfinite(v) else round(v, 4)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, np.generic):
        return _clean(v.item())
    return v


def actions_sha(fs: Funscript) -> str:
    """Identifies the motion (actions only, not the metadata): equal hashes mean point-by-point equal scripts."""
    return hashlib.sha1(json.dumps([(a.at, a.pos) for a in fs.actions]).encode()).hexdigest()[:12]


def scene_scores(ref: Funscript, pred: Funscript, scenes: list[dict]) -> list[dict]:
    """Per scene of the debug data: zero-lag r of the output against the hand-made script (50 ms grid), turning
    points per second (hand-made simplified / output), the share of hand-made turning points with an output
    one of the same kind within 150 ms, and what the pipeline noted."""
    rt, _, rk = simple_extrema(ref)
    pt, _, pk = simple_extrema(pred, ratio=0.0, vibration=False)
    ra = ([a.at for a in ref.actions], [a.pos for a in ref.actions])
    pa = ([a.at for a in pred.actions], [a.pos for a in pred.actions])
    rows = []
    for k, sc in enumerate(scenes):
        s, e = float(sc["start_ms"]), float(sc["end_ms"])
        dur = max(e - s, 1.0) / 1000
        t = np.arange(s, e, 50.0)
        r = float("nan")
        if len(t) > 2 and len(ra[0]) > 1 and len(pa[0]) > 1:
            x, y = np.interp(t, *ra), np.interp(t, *pa)
            if x.std() > 0 and y.std() > 0:
                r = float(np.corrcoef(x, y)[0, 1])
        inside = np.flatnonzero((rt >= s) & (rt < e))
        lags = np.array([np.min(np.abs(pt[pk == rk[i]] - rt[i])) if (pk == rk[i]).any() else np.inf for i in inside])
        near = float(np.mean(lags <= 150)) if len(inside) else float("nan")
        mode = "rest" if sc.get("rest") else "skip" if sc.get("skip") else sc.get("mode")
        rows.append({
            "i": k, "start_ms": s, "end_ms": e, "mode": mode, "r": r,
            "ref_tps": len(inside) / dur, "out_tps": int(((pt >= s) & (pt < e)).sum()) / dur, "near_150": near,
            "tempo_hz": sc.get("tempo_hz"), "flipped": sc.get("flipped"), "sign_margin": sc.get("sign_margin"),
            "asym": sc.get("asym"), "audio_sign": sc.get("audio_sign"), "part_sign": sc.get("part_sign"),
            "note": sc.get("note") or "",
        })
    return rows


def direction_tally(scenes: list[dict]) -> dict:
    """Scenes with |r| >= SIGN_MIN_R and how many of them have the right sign, and the duration-weighted mean r."""
    moving = [s for s in scenes if s["mode"] not in ("rest", "skip") and s["r"] is not None and math.isfinite(s["r"])]
    clear = [s for s in moving if abs(s["r"]) >= SIGN_MIN_R]
    dur = sum(s["end_ms"] - s["start_ms"] for s in moving)
    mean_r = sum(s["r"] * (s["end_ms"] - s["start_ms"]) for s in moving) / dur if dur else float("nan")
    return {"sign_ok": sum(s["r"] > 0 for s in clear), "sign_n": len(clear), "scene_r": mean_r}


# Scenes with a flow signal weaker than this (standard deviation) and no part boxes are stretches the picture does not
# show a stroke in (the author followed the music there): `ignore_spans`. Only the clips listed under
# `ignore_low_flow` in validation.toml (the 3D series) are scored that way: in the others (E01) such scenes hold small
# strokes the author drew on purpose.
LOW_FLOW_STD = 2.0


def ignore_spans(scenes: list[dict]) -> list[tuple[float, float]]:
    """Time spans (ms) of the scenes whose flow is very low and where no part boxes were found."""
    spans = []
    for sc in scenes:
        raw = np.array([v for v in sc.get("raw") or [] if v is not None], float)
        if sc.get("rest") or sc.get("skip") or len(raw) < 3 or "parts_found" not in sc:
            continue
        if raw.std() < LOW_FLOW_STD and not sc["parts_found"]:
            spans.append((float(sc["start_ms"]), float(sc["end_ms"])))
    return spans


def _outside_points(ref: Funscript, spans: list[tuple[float, float]]) -> np.ndarray:
    t0, _, _ = simple_extrema(ref)
    return np.array([t for t in t0 if not any(a <= t < b for a, b in spans)])


def score(reference: Path, output: Path, debug: Path | None = None, ignore_low_flow: bool = False) -> dict:
    """Scores of `output` against the hand-made `reference`. `f1` skips the stretches in `ignore_spans` when
    `ignore_low_flow` (needs the debug data); `f1_noign` is the same without skipping, `f1_raw` the all-points measure until 2026-11-05."""
    ref, pred = Funscript.load(reference), Funscript.load(output)
    scenes_raw = json.loads(debug.read_text(encoding="utf-8"))["scenes"] if debug is not None and debug.exists() else None
    spans = ignore_spans(scenes_raw) if scenes_raw is not None and ignore_low_flow else []
    if spans and not len(_outside_points(ref, spans)):  # nothing left to judge: score the whole clip
        spans = []
    s = compare(ref, pred, ignore=spans)
    raw = compare(ref, pred, simplify=False)
    w = compare(drop_wiggles(ref), pred, simplify=False)
    out = {
        "f1": s.f1, "precision": s.precision, "recall": s.recall, "f1_strokes": w.f1, "f1_raw": raw.f1,
        "f1_noign": compare(ref, pred).f1 if spans else s.f1, "ignored_s": sum(b - a for a, b in spans) / 1000,
        "r100": s.correlation, "lag_ms": s.best_lag_ms, "r500": s.correlation_wide,
        "actions": len(pred.actions), "sha": actions_sha(pred),
    }
    if scenes_raw is not None:
        scenes = scene_scores(ref, pred, scenes_raw)
        up = compare(ref, upright(pred, scenes), ignore=spans)
        out |= direction_tally(scenes) | {"f1_upright": up.f1, "r_upright": up.correlation, "scenes": scenes}
    return _clean(out)


def upright(pred: Funscript, scenes: list[dict]) -> Funscript:
    """`pred` with every scene that moves against the hand-made script (scene r < 0) mirrored: its scores tell what the
    output would score with every direction right. A change that only turns scenes over leaves them alone, so they
    separate real gains from direction luck (one scene turned over moves a clip's F1 by about 0.2)."""
    spans = [(s["start_ms"], s["end_ms"]) for s in scenes if s["mode"] not in ("rest", "skip")
             and s["r"] is not None and math.isfinite(s["r"]) and s["r"] < 0]
    flip = lambda at: any(a <= at < b for a, b in spans)  # noqa: E731
    acts = [Action(a.at, 100 - a.pos) if flip(a.at) else a for a in pred.actions]
    return Funscript(acts, pred.inverted, pred.range, dict(pred.metadata))


def snapshot(run_dir: Path, source: Path | None = None) -> tuple[Path, dict]:
    """Copy the package (the installed one, or `source`/funscript_gen) into the run; returns the directory to put on
    PYTHONPATH and where the code came from."""
    from funscript_gen.version import PACKAGE_DIR, code_hash, git_state

    package = (source / "funscript_gen") if source is not None else PACKAGE_DIR
    if not (package / "__init__.py").exists():
        raise ValueError(f"no funscript_gen package in {package.parent}")
    dest = run_dir / "code" / "funscript_gen"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(package, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return run_dir / "code", {"source": str(package.resolve()), "code": code_hash(package)} | (git_state(package) or {})


def _duration_s(video: Path) -> float:
    from funscript_gen.video.decoder import probe

    try:
        return probe(video).duration_ms / 1000
    except Exception:  # noqa: BLE001 - only used to start the long clips first
        return 0.0


class Run:
    """One run directory: its settings and results, saved as they change."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.meta = _read_json(path / "run.json") or {}
        self.results = _read_json(path / "results.json") or {"configs": {}}

    def done(self, config: str, clip: str) -> bool:
        got = self.results["configs"].get(config, {}).get("clips", {}).get(clip)
        return bool(got) and "error" not in got and (self.path / config / f"{clip}.funscript").exists()

    def record(self, config: str, args: list[str], clip: str, value: dict) -> None:
        with self.lock:
            entry = self.results["configs"].setdefault(config, {"args": args, "clips": {}})
            entry["args"] = args
            entry["clips"][clip] = value
            self.save()

    def save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        _write_json(self.path / "run.json", self.meta)
        _write_json(self.path / "results.json", self.results)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def replay_one(clip: Clip, args: list[str], out: Path, source: Path) -> None:
    """Render the clip's analysis saved in run `source` (any config whose analysis fits `args`) with `args`, into
    `out` and its debug data: what a full run would give, in seconds."""
    from funscript_gen.cli import parse_generate_args
    from funscript_gen.options import analysis_key, build, for_analysis, resolve
    from funscript_gen.pipeline import load_analysis, render
    from funscript_gen.report import debug_data

    given, preset = parse_generate_args(args)
    want = analysis_key(resolve(given, preset))
    for path in sorted(source.glob(f"*/{clip.name}.analysis.pkl")):
        analysis = load_analysis(path)
        if analysis.serves(clip.video.resolve(), want):
            break
    else:
        raise ValueError(f"no analysis of {clip.name} in {source} fits these settings")
    result = render(analysis, build(for_analysis(analysis.key, given, preset)))
    result.funscript.save(out)
    out.with_suffix(".debug.json").write_text(json.dumps(debug_data(result)), encoding="utf-8")


def run_validation(
    name: str, configs: list[str], selection: str = "", jobs: int = 3, flow_workers: int = 4,
    extra: str = "", resume: bool = False, code: Path | None = None, manifest_path: Path = MANIFEST,
    runs_dir: Path = RUNS_DIR, say: Callable[[str], None] = print, save_analysis: bool = True,
    replay: Path | None = None,
) -> Run:
    """Generate every selected clip with every config (`jobs` processes at a time) and score it. With `replay`, render
    the analyses saved by that run instead (in this process, with the code of this checkout)."""
    manifest = load_manifest(manifest_path)
    todo_clips = clips(manifest, selection, manifest_path.parent)
    args = {c: config_args(manifest, c) for c in configs}
    extra_args = shlex.split(extra)
    run = Run(runs_dir / name)
    if (run.path / "results.json").exists() and not resume:
        raise ValueError(f"{run.path} exists: use --resume to add to it, or another name")
    if replay is not None and code is not None:
        raise ValueError("--code does not apply to --replay (it renders in this process): run the replay from that "
                         "checkout, e.g. cd into the worktree and pass absolute run paths")
    if resume and code is None and replay is None and (run.path / "code" / "funscript_gen").exists():
        code_dir, code_info = run.path / "code", run.meta.get("code", {})  # the run goes on with its own code
    else:
        code_dir, code_info = snapshot(run.path, code)  # (a replay runs in this process, with this checkout's code)
    run.meta = run.meta | {
        "name": name, "host": platform.node(), "python": sys.version.split()[0], "code": code_info,
        "started": run.meta.get("started") or datetime.now().isoformat(timespec="seconds"),
        "manifest": str(manifest_path), "jobs": jobs, "flow_workers": flow_workers, "extra_args": extra_args,
        "replay_of": str(replay) if replay is not None else None,
        "configs": run.meta.get("configs", {}) | args,
        "clips": sorted(set(run.meta.get("clips", [])) | {c.name for c in todo_clips}),
    }
    run.save()
    # Long clips first, so the last jobs to finish are short ones.
    order = sorted(todo_clips, key=lambda c: _duration_s(c.video), reverse=True)
    pending = [(c, cfg) for c in order for cfg in configs if not (resume and run.done(cfg, c.name))]
    # PYTHONUTF8: the log is UTF-8 whatever the console code page is (cp1252 cannot encode the notes).
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=os.pathsep.join(filter(None, [str(code_dir.resolve()), os.environ.get("PYTHONPATH")])))
    counter = {"n": 0}

    def one(job: tuple[Clip, str]) -> None:
        clip, cfg = job
        out = run.path / cfg / f"{clip.name}.funscript"
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "funscript_gen.cli", "generate", str(clip.video.resolve()), "-o", str(out),
               "--debug", "--flow-workers", str(flow_workers), *args[cfg], *extra_args]
        if save_analysis:
            cmd += ["--save-analysis", str(out.with_suffix(".analysis.pkl"))]
        t0 = time.monotonic()
        failed = None
        if replay is not None:
            try:
                replay_one(clip, args[cfg] + extra_args, out, replay)
            except Exception as e:  # noqa: BLE001 - recorded, the other jobs go on
                failed = f"replay failed: {e}"
        else:
            with open(out.with_suffix(".log"), "w", encoding="utf-8") as log:
                proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
            if proc.returncode != 0:
                failed = f"generate exited with {proc.returncode}, see {out.with_suffix('.log')}"
        seconds = round(time.monotonic() - t0, 1)
        if failed:
            value = {"error": failed, "seconds": seconds}
        else:
            try:
                value = score(clip.reference, out, out.with_suffix(".debug.json"),
                              clip.name in manifest.get("ignore_low_flow", [])) | {"seconds": seconds}
            except Exception as e:  # noqa: BLE001 - recorded, the other jobs go on
                value = {"error": f"scoring failed: {e}", "seconds": seconds}
        run.record(cfg, args[cfg] + extra_args, clip.name, value)
        with run.lock:
            counter["n"] += 1
            done = counter["n"]
        what = value.get("error") or (f"F1 {value['f1']:.3f}  F1s {value['f1_strokes']:.3f}  "
                                      f"r {_fmt(value.get('r100'))}  r500 {_fmt(value.get('r500'))}")
        say(f"[{done}/{len(pending)}] {cfg}/{clip.name}: {what} ({seconds:.0f} s)")

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            list(pool.map(one, pending))
    run.meta["finished"] = datetime.now().isoformat(timespec="seconds")
    run.save()
    return run


# --- Reports --------------------------------------------------------------------------------------------------------

METRICS = ("f1", "f1_strokes", "r100", "r500", "f1_upright", "r_upright")
# r: the correlation within +-100 ms (evaluate.LAG_MS); r500: within +-500 ms, as recorded before 2026-10-31;
# F1u, ru: F1 and r with every scene turned the right way up (see upright), not in results before 2026-11-03
HEADS = {"f1": "F1", "f1_strokes": "F1s", "r100": "r", "r500": "r500", "f1_upright": "F1u", "r_upright": "ru"}
# Results written before 2026-10-31 named them "corr_100" and "corr" (then the headline was the +-500 ms one).
_OLD_NAMES = {"corr_100": "r100", "corr": "r500"}


def _fmt(v, width: int = 0) -> str:
    s = "-" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"{v:.3f}"
    return s.rjust(width) if width else s


def load_runs(paths: list[Path]) -> tuple[dict, dict]:
    """Results of several runs merged per config and clip (later runs win), and their run.json files."""
    merged: dict[str, dict] = {}
    metas = {}
    for p in paths:
        data = _read_json(p / "results.json")
        if data is None:
            raise ValueError(f"no results.json in {p}")
        metas[str(p)] = _read_json(p / "run.json") or {}
        for cfg, entry in data["configs"].items():
            m = merged.setdefault(cfg, {"args": entry.get("args", []), "clips": {}})
            m["clips"] |= {c: {_OLD_NAMES.get(k, k): x for k, x in v.items()}
                           for c, v in entry["clips"].items() if "error" not in v}
    return merged, metas


def _groups(manifest: dict | None, names) -> dict[str, list[str]]:
    groups = {g: [c for c in cs if c in names] for g, cs in (manifest or {}).get("groups", {}).items()}
    groups = {g: cs for g, cs in groups.items() if cs}
    return groups | {"all": [c for c in names]}


def _mean(values) -> float:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    return float(np.mean(vals)) if vals else float("nan")


def summary(merged: dict, manifest: dict | None = None, configs: list[str] | None = None) -> str:
    lines = []
    order = (manifest or {}).get("groups", {})
    rank = {c: k for k, c in enumerate(c for cs in order.values() for c in cs)}
    for cfg in configs or list(merged):
        if cfg not in merged:
            lines.append(f"== {cfg}: not in these runs")
            continue
        entry = merged[cfg]
        names = sorted(entry["clips"], key=lambda c: (rank.get(c, len(rank)), c))
        lines.append(f"== {cfg}  {' '.join(entry['args']) or '(defaults)'}")
        lines.append(f"{'clip':10}" + "".join(f"{HEADS[m]:>7}" for m in METRICS) + "  sign ok/n  actions    sec")
        for c in names:
            v = entry["clips"][c]
            sign = f"{v.get('sign_ok', '-')}/{v.get('sign_n', '-')}"
            lines.append(f"{c:10}" + "".join(_fmt(v.get(m), 7) for m in METRICS)
                         + f"  {sign:>9}  {v.get('actions', 0):7}  {v.get('seconds', 0):5.0f}")
        for g, cs in _groups(manifest, names).items():
            vals = [entry["clips"][c] for c in cs]
            ok, n = sum(v.get("sign_ok", 0) for v in vals), sum(v.get("sign_n", 0) for v in vals)
            lines.append(f"{'mean ' + g:10}" + "".join(_fmt(_mean(v.get(m) for v in vals), 7) for m in METRICS)
                         + f"  {f'{ok}/{n}':>9}  ({len(cs)} clips)")
        lines.append("")
    return "\n".join(lines)


def comparison(merged: dict, base: dict, manifest: dict | None = None, configs: list[str] | None = None) -> str:
    """Per config and clip present in both: the change of each metric and whether the motion is identical."""
    lines = []
    for cfg in configs or [c for c in merged if c in base]:
        if cfg not in merged or cfg not in base:
            lines.append(f"== {cfg}: missing in {'the baseline' if cfg not in base else 'these runs'}")
            continue
        new, old = merged[cfg]["clips"], base[cfg]["clips"]
        names = [c for c in new if c in old]
        same = [c for c in names if new[c].get("sha") == old[c].get("sha")]
        lines.append(f"== {cfg}: {len(same)}/{len(names)} clips with identical actions")
        lines.append(f"{'clip':10}" + "".join(f"{'Δ' + HEADS[m]:>8}" for m in METRICS) + "  identical")
        rank = {c: k for k, c in enumerate(c for cs in (manifest or {}).get("groups", {}).values() for c in cs)}
        for c in sorted(names, key=lambda c: (rank.get(c, len(rank)), c)):
            d = {m: _delta(new[c].get(m), old[c].get(m)) for m in METRICS}
            lines.append(f"{c:10}" + "".join(f"{_signed(d[m]):>8}" for m in METRICS)
                         + f"  {'yes' if c in same else 'no'}")
        for g, cs in _groups(manifest, names).items():
            parts = []
            for m in METRICS:
                a, b = _mean(new[c].get(m) for c in cs), _mean(old[c].get(m) for c in cs)
                parts.append(f"{HEADS[m]} {_fmt(b)} → {_fmt(a)}")
            up = sum(_delta(new[c].get("f1"), old[c].get("f1")) > 0.005 for c in cs)
            down = sum(_delta(new[c].get("f1"), old[c].get("f1")) < -0.005 for c in cs)
            lines.append(f"  {g} ({len(cs)}): " + ", ".join(parts) + f"; F1 up {up}, down {down}")
        lines.append("")
    return "\n".join(lines)


def _delta(a, b) -> float:
    if a is None or b is None:
        return float("nan")
    return float(a) - float(b)


def _signed(v: float) -> str:
    return "-" if not math.isfinite(v) else f"{v:+.3f}"


def scene_table(merged: dict, clip: str, configs: list[str] | None = None) -> str:
    lines = []
    for cfg in configs or list(merged):
        v = merged.get(cfg, {}).get("clips", {}).get(clip)
        if not v or "scenes" not in v:
            continue
        lines.append(f"== {cfg}/{clip}")
        for s in v["scenes"]:
            flags = " ".join(k for k in ("flipped",) if s.get(k))
            lines.append(f"  #{s['i']:2} {s['start_ms'] / 1000:6.1f}s {(s['end_ms'] - s['start_ms']) / 1000:5.1f}s "
                         f"r {_signed(s['r'] if s['r'] is not None else float('nan')):>6} "
                         f"tp/s {s['ref_tps']:4.1f}/{s['out_tps']:4.1f} near {_fmt(s['near_150'])} "
                         f"{s['mode'] or '':4} {flags} {s['note'][:80]}")
    return "\n".join(lines)
