"""Offline: where do the hand-made script's turning points that the output misses lie? Per scene (labels.pkl of ft_motion.py)
the simplified turning points of both scripts inside the scene, matched within 150 ms; the misses (and the output's
unmatched points) split by what kind of scene it is. usage: miss_breakdown.py LABELS.pkl RUN [RUN ...]"""

import pickle
import sys
from pathlib import Path

import numpy as np

from funscript_gen.evaluate import simple_extrema
from funscript_gen.export.funscript import Funscript
from funscript_gen.validate import clips, load_manifest

rows = pickle.loads(Path(sys.argv[1]).read_bytes())
runs = [Path(a) for a in sys.argv[2:]]
by_clip = {}
for r in rows:
    by_clip.setdefault(r["clip"], []).append(r)
tot = {}
under = []
for clip in clips(load_manifest(), "all"):
    if clip.name not in by_clip:
        continue
    outp = next(
        (p for run in runs for p in sorted(run.glob(f"*/{clip.name}.funscript"))), None
    )
    if outp is None:
        continue
    ref, out = Funscript.load(clip.reference), Funscript.load(outp)
    rt, re, rk = simple_extrema(ref)
    pt, pe, pk = simple_extrema(out, ratio=0.0, vibration=False)
    # whole-script matching, then attribute hits to the scene of the reference point
    used = np.zeros(len(pt), bool)
    hit = np.zeros(len(rt), bool)
    for i, (t0, t1, k) in enumerate(zip(rt, re, rk)):
        gap = np.maximum(0.0, np.maximum(t0 - pe, pt - t1))
        cand = np.flatnonzero(~used & (pk == k) & (gap <= 150))
        if len(cand):
            used[cand[np.argmin(gap[cand])]] = True
            hit[i] = True
    for r in by_clip[clip.name]:
        t0, t1 = r["t"][0], r["t"][-1] + 100
        ins = (rt >= t0) & (rt < t1)
        pin = (pt >= t0) & (pt < t1)
        nref, npred = int(ins.sum()), int(pin.sum())
        if nref == 0:
            continue
        miss = int((ins & ~hit).sum())
        ratio = npred / nref
        rr = r["r_out"]
        if rr is not None and rr < -0.3:
            cat = "wrong direction (r < -0.3)"
        elif ratio < 0.5:
            cat = "output < half of the reference's points"
        elif rr is not None and rr >= 0.3:
            cat = "right direction, enough points: timing/shape"
        else:
            cat = "weak correlation (|r| < 0.3), enough points"
        if ratio < 0.5:
            under.append(
                (
                    r["group"],
                    r["clip"],
                    r["index"],
                    nref,
                    npred,
                    ratio,
                    rr,
                    r["sec"],
                    nref / r["sec"],
                    int(((np.diff(rt[ins]) < 150).sum() + 1) if nref > 1 else 0),
                )
            )
        d = tot.setdefault(r["group"], {}).setdefault(cat, [0, 0, 0, 0, 0])
        d[0] += nref
        d[1] += miss
        d[2] += npred
        d[3] += int((pin & ~used_scene).sum()) if False else 0
        d[4] += 1
for g, cats in tot.items():
    nref = sum(v[0] for v in cats.values())
    miss = sum(v[1] for v in cats.values())
    print(f"\n{g}: {nref} reference points, {miss} missed ({miss / nref:.0%})")
    for cat, v in sorted(cats.items(), key=lambda kv: -kv[1][1]):
        print(
            f"  {cat:50} scenes {v[4]:4}  ref {v[0]:6} ({v[0] / nref:4.0%}) missed {v[1]:6} ({v[1] / miss:4.0%} of the misses,"
            f" {v[1] / v[0]:.0%} of its own)"
        )

print("\nscenes with the output under half of the reference's points:")
for grp in ("dev", "test", "dev2", "holdout2"):
    u = [x for x in under if x[0] == grp]
    if not u:
        continue
    ref = sum(x[3] for x in u)
    for name, sel in (
        ("r >= 0.3", lambda x: x[6] is not None and x[6] >= 0.3),
        ("|r| < 0.3", lambda x: x[6] is not None and abs(x[6]) < 0.3),
    ):
        v = [x for x in u if sel(x)]
        if v:
            print(
                f"  {grp:9} {name:10} scenes {len(v):3} ref points {sum(x[3] for x in v):5} ({sum(x[3] for x in v) / ref:4.0%}), "
                f"median ratio {np.median([x[5] for x in v]):.2f} (share of 0.35-0.5: {np.mean([0.35 <= x[5] < 0.5 for x in v]):.0%}, "
                f"< 0.2: {np.mean([x[5] < 0.2 for x in v]):.0%}), median ref points/s {np.median([x[8] for x in v]):.1f}"
            )
    fast = sum(x[9] for x in u)
    print(
        f"  {grp:9} under-half scenes: reference points whose next point is < 150 ms away: {fast} of {ref} ({fast / ref:.0%});"
        f" scenes where that is > 60% of the points: {sum(x[9] > 0.6 * x[3] for x in u)} of {len(u)}"
    )
    top = sorted(u, key=lambda x: -(x[3] - x[4]))[:8]
    print(
        "   biggest:",
        ", ".join(
            f"{x[1]}#{x[2]} {x[3]}->{x[4]} r={x[6] if x[6] is None else round(x[6], 2)}"
            for x in top
        ),
    )
