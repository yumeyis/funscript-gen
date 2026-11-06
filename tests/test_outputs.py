import os
import time

from funscript_gen.outputs import OutputStore, human_size


def _run(root, name, age_days=0.0, size=10):
    d = root / name
    d.mkdir(parents=True)
    (d / "a.funscript").write_bytes(b"x" * size)
    t = time.time() - age_days * 86400
    os.utime(d, (t, t))
    return d


def test_purge_by_age_keeps_recent_and_unrelated(tmp_path):
    root = tmp_path / "out"
    old = _run(root, "20260101-120000", age_days=10)
    new = _run(root, "20261028-120000", age_days=1)
    other = _run(root, "keep-me", age_days=100)  # not a job folder: never deleted
    store = OutputStore(root, tmp_path / "cleanup.json")
    assert store.usage().runs == 2 and store.usage().bytes == 20
    freed = store.purge(7)
    assert (freed.runs, freed.bytes) == (1, 10)
    assert not old.exists() and new.exists() and other.exists()


def test_purge_all(tmp_path):
    root = tmp_path / "out"
    _run(root, "20261028-120000")
    _run(root, "20261028-120001")
    store = OutputStore(root, tmp_path / "cleanup.json")
    assert store.purge(None).runs == 2
    assert store.usage().runs == 0 and root.is_dir()


def test_retention_setting(tmp_path):
    root = tmp_path / "out"
    old = _run(root, "20260101-120000", age_days=10)
    store = OutputStore(root, tmp_path / "cleanup.json")
    assert store.retention_days == 0
    assert store.purge_expired().runs == 0 and old.exists()  # 0 = keep forever
    store.set_retention_days(3)
    assert OutputStore(root, tmp_path / "cleanup.json").retention_days == 3
    assert store.purge_expired().runs == 1 and not old.exists()


def test_missing_root_and_bad_config(tmp_path):
    cfg = tmp_path / "cleanup.json"
    cfg.write_text("not json")
    store = OutputStore(tmp_path / "nope", cfg)
    assert store.retention_days == 0 and store.usage().runs == 0 and store.purge(None).runs == 0


def test_auto_cleanup_runs_immediately(tmp_path):
    root = tmp_path / "out"
    old = _run(root, "20260101-120000", age_days=10)
    store = OutputStore(root, tmp_path / "cleanup.json")
    store.set_retention_days(1)
    stop = store.start_auto_cleanup(interval_s=60)
    for _ in range(50):
        if not old.exists():
            break
        time.sleep(0.02)
    stop.set()
    assert not old.exists()


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(2048) == "2.0 KB"
    assert human_size(5 * 1024**3) == "5.0 GB"


def test_files_and_find(tmp_path):
    root = tmp_path / "out"
    _run(root, "20261027-120000")
    newer = _run(root, "20261028-120000")
    (tmp_path / "secret.txt").write_text("no")
    store = OutputStore(root, tmp_path / "cleanup.json")
    files = store.files()
    assert [f.parent.name for f in files] == ["20261028-120000", "20261027-120000"]  # newest first
    assert store.find("20261028-120000", "a.funscript") == newer / "a.funscript"
    assert store.find("20261028-120000", "../../secret.txt") is None
    assert store.find("..", "secret.txt") is None
    assert store.find("20261028-120000", "missing.funscript") is None
