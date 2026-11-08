"""A 3-second test video for smoke-test.ps1: a textured patch moving up and down (as tests/test_parallel.py's _clip).

usage: python.exe -I smoke_clip.py OUT.mp4
"""

import sys

import av
import numpy as np

FPS, SECONDS, W, H = 30, 3.0, 160, 120

rng = np.random.default_rng(0)
patch = rng.integers(0, 255, (40, 40, 3), dtype=np.uint8)
with av.open(sys.argv[1], "w") as out:
    stream = out.add_stream("libx264", rate=FPS)
    stream.width, stream.height, stream.pix_fmt = W, H, "yuv420p"
    for i in range(int(SECONDS * FPS)):
        img = np.full((H, W, 3), 60, np.uint8)
        y = int(40 + 25 * np.sin(2 * np.pi * 1.5 * i / FPS))
        img[y : y + 40, 60:100] = patch
        out.mux(stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")))
    out.mux(stream.encode())
