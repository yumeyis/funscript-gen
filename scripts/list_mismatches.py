"""List the turning points that found no partner for one clip of a validation run (simplified measure of evaluate.py).

  uv run python scripts/list_mismatches.py out/runs/RUN CONFIG CLIP [tol_ms]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from funscript_gen.evaluate import simple_extrema
from funscript_gen.export.funscript import Funscript
from funscript_gen.validate import clips, load_manifest


def fmt(ms: float) -> str:
    return f"{int(ms // 60000)}:{ms % 60000 / 1000:05.2f}"


def main(run: Path, config: str, clip: str, tol: float = 150.0) -> None:
    ref = Funscript.load(clips(load_manifest(), clip)[0].reference)
    pred = Funscript.load(run / config / f"{clip}.funscript")
    rt0, rt1, rk = simple_extrema(ref)
    pt0, pt1, pk = simple_extrema(pred, ratio=0.0, vibration=False)
    rpos = {a.at: a.pos for a in ref.actions}
    ppos = {a.at: a.pos for a in pred.actions}
    used = np.zeros(len(pt0), bool)
    miss = []
    for a, b, k in zip(rt0, rt1, rk):
        gap = np.maximum(0.0, np.maximum(a - pt1, pt0 - b))
        cand = np.flatnonzero(~used & (pk == k) & (gap <= tol))
        if len(cand):
            used[cand[np.argmin(gap[cand])]] = True
        else:
            other = np.flatnonzero(pk != k)
            near = float(np.min(np.maximum(0.0, np.maximum(a - pt1[other], pt0[other] - b)))) if len(other) else np.inf
            miss.append((a, k, rpos[a], near))
    extra = [(t, k, ppos[t]) for t, k, u in zip(pt0, pk, used) if not u]
    print(f"{clip}: reference {len(rt0)}, output {len(pt0)}, matched {int(used.sum())}")
    print(f"missed (reference points without an output one): {len(miss)}")
    for t, k, p, near in miss:
        print(f"  {fmt(t)} {'peak  ' if k > 0 else 'trough'} pos {p:3.0f}  nearest opposite-kind output {near:.0f} ms")
    print(f"extra (output points without a reference one): {len(extra)}")
    for t, k, p in extra:
        print(f"  {fmt(t)} {'peak  ' if k > 0 else 'trough'} pos {p:3.0f}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 150.0)
