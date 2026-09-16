"""Matched DG-28 replay that consumes the sealed MF-03 Formation sidecar."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from milai.application.decision_boundary import decide_deterministic_boundary
from milai.application.formation_extraction import build_formation_sidecar
from milai.domain.formation_artifact import (
    FormationArtifactSidecarV01,
    FormationEventCandidateV01,
    FormationModelEventProposalV01,
)
from milai.domain.requirement_state import canonical_sha256

from evals.dg16.lme10 import load_public_dev_cases
from evals.dg26.stateview_reranking import load_experiment_inputs
from evals.dg27.decision_boundary import (
    DG26_LOCK,
    _compact_source_ref,
    _proofs_by_case,
)
from evals.dg28.acquisition_shadow import build_acquisition_shadow
from evals.dg28.lite_effect import (
    CHANNEL_CAPS,
    _decision_row,
    _hydrate_lite_candidates,
    _lite_plan,
    _mapping,
    _sequence,
    score_lite_effect,
    select_lite_candidates,
)

MF03_UNSCORED = Path(
    "var/mf03/mf03-formation-sidecar-20260830-004/unscored.json"
)
MF03_RECEIPT = Path(
    "var/mf03/mf03-formation-sidecar-20260830-004/receipt.json"
)


class DG28FormationConsumptionError(RuntimeError):
    """A sealed Formation artifact or matched candidate identity drifted."""


def execute_formation_consumption_replay(root: Path) -> dict[str, Any]:
    """Compare identical lexical pools without/with MF-03 semantic artifacts."""

    root = root.resolve()
    inputs = load_experiment_inputs(root, root / DG26_LOCK)
    proofs = _proofs_by_case(root)
    shadow = build_acquisition_shadow(root)
    source_cases, selection = load_public_dev_cases()
    source_by_case = {case.case_id: case for case in source_cases}
    mf03_receipt = _object(root / MF03_RECEIPT)
    if mf03_receipt.get("status") != "PASS_MF03_FORMATION_IDENTITY_TIME":
        raise DG28FormationConsumptionError("MF03_TERMINAL_NOT_PASS")

    baseline_rows: list[dict[str, Any]] = []
    treatment_rows: list[dict[str, Any]] = []
    consumed: list[dict[str, Any]] = []
    for raw_record in _sequence(shadow.get("records"), "shadow records"):
        record = _mapping(raw_record, "shadow record")
        case_id = str(record["case_id"])
        requirement_id = str(record["requirement_id"])
        context = inputs.contexts[case_id]
        selected = select_lite_candidates(record)
        plan = _lite_plan(context.acquisition_plan, requirement_id, len(selected))
        candidates, source_records = _hydrate_lite_candidates(
            case_id=case_id,
            requirement_id=requirement_id,
            selected=selected,
            source_case=source_by_case[case_id],
        )
        capability_digest = canonical_sha256(
            {
                "policy": "DG28_LITE_OFFICIAL_LEXICAL_UNION_V01",
                "channels": CHANNEL_CAPS,
                "candidate_ids": [item.candidate_id for item in candidates],
                "historical_official_probe_run_id": shadow["official_probe_run_id"],
            }
        )
        baseline = decide_deterministic_boundary(
            plan=plan,
            query_ir=context.query_ir,
            acquisition_capability_digest=capability_digest,
            candidates=candidates,
            source_records=source_records,
            completion_proof=proofs[case_id],
        )
        formed_events = formation_events_for_sources(root, source_records)
        treatment = decide_deterministic_boundary(
            plan=plan,
            query_ir=context.query_ir,
            acquisition_capability_digest=capability_digest,
            candidates=candidates,
            source_records=source_records,
            completion_proof=proofs[case_id],
            formation_events=formed_events,
        )
        baseline_rows.append(
            _decision_row(case_id, requirement_id, candidates, baseline)
        )
        treatment_rows.append(
            _decision_row(case_id, requirement_id, candidates, treatment)
        )
        consumed.extend(
            {
                "case_id": case_id,
                "requirement_id": requirement_id,
                "artifact_digest": item.artifact_digest,
                "source_ref": item.span.source_ref,
                "event_identity_key": item.event_identity_key,
                "time_basis": item.time_basis,
            }
            for item in formed_events
        )

    output: dict[str, Any] = {
        "schema": "milai.dg28.formation-consumption-unscored.v0.1",
        "policy": {
            "channels": CHANNEL_CAPS,
            "fusion": "IDENTITY_DEDUP_RRF_K60",
            "formation_sidecar": str(MF03_RECEIPT),
            "candidate_pool_matched": True,
            "model_planner": False,
            "second_round": False,
        },
        "source_selection": selection,
        "baseline": baseline_rows,
        "treatment": treatment_rows,
        "formation_events_consumed": consumed,
        "cost": {
            "new_official_acquisition_calls": 0,
            "historical_official_outputs_replayed": 6,
            "model_calls": 0,
            "reader_calls": 0,
            "canonical_mutations": 0,
            "automatic_retries": 0,
            "formation_artifact_replays": len(consumed),
        },
        "candidate_feature_flag": "OFF",
        "formal_holdout_used": False,
    }
    output["unscored_digest"] = canonical_sha256(output)
    return output


def score_formation_consumption_replay(
    root: Path,
    unscored: Mapping[str, Any],
) -> dict[str, Any]:
    """Reuse the sealed DG-28 scorer, then apply the Formation-specific gate."""

    base = score_lite_effect(root.resolve(), unscored)
    checks = dict(cast(Mapping[str, bool], base["checks"]))
    checks.update(
        {
            "all_target_bindings_closed": base["treatment"]["target_binding_groups"]
            == 7,
            "candidate_pool_unchanged": base["delta"]["candidate_count"] == 0,
            "one_formation_event_consumed": len(
                _sequence(
                    unscored.get("formation_events_consumed"),
                    "formation events consumed",
                )
            )
            == 1,
            "query_time_model_calls_zero": unscored["cost"]["model_calls"] == 0,
        }
    )
    passed = all(checks.values())
    output = dict(base)
    output.update(
        {
            "schema": "milai.dg28.formation-consumption-score.v0.1",
            "checks": checks,
            "status": (
                "PASS_DG28_FORMATION_CONSUMPTION_CLOSURE"
                if passed
                else "NEEDS_REPAIR"
            ),
            "next_route": (
                "DG30_READ_PATH_INTEGRATION_NO_DG29"
                if passed
                else "REPAIR_FORMATION_CONSUMPTION_BOUNDARY"
            ),
            "dg29_refinding_entry": False,
            "dg29_reason": "ALL_TARGET_BINDINGS_CLOSED_WITHOUT_SECOND_ROUND",
        }
    )
    output.pop("score_digest", None)
    output["score_digest"] = canonical_sha256(output)
    return output


def formation_events_for_sources(
    root: Path,
    source_records: Sequence[Mapping[str, Any]],
) -> list[FormationEventCandidateV01]:
    """Rebase sealed Formation proposals onto the exact governed read snapshot."""

    unscored = _object(root.resolve() / MF03_UNSCORED)
    sidecar = FormationArtifactSidecarV01.model_validate(unscored["treatment_sidecar"])
    source_ref_by_old_evidence: dict[str, str] = {}
    for event in sidecar.event_candidates:
        source_ref_by_old_evidence[event.span.evidence_id] = event.span.source_ref
        for anchor in event.temporal_anchor_spans:
            source_ref_by_old_evidence[anchor.evidence_id] = anchor.source_ref
    current_by_ref = {
        _compact_source_ref(str(source["source_ref"])): source
        for source in source_records
    }
    proposals: list[FormationModelEventProposalV01] = []
    for usage in _sequence(unscored.get("model_usage"), "MF03 model usage"):
        for raw_proposal in _sequence(
            _mapping(usage, "MF03 usage").get("proposals"),
            "MF03 proposals",
        ):
            proposal = FormationModelEventProposalV01.model_validate(raw_proposal)
            target_ref = source_ref_by_old_evidence.get(proposal.evidence_id)
            target = current_by_ref.get(_compact_source_ref(target_ref or ""))
            if target is None:
                continue
            updates: dict[str, Any] = {"evidence_id": str(target["evidence_id"])}
            if proposal.temporal_relation is not None:
                relation = proposal.temporal_relation
                anchor_ref = source_ref_by_old_evidence.get(relation.anchor_evidence_id)
                current_anchor = current_by_ref.get(
                    _compact_source_ref(anchor_ref or "")
                )
                if current_anchor is None:
                    continue
                updates["temporal_relation"] = relation.model_copy(
                    update={"anchor_evidence_id": str(current_anchor["evidence_id"])}
                )
            proposals.append(proposal.model_copy(update=updates))
    if not proposals:
        return []
    rebased = build_formation_sidecar(
        source_records,
        model_event_proposals=proposals,
        model_identity=f"MF03_V004_REPLAY:{sidecar.sidecar_digest}",
        model_calls=0,
    )
    if rebased.rejected_model_outputs:
        raise DG28FormationConsumptionError("REBASED_FORMATION_PROPOSAL_REJECTED")
    return [
        item
        for item in rebased.event_candidates
        if item.producer_identity.startswith("MF03_V004_REPLAY:")
        and item.occurrence_time is not None
    ]


def _object(path: Path) -> dict[str, Any]:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG28FormationConsumptionError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


__all__ = [
    "DG28FormationConsumptionError",
    "execute_formation_consumption_replay",
    "formation_events_for_sources",
    "score_formation_consumption_replay",
]
