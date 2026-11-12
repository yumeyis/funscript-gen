"""Offline: does any region of the frame carry the strokes of the scenes the rhythm filter finds no tempo in?

For each flow scene without a tempo (8 s or longer, the hand-made script's stroke rate at least MIN_RATE) the
optical flow is computed again and read in many candidate regions (a grid of boxes of several sizes, the whole frame
and the region the run used). A region's quality is the best |correlation| of its first-component position with
the hand-made script, both band-passed around the script's stroke rate (+-5 frames of shift). Reported: the used
region's quality, the best candidate's (an upper bound: it looks at the script) and what rules that do not look at
the script pick (clearest tempo, most periodic, largest motion).
usage: uv run python scripts/experiments/region_oracle.py OUT_RUN CLIPS [--max-scenes N]
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

from freq_cues import MIN_S, zigzag_rate
from funscript_gen.pipeline import load_analysis
from funscript_gen.signal.audio import periodicity
from funscript_gen.signal.process import dominant_tempo
from funscript_gen.tracking.flow import FlowTracker, integrate
from funscript_gen.validate import clips, load_manifest
from funscript_gen.video.decoder import iter_frames

MIN_RATE = 1.2


def boxes() -> list[tuple[float, float, float, float]]:
    out = [(0.0, 0.0, 1.0, 1.0)]
    for size, pos in ((0.4, (0.0, 0.2, 0.4, 0.6)), (0.7, (0.0, 0.15, 0.3))):
        for y in pos:
            for x in pos:
                out.append((x, y, x + size, y + size))
    return out


@dataclass
class Row:
    clip: str
    t0: float
    used: float
    best: float
    picks: dict
    null: float = 0.0


def band_corr(x: np.ndarray, m: np.ndarray, ref: float, signed: bool = False) -> float:
    sos = butter(2, [0.7 * ref, min(1.5 * ref, 13.0)], btype="band", fs=30, output="sos")
    xf, mf = sosfiltfilt(sos, x), sosfiltfilt(sos, m)
    best = 0.0
    for lag in range(-5, 6):
        a = xf[max(0, lag): len(xf) + min(0, lag)]
        b = mf[max(0, -lag): len(mf) + min(0, -lag)]
        if a.std() > 0 and b.std() > 0:
            r = float(np.corrcoef(a, b)[0, 1])
            if abs(r) > abs(best):
                best = r
    return best if signed else abs(best)


def main(run: str, selection: str, max_scenes: int) -> None:
    rows: list[Row] = []
    signs: list = []
    done = 0
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
            if s["mode"] != "flow" or s["tempo_hz"] is not None or t1 - t0 < MIN_S or plan.flow_position is None:
                continue
            ref = zigzag_rate(mt, mp, t0, t1)
            if not ref or ref < MIN_RATE or done >= max_scenes:
                continue
            done += 1
            tr = FlowTracker(None)
            for f in iter_frames(c.video, target_fps=30.0, max_side=640, start_ms=s["start_ms"], end_ms=s["end_ms"]):
                tr.update(f.t_ms, f.image)
            t = np.array(tr.t_ms)
            if len(t) < 150:
                continue
            m = np.interp(t / 1000, mt, mp)
            cand = {}
            for roi in boxes() + ([plan.roi] if plan.roi else []):
                v = tr.component(roi=roi)[0]
                x = integrate(v, fps=30.0)
                cand[roi] = (x, band_corr(x, m, ref))
            ms = np.interp(t / 1000 + 10.0, mt, mp)  # the script 10 s later: what chance gives
            null = max(band_corr(x, ms, ref) for x, _ in cand.values())
            used = cand[plan.roi][1] if plan.roi else float("nan")
            best = max(v[1] for v in cand.values())

            def stat(fn):
                return {roi: fn(x) for roi, (x, _) in cand.items()}

            tempo = stat(lambda x: dominant_tempo(x, 30, 0.5, 6.0)[1])
            period = stat(lambda x: periodicity(x, 30, 0.15, 2.0)[1])
            size = stat(lambda x: float(np.percentile(x, 95) - np.percentile(x, 5)))
            picks = {name: cand[max(d, key=d.get)][1] for name, d in
                     (("tempo_share", tempo), ("periodicity", period), ("motion_size", size))}
            pr = max(tempo, key=tempo.get)
            sgn_pick = band_corr(cand[pr][0], m, ref, signed=True)
            sgn_used = band_corr(cand[plan.roi][0], m, ref, signed=True) if plan.roi else float("nan")
            rows.append(Row(c.name, t0, used, best, picks, null))
            # the picked region aligned to the run's own output for the scene (its signal after every sign decision)
            to, xo = plan.flow_position
            xo = np.interp(t, np.asarray(to), np.asarray(xo, float))
            align = band_corr(cand[pr][0], xo, ref, signed=True)
            signs.append((c.name, sgn_pick, picks["tempo_share"], sgn_used, used, align))
            print(f"{c.name:5s} {t0:5.0f}s ref {ref:.2f} used {used:.2f} best {best:.2f} "
                  + " ".join(f"{k} {v:.2f}" for k, v in picks.items()), flush=True)
    if signs:
        good = [x for x in signs if x[2] >= 0.5]
        neg = sum(x[1] < 0 for x in good)
        print(f"\ntempo-share pick with |r| >= 0.5: {len(good)} scenes, signed r negative in {neg} (the region's own sign)")
        used = [x for x in signs if x[4] == x[4] and x[4] >= 0.5]
        print(f"used region with |r| >= 0.5: {len(used)} scenes, negative in {sum(x[3] < 0 for x in used)}")
        ok = sum((x[5] >= 0) == (x[1] >= 0) for x in good)
        strong = [x for x in good if abs(x[5]) >= 0.5]
        ok_strong = sum((x[5] >= 0) == (x[1] >= 0) for x in strong)
        print(f"aligning to the run's output gives the right sign in {ok}/{len(good)} scenes; "
              f"where |alignment| >= 0.5: {ok_strong}/{len(strong)}")
        for x in good:
            print(f"   {x[0]:5s} picked r {x[1]:+.2f}  alignment to output {x[5]:+.2f}")
    if rows:
        q = lambda f: np.round(np.nanpercentile([f(r) for r in rows], [25, 50, 75]), 2)  # noqa: E731
        print(f"\n{len(rows)} scenes; |r| quartiles 25/50/75")
        print("  used region     ", q(lambda r: r.used))
        print("  best candidate  ", q(lambda r: r.best), " (looks at the script)")
        print("  chance (best vs the script shifted 10 s)", q(lambda r: r.null))
        for k in rows[0].picks:
            print(f"  pick by {k:12s}", q(lambda r, k=k: r.picks[k]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[sys.argv.index("--max-scenes") + 1]) if "--max-scenes" in sys.argv else 999)
