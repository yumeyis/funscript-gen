"""Offline: can a model learn from the hand-made scripts which frame of a scene is deeper? Every cue tried so far for
the stroke direction (AI questions, divergence, occlusion, sound, SAM2 masks, OpenFunML) was unsupervised or
zero-shot; the hand-made scripts label every frame with a position. Frozen image features (DINOv2, CLIP, an anime
tagger), centred per scene, are fitted to the scripts' positions with ridge regression, one source series held out at
a time (the letter of the clip's alias), and the prediction is used as a direction cue for the default output.
Result (2026-11-04): the prediction follows the scripts only weakly (median r 0.2-0.45), is a worse direction
cue than the output itself and worse at the size of each stroke than the flow; see PLAN.

  jobs RUN [RUN ...] -o JOBS.json
      (dev machine) per clip in dev, test and holdout, the scenes with actions in the default settings' saved
      analyses: start, end and the analysis region
  dump JOBS.json OUT_DIR [--clips A,B] [--models dinov2,clip,wd]
      (GPU host; needs torch, transformers and timm) frames at 10 fps; per model the features of the whole frame and
      of the region (each padded to a square). OUT_DIR/<clip>.npz
  eval RUN [RUN ...] --feats DIR [--groups dev,test]
      (dev machine) leave-one-series-out ridge on the features; per scene the predicted position against the
      hand-made script and the default output: how often it gives the direction right, and the depth of each stroke

RUN: `validate` runs with saved analyses of the default settings (as scripts/experiments/mask_depth.py).
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
from mask_depth import corr, curve, detrend, find, turning, turning_kind  # noqa: E402

FPS = 10.0
DECODE_SIDE = 640
MIN_R = 0.3
MODELS = {
    "dinov2": "facebook/dinov2-base",
    "clip": "openai/clip-vit-base-patch16",
    "wd": "hf-hub:SmilingWolf/wd-vit-tagger-v3",
}
# Tagger tags kept as features of their own (logits): the ones about what is inserted where
WD_TAGS = ("penetration", "insertion", "sex", "vaginal", "anal", "fellatio", "oral", "deepthroat", "penis",
           "pussy", "cross-section", "x-ray", "cum", "testicles", "cowgirl", "missionary", "doggystyle", "pov")


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
            scenes.append(dict(index=p.scene.index, start_ms=p.scene.start_ms, end_ms=p.scene.end_ms,
                               roi=list(map(float, roi)) if roi else None))
            total += (p.scene.end_ms - p.scene.start_ms) / 1000
        out[clip.name] = scenes
        print(f"{clip.name}: {len(scenes)} scenes")
    Path(args.output).write_text(json.dumps(out))
    print(f"{total:.0f} s, about {total * FPS:.0f} frames")


# --- dump (GPU host) ---

def square(image: np.ndarray, roi) -> np.ndarray:
    """The region `roi` (normalized; None: the whole frame) grown to a square around its centre, black outside."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = roi or (0, 0, 1, 1)
    cx, cy = (x1 + x2) / 2 * w, (y1 + y2) / 2 * h
    side = max((x2 - x1) * w, (y2 - y1) * h, 32)
    a, b = int(round(cx - side / 2)), int(round(cy - side / 2))
    s = int(round(side))
    out = np.zeros((s, s, 3), np.uint8)
    sx1, sy1, sx2, sy2 = max(a, 0), max(b, 0), min(a + s, w), min(b + s, h)
    out[sy1 - b:sy2 - b, sx1 - a:sx2 - a] = image[sy1:sy2, sx1:sx2]
    return out


class Encoder:
    """One frozen backbone: RGB uint8 squares -> a feature row each."""

    def __init__(self, name: str, device: str):
        import torch

        self.name, self.device = name, device
        self.tags = None
        if name == "wd":
            import timm
            from huggingface_hub import hf_hub_download

            self.model = timm.create_model(MODELS[name], pretrained=True).eval().to(device, torch.float16)
            cfg = timm.data.resolve_data_config({}, model=self.model)
            self.size = cfg["input_size"][1]
            self.mean, self.std = cfg["mean"], cfg["std"]
            import csv

            path = hf_hub_download(MODELS[name].removeprefix("hf-hub:"), "selected_tags.csv")
            rows = list(csv.DictReader(open(path, encoding="utf-8")))
            self.tags = [(i, r["name"]) for i, r in enumerate(rows) if any(k in r["name"] for k in WD_TAGS)]
        else:
            from transformers import AutoModel, CLIPVisionModel

            cls = CLIPVisionModel if name == "clip" else AutoModel
            self.model = cls.from_pretrained(MODELS[name], torch_dtype=torch.float16).eval().to(device)
            self.size = 224
            self.mean, self.std = ((0.4815, 0.4578, 0.4082), (0.2686, 0.2613, 0.2758)) if name == "clip" else \
                ((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))

    def __call__(self, squares: list[np.ndarray]) -> np.ndarray:
        import cv2
        import torch

        x = np.stack([cv2.resize(s, (self.size, self.size), interpolation=cv2.INTER_AREA) for s in squares])
        x = (x.astype(np.float32) / 255 - np.array(self.mean, np.float32)) / np.array(self.std, np.float32)
        x = torch.from_numpy(x.transpose(0, 3, 1, 2)).to(self.device, torch.float16)
        with torch.no_grad():
            if self.name == "wd":
                f = self.model.forward_features(x)
                pre = self.model.forward_head(f, pre_logits=True)
                logits = self.model.get_classifier()(pre)
                out = torch.cat([pre, logits[:, [i for i, _ in self.tags]]], 1)
            elif self.name == "clip":
                out = self.model(pixel_values=x).pooler_output
            else:
                h = self.model(pixel_values=x).last_hidden_state
                out = torch.cat([h[:, 0], h[:, 1:].mean(1)], 1)
        return out.float().cpu().numpy().astype(np.float16)


def dump(args) -> None:
    import torch

    from funscript_gen.validate import clips, load_manifest
    from funscript_gen.video.decoder import iter_frames

    torch.set_num_threads(4)
    encoders = [Encoder(m, "cuda") for m in args.models.split(",")]
    for e in encoders:
        if e.tags:
            print(f"{e.name}: {len(e.tags)} tags kept: {', '.join(n for _, n in e.tags[:40])} ...")
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
            times, crops = [], {"full": [], "roi": []}
            for f in iter_frames(video, target_fps=FPS, max_side=DECODE_SIDE, start_ms=sc["start_ms"],
                                 end_ms=sc["end_ms"]):
                if f.t_ms >= sc["end_ms"]:
                    break
                rgb = np.ascontiguousarray(f.image[:, :, ::-1])
                times.append(f.t_ms)
                crops["full"].append(square(rgb, None))
                crops["roi"].append(square(rgb, sc["roi"]))
            if not times:
                continue
            i = sc["index"]
            arrays[f"t{i}"] = np.array(times)
            for e in encoders:
                for crop, images in crops.items():
                    arrays[f"{e.name}_{crop}{i}"] = np.concatenate(
                        [e(images[k:k + args.batch]) for k in range(0, len(images), args.batch)])
            n += len(times)
        for e in encoders:
            if e.tags:
                arrays[f"{e.name}_tags"] = np.array([t for _, t in e.tags])
        np.savez_compressed(path, **arrays)
        print(f"{name}: {len(scenes)} scenes, {n} frames, {time.time() - t0:.0f} s", flush=True)


# --- eval ---

def ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    """Weights w of min |x w - y|^2 + alpha |w|^2 (x standardized, y centred)."""
    if x.shape[0] >= x.shape[1]:
        return np.linalg.solve(x.T @ x + alpha * np.eye(x.shape[1]), x.T @ y)
    return x.T @ np.linalg.solve(x @ x.T + alpha * np.eye(x.shape[0]), y)


def load_scenes(args, adjust=None) -> tuple[list[dict], list]:
    """Per scene with actions in the chosen groups: frame times, the scene-centred features per set, the hand-made
    script and the default output (detrended) at those times, the clip's group and series, and the direction
    evidence the output already has; and per clip (clip, render result, options, hand-made script). `adjust(clip,
    opts)`: the options to render that clip with (default: the default settings)."""
    from funscript_gen.cli import parse_generate_args
    from funscript_gen.export.funscript import Funscript
    from funscript_gen.options import build, for_analysis
    from funscript_gen.pipeline import render
    from funscript_gen.validate import clips, load_manifest

    given, preset = parse_generate_args([])
    rows, results = [], []
    for clip in clips(load_manifest(), args.groups):
        path = Path(args.feats) / f"{clip.name}.npz"
        if not path.exists():
            continue
        data = np.load(path)
        analysis = find([Path(r) for r in args.runs], clip.name)
        opts = build(for_analysis(analysis.key, given, preset))
        if adjust is not None:
            opts = adjust(clip, opts)
        res = render(analysis, opts)
        out_acts = res.funscript.normalized().actions
        ref_acts = Funscript.load(clip.reference).normalized().actions
        for plan in res.plans:
            i = plan.scene.index
            if f"t{i}" not in data or plan.skip:
                continue
            t = data[f"t{i}"]
            if len(t) < 12:
                continue
            y_ref = detrend(curve(ref_acts, t), FPS)
            y_out = detrend(curve(out_acts, t), FPS)
            if y_out.std() < 1:
                continue
            feats = {}
            for key in data.files:
                if key.endswith(f"_full{i}") or key.endswith(f"_roi{i}"):
                    x = data[key].astype(np.float64)
                    name = key[: -len(str(i))]
                    feats[name] = x - x.mean(0)
            evidence = ("part" if plan.part_flipped or plan.part_sign is not None and abs(plan.part_sign) >= 0.2
                        else "asym" if plan.asym_flipped else "none")
            inside = [a for a in ref_acts if t[0] <= a.at <= t[-1]]
            pos = np.array([a.pos for a in inside], float)
            if len(pos) >= 3:
                keep = turning(pos)
                turns = (np.array([a.at for a in inside], float)[keep], pos[keep], turning_kind(pos)[keep])
            else:
                turns = (np.zeros(0), np.zeros(0), np.zeros(0))
            rows.append(dict(clip=clip.name, group=clip.group, series=clip.name[0], index=i, t=t, sec=len(t) / FPS,
                             y_ref=y_ref, y_out=y_out, ref_ok=y_ref.std() >= 1,
                             r_out=corr(y_out, y_ref) if y_ref.std() >= 1 else None, evidence=evidence, feats=feats,
                             turns=turns, out_at=curve(out_acts, turns[0]) if len(turns[0]) else turns[0]))
        results.append((clip, res, opts, Funscript.load(clip.reference)))
    return rows, results


def fit_predict(rows: list[dict], feat: str, alpha: float, train_groups: set, cap: int = 300) -> None:
    """For each series, ridge on the other series' scenes in `train_groups` (each scene's frames z-scored to the
    script, at most `cap` frames per scene); the held-out scenes get `pred[feat, alpha]`."""
    rng = np.random.default_rng(0)
    for series in sorted({r["series"] for r in rows}):
        train = [r for r in rows if r["series"] != series and feat in r["feats"] and r["ref_ok"]
                 and r["group"] in train_groups]
        xs, ys = [], []
        for r in train:
            take = rng.permutation(len(r["t"]))[:cap]
            xs.append(r["feats"][feat][take])
            ys.append(r["y_ref"][take] / r["y_ref"].std())
        x, y = np.concatenate(xs), np.concatenate(ys)
        sd = x.std(0) + 1e-6
        w = ridge(x / sd, y, alpha * len(y))
        for r in rows:
            if r["series"] == series and feat in r["feats"]:
                r.setdefault("pred", {})[feat, alpha] = (r["feats"][feat] / sd) @ w


def report(rows: list[dict], keys: list) -> None:
    for group in sorted({r["group"] for r in rows}):
        g = [r for r in rows if r["group"] == group and r["r_out"] is not None and abs(r["r_out"]) >= MIN_R]
        right = sum(r["r_out"] > 0 for r in g)
        none = [r for r in g if r["evidence"] == "none"]
        print(f"\n== {group}: {len(g)} scenes with |r_out| >= {MIN_R}, output right in {right}"
              f" ({sum(r['sec'] for r in g):.0f} s); without evidence {len(none)}, right in"
              f" {sum(r['r_out'] > 0 for r in none)}")
        print(f"{'features':24}{'alpha':>7}{'med r_ref':>10}{'ref>0':>7}{'th':>5}{'used':>6}{'acc':>6}{'fixes':>7}"
              f"{'breaks':>8}{'none acc':>10}{'none fx/br':>11}")
        for key in keys:
            have = [r for r in g if key in r.get("pred", {})]
            if not have:
                continue
            for r in have:
                r["c_ref"] = corr(r["pred"][key], r["y_ref"], 1)
                r["c_out"] = corr(r["pred"][key], r["y_out"])
            med = np.median([r["c_ref"] for r in have if r["c_ref"] is not None])
            pos = sum((r["c_ref"] or 0) > 0 for r in have) / len(have)
            for th in (0.0, 0.2, 0.4):
                used = [r for r in have if r["c_out"] is not None and abs(r["c_out"]) >= th]
                agree = sum((r["c_out"] > 0) == (r["r_out"] > 0) for r in used)
                fixes = sum(r["c_out"] < 0 and r["r_out"] < 0 for r in used)
                breaks = sum(r["c_out"] < 0 and r["r_out"] > 0 for r in used)
                nu = [r for r in used if r["evidence"] == "none"]
                nacc = sum((r["c_out"] > 0) == (r["r_out"] > 0) for r in nu)
                nfx = sum(r["c_out"] < 0 and r["r_out"] < 0 for r in nu)
                nbr = sum(r["c_out"] < 0 and r["r_out"] > 0 for r in nu)
                print(f"{key[0]:24}{key[1]:7g}{med:10.2f}{pos:7.0%}{th:5.1f}{len(used):6}"
                      f"{agree / max(1, len(used)):6.0%}{fixes:7}{breaks:8}{nacc:5}/{len(nu):<4}{nfx:6}/{nbr:<4}")


def stroke_report(rows: list[dict], keys: list) -> None:
    """The size of each stroke: within a scene whose output has the direction right, the hand-made script's
    positions at its peaks (and at its valleys) against the prediction and the output at the same times."""
    print("\n== stroke depth: per scene with >= 6 valleys (peaks), median correlation with the script's positions")
    print(f"{'features':24}{'alpha':>7}{'scenes':>7}{'valley pred':>12}{'valley out':>11}{'peak pred':>10}"
          f"{'peak out':>9}")
    for key in keys:
        vals = {k: [] for k in ("vp", "vo", "pp", "po")}
        n = 0
        for r in rows:
            if key not in r.get("pred", {}) or r["r_out"] is None or r["r_out"] < MIN_R:
                continue
            at, pos, kind = r["turns"]
            if len(at) < 12:
                continue
            pred = np.interp(at, r["t"], r["pred"][key])
            n += 1
            for k, sel in (("v", kind < 0), ("p", kind > 0)):
                if sel.sum() >= 6 and pos[sel].std() > 1:
                    vals[k + "p"].append(np.corrcoef(pred[sel], pos[sel])[0, 1])
                    vals[k + "o"].append(np.corrcoef(r["out_at"][sel], pos[sel])[0, 1]
                                         if r["out_at"][sel].std() > 1e-9 else 0.0)
        med = {k: np.median(v) if v else float("nan") for k, v in vals.items()}
        print(f"{key[0]:24}{key[1]:7g}{n:7}{med['vp']:12.2f}{med['vo']:11.2f}{med['pp']:10.2f}{med['po']:9.2f}")


def simulate(rows: list[dict], results: list, key, th: float, evidence: tuple = ("none",)) -> None:
    """The scores with the cue applied: every scene whose direction evidence is in `evidence` and whose prediction
    goes against the output by `th` or more is flipped (as by hand), against the default output."""
    from funscript_gen.evaluate import compare
    from funscript_gen.pipeline import refinalize

    by_clip: dict[str, set] = {}
    for r in rows:
        if key in r.get("pred", {}) and r["evidence"] in evidence:
            c = corr(r["pred"][key], r["y_out"])
            if c is not None and c <= -th:
                by_clip.setdefault(r["clip"], set()).add(r["index"])
    per = {}
    for clip, res, opts, ref in results:
        base = compare(ref, res.funscript)
        flips = by_clip.get(clip.name, set())
        for p in res.plans:
            p.flipped = p.scene.index in flips
        refinalize(res, opts)
        new = compare(ref, res.funscript)
        for p in res.plans:
            p.flipped = False
        refinalize(res, opts)
        per[clip.name] = (clip.group, len(flips), base.f1, new.f1, base.correlation, new.correlation)
    line = []
    for group in sorted({g for g, *_ in per.values()}):
        v = np.array([x[1:] for x in per.values() if x[0] == group], float)
        line.append(f"{group} flips {int(v[:, 0].sum()):3d}  F1 {v[:, 1].mean():.3f} -> {v[:, 2].mean():.3f}"
                    f"  r {v[:, 3].mean():.3f} -> {v[:, 4].mean():.3f}")
    print(f"{key[0]:24}{key[1]:5g} th {th:.1f} {'+'.join(evidence):10} " + "  |  ".join(line))
    changed = [f"{n}{x[3] - x[2]:+.2f}" for n, x in per.items() if x[1]]
    print(f"{'':48}" + " ".join(changed))


def evaluate(args) -> None:
    rows, results = load_scenes(args)
    feats = sorted({f for r in rows for f in r["feats"]})
    if args.features:
        feats = args.features.split(",")
        for r in rows:  # "a+b": the sets side by side
            for f in feats:
                parts = f.split("+")
                if len(parts) > 1 and all(p in r["feats"] for p in parts):
                    r["feats"][f] = np.concatenate([r["feats"][p] for p in parts], 1)
    alphas = [float(a) for a in args.alphas.split(",")]
    keys = []
    for feat in feats:
        for alpha in alphas:
            fit_predict(rows, feat, alpha, set(args.train_groups.split(",")))
            keys.append((feat, alpha))
    report(rows, keys)
    stroke_report(rows, keys)
    print("\n== flip simulation (mean F1 and r of the clips, default output -> cue applied)")
    ths = [float(t) for t in args.th.split(",")]
    for key in keys:
        for th in ths:
            for evidence in (("none",), ("none", "asym")):
                simulate(rows, results, key, th, evidence)
    if args.v:
        key = keys[0]
        print(f"\n{key}: per scene")
        print(f"{'clip':6}{'#':>4}{'sec':>5}{'r_out':>7}{'evid':>6}{'c_ref':>7}{'c_out':>7}")
        for r in rows:
            if key not in r.get("pred", {}):
                continue
            c_ref, c_out = corr(r["pred"][key], r["y_ref"], 1), corr(r["pred"][key], r["y_out"])
            print(f"{r['clip']:6}{r['index']:4}{r['sec']:5.0f}{r['r_out'] or 0:+7.2f}{r['evidence']:>6}"
                  f"{c_ref or 0:+7.2f}{c_out or 0:+7.2f}")


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
    d.add_argument("--models", default="dinov2,clip,wd")
    d.add_argument("--batch", type=int, default=32)
    e = sub.add_parser("eval")
    e.add_argument("runs", nargs="+")
    e.add_argument("--feats", required=True)
    e.add_argument("--groups", default="dev,test")
    e.add_argument("--features", default="")
    e.add_argument("--alphas", default="0.1,1,10")
    e.add_argument("--train-groups", default="dev,test", help="the groups the ridge learns from (holdout: never)")
    e.add_argument("--th", default="0.2,0.4,0.6", help="flip simulation: thresholds")
    e.add_argument("-v", action="store_true")
    args = p.parse_args()
    {"jobs": jobs, "dump": dump, "eval": evaluate}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
