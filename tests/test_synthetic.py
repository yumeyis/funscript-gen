"""End-to-end regression on a synthetic clip the optical flow can follow, with its exact answer.

A textured patch moves up and down over a textured background: 1.2 Hz, then faster and smaller, a still stretch, and a
hard cut to another background with another tempo. The answer key is the patch's height, up = high. It replaces the old
stick-figure clip (scripts/make_synthetic.py), which only the skeleton mode could follow.
"""

import cv2
import numpy as np

from funscript_gen.evaluate import compare
from funscript_gen.export.funscript import Action, Funscript
from funscript_gen.pipeline import PipelineOptions, generate, render

# (start s, end s, Hz, amplitude px); 0 Hz = still
SEGMENTS = [(0, 5, 1.2, 30), (5, 9, 2.0, 18), (9, 11, 0.0, 0), (11, 15, 1.5, 24)]
CUT_S = 11.0
FPS, W, H, SIDE = 30, 240, 180, 56
A_MAX = max(a for *_, a in SEGMENTS)


def _offset(t: float) -> float:
    for s, e, f, a in SEGMENTS:
        if s <= t < e:
            return a * np.sin(2 * np.pi * f * (t - s)) if f else 0.0
    return 0.0


def synthetic_clip(path) -> Funscript:
    """Write the clip to `path`; returns its answer key (turning points, sized like the motion)."""
    rng = np.random.default_rng(3)
    backs = [cv2.GaussianBlur(rng.integers(lo, lo + 90, (H, W, 3), dtype=np.uint8), (5, 5), 0) for lo in (30, 150)]
    patch = cv2.GaussianBlur(rng.integers(0, 255, (SIDE, SIDE, 3), dtype=np.uint8), (3, 3), 0)
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for i in range(int(SEGMENTS[-1][1] * FPS)):
        t = i / FPS
        img = backs[int(t >= CUT_S)].copy()
        y = int(round(H / 2 - SIDE / 2 - _offset(t)))
        x = W // 2 - SIDE // 2
        img[y:y + SIDE, x:x + SIDE] = patch
        w.write(img)
    w.release()
    actions = []
    for s, e, f, a in SEGMENTS:
        if not f:
            actions += [Action(int(s * 1000), 50), Action(int(e * 1000) - 1, 50)]
            continue
        k = 0
        while (t := s + (0.25 + 0.5 * k) / f) < e:  # the sine's extrema
            actions.append(Action(int(round(t * 1000)), int(round(50 + 50 * a / A_MAX * (1 if k % 2 == 0 else -1)))))
            k += 1
    return Funscript(actions)


def test_the_flow_pipeline_follows_the_synthetic_clip(tmp_path):
    truth = synthetic_clip(tmp_path / "syn.mp4")
    opts = PipelineOptions(use_ai=False, flow_workers=2)
    result = generate(tmp_path / "syn.mp4", opts)
    assert [round(p.scene.start_ms / 1000, 1) for p in result.plans] == [0.0, CUT_S]  # the hard cut
    s = compare(truth, result.funscript)
    assert s.f1 >= 0.9 and s.correlation >= 0.85, s  # 2026-10-31: F1 0.952, r 0.906

    opts.invert = True  # upside down: the correlation says so (the old +-500 ms one did not: +0.71)
    s = compare(truth, render(result.analysis, opts).funscript)
    assert s.f1 < 0.2 and s.correlation < 0
