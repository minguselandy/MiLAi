"""One task-local decision and the exact material it declared as adopted."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from milai_lab.methods.contextual_memory.material_view import MaterialBinding

DECISION_PROTOCOL = "decision-basis-v2"
STATE_TEXT_LIMIT = 1200
STATE_DELTA_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {"type": "null"},
        {"type": "object", "properties": {"op": {"const": "clear"}},
         "required": ["op"], "additionalProperties": False},
        {"type": "object", "properties": {
            "op": {"const": "set"},
            "decision": {"type": "string", "minLength": 1, "maxLength": 320},
            "scope": {"type": "object", "properties": {
                "subject_ref": {"type": "string", "minLength": 1},
                "item": {"type": "string", "maxLength": 220},
                "context": {"type": "string", "maxLength": 220},
            }, "required": ["subject_ref", "item", "context"],
                "additionalProperties": False},
            "adopted_evidence": {"type": "array", "maxItems": 12,
                                 "items": {"type": "string"}},
            "critical_gap": {"oneOf": [
                {"type": "null"},
                {"type": "string", "minLength": 1, "maxLength": 240},
            ]},
            "status": {"type": "string", "enum": ["active", "deferred"]},
        }, "required": ["op", "decision", "scope", "adopted_evidence",
                       "critical_gap", "status"], "additionalProperties": False},
    ],
}
WORK_NOTE_SCHEMA: dict[str, Any] = {"type": ["null", "string"],
                                    "maxLength": STATE_TEXT_LIMIT}


@dataclass(frozen=True)
class AdoptedEvidence:
    exact_ref: str
    kind: str
    spans: tuple[tuple[int, int], ...]
    content_sha256: str
    observed_ref: str


@dataclass
class DecisionBasis:
    decision_id: str
    revision: int
    task_id: str
    decision: str
    scope: dict[str, str]
    adopted: tuple[AdoptedEvidence, ...]
    critical_gap: str
    status: str
    last_delivered_source_sequence: int = 0
    recheck_reasons: list[dict[str, str]] = field(default_factory=list)


def restored(value: dict[str, Any] | None) -> DecisionBasis | None:
    if value is None:
        return None
    item = dict(value)
    item["adopted"] = tuple(
        AdoptedEvidence(
            exact_ref=row["exact_ref"], kind=row["kind"],
            spans=tuple(tuple(span) for span in row["spans"]),
            content_sha256=row["content_sha256"],
            observed_ref=row["observed_ref"],
        ) for row in item["adopted"]
    )
    return DecisionBasis(**item)


def continuation_handles(current: DecisionBasis | None) -> dict[str, AdoptedEvidence]:
    if current is None:
        return {}
    return {f"c{index}": row for index, row in enumerate(current.adopted)}


def projected(
    current: DecisionBasis | None, *, subject_alias: str = "unknown",
    new_observations: tuple[str, ...] = (),
    material_labels: Mapping[str, dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    if current is None:
        return None
    return {
        "decision": current.decision,
        "scope": {**current.scope, "subject_ref": subject_alias},
        "adopted_evidence": [
            {"ref": short, "kind": row.kind,
             "version": row.exact_ref.rsplit("@", 1)[-1] if "@" in row.exact_ref else "source",
             "spans": [list(span) for span in row.spans],
             **(material_labels or {}).get(row.exact_ref, {})}
            for short, row in continuation_handles(current).items()
        ],
        "critical_gap": current.critical_gap,
        "status": "needs_recheck" if current.recheck_reasons else current.status,
        "host_intent": current.status if current.recheck_reasons else None,
        "new_observations": list(new_observations),
        "recheck_reasons": [
            {"ref": short, "reason": reason["reason"],
             "current_version": (reason["current_ref"].rsplit("@", 1)[-1]
                                 if "@" in reason["current_ref"] else
                                 "replaced_or_unavailable")}
            for short, row in continuation_handles(current).items()
            for reason in current.recheck_reasons
            if reason["adopted_ref"] == row.exact_ref
        ],
    }


def bind_delta(
    delta: dict[str, Any] | None, *, current: DecisionBasis | None,
    task_id: str, visible: Mapping[str, MaterialBinding],
    valid_subjects: Mapping[str, str], unavailable: set[str],
    current_ref: Callable[[str], str],
    delivered_source_sequence: int = 0,
    presented_reasons: tuple[dict[str, str], ...] = (),
) -> DecisionBasis | None:
    """Validate a whole replacement before mutating the task state."""
    if delta is None:
        return current
    if delta["op"] == "clear":
        return None
    scope = delta["scope"]
    if scope["subject_ref"] not in valid_subjects:
        raise ValueError("DECISION_SUBJECT_NOT_DELIVERED")
    raw_gap = delta["critical_gap"]
    gap = raw_gap.strip() if isinstance(raw_gap, str) else None
    if gap is not None and (not gap or gap.casefold() in {
        "null", "none", "unknown", "resolved",
    }):
        raise ValueError("DECISION_GAP_NOT_INFORMATION_NEED")
    text_length = sum(len(value) for value in (
        delta["decision"], *scope.values(), gap or "",
    ))
    if text_length > STATE_TEXT_LIMIT:
        raise ValueError("DECISION_TEXT_LIMIT_EXCEEDED")
    continued = continuation_handles(current)
    adopted: list[AdoptedEvidence] = []
    for short in delta["adopted_evidence"]:
        if short in continued:
            row = continued[short]
        elif short in visible:
            binding = visible[short]
            if binding.kind not in {"source", "interpretation"} or not binding.spans:
                raise ValueError("DECISION_EVIDENCE_BODY_NOT_DELIVERED")
            row = AdoptedEvidence(
                binding.exact_ref, binding.kind, binding.spans, binding.content_sha256,
                current_ref(binding.exact_ref),
            )
        else:
            raise ValueError("DECISION_EVIDENCE_NOT_DELIVERED")
        if row.exact_ref in unavailable:
            raise ValueError("DECISION_EVIDENCE_UNAVAILABLE")
        # A continued old version stays old until its change was actually presented.
        if short not in continued:
            row = AdoptedEvidence(row.exact_ref, row.kind, row.spans,
                                  row.content_sha256, row.exact_ref)
        if not any((old.exact_ref, old.kind, old.spans, old.content_sha256) ==
                   (row.exact_ref, row.kind, row.spans, row.content_sha256)
                   for old in adopted):
            adopted.append(row)
    if current is not None and current.task_id != task_id:
        raise ValueError("DECISION_TASK_MISMATCH")
    if gap is None:
        return None
    normalized_scope = {key: value.strip() for key, value in scope.items()}
    normalized_scope["subject_ref"] = valid_subjects[scope["subject_ref"]]
    acknowledged = [
        reason for reason in current.recheck_reasons
        if reason in presented_reasons
    ] if current is not None else []
    adopted = [
        AdoptedEvidence(row.exact_ref, row.kind, row.spans, row.content_sha256,
                        next((reason["current_ref"] for reason in reversed(acknowledged)
                              if reason["adopted_ref"] == row.exact_ref), row.observed_ref))
        for row in adopted
    ]
    def evidence_key(row: AdoptedEvidence) -> tuple[Any, ...]:
        return row.exact_ref, row.kind, row.spans, row.content_sha256

    same_evidence = current is not None and (
        {evidence_key(row) for row in current.adopted}
        == {evidence_key(row) for row in adopted}
    )
    if same_evidence and current is not None:
        adopted = [next(row for row in adopted if evidence_key(row) == evidence_key(old))
                   for old in current.adopted]
    same = current is not None and (
        current.decision == delta["decision"].strip()
        and current.scope == normalized_scope
        and current.critical_gap == gap
        and current.status == delta["status"]
        and same_evidence
    )
    new_sequence = max(current.last_delivered_source_sequence
                       if current else 0, delivered_source_sequence)
    if (same and current is not None and not acknowledged
            and new_sequence == current.last_delivered_source_sequence):
        return current
    return DecisionBasis(
        decision_id=current.decision_id if current else uuid4().hex,
        revision=(current.revision if same else current.revision + 1) if current else 1,
        task_id=task_id, decision=delta["decision"].strip(),
        scope=normalized_scope,
        adopted=tuple(adopted), critical_gap=gap,
        status=delta["status"],
        last_delivered_source_sequence=new_sequence,
        recheck_reasons=[reason for reason in current.recheck_reasons
                         if reason not in acknowledged and any(
                             row.exact_ref == reason["adopted_ref"] for row in adopted
                         )] if current else [],
    )


def mark_change(current: DecisionBasis | None, *, exact_ref: str,
                current_ref: str, reason: str) -> bool:
    """Record one actual change only once, without changing the adopted version."""
    if current is None or not any(
        row.exact_ref == exact_ref and
        (row.observed_ref != current_ref or reason == "task_scope_changed")
        for row in current.adopted
    ):
        return False
    event = {"adopted_ref": exact_ref, "current_ref": current_ref, "reason": reason}
    if event in current.recheck_reasons:
        return False
    current.recheck_reasons.append(event)
    return True


def transition_kind(
    current: DecisionBasis | None, candidate: DecisionBasis | None,
    delta: dict[str, Any] | None,
) -> str:
    if candidate is current:
        return "NO_STATE_CHANGE"
    if candidate is None:
        return "NO_STATE_CHANGE" if current is None else (
            "GAP_RESOLVED" if delta is not None and delta.get("op") == "set"
            else "CLEARED"
        )
    if current is not None and candidate.revision == current.revision:
        return "REVIEW_ACKNOWLEDGED"
    return "STATE_CHANGED"


def dump(current: DecisionBasis | None) -> dict[str, Any] | None:
    return asdict(current) if current is not None else None
