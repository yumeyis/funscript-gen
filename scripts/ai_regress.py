"""Ask the AI again for the scenes of a finished validation run and report how often its answers match the saved ones.

For a new model, a changed prompt or schema: the answers of the run's analyses (`<clip>.analysis.pkl`) are the
reference, the key frames are cut again from the videos (same scene cut, so the same frames), and every field of the
scene analysis and of the stroke range analysis is compared. A model that agrees on most fields is worth a full
validation; one that does not is not. Run it with the same model first (expect 100%: the answers come from the cache,
so this also checks the cache and the scene cut). The key frames only exist in memory; nothing about the videos is
written.

  uv run python scripts/ai_regress.py out/runs/full-1112 --clips dev2 --model Qwen/Qwen3-VL-30B-A3B-Instruct
  uv run python scripts/ai_regress.py out/runs/full-1112 --clips A01,A02 --limit 20

Fields: people_count, has_interaction, motion, motion_axis, ref_a, ref_b, focus_roi (both missing, or boxes with an
IoU of at least 0.5), apparent_minor, penis_visible, penis_complete, glans_visible. The `confidence` numbers are left
out. Scenes the AI failed on, in either answer, are counted separately.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from funscript_gen.config import Settings
from funscript_gen.pipeline import HybridAnalysis, _analyze_scenes, _detect_ranges, load_analysis
from funscript_gen.validate import clips, load_manifest
from funscript_gen.video.scenes import detect_scenes

SCENE_FIELDS = ("people_count", "has_interaction", "motion", "motion_axis", "ref_a", "ref_b")
RANGE_FIELDS = ("apparent_minor", "penis_visible", "penis_complete", "glans_visible")
IOU_MIN = 0.5


def iou(a, b) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / union if union > 0 else 0.0


def same_box(a, b) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and iou(a, b) >= IOU_MIN)


def compare(old, new, fields) -> dict[str, bool]:
    return {f: getattr(old, f) == getattr(new, f) for f in fields}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path, help="validation run directory (out/runs/NAME)")
    ap.add_argument("--config", default="default", help="the config of the run whose analyses are the reference")
    ap.add_argument("--clips", default="dev2", help="groups or clip names, comma-separated (see validation.toml)")
    ap.add_argument("--model", default="", help="model to ask (default: VLLM_MODEL of .env, the one that made the run)")
    ap.add_argument("--workers", type=int, default=0, help="requests at the same time (default: VLLM_CONCURRENCY)")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many scenes (0: all)")
    args = ap.parse_args()

    settings = Settings()
    if args.model:
        settings.vllm_model = args.model
    workers = args.workers or settings.vllm_concurrency
    manifest = load_manifest()
    agree: dict[str, list[bool]] = defaultdict(list)
    failed = scenes_done = 0
    for clip in clips(manifest, args.clips):
        pkl = args.run / args.config / f"{clip.name}.analysis.pkl"
        if not pkl.exists():
            print(f"{clip.name}: no analysis in {pkl.parent}", file=sys.stderr)
            continue
        analysis = load_analysis(pkl)
        found = {round(p.scene.start_ms): p for p in analysis.plans}
        threshold = analysis.key.get("scene_threshold", 30.0)
        scenes = [s for s in detect_scenes(analysis.video, threshold=threshold) if round(s.start_ms) in found
                  and getattr(found[round(s.start_ms)].analysis, "general", found[round(s.start_ms)].analysis) is not None]
        if args.limit:
            scenes = scenes[: max(0, args.limit - scenes_done)]
        if not scenes:
            continue
        old = [found[round(s.start_ms)] for s in scenes]
        new_scene = _analyze_scenes(scenes, workers, "general", settings)
        new_range = _detect_ranges(scenes, workers, settings)
        for plan, (answer, error), (rng, rng_error) in zip(old, new_scene, new_range):
            ref = plan.analysis.general if isinstance(plan.analysis, HybridAnalysis) else plan.analysis
            if answer is None or error or ref is None:
                failed += 1
                continue
            for f, ok in compare(ref, answer, SCENE_FIELDS).items():
                agree[f].append(ok)
            agree["focus_roi"].append(same_box(ref.focus_roi, answer.focus_roi))
            if rng is not None and plan.range_analysis is not None:
                for f, ok in compare(plan.range_analysis, rng, RANGE_FIELDS).items():
                    agree[f].append(ok)
        scenes_done += len(scenes)
        print(f"{clip.name}: {len(scenes)} scenes", flush=True)
        if args.limit and scenes_done >= args.limit:
            break

    print(f"\nmodel: {settings.vllm_model}   scenes asked: {scenes_done}   without an answer: {failed}")
    for f in (*SCENE_FIELDS, "focus_roi", *RANGE_FIELDS):
        v = agree.get(f, [])
        print(f"  {f:16} {sum(v):4}/{len(v):<4} {100 * sum(v) / len(v):5.1f}%" if v else f"  {f:16} -")
    every = [x for v in agree.values() for x in v]
    if every:
        print(f"  all fields       {100 * sum(every) / len(every):5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
