"""Offline: how many of the hand-made script's turning points lie in scenes the program leaves still (skip, rest) or
cannot read (no signal)? usage: skipped_share.py RUN [RUN ...] [--groups all]"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from mask_depth import find, turning  # noqa: E402

from funscript_gen.export.funscript import Funscript  # noqa: E402
from funscript_gen.validate import clips, load_manifest  # noqa: E402

runs = [Path(a) for a in sys.argv[1:] if not a.startswith("--")]
tot = {}
for clip in clips(load_manifest(), "all"):
    an = find(runs, clip.name)
    if an is None:
        continue
    acts = Funscript.load(clip.reference).normalized().actions
    at = np.array([a.at for a in acts], float)
    pos = np.array([a.pos for a in acts], float)
    if len(at) < 3:
        continue
    keep = turning(pos)
    at = at[keep]
    cat = {"read": 0, "skip": 0, "rest": 0, "nosignal": 0, "other": 0}
    for p in an.plans:
        n = int(((at >= p.scene.start_ms) & (at < p.scene.end_ms)).sum())
        k = (
            "skip"
            if p.skip
            else "rest"
            if p.rest
            else "nosignal"
            if p.source is None
            else "read"
        )
        cat[k] += n
    for k, v in cat.items():
        tot.setdefault(clip.group, {}).setdefault(k, 0)
        tot[clip.group][k] += v
    s = sum(cat.values())
    if s and (cat["skip"] + cat["rest"] + cat["nosignal"]) / s > 0.1:
        print(
            f"{clip.name:6} {clip.group:9} {s:5} turning points; "
            + ", ".join(f"{k} {v}" for k, v in cat.items() if v)
        )
for g, c in tot.items():
    s = sum(c.values())
    print(f"{g:9} {s:6} " + ", ".join(f"{k} {v / s:.1%}" for k, v in c.items()))
