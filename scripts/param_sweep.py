"""Offline: one-at-a-time sweep of the render-stage parameters (SignalParams fields and generate options) on the saved
analyses of old-base (dev, test) and fresh-base (dev2, holdout2), 2026-11-09. Before, the sweep (2026-11-03) had only the
first 28 clips. A setting is rendered for every clip with the analysis the run saved, written to a temporary file and
scored like `validate` does (F1, F1u = f1_upright, r100, ru = r_upright).

usage: param_sweep.py OUT.json [--groups dev,test,dev2,holdout2] [--only NAME,NAME] [--workers 6]
The table printed hides holdout2 (it is only for confirming a choice made on the others): add --show-holdout.
"""
import argparse
import dataclasses
import json
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

RUNS = [Path("out/runs/old-base"), Path("out/runs/fresh-base")]
# (kind, name, values): "sp" patches SignalParams after construction, "arg" is a generate option
SWEEPS = [
    ("sp", "hampel_window_s", [0.2, 0.45]), ("sp", "hampel_sigma", [2.0, 4.0]), ("sp", "smooth_window_s", [0.1, 0.2]),
    ("sp", "norm_window_s", [3.0, 6.0]), ("sp", "norm_low_pct", [2.0, 10.0]), ("sp", "norm_high_pct", [90.0, 98.0]),
    ("sp", "min_prominence", [0.1, 0.2]), ("sp", "min_amplitude", [0.02, 0.07]),
    ("sp", "min_interval_ms", [40.0, 90.0]), ("sp", "scale_percentile", [80.0, 95.0]),
    ("sp", "min_stroke_pos", [3.0, 10.0]), ("sp", "rhythm_min_share", [0.35, 0.65]),
    ("sp", "rhythm_sure_share", [0.7, 0.9]), ("sp", "rhythm_min_hz", [0.3, 0.8]), ("sp", "rhythm_max_hz", [5.0, 8.0]),
    ("sp", "rhythm_smooth_window_s", [0.15, 0.3]), ("sp", "scene_scale_blend", [0.25, 0.75, 1.0]),
    ("sp", "max_gap_ms", [300.0, 800.0]), ("sp", "rhythm_rate_tol", [(0.8, 1.25), (0.6, 1.6)]),
    ("sp", "rhythm_band", [(0.7, 1.5), (0.4, 3.0)]),
    ("arg", "--asym-threshold", ["0.3", "0.7"]), ("arg", "--asym-audio-threshold", ["0.1", "0.3"]),
    ("arg", "--part-sign-threshold", ["0.1", "0.3"]), ("arg", "--no-chunk-align", [""]), ("arg", "--no-rhythm-filter", [""]),
    ("arg", "--no-asym-sign", [""]), ("arg", "--no-asym-audio", [""]), ("arg", "--range-cap", ["70", "90", "100"]),
    ("arg", "--range-floor", ["10", "30"]), ("arg", "--freq-limit", ["1.5", "2.5"]), ("arg", "--freq-max", ["2.5", "4"]),
    ("arg", "--amplitude", ["fill"]),
]


def _patch(overrides: dict):
    from funscript_gen.signal import process

    if not overrides:
        return None
    orig = process.SignalParams.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        for key, value in overrides.items():
            setattr(self, key, value)

    process.SignalParams.__init__ = init
    return orig


def _one(task):
    name, overrides, args = task
    from funscript_gen.cli import parse_generate_args
    from funscript_gen.options import build, for_analysis
    from funscript_gen.pipeline import render
    from funscript_gen.report import debug_data
    from funscript_gen.signal import process
    from funscript_gen.validate import clips, load_manifest, score
    from mask_depth import find

    manifest = load_manifest()
    clip = clips(manifest, name)[0]
    analysis = find(RUNS, name)
    orig = _patch(overrides)
    try:
        given, preset = parse_generate_args(args)
        result = render(analysis, build(for_analysis(analysis.key, given, preset)))
    finally:
        if orig is not None:
            process.SignalParams.__init__ = orig
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"{name}.funscript"
        result.funscript.save(out)
        dbg = Path(tmp) / f"{name}.debug.json"
        dbg.write_text(json.dumps(debug_data(result)), encoding="utf-8")
        s = score(clip.reference, out, dbg, name in manifest.get("ignore_low_flow", []))
    return name, {k: s.get(k) for k in ("f1", "f1_upright", "r100", "r_upright", "precision", "recall")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--groups", default="dev,test,dev2,holdout2")
    ap.add_argument("--only")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--show-holdout", action="store_true")
    a = ap.parse_args()
    from funscript_gen.validate import clips, load_manifest

    cl = clips(load_manifest(), a.groups)
    group = {c.name: c.group for c in cl}
    names = [c.name for c in cl]
    settings = [("base", None, {}, [])]
    for kind, name, values in SWEEPS:
        if a.only and name not in a.only.split(","):
            continue
        for v in values:
            label = f"{name}={v}"
            settings.append((label, name, {name: v} if kind == "sp" else {}, [name, str(v)] if kind == "arg" and v != "" else
                             [name] if kind == "arg" else []))
    results = {}
    out = Path(a.out)
    if out.exists():
        results = json.loads(out.read_text())
    with Pool(a.workers) as pool:
        for label, _, over, args in settings:
            if label in results:
                continue
            rows = dict(pool.map(_one, [(n, over, args) for n in names]))
            results[label] = rows
            out.write_text(json.dumps(results))
            agg = {}
            for g in a.groups.split(","):
                sel = [rows[n] for n in names if group[n] == g and rows[n]["f1"] is not None]
                agg[g] = [float(np.mean([r[k] for r in sel])) for k in ("f1", "f1_upright", "r100")]
            base = results["base"]
            line = f"{label:34}"
            for g in a.groups.split(","):
                if g == "holdout2" and not a.show_holdout:
                    continue
                b = [float(np.mean([base[n][k] for n in names if group[n] == g])) for k in ("f1", "f1_upright", "r100")]
                d = [agg[g][i] - b[i] for i in range(3)]
                line += f" | {g} F1 {agg[g][0]:.3f} ({d[0]:+.3f}) F1u ({d[1]:+.3f}) r ({d[2]:+.3f})"
            print(line, flush=True)


if __name__ == "__main__":
    main()
