"""Offline: per scene, the final (after all direction checks) flow position of the AI-region run and the whole-frame
(no-AI) run, their zero-lag correlation with the hand-made script, and whether the two agree on the sign.

Both runs must have saved analyses of the same clips (the scene cuts do not depend on the AI, so scenes match by
index). Each row: the clip, the scene, and per run the correlation `r`, the direction evidence (asymmetry, sound, part
boxes) and which checks flipped it; `agree` is the correlation of the two runs' positions (< 0: opposite signs).

usage: uv run python scripts/two_cues.py out/runs/new-sign default-sign out/runs/noai noai OUT.json
"""
import json
import sys
from pathlib import Path

import numpy as np

from funscript_gen.cli import parse_generate_args
from funscript_gen.export.funscript import Funscript
from funscript_gen.options import build, for_analysis
from funscript_gen.pipeline import load_analysis, render
from funscript_gen.validate import clips, load_manifest


def corr(a, b):
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 10 or a[ok].std() == 0 or b[ok].std() == 0:
        return 0.0
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


def plans_of(run: Path, config: str, clip):
    meta = json.loads((run / "run.json").read_text())
    given, preset = parse_generate_args(meta["configs"][config])
    analysis = load_analysis(run / config / f"{clip.name}.analysis.pkl")
    opts = build(for_analysis(analysis.key, given, preset))
    return {p.scene.index: p for p in render(analysis, opts).plans}


def main():
    ai_run, ai_cfg, ff_run, ff_cfg, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4], sys.argv[5]
    rows = []
    for clip in clips(load_manifest(), "all"):
        ai, ff = plans_of(ai_run, ai_cfg, clip), plans_of(ff_run, ff_cfg, clip)
        ref = Funscript.load(clip.reference)
        rt, rp = [a.at for a in ref.actions], [a.pos for a in ref.actions]
        for k, pa in ai.items():
            pf = ff.get(k)
            assert pf is not None and pf.scene.start_ms == pa.scene.start_ms, (clip.name, k)
            row = {"clip": clip.name, "split": clip.group, "scene": k, "start": pa.scene.start_ms / 1000,
                   "dur": (pa.scene.end_ms - pa.scene.start_ms) / 1000, "continued": pa.scene.continued}
            for tag, p in (("ai", pa), ("ff", pf)):
                fp = p.flow_position if (p.signal is not None and not p.skip) else None
                row[tag] = None
                if fp is None:
                    continue
                t, x = fp
                if p.flipped:
                    x = -x
                y = np.interp(t, rt, rp)
                row[tag] = {"r": corr(x, y), "asym": p.asym, "audio": p.audio_sign, "part": p.part_sign,
                            "part_flipped": p.part_flipped, "asym_flipped": p.asym_flipped,
                            "margin": p.sign_margin, "roi": None if p.roi is None else list(p.roi)}
                row[f"_{tag}"] = (t, x)
            if row["ai"] and row["ff"]:
                (ta, xa), (tf, xf) = row["_ai"], row["_ff"]
                row["agree"] = corr(xa, np.interp(ta, tf, xf))
            row.pop("_ai", None)
            row.pop("_ff", None)
            rows.append(row)
        print(clip.name, len(ai), flush=True)
    Path(out).write_text(json.dumps(rows, indent=0, default=float))


if __name__ == "__main__":
    main()
