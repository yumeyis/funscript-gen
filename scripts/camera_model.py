"""Offline: does a camera model with zoom beat the full-frame median subtracted before FlowTracker.component?

The median takes out a pan but not a zoom (its flow points outwards from the centre and its median is about zero),
so a zoom stays in the region's flow; 3D animation (the G series) moves its camera. Here a similarity motion
(shift, scale and rotation, fitted per frame by reweighted least squares) is compared with the median, with no
camera estimate and with both taken from the cells outside the region only (scripts/camera_motion.py, 2026-10-30,
compared the translations). Per flow scene of the default output the region's first principal component is
integrated as in the pipeline (sign: up = high) and scored against the hand-made script: |r| (best lag within
+-200 ms, the quality of the motion) and the signed r (within +-100 ms, the direction the sign rule gives).

  dump: python scripts/flow_dump.py VIDEO out/regions2/CLIP.npz   (per clip, the analysis' 30 fps)
  uv run python scripts/camera_model.py RUN [RUN ...] --flow out/regions2 [--groups dev,test]

RUN: `validate` runs with saved analyses of the default settings (as scripts/depth_compare.py).
"""
import argparse
import pathlib
import sys
from pathlib import Path

import numpy as np

if sys.platform != "win32":
    pathlib.WindowsPath = pathlib.PureWindowsPath

sys.path.insert(0, str(Path(__file__).parent))
from mask_depth import corr, find  # noqa: E402

CELL = 8
MIN_OUTSIDE = 0.25  # share of the cells outside the region needed to fit the camera to them
MIN_R = 0.3


def cells(rows: int, cols: int, roi) -> tuple[slice, slice]:  # FlowTracker._cells
    if roi is None:
        return slice(0, rows), slice(0, cols)
    x1, y1, x2, y2 = roi
    r0, c0 = int(y1 * rows), int(x1 * cols)
    return slice(r0, max(int(y2 * rows), r0 + 1)), slice(c0, max(int(x2 * cols), c0 + 1))


def similarity(f: np.ndarray, mask: np.ndarray, iters: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Per frame the similarity motion u = tx + a x - b y, v = ty + b x + a y (x, y: cell centres from the frame
    centre, pixels) fitted to the cells in `mask` with Cauchy weights: the camera's flow per cell (n, rows, cols, 2)
    and the scale `a` (per frame, the share the picture grows by)."""
    n, rows, cols, _ = f.shape
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float32)
    x, y = (x + 0.5) * CELL - cols * CELL / 2, (y + 0.5) * CELL - rows * CELL / 2
    xs, ys = x[mask], y[mask]
    m = len(xs)
    one, zero = np.ones(m, np.float32), np.zeros(m, np.float32)
    a_u = np.stack([one, zero, xs, -ys], 1)  # rows of the design matrix for u and for v
    a_v = np.stack([zero, one, ys, xs], 1)
    u, v = f[:, mask, 0], f[:, mask, 1]
    w = np.ones((n, m), np.float32)
    for _ in range(iters + 1):
        ata = np.einsum("nm,mi,mj->nij", w, a_u, a_u) + np.einsum("nm,mi,mj->nij", w, a_v, a_v)
        atb = np.einsum("nm,mi,nm->ni", w, a_u, u) + np.einsum("nm,mi,nm->ni", w, a_v, v)
        p = np.linalg.solve(ata + 1e-6 * np.eye(4), atb[..., None])[..., 0]
        res = np.hypot(u - p @ a_u.T, v - p @ a_v.T)
        c = 1.5 * np.median(res, 1, keepdims=True) + 1e-3
        w = 1 / (1 + (res / c) ** 2)
    cam = np.stack([p[:, 0, None, None] + p[:, 2, None, None] * x - p[:, 3, None, None] * y,
                    p[:, 1, None, None] + p[:, 3, None, None] * x + p[:, 2, None, None] * y], -1)
    return cam, p[:, 2]


def cameras(f: np.ndarray, ys: slice, xs: slice) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Camera estimates (each broadcastable to f) and the full-frame similarity's scale per frame."""
    n, rows, cols, _ = f.shape
    out = np.ones((rows, cols), bool)
    out[ys, xs] = False
    full = np.median(f.reshape(n, -1, 2), 1)[:, None, None]
    sim, scale = similarity(f, np.ones((rows, cols), bool))
    cams = {"median": full, "none": np.zeros((n, 1, 1, 2), np.float32), "sim": sim}
    if out.mean() >= MIN_OUTSIDE:
        cams["out_median"] = np.median(f[:, out], 1)[:, None, None]
        cams["out_sim"] = similarity(f, out)[0]
    else:
        cams["out_median"], cams["out_sim"] = full, sim
    return cams, scale


def component(f: np.ndarray, ys: slice, xs: slice, cam: np.ndarray, fps: float) -> np.ndarray:
    """FlowTracker.component (no direction: up = high) and integrate, on the region's cells."""
    from funscript_gen.tracking.flow import integrate

    n = len(f)
    x = (f - cam)[:, ys, xs].reshape(n, -1)
    x = x - x.mean(0)
    u, s, vt = np.linalg.svd(x, full_matrices=False)
    load = vt[0].reshape(-1, 2)
    weight = np.abs(load).sum(1)
    sign = -1.0 if -(load[:, 1] * weight).sum() < 0 else 1.0
    return integrate(sign * u[:, 0] * s[0] / max(weight.sum(), 1e-9), fps=fps)


def main() -> None:
    from funscript_gen.cli import parse_generate_args
    from funscript_gen.export.funscript import Funscript
    from funscript_gen.options import build, for_analysis
    from funscript_gen.pipeline import render
    from funscript_gen.validate import clips, load_manifest

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--flow", required=True)
    ap.add_argument("--groups", default="dev,test")
    ap.add_argument("-v", action="store_true", help="list the scenes that change")
    a = ap.parse_args()
    given, preset = parse_generate_args([])
    rows = []
    for clip in clips(load_manifest(), a.groups):
        path = Path(a.flow) / f"{clip.name}.npz"
        analysis = find([Path(r) for r in a.runs], clip.name)
        if not path.exists() or analysis is None:
            print(f"{clip.name}: no flow field or analysis")
            continue
        d = np.load(path)
        t_all, f_all = d["t_ms"], d["flow"]
        res = render(analysis, build(for_analysis(analysis.key, given, preset)))
        ref = Funscript.load(clip.reference).normalized().actions
        ra = ([x.at for x in ref], [x.pos for x in ref])
        for plan in res.plans:
            if plan.source is None or plan.skip or plan.rest or plan.decisions or plan.direction is not None:
                continue
            sel = (t_all >= plan.scene.start_ms) & (t_all < plan.scene.end_ms)
            if sel.sum() < 60:
                continue
            t = t_all[sel]
            y = np.interp(t, *ra)
            if y.std() < 1:
                continue
            fps = 1000 * (len(t) - 1) / max(t[-1] - t[0], 1)
            f = f_all[sel].astype(np.float32)
            ys, xs = cells(f.shape[1], f.shape[2], plan.roi)
            cams, scale = cameras(f, ys, xs)
            half_diag = np.hypot(*f.shape[1:3]) * CELL / 2
            pos = {k: component(f, ys, xs, c, fps) for k, c in cams.items()}
            lag_u, lag_s = round(0.2 * fps), round(0.1 * fps)
            rows.append(dict(clip=clip.name, group=clip.group, g=clip.name[0] == "G", index=plan.scene.index,
                             sec=len(t) / fps,
                             zoom=float(np.median(np.abs(scale)) * half_diag),  # px/frame at the corners
                             flow=float(np.median(np.abs(f))),
                             src=corr(pos["median"], np.interp(t, *plan.source), 0),
                             ru={k: abs(corr(p, y, lag_u) or 0) for k, p in pos.items()},
                             rs={k: corr(p, y, lag_s) or 0 for k, p in pos.items()}))
    names = list(rows[0]["ru"])
    src = np.array([r["src"] or 0 for r in rows])
    print(f"{len(rows)} scenes; 'median' against the pipeline's own source: median r {np.median(src):.3f},"
          f" {np.mean(src > 0.9):.0%} above 0.9")
    for part in ("2D dev", "2D test", "G dev", "G test"):
        series, group = part.split()
        sub = [r for r in rows if r["g"] == (series == "G") and r["group"] == group]
        if not sub:
            continue
        zoom = np.array([r["zoom"] / max(r["flow"], 1e-6) for r in sub])
        print(f"\n== {part}: {len(sub)} scenes ({sum(r['sec'] for r in sub):.0f} s); zoom at the corners / median cell"
              f" flow: median {np.median(zoom):.2f}, > 0.5 in {np.sum(zoom > 0.5)}")
        print(f"{'camera':12}{'mean|r|':>8}{'better':>7}{'worse':>6}{'|r|>=.3':>8}{'up=high right':>14}"
              f"{'fixes':>6}{'breaks':>7}")
        base = {id(r): r["rs"]["median"] for r in sub}
        for k in names:
            ru = np.array([r["ru"][k] for r in sub])
            d = ru - np.array([r["ru"]["median"] for r in sub])
            strong = [r for r in sub if abs(r["rs"][k]) >= MIN_R]
            right = sum(r["rs"][k] > 0 for r in strong)
            fixes = sum(r["rs"][k] >= MIN_R and base[id(r)] <= -MIN_R for r in sub)
            breaks = sum(r["rs"][k] <= -MIN_R and base[id(r)] >= MIN_R for r in sub)
            print(f"{k:12}{ru.mean():8.3f}{np.sum(d > 0.1):7}{np.sum(d < -0.1):6}{len(strong):8}"
                  f"{right:8}/{len(strong):<5}{fixes:6}{breaks:7}")
    if a.v:
        print("\nscenes where any camera changes |r| by more than 0.1 or flips the sign:")
        for r in rows:
            if any(abs(r["ru"][k] - r["ru"]["median"]) > 0.1 or r["rs"][k] * r["rs"]["median"] < -0.09
                   for k in names):
                print(f"  {r['clip']} #{r['index']:<3} {r['sec']:5.0f} s zoom {r['zoom'] / max(r['flow'], 1e-6):5.2f}  "
                      + "  ".join(f"{k} {r['rs'][k]:+.2f}" for k in names))


if __name__ == "__main__":
    main()
