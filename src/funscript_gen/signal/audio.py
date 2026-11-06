"""The sound track: where its onsets (impacts) are, where they fall in a signal's stroke cycle (the asymmetry
check's sound backing and its hint), and how periodic a signal is (the region pick)."""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import butter, find_peaks, hilbert, sosfiltfilt, stft

from funscript_gen.signal.process import dominant_tempo

ENV_FPS = 100.0  # onset envelope rate
SAMPLE_RATE = 16000
BLOCK_S = 60.0  # audio analysed per block (seconds)


def onset_envelope(path: str | Path) -> tuple[np.ndarray, np.ndarray] | None:
    """(t_ms, z-scored positive spectral flux) at ENV_FPS, or None when the video has no audio.

    The sound is analysed in blocks of BLOCK_S seconds as it is decoded: a spectrogram of a whole hour
    would need about 1.5 GB.
    """
    hop, nperseg = int(SAMPLE_RATE / ENV_FPS), 1024
    flux: list[np.ndarray] = []
    pending: list[np.ndarray] = []
    buf = np.zeros(0, np.float32)
    prev: np.ndarray | None = None  # log magnitude of the last frame analysed so far

    def take() -> None:
        nonlocal buf, prev
        buf = np.concatenate([buf, *pending])
        pending.clear()
        if len(buf) < nperseg:
            return
        n = 1 + (len(buf) - nperseg) // hop  # whole frames in the buffer
        _, _, z = stft(buf[: (n - 1) * hop + nperseg], SAMPLE_RATE, nperseg=nperseg, noverlap=nperseg - hop,
                       boundary=None, padded=False)
        logmag = np.log1p(np.abs(z) * 100)
        if prev is not None:
            logmag = np.concatenate([prev, logmag], axis=1)
        flux.append(np.maximum(0, np.diff(logmag, axis=1)).sum(axis=0))
        prev = logmag[:, -1:]
        buf = buf[n * hop :]

    with av.open(str(path)) as container:
        if not container.streams.audio:
            return None
        resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        size = 0
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                pending.append(out.to_ndarray().reshape(-1))
                size += len(pending[-1])
            if size >= BLOCK_S * SAMPLE_RATE:
                take()
                size = 0
    take()
    env = np.concatenate(flux) if flux else np.zeros(0)
    if len(env) < 1:
        return None
    env = (env - env.mean()) / (env.std() + 1e-9)
    t = (np.arange(len(env)) + 1) * 1000.0 / ENV_FPS
    return t, env


def onset_phase(t_ms: np.ndarray, x: np.ndarray, env_t: np.ndarray, env: np.ndarray, phase0_deg: float) -> float | None:
    """Where the sound onsets fall in the stroke cycle of position `x`: the onset-weighted mean of the cycle's
    phase (0 = the lows), projected on `phase0_deg`. 1 = every onset at phase0, -1 = every onset half a cycle
    away from it, near 0 = no relation. None when the overlap is shorter than 3 s or `x` has no tempo.

    Impacts land just before the bottom of a thrust: in 13 clips the onsets came ~40 degrees before the lows of
    the hand-made script in most penetration scenes (oral ones had them near the top instead).
    """
    ok = np.isfinite(x)
    if ok.sum() < 2:
        return None
    t_ms, x = t_ms[ok], x[ok]
    m = (env_t >= t_ms[0]) & (env_t <= t_ms[-1])
    if m.sum() < 3 * ENV_FPS:
        return None
    xi = np.interp(env_t[m], t_ms, x)
    f0, _ = dominant_tempo(xi, ENV_FPS, 0.5, 6.0)
    if f0 <= 0:
        return None
    sos = butter(2, [0.6 * f0, min(1.6 * f0, 0.45 * ENV_FPS)], btype="band", fs=ENV_FPS, output="sos")
    phase = np.angle(hilbert(sosfiltfilt(sos, xi - xi.mean()))) - np.pi  # 0 at the lows
    w = np.maximum(gaussian_filter1d(env[m], 2), 0)
    if w.sum() <= 0:
        return None
    v = np.sum(w * np.exp(1j * phase)) / w.sum()
    return float(abs(v) * np.cos(np.angle(v) - np.radians(phase0_deg)))


def periodicity(x: np.ndarray, fps: float, min_period_s: float, max_period_s: float) -> tuple[float, float]:
    """(period in seconds, strength 0..1) of the highest autocorrelation *peak* in the period range.

    Only true local maxima count: the slope down from lag 0 is not a rhythm.
    """
    x = np.nan_to_num(np.asarray(x, float))
    x = x - x.mean()
    lo, hi = max(1, int(min_period_s * fps)), int(max_period_s * fps)
    if len(x) <= hi + 1 or not x.any():
        return 0.0, 0.0
    ac = np.correlate(x, x, "full")[len(x) - 1 :]
    peaks, _ = find_peaks(ac[: hi + 1])
    peaks = peaks[peaks >= lo]
    if not len(peaks):
        return 0.0, 0.0
    lag = int(peaks[np.argmax(ac[peaks])])
    return lag / fps, float(max(0.0, ac[lag] / (ac[0] + 1e-12)))
