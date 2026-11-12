"""Offline: the direction evidence of every scene whose stroke sign is open (fall/rise asymmetry, sound onsets, part
boxes), the true sign from the hand-made script, and how well rules that combine the evidence get the sign right:
the hand-set thresholds of --asym-sign / --part-sign, and logistic models fit with leave-one-clip-out
cross-validation (each clip is judged by a model fit on the other clips only).

Scenes are judged in groups: the chunks of one long shot that chunk alignment linked (as the asymmetry check does).
The truth of a group is its scenes' zero-lag correlation with the hand-made script (duration-weighted); groups with
|r| < MIN_R are left out of fitting and scoring.

usage: uv run python scripts/sign_model.py RUN [CONFIG ...]
       RUN: a `validate` run with saved analyses whose configs ran with --part-sign (default: default user)
"""
import json
import sys
from pathlib import Path

import numpy as np

from funscript_gen.cli import parse_generate_args
from funscript_gen.export.funscript import Funscript
from funscript_gen.options import build, for_analysis
from funscript_gen.direction import _cosine
from funscript_gen.pipeline import load_analysis, render_signals
from funscript_gen.signal.audio import onset_phase
from funscript_gen.signal.process import fall_rise_asymmetry
from funscript_gen.tracking.parts import distance_sign, penis_vulva_distance
from funscript_gen.validate import clips, load_manifest

MIN_R = 0.2


def scene_rows(run: Path, config: str, args: list[str], clip) -> list[dict]:
    given, preset = parse_generate_args(args)
    analysis = load_analysis(run / config / f"{clip.name}.analysis.pkl")
    opts = build(for_analysis(analysis.key, given, preset))
    plans = render_signals(analysis, opts)
    ref = Funscript.load(clip.reference)
    rt, rp = [a.at for a in ref.actions], [a.pos for a in ref.actions]
    rows, prev = [], None
    for plan in plans:
        if plan.signal is None or plan.flow_position is None or plan.skip:
            prev = None
            continue
        t, x = plan.flow_position
        ok = np.isfinite(x)
        y = np.interp(t, rt, rp)
        r = float(np.corrcoef(x[ok], y[ok])[0, 1]) if ok.sum() > 10 and x[ok].std() > 0 and y[ok].std() > 0 else 0.0
        asym, n = fall_rise_asymmetry(x, opts.fps)
        audio = onset_phase(t, x, *analysis.envelope, opts.asym_audio_phase) if analysis.envelope is not None else None
        part = None
        if plan.parts_found is not None:
            times, boxes, size = plan.parts_found
            dist, edge = penis_vulva_distance(boxes, size)
            if edge < opts.part_max_edge:
                part = distance_sign(np.array(times), dist, t, x, opts.part_fps, opts.part_min_cover)
        linked = prev is not None and plan.scene.continued and prev.scene.index == plan.scene.index - 1 \
            and plan.sign_pattern is not None and prev.sign_pattern is not None \
            and _cosine(plan.sign_pattern, prev.sign_pattern) >= opts.chunk_align_similarity
        rows.append({"clip": clip.name, "group_of": clip.group, "scene": plan.scene.index, "linked": linked,
                     "dur": (plan.scene.end_ms - plan.scene.start_ms) / 1000, "r": r, "asym": asym, "n": n,
                     "audio": audio, "part": part, "margin": plan.sign_margin})
        prev = plan
    return rows


def groups(rows: list[dict]) -> list[list[dict]]:
    out = []
    for row in rows:
        if row["linked"] and out and out[-1][-1]["clip"] == row["clip"]:
            out[-1].append(row)
        else:
            out.append([row])
    return out


def features(g: list[dict]) -> dict:
    """Group evidence, each positive when it says the output is upside down."""
    dur = sum(r["dur"] for r in g)
    n = sum(r["n"] for r in g)
    heard = [(r["audio"], r["dur"]) for r in g if r["audio"] is not None]
    seen = [(r["part"], r["dur"]) for r in g if r["part"] is not None]
    return {
        "asym": sum(r["asym"] * r["n"] for r in g) / n if n else 0.0,
        "strokes": n,
        "audio": -sum(a * d for a, d in heard) / sum(d for _, d in heard) if heard else 0.0,
        "part": -sum(p * d for p, d in seen) / sum(d for _, d in seen) if seen else 0.0,
        "has_part": bool(seen),
        "truth": sum(r["r"] * r["dur"] for r in g) / dur,  # > 0: the output follows the script
        "dur": dur,
    }


RULE = (0.2, 0.5, 0.2, 0.3)  # part, asymmetry, asymmetry with the sound backing it, sound: the pipeline's defaults


def rule(g: list[dict], f: dict, th=RULE) -> bool:
    """--part-sign then --asym-sign as in pipeline.flip_by_parts / flip_by_asymmetry (one group at a time)."""
    part_t, asym_t, backed_t, audio_t = th
    if any(r["part"] is not None and r["part"] <= -part_t for r in g):
        return True  # (the pipeline flips the scene itself; a group usually agrees)
    if f["strokes"] < 4:
        return False
    return f["asym"] > (backed_t if f["audio"] > audio_t else asym_t)


def current_rule(g: list[dict], f: dict) -> bool:
    return rule(g, f)


GRID = [(p, a, b, s) for p in (0.1, 0.15, 0.2, 0.3, 0.4) for a in (0.3, 0.4, 0.5, 0.6, 0.8)
        for b in (0.1, 0.2, 0.3) for s in (0.2, 0.3, 0.4, 0.5) if b < a]


def loco_rule(gs: list[list[dict]]) -> dict[str, tuple]:
    """Per clip: the rule's thresholds that get the most labelled groups (by duration) right on the other clips;
    ties go to the thresholds nearest the pipeline's."""
    out = {}
    for clip in sorted({g[0]["clip"] for g in gs}):
        train = [(g, features(g)) for g in gs if g[0]["clip"] != clip and abs(features(g)["truth"]) >= MIN_R]

        def score(th):
            right = sum(f["dur"] for g, f in train if (rule(g, f, th) == (f["truth"] < 0)))
            return right, -sum(abs(x - y) for x, y in zip(th, RULE))

        out[clip] = max(GRID, key=score)
    return out


def design(f: dict, names: tuple[str, ...]) -> np.ndarray:
    cols = {"asym": f["asym"], "audio": f["audio"], "part": f["part"], "asym_x_audio": f["asym"] * max(f["audio"], 0.0),
            "part_sign": float(np.sign(f["part"])) if abs(f["part"]) >= 0.2 else 0.0}
    return np.array([1.0] + [cols[n] for n in names])


def fit(X: np.ndarray, y: np.ndarray, w: np.ndarray, ridge: float = 1.0) -> np.ndarray:
    """Weighted logistic regression by Newton steps, the intercept unpenalized."""
    beta = np.zeros(X.shape[1])
    pen = np.full(X.shape[1], ridge)
    pen[0] = 0.0
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ beta))
        grad = X.T @ (w * (p - y)) + pen * beta
        hess = (X * (w * p * (1 - p))[:, None]).T @ X + np.diag(pen)
        step = np.linalg.solve(hess, grad)
        beta -= step
        if np.abs(step).max() < 1e-8:
            break
    return beta


def evaluate(gs: list[list[dict]], decide) -> dict:
    """Over labelled groups: right-sign count and duration, and the duration-weighted signed correlation."""
    ok = n = 0
    dur_ok = dur = 0.0
    signed = 0.0
    for g in gs:
        f = features(g)
        flip = decide(g, f)
        r = -f["truth"] if flip else f["truth"]
        signed += r * f["dur"]
        if abs(f["truth"]) >= MIN_R:
            n += 1
            dur += f["dur"]
            if r > 0:
                ok += 1
                dur_ok += f["dur"]
    total = sum(features(g)["dur"] for g in gs)
    return {"ok": ok, "n": n, "dur_share": dur_ok / dur if dur else 0.0, "signed_r": signed / total}


def loco(gs: list[list[dict]], names: tuple[str, ...], ridge: float) -> dict[str, np.ndarray]:
    """Per clip: the model fit on the labelled groups of every other clip."""
    models = {}
    for clip in sorted({g[0]["clip"] for g in gs}):
        train = [g for g in gs if g[0]["clip"] != clip and abs(features(g)["truth"]) >= MIN_R]
        X = np.array([design(features(g), names) for g in train])
        y = np.array([features(g)["truth"] < 0 for g in train], float)
        w = np.array([features(g)["dur"] for g in train])
        models[clip] = fit(X, y, w / w.mean(), ridge)
    return models


def main() -> None:
    run = Path(sys.argv[1])
    configs = sys.argv[2:] or ["default", "user"]
    manifest = load_manifest()
    meta = json.loads((run / "run.json").read_text())
    for config in configs:
        rows = []
        for clip in clips(manifest, "all"):
            if (run / config / f"{clip.name}.analysis.pkl").exists():
                rows += scene_rows(run, config, meta["configs"][config], clip)
        gs = groups(rows)
        labelled = [g for g in gs if abs(features(g)["truth"]) >= MIN_R]
        print(f"== {config}: {len(rows)} scenes, {len(gs)} groups, {len(labelled)} with |r| >= {MIN_R}")
        for split in ("dev", "test", "all"):
            sub = [g for g in gs if split == "all" or g[0]["group_of"] == split]
            base = evaluate(sub, lambda g, f: False)
            cur = evaluate(sub, current_rule)
            print(f"  {split:4} keep {base['ok']}/{base['n']} ({base['dur_share']:.2f}, r {base['signed_r']:+.3f})"
                  f"  current {cur['ok']}/{cur['n']} ({cur['dur_share']:.2f}, r {cur['signed_r']:+.3f})")
        for names in (("asym",), ("asym", "audio"), ("asym", "part"), ("asym", "audio", "part"),
                      ("asym", "audio", "part", "asym_x_audio")):
            for ridge in (0.3, 1.0, 3.0):
                models = loco(gs, names, ridge)
                decide = lambda g, f: float(design(f, names) @ models[g[0]["clip"]]) > 0  # noqa: E731
                res = {s: evaluate([g for g in gs if s == "all" or g[0]["group_of"] == s], decide)
                       for s in ("dev", "test", "all")}
                print(f"  model {'+'.join(names):28} ridge {ridge:3}: " + "  ".join(
                    f"{s} {v['ok']}/{v['n']} ({v['dur_share']:.2f}, r {v['signed_r']:+.3f})" for s, v in res.items()))
        chosen = loco_rule(gs)
        res = {s: evaluate([g for g in gs if s == "all" or g[0]["group_of"] == s],
                           lambda g, f: rule(g, f, chosen[g[0]["clip"]])) for s in ("dev", "test", "all")}
        print("  rule, thresholds chosen without the clip: " + "  ".join(
            f"{s} {v['ok']}/{v['n']} ({v['dur_share']:.2f}, r {v['signed_r']:+.3f})" for s, v in res.items()))
        from collections import Counter
        print("    thresholds (part, asym, asym with sound, sound) chosen per clip:",
              Counter(chosen.values()).most_common(4))
        for names in (("part_sign", "asym", "asym_x_audio"), ("part_sign", "asym", "audio", "asym_x_audio")):
            models = loco(gs, names, 0.01)
            decide = lambda g, f: float(design(f, names) @ models[g[0]["clip"]]) > 0  # noqa: E731
            res = {s: evaluate([g for g in gs if s == "all" or g[0]["group_of"] == s], decide) for s in ("dev", "test", "all")}
            print(f"  model {'+'.join(names):28} ridge 0.01: " + "  ".join(
                f"{s} {v['ok']}/{v['n']} ({v['dur_share']:.2f}, r {v['signed_r']:+.3f})" for s, v in res.items()))
        full = fit(np.array([design(features(g), ("asym", "audio", "part")) for g in labelled]),
                   np.array([features(g)["truth"] < 0 for g in labelled], float),
                   np.array([features(g)["dur"] for g in labelled]) / np.mean([features(g)["dur"] for g in labelled]))
        print("  fit on all (asym, audio, part):", np.round(full, 3))


if __name__ == "__main__":
    main()
