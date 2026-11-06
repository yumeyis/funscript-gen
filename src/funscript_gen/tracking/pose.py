"""Multi-person pose estimation + tracking (Ultralytics YOLO-pose + ByteTrack)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from funscript_gen.video.decoder import Frame


@dataclass(slots=True)
class Person:
    track_id: int  # -1 when the tracker has not confirmed the detection yet
    box: np.ndarray  # (4,) xyxy in frame pixels
    kpts: np.ndarray  # (17, 2) COCO keypoints in frame pixels
    kconf: np.ndarray  # (17,) keypoint confidences

    @property
    def center(self) -> np.ndarray:
        return np.array([(self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2])

    @property
    def area(self) -> float:
        return float(max(0.0, self.box[2] - self.box[0]) * max(0.0, self.box[3] - self.box[1]))


@dataclass(slots=True)
class PoseFrame:
    t_ms: float
    width: int
    height: int
    people: list[Person] = field(default_factory=list)


class PoseTracker:
    def __init__(
        self,
        model: str = "yolo11n-pose.pt",
        device: str | None = None,
        conf: float = 0.25,
        imgsz: int = 640,
    ) -> None:
        try:
            from ultralytics import YOLO
        except ImportError:  # an optional extra: the default install has no PyTorch
            raise RuntimeError("the skeleton mode (--mode pose) needs the optional packages: uv sync --extra pose") from None

        self.model = YOLO(model)
        self.device = device
        self.conf = conf
        self.imgsz = imgsz

    def reset(self) -> None:
        """Forget track identities, e.g. at a scene cut."""
        predictor = getattr(self.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", None) or []:
            tracker.reset()

    def detect(self, frame: Frame) -> PoseFrame:
        """Single-image detection without tracking (ids are -1)."""
        result = self.model.predict(frame.image, conf=self.conf, imgsz=self.imgsz, device=self.device, verbose=False)[0]
        return self._convert(frame, result)

    def __call__(self, frame: Frame) -> PoseFrame:
        result = self.model.track(
            frame.image,
            persist=True,
            tracker="bytetrack.yaml",
            conf=self.conf,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )[0]
        return self._convert(frame, result)

    @staticmethod
    def _convert(frame: Frame, result) -> PoseFrame:
        h, w = frame.image.shape[:2]
        out = PoseFrame(frame.t_ms, w, h)
        boxes, kps = result.boxes, result.keypoints
        if boxes is None or kps is None or len(boxes) == 0:
            return out
        xyxy = boxes.xyxy.cpu().numpy()
        ids = boxes.id.int().cpu().numpy() if boxes.id is not None else np.full(len(xyxy), -1)
        kxy = kps.xy.cpu().numpy()
        kconf = kps.conf.cpu().numpy() if kps.conf is not None else np.ones(kxy.shape[:2])
        for i in range(len(xyxy)):
            out.people.append(Person(int(ids[i]), xyxy[i], kxy[i], kconf[i]))
        return out
