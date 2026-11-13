import os

import pytest

os.environ["FUNSCRIPT_GEN_LANG"] = "zh-TW"  # the tests check the source language's texts

from funscript_gen import i18n, pipeline  # noqa: E402

REAL_DETECT_RANGES = pipeline._detect_ranges
REAL_PICK_CONTACTS = pipeline._pick_contacts


@pytest.fixture(autouse=True)
def no_range_calls(monkeypatch):
    """Stroke range detection is on by default; keep it from reaching a real AI backend in tests."""
    monkeypatch.setattr(pipeline, "_detect_ranges", lambda scenes, workers, settings, tick=None: [(None, "off in tests")] * len(scenes))


@pytest.fixture(autouse=True)
def no_contact_calls(monkeypatch):
    """The contact pick is on by default in hybrid focus; keep it from reaching a real AI backend in tests."""
    monkeypatch.setattr(pipeline, "_pick_contacts", lambda plans, workers, settings, fmt, min_prob: None)


@pytest.fixture(autouse=True)
def no_part_cache(monkeypatch):
    """Keep the part boxes of test videos (and of fake detectors) out of the user's cache."""
    from funscript_gen.tracking import parts

    monkeypatch.setattr(parts, "CACHE_DIR", None)


@pytest.fixture(autouse=True)
def source_language():
    """Every test starts in zh-TW, whatever language an earlier test chose."""
    i18n.set_language("zh-TW")


@pytest.fixture(autouse=True)
def no_hash_cache(monkeypatch, tmp_path_factory):
    """Keep the content hashes of test videos out of the user's cache."""
    from funscript_gen import fileid

    monkeypatch.setattr(fileid, "CACHE_DIR", tmp_path_factory.mktemp("hashes"))
