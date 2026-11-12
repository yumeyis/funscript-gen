"""Offline: can the VLM's own boxes (Qwen3-VL grounding) give the penis-vulva distance sign where the censor detector
does not? Per flow scene of a saved analysis: ask for the penis and the vulva box in every frame at --fps (cached in
out/vlm_parts/), take the penis-vulva distance as part_sign does, and compare its sign with the sign of the correlation
between the scene's flow position and the hand-made script (the truth, scenes with |r| >= MIN_R).

usage: uv run python scripts/experiments/vlm_parts.py RUN OUT.json [--clips dev,test] [--fps 5] [--max-s 25] [--only-missing]
"""
import argparse
import base64
import json
import os
import pathlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

pathlib.WindowsPath = pathlib.PureWindowsPath

from stroke_size import find  # noqa: E402

from funscript_gen.cli import parse_generate_args  # noqa: E402
from funscript_gen.export.funscript import Funscript  # noqa: E402
from funscript_gen.options import build, for_analysis  # noqa: E402
from funscript_gen.tracking.parts import distance_sign, penis_vulva_distance  # noqa: E402
from funscript_gen.validate import clips, load_manifest  # noqa: E402
from funscript_gen.video.decoder import iter_frames  # noqa: E402

MIN_R = 0.3
PROMPTS = {
    "penis": "Locate every penis in the image, output bbox coordinates in JSON format.",
    "vulva": "Locate every vulva (vagina) in the image, output bbox coordinates in JSON format.",
}
CACHE = Path("out/vlm_parts")
SIDE = 640  # frames sent to the VLM are at most this large (960: 2.7 requests/s on the vLLM host)


def ask(client, model: str, image: np.ndarray, label: str) -> list[list[float]]:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    url = "data:image/jpeg;base64," + base64.b64encode(buf).decode()
    r = client.chat.completions.create(model=model, temperature=0, max_tokens=300, messages=[{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": url}}, {"type": "text", "text": PROMPTS[label]}]}])
    text = r.choices[0].message.content or ""
    try:
        data = json.loads(text[text.index("["): text.rindex("]") + 1])
    except ValueError:
        return []
    h, w = image.shape[:2]
    out = []
    for q in data:
        try:
            x1, y1, x2, y2 = q["bbox_2d"]
        except (KeyError, TypeError, ValueError):
            continue
        out.append([x1 * w / 1000, y1 * h / 1000, x2 * w / 1000, y2 * h / 1000])
    return out


def boxes_of(client, model, clip, start, end, fps, pool) -> tuple[list[float], list[list], tuple[int, int]]:
    path = CACHE / f"{clip.name}-{int(start)}-{int(end)}-{fps:g}-{SIDE}.json"
    if path.exists():
        d = json.load(open(path))
        return d["t"], [[(tuple(b), lab, 1.0) for b, lab in fr] for fr in d["boxes"]], tuple(d["size"])
    frames = [f for f in iter_frames(clip.video, target_fps=fps, max_side=SIDE, start_ms=start) if f.t_ms < end]
    jobs = [(f, lab, pool.submit(ask, client, model, f.image, lab)) for f in frames for lab in PROMPTS]
    per: dict[int, list] = {i: [] for i in range(len(frames))}
    idx = {id(f): i for i, f in enumerate(frames)}
    for f, lab, job in jobs:
        for b in job.result():
            per[idx[id(f)]].append((b, "penis" if lab == "penis" else "pussy"))
    h, w = frames[0].image.shape[:2]
    path.parent.mkdir(exist_ok=True)
    json.dump({"t": [f.t_ms for f in frames], "boxes": [per[i] for i in range(len(frames))], "size": [w, h]}, open(path, "w"))
    return [f.t_ms for f in frames], [[(tuple(b), lab, 1.0) for b, lab in per[i]] for i in range(len(frames))], (w, h)


def main() -> None:
    from openai import OpenAI

    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("out")
    ap.add_argument("--clips", default="dev,test")
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--max-s", type=float, default=25.0)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--only-missing", action="store_true", help="only scenes the censor detector gave no sign")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    client = OpenAI(base_url=os.environ["VLLM_BASE_URL"], api_key=os.environ["VLLM_API_KEY"], max_retries=3)
    model = os.environ["VLLM_MODEL"]
    given, preset = parse_generate_args([])
    pool = ThreadPoolExecutor(a.workers)
    rows, total = [], 0.0
    for clip in clips(load_manifest(), a.clips):
        an = find([Path(a.run)], clip.name)
        if an is None:
            continue
        opts = build(for_analysis(an.key, given, preset))
        ref = Funscript.load(clip.reference).normalized()
        ra = np.array([x.at for x in ref.actions], float)
        rp = np.array([x.pos for x in ref.actions], float)
        for k, plan in enumerate(an.plans):
            s, e = plan.scene.start_ms, plan.scene.end_ms
            if plan.skip or plan.rest or plan.flow_position is None or (e - s) / 1000 > a.max_s or (e - s) < 1500:
                continue
            ft, fx = plan.flow_position
            grid = np.arange(ft[0], ft[-1], 100.0)
            xa, xb = np.interp(grid, ft, fx), np.interp(grid, ra, rp)
            if xa.std() < 1e-9 or xb.std() < 1e-9 or len(grid) < 10:
                continue
            r_m = float(np.corrcoef(xa, xb)[0, 1])
            det_sign = None
            if plan.parts_found is not None:
                times, boxes, size = plan.parts_found
                dist, edge = penis_vulva_distance(boxes, size)
                det_sign = distance_sign(np.array(times), dist, ft, fx, opts.part_fps, opts.part_min_cover)
            if a.only_missing and det_sign is not None:
                continue
            total += (e - s) / 1000
            if a.list:
                continue
            t, boxes, size = boxes_of(client, model, clip, s, e, a.fps, pool)
            dist, edge = penis_vulva_distance(boxes, size)
            cover = float(np.mean(~np.isnan(dist)))
            vs = distance_sign(np.array(t), dist, ft, fx, a.fps, 0.6)
            row = dict(clip=clip.name, scene=k, dur=(e - s) / 1000, r_m=r_m, det=det_sign, vlm=vs, cover=cover, edge=edge,
                       penis=float(np.mean([any(b[1] == "penis" for b in fr) for fr in boxes])))
            rows.append(row)
            print(json.dumps(row), flush=True)
            json.dump(rows, open(a.out, "w"))
    print(f"seconds: {total:.0f}")


if __name__ == "__main__":
    main()
