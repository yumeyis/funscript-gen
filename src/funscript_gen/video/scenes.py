"""Shot detection and key-frame sampling (first, cheap pass over the video)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from funscript_gen.video.decoder import Frame, iter_frames


@dataclass
class Scene:
    index: int
    start_ms: float
    end_ms: float  # exclusive
    keyframes: list[Frame] = field(default_factory=list)
    continued: bool = False  # same shot as the previous scene, split only because the shot is long

    def contains(self, t_ms: float) -> bool:
        return self.start_ms <= t_ms < self.end_ms


def _thumb(image: np.ndarray) -> np.ndarray:
    small = cv2.resize(image, (64, 36), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2HSV).astype(np.int16)


def _pick(frames: list[Frame], count: int) -> list[Frame]:
    if len(frames) <= count:
        return frames
    idx = np.linspace(0, len(frames) - 1, count).round().astype(int)
    return [frames[i] for i in idx]


def _starts_scene(t_ms: float, start_ms: float, diff: float, threshold: float, min_scene_s: float,
                  max_chunk_s: float) -> bool | None:
    """Whether a new scene starts at t_ms: None = no, True = at a hard cut, False = the next chunk of a long shot."""
    cut = diff > threshold
    if (cut and t_ms - start_ms >= min_scene_s * 1000) or t_ms - start_ms >= max_chunk_s * 1000:
        return cut
    return None


def detect_scenes(
    path: str | Path,
    fps: float = 10.0,
    threshold: float = 30.0,
    min_scene_s: float = 1.0,
    max_chunk_s: float = 20.0,
    keyframes: int = 4,
    keyframe_side: int = 768,
    on_frame: Callable[[float], None] | None = None,
) -> list[Scene]:
    """Split at hard cuts (mean HSV thumbnail difference > threshold), and split long shots into chunks.

    Each scene gets `keyframes` frames spread over it for the vision model.
    """
    scenes: list[Scene] = []
    candidates: list[Frame] = []
    start: float | None = None
    continued = False
    prev: np.ndarray | None = None
    last_t = 0.0
    step_ms = 1000.0 / fps

    def close(end_ms: float) -> None:
        nonlocal candidates
        if start is not None:
            scenes.append(Scene(len(scenes), start, end_ms, _pick(candidates, keyframes), continued))
        candidates = []

    for frame in iter_frames(path, target_fps=fps, max_side=keyframe_side):
        thumb = _thumb(frame.image)
        if start is None:
            start = frame.t_ms
        else:
            cut = _starts_scene(frame.t_ms, start, float(np.abs(thumb - prev).mean()), threshold, min_scene_s,
                                max_chunk_s)
            if cut is not None:
                close(frame.t_ms)
                start = frame.t_ms
                continued = not cut
        prev = thumb
        candidates.append(frame)
        last_t = frame.t_ms
        if on_frame:
            on_frame(frame.t_ms)
    close(last_t + step_ms)
    return scenes


@dataclass
class FrameDiffs:
    """What detect_scenes looks at, kept so that scenes can be split again at another threshold without decoding:
    the sampled frame times and each frame's difference from the previous one (0 for the first)."""
    t_ms: np.ndarray
    diff: np.ndarray
    step_ms: float


def frame_diffs(path: str | Path, fps: float = 10.0, keyframe_side: int = 768,
                on_frame: Callable[[float], None] | None = None) -> FrameDiffs:
    """The frames detect_scenes would sample (same rate and size, so the scenes match) and their differences."""
    times, diffs = [], []
    prev: np.ndarray | None = None
    for frame in iter_frames(path, target_fps=fps, max_side=keyframe_side):
        thumb = _thumb(frame.image)
        times.append(frame.t_ms)
        diffs.append(0.0 if prev is None else float(np.abs(thumb - prev).mean()))
        prev = thumb
        if on_frame:
            on_frame(frame.t_ms)
    return FrameDiffs(np.asarray(times, float), np.asarray(diffs, float), 1000.0 / fps)


def split_scenes(d: FrameDiffs, threshold: float = 30.0, min_scene_s: float = 1.0,
                 max_chunk_s: float = 20.0) -> list[Scene]:
    """The scenes detect_scenes finds at `threshold`, without key frames."""
    if not len(d.t_ms):
        return []
    scenes: list[Scene] = []
    start, continued = float(d.t_ms[0]), False
    for t, diff in zip(d.t_ms[1:], d.diff[1:]):
        cut = _starts_scene(float(t), start, float(diff), threshold, min_scene_s, max_chunk_s)
        if cut is not None:
            scenes.append(Scene(len(scenes), start, float(t), continued=continued))
            start, continued = float(t), not cut
    scenes.append(Scene(len(scenes), start, float(d.t_ms[-1]) + d.step_ms, continued=continued))
    return scenes


def cut_strength(d: FrameDiffs, t_ms: float) -> float | None:
    """The frame difference where a scene starts at t_ms (how clear the cut is), None at the first frame."""
    k = int(np.searchsorted(d.t_ms, t_ms))
    return float(d.diff[k]) if 0 < k < len(d.t_ms) else None
