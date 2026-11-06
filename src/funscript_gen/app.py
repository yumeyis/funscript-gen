"""The desktop app (`funscript-gen app`, FunscriptGen.exe in the Windows build): the web UI on this computer only, in a
window of its own (pywebview, on Windows the system's WebView2), or in the browser when no window can be opened.

Unlike `webui` it takes videos by their path (webui.LOCAL_FILES), with a native file dialog in the window, so they
are read where they are and the script can be written beside them. Closing the window ends the program; in the
browser it runs until its console is closed (or Ctrl+C).
"""

from __future__ import annotations

import ctypes
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

from funscript_gen.i18n import t
from funscript_gen.paths import cache_dir, data_home, settings_file

HOST = "127.0.0.1"
PREFERRED_PORT = 7860
TITLE = "funscript-gen"
START_TIMEOUT_S = 120.0  # the first start of a fresh copy imports everything from cold files


def free_port(preferred: int = PREFERRED_PORT) -> int:
    """`preferred` when nothing listens there, else any free port (a second copy of the app gets its own)."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise OSError("no free port")


def start_server(port: int):
    """The web UI's server running in a thread; returns (server, thread) once it accepts connections."""
    from funscript_gen import webui as ui

    server = ui.make_server(HOST, port)
    thread = threading.Thread(target=server.run, name="webui", daemon=True)
    thread.start()
    deadline = time.monotonic() + START_TIMEOUT_S
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError(f"the web UI did not start on port {port}")
        if time.monotonic() > deadline:
            raise TimeoutError("the web UI took too long to start")
        time.sleep(0.05)
    return server, thread


def stop_server(server, thread) -> None:
    from funscript_gen import webui as ui

    ui._cancel.set()  # a running job stops at its next progress update
    server.should_exit = True
    thread.join(timeout=10)


def file_picker(window):
    """webui.pick_files for the window: the native open-file / open-folder dialog."""
    import webview

    from funscript_gen.webui import video_file_types

    def pick(kind: str) -> list[str]:
        if kind == "folder":
            chosen = window.create_file_dialog(webview.FileDialog.FOLDER)
        else:
            chosen = window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=kind == "videos",
                                               file_types=video_file_types())
        return [str(c) for c in chosen or []]

    return pick


def open_window(url: str) -> bool:
    """Show `url` in a window until it is closed. False when pywebview is missing or cannot open one here."""
    from funscript_gen import webui as ui

    try:
        import webview
    except ImportError:
        return False
    webview.settings["ALLOW_DOWNLOADS"] = True  # the output links: saved to the user's Downloads folder
    window = webview.create_window(TITLE, url, width=1400, height=900, min_size=(800, 600))
    ui.pick_files = file_picker(window)
    try:
        # WebView2's profile goes into the data folder too, not %APPDATA%.
        webview.start(private_mode=False, storage_path=str(cache_dir("webview")))
    except Exception:  # noqa: BLE001 - no GUI toolkit (Linux without GTK/Qt), no WebView2 runtime...
        traceback.print_exc()
        return False
    finally:
        ui.pick_files = None
    return True


def ensure_console() -> None:
    """pythonw (FunscriptGen.exe) has no console: open one for the browser mode, so that closing it ends the
    program and its messages can be read."""
    if sys.platform != "win32" or ctypes.windll.kernel32.GetConsoleWindow():
        return
    ctypes.windll.kernel32.AllocConsole()
    sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115


def log_to_file() -> Path | None:
    """pythonw has no stdout/stderr (writing to them fails): send the messages to app.log in the data folder."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    path = settings_file("app.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    print(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} funscript-gen app")
    return path


def show_error(message: str) -> None:
    print(message, file=sys.stderr)
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10)  # MB_ICONERROR


def run(ui_kind: str = "window", port: int | None = None) -> None:
    """ui_kind: "window" (falls back to the browser), "browser", or "none" (only the server, e.g. for a test)."""
    from funscript_gen import i18n
    from funscript_gen import webui as ui

    i18n.init(saved=ui.saved_language())
    log = log_to_file()
    try:
        ui.LOCAL_FILES = True
        port = port or free_port()
        server, thread = start_server(port)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        show_error(t("app.start_failed", e=e) + (t("app.log_hint", log=log) if log else ""))
        raise SystemExit(1)
    url = f"http://{HOST}:{port}/"
    print(f"funscript-gen: {url}" + (f" (data: {data_home()})" if data_home() else ""), flush=True)
    try:
        if ui_kind == "window" and open_window(url):
            return
        if ui_kind != "none":
            ensure_console()
            print(t("app.in_browser", url=url), flush=True)
            webbrowser.open(url)
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_server(server, thread)
