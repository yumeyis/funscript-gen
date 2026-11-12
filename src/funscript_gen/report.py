"""Human-readable views of a pipeline result (shared by the CLI and the web UI)."""

from __future__ import annotations

import numpy as np

from funscript_gen.i18n import column_headers, t
from funscript_gen.export.funscript import Funscript
from funscript_gen.pipeline import PipelineResult


def _clean(a: np.ndarray) -> list:
    return [None if not np.isfinite(v) else round(float(v), 4) for v in a]


def debug_data(result: PipelineResult) -> dict:
    scenes = []
    for p in result.plans:
        sig = p.signal
        scenes.append({
            "start_ms": p.scene.start_ms, "end_ms": p.scene.end_ms, "mode": p.mode, "axis": p.axis,
            "roi": p.roi, "refs": [p.ref_a, p.ref_b], "error": p.error,
            "direction": p.direction, "skip": p.skip, "rest": p.rest, "note": p.note,
            "alt_roi": p.alt_roi, "decisions": p.decisions, "pick": [p.pick_name, p.pick_roi],
            "sign_margin": p.sign_margin, "asym": p.asym, "audio_sign": p.audio_sign, "part_sign": p.part_sign,
            "flipped": p.flipped, "asym_flipped": p.asym_flipped, "part_flipped": p.part_flipped,
            "asym_hint": p.asym_hint, "sign_doubt": p.sign_doubt, "confidence": direction_confidence(p),
            "range_max": p.range_max, "range_min": p.range_min, "parts_found": p.parts_found is not None,
            "range_analysis": p.range_analysis.model_dump(mode="json") if p.range_analysis is not None else None,
            "analysis": p.analysis.model_dump(mode="json") if p.analysis is not None else None,
            "t_ms": _clean(sig.t_ms) if sig else [], "raw": _clean(sig.raw) if sig else [],
            "smooth": _clean(sig.smooth) if sig else [], "tempo_hz": sig.tempo_hz if sig else None,
        })
    return {"scenes": scenes}


def possibly_inverted(result: PipelineResult) -> list[int]:
    """Scene numbers that may be upside down and were not flipped since: the asymmetry check's hint (asym_sign off),
    or a kept scene whose sound onsets fall at the highs (sign_doubt). The reasons are in the scenes' notes."""
    return [p.scene.index for p in result.plans if (p.asym_hint or p.sign_doubt) and not p.flipped]


# How sure the output's direction (up = high or down = high) is, from the evidence the checks found. Measured on the
# 85 validation clips (default settings, scenes with |r| >= 0.3 against the hand-made script, 1,050 scenes): scenes the
# part check or the asymmetry check turned, or with an asymmetry of 0.4 or more, had the right direction in 94% /
# 100% / 88%; an asymmetry of 0.2-0.4 or a clear flow pattern (sign margin >= 0.4) in 83% / 75%; no evidence at all in
# 47% (260 scenes, a quarter of them), which is chance. The same in each group of clips (tuned on or not).
STRONG_ASYM = 0.4
WEAK_ASYM = 0.2
CLEAR_MARGIN = 0.4


def direction_confidence(plan) -> str:
    """"high", "medium" or "low" for a flow scene with actions; "" for the others (nothing to be upside down)."""
    if plan.skip or plan.rest or plan.mode != "flow" or plan.signal is None or not len(plan.signal.actions):
        return ""
    asym = abs(plan.asym) if plan.asym is not None else 0.0
    if plan.part_sign is not None or plan.part_flipped or plan.asym_flipped or asym >= STRONG_ASYM:
        return "high"
    if asym >= WEAK_ASYM or (plan.sign_margin or 0.0) >= CLEAR_MARGIN:
        return "medium"
    return "low"


def unsure_scenes(result: PipelineResult) -> list[int]:
    """Scene numbers whose direction has no evidence (confidence "low"), not flipped by hand and not already among
    possibly_inverted: about half of them are upside down, so they are the ones to look at first."""
    marked = set(possibly_inverted(result))
    return [p.scene.index for p in result.plans
            if direction_confidence(p) == "low" and not p.flipped and p.scene.index not in marked]


# Column ids: English and stable (code finds a column by its id); the headers shown come from the language pack
# (report.col.*), see scene_headers().
FLIP_COLUMN = "flip (click)"
SCENE_COLUMNS = ["#", "start (s)", "end (s)", "mode", "axis", "roi", "body parts", "actions", FLIP_COLUMN, "direction", "note"]


def scene_headers() -> list[str]:
    return column_headers(SCENE_COLUMNS, "report.col")


def flip_label(plan) -> str:
    if plan.signal is None or not len(plan.signal.actions):
        return "-"
    return t("report.flipped") if plan.flipped else "⇅"


def scene_rows(result: PipelineResult) -> list[list]:
    rows = []
    for p in result.plans:
        fmt_roi = lambda r: "full frame" if r is None else ", ".join(f"{v:.2f}" for v in r)  # noqa: E731
        roi = fmt_roi(p.roi)
        if p.decisions:  # hybrid: genital region / general region
            roi = f"target {fmt_roi(p.roi) if p.roi else '-'} | general {fmt_roi(p.alt_roi)}"
        refs = f"{p.ref_a} / {p.ref_b}" if p.mode == "pose" else "-"
        tempo = t("report.tempo_filter", tempo=format(p.signal.tempo_hz, ".1f")) if p.signal and p.signal.tempo_hz else ""
        note = t("sep.note").join(filter(None, [p.note, tempo, f"AI error: {p.error}" if p.error else ""]))
        n = len(p.signal.actions) if p.signal else 0
        rows.append([p.scene.index, round(p.scene.start_ms / 1000, 1), round(p.scene.end_ms / 1000, 1),
                     "rest" if p.rest else "skip" if p.skip else p.mode, p.axis, roi, refs, n, flip_label(p),
                     t(f"report.conf.{c}") if (c := direction_confidence(p)) else "-", note])
    return rows


def plot_result(result: PipelineResult, reference: Funscript | None = None):
    """Matplotlib figure: per-scene motion signal on top, generated (and reference) script below."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 6), sharex=True)
    for p in result.plans:
        sig = p.signal
        for ax in (ax1, ax2):
            ax.axvline(p.scene.start_ms / 1000, color="gray", lw=0.5, ls="--")
        if sig is None or not len(sig.t_ms):
            continue
        t = sig.t_ms / 1000
        span = np.where(np.isfinite(sig.hi - sig.lo), np.maximum(sig.hi - sig.lo, 1e-9), 1.0)
        ax1.plot(t, (sig.raw - sig.lo) / span, lw=0.6, alpha=0.4, color="C0")
        ax1.plot(t, (sig.smooth - sig.lo) / span, lw=1.0, color="C1")
    ax1.set_ylabel("motion signal")
    if reference is not None:
        ax2.plot([a.at / 1000 for a in reference.actions], [a.pos for a in reference.actions],
                 lw=0.8, color="black", alpha=0.6, label="reference")
    acts = result.funscript.actions
    ax2.plot([a.at / 1000 for a in acts], [a.pos for a in acts], marker=".", lw=0.8, color="C1", label="generated")
    if reference is not None:
        ax2.legend(loc="upper right")
    ax2.set_ylim(-5, 105)
    ax2.set_ylabel("pos")
    ax2.set_xlabel("time (s)")
    fig.tight_layout()
    return fig
