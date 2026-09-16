"""Direct typed-mapping effect for the MF-04 Evolution Bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from milai.application.derivation import CommitPolicy, DeriveAndDiagnose
from milai.application.formation_evolution_bridge import (
    EvolutionCurrentClaimV01,
    map_state_artifact_to_proposal,
)
from milai.application.state_change_formation import build_state_change_sidecar
from milai.domain.formation_state import (
    FormationStateAssertionV01,
    FormationStateTransitionV01,
)
from milai.domain.requirement_state import canonical_sha256

from evals.mf01.labels import build_label_seal
from evals.mf04.state_change_effect import load_state_change_sources

_EXPECTED_OPERATIONS = {
    "mf01-evidence-correction-01": "SUPERSEDE",
    "mf01-evidence-move-01": "SUPERSEDE",
    "mf01-evidence-preference-01": "CREATE",
    "mf01-evidence-temporary-01": "CREATE",
}


def execute_ev01_mapping_effect(root: Path) -> dict[str, Any]:
    """Replay all applicable governed MF-04 artifacts through existing policy."""

    root = root.resolve()
    seal = build_label_seal(root)
    sources = load_state_change_sources(root, seal)
    sidecar = build_state_change_sidecar(sources)
    transition_by_assertion = {
        item.resulting_assertion_digest: item for item in sidecar.transitions
    }
    rows: list[dict[str, Any]] = []
    query_local_filtered = 0
    for assertion in sidecar.assertions:
        transition = transition_by_assertion.get(assertion.artifact_digest)
        current = _current_claim(assertion, transition)
        governed_ref = uuid5(NAMESPACE_URL, assertion.span.evidence_id)
        request = map_state_artifact_to_proposal(
            assertion,
            transition=transition,
            current_claim=current,
            governed_evidence_ref=governed_ref,
            scope_predicate={"project_ids": ["milai"]},
        )
        if request is None:
            query_local_filtered += 1
            continue
        current_row = (
            {
                "claim_version_id": str(current.claim_version_id),
                "effective_status": current.effective_status,
            }
            if current is not None
            else None
        )
        validated = DeriveAndDiagnose().derive(request, current_row)
        policy = CommitPolicy().decide(validated)
        source_span = request.derivation_snapshot["source_span"]
        rows.append(
            {
                "source_evidence_id": assertion.span.evidence_id,
                "assertion_digest": assertion.artifact_digest,
                "transition_digest": transition.artifact_digest if transition else None,
                "operation": request.operation,
                "diagnostic_relation": validated.relation,
                "expected_head_matches": validated.expected_head_matches,
                "commit_policy_decision": policy.decision,
                "supporting_evidence_refs": [
                    str(item) for item in request.supporting_evidence_refs
                ],
                "source_span": source_span,
                "proposed_patch": request.proposed_patch,
                "canonical_commit_authorized": request.derivation_snapshot[
                    "canonical_commit_authorized"
                ],
            }
        )

    wrong_disposition = sum(
        row["operation"] != _EXPECTED_OPERATIONS.get(str(row["source_evidence_id"]))
        for row in rows
    )
    missing_provenance = sum(
        not row["supporting_evidence_refs"]
        or not isinstance(row["source_span"], dict)
        or not row["source_span"].get("text_digest")
        for row in rows
    )
    move = next(row for row in rows if row["source_evidence_id"] == "mf01-evidence-move-01")
    temporary = next(
        row for row in rows if row["source_evidence_id"] == "mf01-evidence-temporary-01"
    )
    valid_time_misassignment = int(
        move["proposed_patch"].get("valid_time_from")
        != "2026-08-12T00:00:00+08:00"
        or "valid_time_to" in move["proposed_patch"]
        or not str(temporary["proposed_patch"].get("valid_time_to", "")).startswith(
            "2026-09-05T23:59:59.999999"
        )
    )
    unsupported_promotion = sum(
        bool(row["canonical_commit_authorized"])
        or row["commit_policy_decision"] != "USER_REVIEW"
        for row in rows
    )
    checks = {
        "four_governed_artifacts_mapped": len(rows) == 4,
        "two_query_local_artifacts_filtered": query_local_filtered == 2,
        "wrong_transition_disposition_zero": wrong_disposition == 0,
        "missing_provenance_closure_zero": missing_provenance == 0,
        "valid_time_misassignment_zero": valid_time_misassignment == 0,
        "unsupported_canonical_promotion_zero": unsupported_promotion == 0,
    }
    output: dict[str, Any] = {
        "schema": "milai.ev01.mapping-effect.v0.1",
        "status": "PASS_EV01_TYPED_MAPPING" if all(checks.values()) else "NEEDS_REPAIR",
        "execution_authority": "USER_20260830_REPAIR_THEN_CONTINUE",
        "rows": rows,
        "metrics": {
            "governed_artifacts_mapped": len(rows),
            "query_local_artifacts_filtered": query_local_filtered,
            "WrongTransitionDisposition": wrong_disposition,
            "MissingProvenanceClosure": missing_provenance,
            "ValidTimeMisassignment": valid_time_misassignment,
            "UnsupportedCanonicalPromotion": unsupported_promotion,
        },
        "checks": checks,
        "model_calls": 0,
        "canonical_mutations": 0,
        "formal_holdout_used": False,
    }
    output["result_digest"] = canonical_sha256(output)
    return output


def _current_claim(
    assertion: FormationStateAssertionV01,
    transition: FormationStateTransitionV01 | None,
) -> EvolutionCurrentClaimV01 | None:
    if transition is None or transition.relation not in {"UPDATES", "CORRECTS"}:
        return None
    assert transition.previous_value is not None
    return EvolutionCurrentClaimV01(
        claim_id=_uuid(f"claim:{assertion.predicate}"),
        claim_version_id=_uuid(
            f"version:{assertion.span.evidence_id}:{transition.previous_value}"
        ),
        subject_id=assertion.subject_identity,
        predicate=assertion.predicate,
        payload=transition.previous_value,
        effective_status="EFFECTIVE",
    )


def _uuid(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, value)


__all__ = ["execute_ev01_mapping_effect"]
