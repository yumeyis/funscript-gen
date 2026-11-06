"""Web UI output folders (one ``YYYYMMDD-HHMMSS`` folder per job): usage, retention and cleanup.

Only folders named like a job are ever deleted, so pointing the output directory somewhere
shared cannot remove unrelated files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from funscript_gen.i18n import t
from funscript_gen.paths import settings_file

DEFAULT_CONFIG = settings_file(".webui-cleanup.json")
RUN_DIR = re.compile(r"\d{8}-\d{6}(-\d+)?")
CHECK_INTERVAL_S = 3600.0


@dataclass
class Usage:
    runs: int
    bytes: int


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class OutputStore:
    def __init__(self, root: str | Path, config: str | Path = DEFAULT_CONFIG) -> None:
        self.root = Path(root)
        self.config = Path(config)

    def runs(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(p for p in self.root.iterdir() if p.is_dir() and not p.is_symlink() and RUN_DIR.fullmatch(p.name))

    def files(self) -> list[Path]:
        """Every file in the job folders, newest job first."""
        return [f for run in reversed(self.runs()) for f in sorted(run.rglob("*")) if f.is_file()]

    def find(self, run: str, name: str) -> Path | None:
        """The file ``run/name`` if it is one of files(); None for anything else (e.g. ``../`` in a name)."""
        if not RUN_DIR.fullmatch(run or ""):
            return None
        path = self.root / run / (name or "")
        return path if path in self.files() else None

    def usage(self) -> Usage:
        runs = self.runs()
        return Usage(len(runs), sum(_size(p) for p in runs))

    def _settings(self) -> dict:
        try:
            data = json.loads(self.config.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _update(self, **values) -> None:
        tmp = self.config.with_name(self.config.name + ".tmp")
        tmp.write_text(json.dumps(self._settings() | values))
        os.replace(tmp, self.config)

    @property
    def retention_days(self) -> int:
        """Delete job folders older than this many days; 0 = keep forever."""
        try:
            return max(0, int(self._settings()["retention_days"]))
        except (KeyError, TypeError, ValueError):
            return 0

    def set_retention_days(self, days: int) -> None:
        if days < 0:
            raise ValueError(t("outputs.negative_days"))
        self._update(retention_days=int(days))

    @property
    def beside_video(self) -> bool:
        """Also write each script beside its video, as <video>.funscript (only for videos picked by their path)."""
        return self._settings().get("beside_video") is True

    def set_beside_video(self, on: bool) -> None:
        self._update(beside_video=bool(on))

    def purge(self, older_than_days: float | None = None, now: float | None = None) -> Usage:
        """Delete job folders last modified more than ``older_than_days`` ago (None = all). Returns what was freed."""
        now = time.time() if now is None else now
        freed = Usage(0, 0)
        for p in self.runs():
            if older_than_days is not None and now - p.stat().st_mtime <= older_than_days * 86400:
                continue
            size = _size(p)
            shutil.rmtree(p, ignore_errors=True)
            if not p.exists():
                freed.runs += 1
                freed.bytes += size
        return freed

    def purge_expired(self, now: float | None = None) -> Usage:
        days = self.retention_days
        return self.purge(days, now) if days > 0 else Usage(0, 0)

    def start_auto_cleanup(self, interval_s: float = CHECK_INTERVAL_S) -> threading.Event:
        """Run purge_expired() now and then every ``interval_s``; set the returned event to stop."""
        stop = threading.Event()

        def loop() -> None:
            while True:
                try:
                    self.purge_expired()
                except OSError:
                    pass
                if stop.wait(interval_s):
                    return

        threading.Thread(target=loop, name="output-cleanup", daemon=True).start()
        return stop


def beside_video(video: Path) -> Path:
    return Path(video).with_suffix(".funscript")


def replaceable(path: Path) -> bool:
    """Whether a script may be written to `path`: nothing is there yet, or a script funscript-gen made (its creator
    metadata), so a hand-made script of the same name is never overwritten."""
    if not path.exists():
        return True
    try:
        creator = (json.loads(path.read_text(encoding="utf-8")).get("metadata") or {}).get("creator", "")
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, AttributeError):
        return False
    return isinstance(creator, str) and creator.startswith("funscript-gen")
