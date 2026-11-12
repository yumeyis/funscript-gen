from dataclasses import replace

import numpy as np
import pytest

from funscript_gen.direction import flip_by_asymmetry, flip_by_parts
from funscript_gen.pipeline import PipelineOptions, ScenePlan, collect_parts
from funscript_gen.signal.process import analyze
from funscript_gen.tracking import parts
from funscript_gen.tracking.flow import MIN_AMPLITUDE_PX
from funscript_gen.tracking.parts import decode, distance_sign, penis_vulva_distance
from funscript_gen.video.scenes import Scene


def test_decode_scales_boxes_and_drops_overlaps_and_weak_ones():
    labels = ["nipple_f", "penis", "pussy"]
    #                   cx   cy   w   h  nipple penis pussy
    anchors = np.array([[320, 320, 64, 128, 0.0, 0.9, 0.1],
                        [322, 318, 64, 128, 0.0, 0.5, 0.1],   # overlaps the first: suppressed
                        [100, 500, 40, 40, 0.0, 0.1, 0.6],
                        [500, 100, 40, 40, 0.1, 0.0, 0.0]],   # below the threshold
                       np.float32).T
    boxes = decode(anchors, labels, 0.2, 0.7, (1.5, 540 / 640), (960, 540))
    assert [(lab, round(c, 2)) for _, lab, c in boxes] == [("penis", 0.9), ("pussy", 0.6)]
    assert boxes[0][0] == (432.0, 216.0, 528.0, 324.0)  # 288..352 x 1.5, 256..384 x 0.84375


def _wave(seconds=8.0, fps=10.0):
    t = np.arange(int(seconds * fps)) * 1000 / fps
    return t, np.sin(2 * np.pi * 1.2 * t / 1000)


def test_distance_sign_follows_the_flow_position():
    t, x = _wave()
    drift = np.linspace(0, 0.05, len(t))  # slow change of framing: removed with the 2 s mean
    assert distance_sign(t, 0.1 + 0.03 * x + drift, t, x, 10.0) > 0.9
    assert distance_sign(t, 0.1 - 0.03 * x + drift, t, x, 10.0) < -0.9
    gaps = 0.1 + 0.03 * x
    gaps[::2] = np.nan  # known in half the frames: below min_cover
    assert distance_sign(t, gaps, t, x, 10.0) is None


def test_distance_sign_does_not_reach_half_a_fast_stroke_away():
    # 1.7 Hz: half a stroke is 300 ms. A lag search that wide would match the inverted wave.
    t = np.arange(80) * 100.0
    x = np.sin(2 * np.pi * 1.7 * t / 1000)
    assert distance_sign(t, 0.1 + 0.03 * x, t, x, 10.0) > 0.9


def test_distance_sign_keeps_the_sign_of_lag_zero_on_fast_strokes():
    # 4 Hz, the distance inverted and 50 ms late: one sample (100 ms) away the waves line up the other way
    # and correlate more strongly than at lag 0 (E02: the best of lags -1..+1 kept two inverted scenes).
    t = np.arange(80) * 100.0
    x = np.sin(2 * np.pi * 4.0 * t / 1000)
    late = -np.sin(2 * np.pi * 4.0 * (t - 50.0) / 1000)
    assert distance_sign(t, 0.1 + 0.03 * late, t, x, 10.0) < 0
    assert distance_sign(t, 0.1 + 0.03 * late, t, x, 10.0, max_lag_ms=100.0) > 0


def test_penis_vulva_distance_uses_the_best_penis_box_and_counts_cut_off_boxes():
    frames = [
        [((100, 100, 140, 180), "penis", 0.9), ((0, 0, 10, 10), "penis", 0.2), ((100, 200, 140, 240), "pussy", 0.5)],
        [((0, 100, 40, 180), "penis", 0.9)],  # touches the left border, no vulva
        [],
    ]
    dist, edge = penis_vulva_distance(frames, (300, 400))
    assert dist[0] == pytest.approx(80 / 500) and np.isnan(dist[1]) and np.isnan(dist[2])
    assert edge == 0.5


def _plan(index: int, t: np.ndarray, x: np.ndarray) -> ScenePlan:
    plan = ScenePlan(Scene(index, index * 10000.0, index * 10000.0 + 8000.0))
    plan.flow_position = (t, x)
    plan.signal = analyze(t, x, replace(PipelineOptions().signal, min_amplitude=MIN_AMPLITUDE_PX))
    return plan


def _fake_detect(kinds: dict[int, str]):
    """detect_span stand-in: per scene index, the penis box moves with the motion ("with"), against it
    ("against"), sits on the frame border ("edge") or is missing ("none"); the vulva box stays put."""
    def detect_span(detector, video, start_ms, end_ms, fps, conf=parts.CONF, stop=None):
        kind = kinds[int(start_ms // 10000)]
        times = list(np.arange(start_ms, end_ms, 1000 / fps))
        boxes = []
        for t in times:
            if kind == "none":
                boxes.append([])
                continue
            x = np.sin(2 * np.pi * 1.2 * (t % 10000) / 1000)  # from the scene's start, also in a piece
            gap = 60 + 30 * (-x if kind == "against" else x)
            left = 0 if kind == "edge" else 200
            boxes.append([((left, 300 - gap - 40, left + 40, 300 - gap), "penis", 0.8),
                          ((200, 300, 240, 340), "pussy", 0.7)])
        return times, boxes, (960, 540)
    return detect_span


@pytest.mark.parametrize("invert", [False, True])
def test_part_check_flips_scenes_whose_distance_moves_against_the_output(monkeypatch, invert):
    kinds = {0: "against", 1: "with", 2: "none", 3: "edge"}
    monkeypatch.setattr(parts, "detect_span", _fake_detect(kinds))
    t = np.arange(240) * 1000 / 30
    x = np.sin(2 * np.pi * 1.2 * t / 1000)
    plans = [_plan(k, t + k * 10000.0, x.copy()) for k in kinds]
    opts = PipelineOptions(part_sign=True, invert=invert)
    assert collect_parts(plans, None, opts, detector=object()) == (None, None)  # a stand-in detector has no device
    flip_by_parts(plans, opts)
    # On the output: inverted, the distance that follows the flow moves against the output.
    flipped = {k for k, p in enumerate(plans) if p.flow_position[1][10] != x[10]}
    assert flipped == ({1} if invert else {0})
    assert [p.part_flipped for p in plans[:2]] == [not invert, invert] and not plans[2].part_flipped
    assert all(p.part_sign > 0.9 for p in plans[:2])  # after a flip the distance follows the output
    assert "方向翻轉" in plans[1 if invert else 0].note and "一致" in plans[0 if invert else 1].note
    assert plans[2].part_sign is None and plans[3].part_sign is None


def test_scenes_the_part_check_flipped_skip_the_asymmetry_check():
    # rises in 0.15 s, falls in 0.45 s: the asymmetry check would flip it
    t = np.arange(240) * 1000 / 30
    phase = (t / 1000) % 0.6
    x = np.where(phase < 0.15, phase / 0.15, 1 - (phase - 0.15) / 0.45) * 20
    for flipped in (False, True):
        plan = _plan(0, t, x)
        plan.part_flipped = flipped
        plan.part_sign = 0.6  # flipped, or kept with a clear answer: a kept scene stays open to the check
        flip_by_asymmetry([plan], PipelineOptions(asym_sign=True))
        assert plan.asym_flipped is not flipped


def test_part_check_reports_a_missing_model_in_the_notes(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(parts, "PartDetector", broken)
    t, x = _wave(8.0, 30.0)
    plan = _plan(0, t, x)
    opts = PipelineOptions(part_sign=True)
    device, error = collect_parts([plan], None, opts)
    assert device is None and error == "offline"
    flip_by_parts([plan], opts, error)
    assert "部位偵測無法使用：offline" in plan.note and not plan.part_flipped


class _FakeSession:
    def __init__(self, path, so, providers):
        if providers[0] == "DmlExecutionProvider":
            raise RuntimeError("no DirectML device")
        # CUDA without its libraries: onnxruntime quietly runs on the CPU
        self.providers = ["CPUExecutionProvider"] if providers[0] == "CUDAExecutionProvider" else providers

    def get_providers(self):
        return self.providers

    def get_modelmeta(self):
        class Meta:
            custom_metadata_map = {"names": "{0: 'nipple_f', 1: 'penis', 2: 'pussy'}"}
        return Meta()


@pytest.mark.parametrize("available, gpu, device", [
    (["CPUExecutionProvider"], True, "CPUExecutionProvider"),
    (["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"], True, "CPUExecutionProvider"),
    (["DmlExecutionProvider", "CPUExecutionProvider"], True, "CPUExecutionProvider"),
])
def test_detector_falls_back_to_the_cpu_when_no_gpu_provider_works(monkeypatch, available, gpu, device):
    import onnxruntime as ort

    monkeypatch.setattr(ort, "get_available_providers", lambda: available)
    monkeypatch.setattr(ort, "InferenceSession", _FakeSession)
    monkeypatch.setattr(ort, "preload_dlls", lambda: None, raising=False)
    d = parts.PartDetector("model.onnx", gpu=gpu)
    assert d.device == device and d.labels == ["nipple_f", "penis", "pussy"]


def test_detector_uses_a_working_gpu_provider(monkeypatch):
    import onnxruntime as ort

    class Works(_FakeSession):
        def __init__(self, path, so, providers):
            self.providers = providers

    monkeypatch.setattr(ort, "get_available_providers", lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(ort, "InferenceSession", Works)
    assert parts.PartDetector("model.onnx").device == "DmlExecutionProvider"
    assert parts.PartDetector("model.onnx", gpu=False).device == "CPUExecutionProvider"


class _SlowDetector:
    """Stands in for PartDetector: a penis box in every frame, a little slow, and it counts the frames."""
    device = "CPUExecutionProvider"

    def __init__(self):
        import threading

        self.frames = 0
        self.lock = threading.Lock()

    def __call__(self, image, conf=parts.CONF):
        import time

        time.sleep(0.01)
        with self.lock:
            self.frames += 1
        return [((10, 10, 30, 30), "penis", 0.9)]


def test_part_detection_starts_with_the_scene_cut_and_stops_on_cancel(tmp_path, monkeypatch):
    import threading
    import time

    from funscript_gen import pipeline
    from test_parallel import _clip as clip

    clip(tmp_path / "c.mp4", seconds=6.0, cut_every_s=1.5)
    detector = _SlowDetector()
    monkeypatch.setattr(parts, "PartDetector", lambda **kw: detector)
    seen = {}
    real = pipeline.plan_scenes

    def slow_ai(scenes, opts, progress=None, on_seen=None):
        time.sleep(1.0)  # the detection runs meanwhile
        seen["frames during the AI"] = detector.frames
        return real(scenes, opts, progress, on_seen)

    monkeypatch.setattr(pipeline, "plan_scenes", slow_ai)
    opts = PipelineOptions(use_ai=False, flow_workers=2, asym_audio=False, part_sign=True)
    result = pipeline.generate(tmp_path / "c.mp4", opts)
    assert seen["frames during the AI"] > 0 and result.part_device == "CPUExecutionProvider"

    class Stop(Exception):
        pass

    def progress(phase, t_ms):
        if phase == "signal":
            raise Stop

    detector.frames = 0
    before = threading.active_count()
    with pytest.raises(Stop):
        pipeline.generate(tmp_path / "c.mp4", opts, progress)
    stopped = detector.frames
    time.sleep(0.3)
    assert detector.frames == stopped and threading.active_count() <= before  # nothing keeps detecting


def test_detections_are_cached_per_video_span_and_setting(tmp_path, monkeypatch):
    import threading

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    calls = []

    def detect_span(detector, v, start_ms, end_ms, fps, conf=parts.CONF, stop=None):
        calls.append((start_ms, fps))
        return [start_ms, start_ms + 100.0], [[((1.0, 2.0, 3.0, 4.0), "penis", 0.9)], []], (960, 540)

    monkeypatch.setattr(parts, "detect_span", detect_span)
    monkeypatch.setattr(parts, "CACHE_DIR", tmp_path / "cache")
    detector = type("Detector", (), {"device": "CPUExecutionProvider"})()
    first = parts.cached_detect_span(detector, video, 0.0, 1000.0, 10.0)
    assert parts.cached_detect_span(detector, video, 0.0, 1000.0, 10.0) == first and len(calls) == 1
    parts.cached_detect_span(detector, video, 0.0, 1000.0, 1.0)  # another frame rate: another entry
    assert len(calls) == 2
    stop = threading.Event()
    stop.set()
    parts.cached_detect_span(detector, video, 1000.0, 2000.0, 10.0, stop=stop)  # stopped early: not kept
    parts.cached_detect_span(detector, video, 1000.0, 2000.0, 10.0)
    assert len(calls) == 4
    video.write_bytes(b"xy")  # the file changed
    parts.cached_detect_span(detector, video, 0.0, 1000.0, 10.0)
    assert len(calls) == 5


@pytest.mark.parametrize("at_highs", [True, False])
def test_a_kept_scene_whose_sound_onsets_fall_at_the_highs_is_listed_for_checking(at_highs):
    t = np.arange(300) * 1000 / 30
    x = np.sin(2 * np.pi * 1.2 * t / 1000)  # rises as fast as it falls: the asymmetry check keeps it
    env_t = np.arange(0, 10000, 10.0)
    onsets = 1000 / 1.2 * (np.arange(12) + (0.25 if at_highs else 0.75))  # sin highs at (k + 1/4) / 1.2 s
    env = sum(np.exp(-(((env_t - o) / 30) ** 2)) for o in onsets)
    plan = _plan(0, t, x)
    flip_by_asymmetry([plan], PipelineOptions(asym_sign=True, sound_hint=True), (env_t, env))
    assert not plan.asym_flipped and plan.audio_sign is not None
    assert bool(plan.sign_doubt) is at_highs and ("請確認" in plan.note) is at_highs
    quiet = _plan(0, t, x)
    flip_by_asymmetry([quiet], PipelineOptions(asym_sign=True), (env_t, env))  # off by default
    assert not quiet.sign_doubt and "請確認" not in quiet.note


def test_a_span_detected_in_pieces_gives_the_same_boxes(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from test_parallel import _clip

    _clip(tmp_path / "c.mp4", seconds=4.0)
    monkeypatch.setattr(parts, "CACHE_DIR", None)
    monkeypatch.setattr(parts, "PIECE_S", 0.7)
    detector = lambda image, conf=parts.CONF: [((float(image.mean()), 0.0, 1.0, 1.0), "penis", conf)]  # noqa: E731
    whole = parts.cached_detect_span(detector, tmp_path / "c.mp4", 250.0, 3900.0, 10.0)
    with ThreadPoolExecutor(3) as pool:
        pieced = parts.cached_detect_span(detector, tmp_path / "c.mp4", 250.0, 3900.0, 10.0, pool=pool)
    assert pieced == whole and len(whole[0]) > 30


def test_part_check_flips_linked_chunks_of_a_shot_together(monkeypatch):
    # Chunk 0 has clear part detections ("against"), chunk 1 of the same shot has none ("none"), and chunk 2 is
    # after a cut ("none"). When chunk 0 and chunk 1 share a matching sign_pattern, flip_by_parts flips both
    # chunks of the shot together so their relative alignment is preserved, while leaving chunk 2 after the cut alone.
    kinds = {0: "against", 1: "none", 2: "none"}
    monkeypatch.setattr(parts, "detect_span", _fake_detect(kinds))
    t = np.arange(240) * 1000 / 30
    x = np.sin(2 * np.pi * 1.2 * t / 1000)
    pattern = np.zeros((10, 10, 2), dtype=np.float32)
    pattern[3:7, 3:7, 1] = -1.0
    plans = [_plan(k, t + k * 10000.0, x.copy()) for k in kinds]
    plans[1].scene = replace(plans[1].scene, continued=True)
    for p in plans:
        p.sign_pattern = pattern.copy()
    opts = PipelineOptions(part_sign=True)
    collect_parts(plans, None, opts, detector=object())
    flip_by_parts(plans, opts)
    assert [p.part_flipped for p in plans] == [True, True, False]
    assert np.allclose(plans[0].flow_position[1], -x) and np.allclose(plans[1].flow_position[1], -x)
    assert np.allclose(plans[2].flow_position[1], x)
    assert (plans[0].sign_pattern[3:7, 3:7, 1] > 0).all() and (plans[1].sign_pattern[3:7, 3:7, 1] > 0).all()
    assert "方向翻轉" in plans[0].note and "方向翻轉" in plans[1].note and "方向翻轉" not in plans[2].note
