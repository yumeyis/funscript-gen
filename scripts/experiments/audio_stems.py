"""Offline: does separating the sound (Demucs) make the sound's direction cue better? The asymmetry check's sound
backing (signal/audio.py onset_phase) takes the onsets of the whole mix, where music and voices bury the impacts.
Here the onsets of each separated stem are tried on the scenes whose direction is known from the hand-made script,
in particular the scenes without part boxes, which no picture cue settles (PLAN, open issue 1).

  stems OUT_DIR [--clips A,B] [--model htdemucs]
      (GPU host; needs torch and demucs) per dev / test clip the onset envelope (signal.audio.onset_envelope) of
      each stem (drums, bass, other, vocals) and of the mix without the vocals: OUT_DIR/<clip>.npz
  eval RUN [RUN ...] [--stems DIR]
      (dev machine) per scene of the default output whose direction is known (|r| >= 0.3 with the hand-made
      script), what the onset phase of the output says (> 0: onsets at the output's lows, the output looks right
      side up) for the mix and each stem: how often and how well it agrees

RUN: `validate` runs with saved analyses of the default settings (see scripts/experiments/mask_depth.py).
"""
import argparse
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

STEMS = ["drums", "bass", "other", "vocals"]
MIN_R = 0.3
LEVELS = (0.1, 0.2, 0.3)


def load_audio(path: Path, rate: int) -> np.ndarray | None:
    """The video's sound as float32 (channels, samples) at `rate`, stereo; None without a sound track."""
    import av

    with av.open(str(path)) as container:
        if not container.streams.audio:
            return None
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=rate)
        parts = [out.to_ndarray() for frame in container.decode(audio=0) for out in resampler.resample(frame)]
        parts += [out.to_ndarray() for out in resampler.resample(None)]
    return np.concatenate(parts, axis=1).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray, rate: int) -> None:
    import wave

    pcm = (np.clip(audio.mean(axis=0), -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def stems(args) -> None:
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    from funscript_gen.signal.audio import onset_envelope
    from funscript_gen.validate import clips, load_manifest

    torch.set_num_threads(4)
    model = get_model(args.model).cuda().eval()
    rate = model.samplerate
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for clip in clips(load_manifest(), args.clips or "dev,test"):
        path = out_dir / f"{clip.name}.npz"
        if path.exists():
            continue
        t0 = time.time()
        audio = load_audio(clip.video, rate)
        if audio is None:
            print(f"{clip.name}: no sound")
            continue
        wav = torch.from_numpy(audio)
        ref = wav.mean(0)
        with torch.no_grad():
            sources = apply_model(model, ((wav - ref.mean()) / ref.std())[None], device="cuda", split=True,
                                  overlap=0.25, progress=False)[0]
        sources = (sources * ref.std() + ref.mean()).cpu().numpy()
        tracks = dict(zip(model.sources, sources))
        tracks["novocals"] = sum(v for k, v in tracks.items() if k != "vocals")
        saved = {}
        with tempfile.TemporaryDirectory(dir=out_dir) as tmp:
            for name, track in tracks.items():
                wav_path = Path(tmp) / f"{name}.wav"
                write_wav(wav_path, track, rate)
                t, env = onset_envelope(wav_path)
                saved[name] = env.astype(np.float32)
                saved["t"] = t
        np.savez_compressed(path, **saved)
        print(f"{clip.name}: {audio.shape[1] / rate:.0f} s of sound, {time.time() - t0:.0f} s", flush=True)


def curve(actions, t: np.ndarray) -> np.ndarray:
    return np.interp(t, [a.at for a in actions], [a.pos for a in actions])


def detrend(x: np.ndarray, fps: float, win_s: float = 2.0) -> np.ndarray:
    k = max(3, int(win_s * fps) | 1)
    return x - np.convolve(np.pad(x, k // 2, mode="edge"), np.ones(k) / k, mode="valid")


def evaluate(args) -> None:
    from mask_depth import find

    from funscript_gen.cli import parse_generate_args
    from funscript_gen.export.funscript import Funscript
    from funscript_gen.options import build, for_analysis
    from funscript_gen.pipeline import PipelineOptions, render
    from funscript_gen.signal.audio import onset_phase
    from funscript_gen.validate import clips, load_manifest

    phase0 = PipelineOptions().asym_audio_phase
    given, preset = parse_generate_args([])
    names = ["mix"] + (["novocals"] + STEMS if args.stems else [])
    rows = []
    for clip in clips(load_manifest(), "dev,test"):
        analysis = find([Path(r) for r in args.runs], clip.name)
        if analysis is None or analysis.envelope is None:
            continue
        envs = {"mix": analysis.envelope}
        if args.stems:
            path = Path(args.stems) / f"{clip.name}.npz"
            if not path.exists():
                continue
            z = np.load(path)
            envs.update({k: (z["t"], z[k]) for k in z.files if k != "t"})
        res = render(analysis, build(for_analysis(analysis.key, given, preset)))
        out = res.funscript.normalized().actions
        ref = Funscript.load(clip.reference).normalized().actions
        for plan in res.plans:
            if plan.skip or plan.signal is None or plan.mode != "flow":
                continue
            s, e = plan.scene.start_ms, plan.scene.end_ms
            t = np.arange(s, e, 1000 / 30)
            if len(t) < 90:
                continue
            y_out, y_ref = curve(out, t), curve(ref, t)
            a, b = detrend(y_out, 30), detrend(y_ref, 30)
            if a.std() < 1e-6 or b.std() < 1e-6:
                continue
            r = float(np.corrcoef(a, b)[0, 1])
            row = dict(clip=clip.name, group=clip.group, s=s / 1000, sec=(e - s) / 1000, r=r,
                       parts=plan.part_sign is not None)
            for n in names:
                if n in envs:
                    row[n] = onset_phase(t, y_out, *envs[n], phase0)
            rows.append(row)

    if args.stems:
        print_scores(args, names)
    known = [r for r in rows if abs(r["r"]) >= MIN_R]
    print(f"scenes of the default output with |r| >= {MIN_R} (direction known): {len(known)}; "
          f"onset phase > 0 says the output is right side up")
    for group in ("dev", "test"):
        for subset, sel in (("all", lambda r: True), ("no part sign", lambda r: not r["parts"])):
            g = [r for r in known if r["group"] == group and sel(r)]
            wrong = sum(r["r"] < 0 for r in g)
            print(f"\n== {group}, {subset}: {len(g)} scenes, {wrong} upside down")
            print(f"{'cue':10}" + "".join(f"{f'|v|>={lv}':>16}" for lv in LEVELS) + f"{'wrong found':>13}")
            for n in names:
                cells = ""
                for lv in LEVELS:
                    h = [r for r in g if r.get(n) is not None and abs(r[n]) >= lv]
                    ok = sum((r[n] > 0) == (r["r"] > 0) for r in h)
                    cells += f"{ok:>8}/{len(h):<3}{ok / len(h) if h else 0:4.0%}"
                found = sum(r.get(n) is not None and r[n] <= -0.3 for r in g if r["r"] < 0)
                false = sum(r.get(n) is not None and r[n] <= -0.3 for r in g if r["r"] > 0)
                print(f"{n:10}{cells}{found:>7} / {false} false")


def print_scores(args, names: list[str]) -> None:
    """Whole clips (mean F1 / r per group) of the default render with the analysis' sound envelope replaced by
    each stem's: the asymmetry check's sound backing is the only step that reads it."""
    import copy

    from mask_depth import find

    from funscript_gen.cli import parse_generate_args
    from funscript_gen.evaluate import compare
    from funscript_gen.export.funscript import Funscript
    from funscript_gen.options import build, for_analysis
    from funscript_gen.pipeline import render
    from funscript_gen.validate import clips, load_manifest

    given, preset = parse_generate_args([])
    scores = {}
    for clip in clips(load_manifest(), "dev,test"):
        analysis = find([Path(r) for r in args.runs], clip.name)
        path = Path(args.stems) / f"{clip.name}.npz"
        ref = Funscript.load(clip.reference)
        z = np.load(path) if path.exists() else None
        for n in names:
            a = copy.copy(analysis)
            if n != "mix" and z is not None:
                a.envelope = (z["t"], z[n])
            fs = render(a, build(for_analysis(a.key, given, preset))).funscript
            sc = compare(ref, fs)
            scores.setdefault((clip.group, n), []).append((sc.f1, sc.correlation))
    print("whole clips, mean F1 / r of the default render with each envelope")
    for (group, n), v in scores.items():
        f1, r = np.mean(v, axis=0)
        print(f"{group:5}{len(v):3}  {n:10}{f1:.3f} / {r:.3f}")
    print()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stems")
    s.add_argument("out")
    s.add_argument("--clips", default="")
    s.add_argument("--model", default="htdemucs")
    e = sub.add_parser("eval")
    e.add_argument("runs", nargs="+")
    e.add_argument("--stems", default="")
    args = p.parse_args()
    {"stems": stems, "eval": evaluate}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
