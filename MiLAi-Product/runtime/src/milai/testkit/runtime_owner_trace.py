"""Owner-produced, body-free identity export for one observed Runtime execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from milai.domain.reader_evidence_plan import DecisionSnapshot
from milai.domain.retrieval_audit import canonical_sha256
from milai.observability.retrieval_audit import ProductRetrievalAuditObserver
from milai.persistence.retrieval_repository import RetrievalTraceCommand


def _ref(kind: str, value: str) -> str:
    return f"{kind}:{canonical_sha256(value)}"


class RuntimeOwnerTraceObserver(ProductRetrievalAuditObserver):
    """Explicit testkit observer; no extra queries, authorization or canonical writes.

    A report must bind the actual recorded trace ID to its response. Exact Evidence
    versions come only from owner-provided content hashes, never hashes of IDs or
    reconstructed text. Canonical Claim versions remain explicitly unsupported.
    """

    def __init__(self) -> None:
        super().__init__(enabled=True)
        self._recorded_trace_id: str | None = None
        self._canonical_position: int | None = None

    def observe_repository_call(
        self, method: str, args: Sequence[Any], kwargs: Mapping[str, Any], result: Any,
    ) -> None:
        super().observe_repository_call(method, args, kwargs, result)
        if method == "record_trace":
            if self._recorded_trace_id is not None:
                raise RuntimeError("OWNER_TRACE_MULTIPLE_EXECUTIONS")
            command = args[1] if len(args) > 1 else kwargs.get("command")
            if not isinstance(command, RetrievalTraceCommand):
                raise RuntimeError("OWNER_TRACE_COMMAND_NOT_OBSERVED")
            self._recorded_trace_id = str(result)
            self._canonical_position = command.canonical_snapshot

    def owner_trace(self, response: Mapping[str, Any]) -> dict[str, Any]:
        captured = self._captured
        if captured is None or self._recorded_trace_id is None:
            raise RuntimeError("OWNER_TRACE_EXECUTION_NOT_OBSERVED")
        if response.get("trace_id") != self._recorded_trace_id:
            raise RuntimeError("OWNER_TRACE_RESPONSE_ID_MISMATCH")
        decision = captured["decision_snapshot"]
        if not isinstance(decision, DecisionSnapshot):
            raise RuntimeError("OWNER_TRACE_DECISION_NOT_OBSERVED")
        context = response.get("memory_context")
        if not isinstance(context, Mapping):
            context = {}
        selected_ids = context.get("selected_evidence_ids")
        gaps: list[dict[str, str]] = []
        if selected_ids is None:
            gaps.append({"reason": "CONTEXT_SELECTION_NOT_OBSERVED"})
            selected_ids = []
        if not isinstance(selected_ids, list) or any(not isinstance(x, str) for x in selected_ids):
            raise RuntimeError("OWNER_TRACE_CONTEXT_IDENTITY_INVALID")
        versions: dict[str, dict[str, str]] = {}
        for item in captured["results"]:
            evidence_id, digest = item.get("evidence_id"), item.get("content_hash")
            if item.get("kind") != "EVIDENCE_OBSERVATION" or not isinstance(evidence_id, str):
                gaps.append({"reason": "UNSUPPORTED_MEMORY_KIND"})
                continue
            if not isinstance(digest, str) or len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest
            ):
                gaps.append({"memory_ref": _ref("evidence", evidence_id),
                             "reason": "EXACT_CONTENT_HASH_NOT_OBSERVED"})
                continue
            version = {
                "memory_ref": _ref("evidence", evidence_id),
                "version_id": _ref("evidence-record", evidence_id),
                "content_sha256": digest,
            }
            if evidence_id in versions and versions[evidence_id] != version:
                raise RuntimeError("OWNER_TRACE_VERSION_CONTENT_CHANGED")
            versions[evidence_id] = version
        selected = []
        for evidence_id in selected_ids:
            if evidence_id not in versions:
                gaps.append({"memory_ref": _ref("evidence", evidence_id),
                             "reason": "SELECTED_EXACT_VERSION_NOT_OBSERVED"})
            else:
                selected.append(dict(versions[evidence_id]))
        return {
            "schema_version": "milai-runtime-owner-trace-v1",
            "retrieval_trace_ref": _ref("retrieval", self._recorded_trace_id),
            "decision_snapshot_digest": decision.snapshot_digest,
            "evidence_set_digest": canonical_sha256(list(decision.accepted_evidence_ids)),
            "gate_digest": decision.gate_digest,
            "binding_digest": decision.binding_digest,
            "canonical_position": self._canonical_position,
            "materialized_evidence_versions": list(versions.values()),
            "selected_evidence_refs": [_ref("evidence", value) for value in selected_ids],
            "selected_versions": selected,
            "status": "PARTIAL" if gaps else "COMPLETE",
            "trace_gaps": gaps,
        }
