"""Simulate: flip a scene when corr(penis-box feature, output) <= -TH. Count fixed / broken scenes.

usage: uv run python scripts/censor_flip.py [area|len|dist] [OUTPUT_DIR]  (dumps from censor_dump.py in out/anime_det/cen)
"""
import glob, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from censor_sign import curve, detrend, best_corr, features, edge_share, Funscript, MIN_COVER
S = "out/anime_det"  # det/ (1 fps, all detectors) and cen/ (10 fps censors) dumps
feat = sys.argv[1] if len(sys.argv) > 1 else "area"
OUT = sys.argv[2] if len(sys.argv) > 2 else "out/v13_def"
for TH in (0.2, 0.4):
    fixed, broken, n, flips = [], [], 0, 0
    for path in sorted(glob.glob(f"{S}/cen/*.json")):
        clip = os.path.basename(path)[:-5]
        data = json.load(open(path)); fps = data["fps"]
        ref = Funscript.load(glob.glob(f"valid/{clip}*.funscript")[0]); pred = Funscript.load(f"{OUT}/{clip}.funscript")
        for sc in json.load(open(f"{OUT}/{clip}.debug.json"))["scenes"]:
            rows = [r for r in data["frames"] if sc["start_ms"] <= r["t"] < sc["end_ms"]]
            if len(rows) < 20 or edge_share(rows, data["w"], data["h"]) >= 0.8: continue
            t, f = features(rows, data["w"], data["h"]); x = f[feat]; ok = ~np.isnan(x)
            if ok.mean() < MIN_COVER: continue
            y_ref, y_out = detrend(curve(ref, t), fps), detrend(curve(pred, t), fps)
            if y_ref.std() < 1: continue
            r_out = best_corr(y_out, y_ref, 0); n += 1
            r_fo = best_corr(detrend(np.interp(t, t[ok], x[ok]), fps), y_out, 1)
            if r_fo <= -TH:
                flips += 1
                tag = f"{clip}@{sc['start_ms']/1000:.0f}s r_out {r_out:+.2f}"
                (fixed if r_out < -0.2 else broken if r_out > 0.2 else []).append(tag)
    print(f"{feat} TH={TH}: {n} scenes, {flips} flipped, fixed {len(fixed)}, broken {len(broken)}")
    print("  broken:", broken)
