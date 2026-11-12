"""Offline (user's proposal, 2026-11-04): where the penis-vulva check has no answer, find the people as objects from
their body parts (female parts -> the woman, a penis -> the man, the head nearest the female parts -> hers, other
heads as objects of their own; no female part: heads of unknown sex), follow the distance between the two points of
different objects seen together most often, closer = down; judged once per scene on one stroke cycle ("cycle": the
largest, "first": the first) or, to compare, on the whole window. Scored as an extra check after the part check on
sign_vote.py's scene groups and score simulation. Result: no better than chance, every variant lowers F1; see PLAN.

  targets RUN OUT.json [--groups dev,test]
      the labelled flow scenes (|r| >= 0.3) without a part-check answer: their first 10 s
  dump TARGETS.json CLIP OUT.json
      heads (imgutils detect_heads), booru_yolo body parts and censor parts at 10 fps on the clip's spans; needs
      imgutils, which must not enter the project's environment (it changes numpy and OpenCV), so run as
        uv run --no-project --with dghs-imgutils --with onnxruntime --with-editable . python scripts/experiments/body_sign.py dump ...
      (about 2 frames/s per process with 3 threads; dev+test, 210 scenes, ~30 min with 4 at a time)
  eval RUN DETS_DIR

RUN: a `validate` run with the default settings' saved analyses of all clips (as sign_vote.py, out/runs/ffcmp-ours).
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

FEMALE = {"pussy", "nipple_f", "boob", "bust", "sideb", "shld", "nopan", "butt", "ass", "split", "sprd", "vsplt",
          "vsprd", "hip", "belly"}
HOWS = ("whole", "cycle", "first")

def centre(b):
    return np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])

def objects(boxes):
    """Per frame {key: centre}: one point per (object, label), the most confident box. Objects: F (female parts),
    M (penis), F's head (the head nearest the female parts), other heads O1, O2 (left to right) or, with no female
    part, U1, U2."""
    best = {}
    for b, lab, c in boxes:
        if lab in FEMALE or lab == "penis":
            k = ("F:" if lab in FEMALE else "M:") + lab
            if k not in best or c > best[k][1]:
                best[k] = (centre(b), c)
    pts = {k: v[0] for k, v in best.items()}
    heads = sorted([centre(b) for b, lab, c in boxes if lab == "head" and c >= 0.3], key=lambda p: p[0])[:3]
    fem = [p for k, p in pts.items() if k.startswith("F:")]
    if fem and heads:
        fc = np.mean(fem, 0)
        j = int(np.argmin([np.hypot(*(h - fc)) for h in heads]))
        pts["F:head"] = heads.pop(j)
        for n, h in enumerate(heads[:2]):
            pts[f"O{n + 1}:head"] = h
    else:
        for n, h in enumerate(heads[:2]):
            pts[f"U{n + 1}:head"] = h
    return pts

def pair_distance(frames, size):
    """The pair of points on two different objects seen together in the most frames: (name, distance per frame)."""
    diag = float(np.hypot(*size))
    per = [objects(b) for _, b in frames]
    cnt = Counter()
    for p in per:
        ks = sorted(p)
        for i, a in enumerate(ks):
            for b in ks[i + 1:]:
                if a.split(":")[0] != b.split(":")[0]:
                    cnt[(a, b)] += 1
    if not cnt:
        return None, None
    (a, b), _ = cnt.most_common(1)[0]
    d = np.array([np.hypot(*(p[a] - p[b])) / diag if a in p and b in p else np.nan for p in per])
    return f"{a}~{b}", d

def turning(y):
    return [i for i in range(1, len(y) - 1) if (y[i] - y[i - 1]) * (y[i + 1] - y[i]) < 0]

def cue(t, d, ft, fx, how, fps=10.0, min_cover=0.6):
    from funscript_gen.tracking.parts import _detrend

    ok = ~np.isnan(d)
    if len(d) < 20 or ok.mean() < min_cover:
        return None
    x = _detrend(np.interp(t, t[ok], d[ok]), fps)
    y = _detrend(np.interp(t, ft, fx), fps)
    if how == "whole":
        sel = np.arange(len(t))
    else:  # one stroke cycle: between two turning points of the same kind, the largest one with the distance seen
        tp = turning(np.convolve(y, np.ones(3) / 3, mode="same"))
        cands = []
        for i in range(len(tp) - 2):
            a, b = tp[i], tp[i + 2]
            if b - a >= 4 and ok[a:b + 1].mean() >= min_cover:
                cands.append((np.ptp(y[a:b + 1]), a, b))
        if not cands:
            return None
        _, a, b = max(cands) if how == "cycle" else cands[0]
        sel = np.arange(a, b + 1)
    xa, ya = x[sel], y[sel]
    if xa.std() < 1e-9 or ya.std() < 1e-9:
        return None
    return float(np.corrcoef(xa, ya)[0, 1])


def targets(run: Path, out: Path, groups: set) -> None:
    import sign_vote
    from funscript_gen.pipeline import load_analysis

    rows, _ = sign_vote.load(run)
    spans = {}
    for r in rows:
        if "part" in r["cue"] or r["group"] not in groups or r["truth"] is None or abs(r["truth"]) < sign_vote.MIN_R:
            continue
        spans.setdefault(r["clip"], []).append(r["index"])
    res = {}
    for clip, idx in spans.items():
        a = load_analysis(run / "default" / f"{clip}.analysis.pkl")
        sc = {p.scene.index: p.scene for p in a.plans}
        res[clip] = dict(video=str(a.video),
                         spans=[(i, sc[i].start_ms, min(sc[i].end_ms, sc[i].start_ms + 10000)) for i in idx])
    out.write_text(json.dumps(res))
    print(len(res), "clips", sum(len(v["spans"]) for v in res.values()), "scenes",
          round(sum(e - s for v in res.values() for _, s, e in v["spans"]) / 1000), "s")


def dump(targets_path: Path, clip: str, out: Path) -> None:
    import cv2
    import onnxruntime as ort
    from PIL import Image

    session = ort.InferenceSession

    def capped(path, sess_options=None, *a, **k):  # imgutils opens each model with every core's threads
        so = sess_options or ort.SessionOptions()
        so.intra_op_num_threads, so.inter_op_num_threads = 3, 1
        return session(path, so, *a, **k)

    ort.InferenceSession = capped
    import imgutils.detect as d
    from funscript_gen.video.decoder import iter_frames

    v = json.loads(targets_path.read_text())[clip]
    res, t0 = {}, time.time()
    for i, s, e in v["spans"]:
        frames, size = [], [0, 0]
        for f in iter_frames(v["video"], target_fps=10, max_side=960, start_ms=s, end_ms=e):
            if f.t_ms >= e:
                break
            size = [f.image.shape[1], f.image.shape[0]]
            img = Image.fromarray(cv2.cvtColor(f.image, cv2.COLOR_BGR2RGB))
            boxes = []
            for fn in (d.detect_heads, d.detect_with_booru_yolo, d.detect_censors):
                boxes += [[list(map(int, b)), lab, round(float(c), 3)] for b, lab, c in fn(img)]
            frames.append([round(f.t_ms, 1), boxes])
        res[i] = dict(size=size, frames=frames)
    out.write_text(json.dumps(res))
    print(clip, len(v["spans"]), round(time.time() - t0), "s")


def evaluate(run: Path, det_dir: Path) -> None:
    import sign_vote

    rows, results = sign_vote.load(run)
    dets = {p.stem: json.loads(p.read_text()) for p in det_dir.glob("*.json")}
    plans = {clip.name: {p.scene.index: p for p in res.plans} for clip, res, _, _ in results}
    pairs = Counter()
    for r in rows:
        det = dets.get(r["clip"], {}).get(str(r["index"]))
        if det is None or not det["frames"]:
            continue
        p = plans[r["clip"]][r["index"]]
        t = np.array([f[0] for f in det["frames"]])
        name, d = pair_distance(det["frames"], det["size"])
        if name is None:
            continue
        ft, fx = p.flow_position
        for how in HOWS:
            c = cue(t, d, ft, fx, how)
            if c is not None:
                r["cue"]["body_" + how] = c
        if "body_whole" in r["cue"]:
            pairs[name.replace("O1", "O").replace("O2", "O").replace("U1", "U").replace("U2", "U")] += 1
    print("pairs used:", pairs.most_common(12))
    sign_vote.CUES = sign_vote.CUES + tuple("body_" + h for h in HOWS)
    gs = sign_vote.groups(rows)

    def report(key):
        print(f"\n== {key}: per labelled group without the part check (truth = script; flip when cue <= -th)")
        for g_name, sel in (("2D", lambda g: g["series"] != "G"), ("G", lambda g: g["series"] == "G")):
            for split in ("dev", "test"):
                sub = [g for g in sign_vote.labelled(gs) if sel(g) and g["group"] == split and key in g["cue"]]
                if not sub:
                    continue
                agree = sum((g["cue"][key] > 0) == (g["truth"] > 0) for g in sub)
                line = f"  {g_name:2} {split:4} n={len(sub):3d} cue agrees with script {agree:3d}"
                for th in (0.2, 0.4):
                    fix = sum(1 for g in sub if g["cue"][key] <= -th and not g["current"] and g["truth"] < 0)
                    brk = sum(1 for g in sub if g["cue"][key] <= -th and not g["current"] and g["truth"] > 0)
                    # as a deciding check before the asymmetry: also undoes asymmetry flips when cue >= th
                    fix2 = fix + sum(1 for g in sub if g["cue"][key] >= th and g["current"] and g["truth"] > 0)
                    brk2 = brk + sum(1 for g in sub if g["cue"][key] >= th and g["current"] and g["truth"] < 0)
                    line += f" | th {th}: flip-only +{fix}/-{brk}, decide +{fix2}/-{brk2}"
                print(line)

    for how in HOWS:
        report("body_" + how)
    cur = {id(g) for g in gs if g["current"]}
    print()
    sign_vote.line("current rule", gs, results, cur)
    for how in HOWS:
        k = "body_" + how
        for th in (0.2, 0.4):
            flips = cur | {id(g) for g in gs if g["cue"].get(k, 0) <= -th}
            sign_vote.line(f"{how} th{th} flip-only", gs, results, flips)
            flips = (cur - {id(g) for g in gs if g["cue"].get(k, 0) >= th}) | {id(g) for g in gs if g["cue"].get(k, 0) <= -th}
            sign_vote.line(f"{how} th{th} decide", gs, results, flips)
            flips = cur | {id(g) for g in gs if g["series"] == "G" and g["cue"].get(k, 0) <= -th}
            sign_vote.line(f"{how} th{th} flip-only, G only", gs, results, flips)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("targets"); p.add_argument("run", type=Path); p.add_argument("out", type=Path)
    p.add_argument("--groups", default="dev,test")
    p = sub.add_parser("dump"); p.add_argument("targets", type=Path); p.add_argument("clip"); p.add_argument("out", type=Path)
    p = sub.add_parser("eval"); p.add_argument("run", type=Path); p.add_argument("dets", type=Path)
    a = ap.parse_args()
    if a.cmd == "targets":
        targets(a.run, a.out, set(a.groups.split(",")))
    elif a.cmd == "dump":
        dump(a.targets, a.clip, a.out)
    else:
        evaluate(a.run, a.dets)


if __name__ == "__main__":
    main()
