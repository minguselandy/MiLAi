from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RunArtifacts:
    """Compact, non-self-referential output layout for a single run."""

    root: Path

    _ALLOWED = frozenset(
        {"run.json", "cases.jsonl", "metrics.json", "terminal.json", "events.jsonl"}
    )

    def write_json(self, name: str, value: dict[str, Any]) -> Path:
        if name not in self._ALLOWED or name.endswith(".jsonl"):
            raise ValueError(f"unsupported JSON artifact: {name}")
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        return target

    def append_jsonl(self, name: str, value: dict[str, Any]) -> Path:
        if name not in self._ALLOWED or not name.endswith(".jsonl"):
            raise ValueError(f"unsupported JSONL artifact: {name}")
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / name
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        return target
