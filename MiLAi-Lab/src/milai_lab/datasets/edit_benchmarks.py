"""Public editing benchmarks: observed input and evaluation material stay separate."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ObservedSession:
    session_id: str
    date: str
    turns: tuple[dict[str, str], ...]


def halumem_users(path: Path, selected: list[str]) -> list[dict[str, Any]]:
    """Decode selected rows only; the public JSONL puts uuid in its first field."""
    wanted = set(selected)
    users = []
    decoder = json.JSONDecoder()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            head = re.match(r'\s*\{\s*"uuid"\s*:\s*', line)
            if head is None:
                raise ValueError("HaluMem rows must put uuid in the first JSON field")
            user_id, _ = decoder.raw_decode(line, head.end())
            if user_id not in wanted:
                continue
            user = json.loads(line)
            if user["uuid"] in wanted:
                users.append(user)
    missing = wanted - {user["uuid"] for user in users}
    if missing:
        raise ValueError(f"HaluMem users missing: {sorted(missing)}")
    return users


def halumem_session(user_id: str, ordinal: int, raw: dict[str, Any]) -> ObservedSession:
    """No persona, reference memories, update flags, questions or answers in Writer input."""
    return ObservedSession(
        f"halumem:{user_id}:session:{ordinal}",
        raw["start_time"],
        tuple(
            {"role": turn["role"], "content": turn["content"], "timestamp": turn["timestamp"]}
            for turn in raw["dialogue"]
        ),
    )


def halumem_time(value: str) -> datetime:
    return datetime.strptime(value, "%b %d, %Y, %H:%M:%S")


def longmemeval_cases(path: Path, selected: list[str]) -> list[dict[str, Any]]:
    wanted = set(selected)
    cases = [row for row in json.loads(path.read_text()) if row["question_id"] in wanted]
    missing = wanted - {row["question_id"] for row in cases}
    if missing:
        raise ValueError(f"LongMemEval questions missing: {sorted(missing)}")
    return cases


def longmemeval_history(raw: dict[str, Any]) -> tuple[ObservedSession, ...]:
    """Consume every original session in chronological order; never copy has_answer."""
    sessions = raw["haystack_sessions"]
    dates = raw["haystack_dates"]
    ids = raw["haystack_session_ids"]
    if not len(sessions) == len(dates) == len(ids):
        raise ValueError("LongMemEval session/date/id lengths differ")
    ordered = sorted(
        enumerate(zip(ids, dates, sessions, strict=True)), key=lambda item: (item[1][1], item[0])
    )
    return tuple(
        ObservedSession(
            str(sid),
            str(date),
            tuple(
                {"role": turn["role"], "content": turn["content"], "timestamp": str(date)}
                for turn in turns
            ),
        )
        for _, (sid, date, turns) in ordered
    )


def history_components(rows: list[dict[str, Any]]) -> list[list[str]]:
    """Identifier-only overlap: connected histories cannot be split into independent sources."""
    parents = list(range(len(rows)))

    def find(i: int) -> int:
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    seen: dict[str, int] = {}
    for i, row in enumerate(rows):
        for sid in row["haystack_session_ids"]:
            if sid in seen:
                parents[find(i)] = find(seen[sid])
            else:
                seen[sid] = i
    groups: dict[int, list[str]] = {}
    for i, row in enumerate(rows):
        groups.setdefault(find(i), []).append(row["question_id"])
    return list(groups.values())
