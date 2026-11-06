"""Offline: does the penis box size (and size ratios) follow the manual script with a stable sign? (dev+test only)

Also simulates flipping scenes by size, and compares distance with size by how much both boxes move.
usage: uv run python scripts/box_size.py [RUN_DIR]  (a run dir with NAME.analysis.pkl and NAME.funscript)
"""
import sys
from pathlib import Path
import numpy as np
from funscript_gen import validate
from funscript_gen.pipeline import load_analysis
from funscript_gen.export.funscript import Funscript
from funscript_gen.tracking.parts import _detrend, penis_vulva_distance

RUN = Path(sys.argv[1] if len(sys.argv) > 1 else "out/runs/pscan-new/user")
man = validate.load_manifest()
rows = []
for c in validate.clips(man, "dev,test"):
    pkl = RUN / f"{c.name}.analysis.pkl"
    if not pkl.exists():
        continue
    an = load_analysis(pkl)
    fs = Funscript.load(c.reference) if hasattr(Funscript, "load") else None
    a = fs.normalized().actions
    mt, mp = np.array([x.at for x in a]), np.array([x.pos for x in a])
    of = Funscript.load(RUN / f"{c.name}.funscript").normalized().actions
    ot, op = np.array([x.at for x in of]), np.array([x.pos for x in of])
    for p in an.plans:
        got = p.parts_found
        if got is None:
            continue
        times, boxes, size = got
        times = np.asarray(times, float)
        w, h = size
        n = len(boxes)
        feats = {k: np.full(n, np.nan) for k in ("area", "height", "width", "ratio", "dist")}
        edge = []
        for i, bs in enumerate(boxes):
            pen = [b for b in bs if b[1] == "penis"]
            if not pen:
                continue
            (x1, y1, x2, y2), _, _ = max(pen, key=lambda b: b[2])
            edge.append(x1 <= 2 or y1 <= 2 or x2 >= w - 2 or y2 >= h - 2)
            ar = (x2 - x1) * (y2 - y1)
            feats["area"][i] = np.log(ar + 1)
            feats["height"][i] = np.log(y2 - y1 + 1)
            feats["width"][i] = np.log(x2 - x1 + 1)
            pus = [b for b, lab, _ in bs if lab == "pussy"]
            if pus:
                pa = max((b[2] - b[0]) * (b[3] - b[1]) for b in pus)
                feats["ratio"][i] = np.log(ar + 1) - np.log(pa + 1)
        pc = np.full((n, 2), np.nan); vc = np.full((n, 2), np.nan)
        for i, bs in enumerate(boxes):
            pen = [b for b in bs if b[1] == "penis"]
            pus = [b for b, lab, _ in bs if lab == "pussy"]
            if pen:
                (x1, y1, x2, y2), _, _ = max(pen, key=lambda b: b[2]); pc[i] = ((x1+x2)/2, (y1+y2)/2)
                if pus:
                    q = min(pus, key=lambda b: np.hypot((b[0]+b[2])/2-pc[i][0], (b[1]+b[3])/2-pc[i][1]))
                    vc[i] = ((q[0]+q[2])/2, (q[1]+q[3])/2)
        diag = float(np.hypot(w, h))
        def mv(c):
            ok = ~np.isnan(c[:, 0])
            if ok.sum() < 10: return None
            return float(np.mean([np.std(np.interp(times, times[ok], c[ok, j])) for j in (0, 1)]) / diag)
        mp_, mv_ = mv(pc), mv(vc)
        feats["dist"], _ = penis_vulva_distance(boxes, size)
        fps = 1000 / np.median(np.diff(times)) if n > 2 else 10
        ref = _detrend(np.interp(times, mt, mp), fps)
        out = _detrend(np.interp(times, ot, op), fps)
        rec = dict(mpen=mp_, mpus=mv_, r_out=float(np.corrcoef(out, ref)[0, 1]) if out.std() > 1e-9 and ref.std() > 1e-9 else None,
                   flip_note=p.part_flipped, clip=c.name, scene=p.scene.index, dur=(p.scene.end_ms - p.scene.start_ms) / 1000,
                   edge=float(np.mean(edge)) if edge else 1.0)
        for k, f in feats.items():
            ok = ~np.isnan(f)
            if ok.mean() < 0.6 or n < 20:
                rec[k] = None
                continue
            x = _detrend(np.interp(times, times[ok], f[ok]), fps)
            rec[k] = float(np.corrcoef(x, ref)[0, 1]) if x.std() > 1e-9 and ref.std() > 1e-9 else None
            rec[k + "_out"] = float(np.corrcoef(x, out)[0, 1]) if x.std() > 1e-9 and out.std() > 1e-9 else None
        rows.append(rec)
print(f"scenes with part boxes: {len(rows)}; edge<0.5: {sum(r['edge']<0.5 for r in rows)}")
for edge_only in (False, True):
    sel = [r for r in rows if (r["edge"] < 0.5 or not edge_only)]
    print(f"\n-- {'edge<0.5 only' if edge_only else 'all'} ({len(sel)} scenes)")
    for k in ("area", "height", "width", "ratio", "dist"):
        v = [(r[k], r["dur"], r["clip"]) for r in sel if r[k] is not None]
        strong = [x for x in v if abs(x[0]) >= 0.3]
        pos = [x for x in strong if x[0] > 0]
        dpos = sum(x[1] for x in pos) / max(1e-9, sum(x[1] for x in strong))
        print(f"{k:7s} n={len(v):3d} |r|>=.3: {len(strong):3d}  r>0 (bigger=up): {len(pos):3d} ({len(pos)/max(1,len(strong)):.0%}, by duration {dpos:.0%})  median r {np.median([x[0] for x in v]) if v else float('nan'):+.2f}")
print("\nper-clip area r (edge<0.5):")
from collections import defaultdict
d = defaultdict(list)
for r in rows:
    if r["edge"] < 0.5 and r["area"] is not None:
        d[r["clip"]].append(f"{r['area']:+.2f}")
for k, v in d.items():
    print(k, " ".join(v))

print("\n== simulate: flip scene when r(feature, output) <= -T, edge<0.5; truth = sign of r(output, manual) (|r_out|>=.3)")
for k in ("area", "height", "dist"):
  for T in (0.2, 0.4):
    fixed = broke = already = 0
    for r in rows:
        if r["edge"] >= 0.5 or r.get(k + "_out") is None or r["r_out"] is None or abs(r["r_out"]) < 0.3:
            continue
        if r.get(k + "_out") <= -T:
            if r["r_out"] < 0: fixed += 1
            else: broke += 1
    print(k, T, "fixed", fixed, "broke", broke)
wrong = [r for r in rows if r["r_out"] is not None and r["r_out"] <= -0.3]
print("scenes with boxes where the current output is wrong:", len(wrong), "of", sum(1 for r in rows if r["r_out"] is not None and abs(r["r_out"])>=.3))
for r in wrong:
    print(" ", r["clip"], r["scene"], f"dur {r['dur']:.0f}s edge {r['edge']:.2f} r_out {r['r_out']:+.2f} area_out {r.get('area_out')} dist_out {r.get('dist_out')}")

print("\n== distance vs area by how much BOTH boxes move (std of centre over scene / diagonal)")
cand = [r for r in rows if r["edge"] < 0.5 and r.get("dist") is not None and r.get("area") is not None and r["mpen"] and r["mpus"]]
cand.sort(key=lambda r: min(r["mpen"], r["mpus"]))
for r in cand:
    print(f"{r['clip']:4s} s{r['scene']:<3d} dur {r['dur']:4.0f}s  move pen {r['mpen']:.3f} pus {r['mpus']:.3f}  r(dist,man) {r['dist']:+.2f}  r(area,man) {r['area']:+.2f}")
