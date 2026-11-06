"""Per stroke (consecutive output turning points): does the penis-box change track the manual script's stroke size
better than the output's own stroke size? Within-scene correlations, pooled over scenes.

usage: uv run python scripts/censor_stroke_size.py [OUTPUT_DIR]  (dumps from censor_dump.py in out/anime_det/cen)
"""
import glob, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from censor_position import series, curve, movavg, CLIPS, CEN
from funscript_gen.export.funscript import Funscript
OUT = sys.argv[1] if len(sys.argv) > 1 else "out/v14_def_asym_part"
for feat in ("dist", "area", "len"):
    r_out, r_feat, r_feat_abs, n_sc = [], [], [], 0
    for clip in CLIPS:
        path = f"{CEN}/{clip}.json"
        if not os.path.exists(path):
            continue
        data = json.load(open(path)); w, h, fps = data["w"], data["h"], data["fps"]
        ref = Funscript.load(glob.glob(f"valid/{clip}*.funscript")[0]).normalized()
        pred = Funscript.load(f"{OUT}/{clip}.funscript").normalized()
        for sc in json.load(open(f"{OUT}/{clip}.debug.json"))["scenes"]:
            s, e = sc["start_ms"], sc["end_ms"]
            acts = [a for a in pred.actions if s <= a.at < e]
            rows = [r for r in data["frames"] if s <= r["t"] < e]
            if len(acts) < 8 or len(rows) < 20:
                continue
            t, x, edge = series(rows, w, h, feat)
            ok = ~np.isnan(x)
            if ok.mean() < 0.6 or edge >= 0.8:
                continue
            x = np.interp(t, t[ok], x[ok])
            at = np.array([a.at for a in acts]); pos = np.array([a.pos for a in acts], float)
            fx = np.interp(at, t, x)
            rv = curve(ref.actions, at)
            d_out, d_ref, d_feat = np.abs(np.diff(pos)), np.abs(np.diff(rv)), np.abs(np.diff(fx))
            if d_ref.std() < 1e-6 or d_out.std() < 1e-6 or d_feat.std() < 1e-9:
                continue
            n_sc += 1
            r_out.append(np.corrcoef(d_out, d_ref)[0, 1]); r_feat.append(np.corrcoef(d_feat, d_ref)[0, 1])
            # absolute level at the turning points (peaks' height), sign from the output
            yd = curve(pred.actions, t); s_ = np.sign(np.corrcoef(x - movavg(x, 20), yd - movavg(yd, 20))[0, 1])
            r_feat_abs.append(np.corrcoef(s_ * fx, rv)[0, 1])
    print(f"{feat}: {n_sc} scenes | stroke size vs manual: output {np.nanmedian(r_out):+.2f}, box change {np.nanmedian(r_feat):+.2f} "
          f"| position at turning points: box {np.nanmedian(r_feat_abs):+.2f} (medians over scenes)")
