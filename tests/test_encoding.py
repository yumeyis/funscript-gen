"""Text files are always UTF-8: without encoding= Python uses the locale's code page on Windows (cp1252 on an
English system cannot write the Chinese notes, and reads other tools' UTF-8 files wrongly)."""
import ast
import json
from pathlib import Path

from funscript_gen.export.funscript import Funscript

SRC = Path(__file__).resolve().parents[1] / "src"


def _text_io_without_encoding(tree: ast.AST):
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or any(k.arg == "encoding" for k in n.keywords):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr in ("read_text", "write_text"):
            yield n
        elif isinstance(f, ast.Name) and f.id == "open":
            mode = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "mode"), None)
            if not (isinstance(mode, ast.Constant) and "b" in str(mode.value)):
                yield n


def test_every_text_file_is_opened_with_an_encoding():
    missing = [f"{p.relative_to(SRC)}:{n.lineno}" for p in sorted(SRC.rglob("*.py"))
               for n in _text_io_without_encoding(ast.parse(p.read_text(encoding="utf-8")))]
    assert missing == []


def test_a_funscript_with_a_bom_loads(tmp_path):
    path = tmp_path / "bom.funscript"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"actions": [{"at": 0, "pos": 10}]}).encode())
    assert Funscript.load(path).actions[0].pos == 10
