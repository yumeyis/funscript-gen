import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NAMES = ROOT / "deidentify.local.toml"


def _committable() -> list[Path]:
    """Tracked files plus new ones that are not ignored: what the next commit can contain."""
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True,
                         check=True).stdout
    return [ROOT / f for f in out.decode().split("\0") if f and (ROOT / f).is_file()]


@pytest.mark.skipif(not NAMES.exists() or shutil.which("git") is None or not (ROOT / ".git").exists(),
                    reason="needs the private names file and a git checkout")
def test_committed_files_use_aliases_only():
    names = tomllib.loads(NAMES.read_text(encoding="utf-8"))
    words = [*names.get("clips", {}).values(), *names.get("old_clips", {}).values(),
             *(s for s in names.get("series", {}).values() if len(s) >= 3)]  # shorter ones are common syllables
    plain = list(names.get("hosts", {}).values())
    pattern = re.compile("|".join([rf"(?<![A-Za-z0-9_]){re.escape(w)}(?![A-Za-z])" for w in words]
                                  + [re.escape(h) for h in plain]), re.IGNORECASE)
    leaks = []
    for path in _committable():
        text = path.read_bytes().decode("utf-8", "ignore")
        leaks += [f"{path.relative_to(ROOT)}:{text.count(chr(10), 0, m.start()) + 1}: {m.group(0)}"
                  for m in pattern.finditer(text)]
        if path.name == NAMES.name:
            leaks.append(f"{path.relative_to(ROOT)} is not ignored")
    assert not leaks, "real names in committable files:\n" + "\n".join(leaks[:50])
