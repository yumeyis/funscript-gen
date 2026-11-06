"""Offline: set the output's stroke positions from the penis box instead of the optical flow's amplitude.

Keeps every output action's time; in scenes with 10 fps censor dumps (out/anime_det/cen) the positions become the
penis-box feature at that time, mapped to the scene's own output range. The feature's sign comes from its
correlation with the output (the direction the pipeline chose), never from the manual script.
usage: uv run python scripts/censor_position.py [OUTPUT_DIR]
"""

import glob
import json
import os
import sys

import numpy as np

from funscript_gen.evaluate import compare, drop_wiggles
from funscript_gen.export.funscript import Action, Funscript

OUT = sys.argv[1] if len(sys.argv) > 1 else "out/v14_def_asym_part"
CEN = "out/anime_det/cen"
CLIPS = ["B01", "C01", "D01", "A01", "A02", "A03", "A04", "E01",
         "B02", "B03", "F01", "E02", "D02"]


def movavg(x, k):
    k = max(3, k | 1)
    return np.convolve(np.pad(x, k // 2, mode="edge"), np.ones(k) / k, mode="valid")


def series(rows, w, h, feat):
    diag = float(np.hypot(w, h))
    t = np.array([r["t"] for r in rows])
    x = np.full(len(rows), np.nan)
    edge = []
    for i, r in enumerate(rows):
        pen = [d for d in r["d"] if d[1] == "penis"]
        if not pen:
            continue
        (x1, y1, x2, y2), _, _ = max(pen, key=lambda d: d[2])
        edge.append(x1 <= 2 or y1 <= 2 or x2 >= w - 2 or y2 >= h - 2)
        if feat == "len":
            x[i] = max(x2 - x1, y2 - y1) / diag
        elif feat == "area":
            x[i] = (x2 - x1) * (y2 - y1) / diag**2
        else:
            pus = [b for b, lab, _ in r["d"] if lab == "pussy"]
            if pus:
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                x[i] = min(np.hypot(cx - (b[0] + b[2]) / 2, cy - (b[1] + b[3]) / 2) for b in pus) / diag
    return t, x, (np.mean(edge) if edge else 1.0)


def curve(acts, t):
    return np.interp(t, [a.at for a in acts], [a.pos for a in acts])


def remap(pred, ref, data, scenes, feat, mode, oracle=False):
    """New action list; scenes without usable features keep their positions. Returns (actions, n scenes)."""
    acts = list(pred.actions)
    used = 0
    w, h, fps = data["w"], data["h"], data["fps"]
    for sc in scenes:
        s, e = sc["start_ms"], sc["end_ms"]
        idx = [i for i, a in enumerate(acts) if s <= a.at < e]
        if len(idx) < 4:
            continue
        lo = min(acts[i].pos for i in idx)
        hi = max(acts[i].pos for i in idx)
        if oracle:
            for i in idx:
                acts[i] = Action(acts[i].at, int(round(curve(ref.actions, np.array([acts[i].at]))[0])))
            used += 1
            continue
        rows = [r for r in data["frames"] if s <= r["t"] < e]
        if len(rows) < 20:
            continue
        t, x, edge = series(rows, w, h, feat)
        ok = ~np.isnan(x)
        if ok.mean() < 0.6 or edge >= 0.8:
            continue
        x = np.interp(t, t[ok], x[ok])
        k2 = int(2 * fps)
        y = curve(pred.actions, t)
        xd, yd = x - movavg(x, k2), y - movavg(y, k2)
        if xd.std() < 1e-9 or yd.std() < 1e-9:
            continue
        r = np.corrcoef(xd, yd)[0, 1]
        if abs(r) < 0.2:  # the box does not follow the strokes the output has
            continue
        g = np.sign(r) * x
        if mode.startswith("detrend"):
            g = g - movavg(g, int(4 * fps)) + g.mean()
        at = np.array([acts[i].at for i in idx])
        # the feature around each action: median over +-100 ms
        val = np.array([np.median(g[np.abs(t - a) <= 100]) if np.any(np.abs(t - a) <= 100) else np.interp(a, t, g)
                        for a in at])
        p5, p95 = np.percentile(g, 5), np.percentile(g, 95)
        if p95 - p5 < 1e-9:
            continue
        new = lo + (hi - lo) * np.clip((val - p5) / (p95 - p5), 0, 1)
        if mode.endswith("blend"):
            new = 0.5 * new + 0.5 * np.array([acts[i].pos for i in idx])
        for i, v in zip(idx, new):
            acts[i] = Action(acts[i].at, int(round(v)))
        used += 1
    return acts, used


def main():
    variants = [("orig", None, None), ("oracle", None, "oracle")] + [
        (f"{f}/{m}", f, m) for f in ("dist", "area", "len") for m in ("raw", "detrend", "raw-blend", "detrend-blend")]
    tot = {v[0]: [] for v in variants}
    print(f"{'clip':7}" + "".join(f"{v[0]:>20}" for v in variants))
    for clip in CLIPS:
        ref = Funscript.load(glob.glob(f"valid/{clip}*.funscript")[0])
        pred = Funscript.load(f"{OUT}/{clip}.funscript")
        scenes = json.load(open(f"{OUT}/{clip}.debug.json"))["scenes"]
        path = f"{CEN}/{clip}.json"
        data = json.load(open(path)) if os.path.exists(path) else {"w": 1, "h": 1, "fps": 10, "frames": []}
        cells = []
        for name, feat, mode in variants:
            if name == "orig":
                acts, used = pred.actions, 0
            else:
                acts, used = remap(pred, ref, data, scenes, feat, mode or "", oracle=mode == "oracle")
            fs = Funscript(actions=acts).normalized()
            sc = compare(ref, fs)
            f1s = compare(drop_wiggles(ref), fs).f1
            tot[name].append((sc.f1, sc.correlation_wide, f1s))  # +-500 ms, as recorded in docs/archive/PLAN-archive.md
            cells.append(f"{sc.f1:.2f}/{sc.correlation_wide:.2f}/{f1s:.2f}({used})".rjust(20))
        print(f"{clip:7}" + "".join(cells))
    print(f"{'mean':7}" + "".join(f"{'/'.join(f'{v:.3f}' for v in np.mean(tot[n], axis=0)):>20}" for n, _, _ in variants))


if __name__ == "__main__":
    main()
