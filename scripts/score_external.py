"""Score funscripts made by another tool the way `validate` scores ours, so `compare-runs` can set them side by side.

Put the other tool's outputs in RUN/CONFIG/CLIP.funscript (one folder per setting of that tool, files named by the
clip codes of validation.toml); this writes RUN/results.json and RUN/run.json. The other tool has no scene list, so
the per-scene scores (direction tally, F1u, ru) use the scenes of our own run SCENES (SCENES/CLIP.debug.json, e.g.
out/runs/NAME/default): both are then turned the right way up over the same shots.

usage: uv run python scripts/score_external.py RUN --scenes out/runs/NAME/default --tool "name commit" \
           [--args CONFIG="its settings" ...]
then:  uv run funscript-gen compare-runs RUN --baseline out/runs/NAME
"""
import argparse
import platform
from datetime import datetime
from pathlib import Path

from funscript_gen.validate import Run, clips, load_manifest, score


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--scenes", type=Path, required=True, help="our run's config folder with CLIP.debug.json")
    ap.add_argument("--tool", required=True, help="what made the outputs, recorded in run.json")
    ap.add_argument("--args", action="append", default=[], help='CONFIG="settings", recorded with its results')
    a = ap.parse_args()
    settings = dict(s.split("=", 1) for s in a.args)
    by_name = {c.name: c for c in clips(load_manifest(), "all")}
    configs = sorted(p.name for p in a.run.iterdir() if p.is_dir() and any(p.glob("*.funscript")))
    run = Run(a.run)
    run.meta = {"name": a.run.name, "host": platform.node(), "tool": a.tool, "scenes_from": str(a.scenes),
                "configs": {c: [settings.get(c, "")] for c in configs},
                "clips": sorted({p.stem for c in configs for p in (a.run / c).glob("*.funscript")} & set(by_name)),
                "finished": datetime.now().isoformat(timespec="seconds")}
    for cfg in configs:
        for out in sorted((a.run / cfg).glob("*.funscript")):
            clip = by_name.get(out.stem)
            if clip is None:
                print(f"skip {cfg}/{out.name}: not a clip of validation.toml")
                continue
            run.record(cfg, [settings.get(cfg, "")], clip.name,
                       score(clip.reference, out, a.scenes / f"{clip.name}.debug.json",
                             clip.name in load_manifest().get("ignore_low_flow", [])))
    print(f"scored {len(configs)} configs: {', '.join(configs)} -> {a.run / 'results.json'}")


if __name__ == "__main__":
    main()
