"""Offline (user's proposal, 2026-11-05): where the penis box is missing, take a female part as the anchor (pussy,
hand, mouth, nipple), the strongest-moving thing near it as the interaction object, and judge the stroke direction
from the distance between the two (apart = pulled out = high). Which part is the anchor: the one whose box has the
most optical flow; when the best two are within `--tie` of each other, the priority pussy > hand > mouth > nipple.
Judged like scripts/experiments/body_sign.py (same targets, same score simulation), so the numbers can be compared with its.

  dump TARGETS.json CLIP OUT.json
      per target scene's first 10 s at 10 fps: boxes of censor parts (pussy, nipple_f, penis), hands, heads, and the
      optical flow magnitude (camera motion removed) on a 64x36 grid. Needs imgutils, which must not enter the
      project's environment, so run as
        uv run --no-project --with dghs-imgutils --with onnxruntime --with-editable . python scripts/experiments/female_anchor.py dump ...
  eval RUN DETS_DIR [--tie 0.25]

TARGETS: `body_sign.py targets RUN OUT.json`.  RUN: out/runs/ffcmp-ours.
The mouth has no detector: it is taken as the lower-middle of every head box (a stand-in, unverified).
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

GW, GH = 64, 36
PRIORITY = ["pussy", "hand", "mouth", "nipple_f"]


def dump(targets_path: Path, clip: str, out: Path) -> None:
    import cv2
    import onnxruntime as ort
    from PIL import Image

    session = ort.InferenceSession

    def capped(path, sess_options=None, *a, **k):
        so = sess_options or ort.SessionOptions()
        so.intra_op_num_threads, so.inter_op_num_threads = 3, 1
        return session(path, so, *a, **k)

    ort.InferenceSession = capped
    cv2.setNumThreads(2)
    import imgutils.detect as d
    from funscript_gen.video.decoder import iter_frames

    v = json.loads(targets_path.read_text())[clip]
    res, t0 = {}, time.time()
    for i, s, e in v["spans"]:
        frames, size, prev = [], [0, 0], None
        for f in iter_frames(v["video"], target_fps=10, max_side=960, start_ms=s, end_ms=e):
            if f.t_ms >= e:
                break
            size = [f.image.shape[1], f.image.shape[0]]
            img = Image.fromarray(cv2.cvtColor(f.image, cv2.COLOR_BGR2RGB))
            boxes = []
            for fn in (d.detect_heads, d.detect_hands, d.detect_censors):
                boxes += [[list(map(int, b)), lab, round(float(c), 3)] for b, lab, c in fn(img)]
            small = cv2.cvtColor(cv2.resize(f.image, (320, int(320 * size[1] / size[0]))), cv2.COLOR_BGR2GRAY)
            grid = None
            if prev is not None:
                fl = cv2.calcOpticalFlowFarneback(prev, small, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                fl = fl - np.median(fl.reshape(-1, 2), axis=0)  # camera motion out
                mag = np.hypot(fl[..., 0], fl[..., 1])
                grid = cv2.resize(mag, (GW, GH), interpolation=cv2.INTER_AREA)
                grid = np.round(grid, 2).tolist()
            prev = small
            frames.append([round(f.t_ms, 1), boxes, grid])
        res[i] = dict(size=size, frames=frames)
    out.write_text(json.dumps(res))
    print(clip, len(v["spans"]), round(time.time() - t0), "s")


def cells(box, size):
    """Grid cell ranges of a box (x1, y1, x2, y2) in frame pixels."""
    w, h = size
    x1, x2 = int(np.clip(box[0] / w * GW, 0, GW - 1)), int(np.clip(np.ceil(box[2] / w * GW), 1, GW))
    y1, y2 = int(np.clip(box[1] / h * GH, 0, GH - 1)), int(np.clip(np.ceil(box[3] / h * GH), 1, GH))
    return x1, max(x2, x1 + 1), y1, max(y2, y1 + 1)


def candidates(boxes, size):
    """Female-part boxes of a frame: {name: (box, confidence)} (the most confident per name)."""
    best = {}
    for b, lab, c in boxes:
        if lab == "pussy" and c >= 0.2:
            name, box = "pussy", b
        elif lab == "nipple_f" and c >= 0.2:
            name, box = "nipple_f", b
        elif lab == "hand" and c >= 0.3:
            name, box = "hand", b
        elif lab == "head" and c >= 0.3:  # mouth: lower-middle of the head box
            w, h = b[2] - b[0], b[3] - b[1]
            name, box = "mouth", [b[0] + 0.25 * w, b[1] + 0.6 * h, b[2] - 0.25 * w, b[3] - 0.05 * h]
        else:
            continue
        if name not in best or c > best[name][1]:
            best[name] = (box, c)
    return best


def has_penis(boxes):
    return any(lab == "penis" and c >= 0.238 for _, lab, c in boxes)


def anchor_series(frames, size, tie, mode):
    """Per frame the anchor part's centre and the interaction object's centre (flow-weighted centre of the strongest
    cells around the anchor); returns (times, distance per frame (NaN where unknown), names used)."""
    gx, gy = np.meshgrid((np.arange(GW) + 0.5) / GW, (np.arange(GH) + 0.5) / GH)
    t = np.array([f[0] for f in frames])
    dist = np.full(len(frames), np.nan)
    used = Counter()
    for k, (_, boxes, grid) in enumerate(frames):
        if grid is None:
            continue
        cand = candidates(boxes, size)
        if not cand:
            continue
        g = np.array(grid)
        score = {}
        for name, (box, _) in cand.items():
            x1, x2, y1, y2 = cells(box, size)
            score[name] = float(g[y1:y2, x1:x2].mean())
        if mode == "priority":
            name = next(n for n in PRIORITY if n in cand)
        else:
            order = sorted(score, key=lambda n: -score[n])
            top = score[order[0]]
            near = [n for n in PRIORITY if n in score and score[n] >= top * (1 - tie)]
            name = near[0]
        box = cand[name][0]
        ax, ay = (box[0] + box[2]) / 2 / size[0], (box[1] + box[3]) / 2 / size[1]
        # the interaction object: strongest cells within 0.35 of the frame diagonal (in width units) of the anchor
        near = np.hypot((gx - ax) * size[0], (gy - ay) * size[1]) < 0.35 * np.hypot(*size)
        gm = np.where(near, g, 0)
        if gm.max() < 0.3:
            continue
        sel = gm >= np.quantile(gm[near], 0.9)
        wgt = gm * sel
        ox, oy = (gx * wgt).sum() / wgt.sum(), (gy * wgt).sum() / wgt.sum()
        dist[k] = np.hypot((ox - ax) * size[0], (oy - ay) * size[1]) / np.hypot(*size)
        used[name] += 1
    return t, dist, used


def evaluate(run: Path, det_dir: Path, tie: float) -> None:
    import sign_vote
    from body_sign import HOWS, cue

    rows, results = sign_vote.load(run)
    dets = {p.stem: json.loads(p.read_text()) for p in det_dir.glob("*.json")}
    plans = {clip.name: {p.scene.index: p for p in res.plans} for clip, res, _, _ in results}
    names = []
    for mode in ("flow", "priority"):
        for how in HOWS:
            names.append(f"fa_{mode}_{how}")
    used_all = Counter()
    nopen_scenes = 0
    for r in rows:
        det = dets.get(r["clip"], {}).get(str(r["index"]))
        if det is None or len(det["frames"]) < 20:
            continue
        frames = [f for f in det["frames"]]
        pen = np.mean([has_penis(f[1]) for f in frames])
        if pen >= 0.5:  # the penis box exists: the part check's job
            continue
        nopen_scenes += 1
        p = plans[r["clip"]][r["index"]]
        ft, fx = p.flow_position
        for mode in ("flow", "priority"):
            t, d, used = anchor_series(frames, det["size"], tie, mode)
            if mode == "flow":
                used_all.update(used)
            for how in HOWS:
                c = cue(t, d, ft, fx, how)
                if c is not None:
                    r["cue"][f"fa_{mode}_{how}"] = c
    print(f"scenes without a penis box: {nopen_scenes}; anchors used (frames): {dict(used_all)}")
    sign_vote.CUES = sign_vote.CUES + tuple(names)
    gs = sign_vote.groups(rows)

    for key in names:
        print(f"\n== {key}: per labelled group (truth = script; flip when cue <= -th)")
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
                    line += f" | th {th}: flip-only +{fix}/-{brk}"
                print(line)
    cur = {id(g) for g in gs if g["current"]}
    print()
    sign_vote.line("current rule", gs, results, cur)
    for key in names:
        for th in (0.2, 0.4):
            flips = cur | {id(g) for g in gs if g["cue"].get(key, 0) <= -th}
            sign_vote.line(f"{key} th{th} flip-only", gs, results, flips)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("dump"); p.add_argument("targets", type=Path); p.add_argument("clip"); p.add_argument("out", type=Path)
    p = sub.add_parser("eval"); p.add_argument("run", type=Path); p.add_argument("dets", type=Path)
    p.add_argument("--tie", type=float, default=0.25)
    a = ap.parse_args()
    if a.cmd == "dump":
        dump(a.targets, a.clip, a.out)
    else:
        evaluate(a.run, a.dets, a.tie)


if __name__ == "__main__":
    main()
