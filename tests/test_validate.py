import json

import numpy as np
import pytest

from funscript_gen import validate
from funscript_gen.export.funscript import Action, Funscript


def _manifest(tmp_path, configs=None) -> dict:
    d = tmp_path / "clips"
    d.mkdir()
    for name in ("a1-女上.mp4", "a1-女上.funscript", "b2.mp4", "b2.funscript", "c3.mp4"):
        (d / name).write_bytes(b"")
    text = 'clips_dir = "clips"\n[groups]\ndev = ["a1"]\ntest = ["b2"]\n[configs]\n'
    text += "\n".join(f"{k} = {json.dumps(v)}" for k, v in (configs or {"default": []}).items()) + "\n"
    (tmp_path / "validation.toml").write_text(text)
    return validate.load_manifest(tmp_path / "validation.toml")


def test_clips_are_found_by_name_or_group(tmp_path):
    m = _manifest(tmp_path)
    assert [(c.name, c.group, c.video.name) for c in validate.clips(m, "all", tmp_path)] == \
        [("a1", "dev", "a1-女上.mp4"), ("b2", "test", "b2.mp4")]
    assert [c.name for c in validate.clips(m, "test,a1", tmp_path)] == ["b2", "a1"]
    with pytest.raises(ValueError, match="unknown"):
        validate.clips(m, "zz", tmp_path)
    assert [c.name for c in validate.clips(m, "", tmp_path)] == ["a1", "b2"]
    m["default_clips"] = ["dev"]  # a held-out group stays out unless named
    assert [c.name for c in validate.clips(m, "", tmp_path)] == ["a1"]
    assert [c.name for c in validate.clips(m, "all", tmp_path)] == ["a1", "b2"]
    m["groups"]["dev"].append("c3")  # a video without a hand-made script
    with pytest.raises(ValueError, match="c3"):
        validate.clips(m, "dev", tmp_path)


def test_clips_named_by_alias_use_the_private_names_file(tmp_path):
    m = _manifest(tmp_path)
    assert "clip_files" not in m
    (tmp_path / "clips" / "real7-後入.mp4").write_bytes(b"")
    (tmp_path / "clips" / "real7.funscript").write_bytes(b"")
    (tmp_path / validate.PRIVATE_NAMES).write_text('[clips]\nX07 = "real7"\n')
    m = validate.load_manifest(tmp_path / "validation.toml")
    m["groups"]["test"].append("X07")
    assert [(c.name, c.video.name, c.reference.name) for c in validate.clips(m, "test", tmp_path)] == \
        [("b2", "b2.mp4", "b2.funscript"), ("X07", "real7-後入.mp4", "real7.funscript")]


def _wave(inverted=False, hz=1.5, seconds=20.0):
    t = np.arange(0, seconds * 1000, 1000 / (2 * hz))
    return Funscript([Action(int(a), (0 if k % 2 else 100) if inverted else (100 if k % 2 else 0))
                      for k, a in enumerate(t)])


def test_scores_show_an_upside_down_script(tmp_path):
    ref, inv = tmp_path / "ref.funscript", tmp_path / "out.funscript"
    _wave().save(ref)
    _wave(inverted=True).save(inv)
    (tmp_path / "out.debug.json").write_text(json.dumps({"scenes": [
        {"start_ms": 0, "end_ms": 10000, "mode": "flow", "rest": False, "skip": False},
        {"start_ms": 10000, "end_ms": 20000, "mode": "flow", "rest": False, "skip": False}]}))
    s = validate.score(ref, inv, tmp_path / "out.debug.json")
    assert s["f1"] == 0 and s["r500"] > 0.9  # the old +-500 ms lag search hides it
    assert s["r100"] < -0.5 and s["sign_ok"] == 0 and s["sign_n"] == 2 and s["scene_r"] < -0.9
    same = validate.score(ref, ref, tmp_path / "out.debug.json")
    assert same["f1"] == 1 and same["sign_ok"] == 2 and same["scenes"][0]["near_150"] == 1
    assert same["sha"] != s["sha"] and same["sha"] == validate.actions_sha(Funscript.load(ref))


def test_upright_scores_ignore_the_direction(tmp_path):
    ref, out = tmp_path / "ref.funscript", tmp_path / "out.funscript"
    _wave().save(ref)
    up, down = _wave(), _wave(inverted=True)
    Funscript([a for a in up.actions if a.at < 10000] + [a for a in down.actions if a.at >= 10000]).save(out)
    scenes = [{"start_ms": 0, "end_ms": 10000, "mode": "flow", "rest": False, "skip": False},
              {"start_ms": 10000, "end_ms": 20000, "mode": "flow", "rest": False, "skip": False}]
    (tmp_path / "out.debug.json").write_text(json.dumps({"scenes": scenes}))
    s = validate.score(ref, out, tmp_path / "out.debug.json")
    assert s["f1"] < 0.6 and s["sign_ok"] == 1  # the second scene is upside down
    assert s["f1_upright"] == 1 and s["r_upright"] > 0.99
    assert "F1u" in validate.summary({"default": {"args": [], "clips": {"a1": s}}})


def _merged(f1):
    return {"default": {"args": [], "clips": {"a1": {"f1": f1, "f1_strokes": f1, "r500": 0.5, "r100": 0.4,
                                                    "sign_ok": 1, "sign_n": 2, "sha": f"s{f1}"}}}}


def test_summary_and_comparison(tmp_path):
    m = _manifest(tmp_path)
    text = validate.summary(_merged(0.8), m)
    assert "a1" in text and "mean dev" in text and "1/2" in text
    diff = validate.comparison(_merged(0.9), _merged(0.8), m)
    assert "+0.100" in diff and "0/1 clips with identical actions" in diff and "F1 up 1, down 0" in diff
    assert "1/1 clips with identical actions" in validate.comparison(_merged(0.8), _merged(0.8), m)


def test_a_run_generates_scores_and_resumes(tmp_path):
    from test_parallel import _clip

    m = _manifest(tmp_path, {"noai": ["--no-ai", "--no-asym-audio"]})
    m["groups"] = {"dev": ["a1"]}
    _clip(tmp_path / "clips" / "a1-女上.mp4", seconds=4.0)
    _wave(seconds=4.0).save(tmp_path / "clips" / "a1-女上.funscript")
    (tmp_path / "validation.toml").write_text(
        'clips_dir = "clips"\n[groups]\ndev = ["a1"]\n[configs]\nnoai = ["--no-ai", "--no-asym-audio"]\n'
        'noai-shape = ["--no-ai", "--no-asym-audio", "--dwell", "--curve"]\n'
        'noai-320 = ["--no-ai", "--no-asym-audio", "--flow-width", "320"]\n')
    lines = []
    run = validate.run_validation("r1", ["noai"], "all", jobs=1, flow_workers=1,
                                  manifest_path=tmp_path / "validation.toml", runs_dir=tmp_path / "runs",
                                  say=lines.append)
    got = run.results["configs"]["noai"]["clips"]["a1"]
    assert "error" not in got and got["actions"] > 0 and got["scenes"] and len(lines) == 1
    assert (run.path / "noai" / "a1.funscript").exists() and (run.path / "code" / "funscript_gen" / "cli.py").exists()
    meta = json.loads((run.path / "run.json").read_text())
    assert meta["code"]["code"] and meta["configs"] == {"noai": ["--no-ai", "--no-asym-audio"]}
    with pytest.raises(ValueError, match="exists"):
        validate.run_validation("r1", ["noai"], manifest_path=tmp_path / "validation.toml", runs_dir=tmp_path / "runs")
    lines.clear()
    validate.run_validation("r1", ["noai"], resume=True, manifest_path=tmp_path / "validation.toml",
                            runs_dir=tmp_path / "runs", say=lines.append)
    assert lines == []  # nothing left to do
    assert (run.path / "noai" / "a1.analysis.pkl").exists()

    # replay: the saved analysis rendered again gives the same script; other output settings need no new analysis
    validate.run_validation("r1-shape", ["noai-shape"], jobs=1, flow_workers=1, manifest_path=tmp_path / "validation.toml",
                            runs_dir=tmp_path / "runs", say=lines.append)
    replayed = validate.run_validation("r2", ["noai", "noai-shape", "noai-320"], jobs=1,
                                       manifest_path=tmp_path / "validation.toml", runs_dir=tmp_path / "runs",
                                       say=lines.append, replay=run.path)
    full_shape = json.loads((tmp_path / "runs" / "r1-shape" / "results.json").read_text())["configs"]["noai-shape"]
    clips = {c: v["clips"]["a1"] for c, v in replayed.results["configs"].items()}
    assert clips["noai"]["sha"] == got["sha"] and clips["noai-shape"]["sha"] == full_shape["clips"]["a1"]["sha"]
    assert "no analysis" in clips["noai-320"]["error"]  # another flow width needs the video analysed again
    # a replay renders with this checkout's code, so another package is refused rather than recorded as the code run
    with pytest.raises(ValueError, match="--code"):
        validate.run_validation("r3", ["noai"], manifest_path=tmp_path / "validation.toml", runs_dir=tmp_path / "runs",
                                replay=run.path, code=run.path / "code")


def test_older_results_are_read_with_the_new_names(tmp_path):
    run = tmp_path / "old"
    run.mkdir()
    (run / "results.json").write_text(json.dumps({"configs": {"default": {"args": [], "clips": {
        "a1": {"f1": 0.9, "f1_strokes": 0.9, "corr": 0.6, "corr_100": 0.5, "sha": "x"}}}}}))
    merged, _ = validate.load_runs([run])
    assert merged["default"]["clips"]["a1"]["r500"] == 0.6 and merged["default"]["clips"]["a1"]["r100"] == 0.5


def test_score_skips_stretches_with_no_flow_and_no_part_boxes(tmp_path):
    import json

    from funscript_gen.export.funscript import Action, Funscript
    from funscript_gen.validate import ignore_spans, score

    flat = [0.0] * 30
    moving = [float(v) for v in range(-15, 15)]
    scenes = [
        {"start_ms": 0, "end_ms": 4000, "raw": moving, "parts_found": False, "mode": "flow"},
        {"start_ms": 4000, "end_ms": 8000, "raw": flat, "parts_found": False, "mode": "flow"},
        {"start_ms": 8000, "end_ms": 12000, "raw": flat, "parts_found": True, "mode": "flow"},
    ]
    assert ignore_spans(scenes) == [(4000.0, 8000.0)]
    assert ignore_spans([{**scenes[1]} | {"raw": None}]) == []
    strokes = lambda times: Funscript([Action(t, 100 if i % 2 else 0) for i, t in enumerate(times)])  # noqa: E731
    ref = strokes([0, 1000, 2000, 3000, 4000, 4500, 5000, 5500, 6000, 6500, 7000, 8000, 9000, 10000, 11000])
    pred = strokes([0, 1000, 2000, 3000, 8000, 9000, 10000, 11000])
    ref.save(tmp_path / "ref.funscript")
    pred.save(tmp_path / "out.funscript")
    (tmp_path / "debug.json").write_text(json.dumps({"scenes": scenes}))
    got = score(tmp_path / "ref.funscript", tmp_path / "out.funscript", tmp_path / "debug.json", True)
    assert got["f1"] > got["f1_noign"] and got["ignored_s"] == 4
    off = score(tmp_path / "ref.funscript", tmp_path / "out.funscript", tmp_path / "debug.json")
    assert off["f1"] == got["f1_noign"] and off["ignored_s"] == 0


def test_bootstrap_resamples_source_series():
    assert validate.series_of("AF02") == "AF" and validate.series_of("B03") == "B"
    assert validate.bootstrap_delta({"A01": 0.1, "B01": 0.1}) is None  # two series: too few
    mean, lo, hi, n = validate.bootstrap_delta({"A01": 0.1, "A02": 0.1, "B01": 0.1, "C01": 0.1})
    assert n == 3 and (mean, lo, hi) == pytest.approx((0.1, 0.1, 0.1))
    mean, lo, hi, _ = validate.bootstrap_delta({f"{s}01": d for s, d in zip("ABCDEF", (0.3, -0.2, 0.1, -0.1, 0.0, 0.2))})
    assert lo < 0 < hi


def test_comparison_prints_an_interval_over_series():
    clips = {f"{s}01": {"f1": 0.5, "f1_strokes": 0.5, "r100": 0.4, "r500": 0.4, "f1_upright": 0.5, "sha": "x"} for s in "ABCD"}
    new = {"default": {"args": [], "clips": {c: dict(v, f1=0.6, sha="y") for c, v in clips.items()}}}
    text = validate.comparison(new, {"default": {"args": [], "clips": clips}}, None)
    assert "95% interval over source series" in text and "ΔF1 +0.100 [+0.100, +0.100]" in text


def test_review_cost_counts_the_checks_until_every_direction_is_right():
    def sc(conf, margin, r, marked=False):
        return {"confidence": conf, "sign_margin": margin, "r": r, "marked": marked}

    scenes = [sc("high", 0.9, 0.8), sc("low", 0.1, 0.5), sc("low", 0.3, -0.6), sc("medium", 0.5, -0.5),
              sc("high", 0.7, 0.4, marked=True), sc("", None, 0.9), sc("high", 0.9, -0.1)]
    # order: the marked one, then low by weak margin (0.1, 0.3), medium, high; the scene without confidence is left out
    # and |r| < 0.3 is not a clear direction. Wrong ones: the low 0.3 (position 3) and the medium (position 4).
    assert validate.review_cost(scenes) == {"fix_n": 2, "fix_checks": 4, "fix_top": 0, "review_n": 6}
    assert validate.review_cost([sc("high", 0.9, 0.8)]) == {"fix_n": 0, "fix_checks": 0, "fix_top": 0, "review_n": 1}
    assert validate._found([{"fix_top": 1, "fix_n": 2, "review_n": 6}, {"fix_top": 0, "fix_n": 3, "review_n": 3}]) == "1/5"
    assert validate._found({}) == "-"
