"""Offline: can the scenes of one video settle each other's stroke sign? Renders the default settings from saved
analyses and compares every pair of flow scenes of a clip (not only the chunks of one shot, which align_chunks
already links) by the cosine of their motion patterns (ScenePlan.sign_pattern, after the direction checks).

Prints how often two scenes with a given similarity have the same sign in the hand-made script (both |r| >= MIN_R),
then a vote: a scene is flipped when the similar scenes (|cosine| >= T) say so by at least V votes, every scene
voting ("all") or only the scenes the part check settled ("anchor", |part_sign| >= part_sign_threshold), with the
scenes fixed and broken per group, and per clip (+ fixed, - broken).

usage: uv run python scripts/experiments/scene_consistency.py RUN [RUN ...]   (runs as for scripts/experiments/stroke_size.py)
"""
import sys
from pathlib import Path

import numpy as np

from stroke_size import find  # (scripts/ is on the path when run as a script; importing it lets Windows-saved analyses load)

from funscript_gen.cli import parse_generate_args
from funscript_gen.export.funscript import Funscript
from funscript_gen.options import build, for_analysis
from funscript_gen.direction import _cosine
from funscript_gen.pipeline import render
from funscript_gen.validate import clips, load_manifest

MIN_R = 0.3
BINS = [(-1, -0.6), (-0.6, -0.4), (-0.4, -0.2), (-0.2, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 1.01)]


def clip_scenes(analysis, clip) -> tuple[list[dict], np.ndarray]:
    given, preset = parse_generate_args([])
    opts = build(for_analysis(analysis.key, given, preset))
    res = render(analysis, opts)
    ref = Funscript.load(clip.reference)
    rt, rp = [a.at for a in ref.actions], [a.pos for a in ref.actions]
    scenes = []
    for plan in res.plans:
        if plan.signal is None or plan.flow_position is None or plan.skip or plan.sign_pattern is None:
            continue
        t, x = plan.flow_position
        ok = np.isfinite(x)
        y = np.interp(t, rt, rp)
        r = float(np.corrcoef(x[ok], y[ok])[0, 1]) if ok.sum() > 10 and x[ok].std() > 0 and y[ok].std() > 0 else 0.0
        scenes.append({"r": r, "dur": (plan.scene.end_ms - plan.scene.start_ms) / 1000, "pattern": plan.sign_pattern,
                       "chunk": plan.scene.continued, "index": plan.scene.index, "parts": plan.parts_found is not None,
                       "anchor": plan.part_sign is not None and abs(plan.part_sign) >= opts.part_sign_threshold})
    sim = np.array([[_cosine(a["pattern"], b["pattern"]) for b in scenes] for a in scenes]).reshape(len(scenes), -1)
    np.fill_diagonal(sim, 0)
    return scenes, sim


def vote(scenes: list[dict], sim: np.ndarray, t: float, v: int, who: str) -> list[bool]:
    flips = []
    for i, s in enumerate(scenes):
        w = np.array([1.0 if who == "all" else float(o["anchor"]) for o in scenes])
        m = (np.abs(sim[i]) >= t) & (w > 0)
        flips.append(not s["anchor"] and (np.sign(sim[i][m]) * w[m]).sum() <= -v)
    return flips


def main(runs: list[Path]) -> None:
    data = []
    for clip in clips(load_manifest(), "dev,test"):
        analysis = find(runs, clip.name)
        if analysis is None:
            print(f"{clip.name}: no analysis of the default settings")
            continue
        data.append((clip, *clip_scenes(analysis, clip)))

    pairs = []  # (cosine, same sign, chunks of one shot)
    for _, scenes, sim in data:
        for a in range(len(scenes)):
            for b in range(a + 1, len(scenes)):
                sa, sb = scenes[a], scenes[b]
                if abs(sa["r"]) >= MIN_R and abs(sb["r"]) >= MIN_R:
                    pairs.append((sim[a, b], np.sign(sa["r"]) == np.sign(sb["r"]), sb["chunk"] and sb["index"] == sa["index"] + 1))
    P = np.array(pairs, float)
    print(f"scene pairs (both |r| >= {MIN_R}): {len(P)}")
    for lo, hi in BINS:
        for chunk in (1, 0):
            m = (P[:, 0] >= lo) & (P[:, 0] < hi) & (P[:, 2] == chunk)
            if m.sum():
                print(f"  cosine [{lo:+.1f}, {hi:+.1f})  {'chunks of a shot' if chunk else 'across cuts     '}"
                      f"  n {int(m.sum()):4d}  same sign {P[m, 1].mean():.2f}")

    print("\nlabelled scenes per clip: wrong sign / all, with part boxes")
    for clip, scenes, _ in data:
        lab = [s for s in scenes if abs(s["r"]) >= MIN_R]
        if lab:
            print(f"  {clip.name:8s} {clip.group:4s} wrong {sum(s['r'] < 0 for s in lab):3d} / {len(lab):3d}"
                  f"  part boxes {sum(s['parts'] for s in lab):3d}  part-settled {sum(s['anchor'] for s in lab):3d}")

    print("\nvote")
    for who in ("all", "anchor"):
        for t in (0.4, 0.5, 0.6, 0.7):
            for v in (1, 2, 3):
                line = []
                for group in ("dev", "test"):
                    fixed = broke = 0
                    per: dict[str, int] = {}
                    for clip, scenes, sim in data:
                        if clip.group != group:
                            continue
                        for s, flip in zip(scenes, vote(scenes, sim, t, v, who)):
                            if flip and abs(s["r"]) >= MIN_R:
                                fixed += s["r"] < 0
                                broke += s["r"] > 0
                                per[clip.name] = per.get(clip.name, 0) + (1 if s["r"] < 0 else -1)
                    line.append(f"{group} fixed {fixed} broke {broke} " + " ".join(f"{k}{n:+d}" for k, n in per.items()))
                print(f"  {who:6s} T {t} V {v}  " + "  |  ".join(line))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main([Path(a) for a in sys.argv[1:]])
