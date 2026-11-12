"""Disk cache for model responses, keyed by model + prompt + schema + image content."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

from funscript_gen.paths import cache_dir

CACHE_DIR = cache_dir("ai")


class ResponseCache:
    def __init__(self, directory: Path = CACHE_DIR, enabled: bool = True) -> None:
        self.directory = directory
        self.enabled = enabled

    @staticmethod
    def key(model: str, prompt: str, schema: dict, images: list[bytes]) -> str:
        h = hashlib.sha256()
        for part in (model, prompt, json.dumps(schema, sort_keys=True)):
            h.update(part.encode())
            h.update(b"\0")
        for img in images:
            h.update(hashlib.sha256(img).digest())
        return h.hexdigest()

    def get(self, key: str) -> dict | None:
        if not self.enabled:
            return None
        path = self.directory / f"{key}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):  # a half-written or damaged file counts as a miss and is asked for again
            return None

    def put(self, key: str, value: dict) -> None:
        if not self.enabled:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{key}.json"
        # Written under a name of its own and renamed, so a run that is interrupted or another process that reads at the
        # same time never sees half a file.
        tmp = path.with_name(f"{key}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
