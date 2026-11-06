"""Offline: does a monocular depth model (Depth Anything V2) follow the strokes? The divergence of the flow was tried
as a direction cue (2026-10-30) and failed partly because a camera zoom and a body coming closer look the same; the
depth of one region against the rest of the same frame does not change with a zoom. Per frame the model's relative
disparity (larger = nearer) is z-scored within the frame and averaged over the AI region and the part boxes; per
scene each feature is checked against the hand-made script: does it follow the strokes, with the same sign across
scenes (a direction cue), and does it tell the size of each stroke (PLAN, open issues 1 and 2)?

  jobs RUN [RUN ...] -o JOBS.json
      (dev machine) per clip, the scenes with actions in the default settings' saved analyses: start, end, the
      analysis region and the part boxes (10 fps) where there are any
  dump JOBS.json OUT_DIR [--clips A,B] [--model small]
      (GPU host; needs torch and transformers) frames at 10 fps; per frame the disparity on a grid 64 cells along
      the long side. OUT_DIR/<clip>.npz
  eval RUN [RUN ...] --depth DIR [--groups dev,test]
      (dev machine) the features against the hand-made script and the default output: correlation and the share of
      scenes with each sign, the direction cue with a fixed sign, the size of each stroke and a flip simulation

RUN: `validate` runs with saved analyses of the default settings (as scripts/depth_compare.py).
"""
import argparse
import json
import pathlib
import sys
import time
from pathlib import Path

import numpy as np

if sys.platform != "win32":
    pathlib.WindowsPath = pathlib.PureWindowsPath

sys.path.insert(0, str(Path(__file__).parent))
from depth_compare import MIN_R, load_scenes, report, simulate, stroke_report  # noqa: E402
from mask_depth import corr, detrend, find  # noqa: E402

FPS = 10.0
DECODE_SIDE = 640
GRID = 64  # cells along the long side of the stored disparity
MODELS = {
    "small": "depth-anything/Depth-Anything-V2-Small-hf",  # Apache-2.0
    "base": "depth-anything/Depth-Anything-V2-Base-hf",  # CC-BY-NC-4.0: experiments only
}


def jobs(args) -> None:
    from funscript_gen.validate import clips, load_manifest

    out = {}
    total = 0.0
    for clip in clips(load_manifest(), "all"):
        analysis = find([Path(r) for r in args.runs], clip.name)
        if analysis is None:
            print(f"{clip.name}: no analysis")
            continue
        scenes = []
        for p in analysis.plans:
            if p.source is None:
                continue
            roi = p.pick_roi if p.pick_name and p.pick_roi else p.roi
            sc = dict(index=p.scene.index, start_ms=p.scene.start_ms, end_ms=p.scene.end_ms,
                      roi=list(map(float, roi)) if roi else None)
            if p.parts_found is not None:
                times, boxes, size = p.parts_found
                sc["parts"] = dict(t=list(map(float, times)), size=list(size),
                                   boxes=[[[*map(float, b), lab, float(c)] for b, lab, c in f] for f in boxes])
            scenes.append(sc)
            total += (p.scene.end_ms - p.scene.start_ms) / 1000
        out[clip.name] = scenes
        print(f"{clip.name}: {len(scenes)} scenes, {sum('parts' in s for s in scenes)} with part boxes")
    Path(args.output).write_text(json.dumps(out))
    print(f"{total:.0f} s, about {total * FPS:.0f} frames")


# --- dump (GPU host) ---

class Depth:
    """Depth Anything V2: RGB uint8 frames of one size -> disparity on the GRID (float16)."""

    def __init__(self, name: str, device: str):
        import torch
        from transformers import AutoModelForDepthEstimation

        self.device = device
        self.model = AutoModelForDepthEstimation.from_pretrained(MODELS[name], torch_dtype=torch.float16)
        self.model = self.model.eval().to(device)
        self.mean = np.array((0.485, 0.456, 0.406), np.float32)
        self.std = np.array((0.229, 0.224, 0.225), np.float32)

    def __call__(self, frames: list[np.ndarray]) -> np.ndarray:
        import cv2
        import torch

        h, w = frames[0].shape[:2]
        k = 644 / max(h, w)  # the long side at 644 (46 patches), both sides multiples of 14
        ih, iw = max(14, round(h * k / 14) * 14), max(14, round(w * k / 14) * 14)
        x = np.stack([cv2.resize(f, (iw, ih), interpolation=cv2.INTER_AREA) for f in frames])
        x = (x.astype(np.float32) / 255 - self.mean) / self.std
        x = torch.from_numpy(x.transpose(0, 3, 1, 2)).to(self.device, torch.float16)
        with torch.no_grad():
            d = self.model(pixel_values=x).predicted_depth.float()
        gh, gw = (max(1, round(GRID * h / w)), GRID) if w >= h else (GRID, max(1, round(GRID * w / h)))
        d = torch.nn.functional.adaptive_avg_pool2d(d[:, None], (gh, gw))[:, 0]
        return d.cpu().numpy().astype(np.float16)


def dump(args) -> None:
    import torch

    from funscript_gen.validate import clips, load_manifest
    from funscript_gen.video.decoder import iter_frames

    torch.set_num_threads(4)
    model = Depth(args.model, "cuda")
    work = json.loads(Path(args.jobs).read_text())
    wanted = set(args.clips.split(",")) if args.clips else set(work)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    for name, scenes in work.items():
        path = out_dir / f"{name}.npz"
        if name not in wanted or path.exists():
            continue
        video = clips(manifest, name)[0].video
        t0, n = time.time(), 0
        arrays = {}
        for sc in scenes:
            times, frames = [], []
            for f in iter_frames(video, target_fps=FPS, max_side=DECODE_SIDE, start_ms=sc["start_ms"],
                                 end_ms=sc["end_ms"]):
                if f.t_ms >= sc["end_ms"]:
                    break
                times.append(f.t_ms)
                frames.append(np.ascontiguousarray(f.image[:, :, ::-1]))
            if not times:
                continue
            i = sc["index"]
            arrays[f"t{i}"] = np.array(times)
            arrays[f"g{i}"] = np.concatenate([model(frames[k:k + args.batch])
                                              for k in range(0, len(frames), args.batch)])
            n += len(times)
        np.savez_compressed(path, **arrays)
        print(f"{name}: {len(scenes)} scenes, {n} frames, {time.time() - t0:.0f} s", flush=True)


# --- eval ---

def cells(box, gh: int, gw: int) -> tuple[slice, slice] | None:
    """The grid cells under a normalized box (at least one)."""
    x1, y1, x2, y2 = box
    c1, c2 = int(np.floor(x1 * gw)), int(np.ceil(x2 * gw))
    r1, r2 = int(np.floor(y1 * gh)), int(np.ceil(y2 * gh))
    c1, r1 = min(max(c1, 0), gw - 1), min(max(r1, 0), gh - 1)
    return slice(r1, max(r2, r1 + 1)), slice(c1, max(c2, c1 + 1))


def part_box(parts: dict | None, t: float, label: str):
    """The most confident box of `label` (normalized) in the part check's frame nearest `t`, within 60 ms."""
    if not parts or not parts["t"]:
        return None
    pt = np.array(parts["t"])
    j = int(np.argmin(np.abs(pt - t)))
    if abs(pt[j] - t) > 60:
        return None
    w, h = parts["size"]
    best = None
    for x1, y1, x2, y2, lab, c in parts["boxes"][j]:
        if lab == label and (best is None or c > best[1]):
            best = ((x1 / w, y1 / h, x2 / w, y2 / h), c)
    return best[0] if best else None


def features(t: np.ndarray, grid: np.ndarray, scene: dict) -> dict[str, np.ndarray]:
    """Per frame: the disparity z-scored within the frame (median, spread between the 10th and 90th percentile),
    averaged over the AI region ('roi'), its upper minus its lower half ('roi_tb'), the penis and the vulva boxes and
    their difference; 'roi_raw': the region's mean disparity before the per-frame scaling."""
    g = grid.astype(np.float32)
    n, gh, gw = g.shape
    flat = g.reshape(n, -1)
    med = np.median(flat, 1)
    spread = np.percentile(flat, 90, 1) - np.percentile(flat, 10, 1) + 1e-6
    z = (g - med[:, None, None]) / spread[:, None, None]
    out = {}
    roi = scene["roi"] or [0.0, 0.0, 1.0, 1.0]
    rs, cs = cells(roi, gh, gw)
    out["roi"] = z[:, rs, cs].mean((1, 2))
    out["roi_raw"] = g[:, rs, cs].mean((1, 2))
    mid = (roi[1] + roi[3]) / 2
    top, bottom = cells([roi[0], roi[1], roi[2], mid], gh, gw), cells([roi[0], mid, roi[2], roi[3]], gh, gw)
    out["roi_tb"] = z[:, top[0], top[1]].mean((1, 2)) - z[:, bottom[0], bottom[1]].mean((1, 2))
    if "parts" in scene:
        for label in ("penis", "pussy"):
            v = np.full(n, np.nan)
            for k in range(n):
                b = part_box(scene["parts"], t[k], label)
                if b is not None:
                    r, c = cells(b, gh, gw)
                    v[k] = z[k, r, c].mean()
            if np.isfinite(v).mean() >= 0.6:  # as the part check's coverage
                out[label] = v
        if "penis" in out and "pussy" in out:
            out["penis_pussy"] = out["penis"] - out["pussy"]
    for key, v in out.items():  # gaps: the nearest frame with a box
        ok = np.isfinite(v)
        if not ok.all():
            out[key] = np.interp(t, t[ok], v[ok])
    return out


def sign_table(rows: list[dict], names: list[str]) -> None:
    """Does the feature follow the script (median |r|), and with which sign (share of scenes with r > 0)?"""
    print(f"\n== feature vs the hand-made script (scenes with |r_out| >= {MIN_R}; r at lag 0, 2 s detrended)")
    print(f"{'feature':12}{'part':>6}{'n':>5}{'med|r|':>8}{'r>0':>6}{'|r|>=.3':>8}{'of those r>0':>13}")
    for name in names:
        for part in ("2D dev", "2D test", "G dev", "G test"):
            series, group = part.split()
            sel = [r for r in rows if name in r["depth"] and (r["series"] == "G") == (series == "G")
                   and r["group"] == group and r["r_out"] is not None and abs(r["r_out"]) >= MIN_R]
            cs = [c for c in (corr(r["depth"][name], r["y_ref"]) for r in sel) if c is not None]
            if not cs:
                continue
            cs = np.array(cs)
            strong = cs[np.abs(cs) >= 0.3]
            print(f"{name:12}{part:>8}{len(cs):5}{np.median(np.abs(cs)):8.2f}{(cs > 0).mean():6.0%}"
                  f"{len(strong):8}{(strong > 0).mean() if len(strong) else float('nan'):13.0%}")


def evaluate(args) -> None:
    from dataclasses import replace

    args.feats = args.depth  # load_scenes reads t{i}; the grids are read here
    adjust = None
    if args.g_asym is not None:  # the 3D series with the lower asymmetry threshold (PLAN, follow-up work)
        def adjust(clip, opts):
            return replace(opts, asym_sign_threshold=args.g_asym) if clip.name[0] == "G" else opts
    rows, results = load_scenes(args, adjust)
    work = {name: {s["index"]: s for s in scenes} for name, scenes in json.loads(Path(args.jobs).read_text()).items()}
    data = {}
    for r in rows:
        if r["clip"] not in data:
            data[r["clip"]] = np.load(Path(args.depth) / f"{r['clip']}.npz")
        grid = data[r["clip"]][f"g{r['index']}"]
        feats = features(r["t"], grid, work[r["clip"]][r["index"]])
        r["depth"] = {k: detrend(v, FPS) for k, v in feats.items()}
    names = ["roi", "roi_raw", "roi_tb", "penis", "pussy", "penis_pussy"]
    sign_table(rows, names)
    if args.series:  # the cue on these scenes only ("G": the 3D series, "2D": the others); all clips are scored
        rows = [r for r in rows if (r["series"] == "G") == (args.series == "G")]
    # direction cue: the feature times a fixed sign (+1: nearer = higher position), its sign against the output
    keys = []
    for name in names:
        for s in (1, -1):
            key = (f"{name}{'+' if s > 0 else '-'}", 0)
            for r in rows:
                if name in r["depth"]:
                    r.setdefault("pred", {})[key] = s * r["depth"][name]
            keys.append(key)
    report(rows, keys)
    # stroke size: the sign taken from the output, so only the size of each stroke is compared
    size_keys = []
    for name in names:
        key = (f"{name}|out", 0)
        for r in rows:
            if name in r["depth"]:
                c = corr(r["depth"][name], r["y_out"])
                r.setdefault("pred", {})[key] = (1 if (c or 0) >= 0 else -1) * r["depth"][name]
        size_keys.append(key)
    stroke_report(rows, size_keys)
    if args.simulate:
        print("\n== flip simulation (mean F1 and r of the clips, default output -> cue applied)")
        for key in args.simulate.split(","):
            for th in (float(x) for x in args.th.split(",")):
                for evidence in (("none",), ("none", "asym")):
                    simulate(rows, results, (key, 0), th, evidence)


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
    d.add_argument("--model", default="small", choices=sorted(MODELS))
    d.add_argument("--batch", type=int, default=16)
    e = sub.add_parser("eval")
    e.add_argument("runs", nargs="+")
    e.add_argument("--jobs", required=True)
    e.add_argument("--depth", required=True)
    e.add_argument("--groups", default="dev,test")
    e.add_argument("--simulate", default="", help="cue keys (as printed, e.g. roi+) for the flip simulation")
    e.add_argument("--th", default="0.2,0.4")
    e.add_argument("--g-asym", type=float, default=None, help="render the G clips with this asymmetry threshold")
    e.add_argument("--series", default="", choices=("", "G", "2D"), help="apply the cue to these scenes only")
    args = p.parse_args()
    {"jobs": jobs, "dump": dump, "eval": evaluate}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
