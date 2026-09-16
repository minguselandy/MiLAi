"""Typed, label-free contracts for the DG-14 LongMemEval adapter."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast, runtime_checkable

METHOD_ID = "DG14-MILAI-MCP"
MCP_PROTOCOL_MODE = "2026-07-28"

McpProfile = Literal["submitter", "reviewer", "reader-detail", "operator"]
HistoryRole = Literal["user", "assistant", "system", "tool"]


class DG14Error(RuntimeError):
    """Base error for the DG-14 adapter."""


class DG14ContractError(DG14Error, ValueError):
    """A DG-14 input or response violated the explicit contract."""


class DG14LabelBoundaryError(DG14ContractError):
    """Benchmark-only information crossed the history-ingest boundary."""


class DG14LifecycleError(DG14Error):
    """A lifecycle method was called out of order."""


class DG14TransportError(DG14Error):
    """A current-protocol MCP call failed."""


class DG14ReadinessError(DG14Error):
    """Canonical projections are not ready for a benchmark query."""


class DG14ContextBudgetError(DG14Error):
    """The final exported context cannot satisfy the requested token budget."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _normalized_key(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return "".join(character for character in normalized if character.isalnum())


_FORBIDDEN_KEYS = frozenset(
    {
        "answer",
        "answers",
        "answersessionid",
        "answersessionids",
        "category",
        "gold",
        "goldanswer",
        "goldanswers",
        "label",
        "labels",
        "question",
        "questions",
        "questiontype",
        "score",
        "scores",
        "scorer",
        "scoreroutput",
    }
)


def validate_label_free(value: object, *, path: str = "history") -> None:
    """Reject label-bearing keys recursively without inspecting user text values."""

    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            if not isinstance(raw_key, str):
                raise DG14LabelBoundaryError(
                    f"history mapping key at {path} must be a string"
                )
            key = _normalized_key(raw_key)
            if (
                key in _FORBIDDEN_KEYS
                or "answer" in key
                or key.startswith("gold")
                or "question" in key
                or "scorer" in key
                or "holdout" in key
            ):
                raise DG14LabelBoundaryError(
                    f"forbidden benchmark field at {path}.{raw_key}"
                )
            validate_label_free(nested, path=f"{path}.{raw_key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            validate_label_free(nested, path=f"{path}[{index}]")


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DG14ContractError(f"{name} must be a non-empty string")


def _require_timestamp(value: str, name: str) -> None:
    _require_text(value, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DG14ContractError(f"{name} must be an RFC3339 timestamp") from exc
    if parsed.utcoffset() is None:
        raise DG14ContractError(f"{name} must include a timezone offset")


def normalize_lme_timestamp(value: str) -> str:
    """Normalize LongMemEval's opened snapshot timestamp convention to RFC3339 UTC."""

    _require_text(value, "timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)
        except ValueError as exc:
            raise DG14ContractError(
                "timestamp must be RFC3339 or LongMemEval %Y/%m/%d (%a) %H:%M"
            ) from exc
    if parsed.utcoffset() is None:
        raise DG14ContractError("RFC3339 timestamp must include a timezone offset")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def deterministic_event_id(
    case_id: str,
    session_ordinal: int,
    original_session_id: str,
    turn_ordinal: int,
) -> str:
    """Bind all source identity components into one deterministic Event identity."""

    identity = {
        "case_id": case_id,
        "session_ordinal": session_ordinal,
        "original_session_id": original_session_id,
        "turn_ordinal": turn_ordinal,
    }
    return f"dg14-event-{sha256_json(identity)}"


def deterministic_history_session_id(
    case_id: str,
    session_ordinal: int,
    original_session_id: str,
) -> str:
    """Return the collision-free source session identity used by Runtime.

    LongMemEval scorer session IDs are not guaranteed to be unique within one
    case. Runtime adjacency therefore binds the case-local session ordinal as
    well as the scorer-facing ID. The original ID remains available through
    ``source_ref`` and scorer provenance.
    """

    identity = {
        "case_id": case_id,
        "session_ordinal": session_ordinal,
        "original_session_id": original_session_id,
    }
    return f"lme-source-session-{sha256_json(identity)}"


def deterministic_project_id(run_id: str, case_id: str, *, prefix: str = "dg14-lme") -> str:
    _require_text(run_id, "run_id")
    _require_text(case_id, "case_id")
    digest = hashlib.sha256(f"{run_id}\0{case_id}".encode()).hexdigest()[:24]
    return f"{prefix}-{digest}"


@dataclass(frozen=True, slots=True)
class DG14HistoryEvent:
    """The complete and only allowed history-ingest shape."""

    case_id: str
    session_ordinal: int
    original_session_id: str
    turn_ordinal: int
    role: HistoryRole
    content: str
    observed_at: str

    def __post_init__(self) -> None:
        _require_text(self.case_id, "case_id")
        _require_text(self.original_session_id, "original_session_id")
        _require_text(self.content, "content")
        _require_timestamp(self.observed_at, "observed_at")
        if isinstance(self.session_ordinal, bool) or self.session_ordinal < 0:
            raise DG14ContractError("session_ordinal must be a non-negative integer")
        if isinstance(self.turn_ordinal, bool) or self.turn_ordinal < 0:
            raise DG14ContractError("turn_ordinal must be a non-negative integer")
        if self.role not in {"user", "assistant", "system", "tool"}:
            raise DG14ContractError("role is not an enabled history role")

    @property
    def event_id(self) -> str:
        return deterministic_event_id(
            self.case_id,
            self.session_ordinal,
            self.original_session_id,
            self.turn_ordinal,
        )

    def canonical(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "session_ordinal": self.session_ordinal,
            "original_session_id": self.original_session_id,
            "turn_ordinal": self.turn_ordinal,
            "role": self.role,
            "content": self.content,
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DG14HistoryEvent:
        """Load the exact allowlist shape and reject nested benchmark labels first."""

        validate_label_free(value)
        allowed = {
            "case_id",
            "session_ordinal",
            "original_session_id",
            "turn_ordinal",
            "role",
            "content",
            "observed_at",
        }
        unexpected = sorted(set(value) - allowed)
        missing = sorted(allowed - set(value))
        if unexpected or missing:
            raise DG14ContractError(
                f"history event keys mismatch; missing={missing}, unexpected={unexpected}"
            )
        case_id = value["case_id"]
        session_ordinal = value["session_ordinal"]
        original_session_id = value["original_session_id"]
        turn_ordinal = value["turn_ordinal"]
        role = value["role"]
        content = value["content"]
        observed_at = value["observed_at"]
        if not all(
            isinstance(item, str)
            for item in (case_id, original_session_id, role, content, observed_at)
        ):
            raise DG14ContractError("history event text fields must be strings")
        if not isinstance(session_ordinal, int) or isinstance(session_ordinal, bool):
            raise DG14ContractError("session_ordinal must be an integer")
        if not isinstance(turn_ordinal, int) or isinstance(turn_ordinal, bool):
            raise DG14ContractError("turn_ordinal must be an integer")
        return cls(
            case_id=cast(str, case_id),
            session_ordinal=session_ordinal,
            original_session_id=cast(str, original_session_id),
            turn_ordinal=turn_ordinal,
            role=cast(HistoryRole, role),
            content=cast(str, content),
            observed_at=cast(str, observed_at),
        )


@dataclass(frozen=True, slots=True)
class DG14CaseNamespace:
    run_id: str
    case_id: str
    project_id: str
    scope: Mapping[str, object]
    tenant_id: str | None = None
    principal_id: str | None = None


@dataclass(frozen=True, slots=True)
class DG14AdapterConfig:
    base_url: str
    executable: Path | str
    profile_tokens: Mapping[McpProfile, str]
    tenant_id: str | None = None
    principal_id: str | None = None
    scope: Mapping[str, object] = field(default_factory=dict)
    max_limit: int = 3
    allowed_budgets: tuple[int, ...] = (512, 2048)
    project_prefix: str = "dg14-lme"

    def __post_init__(self) -> None:
        _require_text(self.base_url, "base_url")
        required_profiles = {"submitter", "reviewer", "reader-detail", "operator"}
        if set(self.profile_tokens) != required_profiles:
            raise DG14ContractError(
                "profile_tokens must contain exactly submitter, reviewer, reader-detail, operator"
            )
        if any(not token.strip() for token in self.profile_tokens.values()):
            raise DG14ContractError("profile tokens must be non-empty")
        if not 1 <= self.max_limit <= 50:
            raise DG14ContractError("max_limit must be between 1 and 50")
        if not self.allowed_budgets or any(value <= 0 for value in self.allowed_budgets):
            raise DG14ContractError("allowed_budgets must contain positive values")
        if "project_ids" in self.scope:
            raise DG14ContractError(
                "config scope must not pre-bind project_ids; reset binds the exact case scope"
            )
        validate_label_free(self.scope, path="config.scope")


@runtime_checkable
class DG14McpTransport(Protocol):
    def open_case(self, scope: Mapping[str, object]) -> None: ...

    def call(
        self,
        profile: McpProfile,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def close(self) -> None: ...


TokenCounter = Callable[[str], int]


@dataclass(frozen=True, slots=True)
class DG14ReadinessRequest:
    namespace: DG14CaseNamespace
    evidence_count: int
    claim_count: int


ReadinessHook = Callable[[DG14ReadinessRequest], Mapping[str, object] | None]


@dataclass(frozen=True, slots=True)
class DG14CallRecord:
    sequence: int
    stage: str
    profile: McpProfile
    tool_name: str
    request_sha256: str
    response_sha256: str | None
    latency_ms: float
    status: Literal["SUCCEEDED", "FAILED"]
    runtime_request_id: str | None = None
    retrieval_trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class DG14StageRecord:
    sequence: int
    stage: str
    latency_ms: float
    logical_call_start: int
    logical_call_end: int
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DG14Provenance:
    rank: int
    source_id: str
    session_id: str
    session_ordinal: int
    claim_id: str
    claim_version_id: str
    evidence_ids: tuple[str, ...]
    relevance_score: float | None
    context_selected: bool


@dataclass(frozen=True, slots=True)
class DG14QueryResult:
    method_id: str
    status: str
    context: str
    source_ids: tuple[str, ...]
    provenance: tuple[DG14Provenance, ...]
    stage_trace: tuple[DG14StageRecord, ...]
    declared_tokens: int
    latency_ms: float
    usage: Mapping[str, object]
    raw_resolve: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class DG14AdapterStats:
    method_id: str
    case_id: str | None
    evidence_count: int
    claim_count: int
    query_count: int
    logical_mcp_calls: int
    evidence_ingest_ms: float
    finalize_ms: float
    query_ms: tuple[float, ...]
    context_tokens: tuple[int, ...]


_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def lexical_terms(value: str) -> frozenset[str]:
    return frozenset(match.group(0).casefold() for match in _WORD.finditer(value))
