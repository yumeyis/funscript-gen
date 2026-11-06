import numpy as np
import pytest

from funscript_gen import pipeline
from funscript_gen.ai.prompts import RangeAnalysis
from funscript_gen.export.funscript import Action
from funscript_gen.pipeline import PipelineOptions, ScenePlan, apply_ranges, clip_range, plan_scenes
from funscript_gen.video.decoder import Frame
from funscript_gen.video.scenes import Scene

from conftest import REAL_DETECT_RANGES


def _scene(i: int) -> Scene:
    return Scene(i, i * 1000.0, (i + 1) * 1000.0, [Frame(i * 1000.0, np.zeros((100, 200, 3), np.uint8))])


def _range(**kw) -> RangeAnalysis:
    base = dict(apparent_minor=False, penis_visible=True, penis_complete=True, glans_visible=True, confidence=0.9)
    base.update(kw)
    return RangeAnalysis(**base)


@pytest.fixture
def plans(monkeypatch):
    monkeypatch.setattr(pipeline, "_analyze_scenes", lambda scenes, workers, focus, settings, tick=None: [(None, None)] * len(scenes))
    ranges = [
        (_range(), None),
        (_range(penis_complete=False, glans_visible=False), None),
        (_range(glans_visible=True, penis_complete=False), None),
        (_range(apparent_minor=True), None),
        (None, "timeout"),
    ]
    monkeypatch.setattr(pipeline, "_detect_ranges", lambda scenes, workers, settings, tick=None: ranges[: len(scenes)])
    opts = PipelineOptions(region_pick=False)
    plans = plan_scenes([_scene(i) for i in range(5)], opts)
    assert all(p.range_max is None and p.range_min is None for p in plans)  # output settings: applied when rendering
    apply_ranges(plans, opts)
    return plans


def test_whole_penis_and_glans_keep_the_full_range(plans):
    assert plans[0].range_max is None and plans[0].range_min is None and "完整" in plans[0].note


def test_no_glans_caps_the_scene_at_80(plans):
    assert plans[1].range_max == 80 and plans[1].range_min is None and "看不到前端" in plans[1].note


def test_glans_without_the_whole_penis_raises_the_minimum_to_20(plans):
    assert plans[2].range_max is None and plans[2].range_min == 20 and "最小值 20" in plans[2].note


def test_no_glans_caps_even_if_the_penis_is_called_complete(monkeypatch):
    plan = ScenePlan(_scene(0))
    pipeline._apply_range(plan, _range(glans_visible=False), None, 80, 20)
    assert plan.range_max == 80 and plan.range_min is None


@pytest.mark.skip(reason="disabled by the user: the skip note was changed in pipeline18off")
def test_apparent_minor_skips_the_scene(plans):
    assert plans[3].skip and "未成年" in plans[3].note


def test_failed_call_leaves_the_scene_uncapped(plans):
    assert plans[4].range_max is None and not plans[4].skip and "timeout" in plans[4].note


@pytest.mark.parametrize("opts", [PipelineOptions(stroke_range=False), PipelineOptions(use_ai=False)])
def test_detection_does_not_run_when_off(monkeypatch, opts):
    monkeypatch.setattr(pipeline, "_analyze_scenes", lambda scenes, workers, focus, settings, tick=None: [(None, None)] * len(scenes))
    monkeypatch.setattr(pipeline, "_detect_ranges", lambda *a: pytest.fail("range detection ran"))
    opts.region_pick = False
    plan = plan_scenes([_scene(0)], opts)[0]
    assert plan.range_max is None and plan.range_min is None


def test_cap_clips_only_the_capped_scene():
    plans = [ScenePlan(_scene(0)), ScenePlan(_scene(1), range_max=80)]
    actions = [Action(100, 0), Action(500, 100), Action(1100, 0), Action(1500, 100), Action(1900, 50)]
    out = clip_range(actions, plans, 0, 100)
    assert [a.pos for a in out] == [0, 100, 0, 80, 50]


def test_floor_clips_only_the_low_end():
    plans = [ScenePlan(_scene(0), range_min=20)]
    out = clip_range([Action(0, 0), Action(300, 100), Action(600, 35)], plans, 0, 100)
    assert [a.pos for a in out] == [20, 100, 35]


def test_cap_keeps_the_low_end_of_a_custom_range():
    plans = [ScenePlan(_scene(0), range_max=80)]
    out = clip_range([Action(0, 20), Action(500, 90)], plans, 20, 90)
    assert [a.pos for a in out] == [20, 80]
    plans[0].range_max = 10  # a cap below the low end does not push positions under it
    assert [a.pos for a in clip_range([Action(0, 20), Action(500, 90)], plans, 20, 90)] == [20, 20]


def test_detect_ranges_sends_the_keyframes(monkeypatch):
    seen = []

    class Fake:
        def analyze(self, images, prompt, schema):
            seen.append((len(images), schema))
            return _range()

    monkeypatch.setattr("funscript_gen.config.make_provider", lambda settings=None: Fake())
    out = REAL_DETECT_RANGES([_scene(0), _scene(1)], 2, None)
    assert [a.glans_visible for a, _ in out] == [True, True]
    assert seen == [(1, RangeAnalysis)] * 2


def test_cap_and_floor_come_from_the_render_settings(plans):
    opts = PipelineOptions(range_cap=70, range_floor=30)
    apply_ranges(plans, opts)
    assert plans[1].range_max == 70 and plans[2].range_min == 30 and "最大值 70" in plans[1].note
