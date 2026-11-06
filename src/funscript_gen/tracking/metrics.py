"""Turn per-frame poses into a relative-motion signal between two subjects (A and B)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.ndimage import median_filter

from funscript_gen.tracking.pose import Person, PoseFrame

# COCO-17 keypoint groups usable as reference points.
KEYPOINT_GROUPS: dict[str, list[int]] = {
    "head": [0, 1, 2, 3, 4],
    "shoulder": [5, 6],
    "wrist": [9, 10],
    "hip": [11, 12],
    "knee": [13, 14],
    "ankle": [15, 16],
    "torso": [5, 6, 11, 12],
}

Axis = Literal["auto", "distance", "vertical", "horizontal"]
Roi = tuple[float, float, float, float]  # normalized x1, y1, x2, y2


# When a reference group is rarely visible (e.g. hips out of frame), try these instead.
FALLBACKS: dict[str, list[str]] = {
    "hip": ["torso", "shoulder"],
    "knee": ["hip", "torso"],
    "ankle": ["knee", "hip"],
    "head": ["shoulder", "torso"],
    "shoulder": ["torso", "head"],
    "wrist": ["shoulder", "torso"],
    "torso": ["shoulder", "hip"],
}


def group_point(person: Person, group: str, min_conf: float = 0.2, min_total: float = 0.3) -> np.ndarray | None:
    """Confidence-weighted mean of a keypoint group, or None if it is not visible enough.

    Soft weights (instead of a hard in/out threshold) keep the point from jumping when one side
    of a symmetric pair flickers around the threshold.
    """
    idx = KEYPOINT_GROUPS[group]
    w = person.kconf[idx].astype(float)
    w[w < min_conf] = 0.0
    if w.sum() < min_total:
        return None
    return (person.kpts[idx] * w[:, None]).sum(axis=0) / w.sum()


def body_scale(person: Person, min_conf: float = 0.3) -> float:
    """Torso length in pixels, used to make the signal independent of camera zoom."""
    c = person.kconf
    if min(c[5], c[6], c[11], c[12]) >= min_conf:
        shoulders = person.kpts[[5, 6]].mean(axis=0)
        hips = person.kpts[[11, 12]].mean(axis=0)
        torso = float(np.linalg.norm(shoulders - hips))
        if torso > 1.0:
            return torso
    w, h = person.box[2] - person.box[0], person.box[3] - person.box[1]
    return 0.3 * float(max(w, h, 1.0))


def _in_roi(p: Person, roi: Roi | None, width: int, height: int) -> bool:
    if roi is None:
        return True
    cx, cy = p.center
    x1, y1, x2, y2 = roi
    return x1 * width <= cx <= x2 * width and y1 * height <= cy <= y2 * height


@dataclass
class RelativeTrack:
    t_ms: np.ndarray  # (N,)
    rel: np.ndarray  # (N, 2) ref point A minus ref point B, pixels; NaN when a subject is missing
    scale: np.ndarray  # (N,) mean body scale of A and B; NaN when missing
    ids: np.ndarray  # (N, 2) track ids of A and B; -1 when missing
    refs: tuple[str, str]  # keypoint groups actually used for A and B


def select_subjects(frames: Sequence[PoseFrame], roi: Roi | None = None) -> list[tuple[Person | None, Person | None]]:
    """Pick subjects A and B in every frame, keeping identities stable over time.

    Priority per slot: same track id as before > nearest to the previous position > largest box.
    """
    pairs: list[tuple[Person | None, Person | None]] = []
    prev: list[tuple[int, np.ndarray] | None] = [None, None]

    for f in frames:
        cands = sorted(
            (p for p in f.people if _in_roi(p, roi, f.width, f.height)), key=lambda p: p.area, reverse=True
        )[:4]
        chosen: list[Person | None] = [None, None]
        taken: set[int] = set()

        def pick(slot: int, person: Person) -> None:
            chosen[slot] = person
            taken.add(id(person))

        for slot in (0, 1):  # 1) same track id
            if prev[slot] is not None and prev[slot][0] >= 0:
                match = next((p for p in cands if p.track_id == prev[slot][0] and id(p) not in taken), None)
                if match is not None:
                    pick(slot, match)
        max_jump = 0.25 * max(f.width, f.height)
        for slot in (0, 1):  # 2) nearest to last known position
            if chosen[slot] is None and prev[slot] is not None:
                pool = [p for p in cands if id(p) not in taken]
                if pool:
                    d = [float(np.linalg.norm(p.center - prev[slot][1])) for p in pool]
                    j = int(np.argmin(d))
                    if d[j] < max_jump:
                        pick(slot, pool[j])
        for slot in (0, 1):  # 3) largest remaining
            if chosen[slot] is None:
                pool = [p for p in cands if id(p) not in taken]
                if pool:
                    pick(slot, pool[0])

        for slot, p in enumerate(chosen):
            if p is not None:
                prev[slot] = (p.track_id, p.center)
        pairs.append((chosen[0], chosen[1]))
    return pairs


def choose_group(people: Sequence[Person | None], wanted: str, min_availability: float = 0.6) -> str:
    """Use `wanted` if it is visible often enough, else the most visible of its fallbacks.

    One group is used for the whole track: switching groups frame by frame causes jumps.
    """
    present = [p for p in people if p is not None]
    if not present:
        return wanted
    candidates = [wanted, *FALLBACKS.get(wanted, [])]
    avail = {g: sum(group_point(p, g) is not None for p in present) / len(present) for g in candidates}
    if avail[wanted] >= min_availability:
        return wanted
    return max(candidates, key=lambda g: avail[g])


def assign_pairs(
    frames: Sequence[PoseFrame],
    roi: Roi | None = None,
    ref_a: str = "hip",
    ref_b: str = "hip",
) -> RelativeTrack:
    n = len(frames)
    rel = np.full((n, 2), np.nan)
    scale = np.full(n, np.nan)
    ids = np.full((n, 2), -1, dtype=int)

    pairs = select_subjects(frames, roi)
    group_a = choose_group([a for a, _ in pairs], ref_a)
    group_b = choose_group([b for _, b in pairs], ref_b)

    for i, (a, b) in enumerate(pairs):
        ids[i] = [a.track_id if a else -1, b.track_id if b else -1]
        if a is None or b is None:
            continue
        pa, pb = group_point(a, group_a), group_point(b, group_b)
        if pa is None or pb is None:
            continue  # gap: interpolated later if short, rather than switching reference source
        rel[i] = pa - pb
        scale[i] = (body_scale(a) + body_scale(b)) / 2

    return RelativeTrack(np.array([f.t_ms for f in frames], dtype=float), rel, scale, ids, (group_a, group_b))


def _fill_nan(x: np.ndarray) -> np.ndarray:
    ok = ~np.isnan(x)
    if not ok.any():
        return np.zeros_like(x)
    idx = np.arange(len(x))
    return np.interp(idx, idx[ok], x[ok])


def to_signal(track: RelativeTrack, axis: Axis = "auto", fps: float = 30.0) -> tuple[np.ndarray, np.ndarray | None]:
    """Project the relative vector onto a scalar signal in body-scale units.

    The sign is chosen so that larger values mean the subjects are further apart.
    Returns (signal with NaN where invalid, axis unit vector or None for "distance").
    """
    valid = ~np.isnan(track.rel[:, 0])
    if valid.sum() < 2:
        return np.full(len(track.t_ms), np.nan), None

    window = max(3, round(fps * 3) | 1)  # ~3 s rolling median: robust to per-frame pose jitter
    scale = median_filter(_fill_nan(track.scale), size=window, mode="nearest")
    r = track.rel / np.maximum(scale, 1e-6)[:, None]
    dist = np.linalg.norm(r, axis=1)

    vec: np.ndarray | None
    if axis == "distance":
        signal, vec = dist, None
    else:
        if axis == "vertical":
            vec = np.array([0.0, 1.0])
        elif axis == "horizontal":
            vec = np.array([1.0, 0.0])
        else:
            centered = r[valid] - np.median(r[valid], axis=0)
            vec = np.linalg.svd(centered, full_matrices=False)[2][0]
        signal = r @ vec
        c = np.corrcoef(signal[valid], dist[valid])[0, 1]
        if np.isfinite(c) and c < 0:
            signal, vec = -signal, -vec

    signal = signal.astype(float)
    signal[~valid] = np.nan
    return signal, vec
