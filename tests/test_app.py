"""The desktop app (funscript-gen app) and the folder settings of the portable build (FUNSCRIPT_GEN_HOME)."""

import os
import signal
import socket
import subprocess
import sys
import time
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


def test_picker_adds_to_the_batch_box(monkeypatch):
    from funscript_gen import webui as ui

    picked = {"video": ["v.mp4"], "videos": ["a.mp4", "b.mp4"], "folder": ["D"]}
    monkeypatch.setattr(ui, "pick_files", lambda kind: picked[kind])
    assert ui.pick_video() == ("v.mp4", None)  # into the path box, the upload cleared
    assert ui.pick_batch("videos", "a.mp4\n") == "a.mp4\nb.mp4"
    assert ui.pick_batch("folder", "") == "D"
    monkeypatch.setattr(ui, "pick_files", lambda kind: [])
    assert ui.pick_batch("videos", "x")["__type__"] == "update"  # cancelled: the box is left alone


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
        assert "或指定本機的影片" in page and "local-video" in page  # smoke-test.ps1 looks for the id
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
