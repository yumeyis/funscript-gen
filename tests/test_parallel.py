import cv2
import numpy as np

from funscript_gen.pipeline import PipelineOptions, generate
from funscript_gen.video.decoder import iter_frames


def _clip(path, fps=60, seconds=6.0, cut_every_s=1.5):
    """A textured patch moving up and down, with a hard cut (new background) every cut_every_s."""
    rng = np.random.default_rng(0)
    patch = rng.integers(0, 255, (40, 40, 3), dtype=np.uint8)
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (160, 120))
    for i in range(int(seconds * fps)):
        t = i / fps
        img = np.full((120, 160, 3), 40 + 160 * (int(t / cut_every_s) % 2), np.uint8)
        y = int(40 + 25 * np.sin(2 * np.pi * 1.5 * t))
        img[y : y + 40, 60:100] = patch
        w.write(img)
    w.release()


def test_decoding_from_the_middle_keeps_the_same_frames(tmp_path):
    _clip(tmp_path / "c.mp4")
    full = [f.t_ms for f in iter_frames(tmp_path / "c.mp4", target_fps=30)]
    for start in (1000.0, 2508.0, 3333.3):  # the 60 fps source has two frames per 30 fps slot
        part = [f.t_ms for f in iter_frames(tmp_path / "c.mp4", target_fps=30, start_ms=start)]
        assert part == [t for t in full if t >= start]


def test_decoding_from_a_key_frame_that_shares_its_slot_keeps_the_same_frames(tmp_path):
    import av

    path = tmp_path / "k.mp4"
    with av.open(str(path), "w") as out:  # 60 fps, a key frame every 3 frames: odd ones share a 30 fps slot
        stream = out.add_stream("libx264", rate=60, options={"g": "3", "keyint_min": "3", "sc_threshold": "0"})
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for i in range(60):
            frame = av.VideoFrame.from_ndarray(np.full((48, 64, 3), i * 4, np.uint8), format="rgb24")
            out.mux(stream.encode(frame))
        out.mux(stream.encode())
    full = [f.t_ms for f in iter_frames(path, target_fps=30)]
    start = 3 / 60 * 1000  # the key frame at frame 3, the second frame of its slot: dropped when decoding it all
    assert start not in full
    assert [f.t_ms for f in iter_frames(path, target_fps=30, start_ms=start)] == [t for t in full if t >= start]


def test_parallel_flow_gives_the_same_script(tmp_path):
    _clip(tmp_path / "c.mp4")
    scripts = []
    for workers in (1, 3):
        opts = PipelineOptions(use_ai=False, flow_workers=workers, asym_audio=False)
        result = generate(tmp_path / "c.mp4", opts)
        scripts.append([(a.at, a.pos) for a in result.funscript.actions])
        assert len(result.plans) >= 3  # the cuts split it, so there is something to run in parallel
    assert scripts[0] == scripts[1] and len(scripts[0]) > 5


def test_flow_in_pieces_gives_the_same_script(tmp_path, monkeypatch):
    from funscript_gen import pipeline

    _clip(tmp_path / "c.mp4", seconds=8.0, cut_every_s=4.0)
    scripts = []
    for piece_s in (100.0, 0.7):  # whole scenes; pieces that start between the 60 fps source's frames
        monkeypatch.setattr(pipeline, "FLOW_PIECE_S", piece_s)
        result = generate(tmp_path / "c.mp4", PipelineOptions(use_ai=False, flow_workers=3, asym_audio=False))
        scripts.append([(a.at, a.pos) for a in result.funscript.actions])
    assert scripts[0] == scripts[1] and len(scripts[0]) > 5


def test_scenes_are_cut_into_equal_pieces():
    from funscript_gen.pipeline import FLOW_PIECE_S, _pieces

    assert _pieces(0.0, 4000.0, 4000.0) == [(0.0, 4000.0)]
    n = 3
    pieces = _pieces(1000.0, None, 1000.0 + FLOW_PIECE_S * 1000 * (n - 0.5))  # the last scene reads to the end
    assert len(pieces) == n and pieces[0][0] == 1000.0 and pieces[-1][1] is None
    assert all(a[1] == b[0] for a, b in zip(pieces, pieces[1:]))


def test_an_ai_error_while_the_flow_runs_does_not_hang(tmp_path, monkeypatch):
    import threading
    import time

    import pytest

    from funscript_gen import pipeline

    _clip(tmp_path / "c.mp4", seconds=8.0, cut_every_s=0.5)  # 8 scenes, more than may wait for the AI
    monkeypatch.setattr(pipeline, "FLOW_WAITING", 3)
    monkeypatch.setattr(pipeline, "FLOW_PIECE_S", 0.3)  # and each in pieces

    def broken(scenes, opts, progress=None, on_seen=None):
        time.sleep(4)  # long enough for the flow of 3 scenes to be done and wait
        raise RuntimeError("AI down")

    monkeypatch.setattr(pipeline, "plan_scenes", broken)
    before = threading.active_count()
    with pytest.raises(RuntimeError, match="AI down"):
        generate(tmp_path / "c.mp4", PipelineOptions(use_ai=False, flow_workers=2, asym_audio=False))
    assert threading.active_count() <= before  # the flow workers stopped


def test_skipped_scenes_get_no_signal(tmp_path, monkeypatch):
    from funscript_gen import pipeline

    _clip(tmp_path / "c.mp4")
    real = pipeline.plan_scenes

    def skip_first(scenes, opts, progress=None, on_seen=None):
        plans = real(scenes, opts, progress, on_seen)
        plans[0].skip = True
        return plans

    monkeypatch.setattr(pipeline, "plan_scenes", skip_first)
    result = generate(tmp_path / "c.mp4", PipelineOptions(use_ai=False, flow_workers=2, asym_audio=False))
    assert result.plans[0].signal is None and all(p.signal is not None for p in result.plans[1:])


def test_raising_from_the_progress_callback_stops_the_flow(tmp_path):
    import threading
    import time

    import pytest

    _clip(tmp_path / "c.mp4", seconds=30.0, cut_every_s=1.5)  # ~20 scenes, several seconds of flow

    class Stop(Exception):
        pass

    def progress(phase, t_ms):
        if phase == "signal":
            raise Stop

    before = threading.active_count()
    t0 = time.monotonic()
    with pytest.raises(Stop):
        generate(tmp_path / "c.mp4", PipelineOptions(use_ai=False, flow_workers=2, asym_audio=False), progress)
    assert time.monotonic() - t0 < 6.0  # not waiting for the flow of every scene
    assert threading.active_count() <= before


def test_the_ai_step_reports_progress_and_can_be_stopped(monkeypatch):
    import time

    import pytest

    from funscript_gen import pipeline
    from funscript_gen.video.scenes import Scene

    calls = []

    def slow(item):
        time.sleep(0.05)
        calls.append(item)
        return item

    assert pipeline._run_all(2, slow, list(range(6))) == list(range(6))  # results in order

    class Stop(Exception):
        pass

    ticks = []

    def tick():
        ticks.append(1)
        if len(ticks) == 2:
            raise Stop

    calls.clear()
    with pytest.raises(Stop):
        pipeline._run_all(2, slow, list(range(20)), tick)
    assert len(calls) < 8  # the queued items were dropped

    # a cancel raised from the poll stops at once instead of waiting for the slow running items
    def very_slow(item):
        time.sleep(1.0)
        return item

    polls = []

    def tick2():
        pass

    def poll():
        polls.append(1)
        if len(polls) == 2:
            raise Stop

    tick2.poll = poll
    monkeypatch.setattr(pipeline, "POLL_S", 0.05)
    start = time.monotonic()
    with pytest.raises(Stop):
        pipeline._run_all(2, very_slow, list(range(4)), tick2)
    assert time.monotonic() - start < 0.8

    shares = []
    monkeypatch.setattr(pipeline, "_analyze_scenes",
                        lambda scenes, workers, focus, settings, tick=None: [tick() or (None, None) for _ in scenes])
    pipeline.plan_scenes([Scene(i, i * 1000.0, i * 1000.0 + 1000.0) for i in range(4)],
                         PipelineOptions(stroke_range=False, region_pick=False), shares.append)
    assert shares == [0.25, 0.5, 0.75, 1.0]


def _blas_env(env: dict) -> str:
    import os
    import subprocess
    import sys

    code = "import funscript_gen.cli, os, sys; assert 'numpy' in sys.modules; print(os.environ['OPENBLAS_NUM_THREADS'])"
    env = {k: v for k, v in os.environ.items() if k != "OPENBLAS_NUM_THREADS"} | env
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.strip()


def test_blas_runs_on_one_thread_unless_the_user_sets_it():
    # the flow workers run in parallel; BLAS threads on every core only spin-wait against them
    assert _blas_env({}) == "1"
    assert _blas_env({"OPENBLAS_NUM_THREADS": "4"}) == "4"


def test_a_run_without_an_ai_server_goes_on_without_it_and_says_so(tmp_path):
    from funscript_gen.config import Settings
    from funscript_gen.pipeline import render

    _clip(tmp_path / "c.mp4", seconds=3.0)
    opts = PipelineOptions(part_sign=False, ai_settings=Settings(vllm_base_url="http://127.0.0.1:1/v1"))
    result = generate(tmp_path / "c.mp4", opts)
    assert result.ai_notice and "AI" in result.ai_notice
    assert result.analysis.key["use_ai"] is False  # asking for the AI again analyses the video again
    assert render(result.analysis, opts).ai_notice == result.ai_notice
