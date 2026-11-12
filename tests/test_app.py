"""The desktop app (funscript-gen app) and the folder settings of the portable build (FUNSCRIPT_GEN_HOME)."""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import gradio as gr
import pytest

from funscript_gen import paths
from funscript_gen.export.funscript import Action, Funscript
from funscript_gen.outputs import OutputStore, replaceable


def test_data_home_takes_every_file_the_program_keeps(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.HOME_ENV, raising=False)
    assert paths.settings_file(".env") == Path(".env")
    assert paths.cache_dir("ai") == Path.home() / ".cache" / "funscript-gen" / "ai"
    assert paths.webui_output_dir() == Path("out/webui").resolve()
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path))
    assert paths.settings_file(".env") == tmp_path / ".env"
    assert paths.cache_dir("ai") == tmp_path / "cache" / "ai"
    assert paths.webui_output_dir() == tmp_path / "out"


def test_library_caches_follow_the_data_home(tmp_path):
    code = "import os, funscript_gen; print(os.environ['HF_HOME'], os.environ['GRADIO_TEMP_DIR'], os.environ['MPLCONFIGDIR'])"
    env = {k: v for k, v in os.environ.items() if k not in ("HF_HOME", "GRADIO_TEMP_DIR", "MPLCONFIGDIR")}
    out = subprocess.run([sys.executable, "-c", code], env=env | {paths.HOME_ENV: str(tmp_path)},
                         capture_output=True, text=True, check=True).stdout.split()
    assert all(Path(p).is_relative_to(tmp_path.resolve()) for p in out) and len(out) == 3


def test_beside_video_setting_keeps_the_retention(tmp_path):
    store = OutputStore(tmp_path / "out", tmp_path / "cleanup.json")
    assert store.beside_video is False
    store.set_retention_days(5)
    store.set_beside_video(True)
    assert (store.retention_days, store.beside_video) == (5, True)
    store.set_retention_days(2)
    assert OutputStore(tmp_path / "out", tmp_path / "cleanup.json").beside_video is True


def test_only_scripts_funscript_gen_made_are_replaced(tmp_path):
    assert replaceable(tmp_path / "new.funscript")
    Funscript([Action(0, 0)], metadata={"creator": "funscript-gen 0.2.0"}).save(tmp_path / "ours.funscript")
    assert replaceable(tmp_path / "ours.funscript")
    Funscript([Action(0, 0)], metadata={"creator": "someone"}).save(tmp_path / "theirs.funscript")
    (tmp_path / "broken.funscript").write_text("not json")
    assert not replaceable(tmp_path / "theirs.funscript") and not replaceable(tmp_path / "broken.funscript")


def test_local_paths_only_in_the_desktop_app(tmp_path, monkeypatch):
    from funscript_gen import webui as ui

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    assert ui.local_video("") is None and ui.local_videos(" \n") == []
    with pytest.raises(gr.Error, match="不接受本機路徑"):
        ui.local_video(str(video))
    monkeypatch.setattr(ui, "LOCAL_FILES", True)
    assert ui.local_video(f'"{video}"') == video  # as Explorer's "copy as path" gives it
    with pytest.raises(gr.Error, match="找不到"):
        ui.local_video(str(tmp_path / "missing.mp4"))
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.mkv").write_bytes(b"x")
    (tmp_path / "sub" / "notes.txt").write_text("")
    assert ui.local_videos(f"{video}\n{tmp_path / 'sub'}\n{video}") == [video, tmp_path / "sub" / "a.mkv"]


def test_picker_and_drops_fill_the_boxes(tmp_path, monkeypatch):
    from funscript_gen import webui as ui

    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.mkv").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "s.funscript").write_text("{}")
    a, b, d, s = (str(tmp_path / n) for n in ("a.mp4", "b.mkv", "sub", "s.funscript"))
    picked = {"video": [a], "videos": [a, b], "folder": [d], "script": [s]}
    monkeypatch.setattr(ui, "pick_files", lambda kind: picked[kind])

    def changed(updates):  # {box: value} of what the handler's outputs change, and the message
        boxes = {k: u["value"] for k, u in zip(ui.BOXES, updates) if "value" in u}
        return boxes, updates[-1].get("value")

    assert changed(ui.choose("gen-video", "video")) == ({"gen-video": a}, None)
    assert changed(ui.choose("batch", "videos", a + "\n")) == ({"batch": f"{a}\n{b}"}, None)  # added, once
    assert changed(ui.choose("batch", "folder", "")) == ({"batch": d}, None)
    assert changed(ui.choose("gen-ref", "script")) == ({"gen-ref": s}, None)
    monkeypatch.setattr(ui, "pick_files", lambda kind: [])
    assert changed(ui.choose("batch", "videos", "x")) == ({}, None)  # cancelled: every box is left alone
    monkeypatch.setattr(ui, "pick_files", None)
    with pytest.raises(gr.Error, match="沒有檔案選擇對話框"):
        ui.choose("gen-video", "video")
    # The drops the page reports (UI_JS puts them in the hidden box), including the wrong kind of file
    drop = lambda zone, *paths, **kw: changed(ui.drop_arrived(json.dumps({"zone": zone, "paths": list(paths), "n": 1}), **kw))
    assert drop("gen-video", s, b) == ({"gen-video": b}, None)  # the video among the files
    assert drop("gen-ref", s) == ({"gen-ref": s}, None)
    assert drop("batch", d, a, s, batch_text=b) == ({"batch": f"{b}\n{d}\n{a}"}, None)  # folders and videos only
    assert ui.drop_arrived("not json") == ui.box_updates({}) and ui.drop_arrived(json.dumps({"zone": "x", "paths": []})) == ui.box_updates({})
    # Files nothing can be taken from: the note is a warning, no box changes
    (tmp_path / "t.txt").write_text("")
    shown = []
    monkeypatch.setattr(ui.gr, "Warning", shown.append)
    for zone, files in (("gen-video", [s]), ("gen-ref", [a]), ("batch", [s]), ("pv-video", [str(tmp_path / "t.txt")])):
        assert changed(ui.box_updates(*ui.dropped(zone, files))) == ({}, None)
    assert len(shown) == 4


def test_preview_brings_in_the_file_of_the_same_name(tmp_path):
    from funscript_gen import webui as ui

    for name in ("clip.mp4", "clip.funscript", "Other.MKV", "other.json", "lone.mp4", "x.funscript"):
        (tmp_path / name).write_text("")
    (tmp_path / "other.funscript").write_text("")
    f = lambda n: str(tmp_path / n)
    assert ui.sibling(tmp_path / "clip.mp4", "script") == tmp_path / "clip.funscript"
    assert ui.sibling(tmp_path / "clip.funscript", "video") == tmp_path / "clip.mp4"
    assert ui.sibling(tmp_path / "other.json", "video") == tmp_path / "Other.MKV"  # Windows names are not case-sensitive
    assert ui.sibling(tmp_path / "Other.MKV", "script") == tmp_path / "other.funscript"  # .funscript before .json
    assert ui.sibling(tmp_path / "lone.mp4", "script") is None and ui.sibling(tmp_path / "nope" / "a.mp4", "video") is None
    # a video alone: the script of the same name when asked for, nothing when not
    out, note, ok = ui.dropped("pv-video", [f("clip.mp4")], auto=True)
    assert out == {"pv-video": f("clip.mp4"), "pv-script": f("clip.funscript"), "pv-axes": ""} and "同名的 funscript「clip.funscript」" in note
    assert ui.dropped("pv-video", [f("clip.mp4")], auto=False) == ({"pv-video": f("clip.mp4")}, "", True)
    out, note, _ = ui.dropped("pv-video", [f("lone.mp4")], auto=True)  # none there: the script box is not touched
    assert out == {"pv-video": f("lone.mp4")} and "沒有同名的 funscript" in note
    # a script alone, dropped on either box: the video of the same name
    for zone in ("pv-script", "pv-video"):
        out, note, _ = ui.dropped(zone, [f("clip.funscript")], auto=True)
        assert out == {"pv-video": f("clip.mp4"), "pv-script": f("clip.funscript"), "pv-axes": ""} and "同名的影片「clip.mp4」" in note
    out, note, _ = ui.dropped("pv-script", [f("x.funscript")], auto=True)
    assert out == {"pv-script": f("x.funscript"), "pv-axes": ""} and "沒有同名的影片" in note
    assert ui.dropped("pv-script", [f("x.funscript")], auto=False)[1] == ui.t("web.pv.picked_script", script="x.funscript")
    # a pair dropped together is used as it is (the script named like the video wins), the switch changes nothing
    out, note, _ = ui.dropped("pv-video", [f("x.funscript"), f("clip.mp4"), f("clip.funscript")], auto=True)
    assert out == {"pv-video": f("clip.mp4"), "pv-script": f("clip.funscript"), "pv-axes": ""} and "已分別代入" in note
    # the reference takes a script only, and no switch applies
    assert ui.dropped("pv-ref", [f("clip.mp4"), f("x.funscript")], auto=True) == ({"pv-ref": f("x.funscript")}, "", True)
    assert ui.dropped("pv-video", [f("missing.mp4")])[2] is False  # a path that is not there
    # Enter in a box is the same as a drop of what it holds
    updates = ui.typed("pv-video", f' "{tmp_path / "clip.mp4"}" ', "", True)
    assert [u.get("value") for u in updates[:6]] == [None, None, None, f("clip.mp4"), f("clip.funscript"), None]
    assert ui.typed("pv-video", " ", "", True) == ui.box_updates({})


def test_preview_of_local_paths(tmp_path, monkeypatch):
    from test_webui import _cuts_video

    from funscript_gen import webui as ui
    from funscript_gen.export.funscript import Action, Funscript

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(ui, "LOCAL_FILES", True)
    video = _cuts_video(tmp_path / "v.mp4")
    script = tmp_path / "v.funscript"
    Funscript([Action(500, 20), Action(1000, 90)]).save(script)
    _, job, _, _, _ = ui.preview_files(f'"{video}"', str(script), "", False, 30.0)
    assert job.video == video and job.name == "v"
    with pytest.raises(gr.Error, match="找不到 funscript"):
        ui.preview_files(str(video), str(tmp_path / "gone.funscript"), "", False, 30.0)
    with pytest.raises(gr.Error, match="找不到影片"):
        ui.preview_files(str(tmp_path / "gone.mp4"), str(script), "", False, 30.0)
    with pytest.raises(gr.Error, match="funscript"):
        ui.preview_files(str(video), "", "", False, 30.0)  # no script chosen


def test_window_drops_reach_the_page(monkeypatch):
    from funscript_gen import app

    sent = []

    class Window:
        def evaluate_js(self, code):
            sent.append(code)

    on_drop = app.drop_handler(Window())
    on_drop({"dataTransfer": {"files": [{"name": "a b.mp4", "pywebviewFullPath": "D:\\v\\a b.mp4"},
                                        {"name": "x"}]}})  # a file whose path the window did not give is skipped
    assert sent == [r'window.fgDropped(["D:\\v\\a b.mp4"])']
    on_drop({"dataTransfer": {"files": [{"name": "x"}]}})
    on_drop({})
    assert len(sent) == 1  # nothing to hand over


def _form(ui):
    form = {n: ui.BY_NAME[n].default for n in ui.FORM_NAMES}
    return [(form | {"use_ai": False, "asym_audio": False, "flow_workers": 1})[n] for n in ui.FORM_NAMES]


def test_local_video_script_goes_beside_it_and_follows_flips(tmp_path, monkeypatch):
    from test_parallel import _clip

    from funscript_gen import webui as ui

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(ui, "_cleanup_file", tmp_path / "cleanup.json")
    monkeypatch.setattr(ui, "LOCAL_FILES", True)
    video = tmp_path / "videos" / "clip.mp4"
    video.parent.mkdir()
    _clip(video, seconds=3.0)
    out = ui.run(None, str(video), None, None, *_form(ui), progress=lambda *a, **k: None)
    job = out[-2]
    assert job.copy_to is None and not (tmp_path / "videos" / "clip.funscript").exists()  # off by default
    assert job.out_path.is_relative_to(tmp_path / "out") and job.video == video

    ui.output_store().set_beside_video(True)
    out = ui.run(None, str(video), None, None, *_form(ui), progress=lambda *a, **k: None)
    job, summary = out[-2], out[1]
    beside = tmp_path / "videos" / "clip.funscript"
    assert job.copy_to == beside and "同時存到影片旁邊" in summary
    assert beside.read_text() == job.out_path.read_text()
    ui.flip_scene(job, job.result.plans[0].scene.index)
    assert beside.read_text() == job.out_path.read_text()

    Funscript([Action(0, 50)], metadata={"creator": "by hand"}).save(beside)
    out = ui.run(None, str(video), None, None, *_form(ui), progress=lambda *a, **k: None)
    assert out[-2].copy_to is None and "沒有覆寫" in out[1]
    assert Funscript.load(beside).metadata["creator"] == "by hand"


def test_uploaded_videos_never_go_beside(tmp_path, monkeypatch):
    from test_parallel import _clip

    from funscript_gen import webui as ui

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(ui, "_cleanup_file", tmp_path / "cleanup.json")
    monkeypatch.setattr(ui, "LOCAL_FILES", True)
    ui.output_store().set_beside_video(True)
    _clip(tmp_path / "up.mp4", seconds=3.0)  # stands for Gradio's copy of an upload
    job = ui.run(str(tmp_path / "up.mp4"), "", None, None, *_form(ui), progress=lambda *a, **k: None)[-2]
    assert job.copy_to is None and not job.local and not (tmp_path / "up.funscript").exists()


def test_batch_of_a_local_folder_writes_beside_each_video(tmp_path, monkeypatch):
    from test_batch import _fake_generate

    from funscript_gen import batch
    from funscript_gen import webui as ui

    class Info:
        duration_ms = 1000.0

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(ui, "_cleanup_file", tmp_path / "cleanup.json")
    monkeypatch.setattr(ui, "LOCAL_FILES", True)
    monkeypatch.setattr(ui, "probe", lambda path: Info())
    monkeypatch.setattr(batch, "generate", _fake_generate())
    folder = tmp_path / "videos"
    folder.mkdir()
    for name in ("a.mp4", "b.mp4"):
        (folder / name).write_bytes(b"x")
    ui.output_store().set_beside_video(True)
    *_, (table, files, msg, jobs, _) = ui.run_batch_ui(None, str(folder), *_form(ui), progress=lambda *a, **k: None)
    assert [row[2] for row in table["value"]] == ["完成", "完成"]
    assert all(Path(f).is_relative_to(tmp_path / "out") for f in files)
    assert (folder / "a.funscript").exists() and (folder / "b.funscript").exists()
    out = ui.open_batch_job(jobs, "1. a.mp4")
    assert out[7] is None and out[8] == str(folder / "a.mp4")  # into the path box, not the upload box


@pytest.mark.skipif(sys.platform == "win32", reason="sends SIGINT")
def test_app_server_mode_serves_the_local_ui_and_stops_on_ctrl_c(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = os.environ | {paths.HOME_ENV: str(tmp_path / "data")}
    proc = subprocess.Popen([sys.executable, "-m", "funscript_gen.cli", "app", "--ui", "none", "--port", str(port)],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        assert f"http://127.0.0.1:{port}/" in proc.stdout.readline()  # printed once it accepts connections
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=30).read().decode()
        assert "把影片拖放到這裡" in page and "local-video" in page and "fg-inbox" in page  # smoke-test.ps1 looks for the id
        proc.send_signal(signal.SIGINT)
        assert proc.wait(timeout=15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert (tmp_path / "data" / "out").is_dir()  # the outputs went into the data folder


def test_the_windows_build_records_its_commit(tmp_path):
    from funscript_gen.version import build_info

    assert build_info(tmp_path) == {}
    (tmp_path / "build-info.json").write_text('{"commit": "abc123", "dirty": false, "other": 1}')
    assert build_info(tmp_path) == {"commit": "abc123", "dirty": False}


def test_the_window_opens_before_the_web_ui_is_ready(tmp_path, monkeypatch):
    import types

    from funscript_gen import app

    events = []
    release = threading.Event()

    class Window:
        def __init__(self):
            self.events = types.SimpleNamespace(loaded=types.SimpleNamespace(__iadd__=lambda self, f: self))

        def load_url(self, url):
            events.append(("load_url", url))

        def destroy(self):
            events.append(("destroy",))

    window = Window()
    fake = types.ModuleType("webview")
    fake.settings = {}
    fake.create_window = lambda title, **kw: events.append(("create_window", kw)) or window

    def start(func, **kw):
        events.append(("start", sorted(kw)))
        runner = threading.Thread(target=func)  # pywebview runs it in a thread once the window shows
        runner.start()
        events.append(("window shown, server not ready", not release.is_set()))
        release.set()
        runner.join()

    fake.start = start
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(app, "listen_for_drops", lambda w: None)
    monkeypatch.setattr(app, "file_picker", lambda w: "picker")

    def slow_start_server(port, native=False):
        assert release.wait(5), "the window must open while the server is still starting"
        return "server", threading.Thread()

    monkeypatch.setattr(app, "start_server", slow_start_server)
    startup = app.Startup(7860)
    assert app.open_window("http://127.0.0.1:7860/", startup) is True
    kinds = [e[0] for e in events]
    assert kinds == ["create_window", "start", "window shown, server not ready", "load_url"]
    shown = events[0][1]
    assert "html" in shown and "url" not in shown and "啟動中" in shown["html"]  # the loading page, not the app yet
    assert events[2][1] is True and events[3] == ("load_url", "http://127.0.0.1:7860/")
    assert sys.modules["funscript_gen.webui"].pick_files is None  # reset when the window closes

    # a server that cannot start: the window says why and closes
    events.clear()
    shown_errors = []
    monkeypatch.setattr(app, "show_error", shown_errors.append)
    monkeypatch.setattr(app, "start_server", lambda port, native=False: (_ for _ in ()).throw(OSError("port taken")))
    startup = app.Startup(7860)
    assert app.open_window("http://127.0.0.1:7860/", startup) is True
    assert ("destroy",) in events and not any(e[0] == "load_url" for e in events)
    assert shown_errors and "port taken" in shown_errors[0] and isinstance(startup.error, OSError)
    with pytest.raises(OSError):
        startup.wait()


def test_the_window_path_imports_nothing_heavy_before_the_window():
    code = ("import sys; from funscript_gen import app; app.saved_language(); app.loading_page(); app.free_port(); "
            "print([m for m in ('gradio', 'scipy', 'cv2', 'av', 'funscript_gen.webui', 'funscript_gen.pipeline') if m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"


def test_the_app_reads_the_language_the_web_ui_remembers(tmp_path, monkeypatch):
    from funscript_gen import app
    from funscript_gen import webui as ui

    assert (app.LAST_FORM_NAME, app.LANG_KEY) == (ui.DEFAULT_LAST_FILE.name, ui.LANG_KEY)  # the two must not drift apart
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path))
    assert app.saved_language() is None
    (tmp_path / app.LAST_FORM_NAME).write_text(json.dumps({app.LANG_KEY: "en"}), encoding="utf-8")
    assert app.saved_language() == "en"
    (tmp_path / app.LAST_FORM_NAME).write_text("[1]", encoding="utf-8")
    assert app.saved_language() is None


def test_app_module_takes_the_exes_arguments(monkeypatch):
    from funscript_gen import app

    seen = []
    monkeypatch.setattr(app, "run", lambda ui, port: seen.append((ui, port)))
    monkeypatch.setattr(app, "log_to_file", lambda: None)
    app.main(["--ui", "none", "--port", "17860"])
    app.main([])
    assert seen == [("none", 17860), ("window", None)]


def _script(path, actions, **extra):
    path.write_text(json.dumps({"version": "1.0", "actions": [{"at": at, "pos": pos} for at, pos in actions], **extra}))
    return path


def test_dropping_a_script_brings_in_its_axis_files(tmp_path):
    from funscript_gen import webui as ui

    for name in ("clip.mp4", "lone.funscript"):
        (tmp_path / name).write_text("")
    for name in ("clip.funscript", "clip.roll.funscript", "clip.surge.funscript", "other.funscript"):
        _script(tmp_path / name, [(0, 1)])
    f = lambda n: str(tmp_path / n)
    roll_surge = f("clip.surge.funscript") + "\n" + f("clip.roll.funscript")
    # with the switch the files of the script beside the main one are filled in (in the order of the axes)
    out, note, ok = ui.dropped("pv-script", [f("clip.funscript")], auto=True)
    assert out["pv-axes"] == roll_surge and out["pv-script"] == f("clip.funscript") and "另帶入 2 個其他軸的檔案" in note
    assert ui.dropped("pv-script", [f("clip.funscript")], auto=False)[0]["pv-axes"] == ""  # not asked: and cleared
    # a video brings its script, and the script its axes
    out, note, _ = ui.dropped("pv-video", [f("clip.mp4")], auto=True)
    assert out["pv-script"] == f("clip.funscript") and out["pv-axes"] == roll_surge
    # an axis file alone brings the main file; the files dropped together are used as they are
    out, _, _ = ui.dropped("pv-script", [f("clip.roll.funscript")], auto=True)
    assert out["pv-script"] == f("clip.funscript") and out["pv-axes"] == roll_surge
    out, _, _ = ui.dropped("pv-script", [f("clip.roll.funscript"), f("clip.funscript")], auto=False)
    assert out == {"pv-script": f("clip.funscript"), "pv-axes": f("clip.roll.funscript")}
    out, _, _ = ui.dropped("pv-script", [f("clip.funscript"), f("other.funscript"), f("clip.roll.funscript")])
    assert out["pv-script"] == f("clip.funscript") and out["pv-axes"] == f("clip.roll.funscript")  # the axes of the one chosen
    # a lone axis file with no main file beside it is still a script
    solo = _script(tmp_path / "solo.roll.funscript", [(0, 1)])
    assert ui.dropped("pv-script", [str(solo)], auto=True)[0] == {"pv-script": str(solo), "pv-axes": ""}
    # the axes box takes scripts of any name; a drop of other files is refused
    assert ui.dropped("pv-axes", [f("clip.roll.funscript"), f("clip.mp4")]) == ({"pv-axes": f("clip.roll.funscript")}, "", True)
    assert ui.dropped("pv-axes", [f("clip.mp4")])[2] is False


def test_the_tools_boxes_take_scripts_and_a_folder(tmp_path):
    from funscript_gen import webui as ui

    for name in ("v.funscript", "v.roll.funscript", "v.sway.funscript", "w.funscript"):
        _script(tmp_path / name, [(0, 1)])
    (tmp_path / "v.mp4").write_text("")
    f = lambda n: str(tmp_path / n)
    out, note, ok = ui.dropped("tool-in", [f("v.roll.funscript")], auto=True)
    assert out == {"tool-in": "\n".join(f(n) for n in ("v.roll.funscript", "v.funscript", "v.sway.funscript"))} and ok
    assert ui.dropped("tool-in", [f("v.funscript")], auto=False)[0] == {"tool-in": f("v.funscript")}
    assert ui.dropped("tool-in", [f("v.mp4")])[2] is False
    assert ui.dropped("tool-out", [str(tmp_path)]) == ({"tool-out": str(tmp_path)}, "", True)
    assert ui.dropped("tool-out", [f("v.funscript")])[2] is False  # a file is not a folder
    # the switch of the 工具 tab decides for its boxes, the 預覽 tab's for its own
    drop = lambda **flags: ui.drop_arrived(json.dumps({"zone": "tool-in", "paths": [f("v.funscript")], "n": 1}), "", **flags)
    boxes = lambda updates: dict(zip(ui.BOXES, updates))
    assert boxes(drop(auto=True, tool_auto=False))["tool-in"]["value"] == f("v.funscript")
    assert boxes(drop(auto=False, tool_auto=True))["tool-in"]["value"].count("\n") == 2


def test_preview_of_a_multi_axis_script_with_local_paths(tmp_path, monkeypatch):
    from test_webui import _cuts_video

    from funscript_gen import webui as ui

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(ui, "LOCAL_FILES", True)
    video = _cuts_video(tmp_path / "v.mp4")
    main = _script(tmp_path / "v.funscript", [(500, 20), (1000, 90)])
    roll = _script(tmp_path / "v.roll.funscript", [(0, 5), (1000, 50)])
    player, job, _, msg, _ = ui.preview_files(str(video), str(main), "", False, 30.0, str(roll))
    assert list(job.axes) == ["R1"] and "R1" in msg and "多軸腳本" in msg
    assert "(Roll)" in player  # the strip's label is in the player's data
    assert job.name == "v" and [a.pos for a in job.script.actions] == [20, 90]  # editing and flips work on L0
    # the same through the script box alone (several files, as the web server's upload gives them)
    monkeypatch.setattr(ui, "LOCAL_FILES", False)
    _, job, _, _, _ = ui.preview_files([str(video)], [str(roll), str(main)], None, False, 30.0)
    assert list(job.axes) == ["R1"] and job.name == "v"
    # a one-file multi-axis script shows its own axes
    merged = _script(tmp_path / "m.funscript", [(0, 1), (900, 9)], axes=[{"id": "L2", "actions": [{"at": 0, "pos": 4}]}])
    _, job, _, _, _ = ui.preview_files([str(video)], str(merged), None, False, 30.0)
    assert list(job.axes) == ["L2"]
    # the flip keeps the axes in the player
    player, *_ = ui.preview_flip(job, 100.0, False, "")
    assert "(Surge)" not in player and "(Sway)" in player
    # axis files with no main file cannot be previewed; a single axis file is a script as it is
    _script(tmp_path / "v.sway.funscript", [(0, 1)])
    with pytest.raises(gr.Error, match="主軸"):
        ui.preview_files([str(video)], [str(roll), str(tmp_path / "v.sway.funscript")], None, False, 30.0)
    _, job, _, _, _ = ui.preview_files([str(video)], str(roll), None, False, 30.0)
    assert job.axes == {} and job.name == "v.roll"
    with pytest.raises(gr.Error, match="找不到 funscript"):
        monkeypatch.setattr(ui, "LOCAL_FILES", True)
        ui.preview_files(str(video), str(main), "", False, 30.0, str(tmp_path / "gone.roll.funscript"))
