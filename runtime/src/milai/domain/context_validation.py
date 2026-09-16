from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from milai.domain.context_preparation import MemoryNeedSignature
from milai.domain.retrieval import RetrievalAuthority, RetrievalConsistency


class ClaimHeadCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: UUID
    claim_version_id: UUID


class StateKeyHeadCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scope: dict[str, JsonValue] = Field(default_factory=dict)
    subject: str = Field(min_length=1, max_length=512)
    predicate: str = Field(min_length=1, max_length=255)
    claim_type: str = Field(min_length=1, max_length=255)
    claim_id: UUID
    claim_version_id: UUID


class OpenIssueRevisionCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: UUID
    revision: int = Field(ge=0)


class DependencyFrontier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["GLOBAL_CANONICAL_POSITION"] = "GLOBAL_CANONICAL_POSITION"
    canonical_position: int = Field(ge=0)


class MemorySlotCoverage(BaseModel):
    """Signed, broker-bound facts a prepared context slot can actually satisfy."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    version: Literal["memory-slot-coverage-v1"] = "memory-slot-coverage-v1"
    scope: dict[str, JsonValue] = Field(default_factory=dict)
    authority_supported: RetrievalAuthority
    consistency_supported: RetrievalConsistency
    claim_ids_and_head_versions: list[ClaimHeadCoverage] = Field(
        default_factory=list, max_length=256
    )
    state_keys_and_head_versions: list[StateKeyHeadCoverage] = Field(
        default_factory=list, max_length=64
    )
    open_issue_ids_and_revisions: list[OpenIssueRevisionCoverage] = Field(
        default_factory=list, max_length=256
    )
    temporal_coverage: Literal["CURRENT", "HISTORICAL", "AS_OF"]
    evidence_depth: Literal["NONE", "SUPPORT_POINTERS", "RAW_EVIDENCE"]
    policy_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependency_frontier: DependencyFrontier

    @property
    def coverage_id(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return "coverage:" + hashlib.sha256(encoded).hexdigest()


def need_covered(
    need: MemoryNeedSignature | None,
    coverage: MemorySlotCoverage,
    *,
    expected_policy_identity: str,
) -> tuple[bool, str | None]:
    """Apply the conservative deterministic NeedCovered predicate."""
    if need is None:
        return False, "CACHE_NEED_UNTYPED"
    if coverage.policy_identity != expected_policy_identity:
        return False, "CACHE_POLICY_MISMATCH"
    if need.scope != coverage.scope:
        return False, "CACHE_SCOPE_MISMATCH"
    if need.required_authority != coverage.authority_supported:
        return False, "CACHE_AUTHORITY_UNCOVERED"
    if need.consistency_floor != coverage.consistency_supported:
        return False, "CACHE_CONSISTENCY_UNCOVERED"
    if need.temporal_need != coverage.temporal_coverage:
        return False, "CACHE_TEMPORAL_NEED_UNCOVERED"
    evidence_rank = {"NONE": 0, "SUPPORT_POINTERS": 1, "RAW_EVIDENCE": 2}
    if evidence_rank[coverage.evidence_depth] < evidence_rank[need.evidence_need]:
        return False, "CACHE_EVIDENCE_DEPTH_UNCOVERED"

    covered_claims = {
        str(item.claim_id): str(item.claim_version_id)
        for item in coverage.claim_ids_and_head_versions
    }
    if any(str(claim_id) not in covered_claims for claim_id in need.claim_ids):
        return False, "CACHE_CLAIM_UNCOVERED"

    covered_keys = [
        (
            _canonical(item.scope),
            item.subject,
            item.predicate,
            item.claim_type,
            str(item.claim_id),
        )
        for item in coverage.state_keys_and_head_versions
    ]
    for key in need.state_keys:
        key_prefix = (_canonical(key.scope), key.subject, key.predicate, key.claim_type)
        if not any(
            covered[:4] == key_prefix
            and (key.claim_id is None or covered[4] == str(key.claim_id))
            for covered in covered_keys
        ):
            return False, "CACHE_STATE_KEY_UNCOVERED"

    covered_issues = {
        str(item.issue_id): item.revision
        for item in coverage.open_issue_ids_and_revisions
    }
    if any(str(issue_id) not in covered_issues for issue_id in need.open_issue_ids):
        return False, "CACHE_OPEN_ISSUE_UNCOVERED"
    if (
        need.intent_class != "NONE"
        and not need.claim_ids
        and not need.state_keys
        and not need.open_issue_ids
    ):
        return False, "CACHE_NEED_UNDER_SPECIFIED"
    return True, None


class ContextValidationTokenError(ValueError):
    """A context validation token is malformed, stale, forged, or mis-bound."""


@dataclass(frozen=True, slots=True)
class ContextValidationState:
    tenant_id: UUID
    principal_profile: str
    binding_digest: str
    canonical_position: int
    issue_revision_digest: str
    issue_ids: tuple[str, ...]
    slot_coverage: MemorySlotCoverage
    capsule_id: str
    context_hash: str
    prepare_calls: int
    full_recall_calls: int
    delta_refreshes: int
    validation_calls: int
    issued_at: datetime
    expires_at: datetime


class ContextValidationTokenCodec:
    VERSION = 2

    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("context validation secret must contain at least 32 characters")
        self._key = hashlib.sha256(
            b"milai-context-validation-token-v1\x00" + secret.encode("utf-8")
        ).digest()

    def issue(self, state: ContextValidationState) -> str:
        self._validate_state(state)
        payload = json.dumps(
            {
                "binding_digest": state.binding_digest,
                "canonical_position": state.canonical_position,
                "capsule_id": state.capsule_id,
                "context_hash": state.context_hash,
                "delta_refreshes": state.delta_refreshes,
                "expires_at": state.expires_at.astimezone(UTC).isoformat(),
                "full_recall_calls": state.full_recall_calls,
                "issue_ids": list(state.issue_ids),
                "issue_revision_digest": state.issue_revision_digest,
                "issued_at": state.issued_at.astimezone(UTC).isoformat(),
                "prepare_calls": state.prepare_calls,
                "principal_profile": state.principal_profile,
                "slot_coverage": state.slot_coverage.model_dump(mode="json"),
                "tenant_id": str(state.tenant_id),
                "validation_calls": state.validation_calls,
                "version": self.VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        encoded = _encode(payload)
        signature = _encode(hmac.digest(self._key, encoded.encode("ascii"), "sha256"))
        return f"{encoded}.{signature}"

    def decode(
        self,
        token: str,
        *,
        expected_tenant_id: UUID,
        expected_profile: str,
        expected_binding_digest: str,
        now: datetime | None = None,
    ) -> ContextValidationState:
        encoded, separator, supplied_signature = token.partition(".")
        if separator != "." or not encoded or not supplied_signature or len(token) > 8_192:
            raise ContextValidationTokenError("invalid context validation token")
        expected_signature = _encode(hmac.digest(self._key, encoded.encode("ascii"), "sha256"))
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ContextValidationTokenError("invalid context validation token")
        try:
            value = json.loads(_decode(encoded))
            if not isinstance(value, dict) or value.get("version") != self.VERSION:
                raise ValueError
            state = ContextValidationState(
                tenant_id=UUID(str(value["tenant_id"])),
                principal_profile=str(value["principal_profile"]),
                binding_digest=str(value["binding_digest"]),
                canonical_position=_counter(value, "canonical_position"),
                issue_revision_digest=str(value["issue_revision_digest"]),
                issue_ids=_string_tuple(value.get("issue_ids")),
                slot_coverage=MemorySlotCoverage.model_validate(value["slot_coverage"]),
                capsule_id=str(value["capsule_id"]),
                context_hash=str(value["context_hash"]),
                prepare_calls=_counter(value, "prepare_calls"),
                full_recall_calls=_counter(value, "full_recall_calls"),
                delta_refreshes=_counter(value, "delta_refreshes"),
                validation_calls=_counter(value, "validation_calls"),
                issued_at=datetime.fromisoformat(str(value["issued_at"])),
                expires_at=datetime.fromisoformat(str(value["expires_at"])),
            )
            self._validate_state(state)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ContextValidationTokenError("invalid context validation token") from exc
        if state.tenant_id != expected_tenant_id:
            raise ContextValidationTokenError("context validation token tenant mismatch")
        if state.principal_profile != expected_profile:
            raise ContextValidationTokenError("context validation token profile mismatch")
        if not hmac.compare_digest(state.binding_digest, expected_binding_digest):
            raise ContextValidationTokenError("context validation token binding mismatch")
        checked_at = (now or datetime.now(UTC)).astimezone(UTC)
        issued_at = state.issued_at.astimezone(UTC)
        expires_at = state.expires_at.astimezone(UTC)
        if checked_at < issued_at or checked_at >= expires_at:
            raise ContextValidationTokenError("context validation token expired")
        return state

    @staticmethod
    def _validate_state(state: ContextValidationState) -> None:
        if state.issued_at.tzinfo is None or state.expires_at.tzinfo is None:
            raise ValueError("context validation timestamps must be timezone-aware")
        if state.expires_at <= state.issued_at:
            raise ValueError("context validation expiry must follow issuance")
        if not state.principal_profile or not state.capsule_id:
            raise ValueError("context validation identity fields are required")
        for digest in (
            state.binding_digest,
            state.issue_revision_digest,
            state.context_hash,
        ):
            if len(digest) != 64 or any(value not in "0123456789abcdef" for value in digest):
                raise ValueError("context validation digests must be lowercase SHA-256")
        for count in (
            state.canonical_position,
            state.prepare_calls,
            state.full_recall_calls,
            state.delta_refreshes,
            state.validation_calls,
        ):
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("context validation counters must be non-negative")
        if (
            state.slot_coverage.dependency_frontier.canonical_position
            != state.canonical_position
        ):
            raise ValueError("slot coverage dependency frontier does not match token state")


def _counter(value: dict[str, object], key: str) -> int:
    result = value[key]
    if isinstance(result, bool) or not isinstance(result, int) or result < 0:
        raise ValueError
    return result


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError
    result = tuple(sorted(set(value)))
    if len(result) > 64:
        raise ValueError
    return result


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
