"""Offline: render a run's saved analyses (default config) with variants of the asymmetry check's threshold, swapped
into pipeline.flip_by_asymmetry, and score them as validate does (F1, r per group; which clips' flips changed).

2026-11-05: chose the sound veto (asym_audio_threshold unless the onsets fall at the lows) over lowering it only
where they fall at the highs; see PLAN.md.

usage: uv run python scripts/asym_threshold_sim.py OUT.json [RUN]   (RUN: default out/runs/ffcmp-ours)
"""
import inspect, json, sys, textwrap
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
from funscript_gen import pipeline
from funscript_gen.cli import parse_generate_args
from funscript_gen.evaluate import compare, drop_wiggles
from funscript_gen.export.funscript import Funscript
from funscript_gen.options import build, for_analysis
from funscript_gen.validate import clips, load_manifest

RUN = Path(sys.argv[2] if len(sys.argv) > 2 else 'out/runs/ffcmp-ours')
src = textwrap.dedent(inspect.getsource(pipeline.flip_by_asymmetry))
old = "        threshold = opts.asym_sign_threshold - audio_share * (opts.asym_sign_threshold - opts.asym_audio_threshold)\n"
assert old in src
new = old + "        threshold = VARIANT(opts, threshold, audio, group, out)\n"
src = src.replace(old, new)

def part_of(group, out):
    seen = [(p.part_sign, p.scene.end_ms - p.scene.start_ms) for p, _ in group if p.part_sign is not None]
    return out * sum(a * d for a, d in seen) / sum(d for _, d in seen) if seen else None

def make(kind, t0=0.3, amax=0.3, veto=0.4, none_t0=True):
    def v(opts, th, audio, group, out):
        if kind == 'base':
            return th
        if kind in ('neutral', 'both'):
            if audio is None:
                th = min(th, t0) if none_t0 else th
            elif audio >= 0:
                th = t0 + (opts.asym_sign_threshold - t0) * min(1.0, audio / amax)
            else:
                th = min(th, t0)
        if kind in ('veto', 'both'):
            ps = part_of(group, out)
            if ps is not None and ps >= veto:
                th = np.inf
        return th
    return v

VARIANTS = {'base': make('base')}
for t0 in (0.2, 0.3, 0.4):
    for amax in (0.15, 0.3):
        VARIANTS[f'neutral t0={t0} amax={amax}'] = make('neutral', t0, amax)
        VARIANTS[f'both t0={t0} amax={amax}'] = make('both', t0, amax)
    VARIANTS[f'neutral t0={t0} amax=0.3 none->0.5'] = make('neutral', t0, 0.3, none_t0=False)
VARIANTS['veto 0.4'] = make('veto', veto=0.4)
VARIANTS['veto 0.2'] = make('veto', veto=0.2)

def run(args):
    clip, names = args
    out = {}
    given, preset = parse_generate_args([])
    a = pipeline.load_analysis(RUN / 'default' / f'{clip.name}.analysis.pkl')
    opts = build(for_analysis(a.key, given, preset))
    ref = Funscript.load(clip.reference)
    for name in names:
        ns = dict(vars(pipeline)); ns['VARIANT'] = VARIANTS[name]
        exec(src, ns)
        pipeline.flip_by_asymmetry = ns['flip_by_asymmetry']
        res = pipeline.render(a, opts)
        s = compare(ref, res.funscript)
        flips = sorted(p.scene.index for p in res.plans if p.asym_flipped)
        out[name] = (s.f1, s.correlation, flips)
    return clip.name, clip.group, out

if __name__ == '__main__':
    cs = [c for c in clips(load_manifest(), 'all')]
    names = list(VARIANTS)
    with ProcessPoolExecutor(6) as pool:
        res = list(pool.map(run, [(c, names) for c in cs]))
    json.dump(res, open(sys.argv[1], 'w'))
    for name in names:
        line = []
        for g in ('dev', 'test', 'holdout'):
            r = [o[name] for c, gg, o in res if gg == g]
            b = [o['base'] for c, gg, o in res if gg == g]
            line.append(f"{g} F1 {np.mean([x[0] for x in r]):.3f} ({np.mean([x[0] for x in r]) - np.mean([x[0] for x in b]):+.3f}) r {np.mean([x[1] for x in r]):.3f}")
        changed = [c for c, gg, o in res if o[name][2] != o['base'][2]]
        print(f"{name:34} " + " | ".join(line) + f" | changed: {','.join(changed)}")
