"""The scripts: the maintained ones in scripts/ import and show their help; every one (also scripts/experiments/) is
at least valid Python."""

import ast
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
MAINTAINED = sorted(p for p in SCRIPTS.glob("*.py"))


@pytest.mark.parametrize("path", sorted(SCRIPTS.rglob("*.py")), ids=lambda p: str(p.relative_to(SCRIPTS)))
def test_every_script_is_valid_python(path):
    ast.parse(path.read_text(encoding="utf-8"), str(path))


def test_the_maintained_scripts_are_listed_in_the_development_guide():
    guide = (SCRIPTS.parent / "DEVELOPMENT.md").read_text(encoding="utf-8")
    missing = [p.name for p in MAINTAINED if p.name not in guide]
    assert not missing, f"scripts/ has {missing} that DEVELOPMENT.md does not mention: describe them, or move them to scripts/experiments/"


def test_ai_regress_compares_boxes_by_overlap():
    import importlib.util
    from types import SimpleNamespace as Box

    spec = importlib.util.spec_from_file_location("ai_regress", SCRIPTS / "ai_regress.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    a = Box(x1=0.0, y1=0.0, x2=0.5, y2=0.5)
    assert mod.iou(a, a) == 1.0
    assert mod.same_box(a, Box(x1=0.05, y1=0.0, x2=0.5, y2=0.5)) and not mod.same_box(a, Box(x1=0.4, y1=0.4, x2=0.9, y2=0.9))
    assert mod.same_box(None, None) and not mod.same_box(a, None)
    assert mod.compare(Box(motion="still", ref_a="hip"), Box(motion="still", ref_a="knee"), ("motion", "ref_a")) == {
        "motion": True, "ref_a": False}
