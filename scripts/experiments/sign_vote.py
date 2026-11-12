"""Offline: every stroke-direction cue tried so far that can still be computed, side by side per scene group against
the hand-made script, and votes weighted by each cue's confidence (fitted leaving one source series out) scored with
the real F1 and r. Extends scripts/sign_model.py (part boxes, asymmetry, sound; 2026-10-31) with OpenFunML's output
and the depth models of scripts/experiments/depth_compare.py.

Base output: the default settings with the part check and the asymmetry check off (the chunks of a long shot still
aligned), i.e. "up = high". Every cue is signed so that > 0 means "keep the base sign" and < 0 "flip"; |value| is its
confidence. Groups: the chunks that chunk alignment links (as sign_model.py); truth = the duration-weighted zero-lag
correlation of the base position with the hand-made script (10 fps, 2 s detrend); |truth| < MIN_R is unlabelled
(not fitted, not counted, but still flipped in the score simulation).

Cues: part (penis-vulva distance, as flip_by_parts), asym (fall/rise asymmetry, >= asym_sign_min_strokes), audio
(onset phase), ofml02 / ofml03 (correlation of OpenFunML's output, out/runs/ofml, with the base position), dino_roi /
wd_full (depth_compare.py's ridge prediction, alpha 1, leave-one-series-out, out/depth_feats).

Votes, per cue a weight from the training folds (dev+test, one series held out; holdout judged by a fit on all of
dev+test), summed with the base sign's prior log-odds; a group is flipped when the sum < -margin:
  abs     P(cue right) = sigmoid(b |v|), the vote sign(v) * b |v| (no confidence, no vote)
  binned  per |v| bin, the log-odds of the cue's accuracy (shrunk; 0 when <= 50%)
  signed  per cue P(keep) = sigmoid(a + b v), the vote b v (a likelihood ratio: the prior is not counted twice)
plus "part first" (|part| >= 0.2 decides, as the pipeline; the vote decides the rest) and a stacked logistic model.

Result (2026-11-04): no vote beats the current rule on both dev and test; see PLAN.

usage: uv run python scripts/experiments/sign_vote.py [--run out/runs/ffcmp-ours] [--cal abs|binned|signed] [--subsets]
       RUN: a `validate` run with the default settings' saved analyses of all clips (made with --part-sign)
"""
import argparse
import pathlib
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from depth_compare import fit_predict  # noqa: E402
from mask_depth import corr, curve, detrend  # noqa: E402

from funscript_gen.cli import parse_generate_args  # noqa: E402
from funscript_gen.evaluate import compare  # noqa: E402
from funscript_gen.export.funscript import Funscript  # noqa: E402
from funscript_gen.options import build, for_analysis  # noqa: E402
from funscript_gen.direction import _cosine  # noqa: E402
from funscript_gen.pipeline import load_analysis, refinalize, render, sample_rate  # noqa: E402
from funscript_gen.signal.process import fall_rise_asymmetry  # noqa: E402
from funscript_gen.tracking.parts import distance_sign, penis_vulva_distance  # noqa: E402
from funscript_gen.validate import clips, load_manifest  # noqa: E402

if sys.platform != "win32":
    pathlib.WindowsPath = pathlib.PureWindowsPath

OUT = Path(__file__).resolve().parents[2] / "out"
FPS = 10.0
MIN_R = 0.3
CUES = ("part", "asym", "audio", "ofml02", "ofml03", "dino_roi", "wd_full")
BINS = (0.0, 0.2, 0.4, 0.6, np.inf)


def load(run: Path) -> tuple[list[dict], list]:
    """Per flow scene of the base output: its cues and truth; per clip (clip, base result, its options, script)."""
    rows, results = [], []
    for clip in clips(load_manifest(), "all"):
        pkl = run / "default" / f"{clip.name}.analysis.pkl"
        if not pkl.exists():
            continue
        analysis = load_analysis(pkl)
        given, preset = parse_generate_args([])
        o_def = build(for_analysis(analysis.key, given, preset))
        given, preset = parse_generate_args(["--no-part-sign", "--no-asym-sign"])
        o_base = build(for_analysis(analysis.key, given, preset))
        current = {p.scene.index for p in render(analysis, o_def).plans if p.part_flipped or p.asym_flipped}
        res = render(analysis, o_base)
        ref = Funscript.load(clip.reference)
        ref_acts = ref.normalized().actions
        ofml = {k: Funscript.load(p).normalized().actions
                for k, p in (("ofml02", OUT / "runs/ofml/ofml-0.2" / f"{clip.name}.funscript"),
                             ("ofml03", OUT / "runs/ofml/ofml-0.3" / f"{clip.name}.funscript")) if p.exists()}
        fpath = OUT / "depth_feats" / f"{clip.name}.npz"
        feats = np.load(fpath) if fpath.exists() else None
        prev = None
        for plan in res.plans:
            if plan.signal is None or plan.flow_position is None or plan.skip:
                prev = None
                continue
            t, x = plan.flow_position
            ok = np.isfinite(x)
            if ok.sum() < 30:
                prev = None
                continue
            i = plan.scene.index
            tt = np.arange(plan.scene.start_ms, plan.scene.end_ms, 1000 / FPS)
            xs = detrend(np.interp(tt, t[ok], x[ok]), FPS)
            ys = detrend(curve(ref_acts, tt), FPS)
            cue = {}
            if plan.parts_found is not None:
                times, boxes, size = plan.parts_found
                dist, edge = penis_vulva_distance(boxes, size)
                if edge < o_def.part_max_edge:
                    r = distance_sign(np.array(times), dist, t, x, o_def.part_fps, o_def.part_min_cover)
                    if r is not None:
                        cue["part"] = r
            n = fall_rise_asymmetry(x, sample_rate(t, o_def.fps))[1]
            if plan.asym is not None and n >= o_def.asym_sign_min_strokes:
                cue["asym"] = -plan.asym
            if plan.audio_sign is not None:
                cue["audio"] = plan.audio_sign
            for k, acts in ofml.items():
                c = corr(detrend(curve(acts, tt), FPS), xs)
                if c is not None:
                    cue[k] = c
            row = dict(clip=clip.name, group=clip.group, series=clip.name[0], index=i, n=n, cue=cue,
                       sec=(plan.scene.end_ms - plan.scene.start_ms) / 1000, current=i in current,
                       truth=corr(xs, ys) if ys.std() >= 1 else None, feats={})
            if feats is not None and f"t{i}" in feats.files and len(feats[f"t{i}"]) >= 12:
                ft = feats[f"t{i}"]  # the depth model's frames (10 fps), for fit_predict
                row.update(t=ft, y_ref=detrend(curve(ref_acts, ft), FPS), x_at=detrend(np.interp(ft, t[ok], x[ok]), FPS))
                row["ref_ok"] = row["y_ref"].std() >= 1
                for name, key in (("dino_roi", f"dinov2_roi{i}"), ("wd_full", f"wd_full{i}")):
                    if key in feats.files:
                        f = feats[key].astype(np.float64)
                        row["feats"][name] = f - f.mean(0)
            row["linked"] = prev is not None and plan.scene.continued and prev.scene.index == i - 1 \
                and plan.sign_pattern is not None and prev.sign_pattern is not None \
                and _cosine(plan.sign_pattern, prev.sign_pattern) >= o_def.chunk_align_similarity
            rows.append(row)
            prev = plan
        results.append((clip, res, o_base, ref))
    for feat in ("dino_roi", "wd_full"):
        fit_predict(rows, feat, 1.0, {"dev", "test"})
    for r in rows:
        for feat in ("dino_roi", "wd_full"):
            pred = r.get("pred", {}).get((feat, 1.0))
            c = corr(pred, r["x_at"]) if pred is not None else None
            if c is not None:
                r["cue"][feat] = c
    return rows, results


def groups(rows: list[dict]) -> list[dict]:
    """The linked chunks of one shot as one group: duration-weighted truth and cues (asymmetry by strokes)."""
    runs = []
    for row in rows:
        if row["linked"] and runs and runs[-1][-1]["clip"] == row["clip"]:
            runs[-1].append(row)
        else:
            runs.append([row])
    out = []
    for g in runs:
        lab = [r for r in g if r["truth"] is not None]
        cue = {}
        for k in CUES:
            have = [(r["cue"][k], r["n"] if k == "asym" else r["sec"]) for r in g if k in r["cue"]]
            if have and sum(w for _, w in have) > 0:
                cue[k] = sum(v * w for v, w in have) / sum(w for _, w in have)
        out.append(dict(rows=g, clip=g[0]["clip"], group=g[0]["group"], series=g[0]["series"], cue=cue,
                        dur=sum(r["sec"] for r in g), current=any(r["current"] for r in g),
                        truth=sum(r["truth"] * r["sec"] for r in lab) / sum(r["sec"] for r in lab) if lab else None))
    return out


def labelled(gs: list[dict]) -> list[dict]:
    return [g for g in gs if g["truth"] is not None and abs(g["truth"]) >= MIN_R]


# --- votes ---

def logit_fit(x: np.ndarray, y: np.ndarray, w: np.ndarray, ridge: float, intercept: bool = True) -> np.ndarray:
    """Weighted logistic regression by Newton steps; with `intercept` the first column is unpenalized."""
    beta = np.zeros(x.shape[1])
    pen = np.full(x.shape[1], ridge)
    if intercept:
        pen[0] = 0.0
    for _ in range(50):
        p = 1 / (1 + np.exp(-np.clip(x @ beta, -30, 30)))
        grad = x.T @ (w * (p - y)) + pen * beta
        hess = (x * (w * p * (1 - p))[:, None]).T @ x + np.diag(pen)
        step = np.linalg.solve(hess, grad)
        beta -= step
        if np.abs(step).max() < 1e-8:
            break
    return beta


def calibrate(train: list[dict], cues: tuple, how: str) -> tuple[dict, float]:
    """Per cue its vote weight (see the module doc), and the base sign's prior log-odds, duration-weighted."""
    cal = {}
    for k in cues:
        have = [g for g in train if k in g["cue"] and g["cue"][k] != 0]
        if len(have) < 8:
            continue
        v = np.array([g["cue"][k] for g in have])
        keep = np.array([g["truth"] > 0 for g in have], float)
        right = ((v > 0) == (keep > 0)).astype(float)
        w = np.array([g["dur"] for g in have])
        w = w / w.mean()
        if how == "abs":
            cal[k] = ("abs", float(logit_fit(np.abs(v)[:, None], right, w, 0.1, intercept=False)[0]))
        elif how == "signed":
            cal[k] = ("signed", float(logit_fit(np.c_[np.ones(len(v)), v], keep, w, 0.3)[1]))
        else:
            ws = []
            for lo, hi in zip(BINS, BINS[1:]):
                m = (np.abs(v) >= lo) & (np.abs(v) < hi)
                p = ((w * right)[m].sum() + 2) / (w[m].sum() + 4)
                ws.append(max(0.0, float(np.log(p / (1 - p)))))
            cal[k] = ("binned", ws)
    w = np.array([g["dur"] for g in train])
    p = sum(g["dur"] for g in train if g["truth"] > 0) / w.sum()
    return cal, float(np.log(p / (1 - p)))


def vote(g: dict, cal: dict, prior: float) -> float:
    s = prior
    for k, (how, c) in cal.items():
        v = g["cue"].get(k, 0.0)
        if v == 0:
            continue
        if how == "binned":
            s += np.sign(v) * c[int(np.searchsorted(BINS, abs(v), side="right")) - 1]
        else:  # abs: sign(v) * b |v| = b v; signed: b v
            s += c * v
    return s


def folds(gs: list[dict]) -> list[tuple[list[dict], list[dict]]]:
    """(groups to judge, labelled training groups): one series of dev+test held out at a time; the holdout clips
    judged by a fit on all of dev+test."""
    lab = [g for g in labelled(gs) if g["group"] in ("dev", "test")]
    out = [([g for g in gs if g["series"] == s and g["group"] in ("dev", "test")], [g for g in lab if g["series"] != s])
           for s in sorted({g["series"] for g in gs if g["group"] in ("dev", "test")})]
    return out + [([g for g in gs if g["group"] not in ("dev", "test")], lab)]


def settled(g: dict, part_t: float = 0.2) -> bool:
    return "part" in g["cue"] and abs(g["cue"]["part"]) >= part_t


def decide_vote(gs: list[dict], cues: tuple, how: str, margin: float, part_first: bool) -> set:
    flips = set()
    for judge, train in folds(gs):
        cal, prior = calibrate([g for g in train if not (part_first and settled(g))], cues, how)
        for g in judge:
            if part_first and settled(g):
                if g["cue"]["part"] < 0:
                    flips.add(id(g))
            elif vote(g, cal, prior) < -margin:
                flips.add(id(g))
    return flips


def decide_stack(gs: list[dict], cues: tuple, ridge: float) -> set:
    flips = set()
    design = lambda g: np.array([1.0] + [g["cue"].get(k, 0.0) for k in cues])  # noqa: E731
    for judge, train in folds(gs):
        w = np.array([g["dur"] for g in train])
        beta = logit_fit(np.array([design(g) for g in train]), np.array([g["truth"] > 0 for g in train], float),
                         w / w.mean(), ridge)
        flips |= {id(g) for g in judge if design(g) @ beta < 0}
    return flips


# --- scoring ---

_SCORES: dict = {}


def clip_scores(gs: list[dict], results: list, flips: set) -> dict[str, tuple]:
    """Per clip (group, F1, r) with these groups flipped on the base output (as by hand); cached per clip and set of
    flipped scenes."""
    by_clip: dict[str, set] = {}
    for g in gs:
        if id(g) in flips:
            by_clip.setdefault(g["clip"], set()).update(r["index"] for r in g["rows"])
    out = {}
    for clip, res, opts, ref in results:
        key = (clip.name, frozenset(by_clip.get(clip.name, ())))
        if key not in _SCORES:
            for p in res.plans:
                p.flipped = p.scene.index in key[1]
            refinalize(res, opts)
            s = compare(ref, res.funscript)
            _SCORES[key] = (clip.group, s.f1, s.correlation)
            for p in res.plans:
                p.flipped = False
            refinalize(res, opts)
        out[clip.name] = _SCORES[key]
    return out


def simulate(gs: list[dict], results: list, flips: set) -> dict:
    """Mean F1 and r per split with these groups flipped on the base output."""
    per: dict[str, list] = {}
    for group, f1, r in clip_scores(gs, results, flips).values():
        per.setdefault(group, []).append((f1, r))
    return {k: np.mean(v, 0) for k, v in per.items()}


def fold_clips(gs: list[dict]) -> list[tuple[set, set]]:
    """folds() as clip names: (clips judged, training clips)."""
    out = []
    for judge, train in folds(gs):
        series = {g["series"] for g in judge}
        held = {g["group"] for g in judge}
        j = {g["clip"] for g in judge}
        t = {g["clip"] for g in gs if g["group"] in ("dev", "test") and (g["series"] not in series or held == {"holdout"})}
        out.append((j, t - j))
    return out


def choose_by_f1(gs: list[dict], results: list, candidates: dict) -> tuple[set, list]:
    """Per fold the candidate (name -> flips over all groups) with the best mean F1 of the training clips; the judged
    clips get that candidate's flips. Returns the flips and the names chosen."""
    scores = {name: clip_scores(gs, results, flips) for name, flips in candidates.items()}
    out, chosen = set(), []
    for judge, train in fold_clips(gs):
        best = max(candidates, key=lambda n: np.mean([scores[n][c][1] for c in train]))
        chosen.append(best)
        out |= {id(g) for g in gs if g["clip"] in judge and id(g) in candidates[best]}
    return out, chosen


def line(name: str, gs: list[dict], results: list, flips: set) -> None:
    parts = []
    for split in ("dev", "test", "holdout"):
        sub = [g for g in labelled(gs) if g["group"] == split]
        ok = [g for g in sub if (g["truth"] > 0) != (id(g) in flips)]
        parts.append(f"{len(ok):3d}/{len(sub):<3d}({sum(g['dur'] for g in ok) / sum(g['dur'] for g in sub):.2f})")
    unl = sum(1 for g in gs if id(g) in flips and not (g["truth"] is not None and abs(g["truth"]) >= MIN_R))
    sim = simulate(gs, results, flips)
    print(f"{name:42} " + " ".join(parts) + f"  flips {len(flips):3d} ({unl:3d} unl.)   "
          + "  ".join(f"{sim[k][0]:.3f}/{sim[k][1]:.3f}" for k in ("dev", "test", "holdout")), flush=True)


def single_cue_report(gs: list[dict]) -> None:
    print(f"\n== each cue alone (groups with |r| >= {MIN_R}): used, sign right, base sign right in them, fixes, breaks")
    for k in CUES:
        for split in ("dev+test", "holdout"):
            sub = [g for g in labelled(gs) if (g["group"] != "holdout") == (split == "dev+test") and k in g["cue"]]
            for th in (0.0, 0.2, 0.4, 0.6):
                used = [g for g in sub if abs(g["cue"][k]) >= th and g["cue"][k] != 0]
                if used:
                    acc = sum((g["cue"][k] > 0) == (g["truth"] > 0) for g in used) / len(used)
                    base = sum(g["truth"] > 0 for g in used) / len(used)
                    fix = sum(g["cue"][k] < 0 and g["truth"] < 0 for g in used)
                    brk = sum(g["cue"][k] < 0 and g["truth"] > 0 for g in used)
                    print(f"  {k:9}{split:>9} |v|>={th:.1f} {len(used):4d}  {acc:4.0%}  base {base:4.0%}"
                          f"  fix {fix:3d} break {brk:3d}")


def overlap_report(gs: list[dict]) -> None:
    lab = [g for g in labelled(gs) if g["group"] != "holdout"]
    print("\n== dev+test, |v| >= 0.2: share asking to flip where the base sign is wrong / right")
    for k in CUES:
        w = [g for g in lab if g["truth"] < 0 and abs(g["cue"].get(k, 0)) >= 0.2]
        r = [g for g in lab if g["truth"] > 0 and abs(g["cue"].get(k, 0)) >= 0.2]
        print(f"  {k:9} wrong: {sum(g['cue'][k] < 0 for g in w) / max(1, len(w)):4.0%} of {len(w):3d}"
              f"   right: {sum(g['cue'][k] < 0 for g in r) / max(1, len(r)):4.0%} of {len(r):3d}")
    print("== pairs (both |v| >= 0.2): n, agree, sign right when they agree")
    for i, a in enumerate(CUES):
        for b in CUES[i + 1:]:
            both = [g for g in lab if abs(g["cue"].get(a, 0)) >= 0.2 and abs(g["cue"].get(b, 0)) >= 0.2]
            agree = [g for g in both if (g["cue"][a] > 0) == (g["cue"][b] > 0)]
            if len(both) >= 5:
                acc = sum((g["cue"][a] > 0) == (g["truth"] > 0) for g in agree) / max(1, len(agree))
                print(f"  {a:9}{b:9} {len(both):3d}  {len(agree) / len(both):4.0%}  {acc:4.0%}")


def wrong_report(gs: list[dict]) -> None:
    """Relative to the current output (after the part and asymmetry checks): on the groups it gets wrong, how often
    each cue says flip, and how often it says so on the groups it gets right; G (3D) and the other series apart."""
    print("\n== current output wrong: cue says flip / has the cue  |  current right: says flip / has")
    for split in (("dev", "test"), ("holdout",)):
        for name, keep in (("all", lambda g: True), ("G", lambda g: g["series"] == "G"),
                           ("non-G", lambda g: g["series"] != "G")):
            sub = [g for g in labelled(gs) if g["group"] in split and keep(g)]
            wrong = sum((g["truth"] > 0) == g["current"] for g in sub)
            out = []
            for k, th in (("part", 0.2), ("asym", 0.2), ("asym", 0.4), ("audio", 0.4), ("ofml02", 0.4),
                          ("dino_roi", 0.4), ("wd_full", 0.4)):
                s = {True: [0, 0], False: [0, 0]}  # current right?: [says flip, has]
                for g in sub:
                    v = g["cue"].get(k, 0.0) * (-1 if g["current"] else 1)  # > 0: keep the current output
                    if abs(v) >= th:
                        ok = (g["truth"] > 0) != g["current"]
                        s[ok][0] += v < 0
                        s[ok][1] += 1
                out.append(f"{k}>={th} {s[False][0]}/{s[False][1]}|{s[True][0]}/{s[True][1]}")
            print(f"  {'+'.join(split):9}{name:6} wrong {wrong:3d}/{len(sub):<3d} " + "  ".join(out))


def addon_report(gs: list[dict], results: list) -> None:
    """The current rule kept; WD (alone, or with a weak asymmetry pointing the same way) only adds flips to the
    groups it left open; and the same restricted to series G, as if 3D could be told apart (an upper bound)."""
    cur = {id(g) for g in gs if g["current"]}
    open_ = [g for g in gs if not g["current"] and not settled(g)]
    wd = lambda g: g["cue"].get("wd_full", 0.0)  # noqa: E731
    asym = lambda g: g["cue"].get("asym", 0.0)  # noqa: E731
    print("\n== the current rule, plus flips of the groups it left open")
    for name, test in (("WD <= -0.4", lambda g: wd(g) <= -0.4), ("WD <= -0.6", lambda g: wd(g) <= -0.6),
                       ("WD <= -0.2 and asym <= -0.1", lambda g: wd(g) <= -0.2 and asym(g) <= -0.1),
                       ("WD <= -0.3 and asym <= -0.2", lambda g: wd(g) <= -0.3 and asym(g) <= -0.2)):
        line(f"current + {name}", gs, results, cur | {id(g) for g in open_ if test(g)})
    for name, test in (("asym <= -0.2", lambda g: asym(g) <= -0.2), ("WD <= -0.4", lambda g: wd(g) <= -0.4),
                       ("WD <= -0.2 and asym <= -0.1", lambda g: wd(g) <= -0.2 and asym(g) <= -0.1),
                       ("asym <= -0.2 or WD <= -0.4", lambda g: asym(g) <= -0.2 or wd(g) <= -0.4)):
        line(f"G only: {name}", gs, results, cur | {id(g) for g in open_ if g["series"] == "G" and test(g)})


RULE = (0.2, 0.5, 0.2, 0.3)  # part, asymmetry, asymmetry with the sound backing it, sound: the pipeline's defaults


def rule(g: dict, cues: tuple, th: tuple) -> bool:
    """The pipeline's checks restricted to `cues`: the part boxes first, then the asymmetry (a lower threshold when
    the sound backs it); with the sound but no asymmetry, the sound alone."""
    part_t, asym_t, backed_t, audio_t = th
    c = g["cue"]
    if "part" in cues and c.get("part", 0.0) <= -part_t:
        return True
    if "asym" in cues:
        backed = "audio" in cues and c.get("audio", 0.0) <= -audio_t
        return c.get("asym", 0.0) <= -(backed_t if backed else asym_t)
    return "audio" in cues and c.get("audio", 0.0) <= -audio_t


def rule_grid(cues: tuple) -> list[tuple]:
    parts = (0.1, 0.2, 0.3, 0.4) if "part" in cues else (RULE[0],)
    asyms = (0.2, 0.3, 0.4, 0.5, 0.6, 0.8) if "asym" in cues else (RULE[1],)
    backs = (0.1, 0.2, 0.3) if {"asym", "audio"} <= set(cues) else (RULE[2],)
    sounds = (0.2, 0.3, 0.4, 0.5, 0.6, 0.8) if "audio" in cues else (RULE[3],)
    return [(p, a, b, s) for p in parts for a in asyms for b in backs for s in sounds if b <= a]


def right_share(train: list[dict], flip) -> float:
    return sum(g["dur"] for g in train if (g["truth"] > 0) != flip(g)) / sum(g["dur"] for g in train)


def decide_rule(gs: list[dict], cues: tuple, th: tuple | None) -> tuple[set, list]:
    """Flips of the rule with thresholds `th`, or (None) per fold the thresholds that get the most labelled training
    duration right (ties to the nearest defaults); and the thresholds chosen."""
    flips, chosen = set(), []
    for judge, train in folds(gs):
        t = th or max(rule_grid(cues), key=lambda t: (round(right_share(train, lambda g: rule(g, cues, t)), 9),
                                                      -sum(abs(x - y) for x, y in zip(t, RULE))))
        chosen.append(t)
        flips |= {id(g) for g in judge if rule(g, cues, t)}
    return flips, chosen


def decide_vote_cv(gs: list[dict], cues: tuple, part_first: bool, margins=(0.0, 0.5, 1.0, 2.0, 3.0)) -> tuple[set, list]:
    """The vote with its margin chosen per fold as decide_rule chooses thresholds."""
    flips, chosen = set(), []
    for judge, train in folds(gs):
        cal, prior = calibrate([g for g in train if not (part_first and settled(g))], cues, "signed")

        def flip(g, m):
            if part_first and settled(g):
                return g["cue"]["part"] < 0
            return vote(g, cal, prior) < -m
        m = max(margins, key=lambda m: (round(right_share(train, lambda g: flip(g, m)), 9), m))
        chosen.append(m)
        flips |= {id(g) for g in judge if flip(g, m)}
    return flips, chosen


def subset_report(gs: list[dict], results: list) -> None:
    """Part boxes, asymmetry and sound alone, in pairs and all three: as rules and as confidence votes."""
    from itertools import combinations
    from collections import Counter

    print("\n== part / asym / audio: every subset as a rule and as a vote (signed)")
    line("base (up = high)", gs, results, set())
    line("current pipeline", gs, results, {id(g) for g in gs if g["current"]})
    for k in (1, 2, 3):
        for cues in combinations(("part", "asym", "audio"), k):
            name = "+".join(cues)
            print(f"-- {name}")
            line("rule, default thresholds", gs, results, decide_rule(gs, cues, RULE)[0])
            flips, chosen = decide_rule(gs, cues, None)
            line("rule, thresholds chosen per fold", gs, results, flips)
            print(f"{'':6}chosen (part, asym, backed, sound):", Counter(chosen).most_common(3))
            cands = {t: {id(g) for g in gs if rule(g, cues, t)} for t in rule_grid(cues)}
            flips, chosen = choose_by_f1(gs, results, cands)
            line("rule, thresholds chosen per fold by F1", gs, results, flips)
            print(f"{'':6}chosen (part, asym, backed, sound):", Counter(chosen).most_common(3))
            for part_first in ((False, True) if "part" in cues and k > 1 else (False,)):
                tag = "part first + vote" if part_first else "vote"
                for m in (0.0, 1.0, 2.0):
                    line(f"{tag}, margin {m}", gs, results, decide_vote(gs, cues, "signed", m, part_first))
                flips, chosen = decide_vote_cv(gs, cues, part_first)
                line(f"{tag}, margin chosen per fold", gs, results, flips)
                print(f"{'':6}chosen margins:", Counter(chosen).most_common(3))
                cands = {m: decide_vote(gs, cues, "signed", m, part_first) for m in (0.0, 0.5, 1.0, 2.0, 3.0)}
                flips, chosen = choose_by_f1(gs, results, cands)
                line(f"{tag}, margin chosen per fold by F1", gs, results, flips)
                print(f"{'':6}chosen margins:", Counter(chosen).most_common(3))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default=str(OUT / "runs/ffcmp-ours"))
    ap.add_argument("--cal", default="signed", choices=("abs", "binned", "signed"))
    ap.add_argument("--subsets", action="store_true", help="only the subsets of part / asym / audio")
    args = ap.parse_args()
    rows, results = load(Path(args.run))
    gs = groups(rows)
    if args.subsets:
        subset_report(gs, results)
        return
    print(f"{len(rows)} scenes, {len(gs)} groups, {len(labelled(gs))} with |r| >= {MIN_R}")
    for split in ("dev", "test", "holdout"):
        lab = [g for g in labelled(gs) if g["group"] == split]
        print(f"  {split}: {len(lab)} labelled; with the cue: " + ", ".join(
            f"{k} {sum(k in g['cue'] for g in lab)}" for k in CUES))
    single_cue_report(gs)
    overlap_report(gs)
    wrong_report(gs)
    addon_report(gs, results)
    cal, prior = calibrate(folds(gs)[-1][1], CUES, args.cal)
    print(f"\nfitted on dev+test ({args.cal}): prior {prior:.2f}, " + ", ".join(
        f"{k} {np.round(c, 2).tolist()}" for k, (_, c) in cal.items()))
    print("\n== right/labelled (duration share) dev test holdout; flips (unlabelled); mean F1/r dev test holdout")
    line("base (up = high, chunks aligned)", gs, results, set())
    line("current rule (part 0.2 -> asym 0.5 / sound)", gs, results, {id(g) for g in gs if g["current"]})
    line("oracle", gs, results, {id(g) for g in gs if g["truth"] is not None and g["truth"] < 0})
    sets = {"part, asym, audio": ("part", "asym", "audio"), "+ wd_full": ("part", "asym", "audio", "wd_full"),
            "+ ofml02 + wd_full": ("part", "asym", "audio", "ofml02", "wd_full"), "all": CUES}
    for margin in (0.0, 0.5, 1.0, 2.0):
        for part_first in (False, True):
            print(f"-- vote ({args.cal}), flip below -{margin}" + (", part boxes first" if part_first else ""))
            for name, cues in sets.items():
                line(f"{'part+' if part_first else ''}vote m{margin}: {name}", gs, results,
                     decide_vote(gs, cues, args.cal, margin, part_first))
    print("-- stacked logistic on the signed values (missing = 0)")
    for name, cues in (("part, asym, audio", ("part", "asym", "audio")), ("all", CUES)):
        for ridge in (0.1, 1.0, 10.0):
            line(f"stack r{ridge}: {name}", gs, results, decide_stack(gs, cues, ridge))


if __name__ == "__main__":
    main()
