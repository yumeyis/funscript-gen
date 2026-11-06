import numpy as np
import pytest

from funscript_gen.export.funscript import Action, Funscript
from funscript_gen.evaluate import compare
from funscript_gen.signal.process import (
    SignalParams, analyze, bridge_gap, frequency_scale, insert_holds, limit_frequency, limit_speed, process, reference_scale, scene_scale,
)


def _sine(freq_hz: float, seconds: float = 10.0, fps: float = 30.0, amp: float = 0.5, noise: float = 0.02, seed: int = 0):
    rng = np.random.default_rng(seed)
    t = np.arange(0, seconds * 1000, 1000 / fps)
    x = 1.0 + amp * np.sin(2 * np.pi * freq_hz * t / 1000) + rng.normal(0, noise, len(t))
    return t, x


def test_fast_strokes_keep_their_turning_points():
    # 5.8 Hz: 86 ms between turning points, faster than 90 ms
    t, x = _sine(5.8, noise=0.0)
    out = process(t, x, SignalParams())
    assert len(out.actions) >= 100  # 116 turning points in 10 s
    assert len(process(t, x, SignalParams(min_interval_ms=90)).actions) < 60


def test_sine_strokes_counted():
    t, x = _sine(2.0)
    out = process(t, x, SignalParams(fps=30, freq_limit_hz=0))
    # 2 Hz for 10 s -> 20 peaks + 20 troughs (edges may lose one)
    assert 37 <= len(out.actions) <= 41
    pos = [a.pos for a in out.actions]
    assert max(pos) >= 90 and min(pos) <= 10


def test_noise_only_gives_few_actions():
    rng = np.random.default_rng(1)
    t = np.arange(0, 10_000, 1000 / 30)
    x = 1.0 + rng.normal(0, 0.005, len(t))
    assert len(process(t, x).actions) < 6


def test_gap_splits_signal():
    t, x = _sine(1.0)
    x[(t > 4000) & (t < 6000)] = np.nan
    out = process(t, x)
    assert not any(4300 < a.at < 5700 for a in out.actions)
    assert out.actions


def test_speed_limit():
    acts = limit_speed([Action(0, 0), Action(100, 100)], max_speed=400)
    assert acts[1].pos == 40


def test_frequency_scale_ramp():
    p = SignalParams(freq_limit_hz=1.5, freq_max_hz=2.0, freq_min_scale=0.5)
    assert frequency_scale(1.0, p) == 1.0
    assert frequency_scale(1.75, p) == pytest.approx(0.75)
    assert frequency_scale(3.0, p) == 0.5
    assert frequency_scale(3.0, SignalParams(freq_limit_hz=0)) == 1.0


def test_default_keeps_full_strokes_below_2_hz():
    # Hand-made scripts keep ~1.9 Hz strokes at full length; the shrinking starts at 2 Hz.
    assert frequency_scale(1.9, SignalParams()) == 1.0
    assert frequency_scale(2.5, SignalParams()) == pytest.approx(0.75)


def test_limit_frequency_shrinks_fast_strokes_around_center():
    p = SignalParams(freq_limit_hz=1.5, freq_max_hz=2.0, freq_min_scale=0.5)
    fast = [Action(i * 200, 100 if i % 2 else 0) for i in range(8)]  # 2.5 Hz
    pos = [a.pos for a in limit_frequency(fast, p)[1:-1]]
    assert set(pos) == {25, 75}
    slow = [Action(i * 500, 100 if i % 2 else 20) for i in range(8)]  # 1 Hz
    assert limit_frequency(slow, p) == slow


def test_limit_frequency_keeps_off_center_range():
    p = SignalParams(freq_limit_hz=1.5, freq_max_hz=2.0, freq_min_scale=0.5)
    fast = [Action(i * 200, 90 if i % 2 else 40) for i in range(8)]
    assert {a.pos for a in limit_frequency(fast, p)[1:-1]} == {52, 78}  # centre 65, half length 12.5


def test_limit_frequency_ignores_pauses():
    p = SignalParams(freq_limit_hz=1.5, freq_max_hz=2.0, freq_min_scale=0.5, hold_after_ms=1000)
    acts = [Action(0, 0), Action(5000, 100), Action(10000, 0)]
    assert limit_frequency(acts, p) == acts


def test_process_shrinks_fast_sine():
    t, x = _sine(3.0)
    pos = [a.pos for a in process(t, x, SignalParams(fps=30)).actions]
    assert 60 <= max(pos) <= 85 and 15 <= min(pos) <= 40


def test_compare_perfect_and_shifted():
    t, x = _sine(1.5)
    ref = Funscript(process(t, x).actions)
    s = compare(ref, ref)
    assert s.f1 == 1.0 and s.correlation > 0.99
    late = Funscript([Action(a.at + 100, a.pos) for a in ref.actions])
    s2 = compare(ref, late)
    assert abs(s2.best_lag_ms - 100) <= 20


def test_correlation_sees_an_upside_down_script():
    t = np.arange(0, 20000, 1000 / 3)  # turning points every 333 ms: 1.5 Hz strokes
    ref = Funscript([Action(int(a), 100 if k % 2 else 0) for k, a in enumerate(t)])
    inv = Funscript([Action(int(a), 0 if k % 2 else 100) for k, a in enumerate(t)])
    s = compare(ref, inv)
    assert s.correlation < -0.5 and s.correlation_wide > 0.9  # +-500 ms found it half a stroke later


def test_funscript_roundtrip(tmp_path):
    fs = Funscript([Action(200, 50), Action(100, 120), Action(100, 30)])
    p = tmp_path / "a.funscript"
    fs.save(p)
    back = Funscript.load(p)
    assert back.actions == [Action(100, 30), Action(200, 50)]


def test_long_pause_holds_position():
    acts = insert_holds([Action(0, 80), Action(4000, 0)], hold_after_ms=1000)
    assert acts == [Action(0, 80), Action(3500, 80), Action(4000, 0)]


def test_holds_are_inserted_once():
    # each scene's actions get holds, then the whole output again (pauses across scene cuts)
    acts = insert_holds([Action(0, 80), Action(4000, 0)], hold_after_ms=1000)
    assert insert_holds(acts, hold_after_ms=1000) == acts


def test_slow_strokes_are_not_held_by_default():
    # 0.25 Hz: 2 s from each turning point to the next
    t = np.arange(0, 16_000, 1000 / 30)
    x = np.sin(2 * np.pi * 0.25 * t / 1000)
    p = SignalParams(rhythm_filter=False, freq_limit_hz=0)
    plain = process(t, x, p).actions
    assert all(b.at - a.at > 1500 and a.pos != b.pos for a, b in zip(plain, plain[1:]))  # ramps, no steps
    held = process(t, x, SignalParams(rhythm_filter=False, freq_limit_hz=0, hold=True)).actions
    assert len(held) > len(plain) and any(a.pos == b.pos for a, b in zip(held, held[1:]))


def _big_then_small():
    t = np.arange(0, 16_000, 1000 / 30)
    amp = np.where(t < 8000, 0.5, 0.1)  # second half moves 5x less
    return t, 1.0 + amp * np.sin(2 * np.pi * 1.5 * t / 1000)


def _spread(actions, lo_ms, hi_ms):
    pos = [a.pos for a in actions if lo_ms < a.at < hi_ms]
    return max(pos) - min(pos)


def test_preserve_keeps_small_motion_small():
    t, x = _big_then_small()
    acts = process(t, x, SignalParams()).actions
    assert _spread(acts, 1000, 7000) >= 85
    assert 10 <= _spread(acts, 10_000, 15_000) <= 35


def test_fill_mode_stretches_small_motion():
    t, x = _big_then_small()
    acts = process(t, x, SignalParams(amplitude="fill")).actions
    assert _spread(acts, 10_000, 15_000) >= 85


def test_gain_scales_strokes():
    t, x = _big_then_small()
    acts = process(t, x, SignalParams(gain=2.0)).actions
    assert _spread(acts, 10_000, 15_000) >= 2 * 15


def test_tiny_wiggles_dropped_in_preserve_mode():
    t = np.arange(0, 10_000, 1000 / 30)
    x = 1.0 + np.where(t < 5000, 0.5, 0.01) * np.sin(2 * np.pi * 1.5 * t / 1000)
    acts = process(t, x, SignalParams(min_prominence=0.0, min_amplitude=0.0)).actions
    # ~13 wiggle extrema in the quiet half; only hold / settle points may remain
    assert len([a for a in acts if a.at > 5500]) <= 4


def test_rhythm_filter_recovers_strokes_hidden_by_drift():
    # 2 Hz strokes whose size swings 10x, riding on a slow drift
    t = np.arange(0, 10_000, 1000 / 30)
    amp = 0.05 + 0.45 * (np.sin(2 * np.pi * 0.2 * t / 1000) > 0)
    x = 0.5 * np.sin(2 * np.pi * 0.07 * t / 1000) + amp * np.sin(2 * np.pi * 2.0 * t / 1000)
    off = analyze(t, x, SignalParams(rhythm_filter=False))
    on = analyze(t, x, SignalParams())
    assert on.tempo_hz == pytest.approx(2.0, abs=0.15)
    assert len(on.strokes) >= len(off.strokes) + 3


def test_rhythm_filter_leaves_noise_alone():
    rng = np.random.default_rng(2)
    t = np.arange(0, 10_000, 1000 / 30)
    x = np.cumsum(rng.normal(0, 0.01, len(t)))
    assert analyze(t, x, SignalParams()).tempo_hz is None


def test_band_passed_signals_are_smoothed_longer():
    t, x = _sine(1.5, noise=0.1)
    assert SignalParams().rhythm_smooth_window_s > SignalParams().smooth_window_s
    short, long = (analyze(t, x, SignalParams(rhythm_smooth_window_s=w)) for w in (0.15, 0.3))
    assert short.tempo_hz and np.std(np.diff(long.smooth, 2)) < 0.9 * np.std(np.diff(short.smooth, 2))
    # without a tempo the stroke smoothing stays, fast strokes may be all there is
    off = [analyze(t, x, SignalParams(rhythm_filter=False, rhythm_smooth_window_s=w)).smooth for w in (0.15, 0.3)]
    assert np.array_equal(*off)


def test_scene_scale_blends_toward_the_scene():
    t, x = _sine(1.5, amp=0.1, noise=0.0)
    sig = analyze(t, x, SignalParams(rhythm_filter=False))
    own = reference_scale([sig], SignalParams())
    assert scene_scale(1.0, sig, SignalParams(scene_scale_blend=0.0)) == 1.0
    assert scene_scale(1.0, sig, SignalParams(scene_scale_blend=1.0)) == pytest.approx(own)
    assert scene_scale(1.0, sig, SignalParams()) == pytest.approx(own ** 0.5)


def test_huge_drift_is_not_mistaken_for_a_tempo():
    t = np.arange(0, 10_000, 1000 / 30)
    x = 3.0 * np.sin(2 * np.pi * 0.07 * t / 1000) + 0.1 * np.sin(2 * np.pi * 2.0 * t / 1000)
    assert analyze(t, x, SignalParams()).tempo_hz is None


def _flat_bottom(seconds: float = 12.0, freq_hz: float = 0.9):
    """Strokes that rest at the bottom for ~0.3 s each cycle (sine clipped from below)."""
    t = np.arange(0, seconds * 1000, 1000 / 30)
    return t, 1.0 + 0.5 * np.clip(np.sin(2 * np.pi * freq_hz * t / 1000), -0.7, 1.0)


def _plain(**kw):
    return SignalParams(freq_limit_hz=0, rhythm_filter=False, **kw)


def test_dwell_off_gives_one_point_per_extremum():
    t, x = _flat_bottom()
    acts = process(t, x, _plain()).actions
    assert all(a.pos != b.pos for a, b in zip(acts, acts[1:]))


def test_dwell_splits_resting_bottoms_only():
    t, x = _flat_bottom()
    base = process(t, x, _plain()).actions
    acts = process(t, x, _plain(dwell=True)).actions
    pairs = [(a, b) for a, b in zip(acts, acts[1:]) if a.pos == b.pos]
    bottoms = [a for a in base[1:-1] if a.pos < 50]
    assert len(pairs) >= len(bottoms) - 1 and all(a.pos < 50 for a, _ in pairs)
    for a, b in pairs:
        assert 200 <= b.at - a.at <= 450
        # The rest surrounds the original turning point.
        assert any(a.at <= c.at <= b.at for c in bottoms)


def test_dwell_ignores_short_rests():
    t, x = _flat_bottom()
    acts = process(t, x, _plain(dwell=True, dwell_min_ms=600)).actions
    assert len(acts) == len(process(t, x, _plain()).actions)


def test_curve_adds_points_only_on_long_strokes():
    t = np.arange(0, 12_000, 1000 / 30)
    # Slow strokes (2 s each way) with a shoulder halfway down.
    phase = (t % 4000) / 2000
    tri = np.where(phase < 1, phase, 2 - phase)
    x = 1.0 + 0.5 * (tri + 0.15 * np.sin(2 * np.pi * tri))
    base = process(t, x, _plain()).actions
    acts = process(t, x, _plain(curve=True, curve_tol=3)).actions
    assert len(acts) > len(base)
    gaps = np.diff([a.at for a in acts])
    assert gaps.min() >= SignalParams().min_interval_ms - 1
    # Added points lie between their neighbours' positions.
    for a, b, c in zip(acts, acts[1:], acts[2:]):
        if b not in base:
            assert min(a.pos, c.pos) <= b.pos <= max(a.pos, c.pos)
    short = process(t, x, _plain(curve=True, curve_tol=3, curve_after_ms=5000)).actions
    assert short == base


def test_drop_wiggles_keeps_the_strokes_only():
    from funscript_gen.evaluate import compare, drop_wiggles
    from funscript_gen.export.funscript import Funscript

    # strokes 0 -> 100 -> 0 -> 100 with 3-unit wiggles on the way
    pos = [0, 40, 37, 70, 67, 100, 60, 63, 30, 33, 0, 50, 47, 100]
    ref = Funscript([Action(i * 50, p) for i, p in enumerate(pos)])
    kept = drop_wiggles(ref)
    assert [a.pos for a in kept.actions] == [0, 100, 0, 100]
    assert drop_wiggles(ref, 0) is ref
    pred = Funscript([Action(0, 0), Action(250, 100), Action(500, 0), Action(650, 100)])
    assert compare(ref, pred, simplify=False).recall < 0.5 and compare(kept, pred, simplify=False).f1 == 1.0
    assert compare(ref, pred).f1 == 1.0  # the simplified measure ignores them as well


def test_held_peak_end_counts_as_a_peak():
    from funscript_gen.evaluate import _extrema, compare

    # a hold at the top (insert_holds): 100 kept until 2500, then down; its end is a peak, not a trough
    held = Funscript([Action(0, 0), Action(1000, 100), Action(2500, 100), Action(3000, 0), Action(4500, 0), Action(5000, 100)])
    _, kind = _extrema(held)
    assert list(kind) == [-1, 1, 1, -1, -1, 1]
    # a human peak at the end of the hold is matched
    ref = Funscript([Action(0, 0), Action(2450, 100), Action(4550, 0), Action(5000, 100)])
    assert compare(ref, held).recall == 1.0


def test_rhythm_filter_skips_an_unclear_tempo():
    from funscript_gen.signal.process import SignalParams, dominant_tempo, rhythm_filter

    t = np.arange(0, 20, 1 / 30)
    rng = np.random.default_rng(0)
    clear = np.sin(2 * np.pi * 1.5 * t)
    mixed = np.sin(2 * np.pi * 0.8 * t) + 0.8 * np.sin(2 * np.pi * 1.8 * t) + 0.2 * rng.normal(size=len(t))
    assert rhythm_filter(clear, SignalParams())[1] is not None
    tempo, share = dominant_tempo(mixed, 30.0, 0.5, 6.0)
    assert tempo == pytest.approx(0.8, abs=0.15) and 0.5 <= share < 0.8  # found, but not sure
    out, f0 = rhythm_filter(mixed, SignalParams())
    assert f0 is None and np.array_equal(out, mixed)  # the strokes do not follow 0.8 Hz: left as they are
    assert rhythm_filter(mixed, SignalParams(rhythm_sure_share=0.5))[1] is not None  # the old rule filtered it


def _sawtooth(seconds: float = 10.0, rise_s: float = 0.45, fall_s: float = 0.15, fps: float = 30.0, seed: int = 0):
    """Strokes that rise for rise_s and fall for fall_s, with a little noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, seconds, 1 / fps)
    phase = (t % (rise_s + fall_s))
    x = np.where(phase < rise_s, phase / rise_s, 1 - (phase - rise_s) / fall_s)
    return x + rng.normal(0, 0.02, len(t))


def test_fall_rise_asymmetry_tells_which_way_is_faster():
    from funscript_gen.signal.process import fall_rise_asymmetry

    fast_fall, n = fall_rise_asymmetry(_sawtooth(), 30.0)
    assert fast_fall < -0.5 and n >= 10
    fast_rise, _ = fall_rise_asymmetry(-_sawtooth(), 30.0)
    assert fast_rise > 0.5
    t, x = _sine(1.5)
    assert abs(fall_rise_asymmetry(x, 30.0)[0]) < 0.2
    assert fall_rise_asymmetry(_sawtooth(seconds=1.0), 30.0) == (0.0, 0)  # too short to tell


def test_fall_rise_asymmetry_works_at_a_low_analysis_frame_rate():
    from funscript_gen.signal.process import fall_rise_asymmetry

    # --fps 10: the 6 Hz low-pass is above the Nyquist frequency and must be capped, not raise
    slow = _sawtooth(seconds=20.0, rise_s=0.9, fall_s=0.3, fps=10.0)
    assert fall_rise_asymmetry(slow, 10.0)[0] < -0.3
    assert fall_rise_asymmetry(-slow, 10.0)[0] > 0.3


def _small_on_slow():
    """2 Hz strokes riding on a 0.05 Hz motion three times their size: top at 5 s, bottom at 15 s."""
    t = np.arange(0, 20_000, 1000 / 30)
    return t, np.sin(2 * np.pi * 0.05 * t / 1000) + 0.3 * np.sin(2 * np.pi * 2.0 * t / 1000)


@pytest.mark.parametrize("rhythm_filter", [False, True])
def test_scene_center_keeps_the_height_of_slow_motion(rhythm_filter):
    t, x = _small_on_slow()

    def high_minus_low(scene_center):
        p = SignalParams(rhythm_filter=rhythm_filter, freq_limit_hz=0, scene_center=scene_center)
        acts = process(t, x, p).actions
        mean = lambda lo, hi: np.mean([a.pos for a in acts if lo < a.at < hi])  # noqa: E731
        return mean(3000, 7000) - mean(13_000, 17_000)  # around the slow motion's top and bottom

    if rhythm_filter:  # band-passed around the 2 Hz tempo: the slow motion is gone either way
        assert high_minus_low(True) == high_minus_low(False)
    else:  # the 4 s window's centre follows the slow motion; the scene's does not
        assert high_minus_low(False) < 30 and high_minus_low(True) > 50


def _strokes(start: int, step: int, n: int, low: int = 10, high: int = 90) -> list[Action]:
    """n actions `step` ms apart, ending on `high`."""
    return [Action(start + k * step, high if (n - 1 - k) % 2 == 0 else low) for k in range(n)]


def test_bridge_leaves_a_join_that_keeps_the_rhythm():
    prev = _strokes(0, 300, 5)  # ends on a peak (90) at 1200 ms
    assert bridge_gap(prev, [Action(1500, 10), Action(1800, 90)], SignalParams()) == []
    assert bridge_gap(prev, [Action(1650, 10)], SignalParams()) == []  # 1.5 half-strokes: still one stroke


def test_bridge_repeats_the_last_stroke_in_a_long_gap():
    prev = _strokes(0, 300, 5, low=20, high=80)
    # 900 ms to the next trough: three half-strokes, so a trough and a peak in between, evenly spaced
    assert [(a.at, a.pos) for a in bridge_gap(prev, [Action(2100, 10)], SignalParams())] == [(1500, 20), (1800, 80)]


def test_bridge_adds_the_missing_turn_between_two_peaks():
    prev = _strokes(0, 300, 5)
    assert [(a.at, a.pos) for a in bridge_gap(prev, [Action(1800, 95)], SignalParams())] == [(1500, 10)]
    # one half-stroke apart: a turn in between would double the speed, so the join is left alone
    assert bridge_gap(prev, [Action(1500, 95)], SignalParams()) == []


def test_bridge_copies_the_stroke_only_once():
    prev = _strokes(0, 300, 5)
    out = bridge_gap(prev, [Action(4200, 10)], SignalParams())  # ten half-strokes of room
    assert [(a.at, a.pos) for a in out] == [(1500, 10), (1800, 90)]  # at the previous scene's own timing
    assert bridge_gap(prev, [Action(4200, 90)], SignalParams()) == [Action(1500, 10)]  # parity: then 90 again


def test_bridge_counts_a_rest_at_a_turn_once():
    # dwell output: the rest at the last peak is two points; the half-stroke is measured between the turns
    prev = [Action(0, 10), Action(300, 90), Action(600, 10), Action(900, 90), Action(1000, 90)]
    assert [(a.at, a.pos) for a in bridge_gap(prev, [Action(1900, 10)], SignalParams())] == [(1300, 10), (1600, 90)]
    assert bridge_gap(prev[:2], [Action(1900, 10)], SignalParams()) == []  # no rhythm to copy


def test_simplified_turning_points_ignore_dips_inside_a_stroke_and_count_holds_once():
    from funscript_gen.evaluate import compare, simple_extrema

    # a rise 0 -> 90 with 5-unit dips on the way, between two falls
    pos = [100, 0, 20, 15, 35, 30, 50, 45, 70, 65, 85, 90, 7]
    ref = Funscript([Action(i * 100, p) for i, p in enumerate(pos)])
    t0, t1, kind = simple_extrema(ref)
    assert [int(t) for t in t0] == [0, 100, 1100, 1200] and list(kind) == [1, -1, 1, -1]
    # a series of equal oscillations stays (each has a neighbour of its own size)
    osc = Funscript([Action(i * 100, p) for i, p in enumerate([100, 0, 30, 0, 30, 0, 30, 0, 100])])
    assert len(simple_extrema(osc)[0]) == 9
    # a hold is one turning point spanning its start to its end
    hold = Funscript([Action(0, 0), Action(1000, 100), Action(2500, 100), Action(3000, 0)])
    t0, t1, kind = simple_extrema(hold)
    assert list(t0) == [0, 1000, 3000] and list(t1) == [0, 2500, 3000] and list(kind) == [-1, 1, -1]
    # an output peak anywhere in the hold, or within 150 ms of it, is a hit; the older measure wants one of its ends
    pred = Funscript([Action(0, 0), Action(1800, 100), Action(3000, 0)])
    assert compare(hold, pred).f1 == 1.0 and compare(hold, pred, simplify=False).f1 < 1.0


def test_simplified_turning_points_merge_a_tremble_into_a_hold():
    from funscript_gen.evaluate import simple_extrema

    # a fall to 30, a 6 Hz tremble of 10 units (30, 40, 30, 40, 30) and a rise: the tremble is one hold at 30
    pos = [75, 30, 40, 30, 40, 30, 85]
    at = [0, 200, 283, 366, 449, 532, 900]
    fs = Funscript([Action(a, p) for a, p in zip(at, pos)])
    t0, t1, kind = simple_extrema(fs)
    assert list(t0) == [0, 200, 900] and list(t1) == [0, 532, 900] and list(kind) == [1, -1, 1]
    # the output's own tremble is not touched
    assert len(simple_extrema(fs, ratio=0.0, vibration=False)[0]) == 7
    # slower or larger swings stay
    slow = Funscript([Action(a * 3, p) for a, p in zip(at, pos)])
    assert len(simple_extrema(slow)[0]) == 7
    big = Funscript([Action(a, p) for a, p in zip(at, [75, 30, 50, 30, 50, 30, 85])])
    assert len(simple_extrema(big)[0]) == 7
    # a staircase of small steps is a stroke, not a tremble
    stairs = Funscript([Action(i * 50, p) for i, p in enumerate([0, 9, 4, 13, 8, 17, 12, 21, 16, 25, 20, 29, 24, 100])])
    assert list(simple_extrema(stairs)[0]) == [0, 650]  # one rise from the first to the last point, no hold
    assert list(simple_extrema(stairs)[2]) == [-1, 1]
