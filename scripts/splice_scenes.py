"""Offline: score a per-scene choice between two runs of the same clips (default and the user's Hybrid settings).

Both runs cut the clips into the same scenes. For each scene a rule picks which run's actions to keep; the spliced
script is scored like a validation run. A rule only sees what both runs know without the hand-made script (a scene's
tempo, mode, direction margin ...). Controls: `base` (all from the first run) and `alt` (all from the second).
usage: uv run python scripts/splice_scenes.py BASE_RUN BASE_CFG ALT_RUN ALT_CFG CLIPS
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

from funscript_gen.export.funscript import Action, Funscript
from funscript_gen.validate import clips, load_manifest, score

RULES = {
    "base": lambda b, a: False,
    "alt": lambda b, a: True,
    "alt_if_base_no_tempo": lambda b, a: b["tempo_hz"] is None,
    "alt_if_base_none_alt_tempo": lambda b, a: b["tempo_hz"] is None and a["tempo_hz"] is not None,
    "mirror_if_base_no_tempo": lambda b, a: "mirror" if b["tempo_hz"] is None else False,
    "mirror_if_base_no_tempo_flow": lambda b, a: "mirror" if b["tempo_hz"] is None and b["mode"] == "flow" else False,
    "alt_if_alt_tempo": lambda b, a: a["tempo_hz"] is not None,
    "alt_if_base_none_alt_tempo_fast": lambda b, a: (b["tempo_hz"] is None and a["tempo_hz"] is not None
                                                     and a["tempo_hz"] >= 1.2),
}


def agreement(base: Funscript, alt: Funscript, t0: float, t1: float) -> float:
    """Correlation of the two scripts' positions inside a scene (50 ms grid); 0 when either has no motion there."""
    t = np.arange(t0, t1, 50.0)
    out = []
    for fs in (base, alt):
        at = np.array([a.at for a in fs.actions], float)
        pos = np.array([a.pos for a in fs.actions], float)
        out.append(np.interp(t, at, pos) if len(at) > 1 else np.zeros(len(t)))
    if len(t) < 8 or out[0].std() < 1e-6 or out[1].std() < 1e-6:
        return 0.0
    return float(np.corrcoef(*out)[0, 1])


def splice(base: Funscript, alt: Funscript, scenes_b: list[dict], scenes_a: list[dict], rule) -> Funscript:
    acts = []
    for sb, sa in zip(scenes_b, scenes_a):
        sb = sb | {"corr": agreement(base, alt, sb["start_ms"], sb["end_ms"])}
        use = rule(sb, sa)
        src = alt if use else base
        part = [a for a in src.actions if sb["start_ms"] <= a.at < sb["end_ms"]]
        if use == "mirror" and sb["corr"] < 0:  # alt's measurement, base's direction
            part = [Action(a.at, 100 - a.pos) for a in part]
        acts += part
    return Funscript(acts, base.inverted, base.range, dict(base.metadata))


def main(base_run, base_cfg, alt_run, alt_cfg, selection):
    manifest = load_manifest()
    ign = manifest.get("ignore_low_flow", [])
    results = {k: {} for k in RULES}
    n_alt = {k: 0 for k in RULES}
    for c in clips(manifest, selection):
        pb, pa = Path(base_run) / base_cfg, Path(alt_run) / alt_cfg
        if not (pb / f"{c.name}.funscript").exists() or not (pa / f"{c.name}.funscript").exists():
            continue
        sb = json.load(open(pb / f"{c.name}.debug.json"))["scenes"]
        sa = json.load(open(pa / f"{c.name}.debug.json"))["scenes"]
        if len(sb) != len(sa) or any(abs(x["start_ms"] - y["start_ms"]) > 1 for x, y in zip(sb, sa)):
            print("scenes differ:", c.name)
            continue
        fb, fa = Funscript.load(pb / f"{c.name}.funscript"), Funscript.load(pa / f"{c.name}.funscript")
        for name, rule in RULES.items():
            fs = splice(fb, fa, sb, sa, rule)
            n_alt[name] += sum(bool(rule(x, y)) and x["mode"] == "flow" for x, y in zip(sb, sa))
            with tempfile.TemporaryDirectory() as d:
                out = Path(d) / "x.funscript"
                fs.save(out) if hasattr(fs, "save") else out.write_text(json.dumps(
                    {"actions": [{"at": a.at, "pos": a.pos} for a in fs.actions]}))
                results[name][c.name] = score(c.reference, out, pb / f"{c.name}.debug.json", c.name in ign)
    for name in RULES:
        r = results[name]
        m = lambda k: np.mean([v[k] for v in r.values()])  # noqa: E731
        print(f"{name:34s} F1 {m('f1'):.3f}  F1u {m('f1_upright'):.3f}  r {m('r100'):.3f}  ru {m('r_upright'):.3f}"
              f"  flow scenes from alt: {n_alt[name]}  ({len(r)} clips)")
    return results


if __name__ == "__main__":
    main(*sys.argv[1:6])
