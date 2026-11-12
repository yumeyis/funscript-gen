import av
import numpy as np
import pytest

from funscript_gen.video import decoder


def write_video(path, rotation: int, w: int = 64, h: int = 48, frames: int = 6) -> None:
    """A video whose left half is white (the stored picture), with a display rotation (degrees counterclockwise)."""
    with av.open(str(path), "w") as out:
        stream = out.add_stream("libx264", rate=10)
        stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
        stream.options = {"crf": "10"}
        if rotation:
            stream.set_display_rotation(rotation)
        img = np.zeros((h, w, 3), np.uint8)
        img[:, : w // 2] = 255
        for _ in range(frames):
            for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)


def bright(image) -> tuple[float, float]:
    """The share of bright pixels in (left half, top half)."""
    g = image.mean(axis=2) > 128
    return float(g[:, : g.shape[1] // 2].mean()), float(g[: g.shape[0] // 2].mean())


def test_a_video_without_rotation_is_decoded_as_stored(tmp_path):
    write_video(tmp_path / "a.mp4", 0)
    info = decoder.probe(tmp_path / "a.mp4")
    assert (info.width, info.height) == (64, 48)
    image = next(decoder.iter_frames(tmp_path / "a.mp4")).image
    assert image.shape == (48, 64, 3) and bright(image)[0] > 0.9


@pytest.mark.parametrize("rotation, shape, white", [
    (90, (64, 48), "bottom"),   # counterclockwise: the stored left side ends up at the bottom
    (180, (48, 64), "right"),
    (270, (64, 48), "top"),     # clockwise: the stored left side ends up at the top
])
def test_the_display_rotation_is_applied(tmp_path, rotation, shape, white):
    path = tmp_path / "r.mp4"
    write_video(path, rotation)
    info = decoder.probe(path)
    assert (info.height, info.width) == shape
    image = next(decoder.iter_frames(path)).image
    assert image.shape == (*shape, 3)
    left, top = bright(image)
    got = {"left": (left, 1), "right": (left, 0), "top": (top, 1), "bottom": (top, 0)}[white]
    assert got[0] == pytest.approx(got[1], abs=0.05)
