"""Reader-facing semantic projection helpers."""

from __future__ import annotations

from typing import Any

_OPAQUE_READER_KEYS = frozenset(
    {
        "blob_id",
        "claim_id",
        "claim_version_id",
        "claim_versions",
        "context_id",
        "evidence_id",
        "evidence_ids",
        "evidence_refs",
        "event_id",
        "interpretation_id",
        "issue_id",
        "open_issue_ids",
        "outbox_id",
        "principal_id",
        "request_id",
        "requirement_id",
        "retrieval_trace_id",
        "session_id",
        "source_evidence_id",
        "source_evidence_ids",
        "source_ref",
        "source_refs",
        "source_turn_ref",
        "source_turn_refs",
        "span_id",
        # Operational capture time changes on a faithful re-ingest of the same
        # immutable source snapshot. Keep it in the full trace, but exclude it
        # from the Reader-facing semantic projection and digest.
        "system_timestamp",
        "tenant_id",
        "trace_id",
    }
)


def _query_ir_operator_family(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    steps = value.get("steps")
    if not isinstance(steps, list):
        return None
    families = {
        family
        for step in steps
        if isinstance(step, dict)
        and isinstance((constraints := step.get("constraints")), dict)
        and isinstance((family := constraints.get("operator_family")), str)
        and family
    }
    return next(iter(families)) if len(families) == 1 else None


def _query_ir_has_temporal_constraint(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    constraints = value.get("constraints")
    return isinstance(constraints, dict) and isinstance(
        constraints.get("normalized_temporal"), dict
    )


def _query_ir_enumerates_members(value: object) -> bool:
    """Whether a COUNT answer must be derived from evidence members.

    A number printed in one candidate is not itself an answer in this mode.
    Scalar count facts use ``ALL_REQUIRED_BINDINGS`` and retain the ordinary
    numeric-answer signal.
    """

    return (
        isinstance(value, dict)
        and value.get("completeness") == "ALL_MATCHES_IN_RANGE"
        and _query_ir_operator_family(value) == "COUNT"
    )


def _reader_semantic_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): _reader_semantic_value(item)
            for key, item in value.items()
            if str(key) not in _OPAQUE_READER_KEYS and not str(key).endswith(("_sha256", "_hash"))
        }
    if isinstance(value, list):
        return [_reader_semantic_value(item) for item in value]
    if isinstance(value, tuple):
        return [_reader_semantic_value(item) for item in value]
    return value


def _validated_operand(operand: dict[str, Any]) -> bool:
    if operand.get("canonical_mutation") is True:
        return False
    authority = operand.get("authority_class")
    if authority is not None and authority != "EVIDENCE_ONLY":
        return False
    binding = operand.get("requirement_binding")
    if binding is None:
        return True
    return (
        isinstance(binding, dict)
        and binding.get("status") == "MATCH"
        and binding.get("canonical_mutation") is False
        and binding.get("authority_class") == "EVIDENCE_ONLY"
    )
