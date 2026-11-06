"""Language packs: loading, fallback, the template, and that no text is left in the code."""

import ast
import re
from pathlib import Path

import pytest

from funscript_gen import i18n

SRC = Path(i18n.__file__).parent
CJK = re.compile("[　-〿一-鿿＀-￯]")


def write(path: Path, code: str, name: str, texts: dict[str, str]) -> Path:
    i18n.write_pack(path, code, name, texts)
    return path


@pytest.fixture
def lang_dir(tmp_path, monkeypatch):
    """An external lang folder (FUNSCRIPT_GEN_LANG_DIR) for the test."""
    monkeypatch.setenv(i18n.ENV_DIR, str(tmp_path))
    monkeypatch.chdir(tmp_path)  # ./lang is not the repository's
    yield tmp_path
    i18n.available(rescan=True)


def test_builtin_packs_have_the_same_keys_and_placeholders():
    packs = i18n.available()
    assert {"zh-TW", "en"} <= set(packs)
    report = i18n.check(packs["en"])
    assert report.ok and not report.missing, (report.missing[:5], report.unknown[:5], report.placeholders[:5])
    assert i18n.check(packs["zh-TW"]).ok


def test_the_template_is_current():
    """lang/_template.toml is written from zh-TW and en: `funscript-gen lang template` when this fails."""
    packs = i18n.available()
    committed = i18n.load_pack(i18n.BUILTIN_DIR / i18n.TEMPLATE_NAME)
    assert committed.texts == {}  # every text is empty
    text = (i18n.BUILTIN_DIR / i18n.TEMPLATE_NAME).read_text(encoding="utf-8")
    keys = re.findall(r'^"([^"]+)" = ""$', text, re.M)
    assert keys == list(packs["zh-TW"].texts)
    for key in ("web.tab.gen", "opt.focus.info"):
        assert f"# zh-TW: {packs['zh-TW'].texts[key]}" in text and f"# en: {packs['en'].texts[key]}" in text


def test_a_text_comes_from_the_chosen_language_then_zh_tw_then_the_key(lang_dir):
    write(lang_dir / "xx.toml", "xx", "Test", {"web.tab.gen": "Erzeugen"})
    i18n.available(rescan=True)
    i18n.set_language("xx")
    assert i18n.t("web.tab.gen") == "Erzeugen"
    assert i18n.t("web.tab.batch") == "批次"  # not in the pack: zh-TW
    assert i18n.t("no.such.key") == "no.such.key"
    i18n.set_language("en")
    assert i18n.t("web.tab.gen") == "Generate"


def test_parameters_are_filled_and_unknown_ones_stay():
    i18n.set_language("en")
    assert i18n.t("app.start_failed", e="boom") == "funscript-gen could not start: boom"
    assert i18n.fill("a {x} b {y}", {"x": 1}) == "a 1 b {y}"
    assert i18n.fill("{{literal}}", {}) == "{{literal}}"  # without parameters the text is used as it is


def test_an_external_pack_is_listed_and_replaces_a_built_in_one(lang_dir):
    write(lang_dir / "fr.toml", "fr", "Français", {"web.tab.gen": "Générer"})
    write(lang_dir / "en.toml", "en", "English (mine)", {"web.tab.gen": "Make"})
    (lang_dir / "broken.toml").write_text("not = [valid", encoding="utf-8")
    packs = i18n.available(rescan=True)
    assert packs["fr"].name == "Français" and not packs["fr"].builtin
    assert packs["en"].name == "English (mine)"
    assert ("Français", "fr") in i18n.choices() and i18n.choices()[0][1] == "zh-TW"
    assert any("broken.toml" in e for e in i18n.errors())
    i18n.set_language("en")
    assert i18n.t("web.tab.gen") == "Make"


def test_empty_texts_count_as_missing(lang_dir):
    write(lang_dir / "xx.toml", "xx", "Test", {"web.tab.gen": "", "web.tab.batch": "Stapel"})
    pack = i18n.available(rescan=True)["xx"]
    assert "web.tab.gen" not in pack.texts and "web.tab.batch" in pack.texts
    assert "web.tab.gen" in i18n.check(pack).missing


def test_check_reports_unknown_keys_and_different_placeholders(lang_dir):
    write(lang_dir / "xx.toml", "xx", "Test", {"app.start_failed": "kaputt", "web.nonsense": "x"})
    report = i18n.check(i18n.available(rescan=True)["xx"])
    assert report.unknown == ["web.nonsense"] and report.placeholders == ["app.start_failed"] and not report.ok


@pytest.mark.parametrize("tag, found", [
    ("zh_TW.UTF-8", "zh-TW"), ("zh-tw", "zh-TW"), ("zh_CN", "zh-TW"), ("en_US.UTF-8", "en"), ("en-GB", "en"),
    ("fr_FR", None), ("C", None), ("POSIX", None), ("", None),
])
def test_a_locale_tag_matches_a_pack(tag, found):
    assert i18n.match(tag, ["zh-TW", "en"]) == found


def test_the_language_is_chosen_in_order(monkeypatch):
    monkeypatch.delenv(i18n.ENV_LANG, raising=False)
    monkeypatch.setattr(i18n, "system_tag", lambda: "fr_FR")
    assert i18n.resolve() == "en"  # nothing matches: English
    monkeypatch.setattr(i18n, "system_tag", lambda: "zh_TW.UTF-8")
    assert i18n.resolve() == "zh-TW"
    assert i18n.resolve(saved="en") == "en"  # a choice in the web UI beats the system
    monkeypatch.setenv(i18n.ENV_LANG, "zh-TW")
    assert i18n.resolve(saved="en") == "zh-TW"  # the environment beats it
    assert i18n.resolve("en", saved="zh-TW") == "en"  # --lang beats everything
    monkeypatch.setattr(i18n, "_preferred", "en")
    assert i18n.resolve() == "en"
    monkeypatch.setattr(i18n, "_preferred", None)


def test_the_cli_lists_and_checks_packs(lang_dir):
    from typer.testing import CliRunner

    from funscript_gen.cli import app

    runner = CliRunner()
    out = runner.invoke(app, ["lang", "list"])
    assert out.exit_code == 0 and "English" in out.output and "繁體中文" in out.output
    assert runner.invoke(app, ["lang", "check", str(i18n.BUILTIN_DIR / "en.toml")]).exit_code == 0
    write(lang_dir / "xx.toml", "xx", "Test", {"web.nonsense": "x"})
    bad = runner.invoke(app, ["lang", "check", str(lang_dir / "xx.toml")])
    assert bad.exit_code == 1 and "web.nonsense" in bad.output
    template = lang_dir / "t.toml"
    assert runner.invoke(app, ["lang", "template", str(template)]).exit_code == 0 and template.exists()


def test_the_option_texts_follow_the_language():
    from funscript_gen import options

    o = options.BY_NAME["focus"]
    assert o.label == "分析目標" and ("一般（兩人之間的動作）", "general") in o.choices
    i18n.set_language("en")
    assert o.label == "Analysis target" and ("General (the motion between the two people)", "general") in o.choices
    assert options.BY_NAME["axis"].choices[0] == ("AI decides", "")
    assert options.BY_NAME["gain"].short_label == "Stroke multiplier"
    assert all(o.label and o.label != o.name for o in options.UI_OPTIONS)
    with pytest.raises(options.OptionError) as e:
        options.build(options.resolve({"range_low": 90, "range_high": 10}))
    assert "range-low" in e.value.en and "lower limit" in e.value.local


def test_the_player_is_in_the_chosen_language():
    from funscript_gen.export.funscript import Action, Funscript
    from funscript_gen.preview import player_html

    script = Funscript([Action(0, 0), Action(500, 100)])
    zh = player_html("/media/x", script)
    i18n.set_language("en")
    en = player_html("/media/x", script)
    assert "上一個鏡頭" in zh and 'lang="zh-TW"' in zh and "Previous scene" in en and 'lang="en"' in en
    assert "上一個鏡頭" not in en and "@@" not in zh + en and "__I18N__" not in en
    assert '<span class="key">PageUp</span>' in en and "<k>" not in en  # key caps are drawn
    assert '"preview.js.selected":"{n} points selected"' in en


def test_the_web_ui_follows_a_language_change(tmp_path, monkeypatch):
    import gradio as gr

    from funscript_gen import webui as ui

    monkeypatch.setattr(ui, "_last_file", tmp_path / "last.json")
    monkeypatch.setattr(ui, "_cleanup_file", tmp_path / "cleanup.json")
    monkeypatch.setattr(ui, "OUTPUT_DIR", tmp_path / "out")
    demo = ui.build()
    components = ui.translated_components()
    tabs = {c.label: k for k, c in enumerate(components) if isinstance(c, gr.Tab)}
    assert list(tabs) == ["產生", "批次", "預覽", "輸出", "設定"]
    out = ui.pick_language("en")
    assert len(out) == len(components) + 5 and i18n.current() == "en"
    assert [out[k]["label"] for k in tabs.values()] == ["Generate", "Batch", "Preview", "Output", "Settings"]
    assert ui.saved_language() == "en"
    lang_list = out[len(components)]
    assert ("English", "en") in lang_list["choices"] and lang_list["value"] == "en"
    assert demo is not None


def _keys_used(tree: ast.AST) -> set[str]:
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("t", "tr", "L", "tt"):
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                used.add(arg.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("DeviceError", "OptionError"):
            for arg in node.args[1:2]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    used.add(arg.value)
    return used


def test_every_key_the_code_asks_for_is_in_the_source_pack():
    source = i18n.available()[i18n.SOURCE_LANG].texts
    missing = {}
    for path in sorted(SRC.rglob("*.py")):
        for key in _keys_used(ast.parse(path.read_text(encoding="utf-8"))):
            if key not in source:
                missing.setdefault(path.name, []).append(key)
    assert not missing
    from funscript_gen import preview

    tokens = set(re.findall(r"@@([\w.]+)@@", preview._PLAYER))
    assert tokens and tokens <= set(source), tokens - set(source)


def test_no_text_is_left_in_the_code():
    """User-visible text lives in the language packs; the only Chinese strings in the code are the ones that have to be."""
    allowed = ("語言 / Language", r"\s*[（(]", "<!doctype html>", "funscript-gen language pack template")
    found = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
                    and CJK.search(node.value) and not node.value.startswith(allowed)):
                found.append(f"{path.name}:{node.lineno} {node.value[:40]!r}")
    assert not found, found
