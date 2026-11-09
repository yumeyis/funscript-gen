"""Multi-axis funscripts: names, kinds of files, merging, splitting and the safe writing of the results."""

import json

import pytest

from funscript_gen import multiaxis as ma


def script(path, actions, **header):
    data = {"version": "1.0", "range": 100, "metadata": {"title": "t"}, **header, "actions": actions}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def acts(*pairs):
    return [{"at": at, "pos": pos} for at, pos in pairs]


@pytest.fixture
def separate(tmp_path):
    """video.funscript with roll, surge and a lube axis beside it."""
    script(tmp_path / "video.funscript", acts((0, 10), (500, 90)))
    script(tmp_path / "video.roll.funscript", acts((0, 50), (500, 60)))
    script(tmp_path / "video.surge.funscript", acts((0, 20)))
    script(tmp_path / "video.lube.funscript", acts((100, 30)))
    return tmp_path


def test_the_axis_of_a_file_name():
    assert ma.split_name("a.roll.funscript") == ("a", "R1")
    assert ma.split_name("dir/My Clip.Valve.json") == ("My Clip", "A0")  # any case, .json too
    assert ma.split_name("a.funscript") == ("a", None)
    assert ma.split_name("roll.funscript") == ("roll", None)  # a name that is only the suffix is a name
    assert ma.split_name("a.b.funscript") == ("a.b", None)
    assert [ma.AXIS_SUFFIX[a] for a in ("L1", "L2", "R0", "R1", "R2", "V0", "V1", "A0", "A1", "A2")] == [
        "surge", "sway", "twist", "roll", "pitch", "vib", "pump", "valve", "suck", "lube"]


def test_separate_files_are_a_merge(separate):
    plan = ma.classify(sorted(separate.iterdir()))
    assert plan.kind == "merge" and plan.problems == []
    (s,) = plan.sets
    assert s.name == "video" and list(s.axes) == ["L1", "R1", "A2"]  # the order of the axes, not of the files
    data = ma.merge(s)
    assert list(data) == ["version", "range", "metadata", "actions", "axes"]
    assert data["actions"] == acts((0, 10), (500, 90))
    assert [a["id"] for a in data["axes"]] == ["L1", "R1", "A2"] and data["axes"][1]["actions"] == acts((0, 50), (500, 60))


def test_a_file_with_axes_is_a_split(tmp_path):
    merged = script(tmp_path / "clip_merged.funscript", acts((0, 1)), axes=[
        {"id": "r1", "actions": acts((0, 5))}, {"id": "L1", "actions": acts((0, 7))}, {"id": "X9", "actions": []}])
    plan = ma.classify([merged])
    assert plan.kind == "split" and plan.problems == [("unknown_axis", "X9")]
    files = ma.split(plan.sets[0])
    assert [name for name, _ in files] == ["clip.funscript", "clip.surge.funscript", "clip.roll.funscript"]
    assert files[0][1]["actions"] == acts((0, 1)) and "axes" not in files[0][1]
    assert files[2][1]["actions"] == acts((0, 5)) and files[2][1]["metadata"] == {"title": "t"}


def test_merge_then_split_gives_the_files_back(separate, tmp_path):
    out = tmp_path / "out"
    merged = ma.classify(sorted(separate.iterdir()))
    (w,) = [w for w in ma.write_plan(merged, out, False)]
    again = ma.classify([w.path])
    assert again.kind == "split"
    ma.write_plan(again, out / "back", False)
    for name in ("video.funscript", "video.roll.funscript", "video.surge.funscript", "video.lube.funscript"):
        assert json.loads((out / "back" / name).read_text("utf-8"))["actions"] == json.loads((separate / name).read_text("utf-8"))["actions"]


def test_the_header_of_the_main_file_is_kept_and_actions_stay_as_written(tmp_path):
    main = script(tmp_path / "v.funscript", [{"at": 5, "pos": 1, "extra": True}, {"at": 1, "pos": 2}], inverted=True,
                  creator="me")
    script(tmp_path / "v.pitch.funscript", acts((0, 1)), creator="other")
    data = ma.merge(ma.classify([main, tmp_path / "v.pitch.funscript"]).sets[0])
    assert data["inverted"] is True and data["creator"] == "me"
    assert data["actions"] == [{"at": 5, "pos": 1, "extra": True}, {"at": 1, "pos": 2}]  # not sorted, not trimmed


def test_dumps_puts_each_actions_array_on_one_line():
    text = ma.dumps({"version": "1.1", "actions": acts((0, 1), (2, 3)), "axes": [{"id": "L1", "actions": acts((4, 5))}],
                     "metadata": {"tags": ["a", "ü"]}})
    assert '"actions": [{"at":0,"pos":1},{"at":2,"pos":3}],' in text
    assert '"actions": [{"at":4,"pos":5}]' in text and "ü" in text
    assert json.loads(text)["axes"][0]["id"] == "L1"
    assert ma.dumps({"actions": [], "metadata": {}}) == '{\n  "actions": [],\n  "metadata": {}\n}'


def test_files_without_axes_and_unusable_files(tmp_path):
    a, b = script(tmp_path / "a.funscript", acts((0, 1))), script(tmp_path / "b.funscript", acts((0, 1)))
    assert ma.classify([a, b]).kind == "single"
    bad = tmp_path / "bad.funscript"
    bad.write_text("{not json", encoding="utf-8")
    plan = ma.classify([bad])
    assert plan.kind == "none" and plan.problems[0][0] == "unreadable" and plan.problems[0][1].startswith("bad.funscript\t")
    assert ma.classify([]).kind == "none"
    # axis files without their main file, and a plain script among the files of another
    roll = script(tmp_path / "c.roll.funscript", acts((0, 1)))
    plan = ma.classify([roll, a])
    assert plan.kind == "none" and ("no_main", "c") in plan.problems
    script(tmp_path / "a.sway.funscript", acts((0, 1)))
    plan = ma.classify([a, tmp_path / "a.sway.funscript", b])
    assert plan.kind == "merge" and ("ignored", "b.funscript") in plan.problems
    broken = tmp_path / "d.funscript"
    broken.write_text(json.dumps({"actions": [{"at": 1}]}), encoding="utf-8")
    plan = ma.classify([broken, script(tmp_path / "d.roll.funscript", acts((0, 1)))])
    assert plan.kind == "none" and plan.problems[0][0] == "unreadable"  # an action without a position


def test_a_merged_file_wins_over_loose_files(separate, tmp_path):
    merged = script(tmp_path / "m.funscript", acts((0, 1)), axes=[{"id": "L2", "actions": acts((0, 2))}])
    plan = ma.classify([separate / "video.funscript", merged, separate / "video.roll.funscript"])
    assert plan.kind == "split" and [s.name for s in plan.sets] == ["m"]
    assert ("ignored", "video.funscript") in plan.problems and ("ignored", "video.roll.funscript") in plan.problems


def test_scripts_are_grouped_by_name_case_insensitively(tmp_path):
    a = script(tmp_path / "Clip.funscript", acts((0, 1)))
    b = script(tmp_path / "clip.ROLL.funscript", acts((0, 2)))
    c = script(tmp_path / "other.funscript", acts((0, 3)))
    d = script(tmp_path / "other.twist.json", acts((0, 4)))
    plan = ma.classify([a, b, c, d])
    assert plan.kind == "merge" and [(s.name, list(s.axes)) for s in plan.sets] == [("Clip", ["R1"]), ("other", ["R0"])]


def test_the_files_beside_a_script_are_found(separate):
    (separate / "other.funscript").write_text("{}")
    (separate / "video.Sway.json").write_text(json.dumps({"actions": []}))
    (separate / "video.sway.funscript").write_text(json.dumps({"actions": []}))
    (separate / "video.mp4").write_text("")
    found = ma.find_axis_files(separate / "video.funscript")
    assert list(found) == ["L1", "L2", "R1", "A2"] and found["L2"].name == "video.sway.funscript"  # .funscript first
    assert ma.find_axis_files(separate / "video.roll.funscript") == found  # from any file of the script
    assert ma.find_axis_files(separate / "nobody" / "x.funscript") == {}
    assert ma.find_main_file(separate / "video.roll.funscript") == separate / "video.funscript"
    assert ma.find_main_file(separate / "other.funscript") == separate / "other.funscript"
    (separate / "video.funscript").unlink()
    assert ma.find_main_file(separate / "video.roll.funscript") is None


def test_expand_brings_the_other_files_once(separate, tmp_path):
    main, roll = separate / "video.funscript", separate / "video.roll.funscript"
    names = lambda files: [f.name for f in files]
    assert names(ma.expand([main])) == ["video.funscript", "video.surge.funscript", "video.roll.funscript", "video.lube.funscript"]
    assert names(ma.expand([roll])) == ["video.roll.funscript", "video.funscript", "video.surge.funscript", "video.lube.funscript"]
    assert names(ma.expand([main, roll])) == ["video.funscript", "video.roll.funscript", "video.surge.funscript", "video.lube.funscript"]
    merged = script(tmp_path / "m.funscript", [], axes=[{"id": "L1", "actions": []}])
    script(tmp_path / "m.roll.funscript", [])
    assert ma.expand([merged]) == [merged]  # a one-file script has all its axes
    lone = script(tmp_path / "lone.funscript", [])
    assert ma.expand([lone, tmp_path / "gone.funscript"]) == [lone, tmp_path / "gone.funscript"]


def test_load_separate_adds_files_to_the_axes_of_a_merged_main(tmp_path):
    main = script(tmp_path / "v.funscript", acts((0, 1)), axes=[{"id": "L1", "actions": acts((0, 2))}])
    roll = script(tmp_path / "v.roll.funscript", acts((0, 3)))
    other = script(tmp_path / "x.funscript", acts((0, 4)))  # names no axis: skipped
    s = ma.load_separate(main, [roll, other])
    assert list(s.axes) == ["L1", "R1"] and s.sources == [main, roll]
    main_fs, axes = s.funscripts()
    assert [a.pos for a in main_fs.actions] == [1] and axes["R1"].actions[0].pos == 3


def test_funscripts_for_the_preview_are_sorted_and_clamped(tmp_path):
    s = ma.ScriptSet("v", {"range": 100}, acts((20, 50), (10, 150)), {"R1": acts((5, -3))})
    main, axes = s.funscripts()
    assert [(a.at, a.pos) for a in main.actions] == [(10, 100), (20, 50)] and axes["R1"].actions[0].pos == 0
    with pytest.raises(ValueError):
        ma.parse_actions([{"at": 1}])


def test_writing_keeps_a_backup_or_replaces(tmp_path):
    target = tmp_path / "v.funscript"
    target.write_text("old", encoding="utf-8")
    first = ma.write_script(target, {"actions": []}, keep_backup=True)
    assert first.backup == tmp_path / "v.funscript.backup" and first.backup.read_text() == "old"
    second = ma.write_script(target, {"actions": [{"at": 1, "pos": 2}]}, keep_backup=True)
    assert second.backup == tmp_path / "v.funscript.backup2"  # the first backup is not touched
    assert first.backup.read_text() == "old" and second.backup.read_text() == '{\n  "actions": []\n}'
    third = ma.write_script(target, {"actions": []}, keep_backup=False)
    assert third.backup is None and not list(tmp_path.glob("*.tmp")) and len(list(tmp_path.glob("*.backup*"))) == 2
    fresh = ma.write_script(tmp_path / "sub" / "dir" / "n.funscript", {"actions": []}, keep_backup=True)
    assert fresh.backup is None and fresh.path.is_file()  # nothing there: no backup, the folder is made


def test_direct_output_writes_beside_the_originals(separate):
    plan = ma.classify(sorted(separate.iterdir()))
    (w,) = ma.write_plan(plan, None, keep_backup=True)
    assert w.path == separate / "video.funscript" and w.backup == separate / "video.funscript.backup"
    assert json.loads(w.backup.read_text("utf-8"))["actions"] == acts((0, 10), (500, 90))  # the original main file
    assert [a["id"] for a in json.loads(w.path.read_text("utf-8"))["axes"]] == ["L1", "R1", "A2"]
    assert (separate / "video.roll.funscript").is_file()  # the axis files stay


def test_splitting_in_place_replaces_the_merged_file(tmp_path):
    merged = script(tmp_path / "video.funscript", acts((0, 1)), axes=[{"id": "R1", "actions": acts((0, 2))}])
    written = ma.write_plan(ma.classify([merged]), None, keep_backup=True)
    assert [w.path.name for w in written] == ["video.funscript", "video.roll.funscript"]
    assert written[0].backup.name == "video.funscript.backup" and "axes" in json.loads(written[0].backup.read_text("utf-8"))
    assert "axes" not in json.loads(merged.read_text("utf-8"))


def test_two_scripts_with_one_name_cannot_share_a_folder(tmp_path):
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
        script(tmp_path / d / "v.funscript", [])
        script(tmp_path / d / "v.roll.funscript", [])
    plan = ma.classify([tmp_path / d / n for d in "ab" for n in ("v.funscript", "v.roll.funscript")])
    # grouped by name, so both folders' files make one script; a folder given for the output holds one file for it
    assert len(plan.sets) == 1
    assert len(ma.write_plan(plan, tmp_path / "out", False)) == 1
