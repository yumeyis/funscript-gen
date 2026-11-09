"""Multi-axis funscripts: finding the axes of a script, merging axis files into one file and splitting them again.

A script with several axes comes in two forms:
- one file per axis: `video.funscript` is the main axis (L0), the others are `video.<suffix>.funscript`
  (`video.surge.funscript` is L1, ... see AXIS_SUFFIX);
- one file with all of them: the main axis in `actions`, the others in `"axes": [{"id": "L1", "actions": [...]}]`.

merge() / split() work on the raw action lists, so what a script holds besides `at` and `pos` is kept. Nothing here
writes a text for the user: problems come back as (code, name) pairs for the caller to word.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from funscript_gen.export.funscript import Action, Funscript

MAIN_AXIS = "L0"
# The other axes by their id and the suffix of their file name (`video.surge.funscript`), in the order a merged file lists them.
AXIS_SUFFIX = {
    "L1": "surge", "L2": "sway",
    "R0": "twist", "R1": "roll", "R2": "pitch",
    "V0": "vib", "V1": "pump",
    "A0": "valve", "A1": "suck", "A2": "lube",
}
AXIS_IDS = (MAIN_AXIS, *AXIS_SUFFIX)
SUFFIX_AXIS = {suffix: axis for axis, suffix in AXIS_SUFFIX.items()}
SCRIPT_SUFFIXES = (".funscript", ".json")
MERGED_TAIL = "_merged"  # a merged file may be named `video_merged.funscript`: the name of its scripts is `video`


def split_name(path: str | Path) -> tuple[str, str | None]:
    """(name, axis id) of a script file: `a.roll.funscript` is ("a", "R1"), `a.funscript` ("a", None)."""
    stem = Path(path).stem
    name, dot, tail = stem.rpartition(".")
    if dot and name and tail.casefold() in SUFFIX_AXIS:
        return name, SUFFIX_AXIS[tail.casefold()]
    return stem, None


def is_script_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SCRIPT_SUFFIXES


def read_json(path: str | Path) -> dict:
    """A script file's JSON object (a BOM, as some tools write, is accepted)."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("not a funscript (the JSON is not an object)")
    return data


def merged_axes(data: dict) -> list[dict]:
    """The `axes` entries of a one-file multi-axis script (empty for any other)."""
    raw = data.get("axes")
    return [a for a in raw if isinstance(a, dict)] if isinstance(raw, list) else []


def is_merged(data: dict) -> bool:
    return bool(merged_axes(data))


def parse_actions(raw) -> list[Action]:
    """Raw `actions` as Actions; ValueError when an entry has no usable `at` and `pos`."""
    if not isinstance(raw, list):
        raise ValueError("actions is not a list")
    try:
        return [Action(int(round(float(a["at"]))), int(round(float(a["pos"])))) for a in raw]
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"bad action: {e!r}") from None


def funscript_of(header: dict, raw_actions: list) -> Funscript:
    """A Funscript (for viewing: sorted, clamped) from a script's header keys and raw actions."""
    return Funscript(parse_actions(raw_actions), bool(header.get("inverted", False)), int(header.get("range", 100)),
                     header.get("metadata") or {}).normalized()


@dataclass
class ScriptSet:
    """One multi-axis script: the header keys of its main file (all but `actions` and `axes`), the raw actions of
    the main axis and of every other axis."""
    name: str
    header: dict
    actions: list
    axes: dict[str, list] = field(default_factory=dict)  # axis id -> raw actions, in AXIS_IDS order
    folder: Path | None = None  # where the main file was, for "output beside the original"
    sources: list[Path] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)  # ids in a merged file that no axis has

    def ordered(self) -> list[tuple[str, list]]:
        return [(a, self.axes[a]) for a in AXIS_IDS[1:] if a in self.axes]

    def funscripts(self) -> tuple[Funscript, dict[str, Funscript]]:
        """The main axis and the others for the preview player."""
        return funscript_of(self.header, self.actions), {a: funscript_of(self.header, acts) for a, acts in self.ordered()}


def _header(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in ("actions", "axes")}


def _axis_entries(entries: list[dict]) -> tuple[dict[str, list], list[str]]:
    """The axes of a merged file by id (an id is accepted in any case; the first of a repeated id wins), and the ids
    that are none of the axes."""
    axes: dict[str, list] = {}
    unknown: list[str] = []
    for e in entries:
        axis = str(e.get("id", "")).strip().upper()
        if axis in AXIS_SUFFIX:
            parse_actions(e.get("actions", []))  # a broken axis is an error, not a silent gap
            axes.setdefault(axis, e.get("actions", []))
        elif axis != MAIN_AXIS:
            unknown.append(str(e.get("id", "")))
    return {a: axes[a] for a in AXIS_IDS[1:] if a in axes}, unknown


def load_merged(path: str | Path, data: dict | None = None) -> ScriptSet:
    """The script set in a one-file multi-axis script."""
    path = Path(path)
    data = read_json(path) if data is None else data
    parse_actions(data.get("actions", []))
    axes, unknown = _axis_entries(merged_axes(data))
    name = split_name(path)[0]
    if name.endswith(MERGED_TAIL) and len(name) > len(MERGED_TAIL):
        name = name[: -len(MERGED_TAIL)]
    return ScriptSet(name, _header(data), data.get("actions", []), axes, path.parent, [path], unknown)


def load_separate(main: str | Path, axis_files: list[str | Path]) -> ScriptSet:
    """The script set of a main file and its axis files (the axis of each is named by its file name, a file that
    names none is skipped; a second file for an axis is skipped too). A main file that is itself a one-file
    multi-axis script keeps its own axes, and the files are added to them."""
    main = Path(main)
    data = read_json(main)
    base = load_merged(main, data) if is_merged(data) else ScriptSet(
        split_name(main)[0], _header(data), data.get("actions", []), {}, main.parent, [main])
    parse_actions(base.actions)
    found = dict(base.axes)
    for path in map(Path, axis_files):
        axis = split_name(path)[1]
        if axis is None or (axis in found and axis not in base.axes):
            continue
        acts = read_json(path).get("actions", [])
        parse_actions(acts)
        found[axis] = acts
        base.sources.append(path)
    base.axes = {a: found[a] for a in AXIS_IDS[1:] if a in found}
    return base


def find_axis_files(path: str | Path) -> dict[str, Path]:
    """The axis files beside a script, by axis id: `video.funscript` (or `video.roll.funscript`) finds
    `video.<suffix>.funscript` (and `.json`) in its folder. Names are not case-sensitive, as on Windows; the
    exact-case one wins, .funscript before .json."""
    path = Path(path)
    name = split_name(path)[0]
    try:
        files = [f for f in path.parent.iterdir() if f.is_file() and is_script_file(f)]
    except OSError:
        return {}
    found: dict[str, Path] = {}
    for f in sorted(files, key=lambda f: (split_name(f)[0] != name, f.suffix.lower() != ".funscript", f.name.lower())):
        base, axis = split_name(f)
        if axis and base.casefold() == name.casefold() and axis not in found:
            found[axis] = f
    return {a: found[a] for a in AXIS_IDS[1:] if a in found}


def find_main_file(path: str | Path) -> Path | None:
    """The main file beside an axis file (`video.roll.funscript` -> `video.funscript`), None when there is none."""
    path = Path(path)
    name = split_name(path)[0]
    try:
        files = [f for f in path.parent.iterdir() if f.is_file() and is_script_file(f)]
    except OSError:
        return None
    mains = [f for f in files if split_name(f) == (f.stem, None) and f.stem.casefold() == name.casefold()]
    return min(mains, key=lambda f: (f.stem != name, f.suffix.lower() != ".funscript", f.name.lower()), default=None)


def expand(paths: list[Path]) -> list[Path]:
    """`paths` with the files of the same script that lie beside them: a main file brings its axis files, an axis
    file without its main file brings the main file and the other axes. A one-file multi-axis script (or a file that
    cannot be read) stays as it is. Order is kept, nothing is repeated."""
    out = list(paths)
    have = {p.resolve() for p in out}
    mains = {split_name(p)[0].casefold() for p in paths if split_name(p)[1] is None}
    for p in paths:
        try:
            if is_merged(read_json(p)):
                continue
        except (OSError, ValueError):
            continue
        name, axis = split_name(p)
        extra = list(find_axis_files(p).values())
        if axis is not None and name.casefold() not in mains:
            main = find_main_file(p)
            if main:
                extra.insert(0, main)
                mains.add(name.casefold())
        for q in extra:
            if q.resolve() not in have:
                have.add(q.resolve())
                out.append(q)
    return out


@dataclass
class Plan:
    """What a set of files is: kind "merge" (axis files of one or more scripts), "split" (one-file multi-axis
    scripts), "single" (plain one-axis scripts: nothing to do) or "none" (nothing usable). `problems` are
    (code, name) pairs: "unreadable" (name: file; the reason follows after a tab), "no_main" (axis files without
    their main file; name: the script), "ignored" (a file that is neither, name: file), "unknown_axis" (an axis id of
    a merged file that is none of the axes; name: the id)."""
    kind: str = "none"
    sets: list[ScriptSet] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)


def classify(paths: list[str | Path]) -> Plan:
    """Tell what the files are. One-file multi-axis scripts win (they are split); otherwise the files are grouped by
    script name, and a group with axis files is merged. Pure on the given files: expand() looks beside them."""
    plan = Plan()
    loaded: list[tuple[Path, dict]] = []
    for p in map(Path, paths):
        try:
            loaded.append((p, read_json(p)))
        except (OSError, ValueError) as e:  # json.JSONDecodeError is a ValueError
            plan.problems.append(("unreadable", f"{p.name}\t{e}"))
    merged = [(p, d) for p, d in loaded if is_merged(d)]
    if merged:
        plan.kind = "split"
        for p, d in merged:
            try:
                plan.sets.append(load_merged(p, d))
            except ValueError as e:
                plan.problems.append(("unreadable", f"{p.name}\t{e}"))
        plan.problems += [("unknown_axis", u) for s in plan.sets for u in s.unknown]
        plan.problems += [("ignored", p.name) for p, d in loaded if not is_merged(d)]
        if not plan.sets:
            plan.kind = "none"
        return plan
    groups: dict[str, dict] = {}
    for p, _ in loaded:
        name, axis = split_name(p)
        g = groups.setdefault(name.casefold(), {"name": name, "main": None, "axes": [], "extra": []})
        if axis is not None:
            g["axes"].append(p)
        elif g["main"] is None:
            g["main"] = p
            g["name"] = name
        else:
            g["extra"].append(p)
    lone: list[str] = []
    for g in groups.values():
        plan.problems += [("ignored", p.name) for p in g["extra"]]
        if not g["axes"]:
            if g["main"] is not None:
                lone.append(g["main"].name)
            continue
        if g["main"] is None:
            plan.problems.append(("no_main", g["name"]))
            continue
        try:
            plan.sets.append(load_separate(g["main"], g["axes"]))
        except ValueError as e:
            plan.problems.append(("unreadable", f"{g['main'].name}\t{e}"))
    if plan.sets:
        plan.kind = "merge"
        plan.problems += [("ignored", name) for name in lone]  # plain scripts among the files of others
    elif lone and not any(code == "no_main" for code, _ in plan.problems):
        plan.kind = "single"
    return plan


# --- output ------------------------------------------------------------------------------------------------------


def _line(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def dumps(value, indent: int = 0) -> str:
    """JSON with the keys indented and every `actions` array on one line (a script has thousands of actions)."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [f"{pad}  {json.dumps(k, ensure_ascii=False)}: " + (_line(v) if k == "actions" else dumps(v, indent + 1))
                 for k, v in value.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[\n" + ",\n".join(f"{pad}  " + dumps(v, indent + 1) for v in value) + f"\n{pad}]"
    return json.dumps(value, ensure_ascii=False)


def _file_data(header: dict, actions: list) -> dict:
    data = {"version": header.get("version", "1.1")}
    data.update({k: v for k, v in header.items() if k != "version"})
    data.setdefault("range", 100)
    data.setdefault("metadata", {})
    data["actions"] = actions
    return data


def merge(s: ScriptSet) -> dict:
    """The one-file multi-axis script of a set: its header, the main axis in `actions`, the others in `axes`."""
    data = _file_data(s.header, s.actions)
    data["axes"] = [{"id": a, "actions": acts} for a, acts in s.ordered()]
    return data


def split(s: ScriptSet) -> list[tuple[str, dict]]:
    """(file name, script) per axis of a set: `name.funscript` for the main axis, `name.<suffix>.funscript`."""
    files = [(f"{s.name}.funscript", _file_data(s.header, s.actions))]
    files += [(f"{s.name}.{AXIS_SUFFIX[a]}.funscript", _file_data(s.header, acts)) for a, acts in s.ordered()]
    return files


def outputs(plan: Plan) -> list[tuple[ScriptSet, str, dict]]:
    """(set, file name, script) for every file the plan writes: a merge writes `name.funscript` holding all the axes,
    a split the main axis in `name.funscript` and one file per other axis."""
    if plan.kind == "merge":
        return [(s, f"{s.name}.funscript", merge(s)) for s in plan.sets]
    if plan.kind == "split":
        return [(s, name, data) for s in plan.sets for name, data in split(s)]
    return []


@dataclass(frozen=True)
class Written:
    path: Path
    backup: Path | None = None  # where the file that was there went


def backup_path(path: Path) -> Path:
    """`path` + ".backup"; when that is taken, ".backup2", ".backup3"... so an earlier backup is never overwritten."""
    candidate, n = path.with_name(path.name + ".backup"), 2
    while candidate.exists():
        candidate, n = path.with_name(f"{path.name}.backup{n}"), n + 1
    return candidate


def write_script(path: Path, data: dict, keep_backup: bool) -> Written:
    """Write a script. A file already there is renamed to its backup first (keep_backup) or replaced; the new file
    is written beside it and moved into place, so a failure leaves the old one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(dumps(data), encoding="utf-8")
        backup = None
        if keep_backup and path.exists():
            backup = backup_path(path)
            os.replace(path, backup)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return Written(path, backup)


def write_plan(plan: Plan, folder: Path | None, keep_backup: bool) -> list[Written]:
    """Write the plan's files into `folder`, or beside the main file of each script when it is None. Everything is
    built before the first file is written."""
    todo = [((folder or s.folder or Path.cwd()) / name, data) for s, name, data in outputs(plan)]
    seen: set[Path] = set()
    for path, _ in todo:
        key = Path(os.path.normcase(path.resolve()))
        if key in seen:
            raise ValueError(f"two files would be written to {path}")
        seen.add(key)
    return [write_script(path, data, keep_backup) for path, data in todo]
