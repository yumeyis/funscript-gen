import html
import json
import re
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from funscript_gen.export.funscript import Action, Funscript
import numpy as np

from funscript_gen.pipeline import ScenePlan
from funscript_gen.preview import iframe, player_html, scene_regions
from funscript_gen.signal.process import analyze
from funscript_gen.video.scenes import Scene


def _data(doc: str) -> dict:
    return json.loads(re.search(r"const DATA = (\{.*?\});\n", doc).group(1))


def test_player_embeds_actions_reference_and_scenes():
    doc = player_html("/media/abc", Funscript([Action(100, 10), Action(50, 90)]), Funscript([Action(0, 50)]), [0, 5000.4])
    data = _data(doc)
    assert data["actions"] == [{"at": 50, "pos": 90}, {"at": 100, "pos": 10}]  # normalized order
    assert data["reference"] == [{"at": 0, "pos": 50}]
    assert data["scenes"] == [5000]  # the start at 0 is not a cut
    assert 'src="/media/abc"' in doc


def test_player_lists_the_editing_keys_and_speed_controls():
    doc = player_html("/media/abc", Funscript([Action(0, 0)]))
    help_box = re.search(r'<div id="help">(.*?)</div>', doc, re.S).group(1)
    for words in ("新增", "Insert", "刪除", "Delete", "復原", "幅度", "頂點", "儲存編輯"):
        assert words in help_box
    for ident in ("prevscene", "nextscene", "scaleup", "scaledown", "topval", "settop", "botval", "setbot", "slower",
                  "faster", "irate"):
        assert f'id="{ident}"' in doc


def test_player_keeps_volume_and_mute_for_the_next_player():
    # the player is rebuilt after a flip or a save; a new <video> would start at full volume again
    doc = player_html("/media/abc", Funscript([Action(0, 0)]))
    assert 'localStorage.getItem("funscript-gen-volume")' in doc
    assert 'localStorage.getItem("funscript-gen-muted")' in doc
    assert 'addEventListener("volumechange"' in doc


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_scene_scaling_centers_each_stroke_on_its_own_middle():
    doc = player_html("/media/abc", Funscript([Action(0, 0)]))
    fn = re.search(r"function strokeCenters.*?\n}\n", doc, re.S).group(0)
    cases = [[20, 50, 20, 50, 60, 90, 60, 90], [80, 80, 20], [0, 50, 100], [50, 50]]
    out = subprocess.run(["node", "-e", f"{fn}console.log(JSON.stringify({cases}.map(strokeCenters)))"],
                         capture_output=True, text=True, check=True).stdout
    # the low strokes stay around 35 and the high ones around 75 (not the scene's 55); a hold stays flat
    assert json.loads(out) == [[35, 35, 35, 45, 65, 75, 75, 75], [50, 50, 50], [25, 50, 75], [50, 50]]

@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_scene_tops_and_bottoms_are_set_and_the_points_between_follow():
    doc = player_html("/media/abc", Funscript([Action(0, 0)]))
    fns = "".join(re.search(rf"function {f}\(.*?\n}}\n", doc, re.S).group(0) for f in ("turns", "setTurns"))
    cases = [([20, 80, 30, 90, 10], 0, 5, "true", 70), ([20, 50, 80, 80, 20, 60, 90], 0, 7, "false", 40),
             ([10, 90, 10, 90, 10, 90], 2, 4, "true", 50), ([50, 50, 50], 0, 3, "true", 80)]
    calls = ",".join(f"setTurns({p}, {list(range(lo, hi))}, {top}, {v})" for p, lo, hi, top, v in cases)
    calls += ",setTurns([10, 50, 90, 10, 50, 90, 10], [1, 2, 5], true, 70)"  # selected actions, not a range
    out = subprocess.run(["node", "-e", f"{fns}console.log(JSON.stringify([{calls}]))"],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [
        [20, 70, 30, 70, 10],
        [40, 60, 80, 80, 40, 69, 90],  # the hold at 80 is one top; 50 and 60 keep their fraction of the stroke
        [10, 90, 10, 50, 10, 90],  # only the tops in the scene
        [50, 50, 50],  # no strokes, nothing to set
        [10, 40, 70, 10, 50, 70, 10],  # 50 at 4 is not selected and stays
    ]

@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_selected_actions_move_together_without_passing_the_others():
    doc = player_html("/media/abc", Funscript([Action(0, 0)]))
    fn = re.search(r"function moveLimits.*?\n}\n", doc, re.S).group(0)
    acts = [{"at": t, "pos": 0} for t in (100, 200, 300, 600, 700, 1000)]
    out = subprocess.run(["node", "-e", f"const acts = {json.dumps(acts)};{fn}"
                          "console.log(JSON.stringify([moveLimits([1, 2]), moveLimits([0, 4]), moveLimits([5])]))"],
                         capture_output=True, text=True, check=True).stdout
    # [1, 2] stays between 100 and 600; [0, 4] can reach 0 but not pass 600 or 1000; the last one has no right limit
    assert json.loads(out) == [[-99, 299], [-99, 99], [-299, None]]

def test_player_marks_the_scenes_to_check():
    scenes = [(0.0, 0, False), (2000.0, 1, False), (4000.0, 2, True)]
    data = _data(player_html("/media/abc", Funscript([Action(0, 0)]), scene_list=scenes, checks=[1, 2]))
    assert [(s["i"], s["check"], s["flipped"]) for s in data["scene_list"]] == [(0, False, False), (1, True, False),
                                                                                (2, True, True)]
    assert 'id="nextcheck"' in player_html("/media/abc", Funscript([Action(0, 0)]))  # hidden without checks (JS)


def test_scene_regions_name_the_flow_region_of_each_scene():
    t = np.arange(0, 3000, 33.0)
    sig = analyze(t, np.sin(t / 300))
    general = ScenePlan(Scene(0, 0.0, 3000.0), roi=(0.1, 0.2, 0.5, 0.6), signal=sig)
    whole = ScenePlan(Scene(1, 3000.0, 6000.0), signal=sig)
    hybrid = ScenePlan(Scene(2, 6000.0, 9000.0), roi=(0.3, 0.3, 0.6, 0.6), alt_roi=(0.0, 0.0, 1.0, 0.8),
                       decisions=[(6500.0, True), (8000.0, False)], signal=sig)
    skipped = ScenePlan(Scene(3, 9000.0, 12000.0), roi=(0.1, 0.1, 0.2, 0.2), skip=True)
    pose = ScenePlan(Scene(4, 12000.0, 15000.0), mode="pose", signal=sig)
    regions = scene_regions([general, whole, hybrid, skipped, pose])
    assert regions == {
        0: {"hybrid": False, "box": [0.1, 0.2, 0.5, 0.6]},
        1: {"hybrid": False, "box": None},  # the whole frame
        2: {"hybrid": True, "box": [0.3, 0.3, 0.6, 0.6], "alt": [0.0, 0.0, 1.0, 0.8], "dec": [[6500, 1], [8000, 0]]},
    }


def test_player_embeds_the_regions_by_scene_number():
    scenes = [(0.0, 0, False), (2000.0, 1, False)]
    doc = player_html("/media/abc", Funscript([Action(0, 0)]), scene_list=scenes,
                      regions={1: {"hybrid": False, "box": [0.1, 0.2, 0.5, 0.6]}})
    data = _data(doc)
    assert [s["region"] for s in data["scene_list"]] == [None, {"hybrid": False, "box": [0.1, 0.2, 0.5, 0.6]}]
    assert 'id="roi"' in doc and 'id="roion"' in doc  # the switch is hidden without regions (JS)
    # The overlay is a canvas over the video: it must not take the timeline canvases' opaque background (it hid the
    # video, black in a dark theme).
    roi_css = re.search(r"#roi \{([^}]*)\}", doc).group(1)
    assert "background: none" in roi_css


def test_player_escapes_untrusted_values():
    doc = player_html('/media/x"><script>alert(1)</script>', Funscript([Action(0, 0)]))
    assert "<script>alert(1)" not in doc
    framed = iframe(doc)
    assert framed.startswith('<iframe srcdoc="') and "<script>" not in framed  # whole document is attribute-escaped
    assert html.unescape(framed[len('<iframe srcdoc="'):framed.index('" style=')]) == doc


def test_media_route_serves_registered_files_with_range(tmp_path):
    from funscript_gen import webui

    f = tmp_path / "clip.mp4"
    f.write_bytes(bytes(range(256)) * 4)
    url = webui.register_media(f)
    assert webui.register_media(f) == url  # same file, same token

    client = TestClient(webui.create_app())
    full = client.get(url)
    assert full.status_code == 200 and len(full.content) == 1024
    part = client.get(url, headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == bytes(range(10, 20))
    assert client.get("/media/not-a-token").status_code == 404
    assert client.head(url).status_code == 200


def test_player_shows_the_other_axes_of_a_multi_axis_script():
    surge = Funscript([Action(0, 10), Action(1000, 90)])
    doc = player_html("/media/abc", Funscript([Action(0, 0)]), axes={"L1": surge, "R1": Funscript([Action(0, 50)])})
    data = _data(doc)
    assert [a["id"] for a in data["axes"]] == ["L1", "R1"]
    assert data["axes"][0]["label"] == "前後推移 (Surge)" and data["axes"][0]["actions"][1] == {"at": 1000, "pos": 90}
    assert data["main_label"] == "L0 上下衝程 (Stroke)"
    assert doc.count('<canvas class="axis"') == 2 and "點擊跳轉" in re.search(r'<canvas class="axis" title="([^"]*)"', doc).group(1)
    assert "@@" not in doc and "__AXES__" not in doc
    plain = player_html("/media/abc", Funscript([Action(0, 0)]))
    assert _data(plain)["axes"] == [] and '<canvas class="axis"' not in plain  # nothing changes for a single axis


def test_viewer_page_holds_every_axis_of_every_script():
    from funscript_gen import multiaxis as ma
    from funscript_gen.preview import axes_viewer_html, viewer_height

    sets = [ma.ScriptSet("a</script>", {}, [{"at": 0, "pos": 1}, {"at": 4000, "pos": 9}], {"R1": [{"at": 100, "pos": 5}]}),
            ma.ScriptSet("b", {}, [], {})]
    doc = axes_viewer_html(sets)
    data = json.loads(re.search(r"const DATA = (\{.*?\});\n", doc).group(1))
    assert [s["name"] for s in data["sets"]] == ["a</script>", "b"] and data["sets"][0]["duration"] == 4000
    assert [a["id"] for a in data["sets"][0]["axes"]] == ["L0", "R1"] and data["sets"][1]["axes"][0]["actions"] == []
    assert doc.count("</script>") == 1  # the name cannot end the script
    assert "拖曳平移" in doc and "@@" not in doc
    assert viewer_height(sets) > viewer_height(sets[:1]) > viewer_height([])


def test_the_player_gets_the_scenes_without_direction_evidence():
    from funscript_gen.export.funscript import Action, Funscript

    fs = Funscript([Action(0, 0), Action(500, 100)])
    html_ = player_html("v.mp4", fs, scene_list=[(0.0, 0, False), (1000.0, 1, False)], checks=[0], unsure=[1])
    assert '"check":true,"unsure":false' in html_ and '"check":false,"unsure":true' in html_


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_upside_down_mirrors_the_selected_actions_within_their_own_range():
    doc = player_html("/media/abc", Funscript([Action(0, 0)]))
    fn = re.search(r"function mirrorScene\(.*?\n}\n", doc, re.S).group(0)
    script = f"""
    let acts = [{{at: 0, pos: 10}}, {{at: 1, pos: 90}}, {{at: 2, pos: 30}}, {{at: 3, pos: 70}}, {{at: 4, pos: 5}}];
    let idx = [1, 2, 3], edits = 0, editing = false, snaps = 0;
    const target = () => ({{idx}}), setEditing = on => {{ editing = on; }}, snapshot = () => {{ snaps++; }},
          edited = () => {{ edits++; }};
    {fn}
    mirrorScene();
    const first = acts.map(a => a.pos);
    idx = [0]; mirrorScene();  // one action: nothing to turn
    idx = [2, 4]; acts[2].pos = 40; acts[4].pos = 40; mirrorScene();  // all equal: nothing to turn
    console.log(JSON.stringify([first, acts.map(a => a.pos), edits, snaps, editing]));
    """
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    # 90, 30, 70 lie within 30..90: mirrored around 60 they become 30, 90, 50; the ends outside stay
    assert out[0] == [10, 30, 90, 50, 5]
    assert out[1] == [10, 30, 40, 50, 40] and out[2] == 1 and out[3] == 1 and out[4] is True
