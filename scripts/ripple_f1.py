"""Offline: the default runs' F1 per group when the reference's tremble is collapsed more (evaluate.VIBRATION_SWING/MS), and how
many of its turning points have a neighbour within 100 / 150 ms (2026-11-09). usage: ripple_f1.py"""

import numpy as np
from pathlib import Path
from funscript_gen import evaluate as ev
from funscript_gen.export.funscript import Funscript
from funscript_gen.validate import clips, load_manifest

runs = [Path("out/runs/old-base"), Path("out/runs/fresh-base")]
variants = {
    "current (swing 10, 200 ms)": (10.0, 200.0),
    "swing 20, 150 ms": (20.0, 150.0),
    "swing 25, 130 ms": (25.0, 130.0),
}
res = {v: {} for v in variants}
iv = {}
for clip in clips(load_manifest(), "all"):
    outp = next(
        (p for run in runs for p in sorted(run.glob(f"default/{clip.name}.funscript"))),
        None,
    )
    if outp is None:
        continue
    ref, out = Funscript.load(clip.reference), Funscript.load(outp)
    for v, (sw, ms) in variants.items():
        ev.VIBRATION_SWING, ev.VIBRATION_MS = sw, ms
        sc = ev.compare(ref, out)
        res[v].setdefault(clip.group, []).append(sc.f1)
    ev.VIBRATION_SWING, ev.VIBRATION_MS = 10.0, 200.0
    rt, re, rk = ev.simple_extrema(ref)
    d = np.diff(rt)
    iv.setdefault(clip.group, []).append(
        (len(rt), int((d < 100).sum()), int((d < 150).sum()))
    )
for v in variants:
    print(v, {g: round(float(np.mean(x)), 3) for g, x in res[v].items()})
for g, x in iv.items():
    n = sum(a for a, b, c in x)
    b = sum(b for a, b, c in x)
    c = sum(c for a, b, c in x)
    print(
        g,
        "ref points",
        n,
        "with next point < 100 ms:",
        f"{b / n:.1%}",
        "< 150 ms:",
        f"{c / n:.1%}",
    )
