"""End-to-end: video -> scenes -> AI scene analysis -> per-scene motion signal -> funscript."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

import numpy as np

from funscript_gen.i18n import t as tr
from funscript_gen import __version__
from funscript_gen.export.funscript import Action, Funscript
from funscript_gen.signal.audio import onset_envelope, onset_phase, periodicity
from funscript_gen.signal.process import (
    ProcessedSignal, SignalParams, analyze, bridge_gap, fall_rise_asymmetry, insert_holds, limit_speed,
    reference_scale, scene_scale, to_actions,
)
from funscript_gen.tracking.flow import MIN_AMPLITUDE_PX, FlowTracker, integrate, sample_rate
from funscript_gen.tracking.metrics import Roi, assign_pairs, to_signal
from funscript_gen.tracking.pose import PoseFrame, PoseTracker
from funscript_gen.video.decoder import iter_frames, pieces
from funscript_gen.video.scenes import Scene, detect_scenes

Mode = Literal["auto", "flow", "pose"]
# Pieces (FLOW_PIECE_S of a scene) whose optical flow may be computed ahead of the AI analysis (about 8 KB per
# frame each): 320 s of video, as 16 scenes of 20 s before scenes were cut into pieces.
FLOW_WAITING = 64
# Flow pieces computed at the same time: half the cores, at most 8 (Farneback already uses a few threads).
# 12 cores, A04: 4 -> 34.7 s, 6 -> 27.1 s, 8 -> 27.4 s.
DEFAULT_FLOW_WORKERS = max(1, min(8, (os.cpu_count() or 2) // 2))
# Longest stretch of a scene whose flow one worker computes (see _analyze).
FLOW_PIECE_S = 5.0
Focus = Literal["general", "hybrid"]
Progress = Callable[[str, float], None]  # (phase, t_ms); for "ai" and "parts" the share done (0..1)


@dataclass
class PipelineOptions:
    fps: float = 30.0  # analysis frame rate
    max_side: int = 640  # downscale frames before pose estimation / optical flow
    # Optical flow is computed on a frame this wide (at most 480, the width its units refer to). 320 took about
    # half the flow time; on the 13 validation clips F1 0.744 -> 0.747, correlation 0.529 -> 0.519 (offline).
    flow_width: int = 480
    model: str = "yolo11n-pose.pt"
    device: str | None = None  # the pose model's device as Ultralytics takes it ("cuda:1"); overrides pose_compute
    # Where the GPU-capable steps run, auto | gpu | cpu (see devices): the whole run, and each step (auto: as the run)
    compute: str = "auto"
    flow_compute: str = "auto"
    part_compute: str = "auto"
    pose_compute: str = "auto"
    mode: Mode = "auto"
    use_ai: bool = True
    ai_workers: int | None = None  # concurrent AI requests; None: the AI settings' vllm_concurrency
    flow_workers: int = DEFAULT_FLOW_WORKERS  # optical flow pieces (see _analyze) computed at the same time
    # "hybrid": per scene the general analysis and a genital one (the AI frames the penis and the body part
    # interacting with it, and may give the shaft direction, which then sets the stroke sign); each frame uses the
    # genital region where the penis is identifiable and not occluded, the general region elsewhere. Optical flow.
    focus: Focus = "general"
    ai_settings: object | None = None  # config.Settings; None reads .env
    # General focus: show the VLM numbered candidate regions (its own box, each person, both, the whole
    # frame, a 3x3 grid) and use its pick when that region's signal is at least as periodic as the
    # original one (+ margin). Validation: mean F1 0.874 -> 0.890, no clip lower.
    region_pick: bool = True
    region_pick_margin: float = 0.0
    # Hybrid focus: when the AI's two most likely contact parts (its token probabilities) are the hand and the mouth,
    # it boxes both, and the genital region becomes the box of the one that moves more (one or two more AI calls in
    # those scenes; vLLM only).
    contact_pick: bool = True
    # ...only when the second of the two is at least this likely: most scenes the rule caught had it under 0.01, the AI
    # being sure of one part
    contact_min_prob: float = 0.1
    # Scenes in which the AI sees nobody (people_count 0: intros, titles, black frames) are not analysed and hold
    # at the top of the output range, where hand-made scripts rest (25 of their 34 still 4 s windows sit at 90..100).
    # General and hybrid focus; not with a manual --roi.
    rest_empty: bool = True
    # Stroke range: per scene the AI says whether the whole penis and its glans can be seen. Glans not seen:
    # the strokes never reach the tip, so positions are clipped to at most range_cap. Glans seen but the penis
    # not whole: positions are clipped to at least range_floor. Validation of the cap: clipping raised the mean
    # correlation 0.573 -> 0.589, scaling pos_low..pos_high to pos_low..cap lowered it to 0.565.
    stroke_range: bool = True
    range_cap: int = 80
    range_floor: int = 20
    # Long shots are split into 20 s scenes, and without an AI direction each one guessed its own stroke
    # sign ("up" = high), which near-horizontal motion leaves to chance: one chunk of a shot came out
    # inverted. The chunk whose sign was clearest sets it for the others of its shot when their motion
    # patterns match (|cosine| >= chunk_align_similarity).
    chunk_align: bool = True
    chunk_align_similarity: float = 0.3
    # Hand-made scripts mostly fall faster than they rise (the thrust is the insertion), so a
    # scene whose strokes clearly rise faster is flipped: fall_rise_asymmetry above asym_sign_threshold (the
    # rises' median peak speed over e^0.5 = 1.65 times the falls'), from at least asym_sign_min_strokes strokes.
    # Only flow scenes without an AI direction; after the chunk alignment, linked chunks of a shot together.
    asym_sign: bool = True
    asym_sign_threshold: float = 0.5
    asym_sign_min_strokes: int = 4
    # The sound vetoes: impacts land just before the bottom of a thrust, so where the sound onsets fall at the
    # signal's lows (onset_phase above 0) the sign looks right and the threshold rises linearly from
    # asym_audio_threshold to asym_sign_threshold at +asym_audio_min; elsewhere (onsets at the highs, or spread
    # evenly: music, no impacts) it is asym_audio_threshold. Without sound it stays asym_sign_threshold. Alone the
    # sound is not enough: in oral scenes the onsets come at the top (13 clips: flipping on the sound alone turned
    # 10 right scenes wrong, B01 among them; with the asymmetry above 0.2 too, 1 scene that barely moves). Until
    # 2026-11-05 only onsets at the highs lowered it; the scenes 0.2 flipped right had onset phases near 0 (the G
    # series, I01), the ones it flipped wrong mostly had onsets at the lows (B02, E02, H02): 38 clips F1 dev
    # 0.747 -> 0.756, test 0.724 -> 0.737.
    asym_audio: bool = True
    asym_audio_threshold: float = 0.2
    asym_audio_min: float = 0.3
    asym_audio_phase: float = -40.0  # degrees from the lows where impacts are expected (negative: before)
    # A scene the checks keep although its sound onsets fall at the highs (onset_phase below -sign_doubt_audio) is
    # listed for checking by hand, not flipped: in oral and some cowgirl scenes impacts come at the top. 25 clips
    # with --asym-sign --part-sign: 7 scenes listed in general focus, 4 clearly upside down, B01 (right side up)
    # not; Hybrid 5, 1 upside down. Chosen on the same clips; on the 13 held-out clips it listed 14 scenes and all
    # were the right way up (C02, D05), so it is off by default (sound_hint).
    sound_hint: bool = False
    sign_doubt_audio: float = 0.4
    # An anime genital detector (tracking/parts.py) finds the penis and vulva boxes; apart = pulled
    # out = high. Scenes with a penis in at least part_min_share of their frames at part_scan_fps are detected at
    # part_fps, and a scene whose penis-vulva distance (known in at least part_min_cover of the frames) follows the
    # flow position inversely (correlation <= -part_sign_threshold) is flipped. Scenes where penis boxes touch
    # the frame border in part_max_edge of the frames (cut off) are left out. Flipped scenes are settled (as
    # asym_flipped): the asymmetry check skips them. A clear "keep" settles nothing: in B03
    # the distance followed 2 inverted scenes the asymmetry check flips right. Validation (13 clips): 21 scenes
    # with a clear answer, 8 flipped, F1 0.744 -> 0.758, no clip lower; the oral and hand scenes have no vulva box.
    # Both checks are on by default since 2026-10-31: on the 12 test clips no rule was tuned on, F1 0.638 -> 0.688
    # with both, no clip lower (the part check does nearly all of it).
    part_sign: bool = True
    part_sign_threshold: float = 0.2
    part_scan_fps: float = 1.0
    part_min_share: float = 0.5
    part_fps: float = 10.0
    part_min_cover: float = 0.6
    part_conf: float = 0.15  # detection threshold at part_fps (the scan uses the model's recommended 0.238)
    part_workers: int = 3  # part detection pieces run at the same time, 4 threads each
    part_max_edge: float = 0.8
    # Scenes (by index) whose output is flipped by hand, on top of everything else.
    flip_scenes: tuple[int, ...] = ()
    # Manual overrides; None lets the AI (or the defaults) decide per scene.
    axis: str | None = None
    roi: Roi | None = None
    ref_a: str | None = None
    ref_b: str | None = None
    invert: bool = False
    scene_threshold: float = 30.0
    signal: SignalParams = field(default_factory=SignalParams)


@dataclass
class ScenePlan:
    scene: Scene
    mode: Literal["flow", "pose"] = "flow"
    roi: Roi | None = None
    axis: str = "auto"
    ref_a: str = "hip"
    ref_b: str = "hip"
    analysis: object | None = None  # SceneAnalysis or HybridAnalysis
    error: str | None = None
    signal: ProcessedSignal | None = None
    direction: tuple[float, float] | None = None  # stroke direction in image pixels (shaft base -> tip)
    skip: bool = False  # no actions for this scene
    rest: bool = False  # skipped because nobody is in the picture: holds at the top of the output range
    note: str = ""
    # hybrid focus: general-mode region, and per key frame (t_ms, use the genital region?)
    alt_roi: Roi | None = None
    decisions: list[tuple[float, bool]] = field(default_factory=list)
    # region pick: the candidate the VLM chose instead of `roi` (None = it kept `roi`, or no pick ran)
    pick_name: str | None = None
    pick_roi: Roi | None = None
    # contact pick (hybrid): the AI's probability per contact part, and the hand, mouth and penis boxes when the hand
    # and the mouth are its top two
    contact_probs: dict[str, float] | None = None
    contact_rois: dict[str, Roi] | None = None
    contact_penis: Roi | None = None
    range_max: int | None = None  # stroke range: highest output position for this scene (None = no cap)
    range_min: int | None = None  # stroke range: lowest output position for this scene (None = no floor)
    range_analysis: object | None = None  # RangeAnalysis
    # chunk sign alignment ("auto" flow without a direction): the component's pattern and sign margin
    # (see FlowTracker.component), and the integrated position the signal came from
    sign_pattern: np.ndarray | None = None
    sign_margin: float | None = None
    flow_position: tuple[np.ndarray, np.ndarray] | None = None
    asym: float | None = None  # fall_rise_asymmetry of flow_position (positive: rises faster than falls)
    audio_sign: float | None = None  # onset_phase of flow_position (negative: sound onsets at the highs)
    asym_flipped: bool = False  # flipped by the asymmetry check (asym_sign)
    asym_hint: bool = False  # rises clearly faster but asym_sign is off: possibly inverted, flip by hand
    sign_doubt: str = ""  # kept, but some evidence says it is upside down: check it by hand (see sign_doubt_audio)
    part_sign: float | None = None  # correlation of the penis-vulva distance with the output (part_sign)
    part_flipped: bool = False  # flipped by the part check: its sign is settled, the asymmetry check skips it
    flipped: bool = False  # output mirrored within the output range (by hand)
    # From the analysis (analyze_video), where render() starts every scene from: the motion before any sign
    # decision, the region pick's candidate, the part detection and the AI plan's notes.
    source: tuple[np.ndarray, np.ndarray] | None = None  # (t_ms, x) the signal is analysed from
    pick_source: tuple[np.ndarray, np.ndarray] | None = None  # the same for pick_roi
    pick_pattern: np.ndarray | None = None
    pick_margin: float | None = None
    parts_found: tuple | None = None  # (times, boxes, frame size) at part_fps; None: no penis, or not detected
    base_note: str = ""
    pick_note: str = ""
    range_error: str | None = None  # the stroke range call failed


@dataclass
class HybridAnalysis:
    general: object | None  # SceneAnalysis
    focus: object | None  # FocusAnalysis

    def model_dump(self, mode: str = "python") -> dict:
        dump = lambda a: a.model_dump(mode=mode) if a is not None else None  # noqa: E731
        return {"general": dump(self.general), "focus": dump(self.focus)}


@dataclass
class VideoAnalysis:
    """The expensive part of a run (scene cut, AI, optical flow, part detection, sound): render() turns it into a
    script, and can do so again with other output settings. `key` holds the settings it was made with that a render
    cannot change (options.analysis_key); `stat` (size, mtime) identifies the video file."""

    video: Path
    key: dict
    plans: list[ScenePlan]
    envelope: tuple[np.ndarray, np.ndarray] | None  # sound onsets (signal.audio.onset_envelope); None: no audio
    stat: tuple[int, int] = (0, 0)
    part_device: str | None = None
    parts_error: str | None = None  # the part detector could not be loaded
    flow_device: str | None = None  # "CPU", or "OpenCL: <GPU>" (None: no optical flow)

    def serves(self, video: str | Path, key: dict) -> bool:
        """Whether rendering this analysis gives what a full run of `video` with settings `key` would. Without the
        part check, an analysis with part detection still serves (its boxes are just not used)."""
        try:
            st = Path(video).stat()
        except OSError:
            return False
        if Path(video).resolve() != self.video.resolve() or (st.st_size, st.st_mtime_ns) != self.stat:
            return False
        from funscript_gen.options import BY_NAME

        # a setting the analysis does not list (it is older than the setting) was at its default
        mine = {k: self.key.get(k, BY_NAME[k].default if k in BY_NAME else None) for k in key}
        if mine.get("part_sign") and not key.get("part_sign"):
            mine["part_sign"] = False
        return mine == dict(key)


ANALYSIS_FORMAT = 1  # bump when VideoAnalysis or ScenePlan change so that old saved analyses no longer fit


def save_analysis(analysis: VideoAnalysis, path: str | Path) -> None:
    """Pickle the analysis without the key frames (only the AI needed them). A pickle can run code when loaded, so only
    load files you made yourself (README and SECURITY.md say so)."""
    import pickle

    from funscript_gen.version import provenance

    plans = [replace(p, scene=replace(p.scene, keyframes=[])) for p in analysis.plans]
    with open(path, "wb") as f:
        pickle.dump({"format": ANALYSIS_FORMAT, "code": provenance(), "analysis": replace(analysis, plans=plans)}, f,
                    protocol=pickle.HIGHEST_PROTOCOL)


def load_analysis(path: str | Path) -> VideoAnalysis:
    import pickle

    with open(path, "rb") as f:
        data = pickle.load(f)
    if not isinstance(data, dict) or data.get("format") != ANALYSIS_FORMAT:
        raise ValueError(f"{path}: saved by another version of funscript-gen, analyse the video again")
    return data["analysis"]


@dataclass
class PipelineResult:
    funscript: Funscript
    plans: list[ScenePlan]
    part_device: str | None = None  # onnxruntime provider the part check ran on (None: it did not run)
    analysis: VideoAnalysis | None = None  # what the script was rendered from
    flow_device: str | None = None  # VideoAnalysis.flow_device


def _run_all(workers: int, fn: Callable, items: list, tick: Callable[[], None] | None = None) -> list:
    """`fn` over `items` on a thread pool, results in order. `tick()` runs in this thread after each item and may
    raise to stop: the items not started yet are dropped (the running ones finish first)."""
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [pool.submit(fn, item) for item in items]
        for _ in as_completed(futures):
            if tick:
                tick()
        return [f.result() for f in futures]
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def _analyze_scenes(
    scenes: list[Scene], workers: int, focus: Focus = "general", settings=None, tick: Callable[[], None] | None = None,
) -> list[tuple[object | None, str | None]]:
    from funscript_gen.ai.base import LabeledImage, ProviderError
    from funscript_gen.ai.prompts import FOCUS_PROMPT, SCENE_PROMPT, FocusAnalysis, SceneAnalysis
    from funscript_gen.config import make_provider

    provider = make_provider(settings)

    def ask(scene: Scene, prompt: str, schema):
        images = [LabeledImage(f.image, f"Frame {i + 1} (t={f.t_ms / 1000:.2f}s):") for i, f in enumerate(scene.keyframes)]
        try:
            return provider.analyze(images, prompt, schema), None
        except ProviderError as e:
            return None, str(e)

    def one(scene: Scene):
        if focus == "general":
            return ask(scene, SCENE_PROMPT, SceneAnalysis)
        general, err_g = ask(scene, SCENE_PROMPT, SceneAnalysis)
        focused, err_f = ask(scene, FOCUS_PROMPT, FocusAnalysis)
        error = "; ".join(e for e in (err_g, err_f) if e) or None
        return HybridAnalysis(general, focused), error

    return _run_all(workers, one, scenes, tick)


def _subject_boxes(plan: ScenePlan, analysis, fmt: str) -> list[Roi]:
    from funscript_gen.ai.prompts import bbox_to_unit

    h, w = plan.scene.keyframes[0].image.shape[:2]
    return [bbox_to_unit(s.bbox, fmt, w, h) for s in analysis.subjects]


def _pick_regions(plans: list[ScenePlan], workers: int, settings, fmt: str, tick: Callable[[], None] | None = None) -> None:
    """Ask the VLM which candidate region holds the contact point; sets `pick_name` / `pick_roi`."""
    from funscript_gen.ai.base import LabeledImage, ProviderError
    from funscript_gen.ai.prompts import REGION_PROMPT, RegionPick
    from funscript_gen.ai.regions import candidates, sheets
    from funscript_gen.config import make_provider

    provider = make_provider(settings)

    def one(plan: ScenePlan) -> None:
        cands = candidates(plan.roi, _subject_boxes(plan, plan.analysis, fmt))
        frames = [f.image for f in plan.scene.keyframes]
        images = [LabeledImage(f, f"Frame {i + 1}:") for i, f in enumerate(frames)]
        regions = [r for _, r in cands]
        images += [LabeledImage(img, f"Regions {4 * k + 1}-{min(4 * k + 4, len(regions))}:")
                   for k, img in enumerate(sheets(frames, regions))]
        try:
            pick = provider.analyze(images, REGION_PROMPT, RegionPick)
        except ProviderError as e:
            plan.pick_note = tr("pipe.pick_failed", e=e)
            return
        if 2 <= pick.best <= len(cands):  # 1 is the current region
            plan.pick_name, plan.pick_roi = cands[pick.best - 1]

    _run_all(workers, one, plans, tick)


def _pick_contacts(plans: list[ScenePlan], workers: int, settings, fmt: str, min_prob: float) -> None:
    """Ask for the probability of each contact part of the genital analysis; where the hand and the mouth are the top
    two (the second at least `min_prob`), ask for both boxes (`contact_rois`) and the penis's (`contact_penis`): _scene_source keeps the part that
    moves more, together with the penis."""
    from funscript_gen.ai.base import LabeledImage, ProviderError
    from funscript_gen.ai.prompts import CONTACT_BOX_PROMPT, FOCUS_PROMPT, ContactBoxes, FocusAnalysis, bbox_to_unit, pad_roi
    from funscript_gen.config import make_provider

    provider = make_provider(settings)

    def note(plan: ScenePlan, text: str) -> None:
        plan.note = tr("sep.note").join(filter(None, [plan.note, text]))

    def one(plan: ScenePlan) -> None:
        keyframes = plan.scene.keyframes
        images = [LabeledImage(f.image, f"Frame {i + 1} (t={f.t_ms / 1000:.2f}s):") for i, f in enumerate(keyframes)]
        try:
            probs = provider.choice_probs(images, FOCUS_PROMPT, FocusAnalysis, plan.analysis.focus, "contact_part")
        except ProviderError as e:
            note(plan, tr("pipe.contact_probs_failed", e=e))
            return
        plan.contact_probs = probs
        first, second = sorted(probs, key=probs.get, reverse=True)[:2]
        if {first, second} != {"hand", "mouth"} or probs[second] <= 0 or probs[second] < min_prob:
            return
        note(plan, tr("pipe.contact_probs", first=first, p_first=format(probs[first], ".2f"),
                      second=second, p_second=format(probs[second], ".2f")))
        try:
            boxes = provider.analyze(images, CONTACT_BOX_PROMPT, ContactBoxes)
        except ProviderError as e:
            note(plan, tr("pipe.contact_boxes_failed", e=e))
            return
        h, w = keyframes[0].image.shape[:2]
        plan.contact_rois = {part: pad_roi(bbox_to_unit(box, fmt, w, h), 0.2)
                             for part, box in (("hand", boxes.hand), ("mouth", boxes.mouth))}
        plan.contact_penis = pad_roi(bbox_to_unit(boxes.penis, fmt, w, h), 0.2)

    _run_all(workers, one, plans)


def _detect_ranges(
    scenes: list[Scene], workers: int, settings, tick: Callable[[], None] | None = None,
) -> list[tuple[object | None, str | None]]:
    """Per scene the AI's RangeAnalysis (or None) and the error, if the call failed."""
    from funscript_gen.ai.base import LabeledImage, ProviderError
    from funscript_gen.ai.prompts import RANGE_PROMPT, RangeAnalysis
    from funscript_gen.config import make_provider

    provider = make_provider(settings)

    def one(scene: Scene):
        images = [LabeledImage(f.image, f"Frame {i + 1} (t={f.t_ms / 1000:.2f}s):") for i, f in enumerate(scene.keyframes)]
        try:
            return provider.analyze(images, RANGE_PROMPT, RangeAnalysis), None
        except ProviderError as e:
            return None, str(e)

    return _run_all(workers, one, scenes, tick)


def _apply_range(plan: ScenePlan, analysis, error: str | None, cap: int, floor: int) -> None:
    if analysis is None:
        plan.note = tr("sep.note").join(filter(None, [plan.note, tr("pipe.range_failed", error=error)]))
        return
    plan.range_analysis = analysis
    if analysis.apparent_minor:
        plan.skip = True
        plan.note = tr("pipe.skipped")
        return
    if not analysis.glans_visible:
        plan.range_max = cap
        what = tr("pipe.range_no_glans", cap=cap)
    elif not analysis.penis_complete:
        plan.range_min = floor
        what = tr("pipe.range_partial", floor=floor)
    else:
        what = tr("pipe.range_whole")
    plan.note = tr("sep.note").join(filter(None, [plan.note, tr("pipe.range", what=what)]))


def clip_range(actions: list[Action], plans: list[ScenePlan], pos_low: int, pos_high: int) -> list[Action]:
    """Clip each scene's positions to its range_min..range_max (kept within pos_low..pos_high)."""
    out = []
    for a in actions:
        plan = next((p for p in plans if p.scene.start_ms <= a.at < p.scene.end_ms), None)
        if plan is not None and (plan.range_max is not None or plan.range_min is not None):
            hi = max(pos_low, min(pos_high, plan.range_max if plan.range_max is not None else pos_high))
            lo = min(hi, max(pos_low, plan.range_min if plan.range_min is not None else pos_low))
            a = Action(a.at, min(max(a.pos, lo), hi))
        out.append(a)
    return out


def _apply_general(plan: ScenePlan, analysis, fmt: str) -> None:
    from funscript_gen.ai.prompts import bbox_to_unit

    h, w = plan.scene.keyframes[0].image.shape[:2]
    if analysis.focus_roi is not None:
        plan.roi = bbox_to_unit(analysis.focus_roi, fmt, w, h)
    elif analysis.subjects:
        # The motion happens between the two people, so the region must hold both of them.
        boxes = [bbox_to_unit(s.bbox, fmt, w, h) for s in analysis.subjects]
        plan.roi = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    plan.axis = analysis.motion_axis
    plan.ref_a, plan.ref_b = analysis.ref_a, analysis.ref_b


def _apply_focus(plan: ScenePlan, analysis, fmt: str) -> None:
    """The genital half of a hybrid analysis: its region, shaft direction and notes."""
    from funscript_gen.ai.prompts import bbox_to_unit, pad_roi, point_to_unit

    h, w = plan.scene.keyframes[0].image.shape[:2]
    if analysis.apparent_minor:
        plan.skip = True
        plan.note = tr("pipe.skipped")
    elif not analysis.target_visible or analysis.focus_roi is None:
        plan.note = tr("pipe.target_missing")
    else:
        plan.roi = pad_roi(bbox_to_unit(analysis.focus_roi, fmt, w, h), 0.2)
        plan.note = tr("pipe.contact_part", contact_part=analysis.contact_part)
        if analysis.shaft_base is not None and analysis.shaft_tip is not None:
            bx, by = point_to_unit(analysis.shaft_base, fmt, w, h)
            tx, ty = point_to_unit(analysis.shaft_tip, fmt, w, h)
            d = ((tx - bx) * w, (ty - by) * h)  # pixels, so the aspect ratio is right
            if np.hypot(*d) > 0.01 * max(w, h):
                plan.direction = d


def _apply_hybrid(plan: ScenePlan, analysis: HybridAnalysis, fmt: str) -> None:
    if analysis.general is not None:
        _apply_general(plan, analysis.general, fmt)
    plan.alt_roi, plan.roi = plan.roi, None
    focused = analysis.focus
    if focused is not None:
        _apply_focus(plan, focused, fmt)
    if plan.skip:
        return
    by_frame = {fv.frame: fv for fv in getattr(focused, "frames", [])}
    for k, f in enumerate(plan.scene.keyframes, start=1):
        fv = by_frame.get(k)
        clear = (fv.visible and not fv.occluded) if fv is not None else bool(focused and focused.target_visible)
        plan.decisions.append((f.t_ms, plan.roi is not None and clear))
    used = sum(use for _, use in plan.decisions)
    mix = tr("pipe.hybrid_mix", used=used, total=len(plan.decisions))
    plan.note = f"{plan.note}{tr('sep.note')}{mix}" if plan.note else mix


def _sees_nobody(analysis) -> bool:
    """The AI's scene analysis (general, or the general half of hybrid) counted no people in the picture."""
    from funscript_gen.ai.prompts import SceneAnalysis

    general = analysis.general if isinstance(analysis, HybridAnalysis) else analysis
    return isinstance(general, SceneAnalysis) and general.people_count == 0


def _ai_workers(opts: PipelineOptions) -> int:
    from funscript_gen.config import Settings

    return max(1, opts.ai_workers or (opts.ai_settings or Settings()).vllm_concurrency)


def plan_scenes(scenes: list[Scene], opts: PipelineOptions, progress: Callable[[float], None] | None = None,
                on_seen: Callable[[list[ScenePlan]], None] | None = None) -> list[ScenePlan]:
    """One plan per scene from the AI's answers. `progress(share)` follows the AI calls (and may raise to stop).
    `on_seen(plans)` is called once the scene analyses are in (before the contact, range and region calls), with
    the scenes nobody is seen in already marked skipped."""
    from funscript_gen.ai.prompts import default_bbox_format
    from funscript_gen.config import Settings

    analyses: list[tuple[object | None, str | None]] = [(None, None)] * len(scenes)
    fmt = "rel1000"
    # AI calls per scene: the analysis, the stroke range, the region pick (an estimate: skipped scenes need fewer)
    steps = 1 + opts.stroke_range + (opts.region_pick and opts.focus == "general" and not opts.roi)
    calls = 0

    def tick() -> None:
        nonlocal calls
        calls += 1
        if progress:
            progress(min(1.0, calls / max(1, steps * len(scenes))))

    if opts.use_ai and scenes:
        settings = opts.ai_settings or Settings()
        fmt = settings.vllm_bbox_format or default_bbox_format(settings.vllm_model)
        analyses = _analyze_scenes(scenes, _ai_workers(opts), opts.focus, settings, tick)

    plans: list[ScenePlan] = []
    for scene, (analysis, error) in zip(scenes, analyses):
        plan = ScenePlan(scene, analysis=analysis, error=error)
        if isinstance(analysis, HybridAnalysis):
            _apply_hybrid(plan, analysis, fmt)
        elif analysis is not None:
            _apply_general(plan, analysis, fmt)
        if opts.roi:
            plan.roi = plan.alt_roi = opts.roi
        plan.axis = opts.axis or plan.axis
        plan.ref_a = opts.ref_a or plan.ref_a
        plan.ref_b = opts.ref_b or plan.ref_b
        # "auto" means optical flow: on the validation clips the skeleton scenes it used to pick
        # (two people in frame) scored lower than flow in 7 of 9 scenes, often by a wide margin.
        plan.mode = "pose" if opts.mode == "pose" else "flow"
        if plan.mode == "flow" and not opts.axis:
            plan.axis = "auto"  # flow finds the dominant motion itself; see _scene_signal
        if opts.rest_empty and not opts.roi and not plan.skip and _sees_nobody(analysis):
            plan.skip = plan.rest = True
            plan.note = tr("pipe.nobody")
        plans.append(plan)
    if on_seen is not None:
        on_seen(plans)

    if opts.use_ai and opts.contact_pick and opts.focus == "hybrid" and not opts.roi:
        todo = [p for p in plans if p.mode == "flow" and not p.skip and p.roi is not None
                and isinstance(p.analysis, HybridAnalysis) and p.analysis.focus is not None
                and p.analysis.focus.contact_part in ("hand", "mouth")]
        if todo:
            _pick_contacts(todo, _ai_workers(opts), opts.ai_settings or Settings(), fmt, opts.contact_min_prob)
    for plan in plans:
        plan.base_note = plan.note
    if opts.use_ai and opts.stroke_range and scenes:
        todo = [p for p in plans if not p.skip]
        ranges = _detect_ranges([p.scene for p in todo], _ai_workers(opts), opts.ai_settings or Settings(), tick)
        for plan, (analysis, error) in zip(todo, ranges):
            # the cap and floor are output settings (render applies them); a skipped scene needs no optical flow
            plan.range_analysis, plan.range_error = analysis, error
            plan.skip = plan.skip or (analysis is not None and analysis.apparent_minor)

    if opts.use_ai and opts.region_pick and opts.focus == "general" and not opts.roi:
        from funscript_gen.ai.prompts import SceneAnalysis

        todo = [p for p in plans if p.mode == "flow" and not p.skip and isinstance(p.analysis, SceneAnalysis)]
        if todo:
            _pick_regions(todo, _ai_workers(opts), opts.ai_settings or Settings(), fmt, tick)
    return plans


def apply_ranges(plans: list[ScenePlan], opts: PipelineOptions) -> None:
    """The stroke range's cap and floor (range_cap / range_floor) on the scenes the AI answered for, and their notes."""
    for plan in plans:
        if plan.range_analysis is not None or plan.range_error is not None:
            _apply_range(plan, plan.range_analysis, plan.range_error, opts.range_cap, opts.range_floor)


def frame_choice(t_ms: np.ndarray, decisions: list[tuple[float, bool]]) -> np.ndarray:
    """Per analysed frame: the decision of the nearest key frame."""
    if not decisions:
        return np.zeros(len(t_ms), bool)
    kt = np.array([t for t, _ in decisions])
    use = np.array([u for _, u in decisions])
    nearest = np.abs(np.asarray(t_ms)[:, None] - kt[None, :]).argmin(axis=1)
    return use[nearest]


def splice_velocity(v_focus: np.ndarray, v_general: np.ndarray, use_focus: np.ndarray) -> np.ndarray:
    """Per frame take the focus-region velocity where `use_focus`, else the general one.

    Both are pixels/frame, so they can be joined directly; the general one is flipped first if the two
    regions disagree on direction, so the stitched position does not jump at the switch.
    """
    if v_focus.std() > 0 and v_general.std() > 0 and np.corrcoef(v_focus, v_general)[0, 1] < 0:
        v_general = -v_general
    return np.where(use_focus, v_focus, v_general)


def _scene_source(plan: ScenePlan, opts: PipelineOptions, flow: FlowTracker | None, poses: list[PoseFrame]) -> None:
    """The scene's motion before any sign decision (`source`, and `flow_position` with its sign pattern when the sign
    is open to alignment), and the region pick's candidate. Only analysis settings matter here (see render)."""
    if plan.mode == "flow":
        assert flow is not None
        # The AI's axis is only a hint: the dominant-motion analysis ("auto") beat projecting onto
        # the AI's axis on the validation clips. An axis set by the user is honoured.
        axis = {"distance": "auto"}.get(opts.axis or "auto", opts.axis or "auto")
        if plan.decisions and axis == "auto" and len(flow.t_ms) >= 3:
            t = np.array(flow.t_ms)
            use = frame_choice(t, plan.decisions)
            vel, pattern, margin = flow.component(roi=plan.alt_roi)
            if plan.roi is not None and use.any():
                if plan.contact_rois:
                    _pick_contact_region(plan, flow, opts)
                # the genital region sets the sign; the general one is flipped to match it
                v_focus, pattern, margin = flow.component(plan.direction, roi=plan.roi)
                vel = splice_velocity(v_focus, vel, use)
            x = integrate(vel, fps=sample_rate(t, opts.fps))
            if plan.direction is None:  # a sign from the AI's shaft direction is never re-aligned
                plan.sign_pattern, plan.sign_margin, plan.flow_position = pattern, margin, (t, x)
        elif axis == "auto" and plan.direction is None and len(flow.t_ms) >= 3:
            v, plan.sign_pattern, plan.sign_margin = flow.component()
            t = np.array(flow.t_ms)
            x = integrate(v, fps=sample_rate(t, opts.fps))
            plan.flow_position = (t, x)
        else:
            t, x = flow.signal(axis, direction=plan.direction)  # type: ignore[arg-type]
        plan.source = (t, x)
        if plan.pick_roi is not None and not plan.decisions and len(flow.t_ms) >= 3:
            if plan.sign_pattern is not None:
                v, plan.pick_pattern, plan.pick_margin = flow.component(roi=plan.pick_roi)
            else:
                v = flow.velocity(axis, plan.direction, roi=plan.pick_roi)  # type: ignore[arg-type]
            t = np.array(flow.t_ms)
            plan.pick_source = (t, integrate(v, fps=sample_rate(t, opts.fps)))
    else:
        axis = {"depth": "distance"}.get(plan.axis, plan.axis)
        track = assign_pairs(poses, roi=None, ref_a=plan.ref_a, ref_b=plan.ref_b)
        x, _ = to_signal(track, axis, fps=sample_rate(track.t_ms, opts.fps))  # type: ignore[arg-type]
        plan.source = (track.t_ms, x)


def motion_size(x: np.ndarray) -> float:
    """How far a position moves: the spread between its 5th and 95th percentiles."""
    return float(np.percentile(x, 95) - np.percentile(x, 5)) if len(x) else 0.0


def _pick_contact_region(plan: ScenePlan, flow: FlowTracker, opts: PipelineOptions) -> None:
    """The genital region becomes the contact box (hand or mouth) whose own motion is larger, joined with the penis's
    box: either part's box alone lost the penis and scored lower where the two moved about as much (A01)."""
    fps = sample_rate(np.array(flow.t_ms), opts.fps)
    sizes = {part: motion_size(integrate(flow.component(plan.direction, roi=roi)[0], fps=fps))
             for part, roi in plan.contact_rois.items()}
    part = max(sizes, key=sizes.get)
    boxes = [plan.contact_rois[part]] + ([plan.contact_penis] if plan.contact_penis is not None else [])
    plan.roi = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    what = tr("sep.list").join(f"{p} {s:.1f} px" for p, s in sizes.items())
    plan.base_note = plan.note = tr("sep.note").join(filter(None, [plan.note, tr("pipe.contact_switch", part=part, what=what)]))


def _source_signal(plan: ScenePlan, opts: PipelineOptions) -> ProcessedSignal:
    """The scene's signal from its source, after the region pick's check."""
    t, x = plan.source
    if plan.mode != "flow":
        return analyze(t, x, replace(opts.signal, rhythm_filter=False))
    p = replace(opts.signal, min_amplitude=MIN_AMPLITUDE_PX)
    sig = analyze(t, x, p)
    if plan.pick_source is not None:
        sig = _apply_pick(plan, sig, opts, p)
    return sig


def _scene_signal(plan: ScenePlan, opts: PipelineOptions, flow: FlowTracker | None, poses: list[PoseFrame]) -> ProcessedSignal:
    """_scene_source and _source_signal in one step."""
    _scene_source(plan, opts, flow, poses)
    return _source_signal(plan, opts)


def _apply_pick(plan: ScenePlan, sig: ProcessedSignal, opts: PipelineOptions, p) -> ProcessedSignal:
    """Switch to the VLM's region if its signal is not less periodic than the original region's.

    The VLM alone replaces good regions too often (validation: 8 scenes worse, 6 better); a region
    with the right content has at least as clear a rhythm.
    """
    t, x = plan.pick_source
    alt = analyze(t, x, p)
    rhythm = lambda s: periodicity(s.smooth, p.fps, 0.15, 2.0)[1]  # noqa: E731
    old, new = rhythm(sig), rhythm(alt)
    if new > 0 and new >= old + opts.region_pick_margin:  # no rhythm in either: no reason to switch
        switched = tr("pipe.pick_used", pick_name=plan.pick_name, old=format(old, ".2f"), new=format(new, ".2f"))
        plan.note = tr("sep.note").join(filter(None, [plan.note, switched]))
        plan.roi = plan.pick_roi
        if plan.sign_pattern is not None:
            plan.sign_pattern, plan.sign_margin, plan.flow_position = plan.pick_pattern, plan.pick_margin, (t, x)
        return alt
    why = tr("pipe.pick_no_rhythm") if new <= 0 else tr("pipe.pick_lower", new=format(new, ".2f"), old=format(old, ".2f"))
    plan.note = tr("sep.note").join(filter(None, [plan.note, tr("pipe.pick_kept", pick_name=plan.pick_name, why=why)]))
    return sig


def _anchor_weight(plan: ScenePlan) -> float:
    sp = plan.sign_pattern
    cells = int((np.hypot(sp[..., 0], sp[..., 1]) > 1e-6).sum()) if sp is not None else 0
    span = motion_size(plan.flow_position[1]) if plan.flow_position is not None else 0.0
    return (plan.sign_margin or 0.0) * max(cells, 1) * max(span, 1e-6)


def align_chunks(plans: list[ScenePlan], opts: PipelineOptions) -> None:
    """Give the chunks of one long shot a consistent stroke sign.

    Within each run of continued scenes that carry a sign pattern, the chunk with the clearest vertical
    displacement across its tracked area keeps its sign; going outwards from it, each chunk is flipped
    when its pattern points against its already-aligned neighbour's. A weak match (|cosine| below the
    threshold) keeps the chunk's own sign.
    """
    runs: list[list[int]] = []
    for k, plan in enumerate(plans):
        usable = plan.signal is not None and plan.sign_pattern is not None and plan.flow_position is not None
        prev = runs[-1][-1] if runs else None
        if usable and plan.scene.continued and prev == k - 1:
            runs[-1].append(k)
        elif usable:
            runs.append([k])
    p = replace(opts.signal, min_amplitude=MIN_AMPLITUDE_PX)
    for run in runs:
        if len(run) < 2:
            continue
        anchor = max(run, key=lambda k: _anchor_weight(plans[k]))
        a = run.index(anchor)
        for order in (run[a + 1:], run[a - 1::-1] if a else []):
            ref = anchor
            for k in order:
                sim = _cosine(plans[k].sign_pattern, plans[ref].sign_pattern)
                if sim <= -opts.chunk_align_similarity:
                    plan = plans[k]
                    plan.sign_pattern = -plan.sign_pattern
                    t, x = plan.flow_position
                    plan.flow_position = (t, -x)
                    plan.signal = analyze(t, -x, p)
                    note = tr("pipe.flip_by_shot", start=format(plans[anchor].scene.start_ms / 1000, ".0f"), sim=format(sim, ".2f"))
                    plan.note = tr("sep.note").join(filter(None, [plan.note, note]))
                ref = k


SOUND_NOTE_MIN = 0.1  # a flip's note names the sound when its onsets are at least this clearly at the highs


def flip_by_asymmetry(
    plans: list[ScenePlan], opts: PipelineOptions, envelope: tuple[np.ndarray, np.ndarray] | None = None,
) -> None:
    """Record each flow scene's fall/rise asymmetry; with `asym_sign`, flip the scenes that clearly rise faster,
    without it only note that they may be inverted (a hint for flipping them by hand). With the sound's onset
    `envelope` (and `asym_audio`), scenes need less asymmetry unless their sound onsets fall at the lows (the sign
    looks right). Scenes the part check flipped are left alone.

    Chunks of one shot whose motion patterns match (cosine >= chunk_align_similarity, the same sign after
    align_chunks) are judged together on their stroke-weighted asymmetry (and duration-weighted onset phase), so
    they keep one sign. It is judged on the output: with `invert` the whole output is mirrored, so rising fast
    before it means falling fast after it, and onsets at its lows are at the output's highs.
    """
    groups: list[list[tuple[ScenePlan, int]]] = []  # (plan, strokes)
    for plan in plans:
        if plan.signal is None or plan.flow_position is None:
            continue
        plan.asym, n = fall_rise_asymmetry(plan.flow_position[1], sample_rate(plan.flow_position[0], opts.fps))
        if envelope is not None and opts.asym_audio:
            plan.audio_sign = onset_phase(*plan.flow_position, *envelope, opts.asym_audio_phase)
        if plan.part_flipped:  # measured, not guessed
            continue
        prev = groups[-1][-1][0] if groups else None
        linked = prev is not None and plan.scene.continued and prev.scene.index == plan.scene.index - 1 \
            and plan.sign_pattern is not None and prev.sign_pattern is not None \
            and _cosine(plan.sign_pattern, prev.sign_pattern) >= opts.chunk_align_similarity
        if linked:
            groups[-1].append((plan, n))
        else:
            groups.append([(plan, n)])
    p = replace(opts.signal, min_amplitude=MIN_AMPLITUDE_PX)
    out = -1.0 if opts.invert else 1.0
    for group in groups:
        strokes = sum(n for _, n in group)
        heard = [(plan.audio_sign, plan.scene.end_ms - plan.scene.start_ms) for plan, _ in group
                 if plan.audio_sign is not None]
        audio = out * sum(a * d for a, d in heard) / sum(d for _, d in heard) if heard else None
        asym = out * sum(plan.asym * n for plan, n in group) / strokes if strokes else 0.0
        # the lower threshold unless the sound says keep: 1 up to onsets evenly spread (0), 0 from +asym_audio_min
        audio_share = 1.0 - min(1.0, max(0.0, audio) / opts.asym_audio_min) \
            if (opts.asym_audio and audio is not None and opts.asym_audio_min > 0) else 0.0
        threshold = opts.asym_sign_threshold - audio_share * (opts.asym_sign_threshold - opts.asym_audio_threshold)
        backed = opts.asym_audio and audio is not None and audio <= -SOUND_NOTE_MIN \
            and (audio < -opts.asym_audio_min or asym <= opts.asym_sign_threshold)
        if strokes < opts.asym_sign_min_strokes or asym <= threshold:
            if opts.sound_hint and audio is not None and audio < -opts.sign_doubt_audio:  # kept, the sound disagrees
                doubt = tr("pipe.sound_doubt", audio=format(audio, ".2f"))
                for plan, _ in group:
                    plan.sign_doubt = doubt
                    plan.note = tr("sep.note").join(filter(None, [plan.note, doubt]))
            continue
        what = tr("pipe.asym_group", n=len(group)) if len(group) > 1 else ""
        sound = tr("pipe.asym_sound", audio=format(audio, ".2f")) if backed else ""
        note = (tr("pipe.asym_note", what=what, asym=format(asym, ".2f"), sound=sound)
                + tr("pipe.direction_flipped" if opts.asym_sign else "pipe.possibly_inverted"))
        for plan, _ in group:
            if not opts.asym_sign:
                plan.asym_hint = True
                plan.note = tr("sep.note").join(filter(None, [plan.note, note]))
                continue
            t, x = plan.flow_position
            plan.flow_position, plan.asym, plan.asym_flipped = (t, -x), -plan.asym, True
            if plan.audio_sign is not None:
                plan.audio_sign = -plan.audio_sign
            if plan.sign_pattern is not None:
                plan.sign_pattern = -plan.sign_pattern
            plan.signal = analyze(t, -x, p)
            plan.note = tr("sep.note").join(filter(None, [plan.note, note]))


class PartScan:
    """The part check's detection (see PipelineOptions.part_sign), started in the background once the scenes are cut:
    it needs neither the AI's answers nor the flow, so it overlaps both. With `defer` no scene starts until `start()`
    names the ones worth detecting (the AI saw somebody in them), so empty scenes do not take the CPU first. Each scene is scanned at part_scan_fps and
    detected at part_fps when a penis shows in part_min_share of the scan, in pieces (parts.PIECE_S) so that videos
    of one or two scenes use all part_workers too. `close()` stops it (cancel, errors).
    """

    def __init__(self, scenes: list[Scene], video: Path, opts: PipelineOptions, detector=None,
                 defer: bool = False) -> None:
        self.error: str | None = None
        self.device: str | None = None
        self.jobs: dict[int, Future] = {}
        self.stop = threading.Event()
        self.pool: ThreadPoolExecutor | None = None
        self.pieces: ThreadPoolExecutor | None = None
        if detector is None:
            from funscript_gen.devices import DeviceError, use_gpu, wanted
            from funscript_gen.tracking.parts import PartDetector

            try:
                detector = PartDetector(gpu=use_gpu("part", opts), require_gpu=wanted("part", opts) == "gpu")
            except DeviceError:
                raise  # set to gpu: stop instead of noting it on the scenes
            except Exception as e:  # noqa: BLE001 - no network for the first download, broken model file...
                self.error = str(e)
                return
        self.detector, self.video, self.opts = detector, video, opts
        self.device = getattr(detector, "device", None)
        self.pieces = ThreadPoolExecutor(max_workers=max(1, opts.part_workers))  # runs the detector
        self.pool = ThreadPoolExecutor(max_workers=max(1, opts.part_workers))  # scenes, waiting for their pieces
        self.jobs = {}
        if not defer:
            self.start(scenes)

    def start(self, scenes: list[Scene]) -> None:
        """Queue these scenes' detection (those already queued are kept)."""
        if self.pool is None or self.stop.is_set():
            return
        for s in scenes:
            if s.index not in self.jobs:
                self.jobs[s.index] = self.pool.submit(self._detect, s)

    def _detect(self, scene: Scene):
        from funscript_gen.tracking.parts import cached_detect_span, penis_share

        o = self.opts
        _, scan, _ = cached_detect_span(self.detector, self.video, scene.start_ms, scene.end_ms, o.part_scan_fps,
                                        stop=self.stop, pool=self.pieces)
        if self.stop.is_set() or len(scan) < 2 or penis_share(scan) < o.part_min_share:
            return None
        return cached_detect_span(self.detector, self.video, scene.start_ms, scene.end_ms, o.part_fps,
                                  conf=o.part_conf, stop=self.stop, pool=self.pieces)

    def close(self) -> None:
        self.stop.set()
        for pool in (self.pool, self.pieces):  # the scenes first: they wait for their pieces
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)


def collect_parts(plans: list[ScenePlan], video: Path, opts: PipelineOptions, detector=None,
                  tick: Callable[[float], None] | None = None, scan: PartScan | None = None) -> tuple[str | None, str | None]:
    """The part check's boxes (see PipelineOptions.part_sign) for the flow scenes whose sign is open, into each
    plan's `parts_found`. Takes them from `scan` (started with the scene cut) or detects them now. `tick(share)`
    reports progress and may raise to cancel. Returns (the detector's onnxruntime provider, why the detector could
    not be used); the provider is None when no scene needed it.
    """
    todo = [p for p in plans if p.flow_position is not None and not p.skip]
    own = scan is None and bool(todo)
    if own:
        scan = PartScan([p.scene for p in todo], video, opts, detector)
    try:
        if not todo:
            return None, None
        if scan.error is not None:
            return None, scan.error
        wanted = {p.scene.index for p in todo}
        for index, job in scan.jobs.items():
            if index not in wanted:
                job.cancel()  # skipped, resting or pose scenes: not started yet, so not detected at all
        for k, plan in enumerate(todo):
            plan.parts_found = scan.jobs[plan.scene.index].result()
            if tick:
                tick((k + 1) / len(todo))
    finally:
        if own:
            scan.close()
    return scan.device, None


def flip_by_parts(plans: list[ScenePlan], opts: PipelineOptions, error: str | None = None) -> None:
    """Experimental part check (see PipelineOptions.part_sign): flip the flow scenes whose penis-vulva distance
    (from collect_parts) moves against the output. Chunks of one shot whose motion patterns match after align_chunks
    are judged together by their duration-weighted clear part_sign so they keep one sign. Judged on the output, as
    the asymmetry check: with `invert` the output is the flow position mirrored. `error`: the detector could not be
    used (noted on the scenes)."""
    from funscript_gen.tracking.parts import penis_vulva_distance, distance_sign

    todo = [p for p in plans if p.signal is not None and p.flow_position is not None and not p.skip]
    if error is not None:
        for plan in todo:
            plan.note = tr("sep.note").join(filter(None, [plan.note, tr("pipe.part_unavailable", error=error)]))
        return
    p = replace(opts.signal, min_amplitude=MIN_AMPLITUDE_PX)
    out = -1.0 if opts.invert else 1.0
    groups: list[list[ScenePlan]] = []
    for plan in todo:
        got = plan.parts_found
        if got is not None:
            times, boxes, size = got
            dist, edge = penis_vulva_distance(boxes, size)
            if edge < opts.part_max_edge:
                t, x = plan.flow_position
                r = distance_sign(np.array(times), dist, t, x, opts.part_fps, opts.part_min_cover)
                if r is not None:
                    plan.part_sign = out * r
        prev = groups[-1][-1] if groups else None
        linked = prev is not None and plan.scene.continued and prev.scene.index == plan.scene.index - 1 \
            and plan.sign_pattern is not None and prev.sign_pattern is not None \
            and _cosine(plan.sign_pattern, prev.sign_pattern) >= opts.chunk_align_similarity
        if linked:
            groups[-1].append(plan)
        else:
            groups.append([plan])
    for group in groups:
        clear = [(plan.part_sign, plan.scene.end_ms - plan.scene.start_ms) for plan in group
                 if plan.part_sign is not None and abs(plan.part_sign) >= opts.part_sign_threshold]
        if not clear:
            continue
        ps = sum(s * d for s, d in clear) / sum(d for _, d in clear)
        if abs(ps) < opts.part_sign_threshold:
            continue
        if ps > 0:
            for plan in group:
                val = plan.part_sign if (plan.part_sign is not None and abs(plan.part_sign) >= opts.part_sign_threshold) else ps
                plan.note = tr("sep.note").join(filter(None, [plan.note, tr("pipe.part_agrees", part_sign=format(val, "+.2f"))]))
            continue
        for plan in group:
            t, x = plan.flow_position
            val = plan.part_sign if (plan.part_sign is not None and abs(plan.part_sign) >= opts.part_sign_threshold) else ps
            plan.flow_position, plan.part_flipped = (t, -x), True
            if plan.part_sign is not None:
                plan.part_sign = -plan.part_sign
            if plan.sign_pattern is not None:
                plan.sign_pattern = -plan.sign_pattern
            plan.signal = analyze(t, -x, p)
            plan.note = tr("sep.note").join(filter(None, [plan.note, tr("pipe.part_disagrees", part_sign=format(val, "+.2f"))]))


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return 0.0
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na <= 0 or nb <= 0:
        return 0.0
    ma = np.hypot(a[..., 0], a[..., 1]) > 1e-6
    mb = np.hypot(b[..., 0], b[..., 1]) > 1e-6
    mask = ma & mb
    n_over = int(mask.sum())
    if n_over >= 4:
        am = a[mask]
        bm = b[mask]
        nam = float(np.linalg.norm(am))
        nbm = float(np.linalg.norm(bm))
        if nam > 0 and nbm > 0:
            if (nam / na) ** 2 * int(ma.sum()) >= 0.3 * n_over and (nbm / nb) ** 2 * int(mb.sum()) >= 0.3 * n_over:
                return float((am * bm).sum()) / float(np.sqrt(na * nam * nb * nbm))
    return float((a * b).sum()) / (na * nb)


def finalize(plans: list[ScenePlan], opts: PipelineOptions) -> list[Action]:
    """The output actions from the scenes' actions: flips, bridges at the cuts, range clip, speed limit and holds.

    Cheap (no video or AI), so a scene flipped by hand in the web UI is applied by running it again.
    """
    lo, hi = opts.signal.pos_low, opts.signal.pos_high
    actions: list[Action] = []
    prev: list[Action] = []
    for p in plans:
        scene: list[Action] = []
        if p.rest:  # not a stroke: --invert and flips fix the stroke direction, the rest stays at the top
            actions += [Action(int(p.scene.start_ms), hi), Action(int(p.scene.end_ms) - 1, hi)]
        elif p.signal:
            flip = opts.invert != p.flipped
            scene = [Action(a.at, lo + hi - a.pos) for a in p.signal.actions] if flip else p.signal.actions
            if opts.signal.bridge and prev and scene:  # after the flips: the next scene's direction is final
                actions += bridge_gap(prev, scene, opts.signal)
            actions += scene
        prev = scene
    # After flipping: the cap is on the output's high end, the tip of the stroke.
    actions = clip_range(actions, plans, lo, hi)
    actions = limit_speed(actions, opts.signal.max_speed)
    return insert_holds(actions, opts.signal.hold_after_ms) if opts.signal.hold else actions


def flipped_scenes(plans: list[ScenePlan]) -> list[int]:
    return [p.scene.index for p in plans if p.flipped]


def refinalize(result: PipelineResult, opts: PipelineOptions) -> None:
    """Rebuild result.funscript after scenes' `flipped` changed, keeping its metadata."""
    import re

    meta = dict(result.funscript.metadata)
    if "notes" in meta:
        meta["notes"] = re.sub(r"flipped=\[[^\]]*\]", f"flipped={flipped_scenes(result.plans)}", meta["notes"])
    result.funscript = Funscript(actions=finalize(result.plans, opts), metadata=meta).normalized()


def toggle_flip(plan: ScenePlan) -> None:
    plan.flipped = not plan.flipped
    note = tr("pipe.manual_flip")
    parts = [n for n in plan.note.split(tr("sep.note")) if n and n != note] if plan.note else []
    plan.note = tr("sep.note").join(parts + ([note] if plan.flipped else []))


def generate(video: str | Path, opts: PipelineOptions | None = None, progress: Progress | None = None) -> PipelineResult:
    """The script for `video`: analyze_video, then render."""
    opts = opts or PipelineOptions()
    return render(analyze_video(video, opts, progress), opts)


def analyze_video(video: str | Path, opts: PipelineOptions | None = None, progress: Progress | None = None) -> VideoAnalysis:
    """The expensive steps: scene cut, AI plan, optical flow (or skeletons), part detection and the sound's onsets.
    `progress(phase, value)` reports them and may raise to stop."""
    from funscript_gen import devices
    from funscript_gen.options import analysis_key, values_of

    opts = opts or PipelineOptions()
    video = Path(video)
    report = progress or (lambda phase, t: None)
    st = video.stat()
    devices.check(opts)  # a step set to gpu without one: stop before the scene cut
    flow_gpu = opts.mode != "pose" and devices.use_gpu("flow", opts)
    scenes = detect_scenes(video, threshold=opts.scene_threshold, on_frame=lambda t: report("scenes", t))
    # The part check's detection runs alongside the flow and the AI: B03 on the CPU 158 -> 119 s (81 s without it).
    # With the AI, only the scenes it saw somebody in are detected (started when its scene analyses are in).
    parts = PartScan(scenes, video, opts, defer=opts.use_ai) if opts.part_sign else None
    try:
        plans = _analyze(video, opts, report, scenes, flow_gpu, parts)
        device, error = collect_parts(plans, video, opts, tick=lambda share: report("parts", share), scan=parts) \
            if parts is not None else (None, None)
    finally:
        if parts is not None:
            parts.close()  # cancelled or failed: stop detecting
    # Always, although only the asymmetry check's sound backing uses it (about 0.4 s for 4 minutes): a later
    # render may turn it on.
    envelope = onset_envelope(video)
    flow_device = None if opts.mode == "pose" else f"OpenCL: {devices.opencl_gpu()}" if flow_gpu else "CPU"
    return VideoAnalysis(video, analysis_key(values_of(opts)), plans, envelope, (st.st_size, st.st_mtime_ns),
                         device, error, flow_device)


def _pieces(lo: float, hi: float | None, end_ms: float) -> list[tuple[float, float | None]]:
    """[lo, hi) cut into equal pieces of at most FLOW_PIECE_S; `end_ms` is where the scene ends when `hi` is None
    (the last scene, read to the end of the video), and the last piece then also reads to the end."""
    cut = pieces(lo, end_ms, FLOW_PIECE_S * 1000)
    return [*cut[:-1], (cut[-1][0], hi)]


def _analyze(video: Path, opts: PipelineOptions, report: Progress, scenes: list[Scene],
             flow_gpu: bool = False, parts: PartScan | None = None) -> list[ScenePlan]:
    pose = None
    if opts.mode == "pose":
        from funscript_gen.devices import torch_gpu, use_gpu

        device = opts.device or (torch_gpu() if use_gpu("pose", opts) else "cpu")
        pose = PoseTracker(opts.model, device=device, imgsz=opts.max_side)

    # Second pass: per-scene motion. A scene's frames are the ones from its start (the previous scene's end) up to
    # its end, the last scene's up to the end of the video. Each flow field only depends on two frames, so a
    # scene's flow is computed in pieces of at most FLOW_PIECE_S, in parallel, each decoding its own stretch, and
    # joined (FlowTracker.extend: identical fields): one Farneback pass used about 2 of 12 cores (A04: 71 s ->
    # 24 s with 4 workers), and pieces keep the cores busy to the end where whole scenes left one long scene
    # running alone. The flow does not depend on the AI's answers either (the field covers the whole frame,
    # regions are applied when reading it), so it starts before the AI analysis and runs alongside it (A04
    # without cached answers: AI 64 s, flow 26 s). At most FLOW_WAITING pieces hold their flow fields while waiting
    # for the AI.
    bounds = [(scenes[k - 1].end_ms if k else 0.0, s.end_ms if k + 1 < len(scenes) else None)
              for k, s in enumerate(scenes)]
    spans = [_pieces(lo, hi, s.end_ms) for (lo, hi), s in zip(bounds, scenes)]
    # ms of each scene (pose) or piece (flow) processed so far; every key is there from the start, as the
    # progress report sums them while the workers run
    done: dict = {key: 0.0 for key in [*range(len(scenes)), *(span for s in spans for span in s)]}
    stop = threading.Event()
    gate = threading.Semaphore(max(FLOW_WAITING, opts.flow_workers, max(map(len, spans), default=1)))

    def frames(lo: float, hi: float | None, key):
        for frame in iter_frames(video, target_fps=opts.fps, max_side=opts.max_side, start_ms=lo):
            if hi is not None and frame.t_ms >= hi:
                break
            done[key] = frame.t_ms - lo
            yield frame

    def track(lo: float, hi: float | None) -> FlowTracker:
        gate.acquire()
        flow = FlowTracker(None, flow_width=opts.flow_width, gpu=flow_gpu)
        for frame in frames(lo, hi, (lo, hi)):
            if stop.is_set():
                break
            flow.update(frame.t_ms, frame.image)
        return flow

    def finish(k: int, jobs: list[Future]) -> None:
        flows: list[FlowTracker] = []
        error: BaseException | None = None
        for job in jobs:  # every piece that was not cancelled holds a place at the gate
            try:
                flows.append(job.result())
            except BaseException as e:  # noqa: BLE001 - re-raised below, once every place is given back
                error = error or e
            finally:
                gate.release()
        if error is not None:
            raise error
        if not plans[k].skip and not stop.is_set():
            flow = flows[0]
            for piece in flows[1:]:
                flow.extend(piece)
            flow.roi = plans[k].roi
            _scene_source(plans[k], opts, flow, [])

    flow_pool = ThreadPoolExecutor(max_workers=max(1, opts.flow_workers))
    tracks = [[flow_pool.submit(track, lo, hi) for lo, hi in p] for p in spans] if opts.mode != "pose" else []
    try:
        report("ai", 0.0)
        seen = (lambda ps: parts.start([p.scene for p in ps if not p.skip])) if parts is not None else None
        plans = plan_scenes(scenes, opts, lambda share: report("ai", share), seen)
        with ThreadPoolExecutor(max_workers=max(1, opts.flow_workers)) as pool:
            jobs = []
            for k, scene_jobs in enumerate(tracks):
                # a skipped scene's flow is dropped; pieces that never started hold no place at the gate
                live = [job for job in scene_jobs if not (plans[k].skip and job.cancel())]
                if live:
                    jobs.append(pool.submit(finish, k, live))
            pending = set(jobs)
            try:
                while pending:
                    _, pending = wait(pending, timeout=0.5)
                    report("signal", sum(done.values()))  # may raise to cancel (web UI, Ctrl+C)
            except BaseException:
                stop.set()  # stop the flow at once instead of finishing every scene first
                for job in jobs:
                    job.cancel()
                raise
            for job in jobs:
                job.result()  # re-raise a worker's error
    finally:
        stop.set()
        for _ in range(sum(map(len, tracks))):
            gate.release()  # pieces still waiting at the gate return at once
        flow_pool.shutdown(wait=True, cancel_futures=True)
    for k, plan in enumerate(plans):  # the pose tracker keeps state, so pose scenes run one by one
        if not plan.skip and plan.mode == "pose" and pose is not None:
            pose.reset()
            poses: list[PoseFrame] = []
            for frame in frames(*bounds[k], k):
                poses.append(pose(frame))
                report("signal", sum(done.values()))
            _scene_source(plan, opts, None, poses)
    report("signal", sum(done.values()))
    return plans


# Render state: what render() works out per scene. A fresh copy of each analysed scene starts without it.
_RENDER_FIELDS = dict(signal=None, range_max=None, range_min=None, asym=None, audio_sign=None,
                      asym_flipped=False, asym_hint=False, sign_doubt="", part_sign=None, part_flipped=False,
                      flipped=False)


def render_signals(analysis: VideoAnalysis, opts: PipelineOptions) -> list[ScenePlan]:
    """render's first steps: a fresh copy of every analysed scene with its stroke range, its signal (after the region
    pick's check) and the long shots' chunks aligned; no direction check yet."""
    if opts.part_sign and not analysis.key.get("part_sign"):
        raise ValueError("the part check needs an analysis made with it (part_sign)")
    plans = [replace(p, note=p.base_note, **{k: (list(v) if isinstance(v, list) else v) for k, v in _RENDER_FIELDS.items()})
             for p in analysis.plans]
    apply_ranges(plans, opts)
    for plan in plans:
        plan.note = tr("sep.note").join(filter(None, [plan.note, plan.pick_note]))
        if not plan.skip and plan.source is not None:
            plan.signal = _source_signal(plan, opts)
    if opts.chunk_align:
        align_chunks(plans, opts)
    return plans


def render(analysis: VideoAnalysis, opts: PipelineOptions | None = None) -> PipelineResult:
    """The script from an analysis: signals, direction checks, positions and the output's limits. Cheap (no video
    decoding or AI), so one analysis can be rendered with other output settings; the settings that need a new
    analysis are in options.analysis_key (see VideoAnalysis.serves)."""
    opts = opts or PipelineOptions()
    plans = render_signals(analysis, opts)
    if opts.part_sign:
        flip_by_parts(plans, opts, analysis.parts_error)
    envelope = analysis.envelope
    flip_by_asymmetry(plans, opts, envelope)

    # Flow and pose signals have different units, so each mode gets its own full-stroke reference.
    for mode in ("flow", "pose"):
        group = [p.signal for p in plans if p.mode == mode and p.signal is not None]
        scale = reference_scale(group, opts.signal)
        for sig in group:
            sig.actions = to_actions(sig, opts.signal, scene_scale(scale, sig, opts.signal))

    for p in plans:
        if p.scene.index in opts.flip_scenes:
            toggle_flip(p)
    actions = finalize(plans, opts)
    modes = ",".join(sorted({p.mode for p in plans}))
    script = Funscript(
        actions=actions,
        metadata={
            "creator": f"funscript-gen {__version__}",
            "title": analysis.video.stem,
            "notes": f"scenes={len(plans)} modes={modes} ai={opts.use_ai} focus={opts.focus} "
                     f"range={opts.use_ai and opts.stroke_range} rest_empty={opts.use_ai and opts.rest_empty} "
                     f"chunk_align={opts.chunk_align} "
                     f"asym_sign={opts.asym_sign} part_sign={opts.part_sign} "
                     f"flipped={flipped_scenes(plans)} fps={opts.fps}",
            "funscript_gen": provenance_metadata(opts),
        },
    ).normalized()
    return PipelineResult(script, plans, part_device=analysis.part_device if opts.part_sign else None,
                          analysis=analysis, flow_device=analysis.flow_device)



def provenance_metadata(opts: PipelineOptions) -> dict:
    """What made a script: the code (version, source hash, git commit when run from a checkout), the AI model and
    backend, every setting by option name, enough to make it again (`generate` with these options)."""
    from funscript_gen.options import values_of
    from funscript_gen.version import provenance

    model = backend = None
    if opts.use_ai:
        from funscript_gen.config import Settings

        settings = opts.ai_settings or Settings()
        model, backend = settings.vllm_model, settings.vllm_backend
    return provenance() | {"ai_model": model, "ai_backend": backend, "options": values_of(opts)}
