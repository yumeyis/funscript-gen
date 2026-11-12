"""Which way is up: the checks that decide a scene's stroke direction (sign) and the hand flips.

The checks run in this order (pipeline.render): the chunks of a long shot are aligned with each other (align_chunks), the
part boxes can turn a scene (flip_by_parts), then the fall/rise asymmetry with the sound (flip_by_asymmetry). They work
on the ScenePlans the analysis made and change them in place. The classes are in pipeline.py (the saved analyses name
them there); they are only imported here for the annotations.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from funscript_gen.i18n import t as tr
from funscript_gen.signal.audio import onset_phase
from funscript_gen.signal.process import analyze, fall_rise_asymmetry
from funscript_gen.tracking.flow import MIN_AMPLITUDE_PX, sample_rate

if TYPE_CHECKING:
    from funscript_gen.pipeline import PipelineOptions, PipelineResult, ScenePlan


def motion_size(x: np.ndarray) -> float:
    """How far a position moves: the spread between its 5th and 95th percentiles."""
    return float(np.percentile(x, 95) - np.percentile(x, 5)) if len(x) else 0.0


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


def flipped_scenes(plans: list[ScenePlan]) -> list[int]:
    return [p.scene.index for p in plans if p.flipped]


def carry_flips(old: PipelineResult, manual: set[int], new: PipelineResult) -> list[int]:
    """Numbers of the scenes of `new` to flip so that the direction a person chose by hand in `old` stays: where a new
    scene mostly lies in a scene of `old` flipped by hand (`manual`, by number) and its output runs against the old
    one there (correlation below -0.3 on a 50 ms grid), it is flipped. Other settings can give other scenes, other
    regions and another automatic direction, so the old flips are not repeated by number; the old output is what they
    are kept against (hand edits included)."""
    spans = [(p.scene.start_ms, p.scene.end_ms) for p in old.plans if p.scene.index in manual]
    oa, na = old.funscript.actions, new.funscript.actions
    if not spans or len(oa) < 2 or len(na) < 2:
        return []
    ot, ov = np.array([a.at for a in oa], float), np.array([a.pos for a in oa], float)
    nt, nv = np.array([a.at for a in na], float), np.array([a.pos for a in na], float)
    out = []
    for p in new.plans:
        s, e = p.scene.start_ms, p.scene.end_ms
        if p.skip or p.rest or p.signal is None or not len(p.signal.actions) or e <= s:
            continue
        inside = sum(max(0.0, min(e, b) - max(s, a)) for a, b in spans)
        grid = np.arange(s, e, 50.0)
        if inside < 0.5 * (e - s) or len(grid) < 4:
            continue
        x, y = np.interp(grid, ot, ov), np.interp(grid, nt, nv)
        if x.std() > 0 and y.std() > 0 and float(np.corrcoef(x, y)[0, 1]) < -0.3:
            out.append(p.scene.index)
    return out


def toggle_flip(plan: ScenePlan) -> None:
    plan.flipped = not plan.flipped
    note = tr("pipe.manual_flip")
    parts = [n for n in plan.note.split(tr("sep.note")) if n and n != note] if plan.note else []
    plan.note = tr("sep.note").join(parts + ([note] if plan.flipped else []))
