"""Offline: share of frames (2 fps, first 300 s, decoded as the part check does) with penis / vulva / both boxes,
the part check's anime detector (at part_conf) against NudeNet 320n (deepghs/nudenet_onnx, pinned; trained on photos,
tried for the 3D clips) at 320 and 640 input and two thresholds. Runs on the CPU (a few minutes per clip).

usage: uv run python scripts/part_detectors.py CLIP[,CLIP...]
"""
import sys
import time

import cv2
import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from funscript_gen.tracking.parts import PartDetector, decode
from funscript_gen.validate import clips, load_manifest
from funscript_gen.video.decoder import iter_frames

NN_LABELS = ["FEMALE_GENITALIA_COVERED", "FACE_FEMALE", "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED",
             "FEMALE_GENITALIA_EXPOSED", "MALE_BREAST_EXPOSED", "ANUS_EXPOSED", "FEET_EXPOSED", "BELLY_COVERED",
             "FEET_COVERED", "ARMPITS_COVERED", "ARMPITS_EXPOSED", "FACE_MALE", "BELLY_EXPOSED",
             "MALE_GENITALIA_EXPOSED", "ANUS_COVERED", "FEMALE_BREAST_COVERED", "BUTTOCKS_COVERED"]
MAP = {"MALE_GENITALIA_EXPOSED": "penis", "FEMALE_GENITALIA_EXPOSED": "pussy"}


class NudeNet:
    def __init__(self, side=320):
        path = hf_hub_download("deepghs/nudenet_onnx", "320n.onnx", revision="44956a0587943016350c7815f9e0dec089d45cae")
        so = ort.SessionOptions(); so.intra_op_num_threads = 4
        self.s = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
        self.side = side

    def __call__(self, image, conf=0.2, iou=0.45):
        h, w = image.shape[:2]
        m = max(h, w)
        sq = cv2.copyMakeBorder(image, 0, m - h, 0, m - w, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        blob = cv2.dnn.blobFromImage(sq, 1 / 255.0, (self.side, self.side), swapRB=True)
        (out,) = self.s.run(None, {"images": blob})
        f = m / self.side
        return [(b, MAP.get(lab, lab), c) for b, lab, c in decode(out[0], NN_LABELS, conf, iou, (f, f), (w, h))]


names = sys.argv[1].split(",")
man = load_manifest()
cl = {c.name: c for c in clips(man, "all")}
old = PartDetector(threads=4, gpu=False)
dets = {"anime": (old, 0.15), "nn320": (NudeNet(320), 0.2), "nn320lo": (None, 0.1), "nn640": (NudeNet(640), 0.2)}  # None: nn320
for name in names:
    cnt = {k: np.zeros(3) for k in dets}; n = 0; t0 = time.time()
    for fr in iter_frames(cl[name].video, target_fps=2, max_side=960, end_ms=300_000):
        n += 1
        for k, (d, conf) in dets.items():
            if d is None:
                d = dets["nn320"][0]
            labs = {lab for _, lab, _ in d(fr.image, conf=conf)}
            p, v = "penis" in labs, "pussy" in labs
            cnt[k] += [p, v, p and v]
    print(f"{name:8s} frames {n:4d} ({time.time()-t0:.0f}s) " +
          "  ".join(f"{k} P {c[0]/n:.2f} V {c[1]/n:.2f} both {c[2]/n:.2f}" for k, c in cnt.items()), flush=True)
