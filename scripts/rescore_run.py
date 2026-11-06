"""Score a finished validation run again with the current evaluate.py / validate.score (no generating), into a new
run directory that holds the rescored results.json (and a copy of run.json), so `compare-runs` can compare it.

  uv run python scripts/rescore_run.py out/runs/OLD out/runs/NEW
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from funscript_gen.validate import clips, load_manifest, score


def main(src: Path, dst: Path) -> None:
    manifest = load_manifest()
    by_name = {c.name: c for c in clips(manifest, "all")}
    results = json.loads((src / "results.json").read_text())
    dst.mkdir(parents=True, exist_ok=False)
    for config, entry in results["configs"].items():
        for name, old in entry["clips"].items():
            out = src / config / f"{name}.funscript"
            if "error" in old or name not in by_name or not out.exists():
                continue
            debug = src / config / f"{name}.debug.json"
            new = score(by_name[name].reference, out, debug, name in manifest.get("ignore_low_flow", []))
            entry["clips"][name] = old | new
    (dst / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    if (src / "run.json").exists():
        shutil.copy(src / "run.json", dst / "run.json")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
