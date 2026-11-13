"""The caches under ~/.cache/funscript-gen (or FUNSCRIPT_GEN_HOME/cache): what they hold, and clearing them.

Only the caches the program can make again are cleared: the AI's answers (`ai`, one request each; asking again costs
the AI's time and the answers may differ), the part boxes (`parts`, keyed by the video's path, size and time, so moving
or editing a video leaves its entry behind), the videos' content hashes (`hashes`, kept the same way) and the
skeletons (`poses`). The downloaded models (`huggingface`) and the
window's data are listed but left alone.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from funscript_gen.paths import cache_dir

CLEARABLE = ("ai", "hashes", "parts", "poses")


@dataclass(frozen=True)
class Usage:
    name: str
    files: int
    size: int  # bytes
    clearable: bool


def root() -> Path:
    return cache_dir("")


def _files(directory: Path):
    return (f for f in directory.rglob("*") if f.is_file()) if directory.is_dir() else iter(())


def usage(base: Path | None = None) -> list[Usage]:
    """Every folder in the cache: its number of files and bytes."""
    base = base or root()
    out = []
    for d in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        sizes = []
        for f in _files(d):
            try:
                sizes.append(f.stat().st_size)
            except OSError:
                pass  # gone meanwhile
        out.append(Usage(d.name, len(sizes), sum(sizes), d.name in CLEARABLE))
    return out


def clear(names: list[str], older_than_days: float | None = None, base: Path | None = None) -> tuple[int, int]:
    """Delete the files of the caches `names` (CLEARABLE ones only; ValueError for another name), or only those not
    changed for `older_than_days` days. Returns (files, bytes) deleted. The folders stay."""
    bad = [n for n in names if n not in CLEARABLE]
    if bad:
        raise ValueError(f"cannot clear {', '.join(bad)}: only {', '.join(CLEARABLE)}")
    base = base or root()
    limit = time.time() - older_than_days * 86400 if older_than_days is not None else None
    files = size = 0
    for name in names:
        for f in list(_files(base / name)):
            try:
                st = f.stat()
                if limit is not None and st.st_mtime >= limit:
                    continue
                f.unlink()
            except OSError:
                continue
            files += 1
            size += st.st_size
    return files, size


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
