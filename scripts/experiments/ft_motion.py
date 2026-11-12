"""Offline: fine-tune a small image network end to end to predict the hand-made script's velocity from the frames
around each moment, and use its agreement with the default output as a direction cue (2026-11-08). The earlier
supervised tries (depth_compare.py, depth_motion.py) kept the backbone frozen and reached 75-77% agreement with the
sign of the output's correlation, the output itself 84%.

  crops JOBS.json OUT_DIR [--clips A,B] [--workers 4] [--side 96]
      (dev machine; JOBS from `depth_compare.py jobs`) per clip OUT_DIR/<clip>.npz: t<i> (ms) and img<i> (N, side,
      side, 3 uint8: the scene's analysis region grown to a square, 10 fps)
  labels RUN [RUN ...] --crops DIR -o LABELS.pkl
      (dev machine) per scene: the hand-made script and the default output at the frame times, the clip's group and
      series, and what the output's correlation with the script says (r_out)
  train LABELS.pkl --crops DIR [--folds 4] [--epochs 6] [--out PRED.pkl]
      (GPU host; needs torch + torchvision) K folds over the source series; a ResNet-18 on the frames t-1, t, t+1
      (9 channels) predicts the script's velocity (z-scored per scene); PRED.pkl: per scene the predicted velocity
  eval LABELS.pkl PRED.pkl   (result 2026-11-08: agrees with the output direction 64% against the output's 78%; see PLAN)
      (dev machine) per scene the correlation of the prediction with the output's velocity; how often its sign agrees
      with the sign of r_out, fixes / breaks against the output's direction
"""
import argparse
import pickle
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

FPS = 10.0
MIN_R = 0.3


def _crop_clip(task):
    import cv2

    from depth_compare import DECODE_SIDE, square
    from funscript_gen.validate import clips, load_manifest
    from funscript_gen.video.decoder import iter_frames

    name, scenes, out_dir, side = task
    path = Path(out_dir) / f"{name}.npz"
    if path.exists():
        return name, 0, 0.0
    video = clips(load_manifest(), name)[0].video
    t0, n, arrays = time.time(), 0, {}
    for sc in scenes:
        times, imgs = [], []
        for f in iter_frames(video, target_fps=FPS, max_side=DECODE_SIDE, start_ms=sc["start_ms"],
                             end_ms=sc["end_ms"]):
            if f.t_ms >= sc["end_ms"]:
                break
            rgb = np.ascontiguousarray(f.image[:, :, ::-1])
            times.append(f.t_ms)
            imgs.append(cv2.resize(square(rgb, sc["roi"]), (side, side), interpolation=cv2.INTER_AREA))
        if times:
            arrays[f"t{sc['index']}"] = np.array(times)
            arrays[f"img{sc['index']}"] = np.stack(imgs)
            n += len(times)
    np.savez_compressed(path, **arrays)
    return name, n, time.time() - t0


def crops(args) -> None:
    import json

    work = json.loads(Path(args.jobs).read_text())
    wanted = set(args.clips.split(",")) if args.clips else set(work)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    tasks = [(n, s, args.out, args.side) for n, s in work.items() if n in wanted]
    with Pool(args.workers) as pool:
        for name, n, secs in pool.imap_unordered(_crop_clip, tasks):
            print(f"{name}: {n} frames, {secs:.0f} s", flush=True)


def labels(args) -> None:
    from depth_compare import load_scenes

    ns = argparse.Namespace(runs=args.runs, feats=args.crops, groups="all")
    rows, _ = load_scenes(ns)
    keep = ("clip", "group", "series", "index", "t", "sec", "y_ref", "y_out", "ref_ok", "r_out", "evidence")
    rows = [{k: r[k] for k in keep} for r in rows]
    Path(args.output).write_bytes(pickle.dumps(rows))
    print(f"{len(rows)} scenes, {sum(r['sec'] for r in rows):.0f} s, {sum(r['ref_ok'] for r in rows)} with a script")


# --- train (GPU host) ---

def central(x: np.ndarray, k: int = 1) -> np.ndarray:
    pad = np.concatenate([x[:1].repeat(k, 0), x, x[-1:].repeat(k, 0)])
    return pad[2 * k:] - pad[: len(x)]


def train(args) -> None:
    import torch
    import torchvision

    rows = pickle.loads(Path(args.labels).read_bytes())
    rows = [r for r in rows if r["ref_ok"] and len(r["t"]) >= 12]
    series = sorted({r["series"] for r in rows})
    rng = np.random.default_rng(0)
    order = rng.permutation(len(series))
    fold_of = {series[i]: k % args.folds for k, i in enumerate(order)}
    print(f"{len(rows)} scenes, {len(series)} series, folds: {fold_of}", flush=True)
    dev = "cuda"
    # keep everything on the CPU as uint8, move batches
    imgs = []
    t0 = time.time()
    cache_clip, cache = None, None
    for r in rows:
        if r["clip"] != cache_clip:
            cache, cache_clip = np.load(Path(args.crops) / f"{r['clip']}.npz"), r["clip"]
        imgs.append(cache[f"img{r['index']}"])
    print(f"loaded {sum(len(i) for i in imgs)} frames in {time.time() - t0:.0f} s", flush=True)
    vel = [(central(r["y_ref"][:, None])[:, 0] / max(r["y_ref"].std(), 1e-6)).astype(np.float32) for r in rows]
    mean = torch.tensor([0.485, 0.456, 0.406] * 3, device=dev).view(1, 9, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225] * 3, device=dev).view(1, 9, 1, 1)

    def batch(items):
        """items: (scene index, frame index) -> (B, 9, S, S) float on the GPU; frames t-1, t, t+1 (edges repeat)."""
        xs = []
        for s, i in items:
            im = imgs[s]
            idx = [max(i - 1, 0), i, min(i + 1, len(im) - 1)]
            xs.append(np.concatenate([im[j] for j in idx], axis=2).transpose(2, 0, 1))
        x = torch.from_numpy(np.stack(xs)).to(dev).float() / 255
        return (x - mean) / std

    def make_net():
        net = torchvision.models.resnet18(weights=torchvision.models.ResNet18_Weights.DEFAULT)
        w = net.conv1.weight.data
        net.conv1 = torch.nn.Conv2d(9, 64, 7, 2, 3, bias=False)
        net.conv1.weight.data = w.repeat(1, 3, 1, 1) / 3
        net.fc = torch.nn.Linear(512, 1)
        return net.to(dev)

    pred = {}
    for fold in range(args.folds):
        tr = [s for s, r in enumerate(rows) if fold_of[r["series"]] != fold]
        te = [s for s, r in enumerate(rows) if fold_of[r["series"]] == fold]
        items = [(s, i) for s in tr for i in range(len(imgs[s]))]
        net = make_net()
        opt = torch.optim.AdamW(net.parameters(), 3e-4, weight_decay=1e-2)
        steps = args.epochs * (len(items) // args.bs)
        sched = torch.optim.lr_scheduler.OneCycleLR(opt, 1e-3, total_steps=steps)
        scaler = torch.amp.GradScaler()
        step = 0
        for ep in range(args.epochs):
            net.train()
            perm = rng.permutation(len(items))
            tot = 0.0
            for b in range(len(items) // args.bs):
                sel = [items[j] for j in perm[b * args.bs:(b + 1) * args.bs]]
                x = batch(sel)
                # augmentation: random brightness, and a horizontal flip (the motion is vertical or free)
                if rng.random() < 0.5:
                    x = x.flip(3)
                y = torch.tensor([vel[s][i] for s, i in sel], device=dev)
                with torch.autocast("cuda", dtype=torch.float16):
                    loss = torch.nn.functional.smooth_l1_loss(net(x).squeeze(1).float(), y)
                opt.zero_grad()
                scaler.scale(loss).backward()
                scaler.step(opt)
                scaler.update()
                sched.step()
                tot += loss.item()
                step += 1
            print(f"fold {fold} epoch {ep}: loss {tot / max(1, len(items) // args.bs):.4f}"
                  f" ({time.time() - t0:.0f} s)", flush=True)
        net.eval()
        with torch.no_grad():
            for s in te:
                out = []
                for k in range(0, len(imgs[s]), 128):
                    with torch.autocast("cuda", dtype=torch.float16):
                        out.append(net(batch([(s, i) for i in range(k, min(k + 128, len(imgs[s])))]))
                                   .squeeze(1).float().cpu().numpy())
                pred[(rows[s]["clip"], rows[s]["index"])] = np.concatenate(out)
        Path(args.out).write_bytes(pickle.dumps(pred))
    print("done", flush=True)


# --- eval ---

def evaluate(args) -> None:
    rows = pickle.loads(Path(args.labels).read_bytes())
    pred = pickle.loads(Path(args.pred).read_bytes())
    for group in sorted({r["group"] for r in rows}) + ["all"]:
        g = [r for r in rows if (r["group"] == group or group == "all") and r["r_out"] is not None
             and abs(r["r_out"]) >= MIN_R and (r["clip"], r["index"]) in pred]
        if not g:
            continue
        right = sum(r["r_out"] > 0 for r in g)
        print(f"\n== {group}: {len(g)} scenes (|r_out| >= {MIN_R}), output right in {right} ({right / len(g):.0%})")
        # correlation of the predicted velocity with the script's velocity
        cr = []
        for r in g:
            p = pred[(r["clip"], r["index"])]
            vref = central(r["y_ref"][:, None])[:, 0]
            if p.std() > 0 and vref.std() > 0:
                cr.append(np.corrcoef(p, vref)[0, 1])
        print(f"median r(pred velocity, script velocity) {np.median(cr):.2f}")
        for th in (0.0, 0.1, 0.2, 0.3, 0.4):
            fixes = breaks = used = agree = 0
            for r in g:
                p = pred[(r["clip"], r["index"])]
                vout = central(r["y_out"][:, None])[:, 0]
                if p.std() == 0 or vout.std() == 0:
                    continue
                c = np.corrcoef(p, vout)[0, 1]
                if abs(c) < th:
                    continue
                used += 1
                agree += (c > 0) == (r["r_out"] > 0)
                fixes += c < 0 and r["r_out"] < 0
                breaks += c < 0 and r["r_out"] > 0
            print(f"  threshold {th:.1f}: used {used}, agrees with sign(r_out) {agree / max(used, 1):.0%},"
                  f" would fix {fixes}, break {breaks}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crops")
    c.add_argument("jobs")
    c.add_argument("out")
    c.add_argument("--clips")
    c.add_argument("--workers", type=int, default=4)
    c.add_argument("--side", type=int, default=96)
    lb = sub.add_parser("labels")
    lb.add_argument("runs", nargs="+")
    lb.add_argument("--crops", required=True)
    lb.add_argument("-o", "--output", required=True)
    t = sub.add_parser("train")
    t.add_argument("labels")
    t.add_argument("--crops", required=True)
    t.add_argument("--folds", type=int, default=4)
    t.add_argument("--epochs", type=int, default=6)
    t.add_argument("--bs", type=int, default=128)
    t.add_argument("--out", default="pred.pkl")
    e = sub.add_parser("eval")
    e.add_argument("labels")
    e.add_argument("pred")
    a = ap.parse_args()
    {"crops": crops, "labels": labels, "train": train, "eval": evaluate}[a.cmd](a)


if __name__ == "__main__":
    main()
