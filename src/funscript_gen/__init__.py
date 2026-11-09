import os
import sys

# The pipeline runs several scenes' optical flow at once, and each scene's SVD (tracking/flow.py) would start
# OpenBLAS threads on every core: they spin-wait against the flow threads (D01 alone: 379 s CPU / 45 s wall,
# with one BLAS thread 160 s / 32 s; on the Windows test host 4 copies at once took 591 s each instead of 105 s).
# Set before numpy is imported; a value set by the user is kept.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

# glibc gives every thread its own malloc arena, and the many worker threads (optical flow pieces, the decoders,
# onnxruntime) leave them fragmented: a 15-minute video peaked at 2.2 GB, one hour at 5.1 GB, and the resident
# size kept growing with the length. Two arenas: 1.6 GB for the 15 minutes at the same speed (2:51 against 2:53).
# Linux with glibc only; a MALLOC_ARENA_MAX set by the user is kept.
if sys.platform.startswith("linux") and "MALLOC_ARENA_MAX" not in os.environ:
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").mallopt(-8, 2)  # M_ARENA_MAX
    except (OSError, AttributeError):
        pass

# FUNSCRIPT_GEN_HOME (the Windows portable build's data folder) also takes the caches the libraries keep under the
# user's home: the part detector's model (Hugging Face), uploads (Gradio) and the font cache (Matplotlib).
if os.environ.get("FUNSCRIPT_GEN_HOME", "").strip():
    from funscript_gen.paths import cache_dir, data_home

    os.environ.setdefault("HF_HOME", str(cache_dir("huggingface")))
    os.environ.setdefault("GRADIO_TEMP_DIR", str(data_home() / "tmp" / "gradio"))
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir("matplotlib")))

__version__ = "1.1.0rc3"  # the only place the version is written; release rules in DEVELOPMENT.md
