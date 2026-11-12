"""Offline: does the frame's global motion (the 'camera' the pipeline removes) follow the hand-made script in scenes where
the output does not? usage: global_motion.py LABELS.pkl FLOW_DIR   (ft_motion.py labels, ft_flow.py dump)"""

import pickle
import sys
from pathlib import Path

import numpy as np

rows = pickle.loads(Path(sys.argv[1]).read_bytes())
flow_dir = Path(sys.argv[2])


def corr(a, b):
    return float(np.corrcoef(a, b)[0, 1]) if a.std() > 1e-9 and b.std() > 1e-9 else 0.0


res, cache_clip, cache = [], None, None
for r in rows:
    if not r["ref_ok"] or len(r["t"]) < 20:
        continue
    if r["clip"] != cache_clip:
        cache, cache_clip = np.load(flow_dir / f"{r['clip']}.npz"), r["clip"]
    k = r["index"]
    if f"f{k}" not in cache.files:
        continue
    f, tf = cache[f"f{k}"].astype(np.float32), cache[f"t{k}"]
    n, h, w, _ = f.shape
    yy, xx = np.mgrid[0:h, 0:w]
    rx, ry = (xx - (w - 1) / 2), (yy - (h - 1) / 2)
    rr = np.maximum(np.hypot(rx, ry), 1)
    sig = {
        "vx": np.median(f[..., 0].reshape(n, -1), axis=1),
        "vy": np.median(f[..., 1].reshape(n, -1), axis=1),
        "zoom": ((f[..., 0] * rx + f[..., 1] * ry) / rr).mean(axis=(1, 2)),
        "mvx": f[..., 0].mean(axis=(1, 2)),
        "mvy": f[..., 1].mean(axis=(1, 2)),
    }
    cs = np.concatenate([np.zeros(1), np.cumsum(np.ones(n))])
    vref = np.gradient(r["y_ref"])
    vout = np.gradient(r["y_out"])
    out = {
        "clip": r["clip"],
        "group": r["group"],
        "sec": r["sec"],
        "c_out": corr(vout, vref),
    }
    for name, s in sig.items():
        c = np.concatenate([[0], np.cumsum(s)])
        v = []
        for t in r["t"]:
            a, b = (np.searchsorted(tf, t + d, side="right") for d in (-100, 100))
            v.append(c[b] - c[a])
        out[name] = corr(np.array(v), vref)
    res.append(out)
names = ["vx", "vy", "zoom", "mvx", "mvy"]
for label, sel in (
    ("all", lambda x: True),
    ("output |corr| < 0.3", lambda x: abs(x["c_out"]) < 0.3),
    ("output |corr| >= 0.3", lambda x: abs(x["c_out"]) >= 0.3),
):
    g = [x for x in res if sel(x)]
    print(f"\n{label}: {len(g)} scenes")
    print(
        "  median |corr|:",
        {n: round(float(np.median([abs(x[n]) for x in g])), 2) for n in names},
        "output",
        round(float(np.median([abs(x["c_out"]) for x in g])), 2),
    )
    best = np.array([max(abs(x[n]) for n in names) for x in g])
    print(
        f"  best of the global signals: median {np.median(best):.2f}, share >= 0.5: {np.mean(best >= 0.5):.0%}"
        f", >= 0.7: {np.mean(best >= 0.7):.0%}"
    )
    for grp in ("dev", "test", "dev2", "holdout2"):
        gg = [x for x in g if x["group"] == grp]
        if gg:
            b = np.array([max(abs(x[n]) for n in names) for x in gg])
            print(
                f"    {grp}: {len(gg)} scenes, best median {np.median(b):.2f}, >=0.5: {np.mean(b >= 0.5):.0%}"
            )
