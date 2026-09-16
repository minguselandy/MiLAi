"""Deterministic B0 characterization for the ML-R02 replacement points.

The fixture deliberately avoids databases and model providers.  It freezes the
observable planner, temporal-proof, and Formation behavior that B1/B2 replace,
while also recording the duplicate product authorities that must disappear.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from milai.application.formation_generalization import build_generalized_formation
from milai.application.query_ir_compat import infer_operator_family
from milai.application.query_planner import QueryPlanner
from milai.domain.requirement_state import canonical_sha256
from milai.domain.retrieval import RetrievalRequest
from milai.domain.temporal_proof import (
    BoundedRangeAccessClosureV02,
    BoundedRangeDedupClosureV02,
    BoundedRangeEventSetClosureV02,
    BoundedRangeProjectionClosureV02,
    BoundedRangeQueryClosureV02,
    BoundedRangeScanClosureV02,
    BoundedRangeSnapshotClosureV02,
    build_bounded_range_scan_proof_v02,
    build_event_time_interval_v02,
)

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = datetime(2026, 3, 20, 12, tzinfo=UTC)

_QUERIES = {
    "simple_lookup": "Where do I currently live?",
    "multi_operand": "What is the difference between the first and second values?",
    "current_state": "What is my current address?",
    "contested": "Did I move to Riga or Vilnius?",
    "wrong_complete_guard": "How many doctor appointments did I attend in March 2026?",
    "preference": "What was my latest preference?",
    "ambiguous_negative": "Who became a parent first, Rachel or Alex?",
}


def _plan(query: str) -> dict[str, Any]:
    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=query,
            as_of=REFERENCE,
            reference_time=REFERENCE,
            system_as_of=REFERENCE,
            requested_scope={"project_ids": ["milai"]},
        )
    )
    query_ir = plan.memory_query_ir
    assert query_ir is not None
    return {
        "schema_version": query_ir.schema_version,
        "mode": query_ir.mode,
        "operator_family": infer_operator_family(query_ir),
        "operator": plan.operator,
        "required_slots": [item.slot_id for item in query_ir.requirements if item.required],
        "completeness": query_ir.completeness,
        "compiler_version": query_ir.planner_trace.compiler_version,
        "auxiliary_model_calls": query_ir.planner_trace.auxiliary_model_calls,
    }


def _temporal_proofs() -> dict[str, Any]:
    interval = build_event_time_interval_v02(
        interval_start=datetime(2026, 3, 1, tzinfo=UTC),
        interval_end_exclusive=datetime(2026, 4, 1, tzinfo=UTC),
        timezone="UTC",
        precision="MONTH",
        basis="EXPLICIT_CALENDAR",
    )
    query = BoundedRangeQueryClosureV02(
        query_ir_digest="1" * 64,
        requirement_state_digest="2" * 64,
        event_time_interval=interval,
        timezone="UTC",
    )
    snapshot = BoundedRangeSnapshotClosureV02(
        transaction_snapshot_identity="3" * 64,
        source_partition_snapshot_identity="4" * 64,
        access_snapshot_identity="5" * 64,
        revocation_snapshot_identity="6" * 64,
        snapshot_stable=True,
    )
    projection = BoundedRangeProjectionClosureV02(
        projection_version="event-v02",
        temporal_normalizer_version="temporal-v02",
        target_watermark=10,
        projection_watermark=10,
        projection_watermark_covered=True,
        dead_letter_gap=False,
        unprojected_source_count=0,
        raw_fallback_closed=True,
    )
    event_set = BoundedRangeEventSetClosureV02(
        candidate_event_count=2,
        in_range_event_count=2,
        out_of_range_event_count=0,
        ambiguous_time_count=0,
        unresolved_event_count=0,
        event_identity_policy_version="event-identity-v02",
    )
    dedup = BoundedRangeDedupClosureV02(
        dedup_policy_version="dedup-v02",
        duplicate_group_count=0,
        unresolved_duplicate_group_count=0,
        distinct_event_count=2,
        dedup_complete=True,
    )
    access = BoundedRangeAccessClosureV02(
        policy_digest="7" * 64,
        unreadable_evidence_count=0,
        access_snapshot_valid=True,
    )

    def build(*, max_items_hit: bool, ambiguous: bool) -> dict[str, Any]:
        local_event_set = event_set.model_copy(
            update={"ambiguous_time_count": 1, "in_range_event_count": 1}
        ) if ambiguous else event_set
        local_dedup = dedup.model_copy(update={"distinct_event_count": 1}) if ambiguous else dedup
        proof = build_bounded_range_scan_proof_v02(
            query_closure=query,
            snapshot_closure=snapshot,
            scan_closure=BoundedRangeScanClosureV02(
                source_partition_closed=True,
                range_scan_complete=not max_items_hit,
                max_items=128,
                max_items_hit=max_items_hit,
                unreadable_source_count=0,
            ),
            projection_closure=projection,
            event_set_closure=local_event_set,
            dedup_closure=local_dedup,
            access_closure=access,
        )
        return {"status": proof.status, "closure_complete": proof.closure_complete}

    return {
        "bounded_complete": build(max_items_hit=False, ambiguous=False),
        "max_items_hit": build(max_items_hit=True, ambiguous=False),
        "ambiguous_time": build(max_items_hit=False, ambiguous=True),
    }


def _source(
    evidence_id: str,
    content: str,
    ordinal: int,
    *,
    speaker: str = "user",
    revoked: bool = False,
) -> dict[str, Any]:
    observed_at = REFERENCE + timedelta(minutes=ordinal)
    return {
        "evidence_id": evidence_id,
        "source_ref": f"memory://mlr02/session-0/turn/{ordinal}",
        "scope_id": "milai",
        "speaker": speaker,
        "content": content,
        "observed_at": observed_at.isoformat(),
        "permission_snapshot": {"readable": True, "project_ids": ["milai"]},
        "retention_state": "READABLE",
        "access_decision": "ALLOWED",
        "revoked_at": observed_at.isoformat() if revoked else None,
    }


def _formation() -> dict[str, Any]:
    sources = [
        _source("topic", "I live in Riga.", 0),
        _source("continuation", "I still live in Riga and work on MiLAi.", 1),
        _source("correction", "Correction: I do not live in Riga; I live in Vilnius.", 2),
        _source("temporary", "Until October 10, 2026, I am staying in Bath.", 3),
        _source("assistant", "I live in Paris.", 4, speaker="assistant"),
        _source("revoked", "I live in Oslo.", 5, revoked=True),
    ]
    first = build_generalized_formation(sources)
    second = build_generalized_formation(list(reversed(sources)))
    relations = sorted(item.relation for item in first.state_changes.transitions)
    candidate_sources = sorted(
        {
            item.span.evidence_id
            for item in [
                *first.formation.entity_candidates,
                *first.formation.event_candidates,
                *first.state_changes.assertions,
                *first.state_changes.transitions,
            ]
        }
    )
    candidates = [
        *first.formation.entity_candidates,
        *first.formation.event_candidates,
        *first.state_changes.assertions,
        *first.state_changes.transitions,
    ]
    source_content = {str(item["evidence_id"]): str(item["content"]) for item in sources}
    raw_span_coverage = all(
        source_content[item.span.evidence_id][item.span.start : item.span.end]
        == item.span.text
        for item in candidates
    )
    return {
        "producer_identity": first.producer_identity,
        "deterministic_replay": (
            first.formation.sidecar_digest == second.formation.sidecar_digest
            and first.state_changes.sidecar_digest == second.state_changes.sidecar_digest
        ),
        "raw_span_coverage": raw_span_coverage,
        "transition_relations": relations,
        "assistant_contamination": "assistant" in candidate_sources,
        "revoked_contamination": "revoked" in candidate_sources,
        "canonical_mutation": first.formation.canonical_mutation,
    }


def _replacement_points() -> dict[str, Any]:
    retrieval = (ROOT / "runtime/src/milai/application/retrieval.py").read_text(
        encoding="utf-8"
    )
    query = (ROOT / "runtime/src/milai/application/memory_query.py").read_text(
        encoding="utf-8"
    )
    formation_projection = (
        ROOT / "runtime/src/milai/application/formation_projection.py"
    ).read_text(encoding="utf-8")
    return {
        "acquisition_final_sufficiency_owner_present": (
            "_acquisition_owns_final_sufficiency" in retrieval
        ),
        "final_sufficiency_reconcile_present": (
            "_reconcile_final_sufficiency_with_requirement_state" in retrieval
        ),
        "product_v01_compiler_call_present": "self.compile_v01(" in query,
        "product_v01_translator_call_present": "translate_memory_query_ir_v01(" in query,
        "product_generalized_builder_direct_call_present": (
            "build_generalized_formation(ordered)" in formation_projection
        ),
    }


def characterize() -> dict[str, Any]:
    material = {
        "schema": "milai.ml-r02.b0-characterization.v1",
        "external_model_calls": 0,
        "formal_holdout_consumed": False,
        "D": {name: _plan(query) for name, query in _QUERIES.items()},
        "Q": {
            name: {
                key: value
                for key, value in _plan(query).items()
                if key in {
                    "schema_version",
                    "mode",
                    "operator_family",
                    "required_slots",
                    "completeness",
                    "compiler_version",
                }
            }
            for name, query in _QUERIES.items()
        },
        "T": _temporal_proofs(),
        "F": _formation(),
        "replacement_points": _replacement_points(),
    }
    return {**material, "characterization_digest": canonical_sha256(material)}


__all__ = ["characterize"]
