import json

import numpy as np
import pytest

from funscript_gen.export.funscript import Action, Funscript
from funscript_gen.pipeline import PipelineOptions, PipelineResult, ScenePlan, finalize, refinalize, toggle_flip
from funscript_gen.signal.process import ProcessedSignal
from funscript_gen.video.scenes import Scene


def _plan(i: int, actions: list[tuple[int, int]], t_ms=None, smooth=None, **kw) -> ScenePlan:
    t = np.asarray(t_ms if t_ms is not None else [i * 1000.0], float)
    x = np.asarray(smooth if smooth is not None else np.zeros(len(t)), float)
    sig = ProcessedSignal(t, x, x, x, x, np.ones(len(t), bool), [Action(a, p) for a, p in actions])
    return ScenePlan(Scene(i, i * 1000.0, (i + 1) * 1000.0), signal=sig, **kw)


def _opts(**kw) -> PipelineOptions:
    opts = PipelineOptions(**kw)
    opts.signal.max_speed = 1e9  # keep the points as they are
    return opts


def test_finalize_flips_only_the_flipped_scene():
    plans = [_plan(0, [(100, 0), (500, 100)]), _plan(1, [(1100, 0), (1500, 100)], flipped=True)]
    assert [a.pos for a in finalize(plans, _opts())] == [0, 100, 100, 0]


def test_finalize_bridges_cuts_after_the_flips_but_not_across_a_rest():
    first = _plan(0, [(0, 0), (300, 100), (600, 0), (900, 100)])  # ends on a peak, 300 ms per half-stroke
    second = _plan(1, [(1650, 0), (1950, 100)], flipped=True)  # flipped: also starts on a peak, 750 ms later
    assert [(a.at, a.pos) for a in finalize([first, second], _opts())][3:6] == [(900, 100), (1275, 0), (1650, 100)]
    second.flipped = False  # a trough 750 ms later: three half-strokes rather than one slow one
    assert [(a.at, a.pos) for a in finalize([first, second], _opts())][3:7] == [(900, 100), (1150, 0), (1400, 100),
                                                                              (1650, 0)]
    resting = ScenePlan(Scene(1, 1000.0, 1400.0), skip=True, rest=True)
    assert len(finalize([first, resting, second], _opts())) == 4 + 2 + 2
    off = _opts()
    off.signal.bridge = False
    assert len(finalize([first, second], off)) == 6


def test_flip_mirrors_within_the_output_range_and_combines_with_invert():
    plans = [_plan(0, [(100, 40), (500, 90)], flipped=True)]
    opts = _opts()
    opts.signal.pos_low, opts.signal.pos_high = 40, 90
    assert [a.pos for a in finalize(plans, opts)] == [90, 40]
    assert [a.pos for a in finalize(plans, _opts(invert=True))] == [40, 90]  # invert + flip = unchanged


def test_range_cap_applies_after_the_flip():
    # The cap is on the output's high end: after a flip the former lows are cut, not the former highs.
    plans = [_plan(0, [(100, 0), (500, 100)], flipped=True, range_max=80)]
    assert [a.pos for a in finalize(plans, _opts())] == [80, 0]


def test_toggle_flip_notes_it_and_undoes():
    plan = _plan(0, [(100, 0)], note="行程範圍：完整")
    toggle_flip(plan)
    assert plan.flipped and plan.note == "行程範圍：完整；手動反轉"
    toggle_flip(plan)
    assert not plan.flipped and plan.note == "行程範圍：完整"


def test_refinalize_updates_the_script_and_its_notes():
    plans = [_plan(0, [(100, 0), (500, 100)])]
    result = PipelineResult(Funscript([Action(100, 0), Action(500, 100)], metadata={"notes": "x flipped=[] y"}), plans)
    toggle_flip(plans[0])
    refinalize(result, _opts())
    assert [a.pos for a in result.funscript.actions] == [100, 0]
    assert result.funscript.metadata["notes"] == "x flipped=[0] y"


def test_scene_numbers_are_parsed():
    from funscript_gen.options import OptionError, parse_scenes

    assert parse_scenes("3, 0,3") == (0, 3) and parse_scenes("") == ()
    with pytest.raises(OptionError):
        parse_scenes("a,1")


def test_debug_data_records_the_flip():
    from funscript_gen.report import FLIP_COLUMN, SCENE_COLUMNS, debug_data, scene_rows

    plans = [_plan(0, [(100, 0)], flipped=True), _plan(1, [])]
    result = PipelineResult(Funscript(), plans)
    assert [s["flipped"] for s in debug_data(result)["scenes"]] == [True, False]
    col = SCENE_COLUMNS.index(FLIP_COLUMN)
    assert [r[col] for r in scene_rows(result)] == ["⇅ 已反轉", "-"]
    json.dumps(debug_data(result))
