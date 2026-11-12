"""Offline: does a learned optical flow (torchvision RAFT-small) measure the hand-made script's motion better than
Farneback? Per scene of a saved analysis: the correlation (within +-LAG_MS, absolute: the sign is not what is asked)
between the hand-made script and the integrated first-component flow position inside the scene's region, for the
analysis' own Farneback source, a fresh Farneback pass over the same frames and RAFT.

usage: uv run python scripts/experiments/raft_compare.py RUN OUT.json [--clips A01,B02] [--min-points 6] [--max-s 30] [--list]
Needs torch and torchvision (uv sync --extra pose).
"""
import argparse
import json
import pathlib
from pathlib import Path

import cv2
import numpy as np

pathlib.WindowsPath = pathlib.PureWindowsPath

from stroke_size import find  # noqa: E402

from funscript_gen.cli import parse_generate_args  # noqa: E402
from funscript_gen.evaluate import _extrema, drop_wiggles  # noqa: E402
from funscript_gen.export.funscript import Funscript  # noqa: E402
from funscript_gen.options import build, for_analysis  # noqa: E402
from funscript_gen.tracking.flow import FlowTracker, integrate, sample_rate  # noqa: E402
from funscript_gen.validate import clips, load_manifest  # noqa: E402
from funscript_gen.video.decoder import iter_frames  # noqa: E402

LAG_MS = 100
STEP_MS = 33.0


def best_r(t, x, ref_t, ref_p) -> float:
    """Largest |r| over lags -LAG_MS..LAG_MS (ms, steps of 33) between x(t) and the hand-made position."""
    grid = np.arange(t[0] + LAG_MS, t[-1] - LAG_MS, STEP_MS)
    if len(grid) < 10:
        return float("nan")
    best = 0.0
    for lag in range(-LAG_MS, LAG_MS + 1, 33):
        a = np.interp(grid, t, x)
        b = np.interp(grid + lag, ref_t, ref_p)
        if a.std() > 1e-9 and b.std() > 1e-9:
            best = max(best, abs(float(np.corrcoef(a, b)[0, 1])))
    return best


class Raft:
    def __init__(self, small: bool = True) -> None:
        import torch
        from torchvision.models.optical_flow import Raft_Small_Weights, raft_small

        self.torch = torch
        self.model = raft_small(weights=Raft_Small_Weights.DEFAULT).eval()

    def __call__(self, prev: np.ndarray, cur: np.ndarray) -> np.ndarray:
        """Flow (H, W, 2) in pixels of the given grey frames (rounded down to a multiple of 8 and padded back)."""
        torch = self.torch
        h, w = prev.shape
        h8, w8 = h // 8 * 8, w // 8 * 8
        def prep(g):
            g = cv2.resize(g, (w8, h8)) if (h8, w8) != (h, w) else g
            return torch.from_numpy(g).float().div(127.5).sub(1).expand(3, -1, -1).unsqueeze(0).contiguous()
        with torch.no_grad():
            f = self.model(prep(prev), prep(cur))[-1][0].permute(1, 2, 0).numpy()
        if (h8, w8) != (h, w):
            f = cv2.resize(f, (w, h)) * np.array([w / w8, h / h8], np.float32)
        return f


class RaftTracker(FlowTracker):
    def __init__(self, raft: Raft, **kw) -> None:
        super().__init__(None, **kw)
        self.raft = raft

    def _field(self, prev, gray):
        return self._pool(self.raft(prev, gray))


def scene_position(flow: FlowTracker, plan, fps: float):
    roi = plan.roi
    v = flow.component(plan.direction, roi=roi)[0]
    t = np.array(flow.t_ms)
    return t, integrate(v, fps=fps)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("out")
    ap.add_argument("--clips", default="dev,test")
    ap.add_argument("--min-points", type=int, default=6)
    ap.add_argument("--max-s", type=float, default=30.0)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--max-r", type=float, default=9.0, help="only scenes whose saved Farneback source has |r| below")
    ap.add_argument("--every", type=int, default=1, help="use every Nth qualifying scene")
    a = ap.parse_args()
    raft = None if a.list else Raft()
    given, preset = parse_generate_args([])
    results = []
    total = 0.0
    seen = 0
    for clip in clips(load_manifest(), a.clips):
        an = find([Path(a.run)], clip.name)
        if an is None:
            continue
        opts = build(for_analysis(an.key, given, preset))
        ref = drop_wiggles(Funscript.load(clip.reference).normalized())
        rt, _ = _extrema(ref)
        ra = np.array([x.at for x in ref.actions], float)
        rp = np.array([x.pos for x in ref.actions], float)
        for k, plan in enumerate(an.plans):
            s, e = plan.scene.start_ms, plan.scene.end_ms
            n = int(((rt >= s) & (rt < e)).sum())
            if plan.skip or plan.rest or plan.source is None or plan.mode != "flow" or n < a.min_points:
                continue
            if (e - s) / 1000 > a.max_s:
                continue
            t0, x0 = plan.source
            r_saved = best_r(t0, x0, ra, rp)
            if not r_saved < a.max_r:
                continue
            seen += 1
            if seen % a.every:
                continue
            total += (e - s) / 1000
            if a.list:
                print(f"{clip.name} #{k} {(e - s) / 1000:.1f}s points {n}")
                continue
            lo = an.plans[k - 1].scene.end_ms if k else 0.0
            frames = []
            for f in iter_frames(clip.video, target_fps=opts.fps, max_side=opts.max_side, start_ms=lo):
                if f.t_ms >= e and k + 1 < len(an.plans):
                    break
                frames.append(f)
            fb = FlowTracker(None, flow_width=opts.flow_width)
            rf = RaftTracker(raft, flow_width=opts.flow_width)
            for f in frames:
                fb.update(f.t_ms, f.image)
                rf.update(f.t_ms, f.image)
            fps = sample_rate(np.array(fb.t_ms), opts.fps)
            row = dict(clip=clip.name, scene=k, dur=(e - s) / 1000, points=n, hybrid=bool(plan.decisions))
            row["r_saved"] = r_saved
            for name, tr in (("fb", fb), ("raft", rf)):
                t, x = scene_position(tr, plan, fps)
                mm = (t >= s) & (t < e)
                row["r_" + name] = best_r(t[mm], x[mm], ra, rp)
            results.append(row)
            print(json.dumps(row), flush=True)
            json.dump(results, open(a.out, "w"))
    print(f"scenes' total seconds: {total:.0f}")


if __name__ == "__main__":
    main()
