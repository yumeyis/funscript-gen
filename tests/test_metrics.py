import numpy as np

from funscript_gen.tracking.metrics import assign_pairs, to_signal
from funscript_gen.tracking.pose import Person, PoseFrame


def _person(track_id: int, cx: float, cy: float, h: float = 200.0) -> Person:
    kpts = np.tile([cx, cy], (17, 1)).astype(float)
    kpts[[5, 6]] = [cx, cy - 0.3 * h]  # shoulders above hips
    kpts[[11, 12]] = [cx, cy]
    box = np.array([cx - 40, cy - h / 2, cx + 40, cy + h / 2])
    return Person(track_id, box, kpts, np.ones(17))


def _frames(dy: np.ndarray, swap_ids_at: int | None = None) -> list[PoseFrame]:
    frames = []
    for i, d in enumerate(dy):
        a_id, b_id = 1, 2
        if swap_ids_at is not None and i >= swap_ids_at:
            a_id, b_id = 7, 8  # tracker lost and re-created both ids
        frames.append(PoseFrame(i * 33.3, 640, 480, [_person(b_id, 400, 240), _person(a_id, 200, 240 + d)]))
    return frames


def test_vertical_motion_recovered_by_auto_axis():
    t = np.arange(300)
    dy = 40 * np.sin(2 * np.pi * t / 30)
    track = assign_pairs(_frames(dy))
    sig, vec = to_signal(track, "auto")
    assert vec is not None
    assert abs(np.corrcoef(sig, dy)[0, 1]) > 0.99


def test_identity_kept_across_id_switch():
    t = np.arange(120)
    dy = 30 * np.sin(2 * np.pi * t / 30)
    track = assign_pairs(_frames(dy, swap_ids_at=60))
    rel_x = track.rel[:, 0]
    # A must stay the same physical person, so the x offset never flips sign
    assert np.all(np.sign(rel_x) == np.sign(rel_x[0]))


def test_missing_subject_is_nan():
    frames = _frames(np.zeros(10))
    frames[5].people = frames[5].people[:1]
    track = assign_pairs(frames)
    sig, _ = to_signal(track, "distance")
    assert np.isnan(sig[5]) and np.isfinite(sig[4])


def test_hips_out_of_frame_falls_back_to_one_group():
    frames = _frames(30 * np.sin(np.arange(90) / 5))
    for f in frames:
        for p in f.people:
            p.kconf[[11, 12]] = 0.05  # hips never visible
    track = assign_pairs(frames)
    assert track.refs[0] in ("torso", "shoulder") and track.refs[0] == track.refs[1]
    assert np.isfinite(track.rel).all()


def test_the_skeleton_mode_says_how_to_install_it(monkeypatch):
    import builtins

    import pytest

    from funscript_gen.tracking.pose import PoseTracker

    real = builtins.__import__

    def no_ultralytics(name, *args, **kwargs):
        if name == "ultralytics":
            raise ImportError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_ultralytics)
    with pytest.raises(RuntimeError, match="uv sync --extra pose"):
        PoseTracker()
