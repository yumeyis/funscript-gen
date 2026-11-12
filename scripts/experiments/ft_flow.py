"""Offline: learn the hand-made script's velocity from the optical-flow field (2026-11-09). The signal the program
uses is the first principal component of the flow in one region; here a small CNN reads the whole coarse flow field
(plus the analysis region as a mask) and is fitted to the script's velocity, one group of source series held out at a
time. Flow has no appearance, so it should carry over between art styles better than the image models did
(ft_motion.py: 64% direction agreement). Two uses are checked: the signal itself (its correlation with the script
against the PCA signal's, in particular in scenes without rhythm) and a direction cue (as ft_motion.py).

  dump JOBS.json OUT_DIR [--clips A,B] [--workers 5] [--cell 16]
      (JOBS from depth_compare.py jobs) per clip OUT_DIR/<clip>.npz: t<i> (ms, 30 fps) and f<i> (T, rows, cols, 2)
      float16: Farneback (the pipeline's parameters, 480 px wide) pooled to cell x cell pixel blocks
  train LABELS.pkl JOBS.json --flow DIR [--folds 4] [--epochs 8] [--out PRED.pkl]
      LABELS.pkl from ft_motion.py labels; per scene the predicted velocity at the label times
  eval LABELS.pkl PRED.pkl  (ft_motion.py eval)
"""

import argparse
import json
import pickle
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

GRID = 24  # the fields are resized to GRID x GRID cells


def _dump_clip(task):
    import cv2

    cv2.setNumThreads(1)
    from funscript_gen.tracking.flow import FARNEBACK
    from funscript_gen.validate import clips, load_manifest
    from funscript_gen.video.decoder import iter_frames

    name, scenes, out_dir, cell = task
    path = Path(out_dir) / f"{name}.npz"
    if path.exists():
        return name, 0, 0.0
    video = clips(load_manifest(), name)[0].video
    t0, n, arrays = time.time(), 0, {}
    for sc in scenes:
        prev, ts, fields = None, [], []
        for f in iter_frames(
            video,
            target_fps=30.0,
            max_side=640,
            start_ms=sc["start_ms"],
            end_ms=sc["end_ms"],
        ):
            if f.t_ms >= sc["end_ms"]:
                break
            h = max(2 * cell, round(f.image.shape[0] * 480 / f.image.shape[1]))
            gray = cv2.cvtColor(
                cv2.resize(f.image, (480, h), interpolation=cv2.INTER_AREA),
                cv2.COLOR_BGR2GRAY,
            )
            flow = (
                cv2.calcOpticalFlowFarneback(prev, gray, None, *FARNEBACK)
                if prev is not None
                else np.zeros((h, 480, 2), np.float32)
            )
            prev = gray
            r, c = h // cell, 480 // cell
            fields.append(
                flow[: r * cell, : c * cell]
                .reshape(r, cell, c, cell, 2)
                .mean(axis=(1, 3))
                .astype(np.float16)
            )
            ts.append(f.t_ms)
        if ts:
            arrays[f"t{sc['index']}"] = np.array(ts)
            arrays[f"f{sc['index']}"] = np.stack(fields)
            n += len(ts)
    np.savez_compressed(path, **arrays)
    return name, n, time.time() - t0


def dump(args) -> None:
    work = json.loads(Path(args.jobs).read_text())
    wanted = set(args.clips.split(",")) if args.clips else set(work)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    tasks = [(n, s, args.out, args.cell) for n, s in work.items() if n in wanted]
    tasks.sort(key=lambda t: -sum(s["end_ms"] - s["start_ms"] for s in t[1]))
    with Pool(args.workers) as pool:
        for name, n, secs in pool.imap_unordered(_dump_clip, tasks):
            print(f"{name}: {n} frames, {secs:.0f} s", flush=True)


# --- train ---


def window_inputs(t_label, t_flow, f, roi, grid=GRID):
    """(N, 5, grid, grid) float32: the flow summed over the 100 ms before and after each label time (x, y each),
    camera motion (the median over the frame) removed per frame, and the region mask."""
    import cv2

    f = f.astype(np.float32)
    f = f - np.median(f.reshape(len(f), -1, 2), axis=1)[:, None, None]
    small = np.stack(
        [cv2.resize(x, (grid, grid), interpolation=cv2.INTER_AREA) for x in f]
    )  # (T, g, g, 2)
    csum = np.concatenate(
        [np.zeros((1, grid, grid, 2), np.float32), np.cumsum(small, axis=0)]
    )
    mask = np.zeros((grid, grid), np.float32)
    if roi is not None:
        x1, y1, x2, y2 = roi
        mask[
            int(y1 * grid) : max(int(np.ceil(y2 * grid)), int(y1 * grid) + 1),
            int(x1 * grid) : max(int(np.ceil(x2 * grid)), int(x1 * grid) + 1),
        ] = 1
    else:
        mask[:] = 1
    out = np.zeros((len(t_label), 5, grid, grid), np.float32)
    for k, t in enumerate(t_label):
        a, b, c = (np.searchsorted(t_flow, t + d, side="right") for d in (-100, 0, 100))
        before, after = csum[b] - csum[a], csum[c] - csum[b]
        out[k, 0], out[k, 1] = before[..., 0], before[..., 1]
        out[k, 2], out[k, 3] = after[..., 0], after[..., 1]
        out[k, 4] = mask
    return out


def train(args) -> None:
    import torch

    torch.set_num_threads(args.threads)
    rows = pickle.loads(Path(args.labels).read_bytes())
    rows = [r for r in rows if r["ref_ok"] and len(r["t"]) >= 12]
    jobs = json.loads(Path(args.jobs).read_text())
    roi_of = {(c, s["index"]): s["roi"] for c, scs in jobs.items() for s in scs}
    xs, ys, owner = [], [], []
    cache_clip, cache = None, None
    for si, r in enumerate(rows):
        if r["clip"] != cache_clip:
            cache, cache_clip = np.load(Path(args.flow) / f"{r['clip']}.npz"), r["clip"]
        key = r["index"]
        if f"f{key}" not in cache.files:
            r["ref_ok"] = False
            continue
        x = window_inputs(
            r["t"], cache[f"t{key}"], cache[f"f{key}"], roi_of.get((r["clip"], key))
        )
        v = np.gradient(r["y_ref"]) / max(
            r["y_ref"].std(), 1e-6
        )  # per frame (10 fps), z-scored by the scene
        scale = np.abs(x[:, :4]).mean() + 1e-3  # scene-wise flow scale
        x[:, :4] /= scale
        xs.append(x)
        ys.append(v.astype(np.float32))
        owner.append(si)
    print(f"{len(xs)} scenes, {sum(len(x) for x in xs)} samples", flush=True)
    series = sorted({rows[o]["series"] for o in owner})
    rng = np.random.default_rng(0)
    fold_of = {
        series[i]: k % args.folds for k, i in enumerate(rng.permutation(len(series)))
    }

    def make_net():
        c = args.width
        return torch.nn.Sequential(
            torch.nn.Conv2d(5, c, 3, padding=1),
            torch.nn.BatchNorm2d(c),
            torch.nn.ReLU(),
            torch.nn.Conv2d(c, c, 3, padding=1),
            torch.nn.BatchNorm2d(c),
            torch.nn.ReLU(),
            torch.nn.MaxPool2d(2),
            torch.nn.Conv2d(c, 2 * c, 3, padding=1),
            torch.nn.BatchNorm2d(2 * c),
            torch.nn.ReLU(),
            torch.nn.Conv2d(2 * c, 2 * c, 3, padding=1),
            torch.nn.BatchNorm2d(2 * c),
            torch.nn.ReLU(),
            torch.nn.MaxPool2d(2),
            torch.nn.Conv2d(2 * c, 4 * c, 3, padding=1),
            torch.nn.BatchNorm2d(4 * c),
            torch.nn.ReLU(),
            torch.nn.AdaptiveAvgPool2d(1),
            torch.nn.Flatten(),
            torch.nn.Dropout(0.3),
            torch.nn.Linear(4 * c, 1),
        )

    pred = {}
    t0 = time.time()
    for fold in range(args.folds):
        tr = [i for i, o in enumerate(owner) if fold_of[rows[o]["series"]] != fold]
        te = [i for i, o in enumerate(owner) if fold_of[rows[o]["series"]] == fold]
        x = torch.from_numpy(np.concatenate([xs[i] for i in tr]))
        y = torch.from_numpy(np.concatenate([ys[i] for i in tr]))
        net = make_net()
        opt = torch.optim.AdamW(net.parameters(), 2e-3, weight_decay=1e-2)
        steps = args.epochs * (len(x) // args.bs)
        sched = torch.optim.lr_scheduler.OneCycleLR(opt, 4e-3, total_steps=steps)
        for ep in range(args.epochs):
            net.train()
            perm = torch.randperm(len(x))
            tot = 0.0
            for b in range(len(x) // args.bs):
                idx = perm[b * args.bs : (b + 1) * args.bs]
                xb, yb = x[idx], y[idx]
                # augmentation: left-right mirror (x flow changes sign), the vertical axis is kept
                if torch.rand(1) < 0.5:
                    xb = xb.flip(3) * torch.tensor([-1, 1, -1, 1, 1.0]).view(1, 5, 1, 1)
                loss = torch.nn.functional.smooth_l1_loss(net(xb).squeeze(1), yb)
                opt.zero_grad()
                loss.backward()
                opt.step()
                sched.step()
                tot += loss.item()
            print(
                f"fold {fold} epoch {ep}: loss {tot / max(1, len(x) // args.bs):.4f} ({time.time() - t0:.0f} s)",
                flush=True,
            )
        net.eval()
        with torch.no_grad():
            for i in te:
                p = net(torch.from_numpy(xs[i])).squeeze(1).numpy()
                pred[(rows[owner[i]]["clip"], rows[owner[i]]["index"])] = p
        Path(args.out).write_bytes(pickle.dumps(pred))
    print("done", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("jobs")
    d.add_argument("out")
    d.add_argument("--clips")
    d.add_argument("--workers", type=int, default=5)
    d.add_argument("--cell", type=int, default=16)
    t = sub.add_parser("train")
    t.add_argument("labels")
    t.add_argument("jobs")
    t.add_argument("--flow", required=True)
    t.add_argument("--folds", type=int, default=4)
    t.add_argument("--epochs", type=int, default=8)
    t.add_argument("--bs", type=int, default=256)
    t.add_argument("--width", type=int, default=24)
    t.add_argument("--threads", type=int, default=6)
    t.add_argument("--out", default="pred_flow.pkl")
    e = sub.add_parser("eval")
    e.add_argument("labels")
    e.add_argument("pred")
    a = ap.parse_args()
    {"dump": dump, "train": train, "eval": evaluate}[a.cmd](a)


# --- eval ---


def evaluate(args) -> None:
    """Per scene: corr(predicted velocity, script velocity) against corr(output velocity, script velocity), and
    the direction cue (as ft_motion.py)."""
    rows = pickle.loads(Path(args.labels).read_bytes())
    pred = pickle.loads(Path(args.pred).read_bytes())

    def corr(a, b):
        return (
            float(np.corrcoef(a, b)[0, 1]) if a.std() > 1e-9 and b.std() > 1e-9 else 0.0
        )

    for group in sorted({r["group"] for r in rows}) + ["all"]:
        g = [
            r
            for r in rows
            if (r["group"] == group or group == "all")
            and r["ref_ok"]
            and (r["clip"], r["index"]) in pred
        ]
        if not g:
            continue
        cm, co, secs = [], [], []
        for r in g:
            p = pred[(r["clip"], r["index"])]
            vref, vout = np.gradient(r["y_ref"]), np.gradient(r["y_out"])
            cm.append(corr(p, vref))
            co.append(corr(vout, vref))
            secs.append(r["sec"])
        cm, co, secs = map(np.array, (cm, co, secs))
        w = secs / secs.sum()
        print(f"\n== {group}: {len(g)} scenes ({secs.sum():.0f} s)")
        print(
            f"  velocity correlation with the script, signed: model median {np.median(cm):.2f}"
            f" (time-weighted mean {np.sum(w * cm):.2f}), output median {np.median(co):.2f}"
            f" (mean {np.sum(w * co):.2f})"
        )
        low = np.abs(co) < 0.3
        print(
            f"  scenes where the output's |corr| < 0.3: {low.sum()}; model median {np.median(cm[low]):.2f},"
            f" share above 0.3: {np.mean(cm[low] > 0.3):.0%}; output share below -0.3: {np.mean(co[low] < -0.3):.0%}"
        )
        print(
            f"  model above 0.3: {np.mean(cm > 0.3):.0%}, below -0.3: {np.mean(cm < -0.3):.0%}"
            f" | output above 0.3: {np.mean(co > 0.3):.0%}, below -0.3: {np.mean(co < -0.3):.0%}"
        )
        # as a cue: the model's velocity against the output's
        sel = [r for r in g if r["r_out"] is not None and abs(r["r_out"]) >= 0.3]
        for th in (0.0, 0.2, 0.4):
            used = agree = fixes = breaks = 0
            for r in sel:
                p, vout = pred[(r["clip"], r["index"])], np.gradient(r["y_out"])
                c = corr(p, vout)
                if abs(c) < th or c == 0.0:
                    continue
                used += 1
                agree += (c > 0) == (r["r_out"] > 0)
                fixes += c < 0 and r["r_out"] < 0
                breaks += c < 0 and r["r_out"] > 0
            print(
                f"  cue th {th:.1f}: {len(sel)} scenes with |r_out| >= 0.3, used {used}, agree"
                f" {agree / max(used, 1):.0%}, fix {fixes}, break {breaks}"
            )


if __name__ == "__main__":
    main()
