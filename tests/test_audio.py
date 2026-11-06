import cv2
import numpy as np
from scipy.io import wavfile

import funscript_gen.signal.audio as audio_mod
from funscript_gen.signal.audio import ENV_FPS, onset_envelope, onset_phase, periodicity

PERIOD = 0.5


def _clicks(path, seconds=12.0, period=PERIOD, sr=16000):
    rng = np.random.default_rng(0)
    audio = rng.normal(0, 0.01, int(seconds * sr))
    for t in np.arange(0.25, seconds, period):  # short noise bursts = "impacts"
        i = int(t * sr)
        audio[i : i + 400] += rng.normal(0, 0.6, 400) * np.exp(-np.arange(400) / 80)
    wavfile.write(path, sr, (audio * 20000).astype(np.int16))
    return np.arange(0.25, seconds, period) * 1000


def test_click_track_period_is_found(tmp_path):
    _clicks(tmp_path / "a.wav")
    t, env = onset_envelope(tmp_path / "a.wav")
    period, strength = periodicity(env, ENV_FPS, 0.15, 1.5)
    assert abs(period - PERIOD) < 0.03 and strength > 0.5
    assert abs(t[-1] - 12000) < 100


def test_smooth_drift_is_not_a_rhythm():
    t = np.arange(0, 4000, 1000 / 30)
    assert periodicity(np.sin(2 * np.pi * t / 20000), 30.0, 0.15, 1.5)[1] == 0.0  # no peak in range


def test_video_without_audio_returns_none(tmp_path):
    path = str(tmp_path / "silent.mp4")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
    for _ in range(10):
        w.write(np.zeros((64, 64, 3), np.uint8))
    w.release()
    assert onset_envelope(path) is None


def test_envelope_is_the_same_in_blocks(tmp_path, monkeypatch):
    _clicks(tmp_path / "a.wav")
    whole = onset_envelope(tmp_path / "a.wav")
    monkeypatch.setattr(audio_mod, "BLOCK_S", 1.3)  # many blocks, not aligned with the frames
    blocks = onset_envelope(tmp_path / "a.wav")
    assert len(blocks[0]) == len(whole[0]) and np.allclose(blocks[1], whole[1])


def _onsets_at(phase_deg, seconds=12.0, f0=2.0, noise=0.0, seed=0):
    """Position cos(2 pi f0 t) (highs at t = k / f0) and an onset envelope with a click at `phase_deg` after
    each low (0 = at the low, 180 = at the high)."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, seconds * 1000, 1000 / 30)
    x = np.cos(2 * np.pi * f0 * t / 1000)
    env_t = np.arange(1, int(seconds * ENV_FPS) + 1) * 1000 / ENV_FPS
    env = rng.normal(0, noise, len(env_t)) if noise else np.zeros(len(env_t))
    for low in np.arange(0.5 / f0, seconds, 1 / f0):
        k = int(round((low + phase_deg / 360 / f0) * ENV_FPS)) - 1
        if 0 <= k < len(env):
            env[k] += 5.0
    return t, x, env_t, env


def test_onset_phase_tells_onsets_at_the_lows_from_the_highs():
    assert onset_phase(*_onsets_at(-40), -40.0) > 0.9  # impacts just before the bottom
    assert onset_phase(*_onsets_at(0), -40.0) > 0.6
    assert onset_phase(*_onsets_at(140), -40.0) < -0.9  # half a cycle away: the signal is upside down
    assert abs(onset_phase(*_onsets_at(50), -40.0)) < 0.2  # a quarter cycle off: no answer
    rng = np.random.default_rng(3)
    t, x, env_t, _ = _onsets_at(0)
    assert abs(onset_phase(t, x, env_t, rng.normal(0, 1, len(env_t)), -40.0)) < 0.2  # unrelated sound


def test_onset_phase_needs_three_seconds_and_a_tempo():
    t, x, env_t, env = _onsets_at(0, seconds=2.5)
    assert onset_phase(t, x, env_t, env, -40.0) is None
    t, x, env_t, env = _onsets_at(0)
    assert onset_phase(t, np.zeros(len(t)), env_t, env, -40.0) is None  # no motion, no tempo
