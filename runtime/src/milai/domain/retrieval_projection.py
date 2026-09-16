from __future__ import annotations

import re
from dataclasses import dataclass

_ROLE_LINE = re.compile(r"^(user|assistant|system|tool)\s*:\s*(.*)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ProjectionFragment:
    ordinal: int
    kind: str
    turn_start: int
    turn_end: int
    roles: tuple[str, ...]
    content_text: str


def _parse_messages(value: str) -> list[tuple[str, str]]:
    messages: list[tuple[str, str]] = []
    role = "memory"
    parts: list[str] = []

    def flush() -> None:
        if parts:
            messages.append((role, " ".join(parts).strip()))
            parts.clear()

    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _ROLE_LINE.match(line)
        if match is not None:
            flush()
            role = match.group(1).casefold()
            if match.group(2).strip():
                parts.append(match.group(2).strip())
        else:
            parts.append(line)
    flush()
    return messages or [("memory", value.strip())]


def _chunks(value: str, *, size: int = 140, overlap: int = 24) -> list[str]:
    words = value.split()
    if len(words) <= size:
        return [value.strip()] if value.strip() else []
    result: list[str] = []
    for start in range(0, len(words), size - overlap):
        result.append(" ".join(words[start : start + size]))
        if start + size >= len(words):
            break
    return result


def derive_projection_fragments(memory_text: str) -> tuple[ProjectionFragment, ...]:
    """Derive bounded turn chunks and adjacent windows without changing canonical state."""
    messages = _parse_messages(memory_text)
    fragments: list[ProjectionFragment] = []
    for turn_index, (role, content) in enumerate(messages):
        for chunk in _chunks(content):
            fragments.append(
                ProjectionFragment(
                    ordinal=len(fragments),
                    kind="turn",
                    turn_start=turn_index,
                    turn_end=turn_index,
                    roles=(role,),
                    content_text=f"{role}: {chunk}",
                )
            )
    for turn_index in range(len(messages) - 1):
        left_role, left_content = messages[turn_index]
        right_role, right_content = messages[turn_index + 1]
        left = " ".join(left_content.split()[-72:])
        right = " ".join(right_content.split()[:96])
        fragments.append(
            ProjectionFragment(
                ordinal=len(fragments),
                kind="window",
                turn_start=turn_index,
                turn_end=turn_index + 1,
                roles=(left_role, right_role),
                content_text=f"{left_role}: {left}\n{right_role}: {right}",
            )
        )
    return tuple(fragments)
