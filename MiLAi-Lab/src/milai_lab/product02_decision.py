from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from milai_lab.context_preflight import material_turn_ordinals
from milai_lab.longmemeval_gate import AnswerBearingSpanLabel


@dataclass(frozen=True, slots=True)
class NativeAnswerEvidence:
    """LongMemEval-native answer turns joined to immutable Runtime source refs."""

    labels: tuple[AnswerBearingSpanLabel, ...]
    source_text_by_turn_ref: Mapping[str, str]
    required_role_groups: tuple[tuple[str, ...], ...]

    @property
    def exact_span_count(self) -> int:
        return sum(label.text is not None for label in self.labels)


@dataclass(frozen=True, slots=True)
class SealedAnswerEvidence:
    """Externally sealed answer/operand labels joined to Runtime source refs."""

    answer_labels: tuple[AnswerBearingSpanLabel, ...]
    source_text_by_turn_ref: Mapping[str, str]
    required_role_groups: tuple[tuple[str, ...], ...]
    required_role_labels: tuple[str, ...]
    native_has_answer_source_turn_refs: tuple[str, ...]
    negative_without_answer_turn: bool

    @property
    def exact_span_count(self) -> int:
        return sum(label.text is not None for label in self.answer_labels)


def _answer_strings(record: Mapping[str, Any]) -> tuple[str, ...]:
    raw = record.get("answer")
    if isinstance(raw, str) and raw:
        return (raw,)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return (str(raw),)
    if isinstance(raw, list) and raw and all(
        isinstance(value, str) and value for value in raw
    ):
        return tuple(raw)
    raise ValueError("LongMemEval answer label is invalid")


def _exact_answer_span(content: str, answers: Sequence[str]) -> tuple[int, int, str] | None:
    matches: list[tuple[int, int, int, str]] = []
    for answer in answers:
        match = re.search(re.escape(answer), content, flags=re.IGNORECASE)
        if match is not None:
            text = content[match.start() : match.end()]
            matches.append((-len(text), match.start(), match.end(), text))
    if not matches:
        return None
    _negative_length, start, end, text = min(matches)
    return start, end, text


def native_answer_evidence(
    record: Mapping[str, Any],
    history_events: Sequence[Mapping[str, Any]],
) -> NativeAnswerEvidence:
    """Build exact labels from native ``has_answer`` fields after capture planning.

    The history event payload is the same label-free material sent to Product.
    Cardinality and content checks make the post-hoc join fail closed if capture
    planning ever diverges from the pinned dataset.
    """

    sessions = record.get("haystack_sessions")
    if not isinstance(sessions, list):
        raise ValueError("LongMemEval sessions are invalid")
    material_turns: list[Mapping[str, Any]] = []
    for session in sessions:
        if not isinstance(session, list):
            raise ValueError("LongMemEval session is invalid")
        material_turns.extend(session[index] for index in material_turn_ordinals(session))
    if len(material_turns) != len(history_events):
        raise ValueError("capture plan and native turn labels have different cardinality")

    answers = _answer_strings(record)
    labels: list[AnswerBearingSpanLabel] = []
    sources: dict[str, str] = {}
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for turn, event in zip(material_turns, history_events, strict=True):
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("capture event payload is invalid")
        source_ref = payload.get("source_ref")
        content = payload.get("content")
        speaker = payload.get("speaker")
        source_context = payload.get("source_context")
        if (
            not isinstance(source_ref, str)
            or not source_ref
            or not isinstance(content, str)
            or not isinstance(speaker, str)
            or not isinstance(source_context, Mapping)
            or not isinstance(source_context.get("session_id"), str)
            or turn.get("content") != content
            or turn.get("role") != speaker
        ):
            raise ValueError("capture plan lost native turn identity")
        sources[source_ref] = content
        if turn.get("has_answer") is not True:
            continue
        span = _exact_answer_span(content, answers)
        labels.append(
            AnswerBearingSpanLabel(
                source_turn_ref=source_ref,
                start=span[0] if span is not None else None,
                end=span[1] if span is not None else None,
                text=span[2] if span is not None else None,
            )
        )
        group = f"{source_context['session_id']}\0{speaker}"
        groups[group].append(source_ref)
    question_id = record.get("question_id")
    if not labels and (
        not isinstance(question_id, str) or not question_id.endswith("_abs")
    ):
        raise ValueError("positive LongMemEval case has no native has_answer turn")
    if len(sources) != len(history_events):
        raise ValueError("capture plan source refs are not unique")
    return NativeAnswerEvidence(
        labels=tuple(labels),
        source_text_by_turn_ref=sources,
        required_role_groups=tuple(
            tuple(groups[key]) for key in sorted(groups)
        ),
    )


def sealed_answer_evidence(
    record: Mapping[str, Any],
    history_events: Sequence[Mapping[str, Any]],
    label_case: Mapping[str, Any],
) -> SealedAnswerEvidence:
    """Join a pinned evaluation-plane label case after Product capture planning."""

    case_id = record.get("question_id")
    if not isinstance(case_id, str) or label_case.get("case_id") != case_id:
        raise ValueError("sealed answer label case identity mismatch")
    sessions = record.get("haystack_sessions")
    session_ids = record.get("haystack_session_ids")
    if not isinstance(sessions, list) or not isinstance(session_ids, list) or len(
        sessions
    ) != len(session_ids):
        raise ValueError("LongMemEval sessions are invalid")
    event_by_turn: dict[tuple[int, int], Mapping[str, Any]] = {}
    native_refs: list[str] = []
    sources: dict[str, str] = {}
    offset = 0
    for session_ordinal, session in enumerate(sessions):
        if not isinstance(session, list):
            raise ValueError("LongMemEval session is invalid")
        for turn_ordinal in material_turn_ordinals(session):
            if offset >= len(history_events):
                raise ValueError("capture plan ended before labeled source turns")
            turn = session[turn_ordinal]
            event = history_events[offset]
            offset += 1
            payload = event.get("payload")
            if not isinstance(turn, Mapping) or not isinstance(payload, Mapping):
                raise ValueError("capture plan turn is invalid")
            source_ref = payload.get("source_ref")
            content = payload.get("content")
            if (
                not isinstance(source_ref, str)
                or not isinstance(content, str)
                or content != turn.get("content")
            ):
                raise ValueError("capture plan lost sealed label source identity")
            event_by_turn[(session_ordinal, turn_ordinal)] = payload
            sources[source_ref] = content
            if turn.get("has_answer") is True:
                native_refs.append(source_ref)
    if offset != len(history_events) or len(sources) != len(history_events):
        raise ValueError("capture plan and sealed labels have different cardinality")

    selections = label_case.get("selections")
    negative = label_case.get("negative_without_answer_turn") is True
    if not isinstance(selections, list) or any(
        not isinstance(value, Mapping) for value in selections
    ):
        raise ValueError("sealed answer selections are invalid")
    if (negative and selections) or (not negative and not selections):
        raise ValueError("sealed positive/negative answer label contract is invalid")
    answer_labels: list[AnswerBearingSpanLabel] = []
    role_groups: list[tuple[str, ...]] = []
    role_labels: list[str] = []
    seen: set[tuple[int, int, str]] = set()
    for selection in selections:
        session_ordinal = selection.get("session_ordinal")
        turn_ordinal = selection.get("turn_ordinal")
        role = selection.get("requirement_role")
        direct_answer = selection.get("direct_answer")
        quote = selection.get("quote")
        if (
            isinstance(session_ordinal, bool)
            or not isinstance(session_ordinal, int)
            or isinstance(turn_ordinal, bool)
            or not isinstance(turn_ordinal, int)
            or not isinstance(role, str)
            or not role
            or not isinstance(direct_answer, bool)
            or not isinstance(quote, str)
            or not 0 <= session_ordinal < len(session_ids)
        ):
            raise ValueError("sealed answer selection shape is invalid")
        key = (session_ordinal, turn_ordinal, role)
        if key in seen:
            raise ValueError("sealed answer selection is duplicated")
        seen.add(key)
        payload = event_by_turn.get((session_ordinal, turn_ordinal))
        if payload is None:
            raise ValueError("sealed answer selection references an unknown turn")
        if selection.get("source_session_id") != session_ids[session_ordinal]:
            raise ValueError("sealed answer selection session identity drifted")
        source_ref = payload["source_ref"]
        content = payload["content"]
        speaker = payload.get("speaker")
        if (
            not isinstance(source_ref, str)
            or not isinstance(content, str)
            or not isinstance(speaker, str)
        ):
            raise AssertionError("validated capture payload changed shape")
        if selection.get("speaker") != speaker:
            raise ValueError("sealed answer selection speaker identity drifted")
        if selection.get("source_text_sha256") != hashlib.sha256(
            content.encode()
        ).hexdigest():
            raise ValueError("sealed answer selection source text drifted")
        role_groups.append((source_ref,))
        role_labels.append(role)
        if not direct_answer:
            continue
        if quote:
            start = content.find(quote)
            if start < 0:
                raise ValueError("sealed exact quote is absent from its source turn")
            answer_labels.append(
                AnswerBearingSpanLabel(
                    source_turn_ref=source_ref,
                    start=start,
                    end=start + len(quote),
                    text=quote,
                )
            )
        else:
            answer_labels.append(AnswerBearingSpanLabel(source_turn_ref=source_ref))
    return SealedAnswerEvidence(
        answer_labels=tuple(answer_labels),
        source_text_by_turn_ref=sources,
        required_role_groups=tuple(role_groups),
        required_role_labels=tuple(role_labels),
        native_has_answer_source_turn_refs=tuple(native_refs),
        negative_without_answer_turn=negative,
    )


def required_role_coverage(
    visible_source_turn_refs: Sequence[str],
    role_groups: Sequence[Sequence[str]],
) -> float:
    """Cover each native answer session/speaker role with at least one exact turn."""

    if not role_groups or any(not group for group in role_groups):
        raise ValueError("required role groups must be non-empty")
    visible = set(visible_source_turn_refs)
    covered = sum(bool(visible.intersection(group)) for group in role_groups)
    return covered / len(role_groups)


def sealed_strict_wrong_complete(
    *,
    lean_recall_mode: str | None,
    sufficiency_status: str | None,
    accepted_source_turn_refs: Sequence[str],
    evidence: SealedAnswerEvidence,
) -> tuple[int, tuple[str, ...]]:
    """Reject STRICT COMPLETE unless every sealed required role was accepted."""

    accepted = set(accepted_source_turn_refs)
    missing_roles = tuple(
        role
        for role, group in zip(
            evidence.required_role_labels,
            evidence.required_role_groups,
            strict=True,
        )
        if accepted.isdisjoint(group)
    )
    wrong = int(
        lean_recall_mode == "STRICT"
        and sufficiency_status == "COMPLETE"
        and (evidence.negative_without_answer_turn or bool(missing_roles))
    )
    return wrong, missing_roles


__all__ = [
    "NativeAnswerEvidence",
    "SealedAnswerEvidence",
    "native_answer_evidence",
    "required_role_coverage",
    "sealed_answer_evidence",
    "sealed_strict_wrong_complete",
]
