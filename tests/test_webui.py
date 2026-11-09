import signal
import socket
import subprocess
import sys
import time

import gradio as gr
import pytest

from funscript_gen.webui import output_stem


def test_output_stem_keeps_original_name():
    assert output_stem("My Video (2024) [1080p]") == "My Video (2024) [1080p]"
    assert output_stem("中文 影片") == "中文 影片"


def test_output_stem_replaces_only_invalid_characters():
    assert output_stem('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
    assert output_stem("tab\there") == "tab_here"
    assert output_stem(" . ") == "video"


# An output with characters that need escaping in HTML (Windows does not allow < and > in file names).
OUTPUT_NAME = "My Video & [1].funscript" if sys.platform == "win32" else "My Video & <1>.funscript"


def _outputs(tmp_path, monkeypatch, ages):
    import os
    import time

    from funscript_gen import webui as ui

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(ui, "_cleanup_file", tmp_path / "cleanup.json")
    for name, age in ages:
        d = tmp_path / "out" / name
        d.mkdir(parents=True)
        (d / OUTPUT_NAME).write_text("{}")
        os.utime(d, (time.time() - age * 86400,) * 2)
    return ui


def test_delete_outputs_from_ui(tmp_path, monkeypatch):
    import gradio as gr
    import pytest

    ui = _outputs(tmp_path, monkeypatch, [("20260101-000000", 30), ("20261028-000000", 0)])
    with pytest.raises(gr.Error):
        ui.delete_expired(0)  # 0 days = keep forever, so there is nothing "expired"
    msg, status, _, listing = ui.save_retention(7)
    assert "1 個過期" in msg and "**1** 次" in status and "7" in status
    assert "20261028-000000" in listing and "20260101-000000" not in listing
    msg, status, _, listing, row = ui.clear_outputs()
    assert "1 個輸出" in msg and "**0** 次" in status and "沒有輸出" in listing and row["visible"] is False


def test_output_list_links_download_through_gradio(tmp_path, monkeypatch):
    import html
    import re

    from fastapi.testclient import TestClient

    ui = _outputs(tmp_path, monkeypatch, [("20261028-120000", 0)])
    listing = ui.output_list_html()
    assert html.escape(OUTPUT_NAME) in listing and OUTPUT_NAME not in listing  # escaped: a name cannot inject HTML
    url = html.unescape(re.search(r'href="([^"]+)"', listing).group(1))

    client = TestClient(ui.create_app(cleanup_file=tmp_path / "cleanup.json"))
    r = client.get("/" + url)
    assert r.status_code == 200 and r.text == "{}"
    assert client.get("/gradio_api/file=/etc/passwd").status_code == 403
    assert client.get("/config").status_code == 200  # single-user: no login


def test_last_form_round_trip(tmp_path, monkeypatch):
    from funscript_gen import webui as ui

    monkeypatch.setattr(ui, "_last_file", tmp_path / "last.json")
    assert ui.load_last_form() == {}
    ui.save_last_form({"mode": "pose", "gain": 0.8, "roi": "中文"})
    assert ui.load_last_form() == {"mode": "pose", "gain": 0.8, "roi": "中文"}
    (tmp_path / "last.json").write_text("not json")
    assert ui.load_last_form() == {}


def test_restore_form_skips_values_that_no_longer_fit():
    import gradio as gr

    from funscript_gen import webui as ui
    from funscript_gen.options import BY_NAME

    with gr.Blocks():
        form = dict(mode=gr.Radio(list(BY_NAME["mode"].choices), value="auto"),
                    axis=gr.Dropdown(list(BY_NAME["axis"].choices), value=""),
                    gain=gr.Slider(0.3, 3.0, value=1.0), invert=gr.Checkbox(value=False), roi=gr.Textbox())
    saved = {"mode": "removed-mode", "axis": "depth", "gain": 9.0, "invert": True, "roi": "0.1,0.1,0.9,0.9"}
    updates = dict(zip(form, ui.restore_form(form, saved)))
    assert "value" not in updates["mode"] and "value" not in updates["gain"]
    assert updates["axis"]["value"] == "depth" and updates["invert"]["value"] is True
    assert updates["roi"]["value"] == "0.1,0.1,0.9,0.9"
    assert "value" not in ui.restore_form(form, {})[0]


def test_generate_click_remembers_settings(tmp_path, monkeypatch):
    from funscript_gen import webui as ui

    monkeypatch.setattr(ui, "_last_file", tmp_path / "last.json")
    demo = ui.build()
    fns = {f.fn.__name__: f for f in demo.fns.values() if f.fn is not None}
    remember = fns["remember"]
    values = [c.value for c in remember.inputs]
    values[[c.label for c in remember.inputs].index("計算方式")] = "pose"
    remember.fn(*values)
    saved = ui.load_last_form()
    assert saved["mode"] == "pose" and saved["fps"] == 30 and len(saved) == len(remember.inputs)
    assert saved["asym_audio"] is True and saved["asym_audio_threshold"] == 0.2  # same defaults as the CLI
    assert "video" not in saved and "reference" not in saved  # uploads are never remembered
    import inspect

    params = list(inspect.signature(ui.run).parameters)[4:-1]
    assert list(saved) == params == ui.FORM_NAMES

    run = fns["run"]
    assert [c._id for c in run.inputs[4:]] == [c._id for c in remember.inputs]  # same order as run()'s parameters
    *_, msg = fns["reset_form"].fn()
    assert "預設" in msg and set(ui.load_last_form()) == {"compute", "flow_compute", "part_compute", "pose_compute"}


def test_compute_settings_live_in_the_settings_tab(tmp_path, monkeypatch):
    """運算裝置 is on the 設定 tab: still sent with the 產生 form, remembered when changed, kept by presets and resets."""
    from funscript_gen import webui as ui

    monkeypatch.setattr(ui, "_last_file", tmp_path / "last.json")
    demo = ui.build()
    fns = {f.fn.__name__: f for f in demo.fns.values() if f.fn is not None}
    names = [c.label for c in fns["run"].inputs[4:]]
    assert names[ui.FORM_NAMES.index("flow_compute")] == "光流"
    settings_tab = next(c for c in demo.blocks.values() if isinstance(c, gr.Tab) and c.label == "設定")
    inside = {id(b) for b in _descendants(settings_tab)}
    run_inputs = dict(zip(ui.FORM_NAMES, fns["run"].inputs[4:]))
    assert all(id(run_inputs[n]) in inside for n in ("compute", "flow_compute", "part_compute", "pose_compute"))
    assert id(run_inputs["fps"]) not in inside
    saved = [f for f in demo.fns.values() if f.fn is not None and f.fn.__name__ == "<lambda>"
             and [c._id for c in f.inputs] == [run_inputs["part_compute"]._id]]
    saved[0].fn("cpu")
    assert ui.load_last_form() == {"part_compute": "cpu"}
    preset = fns["apply_preset"]
    assert run_inputs["part_compute"]._id not in [c._id for c in preset.outputs]
    fns["reset_form"].fn()
    assert ui.load_last_form() == {"part_compute": "cpu"}


def _descendants(block):
    for child in getattr(block, "children", []):
        yield child
        yield from _descendants(child)


def test_shape_switches_show_their_sliders():
    from funscript_gen import webui as ui

    demo = ui.build()
    labels = {"保留轉折處的停頓", "長行程補點", "停頓時保持原位", "依行程快慢判斷方向"}
    for f in demo.fns.values():
        if f.inputs and getattr(f.inputs[0], "label", None) in labels:
            assert f.outputs[0].visible is bool(f.inputs[0].value)  # shown from the start when the switch is on
            assert f.fn(True)["visible"] is True and f.fn(False)["visible"] is False
            labels.remove(f.inputs[0].label)
    assert not labels


def _job(tmp_path):
    import numpy as np

    from funscript_gen import webui as ui
    from funscript_gen.export.funscript import Action, Funscript
    from funscript_gen.pipeline import PipelineOptions, PipelineResult, ScenePlan, finalize
    from funscript_gen.signal.process import ProcessedSignal
    from funscript_gen.video.scenes import Scene

    plans = []
    for k in range(3):
        acts = [] if k == 2 else [Action(k * 1000 + 100, 0), Action(k * 1000 + 500, 100)]
        z = np.zeros(1)
        plans.append(ScenePlan(Scene(k, k * 1000.0, (k + 1) * 1000.0),
                               signal=ProcessedSignal(z, z, z, z, z, z > -1, acts)))
    opts = PipelineOptions()
    opts.signal.max_speed = 1e9
    result = PipelineResult(Funscript(finalize(plans, opts), metadata={"notes": "flipped=[]"}), plans)
    return ui.Job(tmp_path / "clip.mp4", result, opts, tmp_path / "clip.funscript", None, ["3 個鏡頭"])


def test_flip_scene_rewrites_the_output_and_undoes(tmp_path):
    from funscript_gen import webui as ui
    from funscript_gen.export.funscript import Funscript

    job = _job(tmp_path)
    out = ui.flip_scene(job, 1)
    saved = Funscript.load(job.out_path)
    assert [a.pos for a in saved.actions] == [0, 100, 100, 0]
    assert "--flip-scenes 1" in out[1] and "已反轉鏡頭 1" in out[-1]
    assert "&quot;i&quot;:1,&quot;flipped&quot;:true" in out[4]  # the player marks the flipped scene
    ui.flip_scene(job, 1)
    assert [a.pos for a in Funscript.load(job.out_path).actions] == [0, 100, 0, 100] and not job.manual
    with pytest.raises(gr.Error):
        ui.flip_scene(job, 2)  # no actions


def test_table_click_flips_only_from_the_flip_column(tmp_path):
    from funscript_gen import webui as ui
    from funscript_gen.report import FLIP_COLUMN, SCENE_COLUMNS

    job = _job(tmp_path)
    col = SCENE_COLUMNS.index(FLIP_COLUMN)
    other = gr.SelectData(None, {"index": [0, 1], "value": 0.0, "row_value": [0], "col_value": [], "selected": True})
    assert ui.flip_from_table(job, 0.0, False, "", other) == (gr.update(),) * 6 and not job.manual
    click = gr.SelectData(None, {"index": [0, col], "value": "⇅", "row_value": [0], "col_value": [], "selected": True})
    out = ui.flip_from_table(job, 1500.0, True, "", click)
    assert job.manual == {0} and job.result.plans[0].flipped
    assert "&quot;start_ms&quot;:1500.0" in out[4] and "&quot;play&quot;:true" in out[4]  # the player stays put


def test_table_click_keeps_unsaved_edits(tmp_path):
    from funscript_gen import webui as ui
    from funscript_gen.export.funscript import Funscript
    from funscript_gen.report import FLIP_COLUMN, SCENE_COLUMNS

    job = _job(tmp_path)
    click = gr.SelectData(None, {"index": [1, SCENE_COLUMNS.index(FLIP_COLUMN)], "value": "⇅", "row_value": [1],
                                 "col_value": [], "selected": True})
    ui.flip_from_table(job, -1, False, "[[100, 0], [300, 70], [500, 100], [1100, 20], [1500, 80]]", click)
    assert [(a.at, a.pos) for a in Funscript.load(job.out_path).actions] == [(100, 0), (300, 70), (500, 100),
                                                                            (1100, 80), (1500, 20)]
    assert job.edited and job.manual == {1}


def test_flip_button_flips_the_scene_under_the_cursor(tmp_path):
    from funscript_gen import webui as ui

    job = _job(tmp_path)
    ui.flip_at_time(job, 1500.0, False)
    assert job.manual == {1}
    with pytest.raises(gr.Error):
        ui.flip_at_time(job, -1, False)  # the page could not read the player
    assert ui.scene_at([0.0, 1000.0, 2000.0], 999.0) == 0 and ui.scene_at([0.0, 1000.0], 5000.0) == 1


def test_preview_tab_flip_mirrors_within_the_scripts_range(tmp_path, monkeypatch):
    from funscript_gen import webui as ui
    from funscript_gen.export.funscript import Action, Funscript

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path)
    script = Funscript([Action(100, 20), Action(500, 90), Action(1100, 20), Action(1500, 90)])
    job = ui.PreviewJob(tmp_path / "v.mp4", script, None, [0.0, 1000.0], [1000.0, 2000.0], 20, 90, "v")
    player, job, path, msg, table = ui.preview_flip(job, 1200.0, True)
    assert [a.pos for a in Funscript.load(path).actions] == [20, 90, 90, 20] and "鏡頭 1" in msg
    assert '&quot;play&quot;:true' in player and '&quot;start_ms&quot;:1200.0' in player
    ui.preview_flip(job, 1200.0, False)
    assert [a.pos for a in Funscript.load(path).actions] == [20, 90, 20, 90] and not job.flipped


def test_flip_buttons_read_the_player_time():
    from funscript_gen import webui as ui

    demo = ui.build()
    js = {f.fn.__name__: f.js for f in demo.fns.values() if f.fn is not None and f.js}
    assert "#gen-player iframe" in js["flip_at_time"] and "#pv-player iframe" in js["preview_flip"]
    assert "getEdits" in js["save_edits"] and "#pv-player iframe" in js["preview_save"]
    assert "getEdits" in js["flip_from_table"] and "#gen-player iframe" in js["flip_from_table"]
    assert "#pv-player iframe" in js["preview_flip_row"] and "#pv-player iframe" in js["preview_rescene"]


def _cuts_video(path):
    """2 s dark, a strong cut to bright for 2 s, a weak cut to a slightly darker grey for 2 s (10 fps)."""
    import cv2
    import numpy as np

    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
    for i in range(60):
        w.write(np.full((64, 64, 3), 20 if i < 20 else 230 if i < 40 else 200, np.uint8))
    w.release()
    return path


def test_preview_tab_lists_the_scenes_and_splits_again_without_decoding(tmp_path, monkeypatch):
    from funscript_gen import webui as ui
    from funscript_gen.export.funscript import Action, Funscript

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path)
    video = _cuts_video(tmp_path / "v.mp4")
    script = tmp_path / "v.funscript"
    Funscript([Action(t, 10 if k % 2 else 90) for k, t in enumerate(range(100, 6000, 500))]).save(script)
    player, job, out, msg, table = ui.preview_files(str(video), str(script), None, False, 30.0)
    rows = table["value"]
    assert table["headers"] == ui.preview_headers() and len(rows) == 2 and len(job.starts) == 2
    assert rows[1][1] == 2.0 and rows[1][4] > 30.0 and rows[1][5] == 8 and rows[1][6] == "⇅"
    assert "偵測到 **2** 個鏡頭" in msg
    monkeypatch.setattr(ui, "frame_diffs", lambda *a, **k: pytest.fail("decoded again"))
    player, job, out, msg, table = ui.preview_rescene(job, 5.0, 4500.0, True, "")
    assert len(job.starts) == 3 and "偵測到 **3** 個鏡頭" in msg and "切換強度接近門檻" not in str(table["value"])
    assert "&quot;start_ms&quot;:4500.0" in player
    weak = table["value"][2][4]
    _, job, _, _, table = ui.preview_rescene(job, weak / 1.1, 0.0, False, "")
    assert "切換強度接近門檻" in table["value"][2][7]


def test_preview_video_box_splits_files_picked_together(tmp_path):
    from funscript_gen import webui as ui

    video, other, script = (str(tmp_path / n) for n in ("a b.mp4", "c.funscript", "a b.funscript"))
    v, s, msg = ui.preview_video_uploaded([other, video, script])
    assert v["value"] == [video] and s["value"] == [script] and "已分別代入" in msg  # the same-name script
    assert ui.preview_video_uploaded([video]) == (gr.update(),) * 3  # a video alone, as before
    v, s, msg = ui.preview_video_uploaded([other])  # only a script: it moves to its own box
    assert v["value"] is None and s["value"] == [other] and "funscript 欄" in msg
    v, s, msg = ui.preview_video_uploaded([video, str(tmp_path / "d.mp4")])
    assert v["value"] == [video] and s == gr.update() and "一次只能預覽一部影片" in msg
    # the axis files of a multi-axis script go along, the main script first
    roll, surge = str(tmp_path / "a b.roll.funscript"), str(tmp_path / "a b.surge.funscript")
    v, s, msg = ui.preview_video_uploaded([roll, video, surge, script])
    assert v["value"] == [video] and s["value"] == [script, surge, roll] and "另有 2 個其他軸的檔案" in msg


def test_preview_without_scene_cuts_and_cancel(tmp_path, monkeypatch):
    from funscript_gen import webui as ui
    from funscript_gen.export.funscript import Action, Funscript

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path)
    video = _cuts_video(tmp_path / "v.mp4")
    script = tmp_path / "v.funscript"
    Funscript([Action(500, 20), Action(1000, 90)]).save(script)
    monkeypatch.setattr(ui, "frame_diffs", lambda *a, **k: pytest.fail("decoded"))
    _, job, _, _, table = ui.preview_files_whole([str(video)], str(script), None, False, 30.0)
    assert len(job.starts) == 1 and job.diffs is None and len(table["value"]) == 1
    assert ui.preview_rescene(job, 5.0, 0.0, False, "")[3] == ui.t("web.pv.no_scenes_hint")
    monkeypatch.undo()
    ui.preview_cancel()
    orig = ui.frame_diffs
    def cancelling(path, on_frame=None, **k):
        ui.preview_cancel()
        return orig(path, on_frame=on_frame, **k)
    monkeypatch.setattr(ui, "frame_diffs", cancelling)
    out = ui.preview_files([str(video)], str(script), None, False, 30.0)
    assert out[1] is None and out[3] == ui.t("web.pv.cancelled")

def test_preview_tab_split_keeps_flips_and_saves_unsaved_edits(tmp_path, monkeypatch):
    from funscript_gen import webui as ui
    from funscript_gen.export.funscript import Action, Funscript
    from funscript_gen.report import FLIP_COLUMN

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path)
    video = _cuts_video(tmp_path / "v.mp4")
    script = tmp_path / "v.funscript"
    Funscript([Action(500, 20), Action(1000, 90), Action(2500, 20), Action(3000, 90)]).save(script)
    _, job, _, _, _ = ui.preview_files([str(video)], str(script), None, False, 30.0)
    col = ui.PREVIEW_COLUMNS.index(FLIP_COLUMN)
    click = gr.SelectData(None, {"index": [1, col], "value": "⇅", "row_value": [1], "col_value": [], "selected": True})
    _, job, path, msg, table = ui.preview_flip_row(job, 700.0, False, "", click)
    assert [a.pos for a in Funscript.load(path).actions] == [20, 90, 90, 20] and table["value"][1][6] == "⇅ 已反轉"
    other = gr.SelectData(None, {"index": [1, 0], "value": 1, "row_value": [1], "col_value": [], "selected": True})
    assert ui.preview_flip_row(job, 700.0, False, "", other) == (gr.update(),) * 5
    _, job, path, msg, _ = ui.preview_rescene(job, 5.0, 0.0, False, "[[500, 20], [1000, 90], [2500, 90], [3000, 0]]")
    assert [a.pos for a in Funscript.load(path).actions] == [20, 90, 90, 0] and "已先儲存未儲存的編輯" in msg
    assert not job.flipped  # the numbers changed; the flip stays in the script
    assert ui.preview_rescene(None, 30.0, 0.0, False, "")[3].startswith("載入預覽後")


def test_parse_edits_sorts_clamps_and_keeps_one_action_per_time():
    from funscript_gen import webui as ui

    assert ui.parse_edits("") is None and ui.parse_edits(None) is None  # nothing edited
    acts = ui.parse_edits("[[500, 120], [100.4, 30], [100, 40], [-5, 10], [300, -3]]")
    assert [(a.at, a.pos) for a in acts] == [(100, 40), (300, 0), (500, 100)]
    with pytest.raises(gr.Error):
        ui.parse_edits("[[1]]")


def test_saved_edits_go_to_the_output_and_survive_a_flip(tmp_path):
    from funscript_gen import webui as ui
    from funscript_gen.export.funscript import Funscript

    job = _job(tmp_path)
    assert ui.save_edits(job, 0.0, False, "")[-1] == "沒有未儲存的編輯"
    out = ui.save_edits(job, 0.0, False, "[[100, 10], [300, 60], [500, 90], [1100, 0], [1500, 100]]")
    saved = Funscript.load(job.out_path)
    assert [(a.at, a.pos) for a in saved.actions] == [(100, 10), (300, 60), (500, 90), (1100, 0), (1500, 100)]
    assert saved.metadata["funscript_gen"]["hand_edited"] is True and "hand_edited" in out[1]
    ui.flip_scene(job, 0)  # mirrors the edited script; rebuilding from the scenes would drop the added point
    assert [(a.at, a.pos) for a in Funscript.load(job.out_path).actions] == [(100, 90), (300, 40), (500, 10),
                                                                            (1100, 0), (1500, 100)]
    assert "flipped=[0]" in Funscript.load(job.out_path).metadata["notes"]
    ui.flip_at_time(job, 1200.0, False, "[[100, 90], [1100, 0], [1500, 100]]")  # unsaved edits are kept first
    assert [(a.at, a.pos) for a in Funscript.load(job.out_path).actions] == [(100, 90), (1100, 100), (1500, 0)]


def test_preview_tab_saves_edits(tmp_path, monkeypatch):
    from funscript_gen import webui as ui
    from funscript_gen.export.funscript import Action, Funscript

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path)
    script = Funscript([Action(100, 20), Action(500, 90)])
    job = ui.PreviewJob(tmp_path / "v.mp4", script, None, [0.0], [2000.0], 20, 90, "v")
    assert ui.preview_save(job, 0.0, False, "")[3] == "沒有未儲存的編輯"
    player, job, path, msg, table = ui.preview_save(job, 300.0, False, "[[100, 20], [300, 50], [500, 90]]")
    assert [a.pos for a in Funscript.load(path).actions] == [20, 50, 90] and "3 個動作點" in msg
    assert '&quot;start_ms&quot;:300.0' in player


def test_summary_lists_scenes_that_may_be_inverted_until_flipped(tmp_path):
    from funscript_gen import webui as ui

    job = _job(tmp_path)
    job.result.plans[1].asym_hint = True  # the asymmetry check flagged it, --asym-sign was off
    _, summary, _, _, player = ui.job_outputs(job)
    assert "鏡頭 1 可能高低相反" in summary
    assert '&quot;i&quot;:1,&quot;flipped&quot;:false,&quot;check&quot;:true' in player  # shaded in the preview
    _, summary, _, _, player = ui.flip_scene(job, 1)[:5]  # flipped by hand: no longer listed
    assert "可能高低相反" not in summary and "&quot;check&quot;:true" not in player
    job.result.plans[0].sign_doubt = "聲音起點在高點"  # kept, but the sound says otherwise
    assert "鏡頭 0 可能高低相反" in ui.job_outputs(job)[1]


def test_cancel_stops_the_running_job(tmp_path, monkeypatch):
    import inspect

    import gradio as gr
    import pytest

    from funscript_gen import webui as ui

    class Info:
        duration_ms = 10000.0

    seen = []

    def fake_generate(video, opts, progress):
        progress("scenes", 1000.0)
        seen.append("scenes")
        ui.cancel_run()  # the 取消 button, pressed while the job runs
        progress("signal", 2000.0)
        seen.append("signal")

    monkeypatch.setattr(ui, "probe", lambda path: Info())
    monkeypatch.setattr(ui, "generate", fake_generate)
    demo = ui.build()
    run = next(f for f in demo.fns.values() if f.fn is not None and f.fn.__name__ == "run")
    values = [c.value for c in run.inputs[4:]]
    names = list(inspect.signature(ui.run).parameters)[4:-1]
    assert len(values) == len(names)
    ui.cancel_run()  # an old press does not cancel the next job
    with pytest.raises(gr.Error, match="已取消"):
        ui.run(str(tmp_path / "v.mp4"), "", None, None, *values, progress=lambda *a, **k: None)
    assert seen == ["scenes"]
    cancel = next(f for f in demo.fns.values() if f.fn is not None and f.fn.__name__ == "cancel_run")
    assert cancel.queue is False  # runs while the job holds the queue


def test_generating_again_with_new_output_settings_reuses_the_analysis(tmp_path, monkeypatch):
    from test_parallel import _clip

    from funscript_gen import webui as ui
    from funscript_gen.export.funscript import Funscript

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(ui, "_cleanup_file", tmp_path / "cleanup.json")
    _clip(tmp_path / "c.mp4", seconds=3.0)
    form = {n: c for n, c in zip(ui.FORM_NAMES, [ui.BY_NAME[n].default for n in ui.FORM_NAMES])}
    form |= {"use_ai": False, "asym_audio": False, "flow_workers": 1}
    calls = []
    real = ui.generate
    monkeypatch.setattr(ui, "generate", lambda *a, **k: calls.append(1) or real(*a, **k))

    def press(previous, **changes):
        values = [(form | changes)[n] for n in ui.FORM_NAMES]
        out = ui.run(str(tmp_path / "c.mp4"), "", None, previous, *values, progress=lambda *a, **k: None)
        return out[-2], out[1]  # the job, the summary

    first, _ = press(None)
    again, summary = press(first, dwell=True, curve=True)  # output settings only
    assert len(calls) == 1 and "沿用上次的分析" in summary and again.result.analysis is first.result.analysis
    fresh = real(tmp_path / "c.mp4", again.opts)  # the same as analysing again
    assert [(a.at, a.pos) for a in Funscript.load(again.out_path).actions] == \
        [(a.at, a.pos) for a in fresh.funscript.actions]
    press(again, flow_width=320)  # an analysis setting: analysed again
    assert len(calls) == 2


@pytest.mark.skipif(sys.platform == "win32", reason="sends SIGINT")
def test_ctrl_c_stops_the_server_while_a_page_is_open(tmp_path):
    # An open page holds Gradio's heartbeat stream open, so uvicorn's graceful shutdown waited on it forever.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    code = ("import sys; from funscript_gen import webui as ui; ui.OUTPUT_DIR = __import__('pathlib').Path(sys.argv[1]);"
            "ui.launch('127.0.0.1', int(sys.argv[2]), sys.argv[1] + '/c.json', sys.argv[1] + '/l.json')")
    proc = subprocess.Popen([sys.executable, "-c", code, str(tmp_path), str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                page = socket.create_connection(("127.0.0.1", port))
                break
            except OSError:
                assert proc.poll() is None and time.monotonic() < deadline, "server did not start"
                time.sleep(0.2)
        with page:
            page.sendall(f"GET /gradio_api/heartbeat/test HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
            assert page.recv(1024).startswith(b"HTTP/1.1 200")
            proc.send_signal(signal.SIGINT)
            assert proc.wait(timeout=10) is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_backend_choice_in_the_settings_tab(monkeypatch):
    from funscript_gen import webui as ui
    from funscript_gen.config import Settings

    monkeypatch.setattr(ui, "_settings", Settings(_env_file=None, vllm_api_key="secret"))
    s = ui._settings_from_form("http://h:11434", "", "qwen3-vl:8b", "", 2, "ollama", 16384)
    assert (s.vllm_backend, s.vllm_num_ctx, s.vllm_api_key) == ("ollama", 16384, "secret")
    assert ui._settings_from_form("http://h:8000/v1", "", "m", "").vllm_backend == "openai"  # unchanged
    url, num_ctx, box = ui.backend_changed("ollama", "http://127.0.0.1:8000/v1")
    assert url["value"] == "http://127.0.0.1:11434" and num_ctx["visible"] is True and box["visible"] is True
    url, num_ctx, box = ui.backend_changed("openai", "http://gpu:11434")  # a URL the user typed is kept
    assert url["value"] == "http://gpu:11434" and num_ctx["visible"] is False and box["visible"] is False


def test_one_click_ollama_applies_and_saves_the_settings(monkeypatch, tmp_path):
    from funscript_gen import config
    from funscript_gen import ollama_setup as osu
    from funscript_gen import webui as ui
    from funscript_gen.config import Settings

    monkeypatch.setattr(ui, "_settings", Settings(_env_file=None, vllm_api_key="old"))
    saved = {}
    monkeypatch.setattr(config, "save_env", lambda s, path=None: saved.setdefault("s", s))
    monkeypatch.setattr(osu, "setup", lambda mode, model: iter(["step 1", "step 2"]))
    out = list(ui.run_ollama("native", " qwen3-vl:4b-instruct ", 4))
    assert [o[0] for o in out[:2]] == ["step 1", "step 2"]
    done = out[-1]
    assert done[1]["value"] == osu.LOCAL_URL and done[2]["value"] == "qwen3-vl:4b-instruct" and done[4]["value"] == "ollama"
    s = saved["s"]
    assert (s.vllm_backend, s.vllm_base_url, s.vllm_model, s.vllm_api_key, s.vllm_concurrency) == (
        "ollama", osu.LOCAL_URL, "qwen3-vl:4b-instruct", "old", 4)  # the key is kept
    assert ui._settings is s


def test_one_click_ollama_failure_leaves_the_settings(monkeypatch):
    from funscript_gen import ollama_setup as osu
    from funscript_gen import webui as ui
    from funscript_gen.config import Settings

    before = Settings(_env_file=None)
    monkeypatch.setattr(ui, "_settings", before)

    def boom(mode, model):
        yield "step"
        raise osu.SetupError("no docker")

    monkeypatch.setattr(osu, "setup", boom)
    out = list(ui.run_ollama("docker", "m"))
    assert out[-1][0].startswith("❌") and "no docker" in out[-1][0] and ui._settings is before


def _axis_script(path, actions, **extra):
    import json

    path.write_text(json.dumps({"version": "1.0", "range": 100, "actions": [{"at": a, "pos": p} for a, p in actions], **extra}))
    return str(path)


def test_tools_tab_recognizes_the_files_and_merges_for_download(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from funscript_gen import webui as ui

    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path / "out")
    files = [_axis_script(tmp_path / "v.funscript", [(0, 1), (500, 90)]), _axis_script(tmp_path / "v.roll.funscript", [(0, 5)])]
    plan, msg, table, viewer, merge_btn, split_btn = ui.tool_inspect(files)
    assert plan.kind == "merge" and "多檔多軸" in msg and merge_btn["visible"] and not split_btn["visible"]
    assert table["headers"] == ui.tool_headers() and [r[:2] for r in table["value"]] == [["v", "L0"], ["v", "R1"]]
    assert table["value"][0][3:] == [2, 0.5] and "<iframe" in viewer and "(Roll)" in viewer
    result, written = ui.tool_run(plan)  # the web server has no original place: its output folder
    assert len(written) == 1 and written[0].startswith(str(tmp_path / "out")) and "已合併" in result
    assert [a["id"] for a in json.loads(open(written[0], encoding="utf-8").read())["axes"]] == ["R1"]
    # and the result splits again
    plan, msg, table, viewer, merge_btn, split_btn = ui.tool_inspect(written)
    assert plan.kind == "split" and "一檔多軸" in msg and split_btn["visible"] and not merge_btn["visible"]
    result, written = ui.tool_run(plan)
    assert [Path(p).name for p in written] == ["v.funscript", "v.roll.funscript"] and "已分割" in result


def test_tools_tab_messages_and_nothing_to_do(tmp_path):
    from funscript_gen import webui as ui

    assert ui.tool_inspect(None)[:2] == (None, "") and ui.tool_inspect([])[0] is None
    one = _axis_script(tmp_path / "a.funscript", [(0, 1)])
    plan, msg, table, viewer, merge_btn, split_btn = ui.tool_inspect([one])
    assert plan.kind == "single" and "只有一個軸" in msg and viewer == "" and not merge_btn["visible"] and not split_btn["visible"]
    with pytest.raises(gr.Error, match="沒有可以處理"):
        ui.tool_run(plan)
    with pytest.raises(gr.Error, match="沒有可以處理"):
        ui.tool_run(None)
    bad = tmp_path / "b.funscript"
    bad.write_text("{nope")
    plan, msg, *_ = ui.tool_inspect([str(bad), str(tmp_path / "gone.funscript"), _axis_script(tmp_path / "c.roll.funscript", [])])
    assert plan.kind == "none" and "無法讀取「b.funscript」" in msg and "找不到" in msg and "c.funscript" in msg


def test_tools_tab_writes_beside_the_originals_or_elsewhere(tmp_path, monkeypatch):
    import json

    from funscript_gen import webui as ui

    monkeypatch.setattr(ui, "LOCAL_FILES", True)
    main = _axis_script(tmp_path / "v.funscript", [(0, 1)])
    _axis_script(tmp_path / "v.roll.funscript", [(0, 5)])
    paths = "\n".join([main, str(tmp_path / "v.roll.funscript")])
    plan, msg, *_ = ui.tool_inspect(paths)  # the desktop app's box holds the paths
    assert plan.kind == "merge"
    result, written = ui.tool_run(plan, "beside", "", "backup")  # the default: the original is kept
    assert written == [main] and (tmp_path / "v.funscript.backup").is_file() and "v.funscript.backup" in result
    assert "axes" in json.loads((tmp_path / "v.funscript").read_text())
    # the merged file is now a one-file script: splitting it over the originals, without a backup
    plan, *_ = ui.tool_inspect(paths)
    assert plan.kind == "split"
    result, written = ui.tool_run(plan, "beside", "", "overwrite")
    assert len(written) == 2 and not (tmp_path / "v.funscript.backup2").exists()
    assert "axes" not in json.loads((tmp_path / "v.funscript").read_text())
    # saved elsewhere: a file already there is always kept
    plan, *_ = ui.tool_inspect(paths)
    assert plan.kind == "merge"
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "v.funscript").write_text("old")
    result, written = ui.tool_run(plan, "elsewhere", f' "{other}" ', "overwrite")
    assert written == [str(other / "v.funscript")] and (other / "v.funscript.backup").read_text() == "old"
    assert "axes" in json.loads((other / "v.funscript").read_text()) and "axes" not in json.loads((tmp_path / "v.funscript").read_text())
    with pytest.raises(gr.Error, match="另存的資料夾"):
        ui.tool_run(plan, "elsewhere", "  ", "backup")
    # the radio buttons show the folder or the question about the originals
    folder, keep = ui.tool_where_changed("elsewhere")
    assert folder["visible"] and not keep["visible"]
    folder, keep = ui.tool_where_changed("beside")
    assert not folder["visible"] and keep["visible"]


@pytest.mark.parametrize("local", [False, True])
def test_the_tools_tab_is_wired_in_both_modes(local, tmp_path, monkeypatch):
    from funscript_gen import webui as ui

    monkeypatch.setattr(ui, "LOCAL_FILES", local)
    monkeypatch.setattr(ui, "NATIVE_DIALOGS", local)
    monkeypatch.setattr(ui, "_last_file", tmp_path / "last.json")
    monkeypatch.setattr(ui, "_cleanup_file", tmp_path / "cleanup.json")
    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path / "out")
    demo = ui.build()
    handlers = {f.fn.__name__ for f in demo.fns.values() if f.fn is not None}
    assert {"tool_inspect", "tool_run", "preview_files"} <= handlers
    assert ("tool_where_changed" in handlers) == local
    run = next(f for f in demo.fns.values() if f.fn is not None and f.fn.__name__ == "tool_run")
    assert len(run.inputs) == 4
