"""Offline: is the script's velocity in the flow field of a scene at all? Per scene a ridge regression from the 12x12 cells'
flow (x and y, summed over +-100 ms of each 10 fps label time, camera median removed) to the script's velocity, fitted on one
half of the scene and tested on the other (both ways), against the output's own correlation.
usage: flow_oracle.py LABELS.pkl FLOW_DIR JOBS.json [--alpha 10] [--mask]"""

import json
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from ft_flow import window_inputs  # noqa: E402

rows = pickle.loads(Path(sys.argv[1]).read_bytes())
flow_dir = Path(sys.argv[2])
jobs = json.loads(Path(sys.argv[3]).read_text())
roi_of = {(c, s["index"]): s["roi"] for c, scs in jobs.items() for s in scs}
use_mask = "--mask" in sys.argv
G = 12


def corr(a, b):
    return float(np.corrcoef(a, b)[0, 1]) if a.std() > 1e-9 and b.std() > 1e-9 else 0.0


def ridge_fit(x, y, a):
    x = x - x.mean(0)
    return np.linalg.solve(x.T @ x + a * np.eye(x.shape[1]) * len(x), x.T @ y)


out, cache_clip, cache = [], None, None
for r in rows:
    if not r["ref_ok"] or len(r["t"]) < 60:
        continue
    if r["clip"] != cache_clip:
        cache, cache_clip = np.load(flow_dir / f"{r['clip']}.npz"), r["clip"]
    k = r["index"]
    if f"f{k}" not in cache.files:
        continue
    x = window_inputs(
        r["t"], cache[f"t{k}"], cache[f"f{k}"], roi_of.get((r["clip"], k)), grid=G
    )
    mask = x[:, 4].mean(0)
    feats = x[:, 0:2] + x[:, 2:4]  # (N, 2, G, G): flow over +-100 ms
    if use_mask:
        feats = feats * mask[None, None]
    feats = feats.reshape(len(x), -1)
    vref = np.gradient(r["y_ref"])
    vout = np.gradient(r["y_out"])
    n = len(vref)
    half = n // 2
    lagbest = None
    if "--lag" in sys.argv:
        best = (-9, 0)
        for lag in range(-10, 11, 2):  # label times shifted by lag x 100 ms
            vr = np.roll(vref, lag)
            cs = []
            for tr, te in (
                (slice(0, half), slice(half, n)),
                (slice(half, n), slice(0, half)),
            ):
                w = ridge_fit(feats[tr], vr[tr] - vr[tr].mean(), 1.0)
                cs.append(corr((feats[te] - feats[tr].mean(0)) @ w, vr[te]))
            best = max(best, (float(np.mean(cs)), lag))
        lagbest = best
    cs = []
    for tr, te in ((slice(0, half), slice(half, n)), (slice(half, n), slice(0, half))):
        for alpha in (1.0,):
            w = ridge_fit(feats[tr], vref[tr] - vref[tr].mean(), alpha)
            cs.append(corr((feats[te] - feats[tr].mean(0)) @ w, vref[te]))
    out.append(
        dict(
            clip=r["clip"],
            lag=lagbest,
            group=r["group"],
            c_out=corr(vout, vref),
            cv=float(np.mean(cs)),
            sec=r["sec"],
        )
    )
for label, sel in (
    ("all", lambda x: True),
    ("output |corr| < 0.3", lambda x: abs(x["c_out"]) < 0.3),
    ("output |corr| >= 0.3", lambda x: abs(x["c_out"]) >= 0.3),
):
    g = [x for x in out if sel(x)]
    cv = np.array([x["cv"] for x in g])
    print(
        f"{label}: {len(g)} scenes; oracle ridge CV corr median {np.median(cv):.2f}, >=0.3: {np.mean(cv >= 0.3):.0%},"
        f" >=0.5: {np.mean(cv >= 0.5):.0%}; output |corr| median {np.median([abs(x['c_out']) for x in g]):.2f}"
    )

if "--lag" in sys.argv:
    low = [x for x in out if abs(x["c_out"]) < 0.3]
    print(
        "low scenes: CV corr at lag 0 / best lag: median",
        round(float(np.median([x["cv"] for x in low])), 2),
        "/",
        round(float(np.median([x["lag"][0] for x in low])), 2),
        "; best lag != 0 share",
        round(float(np.mean([x["lag"][1] != 0 for x in low])), 2),
        "; best lag histogram",
        np.unique([x["lag"][1] for x in low], return_counts=True),
    )
