from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Literal, Protocol

_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\bpostgres(?:ql)?://[^\s]+"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret)\s*[=:]\s*[^\s,;]{12,}"),
)


class SubmitterLane(Protocol):
    def capture_evidence(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def create_proposal(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class MemoryWriteIntent:
    """Host-owned handoff; it is neither model output nor a canonical object."""

    intent_id: str
    task_epoch: str
    source_type: str
    source_ref: str
    subject_id: str
    observed_at: str
    content: str = field(repr=False)
    permission_snapshot: Mapping[str, Any] = field(default_factory=dict)
    data_classification: Literal["SYNTHETIC", "DEIDENTIFIED", "PERSONAL"] = "SYNTHETIC"
    retention_state: Literal["READABLE", "UNREADABLE", "EXPIRED", "LEGAL_HOLD"] = "READABLE"
    proposal: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        values = (
            self.intent_id,
            self.task_epoch,
            self.source_type,
            self.source_ref,
            self.subject_id,
            self.observed_at,
            self.content,
        )
        if not all(value.strip() for value in values):
            raise ValueError("MemoryWriteIntent fields must be non-empty")
        if len(self.intent_id) > 96 or len(self.task_epoch) > 256:
            raise ValueError("MemoryWriteIntent identity is too long")
        if len(self.content.encode("utf-8")) > 32_768:
            raise ValueError("MemoryWriteIntent content exceeds the host admission boundary")

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "intent_id": self.intent_id,
                    "task_epoch": self.task_epoch,
                    "source_type": self.source_type,
                    "source_ref": self.source_ref,
                    "subject_id": self.subject_id,
                    "observed_at": self.observed_at,
                    "content": self.content,
                    "permission_snapshot": dict(self.permission_snapshot),
                    "data_classification": self.data_classification,
                    "retention_state": self.retention_state,
                    "proposal": dict(self.proposal) if self.proposal is not None else None,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class MemoryWriteReceipt:
    intent_id: str
    intent_digest: str
    evidence_id: str
    proposal_id: str | None
    redacted: bool
    deduplicated: bool
    canonical_changed: Literal[False] = False
    review_required: Literal[True] = True


class MemoryWriteHandoff:
    """Admission, deduplication and explicit submitter-lane execution for task settlement."""

    def __init__(self, submitter: SubmitterLane, *, profile_id: str = "submitter") -> None:
        if profile_id != "submitter":
            raise PermissionError("MemoryWriteHandoff requires an independent submitter lane")
        self._submitter = submitter
        self._receipts: dict[str, MemoryWriteReceipt] = {}
        self._lock = RLock()

    def handoff(
        self,
        intent: MemoryWriteIntent,
        *,
        confirmation: Literal["HANDOFF"],
    ) -> MemoryWriteReceipt:
        if confirmation != "HANDOFF":
            raise PermissionError("literal HANDOFF confirmation is required")
        with self._lock:
            previous = self._receipts.get(intent.digest)
            if previous is not None:
                return MemoryWriteReceipt(
                    intent_id=previous.intent_id,
                    intent_digest=previous.intent_digest,
                    evidence_id=previous.evidence_id,
                    proposal_id=previous.proposal_id,
                    redacted=previous.redacted,
                    deduplicated=True,
                )

            content, redacted = _redact(intent.content)
            suffix = intent.digest[:32]
            evidence = self._submitter.capture_evidence(
                {
                    "operation_id": f"mwi-evidence-{suffix}",
                    "source_type": intent.source_type,
                    "source_ref": intent.source_ref,
                    "subject_id": intent.subject_id,
                    "observed_at": intent.observed_at,
                    "content": content,
                    "permission_snapshot": dict(intent.permission_snapshot),
                    "confirmation": "CAPTURE",
                    "retention_state": intent.retention_state,
                    "data_classification": intent.data_classification,
                }
            )
            evidence_id = evidence.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id:
                raise RuntimeError("submitter lane omitted Evidence identity")

            proposal_id: str | None = None
            if intent.proposal is not None:
                proposal = dict(intent.proposal)
                proposal["supporting_evidence_refs"] = [evidence_id]
                proposal["input_snapshot_hash"] = hashlib.sha256(content.encode()).hexdigest()
                submitted = self._submitter.create_proposal(
                    {
                        "operation_id": f"mwi-proposal-{suffix}",
                        "proposal": proposal,
                        "confirmation": "SUBMIT",
                    }
                )
                raw_proposal_id = submitted.get("proposal_id")
                if not isinstance(raw_proposal_id, str) or not raw_proposal_id:
                    raise RuntimeError("submitter lane omitted Proposal identity")
                summary = submitted.get("confirmation_summary") or {}
                if summary.get("canonical_changed") is not False:
                    raise RuntimeError("submitter lane claimed an unexpected canonical mutation")
                proposal_id = raw_proposal_id

            receipt = MemoryWriteReceipt(
                intent_id=intent.intent_id,
                intent_digest=intent.digest,
                evidence_id=evidence_id,
                proposal_id=proposal_id,
                redacted=redacted,
                deduplicated=False,
            )
            self._receipts[intent.digest] = receipt
            return receipt


def _redact(content: str) -> tuple[str, bool]:
    result = content
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result, result != content
