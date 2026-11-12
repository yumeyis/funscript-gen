"""Offline: how much each stroke's size costs, and whether anything predicts the hand-made script's size.

Renders the default settings from saved analyses and keeps the output's turning points (times and peak / trough),
replacing only their positions:
  base      the output as is
  binary    every peak at 100, every trough at 0
  half      every turning point halfway to that end
  dir       each scene mirrored when it correlates negatively with the hand-made script (direction fixed, sizes kept)
  size      the hand-made position, mirrored where the output's scene is upside down (sizes fixed, directions kept)
  oracle    the hand-made position (both fixed)
Then the per-turning-point features (output sizes and timing, scene statistics) against the hand-made depth, ridge
models over them (leave-one-clip-out on dev, fit on dev and scored on test), and the sound onset strength near each
turning point (within-scene correlations, scenes whose output correlates >= MIN_R with the hand-made script).

usage: uv run python scripts/experiments/stroke_size.py RUN [RUN ...]
       RUN: `validate` runs with saved analyses of the default settings (the first that has a clip is used;
            analyses saved on the Windows host load too)
"""
import pathlib
import sys
from pathlib import Path

import numpy as np

pathlib.WindowsPath = pathlib.PureWindowsPath  # analyses saved on the second test host keep their Windows paths

from funscript_gen.cli import parse_generate_args  # noqa: E402
from funscript_gen.evaluate import compare  # noqa: E402
from funscript_gen.export.funscript import Action, Funscript  # noqa: E402
from funscript_gen.options import BY_NAME, analysis_key, build, for_analysis, resolve  # noqa: E402
from funscript_gen.pipeline import load_analysis, render  # noqa: E402
from funscript_gen.validate import clips, load_manifest  # noqa: E402

MIN_R = 0.3
NAMES = ["bias", "peak", "ext", "ext*peak", "size_prev", "size_next", "rel_prev", "rel_next", "dt_prev", "dt_next",
         "rel_dt", "tempo", "scene_size", "scene_ext", "scene_peak_ext"]
SETS = {"const": [0, 1], "ext": [0, 1, 2, 3], "sizes": list(range(8)), "all": list(range(len(NAMES)))}


def find(runs: list[Path], name: str):
    given, preset = parse_generate_args([])
    want = analysis_key(resolve(given, preset))
    for run in runs:
        for path in sorted(run.glob(f"*/{name}.analysis.pkl")):
            analysis = load_analysis(path)
            # a setting the analysis does not list (it is older than the setting) was at its default
            if all(analysis.key.get(k, BY_NAME[k].default) == v for k, v in want.items()):
                return analysis
    return None


def clip_data(analysis, clip) -> dict:
    given, preset = parse_generate_args([])
    res = render(analysis, build(for_analysis(analysis.key, given, preset)))
    ref = Funscript.load(clip.reference)
    at = np.array([a.at for a in res.funscript.actions], float)
    pos = np.array([a.pos for a in res.funscript.actions], float)
    truth = np.interp(at, [a.at for a in ref.actions], [a.pos for a in ref.actions])
    prev, nxt = np.r_[pos[1:2], pos[:-1]], np.r_[pos[1:], pos[-2:-1]]
    kind = np.where(pos >= np.maximum(prev, nxt), 1.0, np.where(pos <= np.minimum(prev, nxt), -1.0, 0.0))
    n = len(pos)
    scene, scene_r = np.full(n, -1), np.zeros(n)
    for plan in res.plans:
        m = (at >= plan.scene.start_ms) & (at < plan.scene.end_ms)
        scene[m] = plan.scene.index
        if m.sum() > 3 and pos[m].std() > 0 and truth[m].std() > 0:
            scene_r[m] = np.corrcoef(pos[m], truth[m])[0, 1]
    upright = np.where(scene_r < 0, 100 - truth, truth)  # hand-made, oriented like the output

    size_prev, size_next = np.abs(pos - prev) / 100, np.abs(nxt - pos) / 100
    dt_prev, dt_next = np.diff(np.r_[at[0], at]) / 1000, np.diff(np.r_[at, at[-1]]) / 1000
    ext = kind * (pos - 50) / 50
    X = np.zeros((n, len(NAMES)))
    X[:, 0], X[:, 1], X[:, 2], X[:, 3] = 1, kind > 0, ext, ext * (kind > 0)
    X[:, 4], X[:, 5], X[:, 8], X[:, 9] = size_prev, size_next, np.minimum(dt_prev, 3), np.minimum(dt_next, 3)
    for s in np.unique(scene):
        m = scene == s
        size = np.median(np.r_[size_prev[m], size_next[m]]) + 1e-3
        dt = np.median(np.r_[dt_prev[m], dt_next[m]]) + 1e-3
        pk = m & (kind > 0)
        X[m, 6], X[m, 7] = size_prev[m] / size, size_next[m] / size
        X[m, 10], X[m, 11], X[m, 12] = (dt_prev[m] + dt_next[m]) / 2 / dt, 1 / (2 * dt), size
        X[m, 13], X[m, 14] = np.median(ext[m]), np.median(ext[pk]) if pk.any() else 0
    sound = np.full(n, np.nan)
    if analysis.envelope is not None:
        et, ev = analysis.envelope
        for i, a in enumerate(at):
            w = ev[(et >= a - 200) & (et <= a + 200)]
            sound[i] = w.max() if len(w) else np.nan
    return dict(name=clip.name, group=clip.group, ref=ref, at=at, pos=pos, kind=kind, truth=truth, upright=upright,
                scene=scene, scene_r=scene_r, X=X, y=kind * (upright - 50) / 50, ok=kind != 0, sound=sound)


def r_of(d: dict, pos: np.ndarray) -> float:
    fs = Funscript([Action(int(a), int(round(p))) for a, p in zip(d["at"], pos)]).normalized()
    return compare(d["ref"], fs).correlation


def variants(d: dict) -> dict:
    pos, kind = d["pos"], d["kind"]
    end = np.where(kind > 0, 100, np.where(kind < 0, 0, pos))
    return {"base": pos, "binary": end, "half": (pos + end) / 2,
            "dir": np.where(d["scene_r"] < 0, 100 - pos, pos), "size": d["upright"], "oracle": d["truth"]}


def fit(ds: list[dict], cols: list[int], lam: float) -> np.ndarray:
    X = np.concatenate([d["X"][d["ok"]][:, cols] for d in ds])
    y = np.concatenate([d["y"][d["ok"]] for d in ds])
    w = np.sqrt(np.concatenate([np.full(d["ok"].sum(), 1 / d["ok"].sum()) for d in ds]))[:, None]  # clips equal
    A = (X * w).T @ (X * w) + lam * 1e-2 * len(ds) * np.eye(len(cols))
    return np.linalg.solve(A, (X * w).T @ (y * w[:, 0]))


def predicted(d: dict, cols: list[int], beta: np.ndarray) -> np.ndarray:
    return np.where(d["ok"], 50 + d["kind"] * 50 * np.clip(d["X"][:, cols] @ beta, 0, 1), d["pos"])


def main(runs: list[Path]) -> None:
    data = []
    for clip in clips(load_manifest(), "dev,test"):
        analysis = find(runs, clip.name)
        if analysis is None:
            print(f"{clip.name}: no analysis of the default settings")
            continue
        data.append(clip_data(analysis, clip))
    groups = {g: [d for d in data if d["group"] == g] for g in ("dev", "test")}

    print("r with the turning points' positions replaced (mean over clips)")
    scores = {d["name"]: {k: r_of(d, v) for k, v in variants(d).items()} for d in data}
    for k in scores[data[0]["name"]]:
        print(f"  {k:7s}" + "".join(f"  {g} {np.mean([scores[d['name']][k] for d in ds]):.3f}" for g, ds in groups.items()))

    dev = groups["dev"]
    print("\nfeature vs hand-made depth (dev, all turning points)")
    for k, lab in ((1, "peaks"), (-1, "troughs")):
        X = np.concatenate([d["X"][d["kind"] == k] for d in dev])
        y = np.concatenate([d["y"][d["kind"] == k] for d in dev])
        print(f"  {lab:7s} n {len(y)}  " + " ".join(f"{n} {np.corrcoef(X[:, i], y)[0, 1]:+.2f}"
                                                   for i, n in enumerate(NAMES) if X[:, i].std() > 0))
    print("\nridge models: r of the output with the predicted positions")
    for lab, cols in SETS.items():
        for lam in (0.1, 1.0, 10.0):
            loo = np.mean([r_of(d, predicted(d, cols, fit([e for e in dev if e is not d], cols, lam))) for d in dev])
            beta = fit(dev, cols, lam)
            test = np.mean([r_of(d, predicted(d, cols, beta)) for d in groups["test"]])
            print(f"  {lab:6s} lambda {lam:<4}  dev (leave one clip out) {loo:.3f}  test {test:.3f}")

    print(f"\nwithin-scene correlation with the hand-made depth (scenes with r >= {MIN_R})")
    for k, lab in ((1, "peaks"), (-1, "troughs")):
        parts = []
        for d in data:
            for s in np.unique(d["scene"]):
                m = (d["scene"] == s) & (d["kind"] == k) & np.isfinite(d["sound"]) & (d["scene_r"] >= MIN_R)
                if m.sum() >= 4:
                    cols = np.c_[d["y"][m], d["sound"][m], d["X"][m, 2], d["X"][m, 4] + d["X"][m, 5]]
                    parts.append(cols - cols.mean(0))
        a = np.concatenate(parts)
        print(f"  {lab:7s} n {len(a)}  sound {np.corrcoef(a[:, 0], a[:, 1])[0, 1]:+.3f}  "
              f"output ext {np.corrcoef(a[:, 0], a[:, 2])[0, 1]:+.3f}  output size {np.corrcoef(a[:, 0], a[:, 3])[0, 1]:+.3f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main([Path(a) for a in sys.argv[1:]])
