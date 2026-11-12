"""Offline: which signal gives the stroke rate of the scenes the rhythm filter finds no tempo in?

For each flow scene of at least MIN_S seconds, the hand-made script's stroke rate (zigzag of swings >= 30% of its
10..90% range, per second) is compared with candidate cues: the flow signal's own stroke rate, the dominant
frequency of the flow after a 1 Hz high-pass, and the dominant frequency of the sound's onset envelope. A cue "hits"
when it is within 15% of the script's rate; "oct" counts twice or half of it.
usage: uv run python scripts/experiments/freq_cues.py OUT_RUN CLIPS   (e.g. out/runs/fresh-base dev2)
"""

import json
import sys
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt, welch

from funscript_gen.pipeline import load_analysis
from funscript_gen.signal.process import dominant_tempo, stroke_rate
from funscript_gen.validate import clips, load_manifest

MIN_S = 8.0


def zigzag_rate(t_s: np.ndarray, p: np.ndarray, lo_t: float, hi_t: float) -> float | None:
    sel = (t_s >= lo_t) & (t_s <= hi_t)
    if sel.sum() < 8:
        return None
    q = p[sel]
    amp = np.percentile(q, 90) - np.percentile(q, 10)
    if amp < 10:
        return None
    thr = 0.3 * amp
    n, tracking_max, ext = 0, True, q[0]
    for v in q[1:]:
        if tracking_max:
            if v > ext:
                ext = v
            elif ext - v >= thr:
                n, tracking_max, ext = n + 1, False, v
        elif v < ext:
            ext = v
        elif v - ext >= thr:
            n, tracking_max, ext = n + 1, True, v
    return (n / 2) / (hi_t - lo_t)


def env_freq(env, t0, t1):
    et, e = env
    sel = (et >= t0 * 1000) & (et <= t1 * 1000)
    y = e[sel]
    if len(y) < 400:
        return None
    # smooth the 100 fps envelope to ~25 fps, then the dominant 0.7..6 Hz
    y = y[: len(y) // 4 * 4].reshape(-1, 4).mean(axis=1)
    f, pw = welch(y - y.mean(), 25, nperseg=min(len(y), 256))
    s = (f >= 0.7) & (f <= 6)
    return float(f[s][np.argmax(pw[s])]) if s.any() else None


def main(run: str, selection: str) -> None:
    manifest = load_manifest()
    rows = []
    for c in clips(manifest, selection):
        pkl = Path(run) / "default" / f"{c.name}.analysis.pkl"
        dbg = Path(run) / "default" / f"{c.name}.debug.json"
        if not pkl.exists():
            continue
        a = load_analysis(pkl)
        scenes = json.load(open(dbg))["scenes"]
        acts = json.load(open(c.reference))["actions"]
        oacts = json.load(open(Path(run) / "default" / f"{c.name}.funscript"))["actions"]
        ot = np.array([x["at"] for x in oacts]) / 1000.0
        op = np.array([x["pos"] for x in oacts], float)
        mt = np.array([x["at"] for x in acts]) / 1000.0
        mp = np.array([x["pos"] for x in acts], float)
        for plan, s in zip(a.plans, scenes):
            t0, t1 = s["start_ms"] / 1000, s["end_ms"] / 1000
            if s["mode"] != "flow" or t1 - t0 < MIN_S:
                continue
            ref = zigzag_rate(mt, mp, t0, t1)
            if plan.flow_position is None:
                continue
            t, x = plan.flow_position
            t, x = np.asarray(t) / 1000, np.asarray(x, float)
            ok = ~np.isnan(x)
            if not ref or ok.sum() < 150:
                continue
            x = x[ok]
            xh = sosfiltfilt(butter(2, 1.0, btype="high", fs=30, output="sos"), x)
            cues = {"flow_rate": stroke_rate(x, 30), "hp_tempo": dominant_tempo(xh, 30, 1.0, 6.0)[0]}
            if a.envelope is not None:
                cues["audio"] = env_freq(a.envelope, t0, t1)
            f, pw = welch(x - x.mean(), 30, nperseg=min(len(x), 512))
            at = (f >= 0.9 * ref) & (f <= 1.1 * ref)
            around = (f >= 0.5 * ref) & (f <= 2.0 * ref) & ~at
            snr = float(pw[at].max() / (np.median(pw[around]) + 1e-12)) if at.any() and around.any() else 0.0
            cues["snr_at_ref"] = snr
            out_rate = zigzag_rate(ot, op, t0, t1) or 0.0
            rows.append((c.name, t0, t1 - t0, s["tempo_hz"] is None, ref, out_rate, cues))
    if len(sys.argv) > 3:
        for r in rows:
            if r[3]:
                print(f"{r[0]:5s} {r[1]:6.0f}s {r[2]:5.0f}s ref {r[4]:4.2f} out {r[5]:4.2f} " + " ".join(f"{k} {v or 0:4.2f}" for k, v in r[6].items()))
    for label, sel in (("no tempo", lambda r: r[3]), ("with tempo", lambda r: not r[3])):
        rs = [r for r in rows if sel(r)]
        dur = sum(r[2] for r in rs)
        print(f"== {label}: {len(rs)} scenes, {dur:.0f} s")
        for name in ("output", "flow_rate", "hp_tempo", "audio"):
            hit = oct_ = n = 0.0
            for r in rs:
                v = r[5] if name == "output" else r[6].get(name)
                if not v:
                    continue
                n += r[2]
                ratio = v / r[4]
                hit += r[2] * (0.85 <= ratio <= 1.15)
                oct_ += r[2] * (any(abs(ratio / k - 1) <= 0.15 for k in (0.5, 2.0)))
            print(f"  {name:10s} covered {n / dur:4.0%}  within 15%: {hit / dur:4.0%}  at half/double: {oct_ / dur:4.0%}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
