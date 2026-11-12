"""Offline: does the change of frozen image features between neighbouring frames tell which way the hand-made script
moves? depth_compare.py fitted the script's *position* from one frame's features with a linear model (r 0.2-0.45).
Here the target is the script's *velocity* (position change across +-1 frame at 10 fps) and the input the change of the
scene-centred features over the same frames, with a ridge or a small MLP, one source series held out at a time. The cue
for a scene is the correlation of the predicted velocity with the default output's velocity (>0: the output moves the
way the script would), compared with the sign of the output's correlation with the hand-made script.

usage: uv run python scripts/experiments/depth_motion.py RUN [RUN ...] --feats out/depth_feats [--features dinov2_roi,clip_full]
       [--model ridge|mlp] [--train-groups dev,test] [--groups dev,test]   (features: see depth_compare.py dump)
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from depth_compare import MIN_R, load_scenes, ridge  # noqa: E402


def central(x: np.ndarray, k: int = 1) -> np.ndarray:
    """x[t + k] - x[t - k] (edges: one-sided)."""
    pad = np.concatenate([x[:1].repeat(k, 0), x, x[-1:].repeat(k, 0)])
    return pad[2 * k:] - pad[: len(x)]


def mlp_fit(x: np.ndarray, y: np.ndarray, epochs: int = 30, seed: int = 0):
    import torch

    torch.manual_seed(seed)
    xt, yt = torch.tensor(x, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)
    net = torch.nn.Sequential(torch.nn.Dropout(0.2), torch.nn.Linear(x.shape[1], 256), torch.nn.GELU(),
                              torch.nn.Dropout(0.3), torch.nn.Linear(256, 1))
    opt = torch.optim.AdamW(net.parameters(), 1e-3, weight_decay=1e-2)
    for _ in range(epochs):
        net.train()
        for idx in torch.randperm(len(xt)).split(256):
            opt.zero_grad()
            torch.nn.functional.mse_loss(net(xt[idx]).squeeze(1), yt[idx]).backward()
            opt.step()
    net.eval()
    return lambda z: net(torch.tensor(z, dtype=torch.float32)).squeeze(1).detach().numpy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--feats", required=True)
    ap.add_argument("--groups", default="dev,test")
    ap.add_argument("--train-groups", default="dev,test")
    ap.add_argument("--features", default="dinov2_roi,dinov2_full,clip_roi,clip_full")
    ap.add_argument("--model", default="ridge")
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--alpha", type=float, default=100.0)
    ap.add_argument("--cap", type=int, default=400)
    a = ap.parse_args()
    rows, _ = load_scenes(argparse.Namespace(runs=a.runs, feats=a.feats, groups=a.groups))
    train_groups = set(a.train_groups.split(","))
    rng = np.random.default_rng(0)
    for feat in a.features.split(","):
        pool = [r for r in rows if feat in r["feats"] and r["ref_ok"]]
        for r in pool:
            r["dx"] = central(r["feats"][feat], a.k)
            r["vref"] = central(r["y_ref"][:, None], a.k)[:, 0] / r["y_ref"].std()
            r["vout"] = central(r["y_out"][:, None], a.k)[:, 0]
        for series in sorted({r["series"] for r in pool}):
            train = [r for r in pool if r["series"] != series and r["group"] in train_groups]
            xs, ys = [], []
            for r in train:
                take = rng.permutation(len(r["t"]))[: a.cap]
                xs.append(r["dx"][take])
                ys.append(r["vref"][take])
            x, y = np.concatenate(xs), np.concatenate(ys)
            sd = x.std(0) + 1e-6
            if a.model == "ridge":
                w = ridge(x / sd, y, a.alpha * len(y))
                predict = lambda z: (z / sd) @ w  # noqa: E731
            else:
                predict = (lambda f: lambda z: f(z / sd))(mlp_fit(x / sd, y))
            for r in pool:
                if r["series"] == series:
                    r["pv"] = predict(r["dx"])
        g = [r for r in pool if "pv" in r and r["r_out"] is not None and abs(r["r_out"]) >= MIN_R]
        for r in g:
            r["c"] = float(np.corrcoef(r["pv"], r["vout"])[0, 1]) if r["pv"].std() > 0 and r["vout"].std() > 0 else 0.0
        print(f"\n== {feat} ({a.model}, k={a.k}): {len(g)} scenes with |r_out| >= {MIN_R}, output right in "
              f"{sum(r['r_out'] > 0 for r in g)}")
        for th in (0.0, 0.1, 0.2, 0.3):
            used = [r for r in g if abs(r["c"]) >= th]
            agree = sum((r["c"] > 0) == (r["r_out"] > 0) for r in used)
            fixes = sum(r["c"] < 0 and r["r_out"] < 0 for r in used)
            breaks = sum(r["c"] < 0 and r["r_out"] > 0 for r in used)
            none = [r for r in used if r["evidence"] == "none"]
            nfix = sum(r["c"] < 0 and r["r_out"] < 0 for r in none)
            nbrk = sum(r["c"] < 0 and r["r_out"] > 0 for r in none)
            print(f"  th {th:.1f}: used {len(used):3d} agree {agree / max(1, len(used)):4.0%} fixes {fixes:3d} breaks "
                  f"{breaks:3d} | no evidence: fixes {nfix:3d} breaks {nbrk:3d}")


if __name__ == "__main__":
    main()
