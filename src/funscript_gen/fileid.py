"""Identify a video by its content: the SHA-256 of the whole file, so a moved or renamed copy is the same video and
another file under the same name is not.

Hashing reads the whole file (about 1.3 s for 600 MB from a warm disk cache), so each hash is kept in the `hashes`
cache under the file's resolved path, size and modification time and only made again when one of those changes.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

from funscript_gen.paths import cache_dir

CACHE_DIR = cache_dir("hashes")
CHUNK = 1 << 20


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(CHUNK):
            h.update(block)
    return h.hexdigest()


def file_hash(path: str | Path, directory: Path | None = None) -> str:
    """The SHA-256 (hex) of the file's content. OSError when it cannot be read."""
    path = Path(path).resolve()
    st = path.stat()
    directory = directory or CACHE_DIR
    key = hashlib.sha256(f"{path}\0{st.st_size}\0{st.st_mtime_ns}".encode()).hexdigest()
    entry = directory / f"{key}.txt"
    try:
        value = entry.read_text(encoding="ascii").strip()
        if len(value) == 64:
            return value
    except (OSError, ValueError):
        pass  # not there yet, or a damaged entry: hash again
    value = _digest(path)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # under a name of its own and renamed, so a reader never sees half an entry (as ai.cache)
        tmp = entry.with_name(f"{key}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(value, encoding="ascii")
        os.replace(tmp, entry)
    except OSError:
        pass  # a read-only cache only costs the hashing next time
    return value
