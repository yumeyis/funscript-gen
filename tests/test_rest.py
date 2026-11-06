import numpy as np
import pytest

from funscript_gen import pipeline
from funscript_gen.ai.prompts import BBox, SceneAnalysis, Subject
from funscript_gen.export.funscript import Action
from funscript_gen.pipeline import HybridAnalysis, PipelineOptions, ScenePlan, finalize, plan_scenes
from funscript_gen.signal.process import ProcessedSignal
from funscript_gen.video.decoder import Frame
from funscript_gen.video.scenes import Scene


def _scene(i: int) -> Scene:
    return Scene(i, i * 1000.0, (i + 1) * 1000.0, [Frame(i * 1000.0, np.zeros((100, 200, 3), np.uint8))])


def _general(people: int) -> SceneAnalysis:
    return SceneAnalysis(
        people_count=people, has_interaction=people == 2, motion="rhythmic" if people else "none",
        subjects=[Subject(description="a", bbox=BBox(x1=0, y1=0, x2=500, y2=1000))] if people else [],
        focus_roi=BBox(x1=100, y1=100, x2=900, y2=900) if people else None, motion_axis="vertical",
        ref_a="hip", ref_b="hip", confidence=0.9,
    )


def _plans(monkeypatch, analyses, **kw):
    monkeypatch.setattr(pipeline, "_analyze_scenes", lambda scenes, workers, focus, settings, tick=None: analyses)
    asked = []
    monkeypatch.setattr(pipeline, "_detect_ranges",
                        lambda scenes, workers, settings, tick=None: asked.extend(scenes) or [(None, "off")] * len(scenes))
    plans = plan_scenes([_scene(i) for i in range(len(analyses))], PipelineOptions(region_pick=False, **kw))
    return plans, asked


def test_a_scene_with_nobody_in_it_rests(monkeypatch):
    plans, asked = _plans(monkeypatch, [(_general(2), None), (_general(0), None), (None, "timeout")])
    assert not plans[0].rest and not plans[0].skip
    assert plans[1].rest and plans[1].skip and "沒有人" in plans[1].note
    assert not plans[2].rest and not plans[2].skip  # the AI failed: unknown, so the picture is analysed
    assert [s.index for s in asked] == [0, 2]  # no stroke range call for the resting scene


def test_rest_needs_the_switch_and_no_manual_region(monkeypatch):
    for kw in ({"rest_empty": False}, {"roi": (0.1, 0.1, 0.9, 0.9)}):
        plans, _ = _plans(monkeypatch, [(_general(0), None)], **kw)
        assert not plans[0].rest and not plans[0].skip


def test_hybrid_uses_its_general_analysis_to_rest(monkeypatch):
    plans, _ = _plans(monkeypatch, [(HybridAnalysis(_general(0), None), None), (HybridAnalysis(_general(2), None), None)],
                      focus="hybrid")
    assert plans[0].rest and not plans[1].rest


def test_finalize_holds_a_resting_scene_at_the_top():
    z = np.zeros(1)
    moving = ScenePlan(Scene(0, 0.0, 1000.0), signal=ProcessedSignal(z, z, z, z, z, z > -1, [Action(100, 10), Action(500, 60)]))
    resting = ScenePlan(Scene(1, 1000.0, 3000.0), skip=True, rest=True)
    opts = PipelineOptions()
    opts.signal.max_speed = 1e9
    opts.signal.pos_low, opts.signal.pos_high = 10, 90
    assert [(a.at, a.pos) for a in finalize([moving, resting], opts)] == [(100, 10), (500, 60), (1000, 90), (2999, 90)]
    # --invert and flips fix the stroke direction; a rest is not a stroke and stays at the top
    for invert, flipped in ((True, False), (False, True)):
        opts.invert, resting.flipped = invert, flipped
        assert [a.pos for a in finalize([moving, resting], opts)][-2:] == [90, 90]
    assert [a.pos for a in finalize([moving, resting], opts)][:2] == [10, 60]  # the strokes still follow invert


@pytest.mark.parametrize("people", [1, 2])
def test_scenes_with_people_are_analysed(monkeypatch, people):
    plans, _ = _plans(monkeypatch, [(_general(people), None)])
    assert not plans[0].rest and not plans[0].skip


def test_on_seen_gets_the_plans_with_resting_scenes_already_skipped(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "_analyze_scenes",
                        lambda scenes, workers, focus, settings, tick=None: [(_general(2), None), (_general(0), None)])
    monkeypatch.setattr(pipeline, "_detect_ranges",
                        lambda scenes, workers, settings, tick=None: [(None, "off")] * len(scenes))
    plan_scenes([_scene(0), _scene(1)], PipelineOptions(region_pick=False),
                on_seen=lambda plans: seen.append([p.skip for p in plans]))
    assert seen == [[False, True]]  # once, before the range calls


def test_a_deferred_part_scan_detects_only_the_scenes_it_is_started_with():
    scan = pipeline.PartScan([_scene(0), _scene(1)], None, PipelineOptions(), detector=object(), defer=True)
    scan._detect = lambda scene: scene.index  # no real detection: only which scenes are queued matters
    try:
        assert scan.jobs == {}
        scan.start([_scene(1)])
        scan.start([_scene(1)])  # queued once
        assert {k: j.result() for k, j in scan.jobs.items()} == {1: 1}
    finally:
        scan.close()
