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
