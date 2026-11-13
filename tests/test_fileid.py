import hashlib
import os

from funscript_gen import fileid
from funscript_gen.fileid import file_hash


def test_the_hash_is_the_content_s_and_is_kept_until_the_file_changes(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"abc" * 1000)
    want = hashlib.sha256(b"abc" * 1000).hexdigest()
    cache = tmp_path / "hashes"
    assert file_hash(video, cache) == want
    assert len(list(cache.iterdir())) == 1
    reads = []
    monkeypatch.setattr(fileid, "_digest", lambda p: reads.append(p) or "0" * 64)
    assert file_hash(video, cache) == want and not reads  # from the cache
    st = video.stat()
    video.write_bytes(b"xyz" * 1000)  # the same size: told apart by the time
    os.utime(video, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert file_hash(video, cache) == "0" * 64 and len(reads) == 1


def test_a_damaged_entry_is_hashed_again(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"abc")
    cache = tmp_path / "hashes"
    file_hash(video, cache)
    next(cache.iterdir()).write_text("half", encoding="ascii")
    assert file_hash(video, cache) == hashlib.sha256(b"abc").hexdigest()


def test_a_copy_elsewhere_has_the_same_hash(tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "sub" / "b.mp4"
    b.parent.mkdir()
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    assert file_hash(a) == file_hash(b)
