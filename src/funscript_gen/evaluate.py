"""Compare a generated funscript with a reference one."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from funscript_gen.export.funscript import Action, Funscript

# Hand-made scripts often draw small wiggles (a few units, faster than 6 Hz) on top of the strokes; every one
# counts as a turning point. Scores "ignoring wiggles" first drop turning points closer than this to the last kept one.
WIGGLE = 10.0
# The correlation takes the best shift of the output within +-LAG_MS. Until 2026-10-31 it was +-500 ms, within which an
# upside-down periodic script shifted by half a stroke correlates again (1.5 Hz: F1 0, correlation 0.96; I01, upside
# down: 0.21, within +-100 ms -0.06). +-100 ms still covers the hand-made scripts' own timing (C01's best shift is
# +100 ms; zero lag gave it 0.28 instead of 0.87). The +-500 ms value stays as `correlation_wide` for the older records.
LAG_MS = 100.0
# Simplified turning points (the default of `compare`): a hold counts once (one turning point spanning the whole
# hold), and a reversal that is under SIMPLIFY_RATIO times the smaller of its two neighbouring swings (e.g. 16 -> 11
# -> 30 on the way up) is not a turning point: the hand-made script only changes speed there. The reference is
# simplified fully, the output only in its holds; `compare(..., simplify=False)` keeps the older all-points measure.
SIMPLIFY_RATIO = 0.3
# A run of at least three turning points with swings of at most VIBRATION_SWING units less than VIBRATION_MS apart
# (a 5-6 Hz tremble the author added on top of a pause; nothing in the picture shows it) is one hold of the reference:
# only its first and last point stay, and they merge when they are of the same kind. A run stays within
# 2 * VIBRATION_SWING units (slow drifts made of small steps are strokes).
VIBRATION_SWING = 10.0
VIBRATION_MS = 200.0
WIDE_LAG_MS = 500.0


@dataclass
class Score:
    precision: float
    recall: float
    f1: float
    correlation: float  # Pearson r of both scripts at 50 Hz, best shift of `pred` within +-max_lag_ms
    best_lag_ms: float  # that shift (positive = pred is late)
    correlation_wide: float = float("nan")  # the same within +-500 ms: the measure recorded before 2026-10-31


def _extrema_idx(pos: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Indexes of the local maxima and minima among the positions, and their kind (+1 peak / -1 trough). Both ends of a
    hold (equal positions) are turning points of the same kind."""
    n = len(pos)
    if n < 3:
        return np.arange(n), np.zeros(n)
    d_prev = np.sign(pos[1:-1] - pos[:-2])
    d_next = np.sign(pos[2:] - pos[1:-1])
    turn = np.concatenate([[True], d_prev != d_next, [True]])
    kind = np.zeros(n)
    # The end of a hold (flat, then moving) is the extremum the flat part sits at: before a fall it is a peak.
    kind[1:-1] = np.where(d_prev != 0, d_prev, -d_next)
    kind[0], kind[-1] = -np.sign(pos[1] - pos[0]), np.sign(pos[-1] - pos[-2])
    return np.flatnonzero(turn), kind[turn]


def _extrema(fs: Funscript) -> tuple[np.ndarray, np.ndarray]:
    """Times of local maxima and minima among the actions."""
    at = np.array([a.at for a in fs.actions], dtype=float)
    pos = np.array([a.pos for a in fs.actions], dtype=float)
    idx, kind = _extrema_idx(pos)
    return at[idx], kind


def simple_extrema(fs: Funscript, ratio: float = SIMPLIFY_RATIO,
                   vibration: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(start times, end times, kinds) of the simplified turning points (see SIMPLIFY_RATIO): a hold is one point
    spanning its start to its end; small reversals inside a larger stroke and tremble runs (`vibration`) are removed."""
    at = np.array([a.at for a in fs.actions], dtype=float)
    pos = np.array([a.pos for a in fs.actions], dtype=float)
    idx, kind = _extrema_idx(pos)
    t0: list[float] = []
    t1: list[float] = []
    k: list = []
    v: list[float] = []
    for i, kd in zip(idx, kind):
        if k and k[-1] == kd and v[-1] == pos[i]:  # the other end of the hold
            t1[-1] = at[i]
        else:
            t0.append(at[i])
            t1.append(at[i])
            k.append(kd)
            v.append(pos[i])
    i = 0
    while vibration and i < len(v) - 2:
        j = i
        while (j + 1 < len(v) and abs(v[j + 1] - v[j]) <= VIBRATION_SWING and t0[j + 1] - t1[j] <= VIBRATION_MS
               and max(v[i:j + 2]) - min(v[i:j + 2]) <= 2 * VIBRATION_SWING):  # not a staircase of small steps
            j += 1
        if j - i >= 2:
            if k[i] == k[j]:
                t1[i] = t1[j]
                end = j + 1
            else:
                end = j
            for lst in (t0, t1, k, v):
                del lst[i + 1:end]
        i += 1
    while len(v) >= 4:  # a swing between two swings that are both larger; the first and the last stay
        swing = np.abs(np.diff(v))
        inner = swing[1:-1] / np.maximum(np.minimum(swing[:-2], swing[2:]), 1e-9)
        j = int(np.argmin(inner))
        if inner[j] >= ratio:
            break
        for lst in (t0, t1, k, v):
            del lst[j + 1:j + 3]
    return np.array(t0), np.array(t1), np.array(k)


def drop_wiggles(fs: Funscript, min_stroke: float = WIGGLE) -> Funscript:
    """Keep only the turning points at least `min_stroke` away from the previous kept one (zig-zag filter)."""
    acts = fs.actions
    if min_stroke <= 0 or len(acts) < 3:
        return fs
    keep = [acts[0]]
    ext: Action | None = None
    up: bool | None = None
    for a in acts[1:]:
        if up is None:
            if abs(a.pos - keep[-1].pos) >= min_stroke:
                up, ext = a.pos > keep[-1].pos, a
        elif ext is not None and ((a.pos >= ext.pos) if up else (a.pos <= ext.pos)):
            ext = a
        elif ext is not None and abs(a.pos - ext.pos) >= min_stroke:
            keep.append(ext)
            up, ext = not up, a
    if ext is not None:
        keep.append(ext)
    return Funscript(keep, fs.inverted, fs.range, dict(fs.metadata))


def _match(ref_t, ref_k, pred_t, pred_k, tol_ms: float, ref_end=None, pred_end=None) -> int:
    """Hits: each reference turning point takes the nearest unused output one of the same kind within tol_ms. With
    `*_end` the points are spans (start..end), and the distance between two is the gap between them (0 if they overlap)."""
    ref_end = ref_t if ref_end is None else ref_end
    pred_end = pred_t if pred_end is None else pred_end
    used = np.zeros(len(pred_t), bool)
    hits = 0
    for t0, t1, k in zip(ref_t, ref_end, ref_k):
        gap = np.maximum(0.0, np.maximum(t0 - pred_end, pred_t - t1))
        cand = np.flatnonzero(~used & (pred_k == k) & (gap <= tol_ms))
        if len(cand):
            used[cand[np.argmin(gap[cand])]] = True
            hits += 1
    return hits


def _outside(t0, t1, k, ignore):
    """The turning points (spans t0..t1) whose start is not inside one of the `ignore` spans (start, end)."""
    keep = np.ones(len(t0), bool)
    for a, b in ignore:
        keep &= ~((t0 >= a) & (t0 < b))
    return t0[keep], t1[keep], k[keep]


def compare(ref: Funscript, pred: Funscript, tol_ms: float = 150.0, max_lag_ms: float = LAG_MS,
            simplify: bool = True, ignore: list[tuple[float, float]] | None = None) -> Score:
    """Precision, recall and F1 of the turning points (simplified, see SIMPLIFY_RATIO; the hand-made script's, the
    output's holds only), and the correlation of the whole scripts."""
    if simplify:
        rt, re, rk = simple_extrema(ref)
        pt, pe, pk = simple_extrema(pred, ratio=0.0, vibration=False)  # the output's own reversals stay: only its holds are merged
        if ignore:  # stretches nobody can judge from the picture: neither script's points count there
            rt, re, rk = _outside(rt, re, rk, ignore)
            pt, pe, pk = _outside(pt, pe, pk, ignore)
        hits = _match(rt, rk, pt, pk, tol_ms, re, pe)
    else:
        rt, rk = _extrema(ref)
        pt, pk = _extrema(pred)
        hits = _match(rt, rk, pt, pk, tol_ms)
    precision = hits / len(pt) if len(pt) else 0.0
    recall = hits / len(rt) if len(rt) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if hits else 0.0

    best, wide = (float("nan"), 0.0), float("nan")
    if len(ref.actions) >= 2 and len(pred.actions) >= 2:
        start = max(ref.actions[0].at, pred.actions[0].at)
        end = min(ref.actions[-1].at, pred.actions[-1].at)
        grid = np.arange(start, end, 20.0)
        if len(grid) > 10:
            r = np.interp(grid, [a.at for a in ref.actions], [a.pos for a in ref.actions])
            reach = max(max_lag_ms, WIDE_LAG_MS)
            near, wide = (-2.0, 0.0), -2.0
            for shift in np.arange(-reach, reach + 1, 20.0):
                p = np.interp(grid + shift, [a.at for a in pred.actions], [a.pos for a in pred.actions])
                if r.std() > 0 and p.std() > 0:
                    c = float(np.corrcoef(r, p)[0, 1])
                    if abs(shift) <= WIDE_LAG_MS:
                        wide = max(wide, c)
                    if abs(shift) <= max_lag_ms and c > near[0]:
                        near = (c, float(shift))
            if near[0] > -2.0:
                best = near
            wide = wide if wide > -2.0 else float("nan")
    return Score(precision, recall, f1, best[0], best[1], wide)
