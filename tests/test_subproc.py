import subprocess
import sys

from funscript_gen import ollama_setup as osu
from funscript_gen import subproc


def test_run_hides_the_console_window_on_windows(monkeypatch):
    seen = {}

    def fake(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    subproc.run(["docker", "info"], timeout=5)
    assert seen["creationflags"] & subproc.CREATE_NO_WINDOW and seen["capture_output"] and seen["timeout"] == 5
    seen.clear()
    monkeypatch.setattr(sys, "platform", "linux")
    subproc.run(["docker", "info"])
    assert "creationflags" not in seen


def test_docker_check_is_cached_until_fresh(monkeypatch):
    calls = []
    monkeypatch.setattr(osu.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(osu, "_docker", lambda *a, timeout=60: calls.append(a) or subprocess.CompletedProcess(a, 0))
    monkeypatch.setattr(osu, "_docker_checked", None)
    assert osu.docker_available() and osu.docker_available() and osu.docker_available()
    assert len(calls) == 1
    assert osu.docker_available(fresh=True) and len(calls) == 2
