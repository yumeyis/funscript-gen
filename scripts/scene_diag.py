"""Per scene: zero-lag r, turning points per second (manual without wiggles / output), share of manual turning
points with an output one of the same kind within 150 ms / 150-400 ms, and the AI/flow notes.

usage: uv run python scripts/scene_diag.py OUTPUT_DIR CLIP [CLIP...]   (needs OUTPUT_DIR/CLIP.debug.json from --debug)
"""
import glob
import json
import sys

import numpy as np

from funscript_gen.evaluate import _extrema, drop_wiggles
from funscript_gen.export.funscript import Funscript

OUT = sys.argv[1]
for clip in sys.argv[2:]:
    ref = drop_wiggles(Funscript.load(glob.glob(f"valid/{clip}-*.funscript")[0]).normalized())
    pred = Funscript.load(f"{OUT}/{clip}.funscript").normalized()
    rt, rk = _extrema(ref)
    pt, pk = _extrema(pred)
    ra = ([a.at for a in ref.actions], [a.pos for a in ref.actions])
    pa = ([a.at for a in pred.actions], [a.pos for a in pred.actions])
    print(f"== {clip}")
    for k, sc in enumerate(json.load(open(f"{OUT}/{clip}.debug.json"))["scenes"]):
        s, e = sc["start_ms"], sc["end_ms"]
        dur = (e - s) / 1000
        t = np.arange(s, e, 50.0)
        x, y = np.interp(t, *ra), np.interp(t, *pa)
        r = np.corrcoef(x, y)[0, 1] if x.std() > 0 and y.std() > 0 else float("nan")
        lags = []
        for i in np.where((rt >= s) & (rt < e))[0]:
            same = pt[pk == rk[i]]
            if len(same):
                lags.append(np.min(np.abs(same - rt[i])))
        lags = np.array(lags)
        near = (lags <= 150).mean() if len(lags) else float("nan")
        mid = ((lags > 150) & (lags <= 400)).mean() if len(lags) else float("nan")
        nr = ((rt >= s) & (rt < e)).sum() / dur
        npd = ((pt >= s) & (pt < e)).sum() / dur
        tempo = sc.get("tempo_hz")
        note = (sc.get("note") or "")[:90]
        print(f"  #{k:2} {s / 1000:6.1f}s {dur:5.1f}s r={r:+.2f} tp/s ref {nr:4.1f} out {npd:4.1f} "
              f"<=150ms {near:4.0%} 150-400 {mid:4.0%} tempo {tempo or 0:4.2f} {sc['mode'] if not sc['rest'] else 'rest'} {note}")
