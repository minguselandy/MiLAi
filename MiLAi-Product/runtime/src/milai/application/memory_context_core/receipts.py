"""Evidence receipts and semantic context-material projections."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from milai.application.memory_context_core.activation import _MULTI_SESSION
from milai.application.memory_context_core.common import (
    _positions,
    _sha256,
    _sufficiency_status,
)
from milai.application.memory_context_core.provenance import (
    _canonical_item_sources,
    _required_sources,
)
from milai.application.memory_context_core.semantics import _reader_semantic_value
from milai.domain.memory_context import (
    ContextAuthorityClass,
    EvidenceContextReceipt,
    EvidenceView,
    IssueRevisionDependency,
    MemoryContext,
    MemoryContextWindow,
    ReaderContextAliasMapping,
)
from milai.domain.memory_resolve import MemoryResolveRequest

_RECEIPT_WINDOW_HEADER = re.compile(
    r"(?m)^\[(?P<alias>E\d+) "
    r"(?:ACCEPTED BINDING SPAN|EVIDENCE WINDOW) / NON-CANONICAL"
    r"(?: [^\]\n]+)?\]$"
)
_RECEIPT_ALIAS_HEADER = re.compile(
    r"(?m)^\[(?P<alias>(?:C|D|E|I)\d+) "
    r"(?:"
    r"DERIVED OPERATOR RESULT / NON-CANONICAL READ-ONLY|"
    r"CANONICAL STATE / GOVERNED|"
    r"ACCEPTED BINDING SPAN / NON-CANONICAL(?: [^\]\n]+)?|"
    r"EVIDENCE WINDOW / NON-CANONICAL(?: [^\]\n]+)?|"
    r"OPEN ISSUE / SAFETY"
    r")\]$"
)


def _evidence_receipt(
    request: MemoryResolveRequest,
    outcome: dict[str, Any],
    memory_context: MemoryContext,
    selected_canonical: list[dict[str, Any]],
) -> EvidenceContextReceipt | None:
    if memory_context.authority_class == "CANONICAL_STATE":
        return None
    decision = outcome.get("sufficiency_decision")
    decision_dict = decision if isinstance(decision, dict) else {}
    status = _sufficiency_status(decision_dict, outcome)
    missing_slots = [
        str(value) for value in decision_dict.get("missing_slots", []) if isinstance(value, str)
    ]
    canonical_position, watermarks = _positions(outcome.get("canonical_position"))
    return EvidenceContextReceipt(
        context_id=str(uuid4()),
        authority_class=memory_context.authority_class,
        query_ir_digest=_sha256(
            outcome.get("memory_query_ir")
            or {
                "query": request.query,
                "interpretation": outcome.get("interpretation"),
                "compiler": "runtime-context-compiler-v0.2",
            }
        ),
        requirement_digest=_sha256(
            {
                "requirements": (
                    outcome.get("memory_query_ir", {}).get("requirements")
                    if isinstance(outcome.get("memory_query_ir"), dict)
                    else outcome.get("requirement")
                ),
                "sufficiency_decision": decision_dict,
                "derived_completeness": (
                    outcome.get("derived_result", {}).get("completeness")
                    if isinstance(outcome.get("derived_result"), dict)
                    else None
                ),
            }
        ),
        semantic_context_digest=memory_context.semantic_context_digest,
        reader_context_digest=memory_context.reader_context_digest,
        receipt_mapping=_receipt_mapping(
            memory_context,
            outcome,
            selected_canonical,
        ),
        source_evidence_ids=memory_context.selected_evidence_ids,
        claim_versions=memory_context.claim_versions,
        issue_revisions=[
            IssueRevisionDependency(issue_id=value, revision=None)
            for value in memory_context.open_issue_ids
        ],
        sufficiency_status=status,
        missing_slots=missing_slots,
        canonical_position=canonical_position,
        projection_watermarks=watermarks,
        issued_at=datetime.now(UTC),
    )


def _receipt_mapping(
    memory_context: MemoryContext,
    outcome: dict[str, Any],
    selected_canonical: list[dict[str, Any]],
) -> list[ReaderContextAliasMapping]:
    mappings: list[ReaderContextAliasMapping] = []
    derived_evidence_ids, derived_source_refs = _required_sources(outcome.get("derived_result"))
    selected_evidence_ids = set(memory_context.selected_evidence_ids)
    selected_source_refs = set(memory_context.selected_source_turn_refs)
    derived_evidence_ids = [
        value for value in derived_evidence_ids if value in selected_evidence_ids
    ]
    derived_source_refs = [value for value in derived_source_refs if value in selected_source_refs]
    if derived_evidence_ids or derived_source_refs:
        mappings.append(
            ReaderContextAliasMapping(
                alias="D1",
                evidence_ids=derived_evidence_ids,
                source_turn_refs=derived_source_refs,
            )
        )
    for ordinal, item in enumerate(selected_canonical, start=1):
        evidence_ids, source_refs = _canonical_item_sources(item)
        claim_version = item.get("claim_version_id")
        claim_versions = [str(claim_version)] if claim_version is not None else []
        evidence_ids = [value for value in evidence_ids if value in selected_evidence_ids]
        source_refs = [value for value in source_refs if value in selected_source_refs]
        if evidence_ids or source_refs or claim_versions:
            mappings.append(
                ReaderContextAliasMapping(
                    alias=f"C{ordinal}",
                    evidence_ids=evidence_ids,
                    source_turn_refs=source_refs,
                    claim_versions=claim_versions,
                )
            )
    window_aliases = [
        match.group("alias") for match in _RECEIPT_WINDOW_HEADER.finditer(memory_context.text)
    ]
    if len(window_aliases) != len(memory_context.windows) or len(set(window_aliases)) != len(
        window_aliases
    ):
        raise AssertionError("Reader Context window aliases are not lossless")
    mappings.extend(
        ReaderContextAliasMapping(
            alias=alias,
            evidence_ids=window.evidence_ids,
            source_turn_refs=window.source_turn_refs,
        )
        for alias, window in zip(window_aliases, memory_context.windows, strict=True)
    )
    if memory_context.open_issue_ids:
        mappings.append(
            ReaderContextAliasMapping(
                alias="I1",
                issue_revisions=[
                    IssueRevisionDependency(issue_id=value, revision=None)
                    for value in memory_context.open_issue_ids
                ],
            )
        )
    visible_aliases = [
        match.group("alias") for match in _RECEIPT_ALIAS_HEADER.finditer(memory_context.text)
    ]
    mapping_by_alias = {mapping.alias: mapping for mapping in mappings}
    if (
        len(visible_aliases) != len(set(visible_aliases))
        or len(mapping_by_alias) != len(mappings)
        or set(visible_aliases) != set(mapping_by_alias)
    ):
        raise AssertionError("Reader Context aliases are not losslessly mapped")
    return [mapping_by_alias[alias] for alias in visible_aliases]


def _semantic_context_material(
    request: MemoryResolveRequest,
    outcome: dict[str, Any],
    authority_class: ContextAuthorityClass,
    canonical_items: list[dict[str, Any]],
    windows: list[MemoryContextWindow],
    derived_result: object,
) -> dict[str, Any]:
    return {
        "contract": "milai-reader-semantic-context-v0.1",
        "memory_status": outcome.get("status", "ABSENT"),
        "authority_class": authority_class,
        "requested_scope": request.requested_scope,
        "required_authority": request.required_authority,
        "query_ir": _reader_semantic_value(outcome.get("memory_query_ir")),
        "sufficiency_decision": _reader_semantic_value(outcome.get("sufficiency_decision")),
        "derived_result": _reader_semantic_value(derived_result),
        "canonical_items": [
            {
                "alias": f"C{ordinal}",
                "value": _reader_semantic_value(item),
            }
            for ordinal, item in enumerate(canonical_items, start=1)
        ],
        "evidence_windows": [
            {
                "alias": f"E{ordinal}",
                "observed_at": window.observed_at,
                "speakers": window.speakers,
                "text": window.text,
                "requirement_priority": window.requirement_priority,
                "truncated": window.truncated,
            }
            for ordinal, window in enumerate(windows, start=1)
        ],
    }


def _requires_multiple_sessions(
    query: str,
    query_ir: object,
    views: list[EvidenceView],
    required_evidence_ids: list[str],
    required_source_refs: list[str],
) -> bool:
    required_ids = set(required_evidence_ids)
    required_refs = set(required_source_refs)
    required_sessions = {
        view.session_id
        for view in views
        if view.evidence_id in required_ids or view.source_turn_ref in required_refs
    }
    return len(required_sessions) > 1 or _MULTI_SESSION.search(query) is not None
