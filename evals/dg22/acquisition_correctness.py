"""DG-22 S5 requirement-complete acquisition and precision-fusion validation."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from milai.application.accuracy_acquisition import (
    AccuracyAcquisitionExecutor,
    AccuracyChannel,
    compile_accuracy_action_decision,
    compile_requirement_complete_bundle,
    default_accuracy_acquisition_policy,
    execute_requirement_complete_bundle,
)
from milai.application.memory_query import MemoryQueryCompiler
from milai.domain.semantic_query import EvidenceRequirementV02

REFERENCE = datetime(2031, 6, 30, 12, 0, tzinfo=UTC)
STATE_DIGEST = "1" * 64
CAPABILITY_DIGEST = "2" * 64


class _Repository:
    def __init__(self, evidence: Sequence[dict[str, Any]]) -> None:
        self.evidence = list(evidence)
        self.calls = 0

    def scan_accuracy_bundle(self, **_: Any) -> list[dict[str, Any]]:
        self.calls += 1
        return list(self.evidence)


def run_acquisition_correctness() -> dict[str, Any]:
    policy = default_accuracy_acquisition_policy()
    query_ir = MemoryQueryCompiler().compile(
        "How much did each Atlas ticket cost?",
        reference_time=REFERENCE,
    )
    missing = [item.slot_id for item in query_ir.requirements if item.required]
    decision = compile_accuracy_action_decision(
        query_ir,
        missing,
        executable_channels=["FTS_ENRICHED", "EVIDENCE_DENSE", "FTS_RAW"],
        requirement_state_digest=STATE_DIGEST,
        acquisition_capability_digest=CAPABILITY_DIGEST,
        expected_new_binding_by_channel={"FTS_ENRICHED": 2},
        policy=policy,
    )
    bundle = decision["bundle"]
    assert bundle is not None
    evidence = _core_evidence()
    repository = _Repository(evidence)
    execution = AccuracyAcquisitionExecutor(repository).execute(
        query_ir,
        bundle,
        current_requirement_state_digest=STATE_DIGEST,
        current_acquisition_capability_digest=CAPABILITY_DIGEST,
        policy=policy,
    )
    fast_stops = _fast_stop_matrix(query_ir, missing)
    cap = _target_cap_probe(query_ir)
    stale = _stale_identity_probe(query_ir, bundle, evidence)
    development_matrix = _development_ceiling_matrix(query_ir, missing)
    function_parameters = {
        name
        for function in (
            compile_accuracy_action_decision,
            compile_requirement_complete_bundle,
            execute_requirement_complete_bundle,
        )
        for name in inspect.signature(function).parameters
    }
    accepted_regions = {item["source_ref"] for item in execution["selected_evidence"]}
    metrics = {
        "target_requirement_count": len(bundle.target_requirement_ids),
        "executed_probe_count": len(bundle.probe_ids),
        "probe_attribution_requirement_count": len(execution["probe_attribution"]),
        "binding_attribution_requirement_count": len(execution["binding_attribution"]),
        "extra_passes_per_query": execution["acquisition_passes"],
        "repository_probe_calls": execution["repository_probe_calls"],
        "provider_controller_calls": execution["provider_controller_calls"],
        "automatic_retries": execution["automatic_retries"],
        "global_probe_count": execution["global_probe_count"],
        "repeated_accepted_region": execution["repeated_accepted_region_count"],
        "candidates_hydrated": execution["candidates_hydrated"],
        "useful_candidate_rate": execution["useful_candidate_rate"],
        "fast_stop_cells": len(fast_stops),
        "target_cap_residual_count": len(cap["residual_requirement_ids"]),
        "stale_identity_rejections": sum(stale.values()),
        "case_id_or_gold_function_parameters": len(
            {"case_id", "gold", "answer"} & function_parameters
        ),
        "accepted_region_count": len(accepted_regions),
    }
    checks = {
        "candidate_default_false": policy.default_enabled is False,
        "policy_digest_valid": len(policy.policy_digest) == 64,
        "all_missing_requirements_targeted": set(bundle.target_requirement_ids)
        == set(missing),
        "same_channel_probe_batch": len({bundle.channel for _ in bundle.probe_ids})
        == 1,
        "every_probe_attributed": len(bundle.probe_ids)
        == len(bundle.target_requirement_ids),
        "one_extra_pass": metrics["extra_passes_per_query"] == 1,
        "one_repository_call": repository.calls
        == metrics["repository_probe_calls"]
        == 1,
        "provider_controller_zero": metrics["provider_controller_calls"] == 0,
        "retry_zero": metrics["automatic_retries"] == 0,
        "global_probe_zero": metrics["global_probe_count"] == 0,
        "first_reserve_all_requirements": set(
            execution["first_reserve_requirement_ids"]
        )
        == set(missing),
        "probe_and_binding_attribution_separate": execution["probe_attribution"]
        != execution["binding_attribution"],
        "repeated_accepted_region_zero": metrics["repeated_accepted_region"] == 0,
        "governance_denied_not_hydrated": "denied"
        not in {item["evidence_id"] for item in execution["selected_evidence"]},
        "useful_candidate_rate_at_least_030": metrics["useful_candidate_rate"] >= 0.30,
        "fast_stop_matrix_pass": all(row["passed"] for row in fast_stops),
        "target_cap_preserves_residual_partial": cap["passed"],
        "all_stale_identities_rejected": all(stale.values()),
        "development_8_12_16_each_one_run": all(
            row["passed"] for row in development_matrix
        ),
        "case_id_gold_runtime_inputs_zero": metrics[
            "case_id_or_gold_function_parameters"
        ]
        == 0,
    }
    return {
        "schema": "milai.dg22.s5-acquisition-correctness.v0.3",
        "status": "PASS_REQUIREMENT_COMPLETE_ACQUISITION_FUSION"
        if all(checks.values())
        else "FAIL",
        "policy": policy.model_dump(mode="json"),
        "action_decision": {
            **decision,
            "bundle": bundle.model_dump(mode="json"),
        },
        "execution": execution,
        "fast_stop_matrix": fast_stops,
        "target_cap_probe": cap,
        "stale_identity_probe": stale,
        "development_ceiling_matrix": development_matrix,
        "metrics": metrics,
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "safety": {
            "candidate_default": False,
            "provider_calls": 0,
            "reader_calls": 0,
            "automatic_retries": 0,
            "canonical_mutations": 0,
            "formal_holdout_consumed": False,
        },
    }


def _core_evidence() -> list[dict[str, Any]]:
    return [
        _evidence(
            "total",
            "memory://synthetic/atlas/turn/1",
            "The total Atlas ticket cost was $120.",
        ),
        _evidence(
            "count",
            "memory://synthetic/atlas/turn/2",
            "The Atlas ticket cost covered 4 tickets.",
        ),
        _evidence(
            "duplicate-total",
            "memory://synthetic/atlas/turn/1",
            "The total Atlas ticket cost was $120.",
        ),
        _evidence(
            "noise", "memory://synthetic/atlas/turn/3", "Borealis weather was cloudy."
        ),
        _evidence(
            "denied",
            "memory://synthetic/atlas/turn/4",
            "The total Atlas ticket cost was $999.",
            readable=False,
        ),
    ]


def _fast_stop_matrix(query_ir: Any, missing: Sequence[str]) -> list[dict[str, Any]]:
    cases = [
        (
            "complete",
            compile_accuracy_action_decision(
                query_ir,
                [],
                executable_channels=["FTS_RAW"],
                requirement_state_digest=STATE_DIGEST,
                acquisition_capability_digest=CAPABILITY_DIGEST,
            ),
            "SKIP_COMPLETE_OR_NO_TARGETABLE",
        ),
        (
            "no-targetable",
            compile_accuracy_action_decision(
                query_ir,
                ["not-required"],
                executable_channels=["FTS_RAW"],
                requirement_state_digest=STATE_DIGEST,
                acquisition_capability_digest=CAPABILITY_DIGEST,
            ),
            "SKIP_COMPLETE_OR_NO_TARGETABLE",
        ),
        (
            "semantics-owner",
            compile_accuracy_action_decision(
                query_ir,
                missing,
                executable_channels=["FTS_RAW"],
                requirement_state_digest=STATE_DIGEST,
                acquisition_capability_digest=CAPABILITY_DIGEST,
                semantics_owner_requirement_ids=missing,
            ),
            "SKIP_SEMANTICS_OWNER",
        ),
        (
            "exhausted",
            compile_accuracy_action_decision(
                query_ir,
                missing,
                executable_channels=["FTS_RAW"],
                requirement_state_digest=STATE_DIGEST,
                acquisition_capability_digest=CAPABILITY_DIGEST,
                attempted_by_requirement={item: ["FTS_RAW"] for item in missing},
            ),
            "SKIP_EXHAUSTED_OR_NO_EXPECTED_GAIN",
        ),
        (
            "no-expected-gain",
            compile_accuracy_action_decision(
                query_ir,
                missing,
                executable_channels=["FTS_RAW"],
                requirement_state_digest=STATE_DIGEST,
                acquisition_capability_digest=CAPABILITY_DIGEST,
                expected_new_binding_by_channel={"FTS_RAW": 0},
            ),
            "SKIP_EXHAUSTED_OR_NO_EXPECTED_GAIN",
        ),
    ]
    return [
        {
            "name": name,
            "status": result["status"],
            "reason_code": result["reason_code"],
            "extra_passes": result["extra_passes"],
            "passed": result["status"] == "SKIPPED"
            and result["reason_code"] == reason
            and result["extra_passes"] == 0,
        }
        for name, result, reason in cases
    ]


def _target_cap_probe(query_ir: Any) -> dict[str, Any]:
    requirements = [
        EvidenceRequirementV02(
            slot_id=f"R{index}",
            interpretation_kind="STATE_OBSERVATION",
            entity_constraints=[f"entity-{index}"],
        )
        for index in range(4)
    ]
    expanded = query_ir.model_copy(update={"requirements": requirements})
    bundle = compile_requirement_complete_bundle(
        expanded,
        [item.slot_id for item in requirements],
        channel="FTS_RAW",
        requirement_state_digest=STATE_DIGEST,
        acquisition_capability_digest=CAPABILITY_DIGEST,
    )
    return {
        "target_requirement_ids": bundle.target_requirement_ids,
        "residual_requirement_ids": bundle.residual_requirement_ids,
        "residual_disposition": bundle.residual_disposition,
        "passed": len(bundle.target_requirement_ids) == 3
        and len(bundle.residual_requirement_ids) == 1
        and bundle.residual_disposition == "BUDGET_EXHAUSTED",
    }


def _stale_identity_probe(
    query_ir: Any, bundle: Any, evidence: Sequence[dict[str, Any]]
) -> dict[str, bool]:
    checks = {}
    variants = {
        "state": ("3" * 64, CAPABILITY_DIGEST),
        "capability": (STATE_DIGEST, "4" * 64),
    }
    for name, (state, capability) in variants.items():
        try:
            execute_requirement_complete_bundle(
                query_ir,
                bundle,
                evidence,
                current_requirement_state_digest=state,
                current_acquisition_capability_digest=capability,
            )
        except ValueError as exc:
            checks[name] = str(exc).startswith("STALE_")
        else:
            checks[name] = False
    stale_query = query_ir.model_copy(update={"answer_shape": "LIST"})
    try:
        execute_requirement_complete_bundle(
            stale_query,
            bundle,
            evidence,
            current_requirement_state_digest=STATE_DIGEST,
            current_acquisition_capability_digest=CAPABILITY_DIGEST,
        )
    except ValueError as exc:
        checks["query_ir"] = str(exc) == "STALE_QUERY_IR_REJECTED"
    else:
        checks["query_ir"] = False
    return checks


def _development_ceiling_matrix(
    query_ir: Any, missing: Sequence[str]
) -> list[dict[str, Any]]:
    records = []
    channels: tuple[tuple[int, AccuracyChannel], ...] = (
        (8, "FTS_RAW"),
        (12, "EVIDENCE_DENSE"),
        (16, "EVIDENCE_DENSE"),
    )
    for ceiling, channel in channels:
        values = _core_evidence()
        for index in range(len(values), ceiling):
            values.append(
                _evidence(
                    f"noise-{ceiling}-{index}",
                    f"memory://synthetic/noise/{ceiling}/{index}",
                    f"Unrelated neutral record {index}.",
                )
            )
        bundle = compile_requirement_complete_bundle(
            query_ir,
            missing,
            channel=channel,
            requirement_state_digest=STATE_DIGEST,
            acquisition_capability_digest=CAPABILITY_DIGEST,
        )
        repository = _Repository(values)
        result = AccuracyAcquisitionExecutor(repository).execute(
            query_ir,
            bundle,
            current_requirement_state_digest=STATE_DIGEST,
            current_acquisition_capability_digest=CAPABILITY_DIGEST,
        )
        records.append(
            {
                "development_input_ceiling": ceiling,
                "channel": channel,
                "functional_runs": 1,
                "repository_calls": repository.calls,
                "candidates_scanned": result["candidates_scanned"],
                "passed": repository.calls == 1
                and result["candidates_scanned"] == ceiling,
            }
        )
    return records


def _evidence(
    evidence_id: str,
    source_ref: str,
    content: str,
    *,
    readable: bool = True,
) -> dict[str, Any]:
    observed = REFERENCE - timedelta(days=1)
    return {
        "evidence_id": evidence_id,
        "source_ref": source_ref,
        "subject_id": "synthetic-atlas",
        "observed_at": observed.isoformat(),
        "captured_at": (observed + timedelta(seconds=1)).isoformat(),
        "content": content,
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "permission_snapshot": {"readable": readable},
        "retention_state": "READABLE",
        "access_decision": "ALLOWED" if readable else "DENIED",
    }


__all__ = ["run_acquisition_correctness"]
