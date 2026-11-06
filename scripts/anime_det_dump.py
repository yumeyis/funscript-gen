"""Run imgutils anime detectors on sampled frames; dump boxes to JSON.

usage: uv run --with dghs-imgutils --with onnxruntime python scripts/anime_det_dump.py VIDEO OUT.json [--fps 1] [--models person,halfbody,heads,hands,censors,booru]
"""

from __future__ import annotations

import argparse
import json
import time

import cv2
from PIL import Image

from funscript_gen.video.decoder import iter_frames


def detectors(names):
    import imgutils.detect as d

    table = {
        "person": d.detect_person,
        "halfbody": d.detect_halfbody,
        "heads": d.detect_heads,
        "hands": d.detect_hands,
        "censors": d.detect_censors,
        "booru": d.detect_with_booru_yolo,
        "nudenet": d.detect_with_nudenet,
    }
    return {n: table[n] for n in names}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--models", default="person,halfbody,heads,hands,censors,booru")
    a = ap.parse_args()

    fns = detectors(a.models.split(","))
    rows, t0 = [], time.time()
    W = H = 0
    for f in iter_frames(a.video, target_fps=a.fps, max_side=960):
        H, W = f.image.shape[:2]
        img = Image.fromarray(cv2.cvtColor(f.image, cv2.COLOR_BGR2RGB))
        row = {"t": round(f.t_ms, 1)}
        for n, fn in fns.items():
            row[n] = [[list(map(int, b)), lab, round(float(c), 3)] for b, lab, c in fn(img)]
        rows.append(row)
    with open(a.out, "w") as fh:
        json.dump({"w": W, "h": H, "fps": a.fps, "sec": round(time.time() - t0, 1), "frames": rows}, fh)


if __name__ == "__main__":
    main()
