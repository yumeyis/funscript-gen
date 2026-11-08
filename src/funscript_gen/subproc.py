"""Running console programs (docker, git) from the windowed Windows app without a console window flashing up."""

from __future__ import annotations

import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run with captured text output; on Windows the child gets no console window of its own."""
    if sys.platform == "win32":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)
