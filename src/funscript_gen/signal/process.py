"""Signal post-processing: resample, de-spike, smooth, find strokes, normalize to 0..100."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.ndimage import median_filter, percentile_filter
from scipy.signal import butter, find_peaks, savgol_filter, sosfiltfilt, welch

from funscript_gen.export.funscript import Action


@dataclass
class SignalParams:
    fps: float = 30.0  # uniform grid the signal is resampled to
    max_gap_ms: float = 500.0  # longer gaps between valid samples split the signal into segments
    hampel_window_s: float = 0.3
    hampel_sigma: float = 3.0
    smooth_window_s: float = 0.15
    norm_window_s: float = 4.0  # rolling window for the adaptive 0..100 mapping
    norm_low_pct: float = 5.0
    norm_high_pct: float = 95.0
    min_prominence: float = 0.15  # stroke must span this fraction of the local range...
    min_amplitude: float = 0.04  # ...and at least this much in body-scale units
    # Minimum time between consecutive actions. 90 ms dropped the turning points of strokes above 5.5 Hz (D03 #1:
    # ~5 Hz strokes, 7.1 -> 4.45 per second); 60 ms: 28 clips F1 +0.002 (user +0.004), no clip lower.
    min_interval_ms: float = 60.0
    max_speed: float = 500.0  # pos units per second the device can follow
    # Faster strokes get shorter around the centre of their original range: full length up to
    # freq_limit_hz, shrinking linearly to freq_min_scale at freq_max_hz and above (freq_limit_hz <= 0: off).
    # Hand-made scripts keep full strokes up to about 2.5 Hz (validation, 27 clips: median length 80 below 2.5 Hz,
    # 70 at 2.5-4 Hz); starting at 1.5 Hz shrank the common ~1.9 Hz strokes to 60% (dev correlation 0.495, 0.514 from 2 Hz).
    freq_limit_hz: float = 2.0
    freq_max_hz: float = 3.0
    freq_min_scale: float = 0.5
    # Hold: across gaps longer than hold_after_ms keep the position and move shortly before the next action,
    # instead of moving slowly. Off by default: it also turned slow strokes (2-3 s each way) into steps
    # (validation, 13 clips: mean correlation 0.435 with a 1 s hold, 0.485 without; F1 unchanged).
    hold: bool = False
    hold_after_ms: float = 1000.0  # also the gap that counts as a pause, not a stroke, for freq_limit_hz
    # Dwell: where the signal rests near a turning point, output the start and end of the rest instead
    # of one point (the rest counts while within dwell_tol of the adjacent stroke size of the extremum).
    dwell: bool = False
    dwell_tol: float = 0.05
    dwell_min_ms: float = 200.0  # shorter rests stay a single point
    # Curve: between turning points further apart than curve_after_ms, add points where the signal
    # leaves the straight line by more than curve_tol (0..100 scale).
    curve: bool = False
    curve_after_ms: float = 600.0
    curve_tol: float = 5.0
    pos_low: int = 0
    pos_high: int = 100
    # "preserve": a stroke's size relative to the video's big strokes sets its length (small motion -> short stroke).
    # "fill": every stroke is stretched to the local range (old behaviour).
    amplitude: Literal["preserve", "fill"] = "preserve"
    gain: float = 1.0  # multiplies stroke length in "preserve" mode
    scale_percentile: float = 90.0  # stroke size (percentile over the video) that counts as a full stroke
    min_stroke_pos: float = 6.0  # in "preserve" mode, drop strokes shorter than this (0..100 scale)
    # A signal segment whose spectrum is dominated by one tempo is band-passed around it, which removes
    # drift and unrelated motion that otherwise hide strokes. Off for skeleton signals (not validated).
    rhythm_filter: bool = True
    rhythm_min_share: float = 0.5  # fraction of the spectrum near the dominant tempo needed to filter
    # Below this share the tempo is often wrong (13 clips: it matched the hand-made script in 15 of 27 scenes
    # with a share of 0.5..0.8, in 44 of 47 from 0.8 up), and filtering around a wrong tempo removes the real
    # strokes (F01: 0.82 Hz found, strokes at ~1.8 Hz). So there the signal's own stroke rate must agree.
    rhythm_sure_share: float = 0.8
    rhythm_rate_tol: tuple[float, float] = (0.7, 1.4)  # stroke rate / tempo accepted below rhythm_sure_share
    rhythm_min_hz: float = 0.5  # tempo search range
    rhythm_max_hz: float = 6.0
    rhythm_band: tuple[float, float] = (0.5, 2.0)  # pass band as multiples of the tempo
    # A band-passed signal has no fast motion left to keep, so it is smoothed over a longer window (validation,
    # 28 clips: F1 0.707 -> 0.713, with every scene the right way up 0.743 -> 0.754; 0.2-0.3 s alike, 0.45 s worse).
    # Without a tempo the stroke smoothing stays: 0.2 s there wiped out D03's ~6 Hz strokes.
    rhythm_smooth_window_s: float = 0.2
    # Each scene's full-stroke reference is the geometric mean of the video-wide one and the scene's own
    # (0 = video-wide only, 1 = scene only): pixel motion depends on how close the shot is.
    scene_scale_blend: float = 0.5
    # Scene centre: in signals without a tempo (no rhythm filter) centre the positions on the whole signal's
    # norm_low_pct..norm_high_pct range instead of the norm_window_s window's, so slow strokes keep their height
    # (the window's centre follows them); a range wider than a full stroke is fitted into the output range.
    scene_center: bool = False
    # Bridge: each scene's strokes are found on its own, so at a cut the gap to the next scene's first action often
    # holds more than one of the previous scene's strokes, or both sides end on a peak. There the previous scene's
    # last stroke is repeated (at most bridge_max points, its own positions and timing) instead of a slow move or a stall.
    bridge: bool = True
    bridge_max: int = 2
    bridge_tol: float = 1.5  # inserted points' spacing within 1/tol..tol of the previous scene's half-stroke


@dataclass
class ProcessedSignal:
    t_ms: np.ndarray
    raw: np.ndarray  # resampled, NaN where invalid
    smooth: np.ndarray  # NaN where invalid
    lo: np.ndarray  # local normalization bounds
    hi: np.ndarray
    valid: np.ndarray
    actions: list[Action]
    strokes: list[int] = field(default_factory=list)  # indices of the kept extrema
    tempo_hz: float | None = None  # tempo the signal was band-passed around, if it was


def _odd(n: float, minimum: int = 3) -> int:
    n = max(minimum, int(round(n)))
    return n if n % 2 else n + 1


def _smooth(x: np.ndarray, window_s: float, fps: float) -> np.ndarray:
    win = _odd(window_s * fps)
    return savgol_filter(x, win, polyorder=min(2, win - 1), mode="interp") if len(x) > win else x


def resample(t_ms: np.ndarray, x: np.ndarray, fps: float, max_gap_ms: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ok = ~np.isnan(x)
    tv, xv = t_ms[ok], x[ok]
    step = 1000.0 / fps
    if len(tv) < 2:
        tg = np.arange(t_ms[0], t_ms[-1] + step, step) if len(t_ms) else np.zeros(0)
        return tg, np.full(len(tg), np.nan), np.zeros(len(tg), bool)
    tg = np.arange(tv[0], tv[-1] + step / 2, step)
    xg = np.interp(tg, tv, xv)
    j = np.clip(np.searchsorted(tv, tg), 1, len(tv) - 1)
    gap = tv[j] - tv[j - 1]
    valid = gap <= max_gap_ms
    return tg, xg, valid


def dominant_tempo(x: np.ndarray, fps: float, min_hz: float, max_hz: float) -> tuple[float, float]:
    """(tempo in Hz, share of the min_hz/2..8 Hz power within -20%/+25% of it); (0, 0) if too short.

    Slower motion than half the slowest tempo is drift, not strokes; counted in, it hid clear tempos.
    """
    n = min(len(x), 256)
    if n < 64:
        return 0.0, 0.0
    f, power = welch(x - x.mean(), fps, nperseg=n)
    search = (f >= min_hz) & (f <= max_hz)
    total = power[(f > min_hz / 2) & (f <= 8.0)].sum()
    if not search.any() or total <= 0:
        return 0.0, 0.0
    f0 = float(f[search][np.argmax(power[search])])
    near = (f > f0 * 0.8) & (f < f0 * 1.25)
    return f0, float(power[near].sum() / total)


def stroke_rate(x: np.ndarray, fps: float) -> float:
    """Strokes per second of the lightly smoothed signal (peaks of at least 30% of its 10..90% range)."""
    xs = savgol_filter(x, 5, 2) if len(x) > 5 else x
    amp = float(np.percentile(xs, 90) - np.percentile(xs, 10))
    if amp <= 0:
        return 0.0
    peaks, _ = find_peaks(xs, prominence=0.3 * amp, distance=max(2, int(fps / 8)))
    return len(peaks) / (len(x) / fps)


def rhythm_filter(x: np.ndarray, p: SignalParams) -> tuple[np.ndarray, float | None]:
    """Band-pass `x` around its dominant tempo if that tempo is clear; returns (signal, tempo or None)."""
    f0, share = dominant_tempo(x, p.fps, p.rhythm_min_hz, p.rhythm_max_hz)
    if share < p.rhythm_min_share:
        return x, None
    if share < p.rhythm_sure_share:
        lo, hi = p.rhythm_rate_tol
        if not lo * f0 <= stroke_rate(x, p.fps) <= hi * f0:
            return x, None
    lo, hi = p.rhythm_band
    sos = butter(2, [f0 * lo, min(f0 * hi, 0.45 * p.fps)], btype="band", fs=p.fps, output="sos")
    return sosfiltfilt(sos, x), f0


def hampel(x: np.ndarray, window: int, n_sigma: float) -> np.ndarray:
    med = median_filter(x, size=window, mode="nearest")
    mad = 1.4826 * median_filter(np.abs(x - med), size=window, mode="nearest")
    outlier = np.abs(x - med) > n_sigma * np.maximum(mad, 1e-9)
    return np.where(outlier, med, x)


def _segments(valid: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index ranges of contiguous True runs."""
    edges = np.diff(np.concatenate([[0], valid.astype(int), [0]]))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def _alternate(x: np.ndarray, peaks: np.ndarray, troughs: np.ndarray) -> list[tuple[int, int]]:
    """(index, +1 peak / -1 trough) in time order; of consecutive same-type extrema only the most extreme."""
    alt: list[tuple[int, int]] = []
    for i, kind in sorted([(i, 1) for i in peaks] + [(i, -1) for i in troughs]):
        if alt and alt[-1][1] == kind:
            if kind * x[i] > kind * x[alt[-1][0]]:
                alt[-1] = (i, kind)
        else:
            alt.append((i, kind))
    return alt


def find_strokes(x: np.ndarray, t_ms: np.ndarray, local_range: np.ndarray, p: SignalParams) -> list[int]:
    """Indices of alternating extrema, with strokes that are too small or too fast pruned away."""
    if len(x) < 3:
        return []
    idx = [i for i, _ in _alternate(x, find_peaks(x)[0], find_peaks(-x)[0])]
    thresh = lambda arr: np.maximum(p.min_prominence * local_range[arr[1:]], p.min_amplitude)  # noqa: E731
    return prune_strokes(idx, x, t_ms, thresh, p.min_interval_ms)


def fall_rise_asymmetry(x: np.ndarray, fps: float, lowpass_hz: float = 6.0, prominence: float = 0.25) -> tuple[float, int]:
    """How much faster `x` rises than it falls: (log of the median peak speed of its rises over its falls,
    number of rises or falls, whichever is fewer). Positive = rises faster; (0, n) below 3 of either.

    Hand-made scripts mostly fall faster than they rise (13 clips: velocity skewed that way in 78 of 94
    scenes): the thrust is the insertion. Turning points need `prominence` of the 10..90% range.
    """
    if len(x) < 2 * fps:
        return 0.0, 0
    xs = sosfiltfilt(butter(2, min(lowpass_hz, 0.45 * fps), fs=fps, output="sos"), x)
    amp = float(np.percentile(xs, 90) - np.percentile(xs, 10))
    if amp <= 0:
        return 0.0, 0
    speed = np.abs(np.gradient(xs))
    ext = _alternate(xs, find_peaks(xs, prominence=prominence * amp)[0], find_peaks(-xs, prominence=prominence * amp)[0])
    falls = [speed[i:j + 1].max() for (i, kind), (j, _) in zip(ext, ext[1:]) if kind > 0]
    rises = [speed[i:j + 1].max() for (i, kind), (j, _) in zip(ext, ext[1:]) if kind < 0]
    n = min(len(falls), len(rises))
    if n < 3:
        return 0.0, n
    return float(np.log(np.median(rises) / np.median(falls))), n


def prune_strokes(idx: list[int], x: np.ndarray, t_ms: np.ndarray, thresh, min_interval_ms: float) -> list[int]:
    """Repeatedly drop the weakest stroke until every stroke is big enough and slow enough.

    `idx` are alternating extrema; `thresh(arr)` gives the minimum size for each stroke arr[k]->arr[k+1].
    """
    idx = list(idx)
    while len(idx) >= 2:
        arr = np.array(idx)
        amp = np.abs(np.diff(x[arr]))
        th = np.maximum(thresh(arr), 1e-12)
        too_fast = np.diff(t_ms[arr]) < min_interval_ms
        weak = (amp < th) | too_fast
        if not weak.any():
            break
        k = int(np.argmin(np.where(weak, amp / th, np.inf)))
        if k == 0:
            del idx[0]  # first stroke: drop the leading extremum only
        elif k == len(idx) - 2:
            del idx[-1]
        else:
            del idx[k : k + 2]  # interior: removing a pair keeps alternation
    return idx


def limit_speed(actions: list[Action], max_speed: float) -> list[Action]:
    out: list[Action] = []
    for a in actions:
        if out:
            prev = out[-1]
            max_delta = max_speed * (a.at - prev.at) / 1000.0
            delta = a.pos - prev.pos
            if abs(delta) > max_delta:
                a = Action(a.at, int(round(prev.pos + np.sign(delta) * max_delta)))
        out.append(a)
    return out


def frequency_scale(freq_hz: float, p: SignalParams) -> float:
    """Stroke length multiplier for a stroke frequency (full cycles per second)."""
    if p.freq_limit_hz <= 0 or freq_hz <= p.freq_limit_hz:
        return 1.0
    if freq_hz >= p.freq_max_hz:
        return p.freq_min_scale
    frac = (freq_hz - p.freq_limit_hz) / (p.freq_max_hz - p.freq_limit_hz)
    return 1.0 - frac * (1.0 - p.freq_min_scale)


def limit_frequency(actions: list[Action], p: SignalParams) -> list[Action]:
    """Shrink fast strokes toward the centre of their original range (see SignalParams.freq_limit_hz).

    An action's frequency comes from its gaps to the neighbouring actions (one gap = half a cycle);
    gaps longer than hold_after_ms are pauses and do not count. The centre is halfway between the
    action and the mean of its neighbours, so a regular 0..100 stroke at half length becomes 25..75.
    """
    if p.freq_limit_hz <= 0 or len(actions) < 2:
        return list(actions)
    out: list[Action] = []
    for k, a in enumerate(actions):
        near = [actions[j] for j in (k - 1, k + 1) if 0 <= j < len(actions)]
        gaps = [abs(a.at - b.at) for b in near if 0 < abs(a.at - b.at) <= p.hold_after_ms]
        if not gaps:
            out.append(a)
            continue
        scale = frequency_scale(1000.0 / (2 * float(np.mean(gaps))), p)
        center = (a.pos + np.mean([b.pos for b in near])) / 2
        out.append(Action(a.at, int(round(center + scale * (a.pos - center)))))
    return out


def insert_holds(actions: list[Action], hold_after_ms: float) -> list[Action]:
    """Across long pauses keep the previous position, then move shortly before the next action.

    A pause that already ends at the same position needs no hold, so running it again adds nothing."""
    out: list[Action] = []
    for a in actions:
        if out and a.at - out[-1].at > hold_after_ms and a.pos != out[-1].pos:
            move_ms = min(hold_after_ms / 2, 500.0)
            out.append(Action(int(a.at - move_ms), out[-1].pos))
        out.append(a)
    return out


def _turns(actions: list[Action]) -> list[tuple[int, int]]:
    """(index, +1 peak / -1 trough) of the actions where the direction changes; a rest (equal positions) counts once,
    at its end; the first and last action count when the direction next to them is known."""
    pos = [a.pos for a in actions]
    moves = [(k + 1, int(np.sign(pos[k + 1] - pos[k]))) for k in range(len(pos) - 1) if pos[k + 1] != pos[k]]
    turns: list[tuple[int, int]] = []
    for (_, d), (j, d_next) in zip(moves, moves[1:]):
        if d != d_next:
            turns.append((j - 1, d))
    if moves:
        first = next(k for k in range(len(pos)) if pos[k] != pos[0]) - 1
        turns = [(first, -moves[0][1])] + turns + [(len(pos) - 1, moves[-1][1])]
    return turns


def bridge_gap(prev: list[Action], nxt: list[Action], p: SignalParams) -> list[Action]:
    """Actions to insert between two scenes' actions (see SignalParams.bridge): none when the next scene's first action
    continues the previous scene's rhythm, else the previous scene's last stroke once more.

    h is the previous scene's half-stroke (median of its last 4); the gap is split into n parts, n odd when the first
    action turns the other way than the last one and even when both are peaks (or troughs), the n closest to gap / h.
    n = 1 needs nothing; otherwise n - 1 points (at most bridge_max) alternate between the previous scene's last two
    turning positions, gap / n apart (h apart when capped); no points when that spacing is off h by more than bridge_tol.
    """
    turns = _turns(prev)
    if len(turns) < 3 or not nxt:
        return []
    last, kind = turns[-1]
    h = float(np.median(np.diff([prev[i].at for i, _ in turns[-5:]])))
    gap = nxt[0].at - prev[-1].at
    if h <= 0 or gap <= 0:
        return []
    first = 1 if (nxt[0].pos - prev[last].pos) * kind < 0 else 2
    n = min(range(first, first + 2 * int(gap / h + 2), 2), key=lambda k: abs(np.log(gap / k / h)))
    m = n - 1 if n - 1 <= p.bridge_max else p.bridge_max - (p.bridge_max - n + 1) % 2  # same parity as n - 1
    if m <= 0:
        return []
    step = gap / n if m == n - 1 else h
    if abs(np.log(step / h)) > np.log(p.bridge_tol) or step < p.min_interval_ms:
        return []
    same, other = prev[last].pos, prev[turns[-2][0]].pos
    return [Action(int(round(prev[-1].at + k * step)), other if k % 2 else same) for k in range(1, m + 1)]


def analyze(t_ms: np.ndarray, signal: np.ndarray, p: SignalParams | None = None) -> ProcessedSignal:
    """Resample, clean and smooth the signal and find its strokes (no positions yet)."""
    p = p or SignalParams()
    tg, xg, valid = resample(t_ms, signal, p.fps, p.max_gap_ms)
    if len(tg) == 0 or not valid.any():
        empty = np.full(len(tg), np.nan)
        return ProcessedSignal(tg, empty, empty, empty, empty, valid, [])

    tempo = None
    banded = np.zeros(len(xg), bool)  # samples of the segments band-passed around their tempo
    if p.rhythm_filter:
        xg = xg.copy()
        for s, e in _segments(valid):
            xg[s:e], f0 = rhythm_filter(xg[s:e], p)
            banded[s:e] = f0 is not None
            tempo = tempo or f0
    clean = hampel(xg, _odd(p.hampel_window_s * p.fps), p.hampel_sigma)
    x = _smooth(clean, p.smooth_window_s, p.fps)
    if banded.any():
        x = np.where(banded, _smooth(clean, p.rhythm_smooth_window_s, p.fps), x)

    nwin = _odd(p.norm_window_s * p.fps)
    lo = percentile_filter(x, p.norm_low_pct, size=nwin, mode="nearest")
    hi = percentile_filter(x, p.norm_high_pct, size=nwin, mode="nearest")
    span = np.maximum(hi - lo, p.min_amplitude)

    strokes: list[int] = []
    for s, e in _segments(valid):
        strokes += [s + i for i in find_strokes(x[s:e], tg[s:e], span[s:e], p)]

    raw = np.where(valid, xg, np.nan)
    smooth = np.where(valid, x, np.nan)
    return ProcessedSignal(tg, raw, smooth, lo, hi, valid, [], strokes, tempo)


def stroke_sizes(sig: ProcessedSignal) -> np.ndarray:
    if len(sig.strokes) < 2:
        return np.zeros(0)
    return np.abs(np.diff(sig.smooth[np.array(sig.strokes)]))


def reference_scale(signals: list[ProcessedSignal], p: SignalParams) -> float | None:
    """Stroke size that counts as a full stroke, shared by all given signals."""
    sizes = np.concatenate([stroke_sizes(s) for s in signals] or [np.zeros(0)])
    sizes = sizes[np.isfinite(sizes)]
    return float(np.percentile(sizes, p.scale_percentile)) if len(sizes) else None


def scene_scale(shared: float | None, sig: ProcessedSignal, p: SignalParams) -> float | None:
    """Full-stroke reference for one scene: `shared` pulled toward the scene's own stroke size."""
    own = reference_scale([sig], p)
    if not shared or not own or p.scene_scale_blend <= 0:
        return shared
    return shared ** (1 - p.scene_scale_blend) * own ** p.scene_scale_blend


def dwell_span(x: np.ndarray, e: int, lo: int, hi: int, tol: float) -> tuple[int, int]:
    """[l, r] around extremum `e` (strictly between `lo` and `hi`) where `x` stays within `tol` of x[e]."""
    l, r = e, e
    while l - 1 > lo and abs(x[l - 1] - x[e]) <= tol:
        l -= 1
    while r + 1 < hi and abs(x[r + 1] - x[e]) <= tol:
        r += 1
    return l, r


def _simplify(t: np.ndarray, y: np.ndarray, tol: float) -> list[int]:
    """Douglas-Peucker on (t, y) with vertical error: indices of the points to keep, ends included."""
    keep = {0, len(y) - 1}
    stack = [(0, len(y) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        line = y[a] + (y[b] - y[a]) * (t[a + 1 : b] - t[a]) / (t[b] - t[a])
        err = np.abs(y[a + 1 : b] - line)
        k = int(np.argmax(err))
        if err[k] > tol:
            m = a + 1 + k
            keep.add(m)
            stack += [(a, m), (m, b)]
    return sorted(keep)


def shape_points(actions: list[Action], ext: list[int], sig: ProcessedSignal, p: SignalParams) -> list[Action]:
    """Add dwell and curve points (see SignalParams.dwell / curve) to one action per extremum `ext`."""
    x, t = sig.smooth, sig.t_ms
    # (signal index, pos, extremum number) for every output point.
    pts: list[tuple[int, int, int]] = []
    for k, (a, e) in enumerate(zip(actions, ext)):
        span = None
        if p.dwell:
            lo = ext[k - 1] if k > 0 else -1
            hi = ext[k + 1] if k + 1 < len(ext) else len(x)
            sizes = [abs(x[j] - x[e]) for j in (lo, hi) if 0 <= j < len(x) and np.isfinite(x[j])]
            if sizes:
                l, r = dwell_span(x, e, lo, hi, p.dwell_tol * min(sizes))
                if t[r] - t[l] >= p.dwell_min_ms:
                    span = (l, r)
        pts += [(l, a.pos, k), (r, a.pos, k)] if span else [(e, a.pos, k)]

    out: list[Action] = []
    for n, (i, pos, k) in enumerate(pts):
        out.append(Action(int(round(t[i])), pos))
        if not p.curve or n + 1 == len(pts):
            continue
        j, pos_b, k_b = pts[n + 1]
        seg = x[i : j + 1]
        if k == k_b or pos == pos_b or t[j] - t[i] <= p.curve_after_ms or not np.isfinite(seg).all():
            continue
        if abs(seg[-1] - seg[0]) < 1e-12:
            continue
        # Map the signal onto the stroke's output range so the ends land on the anchors.
        y = np.clip(pos + (seg - seg[0]) / (seg[-1] - seg[0]) * (pos_b - pos), min(pos, pos_b), max(pos, pos_b))
        last = t[i]
        for m in _simplify(t[i : j + 1], y, p.curve_tol)[1:-1]:
            tm = t[i + m]
            if tm - last >= p.min_interval_ms and t[j] - tm >= p.min_interval_ms:
                out.append(Action(int(round(tm)), int(round(y[m]))))
                last = tm
    return out


def to_actions(sig: ProcessedSignal, p: SignalParams, scale: float | None = None) -> list[Action]:
    if not sig.strokes:
        return []
    idx = np.array(sig.strokes)
    x = sig.smooth
    if p.amplitude == "fill" or not scale:
        span = np.maximum(sig.hi - sig.lo, p.min_amplitude)
        u = np.clip((x[idx] - sig.lo[idx]) / span[idx], 0.0, 1.0)
        keep = list(range(len(idx)))
    else:
        center = (sig.lo + sig.hi) / 2
        if p.scene_center and sig.tempo_hz is None:
            low, high = np.percentile(x[sig.valid], [p.norm_low_pct, p.norm_high_pct])
            center = np.full(len(x), (low + high) / 2)
            scale = max(scale, p.gain * (high - low))
        u = np.clip(0.5 + p.gain * (x[idx] - center[idx]) / scale, 0.0, 1.0)
        # Strokes that end up too short to feel are noise: prune them on the final scale.
        keep = prune_strokes(list(range(len(idx))), u, sig.t_ms[idx], lambda a: p.min_stroke_pos / 100.0, 0.0)

    actions: list[Action] = []
    for k in keep:
        pos = p.pos_low + float(u[k]) * (p.pos_high - p.pos_low)
        actions.append(Action(int(round(sig.t_ms[idx[k]])), int(round(pos))))
    actions = limit_frequency(actions, p)
    if p.dwell or p.curve:
        actions = shape_points(actions, [int(idx[k]) for k in keep], sig, p)
    actions = limit_speed(actions, p.max_speed)
    return insert_holds(actions, p.hold_after_ms) if p.hold else actions


def process(t_ms: np.ndarray, signal: np.ndarray, p: SignalParams | None = None) -> ProcessedSignal:
    """analyze() + to_actions() using this signal alone as the amplitude reference."""
    p = p or SignalParams()
    sig = analyze(t_ms, signal, p)
    sig.actions = to_actions(sig, p, reference_scale([sig], p))
    return sig
