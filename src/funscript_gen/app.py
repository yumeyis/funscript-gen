"""The desktop app (`funscript-gen app`, FunscriptGen.exe in the Windows build): the web UI on this computer only, in a
window of its own (pywebview, on Windows the system's WebView2), or in the browser when no window can be opened.

The window opens at once with a loading page while the server starts in a thread (importing Gradio and building the
page take seconds); FunscriptGen.exe runs this module's main() directly (`python -m funscript_gen.app` does the same) so
that nothing heavy is imported before the window.

Unlike `webui` it takes files by their path (webui.LOCAL_FILES) instead of uploads: typed, dropped on the window
(drop_handler) or chosen in a native file dialog, so they are read where they are and the script can be written
beside the videos. Closing the window ends the program; in the
browser it runs until its console is closed (or Ctrl+C).
"""

from __future__ import annotations

import argparse
import ctypes
import html
import importlib.util
import json
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
# The language remembered by the web UI (webui.DEFAULT_LAST_FILE, webui.LANG_KEY), read here without importing it.
LAST_FORM_NAME = ".webui-last.json"
LANG_KEY = "lang"


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


def saved_language() -> str | None:
    """The language chosen in the web UI's settings tab (None: none), from its remembered-settings file."""
    try:
        data = json.loads(settings_file(LAST_FORM_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get(LANG_KEY) if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def start_server(port: int, native_dialogs: bool = False):
    """The web UI's server running in a thread; returns (server, thread) once it accepts connections."""
    from funscript_gen import webui as ui

    ui.LOCAL_FILES = True
    ui.NATIVE_DIALOGS = native_dialogs  # decided before the page is built: the window comes later
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


class Startup:
    """start_server in a thread of its own, so that the window can open while the web UI is imported and built."""

    def __init__(self, port: int, native_dialogs: bool = False):
        self.server = self.thread = self.error = None
        self.done = threading.Event()
        self._boot_args = (port, native_dialogs)
        threading.Thread(target=self._boot, name="boot", daemon=True).start()

    def _boot(self) -> None:
        try:
            self.server, self.thread = start_server(*self._boot_args)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.error = e
        finally:
            self.done.set()

    def wait(self):
        """(server, thread) once it listens; raises what stopped it from starting."""
        self.done.wait()
        if self.error is not None:
            raise self.error
        return self.server, self.thread

    def stop(self) -> None:
        if self.done.is_set() and self.server is not None:
            stop_server(self.server, self.thread)


def stop_server(server, thread) -> None:
    from funscript_gen import webui as ui

    ui._cancel.set()  # a running job stops at its next progress update
    server.should_exit = True
    thread.join(timeout=10)


def file_picker(window):
    """webui.pick_files for the window: the native open-file / open-folder dialog."""
    import webview

    def pick(kind: str) -> list[str]:
        from funscript_gen.webui import script_file_types, video_file_types

        if kind == "folder":
            chosen = window.create_file_dialog(webview.FileDialog.FOLDER)
        else:
            types = script_file_types() if kind in ("script", "scripts") else video_file_types()
            chosen = window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=kind in ("videos", "scripts"),
                                               file_types=types)
        return [str(c) for c in chosen or []]

    return pick


def drop_handler(window):
    """The window's `drop` event handler: the dropped files' paths (WebView2 tells pywebview where they are, the
    page cannot know) go to the page's fgDropped (webui.UI_JS), which hands them to the zone they were dropped on."""

    def on_drop(event: dict) -> None:
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
        if paths:
            window.evaluate_js(f"window.fgDropped({json.dumps(paths)})")

    return on_drop


def listen_for_drops(window) -> None:
    """Have `window` report every drop to drop_handler, again after each page load (the listener lives in the page)."""
    from webview.dom import DOMEventHandler

    handler = DOMEventHandler(drop_handler(window), prevent_default=True)

    def on_loaded() -> None:
        window.dom.document.events.drop += handler

    window.events.loaded += on_loaded


def loading_page() -> str:
    """What the window shows until the server answers."""
    return f"""<!doctype html><meta charset="utf-8"><title>{TITLE}</title>
<style>
html, body {{ height: 100%; margin: 0; color-scheme: light dark; background: Canvas; color: CanvasText; }}
body {{ display: flex; flex-direction: column; align-items: center; justify-content: center;
  font: 16px "Segoe UI", sans-serif; }}
.spin {{ width: 36px; height: 36px; margin-bottom: 18px; border: 4px solid #8884; border-top-color: #f97316;
  border-radius: 50%; animation: turn 1s linear infinite; }}
@keyframes turn {{ to {{ transform: rotate(360deg); }} }}
</style>
<div class="spin"></div><div>{html.escape(t("app.loading"))}</div>"""


def announce(url: str) -> None:
    print(f"funscript-gen: {url}" + (f" (data: {data_home()})" if data_home() else ""), flush=True)


def open_window(url: str, startup: Startup, log: Path | None = None) -> bool:
    """Show a window until it is closed: the loading page at once, `url` when the server answers. False when
    pywebview is missing or cannot open a window here (the server keeps starting)."""
    try:
        import webview
    except ImportError:
        return False
    webview.settings["ALLOW_DOWNLOADS"] = True  # the output links: saved to the user's Downloads folder
    window = webview.create_window(TITLE, html=loading_page(), width=1400, height=900, min_size=(800, 600))
    listen_for_drops(window)

    def load_when_ready() -> None:  # in a thread of its own, once the window runs
        try:
            startup.wait()
        except Exception as e:  # noqa: BLE001 - already in the log
            show_error(t("app.start_failed", e=e) + (t("app.log_hint", log=log) if log else ""))
            window.destroy()
            return
        from funscript_gen import webui as ui

        ui.pick_files = file_picker(window)
        announce(url)
        window.load_url(url)

    try:
        # WebView2's profile goes into the data folder too, not %APPDATA%.
        webview.start(load_when_ready, private_mode=False, storage_path=str(cache_dir("webview")))
    except Exception:  # noqa: BLE001 - no GUI toolkit (Linux without GTK/Qt), no WebView2 runtime...
        traceback.print_exc()
        return False
    finally:
        ui = sys.modules.get("funscript_gen.webui")
        if ui is not None:
            ui.pick_files = None
    return True


def ensure_console() -> None:
    """The windowed FunscriptGen.exe has no console: open one for the browser mode, so that closing it ends the
    program and its messages can be read."""
    if sys.platform != "win32" or ctypes.windll.kernel32.GetConsoleWindow():
        return
    ctypes.windll.kernel32.AllocConsole()
    sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115


_log: Path | None = None


def log_to_file() -> Path | None:
    """A windowed program has no stdout/stderr (writing to them fails): send the messages to app.log in the data folder.
    Returns that file (again on a second call), None when there is a console."""
    global _log
    if _log is not None:
        return _log
    if sys.stdout is not None and sys.stderr is not None:
        return None
    path = settings_file("app.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    print(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} funscript-gen app")
    _log = path
    return path


def show_error(message: str) -> None:
    print(message, file=sys.stderr)
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10)  # MB_ICONERROR


def run(ui_kind: str = "window", port: int | None = None) -> None:
    """ui_kind: "window" (falls back to the browser), "browser", or "none" (only the server, e.g. for a test)."""
    from funscript_gen import i18n

    i18n.init(saved=saved_language())
    log = log_to_file()
    try:
        port = port or free_port()
    except OSError as e:
        show_error(t("app.start_failed", e=e) + (t("app.log_hint", log=log) if log else ""))
        raise SystemExit(1)
    url = f"http://{HOST}:{port}/"
    startup = Startup(port, native_dialogs=ui_kind == "window" and importlib.util.find_spec("webview") is not None)
    try:
        if ui_kind == "window" and open_window(url, startup, log):
            if startup.error is not None:
                raise SystemExit(1)  # the window already showed why
            return
        try:
            _, thread = startup.wait()
        except Exception as e:  # noqa: BLE001
            show_error(t("app.start_failed", e=e) + (t("app.log_hint", log=log) if log else ""))
            raise SystemExit(1)
        announce(url)
        if ui_kind != "none":
            ensure_console()
            print(t("app.in_browser", url=url), flush=True)
            webbrowser.open(url)
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        startup.stop()


def main(argv: list[str] | None = None) -> None:
    """`python -m funscript_gen.app`: what FunscriptGen.exe runs (the same as `funscript-gen app`)."""
    from funscript_gen import i18n

    log_to_file()  # windowed: an error in the arguments has nowhere else to go
    parser = argparse.ArgumentParser(prog="FunscriptGen", description="The funscript-gen desktop app.")
    parser.add_argument("--ui", choices=("window", "browser", "none"), default="window",
                        help="window: its own window (falls back to the browser) | browser | none (only the server)")
    parser.add_argument("--port", type=int, help="Default: 7860, or any free port when it is taken")
    parser.add_argument("--lang", help="Language of the messages and the web UI (a pack in lang/, e.g. en or zh-TW)")
    args = parser.parse_args(argv)
    i18n.set_preferred(args.lang)
    run(args.ui, args.port)


if __name__ == "__main__":
    main()
