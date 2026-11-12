"""Offline: how the camera-motion estimate subtracted before FlowTracker.component affects the region's signal.

For every flow scene of a run (its debug.json gives the regions) the stored flow field (scripts/flow_dump.py,
out/regions/CLIP.npz) is cut to the scene's region and reduced like FlowTracker.component: camera motion
subtracted, first principal component over the cells, integrated with a 3 s detrend. Each camera estimate's
signal is scored by |r| with the manual script (best lag within +-200 ms; the component's sign is arbitrary here).
usage: uv run python scripts/experiments/camera_motion.py RUN_DIR_OLD13 RUN_DIR_NEW12 [roi|alt_roi] [PICK_MARGIN]
"""

import glob
import json
import sys

import numpy as np

from funscript_gen.export.funscript import Funscript
from funscript_gen.signal.process import dominant_tempo
from funscript_gen.tracking.flow import integrate

OLD = ["B01", "C01", "D01", "A01", "A02", "A03", "A04", "E01",
       "B02", "B03", "F01", "E02", "D02"]
NEW = ["B04", "H01", "H02", "I01", "G01", "J01", "A05", "A06", "A07", "K01", "D03", "L01"]
PICK_MARGIN = float(sys.argv[4]) if len(sys.argv) > 4 else 0.1  # periodicity lead "none" needs
MIN_OUTSIDE = 0.25  # share of the frame's cells outside the region needed to estimate the camera from them


def cells(rows, cols, roi):
    if roi is None:
        return slice(0, rows), slice(0, cols)
    x1, y1, x2, y2 = roi
    r0, c0 = int(y1 * rows), int(x1 * cols)
    return slice(r0, max(int(y2 * rows), r0 + 1)), slice(c0, max(int(x2 * cols), c0 + 1))


def cameras(f, ys, xs):
    """Camera-motion estimates per frame, (n, 2) each."""
    n, rows, cols, _ = f.shape
    full = np.median(f.reshape(n, -1, 2), axis=1)
    mask = np.ones((rows, cols), bool)
    mask[ys, xs] = False
    outside = np.median(f[:, mask], axis=1) if mask.mean() >= MIN_OUTSIDE else None
    return {
        "full": full,
        "none": np.zeros((n, 2), np.float32),
        "out|full": outside if outside is not None else full,
        "out|none": outside if outside is not None else np.zeros((n, 2), np.float32),
    }


def component(f, ys, xs, camera):
    n = len(f)
    x = (f[:, ys, xs] - camera[:, None, None]).reshape(n, -1)
    x = x - x.mean(axis=0)
    u, s, vt = np.linalg.svd(x, full_matrices=False)
    return integrate(u[:, 0] * s[0] / max(np.abs(vt[0]).sum(), 1e-9))


def best_r(pos, ref):
    rs = [np.corrcoef(np.roll(pos, lag)[6:-6], ref[6:-6])[0, 1] for lag in range(-6, 7)]
    return max(abs(r) for r in rs if np.isfinite(r)) if any(np.isfinite(rs)) else np.nan


def main():
    run_old, run_new = sys.argv[1], sys.argv[2]
    key = sys.argv[3] if len(sys.argv) > 3 else "roi"
    rows_out = []
    for clip in OLD + NEW:
        run = run_old if clip in OLD else run_new
        d = np.load(f"out/regions/{clip}.npz")
        t_all, f_all = d["t_ms"], d["flow"]
        ref = Funscript.load(glob.glob(f"valid/{clip}-*.funscript")[0]).normalized()
        ra = ([a.at for a in ref.actions], [a.pos for a in ref.actions])
        for k, sc in enumerate(json.load(open(f"{run}/{clip}.debug.json"))["scenes"]):
            if sc["mode"] != "flow" or sc["rest"] or sc["skip"] or sc["end_ms"] - sc["start_ms"] < 4000:
                continue
            if key == "alt_roi" and sc["alt_roi"] is None:
                continue
            m = (t_all >= sc["start_ms"]) & (t_all < sc["end_ms"])
            x_ref = np.interp(t_all[m], *ra)
            if m.sum() < 120 or x_ref.std() < 1:
                continue
            f = f_all[m].astype(np.float32)
            ys, xs = cells(f.shape[1], f.shape[2], sc[key])
            cams = cameras(f, ys, xs)
            pos = {name: component(f, ys, xs, cam) for name, cam in cams.items()}
            r = {name: best_r(p, x_ref) for name, p in pos.items()}
            # "pick": the full-frame median or none, whichever signal is more periodic (by PICK_MARGIN)
            share = {name: dominant_tempo(pos[name], 30.0, 0.5, 6.0)[1] for name in ("full", "none")}
            r["pick"] = r["none"] if share["none"] > share["full"] + PICK_MARGIN else r["full"]
            share = np.abs(cams["full"]).mean() / max(np.abs(f).mean(), 1e-9)
            rows_out.append((clip, k, r, share))
    names = list(rows_out[0][2])
    print(f"{len(rows_out)} scenes, mean |r|: " + "  ".join(f"{n} {np.nanmean([r[n] for _, _, r, _ in rows_out]):.3f}"
                                                        for n in names))
    for n in names[1:]:
        d = np.array([r[n] - r["full"] for _, _, r, _ in rows_out])
        print(f"  {n:9} vs full: better by >0.1 in {np.sum(d > 0.1):2}, worse by >0.1 in {np.sum(d < -0.1):2}")
    print("scenes that change by more than 0.1 (camera share = full-frame median / mean cell flow):")
    for clip, k, r, share in sorted(rows_out, key=lambda q: -max(abs(q[2][n] - q[2]["full"]) for n in names)):
        if max(abs(r[n] - r["full"]) for n in names) > 0.1:
            print(f"  {clip:8}#{k:2} camera share {share:.2f}  " + "  ".join(f"{n} {r[n]:.2f}" for n in names))


if __name__ == "__main__":
    main()
