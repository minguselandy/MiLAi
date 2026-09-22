"""Pure, bounded research Attention decisions; no retrieval/model/dispatch here.

Visible state and coverage are caller-reviewed assertions, never semantic truth.
The runner authenticates provenance and owns a monotonic expansion-attempt count.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from milai_lab.methods.state_focus import Eligibility, SourceSnapshot, SourceUnit

FIELDS = {
    "active_goal",
    "hypotheses",
    "failed_approaches",
    "unresolved_constraints",
    "next_actions",
    "memory_intentions",
    "uncertainty",
    "open_conflicts",
    "recent_evidence",
}
POLICY = "research-state-attention-v0.1"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def question_digest(question: str) -> str:
    return hashlib.sha256(question.encode()).hexdigest()


@dataclass(frozen=True)
class StateField:
    name: str
    owner: Literal["HOST", "ACTOR", "TOOL"]
    observed_sequence: int
    valid_through_sequence: int
    artifact_ref: str | None
    sources: tuple[SourceUnit, ...] = ()


@dataclass(frozen=True)
class AttentionState:
    task_id: str
    scope: str
    input_sha256: str
    snapshot_sha256: str
    fields: tuple[StateField, ...]

    @property
    def sha256(self) -> str:
        return _digest(
            {
                "task_id": self.task_id,
                "scope": self.scope,
                "input_sha256": self.input_sha256,
                "snapshot_sha256": self.snapshot_sha256,
                "fields": [
                    {
                        **{k: v for k, v in asdict(f).items() if k != "sources"},
                        "sources": [s.reference() | {"scope": s.scope} for s in f.sources],
                    }
                    for f in self.fields
                ],
            }
        )


@dataclass(frozen=True)
class CoverageReview:
    state_sha256: str
    snapshot_sha256: str
    selected_ids: tuple[str, ...]
    status: Literal["SUFFICIENT", "GAP", "UNKNOWN"]
    artifact_ref: str | None
    observed_sequence: int
    valid_through_sequence: int


@dataclass(frozen=True)
class AttentionLimits:
    max_sources: int = 8
    max_bytes: int = 8192
    expansion_limit: int = 4


DEFAULT_LIMITS = AttentionLimits()


def decide_attention(
    *,
    task_id: str,
    question: str,
    sequence: int,
    snapshot: SourceSnapshot,
    baseline_ids: tuple[str, ...],
    state: AttentionState | None,
    coverage: CoverageReview | None,
    expansion_attempts: int,
    check_source: Callable[[SourceUnit], Eligibility],
    limits: AttentionLimits = DEFAULT_LIMITS,
) -> dict[str, Any]:
    """Plan over an already acquired pool; preserve original source order/bytes.

    memory_intentions lists explicitly reviewed relevant sources. open_conflicts
    lists ALL sides of reviewed current conflicts (empty means reviewed absent).
    Unknown state falls back to baseline, never inventing relevance or confidence.
    Coverage must describe the exact bounded selection, not the whole acquired pool.
    A RETRIEVE_ONCE intent is not a call or permission: persist/debit its attempt
    before dispatch, count failures too, merge results then decide again with 1.
    Recheck eligibility again at dispatch. Callers must not reset the counter.
    """
    if (
        not task_id
        or not question.strip()
        or len(question.encode()) > 4096
        or type(sequence) is not int
        or sequence < 1
        or type(expansion_attempts) is not int
        or expansion_attempts not in {0, 1}
        or type(limits.max_sources) is not int
        or not 1 <= limits.max_sources <= 32
        or type(limits.max_bytes) is not int
        or not 1 <= limits.max_bytes <= 65536
        or type(limits.expansion_limit) is not int
        or not 1 <= limits.expansion_limit <= 32
    ):
        raise ValueError("INVALID_ATTENTION_INPUT_OR_LIMITS")
    units = {s.source_id: s for s in snapshot.units}
    if len(set(baseline_ids)) != len(baseline_ids) or not set(baseline_ids) <= units.keys():
        raise ValueError("INVALID_ATTENTION_BASELINE")
    eligibility: dict[str, str] = {}
    for unit in snapshot.units:
        try:
            value = check_source(unit)
        except Exception:
            value = "UNKNOWN"
        eligibility[unit.source_id] = (
            value if isinstance(value, str) and value in {"ELIGIBLE", "DENIED"} else "UNKNOWN"
        )
    eligible = {ref for ref, value in eligibility.items() if value == "ELIGIBLE"}
    field_status: dict[str, str] = {}
    fields: dict[str, StateField] = {}
    state_matches = state is not None and (
        state.task_id == task_id
        and state.scope == snapshot.scope
        and state.input_sha256 == question_digest(question)
        and state.snapshot_sha256 == snapshot.sha256
    )
    if state is not None:
        for field in state.fields:
            if field.name not in FIELDS or field.name in fields:
                raise ValueError("INVALID_ATTENTION_STATE_FIELDS")
            fields[field.name] = field
            allowed_owners = {"HOST", "ACTOR"}
            if field.name in {"failed_approaches", "unresolved_constraints", "recent_evidence"}:
                allowed_owners.add("TOOL")
            valid = (
                state_matches
                and field.owner in allowed_owners
                and bool(field.artifact_ref)
                and type(field.observed_sequence) is int
                and type(field.valid_through_sequence) is int
                and 0 <= field.observed_sequence < sequence <= field.valid_through_sequence
                and len({s.source_id for s in field.sources}) == len(field.sources)
                and all(
                    units.get(s.source_id) == s and s.source_id in eligible for s in field.sources
                )
            )
            field_status[field.name] = "CURRENT" if valid else "UNKNOWN"
    for name in FIELDS:
        field_status.setdefault(name, "UNKNOWN")

    def bounded(wanted: set[str], required: set[str]) -> tuple[str, ...] | None:
        if (
            len(required) > limits.max_sources
            or sum(len(units[ref].content.encode()) for ref in required) > limits.max_bytes
        ):
            return None
        chosen = set(required)
        used = sum(len(units[ref].content.encode()) for ref in chosen)
        for unit in snapshot.units:
            ref, size = unit.source_id, len(unit.content.encode())
            if ref in wanted & eligible and ref not in chosen:
                if len(chosen) < limits.max_sources and used + size <= limits.max_bytes:
                    chosen.add(ref)
                    used += size
        return tuple(unit.source_id for unit in snapshot.units if unit.source_id in chosen)

    baseline = bounded(set(baseline_ids), set())
    assert baseline is not None
    selected = baseline
    mode, action, reason = "FOCUS", "CONTEXT", "BASELINE_STATE_UNKNOWN"
    coverage_status = "UNKNOWN"
    retrieval = None
    conflict: set[str] = set()
    focus_current = field_status["memory_intentions"] == "CURRENT"
    conflicts_current = field_status["open_conflicts"] == "CURRENT"
    if conflicts_current:
        conflict = {s.source_id for s in fields["open_conflicts"].sources}
        if len(conflict) == 1:
            field_status["open_conflicts"] = "UNKNOWN"
            conflicts_current = False
    if conflicts_current and (conflict or focus_current):
        wanted = (
            {s.source_id for s in fields["memory_intentions"].sources} if focus_current else set()
        )
        candidate = bounded(wanted | conflict, conflict)
        if candidate is None:
            mode, action, reason, selected = (
                "CONFLICT",
                "ABSTAIN_MEMORY",
                "CONFLICT_OVER_BUDGET",
                (),
            )
        else:
            selected = candidate
            mode = "CONFLICT" if conflict else "FOCUS"
            reason = "PRESERVE_CONFLICT" if conflict else "REVIEWED_FOCUS"
            if (
                coverage is not None
                and state is not None
                and coverage.state_sha256 == state.sha256
                and coverage.snapshot_sha256 == snapshot.sha256
                and coverage.selected_ids == selected
                and coverage.artifact_ref
                and type(coverage.observed_sequence) is int
                and type(coverage.valid_through_sequence) is int
                and max(
                    (
                        f.observed_sequence
                        for f in state.fields
                        if field_status[f.name] == "CURRENT"
                    ),
                    default=0,
                )
                <= coverage.observed_sequence
                < sequence
                <= coverage.valid_through_sequence
                and coverage.status in {"SUFFICIENT", "GAP", "UNKNOWN"}
            ):
                coverage_status = coverage.status
            if not conflict:
                if coverage_status == "UNKNOWN":
                    selected, reason = baseline, "BASELINE_COVERAGE_UNKNOWN"
                elif coverage_status == "GAP":
                    mode = "EXPLORE"
                    remaining = min(limits.expansion_limit, 32 - len(snapshot.units))
                    remaining_bytes = 65536 - sum(len(s.content.encode()) for s in snapshot.units)
                    if expansion_attempts or remaining == 0 or remaining_bytes == 0:
                        action, reason = "ABSTAIN_MEMORY", "EXPANSION_EXHAUSTED"
                        selected = ()
                    else:
                        action, reason = "RETRIEVE_ONCE", "REVIEWED_COVERAGE_GAP"
                        retrieval = {
                            "query": question,
                            "scope": snapshot.scope,
                            "exclude_source_ids": list(units),
                            "limit": remaining,
                            "max_bytes": remaining_bytes,
                        }
    if not selected and action == "CONTEXT":
        action, reason = "ABSTAIN_MEMORY", "NO_ELIGIBLE_MEMORY"
    result = {
        "policy": POLICY,
        "policy_sha256": _digest(asdict(limits)),
        "arm_kind": "RESEARCH_PROTOTYPE",
        "task_id": task_id,
        "scope": snapshot.scope,
        "input_sha256": question_digest(question),
        "sequence": sequence,
        "state_sha256": state.sha256 if state else None,
        "coverage_review_sha256": _digest(asdict(coverage)) if coverage else None,
        "snapshot_sha256": snapshot.sha256,
        "baseline_ids": baseline_ids,
        "field_status": field_status,
        "eligibility": eligibility,
        "mode": mode,
        "action": action,
        "reason": reason,
        "coverage": coverage_status,
        "selected_sources": [units[ref].reference() for ref in selected],
        "selected_bytes": sum(len(units[ref].content.encode()) for ref in selected),
        "expansion_attempts": expansion_attempts,
        "retrieval": retrieval,
        "observable_use": "UNKNOWN",
        "claim_ceiling": "POLICY_DECISION_NOT_EFFECT",
    }
    return {**result, "decision_sha256": _digest(result)}
