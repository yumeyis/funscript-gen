"""Candidate analysis regions for a scene, and the numbered image sheets the VLM picks one from.

The single `focus_roi` box is often not the best region (validation: picking per scene from these
candidates by hand would raise mean F1 0.874 -> 0.907), and the signal's periodicity alone cannot tell
a wrong region with the same rhythm apart. Showing the VLM what each region contains can.
"""

from __future__ import annotations

import cv2
import numpy as np

from funscript_gen.tracking.metrics import Roi

FULL: Roi = (0.0, 0.0, 1.0, 1.0)
PANEL_SIDE = 384  # one 2x2 panel; four panels make one 768-pixel sheet
MAX_KEYFRAMES = 4  # frames per panel


def _union(boxes: list[Roi]) -> Roi:
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def _iou(p: Roi, q: Roi) -> float:
    ix = max(0.0, min(p[2], q[2]) - max(p[0], q[0]))
    iy = max(0.0, min(p[3], q[3]) - max(p[1], q[1]))
    inter = ix * iy
    return inter / ((p[2] - p[0]) * (p[3] - p[1]) + (q[2] - q[0]) * (q[3] - q[1]) - inter)


def candidates(roi: Roi | None, subjects: list[Roi], min_side: float = 0.02, max_iou: float = 0.9) -> list[tuple[str, Roi]]:
    """Named candidates, the current region ("ai") first: subjects A/B, their union, the whole frame and
    a 3x3 grid of half-frame boxes overlapping by a quarter. Tiny boxes and near-duplicates are dropped."""
    named: list[tuple[str, Roi]] = [("ai", roi or FULL), ("full", FULL)]
    named += list(zip("AB", subjects))
    if subjects:
        named.append(("union", _union(subjects)))
    for i, y in enumerate((0.0, 0.25, 0.5)):
        for j, x in enumerate((0.0, 0.25, 0.5)):
            named.append((f"g{i}{j}", (x, y, x + 0.5, y + 0.5)))
    out: list[tuple[str, Roi]] = []
    for name, r in named:
        if r[2] - r[0] < min_side or r[3] - r[1] < min_side:
            continue
        if all(_iou(r, kept) <= max_iou for _, kept in out):
            out.append((name, r))
    return out


def panel(frames: list[np.ndarray], roi: Roi, number: int) -> np.ndarray:
    """The region cut out of up to four frames as a 2x2 grid, with its number in the corner."""
    side = PANEL_SIDE // 2
    tiles = []
    for f in frames[:MAX_KEYFRAMES]:
        h, w = f.shape[:2]
        x1, y1 = int(roi[0] * w), int(roi[1] * h)
        crop = f[y1:max(int(roi[3] * h), y1 + 1), x1:max(int(roi[2] * w), x1 + 1)]
        tiles.append(cv2.resize(crop, (side, side), interpolation=cv2.INTER_AREA))
    tiles += [np.zeros((side, side, 3), np.uint8)] * (MAX_KEYFRAMES - len(tiles))
    img = np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])
    img = cv2.copyMakeBorder(img, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.rectangle(img, (6, 6), (70, 52), (0, 0, 0), -1)
    cv2.putText(img, str(number), (12, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 255, 255), 3)
    return img


def sheets(frames: list[np.ndarray], regions: list[Roi]) -> list[np.ndarray]:
    """Panels numbered from 1, four per sheet (vLLM accepts few images per request)."""
    panels = [panel(frames, r, n) for n, r in enumerate(regions, start=1)]
    out = []
    for k in range(0, len(panels), 4):
        group = panels[k:k + 4]
        group += [np.zeros_like(panels[0])] * (4 - len(group))
        out.append(np.vstack([np.hstack(group[:2]), np.hstack(group[2:])]))
    return out
