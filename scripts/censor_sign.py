"""Does the censor detector's penis box track the stroke? Per scene: corr(feature, manual) and corr(feature, output).

A feature that follows the manual script with a stable sign can decide the scene's direction: flip the output when
corr(feature, output) has the wrong sign. Reports how often that rule agrees with the manual script.
"""

from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

from funscript_gen.export.funscript import Funscript

S = "out/anime_det"  # det/ (1 fps, all detectors) and cen/ (10 fps censors) dumps
OUT = sys.argv[1] if len(sys.argv) > 1 else "out/v13_def"
MIN_COVER = 0.6


def curve(fs: Funscript, t: np.ndarray) -> np.ndarray:
    a = fs.normalized().actions
    return np.interp(t, [x.at for x in a], [x.pos for x in a])


def detrend(x: np.ndarray, fps: float, win_s: float = 2.0) -> np.ndarray:
    k = max(3, int(win_s * fps) | 1)
    pad = np.pad(x, k // 2, mode="edge")
    return x - np.convolve(pad, np.ones(k) / k, mode="valid")


def best_corr(x: np.ndarray, y: np.ndarray, max_lag: int) -> float:
    """Correlation with the largest |r| over small lags (keeps the sign)."""
    best = 0.0
    for lag in range(-max_lag, max_lag + 1):
        a, b = (x[lag:], y[: len(y) - lag]) if lag >= 0 else (x[:lag], y[-lag:])
        if len(a) > 10 and a.std() > 1e-6 and b.std() > 1e-6:
            r = float(np.corrcoef(a, b)[0, 1])
            if abs(r) > abs(best):
                best = r
    return best


def edge_share(rows, w: int, h: int) -> float:
    """Share of frames whose best penis box touches the frame border (box cut off)."""
    hits = []
    for r in rows:
        pen = [d for d in r["d"] if d[1] == "penis"]
        if pen:
            (x1, y1, x2, y2), _, _ = max(pen, key=lambda d: d[2])
            hits.append(x1 <= 2 or y1 <= 2 or x2 >= w - 2 or y2 >= h - 2)
    return float(np.mean(hits)) if hits else 0.0


def features(rows, w: int, h: int):
    t = np.array([r["t"] for r in rows])
    feats = {"len": np.full(len(t), np.nan), "area": np.full(len(t), np.nan), "dist": np.full(len(t), np.nan)}
    diag = float(np.hypot(w, h))
    for i, r in enumerate(rows):
        pen = [d for d in r["d"] if d[1] == "penis"]
        if not pen:
            continue
        (x1, y1, x2, y2), _, _ = max(pen, key=lambda d: d[2])
        feats["len"][i] = max(x2 - x1, y2 - y1) / diag
        feats["area"][i] = (x2 - x1) * (y2 - y1) / diag**2
        pus = [d for d in r["d"] if d[1] == "pussy"]
        if pus:
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            feats["dist"][i] = min(np.hypot(cx - (b[0] + b[2]) / 2, cy - (b[1] + b[3]) / 2) for b, _, _ in pus) / diag
    return t, feats


def main() -> None:
    names = ["len", "area", "dist"]
    agree = {n: [0, 0] for n in names}
    base = [0, 0]  # current output: scenes with |r_out| >= 0.2 that have the manual script's direction
    print(f"{'clip':7}{'s':>7}{'sec':>5}{'r_out':>7} " + " ".join(f"{n + '_cov':>8}{n + '_ref':>8}" for n in names))
    for path in sorted(glob.glob(f"{S}/cen/*.json")):
        clip = os.path.basename(path)[:-5]
        data = json.load(open(path))
        fps = data["fps"]
        ref = Funscript.load(glob.glob(f"valid/{clip}*.funscript")[0])
        pred = Funscript.load(f"{OUT}/{clip}.funscript")
        for sc in json.load(open(f"{OUT}/{clip}.debug.json"))["scenes"]:
            rows = [r for r in data["frames"] if sc["start_ms"] <= r["t"] < sc["end_ms"]]
            if len(rows) < 20:
                continue
            t, feats = features(rows, data["w"], data["h"])
            if edge_share(rows, data["w"], data["h"]) >= 0.8:
                continue
            y_ref, y_out = detrend(curve(ref, t), fps), detrend(curve(pred, t), fps)
            r_out = best_corr(y_out, y_ref, 0)
            if abs(r_out) >= 0.2 and feats["len"][~np.isnan(feats["len"])].size >= MIN_COVER * len(t):
                base[0] += int(r_out > 0)
                base[1] += 1
            cells = []
            for n in names:
                x = feats[n]
                ok = ~np.isnan(x)
                cov = ok.mean()
                if cov < MIN_COVER or y_ref.std() < 1:
                    cells.append(f"{cov:8.0%}{'-':>8}")
                    continue
                x = detrend(np.interp(t, t[ok], x[ok]), fps)
                r_ref = best_corr(x, y_ref, int(0.1 * fps))
                r_feat_out = best_corr(x, y_out, int(0.1 * fps))
                cells.append(f"{cov:8.0%}{r_ref:+8.2f}")
                if abs(r_out) >= 0.2 and abs(r_feat_out) >= 0.2:
                    # Rule for len/area: the output should rise when the penis box grows (pulled out = high);
                    # dist: farther apart = high. Agreement = the rule's sign choice matches the manual script.
                    agree[n][0] += int(np.sign(r_feat_out) == np.sign(r_out))
                    agree[n][1] += 1
            print(f"{clip:7}{sc['start_ms'] / 1000:7.0f}{(sc['end_ms'] - sc['start_ms']) / 1000:5.0f}{r_out:+7.2f} " + " ".join(cells))
    print(f"current output has the manual script's direction in {base[0]}/{base[1]} scenes (len coverage >= {MIN_COVER:.0%})")
    for n, (a, m) in agree.items():
        print(f"{n}: rule picks the manual script's direction in {a}/{m} scenes")


if __name__ == "__main__":
    main()
