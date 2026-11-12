"""Run imgutils detect_censors at a high frame rate on given time spans; dump boxes to JSON.

usage: uv run --with dghs-imgutils --with onnxruntime python scripts/experiments/censor_dump.py VIDEO OUT.json --spans 0-13000,20000-40000 [--fps 10]
"""

from __future__ import annotations

import argparse
import json
import time

import cv2
from PIL import Image

from funscript_gen.video.decoder import iter_frames


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--spans", required=True)
    ap.add_argument("--fps", type=float, default=10.0)
    a = ap.parse_args()

    from imgutils.detect import detect_censors

    spans = [tuple(map(float, s.split("-"))) for s in a.spans.split(",")]
    rows, t0 = [], time.time()
    for s, e in spans:
        for f in iter_frames(a.video, target_fps=a.fps, max_side=960, start_ms=s, end_ms=e):
            img = Image.fromarray(cv2.cvtColor(f.image, cv2.COLOR_BGR2RGB))
            dets = detect_censors(img, conf_threshold=0.15)
            rows.append({"t": round(f.t_ms, 1), "d": [[list(map(int, b)), l, round(float(c), 3)] for b, l, c in dets]})
    h, w = f.image.shape[:2]
    with open(a.out, "w") as fh:
        json.dump({"w": w, "h": h, "fps": a.fps, "sec": round(time.time() - t0, 1), "frames": rows}, fh)


if __name__ == "__main__":
    main()
