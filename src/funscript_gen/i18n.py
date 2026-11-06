"""Language packs: every text the user sees comes from a pack, a TOML file named after its language code
(`zh-TW.toml`, `en.toml`) with `[meta]` (name, code) and a flat `[texts]` table of `"key" = "text"`.

Packs are read from funscript_gen/lang/ (zh-TW is the source of every key, en ships with the program) and from an
external `lang/` folder, so a translation can be added without touching the program: $FUNSCRIPT_GEN_LANG_DIR (the
Windows build points it at the lang\\ folder beside the exe), then ./lang. An external pack replaces a built-in one
with the same code. `_template.toml` is the empty pack to copy for a new language (`funscript-gen lang template`
rewrites it from zh-TW and en).

t("key", n=3) looks the key up in the chosen pack, then in zh-TW, then gives the key itself; "{n}" in the text is
replaced by a parameter. A text without parameters is used as it is. The language is a setting of the whole program
(like the AI settings): set_language() changes it for every later t().
"""

from __future__ import annotations

import locale
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SOURCE_LANG = "zh-TW"  # holds every key; what a missing text falls back to
DEFAULT_LANG = "en"  # when the system's language has no pack
ENV_LANG = "FUNSCRIPT_GEN_LANG"
ENV_DIR = "FUNSCRIPT_GEN_LANG_DIR"
BUILTIN_DIR = Path(__file__).parent / "lang"
TEMPLATE_NAME = "_template.toml"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True)
class Pack:
    code: str
    name: str  # the language's own name, shown in the language list
    path: Path
    texts: dict[str, str]
    builtin: bool = False


_cache: dict[tuple, dict[str, Pack]] = {}
_current: str = SOURCE_LANG
_preferred: str | None = None  # --lang
_errors: list[str] = []


def external_dirs() -> list[Path]:
    dirs = []
    env = os.environ.get(ENV_DIR, "").strip()
    if env:
        dirs.append(Path(env).expanduser())
    dirs.append(Path("lang"))
    return dirs


def load_pack(path: Path, builtin: bool = False) -> Pack:
    """The pack in `path`; ValueError when it is not a valid pack."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"{path.name}: {e}") from e
    meta = data.get("meta")
    code = str(meta.get("code") or path.stem) if isinstance(meta, dict) else path.stem
    name = str(meta.get("name") or code) if isinstance(meta, dict) else code
    table = data.get("texts")
    texts = {k: v for k, v in table.items() if isinstance(v, str) and v.strip()} if isinstance(table, dict) else {}
    return Pack(code, name, path, texts, builtin)


def _files(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.glob("*.toml") if not p.name.startswith("_") and p.is_file())
    except OSError:
        return []


def available(rescan: bool = False) -> dict[str, Pack]:
    """Code -> pack, for every pack found. Cached by the folders' contents; `rescan` reads them again."""
    folders = [(BUILTIN_DIR, True)] + [(d, False) for d in external_dirs()]
    stamp = tuple((str(f), p.name, p.stat().st_mtime_ns) for f, _ in folders for p in _files(f))
    if not rescan and stamp in _cache:
        return _cache[stamp]
    packs: dict[str, Pack] = {}
    _errors.clear()
    for folder, builtin in folders:
        for path in _files(folder):
            try:
                pack = load_pack(path, builtin)
            except ValueError as e:
                _errors.append(str(e))
                continue
            packs[pack.code] = pack
    _cache.clear()
    _cache[stamp] = packs
    return packs


def errors() -> list[str]:
    """Packs that could not be read in the last scan."""
    return list(_errors)


def choices() -> list[tuple[str, str]]:
    """(language name, code) for the language list, the source language first."""
    packs = available()
    return [(p.name, c) for c, p in sorted(packs.items(), key=lambda kv: (kv[0] != SOURCE_LANG, kv[0]))]


def match(tag: str, codes) -> str | None:
    """The pack code that best fits a locale tag such as "zh_TW.UTF-8" or "en-GB": the same tag, else the same language."""
    tag = re.split(r"[.@:]", tag or "")[0].replace("_", "-").strip().lower()
    if not tag or tag in ("c", "posix"):
        return None
    by_lower = {c.lower(): c for c in codes}
    if tag in by_lower:
        return by_lower[tag]
    primary = tag.split("-")[0]
    if primary in by_lower:
        return by_lower[primary]
    same = sorted(c for low, c in by_lower.items() if low.split("-")[0] == primary)
    return same[0] if same else None


def system_tag() -> str:
    if sys.platform == "win32":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, len(buf)):
                return buf.value
        except (AttributeError, OSError):
            pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        value = os.environ.get(var, "").split(":")[0]
        if value:
            return value
    try:
        return locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        return ""


def resolve(preferred: str | None = None, saved: str | None = None) -> str:
    """The language to use: `preferred` (--lang), $FUNSCRIPT_GEN_LANG, `saved` (chosen in the web UI), the system's
    language, English. A name that matches no pack is skipped."""
    codes = available()
    for tag in (preferred or _preferred, os.environ.get(ENV_LANG), saved, system_tag()):
        found = match(tag or "", codes)
        if found:
            return found
    return DEFAULT_LANG if DEFAULT_LANG in codes else SOURCE_LANG


def set_language(code: str | None) -> str:
    """Use the pack `code` (a tag is matched to a pack; None or an unknown one means the source language)."""
    global _current
    _current = match(code or "", available()) or SOURCE_LANG
    return _current


def set_preferred(code: str | None) -> None:
    """The language asked for on the command line (--lang): it comes before everything else in resolve()."""
    global _preferred
    _preferred = code or None


def init(preferred: str | None = None, saved: str | None = None) -> str:
    return set_language(resolve(preferred, saved))


def current() -> str:
    return _current


def _lookup(key: str, code: str) -> str | None:
    pack = available().get(code)
    return pack.texts.get(key) if pack else None


def has(key: str) -> bool:
    return _lookup(key, SOURCE_LANG) is not None


def fill(text: str, params: dict) -> str:
    """Replace "{name}" with params[name]; a name that is not given stays as it is."""
    if not params:
        return text
    def value(m):
        name = m.group(1)
        if name not in params:
            return m.group(0)
        v = params[name]
        return str(v() if isinstance(v, Late) else v)

    return _PLACEHOLDER.sub(value, text)


def t(key: str, /, **params) -> str:
    text = _lookup(key, _current) or _lookup(key, SOURCE_LANG)
    return fill(text if text is not None else key, params)


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


class Late:
    """A text that is looked up when it is used, not when it is made: widgets built once (the web UI's labels) ask it
    again after the language changes."""

    def __init__(self, fn: Callable[[], object]) -> None:
        self.fn = fn

    def __call__(self):
        return self.fn()


def L(key: str, /, **params) -> Late:
    return Late(lambda: t(key, **params))


# --- the pack files ---------------------------------------------------------------------------------------------

def toml_string(text: str) -> str:
    out = ['"']
    for ch in text:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _section(key: str) -> str:
    return key.split(".")[0]


def write_pack(path: Path, code: str, name: str, texts: dict[str, str], header: str = "",
               reference: dict[str, dict[str, str]] | None = None) -> None:
    """A pack file: [meta], then the keys in `texts` order with a blank line and a comment where the section (the
    key's first part) changes. `reference` (language code -> texts) adds each key's text in those languages as
    comments, for a template."""
    lines = [f"# {line}".rstrip() for line in header.splitlines()]
    lines += ["", "[meta]", f"code = {toml_string(code)}", f"name = {toml_string(name)}"] if lines else \
        ["[meta]", f"code = {toml_string(code)}", f"name = {toml_string(name)}"]
    lines.append("")
    lines.append("[texts]")
    last = None
    for key, text in texts.items():
        if _section(key) != last:
            last = _section(key)
            lines += ["", f"# --- {last} ---"]
        for lang, ref in (reference or {}).items():
            if key in ref:
                lines.append("# " + lang + ": " + ref[key].replace("\n", "\\n"))
        lines.append(f"{toml_string(key)} = {toml_string(text)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass
class Report:
    missing: list[str]  # keys of the source language this pack does not translate
    unknown: list[str]  # keys the source language does not have
    placeholders: list[str]  # keys whose {names} differ from the source's

    @property
    def ok(self) -> bool:
        return not (self.unknown or self.placeholders)


def check(pack: Pack) -> Report:
    source = available()[SOURCE_LANG].texts
    return Report(
        missing=[k for k in source if k not in pack.texts],
        unknown=[k for k in pack.texts if k not in source],
        placeholders=[k for k, v in pack.texts.items() if k in source and placeholders(v) != placeholders(source[k])],
    )


def tt(key: str, default: str, /, **params) -> str:
    """t(), but `default` instead of the key when no pack has the text."""
    text = _lookup(key, _current) or _lookup(key, SOURCE_LANG)
    return fill(text if text is not None else default, params)


def column_headers(ids, prefix: str) -> list[str]:
    """Table headers: the ids (English, stable: code finds a column by its id) shown as the packs' "<prefix>.<slug>"."""
    return [tt(f"{prefix}.{re.sub(r'[^0-9a-zA-Z]+', '_', c).strip('_') or 'num'}", c) for c in ids]


def prefixed(prefix: str) -> dict[str, str]:
    """Every text whose key starts with `prefix`, in the chosen language (the source language's where it has none)."""
    out = {}
    for code in (SOURCE_LANG, _current):
        pack = available().get(code)
        if pack:
            out |= {k: v for k, v in pack.texts.items() if k.startswith(prefix)}
    return out


TEMPLATE_HEADER = """funscript-gen language pack template (語言包範本)

To add a language:
 1. Copy this file to lang/<code>.toml in the program's folder (e.g. lang/ja.toml, lang/zh-CN.toml).
 2. Fill in `code` (the same as the file name) and `name` (the language's own name, shown in the language list).
 3. Write each text after its key. The comment lines above a key show the zh-TW and en texts. A key left empty uses
    the zh-TW text.
 4. Keep {placeholders} as they are (they may move within the sentence). Keep Markdown (**bold**, `code`), HTML
    (<p>, <b>) and <k>key</k> (a key cap) markers, and "\\n" (a line break).
 5. Check the file: funscript-gen lang check lang/<code>.toml
 6. Pick the language in the web UI's Settings tab, or run with --lang <code>.

加入新語言：複製本檔為 lang/<code>.toml，填寫 code 與 name，翻譯每個 key 的內容（註解是 zh-TW 與 en 的對照；
留空的 key 會使用 zh-TW 的文字），{名稱} 與標記要保留，最後用 `funscript-gen lang check` 檢查。"""


def write_template(path: Path) -> int:
    """Write the empty pack to copy for a new language, from the source language's keys; their number."""
    packs = available()
    source = packs[SOURCE_LANG].texts
    reference = {c: packs[c].texts for c in (SOURCE_LANG, "en") if c in packs}
    write_pack(path, "", "", {k: "" for k in source}, header=TEMPLATE_HEADER, reference=reference)
    return len(source)
