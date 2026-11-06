from pathlib import Path

import gradio as gr
import pytest
from typer.testing import CliRunner

from funscript_gen import batch
from funscript_gen.batch import BatchItem, find_videos, output_paths, run_batch
from funscript_gen.export.funscript import Action, Funscript
from funscript_gen.pipeline import PipelineOptions, PipelineResult


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def _fake_generate(fail=(), calls=None):
    """generate() that makes a two-action script, and raises for videos named in `fail`."""
    def fake(video, opts, progress=None):
        if calls is not None:
            calls.append(Path(video).name)
        if progress:
            progress("scenes", 500.0)
        if Path(video).name in fail:
            raise RuntimeError("broken video")
        return PipelineResult(Funscript([Action(0, 0), Action(500, 100)]), [])
    return fake


def test_find_videos_expands_folders_by_extension_and_keeps_the_given_order(tmp_path):
    b = _touch(tmp_path / "b.mp4")
    d = tmp_path / "dir"
    _touch(d / "Z.MKV")
    _touch(d / "a.webm")
    _touch(d / "notes.txt")
    _touch(d / "sub" / "c.mp4")
    assert find_videos([b, d]) == [b, d / "a.webm", d / "Z.MKV"]
    assert find_videos([d, d / "a.webm"], recursive=True) == [d / "a.webm", d / "sub" / "c.mp4", d / "Z.MKV"]
    odd = _touch(tmp_path / "clip.bin")  # a file given by name counts whatever its extension
    assert find_videos([odd, b, odd]) == [odd, b]


def test_output_paths_beside_the_video_or_numbered_in_one_folder(tmp_path):
    videos = [tmp_path / "x" / "a.mp4", tmp_path / "y" / "a.mkv", tmp_path / "b<1>.mp4"]
    assert output_paths(videos) == [tmp_path / "x" / "a.funscript", tmp_path / "y" / "a.funscript",
                                    tmp_path / "b<1>.funscript"]
    out = tmp_path / "out"
    assert output_paths(videos, out, lambda s: s.replace("<", "_").replace(">", "_")) == [
        out / "a.funscript", out / "a (2).funscript", out / "b_1_.funscript"]


def test_run_batch_goes_on_after_a_failure_and_skips_existing_outputs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(batch, "generate", _fake_generate(fail={"bad.mp4"}, calls=calls))
    videos = [tmp_path / n for n in ("a.mp4", "bad.mp4", "c.mp4", "old.mp4")]
    _touch(tmp_path / "out" / "old.funscript")
    items = [BatchItem(v, o) for v, o in zip(videos, output_paths(videos, tmp_path / "out"))]
    seen = []
    run_batch(items, PipelineOptions(), overwrite=False, on_progress=lambda k, phase, t: seen.append((k, phase)))
    assert [i.status for i in items] == ["done", "failed", "done", "skipped"]
    assert calls == ["a.mp4", "bad.mp4", "c.mp4"] and items[1].error == "broken video"
    assert [a.pos for a in Funscript.load(items[2].output).actions] == [0, 100]
    assert seen == [(0, "scenes"), (1, "scenes"), (2, "scenes")]
    assert items[0].result.analysis is None  # only kept with keep_results


def test_run_batch_stops_between_videos_and_cancels_the_rest(tmp_path, monkeypatch):
    stop = []
    monkeypatch.setattr(batch, "generate", _fake_generate())
    items = [BatchItem(tmp_path / f"{k}.mp4", tmp_path / f"{k}.funscript") for k in range(3)]
    run_batch(items, PipelineOptions(), on_done=lambda k, item: stop.append(k), stopped=lambda: bool(stop))
    assert [i.status for i in items] == ["done", "cancelled", "cancelled"]

    def interrupted(video, opts, progress=None):  # the stop request arrives while a video runs
        stop.append("x")
        progress("scenes", 0.0)

    stop.clear()
    monkeypatch.setattr(batch, "generate", interrupted)

    def raise_when_stopped(k, phase, t):
        if stop:
            raise RuntimeError("cancelled")
    items = [BatchItem(tmp_path / f"{k}.mp4", tmp_path / f"n{k}.funscript") for k in range(2)]
    run_batch(items, PipelineOptions(), on_progress=raise_when_stopped, stopped=lambda: bool(stop))
    assert [(i.status, i.error) for i in items] == [("cancelled", ""), ("cancelled", "")]


def _cli(monkeypatch, fail=()):
    from funscript_gen import cli

    class Info:
        duration_ms = 1000.0

    calls = []
    monkeypatch.setattr(batch, "generate", _fake_generate(fail, calls))
    monkeypatch.setattr(cli, "probe", lambda video: Info())
    return cli.app, calls


def test_cli_batch_writes_beside_each_video_and_skips_done_ones(tmp_path, monkeypatch):
    app, calls = _cli(monkeypatch)
    folder = tmp_path / "videos"
    for n in ("a.mp4", "b.mkv"):
        _touch(folder / n)
    _touch(folder / "b.funscript")
    r = CliRunner().invoke(app, ["batch", str(folder), "--no-ai"])
    assert r.exit_code == 0, r.output
    assert calls == ["a.mp4"] and (folder / "a.funscript").exists() and "1 done, 1 skipped" in r.output
    r = CliRunner().invoke(app, ["batch", str(folder), "--overwrite", "-o", str(tmp_path / "out")])
    assert r.exit_code == 0, r.output
    assert calls == ["a.mp4", "a.mp4", "b.mkv"] and (tmp_path / "out" / "b.funscript").exists()


def test_cli_batch_reports_failures_with_a_nonzero_exit(tmp_path, monkeypatch):
    app, calls = _cli(monkeypatch, fail={"bad.mp4"})
    videos = [_touch(tmp_path / n) for n in ("bad.mp4", "[1080p] ok.mp4")]
    r = CliRunner().invoke(app, ["batch", *map(str, videos)])
    assert r.exit_code == 1 and calls == ["bad.mp4", "[1080p] ok.mp4"]
    assert "broken video" in r.output and (tmp_path / "[1080p] ok.funscript").exists()
    assert "[1080p] ok.funscript" in r.output.replace("\n", "")  # names are not read as markup
    assert CliRunner().invoke(app, ["batch", str(tmp_path / "missing")]).exit_code == 2
    assert CliRunner().invoke(app, ["batch", str(tmp_path), "--flip-scenes", "1"]).exit_code == 2  # per video only


def test_web_ui_batch_fills_the_table_and_opens_a_result_in_the_generate_tab(tmp_path, monkeypatch):
    from funscript_gen import webui as ui

    class Info:
        duration_ms = 1000.0

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(ui, "_cleanup_file", tmp_path / "cleanup.json")
    monkeypatch.setattr(ui, "probe", lambda path: Info())
    monkeypatch.setattr(batch, "generate", _fake_generate(fail={"bad.mp4"}))
    values = [ui.BY_NAME[n].default for n in ui.FORM_NAMES]
    files = [str(tmp_path / n) for n in ("a.mp4", "bad.mp4", "c.mp4")]
    steps = list(ui.run_batch_ui(files, "", *values, progress=lambda *a, **k: None))
    assert len(steps) == 4  # after each video, and the summary
    table, out_files, msg, jobs, pick = steps[-1]
    assert [row[2] for row in table["value"]] == ["完成", "失敗", "完成"]
    assert "broken video" in table["value"][1][-1] and "完成 2 部、失敗 1 部" in msg
    assert [Path(f).name for f in out_files] == ["a.funscript", "c.funscript"]
    assert list(jobs) == pick["choices"] == ["1. a.mp4", "3. c.mp4"]

    out = ui.open_batch_job(jobs, "3. c.mp4")
    assert out[0] == str(jobs["3. c.mp4"].out_path) and out[5] is jobs["3. c.mp4"]
    assert out[7] == files[2] and out[8] == "" and out[9].selected == "gen"
    with pytest.raises(gr.Error):
        ui.open_batch_job(jobs, None)
    with pytest.raises(gr.Error):
        list(ui.run_batch_ui([], "", *values, progress=lambda *a, **k: None))


def test_web_ui_batch_cancel_keeps_the_finished_videos(tmp_path, monkeypatch):
    from funscript_gen import webui as ui

    class Info:
        duration_ms = 1000.0

    def fake(video, opts, progress=None):
        if Path(video).name == "b.mp4":
            ui.cancel_run()  # the 取消 button, pressed during the second video
            progress("signal", 500.0)
        return PipelineResult(Funscript([Action(0, 0), Action(500, 100)]), [])

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(ui, "_cleanup_file", tmp_path / "cleanup.json")
    monkeypatch.setattr(ui, "probe", lambda path: Info())
    monkeypatch.setattr(batch, "generate", fake)
    values = [ui.BY_NAME[n].default for n in ui.FORM_NAMES]
    ui.cancel_run()  # an old press does not cancel the next batch
    steps = list(ui.run_batch_ui([str(tmp_path / n) for n in ("a.mp4", "b.mp4", "c.mp4")], "", *values,
                                 progress=lambda *a, **k: None))
    table, _, _, jobs, _ = steps[-1]
    assert [row[2] for row in table["value"]] == ["完成", "已取消", "已取消"] and list(jobs) == ["1. a.mp4"]
    demo = ui.build()
    fns = [f for f in demo.fns.values() if f.fn is not None and f.fn.__name__ == "run_batch_ui"]
    assert len(fns) == 1 and len(fns[0].inputs) == 2 + len(ui.FORM_NAMES)


def test_batch_gives_the_same_scripts_as_generate(tmp_path):
    from test_parallel import _clip

    from funscript_gen.pipeline import generate

    videos = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    _clip(videos[0], seconds=3.0)
    _clip(videos[1], seconds=3.0, cut_every_s=1.0)
    opts = PipelineOptions(use_ai=False, flow_workers=1)
    items = run_batch([BatchItem(v, o) for v, o in zip(videos, output_paths(videos))], opts)
    assert [i.status for i in items] == ["done", "done"]
    for v, item in zip(videos, items):
        assert [(a.at, a.pos) for a in Funscript.load(item.output).actions] == \
            [(a.at, a.pos) for a in generate(v, opts).funscript.actions]
