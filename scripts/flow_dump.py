"""Dump a coarse optical-flow field for every analysed frame, for fast offline experiments.

usage: python scripts/flow_dump.py VIDEO OUT.npz [--fps 30] [--width 480] [--cell 8]
Saves t_ms (N,) and flow (N, H/cell, W/cell, 2) float16 in pixels of the --width-scaled frame.
"""

from __future__ import annotations

import argparse

import cv2
import numpy as np

from funscript_gen.tracking.flow import FARNEBACK
from funscript_gen.video.decoder import iter_frames


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--width", type=int, default=480)
    ap.add_argument("--cell", type=int, default=8)
    a = ap.parse_args()

    prev = None
    ts, fields = [], []
    for f in iter_frames(a.video, target_fps=a.fps, max_side=640):
        h = round(f.image.shape[0] * a.width / f.image.shape[1])
        gray = cv2.cvtColor(cv2.resize(f.image, (a.width, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        if prev is None:
            flow = np.zeros((h, a.width, 2), np.float32)
        else:
            flow = cv2.calcOpticalFlowFarneback(prev, gray, None, *FARNEBACK)
        prev = gray
        hc, wc = h // a.cell, a.width // a.cell
        pooled = flow[: hc * a.cell, : wc * a.cell].reshape(hc, a.cell, wc, a.cell, 2).mean(axis=(1, 3))
        ts.append(f.t_ms)
        fields.append(pooled.astype(np.float16))
    np.savez_compressed(a.out, t_ms=np.array(ts), flow=np.stack(fields))
    print(f"{len(ts)} frames -> {a.out}")


if __name__ == "__main__":
    main()
