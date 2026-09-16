from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

FailureClass = Literal[
    "INFRASTRUCTURE",
    "PROTOCOL_IMPLEMENTATION",
    "SEMANTIC_INSUFFICIENCY",
]


@dataclass(frozen=True, slots=True)
class ContextCaseMetadata:
    question_id: str
    question_type: str
    gold_session_count: int
    gold_session_bin: Literal["1", "2", "3+"]
    history_session_count: int
    history_event_count: int

    @property
    def stratum(self) -> tuple[str, str]:
        return self.question_type, self.gold_session_bin

    def to_dict(self) -> dict[str, object]:
        return {
            "question_id": self.question_id,
            "question_type": self.question_type,
            "gold_session_count": self.gold_session_count,
            "gold_session_bin": self.gold_session_bin,
            "history_session_count": self.history_session_count,
            "history_event_count": self.history_event_count,
        }


def structural_metadata(record: Mapping[str, Any]) -> ContextCaseMetadata:
    """Project only fields authorized for outcome-blind preflight selection."""

    question_id = record.get("question_id")
    question_type = record.get("question_type")
    gold_sessions = record.get("answer_session_ids")
    history = record.get("haystack_sessions")
    if (
        not isinstance(question_id, str)
        or not question_id
        or not isinstance(question_type, str)
        or not question_type
        or not isinstance(gold_sessions, list)
        or not gold_sessions
        or not isinstance(history, list)
        or not history
        or any(not isinstance(session, list) for session in history)
    ):
        raise ValueError("LongMemEval structural metadata is invalid")
    gold_count = len(gold_sessions)
    gold_bin: Literal["1", "2", "3+"] = (
        "1" if gold_count == 1 else "2" if gold_count == 2 else "3+"
    )
    return ContextCaseMetadata(
        question_id=question_id,
        question_type=question_type,
        gold_session_count=gold_count,
        gold_session_bin=gold_bin,
        history_session_count=len(history),
        history_event_count=sum(len(session) for session in history),
    )


def select_outcome_blind_context_cases(
    records: Sequence[Mapping[str, Any]],
    *,
    case_count: int = 24,
) -> tuple[ContextCaseMetadata, ...]:
    """Select a deterministic short/long pair per structural stratum.

    Selection never reads question text, answer text, lexical gold material, or
    a Product outcome. Every observed question-type/gold-session-count stratum
    receives a short and a long context. Remaining slots go to the largest
    strata and select their median context.
    """

    metadata = [structural_metadata(record) for record in records]
    if len({item.question_id for item in metadata}) != len(metadata):
        raise ValueError("LongMemEval question identities must be unique")
    grouped: defaultdict[tuple[str, str], list[ContextCaseMetadata]] = defaultdict(list)
    for item in metadata:
        grouped[item.stratum].append(item)
    if not grouped or case_count < 2 * len(grouped):
        raise ValueError("case_count cannot cover both length tails of every stratum")
    if case_count > len(metadata):
        raise ValueError("case_count exceeds the population")

    ordered_groups: dict[tuple[str, str], list[ContextCaseMetadata]] = {}
    for key, values in grouped.items():
        ordered_groups[key] = sorted(
            values,
            key=lambda item: (
                item.history_event_count,
                _stable_id_digest(item.question_id),
            ),
        )
    selected: list[ContextCaseMetadata] = []
    selected_ids: set[str] = set()

    def admit(item: ContextCaseMetadata) -> None:
        if item.question_id not in selected_ids:
            selected.append(item)
            selected_ids.add(item.question_id)

    for key in sorted(ordered_groups):
        values = ordered_groups[key]
        if len(values) < 2:
            raise ValueError(f"stratum {key!r} cannot cover both context-length tails")
        admit(values[0])
        admit(values[-1])

    remaining = case_count - len(selected)
    expansion_order = sorted(
        ordered_groups,
        key=lambda key: (-len(ordered_groups[key]), key),
    )
    for key in expansion_order:
        if remaining == 0:
            break
        values = ordered_groups[key]
        admit(values[(len(values) - 1) // 2])
        remaining = case_count - len(selected)
    if remaining:
        population = sorted(
            metadata,
            key=lambda item: (
                _stable_id_digest(item.question_id),
                item.question_id,
            ),
        )
        for item in population:
            if remaining == 0:
                break
            admit(item)
            remaining = case_count - len(selected)
    if len(selected) != case_count:
        raise ValueError("outcome-blind selector did not produce the requested denominator")
    return tuple(sorted(selected, key=lambda item: (item.stratum, item.history_event_count)))


def selection_digest(items: Sequence[ContextCaseMetadata]) -> str:
    payload = [item.to_dict() for item in items]
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def classify_terminal_failure(error: BaseException) -> FailureClass:
    """Keep transport/implementation failures distinct from semantic terminals."""

    if isinstance(error, (ConnectionError, OSError, TimeoutError, MemoryError)):
        return "INFRASTRUCTURE"
    return "PROTOCOL_IMPLEMENTATION"


def semantic_terminal(status: object) -> bool:
    return status in {"ABSENT", "ABSTAINED", "AMBIGUOUS", "INSUFFICIENT"}


def source_session_instance_keys(session_ids: Sequence[object]) -> tuple[str, ...]:
    """Preserve source IDs while disambiguating repeated session instances."""

    if any(not isinstance(value, str) or not value for value in session_ids):
        raise ValueError("LongMemEval source session identity is invalid")
    typed_ids = [str(value) for value in session_ids]
    totals = Counter(typed_ids)
    seen: Counter[str] = Counter()
    keys: list[str] = []
    for source_session_id in typed_ids:
        occurrence = seen[source_session_id]
        seen[source_session_id] += 1
        keys.append(
            source_session_id
            if totals[source_session_id] == 1
            else f"{source_session_id}\x1fduplicate-occurrence:{occurrence}"
        )
    return tuple(keys)


def material_turn_ordinals(session: object) -> tuple[int, ...]:
    """Return original ordinals for structurally valid, non-empty turns."""

    if not isinstance(session, list):
        raise ValueError("LongMemEval session material is invalid")
    ordinals: list[int] = []
    for ordinal, turn in enumerate(session):
        if not isinstance(turn, Mapping):
            raise ValueError("LongMemEval turn is invalid")
        role = turn.get("role")
        content = turn.get("content")
        if role not in {"user", "assistant", "system", "tool"} or not isinstance(
            content, str
        ):
            raise ValueError("LongMemEval turn material is invalid")
        if content:
            ordinals.append(ordinal)
    return tuple(ordinals)


def _stable_id_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


__all__ = [
    "ContextCaseMetadata",
    "FailureClass",
    "classify_terminal_failure",
    "material_turn_ordinals",
    "select_outcome_blind_context_cases",
    "selection_digest",
    "semantic_terminal",
    "source_session_instance_keys",
    "structural_metadata",
]
