import os
import time

import pytest
from typer.testing import CliRunner

from funscript_gen import cache


def _fill(base):
    for name, n in (("ai", 3), ("parts", 2), ("huggingface", 1)):
        (base / name).mkdir(parents=True)
        for k in range(n):
            (base / name / f"{k}.json").write_text("x" * 100)
    old = base / "parts" / "0.json"
    os.utime(old, (time.time() - 40 * 86400,) * 2)


def test_usage_lists_every_folder_and_marks_the_clearable_ones(tmp_path):
    _fill(tmp_path)
    rows = {u.name: u for u in cache.usage(tmp_path)}
    assert (rows["ai"].files, rows["ai"].size, rows["ai"].clearable) == (3, 300, True)
    assert rows["huggingface"].clearable is False and rows["parts"].files == 2
    assert cache.usage(tmp_path / "nope") == []


def test_clear_deletes_only_clearable_caches_and_can_keep_the_recent_files(tmp_path):
    _fill(tmp_path)
    assert cache.clear(["parts"], older_than_days=30, base=tmp_path) == (1, 100)  # the 40-day-old one only
    assert sorted(p.name for p in (tmp_path / "parts").iterdir()) == ["1.json"]
    assert cache.clear(["ai", "parts"], base=tmp_path) == (4, 400)
    assert (tmp_path / "huggingface" / "0.json").exists() and (tmp_path / "ai").is_dir()
    with pytest.raises(ValueError, match="huggingface"):
        cache.clear(["huggingface"], base=tmp_path)


def test_cli_cache_commands(tmp_path, monkeypatch):
    from funscript_gen.cli import app

    monkeypatch.setenv("FUNSCRIPT_GEN_HOME", str(tmp_path))
    _fill(tmp_path / "cache")
    run = CliRunner().invoke
    info = run(app, ["cache", "info"])
    assert info.exit_code == 0 and "ai" in info.output and "not cleared" in info.output
    assert run(app, ["cache", "clear", "huggingface", "-y"]).exit_code != 0
    assert run(app, ["cache", "clear", "ai"], input="n\n").exit_code == 1  # asked, answered no
    assert (tmp_path / "cache" / "ai" / "0.json").exists()
    done = run(app, ["cache", "clear", "ai", "-y"])
    assert done.exit_code == 0 and "deleted 3 files" in done.output
