"""Dense optical flow inside a region of interest, relative to the rest of the frame.

Works without skeletons, so it covers close-ups, POV shots, occlusion and animation.
"""

from __future__ import annotations

from typing import Literal

import cv2
import numpy as np
from scipy.ndimage import uniform_filter1d

from funscript_gen.tracking.metrics import Roi

FlowAxis = Literal["auto", "vertical", "horizontal", "depth"]

# Flow signals are in pixels (of the `width`-scaled frame); strokes smaller than this are noise.
MIN_AMPLITUDE_PX = 0.5
# cv2.calcOpticalFlowFarneback(pyr_scale, levels, winsize, iterations, poly_n, poly_sigma, flags). Two iterations per
# pyramid level instead of three take about 25% less time (A04 15.9 -> 12.0 ms per frame).
FARNEBACK = (0.5, 4, 21, 2, 5, 1.2, 0)


class FlowTracker:
    """Feed frames of one scene in order; keeps a coarse flow field (cell x cell pixel blocks) per frame.

    The field is in pixels of the `width`-scaled frame. With a smaller `flow_width` the flow is computed on a
    frame that narrow (faster: 320 takes about half the time) and scaled back to the same units and grid.
    Frames narrower than that (portrait video decoded at 360x640) are not enlarged: it adds pixels, not detail.
    With `gpu` Farneback runs on OpenCV's OpenCL device (devices.opencl_gpu): RTX 3070 107 fps against 37 on one CPU
    thread, fields within 0.004 px on average of the CPU's but not the same. The frames are scaled on the CPU.
    """

    def __init__(self, roi: Roi | None, width: int = 480, cell: int = 8, flow_width: int | None = None,
                 gpu: bool = False) -> None:
        self.roi = roi
        self.gpu = gpu
        self.width = width
        self.cell = cell
        self.flow_width = min(flow_width or width, width)
        self.prev: np.ndarray | None = None  # grey frames the flow is computed on: the last one fed
        self.first: np.ndarray | None = None  # and the first
        self.height = 0  # of the `width`-scaled frame
        self.t_ms: list[float] = []
        self.fields: list[np.ndarray] = []  # (rows, cols, 2) float16 per frame

    def update(self, t_ms: float, image: np.ndarray) -> None:
        h0, w0 = image.shape[:2]
        self.height = max(2 * self.cell, round(h0 * self.width / w0))
        fw = min(self.flow_width, w0)
        fh = max(2 * self.cell, round(h0 * fw / w0))
        gray = cv2.cvtColor(cv2.resize(image, (fw, fh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        if self.prev is None:
            self.first = gray
            field = self._pool(np.zeros((fh, fw, 2), np.float32))
        else:
            field = self._field(self.prev, gray)
        self.prev = gray
        self.t_ms.append(t_ms)
        self.fields.append(field)

    def extend(self, other: FlowTracker) -> None:
        """Append `other`, fed the frames that follow this tracker's: its first field (zero, it had no previous
        frame) becomes the flow from this tracker's last frame, so the result is the same as one tracker fed all
        the frames. Each field only depends on its two frames, so one scene's flow can be computed in pieces."""
        if other.first is None:
            return
        if self.prev is None:
            self.first, self.height = other.first, other.height
            self.fields = list(other.fields)
        else:
            self.fields += [self._field(self.prev, other.first), *other.fields[1:]]
        self.t_ms += other.t_ms
        self.prev = other.prev

    def _field(self, prev: np.ndarray, gray: np.ndarray) -> np.ndarray:
        if self.gpu:  # UMat arguments run OpenCV's OpenCL version
            return self._pool(cv2.calcOpticalFlowFarneback(cv2.UMat(prev), cv2.UMat(gray), None, *FARNEBACK).get())
        return self._pool(cv2.calcOpticalFlowFarneback(prev, gray, None, *FARNEBACK))

    def _pool(self, flow: np.ndarray) -> np.ndarray:
        """The (rows, cols, 2) float16 cell field of a flow computed on the flow_width-wide frame."""
        fh, fw = flow.shape[:2]
        c, h = self.cell, self.height
        rows, cols = h // c, self.width // c
        if fw == self.width:
            pooled = flow[: rows * c, : cols * c].reshape(rows, c, cols, c, 2).mean(axis=(1, 3))
        else:  # average over the same cells of the frame, in pixels of the `width`-scaled frame
            area = flow[: round(rows * c * fh / h), : round(cols * c * fw / self.width)]
            pooled = cv2.resize(area, (cols, rows), interpolation=cv2.INTER_AREA) * (self.width / fw)
        return pooled.astype(np.float16)

    @staticmethod
    def _cells(rows: int, cols: int, roi: Roi | None) -> tuple[slice, slice]:
        if roi is None:
            return slice(0, rows), slice(0, cols)
        x1, y1, x2, y2 = roi
        r0, c0 = int(y1 * rows), int(x1 * cols)
        return slice(r0, max(int(y2 * rows), r0 + 1)), slice(c0, max(int(x2 * cols), c0 + 1))

    def velocity(
        self, axis: FlowAxis = "auto", direction: tuple[float, float] | None = None, roi: Roi | None = None,
    ) -> np.ndarray:
        """Per-frame velocity of the subject in pixels/frame, camera motion removed.

        "auto" takes the dominant coherent motion inside the ROI (first principal component over all
        cells), so it also handles parts moving in opposite directions and diagonal motion. Its sign
        is chosen so that motion along `direction` (image x/y, e.g. penis base -> tip) is positive;
        without a direction, the strongest-moving cells going up count as positive.
        An explicit axis projects the ROI's mean flow instead: up, right or expanding is positive.
        `roi` overrides the tracker's ROI: the stored flow field covers the whole frame, so several
        regions can be read from one pass.
        """
        if axis == "auto":
            return self.component(direction, roi)[0]
        f = np.stack(self.fields).astype(np.float32)  # (T, rows, cols, 2)
        n, rows, cols, _ = f.shape
        ys, xs = self._cells(rows, cols, roi if roi is not None else self.roi)
        camera = np.median(f.reshape(n, -1, 2), axis=1)  # dominant (background) motion per frame
        inside = f[:, ys, xs] - camera[:, None, None]

        if axis == "depth":
            fx, fy = inside[..., 0], inside[..., 1]
            return (np.gradient(fx, axis=2) + np.gradient(fy, axis=1)).mean(axis=(1, 2)) * self.cell
        vec = np.array([0.0, -1.0]) if axis == "vertical" else np.array([1.0, 0.0])
        return inside.reshape(n, -1, 2).mean(axis=1) @ vec

    def component(
        self, direction: tuple[float, float] | None = None, roi: Roi | None = None,
    ) -> tuple[np.ndarray, np.ndarray, float]:
        """The "auto" motion: (velocity, pattern, margin).

        `pattern` is the component's flow per cell over the whole frame grid (rows, cols, 2), zero
        outside the ROI, with the same sign as the velocity; patterns of two parts of one shot can be
        compared to keep their signs consistent. `margin` (0..1) is how clearly the sign rule decided:
        the net share of the motion along `direction`, or vertical without one; near 0 the sign is a guess.
        """
        f = np.stack(self.fields).astype(np.float32)
        n, rows, cols, _ = f.shape
        ys, xs = self._cells(rows, cols, roi if roi is not None else self.roi)
        camera = np.median(f.reshape(n, -1, 2), axis=1)
        inside = f[:, ys, xs] - camera[:, None, None]
        x = inside.reshape(n, -1)
        x = x - x.mean(axis=0)
        u, s, vt = np.linalg.svd(x, full_matrices=False)
        load = vt[0].reshape(-1, 2)
        score = u[:, 0] * s[0] / max(np.abs(load).sum(), 1e-9)  # pixels/frame of the moving cells
        weight = np.abs(load).sum(axis=1)
        if direction is not None and np.hypot(*direction) > 0:
            d = np.asarray(direction, float) / np.hypot(*direction)
            net = ((load @ d) * weight).sum()  # positive: the component moves along `direction`
        else:
            net = -(load[:, 1] * weight).sum()  # positive: it moves up (image y grows downward)
        sign = -1.0 if net < 0 else 1.0
        margin = abs(net) / max((np.hypot(load[:, 0], load[:, 1]) * weight).sum(), 1e-9)
        pattern = np.zeros((rows, cols, 2), np.float32)
        pattern[ys, xs] = sign * load.reshape(inside.shape[1:])
        return sign * score, pattern, float(margin)

    def signal(
        self, axis: FlowAxis = "auto", detrend_s: float = 3.0, fps: float | None = None,
        direction: tuple[float, float] | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """(t_ms, position in pixels) — integrated velocity with slow drift removed (`fps`: the frames' rate, by
        default measured from their times)."""
        t = np.array(self.t_ms)
        if len(t) < 3:
            return t, np.zeros(len(t))
        return t, integrate(self.velocity(axis, direction), detrend_s, fps or sample_rate(t))


def sample_rate(t_ms: np.ndarray, fallback: float = 30.0) -> float:
    """Frames per second of the frames at `t_ms`: the analysis takes at most --fps of them, but a 24 fps video has
    only 24 (the per-frame flow and its windows are counted in frames, not in time)."""
    gaps = np.diff(np.asarray(t_ms, float))
    gaps = gaps[gaps > 0]
    return 1000.0 / float(np.median(gaps)) if len(gaps) else fallback


def integrate(velocity: np.ndarray, detrend_s: float = 3.0, fps: float = 30.0) -> np.ndarray:
    """Velocity per frame (`fps` frames per second) -> position, with drift slower than `detrend_s` removed."""
    pos = np.cumsum(velocity)
    win = max(3, round(detrend_s * fps))
    return pos - uniform_filter1d(pos, win, mode="nearest")
