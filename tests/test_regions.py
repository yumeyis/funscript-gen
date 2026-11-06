import numpy as np
import pytest

from funscript_gen import pipeline
from funscript_gen.ai.prompts import BBox, RegionPick, SceneAnalysis, Subject
from funscript_gen.ai.regions import FULL, candidates, sheets
from funscript_gen.pipeline import PipelineOptions, ScenePlan, _scene_signal, plan_scenes
from funscript_gen.tracking.flow import FlowTracker
from funscript_gen.video.decoder import Frame
from funscript_gen.video.scenes import Scene


def test_candidates_put_the_current_region_first_and_drop_duplicates():
    a, b = (0.1, 0.1, 0.5, 0.9), (0.5, 0.1, 0.9, 0.9)
    names = [n for n, _ in candidates((0.3, 0.3, 0.7, 0.7), [a, b])]
    assert names[:5] == ["ai", "full", "A", "B", "union"]
    assert len(names) == 14  # + 3x3 grid
    # No focus box: "ai" is the whole frame, so "full" is a duplicate.
    names = [n for n, _ in candidates(None, [])]
    assert names[0] == "ai" and "full" not in names and len(names) == 10


def test_candidates_drop_tiny_boxes():
    names = [n for n, _ in candidates((0.3, 0.3, 0.7, 0.7), [(0.5, 0.5, 0.51, 0.9)])]
    assert "A" not in names


def test_sheets_hold_four_numbered_panels_each():
    frames = [np.full((90, 160, 3), k * 60, np.uint8) for k in range(4)]
    out = sheets(frames, [FULL] * 5)
    assert len(out) == 2
    assert out[0].shape == out[1].shape and out[0].shape[0] == out[0].shape[1]
    assert not out[1][out[1].shape[0] // 2:].any()  # second sheet: one panel, the rest blank


def _flow(moving: tuple[slice, slice], seconds: float = 6.0) -> FlowTracker:
    """A 10x10-cell flow field where only `moving` cells move up and down at 1.5 Hz; the rest is noise."""
    rng = np.random.default_rng(0)
    tracker = FlowTracker(roi=None)
    for i in range(int(seconds * 30)):
        f = rng.normal(0, 0.05, (10, 10, 2))
        f[moving[0], moving[1], 1] += 2.0 * np.sin(2 * np.pi * 1.5 * i / 30)
        tracker.t_ms.append(i * 1000 / 30)
        tracker.fields.append(f.astype(np.float16))
    return tracker


def _plan(roi, pick) -> ScenePlan:
    plan = ScenePlan(Scene(0, 0.0, 6000.0, []), roi=roi)
    plan.pick_name, plan.pick_roi = "g22", pick
    return plan


def test_pick_is_used_when_its_signal_is_more_periodic():
    flow = _flow((slice(6, 9), slice(6, 9)))
    plan = _plan((0.0, 0.0, 0.3, 0.3), (0.5, 0.5, 1.0, 1.0))
    sig = _scene_signal(plan, PipelineOptions(), flow, [])
    assert plan.roi == (0.5, 0.5, 1.0, 1.0) and "改用 g22" in plan.note
    assert len(sig.strokes) >= 12


def test_pick_is_ignored_when_its_signal_is_less_periodic():
    flow = _flow((slice(0, 3), slice(0, 3)))
    plan = _plan((0.0, 0.0, 0.3, 0.3), (0.5, 0.5, 1.0, 1.0))
    _scene_signal(plan, PipelineOptions(), flow, [])
    assert plan.roi == (0.0, 0.0, 0.3, 0.3) and "沿用原區域" in plan.note


def test_pick_is_ignored_when_neither_region_has_a_rhythm():
    flow = FlowTracker(roi=None)
    for i in range(180):  # nothing moves: both periodicities are 0, a tie that must not switch
        flow.t_ms.append(i * 1000 / 30)
        flow.fields.append(np.zeros((10, 10, 2), np.float16))
    plan = _plan((0.0, 0.0, 0.3, 0.3), (0.5, 0.5, 1.0, 1.0))
    _scene_signal(plan, PipelineOptions(), flow, [])
    assert plan.roi == (0.0, 0.0, 0.3, 0.3) and "沒有節奏" in plan.note


def _general() -> SceneAnalysis:
    return SceneAnalysis(
        people_count=2, has_interaction=True, motion="rhythmic",
        subjects=[Subject(description="a", bbox=BBox(x1=0, y1=0, x2=500, y2=1000)),
                  Subject(description="b", bbox=BBox(x1=500, y1=0, x2=1000, y2=1000))],
        focus_roi=BBox(x1=300, y1=300, x2=700, y2=700), motion_axis="vertical", ref_a="hip", ref_b="hip",
        confidence=0.9,
    )


class FakeProvider:
    def __init__(self, best: int) -> None:
        self.best = best
        self.calls = 0

    def analyze(self, images, prompt, schema):
        assert schema is RegionPick
        self.calls += 1
        return RegionPick(best=self.best, second=1)


def _scenes(n: int) -> list[Scene]:
    return [Scene(i, i * 1000.0, (i + 1) * 1000.0,
                  [Frame(i * 1000.0 + 250 * k, np.zeros((100, 200, 3), np.uint8)) for k in range(4)])
            for i in range(n)]


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(pipeline, "_analyze_scenes", lambda scenes, workers, focus, settings, tick=None: [(_general(), None)] * len(scenes))
    fake = FakeProvider(best=3)
    monkeypatch.setattr("funscript_gen.config.make_provider", lambda settings=None: fake)
    return fake


def test_plan_scenes_records_the_pick(provider):
    plans = plan_scenes(_scenes(2), PipelineOptions())
    assert provider.calls == 2
    assert plans[0].pick_name == "A" and plans[0].pick_roi == pytest.approx((0.0, 0.0, 0.5, 1.0))


def test_pick_of_the_current_region_or_out_of_range_changes_nothing(provider):
    for best in (1, 99):
        provider.best = best
        plans = plan_scenes(_scenes(1), PipelineOptions())
        assert plans[0].pick_roi is None


@pytest.mark.parametrize("opts", [
    PipelineOptions(region_pick=False),
    PipelineOptions(roi=(0.1, 0.1, 0.9, 0.9)),
    PipelineOptions(mode="pose"),
])
def test_region_pick_does_not_run_when_off_or_not_applicable(provider, opts):
    plans = plan_scenes(_scenes(1), opts)
    assert provider.calls == 0 and plans[0].pick_roi is None
