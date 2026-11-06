"""Offline: how far the output's turning points are from the hand-made ones in time, and whether that can be fixed.

Renders the default settings from saved analyses (each clip once) and reports:
  1. stages   For every hand-made turning point (wiggles dropped) in a scene whose output correlates >= MIN_R with the
              hand-made script (direction right): the nearest output turning point of the same kind ("hit" within
              TOL_MS, "late" within TOL_MS..LATE_MS), and where the same-kind extremum lies around it (within half of
              the hand-made half-strokes on either side) in
                raw       the scene's source on the signal grid (no filtering)
                hampel    raw de-spiked and smoothed as analyze() does, without the rhythm filter
                filtered  the signal the strokes are found on (rhythm filter, de-spiked, smoothed)
                output    the output actions (piecewise linear)
              as median |dt| and median dt (+ = the output is late), and the share where the curve does not turn
              within the window ("edge"). Fast: a neighbouring hand-made turning point less than FAST_MS away.
  2. scenes   Unmatched hand-made turning points (all, wiggles included, as `compare` counts them) by the scene's
              correlation with the hand-made script, and by the scene's output stroke count against the hand-made one.
  3. oracle   Upper bounds: every output turning point moved onto the hand-made one of the same kind TOL_MS..LATE_MS
              away ("snap"; also repairs some upside-down fast scenes), each scene / the whole clip shifted by the
              constant that maximizes its F1 (ties to the smallest shift), and the scene shifts' spread.
  4. sound    A shift from the sound: scenes whose onsets fall at a clear phase of the output's stroke cycle (onset
              phase strength > MIN_ONSET) are shifted so that phase becomes PHASE_DEG (as in signal.audio.onset_phase).

usage: uv run python scripts/turn_timing.py RUN [RUN ...]   (runs as for scripts/stroke_size.py)
"""
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import butter, hilbert, savgol_filter, sosfiltfilt

from stroke_size import find  # (scripts/ is on the path when run as a script; importing it lets Windows-saved analyses load)

from funscript_gen.cli import parse_generate_args
from funscript_gen.evaluate import _extrema, compare, drop_wiggles
from funscript_gen.export.funscript import Action, Funscript
from funscript_gen.options import build, for_analysis
from funscript_gen.pipeline import render
from funscript_gen.signal.audio import ENV_FPS
from funscript_gen.signal.process import _odd, dominant_tempo, hampel, resample
from funscript_gen.validate import clips, load_manifest

MIN_R = 0.3
FAST_MS = 250.0
TOL_MS = 150.0
LATE_MS = 400.0
SCENE_SHIFTS = range(-100, 101, 10)
CLIP_SHIFTS = range(-150, 151, 10)
MIN_ONSET = 0.3
PHASE_DEG = (-40.0, -28.0)  # onset_phase's constant, and the hand-made scripts' mean phase in these scenes
STAGES = ["raw", "hampel", "filtered", "output"]


def scene_corr(plan, out_at, out_pos, ref_at, ref_pos) -> float:
    tg = np.arange(plan.scene.start_ms, plan.scene.end_ms, 20.0)
    a, b = np.interp(tg, out_at, out_pos), np.interp(tg, ref_at, ref_pos)
    return float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else 0.0


def stage_rows(clip, res, p, ref) -> list[dict]:
    rt, rk = _extrema(ref)
    ra, rp = np.array([a.at for a in ref.actions], float), np.array([a.pos for a in ref.actions], float)
    oa = np.array([a.at for a in res.funscript.actions], float)
    op = np.array([a.pos for a in res.funscript.actions], float)
    ot, ok_kind = _extrema(res.funscript)
    rows = []
    for plan in res.plans:
        if plan.skip or plan.rest or plan.signal is None or plan.source is None or not plan.signal.actions:
            continue
        if scene_corr(plan, oa, op, ra, rp) < MIN_R:
            continue
        sig, (t, x) = plan.signal, plan.source
        tg, xg, _ = resample(np.asarray(t, float), np.asarray(x, float), p.fps, p.max_gap_ms)
        h = hampel(xg, _odd(p.hampel_window_s * p.fps), p.hampel_sigma)
        win = _odd(p.smooth_window_s * p.fps)
        if len(h) > win:
            h = savgol_filter(h, win, polyorder=min(2, win - 1), mode="interp")
        g = sig.t_ms
        curves = {"raw": np.interp(g, tg, xg), "hampel": np.interp(g, tg, h), "filtered": sig.smooth}
        ok = np.isfinite(sig.smooth) & (g >= plan.scene.start_ms) & (g < plan.scene.end_ms)
        if ok.sum() < 30:
            continue
        out = np.interp(g, oa, op)
        sgn = np.sign(np.corrcoef(out[ok], sig.smooth[ok])[0, 1]) or 1.0  # flips happen after the signal
        curves["output"] = out * sgn
        for i in np.flatnonzero((rt >= plan.scene.start_ms + 100) & (rt < plan.scene.end_ms - 100)):
            if i == 0 or i == len(rt) - 1:
                continue
            before, after = rt[i] - rt[i - 1], rt[i + 1] - rt[i]
            w = (g >= rt[i] - before / 2) & (g <= rt[i] + after / 2) & ok
            if w.sum() < 2:
                continue
            row = {"group": clip.group, "kind": rk[i], "fast": min(before, after) < FAST_MS}
            for name, c in curves.items():
                k = int(np.nanargmax(c[w] * rk[i] * sgn))
                row[name] = g[w][k] - rt[i]
                row[name + "_edge"] = k in (0, w.sum() - 1)
            same = ot[ok_kind == rk[i]]
            row["nearest"] = same[np.argmin(np.abs(same - rt[i]))] - rt[i] if len(same) else np.inf
            rows.append(row)
    return rows


def stage_line(label: str, rows: list[dict]) -> str:
    if not rows:
        return f"{label:16s} n 0"
    near = np.abs([r["nearest"] for r in rows])
    parts = [f"hit {np.mean(near <= TOL_MS):.2f} late {np.mean((near > TOL_MS) & (near <= LATE_MS)):.2f}"]
    for st in STAGES:
        d = np.array([r[st] for r in rows])
        parts.append(f"{st} |{np.median(np.abs(d)):3.0f}| {np.median(d):+4.0f} edge {np.mean([r[st + '_edge'] for r in rows]):.2f}")
    return f"{label:16s} n {len(rows):5d}  " + "  ".join(parts)


def scene_counts(res, ref) -> list[tuple[str, str, int, int, int]]:
    """(correlation class, stroke count class, hand-made turning points, hits, output turning points) per scene."""
    rt, rk = _extrema(ref)
    pt, pk = _extrema(res.funscript)
    rw, _ = _extrema(drop_wiggles(ref))
    ra, rp = np.array([a.at for a in ref.actions], float), np.array([a.pos for a in ref.actions], float)
    oa = np.array([a.at for a in res.funscript.actions], float)
    op = np.array([a.pos for a in res.funscript.actions], float)
    rows = []
    for plan in res.plans:
        s, e = plan.scene.start_ms, plan.scene.end_ms
        sr, so = (rt >= s) & (rt < e), (pt >= s) & (pt < e)
        if not sr.any():
            continue
        hits = sum(np.any((pk == k) & (np.abs(pt - t) <= TOL_MS)) for t, k in zip(rt[sr], rk[sr]))
        if plan.skip or plan.rest or plan.signal is None or not plan.signal.actions:
            rc = "no output"
        else:
            r = scene_corr(plan, oa, op, ra, rp)
            rc = "r >= 0.3" if r >= MIN_R else ("r <= -0.3" if r <= -MIN_R else "|r| < 0.3")
        ratio = so.sum() / max(((rw >= s) & (rw < e)).sum(), 1)
        cc = "out < 0.7x" if ratio < 0.7 else ("out > 1.4x" if ratio > 1.4 else "count ok")
        rows.append((rc, cc, int(sr.sum()), int(hits), int(so.sum())))
    return rows


def shifted(actions: list[Action], ms: int) -> list[Action]:
    return [Action(a.at + ms, a.pos) for a in actions]


def best_shift(ref: Funscript, actions: list[Action], shifts) -> int:
    return max(shifts, key=lambda L: (round(compare(ref, Funscript(actions=shifted(actions, L))).f1, 6), -abs(L)))


def by_scene(res, fn) -> Funscript:
    """The output with each scene's actions replaced by fn(plan, actions) (scenes with < 3 actions kept)."""
    out = []
    for plan in res.plans:
        sel = [a for a in res.funscript.actions if plan.scene.start_ms <= a.at < plan.scene.end_ms]
        out += fn(plan, sel) if len(sel) >= 3 else sel
    return Funscript(actions=sorted(out, key=lambda a: a.at)).normalized()


def oracle(res, ref) -> tuple[dict[str, Funscript], list[tuple[int, int]]]:
    rt, rk = _extrema(ref)
    pt, pk = _extrema(res.funscript)
    kind = dict(zip(pt, pk))
    snap = []
    for a in res.funscript.actions:
        c = rt[(rk == kind.get(a.at, 0)) & (np.abs(rt - a.at) <= LATE_MS)] if a.at in kind else []
        d = c[np.argmin(np.abs(c - a.at))] if len(c) else a.at
        snap.append(Action(int(d) if abs(d - a.at) > TOL_MS else a.at, a.pos))
    shifts: list[tuple[int, int]] = []

    def scene_best(plan, sel):
        part = Funscript(actions=[a for a in ref.actions if plan.scene.start_ms - 500 <= a.at < plan.scene.end_ms + 500])
        if len(part.actions) < 3:
            return sel
        L = best_shift(part, sel, SCENE_SHIFTS)
        shifts.append((L, len(sel)))
        return shifted(sel, L)

    scripts = {"snap": Funscript(actions=sorted(snap, key=lambda a: a.at)).normalized(),
               "scene": by_scene(res, scene_best),
               "clip": Funscript(actions=shifted(res.funscript.actions, best_shift(ref, res.funscript.actions, CLIP_SHIFTS))).normalized()}
    return scripts, shifts


def onset_vector(t: np.ndarray, x: np.ndarray, env_t: np.ndarray, env: np.ndarray) -> tuple[complex, float] | None:
    """onset_phase's onset-weighted mean of the cycle phase (0 = the lows) as a complex number, and the tempo."""
    m = (env_t >= t[0]) & (env_t <= t[-1])
    if m.sum() < 3 * ENV_FPS:
        return None
    xi = np.interp(env_t[m], t, x)
    f0, _ = dominant_tempo(xi, ENV_FPS, 0.5, 6.0)
    w = np.maximum(gaussian_filter1d(env[m], 2), 0)
    if f0 <= 0 or w.sum() <= 0 or xi.std() == 0:
        return None
    sos = butter(2, [0.6 * f0, min(1.6 * f0, 0.45 * ENV_FPS)], btype="band", fs=ENV_FPS, output="sos")
    phase = np.angle(hilbert(sosfiltfilt(sos, xi - xi.mean()))) - np.pi
    return complex(np.sum(w * np.exp(1j * phase)) / w.sum()), f0


def sound_shift(res, envelope, phase_deg: float) -> Funscript:
    def fn(plan, sel):
        if len(sel) < 8:
            return sel
        v = onset_vector(np.array([a.at for a in sel], float), np.array([a.pos for a in sel], float), *envelope)
        if v is None or abs(v[0]) <= MIN_ONSET:
            return sel
        # onsets at phase phi of the output's cycle; moving the output dt later moves them to phi - 2 pi f0 dt
        d = np.angle(v[0] * np.exp(-1j * np.radians(phase_deg)))
        return shifted(sel, int(np.clip(d / (2 * np.pi * v[1]) * 1000, -100, 100)))
    return by_scene(res, fn)


def main(runs: list[Path]) -> None:
    stages, counts, scores, shifts = [], defaultdict(list), defaultdict(list), []
    for clip in clips(load_manifest(), "dev,test"):
        analysis = find(runs, clip.name)
        if analysis is None:
            print(f"{clip.name}: no analysis of the default settings")
            continue
        given, preset = parse_generate_args([])
        opts = build(for_analysis(analysis.key, given, preset))
        res = render(analysis, opts)
        ref = Funscript.load(clip.reference)
        stages += stage_rows(clip, res, opts.signal, drop_wiggles(ref))
        counts[clip.group] += scene_counts(res, ref)
        scripts, sh = oracle(res, ref)
        shifts += sh
        if analysis.envelope is not None:
            for deg in PHASE_DEG:
                scripts[f"sound {deg:.0f}"] = sound_shift(res, analysis.envelope, deg)
        scores[clip.group].append({"base": compare(ref, res.funscript), **{k: compare(ref, s) for k, s in scripts.items()}})

    print(f"1. direction-right scenes: nearest same-kind output turning point; per stage median |dt|, median dt (ms)")
    for group in ("dev", "test"):
        g = [r for r in stages if r["group"] == group]
        print(stage_line(f"[{group}]", g))
        for label, sel in [("fast", lambda r: r["fast"]), ("slow", lambda r: not r["fast"]),
                           ("fast peaks", lambda r: r["fast"] and r["kind"] > 0),
                           ("fast troughs", lambda r: r["fast"] and r["kind"] < 0)]:
            print(stage_line(f"  {label}", [r for r in g if sel(r)]))

    print("\n2. hand-made turning points by scene: share of all, hit rate, missed share of all")
    for group in ("dev", "test"):
        rows = counts[group]
        total = sum(r[2] for r in rows)
        for col in (0, 1):
            agg = defaultdict(lambda: np.zeros(4))
            for r in rows:
                agg[r[col]] += [r[2], r[3], r[4], 1]
            print(f"[{group}] " + "  ".join(f"{k}: scenes {int(v[3])} share {v[0] / total:.2f} hit {v[1] / v[0]:.2f} "
                                          f"missed {(v[0] - v[1]) / total:.3f}" for k, v in sorted(agg.items())))

    print("\n3./4. mean F1 / r (+-100 ms) per group")
    for group in ("dev", "test"):
        s = scores[group]
        print(f"[{group}] {len(s)} clips  " + "  ".join(
            f"{k} {np.mean([x[k].f1 for x in s]):.3f} / {np.mean([x[k].correlation for x in s]):.3f}" for k in s[0]))
    L = np.array([x for x, _ in shifts])
    n = np.array([w for _, w in shifts])
    print(f"scene shifts: {len(L)} scenes, share 0 {np.mean(L == 0):.2f}, mean (by actions) {np.average(L, weights=n):+.0f} ms, "
          f"<= -60 {np.mean(L <= -60):.2f}, >= 60 {np.mean(L >= 60):.2f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main([Path(a) for a in sys.argv[1:]])
