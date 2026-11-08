import os

# The pipeline runs several scenes' optical flow at once, and each scene's SVD (tracking/flow.py) would start
# OpenBLAS threads on every core: they spin-wait against the flow threads (D01 alone: 379 s CPU / 45 s wall,
# with one BLAS thread 160 s / 32 s; on the Windows test host 4 copies at once took 591 s each instead of 105 s).
# Set before numpy is imported; a value set by the user is kept.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

# FUNSCRIPT_GEN_HOME (the Windows portable build's data folder) also takes the caches the libraries keep under the
# user's home: the part detector's model (Hugging Face), uploads (Gradio) and the font cache (Matplotlib).
if os.environ.get("FUNSCRIPT_GEN_HOME", "").strip():
    from funscript_gen.paths import cache_dir, data_home

    os.environ.setdefault("HF_HOME", str(cache_dir("huggingface")))
    os.environ.setdefault("GRADIO_TEMP_DIR", str(data_home() / "tmp" / "gradio"))
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir("matplotlib")))

__version__ = "1.1.0rc1"  # the only place the version is written; release rules in DEVELOPMENT.md
