"""Offline: does a segmentation mask of the penis (SAM2 video, prompted with the part check's boxes) follow the strokes
better than the boxes themselves? The visible part of the penis shrinks as it goes in, so the mask could give the
direction and the depth of each stroke where the flow cannot (PLAN, open issues 1 and 2). Result (2026-11-02): the
masks follow the hand-made scripts closer than the boxes, but no use of them raised the scores; see PLAN.

  jobs RUN [RUN ...] -o JOBS.json
      (dev machine) the scenes with part boxes (ScenePlan.parts_found, 10 fps) in the default settings' saved
      analyses of dev and test: frame times and boxes
  dump JOBS.json OUT_DIR [--clips A,B] [--model facebook/sam2.1-hiera-small]
      (GPU host; needs torch and transformers) per scene, SAM2 tracks the penis and the vulva separately, each
      prompted once a second with the most confident box of that label; per frame the mask's area, centre, length
      and width along its main axis. OUT_DIR/<clip>.json
  eval RUN [RUN ...] --masks DIR
      (dev machine) the mask and box features against the hand-made script and the default output: correlation,
      sign consistency, the direction rule of the part check, and the size of each stroke

RUN: `validate` runs with saved analyses of the default settings (the first that has a clip is used; analyses saved
on the Windows host load too).
"""
import argparse
import json
import math
import pathlib
import sys
import time
from pathlib import Path

import numpy as np

if sys.platform != "win32":
    pathlib.WindowsPath = pathlib.PureWindowsPath  # analyses saved on the second test host keep their Windows paths

FPS = 10.0  # PipelineOptions.part_fps: the boxes' frames
DECODE_SIDE = 960  # tracking.parts.DECODE_SIDE
PROMPT_CONF = 0.238  # the detector's recommended threshold; the part check detects at 0.15
PROMPT_EVERY = 10  # frames: one prompt per second and label
LABELS = {"penis": 1, "pussy": 2}
MIN_COVER = 0.6
MIN_R = 0.3


def find(runs: list[Path], name: str):
    from funscript_gen.cli import parse_generate_args
    from funscript_gen.options import BY_NAME, analysis_key, resolve
    from funscript_gen.pipeline import load_analysis

    given, preset = parse_generate_args([])
    want = analysis_key(resolve(given, preset))
    for run in runs:
        for path in sorted(run.glob(f"*/{name}.analysis.pkl")):
            analysis = load_analysis(path)
            if all(analysis.key.get(k, BY_NAME[k].default) == v for k, v in want.items()):
                return analysis
    return None


def jobs(args) -> None:
    from funscript_gen.validate import clips, load_manifest

    out = {}
    for clip in clips(load_manifest(), "dev,test"):
        analysis = find([Path(r) for r in args.runs], clip.name)
        if analysis is None:
            print(f"{clip.name}: no analysis")
            continue
        scenes = []
        for plan in analysis.plans:
            if plan.parts_found is None:
                continue
            times, boxes, size = plan.parts_found
            scenes.append(dict(index=plan.scene.index, start_ms=plan.scene.start_ms, end_ms=plan.scene.end_ms,
                               t=list(times), size=list(size),
                               boxes=[[[*map(float, b), lab, float(c)] for b, lab, c in f] for f in boxes]))
        if scenes:
            out[clip.name] = scenes
        print(f"{clip.name}: {len(scenes)} scenes with part boxes")
    Path(args.output).write_text(json.dumps(out))


def prompts(boxes: list, label: str) -> list[tuple[int, list[float]]]:
    """(frame, box): the most confident box of `label` in each PROMPT_EVERY frames, at PROMPT_CONF or more."""
    found = []
    for start in range(0, len(boxes), PROMPT_EVERY):
        best = None
        for i in range(start, min(start + PROMPT_EVERY, len(boxes))):
            for x1, y1, x2, y2, lab, conf in boxes[i]:
                if lab == label and conf >= PROMPT_CONF and (best is None or conf > best[2]):
                    best = (i, [x1, y1, x2, y2], conf)
        if best is not None:
            found.append(best[:2])
    return found


def mask_features(mask, diag: float) -> list[float | None]:
    """area share, centre x, y (share of the width / height), length and width along the main axis (share of the
    diagonal) of a boolean H x W mask; None without one."""
    import torch

    h, w = mask.shape
    ys, xs = torch.nonzero(mask, as_tuple=True)
    if len(xs) < 20:
        return [None] * 5
    p = torch.stack([xs, ys], 1).float()
    c = p.mean(0)
    q = p - c
    _, vecs = torch.linalg.eigh(q.T @ q / len(q))
    major, minor = q @ vecs[:, 1], q @ vecs[:, 0]
    qs = torch.tensor([0.05, 0.95], device=p.device)
    if len(q) > 200_000:  # torch.quantile's limit is 16M; keep it quick
        major, minor = major[:: len(q) // 200_000], minor[:: len(q) // 200_000]
    lo, hi = torch.quantile(major, qs)
    lo2, hi2 = torch.quantile(minor, qs)
    return [len(xs) / (h * w), float(c[0]) / w, float(c[1]) / h, float(hi - lo) / diag, float(hi2 - lo2) / diag]


def track(model, processor, frames: list[np.ndarray], marks: list[tuple[int, list[float]]], dtype) -> list:
    """Per frame the features of the mask SAM2 tracks from the prompt boxes `marks` (None where it lost it)."""
    import torch

    h, w = frames[0].shape[:2]
    diag = math.hypot(w, h)
    # The 8 GB of the RTX 3070 (the owner uses 2-3 GB) spill into shared memory, 10x slower, with the frames
    # processed on the GPU or the state of a 200-frame scene kept there: both stay on the CPU.
    session = processor.init_video_session(video=frames, inference_device="cuda", inference_state_device="cpu",
                                           video_storage_device="cpu", dtype=dtype)
    for f, box in marks:
        processor.add_inputs_to_inference_session(inference_session=session, frame_idx=f, obj_ids=1,
                                                  input_boxes=[[box]])
        model(inference_session=session, frame_idx=f)
    feats: list = [[None] * 5 for _ in frames]
    first = marks[0][0]
    for reverse in (False, True):
        if reverse and first == 0:
            break
        for out in model.propagate_in_video_iterator(session, start_frame_idx=first, reverse=reverse):
            masks = processor.post_process_masks([out.pred_masks], original_sizes=[[h, w]], binarize=True)[0]
            feats[out.frame_idx] = mask_features(masks[0, 0], diag)
    del session
    torch.cuda.empty_cache()
    return feats


def dump(args) -> None:
    import torch
    from transformers import Sam2VideoModel, Sam2VideoProcessor

    from funscript_gen.validate import clips, load_manifest
    from funscript_gen.video.decoder import iter_frames

    torch.set_num_threads(4)
    dtype = torch.bfloat16
    model = Sam2VideoModel.from_pretrained(args.model).to("cuda", dtype=dtype)
    processor = Sam2VideoProcessor.from_pretrained(args.model)
    work = json.loads(Path(args.jobs).read_text())
    wanted = set(args.clips.split(",")) if args.clips else set(work)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    for name, scenes in work.items():
        path = out_dir / f"{name}.json"
        if name not in wanted or path.exists():
            continue
        video = clips(manifest, name)[0].video
        t0, n = time.time(), 0
        result = []
        for sc in scenes:
            times, frames = [], []
            for f in iter_frames(video, target_fps=FPS, max_side=DECODE_SIDE, start_ms=sc["start_ms"],
                                 end_ms=sc["end_ms"]):
                if f.t_ms >= sc["end_ms"]:
                    break
                times.append(f.t_ms)
                frames.append(np.ascontiguousarray(f.image[:, :, ::-1]))  # RGB
            if len(times) != len(sc["t"]) or max(abs(a - b) for a, b in zip(times, sc["t"])) > 1:
                print(f"{name} scene {sc['index']}: frames differ from the boxes' ({len(times)}, {len(sc['t'])})")
                continue
            row = dict(index=sc["index"], start_ms=sc["start_ms"], end_ms=sc["end_ms"], t=times,
                       size=[frames[0].shape[1], frames[0].shape[0]])
            for label in LABELS:
                marks = prompts(sc["boxes"], label)
                row[label + "_prompts"] = [f for f, _ in marks]
                row[label] = track(model, processor, frames, marks, dtype) if marks else None
            result.append(row)
            n += len(frames)
            print(f"  {name} scene {sc['index']}: {len(frames)} frames, {time.time() - t0:.0f} s", flush=True)
        path.write_text(json.dumps(dict(clip=name, fps=FPS, scenes=result)))
        print(f"{name}: {len(result)} scenes, {n} frames, {time.time() - t0:.0f} s", flush=True)


# --- eval ---

def detrend(x: np.ndarray, fps: float = FPS, win_s: float = 2.0) -> np.ndarray:
    k = max(3, int(win_s * fps) | 1)
    return x - np.convolve(np.pad(x, k // 2, mode="edge"), np.ones(k) / k, mode="valid")


def corr(x: np.ndarray, y: np.ndarray, max_lag: int = 0) -> float | None:
    """The correlation with the largest |r| over lags -max_lag..max_lag (keeps the sign)."""
    best = None
    for lag in range(-max_lag, max_lag + 1):
        a, b = (x[lag:], y[: len(y) - lag]) if lag >= 0 else (x[:lag], y[-lag:])
        if len(a) > 10 and a.std() > 1e-9 and b.std() > 1e-9:
            r = float(np.corrcoef(a, b)[0, 1])
            if best is None or abs(r) > abs(best):
                best = r
    return best


def box_series(boxes: list, size) -> dict:
    """The part check's box features per frame (as scripts/censor_sign.py): the most confident penis box's long
    side and area, its centre's distance to the nearest vulva box (shares of the diagonal)."""
    w, h = size
    diag = math.hypot(w, h)
    out = {k: np.full(len(boxes), np.nan) for k in ("box_len", "box_area", "box_dist")}
    for i, f in enumerate(boxes):
        pen = [b for b in f if b[4] == "penis"]
        if not pen:
            continue
        x1, y1, x2, y2 = max(pen, key=lambda b: b[5])[:4]
        out["box_len"][i] = max(x2 - x1, y2 - y1) / diag
        out["box_area"][i] = (x2 - x1) * (y2 - y1) / diag**2
        pus = [b for b in f if b[4] == "pussy"]
        if pus:
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            out["box_dist"][i] = min(math.hypot(cx - (b[0] + b[2]) / 2, cy - (b[1] + b[3]) / 2) for b in pus) / diag
    return out


def mask_series(row: dict) -> dict:
    w, h = row["size"]
    diag = math.hypot(w, h)
    n = len(row["t"])

    def col(label, k):
        feats = row.get(label)
        return np.array([np.nan if f[k] is None else f[k] for f in feats], float) if feats else np.full(n, np.nan)

    out = {"mask_area": col("penis", 0), "mask_len": col("penis", 3)}
    px, py, vx, vy = col("penis", 1) * w, col("penis", 2) * h, col("pussy", 1) * w, col("pussy", 2) * h
    out["mask_dist"] = np.hypot(px - vx, py - vy) / diag
    return out


# A longer visible penis, a larger one, or the penis farther from the vulva = pulled out = high in the script.
FEATS = ["box_len", "box_area", "box_dist", "mask_len", "mask_area", "mask_dist"]


def curve(actions, t: np.ndarray) -> np.ndarray:
    return np.interp(t, [a.at for a in actions], [a.pos for a in actions])


def turning_kind(pos: np.ndarray) -> np.ndarray:
    """+1 at a peak (not below either neighbour), else -1."""
    prev, nxt = np.r_[pos[1:2], pos[:-1]], np.r_[pos[1:], pos[-2:-1]]
    return np.where(pos >= np.maximum(prev, nxt), 1, -1)


def turning(pos: np.ndarray) -> np.ndarray:
    prev, nxt = np.r_[pos[1:2], pos[:-1]], np.r_[pos[1:], pos[-2:-1]]
    return (pos >= np.maximum(prev, nxt)) | (pos <= np.minimum(prev, nxt))


def evaluate(args) -> None:
    from funscript_gen.cli import parse_generate_args
    from funscript_gen.export.funscript import Funscript
    from funscript_gen.options import build, for_analysis
    from funscript_gen.pipeline import render
    from funscript_gen.validate import clips, load_manifest

    given, preset = parse_generate_args([])
    rows = []  # one per scene
    scored = []  # one per clip, with or without masks: the group means are over all of them
    for clip in clips(load_manifest(), "dev,test"):
        path = Path(args.masks) / f"{clip.name}.json"
        analysis = find([Path(r) for r in args.runs], clip.name)
        res = render(analysis, build(for_analysis(analysis.key, given, preset)))
        out_acts = res.funscript.normalized().actions
        ref = Funscript.load(clip.reference)
        ref_acts = ref.normalized().actions
        plans = {p.scene.index: p for p in res.plans}
        recs = []
        scored.append(dict(group=clip.group, ref=ref, acts=out_acts, recs=recs, analysis=analysis))
        for row in (json.loads(path.read_text())["scenes"] if path.exists() else []):
            plan = plans[row["index"]]
            t = np.array(row["t"])
            y_ref, y_out = detrend(curve(ref_acts, t)), detrend(curve(out_acts, t))
            r_out = corr(y_out, y_ref)
            boxes = [[[*b, lab, c] for b, lab, c in f] for f in plan.parts_found[1]]
            feats = {**box_series(boxes, plan.parts_found[2]), **mask_series(row)}
            rec = dict(clip=clip.name, group=clip.group, s=row["start_ms"] / 1000, sec=len(t) / FPS, r_out=r_out,
                       note=plan.note, index=row["index"], start_ms=row["start_ms"], end_ms=row["end_ms"], _t=t,
                       _x={})
            recs.append(rec)
            # strokes: the output's turning points in this scene
            at = np.array([a.at for a in out_acts if row["start_ms"] <= a.at < row["end_ms"]], float)
            pos = np.array([a.pos for a in out_acts if row["start_ms"] <= a.at < row["end_ms"]], float)
            for name, x in feats.items():
                ok = ~np.isnan(x)
                rec[name + "_cov"] = ok.mean()
                if ok.mean() < MIN_COVER or y_ref.std() < 1:
                    continue
                xi = np.interp(t, t[ok], x[ok])
                xd = detrend(xi)
                rec["_x"][name] = xi
                rec[name] = corr(xd, y_ref, 1)
                rec[name + "_out"] = corr(xd, y_out)
                if len(at) >= 8 and r_out is not None and r_out >= MIN_R:
                    keep = turning(pos)
                    a2, p2 = at[keep], pos[keep]
                    d_ref = np.abs(np.diff(curve(ref_acts, a2)))
                    d_out, d_feat = np.abs(np.diff(p2)), np.abs(np.diff(np.interp(a2, t, xi)))
                    if d_ref.std() > 1e-6 and d_out.std() > 1e-6 and d_feat.std() > 1e-12:
                        rec[name + "_size"] = float(np.corrcoef(d_feat, d_ref)[0, 1])
                        rec["out_size"] = float(np.corrcoef(d_out, d_ref)[0, 1])
            rows.append(rec)
    print_scenes(rows)
    print_scores(scored)


def variant(acts, recs: list, feat: str, mode: str):
    """The output with the scenes the feature follows (|corr| >= 0.2) changed: "flip" mirrors those it moves
    against; "pos" also sets the positions to the feature (higher = pulled out = high; drift over 4 s removed),
    mapped to the scene's output range; "size" sets them to the feature turned to agree with the output (only the
    stroke sizes change, not the direction). The action times stay."""
    from funscript_gen.export.funscript import Action, Funscript

    at = np.array([a.at for a in acts], float)
    pos = np.array([a.pos for a in acts], float)
    for r in recs:
        c = r.get(feat + "_out")
        m = (at >= r["start_ms"]) & (at < r["end_ms"])
        if c is None or abs(c) < 0.2 or m.sum() < 4:
            continue
        lo, hi = pos[m].min(), pos[m].max()
        if mode == "flip":
            if c < 0:
                pos[m] = lo + hi - pos[m]
            continue
        # the output's turning points are a little off the stroke's ends: a peak takes the feature's highest value
        # within +-150 ms, a trough its lowest, after the flip rule (a mirrored peak is a trough)
        x, t = detrend(r["_x"][feat], win_s=4.0), r["_t"]
        idx = np.flatnonzero(m)
        peak = turning_kind(pos[idx]) * (1 if c > 0 or mode == "size" else -1)
        if mode == "size":
            x = np.sign(c) * x
        v = np.array([(np.max if k > 0 else np.min)(x[np.abs(t - a) <= 150]) if np.any(np.abs(t - a) <= 150)
                      else np.interp(a, t, x) for a, k in zip(at[idx], peak)])
        p5, p95 = np.percentile(x, 5), np.percentile(x, 95)
        if p95 - p5 > 1e-12:
            pos[idx] = lo + (hi - lo) * np.clip((v - p5) / (p95 - p5), 0, 1)
    return Funscript([Action(int(a), int(round(p))) for a, p in zip(at, pos)])


SOURCE_PX = math.hypot(480, 270)  # a share of the diagonal in pixels of the flow's frame (flow_width 480)


def source_variant(analysis, recs: list, feat: str, keep: bool = False):
    """The default render with the source of the scenes the feature follows (|corr| >= 0.2 with the output) set to
    the feature (higher = pulled out = high; with `keep` turned to agree with the output) instead of the flow. Their
    sign is final: no chunk alignment, part or asymmetry check (they need flow_position), no region pick."""
    import copy

    from funscript_gen.cli import parse_generate_args
    from funscript_gen.options import build, for_analysis
    from funscript_gen.pipeline import render

    a = copy.deepcopy(analysis)
    by_index = {p.scene.index: p for p in a.plans}
    for r in recs:
        c = r.get(feat + "_out")
        if c is None or abs(c) < 0.2:
            continue
        plan = by_index[r["index"]]
        plan.source = (r["_t"], r["_x"][feat] * SOURCE_PX * (np.sign(c) if keep else 1))
        plan.flow_position = plan.sign_pattern = plan.pick_source = None
    given, preset = parse_generate_args([])
    return render(a, build(for_analysis(a.key, given, preset))).funscript.normalized()


def print_scores(scored: list) -> None:
    from funscript_gen.evaluate import compare, drop_wiggles
    from funscript_gen.export.funscript import Funscript

    print("\nwhole clips, mean F1 / F1s / r (all clips of the group; the output changed only in scenes with masks)")
    tries = [("output", None, None)] + [(f"{m} {f}", f, m) for m in ("flip", "pos", "size")
                                         for f in ("box_dist", "mask_len", "mask_area", "mask_dist")]
    tries += [(f"{m} {f}", f, m) for m in ("src", "srckeep") for f in ("mask_len", "mask_area", "mask_dist")]
    for group in ("dev", "test"):
        g = [c for c in scored if c["group"] == group]
        for label, feat, mode in tries:
            s = []
            for c in g:
                if feat is None:
                    pred = Funscript(list(c["acts"]))
                elif mode.startswith("src"):
                    pred = source_variant(c["analysis"], c["recs"], feat, keep=mode == "srckeep")
                else:
                    pred = variant(c["acts"], c["recs"], feat, mode)
                a, b = compare(c["ref"], pred), compare(drop_wiggles(c["ref"]), pred)
                s.append((a.f1, b.f1, a.correlation))
            f1, f1s, r = np.mean(s, axis=0)
            print(f"{group:5}{len(g):3}  {label:16}{f1:.3f} / {f1s:.3f} / {r:.3f}")


def print_scenes(rows: list) -> None:
    print(f"{'clip':8}{'s':>5}{'sec':>5}{'r_out':>7}" + "".join(f"{f:>10}" for f in FEATS) + "  (cover / r with the script)")
    for r in rows:
        cells = "".join(f"{r[f + '_cov']:5.0%}{r[f]:+5.2f}" if f in r else f"{r[f + '_cov']:5.0%}{'-':>5}"
                        for f in FEATS)
        ro = f"{r['r_out']:+7.2f}" if r["r_out"] is not None else f"{'-':>7}"
        print(f"{r['clip']:8}{r['s']:5.0f}{r['sec']:5.0f}{ro}{cells}  {r['note']}")

    for group in ("dev", "test"):
        g = [r for r in rows if r["group"] == group]
        print(f"\n== {group}: {len(g)} scenes with part boxes, {sum(r['sec'] for r in g):.0f} s")
        known = [r for r in g if r["r_out"] is not None and abs(r["r_out"]) >= MIN_R]
        right = sum(r["r_out"] > 0 for r in known)
        print(f"default output: right direction in {right}/{len(known)} scenes with |r| >= {MIN_R}")
        print(f"{'feature':10}{'scenes':>7}{'med|r|':>8}{'|r|>=.5':>8}{'r>=.3':>7}{'r<=-.3':>7}"
              f"{'rule ok':>9}{'fixes':>6}{'breaks':>7}{'size r':>8}{'out':>6}")
        for f in FEATS:
            have = [r for r in g if f in r and r[f] is not None]
            rs = np.array([r[f] for r in have])
            # the part check's rule: flip the output when the feature moves against it (corr < 0)
            ruled = [r for r in known if f in r and r[f + "_out"] is not None and abs(r[f + "_out"]) >= 0.2]
            ok = sum((r[f + "_out"] > 0) == (r["r_out"] > 0) for r in ruled)
            fixes = sum(r[f + "_out"] < 0 and r["r_out"] < 0 for r in ruled)
            breaks = sum(r[f + "_out"] < 0 and r["r_out"] > 0 for r in ruled)
            sz = [(r[f + "_size"], r["out_size"]) for r in g if f + "_size" in r]
            med_sz = f"{np.median([a for a, _ in sz]):+8.2f}{np.median([b for _, b in sz]):+6.2f}" if sz else ""
            print(f"{f:10}{len(have):7}{np.median(np.abs(rs)) if len(rs) else 0:8.2f}{(np.abs(rs) >= .5).sum():8}"
                  f"{(rs >= MIN_R).sum():7}{(rs <= -MIN_R).sum():7}{ok:5}/{len(ruled):<3}{fixes:6}{breaks:7}{med_sz}"
                  f"  ({len(sz)})")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("jobs")
    j.add_argument("runs", nargs="+")
    j.add_argument("-o", "--output", required=True)
    d = sub.add_parser("dump")
    d.add_argument("jobs")
    d.add_argument("out")
    d.add_argument("--clips", default="")
    d.add_argument("--model", default="facebook/sam2.1-hiera-small")
    e = sub.add_parser("eval")
    e.add_argument("runs", nargs="+")
    e.add_argument("--masks", required=True)
    args = p.parse_args()
    {"jobs": jobs, "dump": dump, "eval": evaluate}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
