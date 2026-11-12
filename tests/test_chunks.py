import cv2
import numpy as np
import pytest

from funscript_gen.direction import align_chunks
from funscript_gen.pipeline import PipelineOptions, ScenePlan, _scene_signal
from funscript_gen.tracking.flow import FlowTracker
from funscript_gen.video.scenes import Scene, cut_strength, detect_scenes, frame_diffs, split_scenes


def test_chunks_of_a_long_shot_are_marked_continued(tmp_path):
    path = str(tmp_path / "clip.mp4")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
    for i in range(50):  # 3 s dark, then a hard cut to 2 s bright
        w.write(np.full((64, 64, 3), 20 if i < 30 else 230, np.uint8))
    w.release()
    scenes = detect_scenes(path, fps=10, max_chunk_s=1.0)
    cut = next(s for s in scenes if s.start_ms >= 2950)
    assert not scenes[0].continued and not cut.continued
    assert all(s.continued for s in scenes[1:] if s.start_ms < 2950)
    assert all(s.continued for s in scenes if s.start_ms > cut.start_ms)



def test_split_scenes_matches_detect_scenes_at_any_threshold(tmp_path):
    path = str(tmp_path / "clip.mp4")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
    for i in range(60):  # cuts of different strength every 1.5 s, one too soon after the previous (0.5 s)
        level = [20, 230, 120, 160, 60, 200][min(5, i // 15) if i < 45 else 4 + (i >= 50)]
        w.write(np.full((64, 64, 3), level, np.uint8))
    w.release()
    d = frame_diffs(path, fps=10)
    for threshold in (5.0, 15.0, 30.0, 60.0):
        for chunk in (1.0, 20.0):
            want = [(s.start_ms, s.end_ms, s.continued) for s in detect_scenes(path, fps=10, threshold=threshold,
                                                                                 max_chunk_s=chunk, keyframes=0)]
            got = [(s.start_ms, s.end_ms, s.continued) for s in split_scenes(d, threshold, max_chunk_s=chunk)]
            assert got == want, (threshold, chunk)
    scenes = split_scenes(d, 15.0)
    assert len(scenes) > 2 and cut_strength(d, scenes[0].start_ms) is None
    assert all(cut_strength(d, s.start_ms) > 15.0 for s in scenes[1:])


def _tracker(motion: tuple[float, float], seconds: float = 6.0) -> tuple[FlowTracker, np.ndarray]:
    """A 10x10 grid where the middle cells move along `motion` (image x, y) with a sine; returns the
    tracker and the true displacement along `motion`."""
    rng = np.random.default_rng(1)
    tracker = FlowTracker(roi=None)
    n = int(seconds * 30)
    vel = np.sin(2 * np.pi * 1.5 * np.arange(n) / 30)
    for i in range(n):
        f = rng.normal(0, 0.05, (10, 10, 2))
        f[3:7, 3:7] += 2.0 * vel[i] * np.asarray(motion)
        tracker.t_ms.append(i * 1000 / 30)
        tracker.fields.append(f.astype(np.float16))
    return tracker, np.cumsum(vel)


def test_component_margin_tells_how_clear_the_sign_was():
    up, _ = _tracker((0.0, -1.0))
    side, _ = _tracker((1.0, 0.0))
    v, pattern, margin = up.component()
    assert margin > 0.9 and side.component()[2] < 0.2
    assert np.allclose(v, up.velocity("auto")) and pattern.shape == (10, 10, 2)
    assert (pattern[3:7, 3:7, 1] < 0).all()  # same sign as the velocity: positive moves up


def _corr(sig, truth) -> float:
    x = np.interp(np.arange(len(truth)) * 1000 / 30, sig.t_ms, sig.smooth)
    return float(np.corrcoef(x[15:-15], truth[15:-15] - np.mean(truth[15:-15]))[0, 1])


def test_chunks_of_one_shot_get_the_clearest_chunks_sign():
    # The same rightward stroke: tilted clearly up in the first chunk, slightly down in the second,
    # so "up = high" alone gives them opposite signs.
    clear, truth1 = _tracker((1.0, -0.6))
    vague, truth2 = _tracker((1.0, 0.05))
    opts = PipelineOptions()
    plans = [ScenePlan(Scene(0, 0.0, 6000.0)), ScenePlan(Scene(1, 6000.0, 12000.0, continued=True))]
    for plan, flow in zip(plans, (clear, vague)):
        plan.signal = _scene_signal(plan, opts, flow, [])
    assert _corr(plans[0].signal, truth1) > 0.9 and _corr(plans[1].signal, truth2) < -0.9
    align_chunks(plans, opts)
    assert _corr(plans[0].signal, truth1) > 0.9 and _corr(plans[1].signal, truth2) > 0.9
    assert "翻轉" in plans[1].note and "翻轉" not in plans[0].note


def test_chunks_are_not_aligned_across_a_cut_or_when_off():
    for continued, on in ((False, True), (True, False)):
        clear, _ = _tracker((1.0, -0.6))
        vague, truth = _tracker((1.0, 0.05))
        opts = PipelineOptions(chunk_align=on)
        plans = [ScenePlan(Scene(0, 0.0, 6000.0)), ScenePlan(Scene(1, 6000.0, 12000.0, continued=continued))]
        for plan, flow in zip(plans, (clear, vague)):
            plan.signal = _scene_signal(plan, opts, flow, [])
        if opts.chunk_align:
            align_chunks(plans, opts)
        assert _corr(plans[1].signal, truth) < -0.9


def test_chunks_with_unrelated_motion_keep_their_own_sign():
    a, _ = _tracker((0.0, -1.0))
    b = FlowTracker(roi=None)
    b.t_ms, b.fields = a.t_ms, [np.roll(f, 5, axis=1) for f in a.fields]  # same motion, other cells
    opts = PipelineOptions()
    plans = [ScenePlan(Scene(0, 0.0, 6000.0)), ScenePlan(Scene(1, 6000.0, 12000.0, continued=True))]
    for plan, flow in zip(plans, (a, b)):
        plan.signal = _scene_signal(plan, opts, flow, [])
    before = plans[1].signal.smooth.copy()
    plans[1].sign_pattern = -plans[1].sign_pattern * 0  # no overlap at all: cosine 0
    align_chunks(plans, opts)
    assert np.array_equal(plans[1].signal.smooth, before, equal_nan=True) and "翻轉" not in plans[1].note


def test_hybrid_chunks_are_aligned_too():
    # Hybrid scenes (per-frame genital/general choice) used to skip the alignment: a vague chunk stayed inverted.
    clear, truth1 = _tracker((1.0, -0.6))
    vague, truth2 = _tracker((1.0, 0.05))
    opts = PipelineOptions(focus="hybrid")
    plans = [ScenePlan(Scene(0, 0.0, 6000.0)), ScenePlan(Scene(1, 6000.0, 12000.0, continued=True))]
    for plan, flow, use in zip(plans, (clear, vague), (False, True)):
        plan.alt_roi, plan.roi = None, (0.0, 0.0, 1.0, 1.0) if use else None
        plan.decisions = [(0.0, use), (3000.0, use)]
        plan.signal = _scene_signal(plan, opts, flow, [])
    assert _corr(plans[1].signal, truth2) < -0.9
    align_chunks(plans, opts)
    assert _corr(plans[0].signal, truth1) > 0.9 and _corr(plans[1].signal, truth2) > 0.9
    assert "翻轉" in plans[1].note


def test_hybrid_chunk_with_an_ai_direction_is_not_flipped():
    clear, _ = _tracker((1.0, -0.6))
    vague, truth = _tracker((1.0, 0.05))
    opts = PipelineOptions(focus="hybrid")
    plans = [ScenePlan(Scene(0, 0.0, 6000.0)), ScenePlan(Scene(1, 6000.0, 12000.0, continued=True))]
    for plan, flow in zip(plans, (clear, vague)):
        plan.alt_roi, plan.roi = None, (0.0, 0.0, 1.0, 1.0)
        plan.decisions = [(0.0, True), (3000.0, True)]
    plans[1].direction = (-1.0, 0.0)  # the AI says the shaft points left: moving left is positive
    for plan, flow in zip(plans, (clear, vague)):
        plan.signal = _scene_signal(plan, opts, flow, [])
    align_chunks(plans, opts)
    assert _corr(plans[1].signal, truth) < -0.9 and "翻轉" not in plans[1].note


def _asym_tracker(rise_s: float, fall_s: float, seconds: float = 8.0, fps: float = 30.0) -> tuple[FlowTracker, np.ndarray]:
    """Middle cells move up for rise_s and down for fall_s (same distance); returns the tracker and the
    true height of the motion (up = high)."""
    rng = np.random.default_rng(2)
    tracker = FlowTracker(roi=None)
    t = np.arange(int(seconds * fps)) / fps
    phase = t % (rise_s + fall_s)
    height = np.where(phase < rise_s, phase / rise_s, 1 - (phase - rise_s) / fall_s)
    up = np.diff(height, prepend=height[0]) * 20  # pixels/frame, positive = up
    for i, v in enumerate(up):
        f = rng.normal(0, 0.05, (10, 10, 2))
        f[3:7, 3:7, 1] -= v  # image y grows downward
        tracker.t_ms.append(t[i] * 1000)
        tracker.fields.append(f.astype(np.float16))
    return tracker, height


def test_asym_sign_flips_a_scene_that_rises_faster_than_it_falls():
    from funscript_gen.direction import flip_by_asymmetry

    for on in (False, True):
        opts = PipelineOptions(asym_sign=on)
        plans = [ScenePlan(Scene(0, 0.0, 8000.0)), ScenePlan(Scene(1, 8000.0, 16000.0))]
        flows = [_asym_tracker(0.15, 0.45), _asym_tracker(0.45, 0.15)]  # "up" fast, then "up" slow
        for plan, (flow, _) in zip(plans, flows):
            plan.signal = _scene_signal(plan, opts, flow, [])
        flip_by_asymmetry(plans, opts)
        assert plans[0].asym is not None and plans[1].asym < -0.5  # recorded either way
        assert (_corr(plans[0].signal, flows[0][1]) < -0.8) is on and ("方向翻轉" in plans[0].note) is on
        assert ("可能高低相反" in plans[0].note) is not on  # off: only a hint for flipping it by hand
        assert _corr(plans[1].signal, flows[1][1]) > 0.8 and "方向翻轉" not in plans[1].note
        assert "可能高低相反" not in plans[1].note
        if on:
            assert plans[0].asym < -0.5  # after the flip it falls faster


def test_a_24_fps_video_is_measured_in_its_own_frames():
    from funscript_gen.direction import flip_by_asymmetry
    from funscript_gen.signal.process import fall_rise_asymmetry
    from funscript_gen.tracking.flow import integrate

    flow, _ = _asym_tracker(0.15, 0.45, fps=24)  # fewer frames than --fps 30 asks for
    opts = PipelineOptions(asym_sign=False)
    plan = ScenePlan(Scene(0, 0.0, 8000.0))
    plan.signal = _scene_signal(plan, opts, flow, [])
    assert np.allclose(plan.flow_position[1], integrate(flow.component()[0], fps=24))  # 3 s = 72 frames, not 90
    flip_by_asymmetry([plan], opts)
    assert plan.asym == pytest.approx(fall_rise_asymmetry(plan.flow_position[1], 24)[0])


def test_asym_sign_leaves_scenes_with_an_ai_direction_alone():
    from funscript_gen.direction import flip_by_asymmetry

    flow, height = _asym_tracker(0.15, 0.45)
    opts = PipelineOptions(asym_sign=True)
    plan = ScenePlan(Scene(0, 0.0, 8000.0), direction=(0.0, -1.0))  # the AI says the shaft points up
    plan.signal = _scene_signal(plan, opts, flow, [])
    flip_by_asymmetry([plan], opts)
    assert _corr(plan.signal, height) > 0.8 and plan.asym is None and "方向翻轉" not in plan.note


def test_asym_sign_judges_linked_chunks_of_a_shot_together():
    from funscript_gen.direction import flip_by_asymmetry

    for continued in (True, False):
        opts = PipelineOptions(asym_sign=True)
        plans = [ScenePlan(Scene(0, 0.0, 8000.0)), ScenePlan(Scene(1, 8000.0, 16000.0, continued=continued))]
        flows = [_asym_tracker(0.1, 0.5), _asym_tracker(0.3, 0.3)]  # clearly "up" fast, then even
        for plan, (flow, _) in zip(plans, flows):
            plan.signal = _scene_signal(plan, opts, flow, [])
        flip_by_asymmetry(plans, opts)
        assert "方向翻轉" in plans[0].note
        # same shot, same motion pattern: the even chunk follows the clear one; after a cut it keeps its sign
        assert ("方向翻轉" in plans[1].note) is continued
        assert (_corr(plans[1].signal, flows[1][1]) < -0.8) is continued
        if continued:
            assert "2 段合計" in plans[1].note


def test_asym_sign_judges_the_output_direction_when_inverted():
    from funscript_gen.direction import flip_by_asymmetry

    # --invert mirrors the whole output, so "rises faster" must be judged after it: a scene that rises fast before
    # the invert falls fast in the output (keep it), one that falls fast before it rises fast in the output (flip it)
    for rise_s, fall_s, flips in ((0.15, 0.45, False), (0.45, 0.15, True)):
        for on in (True, False):
            opts = PipelineOptions(asym_sign=on, invert=True)
            flow, _ = _asym_tracker(rise_s, fall_s)
            plan = ScenePlan(Scene(0, 0.0, 8000.0))
            plan.signal = _scene_signal(plan, opts, flow, [])
            flip_by_asymmetry([plan], opts)
            assert plan.asym_flipped is (flips and on) and plan.asym_hint is (flips and not on)


def _clicks_at(times_ms: np.ndarray, seconds: float = 8.0) -> tuple[np.ndarray, np.ndarray]:
    """A sound onset envelope (100 Hz) with a click at each of `times_ms`."""
    env_t = np.arange(1, int(seconds * 100) + 1) * 10.0
    env = np.zeros(len(env_t))
    env[np.round(np.asarray(times_ms) / 10).astype(int) - 1] += 5.0
    return env_t, env


def test_asym_sign_needs_less_asymmetry_when_the_sound_hits_at_the_highs():
    from funscript_gen.direction import flip_by_asymmetry

    highs = np.arange(0.25, 7.9, 0.6) * 1000  # rises take 0.25 s, falls 0.35 s
    cases = (  # (clicks, asym_audio, asym_sign, flipped, hinted)
        (highs, True, True, True, False),
        (highs, True, False, False, True),  # off: only the hint, also with the sound's help
        (highs - 250, True, True, False, False),  # impacts at the lows: the sign looks right
        (highs, False, True, False, False),
        (None, True, True, False, False),  # no sound
    )
    for clicks, audio_on, on, flipped, hinted in cases:
        opts = PipelineOptions(asym_sign=on, asym_audio=audio_on)
        flow, height = _asym_tracker(0.25, 0.35)
        plan = ScenePlan(Scene(0, 0.0, 8000.0))
        plan.signal = _scene_signal(plan, opts, flow, [])
        flip_by_asymmetry([plan], opts, _clicks_at(clicks) if clicks is not None else None)
        assert 0.2 < abs(plan.asym) < 0.5  # between the two thresholds
        assert plan.asym_flipped is flipped and (_corr(plan.signal, height) < -0.8) is flipped
        assert plan.asym_hint is hinted and ("聲音起點在高點" in plan.note) is (flipped or hinted)
        if flipped:
            assert plan.audio_sign > 0.3  # after the flip the onsets are at the lows


def test_asym_sign_uses_the_lower_threshold_when_the_sound_does_not_object():
    from funscript_gen.direction import flip_by_asymmetry

    # Rises take 0.25 s, falls 0.35 s (asym between the two thresholds). Onsets every 0.37 s have no fixed place in
    # the 0.6 s strokes (music, no impacts): the sound neither backs nor vetoes, so the lower threshold applies;
    # the note does not claim onsets at the highs. Onsets at the lows still keep it, and so does no sound at all.
    spread = np.arange(0.1, 7.9, 0.37) * 1000
    highs = np.arange(0.25, 7.9, 0.6) * 1000
    for clicks, flipped in ((spread, True), (highs - 250, False), (None, False)):
        opts = PipelineOptions(asym_sign=True, asym_audio=True)
        flow, height = _asym_tracker(0.25, 0.35)
        plan = ScenePlan(Scene(0, 0.0, 8000.0))
        plan.signal = _scene_signal(plan, opts, flow, [])
        flip_by_asymmetry([plan], opts, _clicks_at(clicks) if clicks is not None else None)
        assert 0.2 < abs(plan.asym) < 0.5
        assert plan.asym_flipped is flipped and (_corr(plan.signal, height) < -0.8) is flipped
        assert "聲音起點在高點" not in plan.note
        if clicks is spread:
            assert abs(plan.audio_sign) < 0.15


def test_sound_backed_asym_sign_judges_the_output_when_inverted():
    from funscript_gen.direction import flip_by_asymmetry

    # rises take 0.35 s, falls 0.25 s: inverted, the output rises fast and the clicks at the lows are at its highs
    lows = np.arange(0.35 + 0.25, 7.9, 0.6) * 1000
    for clicks, flipped in ((lows, True), (lows - 250, False)):
        opts = PipelineOptions(asym_sign=True, invert=True)
        flow, _ = _asym_tracker(0.35, 0.25)
        plan = ScenePlan(Scene(0, 0.0, 8000.0))
        plan.signal = _scene_signal(plan, opts, flow, [])
        flip_by_asymmetry([plan], opts, _clicks_at(clicks))
        assert plan.asym_flipped is flipped


def test_align_chunks_links_sub_roi_chunk_and_anchors_on_wider_motion():
    # Chunk 0 tracks a small sub-ROI (2x2 = 4 cells) tilted slightly down (so "up = high" gives it the inverted sign,
    # even with a slightly higher per-cell sign_margin); chunk 1 tracks a 6x6 area (36 cells) tilted up with
    # a much larger total vertical displacement. Overlap-aware _cosine links them despite the 4/36 area ratio, and
    # _anchor_weight picks chunk 1 as the anchor so chunk 0 is flipped to match chunk 1.
    rng = np.random.default_rng(7)
    n = 180
    vel = np.sin(2 * np.pi * 1.5 * np.arange(n) / 30)
    truth = np.cumsum(vel)
    sub = FlowTracker(roi=(0.3, 0.3, 0.5, 0.5))
    wide = FlowTracker(roi=(0.2, 0.2, 0.8, 0.8))
    for i in range(n):
        f_sub = rng.normal(0, 0.02, (10, 10, 2))
        f_wide = rng.normal(0, 0.02, (10, 10, 2))
        f_sub[3:5, 3:5] += 1.5 * vel[i] * np.array([1.0, 0.45])     # 4 cells, slightly steeper per cell, inverted
        f_wide[2:8, 2:8] += 2.5 * vel[i] * np.array([1.0, -0.35])   # 36 cells, right sign, much more total motion
        t_ms = i * 1000 / 30
        sub.t_ms.append(t_ms)
        sub.fields.append(f_sub.astype(np.float16))
        wide.t_ms.append(t_ms)
        wide.fields.append(f_wide.astype(np.float16))
    opts = PipelineOptions()
    plans = [
        ScenePlan(Scene(0, 0.0, 6000.0)),
        ScenePlan(Scene(1, 6000.0, 12000.0, continued=True)),
    ]
    for plan, flow in zip(plans, (sub, wide)):
        plan.signal = _scene_signal(plan, opts, flow, [])
    assert plans[0].sign_margin > plans[1].sign_margin
    assert _corr(plans[0].signal, truth) < -0.9 and _corr(plans[1].signal, truth) > 0.9
    align_chunks(plans, opts)
    assert _corr(plans[0].signal, truth) > 0.9 and _corr(plans[1].signal, truth) > 0.9
    assert "翻轉" in plans[0].note and "翻轉" not in plans[1].note


def test_asym_sign_interpolates_threshold_linearly_with_negative_audio_phase():
    from funscript_gen.direction import flip_by_asymmetry

    # Rises take 0.25 s, falls 0.35 s -> asym ~ 0.34 (below 0.50 alone, above ~0.27 when audio_sign ~ -0.22).
    # Shifting clicks produces -0.30 < audio_sign < -0.15, which the old step function at -0.30 missed
    # but the linear ramp between 0 and -asym_audio_min catches.
    highs = np.arange(0.25, 7.9, 0.6) * 1000
    mixed = np.concatenate([highs[:7], highs[7:] - 250])
    opts = PipelineOptions(asym_sign=True, asym_audio=True)
    flow, height = _asym_tracker(0.25, 0.35)
    plan = ScenePlan(Scene(0, 0.0, 8000.0))
    plan.signal = _scene_signal(plan, opts, flow, [])
    flip_by_asymmetry([plan], opts, _clicks_at(mixed))
    assert 0.30 < abs(plan.asym) < 0.50
    assert 0.15 < plan.audio_sign < 0.30  # flipped from (-0.30, -0.15) to positive
    assert plan.asym_flipped and _corr(plan.signal, height) < -0.8
    assert "聲音起點在高點" in plan.note
