import cv2
import numpy as np

from funscript_gen.tracking.flow import FlowTracker


def _frame(y: int, x: int = 200, size: int = 60, y2: int | None = None) -> np.ndarray:
    rng = np.random.default_rng(0)
    img = np.full((360, 640, 3), 40, np.uint8)
    patch = rng.integers(0, 255, (size, size, 3), dtype=np.uint8)  # textured so flow has something to lock on
    img[y : y + size, x : x + size] = patch
    if y2 is not None:  # a second patch moving independently
        img[y2 : y2 + size, x + 150 : x + 150 + size] = patch[::-1]
    return img


def _sine(n: int = 90, amp: float = 30) -> np.ndarray:
    return (150 + amp * np.sin(2 * np.pi * np.arange(n) / 30)).astype(int)


def test_vertical_motion_in_roi_is_recovered():
    y = _sine()
    for axis in ("auto", "vertical"):
        tracker = FlowTracker(roi=(0.2, 0.2, 0.6, 0.9))
        for i, yi in enumerate(y):
            tracker.update(i * 33.3, _frame(yi))
        _, pos = tracker.signal(axis, fps=30)
        # upward motion is positive, image y grows downward
        assert np.corrcoef(pos[5:-5], -y[5:-5])[0, 1] > 0.9, axis


def test_signal_detrends_over_seconds_of_the_frames_it_got():
    from funscript_gen.tracking.flow import integrate, sample_rate

    assert sample_rate(np.arange(10) * 1000 / 24) == 24 and sample_rate(np.zeros(1), 30.0) == 30
    tracker = FlowTracker(roi=(0.2, 0.2, 0.6, 0.9))
    for i, yi in enumerate(_sine(120)):
        tracker.update(i * 1000 / 24, _frame(yi))  # a 24 fps video
    assert np.allclose(tracker.signal("vertical")[1], integrate(tracker.velocity("vertical"), fps=24))


def test_opposite_motion_does_not_cancel_in_auto():
    y = _sine()
    tracker = FlowTracker(roi=(0.2, 0.1, 0.8, 0.95))
    for i, yi in enumerate(y):
        tracker.update(i * 33.3, _frame(yi, y2=300 - yi))  # second patch mirrors the first
    _, auto = tracker.signal("auto", fps=30)
    assert abs(np.corrcoef(auto[5:-5], y[5:-5])[0, 1]) > 0.9
    assert np.std(auto) > 3 * np.std(tracker.signal("vertical", fps=30)[1])  # mean flow mostly cancels


def test_amplitude_is_independent_of_roi_size():
    y = _sine()
    stds = []
    for roi in [(0.25, 0.3, 0.45, 0.7), (0.0, 0.0, 1.0, 1.0)]:
        tracker = FlowTracker(roi=roi)
        for i, yi in enumerate(y):
            tracker.update(i * 33.3, _frame(yi))
        stds.append(np.std(tracker.signal("auto", fps=30)[1]))
    assert 0.6 < stds[0] / stds[1] < 1.6


def test_camera_pan_is_cancelled():
    tracker = FlowTracker(roi=(0.2, 0.2, 0.6, 0.9))
    rng = np.random.default_rng(1)
    world = rng.integers(0, 255, (400, 800, 3), dtype=np.uint8)
    for i in range(30):
        tracker.update(i * 33.3, np.ascontiguousarray(world[i : i + 360, :640]))  # whole frame shifts together
    assert np.abs(tracker.velocity("vertical")).max() < 0.2


def test_direction_sets_the_sign():
    y = _sine()
    tracker = FlowTracker(roi=(0.2, 0.2, 0.6, 0.9))
    for i, yi in enumerate(y):
        tracker.update(i * 33.3, _frame(yi))
    down = tracker.signal("auto", fps=30, direction=(0.0, 1.0))[1]  # "tip" is below the base
    up = tracker.signal("auto", fps=30, direction=(0.0, -1.0))[1]
    assert np.corrcoef(down[5:-5], y[5:-5])[0, 1] > 0.9
    assert np.corrcoef(up[5:-5], -y[5:-5])[0, 1] > 0.9


def test_narrower_flow_keeps_the_units_and_grid():
    y = _sine()
    trackers = [FlowTracker(roi=(0.2, 0.2, 0.6, 0.9)), FlowTracker(roi=(0.2, 0.2, 0.6, 0.9), flow_width=320)]
    for tracker in trackers:
        for i, yi in enumerate(y):
            tracker.update(i * 33.3, _frame(yi))
    full, narrow = (t.signal("auto", fps=30)[1] for t in trackers)
    assert trackers[1].fields[0].shape == trackers[0].fields[0].shape  # same cells, so ROIs and patterns match
    assert np.corrcoef(full[5:-5], narrow[5:-5])[0, 1] > 0.95
    assert 0.85 < np.std(narrow) / np.std(full) < 1.15  # pixels of the 480-wide frame either way
    assert FlowTracker(roi=None, flow_width=800).flow_width == 480  # never above the reference width


def test_narrow_frames_are_not_enlarged():
    y = _sine()
    portrait = [_frame(yi)[:, 140:500] for yi in y]  # 360 wide, as portrait video is decoded
    trackers = [FlowTracker(roi=None), FlowTracker(roi=None)]
    for i, img in enumerate(portrait):
        trackers[0].update(i * 33.3, img)
        trackers[1].update(i * 33.3, cv2.resize(img, (480, 480), interpolation=cv2.INTER_LINEAR))
    assert trackers[0].first.shape == (360, 360)  # the flow ran on the frame as decoded
    assert trackers[0].fields[0].shape == trackers[1].fields[0].shape == (60, 60, 2)  # cells of the 480-wide frame
    narrow, wide = (t.signal("auto", fps=30)[1] for t in trackers)
    assert np.corrcoef(narrow[5:-5], wide[5:-5])[0, 1] > 0.95
    assert 0.85 < np.std(narrow) / np.std(wide) < 1.15  # pixels of the 480-wide frame either way


def test_pieces_joined_give_the_same_fields():
    y = _sine()
    whole = FlowTracker(roi=None)
    for i, yi in enumerate(y):
        whole.update(i * 33.3, _frame(yi))
    joined = FlowTracker(roi=None)
    for lo, hi in ((0, 0), (0, 20), (20, 21), (21, 21), (21, len(y))):  # empty pieces and a one-frame piece
        piece = FlowTracker(roi=None)
        for i in range(lo, hi):
            piece.update(i * 33.3, _frame(y[i]))
        joined.extend(piece)
    assert joined.t_ms == whole.t_ms
    assert all(np.array_equal(a, b) for a, b in zip(joined.fields, whole.fields)) and len(joined.fields) == len(y)
    assert np.array_equal(joined.prev, whole.prev) and np.array_equal(joined.first, whole.first)
