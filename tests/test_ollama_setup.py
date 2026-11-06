import json

import httpx
import pytest

from funscript_gen import ollama_setup as osu


@pytest.fixture(autouse=True)
def _no_leftovers():
    """The tests start nothing for real: forget what the fake starts recorded so atexit stops nothing."""
    yield
    osu._proc = None
    osu._container_started = False


def test_setup_rejects_bad_input():
    with pytest.raises(osu.SetupError):
        list(osu.setup("kubernetes", "m"))
    with pytest.raises(osu.SetupError):
        list(osu.setup("docker", "  "))


def test_native_reuses_a_running_server(monkeypatch):
    monkeypatch.setattr(osu, "native_available", lambda: True)
    monkeypatch.setattr(osu, "server_up", lambda url=osu.LOCAL_URL: True)
    started = []
    monkeypatch.setattr(osu.subprocess, "Popen", lambda *a, **k: started.append(a))
    assert len(list(osu.start_native())) == 1 and not started


def test_native_starts_serve_and_waits(monkeypatch):
    monkeypatch.setattr(osu, "native_available", lambda: True)
    up = iter([False, False, True])
    monkeypatch.setattr(osu, "server_up", lambda url=osu.LOCAL_URL: next(up))
    monkeypatch.setattr(osu.time, "sleep", lambda s: None)
    started = []
    monkeypatch.setattr(osu.subprocess, "Popen", lambda cmd, **k: started.append(cmd))
    list(osu.start_native())
    assert started == [["ollama", "serve"]]


def test_native_missing(monkeypatch):
    monkeypatch.setattr(osu, "native_available", lambda: False)
    with pytest.raises(osu.SetupError):
        list(osu.start_native())


class _Run:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_docker_creates_the_container_and_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(osu, "docker_available", lambda: True)
    up = iter([False, True])
    monkeypatch.setattr(osu, "server_up", lambda url=osu.LOCAL_URL: next(up))
    calls = []

    def fake(*args, timeout=60):
        calls.append(args)
        if args[0] == "inspect":
            return _Run(1)
        if args[0] == "run" and "--gpus" in args:
            return _Run(125, err="could not select device driver nvidia with capabilities: [[gpu]]")
        return _Run()

    monkeypatch.setattr(osu, "_docker", fake)
    msgs = list(osu.start_docker())
    runs = [c for c in calls if c[0] == "run"]
    assert len(runs) == 2 and "--gpus" in runs[0] and "--gpus" not in runs[1]
    assert ("rm", "-f", osu.CONTAINER) in calls and len(msgs) >= 3


def test_docker_refuses_a_foreign_server_on_the_port(monkeypatch):
    monkeypatch.setattr(osu, "docker_available", lambda: True)
    monkeypatch.setattr(osu, "server_up", lambda url=osu.LOCAL_URL: True)
    monkeypatch.setattr(osu, "_docker", lambda *a, timeout=60: _Run(1))  # no container of ours
    with pytest.raises(osu.SetupError):
        list(osu.start_docker())


def _mock_http(monkeypatch, tags, pull_lines):
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n} for n in tags]})
        return httpx.Response(200, content="\n".join(json.dumps(m) for m in pull_lines).encode())

    transport = httpx.MockTransport(handler)
    real_get, real_stream = httpx.get, httpx.stream
    monkeypatch.setattr(httpx, "get", lambda url, **k: httpx.Client(transport=transport).get(url))

    def stream(method, url, **k):
        return httpx.Client(transport=transport).stream(method, url, json=k.get("json"))

    monkeypatch.setattr(httpx, "stream", stream)
    return real_get, real_stream


def test_pull_skips_a_present_model(monkeypatch):
    _mock_http(monkeypatch, ["m:1"], [])
    assert len(list(osu.pull_model("m:1"))) == 1


def test_pull_reports_progress_and_errors(monkeypatch):
    _mock_http(monkeypatch, [], [{"status": "pulling", "total": 4_000_000_000, "completed": 1_000_000_000}])
    msgs = list(osu.pull_model("m:1"))
    assert "25%" in msgs[0] and len(msgs) == 2
    _mock_http(monkeypatch, [], [{"error": "pull model manifest: file does not exist"}])
    with pytest.raises(osu.SetupError):
        list(osu.pull_model("nope"))


def test_stop_started_stops_only_what_this_program_started(monkeypatch):
    calls = []
    monkeypatch.setattr(osu, "_docker", lambda *a, timeout=60: calls.append(a))
    monkeypatch.setattr(osu, "_container_started", False)
    osu.stop_started()
    assert calls == []  # nothing was started here

    class Proc:
        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout=None):
            calls.append("wait")

    monkeypatch.setattr(osu, "_proc", Proc())
    monkeypatch.setattr(osu, "_container_started", True)
    osu.stop_started()
    assert calls == ["terminate", "wait", ("stop", osu.CONTAINER)]
    osu.stop_started()
    assert len(calls) == 3  # a second call does nothing


def test_status_and_remove(monkeypatch):
    monkeypatch.setattr(osu, "server_up", lambda url=osu.LOCAL_URL: False)
    monkeypatch.setattr(osu, "docker_available", lambda: True)
    monkeypatch.setattr(osu, "native_available", lambda: False)
    calls = []

    def fake(*args, timeout=60):
        calls.append(args)
        if args[0] == "inspect":
            return _Run(0, out="false\n")
        if args[:2] == ("volume", "inspect"):
            return _Run(0)
        if args[0] == "rmi":
            return _Run(1, err="Error: No such image")
        return _Run()

    monkeypatch.setattr(osu, "_docker", fake)
    lines = osu.status()
    assert len(lines) == 4 and "funscript-gen-ollama" in lines[1]
    msgs = list(osu.remove_docker())
    assert ("rm", "-f", osu.CONTAINER) in calls and ("volume", "rm", osu.VOLUME) in calls and len(msgs) == 2


def test_remove_needs_docker(monkeypatch):
    monkeypatch.setattr(osu, "docker_available", lambda: False)
    with pytest.raises(osu.SetupError):
        list(osu.remove_docker())
