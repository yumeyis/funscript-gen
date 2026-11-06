import dataclasses

import pytest
from typer.testing import CliRunner

from funscript_gen import options
from funscript_gen.options import BY_NAME, OPTIONS, PRESETS, UI_OPTIONS, OptionError, build, resolve, values_of
from funscript_gen.pipeline import PipelineOptions


def _fields(opts: PipelineOptions) -> dict:
    d = dataclasses.asdict(opts)
    d.pop("ai_settings")
    return d


def test_the_table_defaults_are_the_pipeline_defaults():
    # the CLI and the web UI start from the table: they must agree with PipelineOptions / SignalParams
    assert _fields(build(options.defaults())) == _fields(PipelineOptions())


def test_values_survive_a_round_trip_through_the_pipeline_options():
    for name in PRESETS:
        values = resolve({}, name)
        assert {k: v for k, v in values_of(build(values)).items()} == {o.name: values[o.name] for o in OPTIONS if o.targets}
    values = resolve({"roi": "0.1,0.2,0.9,0.8", "flip_scenes": "3,0", "axis": "vertical", "ai_workers": 4})
    back = values_of(build(values))
    assert back["roi"] == "0.1,0.2,0.9,0.8" and back["flip_scenes"] == "0,3" and back["axis"] == "vertical"
    assert build(values).roi == (0.1, 0.2, 0.9, 0.8) and build(values).flip_scenes == (0, 3)


def test_presets_and_given_values_override_the_defaults():
    values = resolve({"dwell": False, "gain": None}, "user")  # None = not given
    assert values["focus"] == "hybrid" and values["dwell"] is False and values["curve"] is True and values["gain"] == 1.0
    opts = build(resolve({}, "user"))
    assert opts.asym_sign and opts.part_sign and opts.signal.freq_max_hz == 3.0 and opts.focus == "hybrid"
    assert not build(resolve({"asym_sign": False, "part_sign": False}, "user")).part_sign
    with pytest.raises(OptionError, match="unknown preset"):
        resolve({}, "nope")
    with pytest.raises(OptionError, match="unknown options"):
        resolve({"nope": 1})


@pytest.mark.parametrize("given, en, zh", [
    ({"range_low": 60, "range_high": 40}, "range-low < range-high", "下限必須小於上限"),
    ({"freq_limit": 2.0, "freq_max": 1.0}, "--freq-max must be above", "最高頻率必須大於門檻"),
    ({"range_low": 50, "range_cap": 40}, "range-cap", "最大值不能低於範圍下限"),
    ({"roi": "0.5,0,0.4,1"}, "ROI", "ROI 格式"),
    ({"focus": "genital"}, "focus must be general, hybrid", "分析目標只能是"),  # the standalone genital focus is gone
    ({"flow_width": 100}, "--flow-width must be within 160..480", "光流計算寬度必須在 160–480 之間"),
    ({"asym_threshold": 0.0}, "--asym-threshold must be above 0", "翻轉門檻必須大於 0"),
    ({"part_sign_threshold": 1.0}, "--part-sign-threshold must be within 0..1", "翻轉門檻必須在 0–1 之間"),
    ({"dwell": "yes"}, "--dwell must be true or false", "保留轉折處的停頓必須是開或關"),
])
def test_invalid_settings_are_explained_in_both_languages(given, en, zh):
    with pytest.raises(OptionError) as e:
        build(resolve(given))
    assert en in e.value.en and zh in e.value.local


def test_the_cap_is_only_checked_with_the_stroke_range_on():
    build(resolve({"stroke_range": False, "range_low": 50, "range_cap": 40}))


def test_the_web_ui_and_cli_entries_are_complete():
    for o in UI_OPTIONS:
        assert o.group in options.GROUPS, o.name
        if o.kind in ("int", "float"):
            lo, hi, _ = o.slider
            assert lo <= o.default <= hi, o.name
        if o.show_if:
            assert BY_NAME[o.show_if].kind == "bool" and o.row, o.name
    flags = [o.cli_name for o in options.CLI_OPTIONS]
    assert len(flags) == len(set(flags))
    for preset in PRESETS.values():
        assert set(preset) <= set(BY_NAME)


def _capture(monkeypatch):
    from funscript_gen import cli

    seen = {}

    class Info:
        duration_ms = 1000.0

    def fake_generate(video, opts, progress=None):
        seen["opts"] = opts
        raise SystemExit(0)

    monkeypatch.setattr(cli, "probe", lambda video: Info())
    monkeypatch.setattr(cli, "generate", fake_generate)
    return cli.app, seen


def test_cli_flags_reach_the_pipeline(monkeypatch):
    app, seen = _capture(monkeypatch)
    r = CliRunner().invoke(app, ["generate", "v.mp4", "--no-ai", "--asym-threshold", "0.4", "--freq-limit", "1.8",
                                 "--scene-threshold", "20", "--flip-scenes", "2,1", "--roi", "0.1,0.1,0.9,0.9"])
    assert r.exit_code == 0, r.output
    o = seen["opts"]
    assert not o.use_ai and o.asym_sign_threshold == 0.4 and o.signal.freq_limit_hz == 1.8
    assert o.scene_threshold == 20 and o.flip_scenes == (1, 2) and o.roi == (0.1, 0.1, 0.9, 0.9)


def test_cli_preset_with_an_override(monkeypatch):
    app, seen = _capture(monkeypatch)
    r = CliRunner().invoke(app, ["generate", "v.mp4", "--preset", "user", "--no-curve"])
    assert r.exit_code == 0, r.output
    o = seen["opts"]
    assert o.focus == "hybrid" and o.signal.dwell and not o.signal.curve and o.signal.freq_max_hz == 3.0
    r = CliRunner().invoke(app, ["generate", "v.mp4", "--range-low", "50", "--range-high", "40"])
    assert r.exit_code == 2 and "range-low" in r.output


def test_web_ui_preset_sets_the_form(tmp_path, monkeypatch):
    from funscript_gen import webui as ui

    monkeypatch.setattr(ui, "_last_file", tmp_path / "last.json")
    demo = ui.build()
    apply = next(f for f in demo.fns.values() if f.fn is not None and f.fn.__name__ == "apply_preset")
    updates = apply.fn("user")
    by_label = {c.label: u for c, u in zip(apply.outputs, updates)}
    assert by_label["分析目標"]["value"] == "hybrid" and by_label["保留轉折處的停頓"]["value"] is True
    assert by_label["幅度縮小門檻（Hz，0 = 關閉）"]["value"] == 2.0 and "使用者的 Web UI 設定" in updates[-1]


def test_scripts_record_how_they_were_made(tmp_path):
    from test_parallel import _clip

    from funscript_gen.pipeline import generate

    _clip(tmp_path / "c.mp4", seconds=3.0)
    opts = build(resolve({"use_ai": False, "asym_audio": False, "flow_workers": 1, "gain": 1.5}))
    meta = generate(tmp_path / "c.mp4", opts).funscript.metadata["funscript_gen"]
    assert meta["options"]["gain"] == 1.5 and meta["options"]["use_ai"] is False and meta["ai_model"] is None
    assert len(meta["code"]) == 12 and meta["version"]
    assert _fields(build(resolve(meta["options"]))) == _fields(opts)  # enough to make the script again


def test_an_analysis_serves_the_same_video_with_the_same_analysis_settings(tmp_path):
    from funscript_gen.options import analysis_key
    from funscript_gen.pipeline import VideoAnalysis

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    st = (video.stat().st_size, video.stat().st_mtime_ns)
    key = analysis_key(resolve({}))
    no_parts = analysis_key(resolve({"part_sign": False}))
    older = VideoAnalysis(video, {k: v for k, v in key.items() if k != "device"}, [], None, st)
    assert older.serves(video, key)  # made before "device" was an analysis setting: it was at its default
    assert older.serves(video, no_parts)  # without the part check its boxes are just not used
    assert not older.serves(video, analysis_key(resolve({"focus": "hybrid"})))
    assert not VideoAnalysis(video, no_parts, [], None, st).serves(video, key)  # no boxes
    video.write_bytes(b"xy")  # another file now
    assert not older.serves(video, key)
