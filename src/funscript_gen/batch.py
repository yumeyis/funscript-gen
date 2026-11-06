"""Batch generation: many videos one after another with the same settings (CLI `batch`, web UI 批次 tab)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Literal

from funscript_gen.devices import DeviceError
from funscript_gen.pipeline import PipelineOptions, PipelineResult, generate

VIDEO_SUFFIXES = {".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".wmv", ".flv", ".ts", ".mpg", ".mpeg"}


def find_videos(paths: Iterable[str | Path], recursive: bool = False) -> list[Path]:
    """The videos among `paths` in the order given: files as they are (any suffix), folders expanded to the videos in
    them (by suffix, sorted by name; with `recursive` also in their subfolders). A video listed twice is kept once."""
    found: list[Path] = []
    seen: set[Path] = set()
    for path in map(Path, paths):
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            files = sorted((f for f in path.glob(pattern) if f.is_file() and f.suffix.lower() in VIDEO_SUFFIXES),
                           key=lambda f: [part.lower() for part in f.relative_to(path).parts])
        else:
            files = [path]
        for f in files:
            key = f.resolve()
            if key not in seen:
                seen.add(key)
                found.append(f)
    return found


def output_paths(videos: list[Path], output_dir: Path | None = None, stem: Callable[[str], str] = str) -> list[Path]:
    """Where each video's script goes: `<video>.funscript` beside it, or `<stem(name)>.funscript` in `output_dir`
    (players pair a script with the video of the same name). Names that collide in `output_dir` get " (2)", " (3)"..."""
    out: list[Path] = []
    used: set[Path] = set()
    for video in videos:
        base = (output_dir / stem(video.stem)) if output_dir else video.with_suffix("")
        path, n = base.with_name(base.name + ".funscript"), 1
        while path.resolve() in used:
            n += 1
            path = base.with_name(f"{base.name} ({n}).funscript")
        used.add(path.resolve())
        out.append(path)
    return out


Status = Literal["pending", "done", "skipped", "failed", "cancelled"]


@dataclass
class BatchItem:
    video: Path
    output: Path
    status: Status = "pending"
    error: str = ""
    seconds: float = 0.0
    result: PipelineResult | None = field(default=None, repr=False)


def run_batch(
    items: list[BatchItem],
    opts: PipelineOptions,
    overwrite: bool = True,
    on_start: Callable[[int, BatchItem], None] | None = None,
    on_progress: Callable[[int, str, float], None] | None = None,
    on_done: Callable[[int, BatchItem], None] | None = None,
    stopped: Callable[[], bool] = lambda: False,
    keep_results: bool = False,
) -> list[BatchItem]:
    """Generate every item's script in turn and save it to its output. A video that fails is recorded and the next one
    runs (a step set to gpu without a usable GPU raises DeviceError instead); an existing output is kept (status "skipped") unless `overwrite`. When `stopped()` turns true (checked between
    videos, and after a video fails: a progress callback may raise to stop it) the rest are "cancelled".
    `on_progress(k, phase, t_ms)` gets generate()'s progress for item k. The analyses are kept only with `keep_results`
    (the web UI opens the results afterwards and may render them again)."""
    for k, item in enumerate(items):
        if stopped():
            item.status = "cancelled"
        elif item.output.exists() and not overwrite:
            item.status = "skipped"
        else:
            if on_start:
                on_start(k, item)
            t0 = time.monotonic()
            try:
                progress = (lambda phase, t_ms, k=k: on_progress(k, phase, t_ms)) if on_progress else None
                result = generate(item.video, opts, progress=progress)
                item.output.parent.mkdir(parents=True, exist_ok=True)
                result.funscript.save(item.output)
                item.status = "done"
                # without keep_results only what the summary needs: the analysis is the large part
                item.result = result if keep_results else PipelineResult(result.funscript, result.plans, result.part_device,
                                                                         flow_device=result.flow_device)
            except DeviceError:
                raise  # a step set to gpu without one: every video would fail the same way
            except Exception as e:  # noqa: BLE001 - one bad video must not stop the others
                item.status = "cancelled" if stopped() else "failed"
                item.error = "" if stopped() else (str(e) or type(e).__name__)
            item.seconds = time.monotonic() - t0
        if on_done:
            on_done(k, item)
    return items
