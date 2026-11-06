"""Reading and writing .funscript files."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Action:
    at: int  # milliseconds
    pos: int  # 0..100


@dataclass
class Funscript:
    actions: list[Action] = field(default_factory=list)
    inverted: bool = False
    range: int = 100
    metadata: dict = field(default_factory=dict)

    def normalized(self) -> Funscript:
        """Sorted by time, one action per timestamp (last wins), positions clamped to 0..100."""
        by_time: dict[int, int] = {}
        for a in self.actions:
            by_time[int(round(a.at))] = int(round(min(100, max(0, a.pos))))
        actions = [Action(at, pos) for at, pos in sorted(by_time.items()) if at >= 0]
        return Funscript(actions, self.inverted, self.range, dict(self.metadata))

    def to_dict(self) -> dict:
        fs = self.normalized()
        return {
            "version": "1.0",
            "inverted": fs.inverted,
            "range": fs.range,
            "metadata": fs.metadata,
            "actions": [{"at": a.at, "pos": a.pos} for a in fs.actions],
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Funscript:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))  # other tools may add a BOM
        actions = [Action(int(a["at"]), int(a["pos"])) for a in data.get("actions", [])]
        return cls(
            actions=actions,
            inverted=bool(data.get("inverted", False)),
            range=int(data.get("range", 100)),
            metadata=data.get("metadata") or {},
        ).normalized()
