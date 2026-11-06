"""Genital-part boxes in anime frames and the stroke direction they show.

The detector is deepghs' anime_censor_detection (a YOLOv8 trained on anime/illustrations, labels nipple_f, penis,
pussy), run with onnxruntime only: the dghs-imgutils package that ships it pins numpy 1.x and OpenCV 4, which would
change the flow results. Preprocessing and box decoding follow imgutils' yolo_predict, so the boxes are the same.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import os
import threading
from collections.abc import Iterable
from concurrent.futures import Executor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from funscript_gen.paths import cache_dir
from funscript_gen.video.decoder import iter_frames, pieces

REPO = "deepghs/anime_censor_detection"
REVISION = "0cf62fd6b28213b40ae0c0055f92e7ae6a96bdc2"  # pinned: a new upload must not change the results
MODEL = "censor_detect_v1.0_s/model.onnx"
CONF = 0.238  # the model's recommended threshold (threshold.json, best F1)
DECODE_SIDE = 960  # frames are decoded at most this large, as in the validation run
# Used when the installed onnxruntime has them (onnxruntime-gpu, onnxruntime-directml), else the CPU.
GPU_PROVIDERS = ("CUDAExecutionProvider", "DmlExecutionProvider")
# Longest stretch one detection job covers when a span is detected in parallel (cached_detect_span's `pool`).
PIECE_S = 5.0
# The boxes of a span depend only on the video, the span and the detection settings, so they are kept on disk: a
# second run on the same video (another setting, a validation run) skips the detector. None turns the cache off.
CACHE_DIR: Path | None = cache_dir("parts")

Box = tuple[tuple[float, float, float, float], str, float]  # ((x1, y1, x2, y2) in frame pixels, label, confidence)


class PartDetector:
    """Detects penis / pussy / nipple boxes in BGR frames. Downloads the model on first use (about 43 MB).

    Safe to call from several threads at once (onnxruntime sessions are). On the CPU each call uses `threads`
    threads without busy-waiting: onnxruntime's default (every physical core, spinning) took 52 ms per frame but
    623 ms of CPU, 4 threads without spinning 65 ms and 213 ms, so scenes are better detected side by side.
    With `gpu` it runs on a GPU provider the installed onnxruntime offers; `device` says which one is in use. With
    `require_gpu` a GPU that does not load raises devices.DeviceError instead of falling back to the CPU.
    """

    def __init__(self, model_path: str | Path | None = None, threads: int = 4, gpu: bool = True,
                 require_gpu: bool = False) -> None:
        import onnxruntime as ort

        if model_path is None:
            from huggingface_hub import hf_hub_download

            model_path = hf_hub_download(REPO, MODEL, revision=REVISION)
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads  # 0 = onnxruntime's default (the physical cores)
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = None
        for provider in [p for p in GPU_PROVIDERS if gpu and p in ort.get_available_providers()]:
            if provider == "CUDAExecutionProvider" and hasattr(ort, "preload_dlls"):
                try:
                    ort.preload_dlls()  # CUDA and cuDNN from the nvidia-* wheels (onnxruntime-gpu[cuda,cudnn])
                except Exception:  # noqa: BLE001 - system-wide CUDA may still be found
                    pass
            try:
                session = ort.InferenceSession(str(model_path), so, providers=[provider, "CPUExecutionProvider"])
            except Exception:  # noqa: BLE001 - driver or library missing: try the next one
                continue
            if session.get_providers()[0] == provider:  # CUDA falls back to the CPU quietly without its libraries
                self.session = session
                break
        if self.session is None:
            if require_gpu:
                from funscript_gen.devices import no_gpu

                raise no_gpu("part")
            self.session = ort.InferenceSession(str(model_path), so, providers=["CPUExecutionProvider"])
        self.device = self.session.get_providers()[0]
        # DirectML cannot run one session from several threads at once; the CPU and CUDA can
        self.lock = threading.Lock() if self.device == "DmlExecutionProvider" else contextlib.nullcontext()
        names = ast.literal_eval(self.session.get_modelmeta().custom_metadata_map["names"])
        self.labels = [names[i] for i in range(len(names))]
        self.size = 640

    def __call__(self, image: np.ndarray, conf: float = CONF, iou: float = 0.7) -> list[Box]:
        h, w = image.shape[:2]
        rgb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)).resize((self.size, self.size), Image.BICUBIC)
        data = (np.asarray(rgb).transpose(2, 0, 1) / 255.0).astype(np.float32)[None]
        with self.lock:
            (out,) = self.session.run(["output0"], {"images": data})
        return decode(out[0], self.labels, conf, iou, (w / self.size, h / self.size), (w, h))


def decode(out: np.ndarray, labels: list[str], conf: float, iou: float,
           scale: tuple[float, float], frame: tuple[int, int]) -> list[Box]:
    """YOLOv8 output (4 + classes, anchors) -> boxes above `conf` after non-maximum suppression."""
    scores = out[4:].T
    best = scores.max(axis=1)
    keep = best > conf
    if not keep.any():
        return []
    xywh, scores, best = out[:4].T[keep], scores[keep], best[keep]
    boxes = np.concatenate([xywh[:, :2] - xywh[:, 2:] / 2, xywh[:, :2] + xywh[:, 2:] / 2], axis=1)
    sx, sy = scale
    fw, fh = frame
    result = []
    for k in _nms(boxes, best, iou):
        x1, y1, x2, y2 = boxes[k]
        box = (float(np.clip(round(x1 * sx), 0, fw)), float(np.clip(round(y1 * sy), 0, fh)),
               float(np.clip(round(x2 * sx), 0, fw)), float(np.clip(round(y2 * sy), 0, fh)))
        result.append((box, labels[int(scores[k].argmax())], float(best[k])))
    return result


def _nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> list[int]:
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        w = np.maximum(0.0, np.minimum(x2[i], x2[order[1:]]) - np.maximum(x1[i], x1[order[1:]]) + 1)
        h = np.maximum(0.0, np.minimum(y2[i], y2[order[1:]]) - np.maximum(y1[i], y1[order[1:]]) + 1)
        inter = w * h
        order = order[1:][inter / (areas[i] + areas[order[1:]] - inter) <= iou]
    return keep


def detect_span(detector, video: str | Path, start_ms: float, end_ms: float, fps: float, conf: float = CONF,
                stop: threading.Event | None = None) -> tuple[list[float], list[list[Box]], tuple[int, int]]:
    """Boxes in the frames of start_ms..end_ms at `fps`; also the decoded frame size (w, h). Ends early (with the
    frames so far) once `stop` is set."""
    times, boxes, size = [], [], (0, 0)
    for f in iter_frames(video, target_fps=fps, max_side=DECODE_SIDE, start_ms=start_ms, end_ms=end_ms):
        if f.t_ms >= end_ms or (stop is not None and stop.is_set()):
            break
        size = (f.image.shape[1], f.image.shape[0])
        times.append(f.t_ms)
        boxes.append(detector(f.image, conf=conf))
    return times, boxes, size


def _cache_path(video: str | Path, start_ms: float, end_ms: float, fps: float, conf: float, device) -> Path | None:
    if CACHE_DIR is None:
        return None
    try:
        st = Path(video).stat()
    except OSError:
        return None
    key = json.dumps([str(Path(video).resolve()), st.st_size, st.st_mtime_ns, start_ms, end_ms, fps, conf,
                      DECODE_SIDE, REPO, REVISION, MODEL, device])
    return CACHE_DIR / f"{hashlib.sha256(key.encode()).hexdigest()}.json"


def cached_detect_span(detector, video: str | Path, start_ms: float, end_ms: float, fps: float, conf: float = CONF,
                       stop: threading.Event | None = None, pool: Executor | None = None,
                       ) -> tuple[list[float], list[list[Box]], tuple[int, int]]:
    """detect_span through the disk cache (CACHE_DIR), keyed by the video file, the span, the settings and the
    detector's device (CUDA boxes can differ by a pixel). A span stopped early is not stored. With a `pool`, the
    span is detected in pieces of at most PIECE_S on it (each frame's boxes only depend on the frame, so the
    result is the same)."""
    path = _cache_path(video, start_ms, end_ms, fps, conf, getattr(detector, "device", None))
    if path is not None and path.exists():
        try:
            data = json.loads(path.read_text())
            boxes = [[(tuple(b), label, c) for b, label, c in frame] for frame in data["boxes"]]
            return data["times"], boxes, tuple(data["size"])
        except (OSError, ValueError, KeyError, TypeError):
            pass  # unreadable: detect again
    if pool is None:
        times, boxes, size = detect_span(detector, video, start_ms, end_ms, fps, conf=conf, stop=stop)
    else:
        jobs = [pool.submit(detect_span, detector, video, a, b, fps, conf=conf, stop=stop)
                for a, b in pieces(start_ms, end_ms, PIECE_S * 1000)]
        found = [job.result() for job in jobs]
        times = [t for piece in found for t in piece[0]]
        boxes = [b for piece in found for b in piece[1]]
        size = next((piece[2] for piece in found if piece[0]), (0, 0))
    if path is not None and not (stop is not None and stop.is_set()):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"times": times, "boxes": boxes, "size": size}))
        os.replace(tmp, path)
    return times, boxes, size


def penis_share(frames: Iterable[list[Box]]) -> float:
    frames = list(frames)
    return sum(any(lab == "penis" for _, lab, _ in b) for b in frames) / len(frames) if frames else 0.0


def penis_vulva_distance(frames: list[list[Box]], size: tuple[int, int]) -> tuple[np.ndarray, float]:
    """Per frame: the distance between the most confident penis box's centre and the nearest pussy box's centre
    over the frame diagonal (NaN without both). Also the share of penis boxes touching the frame border."""
    w, h = size
    diag = float(np.hypot(w, h))
    dist = np.full(len(frames), np.nan)
    edge = []
    for i, boxes in enumerate(frames):
        pen = [b for b in boxes if b[1] == "penis"]
        if not pen:
            continue
        (x1, y1, x2, y2), _, _ = max(pen, key=lambda b: b[2])
        edge.append(x1 <= 2 or y1 <= 2 or x2 >= w - 2 or y2 >= h - 2)
        pus = [b for b, lab, _ in boxes if lab == "pussy"]
        if pus:
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            dist[i] = min(np.hypot(cx - (b[0] + b[2]) / 2, cy - (b[1] + b[3]) / 2) for b in pus) / diag
    return dist, (float(np.mean(edge)) if edge else 0.0)


def _detrend(x: np.ndarray, fps: float, win_s: float = 2.0) -> np.ndarray:
    k = max(3, int(win_s * fps) | 1)
    pad = np.pad(x, k // 2, mode="edge")
    return x - np.convolve(pad, np.ones(k) / k, mode="valid")


def distance_sign(t_ms: np.ndarray, dist: np.ndarray, flow_t: np.ndarray, flow_x: np.ndarray, fps: float,
                  min_cover: float = 0.6, max_lag_ms: float = 0.0) -> float | None:
    """Correlation of the penis-vulva distance with the flow position (both without their drift over 2 s).

    Apart = pulled out = high, so a negative value says the flow's sign is inverted. Both come from the same frames,
    so by default there is no lag search: at 10 fps one sample is a third of a 3 Hz stroke, and the best of lags
    -1..+1 often has the sign opposite to lag 0 (25 clips: 13 of 28 scenes with boxes, 3 judged wrong that lag 0
    gets right). None when the distance is known in fewer than `min_cover` of the frames or nothing moves.
    """
    ok = ~np.isnan(dist)
    if len(dist) < 20 or ok.mean() < min_cover or len(flow_t) < 2:
        return None
    x = _detrend(np.interp(t_ms, t_ms[ok], dist[ok]), fps)
    y = _detrend(np.interp(t_ms, flow_t, flow_x), fps)
    best = None
    lags = int(max_lag_ms / 1000 * fps)
    for lag in range(-lags, lags + 1):
        a, b = (x[lag:], y[: len(y) - lag]) if lag >= 0 else (x[:lag], y[-lag:])
        if len(a) > 10 and a.std() > 1e-9 and b.std() > 1e-9:
            r = float(np.corrcoef(a, b)[0, 1])
            if best is None or abs(r) > abs(best):
                best = r
    return best
