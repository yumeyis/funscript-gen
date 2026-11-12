"""Command-line interface."""

from __future__ import annotations

import inspect
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from funscript_gen import i18n
from funscript_gen.export.funscript import Funscript
from funscript_gen.paths import settings_file, webui_output_dir
from funscript_gen.pipeline import PipelineResult, generate
from funscript_gen.video.decoder import probe

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.callback()
def main(lang: Annotated[Optional[str], typer.Option(
        "--lang", help="Language of the messages and the web UI (a pack in lang/, e.g. en or zh-TW); default: "
                       "$FUNSCRIPT_GEN_LANG, the language chosen in the web UI, the system's language")] = None) -> None:
    i18n.set_preferred(lang)
    i18n.init()


@app.command()
def info(video: Path) -> None:
    """Show basic video information."""
    i = probe(video)
    console.print(f"{i.path.name}: {i.width}x{i.height} @ {i.fps:.3f} fps, {i.duration_ms / 1000:.1f}s, ~{i.frame_count} frames")


def _shown_default(o) -> str:
    if o.name in ("ai_workers", "flow_workers", "device"):  # explained in the help
        return ""
    if o.kind == "bool":
        return "on" if o.default else "off"
    if o.default == "":
        return "the AI decides" if o.name in ("axis", "roi", "ref_a", "ref_b") else "none"
    return f"{o.default:g}" if isinstance(o.default, float) else str(o.default)


def _option_parameter(o) -> inspect.Parameter:
    """`generate`'s parameter for option `o`. It defaults to None, so an option counts as given only when typed, and
    a preset can fill in the rest."""
    shown = _shown_default(o)
    text = f"{o.help} (default: {shown})" if shown else o.help
    if o.kind == "bool":
        flag = (o.flag or o.name).replace("_", "-")
        kind, info = Optional[bool], typer.Option(f"--{flag}/--no-{flag}", help=text, show_default=False)
    else:
        kind = {"int": Optional[int], "float": Optional[float]}.get(o.kind, Optional[str])
        info = typer.Option(o.cli_name, help=text, show_default=False)
    return inspect.Parameter(o.name, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None, annotation=Annotated[kind, info])


@contextmanager
def _progress(opts, duration_ms: float, transient: bool = False):
    """A progress bar per step of generate(); yields the callback to pass it. `transient`: removed when done."""
    total = max(duration_ms, 1.0)
    with Progress(
        TextColumn("[bold]{task.description:<7}"), BarColumn(), TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(), TimeRemainingColumn(), console=console, transient=transient,
    ) as progress:
        tasks = {
            "scenes": progress.add_task("scenes", total=total),
            "ai": progress.add_task("ai", total=1, visible=opts.use_ai),
            "signal": progress.add_task("signal", total=total),
            "parts": progress.add_task("parts", total=1, visible=opts.part_sign),
        }

        def on_progress(phase: str, t_ms: float) -> None:
            if phase == "ai":
                progress.update(tasks["scenes"], completed=total)
            elif phase == "signal":
                progress.update(tasks["ai"], completed=1)
            elif phase == "parts":
                progress.update(tasks["signal"], completed=total)
            progress.update(tasks[phase], completed=t_ms)

        yield on_progress
        progress.update(tasks["signal"], completed=total)


def _generate(video: Path, output: Optional[Path] = None, preset: Optional[str] = None, debug: bool = False,
              save_analysis: Optional[Path] = None, **given) -> None:
    """Generate a funscript from the relative motion in VIDEO."""
    from funscript_gen.options import OptionError, build, resolve
    from funscript_gen.pipeline import save_analysis as save

    try:
        opts = build(resolve(given, preset))
    except OptionError as e:
        raise typer.BadParameter(e.en)
    _check_devices(opts)
    output = output or video.with_suffix(".funscript")

    with _progress(opts, probe(video).duration_ms) as on_progress:
        result = generate(video, opts, progress=on_progress)

    if save_analysis is not None:
        save(result.analysis, save_analysis)
        console.print(f"analysis: {save_analysis}")
    _report(result, opts, output, debug)


def _check_devices(opts) -> None:
    """Stop before any work when a step set to gpu (--compute, --*-compute) has no usable GPU."""
    from funscript_gen.devices import DeviceError, check

    try:
        check(opts)
    except DeviceError as e:
        console.print(f"[red]{e.en}[/]")
        raise typer.Exit(1)


def _report(result: PipelineResult, opts, output: Path, debug: bool) -> None:
    """Save the script and list what was done per scene (generate, render)."""
    result.funscript.save(output)
    console.print(f"wrote [bold]{output}[/] — {len(result.funscript.actions)} actions, {len(result.plans)} scenes")
    if result.ai_notice:
        console.print(f"[yellow]{result.ai_notice}[/]")
    if result.flow_device is not None:
        console.print(f"  optical flow ran on {result.flow_device}")
    if result.part_device is not None:
        console.print(f"  part check ran on {result.part_device.removesuffix('ExecutionProvider')}")
    from funscript_gen.report import possibly_inverted

    suspects = possibly_inverted(result)
    if suspects:
        nums = ",".join(map(str, suspects))
        which = f"scenes {nums.replace(',', ', ')}" if len(suspects) > 1 else f"scene {nums}"
        console.print(f"  [yellow]{which} may be upside down[/] (the reasons are in the notes below; check them, "
                      f"--flip-scenes {nums} flips them)")
    from funscript_gen.report import unsure_scenes

    unsure = unsure_scenes(result)
    if unsure:
        console.print(f"  [yellow]scenes {', '.join(map(str, unsure))} have no evidence for their direction[/] "
                      f"(about half of such scenes were upside down in validation: check them first)")
    missing = set(opts.flip_scenes) - {p.scene.index for p in result.plans}
    if missing:
        console.print(f"  [yellow]--flip-scenes: no scene {', '.join(map(str, sorted(missing)))}[/]")
    for p in result.plans:
        roi_s = "full" if p.roi is None else ",".join(f"{v:.2f}" for v in p.roi)
        extra = (f" [red]ai error: {p.error}[/]" if p.error else "") + (" [cyan]flipped[/]" if p.flipped else "") \
            + (f" {p.note}" if p.note else "")
        n = len(p.signal.actions) if p.signal else 0
        console.print(
            f"  scene {p.scene.index:>3} {p.scene.start_ms / 1000:7.1f}-{p.scene.end_ms / 1000:7.1f}s "
            f"{'rest' if p.rest else 'skip' if p.skip else p.mode:<4} axis={p.axis:<10} roi={roi_s} refs={p.ref_a}/{p.ref_b} actions={n}{extra}"
        )
    if debug:
        _write_debug(output, result)


def _generate_signature() -> inspect.Signature:
    from funscript_gen.options import CLI_OPTIONS, PRESETS

    fixed = [
        ("video", Annotated[Path, typer.Argument(help="The video")], inspect.Parameter.empty),
        ("output", Annotated[Optional[Path], typer.Option("-o", "--output", help="Default: <video>.funscript")], None),
        ("preset", Annotated[Optional[str], typer.Option(
            help=f"Start from a named set of settings ({', '.join(PRESETS)}); options given here override it")], None),
        ("debug", Annotated[bool, typer.Option(help="Also write <output>.debug.json and a signal plot")], False),
        ("save_analysis", Annotated[Optional[Path], typer.Option(
            help="Also save the analysis (scenes, AI answers, motion, part boxes) to this file: `render` makes "
                 "scripts from it with other output settings, without analysing the video again")], None),
    ]
    params = [inspect.Parameter(n, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=d, annotation=a) for n, a, d in fixed]
    return inspect.Signature(params + [_option_parameter(o) for o in CLI_OPTIONS])


def _render(analysis: Path, output: Path, preset: Optional[str] = None, debug: bool = False, **given) -> None:
    """Make a funscript from a saved analysis (generate --save-analysis) with other output settings."""
    from funscript_gen.options import OptionError, build, for_analysis
    from funscript_gen.pipeline import load_analysis, render

    try:
        saved = load_analysis(analysis)
        opts = build(for_analysis(saved.key, given, preset))
        result = render(saved, opts)
    except OptionError as e:
        raise typer.BadParameter(e.en)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    _report(result, opts, output, debug)


def _render_signature() -> inspect.Signature:
    from funscript_gen.options import CLI_OPTIONS, PRESETS

    fixed = [
        ("analysis", Annotated[Path, typer.Argument(help="An analysis saved by generate --save-analysis")],
         inspect.Parameter.empty),
        ("output", Annotated[Path, typer.Option("-o", "--output", help="Where to write the funscript")], inspect.Parameter.empty),
        ("preset", Annotated[Optional[str], typer.Option(
            help=f"Start from a named set of settings ({', '.join(PRESETS)}); options given here override it")], None),
        ("debug", Annotated[bool, typer.Option(help="Also write <output>.debug.json and a signal plot")], False),
    ]
    params = [inspect.Parameter(n, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=d, annotation=a) for n, a, d in fixed]
    # the analysis settings come from the analysis; giving a different one is an error
    return inspect.Signature(params + [_option_parameter(o) for o in CLI_OPTIONS])


for _fn, _name, _signature in ((_generate, "generate", _generate_signature), (_render, "render", _render_signature)):
    _fn.__signature__ = _signature()
    _fn.__annotations__ = {p.name: p.annotation for p in _fn.__signature__.parameters.values()}
    app.command(_name)(_fn)


def _batch(paths: list[Path], output_dir: Optional[Path] = None, recursive: bool = False, overwrite: bool = False,
           preset: Optional[str] = None, **given) -> None:
    """Generate funscripts for many videos (files or folders) one after another with the same settings."""
    from funscript_gen.batch import BatchItem, find_videos, output_paths, run_batch
    from funscript_gen.options import OptionError, build, resolve
    from rich.markup import escape

    from funscript_gen.report import possibly_inverted

    try:
        opts = build(resolve(given, preset))
    except OptionError as e:
        raise typer.BadParameter(e.en)
    _check_devices(opts)
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise typer.BadParameter(f"not found: {', '.join(map(str, missing))}")
    videos = find_videos(paths, recursive)
    if not videos:
        raise typer.BadParameter("no videos found" + ("" if recursive else " (--recursive also searches subfolders)"))
    items = [BatchItem(v, o) for v, o in zip(videos, output_paths(videos, output_dir))]
    console.print(f"{len(items)} videos")

    for k, item in enumerate(items):
        head = escape(f"[{k + 1}/{len(items)}] {item.video}")
        if item.output.exists() and not overwrite:
            item.status = "skipped"
            console.print(f"{head} [dim]skipped: {escape(str(item.output))} exists (--overwrite replaces it)[/]")
            continue
        console.print(head)
        try:
            duration = probe(item.video).duration_ms
        except Exception as e:  # noqa: BLE001 - not a readable video: the next one runs
            item.status, item.error = "failed", str(e) or type(e).__name__
            console.print(f"  [red]failed: cannot read the video: {escape(item.error)}[/]")
            continue
        try:
            with _progress(opts, duration, transient=True) as on_progress:
                run_batch([item], opts, overwrite=True, on_progress=lambda _k, phase, t: on_progress(phase, t))
        except KeyboardInterrupt:
            for rest in items[k:]:
                rest.status = "cancelled"
            console.print("  [yellow]cancelled[/]")
            break
        if item.status == "failed":
            console.print(f"  [red]failed: {escape(item.error)}[/]")
            continue
        result = item.result
        console.print(f"  wrote [bold]{escape(str(item.output))}[/] — {len(result.funscript.actions)} actions, "
                      f"{len(result.plans)} scenes, {item.seconds:.0f} s")
        suspects = possibly_inverted(result)
        if suspects:
            nums = ",".join(map(str, suspects))
            console.print(f"  [yellow]scenes {nums.replace(',', ', ')} may be upside down[/] (check them; "
                          f"generate with --flip-scenes {nums} flips them)")

    counts = {s: sum(i.status == s for i in items) for s in ("done", "skipped", "failed", "cancelled")}
    console.print("done: " + ", ".join(f"{n} {s}" for s, n in counts.items() if n))
    for item in items:
        if item.status == "failed":
            console.print(f"  [red]failed[/] {escape(f'{item.video}: {item.error}')}")
    if counts["failed"] or counts["cancelled"]:
        raise typer.Exit(1)


def _batch_signature() -> inspect.Signature:
    from funscript_gen.options import CLI_OPTIONS, PRESETS

    fixed = [
        ("paths", Annotated[list[Path], typer.Argument(
            help="Videos, or folders: every video in them (by file extension)")], inspect.Parameter.empty),
        ("output_dir", Annotated[Optional[Path], typer.Option(
            "-o", "--output-dir", help="Write the scripts here (default: beside each video, as <video>.funscript)")],
         None),
        ("recursive", Annotated[bool, typer.Option("-r", "--recursive", help="Also search the folders' subfolders")],
         False),
        ("overwrite", Annotated[bool, typer.Option(
            help="Replace scripts that already exist (default: skip those videos, so a stopped batch can go on)")],
         False),
        ("preset", Annotated[Optional[str], typer.Option(
            help=f"Start from a named set of settings ({', '.join(PRESETS)}); options given here override it")], None),
    ]
    params = [inspect.Parameter(n, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=d, annotation=a) for n, a, d in fixed]
    # scene numbers differ per video, so flipping them by number is left to generate / render
    return inspect.Signature(params + [_option_parameter(o) for o in CLI_OPTIONS if o.name != "flip_scenes"])


_batch.__signature__ = _batch_signature()
_batch.__annotations__ = {p.name: p.annotation for p in _batch.__signature__.parameters.values()}
app.command("batch")(_batch)


def parse_generate_args(args: list[str]) -> tuple[dict, str | None]:
    """The options given in `generate` arguments (no video), and the preset: what validation configs are made of."""
    import typer.main

    command = typer.main.get_command(app).commands["generate"]
    params = dict(command.make_context("generate", ["-", *args]).params)
    for fixed in ("video", "output", "debug", "save_analysis"):
        params.pop(fixed, None)
    preset = params.pop("preset", None)
    return {k: v for k, v in params.items() if v is not None}, preset



@app.command("ai-check")
def ai_check(
    video: Path,
    at: Annotated[float, typer.Option(help="Start time in seconds")] = 0.0,
    span: Annotated[float, typer.Option(help="Seconds covered by the sampled frames")] = 2.0,
    frames: Annotated[int, typer.Option(help="Number of frames sent to the model")] = 4,
    focus: Annotated[str, typer.Option(help="general | genital (the hybrid focus's genital analysis)")] = "general",
    no_cache: Annotated[bool, typer.Option("--no-cache")] = False,
    out: Annotated[Optional[Path], typer.Option(help="Annotated first frame (default out/ai-check.jpg)")] = None,
) -> None:
    """Send a few frames to the configured vLLM model and show its scene analysis."""
    import cv2

    from funscript_gen.ai.base import InvalidResponse, LabeledImage, ProviderError
    from funscript_gen.ai.prompts import (
        FOCUS_PROMPT, SCENE_PROMPT, FocusAnalysis, SceneAnalysis, bbox_to_unit, default_bbox_format, point_to_unit,
    )
    from funscript_gen.config import Settings, make_provider
    from funscript_gen.video.decoder import iter_frames

    settings = Settings()
    provider = make_provider(settings, use_cache=not no_cache)
    fmt = settings.vllm_bbox_format or default_bbox_format(settings.vllm_model)

    sampled = list(iter_frames(video, target_fps=frames / span, start_ms=at * 1000, end_ms=(at + span) * 1000))[:frames]
    if not sampled:
        raise typer.BadParameter("no frames in that time range")
    images = [LabeledImage(f.image, f"Frame {i + 1} (t={f.t_ms / 1000:.2f}s):") for i, f in enumerate(sampled)]
    console.print(f"{settings.vllm_model} @ {settings.vllm_base_url} — {len(images)} frames, bbox format {fmt}")
    try:
        prompt, schema = (FOCUS_PROMPT, FocusAnalysis) if focus == "genital" else (SCENE_PROMPT, SceneAnalysis)
        result = provider.analyze(images, prompt, schema)
    except InvalidResponse as e:
        console.print(f"[red]invalid response:[/] {e}\n--- raw ---\n{e.raw[:2000]}")
        raise typer.Exit(1)
    except ProviderError as e:
        console.print(f"[red]provider error:[/] {e}")
        raise typer.Exit(1)

    console.print_json(result.model_dump_json())
    console.print(f"latency {provider.last_latency_s:.1f}s" if provider.last_latency_s else "(cached)")

    img = sampled[0].image.copy()
    h, w = img.shape[:2]
    subjects = getattr(result, "subjects", [])
    boxes = [(s.bbox, (0, 0, 255), f"{'AB'[i]}: {s.description}") for i, s in enumerate(subjects)]
    if result.focus_roi:
        boxes.append((result.focus_roi, (0, 200, 255), "focus"))
    for bbox, color, label in boxes:
        x1, y1, x2, y2 = bbox_to_unit(bbox, fmt, w, h)  # type: ignore[arg-type]
        p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
        cv2.rectangle(img, p1, p2, color, 2)
        cv2.putText(img, label[:40], (p1[0] + 4, p1[1] + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    base, tip = getattr(result, "shaft_base", None), getattr(result, "shaft_tip", None)
    if base is not None and tip is not None:
        p1, p2 = (point_to_unit(pt, fmt, w, h) for pt in (base, tip))  # type: ignore[arg-type]
        cv2.arrowedLine(img, (int(p1[0] * w), int(p1[1] * h)), (int(p2[0] * w), int(p2[1] * h)), (0, 255, 0), 2)
    out = out or Path("out/ai-check.jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img)
    console.print(f"annotated frame: {out}")


lang_app = typer.Typer(no_args_is_help=True, help="Language packs (the .toml files in lang/)")
app.add_typer(lang_app, name="lang")


@lang_app.command("list")
def lang_list() -> None:
    """List the language packs found, with the one in use."""
    for name, code in i18n.choices():
        pack = i18n.available()[code]
        mark = "*" if code == i18n.current() else " "
        console.print(f"{mark} {code:<10} {name}  ({'built in' if pack.builtin else 'external'}: {pack.path})", soft_wrap=True)
    for error in i18n.errors():
        console.print(f"[red]{error}[/]")


@lang_app.command("template")
def lang_template(
    output: Annotated[Path, typer.Argument(help="Where to write it")] = i18n.BUILTIN_DIR / i18n.TEMPLATE_NAME,
) -> None:
    """Write the empty pack to copy for a new language (all keys, with the zh-TW and en texts as comments)."""
    n = i18n.write_template(output)
    console.print(f"wrote [bold]{output}[/] — {n} texts")


@lang_app.command("check")
def lang_check(file: Annotated[Path, typer.Argument(help="A pack, e.g. lang/ja.toml")]) -> None:
    """Compare a pack with zh-TW: texts it lacks (zh-TW's are used), keys zh-TW does not have, and {placeholders} that differ."""
    try:
        pack = i18n.load_pack(file)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    source = i18n.available()[i18n.SOURCE_LANG]
    report = i18n.check(pack)
    for title, keys, show_source in (("missing (zh-TW is used)", report.missing, False),
                                     ("unknown keys", report.unknown, False),
                                     ("different {placeholders}", report.placeholders, True)):
        if keys:
            console.print(f"[bold]{title}[/] ({len(keys)})")
            for key in keys:
                console.print(f"  {key}" + (f"  zh-TW: {source.texts[key]}" if show_source else ""), soft_wrap=True)
    done = len(source.texts) - len(report.missing)
    console.print(f"{pack.code} ({pack.name}): {done}/{len(source.texts)} texts")
    if not report.ok:
        raise typer.Exit(1)


@app.command()
def webui(
    host: Annotated[str, typer.Option(help="0.0.0.0 to allow other machines on the LAN")] = "127.0.0.1",
    port: int = 7860,
    output_dir: Annotated[Optional[Path], typer.Option(
        help="Where generated scripts are saved (default out/webui, or out in FUNSCRIPT_GEN_HOME)",
        envvar="FUNSCRIPT_GEN_OUTPUT_DIR",
    )] = None,
    cleanup_file: Annotated[Path, typer.Option(help="Where the output settings are stored")] = settings_file(".webui-cleanup.json"),
    last_file: Annotated[Path, typer.Option(help="Where the last-used Generate settings are stored")] = settings_file(".webui-last.json"),
) -> None:
    """Start the web interface."""
    from funscript_gen import webui as ui
    from funscript_gen.webui import launch

    if output_dir is not None:
        ui.OUTPUT_DIR = output_dir.expanduser().resolve()
    launch(host, port, cleanup_file, last_file)


@app.command("app")
def desktop_app(
    ui: Annotated[str, typer.Option(
        help="window: its own window (falls back to the browser) | browser | none (only the server)")] = "window",
    port: Annotated[Optional[int], typer.Option(help="Default: 7860, or any free port when it is taken")] = None,
) -> None:
    """Start the desktop app: the web UI on this computer only, taking videos by their path."""
    from funscript_gen.app import run

    if ui not in ("window", "browser", "none"):
        raise typer.BadParameter("--ui must be window, browser or none")
    run(ui, port)


@app.command()
def clean_webui(
    older_than_days: Annotated[Optional[int], typer.Option(
        help="Delete web UI job folders older than this; default = the retention set in the web UI")] = None,
    all_: Annotated[bool, typer.Option("--all", help="Delete every web UI job folder")] = False,
    output_dir: Annotated[Path, typer.Option(envvar="FUNSCRIPT_GEN_OUTPUT_DIR")] = webui_output_dir(),
    cleanup_file: Annotated[Path, typer.Option(help="Retention setting written by the web UI")] = settings_file(".webui-cleanup.json"),
    retention_days: Annotated[Optional[int], typer.Option(
        help="Save a new retention (days, 0 = keep forever) before cleaning, as the Settings tab does")] = None,
) -> None:
    """Delete generated web UI outputs (only the <time>/ job folders)."""
    from funscript_gen.outputs import OutputStore, human_size

    store = OutputStore(output_dir, cleanup_file)
    if retention_days is not None:
        if retention_days < 0:
            raise typer.BadParameter("retention-days must be >= 0")
        store.set_retention_days(retention_days)
    if all_:
        freed = store.purge(None)
    elif older_than_days is not None:
        if older_than_days < 0:
            raise typer.BadParameter("older-than-days must be >= 0")
        freed = store.purge(older_than_days)
    else:
        freed = store.purge_expired()
    u = store.usage()
    console.print(f"deleted {freed.runs} folders ({human_size(freed.bytes)}); "
                  f"{u.runs} left ({human_size(u.bytes)}), retention {store.retention_days or 'off'} days")


@app.command()
def compare(reference: Path, predicted: Path, tolerance_ms: float = 150.0) -> None:
    """Score PREDICTED against a hand-made REFERENCE funscript."""
    from funscript_gen.evaluate import compare as score

    from funscript_gen.evaluate import WIGGLE, drop_wiggles

    ref, pred = Funscript.load(reference), Funscript.load(predicted)
    s = score(ref, pred, tol_ms=tolerance_ms)
    console.print(
        f"simplified extrema P={s.precision:.2f} R={s.recall:.2f} F1={s.f1:.2f} | "
        f"correlation={s.correlation:.3f} at lag {s.best_lag_ms:+.0f} ms "
        f"(lag within ±100 ms; within ±500 ms as recorded before 2026-10-31: {s.correlation_wide:.3f})"
    )
    w = score(drop_wiggles(ref), pred, tol_ms=tolerance_ms, simplify=False)
    console.print(f"ignoring reference wiggles < {WIGGLE:.0f}: P={w.precision:.2f} R={w.recall:.2f} F1(strokes)={w.f1:.2f}")


@app.command()
def validate(
    name: Annotated[str, typer.Argument(help="Run name: the run is kept in out/runs/NAME")],
    config: Annotated[Optional[list[str]], typer.Option(
        "--config", "-c", help="Config from validation.toml; repeat for several (default: default)")] = None,
    clips: Annotated[str, typer.Option(
        help="Comma-separated groups (dev, test, holdout), clip names, or all (default: default_clips)")] = "",
    jobs: Annotated[int, typer.Option("--jobs", "-j", help="Clips generated at the same time")] = 3,
    flow_workers: Annotated[int, typer.Option(help="--flow-workers of each generate")] = 4,
    extra: Annotated[str, typer.Option(
        "--args", help='Extra generate options added to every config, e.g. "--flow-width 320"')] = "",
    baseline: Annotated[Optional[list[Path]], typer.Option(help="Compare with this run directory afterwards")] = None,
    resume: Annotated[bool, typer.Option(help="Add to an existing run, skipping the jobs it has done")] = False,
    save_analysis: Annotated[bool, typer.Option(
        help="Keep each job's analysis (CLIP.analysis.pkl, about 1 MB) for --replay")] = True,
    replay: Annotated[Optional[Path], typer.Option(
        help="Render the analyses saved by this run instead of generating: output settings in seconds")] = None,
    code: Annotated[Optional[Path], typer.Option(
        help="Run the funscript_gen package in this directory (e.g. a git worktree's src) instead of this one")] = None,
    manifest: Annotated[Path, typer.Option(help="Clips, groups and configs")] = Path("validation.toml"),
    runs_dir: Annotated[Path, typer.Option(help="Where runs are kept")] = Path("out/runs"),
) -> None:
    """Generate the validation clips with configs from validation.toml and score them against their scripts."""
    from funscript_gen.validate import comparison, load_manifest, load_runs, run_validation, summary

    configs = config or ["default"]
    try:
        run = run_validation(name, configs, clips, jobs, flow_workers, extra, resume, code, manifest, runs_dir,
                             say=console.print, save_analysis=save_analysis and replay is None, replay=replay)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    m = load_manifest(manifest)
    merged, _ = load_runs([run.path])
    typer.echo(summary(merged, m, configs))
    if baseline:
        base, _ = load_runs(baseline)
        typer.echo(comparison(merged, base, m, configs))
    console.print(f"run: {run.path}")


@app.command("compare-runs")
def compare_runs(
    runs: Annotated[list[Path], typer.Argument(help="Run directories; several are merged (later ones win)")],
    baseline: Annotated[Optional[list[Path]], typer.Option(help="Compare with this run directory")] = None,
    config: Annotated[Optional[list[str]], typer.Option("--config", "-c", help="Only this config")] = None,
    scenes: Annotated[Optional[str], typer.Option(help="Also list the scenes of this clip")] = None,
    manifest: Annotated[Path, typer.Option(help="Clips and groups")] = Path("validation.toml"),
) -> None:
    """Summarize validation runs, or compare them with a baseline run."""
    from funscript_gen.validate import comparison, load_manifest, load_runs, scene_table, summary

    try:
        merged, _ = load_runs(runs)
        base = load_runs(baseline)[0] if baseline else None
    except ValueError as e:
        raise typer.BadParameter(str(e))
    m = load_manifest(manifest) if manifest.exists() else None
    out = comparison(merged, base, m, config) if base is not None else summary(merged, m, config)
    typer.echo(out)
    if scenes:
        typer.echo(scene_table(merged, scenes, config))
        if base is not None:
            typer.echo("--- baseline")
            typer.echo(scene_table(base, scenes, config))


def _write_debug(output: Path, result: PipelineResult) -> None:
    from funscript_gen.report import debug_data, plot_result

    path = output.with_suffix(".debug.json")
    path.write_text(json.dumps(debug_data(result)), encoding="utf-8")
    console.print(f"debug data: {path}")
    fig = plot_result(result)
    png = output.with_suffix(".debug.png")
    fig.savefig(png, dpi=100)
    console.print(f"plot: {png}")




if __name__ == "__main__":
    app()
