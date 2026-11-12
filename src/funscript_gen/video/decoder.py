"""Video decoding with exact presentation timestamps (safe for VFR sources)."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np


@dataclass(frozen=True, slots=True)
class VideoInfo:
    path: Path
    width: int
    height: int
    fps: float
    duration_ms: float
    frame_count: int


@dataclass(slots=True)
class Frame:
    t_ms: float  # presentation timestamp of the source frame
    image: np.ndarray  # BGR uint8, possibly downscaled


def probe(path: str | Path) -> VideoInfo:
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        fps = float(stream.average_rate or stream.guessed_rate or 0.0)
        if stream.duration is not None and stream.time_base is not None:
            duration_ms = float(stream.duration * stream.time_base) * 1000.0
        elif container.duration is not None:
            duration_ms = container.duration / av.time_base * 1000.0
        else:
            duration_ms = 0.0
        frame_count = stream.frames or int(round(duration_ms / 1000.0 * fps))
        ctx = stream.codec_context
        width, height = ctx.width, ctx.height
        if _quarter_turns(next(container.decode(stream), None)) % 2:  # turned by 90 or 270 degrees for display
            width, height = height, width
        return VideoInfo(Path(path), width, height, fps, duration_ms, frame_count)


def _quarter_turns(frame) -> int:
    """How many counterclockwise quarter turns show the frame upright: phone videos are stored sideways with a display
    rotation (displaymatrix) that players apply and the decoder does not."""
    rotation = getattr(frame, "rotation", 0) if frame is not None else 0
    return round(rotation / 90) % 4


def scaled_size(width: int, height: int, max_side: int | None) -> tuple[int, int]:
    if not max_side or max(width, height) <= max_side:
        return width, height
    k = max_side / max(width, height)
    return max(2, round(width * k) // 2 * 2), max(2, round(height * k) // 2 * 2)


def pieces(start_ms: float, end_ms: float, piece_ms: float) -> list[tuple[float, float]]:
    """start_ms..end_ms cut into equal pieces of at most piece_ms: iter_frames over each gives the frames of the
    whole, so their per-frame work can run in parallel."""
    n = max(1, math.ceil((end_ms - start_ms) / piece_ms - 1e-9))
    cuts = [start_ms + (end_ms - start_ms) * j / n for j in range(n)] + [end_ms]
    return list(zip(cuts, cuts[1:]))


def iter_frames(
    path: str | Path,
    target_fps: float | None = None,
    max_side: int | None = None,
    start_ms: float = 0.0,
    end_ms: float | None = None,
) -> Iterator[Frame]:
    """Yield frames, keeping at most one per 1/target_fps time slot. Frames come out the way a player shows them: a
    display rotation in the file is applied."""
    step_ms = 1000.0 / target_fps if target_fps else None
    last_slot = -1
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        width, height = scaled_size(stream.codec_context.width, stream.codec_context.height, max_side)
        if start_ms > 0:
            # A slot earlier: seeking lands on the key frame at or before the target, and a key frame at start_ms
            # that shares its slot with the frame before would take the slot that frame takes when decoding all.
            container.seek(int(max(0.0, start_ms - (step_ms or 0.0)) / 1000.0 * av.time_base))
        for frame in container.decode(stream):
            if frame.time is None:
                continue
            t_ms = frame.time * 1000.0
            if end_ms is not None and t_ms > end_ms:
                break
            if step_ms is not None:
                # Frames before start_ms (decoded after seeking to a key frame) still take their slot, so the
                # frames kept from start_ms on are the same as when decoding from the beginning.
                slot = math.floor(t_ms / step_ms + 0.01)
                if slot <= last_slot:
                    continue
                last_slot = slot
            if t_ms < start_ms:
                continue
            image = frame.to_ndarray(format="bgr24", width=width, height=height)
            if turns := _quarter_turns(frame):
                image = np.ascontiguousarray(np.rot90(image, turns))
            yield Frame(t_ms, image)
