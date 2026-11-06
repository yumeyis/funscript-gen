"""Offline: does occlusion at the contact point give the stroke direction? Going in, the penis's pixels vanish at
the vulva's (or mouth's) edge; pulling out, new pixels appear there. A forward-backward consistency check of the
optical flow marks both: pixels of frame t with no match in frame t+1 (occluded) and pixels of t+1 with no match in
t (disoccluded). Summed over time, disoccluded minus occluded follows the visible length: high = pulled out.

  dump RUN [RUN ...] OUT_DIR [--clips A,B] [-j 6]
      per clip in dev and test, per scene with actions: forward and backward Farneback flow at 30 fps on the
      480-wide frame (as the analysis), occluded and disoccluded pixels per 8 px cell. OUT_DIR/<clip>.npz
  eval RUN [RUN ...] --occ DIR
      per scene and region (AI region, vulva box, penis box, whole frame), the occlusion cue against the
      hand-made script and the default output: how often it gives the direction right

RUN: `validate` runs with saved analyses of the default settings (as scripts/mask_depth.py).
"""
import argparse
import math
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

if sys.platform != "win32":
    pathlib.WindowsPath = pathlib.PureWindowsPath

sys.path.insert(0, str(Path(__file__).parent))
from mask_depth import corr, curve, detrend, find  # noqa: E402

FPS = 30.0
WIDTH = 480
CELL = 8
MIN_R = 0.3


def occlusion(fwd: np.ndarray, bwd: np.ndarray) -> np.ndarray:
    """Pixels of the frame `fwd` starts from whose match does not come back (Sundaram et al. 2010's check)."""
    import cv2

    h, w = fwd.shape[:2]
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    mx, my = gx + fwd[..., 0], gy + fwd[..., 1]
    back = cv2.remap(bwd, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    err = ((fwd + back) ** 2).sum(-1)
    bound = 0.01 * ((fwd**2).sum(-1) + (back**2).sum(-1)) + 0.5
    outside = (mx < 0) | (mx > w - 1) | (my < 0) | (my > h - 1)
    return (err > bound) & ~outside


def pool(mask: np.ndarray) -> np.ndarray:
    hc, wc = mask.shape[0] // CELL, mask.shape[1] // CELL
    return mask[: hc * CELL, : wc * CELL].reshape(hc, CELL, wc, CELL).sum(axis=(1, 3)).astype(np.uint8)


def dump_clip(job: tuple[str, str, list, str]) -> str:
    import cv2

    from funscript_gen.tracking.flow import FARNEBACK
    from funscript_gen.video.decoder import iter_frames

    cv2.setNumThreads(1)
    name, video, scenes, out = job
    arrays = {}
    for index, start, end in scenes:
        prev, ts, occ, dis = None, [], [], []
        for f in iter_frames(video, target_fps=FPS, max_side=640, start_ms=start, end_ms=end):
            if f.t_ms >= end:
                break
            h = round(f.image.shape[0] * WIDTH / f.image.shape[1])
            gray = cv2.cvtColor(cv2.resize(f.image, (WIDTH, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            if prev is not None:
                fwd = cv2.calcOpticalFlowFarneback(prev, gray, None, *FARNEBACK)
                bwd = cv2.calcOpticalFlowFarneback(gray, prev, None, *FARNEBACK)
                ts.append(f.t_ms)
                occ.append(pool(occlusion(fwd, bwd)))  # in frame t, gone in t+1
                dis.append(pool(occlusion(bwd, fwd)))  # in frame t+1, not in t
            prev = gray
        if ts:
            arrays[f"t{index}"] = np.array(ts)
            arrays[f"o{index}"] = np.stack(occ)
            arrays[f"d{index}"] = np.stack(dis)
    np.savez_compressed(out, **arrays)
    return f"{name}: {len(scenes)} scenes"


def dump(args) -> None:
    from funscript_gen.validate import clips, load_manifest

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = set(args.clips.split(",")) if args.clips else None
    work = []
    for clip in clips(load_manifest(), "dev,test"):
        out = out_dir / f"{clip.name}.npz"
        if (wanted and clip.name not in wanted) or out.exists():
            continue
        analysis = find([Path(r) for r in args.runs], clip.name)
        if analysis is None:
            print(f"{clip.name}: no analysis")
            continue
        scenes = [(p.scene.index, p.scene.start_ms, p.scene.end_ms) for p in analysis.plans if p.source is not None]
        work.append((clip.name, str(clip.video), scenes, str(out)))
    with ProcessPoolExecutor(args.jobs) as ex:
        for msg in ex.map(dump_clip, work):
            print(msg, flush=True)


# --- eval ---

def box_region(parts_found, label: str, grow: float) -> tuple | None:
    """The median box of `label` (normalized), each side grown by `grow` of its size; None without one."""
    if parts_found is None:
        return None
    _, boxes, (w, h) = parts_found
    found = [max((b for b in f if b[1] == label), key=lambda b: b[2])[0] for f in boxes if any(b[1] == label for b in f)]
    if len(found) < 5:
        return None
    x1, y1, x2, y2 = np.median(np.array(found, float), axis=0)
    gx, gy = (x2 - x1) * grow, (y2 - y1) * grow
    return (max(0, (x1 - gx) / w), max(0, (y1 - gy) / h), min(1, (x2 + gx) / w), min(1, (y2 + gy) / h))


def cue(o: np.ndarray, d: np.ndarray, roi) -> np.ndarray:
    """Disoccluded minus occluded pixels in `roi`, summed over time: the visible length (high = pulled out)."""
    rows, cols = o.shape[1:]
    x1, y1, x2, y2 = roi
    ys = slice(int(y1 * rows), max(int(y1 * rows) + 1, math.ceil(y2 * rows)))
    xs = slice(int(x1 * cols), max(int(x1 * cols) + 1, math.ceil(x2 * cols)))
    net = d[:, ys, xs].astype(float).sum(axis=(1, 2)) - o[:, ys, xs].astype(float).sum(axis=(1, 2))
    return np.cumsum(net)


REGIONS = ["roi", "pussy", "pussy2", "penis", "full"]


def evaluate(args) -> None:
    from funscript_gen.cli import parse_generate_args
    from funscript_gen.export.funscript import Funscript
    from funscript_gen.options import build, for_analysis
    from funscript_gen.pipeline import render
    from funscript_gen.validate import clips, load_manifest

    given, preset = parse_generate_args([])
    rows = []
    for clip in clips(load_manifest(), "dev,test"):
        path = Path(args.occ) / f"{clip.name}.npz"
        if not path.exists():
            continue
        data = np.load(path)
        analysis = find([Path(r) for r in args.runs], clip.name)
        res = render(analysis, build(for_analysis(analysis.key, given, preset)))
        out_acts = res.funscript.normalized().actions
        ref_acts = Funscript.load(clip.reference).normalized().actions
        for plan in res.plans:
            i = plan.scene.index
            if f"t{i}" not in data or plan.skip:
                continue
            t, o, d = data[f"t{i}"], data[f"o{i}"], data[f"d{i}"]
            if len(t) < 30:
                continue
            y_ref = detrend(curve(ref_acts, t), FPS)
            y_out = detrend(curve(out_acts, t), FPS)
            if y_ref.std() < 1 or y_out.std() < 1:
                continue
            roi = plan.pick_roi if plan.pick_name and plan.pick_roi else plan.roi
            regions = {"roi": roi or (0, 0, 1, 1), "full": (0, 0, 1, 1),
                       "pussy": box_region(plan.parts_found, "pussy", 0.25),
                       "pussy2": box_region(plan.parts_found, "pussy", 1.0),
                       "penis": box_region(plan.parts_found, "penis", 0.25)}
            evidence = ("part" if plan.part_flipped or plan.part_sign is not None and abs(plan.part_sign) >= 0.2
                        else "asym" if plan.asym_flipped else "none")
            rec = dict(clip=clip.name, group=clip.group, index=i, sec=len(t) / FPS, r_out=corr(y_out, y_ref),
                       evidence=evidence)
            for name, region in regions.items():
                if region is None:
                    continue
                x = detrend(cue(o, d, region), FPS)
                if x.std() < 1e-9:
                    continue
                rec[name] = corr(x, y_out)
                rec[name + "_ref"] = corr(x, y_ref, 3)
            rows.append(rec)
    report(rows)


def report(rows: list) -> None:
    for group in ("dev", "test"):
        g = [r for r in rows if r["group"] == group and r["r_out"] is not None and abs(r["r_out"]) >= MIN_R]
        right = sum(r["r_out"] > 0 for r in g)
        print(f"\n== {group}: {len(g)} scenes with |r_out| >= {MIN_R}, output right in {right}"
              f" ({sum(r['sec'] for r in g):.0f} s)")
        print(f"{'region':8}{'th':>5}{'used':>6}{'agree':>7}{'acc':>6}{'fixes':>7}{'breaks':>8}{'acc none':>10}"
              f"{'med|r_ref|':>12}")
        for name in REGIONS:
            have = [r for r in g if r.get(name) is not None]
            med = np.median([abs(r[name + "_ref"]) for r in have if r.get(name + "_ref") is not None] or [0])
            for th in (0.0, 0.2, 0.4):
                used = [r for r in have if abs(r[name]) >= th]
                agree = sum((r[name] > 0) == (r["r_out"] > 0) for r in used)
                fixes = sum(r[name] < 0 and r["r_out"] < 0 for r in used)
                breaks = sum(r[name] < 0 and r["r_out"] > 0 for r in used)
                none = [r for r in used if r["evidence"] == "none"]
                acc_none = sum((r[name] > 0) == (r["r_out"] > 0) for r in none)
                print(f"{name:8}{th:5.1f}{len(used):6}{agree:7}{agree / max(1, len(used)):6.0%}{fixes:7}{breaks:8}"
                      f"{acc_none:5}/{len(none):<4}{med:12.2f}")
    if rows and "-v" in sys.argv:
        print(f"\n{'clip':6}{'#':>4}{'sec':>5}{'r_out':>7}{'evid':>6}" + "".join(f"{n:>8}" for n in REGIONS))
        for r in rows:
            cells = "".join(f"{r[n]:+8.2f}" if r.get(n) is not None else f"{'-':>8}" for n in REGIONS)
            ro = f"{r['r_out']:+7.2f}" if r["r_out"] is not None else f"{'-':>7}"
            print(f"{r['clip']:6}{r['index']:4}{r['sec']:5.0f}{ro}{r['evidence']:>6}{cells}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("runs", nargs="+")
    d.add_argument("out")
    d.add_argument("--clips", default="")
    d.add_argument("-j", "--jobs", type=int, default=6)
    e = sub.add_parser("eval")
    e.add_argument("runs", nargs="+")
    e.add_argument("--occ", required=True)
    e.add_argument("-v", action="store_true")
    args = p.parse_args()
    {"dump": dump, "eval": evaluate}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
