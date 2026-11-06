"""Test web UI: upload a video, pick detection models and a time, see the boxes and the AI's answer.

Not part of the product (no language packs): a tool for comparing detectors on a frame or on a whole video.

    uv run python scripts/detect_viewer.py [--port 7861] [--share-lan]

Models: the DeepGHS YOLO detectors (censor parts, person, head, face; every variant the repository has) and NudeNet 320n,
all through onnxruntime; "VLM" asks the configured vLLM / Ollama (.env) for the scene analysis of the frames from the
chosen time on and draws its boxes. Videos stay on this machine (and the VLM host named in .env).
"""
from __future__ import annotations

import argparse
import tempfile
import threading
import time
from pathlib import Path

import av
import cv2
import gradio as gr
import numpy as np
import pandas as pd

from funscript_gen.tracking.parts import PartDetector, decode
from funscript_gen.video.decoder import iter_frames

REPOS = {  # repository -> (pinned revision or None for the latest, fallback variants when offline)
    "deepghs/anime_censor_detection": ("0cf62fd6b28213b40ae0c0055f92e7ae6a96bdc2", ["censor_detect_v1.0_s", "censor_detect_v1.0_n"]),
    "deepghs/anime_person_detection": ("e39c744c22432ad01f91dd254fe2b02c8d878b8c", ["person_detect_v1.3_s"]),
    "deepghs/anime_head_detection": (None, []),
    "deepghs/anime_face_detection": (None, []),
}
NUDENET = "NudeNet 320n (photos)"
VLM = "VLM scene analysis"
PALETTE = [(0, 0, 255), (0, 200, 0), (255, 100, 0), (0, 200, 255), (200, 0, 200), (150, 150, 0), (0, 120, 255), (255, 0, 100)]
NN_LABELS = ["FEMALE_GENITALIA_COVERED", "FACE_FEMALE", "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED",
             "FEMALE_GENITALIA_EXPOSED", "MALE_BREAST_EXPOSED", "ANUS_EXPOSED", "FEET_EXPOSED", "BELLY_COVERED",
             "FEET_COVERED", "ARMPITS_COVERED", "ARMPITS_EXPOSED", "FACE_MALE", "BELLY_EXPOSED",
             "MALE_GENITALIA_EXPOSED", "ANUS_COVERED", "FEMALE_BREAST_COVERED", "BUTTOCKS_COVERED"]

_cache: dict[str, object] = {}
_lock = threading.Lock()


def variants() -> list[str]:
    """Every '<repo short name>: <variant>' the repositories offer (the hub's listing; the fallbacks offline)."""
    out = []
    try:
        from huggingface_hub import HfApi

        api = HfApi()
    except Exception:  # noqa: BLE001
        api = None
    for repo, (rev, fallback) in REPOS.items():
        names: list[str] = []
        if api is not None:
            try:
                files = [s.rfilename for s in api.model_info(repo, revision=rev).siblings]
                names = sorted({f.split("/")[0] for f in files if f.endswith("/model.onnx")})
            except Exception:  # noqa: BLE001 - offline
                pass
        out += [f"{repo.split('/')[1]}: {n}" for n in (names or fallback)]
    return out


class NudeNet:
    def __init__(self, side: int = 320) -> None:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download

        path = hf_hub_download("deepghs/nudenet_onnx", "320n.onnx", revision="44956a0587943016350c7815f9e0dec089d45cae")
        so = ort.SessionOptions()
        so.intra_op_num_threads = 4
        self.session = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
        self.side, self.default_conf, self.device = side, 0.2, "CPUExecutionProvider"

    def __call__(self, image: np.ndarray, conf: float, iou: float = 0.45):
        h, w = image.shape[:2]
        m = max(h, w)
        sq = cv2.copyMakeBorder(image, 0, m - h, 0, m - w, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        blob = cv2.dnn.blobFromImage(sq, 1 / 255.0, (self.side, self.side), swapRB=True)
        (out,) = self.session.run(None, {"images": blob})
        f = m / self.side
        return decode(out[0], NN_LABELS, conf, iou, (f, f), (w, h))


class Yolo:
    def __init__(self, choice: str) -> None:
        import json

        from huggingface_hub import hf_hub_download

        short, variant = choice.split(": ")
        repo = f"deepghs/{short}"
        rev = REPOS[repo][0]
        self.detector = PartDetector(model_path=hf_hub_download(repo, f"{variant}/model.onnx", revision=rev))
        self.device = self.detector.device
        try:
            self.default_conf = float(json.loads(Path(hf_hub_download(repo, f"{variant}/threshold.json", revision=rev)).read_text())["threshold"])
        except Exception:  # noqa: BLE001
            self.default_conf = 0.25

    def __call__(self, image: np.ndarray, conf: float, iou: float = 0.7):
        return self.detector(image, conf=conf, iou=iou)


def model(name: str):
    with _lock:
        if name not in _cache:
            _cache[name] = NudeNet() if name == NUDENET else Yolo(name)
        return _cache[name]


def frame_at(path: str, t_s: float, max_side: int = 960) -> tuple[np.ndarray, float]:
    for f in iter_frames(path, start_ms=t_s * 1000, end_ms=t_s * 1000 + 2000, max_side=max_side):
        return f.image, f.t_ms / 1000
    raise gr.Error("No frame at that time")


def duration(path: str) -> float:
    with av.open(path) as c:
        s = c.streams.video[0]
        return float(s.duration * s.time_base) if s.duration else float(c.duration / av.time_base)


def draw(image: np.ndarray, boxes: list[tuple[tuple[float, float, float, float], str, float]], colors: dict[str, tuple]) -> np.ndarray:
    out = image.copy()
    t = max(2, round(max(out.shape[:2]) / 400))
    for (x1, y1, x2, y2), label, c in boxes:
        col = colors.setdefault(label, PALETTE[len(colors) % len(PALETTE)])
        cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), col, t)
        text = f"{label} {c:.2f}"
        cv2.putText(out, text, (int(x1) + 3, max(14, int(y1) - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * t / 2 + 0.3, col, max(1, t - 1))
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def vlm_boxes(images: list[np.ndarray], times: list[float]):
    """The VLM's scene analysis of the frames: (json text, boxes in pixels of the first frame, seconds)."""
    from funscript_gen.ai.base import LabeledImage
    from funscript_gen.ai.prompts import SCENE_PROMPT, SceneAnalysis, bbox_to_unit, default_bbox_format
    from funscript_gen.config import Settings, make_provider

    settings = Settings()
    fmt = settings.vllm_bbox_format or default_bbox_format(settings.vllm_model)
    t0 = time.time()
    result = make_provider(settings).analyze(
        [LabeledImage(im, f"Frame {i + 1} (t={t:.2f}s):") for i, (im, t) in enumerate(zip(images, times))], SCENE_PROMPT, SceneAnalysis)
    h, w = images[0].shape[:2]
    boxes = []
    for i, s in enumerate(result.subjects):
        x1, y1, x2, y2 = bbox_to_unit(s.bbox, fmt, w, h)
        boxes.append(((x1 * w, y1 * h, x2 * w, y2 * h), f"{'AB'[i]}: {s.description}"[:40], 1.0))
    if result.focus_roi is not None:
        x1, y1, x2, y2 = bbox_to_unit(result.focus_roi, fmt, w, h)
        boxes.append(((x1 * w, y1 * h, x2 * w, y2 * h), "focus_roi", 1.0))
    return result.model_dump_json(indent=2), boxes, time.time() - t0, settings.vllm_model, fmt


def upload(video: str | None):
    if not video:
        return gr.update(), "", None
    d = duration(video)
    return gr.update(maximum=max(1.0, round(d, 1)), value=0, step=0.1), f"{d:.1f} s", None


def run(video, t_s, names, conf_override, iou, vlm_window):
    if not video:
        raise gr.Error("Upload a video first")
    if not names:
        raise gr.Error("Pick at least one model")
    image, t_real = frame_at(video, t_s)
    h, w = image.shape[:2]
    gallery, rows, info, colors = [(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), f"original  t={t_real:.2f}s  {w}x{h}")], [], [], {}
    vlm_text = ""
    for name in names:
        if name == VLM:
            frames = [image]
            for k in (1, 2, 3):
                try:
                    frames.append(frame_at(video, min(duration(video) - 0.1, t_s + vlm_window * k / 3))[0])
                except gr.Error:
                    break
            times = [t_s + vlm_window * k / 3 for k in range(len(frames))]
            try:
                vlm_text, boxes, dt, vname, fmt = vlm_boxes(frames, times)
            except Exception as e:  # noqa: BLE001 - shown in the page
                vlm_text, boxes, dt, vname, fmt = f"VLM failed: {e}", [], 0.0, "?", "?"
            gallery.append((draw(image, boxes, colors), f"{VLM} ({vname}, {fmt}, {dt:.1f} s, {len(frames)} frames)"))
            rows += [{"model": VLM, "label": lab, "conf": "", "x1": round(b[0]), "y1": round(b[1]), "x2": round(b[2]), "y2": round(b[3])} for b, lab, _ in boxes]
            info.append(f"{VLM}: {len(boxes)} boxes, {dt:.1f} s")
            continue
        m = model(name)
        conf = conf_override or m.default_conf
        t0 = time.time()
        boxes = m(image, conf=conf, iou=iou)
        dt = (time.time() - t0) * 1000
        gallery.append((draw(image, boxes, colors), f"{name}  conf>={conf:.3f}  {len(boxes)} boxes  {dt:.0f} ms ({m.device.replace('ExecutionProvider', '')})"))
        rows += [{"model": name, "label": lab, "conf": round(c, 3), "x1": round(b[0]), "y1": round(b[1]), "x2": round(b[2]), "y2": round(b[3])} for b, lab, c in boxes]
        info.append(f"{name}: {len(boxes)} boxes ({', '.join(sorted({r[1] for r in boxes})) or 'none'})")
    table = pd.DataFrame(rows, columns=["model", "label", "conf", "x1", "y1", "x2", "y2"])
    return gallery, table, "\n".join(info), vlm_text


def scan(video, names, conf_override, iou, count, progress=gr.Progress()):
    """Share of sampled frames with each label, per model, over the whole video."""
    if not video:
        raise gr.Error("Upload a video first")
    names = [n for n in names if n != VLM]
    if not names:
        raise gr.Error("Pick at least one detector (the VLM is not run over a whole video)")
    d = duration(video)
    times = np.linspace(0.0, max(0.0, d - 0.5), int(count))
    frames = []
    for i, t in enumerate(progress.tqdm(times, desc="decoding")):
        try:
            frames.append(frame_at(video, float(t))[0])
        except gr.Error:
            pass
    rows = []
    for name in names:
        m = model(name)
        conf = conf_override or m.default_conf
        seen: dict[str, int] = {}
        for im in progress.tqdm(frames, desc=name):
            for lab in {b[1] for b in m(im, conf=conf, iou=iou)}:
                seen[lab] = seen.get(lab, 0) + 1
        if not seen:
            rows.append({"model": name, "label": "(nothing)", "frames": 0, "share": 0.0, "of": len(frames)})
        rows += [{"model": name, "label": lab, "frames": n, "share": round(n / len(frames), 3), "of": len(frames)} for lab, n in sorted(seen.items())]
    return pd.DataFrame(rows, columns=["model", "label", "frames", "share", "of"])


def build() -> gr.Blocks:
    choices = variants() + [NUDENET, VLM]
    default = [c for c in choices if c in ("anime_censor_detection: censor_detect_v1.0_s", "anime_person_detection: person_detect_v1.3_s")]
    with gr.Blocks(title="Detection viewer") as demo:
        gr.Markdown("## Detection viewer\nUpload a video, pick models, move the time slider. Boxes are drawn on the frame at that time.")
        with gr.Row():
            with gr.Column(scale=1):
                video = gr.Video(label="Video", sources=["upload"])
                length = gr.Textbox(label="Length", interactive=False)
                t = gr.Slider(0, 1, value=0, step=0.1, label="Time (s)")
                names = gr.CheckboxGroup(choices, value=default, label="Models")
                conf = gr.Slider(0, 0.9, value=0, step=0.01, label="Confidence (0 = each model's recommended threshold)")
                iou = gr.Slider(0.1, 0.95, value=0.7, step=0.05, label="NMS IoU")
                window = gr.Slider(0.5, 20, value=3, step=0.5, label="VLM: seconds covered by its 4 frames")
                go = gr.Button("Detect at this time", variant="primary")
                with gr.Accordion("Whole video", open=False):
                    count = gr.Slider(10, 300, value=60, step=10, label="Frames sampled")
                    scan_btn = gr.Button("Scan the whole video (detectors only)")
            with gr.Column(scale=2):
                gallery = gr.Gallery(label="Results", columns=2, height="auto", object_fit="contain")
                summary = gr.Textbox(label="Summary", lines=4, interactive=False)
                table = gr.Dataframe(label="Boxes (pixels of the decoded frame, longest side 960)", interactive=False)
                vlm_out = gr.Code(label="VLM answer", language="json")
                scan_table = gr.Dataframe(label="Whole video: frames with each label", interactive=False)
        video.change(upload, video, [t, length, scan_table])
        go.click(run, [video, t, names, conf, iou, window], [gallery, table, summary, vlm_out])
        t.release(run, [video, t, names, conf, iou, window], [gallery, table, summary, vlm_out])
        scan_btn.click(scan, [video, names, conf, iou, count], scan_table)
    return demo


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7861)
    ap.add_argument("--share-lan", action="store_true", help="listen on every interface (default: this machine only)")
    a = ap.parse_args()
    build().queue().launch(server_name="0.0.0.0" if a.share_lan else "127.0.0.1", server_port=a.port,
                           allowed_paths=[tempfile.gettempdir()])
