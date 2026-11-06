"""Build a synthetic test video with known ground truth.

Cuts two full-body people out of Ultralytics' bundled bus.jpg with a segmentation model and
composites them onto a plain background: A stays still, B moves along a diagonal axis, so the
relative motion follows a known curve with changing tempo, amplitude and a still section.
Writes <out>.mp4 and <out>.truth.funscript (100 = furthest apart).
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO
from ultralytics.utils import ASSETS

from funscript_gen.export.funscript import Action, Funscript

FPS = 30.0
SIZE = (1280, 720)
AXIS = np.array([np.cos(np.radians(25)), np.sin(np.radians(25))])  # B moves along this direction
# (seconds, frequency Hz, amplitude px)
SEGMENTS = [(8.0, 1.2, 90.0), (8.0, 2.5, 45.0), (4.0, 0.0, 0.0), (8.0, 1.8, 70.0)]


def displacement() -> tuple[np.ndarray, np.ndarray]:
    t_parts, d_parts, t0, phase = [], [], 0.0, 0.0
    for dur, freq, amp in SEGMENTS:
        t = np.arange(0, dur, 1 / FPS)
        d_parts.append(amp * np.sin(phase + 2 * np.pi * freq * t))
        t_parts.append(t0 + t)
        phase += 2 * np.pi * freq * dur
        t0 += dur
    return np.concatenate(t_parts), np.concatenate(d_parts)


def cutouts(img: np.ndarray, count: int = 2) -> list[tuple[np.ndarray, np.ndarray]]:
    """(BGR crop, alpha mask) of the `count` largest people, scaled to ~65% of the frame height."""
    res = YOLO("yolo11n-seg.pt")(img, classes=[0], retina_masks=True, verbose=False)[0]
    order = np.argsort([-(b[2] - b[0]) * (b[3] - b[1]) for b in res.boxes.xyxy.cpu().numpy()])[:count]
    out = []
    for i in order:
        x1, y1, x2, y2 = res.boxes.xyxy[i].int().tolist()
        mask = res.masks.data[i].cpu().numpy()[y1:y2, x1:x2].astype(np.float32)
        crop = img[y1:y2, x1:x2]
        k = SIZE[1] * 0.65 / crop.shape[0]
        size = (round(crop.shape[1] * k), round(crop.shape[0] * k))
        out.append((cv2.resize(crop, size), cv2.resize(mask, size)[..., None]))
    return out


def paste(canvas: np.ndarray, crop: np.ndarray, alpha: np.ndarray, x: int, y: int) -> None:
    h, w = crop.shape[:2]
    region = canvas[y : y + h, x : x + w]
    region[:] = (alpha * crop + (1 - alpha) * region).astype(np.uint8)


def main(out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    (a_img, a_mask), (b_img, b_mask) = cutouts(cv2.imread(str(ASSETS / "bus.jpg")))
    background = np.full((SIZE[1], SIZE[0], 3), 90, np.uint8)
    base_a = (300, 120)
    base_b = (650, 100)

    t, d = displacement()
    writer = cv2.VideoWriter(str(out.with_suffix(".mp4")), cv2.VideoWriter_fourcc(*"mp4v"), FPS, SIZE)
    for di in d:
        frame = background.copy()
        paste(frame, a_img, a_mask, *base_a)
        dx, dy = (AXIS * di).round().astype(int)
        paste(frame, b_img, b_mask, base_b[0] + dx, base_b[1] + dy)
        writer.write(frame)
    writer.release()

    # Ground truth: extrema of the displacement, scaled by the local amplitude to 0..100.
    actions = []
    for i in range(1, len(d) - 1):
        if (d[i] - d[i - 1]) * (d[i + 1] - d[i]) < 0:
            amp = np.abs(d[max(0, i - 60) : i + 60]).max() or 1.0
            actions.append(Action(int(round(t[i] * 1000)), int(round(50 + 50 * d[i] / amp))))
    start = 0.0
    for dur, _, amp in SEGMENTS:  # still sections hold the rest position
        if amp == 0:
            actions += [Action(int(start * 1000), 50), Action(int((start + dur) * 1000), 50)]
        start += dur
    Funscript(actions).save(out.with_suffix(".truth.funscript"))
    print(f"wrote {out.with_suffix('.mp4')} ({len(d)} frames) and {len(actions)} truth actions")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "out/synthetic"))
