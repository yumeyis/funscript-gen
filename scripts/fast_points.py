"""Offline: recall over the hand-made script's turning points that have a neighbour within 150 ms (tremble, ripples) and over the
others (the strokes), per group, for the default runs out/runs/old-base and fresh-base (2026-11-09). usage: fast_points.py"""

import numpy as np
from pathlib import Path
from funscript_gen import evaluate as ev
from funscript_gen.export.funscript import Funscript
from funscript_gen.validate import clips, load_manifest

runs = [Path("out/runs/old-base"), Path("out/runs/fresh-base")]
tot = {}
for clip in clips(load_manifest(), "all"):
    outp = next(
        (p for run in runs for p in sorted(run.glob(f"default/{clip.name}.funscript"))),
        None,
    )
    if outp is None:
        continue
    ref, out = Funscript.load(clip.reference), Funscript.load(outp)
    rt, re, rk = ev.simple_extrema(ref)
    pt, pe, pk = ev.simple_extrema(out, ratio=0.0, vibration=False)
    used = np.zeros(len(pt), bool)
    hit = np.zeros(len(rt), bool)
    for i, (t0, t1, k) in enumerate(zip(rt, re, rk)):
        gap = np.maximum(0.0, np.maximum(t0 - pe, pt - t1))
        cand = np.flatnonzero(~used & (pk == k) & (gap <= 150))
        if len(cand):
            used[cand[np.argmin(gap[cand])]] = True
            hit[i] = True
    d = np.diff(rt)
    near = np.zeros(len(rt), bool)
    near[:-1] |= d < 150
    near[1:] |= d < 150
    a = tot.setdefault(clip.group, np.zeros(5))
    a += [near.sum(), (near & hit).sum(), (~near).sum(), (~near & hit).sum(), len(pt)]
for g, a in tot.items():
    print(
        f"{g:9} fast-neighbour ref points {int(a[0]):6} ({a[0] / (a[0] + a[2]):.0%}) recall {a[1] / a[0]:.0%}; "
        f"stroke points {int(a[2]):6} recall {a[3] / a[2]:.0%}; output points {int(a[4])}; "
        f"precision of all {(a[1] + a[3]) / a[4]:.0%}"
    )
