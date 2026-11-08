"""One-click Ollama (what it starts is stopped again when the program ends): start a local Ollama (a Docker container or the installed program), pull the model, report progress.

The web UI's 設定 tab calls setup(); this module knows nothing about the settings, the caller points the AI backend at
LOCAL_URL once the generator ends without an error.
"""

from __future__ import annotations

import atexit
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator

import httpx

from funscript_gen import subproc
from funscript_gen.i18n import t

LOCAL_URL = "http://127.0.0.1:11434"
CONTAINER = "funscript-gen-ollama"
VOLUME = "funscript-gen-ollama"  # the downloaded models; survives removing the container
IMAGE = "ollama/ollama:0.40.13"  # the version docker/docker-compose.ollama.yaml and the README were tested with
MODES = ("docker", "native")
MODELS = ("qwen3-vl:8b-instruct", "qwen3-vl:4b-instruct", "qwen3-vl:2b-instruct")
DEFAULT_MODEL = MODELS[0]


# What this program started, stopped again by stop_started() when it ends; an Ollama that was running already is left alone.
_proc: subprocess.Popen | None = None
_container_started = False


def stop_started() -> None:
    """Stop the Ollama this program started (the container is stopped, not removed: the models stay in the volume)."""
    global _proc, _container_started
    proc, _proc = _proc, None
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    if _container_started:
        _container_started = False
        try:
            _docker("stop", CONTAINER, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass


atexit.register(stop_started)


class SetupError(Exception):
    """The message is already translated, ready to show."""


def native_available() -> bool:
    return shutil.which("ollama") is not None


def _docker(*args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subproc.run(["docker", *args], timeout=timeout)


DOCKER_CHECK_TTL_S = 30.0  # the web UI asks several times while it is built; `docker info` is slow when the daemon is down
_docker_checked: tuple[float, bool] | None = None


def docker_available(fresh: bool = False) -> bool:
    """The docker command exists and the daemon answers; the answer is kept for DOCKER_CHECK_TTL_S unless `fresh`."""
    global _docker_checked
    if shutil.which("docker") is None:
        return False
    now = time.monotonic()
    if not fresh and _docker_checked is not None and now - _docker_checked[0] < DOCKER_CHECK_TTL_S:
        return _docker_checked[1]
    try:
        ok = _docker("info", timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    _docker_checked = (time.monotonic(), ok)
    return ok


def available(mode: str) -> bool:
    return docker_available() if mode == "docker" else native_available()


def server_up(url: str = LOCAL_URL) -> bool:
    try:
        return httpx.get(f"{url}/api/tags", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False


def _wait_for_server(url: str, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if server_up(url):
            return
        time.sleep(0.5)
    raise SetupError(t("web.ollama.err.no_server", url=url, s=int(timeout_s)))


def _container_state() -> bool | None:
    """True = running, False = exists but stopped, None = no such container."""
    r = _docker("inspect", "-f", "{{.State.Running}}", CONTAINER)
    if r.returncode != 0:
        return None
    return r.stdout.strip() == "true"


def status(url: str = LOCAL_URL) -> list[str]:
    """What runs now, as translated lines: the server, the container with its model volume, the installed program."""
    lines = []
    if server_up(url):
        try:
            models = ", ".join(installed_models(url)) or t("web.ollama.s.no_models")
        except (httpx.HTTPError, ValueError):
            models = "?"
        lines.append(t("web.ollama.s.server_up", url=url, models=models))
    else:
        lines.append(t("web.ollama.s.server_down", url=url))
    if not docker_available(fresh=True):
        lines.append(t("web.ollama.s.no_docker"))
    else:
        state = _container_state()
        key = "none" if state is None else "running" if state else "stopped"
        lines.append(t(f"web.ollama.s.container_{key}", name=CONTAINER))
        if _docker("volume", "inspect", VOLUME).returncode == 0:
            lines.append(t("web.ollama.s.volume", name=VOLUME))
    lines.append(t("web.ollama.s.native_yes" if native_available() else "web.ollama.s.native_no"))
    if _proc is not None and _proc.poll() is None or _container_started:
        lines.append(t("web.ollama.s.ours"))
    return lines


def remove_docker() -> Iterator[str]:
    """Remove what the Docker mode created: the container, its model volume and the image (the models are lost)."""
    if not docker_available(fresh=True):
        raise SetupError(t("web.ollama.err.no_docker"))
    stop_started()
    removed = False
    for what, args in (("container", ("rm", "-f", CONTAINER)), ("volume", ("volume", "rm", VOLUME)),
                       ("image", ("rmi", IMAGE))):
        r = _docker(*args, timeout=120)
        if r.returncode == 0:
            removed = True
            yield t(f"web.ollama.p.removed_{what}")
        elif "no such" not in r.stderr.lower():  # nothing to remove is fine
            yield t("web.ollama.p.remove_failed", what=t(f"web.ollama.what_{what}"), e=r.stderr.strip()[-200:])
    if not removed:
        yield t("web.ollama.p.nothing_to_remove")


def start_docker(url: str = LOCAL_URL) -> Iterator[str]:
    global _container_started
    if not docker_available(fresh=True):
        raise SetupError(t("web.ollama.err.no_docker"))
    state = _container_state()
    if state:
        yield t("web.ollama.p.reuse_container", name=CONTAINER)
    elif server_up(url):
        raise SetupError(t("web.ollama.err.port_busy", url=url))
    elif state is False:
        yield t("web.ollama.p.start_container", name=CONTAINER)
        r = _docker("start", CONTAINER)
        if r.returncode != 0:
            raise SetupError(t("web.ollama.err.docker_failed", e=r.stderr.strip()[-300:]))
        _container_started = True
    else:
        yield t("web.ollama.p.create_container", name=CONTAINER, image=IMAGE)
        base = ["run", "-d", "--name", CONTAINER, "-p", "127.0.0.1:11434:11434",
                "-v", f"{VOLUME}:/root/.ollama", "-e", "OLLAMA_KEEP_ALIVE=30m"]
        # The image is pulled on the first run (about 2 GB), hence the long timeout.
        r = _docker(*base, "--gpus", "all", IMAGE, timeout=1800)
        if r.returncode != 0 and any(w in r.stderr.lower() for w in ("gpu", "nvidia", "cdi")):
            _docker("rm", "-f", CONTAINER)  # a container that failed to start is left behind
            yield t("web.ollama.p.no_gpu")
            r = _docker(*base, IMAGE, timeout=1800)
        if r.returncode != 0:
            raise SetupError(t("web.ollama.err.docker_failed", e=r.stderr.strip()[-300:]))
        _container_started = True
    yield t("web.ollama.p.wait_server", url=url)
    _wait_for_server(url, 60)


def start_native(url: str = LOCAL_URL) -> Iterator[str]:
    global _proc
    if not native_available():
        raise SetupError(t("web.ollama.err.no_native"))
    if server_up(url):
        yield t("web.ollama.p.reuse_server", url=url)
        return
    yield t("web.ollama.p.start_native")
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000200 | 0x08000000  # NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kwargs["start_new_session"] = True  # not stopped by Ctrl+C in the terminal; stop_started() ends it with the program
    try:
        _proc = subprocess.Popen(["ollama", "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **kwargs)
    except OSError as e:
        raise SetupError(t("web.ollama.err.start_failed", e=e)) from e
    yield t("web.ollama.p.wait_server", url=url)
    _wait_for_server(url, 60)


def installed_models(url: str = LOCAL_URL) -> list[str]:
    return [m["name"] for m in httpx.get(f"{url}/api/tags", timeout=10.0).json().get("models", [])]


def pull_model(model: str, url: str = LOCAL_URL) -> Iterator[str]:
    """Download the model (nothing happens when it is there already), yielding a progress text about twice a second."""
    if model in installed_models(url):
        yield t("web.ollama.p.model_present", model=model)
        return
    last = 0.0
    try:
        with httpx.stream("POST", f"{url}/api/pull", json={"model": model, "stream": True},
                          timeout=httpx.Timeout(30.0, read=300.0)) as resp:
            if resp.status_code != 200:
                resp.read()
                raise SetupError(t("web.ollama.err.pull_failed", model=model, e=f"{resp.status_code} {resp.text[:200]}"))
            for line in resp.iter_lines():
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("error"):
                    raise SetupError(t("web.ollama.err.pull_failed", model=model, e=msg["error"]))
                total, done = msg.get("total"), msg.get("completed")
                now = time.monotonic()
                if total and done is not None and now - last >= 0.5:
                    last = now
                    yield t("web.ollama.p.pulling", model=model, pct=format(100 * done / total, ".0f"),
                            done=format(done / 1e9, ".1f"), total=format(total / 1e9, ".1f"))
    except httpx.HTTPError as e:
        raise SetupError(t("web.ollama.err.pull_failed", model=model, e=e)) from e
    yield t("web.ollama.p.pulled", model=model)


def setup(mode: str, model: str, url: str = LOCAL_URL) -> Iterator[str]:
    """Start Ollama the chosen way and make sure the model is there; yields progress texts, raises SetupError."""
    model = (model or "").strip()
    if mode not in MODES:
        raise SetupError(t("web.ollama.err.mode", mode=mode))
    if not model:
        raise SetupError(t("web.ollama.err.no_model"))
    yield from (start_docker if mode == "docker" else start_native)(url)
    yield from pull_model(model, url)
