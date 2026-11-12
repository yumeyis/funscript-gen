import os
import pickle

import numpy as np
import pytest

from funscript_gen.ai.prompts import BBox, SceneAnalysis, Subject
from funscript_gen.pipeline import (
    ANALYSIS_FORMAT, HybridAnalysis, ScenePlan, VideoAnalysis, load_analysis, save_analysis,
)
from funscript_gen.video.scenes import Scene


def _analysis(tmp_path) -> VideoAnalysis:
    box = BBox(x1=0.1, y1=0.2, x2=0.4, y2=0.6)
    scene_analysis = SceneAnalysis(
        people_count=2, has_interaction=True, motion="rhythmic",
        subjects=[Subject(description="a", bbox=box)], focus_roi=box, motion_axis="vertical",
        ref_a="hip", ref_b="hip", confidence=0.9)
    plan = ScenePlan(Scene(0, 0.0, 5000.0), roi=(0.1, 0.2, 0.5, 0.6), analysis=HybridAnalysis(scene_analysis, None),
                     source=(np.arange(5.0), np.arange(5.0) ** 2), sign_pattern=np.eye(2, dtype=np.float32),
                     parts_found=(np.arange(3.0), np.zeros((3, 2, 4)), (480, 270)))
    return VideoAnalysis(tmp_path / "clip.mp4", {"fps": 10.0}, [plan], (np.arange(4.0), np.ones(4)), stat=(7, 9))


def test_a_saved_analysis_loads_again(tmp_path):
    original = _analysis(tmp_path)
    save_analysis(original, tmp_path / "a.pkl")
    loaded = load_analysis(tmp_path / "a.pkl")
    assert loaded.video == original.video and loaded.key == original.key and loaded.stat == (7, 9)
    plan = loaded.plans[0]
    assert plan.scene.end_ms == 5000.0 and plan.roi == (0.1, 0.2, 0.5, 0.6)
    assert plan.analysis.general == original.plans[0].analysis.general  # a pydantic model
    assert np.array_equal(plan.source[1], np.arange(5.0) ** 2) and plan.sign_pattern.dtype == np.float32
    assert plan.parts_found[2] == (480, 270) and np.array_equal(loaded.envelope[1], np.ones(4))


class _Evil:
    def __reduce__(self):
        return os.system, ("echo should-not-run",)


def test_a_file_that_calls_something_else_is_refused(tmp_path):
    with open(tmp_path / "evil.pkl", "wb") as f:
        pickle.dump({"format": ANALYSIS_FORMAT, "analysis": _Evil()}, f)
    with pytest.raises(pickle.UnpicklingError, match="not allowed"):
        load_analysis(tmp_path / "evil.pkl")


def test_a_function_of_the_program_is_not_a_class_that_may_be_loaded(tmp_path):
    from funscript_gen.pipeline import generate

    class Call:
        def __reduce__(self):
            return generate, ("x",)

    with open(tmp_path / "call.pkl", "wb") as f:
        pickle.dump({"format": ANALYSIS_FORMAT, "analysis": Call()}, f)
    with pytest.raises(pickle.UnpicklingError, match="not allowed"):
        load_analysis(tmp_path / "call.pkl")


def test_an_analysis_of_another_format_is_refused(tmp_path):
    with open(tmp_path / "old.pkl", "wb") as f:
        pickle.dump({"format": ANALYSIS_FORMAT + 1}, f)
    with pytest.raises(ValueError, match="another version"):
        load_analysis(tmp_path / "old.pkl")
