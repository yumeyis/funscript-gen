"""Offline: a narrow-peak detector for the stroke rate of flow scenes without a tempo.

The scene's flow spectrum is divided by its local median (+-0.4 Hz, the peak's own +-2 bins left out); the highest
ratio in MIN_HZ..MAX_HZ is the candidate stroke rate. For each threshold: how many scenes it fires on and how often
the candidate is within 15% of the hand-made script's stroke rate (see freq_cues.py), in scenes without a tempo.
usage: uv run python scripts/peak_cue.py OUT_RUN CLIPS
"""

import json
import sys
from pathlib import Path

import numpy as np
from scipy.signal import welch

from freq_cues import MIN_S, zigzag_rate
from funscript_gen.pipeline import load_analysis
from funscript_gen.validate import clips, load_manifest

MIN_HZ, MAX_HZ = 1.2, 6.0


def peak(x: np.ndarray, fps: float = 30.0, half_w_hz: float = 0.4) -> tuple[float, float]:
    f, pw = welch(x - x.mean(), fps, nperseg=min(len(x), 512))
    df = f[1] - f[0]
    w = max(3, int(half_w_hz / df))
    best = (0.0, 0.0)
    for k in np.flatnonzero((f >= MIN_HZ) & (f <= MAX_HZ)):
        nb = np.r_[pw[max(0, k - w):max(0, k - 2)], pw[k + 3:k + w + 1]]
        if len(nb) < 4:
            continue
        r = pw[k] / (np.median(nb) + 1e-12)
        if r > best[1]:
            best = (float(f[k]), float(r))
    return best


def collect(run: str, selection: str):
    rows = []
    for c in clips(load_manifest(), selection):
        pkl = Path(run) / "default" / f"{c.name}.analysis.pkl"
        if not pkl.exists():
            continue
        a = load_analysis(pkl)
        scenes = json.load(open(Path(run) / "default" / f"{c.name}.debug.json"))["scenes"]
        acts = json.load(open(c.reference))["actions"]
        mt = np.array([x["at"] for x in acts]) / 1000.0
        mp = np.array([x["pos"] for x in acts], float)
        for plan, s in zip(a.plans, scenes):
            t0, t1 = s["start_ms"] / 1000, s["end_ms"] / 1000
            if s["mode"] != "flow" or t1 - t0 < MIN_S or plan.flow_position is None:
                continue
            x = np.asarray(plan.flow_position[1], float)
            x = x[~np.isnan(x)]
            ref = zigzag_rate(mt, mp, t0, t1)
            if len(x) < 150 or not ref:
                continue
            f0, r = peak(x)
            rows.append((c.name, t1 - t0, s["tempo_hz"] is None, ref, f0, r))
    return rows


if __name__ == "__main__":
    rows = collect(sys.argv[1], sys.argv[2])
    for label, sel in (("no tempo", True), ("with tempo", False)):
        rs = [r for r in rows if r[2] == sel]
        dur = sum(r[1] for r in rs)
        print(f"== {label}: {len(rs)} scenes {dur:.0f} s")
        for thr in (4, 8, 16, 32, 64):
            fire = [r for r in rs if r[5] >= thr]
            ok = [r for r in fire if abs(r[4] / r[3] - 1) <= 0.15]
            ok2 = [r for r in fire if any(abs(r[4] / r[3] / k - 1) <= 0.15 for k in (0.5, 2.0))]
            tf = sum(r[1] for r in fire)
            print(f"  ratio >= {thr:3d}: fires on {len(fire):3d} scenes ({tf / dur:4.0%} of time); "
                  f"within 15%: {len(ok)} ({len(ok) / max(1, len(fire)):4.0%}); half/double: {len(ok2)}")
