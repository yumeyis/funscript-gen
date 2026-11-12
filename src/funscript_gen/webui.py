"""Gradio web UI: upload a video, tune settings, download the funscript."""

from __future__ import annotations

import html
import inspect
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import quote

import gradio as gr

from funscript_gen.batch import VIDEO_SUFFIXES
from funscript_gen.devices import DeviceError
from funscript_gen.devices import check as check_devices
from funscript_gen.export.funscript import Funscript
from funscript_gen import i18n, multiaxis, ollama_setup
from funscript_gen.i18n import L, Late, column_headers, t
from funscript_gen.outputs import DEFAULT_CONFIG as DEFAULT_CLEANUP_FILE
from funscript_gen.outputs import OutputStore, beside_video, human_size, replaceable
from funscript_gen.paths import settings_file, webui_output_dir
from funscript_gen.options import (
    BY_NAME, GROUPS, PRESETS, UI_OPTIONS, OptionError, analysis_key, group_title, preset_label, resolve,
)
from funscript_gen.options import build as build_options
from funscript_gen.pipeline import (
    PipelineOptions, PipelineResult, carry_flips, flipped_scenes, generate, refinalize, render, toggle_flip,
)
from funscript_gen.preview import AXIS_STRIP_PX, axes_viewer_html, iframe, player_html, scene_regions, viewer_height
from funscript_gen.report import FLIP_COLUMN
from funscript_gen.video.decoder import probe
from funscript_gen.video.scenes import FrameDiffs, cut_strength, frame_diffs, split_scenes

OUTPUT_DIR = webui_output_dir()
SHUTDOWN_TIMEOUT_S = 2  # Ctrl+C: how long a request still running may hold up the exit


def bbox_choices() -> list[tuple[str, str]]:
    return [(t("web.bbox.auto"), ""), (t("web.bbox.rel1000"), "rel1000"), (t("web.bbox.abs"), "abs")]


def backend_choices() -> list[tuple[str, str]]:
    return [(t("web.backend.openai"), "openai"), ("Ollama", "ollama")]



# Components whose text comes from the language pack, with the attributes that do (each a Late, looked up again when
# the language changes): ui() builds and records them, translations() is the update that makes them follow the
# language. build() starts the list over.
_translated: list[tuple[object, dict[str, Late]]] = []


def ui(cls, *args, **kwargs):
    """cls(*args, **kwargs), the Late values among the keyword arguments resolved now and again by translations()."""
    late = {k: v for k, v in kwargs.items() if isinstance(v, Late)}
    component = cls(*args, **{**kwargs, **{k: v() for k, v in late.items()}})
    if late:
        _translated.append((component, late))
    return component


def translations() -> list:
    """gr.update per recorded component (same order as in `translated_components`), in the chosen language."""
    return [gr.update(**{k: v() for k, v in late.items()}) for _, late in _translated]


def translated_components() -> list:
    return [c for c, _ in _translated]


# Characters that are invalid in file names on Windows or Unix, plus control characters.
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def output_stem(stem: str) -> str:
    """Keep the video's name (spaces included) so players pair the script with the video."""
    return _UNSAFE_FILENAME.sub("_", stem)[:150].strip(" .") or "video"


# AI backend settings shared by every job; loaded from .env and changed in the 設定 tab.
_settings = None


def current_settings():
    global _settings
    if _settings is None:
        from funscript_gen.config import Settings

        _settings = Settings()
    return _settings


def _settings_from_form(base_url: str, api_key: str, model: str, bbox_format: str, concurrency=None, backend=None,
                        num_ctx=None):
    """Form values -> Settings. An empty key field keeps the saved key (it is never sent to the browser)."""
    cur = current_settings()
    base_url = (base_url or "").strip()
    if not base_url.startswith(("http://", "https://")):
        raise gr.Error(t("web.err.url_scheme"))
    return cur.model_copy(update={
        "vllm_base_url": base_url,
        "vllm_api_key": api_key.strip() if api_key and api_key.strip() else cur.vllm_api_key,
        "vllm_model": (model or "").strip() or cur.vllm_model,
        "vllm_bbox_format": bbox_format or "",
        "vllm_concurrency": int(concurrency) if concurrency else cur.vllm_concurrency,
        "vllm_backend": backend or cur.vllm_backend,
        "vllm_num_ctx": int(num_ctx) if num_ctx else cur.vllm_num_ctx,
    })


def _ai_status(s) -> str:
    key = t("web.key_set") if s.vllm_api_key else t("web.key_unset")
    backend = t("web.ollama_prefix") if s.vllm_backend == "ollama" else ""
    return t("web.ai_status", backend=backend, url=s.vllm_base_url, model=s.vllm_model, key=key)


def fetch_models(base_url, api_key, model, bbox_format, concurrency=None, backend=None, num_ctx=None):
    from funscript_gen.config import list_models

    s = _settings_from_form(base_url, api_key, model, bbox_format, concurrency, backend, num_ctx)
    try:
        models = list_models(s)
    except Exception as e:  # noqa: BLE001 - shown to the user verbatim
        raise gr.Error(t("web.err.models_failed", e=e))
    value = s.vllm_model if s.vllm_model in models else (models[0] if models else s.vllm_model)
    return gr.update(choices=models, value=value), t("web.models_fetched", n=len(models))


DEFAULT_URLS = {"openai": "http://127.0.0.1:8000/v1", "ollama": "http://127.0.0.1:11434"}


def _url_placeholder(backend: str) -> str:
    return DEFAULT_URLS[backend].replace("127.0.0.1", t("web.host"))


def backend_changed(backend: str, base_url: str):
    """Swap an untouched default URL for the new backend's default; the context length and the one-click Ollama
    section only apply to Ollama."""
    url = DEFAULT_URLS[backend] if (base_url or "").strip() in ("", *DEFAULT_URLS.values()) else base_url
    placeholder = _url_placeholder(backend)
    show = gr.update(visible=backend == "ollama")
    return gr.update(value=url, placeholder=placeholder), show, show


def ollama_mode_choices() -> list[tuple[str, str]]:
    osu = ollama_setup

    return [(t(f"web.ollama.mode_{m}") + ("" if osu.available(m) else t("web.ollama.not_found")), m)
            for m in osu.MODES]


def ollama_status() -> str:
    try:
        return "\n".join(f"- {line}" for line in ollama_setup.status())
    except Exception as e:  # noqa: BLE001 - shown to the user verbatim
        return f"❌ {e}"


def ask_ollama_clear(show: bool):
    return gr.update(visible=show)


def clear_ollama():
    """Remove the Docker container, volume and image that the one-click run created."""
    lines = []
    try:
        lines += ollama_setup.remove_docker()
    except ollama_setup.SetupError as e:
        lines.append(f"❌ {e}")
    return "\n".join(f"- {line}" for line in lines), gr.update(visible=False)


def run_ollama(mode, model, concurrency=None):
    """One-click Ollama: start it, pull the model, then point the AI settings at it and save them (a generator)."""
    global _settings
    from funscript_gen.config import save_env

    osu = ollama_setup

    keep = gr.update()
    try:
        for text in osu.setup(mode, model):
            yield text, keep, keep, keep, keep, keep
    except osu.SetupError as e:
        yield f"❌ {e}", keep, keep, keep, keep, keep
        return
    cur = current_settings()
    s = cur.model_copy(update={
        "vllm_backend": "ollama", "vllm_base_url": osu.LOCAL_URL, "vllm_model": model.strip(),
        "vllm_concurrency": int(concurrency) if concurrency else cur.vllm_concurrency,
    })
    save_env(s)
    _settings = s
    yield (t("web.ollama.done", url=s.vllm_base_url, model=s.vllm_model),
           gr.update(value=s.vllm_base_url), gr.update(choices=[s.vllm_model], value=s.vllm_model),
           _ai_status(s), gr.update(value="ollama"), gr.update(visible=True))


def save_settings(base_url, api_key, model, bbox_format, concurrency=None, backend=None, num_ctx=None):
    global _settings
    from funscript_gen.config import save_env

    s = _settings_from_form(base_url, api_key, model, bbox_format, concurrency, backend, num_ctx)
    save_env(s)
    _settings = s
    return t("web.saved_env", time=time.strftime('%H:%M:%S')), _ai_status(s), gr.update(value="")


LANG_KEY = "lang"  # the language chosen in the settings tab, remembered in the same file as the form


def saved_language() -> str | None:
    value = load_last_form().get(LANG_KEY)
    return value if isinstance(value, str) else None


def language_update():
    """The language list (packs are read again, so a file added to lang/ shows up), the chosen one and its help."""
    return gr.update(choices=i18n.choices(), value=i18n.current(), info=t("web.set.lang_info"))


def pick_language(code: str):
    """The language list changed: use that language, remember it, and update every text."""
    i18n.set_language(code)
    remember_settings_tab({LANG_KEY: i18n.current()})
    return apply_language()


def apply_language():
    """Updates for `language_outputs()`: the recorded components, the language list, and the texts that are made when
    a result or a status is shown."""
    status = output_status()
    return [*translations(), language_update(), _ai_status(current_settings()), status, status, output_list_html()]


# Generated scripts: kept in OUTPUT_DIR/<time>/, deleted by age (設定 tab) or by hand.
_cleanup_file: Path = DEFAULT_CLEANUP_FILE


def output_store() -> OutputStore:
    return OutputStore(OUTPUT_DIR, _cleanup_file)  # OUTPUT_DIR may be changed by the CLI after import


def output_status() -> str:
    store = output_store()
    u = store.usage()
    days = store.retention_days
    rule = t("web.out.auto_delete", days=days) if days else t("web.out.no_auto_delete")
    return t("web.out.status", folder=OUTPUT_DIR, runs=u.runs, size=human_size(u.bytes), rule=rule)


def output_rows() -> list[tuple[str, str, Path]]:
    """(job folder, file name, path) for every output file, newest job first."""
    store = output_store()
    rows = []
    for f in store.files():
        run, *name = f.relative_to(store.root).parts
        rows.append((run, "/".join(name), f))
    return rows


def download_url(path: Path) -> str:
    # Gradio's own file route: it only serves files under allowed_paths (OUTPUT_DIR).
    return "gradio_api/file=" + quote(str(path.resolve()))


def output_list_html() -> str:
    rows = output_rows()
    if not rows:
        return t("web.out.empty")
    body = []
    for run, name, path in rows:
        st = path.stat()
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))
        link = (f'<a href="{html.escape(download_url(path))}" download="{html.escape(path.name)}">'
                f"{html.escape(name)}</a>")
        body.append(f"<tr><td>{link}</td><td>{html.escape(run)}</td><td>{human_size(st.st_size)}</td>"
                    f"<td>{when}</td></tr>")
    head = "".join(f"<th>{html.escape(t(k))}</th>" for k in
                   ("web.out.col_file", "web.out.col_folder", "web.out.col_size", "web.out.col_modified"))
    return f'<table style="width:100%"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def refresh_outputs():
    status = output_status()
    return status, status, output_list_html()


def save_retention(days):
    try:
        output_store().set_retention_days(int(days or 0))
    except ValueError as e:
        raise gr.Error(str(e))
    freed = output_store().purge_expired()
    note = t("web.out.expired_note", runs=freed.runs, size=human_size(freed.bytes)) if freed.runs else ""
    return (t("web.saved", time=time.strftime('%H:%M:%S'), note=note), *refresh_outputs())


def _deleted(freed) -> str:
    return t("web.out.deleted", runs=freed.runs, size=human_size(freed.bytes), time=time.strftime('%H:%M:%S'))


def delete_expired(days):
    days = int(days or 0)
    if days <= 0:
        raise gr.Error(t("web.err.days_positive"))
    return (_deleted(output_store().purge(days)), *refresh_outputs())


def clear_outputs():
    return (_deleted(output_store().purge(None)), *refresh_outputs(), gr.update(visible=False))


def ask_clear(show: bool):
    return gr.update(visible=show)


# Files by their path on this computer (the desktop app, `funscript-gen app`): the 產生, 批次 and 預覽 tabs take a
# path (typed, dropped on the box, or chosen in the native dialog) instead of an upload, so a file is read where it
# is and the script can also be written beside the video. Off for `webui`, which may serve other machines.
LOCAL_FILES = False
# Whether the app opens a window with a native file dialog (known before the page is built; the window comes later).
NATIVE_DIALOGS = False
# The app's native file dialog: pick_files(kind) with kind "video", "videos", "script", "scripts" or "folder" returns
# the paths.
pick_files = None
def video_file_types() -> tuple[str, str]:
    return (t("web.file_types.video", types=";".join(f"*{s}" for s in sorted(VIDEO_SUFFIXES))),
            t("web.file_types.all"))


def script_file_types() -> tuple[str, str]:
    return (t("web.file_types.script", types=";".join(f"*{s}" for s in sorted(SCRIPT_SUFFIXES))),
            t("web.file_types.all"))


def clean_path(text: str | Path | None) -> str:
    """A path as typed or pasted: no spaces around it and no quotes (Explorer's "copy as path" adds them)."""
    return str(text or "").strip().strip('"').strip()


def local_video(path: str | Path | None) -> Path | None:
    """A local path box that names a video: the file, None when the box is empty."""
    if not clean_path(path):
        return None
    if not LOCAL_FILES:
        raise gr.Error(t("web.err.no_local_paths"))
    video = Path(clean_path(path)).expanduser()
    if not video.is_file():
        raise gr.Error(t("web.err.video_not_found", video=video))
    return video


def local_script(path: str | Path | None) -> Path | None:
    """A local path box that names a funscript: the file, None when the box is empty."""
    if not clean_path(path):
        return None
    if not LOCAL_FILES:
        raise gr.Error(t("web.err.no_local_paths"))
    script = Path(clean_path(path)).expanduser()
    if not script.is_file():
        raise gr.Error(t("web.err.script_not_found", script=script))
    return script


def local_videos(text: str | None) -> list[Path]:
    """The 批次 tab's local path box: one video or folder per line, folders expanded to the videos in them."""
    from funscript_gen.batch import find_videos

    lines = [line.strip().strip('"') for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return []
    if not LOCAL_FILES:
        raise gr.Error(t("web.err.no_local_paths"))
    missing = [line for line in lines if not Path(line).expanduser().exists()]
    if missing:
        raise gr.Error(t("web.err.not_found", names=t("sep.list").join(missing)))
    return find_videos(Path(line).expanduser() for line in lines)


# The boxes of local paths, by the zone that drops and 選擇… buttons name them (the order of box_updates).
BOXES = ("gen-video", "gen-ref", "batch", "pv-video", "pv-script", "pv-ref", "pv-axes", "tool-in", "tool-out")
SCRIPT_SUFFIXES = {".funscript", ".json"}


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_SUFFIXES


def is_script(path: Path) -> bool:
    return path.suffix.lower() in SCRIPT_SUFFIXES


def sibling(path: Path, kind: str) -> Path | None:
    """The file named like `path` (same name, other suffix) in its folder: its script (kind "script", .funscript
    before .json) or its video (kind "video"). An exact-case name is preferred, Windows names are not case-sensitive."""
    try:
        files = [f for f in path.parent.iterdir() if f.is_file()]
    except OSError:
        return None
    ok = is_script if kind == "script" else is_video
    same = [f for f in files if ok(f) and f.stem.casefold() == path.stem.casefold()]
    return min(same, key=lambda f: (f.stem != path.stem, f.suffix.lower() != ".funscript", f.name.lower()),
               default=None)


def pick_scripts(scripts: list[Path], video: Path | None = None, auto: bool = False) -> tuple[Path | None, list[Path], int]:
    """(the main script, its axis files, how many files `auto` brought in) among scripts given together: the main
    script is the one named like the video, else the first without an axis in its name; the axis files are the ones
    of its name (the files beside them too with `auto`, see multiaxis.expand). A single axis file is a script as it is."""
    full = multiaxis.expand(scripts) if auto else list(scripts)
    def axis_of(f: Path) -> str | None:
        return multiaxis.split_name(f)[1]

    mains = [f for f in full if axis_of(f) is None]
    axes = [f for f in full if axis_of(f) is not None]
    main = next((f for f in mains if video and f.stem == video.stem), mains[0] if mains else None)
    if main is None:
        return (axes[0], [], 0) if axes else (None, [], 0)
    if len(mains) > 1:  # several scripts: the axes of the one chosen
        axes = [f for f in axes if multiaxis.split_name(f)[0].casefold() == main.stem.casefold()]
    axes.sort(key=lambda f: multiaxis.AXIS_IDS.index(axis_of(f)))  # in the order of the axes, whatever came first
    return main, axes, len(full) - len(scripts)


def dropped(zone: str, paths, batch_text: str = "", auto: bool = False) -> tuple[dict[str, str], str, bool]:
    """What files given for `zone` (dropped on it, or chosen by its 選擇… button or typed in its box) change:
    ({box: its new text}, a note, whether anything was taken). The 預覽 tab takes a video and a script from any of its
    boxes (so a pair dropped together goes to both); with `auto` the one that is missing is the file of the same name
    beside the other. The 批次 box gets the videos and folders added to its lines (`batch_text`)."""
    files = [Path(clean_path(p)).expanduser() for p in paths if clean_path(p)]
    missing = [f for f in files if not f.exists()]
    files = [f for f in files if f.exists()]
    if missing:
        return {}, t("web.err.not_found", names=t("sep.list").join(str(f) for f in missing)), False
    videos, scripts = [f for f in files if is_video(f)], [f for f in files if is_script(f)]
    if zone == "batch":
        take = [f for f in files if f.is_dir() or is_video(f)]
        lines = [line for line in batch_text.splitlines() if line.strip()]
        lines += [str(f) for f in take if str(f) not in lines]
        return ({"batch": "\n".join(lines)}, "", True) if take else ({}, t("web.drop.not_videos"), False)
    if zone == "tool-in":  # the files of the 工具 tab replace what was there; with `auto` the rest of each script comes too
        take = [f for f in files if f.is_file() and is_script(f)]
        if not take:
            return {}, t("web.drop.not_script"), False
        take = multiaxis.expand(take) if auto else take
        return {"tool-in": "\n".join(str(f) for f in take)}, "", True
    if zone == "tool-out":
        folders = [f for f in files if f.is_dir()]
        return ({"tool-out": str(folders[0])}, "", True) if folders else ({}, t("web.drop.not_folder"), False)
    if zone == "pv-axes":
        return ({"pv-axes": "\n".join(str(f) for f in scripts)}, "", True) if scripts else ({}, t("web.drop.not_script"), False)
    if zone == "gen-video":
        return ({"gen-video": str(videos[0])}, "", True) if videos else ({}, t("web.drop.not_video"), False)
    if zone in ("gen-ref", "pv-ref"):
        return ({zone: str(scripts[0])}, "", True) if scripts else ({}, t("web.drop.not_script"), False)
    # 預覽: pv-video / pv-script
    if not videos and not scripts:
        return {}, t("web.drop.not_video_or_script"), False
    video = videos[0] if videos else None
    script, axes, _ = pick_scripts(scripts, video)
    note = ""
    if video and script:
        note = t("web.pv.picked_both", video=video.name, script=script.name)
    elif len(videos) > 1:
        note = t("web.pv.picked_one", video=video.name)
    elif script and not video:
        note = t("web.pv.picked_script", script=script.name)
    if auto and video and not script:
        script = sibling(video, "script")
        note = (t("web.pv.auto_script", script=script.name) if script
                else t("web.pv.auto_no_script", video=video.name))
    elif auto and script and not video:
        video = sibling(script, "video")
        note = (t("web.pv.auto_video", video=video.name) if video
                else t("web.pv.auto_no_video", script=script.name))
    if auto and script:  # the axis files beside the script (also those of a script that came in as the video's)
        script, axes, brought = pick_scripts([script, *axes], video, True)
        if brought:
            note += t("sep.note") + t("web.pv.auto_axes", n=brought)
    out = {}
    if video:
        out["pv-video"] = str(video)
    if script:
        out["pv-script"] = str(script)
        out["pv-axes"] = "\n".join(str(f) for f in axes)  # the axes of the script before do not belong to this one
    return out, note, True


def box_updates(changes: dict[str, str], note: str = "", ok: bool = True) -> list:
    """The outputs of the handlers below: one update per box in BOXES, then the 預覽 tab's message. A note when
    nothing was taken is shown as a warning."""
    if note and not ok:
        gr.Warning(note)
        note = ""
    return [*(gr.update(value=changes[k]) if k in changes else gr.update() for k in BOXES),
            gr.update(value=note) if note else gr.update()]


def choose(zone: str, kind: str, batch_text: str = "", auto: bool = False):
    """A 選擇… button: the native dialog (kind "video", "videos", "script", "scripts" or "folder"), then as if dropped."""
    if pick_files is None:
        raise gr.Error(t("web.err.no_dialog"))
    chosen = pick_files(kind)
    return box_updates(*dropped(zone, chosen, batch_text, auto)) if chosen else box_updates({})


def drop_arrived(payload: str | None, batch_text: str = "", auto: bool = False, tool_auto: bool = False):
    """Files dropped on the window: the page's script (UI_JS) puts {"zone", "paths", "n"} in the hidden box."""
    try:
        data = json.loads(payload or "")
        zone, paths = data["zone"], data["paths"]
    except (ValueError, KeyError, TypeError):
        return box_updates({})
    if zone not in BOXES:
        return box_updates({})
    return box_updates(*dropped(zone, paths, batch_text, tool_auto if zone.startswith("tool-") else auto))


def typed(zone: str, text: str, batch_text: str = "", auto: bool = False):
    """Enter in a path box: the same as a drop of that path (so 預覽 can bring in the file of the same name)."""
    if not clean_path(text):
        return box_updates({})
    return box_updates(*dropped(zone, [text], batch_text, auto))


def beside_copy(video: Path, lines: list[str]) -> Path | None:
    """Where a local video's script is also written when the 設定 tab asks for it (None: not asked, or the name is
    taken by a script funscript-gen did not make; `lines` then gets a note)."""
    if not output_store().beside_video:
        return None
    target = beside_video(video)
    if not replaceable(target):
        lines.append(t("web.beside_exists", name=target.name))
        return None
    lines.append(t("web.beside_copy", target=target))
    return target


def save_beside(on: bool) -> str:
    output_store().set_beside_video(on)
    return (t("web.beside_on", time=time.strftime('%H:%M:%S')) if on
            else t("web.beside_off", time=time.strftime('%H:%M:%S')))


def open_output_dir() -> str:
    import subprocess
    import sys

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(OUTPUT_DIR)  # noqa: S606 - the app's own folder
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(OUTPUT_DIR)])
    return t("web.out.opened", folder=OUTPUT_DIR)


def toggle_reference(enabled: bool):
    return gr.update(visible=enabled), gr.update(visible=enabled)


# Last-used 產生 settings: saved on every 產生 click, restored when the page opens. Shared by every
# browser (it is a server-side file), like the AI settings; uploaded files are never remembered.
DEFAULT_LAST_FILE = settings_file(".webui-last.json")
_last_file: Path = DEFAULT_LAST_FILE


def load_last_form() -> dict:
    try:
        data = json.loads(_last_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def remember_settings_tab(values: dict) -> None:
    """A change of the 設定 tab's options (SETTINGS_TAB_GROUPS): remembered at once, without the 產生 form's
    unsaved values."""
    save_last_form(load_last_form() | values)


def save_last_form(values: dict) -> None:
    tmp = _last_file.with_name(_last_file.name + ".tmp")
    tmp.write_text(json.dumps(values, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _last_file)


def valid_form_value(component, value) -> bool:
    """A saved value that still fits the component (choices or slider range may change between versions)."""
    if isinstance(component, gr.Checkbox):
        return isinstance(value, bool)
    if isinstance(component, (gr.Radio, gr.Dropdown)):
        return value in [c[1] if isinstance(c, tuple) else c for c in component.choices]
    if isinstance(component, gr.Slider):
        return isinstance(value, (int, float)) and not isinstance(value, bool) \
            and component.minimum <= value <= component.maximum
    if isinstance(component, gr.Textbox):
        return isinstance(value, str)
    return False


def restore_form(form: dict, saved: dict) -> list:
    """gr.update per component: the saved value when it is still valid, otherwise leave it as is."""
    return [gr.update(value=saved[k]) if k in saved and valid_form_value(c, saved[k]) else gr.update()
            for k, c in form.items()]

# Files the preview player may stream, by unguessable token. Served by our own /media route
# (with HTTP Range support so the video can seek) instead of hand-building Gradio file URLs.
MEDIA: dict[str, Path] = {}


def register_media(path: str | Path) -> str:
    path = Path(path).resolve()
    for token, known in MEDIA.items():
        if known == path:
            return f"/media/{token}"
    token = secrets.token_urlsafe(24)
    MEDIA[token] = path
    return f"/media/{token}"


def preview(video: Path, script: Funscript, reference: Funscript | None = None, scene_list=None,
            start_ms: float = 0.0, play: bool = False, checks: list[int] | None = None,
            regions: dict[int, dict] | None = None, axes: dict[str, Funscript] | None = None,
            unsure: list[int] | None = None) -> str:
    try:
        fps = probe(video).fps
    except Exception:  # noqa: BLE001 - only used for frame stepping
        fps = 30.0
    return iframe(player_html(register_media(video), script, reference, fps=fps, scene_list=scene_list,
                              start_ms=start_ms, play=play, checks=checks, unsure=unsure, regions=regions, axes=axes),
                  height=880 + AXIS_STRIP_PX * len(axes or {}))


# The 反轉 / 儲存編輯 buttons under the players read where the video is, and the actions edited in the player
# (getEdits: [[at, pos], ...], null when unchanged), from the player's iframe (srcdoc: same origin).
# The first argument is the job state, which the server takes from the session whatever is returned for it.
_PLAYER_TIME_JS = """(job, t, play, edits) => {{
  const f = document.querySelector('#{id} iframe');
  const w = f && f.contentWindow;
  const v = w && w.document.getElementById('video');
  const e = w && w.getEdits ? w.getEdits() : null;
  return [job, v ? v.currentTime * 1000 : -1, v ? !v.paused : false, e ? JSON.stringify(e) : ""];
}}"""


def parse_edits(payload: str | None) -> list | None:
    """The actions edited in a player (JSON [[at ms, pos], ...]), sorted, positions within 0..100, one per time;
    None when nothing was edited."""
    from funscript_gen.export.funscript import Action

    if not payload:
        return None
    try:
        pairs = json.loads(payload)
        acts = {int(round(float(at))): int(round(min(100.0, max(0.0, float(pos))))) for at, pos in pairs if float(at) >= 0}
    except (ValueError, TypeError) as e:
        raise gr.Error(t("web.err.edits_unreadable", e=e))
    return [Action(at, pos) for at, pos in sorted(acts.items())]


def hand_edited(script: Funscript, actions: list) -> Funscript:
    """`script` with its actions replaced by hand, marked in its metadata (the CLI cannot reproduce it)."""
    meta = dict(script.metadata)
    meta["funscript_gen"] = {**meta.get("funscript_gen", {}), "hand_edited": True}
    return Funscript(actions, script.inverted, script.range, meta).normalized()


def scene_at(starts: list[float], t_ms: float) -> int | None:
    """Position in `starts` (sorted scene start times) of the scene playing at t_ms."""
    if t_ms is None or t_ms < 0 or not starts:
        return None
    k = sum(1 for s in starts if s <= t_ms) - 1
    return max(k, 0)


@dataclass
class PreviewJob:
    """預覽 tab: the loaded script and its scenes, so the scene under the cursor can be flipped."""
    video: Path
    script: Funscript
    reference: Funscript | None
    starts: list[float]  # scene start times (ms), numbered like the 產生 tab's scenes
    ends: list[float]
    lo: int  # positions are mirrored within the script's own range, fixed at load so flips undo exactly
    hi: int
    name: str
    flipped: set[int] = field(default_factory=set)
    out_path: Path | None = None
    diffs: FrameDiffs | None = None  # kept to split the scenes again at another threshold without decoding
    threshold: float = 30.0
    continued: list[bool] = field(default_factory=list)  # per scene: a chunk of a long shot, not a cut
    axes: dict[str, Funscript] = field(default_factory=dict)  # the other axes of a multi-axis script, shown only

    def scene_list(self) -> list[tuple[float, int, bool]]:
        return [(s, k, k in self.flipped) for k, s in enumerate(self.starts)]

    def split(self, threshold: float) -> None:
        """Split the scenes at `threshold`. Flips stay in the script, but the scene numbers change, so they are no
        longer marked."""
        scenes = split_scenes(self.diffs, threshold)
        self.threshold = threshold
        self.starts, self.ends = [sc.start_ms for sc in scenes], [sc.end_ms for sc in scenes]
        self.continued = [sc.continued for sc in scenes]
        self.flipped = set()


# Column ids (English, stable); the headers shown are web.pcol.* in the language pack, see preview_headers().
PREVIEW_COLUMNS = ["#", "start (s)", "end (s)", "length (s)", "cut strength", "actions", FLIP_COLUMN, "note"]


def preview_headers() -> list[str]:
    return column_headers(PREVIEW_COLUMNS, "web.pcol")


def preview_rows(job: PreviewJob) -> list[list]:
    """The 預覽 tab's scene table: one row per scene, with how clear its cut is to help set the threshold."""
    rows = []
    for k, (t0, t1) in enumerate(zip(job.starts, job.ends)):
        n = sum(1 for a in job.script.actions if t0 <= a.at < t1)
        strength = cut_strength(job.diffs, t0) if job.diffs is not None else None
        if k == 0:
            note = ""
        elif k < len(job.continued) and job.continued[k]:
            note = t("web.pv.note_chunk")
        elif strength is not None and strength < job.threshold * 1.25:
            note = t("web.pv.note_cut")
        else:
            note = ""
        flip = "-" if not n else (t("report.flipped") if k in job.flipped else "⇅")
        rows.append([k, round(t0 / 1000, 2), round(t1 / 1000, 2), round((t1 - t0) / 1000, 2),
                     "-" if strength is None else round(strength, 1), n, flip, note])
    return rows


def preview_summary(job: PreviewJob) -> str:
    """How many scenes were found at the current threshold, and how many there would be a step either way."""
    cuts = sum(1 for c in job.continued[1:] if not c)
    lines = [t("web.pv.summary", threshold=format(job.threshold, "g"), scenes=len(job.starts), cuts=cuts,
               continued=len(job.starts) - 1 - cuts)]
    if job.diffs is not None:
        lo, hi = max(5.0, round(job.threshold * 0.8)), round(job.threshold * 1.25)
        lines.append(t("web.pv.summary_steps", lo=format(lo, "g"), n_lo=len(split_scenes(job.diffs, lo)),
                       hi=format(hi, "g"), n_hi=len(split_scenes(job.diffs, hi))))
    if job.axes:
        lines.append(t("web.pv.axes_loaded", n=len(job.axes), axes=t("sep.list").join(job.axes)))
    return "".join(lines)


def preview_table(job: PreviewJob):
    return gr.update(value=preview_rows(job), headers=preview_headers())


def mirror_span(script: Funscript, t0: float, t1: float, lo: int, hi: int) -> Funscript:
    """The script with the positions of actions in t0 <= at < t1 mirrored within lo..hi."""
    from funscript_gen.export.funscript import Action

    acts = [Action(a.at, lo + hi - a.pos) if t0 <= a.at < t1 else a for a in script.actions]
    return Funscript(acts, script.inverted, script.range, dict(script.metadata)).normalized()


def _paths(value) -> list[Path]:
    """A gr.File value as a list: one path, several (file_count="multiple") or none."""
    if not value:
        return []
    return [Path(value)] if isinstance(value, (str, Path)) else [Path(v) for v in value]


def pair_files(files: list[Path]) -> tuple[Path | None, list[Path]]:
    """The video and the scripts among files picked together: the main script first (the one named like the video is
    preferred), then its axis files."""
    videos = [p for p in files if not is_script(p)]
    video = videos[0] if videos else None
    main, axes, _ = pick_scripts([p for p in files if is_script(p)], video)
    return video, [main, *axes] if main else []


def preview_video_uploaded(picked):
    """預覽 tab: the video box takes several files, so a video and its script (and the axis files of a multi-axis
    script) picked together (the browser does not say which folder a file came from) go to their own boxes. A video
    alone stays as it is."""
    files = _paths(picked)
    if len(files) <= 1 and not any(is_script(p) for p in files):
        return gr.update(), gr.update(), gr.update()
    video, scripts = pair_files(files)
    if video and scripts:
        msg = t("web.pv.picked_both", video=video.name, script=scripts[0].name)
    elif scripts:
        msg = t("web.pv.picked_script", script=scripts[0].name)
    else:
        msg = t("web.pv.picked_one", video=video.name)
    if len(scripts) > 1:
        msg += t("sep.note") + t("web.pv.picked_axes", n=len(scripts) - 1)
    return (gr.update(value=[str(video)] if video else None),
            gr.update(value=[str(f) for f in scripts]) if scripts else gr.update(), msg)


_pv_cancel = threading.Event()  # set by the 取消載入 button; the loading preview stops at its next frame


def preview_cancel() -> str:
    _pv_cancel.set()
    return t("web.pv.cancel_requested", time=time.strftime('%H:%M:%S'))


def local_scripts(text: str | None) -> list[Path]:
    """The 預覽 tab's box of axis files: one funscript per line."""
    lines = [clean_path(line) for line in (text or "").splitlines() if clean_path(line)]
    if lines and not LOCAL_FILES:
        raise gr.Error(t("web.err.no_local_paths"))
    out = []
    for line in lines:
        script = Path(line).expanduser()
        if not script.is_file():
            raise gr.Error(t("web.err.script_not_found", script=script))
        out.append(script)
    return out


def main_and_axes(files: list[Path]) -> tuple[Path, list[Path]]:
    """The scripts of the 預覽 tab: the main script (a file whose name names no axis; a single file is the main one
    whatever its name) and the axis files."""
    mains = [f for f in files if multiaxis.split_name(f)[1] is None]
    if mains:
        return mains[0], [f for f in files if f not in mains]
    if len(files) == 1:
        return files[0], []
    raise gr.Error(t("web.err.need_main_script"))


def preview_files(video_path, script_file, reference_file, use_reference=False, scene_threshold=30.0,
                  axes_files=None, progress=gr.Progress(), split_scenes_on=True):
    if LOCAL_FILES:  # the boxes hold paths
        video_path, script_file = local_video(video_path), local_script(script_file)
        reference_file = local_script(reference_file) if use_reference else None
        axes_files = local_scripts(axes_files)
    video_path = next(iter(_paths(video_path)), None)  # the video box takes several files
    if not video_path:
        raise gr.Error(t("web.err.need_video"))
    scripts = [*_paths(script_file), *_paths(axes_files)]  # the script box takes the axis files of a script too
    if not scripts:
        raise gr.Error(t("web.err.need_script"))
    script_file, axis_files = main_and_axes(scripts)
    try:
        script = Funscript.load(script_file)
        axes = multiaxis.load_separate(script_file, axis_files).funscripts()[1]
        reference = Funscript.load(reference_file) if use_reference and reference_file else None
    except Exception as e:  # noqa: BLE001
        raise gr.Error(t("web.err.script_unreadable", e=e))
    video = Path(video_path)
    _pv_cancel.clear()
    diffs = None
    try:
        duration = max(probe(video).duration_ms, 1.0)
        if split_scenes_on:
            shown = [-1]

            def on_frame(ms: float) -> None:
                if _pv_cancel.is_set():
                    raise Cancelled
                pct = int(min(1.0, ms / duration) * 100)
                if pct != shown[0]:  # one update per percent: the bar and the number then move together
                    shown[0] = pct
                    progress(pct / 100, desc=t("web.progress.detect_scenes"))

            diffs = frame_diffs(video, on_frame=on_frame)
    except Cancelled:
        return (gr.update(), None, gr.update(), t("web.pv.cancelled"), gr.update())
    except Exception as e:  # noqa: BLE001
        raise gr.Error(t("web.err.video_unreadable", e=e))
    pos = [a.pos for a in script.actions] or [0, 100]
    job = PreviewJob(video, script, reference, [], [], min(pos), max(pos), output_stem(Path(script_file).stem),
                     diffs=diffs, axes=axes)
    if diffs is not None:
        job.split(float(scene_threshold))
    else:  # no scene detection: the whole video is one scene
        job.starts, job.ends, job.continued = [0.0], [duration], [False]
    return (preview(video, script, reference, job.scene_list(), axes=axes), job, gr.update(value=None), preview_summary(job),
            preview_table(job))


def preview_files_whole(video_path, script_file, reference_file, use_reference=False, scene_threshold=30.0,
                        axes_files=None):
    return preview_files(video_path, script_file, reference_file, use_reference, scene_threshold, axes_files,
                         split_scenes_on=False)


def preview_rescene(job: PreviewJob | None, threshold: float, t_ms: float, play: bool, edits: str = ""):
    """預覽 tab: split the scenes again at another threshold (no decoding). Unsaved edits are saved first, as a flip
    does, since the player is rebuilt."""
    if job is None:
        return gr.update(), job, gr.update(), t("web.pv.load_first_hint"), gr.update()
    if job.diffs is None:
        return gr.update(), job, gr.update(), t("web.pv.no_scenes_hint"), gr.update()
    acts = parse_edits(edits)
    if acts is not None:
        job.script = hand_edited(job.script, acts)
        job.script.save(_preview_out(job))
    job.split(float(threshold))
    msg = preview_summary(job) + (t("web.pv.saved_first") if acts is not None else "")
    return (preview(job.video, job.script, job.reference, job.scene_list(), max(0.0, t_ms), play, axes=job.axes), job,
            str(job.out_path) if job.out_path else gr.update(), msg, preview_table(job))


def _preview_out(job: PreviewJob) -> Path:
    if job.out_path is None:
        out_dir = OUTPUT_DIR / time.strftime("%Y%m%d-%H%M%S")
        out_dir.mkdir(parents=True, exist_ok=True)
        job.out_path = out_dir / f"{job.name}.funscript"
    return job.out_path


def preview_save(job: PreviewJob | None, t_ms: float, play: bool, edits: str = ""):
    """預覽 tab: write the actions edited in the player."""
    if job is None:
        raise gr.Error(t("web.err.load_preview_first"))
    acts = parse_edits(edits)
    if acts is None:
        return gr.update(), job, gr.update(), t("web.msg.no_edits"), gr.update()
    job.script = hand_edited(job.script, acts)
    job.script.save(_preview_out(job))
    return (preview(job.video, job.script, job.reference, job.scene_list(), t_ms, play, axes=job.axes), job, str(job.out_path),
            t("web.pv.saved_edits", n=len(acts)), preview_table(job))


def preview_flip(job: PreviewJob | None, t_ms: float, play: bool, edits: str = ""):
    if job is None:
        raise gr.Error(t("web.err.load_preview_first"))
    k = scene_at(job.starts, t_ms)
    if k is None:
        raise gr.Error(t("web.err.no_position"))
    return _preview_flip_scene(job, k, t_ms, play, edits)


def preview_flip_row(job: PreviewJob | None, t_ms: float, play: bool, edits: str, evt: gr.SelectData):
    """A click in the 預覽 tab's scene table: flips the row's scene when it is in the flip column."""
    if job is None or evt.index is None or evt.index[1] != PREVIEW_COLUMNS.index(FLIP_COLUMN):
        return (gr.update(),) * 5
    return _preview_flip_scene(job, int(evt.row_value[0]), max(0.0, t_ms if t_ms is not None else 0.0), bool(play),
                               edits)


def _preview_flip_scene(job: PreviewJob, k: int, t_ms: float, play: bool, edits: str = ""):
    acts = parse_edits(edits)
    if acts is not None:  # unsaved edits: keep them
        job.script = hand_edited(job.script, acts)
    end = job.ends[k] if k < len(job.ends) else float("inf")
    job.script = mirror_span(job.script, job.starts[k], end, job.lo, job.hi)
    job.flipped ^= {k}
    job.script.save(_preview_out(job))
    msg = t("web.flipped_scene" if k in job.flipped else "web.unflipped_scene", k=k,
            start=format(job.starts[k] / 1000, ".1f"), end=format(end / 1000, ".1f"),
            flips=", ".join(map(str, sorted(job.flipped))) or t("web.none"))
    return (preview(job.video, job.script, job.reference, job.scene_list(), t_ms, play, axes=job.axes), job, str(job.out_path), msg,
            preview_table(job))


# --- 工具 tab: merge the axis files of a multi-axis script into one file, or split such a file ----------------------

# Column ids (English, stable); the headers shown are web.tcol.* in the language pack.
TOOL_COLUMNS = ["script", "axis", "name", "actions", "length (s)"]


def tool_headers() -> list[str]:
    return column_headers(TOOL_COLUMNS, "web.tcol")


def tool_paths(files) -> list[Path]:
    """The files of the 工具 tab: the lines of its path box (the desktop app), or the uploads."""
    if LOCAL_FILES:
        return [Path(clean_path(line)).expanduser() for line in (files or "").splitlines() if clean_path(line)]
    return _paths(files)


def tool_rows(plan: multiaxis.Plan) -> list[list]:
    """The tools table: one row per axis of every script in the plan."""
    rows = []
    for s in plan.sets:
        for axis, actions in [(multiaxis.MAIN_AXIS, s.actions), *s.ordered()]:
            last = max((a["at"] for a in actions if isinstance(a, dict) and isinstance(a.get("at"), (int, float))),
                       default=0)
            rows.append([s.name, axis, t(f"axis.{axis}"), len(actions), round(last / 1000, 1)])
    return rows


def tool_problem(code: str, name: str) -> str:
    if code == "unreadable":
        file, _, why = name.partition("\t")
        return t("web.tool.problem.unreadable", file=file, why=why)
    return t(f"web.tool.problem.{code}", name=name)


def tool_message(plan: multiaxis.Plan | None, missing: list[Path] | None = None) -> str:
    """What the 工具 tab found in the files, and what can be done with them."""
    lines = []
    if missing:
        lines.append(t("web.err.not_found", names=t("sep.list").join(str(f) for f in missing)))
    if plan is not None:
        if plan.kind == "merge":
            lines.append(t("web.tool.detected_merge", n=len(plan.sets), axes=sum(len(s.axes) for s in plan.sets)))
        elif plan.kind == "split":
            lines.append(t("web.tool.detected_split", n=len(plan.sets), axes=sum(len(s.axes) for s in plan.sets)))
        elif plan.kind == "single":
            lines.append(t("web.tool.detected_single"))
        else:
            lines.append(t("web.tool.detected_none"))
        lines += [tool_problem(code, name) for code, name in plan.problems]
    return "\n\n".join(f"- {line}" if k else line for k, line in enumerate(lines))


def tool_inspect(files):
    """The 工具 tab, when its files change: tell which kind they are, show them in a table and in the viewer, and
    show the button that fits (合併 for the axis files of a script, 分割 for a file with all its axes).
    Returns the plan (kept for the button), message, table, viewer, merge button, split button."""
    paths = tool_paths(files)
    hide = gr.update(visible=False)
    if not paths:
        return None, "", gr.update(value=[], headers=tool_headers()), "", hide, hide
    missing = [f for f in paths if not f.is_file()]
    plan = multiaxis.classify([f for f in paths if f.is_file()])
    viewer = iframe(axes_viewer_html(plan.sets), height=viewer_height(plan.sets)) if plan.sets else ""
    return (plan, tool_message(plan, missing), gr.update(value=tool_rows(plan), headers=tool_headers()), viewer,
            gr.update(visible=plan.kind == "merge"), gr.update(visible=plan.kind == "split"))


def tool_cleared():
    """The 工具 tab, after a merge or split: the files are done with, so the selection is cleared (the written files
    stay listed) and nothing about them is analysed again. Returns the files box and what tool_inspect returns for none."""
    return ("" if LOCAL_FILES else None, *tool_inspect(None))


def tool_where_changed(where: str):
    """The 工具 tab's 輸出方式: the folder to save in is asked for when saving elsewhere, what to do with the
    originals when writing beside them."""
    return gr.update(visible=where == "elsewhere"), gr.update(visible=where == "beside")


def tool_run(plan: multiaxis.Plan | None, where: str = "beside", folder: str = "", keep: str = "backup"):
    """The 工具 tab's 合併 / 分割 button: write the files of the plan. The desktop app writes beside the originals
    (`where` "beside"; an existing file is renamed to name.backup when `keep` is "backup", else replaced) or into a
    folder (an existing file is always kept as a backup); the web server, which has no original place to write to,
    puts them in its output folder to download. Returns the message and the files."""
    if plan is None or plan.kind not in ("merge", "split"):
        raise gr.Error(t("web.tool.nothing"))
    target, backup = None, False
    if LOCAL_FILES:
        if where == "elsewhere":
            if not clean_path(folder):
                raise gr.Error(t("web.tool.need_folder"))
            target, backup = Path(clean_path(folder)).expanduser(), True
        else:
            backup = keep != "overwrite"
    else:
        target = OUTPUT_DIR / time.strftime("%Y%m%d-%H%M%S")
    try:
        written = multiaxis.write_plan(plan, target, backup)
    except (OSError, ValueError) as e:
        raise gr.Error(t("web.tool.write_failed", e=e))
    lines = [t("web.tool.done_" + plan.kind, n=len(written))]
    lines += [f"`{w.path}`" + (t("web.tool.backup_of", backup=w.backup.name) if w.backup else "") for w in written]
    if plan.kind == "merge":
        lines.append(t("web.tool.axes_stay"))
    return "\n\n".join(f"- {line}" if 0 < k <= len(written) else line for k, line in enumerate(lines)), [str(w.path) for w in written]


@dataclass
class Job:
    """產生 tab: what one run keeps, so scenes can be flipped afterwards without analysing again."""
    video: Path
    result: PipelineResult
    opts: PipelineOptions
    out_path: Path
    reference: Funscript | None
    lines: list[str]  # summary lines of the run
    manual: set[int] = field(default_factory=set)  # scene numbers flipped by hand
    edited: bool = False  # actions edited in the player: flips mirror the edited script instead of rebuilding it
    copy_to: Path | None = None  # also written here (beside a local video), kept up to date like out_path
    local: bool = False  # the video was given by its path, not uploaded

    def scene_list(self) -> list[tuple[float, int, bool]]:
        return [(p.scene.start_ms, p.scene.index, p.flipped) for p in self.result.plans]


def job_outputs(job: Job, start_ms: float = 0.0, play: bool = False):
    """(output file, summary, plot, scene table, player) for the job's current script."""
    from funscript_gen.report import plot_result, possibly_inverted, scene_headers, scene_rows, unsure_scenes

    script = job.result.funscript
    script.save(job.out_path)
    if job.copy_to is not None:
        script.save(job.copy_to)
    lines = [t("web.run.actions", n=len(script.actions)) + job.lines[0], *job.lines[1:]]
    suspects = possibly_inverted(job.result)
    if suspects:
        lines.append(t("web.run.suspects", scenes=', '.join(map(str, suspects))))
    unsure = unsure_scenes(job.result)
    if unsure:
        lines.append(t("web.run.unsure", scenes=', '.join(map(str, unsure))))
    if job.edited:
        lines.append(t("web.run.hand_edited"))
    if job.manual:
        nums = ",".join(map(str, sorted(job.manual)))
        lines.append(t("web.run.manual_flips", list=nums.replace(',', ', '), nums=nums))
    if job.reference is not None:
        from funscript_gen.evaluate import WIGGLE, compare, drop_wiggles

        sc = compare(job.reference, script)
        w = compare(drop_wiggles(job.reference), script)
        lines.append(t("web.run.compare", f1=format(sc.f1, ".2f"), precision=format(sc.precision, ".2f"),
                       recall=format(sc.recall, ".2f"), corr=format(sc.correlation, ".2f"),
                       lag=format(sc.best_lag_ms, "+.0f"), corr_wide=format(sc.correlation_wide, ".2f"),
                       wiggle=format(WIGGLE, ".0f"), f1_clean=format(w.f1, ".2f")))
    fig = plot_result(job.result, job.reference)
    player = preview(job.video, script, job.reference, job.scene_list(), start_ms, play, suspects,
                     scene_regions(job.result.plans), unsure=unsure)
    return (str(job.out_path), "\n\n".join(lines), fig,
            gr.update(value=scene_rows(job.result), headers=scene_headers()), player)


def flip_scene(job: Job, number: int, start_ms: float = 0.0, play: bool = False):
    """Flip one scene (by its number) of the job's script and rewrite the output file."""
    plan = next((p for p in job.result.plans if p.scene.index == number), None)
    if plan is None or plan.signal is None or not len(plan.signal.actions):
        raise gr.Error(t("web.err.scene_empty", number=number))
    toggle_flip(plan)
    job.manual ^= {number}
    if job.edited:  # rebuilding from the scenes would drop the hand edits: mirror the edited script instead
        sig = job.opts.signal
        script = mirror_span(job.result.funscript, plan.scene.start_ms, plan.scene.end_ms, sig.pos_low, sig.pos_high)
        if "notes" in script.metadata:
            script.metadata["notes"] = re.sub(r"flipped=\[[^\]]*\]", f"flipped={flipped_scenes(job.result.plans)}",
                                              script.metadata["notes"])
        job.result.funscript = script
    else:
        refinalize(job.result, job.opts)
    msg = t("web.flipped_scene_job" if plan.flipped else "web.unflipped_scene_job", k=number,
            start=format(plan.scene.start_ms / 1000, ".1f"), end=format(plan.scene.end_ms / 1000, ".1f"))
    return (*job_outputs(job, start_ms, play), msg)


def flip_from_table(job: Job | None, t_ms: float, play: bool, edits: str, evt: gr.SelectData):
    """A click in the scene table: flips the row's scene when it is in the flip column, keeping unsaved edits and the
    player's place (read from the player, like the 反轉 button)."""
    from funscript_gen.report import SCENE_COLUMNS

    if job is None or evt.index is None or evt.index[1] != SCENE_COLUMNS.index(FLIP_COLUMN):
        return (gr.update(),) * 6
    apply_edits(job, edits)  # unsaved edits: keep them
    return flip_scene(job, int(evt.row_value[0]), max(0.0, t_ms if t_ms is not None else 0.0), bool(play))


def apply_edits(job: Job, edits: str) -> int | None:
    """Take the actions edited in the player into the job's script; their number, or None when nothing changed."""
    acts = parse_edits(edits)
    if acts is None:
        return None
    job.result.funscript = hand_edited(job.result.funscript, acts)
    job.edited = True
    return len(acts)


def save_edits(job: Job | None, t_ms: float, play: bool, edits: str = ""):
    """產生 tab: write the actions edited in the player to the output file."""
    if job is None:
        raise gr.Error(t("web.err.generate_first"))
    n = apply_edits(job, edits)
    if n is None:
        return (*(gr.update(),) * 5, t("web.msg.no_edits"))
    return (*job_outputs(job, t_ms, play), t("web.saved_edits_job", n=n))


def flip_at_time(job: Job | None, t_ms: float, play: bool, edits: str = ""):
    if job is None:
        raise gr.Error(t("web.err.generate_first"))
    apply_edits(job, edits)  # unsaved edits: keep them
    starts = [p.scene.start_ms for p in job.result.plans]
    k = scene_at(starts, t_ms)
    if k is None:
        raise gr.Error(t("web.err.no_position"))
    return flip_scene(job, job.result.plans[k].scene.index, t_ms, play)


def check_connection(base_url=None, api_key="", model="", bbox_format="", concurrency=None, backend=None,
                     num_ctx=None) -> str:
    from funscript_gen.config import list_models

    s = (_settings_from_form(base_url, api_key, model, bbox_format, concurrency, backend, num_ctx) if base_url
         else current_settings())
    try:
        t0 = time.monotonic()
        models = list_models(s)
        ms = (time.monotonic() - t0) * 1000
    except Exception as e:  # noqa: BLE001 - shown to the user verbatim
        return t("web.conn.failed", url=s.vllm_base_url, e=e)
    mark = "✅" if s.vllm_model in models else t("web.conn.model_missing")
    return t("web.conn.result", mark=mark, url=s.vllm_base_url, ms=format(ms, ".0f"), models=', '.join(models))


# Set by the 取消 button; the running job stops at its next progress report (the AI step reports one per call).
_cancel = threading.Event()


class Cancelled(Exception):
    pass


def cancel_run() -> str:
    _cancel.set()
    return t("web.cancel_requested", time=time.strftime('%H:%M:%S'))


def progress_steps(opts: PipelineOptions, duration_ms: float):
    """generate()'s progress (phase, t_ms) -> (fraction of the whole job, step name)."""
    phases = {"scenes": (0.0, 0.25, t("web.step.scenes")), "ai": (0.25, 0.35, t("web.step.ai")),
              "signal": (0.35, 1.0, t("web.step.signal"))}
    if opts.part_sign:
        phases.update(signal=(0.35, 0.7, t("web.step.signal")), parts=(0.7, 1.0, t("web.step.parts")))

    def step(phase: str, t_ms: float) -> tuple[float, str]:
        lo, hi, label = phases[phase]
        frac = min(1.0, t_ms if phase in ("ai", "parts") else t_ms / max(duration_ms, 1.0))
        return lo + (hi - lo) * frac, label
    return step


def run_lines(result: PipelineResult, elapsed: float, reused: bool = False) -> list[str]:
    """The summary lines of a finished run (Job.lines)."""
    lines = [t("web.run.scenes", n=len(result.plans), elapsed=format(elapsed, ".0f"))
             + (t("web.run.reused") if reused else "")]
    skipped = [p for p in result.plans if p.skip]
    if skipped:
        lines.append(t("web.run.skipped", n=len(skipped)))
    if result.ai_notice:
        lines.append("⚠️ " + result.ai_notice)
    errors = [p for p in result.plans if p.error]
    if errors:
        lines.append(t("web.run.ai_errors", n=len(errors)))
    used = [t("web.run.dev_flow", device=result.flow_device)] if result.flow_device else []
    if result.part_device:
        used.append(t("web.run.dev_parts", device=result.part_device.removesuffix('ExecutionProvider')))
    if used:
        lines.append(t("web.run.devices", list=t("sep.list").join(used)))
    return lines


FORM_NAMES = [o.name for o in UI_OPTIONS]


def run(video_path, local_path, reference_file, previous, *values, progress=None):
    """產生: the form's settings come in FORM_NAMES order (see the signature set below, which Gradio reads). A path in
    `local_path` (the video box of the desktop app, where there is no upload) is used instead of `video_path`.

    `previous` is the last job of this page: when it analysed the same video with the same analysis settings and
    AI backend, only the output is made again from its analysis (render), which takes about a second."""
    if progress is None:  # from Gradio: its progress tracker comes last
        *values, progress = values
    form = dict(zip(FORM_NAMES, values))
    local = local_video(local_path)
    if LOCAL_FILES and form["use_reference"]:  # the reference is a path too: check it before the long part
        reference_file = local_script(reference_file)
    if not video_path and local is None:
        raise gr.Error(t("web.err.need_video_local" if LOCAL_FILES else "web.err.need_video"))
    try:
        settings = resolve(form)
        opts = build_options(settings, ai_settings=current_settings())
        check_devices(opts)
    except (OptionError, DeviceError) as e:
        raise gr.Error(e.local)
    video = local or Path(video_path)
    analysis = previous.result.analysis if isinstance(previous, Job) else None
    if analysis is not None and (previous.opts.ai_settings != opts.ai_settings
                                 or not analysis.serves(video, analysis_key(settings))):
        analysis = None
    try:
        duration = max(probe(video).duration_ms, 1.0)
    except Exception as e:  # noqa: BLE001
        raise gr.Error(t("web.err.video_unreadable", e=e))

    step = progress_steps(opts, duration)

    def on_progress(phase: str, t_ms: float) -> None:
        if _cancel.is_set():
            raise Cancelled
        frac, label = step(phase, t_ms)
        progress(frac, desc=label)

    t0 = time.monotonic()
    _cancel.clear()
    kept: set[int] = set()  # scenes of the new script flipped by hand before and still flipped
    try:
        if analysis is not None:
            progress(0.5, desc=t("web.progress.reuse"))
            # the same scenes: the flips made by hand go on top of the ones the settings ask for
            kept = set(previous.manual)
            result = render(analysis, replace(opts, flip_scenes=tuple(sorted(set(opts.flip_scenes) ^ kept))))
        else:
            result = generate(video, opts, progress=on_progress)
            if isinstance(previous, Job) and previous.manual and previous.video == video:
                kept = set(carry_flips(previous.result, previous.manual, result))
                for plan in result.plans:
                    if plan.scene.index in kept:
                        toggle_flip(plan)
                if kept:
                    refinalize(result, opts)
    except Cancelled:
        raise gr.Error(t("web.err.cancelled"))
    except DeviceError as e:  # a GPU that the check found but that did not load
        raise gr.Error(e.local)
    except Exception as e:  # noqa: BLE001
        raise gr.Error(t("web.err.failed", e=e))
    elapsed = time.monotonic() - t0

    stem = output_stem(video.stem)
    out_dir = OUTPUT_DIR / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}.funscript"
    result.funscript.save(out_path)
    output_store().purge_expired()  # never removes out_dir: it was just written

    reference = None
    lines = run_lines(result, elapsed, analysis is not None)
    if form["use_reference"] and reference_file:
        try:
            reference = Funscript.load(reference_file)
        except Exception as e:  # noqa: BLE001
            lines.append(t("web.run.ref_unreadable", e=e))

    copy_to = beside_copy(video, lines) if local is not None else None
    if kept:
        lines.append(t("web.run.flips_kept", list=", ".join(map(str, sorted(kept)))))
    job = Job(video, result, opts, out_path, reference, lines, manual=kept, copy_to=copy_to, local=local is not None)
    return (*job_outputs(job), job, gr.update())


run.__signature__ = inspect.Signature(
    [inspect.Parameter(n, inspect.Parameter.POSITIONAL_OR_KEYWORD)
     for n in ("video_path", "local_path", "reference_file", "previous", *FORM_NAMES)]
    + [inspect.Parameter("progress", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=gr.Progress())])


BATCH_STATUS = ("pending", "done", "failed", "cancelled", "skipped")  # their names are web.batch.status.*


def batch_columns() -> list[str]:
    return [t(f"web.batch.col_{k}") for k in ("num", "video", "status", "scenes", "actions", "inverted", "seconds", "error")]


def batch_status_name(status: str) -> str:
    return t(f"web.batch.status.{status}")


def batch_label(k: int, item) -> str:
    return f"{k + 1}. {item.video.name}"


def batch_rows(items: list) -> list[list]:
    from funscript_gen.report import possibly_inverted

    rows = []
    for k, item in enumerate(items):
        res = item.result
        rows.append([k + 1, item.video.name, batch_status_name(item.status),
                     len(res.plans) if res else "", len(res.funscript.actions) if res else "",
                     ", ".join(map(str, possibly_inverted(res))) if res else "",
                     f"{item.seconds:.0f}" if item.status in ("done", "failed") else "", item.error])
    return rows


def batch_summary(items: list, out_dir: Path) -> str:
    counts = {s: sum(i.status == s for i in items) for s in BATCH_STATUS}
    done = t("sep.list").join(t("web.batch.count", status=batch_status_name(s), n=n) for s, n in counts.items() if n)
    return t("web.batch.summary", total=len(items), done=done, folder=out_dir.name)


def run_batch_ui(files, local_paths, *values, progress=None):
    """批次: every uploaded video, then every video in `local_paths` (desktop app only: one video or folder per line),
    with the 產生 tab's settings (FORM_NAMES order), one after another, into one output folder. A generator: the table
    fills in as the videos finish. Yields (table, files, summary, jobs, choices)."""
    from funscript_gen.batch import BatchItem, output_paths, run_batch

    if progress is None:  # from Gradio: its progress tracker comes last
        *values, progress = values
    local = local_videos(local_paths)
    videos = [Path(f) for f in files or []] + local
    if not videos:
        raise gr.Error(t("web.err.need_videos"))
    try:
        settings = resolve(dict(zip(FORM_NAMES, values)))
        opts = build_options(settings, ai_settings=current_settings())
        check_devices(opts)
    except (OptionError, DeviceError) as e:
        raise gr.Error(e.local)
    out_dir = OUTPUT_DIR / time.strftime("%Y%m%d-%H%M%S")
    items = [BatchItem(v, o) for v, o in zip(videos, output_paths(videos, out_dir, output_stem))]
    jobs: dict[str, Job] = {}

    def outputs(note: str = ""):
        files_out = [str(i.output) for i in items if i.status == "done"]
        return (gr.update(value=batch_rows(items), headers=batch_columns()), files_out or None,
                note or batch_summary(items, out_dir), jobs, gr.update(choices=list(jobs), value=None))

    _cancel.clear()
    n = len(items)
    for k, item in enumerate(items):
        if _cancel.is_set():
            item.status = "cancelled"
            continue
        try:
            step = progress_steps(opts, probe(item.video).duration_ms)
        except Exception as e:  # noqa: BLE001 - not a readable video: the next one runs
            item.status, item.error = "failed", t("web.err.video_unreadable", e=e)
            yield outputs(t("web.batch.progress", k=k + 1, n=n))
            continue

        def on_progress(_k: int, phase: str, t_ms: float, k=k, step=step, name=item.video.name) -> None:
            if _cancel.is_set():
                raise Cancelled
            frac, label = step(phase, t_ms)
            progress((k + frac) / n, desc=t("web.batch.item_progress", k=k + 1, n=n, name=name, label=label))

        run_batch([item], opts, on_progress=on_progress, stopped=_cancel.is_set, keep_results=True)
        if item.status == "done":
            lines = run_lines(item.result, item.seconds)
            copy_to = beside_copy(item.video, lines) if item.video in local else None
            if copy_to is not None:
                item.result.funscript.save(copy_to)
            jobs[batch_label(k, item)] = Job(item.video, item.result, opts, item.output, None, lines,
                                             copy_to=copy_to, local=item.video in local)
        if item.status == "failed":
            item.error = t("web.err.failed", e=item.error)
        yield outputs(t("web.batch.progress_done", k=k + 1, n=n) if k + 1 < n and not _cancel.is_set() else "")
    output_store().purge_expired()  # never removes out_dir: it was just written
    yield outputs()


run_batch_ui.__signature__ = inspect.Signature(
    [inspect.Parameter(n, inspect.Parameter.POSITIONAL_OR_KEYWORD) for n in ("files", "local_paths", *FORM_NAMES)]
    + [inspect.Parameter("progress", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=gr.Progress())])


def open_batch_job(jobs: dict | None, label: str | None):
    """批次: show one finished video in the 產生 tab, where it can be checked, flipped and edited like a run of its
    own (pressing 產生 there with new output settings reuses its analysis)."""
    job = (jobs or {}).get(label or "")
    if job is None:
        raise gr.Error(t("web.err.pick_job"))
    # A local video goes into the path box: the upload box only takes files Gradio may serve.
    video, local = (None, str(job.video)) if job.local else (str(job.video), "")
    return (*job_outputs(job), job, t("web.batch.opened", name=job.video.name), video, local, gr.Tabs(selected="gen"))


# Radios with elem_classes "segmented" (Opt.control) drawn as one bar of joined buttons, the chosen one filled.
SEGMENTED_CSS = """
.segmented .wrap:has(> label) { display: inline-flex !important; flex-wrap: nowrap !important; gap: 0 !important;
  border: 1px solid var(--border-color-primary); border-radius: var(--radius-lg); overflow: hidden; }
.segmented label { margin: 0 !important; border: 0 !important; border-radius: 0 !important; box-shadow: none !important;
  padding: 6px 16px !important; justify-content: center; cursor: pointer; background: var(--background-fill-primary) !important; }
.segmented label + label { border-left: 1px solid var(--border-color-primary) !important; }
.segmented label input { display: none; }
.segmented label span { margin: 0 !important; }
.segmented label.selected { background: var(--color-accent) !important; color: white !important; }
"""


# Drop zones of the desktop app: a row with class fg-drop (id drop-<zone>). The window's drops reach Python
# (app.drop_handler: only it knows the files' paths), which calls fgDropped(paths); this script remembers which zone
# the drop was on and hands it, with the paths, to the hidden box fg-inbox, whose change event runs drop_arrived (an input event set from a script is not noticed).
UI_CSS = """
.fg-drop { border: 2px dashed transparent; border-radius: var(--radius-lg); padding: 2px; transition: border-color .1s; }
.fg-drop.fg-over { border-color: var(--color-accent); background: var(--background-fill-secondary); }
"""
UI_JS = """() => {
  if (window.fgDropped) return;
  let zone = '', n = 0;
  const files = e => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
  const find = e => (e.target.closest ? e.target.closest('.fg-drop') : null);
  const clear = () => document.querySelectorAll('.fg-over').forEach(el => el.classList.remove('fg-over'));
  // A file dropped anywhere that takes no drop would be opened by the window, replacing the app.
  window.addEventListener('dragover', e => {
    if (!files(e)) return;
    e.preventDefault(); clear();
    const el = find(e); if (el) el.classList.add('fg-over');
  }, true);
  window.addEventListener('dragleave', e => { if (!e.relatedTarget) clear(); }, true);
  window.addEventListener('drop', e => {
    if (!files(e)) return;
    e.preventDefault(); clear();
    const el = find(e); zone = el ? el.id.replace(/^drop-/, '') : '';
  }, true);
  window.fgDropped = paths => {
    const box = document.querySelector('#fg-inbox textarea');
    if (!zone || !box) return;
    const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    set.call(box, JSON.stringify({zone: zone, paths: paths, n: ++n}));
    box.dispatchEvent(new Event('input', {bubbles: true}));
    zone = '';
  };
}"""


def path_row(zone: str, label: str, buttons: dict[str, str], *, placeholder: str | None = None,
             info: str | None = None, lines: int = 1, visible: bool = True, elem_id: str | None = None):
    """A box of paths on this computer (the desktop app) that is also a drop zone `zone`, with a button beside it
    for each of `buttons` (dialog kind -> its text key). Returns the row, the box and the buttons in that order."""
    with gr.Row(equal_height=True, elem_id=f"drop-{zone}", elem_classes=["fg-drop"], visible=visible) as row:
        box = ui(gr.Textbox, label=L(label), placeholder=L(placeholder) if placeholder else None,
                 info=L(info) if info else None, lines=lines, scale=4, elem_id=elem_id)
        with gr.Column(scale=1, min_width=140, visible=NATIVE_DIALOGS):
            picks = {kind: ui(gr.Button, value=L(key)) for kind, key in buttons.items()}
    return row, box, list(picks.values())


def _control(o):
    """The web UI control for option `o`: a choice with "" (the AI decides) is a dropdown, other choices radios
    (a segmented control when o.control says so, see SEGMENTED_CSS)."""
    kw = {"label": Late(lambda: o.label)} | ({"info": Late(lambda: o.info)} if o.info else {})
    if o.kind == "bool":
        return ui(gr.Checkbox, value=o.default, **kw)
    if o.kind == "choice":
        choices = Late(lambda: list(o.choices))
        if o.control == "segmented":
            return ui(gr.Radio, choices=choices, value=o.default, elem_classes=["segmented"], **kw)
        return ui(gr.Dropdown if "" in o.values else gr.Radio, choices=choices, value=o.default, **kw)
    if o.kind == "text":
        return ui(gr.Textbox, value=o.default, placeholder=Late(lambda: o.placeholder or None), **kw)
    lo, hi, step = o.slider
    return ui(gr.Slider, lo, hi, value=o.default, step=step, **kw)


# Option groups shown in the 設定 tab instead of the 產生 tab. They are still part of the 產生 form (run, batch,
# remembered with it), but a preset or 還原預設設定 leaves them alone, and a change there is remembered at once.
SETTINGS_TAB_GROUPS = ("device",)


def settings_form(after: dict | None = None, groups=None) -> tuple[dict, list]:
    """The settings laid out from UI_OPTIONS: an accordion per group (`groups`, default those of the 產生 tab),
    options sharing a row side by side, a row with show_if hidden while its switch is off. after[name]() adds
    components right after that option. Returns (option name -> component, [(switch name, row)])."""
    after = after or {}
    form, toggles = {}, []
    for group in groups or [g for g in GROUPS if g not in SETTINGS_TAB_GROUPS]:
        members = [o for o in UI_OPTIONS if o.group == group]
        with ui(gr.Accordion, label=Late(lambda group=group: group_title(group)), open=group != "advanced" and group not in SETTINGS_TAB_GROUPS):
            k = 0
            while k < len(members):
                o = members[k]
                if not o.row:
                    form[o.name] = _control(o)
                    k += 1
                    placed = [o]
                else:
                    placed = [o]
                    while k + len(placed) < len(members) and members[k + len(placed)].row == o.row:
                        placed.append(members[k + len(placed)])
                    with gr.Row(visible=bool(BY_NAME[o.show_if].default) if o.show_if else True) as row:
                        for m in placed:
                            form[m.name] = _control(m)
                    if o.show_if:
                        toggles.append((o.show_if, row))
                    k += len(placed)
                for m in placed:
                    if m.name in after:
                        after[m.name]()
    return form, toggles



LANGUAGE_LABEL = "語言 / Language"  # the one text that is not translated: it has to be findable in any language


def build() -> gr.Blocks:
    settings = current_settings()
    _translated.clear()
    with gr.Blocks(title="funscript-gen") as demo:
        gr.Markdown("# funscript-gen")
        with gr.Tabs() as tabs:
            with ui(gr.Tab, label=L("web.tab.gen"), id="gen"):
                with gr.Row():
                    with gr.Column(scale=2):
                        with gr.Row():
                            run_btn = ui(gr.Button, value=L("web.gen.run"), variant="primary", scale=4)
                            cancel_btn = ui(gr.Button, value=L("web.cancel"), variant="stop", scale=1)
                        run_msg = gr.Markdown()
                        if LOCAL_FILES:  # no uploads: the files are read where they are
                            video = gr.State(None)
                            _, video_local, (video_pick,) = path_row(
                                "gen-video", "web.gen.local_video", {"video": "web.pick"},
                                placeholder="web.gen.local_placeholder", info="web.gen.local_info", elem_id="local-video")
                            reference_ctl, reference, (reference_pick,) = path_row(
                                "gen-ref", "web.gen.reference", {"script": "web.pick"},
                                placeholder="web.gen.local_script_placeholder", info="web.drop.script_info",
                                visible=False)
                        else:
                            video = ui(gr.Video, label=L("web.gen.video"), sources=["upload"])
                            video_local = gr.State("")
                            reference = reference_ctl = ui(
                                gr.File, label=L("web.gen.reference"), file_types=[".funscript", ".json"],
                                type="filepath", visible=False)

                        with gr.Row():
                            preset = ui(gr.Dropdown, choices=Late(lambda: [(preset_label(k), k) for k in PRESETS]),
                                        value="default", label=L("web.gen.preset"),
                                                 info=L("web.gen.preset_info"), scale=4)
                            preset_btn = ui(gr.Button, value=L("web.gen.apply"), size="sm", scale=1)
                        extra = {}

                        def ai_status() -> None:
                            extra["status"] = gr.Markdown(_ai_status(settings))
                            extra["test_btn"] = ui(gr.Button, value=L("web.test_connection"), size="sm")

                        form, toggles = settings_form({"use_ai": ai_status})
                        status, test_btn = extra["status"], extra["test_btn"]
                        use_reference, scene_threshold = form["use_reference"], form["scene_threshold"]

                        with gr.Row():
                            form_msg = ui(gr.Markdown, value=L("web.gen.remember"))
                            reset_btn = ui(gr.Button, value=L("web.gen.reset"), size="sm", scale=0)

                    with gr.Column(scale=3):
                        ui(gr.Markdown, value=L("web.gen.preview_title"))
                        player = gr.HTML(elem_id="gen-player")
                        with gr.Row():
                            flip_btn = ui(gr.Button, value=L("web.flip"), size="sm", scale=0)
                            save_btn = ui(gr.Button, value=L("web.save_edits"), size="sm", scale=0)
                            flip_msg = ui(gr.Markdown, value=L("web.gen.flip_help"))
                        output_file = ui(gr.File, label=L("web.output_funscript"))
                        summary = gr.Markdown()
                        plot = ui(gr.Plot, label=L("web.gen.plot"))
                        scenes = ui(gr.Dataframe,
                            label=L("web.gen.scenes"),
                            interactive=False, wrap=True,
                        )
                        job = gr.State()
                        cur_t = gr.Number(visible=False)
                        cur_play = gr.Checkbox(visible=False)
                        cur_edits = gr.Textbox(visible=False)

            with ui(gr.Tab, label=L("web.tab.batch")):
                ui(gr.Markdown, value=L("web.batch.intro"))
                with gr.Row():
                    batch_btn = ui(gr.Button, value=L("web.batch.run"), variant="primary", scale=4)
                    batch_cancel = ui(gr.Button, value=L("web.cancel"), variant="stop", scale=1)
                batch_msg = gr.Markdown()
                if LOCAL_FILES:
                    batch_videos = gr.State(None)
                    _, batch_local, (batch_add_files, batch_add_folder) = path_row(
                        "batch", "web.batch.local", {"videos": "web.batch.pick_videos", "folder": "web.batch.pick_folder"},
                        info="web.batch.local_info", lines=4)
                else:
                    batch_videos = ui(gr.File, label=L("web.batch.videos"), file_count="multiple",
                                      file_types=["video"], type="filepath")
                    batch_local = gr.State("")
                batch_table = ui(gr.Dataframe, headers=Late(batch_columns), label=L("web.batch.result"), interactive=False, wrap=True)
                batch_files = ui(gr.File, label=L("web.output_funscript"), file_count="multiple")
                with gr.Row(equal_height=True):
                    batch_pick = ui(gr.Dropdown, [], label=L("web.batch.done_videos"), scale=4,
                                             info=L("web.batch.done_info"))
                    batch_open = ui(gr.Button, value=L("web.batch.open"), scale=1)
                batch_jobs = gr.State()

            with ui(gr.Tab, label=L("web.tab.preview")):
                ui(gr.Markdown, value=L("web.pv.intro"))
                if LOCAL_FILES:
                    pv_auto = ui(gr.Checkbox, label=L("web.pv.auto"), value=True, info=L("web.pv.auto_info"))
                    _, pv_video, (pv_video_pick,) = path_row(
                        "pv-video", "web.pv.video_local", {"video": "web.pick_video"},
                        placeholder="web.gen.local_placeholder", info="web.pv.video_info", elem_id="pv-video")
                    _, pv_script, (pv_script_pick,) = path_row(
                        "pv-script", "web.pv.script_local", {"script": "web.pick_script"},
                        placeholder="web.gen.local_script_placeholder", elem_id="pv-script")
                    _, pv_axes, (pv_axes_pick,) = path_row(
                        "pv-axes", "web.pv.axes_local", {"scripts": "web.tool.pick_scripts"},
                        info="web.pv.axes_info", lines=2, elem_id="pv-axes")
                    pv_ref_ctl, pv_ref, (pv_ref_pick,) = path_row(
                        "pv-ref", "web.pv.reference", {"script": "web.pick"},
                        placeholder="web.gen.local_script_placeholder", visible=False)
                else:
                    with gr.Row():
                        pv_video = ui(gr.File, label=L("web.pv.video"), file_count="multiple",
                                           file_types=["video", *SCRIPT_SUFFIXES], type="filepath", elem_id="pv-video")
                        pv_script = ui(gr.File, label=L("web.pv.script"), file_count="multiple",
                                       file_types=[".funscript", ".json"], type="filepath", elem_id="pv-script")
                    pv_axes = gr.State(None)
                    with gr.Row():
                        pv_ref = pv_ref_ctl = ui(gr.File, label=L("web.pv.reference"),
                                                 file_types=[".funscript", ".json"], type="filepath", visible=False)
                with gr.Row(equal_height=True):
                    pv_threshold = _control(BY_NAME["scene_threshold"])
                    pv_btn = ui(gr.Button, value=L("web.pv.load"), variant="primary", scale=0)
                    pv_whole = ui(gr.Button, value=L("web.pv.load_whole"), scale=0)
                    pv_cancel = ui(gr.Button, value=L("web.pv.cancel_load"), variant="stop", scale=0)
                    pv_rescene = ui(gr.Button, value=L("web.pv.rescene"), scale=0)
                pv_player = gr.HTML(elem_id="pv-player")
                with gr.Row():
                    pv_flip = ui(gr.Button, value=L("web.flip"), size="sm", scale=0)
                    pv_save = ui(gr.Button, value=L("web.save_edits"), size="sm", scale=0)
                    pv_msg = ui(gr.Markdown, value=L("web.pv.help"), elem_id="pv-msg")
                pv_out = ui(gr.File, label=L("web.pv.out"))
                pv_scenes = ui(gr.Dataframe,
                    label=L("web.pv.scenes"),
                    interactive=False, wrap=True,
                )
                pv_job = gr.State()
                pv_t = gr.Number(visible=False)
                pv_play = gr.Checkbox(visible=False)
                pv_edits = gr.Textbox(visible=False)

            with ui(gr.Tab, label=L("web.tab.tools"), id="tools"):
                ui(gr.Markdown, value=L("web.tool.intro"))
                if LOCAL_FILES:
                    tool_auto = ui(gr.Checkbox, label=L("web.tool.auto"), value=True, info=L("web.tool.auto_info"))
                    _, tool_in, (tool_in_pick,) = path_row(
                        "tool-in", "web.tool.files_local", {"scripts": "web.tool.pick_scripts"},
                        info="web.tool.files_info", lines=4, elem_id="tool-in")
                else:
                    tool_auto = gr.State(False)
                    tool_in = ui(gr.File, label=L("web.tool.files"), file_count="multiple",
                                 file_types=[".funscript", ".json"], type="filepath", elem_id="tool-in")
                tool_msg = gr.Markdown()
                tool_table = ui(gr.Dataframe, headers=Late(tool_headers), label=L("web.tool.table"),
                                interactive=False, wrap=True)
                tool_view = gr.HTML(elem_id="tool-view")
                if LOCAL_FILES:
                    tool_where = ui(gr.Radio, value="beside", label=L("web.tool.where"), info=L("web.tool.where_info"),
                                    choices=Late(lambda: [(t("web.tool.where_beside"), "beside"),
                                                          (t("web.tool.where_elsewhere"), "elsewhere")]))
                    tool_keep = ui(gr.Radio, value="backup", label=L("web.tool.keep"), info=L("web.tool.keep_info"),
                                   choices=Late(lambda: [(t("web.tool.keep_backup"), "backup"),
                                                         (t("web.tool.keep_overwrite"), "overwrite")]))
                    tool_out_row, tool_out, (tool_out_pick,) = path_row(
                        "tool-out", "web.tool.folder", {"folder": "web.tool.pick_folder"},
                        info="web.tool.folder_info", visible=False, elem_id="tool-out")
                else:
                    tool_where, tool_keep, tool_out = gr.State("beside"), gr.State("backup"), gr.State("")
                with gr.Row():
                    tool_merge = ui(gr.Button, value=L("web.tool.merge"), variant="primary", scale=0, visible=False)
                    tool_split = ui(gr.Button, value=L("web.tool.split"), variant="primary", scale=0, visible=False)
                tool_result = gr.Markdown()
                tool_files = ui(gr.File, label=L("web.tool.out"), file_count="multiple")
                tool_plan = gr.State()

            with ui(gr.Tab, label=L("web.tab.output")) as out_tab:
                ui(gr.Markdown, value=L("web.out.intro"))
                out_status = gr.Markdown(output_status)
                with gr.Row():
                    out_refresh = ui(gr.Button, value=L("web.out.refresh"))
                    out_open = ui(gr.Button, value=L("web.out.open"), visible=LOCAL_FILES)
                    out_clear = ui(gr.Button, value=L("web.out.clear"), variant="stop")
                with gr.Row(visible=False) as out_confirm_row:
                    ui(gr.Markdown, value=L("web.out.confirm_text"))
                    out_confirm = ui(gr.Button, value=L("web.out.confirm"), variant="stop")
                    out_cancel = ui(gr.Button, value=L("web.cancel"))
                out_msg = gr.Markdown()
                out_list = gr.HTML(output_list_html)

            with ui(gr.Tab, label=L("web.tab.settings")):
                set_lang = gr.Dropdown(i18n.choices(), value=i18n.current(), label=LANGUAGE_LABEL,
                                       info=t("web.set.lang_info"))
                with gr.Accordion("AI API", open=False):
                    ui(gr.Markdown,
                        value=L("web.set.intro")
                    )
                    ollama = settings.vllm_backend == "ollama"
                    set_backend = ui(gr.Radio, choices=Late(backend_choices), value=settings.vllm_backend, label=L("web.set.backend"),
                                           info=L("web.set.backend_info"))
                    set_url = ui(gr.Textbox, label=L("web.set.url"), value=settings.vllm_base_url,
                                         placeholder=Late(lambda: _url_placeholder("ollama" if ollama else "openai")))
                    set_key = ui(gr.Textbox,
                        label=L("web.set.key"), type="password", value="",
                        placeholder=Late(lambda: t("web.key_keep") if current_settings().vllm_api_key else t("web.key_unset")),
                        info=L("web.set.key_info"),
                    )
                    with gr.Row():
                        set_model = ui(gr.Dropdown,
                            [settings.vllm_model], value=settings.vllm_model, label=L("web.set.model"),
                            allow_custom_value=True, scale=4, info=L("web.set.model_info"),
                        )
                        set_fetch = ui(gr.Button, value=L("web.set.fetch"), scale=1)
                    set_bbox = ui(gr.Dropdown, choices=Late(bbox_choices), value=settings.vllm_bbox_format, label=L("web.set.bbox"),
                                           info=L("web.set.bbox_info"))
                    set_concurrency = ui(gr.Slider,
                        1, 32, value=settings.vllm_concurrency, step=1, label=L("web.set.concurrency"),
                        info=L("web.set.concurrency_info"),
                    )
                    set_num_ctx = ui(gr.Number,
                        value=settings.vllm_num_ctx, precision=0, minimum=2048, label=L("web.set.num_ctx"), visible=ollama,
                        info=L("web.set.num_ctx_info"),
                    )
                    with ui(gr.Group, visible=ollama) as ollama_box:
                        ui(gr.Markdown, value=L("web.ollama.intro"))
                        ollama_mode = ui(gr.Radio, choices=Late(ollama_mode_choices), label=L("web.ollama.mode"),
                                         value=next((m for m in ollama_setup.MODES if ollama_setup.available(m)),
                                                    ollama_setup.MODES[0]))
                        ollama_model = ui(gr.Dropdown, ollama_setup.MODELS, value=ollama_setup.DEFAULT_MODEL,
                                          allow_custom_value=True, label=L("web.ollama.model"),
                                          info=L("web.ollama.model_info"))
                        with gr.Row():
                            ollama_run = ui(gr.Button, value=L("web.ollama.run"), scale=2)
                            ollama_check = ui(gr.Button, value=L("web.ollama.check"))
                            ollama_clear = ui(gr.Button, value=L("web.ollama.clear"), variant="stop")
                        with gr.Row(visible=False) as ollama_confirm_row:
                            ui(gr.Markdown, value=L("web.ollama.clear_confirm"))
                            ollama_confirm = ui(gr.Button, value=L("web.ollama.clear_yes"), variant="stop")
                            ollama_cancel = ui(gr.Button, value=L("web.cancel"))
                    with gr.Row():
                        set_test = ui(gr.Button, value=L("web.test_connection"))
                        set_save = ui(gr.Button, value=L("web.set.save"), variant="primary")
                    set_status = gr.Markdown()

                settings_tab, settings_toggles = settings_form(
                    {"compute": lambda: ui(gr.Markdown, value=L("web.set.compute_note"))},
                    groups=SETTINGS_TAB_GROUPS)
                toggles += settings_toggles
                form = {name: (form | settings_tab)[name] for name in FORM_NAMES}  # run()'s parameter order

                with ui(gr.Accordion, label=L("web.set.files"), open=False):
                    ui(gr.Markdown, value=L("web.set.files_intro"))
                    set_out_status = gr.Markdown(output_status)
                    out_days = ui(gr.Number, value=lambda: output_store().retention_days, precision=0, minimum=0,
                                         label=L("web.set.days"), info=L("web.set.days_info"))
                    out_beside = ui(gr.Checkbox,
                        value=lambda: output_store().beside_video, label=L("web.set.beside"), visible=LOCAL_FILES,
                        info=L("web.set.beside_info"))
                    with gr.Row():
                        out_save = ui(gr.Button, value=L("web.set.save_retention"), variant="primary")
                        out_expire = ui(gr.Button, value=L("web.set.delete_expired"), variant="stop")
                    set_out_msg = gr.Markdown()

        if LOCAL_FILES:
            inbox = gr.Textbox(visible="hidden", elem_id="fg-inbox")  # where UI_JS puts the files dropped on the window
        test_btn.click(check_connection, outputs=status)
        lang_outputs = [*translated_components(), set_lang, status, out_status, set_out_status, out_list]
        set_lang.input(pick_language, inputs=set_lang, outputs=lang_outputs)
        demo.load(apply_language, outputs=lang_outputs)  # a page opened later follows the language chosen since
        use_reference.change(toggle_reference, inputs=use_reference, outputs=[reference_ctl, pv_ref_ctl])
        ai_form = [set_url, set_key, set_model, set_bbox, set_concurrency, set_backend, set_num_ctx]
        set_backend.change(backend_changed, inputs=[set_backend, set_url], outputs=[set_url, set_num_ctx, ollama_box])
        ollama_check.click(ollama_status, outputs=set_status)
        ollama_clear.click(lambda: ask_ollama_clear(True), outputs=ollama_confirm_row)
        ollama_cancel.click(lambda: ask_ollama_clear(False), outputs=ollama_confirm_row)
        ollama_confirm.click(clear_ollama, outputs=[set_status, ollama_confirm_row])
        ollama_run.click(run_ollama, inputs=[ollama_mode, ollama_model, set_concurrency],
                         outputs=[set_status, set_url, set_model, status, set_backend, set_num_ctx])
        set_fetch.click(fetch_models, inputs=ai_form, outputs=[set_model, set_status])
        set_test.click(check_connection, inputs=ai_form, outputs=set_status)
        set_save.click(save_settings, inputs=ai_form, outputs=[set_status, status, set_key])
        out_listing = [out_status, set_out_status, out_list]
        out_save.click(save_retention, inputs=out_days, outputs=[set_out_msg, *out_listing])
        out_expire.click(delete_expired, inputs=out_days, outputs=[set_out_msg, *out_listing])
        out_refresh.click(refresh_outputs, outputs=out_listing)
        out_tab.select(refresh_outputs, outputs=out_listing)
        out_clear.click(lambda: ask_clear(True), outputs=out_confirm_row)
        out_cancel.click(lambda: ask_clear(False), outputs=out_confirm_row)
        out_confirm.click(clear_outputs, outputs=[out_msg, *out_listing, out_confirm_row])
        # The keys are the names saved in _last_file; run() takes the values in this order after the two uploads.
        defaults = {k: c.value for k, c in form.items()}
        # Fires on restore, reset and presets too, so the sliders follow the remembered switches.
        for switch, row in toggles:
            form[switch].change(lambda on: gr.update(visible=on), inputs=form[switch], outputs=row)

        gen_form = {k: c for k, c in form.items() if k not in settings_tab}  # what presets and 還原預設設定 change

        def apply_preset(name):
            return [*restore_form(gen_form, resolve({}, name)),
                    t("web.gen.preset_applied", preset=preset_label(name), time=time.strftime('%H:%M:%S'))]

        preset_btn.click(apply_preset, inputs=preset, outputs=[*gen_form.values(), form_msg]).then(
            toggle_reference, inputs=use_reference, outputs=[reference_ctl, pv_ref_ctl])

        def remember(*values):
            save_last_form(dict(zip(form, values)))

        def reset_form():
            kept = {k: v for k, v in load_last_form().items() if k in settings_tab}
            if kept:
                save_last_form(kept)
            else:
                _last_file.unlink(missing_ok=True)
            return [*restore_form(gen_form, defaults), t("web.gen.reset_done", time=time.strftime('%H:%M:%S'))]

        for name, control in settings_tab.items():
            control.input(lambda v, name=name: remember_settings_tab({name: v}), inputs=control, queue=False)

        demo.load(lambda: restore_form(form, load_last_form()), outputs=list(form.values())).then(
            toggle_reference, inputs=use_reference, outputs=[reference_ctl, pv_ref_ctl]).then(
            lambda v: v, inputs=scene_threshold, outputs=pv_threshold)  # the 預覽 tab starts from the same threshold
        reset_btn.click(reset_form, outputs=[*gen_form.values(), form_msg]).then(
            toggle_reference, inputs=use_reference, outputs=[reference_ctl, pv_ref_ctl])
        run_btn.click(remember, inputs=list(form.values()), queue=False)
        run_btn.click(lambda: "", outputs=run_msg, queue=False)
        run_btn.click(
            run,
            inputs=[video, video_local, reference, job, *form.values()],
            outputs=[output_file, summary, plot, scenes, player, job, flip_msg],
        ).then(refresh_outputs, outputs=out_listing)
        cancel_btn.click(cancel_run, outputs=run_msg, queue=False)
        batch_btn.click(remember, inputs=list(form.values()), queue=False)
        batch_btn.click(lambda: "", outputs=batch_msg, queue=False)
        batch_btn.click(
            run_batch_ui,
            inputs=[batch_videos, batch_local, *form.values()],
            outputs=[batch_table, batch_files, batch_msg, batch_jobs, batch_pick],
        ).then(refresh_outputs, outputs=out_listing)
        batch_cancel.click(cancel_run, outputs=batch_msg, queue=False)
        batch_open.click(open_batch_job, inputs=[batch_jobs, batch_pick],
                         outputs=[output_file, summary, plot, scenes, player, job, flip_msg, video, video_local, tabs])
        if LOCAL_FILES:
            drops = [video_local, reference, batch_local, pv_video, pv_script, pv_ref, pv_axes, tool_in, tool_out, pv_msg]
            context = [batch_local, pv_auto, tool_auto]
            inbox.change(drop_arrived, inputs=[inbox, *context], outputs=drops)
            for zone, kind, button in (
                    ("gen-video", "video", video_pick), ("gen-ref", "script", reference_pick),
                    ("batch", "videos", batch_add_files), ("batch", "folder", batch_add_folder),
                    ("pv-video", "video", pv_video_pick), ("pv-script", "script", pv_script_pick),
                    ("pv-axes", "scripts", pv_axes_pick), ("pv-ref", "script", pv_ref_pick),
                    ("tool-in", "scripts", tool_in_pick), ("tool-out", "folder", tool_out_pick)):
                button.click(lambda text, auto, tool_auto, zone=zone, kind=kind:
                             choose(zone, kind, text, tool_auto if zone.startswith("tool-") else auto),
                             inputs=context, outputs=drops)
            for zone, box in (("pv-video", pv_video), ("pv-script", pv_script)):
                box.submit(lambda text, batch, auto, tool_auto, zone=zone: typed(zone, text, batch, auto),
                           inputs=[box, *context], outputs=drops)
        else:
            video.upload(lambda: "", outputs=video_local, queue=False)
        out_open.click(open_output_dir, outputs=out_msg)
        out_beside.input(save_beside, inputs=out_beside, outputs=set_out_msg, queue=False)
        flipped = [output_file, summary, plot, scenes, player, flip_msg]
        scenes.select(flip_from_table, inputs=[job, cur_t, cur_play, cur_edits], outputs=flipped,
                      js=_PLAYER_TIME_JS.format(id="gen-player"))
        flip_btn.click(flip_at_time, inputs=[job, cur_t, cur_play, cur_edits], outputs=flipped,
                       js=_PLAYER_TIME_JS.format(id="gen-player"))
        save_btn.click(save_edits, inputs=[job, cur_t, cur_play, cur_edits], outputs=flipped,
                       js=_PLAYER_TIME_JS.format(id="gen-player"))
        tool_inspected = [tool_plan, tool_msg, tool_table, tool_view, tool_merge, tool_split]
        tool_in.change(tool_inspect, inputs=tool_in, outputs=tool_inspected)
        if LOCAL_FILES:
            tool_where.change(tool_where_changed, inputs=tool_where, outputs=[tool_out_row, tool_keep], queue=False)
        for button in (tool_merge, tool_split):
            button.click(tool_run, inputs=[tool_plan, tool_where, tool_out, tool_keep],
                         outputs=[tool_result, tool_files]).success(tool_cleared, outputs=[tool_in, *tool_inspected])
        pv_outputs = [pv_player, pv_job, pv_out, pv_msg, pv_scenes]
        pv_js = _PLAYER_TIME_JS.format(id="pv-player")
        if not LOCAL_FILES:
            pv_video.upload(preview_video_uploaded, inputs=pv_video, outputs=[pv_video, pv_script, pv_msg])
        pv_btn.click(preview_files, inputs=[pv_video, pv_script, pv_ref, use_reference, pv_threshold, pv_axes],
                     outputs=pv_outputs)
        pv_whole.click(preview_files_whole, inputs=[pv_video, pv_script, pv_ref, use_reference, pv_threshold, pv_axes],
                       outputs=pv_outputs)
        pv_cancel.click(preview_cancel, outputs=pv_msg, queue=False)
        # The threshold goes between the job and the player's values: the JS passes the extra inputs through.
        pv_rescene_js = """(job, threshold, t, play, edits) => {{
  const r = ({js})(job, t, play, edits);
  return [r[0], threshold, r[1], r[2], r[3]];
}}""".format(js=pv_js)
        for trigger in (pv_rescene.click, pv_threshold.release):
            trigger(preview_rescene, inputs=[pv_job, pv_threshold, pv_t, pv_play, pv_edits], outputs=pv_outputs,
                    js=pv_rescene_js)
        pv_flip.click(preview_flip, inputs=[pv_job, pv_t, pv_play, pv_edits], outputs=pv_outputs, js=pv_js)
        pv_save.click(preview_save, inputs=[pv_job, pv_t, pv_play, pv_edits], outputs=pv_outputs, js=pv_js)
        pv_scenes.select(preview_flip_row, inputs=[pv_job, pv_t, pv_play, pv_edits], outputs=pv_outputs, js=pv_js)
    return demo


def create_app(cleanup_file: str | Path | None = None, last_file: str | Path | None = None):
    global _cleanup_file, _last_file
    _cleanup_file = Path(cleanup_file) if cleanup_file else DEFAULT_CLEANUP_FILE
    _last_file = Path(last_file) if last_file else DEFAULT_LAST_FILE
    i18n.init(saved=saved_language())

    import fastapi
    from fastapi.responses import FileResponse

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    demo = build()
    demo.queue(default_concurrency_limit=1)  # one job at a time: pose/flow are CPU-bound

    app = fastapi.FastAPI()

    @app.api_route("/media/{token}", methods=["GET", "HEAD"])
    def media(token: str):
        path = MEDIA.get(token)
        if path is None or not path.is_file():
            raise fastapi.HTTPException(status_code=404)
        return FileResponse(path)  # honours Range requests, so the player can seek

    return gr.mount_gradio_app(app, demo, path="/", allowed_paths=[str(OUTPUT_DIR)], css=SEGMENTED_CSS + UI_CSS,
                               js=UI_JS if LOCAL_FILES else None)


def make_server(host: str = "127.0.0.1", port: int = 7860, cleanup_file: str | Path | None = None,
                last_file: str | Path | None = None):
    """The web UI as a uvicorn server (not started yet); its output cleanup is started."""
    import uvicorn

    class Server(uvicorn.Server):
        async def shutdown(self, sockets=None) -> None:
            # Every open page keeps Gradio's heartbeat stream open, and the graceful shutdown would wait for it
            # until the page is closed or reloaded. Stop listening and drop the connections: the streams then end
            # as if the page had gone, so Ctrl+C stops the server at once.
            for server in self.servers:
                server.close()
            for connection in list(self.server_state.connections):
                connection.transport.close()
            await super().shutdown(sockets)

    app = create_app(cleanup_file, last_file)
    output_store().start_auto_cleanup()
    return Server(uvicorn.Config(app, host=host, port=port, log_level="warning",
                                 timeout_graceful_shutdown=SHUTDOWN_TIMEOUT_S))


def launch(host: str = "127.0.0.1", port: int = 7860, cleanup_file: str | Path | None = None,
           last_file: str | Path | None = None) -> None:
    try:
        make_server(host, port, cleanup_file, last_file).run()
    finally:
        _cancel.set()  # a running job's worker thread is not a daemon and would keep the process alive
        ollama_setup.stop_started()  # the Ollama started by the settings tab's one-click run
