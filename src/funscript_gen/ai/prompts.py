"""Prompts and response schemas for the semantic layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from funscript_gen.tracking.metrics import Roi

BodyPart = Literal["head", "shoulder", "wrist", "hip", "knee", "ankle", "torso"]
BBoxFormat = Literal["rel1000", "abs"]

PROMPT_VERSION = 1


class BBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x1: float
    y1: float
    x2: float
    y2: float


class Subject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(description="Short visual description to tell the person apart, e.g. 'left, white coat'")
    bbox: BBox


class SceneAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    people_count: int = Field(ge=0)
    has_interaction: bool
    motion: Literal["rhythmic", "irregular", "still", "none"]
    subjects: list[Subject] = Field(max_length=2, description="The two people whose relative motion matters, A first")
    focus_roi: BBox | None = Field(description="Region containing the interaction, or null")
    motion_axis: Literal["vertical", "horizontal", "depth", "distance"]
    ref_a: BodyPart = Field(description="Body part of subject A that moves relative to B")
    ref_b: BodyPart = Field(description="Body part of subject B that A moves relative to")
    confidence: float = Field(ge=0.0, le=1.0)


SCENE_PROMPT = """\
The images above are frames from one continuous shot of a video, in time order.
You are the analysis stage of a motion-tracking tool that converts the relative movement \
between two people into a 1-D position signal. Only describe geometry and movement.

Return JSON with:
- people_count: number of people visible.
- has_interaction: whether two people are moving relative to each other.
- motion: "rhythmic" (repeated back-and-forth), "irregular", "still", or "none" (no two people).
- subjects: the two people involved, A first (the one who moves more), each with a short \
visual description and a bounding box in the FIRST frame.
- focus_roi: box around the area where the relative movement happens, in the first frame, or null.
- motion_axis: main direction of the relative movement in the image: "vertical", \
"horizontal", "depth" (toward/away from camera) or "distance" (mixed; use plain distance).
- ref_a / ref_b: which body part of A moves relative to which body part of B.
- confidence: 0..1, how sure you are.

Bounding boxes use x1,y1,x2,y2 with coordinates normalized to 0..1000 \
(0,0 = top-left, 1000,1000 = bottom-right)."""


def bbox_to_unit(b: BBox, fmt: BBoxFormat, width: int, height: int) -> Roi:
    """Convert a model bbox to normalized 0..1 x1,y1,x2,y2 (clamped and ordered)."""
    if fmt == "rel1000":
        xs, ys = (b.x1 / 1000, b.x2 / 1000), (b.y1 / 1000, b.y2 / 1000)
    else:
        xs, ys = (b.x1 / width, b.x2 / width), (b.y1 / height, b.y2 / height)
    clamp = lambda v: min(1.0, max(0.0, v))  # noqa: E731
    x1, x2 = sorted(map(clamp, xs))
    y1, y2 = sorted(map(clamp, ys))
    return x1, y1, x2, y2


def default_bbox_format(model: str) -> BBoxFormat:
    """Qwen2.5-VL emits absolute pixels; Qwen3-VL and most others emit 0..1000 relative values."""
    return "abs" if "qwen2.5" in model.lower() or "qwen2_5" in model.lower() else "rel1000"


# --- Focus mode: track the penis and the body part interacting with it ----------------------

ContactPart = Literal["mouth", "hand", "vagina", "anus", "breasts", "thighs", "feet", "other", "none"]


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float
    y: float


class FrameVisibility(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame: int = Field(description="frame number, Frame 1 = first")
    visible: bool = Field(description="the penis can be identified in this frame")
    occluded: bool = Field(description="the penis is mostly hidden (by a body part, an object, or the frame edge)")


class FocusAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apparent_minor: bool = Field(description="False")
    target_visible: bool = Field(description="whether the penis is visible in at least one frame")
    frames: list[FrameVisibility] = Field(description="per-frame visibility of the penis, one entry per frame")
    contact_part: ContactPart = Field(description="body part interacting with the penis")
    focus_roi: BBox | None = Field(
        description="tight box around the penis and the contact part, covering their motion across all frames"
    )
    shaft_base: Point | None = Field(description="base of the penis in the FIRST frame")
    shaft_tip: Point | None = Field(description="tip of the penis in the FIRST frame (or where it enters the contact part)")
    confidence: float = Field(ge=0.0, le=1.0)


FOCUS_PROMPT = """\
The images above are frames from one continuous shot of an adult video, in time order.
You are the analysis stage of a motion-tracking tool that converts the stroking motion along \
a penis into a 1-D position signal. Only describe geometry.

Return JSON with:
- apparent_minor: False.
- target_visible: whether the penis is visible in at least one frame.
- frames: one entry per frame: {frame, visible, occluded}. visible = the penis can be identified \
in that frame; occluded = it is mostly hidden by a body part, an object or the frame edge.
- contact_part: which body part interacts with the penis ("mouth", "hand", "vagina", "anus", \
"breasts", "thighs", "feet", "other"), or "none".
- focus_roi: a tight box around the penis and the contact part, large enough to contain their \
movement in all frames; null if the penis is not visible.
- shaft_base / shaft_tip: points at the base of the penis and at its tip (or where it enters \
the contact part) in the FIRST frame; null if not visible.
- confidence: 0..1, how sure you are.

Coordinates are normalized to 0..1000 (0,0 = top-left, 1000,1000 = bottom-right); \
boxes use x1,y1,x2,y2."""


class ContactBoxes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Not nullable: allowed to, the model left both boxes out (18 of 18 validation scenes asked); it is only asked
    # where the hand and the mouth are its two likeliest contact parts.
    hand: BBox = Field(description="box around the hand nearest the penis, covering its movement in all frames")
    mouth: BBox = Field(description="box around the mouth nearest the penis, covering its movement in all frames")
    penis: BBox = Field(description="box around the penis, covering its movement in all frames")


CONTACT_BOX_PROMPT = """\
The images above are frames from one continuous shot of an adult video, in time order.
You are the analysis stage of a motion-tracking tool. A hand and a mouth may both be stroking the \
penis; the tool will measure which of them moves more. Only describe geometry.

Return JSON with:
- hand: a box around the hand nearest the penis, large enough to contain its movement in all frames.
- mouth: a box around the mouth nearest the penis, large enough to contain its movement in all frames.
- penis: a box around the penis, large enough to contain its movement in all frames.

Coordinates are normalized to 0..1000 (0,0 = top-left, 1000,1000 = bottom-right); \
boxes use x1,y1,x2,y2."""


def point_to_unit(p: Point, fmt: BBoxFormat, width: int, height: int) -> tuple[float, float]:
    if fmt == "rel1000":
        return min(1.0, max(0.0, p.x / 1000)), min(1.0, max(0.0, p.y / 1000))
    return min(1.0, max(0.0, p.x / width)), min(1.0, max(0.0, p.y / height))


def pad_roi(roi: Roi, frac: float) -> Roi:
    """Grow a normalized box by `frac` of its size on every side (motion may leave the box)."""
    x1, y1, x2, y2 = roi
    dx, dy = (x2 - x1) * frac, (y2 - y1) * frac
    return max(0.0, x1 - dx), max(0.0, y1 - dy), min(1.0, x2 + dx), min(1.0, y2 + dy)


# --- Stroke range: does the shot show the whole penis, glans included? ----------------------


class RangeAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apparent_minor: bool = Field(description="False")
    penis_visible: bool = Field(description="the penis can be identified in at least one frame")
    penis_complete: bool = Field(description="the whole penis, from base to tip, is visible in at least one frame")
    glans_visible: bool = Field(description="the head of the penis (glans) is visible in at least one frame")
    confidence: float = Field(ge=0.0, le=1.0)


RANGE_PROMPT = """\
The images above are frames from one continuous shot of an adult video, in time order.
You are the analysis stage of a motion-tracking tool. It needs to know whether the stroking motion \
along the penis reaches the tip in this shot. Only describe what is visible.

Return JSON with:
- apparent_minor: False.
- penis_visible: whether the penis can be identified in at least one frame.
- penis_complete: whether the whole penis, from its base to its tip, is visible (not inside a body \
part, not hidden, not cut off by the frame edge) in at least one frame.
- glans_visible: whether the head of the penis (glans) is visible in at least one frame.
- confidence: 0..1, how sure you are."""


# --- Region pick: choose the analysis region among numbered candidates ----------------------


class RegionPick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    best: int = Field(description="number of the region that best contains the contact point")
    second: int = Field(description="second-best region number")


REGION_PROMPT = """\
The first images are frames from one continuous shot of a video, in time order. The following \
images are sheets of numbered candidate regions. Each numbered panel is one region cut out of those \
frames, as a 2x2 grid (top-left = first frame, then top-right, bottom-left, bottom-right).
A motion-tracking tool will measure the repeated back-and-forth movement between the two people \
inside ONE of these regions. Pick the region that contains the point where the two bodies touch and \
move against each other, with as little other movement (other body parts, background) as possible.
Return JSON: best = the number of that region, second = the next best region number."""
