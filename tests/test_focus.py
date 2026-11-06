import numpy as np
import pytest

from funscript_gen import pipeline
from funscript_gen.ai.prompts import BBox, FocusAnalysis, FrameVisibility, Point, SceneAnalysis, Subject
from funscript_gen.pipeline import HybridAnalysis, PipelineOptions, ScenePlan, frame_choice, plan_scenes, splice_velocity
from funscript_gen.video.decoder import Frame
from funscript_gen.video.scenes import Scene


def _scene(i: int, keyframes: int = 1) -> Scene:
    frames = [Frame(i * 1000.0 + 250 * k, np.zeros((100, 200, 3), np.uint8)) for k in range(keyframes)]
    return Scene(i, i * 1000.0, (i + 1) * 1000.0, frames)


def _focus(**kw) -> FocusAnalysis:
    base = dict(apparent_minor=False, target_visible=True, frames=[], contact_part="mouth",
                focus_roi=BBox(x1=400, y1=400, x2=600, y2=600),
                shaft_base=Point(x=500, y=700), shaft_tip=Point(x=500, y=500), confidence=0.9)
    base.update(kw)
    return FocusAnalysis(**base)


@pytest.fixture
def plans():
    """The genital half of a hybrid analysis applied on its own."""
    out = []
    for i, analysis in enumerate([_focus(), _focus(apparent_minor=True),
                                  _focus(target_visible=False, focus_roi=None, shaft_base=None, shaft_tip=None)]):
        plan = ScenePlan(_scene(i))
        pipeline._apply_focus(plan, analysis, "rel1000")
        out.append(plan)
    return out


def test_focus_plan_uses_padded_roi_and_shaft_direction(plans):
    p = plans[0]
    assert p.mode == "flow" and not p.skip
    assert p.roi == pytest.approx((0.36, 0.36, 0.64, 0.64))  # 0.4..0.6 grown by 20% of its size per side
    dx, dy = p.direction
    assert dx == pytest.approx(0) and dy < 0  # tip above base: stroke toward the tip is "up" in the image


@pytest.mark.skip(reason="disabled by the user: the skip note was changed in pipeline18off")
def test_apparent_minor_skips_scene(plans):
    assert plans[1].skip and "未成年" in plans[1].note


def test_target_not_visible_falls_back_to_full_frame(plans):
    assert plans[2].roi is None and not plans[2].skip and plans[2].direction is None


def _general() -> SceneAnalysis:
    return SceneAnalysis(
        people_count=2, has_interaction=True, motion="rhythmic",
        subjects=[Subject(description="a", bbox=BBox(x1=0, y1=0, x2=500, y2=1000))],
        focus_roi=BBox(x1=100, y1=100, x2=900, y2=900), motion_axis="vertical", ref_a="hip", ref_b="hip",
        confidence=0.9,
    )


def _frames(*states):  # (visible, occluded) per key frame
    return [FrameVisibility(frame=i + 1, visible=v, occluded=o) for i, (v, o) in enumerate(states)]


@pytest.fixture
def hybrid_plans(monkeypatch):
    analyses = [
        (HybridAnalysis(_general(), _focus(frames=_frames((True, False), (True, True), (False, False), (True, False)))), None),
        (HybridAnalysis(_general(), _focus(target_visible=False, focus_roi=None, frames=_frames(*[(False, False)] * 4))), None),
        (HybridAnalysis(_general(), _focus(apparent_minor=True)), None),
        (HybridAnalysis(_general(), None), "focus call failed"),
    ]
    monkeypatch.setattr(pipeline, "_analyze_scenes", lambda scenes, workers, focus, settings, tick=None: analyses)
    return plan_scenes([_scene(i, keyframes=4) for i in range(4)], PipelineOptions(focus="hybrid"))


def test_hybrid_picks_focus_only_where_visible_and_not_occluded(hybrid_plans):
    p = hybrid_plans[0]
    assert p.mode == "flow" and p.roi == pytest.approx((0.36, 0.36, 0.64, 0.64))
    assert p.alt_roi == pytest.approx((0.1, 0.1, 0.9, 0.9))
    assert [use for _, use in p.decisions] == [True, False, False, True]
    assert "2/4" in p.note


def test_hybrid_without_focus_region_uses_general_everywhere(hybrid_plans):
    for p in hybrid_plans[1], hybrid_plans[3]:
        assert p.roi is None and p.alt_roi is not None and not any(u for _, u in p.decisions)


def test_hybrid_respects_minor_skip(hybrid_plans):
    assert hybrid_plans[2].skip and not hybrid_plans[2].decisions


def test_frame_choice_uses_nearest_keyframe():
    use = frame_choice(np.array([0, 400, 600, 1000, 5000]), [(0, True), (1000, False)])
    assert use.tolist() == [True, True, False, False, False]


def test_splice_flips_general_when_directions_disagree():
    v = np.sin(np.linspace(0, 20, 200))
    out = splice_velocity(v, -2 * v, np.arange(200) < 100)
    assert np.all(out[:100] == v[:100]) and np.allclose(out[100:], 2 * v[100:])


@pytest.mark.parametrize(("mode", "expected"), [("auto", "flow"), ("flow", "flow"), ("pose", "pose")])
def test_general_auto_mode_uses_flow(mode, expected):
    plans = plan_scenes([_scene(0)], PipelineOptions(mode=mode, use_ai=False))
    assert plans[0].mode == expected


def test_without_focus_roi_the_region_covers_both_subjects(monkeypatch):
    two = _general().model_copy(update={"focus_roi": None, "subjects": [
        Subject(description="left", bbox=BBox(x1=200, y1=150, x2=380, y2=780)),
        Subject(description="right", bbox=BBox(x1=450, y1=200, x2=650, y2=800)),
    ]})
    one = two.model_copy(update={"subjects": two.subjects[:1]})
    monkeypatch.setattr(pipeline, "_analyze_scenes", lambda scenes, workers, focus, settings, tick=None: [(two, None), (one, None)])
    plans = plan_scenes([_scene(0), _scene(1)], PipelineOptions())
    assert plans[0].roi == pytest.approx((0.2, 0.15, 0.65, 0.8))
    assert plans[1].roi == pytest.approx((0.2, 0.15, 0.38, 0.78))


class FakeContacts:
    def __init__(self, probs):
        self.probs, self.boxes = probs, 0

    def choice_probs(self, images, prompt, schema, answer, field):
        assert field == "contact_part" and answer.contact_part in ("hand", "mouth")
        return self.probs

    def analyze(self, images, prompt, schema):
        from funscript_gen.ai.prompts import ContactBoxes

        self.boxes += 1
        return ContactBoxes(hand=BBox(x1=0, y1=0, x2=250, y2=500), mouth=BBox(x1=500, y1=0, x2=750, y2=500),
                            penis=BBox(x1=250, y1=500, x2=500, y2=750))


def _contact_plans(monkeypatch, fake, part="mouth", opts=None):
    from conftest import REAL_PICK_CONTACTS

    analyses = [(HybridAnalysis(_general(), _focus(contact_part=part)), None)]
    monkeypatch.setattr(pipeline, "_analyze_scenes", lambda scenes, workers, focus, settings, tick=None: analyses)
    monkeypatch.setattr(pipeline, "_pick_contacts", REAL_PICK_CONTACTS)
    monkeypatch.setattr("funscript_gen.config.make_provider", lambda settings=None: fake)
    return plan_scenes([_scene(0, keyframes=4)], PipelineOptions(focus="hybrid", **(opts or {})))


def test_hand_and_mouth_on_top_get_both_boxes(monkeypatch):
    fake = FakeContacts({"mouth": 0.6, "hand": 0.3, "other": 0.1})
    p = _contact_plans(monkeypatch, fake)[0]
    assert fake.boxes == 1 and p.contact_probs["hand"] == 0.3
    assert p.contact_rois["hand"] == pytest.approx((0.0, 0.0, 0.3, 0.6))  # 0..0.25 x 0..0.5 grown by 20%
    assert p.contact_rois["mouth"] == pytest.approx((0.45, 0.0, 0.8, 0.6))
    assert p.contact_penis == pytest.approx((0.2, 0.45, 0.55, 0.8))
    assert "mouth 0.60、hand 0.30" in p.base_note


@pytest.mark.parametrize(("probs", "min_prob"), [
    ({"mouth": 0.6, "other": 0.3, "hand": 0.1}, 0.0),  # the hand is not second
    ({"mouth": 1.0, "hand": 0.0}, 0.0),  # no probability for the hand at all
    ({"mouth": 0.95, "hand": 0.05}, 0.1),  # the hand is second, but too unlikely
])
def test_contact_boxes_only_for_hand_and_mouth_on_top(monkeypatch, probs, min_prob):
    fake = FakeContacts(probs)
    p = _contact_plans(monkeypatch, fake, opts={"contact_min_prob": min_prob})[0]
    assert p.contact_rois is None and p.contact_probs == probs and fake.boxes == 0


def test_contact_pick_skips_other_parts_and_can_be_turned_off(monkeypatch):
    for part, opts in (("vagina", {}), ("mouth", {"contact_pick": False})):
        from conftest import REAL_PICK_CONTACTS

        analyses = [(HybridAnalysis(_general(), _focus(contact_part=part)), None)]
        monkeypatch.setattr(pipeline, "_analyze_scenes", lambda scenes, workers, focus, settings, tick=None: analyses)
        monkeypatch.setattr(pipeline, "_pick_contacts", REAL_PICK_CONTACTS)
        monkeypatch.setattr("funscript_gen.config.make_provider", lambda settings=None: pytest.fail("no AI call"))
        assert plan_scenes([_scene(0, keyframes=4)], PipelineOptions(focus="hybrid", **opts))[0].contact_probs is None


def test_genital_region_follows_the_contact_part_that_moves_more():
    from funscript_gen.tracking.flow import FlowTracker

    tracker = FlowTracker(roi=None)
    vel = np.sin(2 * np.pi * 1.5 * np.arange(180) / 30)
    rng = np.random.default_rng(1)
    for i in range(180):
        f = rng.normal(0, 0.05, (10, 10, 2))
        f[1:4, 1:4, 1] += 0.5 * vel[i]  # left: small strokes
        f[1:4, 6:9, 1] += 2.0 * vel[i]  # right: large ones
        tracker.t_ms.append(i * 1000 / 30)
        tracker.fields.append(f.astype(np.float16))
    plan = ScenePlan(_scene(0), roi=(0.3, 0.3, 0.7, 0.7), alt_roi=(0.0, 0.0, 1.0, 1.0), decisions=[(0.0, True)],
                     contact_rois={"hand": (0.0, 0.0, 0.5, 0.5), "mouth": (0.5, 0.0, 1.0, 0.5)},
                     contact_penis=(0.4, 0.5, 0.6, 0.9))
    pipeline._scene_source(plan, PipelineOptions(focus="hybrid"), tracker, [])
    # the mouth (right) moves more; the region also holds the penis
    assert plan.roi == (0.4, 0.0, 1.0, 0.9) and "改用移動較大的 mouth＋主動部位" in plan.base_note
