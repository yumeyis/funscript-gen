"""Re-encode the validation clips (dev, test) into a variant set for robustness checks: a manifest, the private names
file and the hand-made scripts (symlinks) go next to the re-encoded videos in out/variants/KIND/, so
`validate NAME --manifest out/variants/KIND/validation.toml` runs them.

usage: uv run python scripts/make_variants.py KIND FFMPEG_VF [--clips dev,test]
  r24    "fps=24000/1001"            23.976 fps by dropping frames
  twos   "fps=12,fps=24000/1001"     animated on twos: 12 pictures a second, each held for two frames of 23.976 fps
  re     "null"                      the same frame rate, only re-encoded: the noise floor of any re-encode
(libx264 veryfast, crf 18, the audio copied.) Encoding next to a running validation can run out of memory: wait.
"""
import argparse
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from funscript_gen.validate import clips, load_manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind")
    ap.add_argument("vf")
    ap.add_argument("--clips", default="dev,test")
    a = ap.parse_args()
    root = Path("out/variants") / a.kind
    vdir = root / "valid"
    vdir.mkdir(parents=True, exist_ok=True)
    text = Path("validation.toml").read_text(encoding="utf-8").replace('clips_dir = "valid"', 'clips_dir = "valid"')
    (root / "validation.toml").write_text(text, encoding="utf-8")  # clips_dir is relative to the manifest
    if Path("deidentify.local.toml").exists():
        shutil.copy("deidentify.local.toml", root / "deidentify.local.toml")

    def encode(c) -> str:
        out = vdir / c.video.name
        if not out.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(c.video), "-vf", a.vf, "-c:v", "libx264",
                            "-preset", "veryfast", "-crf", "18", "-c:a", "copy", "-threads", "4", str(out)], check=True)
        ref = vdir / c.reference.name
        if not ref.exists():
            os.symlink(c.reference.resolve(), ref)
        return c.name

    with ThreadPoolExecutor(3) as ex:
        for name in ex.map(encode, clips(load_manifest(), a.clips)):
            print(name, flush=True)


if __name__ == "__main__":
    main()
