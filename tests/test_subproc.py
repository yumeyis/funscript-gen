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


def test_docker_mode_is_listed_without_starting_docker(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("docker must not be started")

    monkeypatch.setattr(osu, "_docker", boom)
    monkeypatch.setattr(osu.shutil, "which", lambda name: "/usr/bin/docker")
    assert osu.available("docker")
    monkeypatch.setattr(osu.shutil, "which", lambda name: None)
    assert not osu.available("docker")
