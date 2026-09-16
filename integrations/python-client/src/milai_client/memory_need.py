from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from milai_client.task_state import CanonicalStateKey

MemoryIntent = Literal["NONE", "CURRENT_STATE", "HISTORY", "CONFLICT", "EXPLANATION"]
TemporalNeed = Literal["CURRENT", "HISTORICAL", "AS_OF"]
EvidenceNeed = Literal["NONE", "SUPPORT_POINTERS", "RAW_EVIDENCE"]
NeedRoute = Literal["NONE", "L0", "L1"]
QueryIntentLevel = Literal["NOT_NEEDED", "POSSIBLE", "REQUIRED"]
MemoryRequirement = Literal["NONE", "EXACT", "SEARCH"]
InvocationMode = Literal["EXPLICIT_READ", "PREFETCH_AUTO"]

_STATE_KEY_ALIAS_FAMILIES = (
    (
        "orchid-release",
        "release.target",
        "PROJECT_STATE",
        ("current release target", "当前发布目标"),
    ),
    (
        "orchid-release",
        "release.database",
        "PROJECT_CONFIG",
        (
            "current release database",
            "current release config",
            "当前发布数据库",
            "当前发布配置",
        ),
    ),
    (
        "orchid-release",
        "release.decision",
        "PROJECT_DECISION",
        ("current governed release decision", "当前受治理的发布决定"),
    ),
)


class StateKeyAliasAmbiguousError(ValueError):
    """A normalized exact alias is owned by multiple live StateKeys."""

    code = "STATE_KEY_ALIAS_AMBIGUOUS"

    def __init__(self) -> None:
        super().__init__(self.code)


_TOKEN = re.compile(r"[a-z0-9]+")
_NO_MEMORY = re.compile(
    r"^(?:hello|hi|good\s+(?:morning|afternoon|evening))\b|"
    r"\b(?:compute|calculate|what is)\s+\d+\s*(?:plus|minus|times|[+*\-/])\s*\d+",
    re.IGNORECASE,
)
_RETRY = re.compile(r"\b(?:retry|repeat|again|preceding|previous)\b", re.IGNORECASE)
_EXPLANATION = re.compile(r"\b(?:why|explain|provenance|both branches|history)\b", re.IGNORECASE)
_CONFLICT = re.compile(
    r"\b(?:conflict|open issue|blocked|contradict|both branches|governed decision)\b",
    re.IGNORECASE,
)
_CURRENT = re.compile(
    r"\b(?:current|currently|latest|now|configured|owner|target|deadline|window|"
    r"decision|database|queue|build|revoked|setting|state|proceed)\b",
    re.IGNORECASE,
)
_ACTION = re.compile(r"\b(?:may|can|proceed|safe|allowed|authorize)\b", re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "be",
        "by",
        "for",
        "from",
        "goes",
        "is",
        "it",
        "of",
        "only",
        "please",
        "that",
        "the",
        "this",
        "to",
        "under",
        "what",
        "which",
        "with",
    }
)

_QUERY_MEMORY_REQUIRED = re.compile(
    r"\b(?:remember|recall|memory|previous(?:ly)?|earlier|history|historical|"
    r"current|currently|latest|last time|what did i|what have i|my preference|"
    r"open issue|conflict|contradict|why did .+ change)\b|"
    r"(?:记得|记忆|之前|此前|历史|当前|现在|最新|上次|我的偏好|冲突|为什么.*(?:改变|变化))",
    re.IGNORECASE,
)
_QUERY_EXACT_STATE = re.compile(
    r"\b(?:current|currently|latest|configured|setting|status|state|target|owner|"
    r"deadline|database|preference)\b|(?:当前|现在|最新|配置|设置|状态|目标|负责人|截止|数据库|偏好)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class QueryOnlyIntentShadow:
    """Payload-free M0 shadow result; it never selects the production route."""

    intent: QueryIntentLevel
    requirement: MemoryRequirement
    reason_code: str
    interpreter_version: str = "query-only-shadow-v1"


class DeterministicQueryOnlyIntentShadow:
    """Classify Memory reachability from query alone without Task identity.

    This is M0 observability, not an authorization or routing decision.  M1
    moves the owning interpretation into the Runtime kernel.
    """

    VERSION = "query-only-shadow-v1"

    def interpret(
        self,
        query: str,
        *,
        invocation_mode: InvocationMode = "PREFETCH_AUTO",
    ) -> QueryOnlyIntentShadow:
        text = unicodedata.normalize("NFKC", query).strip()
        if not text or _NO_MEMORY.search(text):
            if invocation_mode == "EXPLICIT_READ" and text:
                return QueryOnlyIntentShadow(
                    "POSSIBLE", "SEARCH", "EXPLICIT_READ_REQUIREMENT_FLOOR"
                )
            return QueryOnlyIntentShadow("NOT_NEEDED", "NONE", "QUERY_MEMORY_NOT_NEEDED")
        if _QUERY_MEMORY_REQUIRED.search(text):
            requirement: MemoryRequirement = (
                "EXACT" if _QUERY_EXACT_STATE.search(text) else "SEARCH"
            )
            return QueryOnlyIntentShadow(
                "REQUIRED", requirement, f"QUERY_MEMORY_{requirement}_SIGNAL"
            )
        return QueryOnlyIntentShadow(
            "POSSIBLE",
            "SEARCH",
            (
                "EXPLICIT_READ_REQUIREMENT_FLOOR"
                if invocation_mode == "EXPLICIT_READ"
                else "QUERY_MEMORY_BOUNDED_PROBE"
            ),
        )


@dataclass(frozen=True, slots=True)
class StateKeyRef:
    scope: dict[str, Any]
    subject: str
    predicate: str
    claim_type: str
    claim_id: str | None = None
    relevant_open_issue_ids: tuple[str, ...] = ()
    canonical_position_seen: int | None = None
    version: str = "state-key-ref-v1"

    def __post_init__(self) -> None:
        if not all(
            value.strip() for value in (self.version, self.subject, self.predicate, self.claim_type)
        ):
            raise ValueError("state key reference fields are required")
        if self.canonical_position_seen is not None and self.canonical_position_seen < 0:
            raise ValueError("canonical_position_seen must be non-negative")

    def to_api(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "scope": self.scope,
            "subject": self.subject,
            "predicate": self.predicate,
            "claim_type": self.claim_type,
            "claim_id": self.claim_id,
            "relevant_open_issue_ids": list(self.relevant_open_issue_ids),
            "canonical_position_seen": self.canonical_position_seen,
        }


@dataclass(frozen=True, slots=True)
class MemoryNeedSignature:
    scope: dict[str, Any]
    required_authority: str
    consistency_floor: str
    claim_ids: tuple[str, ...]
    state_keys: tuple[StateKeyRef, ...]
    open_issue_ids: tuple[str, ...]
    temporal_need: TemporalNeed
    evidence_need: EvidenceNeed
    intent_class: MemoryIntent
    version: str = "memory-need-v1"

    @property
    def need_signature_id(self) -> str:
        return "need:" + hashlib.sha256(_canonical(self.to_api())).hexdigest()

    def to_api(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "scope": self.scope,
            "required_authority": self.required_authority,
            "consistency_floor": self.consistency_floor,
            "claim_ids": list(self.claim_ids),
            "state_keys": [key.to_api() for key in self.state_keys],
            "open_issue_ids": list(self.open_issue_ids),
            "temporal_need": self.temporal_need,
            "evidence_need": self.evidence_need,
            "intent_class": self.intent_class,
        }


@dataclass(frozen=True, slots=True)
class MemoryNeedResolution:
    signature: MemoryNeedSignature
    requested_route: NeedRoute
    state_key_ref: StateKeyRef | None
    reason_code: str
    resolver_embedding_calls: int = 0
    resolver_retrieval_calls: int = 0
    resolver_model_calls: int = 0


class DeterministicMemoryNeedResolver:
    """Resolve typed memory needs from Host state without retrieval or learned inference."""

    def resolve(
        self,
        query: str,
        *,
        scope: dict[str, Any],
        required_authority: str,
        consistency_floor: str,
        known_state_keys: tuple[CanonicalStateKey, ...] = (),
        known_claim_ids: tuple[str, ...] = (),
        open_issue_ids: tuple[str, ...] = (),
        canonical_position_seen: int | None = None,
        previous: MemoryNeedResolution | None = None,
    ) -> MemoryNeedResolution:
        text = query.strip()
        exact_key = _exact_alias_state_key(text, known_state_keys)
        if exact_key is not None:
            exact_ref = StateKeyRef(
                scope=scope,
                subject=exact_key.subject,
                predicate=exact_key.predicate,
                claim_type=exact_key.claim_type,
                relevant_open_issue_ids=open_issue_ids,
                canonical_position_seen=canonical_position_seen,
            )
            signature = MemoryNeedSignature(
                scope=scope,
                required_authority=required_authority,
                consistency_floor=consistency_floor,
                claim_ids=(),
                state_keys=(exact_ref,),
                open_issue_ids=open_issue_ids,
                temporal_need="CURRENT",
                evidence_need="SUPPORT_POINTERS",
                intent_class="CURRENT_STATE",
            )
            return MemoryNeedResolution(
                signature,
                "L0",
                exact_ref,
                "EXACT_FROZEN_STATE_KEY_ALIAS",
            )
        if previous is not None and _RETRY.search(text):
            prior = previous.signature
            signature = MemoryNeedSignature(
                scope=scope,
                required_authority=required_authority,
                consistency_floor=consistency_floor,
                claim_ids=prior.claim_ids,
                state_keys=tuple(
                    StateKeyRef(
                        scope=scope,
                        subject=key.subject,
                        predicate=key.predicate,
                        claim_type=key.claim_type,
                        claim_id=key.claim_id,
                        relevant_open_issue_ids=key.relevant_open_issue_ids,
                        canonical_position_seen=canonical_position_seen,
                    )
                    for key in prior.state_keys
                ),
                open_issue_ids=prior.open_issue_ids,
                temporal_need=prior.temporal_need,
                evidence_need=prior.evidence_need,
                intent_class=prior.intent_class,
            )
            prior_ref = signature.state_keys[0] if signature.state_keys else None
            return MemoryNeedResolution(
                signature,
                "L0" if prior_ref is not None or signature.claim_ids else "L1",
                prior_ref,
                "REUSE_PREVIOUS_TYPED_NEED",
            )
        if not text or _NO_MEMORY.search(text):
            signature = self._signature(
                scope, required_authority, consistency_floor, "NONE", "CURRENT", "NONE"
            )
            return MemoryNeedResolution(signature, "NONE", None, "NO_MEMORY_DEPENDENCY")

        intent: MemoryIntent
        temporal: TemporalNeed = "CURRENT"
        evidence: EvidenceNeed = "SUPPORT_POINTERS"
        if _EXPLANATION.search(text):
            intent = "EXPLANATION" if "explain" in text.lower() else "HISTORY"
            temporal = "HISTORICAL"
        elif _CONFLICT.search(text):
            intent = "CONFLICT"
        elif _CURRENT.search(text):
            intent = "CURRENT_STATE"
        else:
            signature = self._signature(
                scope, required_authority, consistency_floor, "NONE", "CURRENT", "NONE"
            )
            return MemoryNeedResolution(signature, "NONE", None, "NO_TYPED_MEMORY_INTENT")

        selected = _select_state_key(
            text, known_state_keys, prefer_decision=bool(_ACTION.search(text))
        )
        ref = (
            StateKeyRef(
                scope=scope,
                subject=selected.subject,
                predicate=selected.predicate,
                claim_type=selected.claim_type,
                relevant_open_issue_ids=open_issue_ids,
                canonical_position_seen=canonical_position_seen,
            )
            if selected is not None
            else None
        )
        claims = known_claim_ids[:1] if ref is None and len(known_claim_ids) == 1 else ()
        signature = MemoryNeedSignature(
            scope=scope,
            required_authority=required_authority,
            consistency_floor=consistency_floor,
            claim_ids=claims,
            state_keys=(ref,) if ref is not None else (),
            open_issue_ids=open_issue_ids,
            temporal_need=temporal,
            evidence_need=evidence,
            intent_class=intent,
        )
        exact = intent in {"CURRENT_STATE", "CONFLICT"} and (ref is not None or bool(claims))
        return MemoryNeedResolution(
            signature,
            "L0" if exact else "L1",
            ref,
            "EXACT_CANONICAL_STATE_KEY" if exact else "PROGRESSIVE_RECALL_REQUIRED",
        )

    @staticmethod
    def _signature(
        scope: dict[str, Any],
        authority: str,
        consistency: str,
        intent: MemoryIntent,
        temporal: TemporalNeed,
        evidence: EvidenceNeed,
    ) -> MemoryNeedSignature:
        return MemoryNeedSignature(
            scope=scope,
            required_authority=authority,
            consistency_floor=consistency,
            claim_ids=(),
            state_keys=(),
            open_issue_ids=(),
            temporal_need=temporal,
            evidence_need=evidence,
            intent_class=intent,
        )


def _select_state_key(
    query: str,
    keys: tuple[CanonicalStateKey, ...],
    *,
    prefer_decision: bool,
) -> CanonicalStateKey | None:
    query_terms = _terms(query)
    ranked: list[tuple[int, str, CanonicalStateKey]] = []
    for key in keys:
        predicate_terms = _terms(key.predicate)
        subject_terms = _terms(key.subject)
        type_terms = _terms(key.claim_type)
        score = 6 * len(query_terms & predicate_terms)
        score += 2 * len(query_terms & subject_terms)
        score += len(query_terms & type_terms)
        if prefer_decision and "decision" in predicate_terms:
            score += 8
        ranked.append((score, json.dumps(key.canonical(), sort_keys=True), key))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[0][2] if ranked and ranked[0][0] > 0 else None


def _exact_alias_state_key(
    query: str, keys: tuple[CanonicalStateKey, ...]
) -> CanonicalStateKey | None:
    normalized = _normalize_alias(query)
    owners: list[CanonicalStateKey] = []
    for subject, predicate, claim_type, aliases in _STATE_KEY_ALIAS_FAMILIES:
        if not any(
            _normalized_alias_occurs(normalized, _normalize_alias(alias)) for alias in aliases
        ):
            continue
        for key in keys:
            if (
                key.subject == subject
                and key.predicate == predicate
                and key.claim_type == claim_type
                and key not in owners
            ):
                owners.append(key)
    if len(owners) > 1:
        raise StateKeyAliasAmbiguousError
    return owners[0] if owners else None


def _normalized_alias_occurs(query: str, alias: str) -> bool:
    if not alias:
        return False
    prefix = r"(?<![a-z0-9])" if alias[0].isascii() and alias[0].isalnum() else ""
    suffix = r"(?![a-z0-9])" if alias[-1].isascii() and alias[-1].isalnum() else ""
    return re.search(prefix + re.escape(alias) + suffix, query) is not None


def _normalize_alias(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _terms(value: str) -> set[str]:
    return {
        term for term in _TOKEN.findall(value.lower().replace("_", "-")) if term not in _STOPWORDS
    }


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
