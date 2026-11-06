"""Offline: find the turning points of scenes without a clear tempo on the slow motion plus an amplified fast
part, so small strokes riding on a slow stroke (K01, A06 20-30 s, B04 40-80 s) reverse.

Reads each scene's resampled flow position (debug.json "raw"; without a rhythm filter it is unfiltered) and
replaces the output's actions inside every flow scene without a tempo. The positions map the scene's 5..95%
range onto its own output range ("--local": around the 4 s centre like to_actions), oriented by the correlation
with the existing output (never with the manual script). Gain 1 is the control: the same rebuild, no amplifying.
usage: uv run python scripts/small_strokes.py OUT_OLD13 OUT_NEW12 [--local]   (outputs need --debug)
"""

import glob
import json
import sys
from dataclasses import replace

import numpy as np
from scipy.ndimage import percentile_filter
from scipy.signal import butter, savgol_filter, sosfiltfilt

from funscript_gen.evaluate import compare, drop_wiggles
from funscript_gen.export.funscript import Action, Funscript
from funscript_gen.signal.process import SignalParams, _odd, find_strokes, hampel
from funscript_gen.tracking.flow import MIN_AMPLITUDE_PX

OLD = ["B01", "C01", "D01", "A01", "A02", "A03", "A04", "E01",
       "B02", "B03", "F01", "E02", "D02"]
NEW = ["B04", "H01", "H02", "I01", "G01", "J01", "A05", "A06", "A07", "K01", "D03", "L01"]
P = replace(SignalParams(), min_amplitude=MIN_AMPLITUDE_PX)
FPS = P.fps
SPLIT_HZ = 0.6  # slow part below, fast part above
GAINS = (1.0, 1.5, 2.0, 3.0)


def composite(x, gain):
    slow = sosfiltfilt(butter(2, SPLIT_HZ, btype="low", fs=FPS, output="sos"), x)
    return slow + gain * (x - slow)


def scene_actions(t, x, lo_pos, hi_pos, local):
    x = hampel(x, _odd(P.hampel_window_s * FPS), P.hampel_sigma)
    win = _odd(P.smooth_window_s * FPS)
    if len(x) > win:
        x = savgol_filter(x, win, polyorder=2, mode="interp")
    nwin = _odd(P.norm_window_s * FPS)
    hi = percentile_filter(x, 95, size=nwin, mode="nearest")
    lo = percentile_filter(x, 5, size=nwin, mode="nearest")
    idx = find_strokes(x, t, np.maximum(hi - lo, P.min_amplitude), P)
    if len(idx) < 2:
        return []
    if local:  # around the 4 s centre, the scene's 90th-percentile stroke as a full stroke
        size = np.percentile(np.abs(np.diff(x[idx])), 90)
        u = np.clip(0.5 + (x[idx] - (lo + hi)[idx] / 2) / max(size, 1e-9), 0, 1)
    else:
        p5, p95 = np.percentile(x, 5), np.percentile(x, 95)
        u = np.clip((x[idx] - p5) / max(p95 - p5, 1e-9), 0, 1)
    return [Action(int(round(t[i])), int(round(lo_pos + v * (hi_pos - lo_pos)))) for i, v in zip(idx, u)]


def rebuild(pred, scenes, gain, local):
    acts = list(pred.actions)
    changed = 0
    for sc in scenes:
        if sc["tempo_hz"] or sc["rest"] or sc["skip"] or sc["mode"] != "flow" or not sc["raw"]:
            continue
        t = np.array(sc["t_ms"], float)
        raw = np.array([np.nan if v is None else v for v in sc["raw"]], float)
        ok = ~np.isnan(raw)
        if ok.mean() < 0.9 or len(t) < 4 * FPS:
            continue
        x = np.interp(t, t[ok], raw[ok])
        s, e = sc["start_ms"], sc["end_ms"]
        at = np.array([a.at for a in acts])
        pos = np.array([a.pos for a in acts])
        inside = (at >= s) & (at < e)
        if inside.sum() < 2:
            continue
        r = np.corrcoef(np.interp(t, at, pos), x)[0, 1]  # the output's orientation of the flow
        if not np.isfinite(r):
            continue
        new = scene_actions(t, composite(np.sign(r) * x, gain), pos[inside].min(), pos[inside].max(), local)
        if len(new) < 2:
            continue
        acts = sorted([a for a in acts if not s <= a.at < e] + new, key=lambda a: a.at)
        changed += 1
    return acts, changed


def score(ref, acts):
    fs = Funscript(actions=acts).normalized()
    sc = compare(ref, fs)
    return sc.f1, sc.correlation_wide, compare(drop_wiggles(ref), fs).f1  # +-500 ms, as recorded in docs/archive/PLAN-archive.md


def main():
    out_old, out_new = sys.argv[1], sys.argv[2]
    local = "--local" in sys.argv[3:]
    names = ["orig"] + [f"g{g}" for g in GAINS]
    tot = {n: {"old": [], "new": []} for n in names}
    print(f"{'clip':8}" + "".join(f"{n:>19}" for n in names))
    for group, out, clips in (("old", out_old, OLD), ("new", out_new, NEW)):
        for clip in clips:
            ref = Funscript.load(glob.glob(f"vaild/{clip}-*.funscript")[0])
            pred = Funscript.load(f"{out}/{clip}.funscript")
            scenes = json.load(open(f"{out}/{clip}.debug.json"))["scenes"]
            cells = []
            for name, gain in zip(names, (None,) + GAINS):
                acts, n = (pred.actions, 0) if gain is None else rebuild(pred, scenes, gain, local)
                s = score(ref, acts)
                tot[name][group].append(s)
                cells.append(f"{s[0]:.2f}/{s[1]:.2f}/{s[2]:.2f}({n})".rjust(19))
            print(f"{clip:8}" + "".join(cells))
    for group in ("old", "new"):
        print(f"{group:8}" + "".join(f"{'/'.join(f'{v:.3f}' for v in np.mean(tot[n][group], axis=0)):>19}"
                                     for n in names))


if __name__ == "__main__":
    main()
