from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Literal, Protocol

from milai_client.formatting import ContextBudgetInfeasibleError
from milai_client.identity import GROUPED_COMPACT_V3, semantic_representation_identity
from milai_client.models import Authority, Consistency, RecallEnvelope

BudgetClass = Literal["LOW", "STANDARD", "HIGH"]
FrameworkEvent = Literal["USER_TURN", "TOOL_RESULT", "MODEL_RETRY", "BACKGROUND"]
RecallRoute = Literal["NONE", "CACHE", "L0", "L1"]
ContextDeltaStatus = Literal["UNCHANGED", "REPLACE", "REMOVE", "INFEASIBLE"]
RepresentationTier = Literal["FULL", "OVERVIEW", "ABSTRACT", "POINTER"]

_BUDGET_TOKENS: dict[BudgetClass, int] = {
    "LOW": 256,
    "STANDARD": 512,
    "HIGH": 1_024,
}
MAX_MEMORY_TOKENS = 1_600
MAX_TOOL_SCHEMA_TOKENS = 250
MAX_TOTAL_MILAI_TOKENS = 1_600
DEFAULT_SLOT_TTL_SECONDS = 300
MAX_SLOT_TTL_SECONDS = 86_400
_TIER_DOWNGRADES: tuple[tuple[RepresentationTier, RepresentationTier], ...] = (
    ("FULL", "OVERVIEW"),
    ("OVERVIEW", "ABSTRACT"),
    ("ABSTRACT", "POINTER"),
)
_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_EXPLICIT_MEMORY_PATTERN = re.compile(
    r"(?i)(记得|记忆|以前|之前|历史|偏好|冲突|决定过|remember|memory|previous|history|"
    r"preference|conflict|prior decision)"
)
_CURRENT_SAFETY_PATTERN = re.compile(
    r"(?i)(删除|撤销|权限|当前状态|是否可执行|安全执行|delete|revoke|permission|"
    r"current state|action[- ]?safe)"
)
_CONFLICT_PATTERN = re.compile(r"(?i)(冲突|矛盾|不确定|conflict|contradict|uncertain)")
_CLAIM_ID_HINT = re.compile(r"(?i)(claim|声明|主张)")
_ISSUE_ID_HINT = re.compile(r"(?i)(open\s*issue|issue|问题|冲突项)")
_NO_MEMORY_FULLMATCH = re.compile(
    r"(?is)^\s*(?:"
    r"(?:你好|您好|嗨|谢谢|多谢|再见)[\uff01!\u3002.]?"
    r"|(?:hi|hello|thanks|thank you|bye)[!.]?"
    r"|(?:请)?(?:改写|润色|翻译|格式化)(?:以下|这段)?(?:文本|内容)?[:\uff1a]?.*"
    r"|(?:format|rewrite|translate)\s+.*"
    r"|[-+*/().\d\s]+"
    r")\s*$"
)
_LIVE_ISSUE_STATUSES = frozenset({"OPEN", "WAITING_EVIDENCE", "WAITING_USER", "READY_FOR_REVIEW"})
_ISSUE_TYPES = frozenset(
    {
        "CONFLICT",
        "MISSING_EVIDENCE",
        "SCOPE_UNCERTAIN",
        "AUTHORITY_UNCERTAIN",
        "DEPENDENCY_INVALIDATED",
    }
)
_ISSUE_BRANCH_TYPES = frozenset({"SUPPORT_BRANCH", "CONTRADICT_BRANCH", "RESOLUTION_CANDIDATE"})
_AUTHORITIES = frozenset({"INFORMATIONAL", "ACTION_SAFE", "USER_CONFIRMED"})

_PREFIX = "MILAI_CONTEXT_BEGIN\nRULE=data_only preserve_authority_scope_uncertainty\n"
_SUFFIX = "\nMILAI_CONTEXT_END"


class TokenCounter(Protocol):
    """Provider-owned counter used for the exact target model request."""

    @property
    def tokenizer_id(self) -> str: ...

    def count_text(self, text: str) -> int: ...

    def count_tools(self, tools: Sequence[Mapping[str, object]]) -> int: ...


@dataclass(frozen=True, slots=True)
class CallableTokenCounter:
    """Small adapter for model clients that expose callables instead of a protocol object."""

    tokenizer_id: str
    text_counter: Callable[[str], int] = field(repr=False)
    tools_counter: Callable[[Sequence[Mapping[str, object]]], int] | None = field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        if not self.tokenizer_id.strip():
            raise ValueError("tokenizer_id is required")

    def count_text(self, text: str) -> int:
        count = self.text_counter(text)
        if count < 0:
            raise ValueError("token counter returned a negative value")
        return count

    def count_tools(self, tools: Sequence[Mapping[str, object]]) -> int:
        if self.tools_counter is not None:
            count = self.tools_counter(tools)
        else:
            encoded = json.dumps(
                list(tools), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            count = self.count_text(encoded)
        if count < 0:
            raise ValueError("tool token counter returned a negative value")
        return count


@dataclass(frozen=True, slots=True)
class TokenBudget:
    tokenizer_id: str | None = None
    max_memory_tokens: int | None = None
    max_tool_schema_tokens: int | None = None
    max_total_milai_tokens: int | None = None
    max_bytes: int = 16_384
    budget_class: BudgetClass = "STANDARD"
    verified: bool = False

    def __post_init__(self) -> None:
        if self.budget_class not in _BUDGET_TOKENS:
            raise ValueError("unknown token budget class")
        if self.max_bytes < 256:
            raise ValueError("max_bytes must be at least 256")
        for name in (
            "max_memory_tokens",
            "max_tool_schema_tokens",
            "max_total_milai_tokens",
        ):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_memory_tokens is not None and self.max_memory_tokens > MAX_MEMORY_TOKENS:
            raise ValueError("max_memory_tokens cannot exceed 1600")
        if (
            self.max_tool_schema_tokens is not None
            and self.max_tool_schema_tokens > MAX_TOOL_SCHEMA_TOKENS
        ):
            raise ValueError("max_tool_schema_tokens cannot exceed 250")
        if (
            self.max_total_milai_tokens is not None
            and self.max_total_milai_tokens > MAX_TOTAL_MILAI_TOKENS
        ):
            raise ValueError("max_total_milai_tokens cannot exceed 1600")
        if self.verified and (self.tokenizer_id is None or self.max_memory_tokens is None):
            raise ValueError("verified token budget requires tokenizer_id and max_memory_tokens")

    @classmethod
    def for_class(
        cls,
        budget_class: BudgetClass = "STANDARD",
        *,
        counter: TokenCounter | None = None,
        max_bytes: int = 16_384,
        max_tool_schema_tokens: int | None = None,
        max_total_milai_tokens: int | None = None,
    ) -> TokenBudget:
        return cls(
            tokenizer_id=counter.tokenizer_id if counter is not None else None,
            max_memory_tokens=_BUDGET_TOKENS[budget_class] if counter is not None else None,
            max_tool_schema_tokens=(
                max_tool_schema_tokens
                if max_tool_schema_tokens is not None
                else (MAX_TOOL_SCHEMA_TOKENS if counter is not None else None)
            ),
            max_total_milai_tokens=(
                max_total_milai_tokens
                if max_total_milai_tokens is not None
                else (MAX_TOTAL_MILAI_TOKENS if counter is not None else None)
            ),
            max_bytes=max_bytes,
            budget_class=budget_class,
            verified=counter is not None,
        )


def context_binding_digest(
    *,
    constraints: Sequence[str],
    token_budget: TokenBudget,
    token_counter: TokenCounter | None,
    representation_policy_version: str = "governed-context-compiler-v2",
    slot_ttl_seconds: int = DEFAULT_SLOT_TTL_SECONDS,
    context_byte_budget: int | None = None,
) -> str:
    """Bind cache reuse to every host/compiler/token budget input that shapes context."""
    if not 1 <= slot_ttl_seconds <= MAX_SLOT_TTL_SECONDS:
        raise ValueError("slot_ttl_seconds is outside the allowed range")
    return _sha256_json(
        {
            "constraints": list(constraints),
            "tokenizer_id": token_counter.tokenizer_id if token_counter is not None else None,
            "budget": {
                "tokenizer_id": token_budget.tokenizer_id,
                "max_memory_tokens": token_budget.max_memory_tokens,
                "max_tool_schema_tokens": token_budget.max_tool_schema_tokens,
                "max_total_milai_tokens": token_budget.max_total_milai_tokens,
                "max_bytes": token_budget.max_bytes,
                "budget_class": token_budget.budget_class,
                "verified": token_budget.verified,
            },
            "representation_policy_version": representation_policy_version,
            "slot_ttl_seconds": slot_ttl_seconds,
            "context_byte_budget": context_byte_budget,
        }
    )


@dataclass(frozen=True, slots=True)
class ToolTokenUsage:
    tokenizer_id: str | None
    verified: bool
    tool_count: int
    actual_tokens: int | None
    actual_bytes: int


@dataclass(frozen=True, slots=True)
class ProviderTokenUsage:
    """Provider-returned billing counters; never inferred from local text length."""

    provider: str
    model_id: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    request_id: str | None = None
    verified: bool = True

    def __post_init__(self) -> None:
        if not self.provider or not self.model_id:
            raise ValueError("provider and model_id are required")
        for name in ("input_tokens", "cached_input_tokens", "output_tokens"):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens cannot exceed input_tokens")
        if not self.verified:
            raise ValueError("provider usage objects must represent verified provider counters")


@dataclass(frozen=True, slots=True)
class ModelCallResult:
    text: str
    usage: ProviderTokenUsage


def measure_tool_schemas(
    tools: Sequence[Mapping[str, object]], counter: TokenCounter | None = None
) -> ToolTokenUsage:
    encoded = (
        json.dumps(list(tools), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if tools
        else ""
    )
    return ToolTokenUsage(
        tokenizer_id=counter.tokenizer_id if counter is not None else None,
        verified=counter is not None,
        tool_count=len(tools),
        actual_tokens=counter.count_tools(tools) if counter is not None else None,
        actual_bytes=len(encoded.encode("utf-8")),
    )


@dataclass(frozen=True, slots=True)
class RecallRoutingInput:
    current_turn: str
    active_goal: str | None = None
    previous_goal_fingerprint: str | None = None
    known_object_ids: tuple[str, ...] = ()
    requested_scope: Mapping[str, object] = field(default_factory=dict)
    required_authority: Authority = "INFORMATIONAL"
    consistency_floor: Consistency = "EVENTUAL"
    session_snapshot_id: str | None = None
    canonical_position_seen: int | None = None
    issue_revision_digest_seen: str | None = None
    framework_event: FrameworkEvent = "USER_TURN"
    cached_query_fingerprint: str | None = None
    cache_validated: bool = False
    context_binding: str | None = None
    max_limit: int = 3

    def __post_init__(self) -> None:
        if self.framework_event not in {
            "USER_TURN",
            "TOOL_RESULT",
            "MODEL_RETRY",
            "BACKGROUND",
        }:
            raise ValueError("unknown framework event")
        if self.required_authority not in {
            "INFORMATIONAL",
            "ACTION_SAFE",
            "USER_CONFIRMED",
        }:
            raise ValueError("unknown required authority")
        if self.consistency_floor not in {
            "EVENTUAL",
            "READ_YOUR_WRITES",
            "CANONICAL_REQUIRED",
        }:
            raise ValueError("unknown consistency floor")
        if not 1 <= self.max_limit <= 50:
            raise ValueError("max_limit must be between 1 and 50")


@dataclass(frozen=True, slots=True)
class RecallRoutingDecision:
    route: RecallRoute
    reason_code: str
    query: str | None
    limit: int
    allow_vector: bool
    budget_class: BudgetClass
    cache_validation_required: bool
    query_fingerprint: str
    exact_claim_id: str | None = None


class DeterministicRecallRouter:
    """Conservative host-side router. It never decides canonical truth."""

    def __init__(self, *, policy_version: str = "deterministic-recall-router-v1") -> None:
        if not policy_version:
            raise ValueError("router policy_version is required")
        self.policy_version = policy_version

    def decide(self, value: RecallRoutingInput) -> RecallRoutingDecision:
        query = value.current_turn.strip()
        fingerprint = turn_fingerprint(query)
        goal_changed = (
            value.previous_goal_fingerprint is not None
            and value.previous_goal_fingerprint != goal_fingerprint(value.active_goal)
        )
        query_ids = tuple(dict.fromkeys(_UUID_PATTERN.findall(query)))
        if value.known_object_ids:
            return self._decision(
                "L0",
                "KNOWN_CLAIM_ID_EXACT",
                query,
                value,
                fingerprint,
                budget_class="HIGH" if _CONFLICT_PATTERN.search(query) else "LOW",
                exact_claim_id=value.known_object_ids[0],
            )
        if len(query_ids) == 1 and _ISSUE_ID_HINT.search(query):
            return self._decision(
                "L1",
                "OPEN_ISSUE_ID_GOVERNED_SEARCH",
                query,
                value,
                fingerprint,
                budget_class="HIGH" if _CONFLICT_PATTERN.search(query) else "STANDARD",
            )
        if len(query_ids) == 1 and _CLAIM_ID_HINT.search(query):
            return self._decision(
                "L0",
                "QUERY_CLAIM_ID_EXACT",
                query,
                value,
                fingerprint,
                budget_class="HIGH" if _CONFLICT_PATTERN.search(query) else "LOW",
                exact_claim_id=query_ids[0],
            )
        if query_ids:
            return self._decision(
                "L1",
                "AMBIGUOUS_OBJECT_ID_GOVERNED_SEARCH",
                query,
                value,
                fingerprint,
                budget_class="HIGH" if _CONFLICT_PATTERN.search(query) else "STANDARD",
            )
        if _CURRENT_SAFETY_PATTERN.search(query):
            return self._decision(
                "L1",
                "SAFETY_CRITICAL_GOVERNED_SEARCH",
                query,
                value,
                fingerprint,
                budget_class="HIGH" if _CONFLICT_PATTERN.search(query) else "LOW",
            )
        if _EXPLICIT_MEMORY_PATTERN.search(query):
            return self._decision(
                "L1",
                "EXPLICIT_MEMORY_INTENT",
                query,
                value,
                fingerprint,
                budget_class="HIGH" if _CONFLICT_PATTERN.search(query) else "STANDARD",
            )
        if goal_changed:
            return self._decision(
                "L1", "ACTIVE_GOAL_CHANGED", query, value, fingerprint, budget_class="STANDARD"
            )
        if (
            value.cache_validated
            and value.session_snapshot_id is not None
            and value.cached_query_fingerprint == fingerprint
        ):
            return self._decision("CACHE", "VALIDATED_SNAPSHOT_REUSE", None, value, fingerprint)
        if (
            value.framework_event == "MODEL_RETRY"
            and value.session_snapshot_id is not None
            and value.cache_validated
        ):
            return self._decision(
                "NONE", "MODEL_RETRY_REUSES_VALIDATED_SLOT", None, value, fingerprint
            )
        if value.framework_event == "BACKGROUND" and not query:
            return self._decision("NONE", "BACKGROUND_WITHOUT_QUERY", None, value, fingerprint)
        if query and _NO_MEMORY_FULLMATCH.fullmatch(query):
            return self._decision(
                "NONE", "HIGH_CONFIDENCE_NO_MEMORY_TASK", None, value, fingerprint
            )
        return self._decision(
            "L1", "SAFE_DEFAULT_RECALL", query, value, fingerprint, budget_class="STANDARD"
        )

    def cache_key(self, value: RecallRoutingInput) -> str:
        payload = {
            "query": _normalize_text(value.current_turn),
            "active_goal_fingerprint": goal_fingerprint(value.active_goal),
            "known_object_ids": list(dict.fromkeys(value.known_object_ids)),
            "scope": value.requested_scope,
            "required_authority": value.required_authority,
            "consistency_floor": value.consistency_floor,
            "canonical_position": value.canonical_position_seen,
            "issue_revision_digest": value.issue_revision_digest_seen,
            "context_binding": value.context_binding,
            "max_limit": value.max_limit,
            "policy_version": self.policy_version,
        }
        return _sha256_json(payload)

    @staticmethod
    def _decision(
        route: RecallRoute,
        reason: str,
        query: str | None,
        value: RecallRoutingInput,
        fingerprint: str,
        *,
        budget_class: BudgetClass = "LOW",
        exact_claim_id: str | None = None,
    ) -> RecallRoutingDecision:
        return RecallRoutingDecision(
            route=route,
            reason_code=reason,
            query=query,
            limit=min(3, value.max_limit),
            allow_vector=route == "L1",
            budget_class=budget_class,
            cache_validation_required=(
                route == "CACHE" and value.consistency_floor == "CANONICAL_REQUIRED"
            ),
            query_fingerprint=fingerprint,
            exact_claim_id=exact_claim_id,
        )


def turn_fingerprint(value: str) -> str:
    return hashlib.sha256(_normalize_text(value).encode("utf-8")).hexdigest()


def goal_fingerprint(value: str | None) -> str | None:
    return turn_fingerprint(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class MemorySlot:
    slot_id: str
    session_id: str
    snapshot_id: str
    query_fingerprint: str
    content_hash: str
    canonical_position: int | None
    live_issue_revision_digest: str
    live_issue_ids: tuple[str, ...]
    tokenizer_id: str | None
    actual_tokens: int | None
    actual_bytes: int
    object_ids: tuple[str, ...]
    representation_policy_version: str
    budget_class: BudgetClass
    cache_key: str
    ttl_seconds: int
    created_at: datetime

    def to_state(self) -> dict[str, object]:
        """Return a JSON-safe, non-canonical host checkpoint."""
        return {
            "slot_id": self.slot_id,
            "session_id": self.session_id,
            "snapshot_id": self.snapshot_id,
            "query_fingerprint": self.query_fingerprint,
            "content_hash": self.content_hash,
            "canonical_position": self.canonical_position,
            "live_issue_revision_digest": self.live_issue_revision_digest,
            "live_issue_ids": list(self.live_issue_ids),
            "tokenizer_id": self.tokenizer_id,
            "actual_tokens": self.actual_tokens,
            "actual_bytes": self.actual_bytes,
            "object_ids": list(self.object_ids),
            "representation_policy_version": self.representation_policy_version,
            "budget_class": self.budget_class,
            "cache_key": self.cache_key,
            "ttl_seconds": self.ttl_seconds,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_state(cls, value: Mapping[str, object]) -> MemorySlot:
        """Validate an untrusted host checkpoint before process-local reuse."""
        try:
            created_at = datetime.fromisoformat(str(value["created_at"]))
            canonical = value.get("canonical_position")
            actual_tokens = value.get("actual_tokens")
            budget_class = str(value["budget_class"])
            issue_ids = _string_sequence(value.get("live_issue_ids"))
            object_ids = _string_sequence(value.get("object_ids"))
            if created_at.tzinfo is None:
                raise ValueError("created_at must include a timezone")
            if canonical is not None and (
                not isinstance(canonical, int) or isinstance(canonical, bool) or canonical < 0
            ):
                raise ValueError("canonical_position must be non-negative")
            if actual_tokens is not None and (
                not isinstance(actual_tokens, int)
                or isinstance(actual_tokens, bool)
                or actual_tokens < 0
            ):
                raise ValueError("actual_tokens must be non-negative")
            actual_bytes = value["actual_bytes"]
            if (
                not isinstance(actual_bytes, int)
                or isinstance(actual_bytes, bool)
                or actual_bytes < 0
            ):
                raise ValueError("actual_bytes must be non-negative")
            if budget_class not in _BUDGET_TOKENS:
                raise ValueError("unknown token budget class")
            ttl_seconds = value["ttl_seconds"]
            if (
                not isinstance(ttl_seconds, int)
                or isinstance(ttl_seconds, bool)
                or not 1 <= ttl_seconds <= MAX_SLOT_TTL_SECONDS
            ):
                raise ValueError("ttl_seconds is outside the allowed range")
            return cls(
                slot_id=_required_string(value, "slot_id"),
                session_id=_required_string(value, "session_id"),
                snapshot_id=_required_digest(value, "snapshot_id"),
                query_fingerprint=_required_digest(value, "query_fingerprint"),
                content_hash=_required_digest(value, "content_hash"),
                canonical_position=canonical,
                live_issue_revision_digest=_required_digest(value, "live_issue_revision_digest"),
                live_issue_ids=issue_ids,
                tokenizer_id=(
                    str(value["tokenizer_id"]) if value.get("tokenizer_id") is not None else None
                ),
                actual_tokens=actual_tokens,
                actual_bytes=actual_bytes,
                object_ids=object_ids,
                representation_policy_version=semantic_representation_identity(
                    _required_string(value, "representation_policy_version")
                ),
                budget_class=budget_class,
                cache_key=_required_digest(value, "cache_key"),
                ttl_seconds=ttl_seconds,
                created_at=created_at,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid MiLAi memory slot checkpoint") from exc


@dataclass(frozen=True, slots=True)
class ContextDelta:
    status: ContextDeltaStatus
    snapshot_id: str | None
    added_object_ids: tuple[str, ...]
    changed_object_ids: tuple[str, ...]
    removed_object_ids: tuple[str, ...]
    rendered_context: str | None
    reason_code: str


@dataclass(frozen=True, slots=True)
class ContextCompileMetrics:
    tokenizer_id: str | None
    token_budget_verified: bool
    max_tokens: int | None
    actual_tokens: int | None
    max_bytes: int
    actual_bytes: int
    protected_minimum_tokens: int | None
    protected_minimum_bytes: int
    omitted_object_ids: tuple[str, ...]
    representation_tiers: tuple[tuple[str, RepresentationTier], ...]


@dataclass(frozen=True, slots=True)
class ContextCompileRequest:
    recall_envelope: RecallEnvelope
    session_id: str
    query_fingerprint: str
    active_goal: str | None = None
    constraints: tuple[str, ...] = ()
    previous_slot: MemorySlot | None = None
    token_budget: TokenBudget = field(default_factory=TokenBudget)
    token_counter: TokenCounter | None = None
    representation_policy_version: str = GROUPED_COMPACT_V3
    protected_sections: Mapping[str, object] | None = None
    open_issues: tuple[Mapping[str, object], ...] = ()
    safety_required: bool = True
    cache_key: str | None = None
    slot_ttl_seconds: int = DEFAULT_SLOT_TTL_SECONDS

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("session_id is required")
        if not self.query_fingerprint:
            raise ValueError("query_fingerprint is required")
        if not self.representation_policy_version:
            raise ValueError("representation policy version is required")
        object.__setattr__(
            self,
            "representation_policy_version",
            semantic_representation_identity(self.representation_policy_version),
        )
        if not 1 <= self.slot_ttl_seconds <= MAX_SLOT_TTL_SECONDS:
            raise ValueError("slot_ttl_seconds is outside the allowed range")
        if self.cache_key is not None and not _is_digest(self.cache_key):
            raise ValueError("cache_key must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class ContextCompileResult:
    delta: ContextDelta
    slot: MemorySlot | None
    metrics: ContextCompileMetrics


@dataclass(frozen=True, slots=True)
class PreparedAgentContext:
    routing: RecallRoutingDecision
    recall_envelope: RecallEnvelope | None
    compiled: ContextCompileResult


class ContextIntegrityError(ValueError):
    pass


class GovernedContextCompiler:
    """Token-aware deterministic compiler that cannot mutate MiLAi state."""

    def compile(self, request: ContextCompileRequest) -> ContextCompileResult:
        counter = request.token_counter
        budget = request.token_budget
        if counter is not None and budget.tokenizer_id not in {None, counter.tokenizer_id}:
            raise ValueError("token budget and counter tokenizer_id do not match")

        material = _material(request)
        if material.missing_issue_details:
            raise ContextIntegrityError("CONTEXT_ISSUE_DETAILS_REQUIRED")

        if _is_zero_injection(request, material):
            return _empty_result(request, reason="NO_RELEVANT_MEMORY")

        snapshot_id = _snapshot_id(request, material)
        if (
            request.previous_slot is not None
            and request.previous_slot.snapshot_id == snapshot_id
            and (request.cache_key is None or request.previous_slot.cache_key == request.cache_key)
        ):
            return _unchanged_result(request, snapshot_id)

        tiers: list[RepresentationTier] = ["FULL"] * len(material.items)
        included = [True] * len(material.items)
        evidence_count = len(material.evidence)
        minimum_tiers: list[RepresentationTier] = ["ABSTRACT"] if material.items else []
        minimum_included = [True] if material.items else []
        minimum_payload = _payload(
            request,
            material,
            minimum_tiers,
            minimum_included,
            evidence_count=0,
            omitted=tuple(
                _object_id(item, index) for index, item in enumerate(material.items[1:], 1)
            ),
        )
        minimum_rendered, minimum_tokens = _render(
            minimum_payload, budget, counter, protected_minimum_tokens=None
        )
        minimum_bytes = len(minimum_rendered.encode("utf-8"))
        if not _fits(minimum_bytes, minimum_tokens, budget, counter):
            raise ContextBudgetInfeasibleError("CONTEXT_BUDGET_INFEASIBLE")

        omitted: list[str] = []
        while True:
            payload = _payload(
                request,
                material,
                tiers,
                included,
                evidence_count=evidence_count,
                omitted=tuple(omitted),
            )
            rendered, token_count = _render(
                payload,
                budget,
                counter,
                protected_minimum_tokens=minimum_tokens,
            )
            byte_count = len(rendered.encode("utf-8"))
            if _fits(byte_count, token_count, budget, counter):
                break
            if evidence_count > 0:
                evidence_count -= 1
                continue
            changed = _downgrade(tiers, included, material.items, omitted)
            if not changed:
                raise ContextBudgetInfeasibleError("CONTEXT_BUDGET_INFEASIBLE")

        object_ids = tuple(
            _object_id(item, index) for index, item in enumerate(material.items) if included[index]
        ) + tuple(_issue_id(issue, index) for index, issue in enumerate(material.issues))
        content_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        canonical_position = _canonical_position(request.recall_envelope.canonical_position)
        issue_digest = issue_revision_digest(material.issues)
        cache_key = request.cache_key or _sha256_json(
            {
                "snapshot_id": snapshot_id,
                "context_binding": context_binding_digest(
                    constraints=request.constraints,
                    token_budget=request.token_budget,
                    token_counter=request.token_counter,
                    representation_policy_version=request.representation_policy_version,
                    slot_ttl_seconds=request.slot_ttl_seconds,
                ),
            }
        )
        slot = MemorySlot(
            slot_id="milai-memory",
            session_id=request.session_id,
            snapshot_id=snapshot_id,
            query_fingerprint=request.query_fingerprint,
            content_hash=content_hash,
            canonical_position=canonical_position,
            live_issue_revision_digest=issue_digest,
            live_issue_ids=tuple(
                sorted(_issue_id(issue, index) for index, issue in enumerate(material.issues))
            ),
            tokenizer_id=counter.tokenizer_id if counter is not None else None,
            actual_tokens=token_count,
            actual_bytes=byte_count,
            object_ids=object_ids,
            representation_policy_version=request.representation_policy_version,
            budget_class=budget.budget_class,
            cache_key=cache_key,
            ttl_seconds=request.slot_ttl_seconds,
            created_at=datetime.now(UTC),
        )
        previous_ids = set(request.previous_slot.object_ids if request.previous_slot else ())
        current_ids = set(object_ids)
        changed_ids = tuple(sorted(previous_ids & current_ids)) if request.previous_slot else ()
        delta = ContextDelta(
            status="REPLACE",
            snapshot_id=snapshot_id,
            added_object_ids=tuple(sorted(current_ids - previous_ids)),
            changed_object_ids=changed_ids,
            removed_object_ids=tuple(sorted(previous_ids - current_ids)),
            rendered_context=rendered,
            reason_code="SNAPSHOT_CHANGED" if request.previous_slot else "INITIAL_CONTEXT",
        )
        tier_metrics = tuple(
            (_object_id(item, index), tiers[index])
            for index, item in enumerate(material.items)
            if included[index]
        )
        metrics = ContextCompileMetrics(
            tokenizer_id=counter.tokenizer_id if counter is not None else None,
            token_budget_verified=counter is not None and budget.verified,
            max_tokens=budget.max_memory_tokens,
            actual_tokens=token_count,
            max_bytes=budget.max_bytes,
            actual_bytes=byte_count,
            protected_minimum_tokens=minimum_tokens,
            protected_minimum_bytes=minimum_bytes,
            omitted_object_ids=tuple(omitted),
            representation_tiers=tier_metrics,
        )
        return ContextCompileResult(delta=delta, slot=slot, metrics=metrics)

    def without_recall(
        self,
        *,
        previous_slot: MemorySlot | None,
        budget: TokenBudget,
        counter: TokenCounter | None,
        reason_code: str,
        retain_previous: bool,
    ) -> ContextCompileResult:
        if retain_previous and previous_slot is not None:
            delta = ContextDelta(
                status="UNCHANGED",
                snapshot_id=previous_slot.snapshot_id,
                added_object_ids=(),
                changed_object_ids=(),
                removed_object_ids=(),
                rendered_context=None,
                reason_code=reason_code,
            )
            slot = previous_slot
        else:
            delta = ContextDelta(
                status="REMOVE" if previous_slot is not None else "UNCHANGED",
                snapshot_id=None,
                added_object_ids=(),
                changed_object_ids=(),
                removed_object_ids=(previous_slot.object_ids if previous_slot is not None else ()),
                rendered_context=None,
                reason_code=reason_code,
            )
            slot = None
        metrics = ContextCompileMetrics(
            tokenizer_id=counter.tokenizer_id if counter is not None else None,
            token_budget_verified=counter is not None and budget.verified,
            max_tokens=budget.max_memory_tokens,
            actual_tokens=0 if counter is not None else None,
            max_bytes=budget.max_bytes,
            actual_bytes=0,
            protected_minimum_tokens=0 if counter is not None else None,
            protected_minimum_bytes=0,
            omitted_object_ids=(),
            representation_tiers=(),
        )
        return ContextCompileResult(delta=delta, slot=slot, metrics=metrics)


class SessionSlotRegistry:
    """Process-local session state; never a canonical or durable memory store."""

    def __init__(self) -> None:
        self._slots: dict[str, MemorySlot] = {}
        self._lock = RLock()

    def get(self, session_id: str) -> MemorySlot | None:
        with self._lock:
            return self._slots.get(session_id)

    def apply(self, session_id: str, result: ContextCompileResult) -> MemorySlot | None:
        with self._lock:
            if result.delta.status == "REPLACE":
                if result.slot is None:
                    raise ValueError("REPLACE delta requires a slot")
                self._slots[session_id] = result.slot
            elif result.delta.status == "UNCHANGED" and result.slot is not None:
                self._slots[session_id] = result.slot
            elif result.delta.status in {"REMOVE", "INFEASIBLE"}:
                self._slots.pop(session_id, None)
            return self._slots.get(session_id)

    def restore(self, session_id: str, slot: MemorySlot) -> None:
        with self._lock:
            if slot.session_id != session_id:
                raise ValueError("memory slot session_id does not match host session")
            if slot.slot_id != "milai-memory":
                raise ValueError("unknown memory slot id")
            self._slots[session_id] = slot

    def invalidate(self, session_id: str) -> MemorySlot | None:
        with self._lock:
            return self._slots.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._slots.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._slots)


@dataclass(frozen=True, slots=True)
class _Material:
    items: tuple[Mapping[str, object], ...]
    issues: tuple[Mapping[str, object], ...]
    evidence: tuple[Mapping[str, object], ...]
    missing_issue_details: bool


def _material(request: ContextCompileRequest) -> _Material:
    sections = request.protected_sections or {}
    section_items = sections.get("ACTIVE STATE")
    section_issues = sections.get("OPEN ISSUES")
    section_evidence = sections.get("RETRIEVED EVIDENCE")
    items = _mapping_tuple(section_items) or tuple(request.recall_envelope.items)
    raw_issues = _mapping_tuple(section_issues) or request.open_issues
    try:
        issues = tuple(open_issue_semantic_projection(issue) for issue in raw_issues)
    except ValueError as exc:
        raise ContextIntegrityError("CONTEXT_ISSUE_DETAILS_INVALID") from exc
    evidence = _mapping_tuple(section_evidence)
    required_ids = set(request.recall_envelope.issues)
    represented_ids = {
        str(issue.get("issue_id")) for issue in issues if issue.get("issue_id") is not None
    }
    missing = bool(required_ids - represented_ids)
    claim_ids = {
        str(item["claim_id"])
        for item in items
        if isinstance(item.get("claim_id"), str) and item.get("claim_id")
    }
    if claim_ids and any(str(issue["target_claim_id"]) not in claim_ids for issue in issues):
        raise ContextIntegrityError("CONTEXT_ISSUE_TARGET_MISMATCH")
    return _Material(items=items, issues=issues, evidence=evidence, missing_issue_details=missing)


def _mapping_tuple(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _is_zero_injection(request: ContextCompileRequest, material: _Material) -> bool:
    envelope = request.recall_envelope
    if material.items or material.issues:
        return False
    return (
        envelope.status == "ABSTAINED"
        and envelope.abstention_reason in {"NO_CANDIDATE", "NO_RELEVANT_MEMORY"}
        and not envelope.degraded_components
        and not request.safety_required
    )


def _empty_result(request: ContextCompileRequest, *, reason: str) -> ContextCompileResult:
    previous = request.previous_slot
    status: ContextDeltaStatus = "REMOVE" if previous is not None else "UNCHANGED"
    delta = ContextDelta(
        status=status,
        snapshot_id=None,
        added_object_ids=(),
        changed_object_ids=(),
        removed_object_ids=previous.object_ids if previous is not None else (),
        rendered_context=None,
        reason_code=reason,
    )
    metrics = ContextCompileMetrics(
        tokenizer_id=request.token_counter.tokenizer_id if request.token_counter else None,
        token_budget_verified=request.token_counter is not None and request.token_budget.verified,
        max_tokens=request.token_budget.max_memory_tokens,
        actual_tokens=0 if request.token_counter is not None else None,
        max_bytes=request.token_budget.max_bytes,
        actual_bytes=0,
        protected_minimum_tokens=0 if request.token_counter is not None else None,
        protected_minimum_bytes=0,
        omitted_object_ids=(),
        representation_tiers=(),
    )
    return ContextCompileResult(delta=delta, slot=None, metrics=metrics)


def _unchanged_result(request: ContextCompileRequest, snapshot_id: str) -> ContextCompileResult:
    previous = request.previous_slot
    assert previous is not None
    refreshed = (
        previous
        if request.cache_key is None
        else replace(
            previous,
            cache_key=request.cache_key,
            ttl_seconds=request.slot_ttl_seconds,
            created_at=datetime.now(UTC),
        )
    )
    delta = ContextDelta(
        status="UNCHANGED",
        snapshot_id=snapshot_id,
        added_object_ids=(),
        changed_object_ids=(),
        removed_object_ids=(),
        rendered_context=None,
        reason_code="SNAPSHOT_UNCHANGED",
    )
    metrics = ContextCompileMetrics(
        tokenizer_id=refreshed.tokenizer_id,
        token_budget_verified=(request.token_counter is not None and request.token_budget.verified),
        max_tokens=request.token_budget.max_memory_tokens,
        actual_tokens=0 if request.token_counter is not None else None,
        max_bytes=request.token_budget.max_bytes,
        actual_bytes=0,
        protected_minimum_tokens=None,
        protected_minimum_bytes=0,
        omitted_object_ids=(),
        representation_tiers=(),
    )
    return ContextCompileResult(delta=delta, slot=refreshed, metrics=metrics)


def _payload(
    request: ContextCompileRequest,
    material: _Material,
    tiers: Sequence[RepresentationTier],
    included: Sequence[bool],
    *,
    evidence_count: int,
    omitted: tuple[str, ...],
) -> dict[str, object]:
    states = [
        _represent_item(item, tiers[index])
        for index, item in enumerate(material.items)
        if index < len(tiers) and index < len(included) and included[index]
    ]
    payload: dict[str, object] = {
        "status": request.recall_envelope.status,
        "sections": {
            "ACTIVE GOAL": (
                {"text": request.active_goal, "protected": True}
                if request.active_goal is not None
                else None
            ),
            "ACTIVE STATE": states,
            "OPEN ISSUES": [dict(issue) for issue in material.issues],
            "CONSTRAINTS": [{"text": value, "protected": True} for value in request.constraints],
            "RETRIEVED EVIDENCE": [
                _evidence_pointer(value) for value in material.evidence[:evidence_count]
            ],
            # Full trace/provenance identifiers remain in the host sidecar.  The
            # fixed section is retained so the model-facing schema stays stable.
            "TRACE POINTERS": {},
        },
        "consistency": request.recall_envelope.consistency,
    }
    if request.recall_envelope.degraded_components:
        payload["degraded_components"] = request.recall_envelope.degraded_components
    if request.recall_envelope.fallback_used:
        payload["fallback"] = {
            "used": True,
            "reason": request.recall_envelope.fallback_reason,
        }
    if request.recall_envelope.abstention_reason is not None:
        payload["abstention_reason"] = request.recall_envelope.abstention_reason
    if omitted:
        payload["omitted_object_ids"] = list(omitted)
    return payload


def _render(
    payload: dict[str, object],
    budget: TokenBudget,
    counter: TokenCounter | None,
    *,
    protected_minimum_tokens: int | None,
) -> tuple[str, int | None]:
    del budget, protected_minimum_tokens
    rendered = f"{_PREFIX}{_compact_payload(payload)}{_SUFFIX}"
    tokens = counter.count_text(rendered) if counter is not None else None
    return rendered, tokens


_MODEL_HIDDEN_KEYS = frozenset(
    {
        "claim_id",
        "claim_version_id",
        "evidence_id",
        "evidence_ids",
        "issue_id",
        "request_id",
        "session_id",
        "trace_id",
        "target_claim_id",
    }
)


def _model_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _model_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _MODEL_HIDDEN_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_model_value(item) for item in value]
    return value


def _line_value(value: object) -> str:
    if isinstance(value, str):
        return value.replace("\r", " ").replace("\n", " ").strip()
    return json.dumps(
        _model_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _compact_payload(payload: Mapping[str, object]) -> str:
    """Render bounded model data while retaining identifiers in the host-side slot."""
    sections = payload.get("sections")
    section_map = sections if isinstance(sections, Mapping) else {}
    lines = [
        f"STATUS={_line_value(payload.get('status'))}",
        f"CONSISTENCY={_line_value(payload.get('consistency'))}",
    ]
    constraints = section_map.get("CONSTRAINTS")
    if isinstance(constraints, list):
        for constraint in constraints:
            if isinstance(constraint, Mapping) and constraint.get("text") is not None:
                lines.append(f"CONSTRAINT={_line_value(constraint['text'])}")

    raw_states = section_map.get("ACTIVE STATE")
    states = (
        [item for item in raw_states if isinstance(item, Mapping)]
        if isinstance(raw_states, list)
        else []
    )
    groups: dict[tuple[str, str], list[Mapping[str, object]]] = {}
    for state in states:
        authority = str(state.get("authority") or "UNKNOWN")
        epistemic = str(state.get("epistemic_status") or state.get("effective_status") or "UNKNOWN")
        groups.setdefault((authority, epistemic), []).append(state)
    hidden_state_keys = _MODEL_HIDDEN_KEYS | {
        "authority",
        "canonical_commit_seq",
        "effective_status",
        "epistemic_status",
        "open_issue_ids",
        "scope_predicate",
    }
    for (authority, epistemic), items in groups.items():
        lines.append(f"GROUP authority={authority} epistemic={epistemic}")
        for state in items:
            lines.append("ITEM_BEGIN")
            for key in (
                "predicate",
                "valid_time_from",
                "valid_time_to",
                "payload",
                "recovery_tool",
            ):
                if key in state and key not in hidden_state_keys:
                    label = "value" if key == "payload" else key
                    lines.append(f"{label}={_line_value(state[key])}")
            lines.append("ITEM_END")

    raw_issues = section_map.get("OPEN ISSUES")
    issues = (
        [item for item in raw_issues if isinstance(item, Mapping)]
        if isinstance(raw_issues, list)
        else []
    )
    for issue in issues:
        header = " ".join(
            f"{key}={_line_value(issue[key])}"
            for key in ("required_authority", "status", "issue_type", "revision")
            if key in issue
        )
        lines.append("OPEN_ISSUE_BEGIN" + (" " + header if header else ""))
        branches = issue.get("branches")
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, Mapping) and branch.get("relation_type") is not None:
                    lines.append(f"BRANCH={_line_value(branch['relation_type'])}")
        if issue.get("discharge_rule") is not None:
            lines.append(f"DISCHARGE={_line_value(issue['discharge_rule'])}")
        lines.append("OPEN_ISSUE_END")

    for key, label in (
        ("degraded_components", "DEGRADED_COMPONENTS"),
        ("fallback", "FALLBACK"),
        ("abstention_reason", "ABSTENTION_REASON"),
    ):
        if payload.get(key) is not None:
            lines.append(f"{label}={_line_value(payload[key])}")
    omitted = payload.get("omitted_object_ids")
    if isinstance(omitted, list) and omitted:
        lines.append(f"OMITTED_OBJECTS={len(omitted)}")
    return "\n".join(lines)


def _fits(
    byte_count: int,
    token_count: int | None,
    budget: TokenBudget,
    counter: TokenCounter | None,
) -> bool:
    if byte_count > budget.max_bytes:
        return False
    if counter is not None and budget.max_memory_tokens is not None:
        return token_count is not None and token_count <= budget.max_memory_tokens
    return True


def _downgrade(
    tiers: list[RepresentationTier],
    included: list[bool],
    items: Sequence[Mapping[str, object]],
    omitted: list[str],
) -> bool:
    for target, replacement in _TIER_DOWNGRADES:
        for index in range(len(tiers) - 1, -1, -1):
            if included[index] and tiers[index] == target:
                if index == 0 and replacement == "POINTER":
                    continue
                tiers[index] = replacement
                return True
    for index in range(len(tiers) - 1, 0, -1):
        if included[index]:
            included[index] = False
            object_id = _object_id(items[index], index)
            if object_id not in omitted:
                omitted.insert(0, object_id)
            return True
    return False


def _represent_item(item: Mapping[str, object], tier: RepresentationTier) -> dict[str, object]:
    if tier == "FULL":
        return {"tier": tier, **dict(item)}
    keys: tuple[str, ...]
    if tier == "OVERVIEW":
        keys = (
            "claim_version_id",
            "claim_id",
            "subject_id",
            "predicate",
            "claim_type",
            "payload",
            "scope_predicate",
            "valid_time_from",
            "valid_time_to",
            "authority",
            "epistemic_status",
            "freshness",
            "canonical_commit_seq",
            "open_issue_ids",
        )
    elif tier == "ABSTRACT":
        keys = (
            "claim_version_id",
            "claim_id",
            "subject_id",
            "predicate",
            "claim_type",
            "payload",
            "authority",
            "effective_status",
            "canonical_commit_seq",
            "open_issue_ids",
        )
    else:
        keys = ("claim_version_id", "claim_id", "content_hash")
    result = {key: item[key] for key in keys if key in item}
    if tier == "ABSTRACT" and "payload" in result:
        result["payload"] = _abstract_payload(result["payload"])
    result["tier"] = tier
    if tier == "POINTER":
        result["recovery_tool"] = "milai_claim_get"
    return result


def _abstract_payload(value: object, *, max_bytes: int = 384) -> object:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= max_bytes:
        return value
    if isinstance(value, Mapping):
        priority = ("value", "answer", "version", "python", "status", "name", "preference")
        ordered_keys = [key for key in priority if key in value]
        ordered_keys.extend(sorted(str(key) for key in value if str(key) not in ordered_keys))
        result: dict[str, object] = {}
        for key in ordered_keys:
            raw = value.get(key)
            compact: object
            if isinstance(raw, str):
                compact = raw[:240]
            elif isinstance(raw, (int, float, bool)) or raw is None:
                compact = raw
            elif isinstance(raw, (list, tuple)):
                compact = [item for item in raw[:8] if isinstance(item, (str, int, float, bool))]
            else:
                continue
            candidate = {**result, key: compact}
            if (
                len(
                    json.dumps(
                        candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8")
                )
                > max_bytes
            ):
                break
            result = candidate
        if result:
            return result
    return {"excerpt": encoded[: max_bytes - 32]}


def _evidence_pointer(item: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "pointer_id",
        "evidence_id",
        "content_hash",
        "permission_snapshot",
        "retention_state",
    )
    return {key: item[key] for key in keys if key in item}


def _snapshot_id(request: ContextCompileRequest, material: _Material) -> str:
    payload = {
        "query_fingerprint": request.query_fingerprint,
        "active_goal": request.active_goal,
        "constraints": request.constraints,
        "canonical_position": request.recall_envelope.canonical_position,
        "items": material.items,
        "issues": material.issues,
        "evidence": material.evidence,
        "consistency": request.recall_envelope.consistency,
        "degraded": request.recall_envelope.degraded_components,
        "fallback": request.recall_envelope.fallback_reason,
        "abstention": request.recall_envelope.abstention_reason,
        "representation_policy_version": request.representation_policy_version,
        "budget_class": request.token_budget.budget_class,
        "tokenizer_id": request.token_counter.tokenizer_id if request.token_counter else None,
    }
    return _sha256_json(payload)


def _object_id(item: Mapping[str, object], index: int) -> str:
    for key in ("claim_version_id", "claim_id", "issue_id", "evidence_id"):
        if item.get(key) is not None:
            return str(item[key])
    return f"unidentified-item:{index}"


def _issue_id(item: Mapping[str, object], index: int) -> str:
    return str(item.get("issue_id", f"unidentified-issue:{index}"))


def open_issue_semantic_projection(issue: Mapping[str, object]) -> dict[str, object]:
    """Validate and strip per-request/transition metadata from a live OpenIssue."""
    issue_id = issue.get("issue_id")
    target_claim_id = issue.get("target_claim_id")
    issue_type = issue.get("issue_type")
    status = issue.get("status")
    revision = issue.get("revision")
    scope = issue.get("scope_predicate")
    discharge = issue.get("discharge_rule")
    authority = issue.get("required_authority")
    branches = issue.get("branches")
    if not isinstance(issue_id, str) or not issue_id:
        raise ValueError("issue_id must be a non-empty string")
    if not isinstance(target_claim_id, str) or not target_claim_id:
        raise ValueError("target_claim_id must be a non-empty string")
    if issue_type not in _ISSUE_TYPES:
        raise ValueError("unknown issue_type")
    if status not in _LIVE_ISSUE_STATUSES:
        raise ValueError("OpenIssue is not live")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("revision must be a positive integer")
    if not isinstance(scope, dict):
        raise ValueError("scope_predicate must be an object")
    if not isinstance(discharge, dict) or not discharge:
        raise ValueError("discharge_rule must be a non-empty object")
    if authority not in _AUTHORITIES:
        raise ValueError("unknown required_authority")
    if not isinstance(branches, list) or not branches:
        raise ValueError("branches must be a non-empty list")

    normalized_branches: list[dict[str, str]] = []
    branch_keys: set[tuple[str, str]] = set()
    branch_types: set[str] = set()
    for branch in branches:
        if not isinstance(branch, dict):
            raise ValueError("branch must be an object")
        relation_type = branch.get("relation_type")
        evidence_id = branch.get("evidence_id")
        if relation_type not in _ISSUE_BRANCH_TYPES:
            raise ValueError("unknown issue branch relation_type")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ValueError("branch evidence_id must be a non-empty string")
        branch_key = (str(relation_type), evidence_id)
        if branch_key in branch_keys:
            raise ValueError("duplicate issue branch")
        branch_keys.add(branch_key)
        branch_types.add(str(relation_type))
        normalized_branches.append(
            {"relation_type": str(relation_type), "evidence_id": evidence_id}
        )
    if issue_type == "CONFLICT" and not {
        "SUPPORT_BRANCH",
        "CONTRADICT_BRANCH",
    }.issubset(branch_types):
        raise ValueError("CONFLICT requires support and contradict branches")

    normalized_branches.sort(key=lambda item: (item["relation_type"], item["evidence_id"]))
    result: dict[str, object] = {
        "issue_id": issue_id,
        "target_claim_id": target_claim_id,
        "issue_type": issue_type,
        "status": status,
        "revision": revision,
        "scope_predicate": dict(scope),
        "discharge_rule": dict(discharge),
        "required_authority": authority,
        "branches": normalized_branches,
    }
    for metadata_key in (
        "created_from_proposal_id",
        "resolved_by_decision_id",
        "resolved_at",
        "created_at",
    ):
        if metadata_key in issue:
            result[metadata_key] = issue[metadata_key]
    return result


def issue_revision_digest(issues: Sequence[Mapping[str, object]]) -> str:
    ordered = sorted(
        (open_issue_semantic_projection(issue) for issue in issues),
        key=lambda item: str(item["issue_id"]),
    )
    return _sha256_json(ordered)


def memory_slot_cache_valid(
    slot: MemorySlot,
    *,
    canonical_snapshot: int,
    open_issues: Sequence[Mapping[str, object]],
    now: datetime | None = None,
) -> bool:
    """Validate a process-local cache against canonical position and relevant live issues."""
    checked_at = now or datetime.now(UTC)
    created_at = slot.created_at.astimezone(UTC)
    age_seconds = (checked_at.astimezone(UTC) - created_at).total_seconds()
    if age_seconds < 0 or age_seconds > slot.ttl_seconds:
        return False
    if slot.canonical_position is None or canonical_snapshot != slot.canonical_position:
        return False
    required = set(slot.live_issue_ids)
    relevant = [issue for issue in open_issues if str(issue.get("issue_id")) in required]
    if {str(issue.get("issue_id")) for issue in relevant} != required:
        return False
    try:
        return issue_revision_digest(relevant) == slot.live_issue_revision_digest
    except ValueError:
        return False


def _required_string(value: Mapping[str, object], key: str) -> str:
    result = value[key]
    if not isinstance(result, str) or not result:
        raise ValueError(f"{key} must be a non-empty string")
    return result


def _required_digest(value: Mapping[str, object], key: str) -> str:
    result = _required_string(value, key)
    if not _is_digest(result):
        raise ValueError(f"{key} must be a lowercase SHA-256 digest")
    return result


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError("slot identifier sequences must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError("slot identifier sequences must be unique")
    return tuple(value)


def _canonical_position(value: Mapping[str, object] | None) -> int | None:
    if value is None:
        return None
    position = value.get("canonical_outbox_sequence")
    return position if isinstance(position, int) and not isinstance(position, bool) else None


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
