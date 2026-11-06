"""Which code produced an output: the package version, a hash of its source files and, in a git checkout, the commit."""

from __future__ import annotations

import functools
import hashlib
import json
import subprocess
from pathlib import Path

from funscript_gen import __version__

PACKAGE_DIR = Path(__file__).resolve().parent
BUILD_INFO = "build-info.json"  # {"commit", "dirty"} written by the Windows build, which has no git


def code_hash(package_dir: Path = PACKAGE_DIR) -> str:
    """First 12 hex digits of a SHA-256 over the package's .py files (paths and contents): the same code gives the
    same hash on any machine, committed or not."""
    h = hashlib.sha256()
    for f in sorted(package_dir.rglob("*.py")):
        h.update(f.relative_to(package_dir).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()[:12]


def git_state(package_dir: Path = PACKAGE_DIR) -> dict | None:
    """{"commit": short hash, "dirty": uncommitted changes in the package} when the package is tracked in a git
    checkout; None otherwise (no git, a copy outside the repository, or a copy in an ignored folder such as out/)."""

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(package_dir), *args], capture_output=True, text=True, timeout=10)

    try:
        if git("ls-files", "--error-unmatch", "__init__.py").returncode != 0:
            return None
        head = git("rev-parse", "--short=12", "HEAD")
        status = git("status", "--porcelain", "--", ".")
    except (OSError, subprocess.SubprocessError):
        return None
    if head.returncode != 0:
        return None
    return {"commit": head.stdout.strip(), "dirty": bool(status.stdout.strip())}


def build_info(package_dir: Path = PACKAGE_DIR) -> dict:
    try:
        info = json.loads((package_dir / BUILD_INFO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: info[k] for k in ("commit", "dirty") if k in info} if isinstance(info, dict) else {}


@functools.cache
def provenance() -> dict:
    """{"version", "code"[, "commit", "dirty"]} of the running package: the commit from git, or from the build."""
    return {"version": __version__, "code": code_hash()} | (git_state() or build_info())
