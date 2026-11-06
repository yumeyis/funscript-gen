"""Release check: scan the whole git history (every branch, all patches, commit messages and authors) for the real
names in deidentify.local.toml and for things that look like secrets. Names are printed masked (first two characters)
so the output can be pasted. Exit status 1 when anything is found. With arguments, only those refs (and their
history) are scanned, e.g. the branch and tag about to be pushed while a private branch stays local.

    uv run python scripts/check_history.py              # every branch and tag
    uv run python scripts/check_history.py main v1.0.0  # only what will be pushed
"""
import re
import subprocess
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRETS = re.compile(r"(sk-[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}"
                     r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
ALLOWED_EMAIL = re.compile(r"@users\.noreply\.github\.com$|^noreply@anthropic\.com$")


def mask(s: str) -> str:
    return s[:2] + "…" + f"({len(s)})"


def main() -> int:
    names = tomllib.loads((ROOT / "deidentify.local.toml").read_text(encoding="utf-8"))
    words = [*names.get("clips", {}).values(), *names.get("old_clips", {}).values(),
             *(s for s in names.get("series", {}).values() if len(s) >= 3)]
    plain = list(names.get("hosts", {}).values())
    names_re = re.compile("|".join([rf"(?<![A-Za-z0-9_]){re.escape(w)}(?![A-Za-z])" for w in words]
                                   + [re.escape(h) for h in plain]), re.IGNORECASE)
    log = subprocess.run(["git", "log", *(sys.argv[1:] or ["--all"]), "-p",
                          "--format=@@@%h %an <%ae> %cn <%ce>%n%B"], cwd=ROOT,
                         capture_output=True, check=True).stdout.decode("utf-8", "ignore")
    found: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    commit = ""
    for line in log.splitlines():
        if line.startswith("@@@"):
            commit = line[3:11]
            for m in EMAIL.findall(line):
                if not ALLOWED_EMAIL.search(m):
                    found["email"][commit] += 1
            continue
        for m in names_re.finditer(line):
            found[f"name {mask(m.group(0))}"][commit] += 1
        for m in SECRETS.finditer(line):
            found[f"secret {mask(m.group(0))}"][commit] += 1
    for kind, commits in sorted(found.items()):
        print(f"{kind}: {len(commits)} commits, e.g. {', '.join(list(commits)[:3])}")
    print("history is clean" if not found else f"{len(found)} kinds of hits: rewrite the history before publishing")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
