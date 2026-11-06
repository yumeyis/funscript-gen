"""Where the program keeps its own files: .env, the web UI's remembered settings, its outputs and the caches.

By default the settings files and the web UI's outputs are relative to the working directory and the caches are in
~/.cache/funscript-gen. FUNSCRIPT_GEN_HOME puts all of them in that one folder instead (the Windows portable build
points it at its data folder, so nothing is written outside it); funscript_gen/__init__.py moves the Hugging Face,
Gradio and Matplotlib caches there too.
"""

from __future__ import annotations

import os
from pathlib import Path

HOME_ENV = "FUNSCRIPT_GEN_HOME"


def data_home() -> Path | None:
    value = os.environ.get(HOME_ENV, "").strip()
    return Path(value).expanduser().resolve() if value else None


def settings_file(name: str) -> Path:
    """`name` (.env, .webui-last.json, ...) in FUNSCRIPT_GEN_HOME, else in the working directory."""
    home = data_home()
    return home / name if home else Path(name)


def cache_dir(name: str) -> Path:
    home = data_home()
    return (home / "cache" if home else Path.home() / ".cache" / "funscript-gen") / name


def webui_output_dir() -> Path:
    home = data_home()
    return (home / "out" if home else Path("out/webui")).resolve()
