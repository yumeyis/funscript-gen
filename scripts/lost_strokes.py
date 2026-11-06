"""Offline: where the strokes the output misses are lost. Takes the hand-made turning points that
scripts/missed_points.py classes "slower" (missed, and the output has fewer turning points nearby) and looks for a
same-kind extremum within TOL ms in each step of the scene's signal:
  pruned after find_strokes   find_strokes kept it; to_actions dropped it (min_stroke_pos, frequency, speed)
  dropped: ...                a local extremum of the smoothed signal that find_strokes dropped, by the reason that
                              applies (its nearest opposite extremum closer than min_interval_ms: usually a ripple
                              beside a stroke the signal does not have; under MIN_AMPLITUDE_PX; under min_prominence
                              of the local range)
  only in unfiltered signal   not in the band-passed signal, but in the same signal without the rhythm filter
  not in signal               nowhere in the signal

usage: uv run python scripts/lost_strokes.py RUN [RUN ...]   (runs as for scripts/stroke_size.py)
"""
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
import numpy as np
from scipy.signal import argrelextrema
import missed_points as M
from stroke_size import find
from funscript_gen.cli import parse_generate_args
from funscript_gen.evaluate import _extrema, drop_wiggles
from funscript_gen.export.funscript import Funscript
from funscript_gen.options import build, for_analysis
from funscript_gen.pipeline import MIN_AMPLITUDE_PX, render
from funscript_gen.signal.process import analyze
from funscript_gen.validate import clips, load_manifest
TOL = 150

def local_ext(t, y, kind):
    ok = np.isfinite(y)
    yy = np.where(ok, y, -np.inf if kind > 0 else np.inf)
    idx = argrelextrema(yy, np.greater_equal if kind > 0 else np.less_equal, order=1)[0]
    return t[idx]

if len(sys.argv) < 2:
    sys.exit(__doc__)
RUNS = [Path(a) for a in sys.argv[1:]]
tal = {g: Counter() for g in ("dev", "test")}
per = Counter()
for clip in clips(load_manifest(), "dev,test"):
    an = find(RUNS, clip.name)
    given, preset = parse_generate_args([])
    opts = build(for_analysis(an.key, given, preset))
    res = render(an, opts)
    ref = Funscript.load(clip.reference)
    rt, rk = _extrema(ref); pt, pk = _extrema(res.funscript)
    kept = set(_extrema(drop_wiggles(ref))[0].tolist())
    hit, _ = M.match(rt, rk, pt, pk)
    off = [(p.scene.start_ms, p.scene.end_ms) for p in res.plans if p.skip or p.rest or p.signal is None]
    for t, k, h in zip(rt, rk, hit):
        if h or t not in kept or any(s <= t < e for s, e in off) or not np.any(np.abs(pt - t) <= M.GAP_MS):
            continue
        if M.near(pt, pk, t, -k, M.TOL_MS) or M.near(pt, pk, t, k, M.LATE_MS) or not (M.count(pt, t) < M.count(rt, t)):
            continue
        plan = next((p for p in res.plans if p.scene.start_ms <= t < p.scene.end_ms), None)
        sig = plan.signal if plan is not None else None
        if sig is None or plan.mode != "flow":
            why = "no flow signal"
        else:
            st = sig.t_ms
            near = lambda times: bool(np.any(np.abs(np.asarray(times) - t) <= TOL))
            sidx = np.array(sig.strokes)
            skind = np.zeros(len(sidx))
            if len(sidx) >= 2:
                v = sig.smooth[sidx]
                skind = np.where(v > np.r_[v[1], v[:-1]], 1, -1)
            if near(st[sidx[skind == k]] if len(sidx) else []):
                why = "pruned after find_strokes (min_stroke_pos / freq / speed)"
            elif near(local_ext(st, sig.smooth, k)):
                x = sig.smooth
                cand = [j for j in np.searchsorted(st, local_ext(st, x, k)) if abs(st[j] - t) <= TOL]
                i = cand[np.argmin([abs(st[j] - t) for j in cand])]
                opp = np.searchsorted(st, local_ext(st, x, -k))
                before, after = opp[opp < i], opp[opp > i]
                if not len(before) or not len(after):
                    why = "dropped: segment edge"
                else:
                    a = min(abs(x[i] - x[before[-1]]), abs(x[i] - x[after[0]]))
                    span = max(sig.hi[i] - sig.lo[i], MIN_AMPLITUDE_PX)
                    dt = min(st[i] - st[before[-1]], st[after[0]] - st[i])
                    if dt < opts.signal.min_interval_ms:
                        why = "dropped: interval < min_interval_ms"
                    elif a < MIN_AMPLITUDE_PX:
                        why = "dropped: amplitude < MIN_AMPLITUDE_PX"
                    elif a < opts.signal.min_prominence * span:
                        why = "dropped: prominence %s" % ("<0.05" if a < 0.05 * span else "0.05-0.10" if a < 0.10 * span else "0.10-0.15")
                    else:
                        why = "dropped: other (pair removal)"
            elif sig.tempo_hz is not None:
                t2, x2 = plan.flow_position
                nf = analyze(t2, x2, replace(opts.signal, rhythm_filter=False, min_amplitude=MIN_AMPLITUDE_PX))
                why = "only in unfiltered signal" if near(local_ext(nf.t_ms, nf.smooth, k)) else "not in signal (filtered scene)"
            else:
                why = "not in signal"
        tal[clip.group][why] += 1
        per[(clip.group, clip.name, why)] += 1
for g, c in tal.items():
    n = sum(c.values())
    print(g, "slower points", n)
    for k, v in c.most_common():
        print(f"   {v:4d} {v/n:.2f} {k}")
for (g, name, why), v in sorted(per.items(), key=lambda kv: -kv[1])[:20]:
    print(g, name, v, why)
