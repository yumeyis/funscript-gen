"""Every user setting in one table: the CLI's `generate` options, the web UI's Generate form, the remembered form
(.webui-last.json), presets and the options written into a funscript's metadata are all built from OPTIONS.

An option's value is in "form" terms (what the web UI shows and saves): "" for "the AI decides", a region as the text
"x1,y1,x2,y2". build() turns a full set of values into PipelineOptions.

The texts the web UI shows are in the language packs, not here: opt.<name>.label (the option is in the web UI when
`ui` is set), .info, .placeholder and .choice.<value> for each of `values`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Any

from funscript_gen.i18n import t, tt
from funscript_gen.pipeline import DEFAULT_FLOW_WORKERS, PipelineOptions
from funscript_gen.tracking.metrics import KEYPOINT_GROUPS


@dataclass(frozen=True)
class Opt:
    name: str  # also the key in .webui-last.json and presets, and the CLI flag (--name, underscores as dashes)
    kind: str  # "bool" | "int" | "float" | "choice" | "text"
    default: Any
    # PipelineOptions attributes ("signal.x" for SignalParams); () = not a pipeline setting (web UI only)
    targets: tuple[str, ...] = ()
    help: str = ""  # CLI help; "" = not on the CLI
    flag: str = ""  # CLI name when it is not the option's name ("ai" -> --ai/--no-ai)
    ui: bool = False  # in the web UI (its label, info, placeholder and choice names are in the language packs)
    group: str = ""  # web UI section, see GROUPS
    row: str = ""  # web UI: neighbouring options with the same row sit side by side
    show_if: str = ""  # web UI: shown only while this switch is on
    slider: tuple[float, float, float] | None = None  # web UI (min, max, step)
    values: tuple[Any, ...] = ()  # the values of a choice
    control: str = ""  # web UI: "segmented" shows a choice as a segmented control
    # Valid numbers: (low, high, low excluded, high excluded); None = any.
    valid: tuple[float, float, bool, bool] | None = None
    # "analysis": changing it means analysing the video again (scene cut, AI, optical flow or detection);
    # "render": only the steps after the analysis; "run": no effect on the output (parallelism)
    stage: str = "render"

    @property
    def cli_name(self) -> str:
        return "--" + (self.flag or self.name).replace("_", "-")

    @property
    def label(self) -> str:
        return tt(f"opt.{self.name}.label", self.name) if self.ui else ""

    @property
    def info(self) -> str:
        return tt(f"opt.{self.name}.info", "")

    @property
    def placeholder(self) -> str:
        return tt(f"opt.{self.name}.placeholder", "")

    @property
    def choices(self) -> tuple[tuple[str, Any], ...]:
        """(name shown, value) for each of `values`."""
        return tuple((self.choice_label(v), v) for v in self.values)

    def choice_label(self, value) -> str:
        if value == "":
            return t("choice.ai_decides")
        return tt(f"opt.{self.name}.choice.{value}", tt(f"choice.{value}", str(value)))

    @property
    def short_label(self) -> str:
        return re.split(r"\s*[（(]", self.label)[0] or self.name


GROUPS = ("ai", "motion", "output", "device", "advanced")  # web UI sections; their titles are group.<name>


def group_title(group: str) -> str:
    return t(f"group.{group}")

_AXES = (("vertical", "vertical"), ("horizontal", "horizontal"), ("depth", "depth"), ("distance", "distance"), ("auto", "auto"))
_PARTS = tuple(KEYPOINT_GROUPS)
_COMPUTE = ("auto", "gpu", "cpu")

OPTIONS: tuple[Opt, ...] = (
    # --- AI 分析 ---
    Opt("use_ai", "bool", True, ("use_ai",), flag="ai", stage="analysis", group="ai",
        help="Use the vLLM model to pick region/axis/body parts per scene",
        ui=True),
    Opt("focus", "choice", "general", ("focus",), stage="analysis", group="ai",
        help="general | hybrid (also a target-region analysis: per frame the target region when the active part is visible "
             "and not occluded, else the general one)",
        values=("general", "hybrid"),
        ui=True),
    Opt("region_pick", "bool", True, ("region_pick",), stage="analysis", group="ai",
        help="General focus: let the AI pick the region among numbered candidates (one more AI call per scene); "
             "used when its signal is at least as periodic as the original region's",
        ui=True),
    Opt("contact_pick", "bool", True, ("contact_pick",), stage="analysis", group="ai",
        help="Hybrid focus: when the AI's two most likely contact parts are the hand and the mouth, it boxes both and "
             "the one that moves more is followed (one or two more AI calls in those scenes; vLLM only)",
        ui=True),
    Opt("contact_min_prob", "float", 0.1, ("contact_min_prob",), valid=(0, 1, False, False), stage="analysis",
        group="ai", row="contact", show_if="contact_pick", slider=(0, 0.5, 0.01),
        help="The contact pick runs only when the second of the hand and the mouth is at least this likely",
        ui=True),
    Opt("stroke_range", "bool", True, ("stroke_range",), stage="analysis", group="ai",
        help="Per scene the AI checks whether the whole active part and its tip are visible (one more AI call per scene); "
             "tip not seen: positions are clipped to at most --range-cap; tip seen but the active part not whole: "
             "to at least --range-floor",
        ui=True),
    Opt("range_cap", "int", 80, ("range_cap",), valid=(0, 100, False, False), group="ai", row="range",
        show_if="stroke_range", slider=(0, 100, 1),
        help="Highest position in scenes where the tip of the active part is not seen", ui=True),
    Opt("range_floor", "int", 20, ("range_floor",), valid=(0, 100, False, False), group="ai", row="range",
        show_if="stroke_range", slider=(0, 100, 1),
        help="Lowest position in scenes where the tip is seen but the active part is not whole",
        ui=True),
    Opt("rest_empty", "bool", True, ("rest_empty",), stage="analysis", group="ai",
        help="Scenes in which the AI sees nobody (intros, titles, black frames) hold at the top of the range "
             "instead of following the picture's motion",
        ui=True),
    # --- 動作偵測 ---
    Opt("mode", "choice", "auto", ("mode",), stage="analysis", group="motion",
        help="auto (= flow) | flow (optical flow) | pose (skeletons; needs `uv sync --extra pose`)",
        values=("auto", "flow", "pose"),
        ui=True),
    Opt("axis", "choice", "", ("axis",), stage="analysis", group="motion",
        help="Override axis: vertical | horizontal | depth | distance | auto",
        values=("", "vertical", "horizontal", "depth", "distance", "auto"),
        ui=True),
    Opt("roi", "text", "", ("roi",), stage="analysis", group="motion",
        help="Override region x1,y1,x2,y2 (0..1)", ui=True),
    Opt("ref_a", "choice", "", ("ref_a",), stage="analysis", group="motion", row="refs",
        help=f"Override body part of A: {', '.join(KEYPOINT_GROUPS)}", values=("",) + _PARTS,
        ui=True),
    Opt("ref_b", "choice", "", ("ref_b",), stage="analysis", group="motion", row="refs",
        help="Override body part of B", values=("",) + _PARTS, ui=True),
    # --- 輸出 ---
    Opt("range_low", "int", 0, ("signal.pos_low",), valid=(0, 100, False, False), group="output", row="out_range",
        slider=(0, 100, 1), help="Output position for the low end of a stroke", ui=True),
    Opt("range_high", "int", 100, ("signal.pos_high",), valid=(0, 100, False, False), group="output", row="out_range",
        slider=(0, 100, 1), help="Output position for the high end of a stroke", ui=True),
    Opt("amplitude", "choice", "preserve", ("signal.amplitude",), group="output",
        help="preserve: small motion -> short stroke | fill: every stroke full length",
        values=("preserve", "fill"), ui=True),
    Opt("gain", "float", 1.0, ("signal.gain",), valid=(0, math.inf, True, False), group="output", slider=(0.3, 3.0, 0.05),
        help="Stroke length multiplier in preserve mode", ui=True),
    Opt("invert", "bool", False, ("invert",), group="output", help="Flip positions (100 - pos)", ui=True),
    Opt("chunk_align", "bool", True, ("chunk_align",), group="output",
        help="Keep one stroke direction across the 20 s chunks of a long shot: the chunk whose direction was "
             "clearest sets it for chunks with a matching motion pattern",
        ui=True),
    Opt("asym_sign", "bool", True, ("asym_sign",), group="output",
        help="Flip scenes whose strokes clearly rise faster than they fall (hand-made scripts mostly "
             "fall faster: the push in is the way in); scenes with an AI direction are left alone",
        ui=True),
    Opt("asym_threshold", "float", 0.5, ("asym_sign_threshold",), valid=(0, math.inf, True, False), group="output",
        row="asym", show_if="asym_sign", slider=(0.2, 1.5, 0.05),
        help="--asym-sign: flip when the rises' median peak speed is above e^this times the falls' (0.5 = 1.65x)",
        ui=True),
    Opt("asym_audio", "bool", True, ("asym_audio",), group="output", row="asym", show_if="asym_sign",
        help="--asym-sign: use --asym-audio-threshold unless the sound's onsets (impacts) fall at a scene's "
             "lows (impacts land at the bottom of a thrust, so the direction looks right)",
        ui=True),
    Opt("asym_audio_threshold", "float", 0.2, ("asym_audio_threshold",), valid=(0, math.inf, True, False),
        group="output", row="asym", show_if="asym_sign", slider=(0.05, 1.5, 0.05),
        help="--asym-sign threshold for scenes whose sound onsets do not fall at the lows", ui=True),
    Opt("sound_hint", "bool", False, ("sound_hint",), group="output",
        help="List kept scenes whose sound onsets fall at the highs as possibly upside down (to check by hand)",
        ui=True),
    Opt("part_sign", "bool", True, ("part_sign",), stage="analysis", group="output",
        help="An anime part detector measures the active part–counterpart distance (apart = pulled back = high) "
             "and flips scenes whose distance moves against the output; downloads a 43 MB model on first use",
        ui=True),
    Opt("part_sign_threshold", "float", 0.2, ("part_sign_threshold",), valid=(0, 1, True, True), group="output",
        row="part", show_if="part_sign", slider=(0.1, 0.8, 0.05),
        help="--part-sign: flip when the distance's correlation with the output is at or below minus this",
        ui=True),
    Opt("max_speed", "float", 500.0, ("signal.max_speed",), valid=(0, math.inf, True, False), group="output",
        slider=(100, 1000, 10), help="Max pos units per second", ui=True),
    Opt("freq_limit", "float", 2.0, ("signal.freq_limit_hz",), valid=(0, math.inf, False, False), group="output",
        row="freq", slider=(0, 5, 0.1),
        help="Strokes faster than this (Hz) get shorter around their centre; 0 turns it off",
        ui=True),
    Opt("freq_max", "float", 3.0, ("signal.freq_max_hz",), valid=(0, math.inf, True, False), group="output",
        row="freq", slider=(0.5, 6, 0.1),
        help="Stroke frequency (Hz) at which the length reaches --freq-min-scale", ui=True),
    Opt("freq_min_scale", "float", 0.5, ("signal.freq_min_scale",), valid=(0, 1, False, False), group="output",
        row="freq", slider=(0.1, 1.0, 0.05),
        help="Stroke length multiplier at --freq-max and above", ui=True),
    Opt("min_prominence", "float", 0.15, ("signal.min_prominence",), valid=(0, 1, True, False), group="output",
        slider=(0.02, 0.6, 0.01), help="Min stroke size as a fraction of local range",
        ui=True),
    Opt("rhythm_filter", "bool", True, ("signal.rhythm_filter",), group="output",
        help="Band-pass optical-flow signals around their tempo when it is clear", ui=True),
    Opt("dwell", "bool", False, ("signal.dwell",), group="output",
        help="Where the motion rests at a turning point, output the start and end of the rest",
        ui=True),
    Opt("dwell_tol", "float", 0.05, ("signal.dwell_tol",), valid=(0, 0.45, True, False), group="output", row="dwell",
        show_if="dwell", slider=(0.01, 0.3, 0.01),
        help="Rest = within this fraction of the stroke size of the turning point (0..0.45)",
        ui=True),
    Opt("dwell_min_ms", "float", 200.0, ("signal.dwell_min_ms",), valid=(0, math.inf, False, False), group="output",
        row="dwell", show_if="dwell", slider=(50, 1000, 10), help="Shorter rests stay a single point",
        ui=True),
    Opt("hold", "bool", False, ("signal.hold",), group="output",
        help="Across pauses longer than --hold-after-ms keep the position instead of moving slowly",
        ui=True),
    Opt("hold_after_ms", "float", 1000.0, ("signal.hold_after_ms",), valid=(0, math.inf, True, False), group="output",
        row="hold", show_if="hold", slider=(500, 5000, 100), help="Gaps longer than this (ms) count as pauses",
        ui=True),
    Opt("curve", "bool", False, ("signal.curve",), group="output",
        help="Add points along strokes longer than --curve-after-ms to follow the motion's shape", ui=True),
    Opt("curve_after_ms", "float", 600.0, ("signal.curve_after_ms",), valid=(0, math.inf, False, False),
        group="output", row="curve", show_if="curve", slider=(200, 3000, 50),
        help="Only strokes longer than this (ms) get extra points", ui=True),
    Opt("curve_tol", "float", 5.0, ("signal.curve_tol",), valid=(0, math.inf, True, False), group="output",
        row="curve", show_if="curve", slider=(1, 30, 1),
        help="Add a point where the motion leaves the straight line by more than this (0..100)",
        ui=True),
    Opt("bridge", "bool", True, ("signal.bridge",), group="output",
        help="At a cut whose next stroke does not continue the previous scene's rhythm, repeat that scene's last "
             "stroke once in the gap",
        ui=True),
    Opt("scene_center", "bool", False, ("signal.scene_center",), group="output",
        help="Experimental: in scenes without a clear tempo, place the strokes around the whole scene's centre "
             "instead of a 4 s window's, so slow strokes keep their height",
        ui=True),
    # --- 運算裝置 ---
    Opt("compute", "choice", "auto", ("compute",), stage="analysis", group="device", control="segmented",
        values=_COMPUTE,
        help="Where the steps that can use a GPU run: auto (a GPU when one is usable, else the CPU) | gpu (stop "
             "when none is usable) | cpu; --flow-compute, --part-compute and --pose-compute set single steps",
        ui=True),
    Opt("flow_compute", "choice", "auto", ("flow_compute",), stage="analysis", group="device", row="compute",
        control="segmented", values=_COMPUTE,
        help="Optical flow: auto (as --compute) | gpu (OpenCL) | cpu", ui=True),
    Opt("part_compute", "choice", "auto", ("part_compute",), stage="analysis", group="device", row="compute",
        control="segmented", values=_COMPUTE,
        help="Part check (--part-sign): auto (as --compute) | gpu (onnxruntime-gpu or -directml) | cpu",
        ui=True),
    Opt("pose_compute", "choice", "auto", ("pose_compute",), stage="analysis", group="device", row="compute",
        control="segmented", values=_COMPUTE,
        help="Skeleton mode (--mode pose): auto (as --compute) | gpu (PyTorch with CUDA) | cpu", ui=True),
    # --- 進階 ---
    Opt("fps", "float", 30.0, ("fps", "signal.fps"), valid=(0, math.inf, True, False), stage="analysis",
        group="advanced", slider=(5, 60, 1), help="Analysis frame rate", ui=True),
    Opt("max_side", "int", 640, ("max_side",), valid=(64, math.inf, False, False), stage="analysis", group="advanced",
        slider=(320, 1280, 32), help="Downscale longest side before analysis", ui=True),
    Opt("flow_width", "int", 480, ("flow_width",), valid=(160, 480, False, False), stage="analysis", group="advanced",
        slider=(160, 480, 16),
        help="Compute optical flow on a frame this wide (160..480; 320 is about twice as fast, nearly the same scores; narrower video such as portrait is not enlarged)",
        ui=True),
    Opt("flow_workers", "int", DEFAULT_FLOW_WORKERS, ("flow_workers",), valid=(1, 16, False, False), stage="run",
        group="advanced", slider=(1, 16, 1),
        help="Optical flow jobs run at the same time, each up to 5 s of a scene (1..16; the output does not "
             "change; default: half the CPU cores, at most 8)",
        ui=True),
    Opt("scene_threshold", "float", 30.0, ("scene_threshold",), valid=(0, math.inf, True, False), stage="analysis",
        group="advanced", slider=(5, 80, 1),
        help="Hard-cut sensitivity: mean colour difference that starts a new scene (lower = more cuts)",
        ui=True),
    Opt("use_reference", "bool", False, group="advanced", ui=True),
    # --- CLI only ---
    Opt("ai_workers", "int", None, ("ai_workers",), valid=(1, 64, False, False), stage="run",
        help="Concurrent AI requests (default: VLLM_CONCURRENCY in .env, 8)"),
    Opt("model", "text", "yolo11n-pose.pt", ("model",), stage="analysis", help="Ultralytics pose model"),
    Opt("device", "text", "", ("device",), stage="analysis",
        help="Pose model device as Ultralytics takes it: cpu, 0, cuda:1 ... (overrides --pose-compute)"),
    Opt("flip_scenes", "text", "", ("flip_scenes",),
        help="Flip the output of these scenes up/down, by the scene numbers printed after generating (e.g. 0,3)"),
)

BY_NAME = {o.name: o for o in OPTIONS}
UI_OPTIONS = tuple(o for o in OPTIONS if o.ui)
CLI_OPTIONS = tuple(o for o in OPTIONS if o.help)

# Named sets of settings on top of the defaults (CLI --preset, the web UI's 設定組). Validation on 25 clips
# (2026-10-31, F1 / correlation ±100 ms): default 0.730 / 0.533, user 0.747 / 0.577.
PRESETS: dict[str, dict[str, Any]] = {
    "default": {},
    "user": {"focus": "hybrid", "dwell": True, "curve": True, "freq_limit": 2.0, "freq_max": 3.0},
}


def preset_label(name: str) -> str:
    return t(f"preset.{name}")


class OptionError(ValueError):
    """An invalid setting, with the message for the CLI (`en`, also str()) and, for the web UI, the pack text `key`
    with `params` (`local`, in the chosen language)."""

    def __init__(self, en: str, key: str, **params) -> None:
        super().__init__(en)
        self.en, self.key, self.params = en, key, params

    @property
    def local(self) -> str:
        return t(self.key, **self.params)


def defaults() -> dict[str, Any]:
    return {o.name: o.default for o in OPTIONS}


def resolve(given: dict[str, Any], preset: str | None = None) -> dict[str, Any]:
    """The defaults, overridden by the preset's settings, overridden by `given` (None in `given` = not given)."""
    if preset is not None and preset not in PRESETS:
        raise OptionError(f"unknown preset {preset} (presets: {', '.join(PRESETS)})",
                          "options.unknown_preset", preset=preset)
    unknown = set(given) - set(BY_NAME)
    if unknown:
        raise OptionError(f"unknown options: {', '.join(sorted(unknown))}",
                          "options.unknown_options", names=", ".join(sorted(unknown)))
    return defaults() | PRESETS.get(preset or "default", {}) | {k: v for k, v in given.items() if v is not None}


def parse_roi(text: str) -> tuple[float, float, float, float] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        v = [float(x) for x in text.split(",")]
    except ValueError:
        v = []
    if len(v) != 4 or not all(0 <= x <= 1 for x in v) or v[0] >= v[2] or v[1] >= v[3]:
        raise OptionError("ROI must be x1,y1,x2,y2 normalized to 0..1",
                          "options.roi_format")
    return v[0], v[1], v[2], v[3]


def parse_scenes(text: str) -> tuple[int, ...]:
    if not (text or "").strip():
        return ()
    try:
        return tuple(sorted({int(v) for v in text.split(",") if v.strip()}))
    except ValueError:
        raise OptionError("scenes must be comma-separated scene numbers, e.g. 0,3",
                          "options.scenes_format")


def _check_one(o: Opt, v: Any) -> None:
    if o.kind == "bool":
        if not isinstance(v, bool):
            raise OptionError(f"{o.cli_name} must be true or false", "options.must_be_bool", name=o.short_label)
    elif o.kind == "choice":
        values = [c[1] for c in o.choices] if o.choices else None
        if values is not None and v not in values:
            shown = ", ".join(str(c) for c in values if c != "")
            raise OptionError(f"{o.cli_name.removeprefix('--')} must be {shown}"
                              + (" (or empty for the AI to decide)" if "" in values else ""),
                              "options.must_be_one_of", name=o.short_label, shown=shown)
    elif o.kind in ("int", "float"):
        if v is None and o.default is None:
            return
        if isinstance(v, bool) or not isinstance(v, (int, float)) or (o.kind == "int" and v != int(v)):
            raise OptionError(f"{o.cli_name} must be a number", "options.must_be_number", name=o.short_label)
        if o.valid is not None:
            lo, hi, lo_open, hi_open = o.valid
            if (v < lo or (lo_open and v == lo)) or (v > hi or (hi_open and v == hi)):
                lo_s = f"above {lo:g}" if lo_open else f"at least {lo:g}"
                span = lo_s if hi == math.inf else f"within {lo:g}..{hi:g}"
                raise OptionError(f"{o.cli_name} must be {span}",
                                  "options.must_be_above" if hi == math.inf else "options.must_be_between",
                                  name=o.short_label, lo=format(lo, "g"), hi=format(hi, "g"))
    elif o.kind == "text" and not isinstance(v, str):
        raise OptionError(f"{o.cli_name} must be text", "options.must_be_text", name=o.short_label)


def check(values: dict[str, Any]) -> None:
    """Raise OptionError for the first invalid setting (each on its own, then the ones that depend on others)."""
    for o in OPTIONS:
        _check_one(o, values[o.name])
    parse_roi(values["roi"])
    parse_scenes(values["flip_scenes"])
    if values["range_low"] >= values["range_high"]:
        raise OptionError("need 0 <= range-low < range-high <= 100", "options.range_low_high")
    if values["stroke_range"] and values["range_cap"] < values["range_low"]:
        raise OptionError("need range-low <= range-cap <= 100", "options.range_cap_low")
    if values["stroke_range"] and values["range_floor"] > values["range_high"]:
        raise OptionError("need 0 <= range-floor <= range-high", "options.range_floor_high")
    if values["freq_limit"] > 0 and values["freq_max"] <= values["freq_limit"]:
        raise OptionError("--freq-max must be above --freq-limit", "options.freq_max_limit")


def _to_pipeline(o: Opt, v: Any) -> Any:
    if o.name == "roi":
        return parse_roi(v)
    if o.name == "flip_scenes":
        return parse_scenes(v)
    if o.kind == "int" and v is not None:
        return int(v)
    if o.kind == "float":
        return float(v)
    if v == "" and o.name in ("axis", "ref_a", "ref_b", "device"):
        return None
    return v


def build(values: dict[str, Any], **extra) -> PipelineOptions:
    """PipelineOptions from a full set of values (see resolve); `extra` sets PipelineOptions fields directly."""
    check(values)
    opts = PipelineOptions(**extra)
    signal = {}
    for o in OPTIONS:
        for target in o.targets:
            value = _to_pipeline(o, values[o.name])
            if target.startswith("signal."):
                signal[target.removeprefix("signal.")] = value
            else:
                setattr(opts, target, value)
    opts.signal = replace(opts.signal, **signal)
    return opts


def _from_pipeline(o: Opt, v: Any) -> Any:
    if o.name == "roi":
        return ",".join(f"{x:g}" for x in v) if v else ""
    if o.name == "flip_scenes":
        return ",".join(map(str, v))
    if v is None and o.default is not None:
        return ""
    return v


def values_of(opts: PipelineOptions) -> dict[str, Any]:
    """The settings of `opts` by option name (the inverse of build, for every option that maps to the pipeline)."""
    out = {}
    for o in OPTIONS:
        if not o.targets:
            continue
        target = o.targets[0]
        obj = opts.signal if target.startswith("signal.") else opts
        out[o.name] = _from_pipeline(o, getattr(obj, target.removeprefix("signal.")))
    return out


def analysis_key(values: dict[str, Any]) -> dict[str, Any]:
    """The settings an analysis of the video depends on (stage "analysis")."""
    return {o.name: values[o.name] for o in OPTIONS if o.stage == "analysis" and o.name in values}


def for_analysis(key: dict[str, Any], given: dict[str, Any], preset: str | None = None) -> dict[str, Any]:
    """Settings for rendering an analysis made with settings `key`: those of the analysis, and for the rest the
    preset's and `given` ones. An analysis setting that is given (or in the preset) and differs is an error: it needs
    the video analysed again. Only the part check may be turned off (its boxes are then not used)."""
    values = resolve(given, preset)
    explicit = {k for k, v in given.items() if v is not None} | set(PRESETS.get(preset or "default", {}))
    for name, value in key.items():
        if name not in explicit:
            values[name] = value
        elif values[name] != value and not (name == "part_sign" and not values[name]):
            o = BY_NAME[name]
            raise OptionError(f"{o.cli_name} differs from the analysis ({value!r}): it needs the video analysed again",
                              "options.differs_from_analysis", name=o.short_label)
    return values
