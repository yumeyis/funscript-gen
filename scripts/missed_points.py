"""Offline: why the hand-made script's turning points are missed (recall) and what the extra output points are
(precision). Renders the default settings from saved analyses and matches the turning points as `compare` does
(same kind within TOL_MS). Every unmatched hand-made turning point gets the first reason that applies:
  wiggle     dropped by drop_wiggles (a stroke under WIGGLE units in the hand-made script)
  no output  in a skipped / resting scene, or no output turning point within GAP_MS
  opposite   an output turning point of the other kind within TOL_MS (direction or half-stroke phase wrong)
  late       one of the same kind within LATE_MS (the timing is off, not the stroke)
  slower     the output has fewer turning points than the hand-made script within +-WINDOW_MS (strokes missing)
  other
Unmatched output turning points: opposite / late as above, "faster" (more output points than hand-made ones in the
window), "still" (the hand-made script moves less than WIGGLE within the window) or other.

usage: uv run python scripts/missed_points.py RUN [RUN ...]   (runs as for scripts/stroke_size.py)
"""
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from stroke_size import find  # (scripts/ is on the path when run as a script; importing it lets Windows-saved analyses load)

from funscript_gen.cli import parse_generate_args
from funscript_gen.evaluate import WIGGLE, _extrema, drop_wiggles
from funscript_gen.export.funscript import Funscript
from funscript_gen.options import build, for_analysis
from funscript_gen.pipeline import render
from funscript_gen.validate import clips, load_manifest

TOL_MS = 150.0
LATE_MS = 400.0
GAP_MS = 1000.0
WINDOW_MS = 1000.0
MISSED = ["wiggle", "no output", "opposite", "late", "slower", "other"]
EXTRA = ["opposite", "late", "faster", "still", "other"]


def match(rt, rk, pt, pk) -> tuple[np.ndarray, np.ndarray]:
    """compare's greedy matching: which reference and which output turning points were matched."""
    used = np.zeros(len(pt), bool)
    hit = np.zeros(len(rt), bool)
    for i, (t, k) in enumerate(zip(rt, rk)):
        cand = np.flatnonzero(~used & (pk == k) & (np.abs(pt - t) <= TOL_MS))
        if len(cand):
            used[cand[np.argmin(np.abs(pt[cand] - t))]] = True
            hit[i] = True
    return hit, used


def near(times, kinds, t, k, within) -> bool:
    return bool(np.any((kinds == k) & (np.abs(times - t) <= within)))


def count(times, t) -> int:
    return int(np.sum(np.abs(times - t) <= WINDOW_MS))


def classify(clip, analysis) -> tuple[Counter, Counter, int, int]:
    given, preset = parse_generate_args([])
    res = render(analysis, build(for_analysis(analysis.key, given, preset)))
    ref = Funscript.load(clip.reference)
    rt, rk = _extrema(ref)
    pt, pk = _extrema(res.funscript)
    kept = set(_extrema(drop_wiggles(ref))[0].tolist())
    off = [(p.scene.start_ms, p.scene.end_ms) for p in res.plans if p.skip or p.rest or p.signal is None]
    hit, used = match(rt, rk, pt, pk)
    ra = np.array([a.at for a in ref.actions], float)
    rp = np.array([a.pos for a in ref.actions], float)

    missed = Counter()
    for t, k in zip(rt[~hit], rk[~hit]):
        if t not in kept:
            why = "wiggle"
        elif any(s <= t < e for s, e in off) or not np.any(np.abs(pt - t) <= GAP_MS):
            why = "no output"
        elif near(pt, pk, t, -k, TOL_MS):
            why = "opposite"
        elif near(pt, pk, t, k, LATE_MS):
            why = "late"
        elif count(pt, t) < count(rt, t):
            why = "slower"
        else:
            why = "other"
        missed[why] += 1

    extra = Counter()
    for t, k in zip(pt[~used], pk[~used]):
        w = (ra >= t - WINDOW_MS) & (ra <= t + WINDOW_MS)
        span = np.ptp(np.r_[rp[w], np.interp([t - WINDOW_MS, t + WINDOW_MS], ra, rp)])
        if near(rt, rk, t, -k, TOL_MS):
            why = "opposite"
        elif near(rt, rk, t, k, LATE_MS):
            why = "late"
        elif span < WIGGLE:
            why = "still"
        elif count(pt, t) > count(rt, t):
            why = "faster"
        else:
            why = "other"
        extra[why] += 1
    return missed, extra, len(rt), len(pt)


def main(runs: list[Path]) -> None:
    rows = []
    for clip in clips(load_manifest(), "dev,test"):
        analysis = find(runs, clip.name)
        if analysis is None:
            print(f"{clip.name}: no analysis of the default settings")
            continue
        rows.append((clip, *classify(clip, analysis)))

    def line(label, missed, extra, n_ref, n_out):
        m = sum(missed.values())
        x = sum(extra.values())
        return (f"{label:10s} recall {1 - m / max(n_ref, 1):.2f} missed {m:5d}/{n_ref:5d}: "
                + " ".join(f"{k} {missed[k] / max(n_ref, 1):.2f}" for k in MISSED)
                + f"  | precision {1 - x / max(n_out, 1):.2f} extra {x:5d}/{n_out:5d}: "
                + " ".join(f"{k} {extra[k] / max(n_out, 1):.2f}" for k in EXTRA))

    print("shares of all hand-made (missed) / all output (extra) turning points")
    for group in ("dev", "test"):
        sel = [r for r in rows if r[0].group == group]
        print(line(f"[{group}]", sum((r[1] for r in sel), Counter()), sum((r[2] for r in sel), Counter()),
                   sum(r[3] for r in sel), sum(r[4] for r in sel)))
        for clip, missed, extra, n_ref, n_out in sorted(sel, key=lambda r: -sum(r[1].values()) / max(r[3], 1)):
            print(line(clip.name, missed, extra, n_ref, n_out))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main([Path(a) for a in sys.argv[1:]])
