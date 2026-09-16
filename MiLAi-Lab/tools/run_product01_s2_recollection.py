#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from milai_lab.harness.artifacts import RunArtifacts  # noqa: E402
from milai_lab.product_adapter.manifest import (  # noqa: E402
    load_product_lock,
    verify_product_lock,
)
from milai_lab.recollection_gate import (  # noqa: E402
    accepted_binding_reference_integrity,
    admitted_dg28_groups,
    dg28_target_source_refs,
    evaluate_recollection_result,
)
from run_product01_s1_context_preflight import (  # noqa: E402
    RuntimeHttpClient,
    _capture_case,
    _case_project,
    _dataset_path,
    _history_events,
    _load_env,
    _load_population,
    _observed_at,
    _wait_projection,
)

EXPECTED_PRODUCT_COMMIT = "fd9674e9ff0abe4db0449dc2a987710fea014c47"
EXPECTED_PRODUCT_LOCK_DIGEST = (
    "7b3039e7ca99631417a967835aa390add55e92d4c56de385d7fb0305e2a10dd7"
)
SYNTHETIC_REFERENCE_TIME = "2026-09-01T00:00:00+00:00"
TARGET_GROUP_COUNT = 7


class RecollectionGateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ArmSpec:
    arm_id: str
    base_url: str
    env_file: Path
    candidate_enabled: bool


@dataclass(frozen=True, slots=True)
class SyntheticQuery:
    case_id: str
    query: str
    project_id: str
    true_source_refs: tuple[str, ...]
    false_source_refs: tuple[str, ...]
    forbidden_source_refs: tuple[str, ...] = ()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Product-01 S2 paired black-box recollection gate"
    )
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument(
        "--product-lock",
        type=Path,
        default=ROOT / "data/locks/product01-s2-product.lock.json",
    )
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=ROOT / "data/manifests/longmemeval-s-cleaned-500.json",
    )
    parser.add_argument("--dg28-lock", type=Path, required=True)
    parser.add_argument("--b0-env-file", type=Path, required=True)
    parser.add_argument("--b1-env-file", type=Path, required=True)
    parser.add_argument("--b0-base-url", default="http://127.0.0.1:38180")
    parser.add_argument("--b1-base-url", default="http://127.0.0.1:38181")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-concurrency", type=int, default=8)
    return parser


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().casefold() in {"1", "true", "yes", "on"}


def _validate_arm_environment(spec: ArmSpec) -> dict[str, str]:
    values = _load_env(spec.env_file)
    if not values.get("MILAI_AGENT_OPERATOR_TOKEN"):
        raise RecollectionGateError(f"{spec.arm_id} lacks the operator token")
    observed_candidate = _truthy(
        values.get("MILAI_RETRIEVAL_TYPE_DIRECTED_ACQUISITION_ENABLED")
    )
    if observed_candidate != spec.candidate_enabled:
        raise RecollectionGateError(f"{spec.arm_id} candidate flag does not match its arm")
    if _truthy(values.get("MILAI_RETRIEVAL_EVIDENCE_DENSE_ENABLED")):
        raise RecollectionGateError(f"{spec.arm_id} must not enable Evidence Dense")
    if _truthy(values.get("MILAI_RETRIEVAL_DETERMINISTIC_RECOVERY_ENABLED")):
        raise RecollectionGateError(f"{spec.arm_id} must use exactly one acquisition phase")
    provider = values.get("MILAI_EMBEDDING_PROVIDER", "deterministic_hash")
    if provider != "deterministic_hash":
        raise RecollectionGateError(f"{spec.arm_id} embedding provider drifted")
    return values


def _synthetic_event(
    label: str,
    content: str,
    *,
    project_id: str,
    speaker: str = "user",
    readable: bool = True,
) -> dict[str, Any]:
    session_id = f"p01-s2:{label}"
    return {
        "operation_id": f"p01-s2-capture-{label}",
        "payload": {
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"s2://{label}/turn/0",
            "subject_id": f"p01-s2:{project_id}",
            "speaker": speaker,
            "source_context": {
                "session_id": session_id,
                "turn_id": f"{session_id}:turn:0",
                "turn_ordinal": 0,
                "round_id": f"{session_id}:round:0",
                "round_ordinal": 0,
                "previous_turn_id": None,
                "next_turn_id": None,
            },
            "observed_at": SYNTHETIC_REFERENCE_TIME,
            "content": content,
            "data_classification": "SYNTHETIC",
            "permission_snapshot": {
                "readable": readable,
                "project_ids": [project_id],
            },
            "retention_state": "READABLE",
        },
    }


def _synthetic_fixture() -> tuple[list[dict[str, Any]], tuple[SyntheticQuery, ...]]:
    events = [
        _synthetic_event(
            "lookup-true",
            "My bicycle lock is cobalt blue.",
            project_id="p01-s2-lookup",
        ),
        _synthetic_event(
            "lookup-question",
            "What color is my bicycle lock?",
            project_id="p01-s2-lookup",
        ),
        _synthetic_event(
            "lookup-intention",
            "I want to make my bicycle lock cobalt blue.",
            project_id="p01-s2-lookup",
        ),
        _synthetic_event(
            "lookup-wrong-subject",
            "My bicycle helmet is cobalt blue.",
            project_id="p01-s2-lookup",
        ),
        _synthetic_event(
            "lookup-cross-scope",
            "My bicycle lock is signal red.",
            project_id="p01-s2-other",
        ),
        _synthetic_event(
            "lookup-unreadable",
            "My bicycle lock is emerald green.",
            project_id="p01-s2-lookup",
            readable=False,
        ),
        _synthetic_event(
            "personal-user",
            "My studio door code is 4821.",
            project_id="p01-s2-personal-role",
        ),
        _synthetic_event(
            "personal-assistant",
            "My studio door code is 9999.",
            project_id="p01-s2-personal-role",
            speaker="assistant",
        ),
        _synthetic_event(
            "role-free-assistant",
            "The cobalt launch code is 47.",
            project_id="p01-s2-role-free",
            speaker="assistant",
        ),
        _synthetic_event(
            "wrong-complete-question",
            "What color is my camping tent?",
            project_id="p01-s2-wrong-complete",
        ),
        _synthetic_event(
            "wrong-complete-intention",
            "I plan to paint my camping tent orange.",
            project_id="p01-s2-wrong-complete",
        ),
        _synthetic_event(
            "wrong-complete-subject",
            "My camping stove is orange.",
            project_id="p01-s2-wrong-complete",
        ),
        _synthetic_event(
            "revoked",
            "My backup lock is amber.",
            project_id="p01-s2-revoked",
        ),
    ]
    queries = (
        SyntheticQuery(
            case_id="ordinary_lookup_mixed_controls",
            query="What color is my bicycle lock?",
            project_id="p01-s2-lookup",
            true_source_refs=("s2://lookup-true/turn/0",),
            false_source_refs=(
                "s2://lookup-question/turn/0",
                "s2://lookup-intention/turn/0",
                "s2://lookup-wrong-subject/turn/0",
            ),
            forbidden_source_refs=(
                "s2://lookup-cross-scope/turn/0",
                "s2://lookup-unreadable/turn/0",
            ),
        ),
        SyntheticQuery(
            case_id="personal_source_role",
            query="What is my studio door code?",
            project_id="p01-s2-personal-role",
            true_source_refs=("s2://personal-user/turn/0",),
            false_source_refs=("s2://personal-assistant/turn/0",),
        ),
        SyntheticQuery(
            case_id="role_free_assistant_answer",
            query="What is the cobalt launch code?",
            project_id="p01-s2-role-free",
            true_source_refs=("s2://role-free-assistant/turn/0",),
            false_source_refs=(),
        ),
        SyntheticQuery(
            case_id="strict_wrong_complete",
            query="What color is my camping tent?",
            project_id="p01-s2-wrong-complete",
            true_source_refs=(),
            false_source_refs=(
                "s2://wrong-complete-question/turn/0",
                "s2://wrong-complete-intention/turn/0",
                "s2://wrong-complete-subject/turn/0",
            ),
        ),
        SyntheticQuery(
            case_id="revoked_read_path",
            query="What color is my backup lock?",
            project_id="p01-s2-revoked",
            true_source_refs=(),
            false_source_refs=(),
            forbidden_source_refs=("s2://revoked/turn/0",),
        ),
    )
    return events, queries


async def _resolve(
    reader: RuntimeHttpClient,
    *,
    query: str,
    project_id: str,
    reference_time: str,
    max_results: int,
) -> dict[str, Any]:
    return await reader.request(
        "POST",
        "/v1/memory/resolve",
        {
            "query": query,
            "requested_scope": {"project_ids": [project_id]},
            "required_authority": "INFORMATIONAL",
            "required_freshness": "CURRENT",
            "consistency_mode": "CANONICAL_REQUIRED",
            "reference_time": reference_time,
            "budget": {
                "max_results": max_results,
                "max_context_tokens": 8_192,
                "max_latency_ms": 2_000,
            },
        },
    )


def _ids_for_refs(
    identities: Mapping[str, Mapping[str, str]], source_refs: Sequence[str]
) -> tuple[str, ...]:
    by_source = {value["source_ref"]: evidence_id for evidence_id, value in identities.items()}
    missing = set(source_refs).difference(by_source)
    if missing:
        raise RecollectionGateError("captured source identity is missing")
    return tuple(by_source[source_ref] for source_ref in source_refs)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RecollectionGateError(f"{name} is missing or invalid")
    return value


def _trace_controls(result: Mapping[str, Any]) -> dict[str, Any]:
    search = _mapping(result.get("search_trace"), "search trace")
    state = _mapping(search.get("acquisition_state"), "acquisition state")
    capability = _mapping(search.get("acquisition_capability"), "acquisition capability")
    channels = _mapping(capability.get("channels"), "acquisition channels")
    dispositions = search.get("acquisition_probe_dispositions")
    if not isinstance(dispositions, list) or any(
        not isinstance(item, Mapping) for item in dispositions
    ):
        raise RecollectionGateError("probe dispositions are invalid")
    compile_trace = _mapping(
        _mapping(result.get("memory_context"), "memory context").get("compile_trace"),
        "compile trace",
    )
    dense_executed = sum(
        item.get("channel") == "EVIDENCE_DENSE" and item.get("status") == "EXECUTED"
        for item in dispositions
    )
    enriched_executed = sum(
        item.get("channel") == "FTS_ENRICHED" and item.get("status") == "EXECUTED"
        for item in dispositions
    )
    prior = state.get("prior_action_digests")
    if not isinstance(prior, list) or any(not isinstance(item, str) for item in prior):
        raise RecollectionGateError("acquisition action trace is invalid")
    residual_calls = state.get("residual_model_call_count")
    hidden_calls = compile_trace.get("hidden_model_calls")
    if not isinstance(residual_calls, int) or not isinstance(hidden_calls, int):
        raise RecollectionGateError("model call trace is invalid")
    return {
        "acquisition_phase_count": len(prior),
        "model_provider_policy_call_count": residual_calls + hidden_calls,
        "automatic_semantic_retry_count": 0,
        "canonical_mutation_count": int(
            state.get("canonical_mutation") is not False
            or compile_trace.get("canonical_mutation") is not False
        ),
        "dense_channel_status": _mapping(
            channels.get("EVIDENCE_DENSE"), "Dense capability"
        ).get("status"),
        "dense_probe_executed_count": dense_executed,
        "enriched_channel_status": _mapping(
            channels.get("FTS_ENRICHED"), "enriched capability"
        ).get("status"),
        "enriched_probe_executed_count": enriched_executed,
        "deterministic_recovery_present": "deterministic_recovery" in search,
    }


def _result_digest_trace(result: Mapping[str, Any]) -> dict[str, Any]:
    memory_context = _mapping(result.get("memory_context"), "memory context")
    compile_trace = _mapping(memory_context.get("compile_trace"), "compile trace")
    raw_value = compile_trace.get("raw_retrieval_trace")
    raw = raw_value if isinstance(raw_value, Mapping) else None
    admitted_value = compile_trace.get("admitted_evidence_trace")
    admitted = admitted_value if isinstance(admitted_value, Mapping) else None
    accepted = result.get("accepted_binding_evidence_refs")
    if not isinstance(accepted, list) or any(not isinstance(item, str) for item in accepted):
        raise RecollectionGateError("accepted binding refs are invalid")
    return {
        "status": result.get("status"),
        "sufficiency_status": _mapping(
            result.get("sufficiency_decision"), "sufficiency decision"
        ).get("status"),
        "accepted_binding_count": len(accepted),
        "raw_candidate_count": (
            raw.get("candidate_count")
            if raw is not None
            else len(result.get("items", []))
            if isinstance(result.get("items"), list)
            else 0
        ),
        "raw_trace_sha256": raw.get("trace_sha256") if raw is not None else None,
        "admitted_trace_sha256": (
            admitted.get("trace_sha256") if admitted is not None else None
        ),
        "decision_snapshot_digest": compile_trace.get("decision_snapshot_digest"),
        "reader_evidence_plan_digest": compile_trace.get("reader_evidence_plan_digest"),
    }


async def _run_arm(
    spec: ArmSpec,
    *,
    records: Mapping[str, Mapping[str, Any]],
    target_refs: Mapping[str, str],
    capture_concurrency: int,
) -> list[dict[str, Any]]:
    env = _validate_arm_environment(spec)
    submitter = RuntimeHttpClient(
        spec.base_url,
        env["MILAI_AGENT_SUBMITTER_TOKEN"],
        max_connections=capture_concurrency,
    )
    reader = RuntimeHttpClient(spec.base_url, env["MILAI_AGENT_READER_TOKEN"], max_connections=4)
    operator = RuntimeHttpClient(
        spec.base_url,
        env["MILAI_AGENT_OPERATOR_TOKEN"],
        max_connections=2,
    )
    cells: list[dict[str, Any]] = []
    try:
        capabilities = await reader.request("GET", "/v1/capabilities")
        if capabilities.get("contract_version") != "agent.v1":
            raise RecollectionGateError(f"{spec.arm_id} agent contract is incompatible")

        synthetic_events, synthetic_queries = _synthetic_fixture()
        outbox_ids, synthetic_identities = await _capture_case(
            submitter,
            synthetic_events,
            concurrency=capture_concurrency,
        )
        await _wait_projection(reader, outbox_ids)
        revoked_id = _ids_for_refs(synthetic_identities, ("s2://revoked/turn/0",))[0]
        revocation = await operator.request(
            "POST",
            f"/v1/evidence/{revoked_id}/revoke",
            {"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
            operation_id="p01-s2-revoke-read-path",
        )
        revocation_outbox = revocation.get("outbox_id")
        if isinstance(revocation_outbox, str):
            await _wait_projection(reader, [revocation_outbox])

        for query in synthetic_queries:
            started = time.perf_counter()
            result = await _resolve(
                reader,
                query=query.query,
                project_id=query.project_id,
                reference_time=SYNTHETIC_REFERENCE_TIME,
                max_results=12,
            )
            metrics = evaluate_recollection_result(
                result,
                identities=synthetic_identities,
                true_evidence_ids=_ids_for_refs(
                    synthetic_identities, query.true_source_refs
                ),
                false_evidence_ids=_ids_for_refs(
                    synthetic_identities, query.false_source_refs
                ),
                forbidden_evidence_ids=_ids_for_refs(
                    synthetic_identities, query.forbidden_source_refs
                ),
            )
            cell = {
                "arm_id": spec.arm_id,
                "case_id": query.case_id,
                "case_kind": "SYNTHETIC_BINDING_CONTROL",
                "status": "OBSERVED",
                "elapsed_ms": round((time.perf_counter() - started) * 1_000, 6),
                "metrics": metrics.to_dict(),
                "trace": _result_digest_trace(result),
                "controls": _trace_controls(result),
            }
            cells.append(cell)
            print(
                json.dumps(
                    {
                        "arm": spec.arm_id,
                        "case": query.case_id,
                        "accepted": metrics.accepted_count,
                        "false": metrics.false_accepted_count,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

        for case_id in sorted(records):
            record = records[case_id]
            events = _history_events(record)
            outbox_ids, identities = await _capture_case(
                submitter,
                events,
                concurrency=capture_concurrency,
            )
            await _wait_projection(reader, outbox_ids)
            started = time.perf_counter()
            result = await _resolve(
                reader,
                query=str(record["question"]),
                project_id=_case_project(case_id),
                reference_time=_observed_at(record["question_date"]),
                max_results=50,
            )
            case_targets = {
                group_id: source_ref
                for group_id, source_ref in target_refs.items()
                if group_id.startswith(f"{case_id}:")
            }
            admitted_groups = admitted_dg28_groups(result, case_targets)
            accepted_raw = result.get("accepted_binding_evidence_refs")
            if not isinstance(accepted_raw, list):
                raise RecollectionGateError("DG28 accepted binding refs are invalid")
            accepted_source_refs = {
                identities[str(evidence_id)]["source_ref"]
                for evidence_id in accepted_raw
                if str(evidence_id) in identities
            }
            bound_groups = tuple(
                sorted(
                    group_id
                    for group_id, source_ref in case_targets.items()
                    if source_ref in accepted_source_refs
                )
            )
            cell = {
                "arm_id": spec.arm_id,
                "case_id": case_id,
                "case_kind": "DG28_MANIPULATION_CHECK",
                "status": "OBSERVED",
                "capture_count": len(events),
                "elapsed_ms": round((time.perf_counter() - started) * 1_000, 6),
                "metrics": {
                    "target_group_count": len(case_targets),
                    "admitted_target_group_count": len(admitted_groups),
                    "bound_target_group_count": len(bound_groups),
                    "accepted_reference_integrity": accepted_binding_reference_integrity(
                        result, identities
                    ),
                },
                "admitted_target_groups": list(admitted_groups),
                "bound_target_groups": list(bound_groups),
                "trace": _result_digest_trace(result),
                "controls": _trace_controls(result),
            }
            cells.append(cell)
            print(
                json.dumps(
                    {
                        "arm": spec.arm_id,
                        "case": case_id,
                        "dg28_admitted": len(admitted_groups),
                        "dg28_targets": len(case_targets),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    finally:
        await submitter.close()
        await reader.close()
        await operator.close()
    return cells


def _aggregate_arm(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    synthetic = [cell for cell in cells if cell["case_kind"] == "SYNTHETIC_BINDING_CONTROL"]
    dg28 = [cell for cell in cells if cell["case_kind"] == "DG28_MANIPULATION_CHECK"]
    accepted = sum(
        int(_mapping(cell["metrics"], "metrics")["accepted_count"])
        for cell in synthetic
    )
    true_accepted = sum(
        int(_mapping(cell["metrics"], "metrics")["true_accepted_count"])
        for cell in synthetic
    )
    expected_true = 3
    admitted_groups = {
        str(group_id)
        for cell in dg28
        for group_id in cell.get("admitted_target_groups", [])
    }
    bound_groups = {
        str(group_id)
        for cell in dg28
        for group_id in cell.get("bound_target_groups", [])
    }
    all_controls = [_mapping(cell["controls"], "controls") for cell in cells]
    all_metrics = [_mapping(cell["metrics"], "metrics") for cell in synthetic]
    dg_reference = [
        float(_mapping(cell["metrics"], "metrics")["accepted_reference_integrity"])
        for cell in dg28
    ]
    return {
        "case_count": len(cells),
        "synthetic_case_count": len(synthetic),
        "dg28_case_count": len(dg28),
        "asserted_binding_count": accepted,
        "true_binding_count": true_accepted,
        "asserted_semantic_binding_precision": (
            true_accepted / accepted if accepted else 0.0
        ),
        "true_binding_coverage": true_accepted / expected_true,
        "known_false_relation_accepted": sum(
            int(metric["false_accepted_count"]) for metric in all_metrics
        ),
        "strict_wrong_complete": sum(
            int(metric["strict_wrong_complete_count"]) for metric in all_metrics
        ),
        "accepted_reference_integrity": min(
            [float(metric["reference_integrity"]) for metric in all_metrics]
            + dg_reference
        ),
        "evidence_set_binding_exactness": min(
            float(metric["evidence_set_binding_exactness"]) for metric in all_metrics
        ),
        "permission_revocation_scope_leak": sum(
            int(metric["forbidden_candidate_count"])
            + int(metric["forbidden_accepted_count"])
            for metric in all_metrics
        ),
        "canonical_mutation_count": sum(
            int(control["canonical_mutation_count"]) for control in all_controls
        ),
        "dg28_opportunity_admitted_count": len(admitted_groups),
        "dg28_opportunity_admitted_coverage": len(admitted_groups) / TARGET_GROUP_COUNT,
        "dg28_target_binding_count": len(bound_groups),
        "model_provider_policy_calls": sum(
            int(control["model_provider_policy_call_count"])
            for control in all_controls
        ),
        "automatic_semantic_retries": 0,
        "acquisition_phase_counts": sorted(
            {int(control["acquisition_phase_count"]) for control in all_controls}
        ),
        "dense_probe_executed_count": sum(
            int(control["dense_probe_executed_count"]) for control in all_controls
        ),
        "enriched_probe_executed_count": sum(
            int(control["enriched_probe_executed_count"]) for control in all_controls
        ),
        "deterministic_recovery_present_count": sum(
            bool(control["deterministic_recovery_present"]) for control in all_controls
        ),
        "exact_source_span_failure_count": sum(
            int(metric["exact_source_span_failure_count"]) for metric in all_metrics
        ),
    }


def _b1_gate(b0: Mapping[str, Any], b1: Mapping[str, Any]) -> tuple[bool, dict[str, bool]]:
    mediator_gain = (
        float(b1["asserted_semantic_binding_precision"])
        > float(b0["asserted_semantic_binding_precision"])
        or float(b1["true_binding_coverage"]) > float(b0["true_binding_coverage"])
        or int(b1["dg28_opportunity_admitted_count"])
        > int(b0["dg28_opportunity_admitted_count"])
    )
    checks = {
        "AcceptedReferenceIntegrity": b1["accepted_reference_integrity"] == 1.0,
        "SemanticBindingPrecision": b1["asserted_semantic_binding_precision"] >= 0.95,
        "KnownFalseRelationAccepted": b1["known_false_relation_accepted"] == 0,
        "StrictWrongComplete": b1["strict_wrong_complete"] == 0,
        "PermissionRevocationScopeLeak": b1["permission_revocation_scope_leak"] == 0,
        "DG28OpportunityAdmittedCoverage": b1["dg28_opportunity_admitted_count"] >= 6,
        "ModelProviderPolicyCalls": b1["model_provider_policy_calls"] == 0,
        "AutomaticSemanticRetries": b1["automatic_semantic_retries"] == 0,
        "ExactlyOneAcquisitionPhase": b1["acquisition_phase_counts"] == [1],
        "DenseCapabilityNotInvented": b1["dense_probe_executed_count"] == 0,
        "CanonicalReadMutation": b1["canonical_mutation_count"] == 0,
        "EvidenceSetBindingExactness": b1["evidence_set_binding_exactness"] == 1.0,
        "ExactSourceSpanFailures": b1["exact_source_span_failure_count"] == 0,
        "DeterministicRecoveryAbsent": b1["deterministic_recovery_present_count"] == 0,
        "StableMediatorGain": mediator_gain,
    }
    return all(checks.values()), checks


async def _run(args: argparse.Namespace) -> int:
    if args.output.exists():
        raise RecollectionGateError("run output already exists")
    if not 1 <= args.capture_concurrency <= 8:
        raise RecollectionGateError("capture concurrency must be between 1 and 8 per arm")

    lock = load_product_lock(args.product_lock)
    verification = verify_product_lock(lock, args.product_root)
    if not verification.valid:
        raise RecollectionGateError("Product pin failed: " + "; ".join(verification.errors))
    if lock.git_commit != EXPECTED_PRODUCT_COMMIT or lock.digest != EXPECTED_PRODUCT_LOCK_DIGEST:
        raise RecollectionGateError("Product commit or lock digest is outside the S2 contract")

    dataset_path, dataset_sha256 = _dataset_path(args.dataset_manifest)
    population = _load_population(dataset_path)
    dg28_raw = json.loads(args.dg28_lock.read_text(encoding="utf-8"))
    target_groups_raw = _mapping(
        _mapping(dg28_raw, "DG28 lock").get("S0_freeze"), "DG28 freeze"
    ).get("target_groups")
    if not isinstance(target_groups_raw, list) or any(
        not isinstance(item, Mapping) for item in target_groups_raw
    ):
        raise RecollectionGateError("DG28 target groups are invalid")
    if len(target_groups_raw) != TARGET_GROUP_COUNT:
        raise RecollectionGateError("DG28 target denominator drifted")
    case_ids = {str(item["case_id"]) for item in target_groups_raw}
    records = {
        str(item["question_id"]): item
        for item in population
        if str(item.get("question_id")) in case_ids
    }
    if set(records) != case_ids:
        raise RecollectionGateError("DG28 cases are absent from the pinned dataset")
    target_refs = dg28_target_source_refs(records, target_groups_raw)
    target_digest = _canonical_sha256(target_refs)

    arms = (
        ArmSpec("B0_REPAIRED_UNTREATED", args.b0_base_url, args.b0_env_file, False),
        ArmSpec("B1_SIMPLE_RECALL", args.b1_base_url, args.b1_env_file, True),
    )
    for arm in arms:
        _validate_arm_environment(arm)

    artifacts = RunArtifacts(args.output)
    run_id = f"product01-s2-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    started_at = datetime.now(UTC)
    run_payload = {
        "schema_version": "milai-product01-s2-run-v1",
        "run_id": run_id,
        "status": "RUNNING",
        "started_at": started_at.isoformat(),
        "arm_kind": "PRODUCT_BLACK_BOX",
        "arms": [arm.arm_id for arm in arms],
        "treatment_delta": {
            "MILAI_RETRIEVAL_TYPE_DIRECTED_ACQUISITION_ENABLED": {
                "B0_REPAIRED_UNTREATED": False,
                "B1_SIMPLE_RECALL": True,
            }
        },
        "product_commit": lock.git_commit,
        "product_lock_digest": lock.digest,
        "product_tree_sha256": lock.tree_sha256,
        "dataset_sha256": dataset_sha256,
        "dg28_run_lock_sha256": hashlib.sha256(args.dg28_lock.read_bytes()).hexdigest(),
        "dg28_target_mapping_digest": target_digest,
        "synthetic_case_count_per_arm": 5,
        "dg28_case_count_per_arm": len(records),
        "capture_concurrency_per_arm": args.capture_concurrency,
        "formal_holdout_consumed": False,
        "reader_calls": 0,
        "answer_calls": 0,
        "judge_calls": 0,
        "policy_model_calls": 0,
        "automatic_semantic_retries": 0,
    }
    artifacts.write_json("run.json", run_payload)

    arm_cells = await asyncio.gather(
        *(
            _run_arm(
                arm,
                records=records,
                target_refs=target_refs,
                capture_concurrency=args.capture_concurrency,
            )
            for arm in arms
        )
    )
    cells = [cell for values in arm_cells for cell in values]
    for cell in cells:
        artifacts.append_jsonl("cases.jsonl", dict(cell))

    aggregates = {
        arm.arm_id: _aggregate_arm(values)
        for arm, values in zip(arms, arm_cells, strict=True)
    }
    b0 = aggregates[arms[0].arm_id]
    b1 = aggregates[arms[1].arm_id]
    passed, checks = _b1_gate(b0, b1)
    metrics_payload = {
        "schema_version": "milai-product01-s2-metrics-v1",
        "run_id": run_id,
        "status": "PASS" if passed else "FAIL",
        "arm_metrics": aggregates,
        "b1_exit_checks": checks,
        "reader_calls": 0,
        "answer_calls": 0,
        "judge_calls": 0,
        "formal_holdout_consumed": False,
    }
    artifacts.write_json("metrics.json", metrics_payload)
    finished_at = datetime.now(UTC)
    terminal = {
        "schema_version": "milai-product01-s2-terminal-v1",
        "run_id": run_id,
        "status": (
            "PASS_S2_SIMPLE_RECALL_READY_FOR_LOCAL_USABILITY"
            if passed
            else "FAIL_S2_REPAIR_REQUIRED"
        ),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 6),
        "product_commit": lock.git_commit,
        "product_lock_digest": lock.digest,
        "dataset_sha256": dataset_sha256,
        "dg28_target_mapping_digest": target_digest,
        "metrics_sha256": _canonical_sha256(metrics_payload),
        "selected_arm": "B1_SIMPLE_RECALL" if passed else "B0_REPAIRED_UNTREATED",
        "candidate_default_enabled": False,
        "rollback_flag": "MILAI_RETRIEVAL_TYPE_DIRECTED_ACQUISITION_ENABLED=false",
        "next_scope": "S3_LOCAL_READY" if passed else "S2_GENERAL_REPAIR_ONLY",
        "formal_holdout_consumed": False,
        "canonical_mutation_count": b1["canonical_mutation_count"],
    }
    artifacts.write_json("terminal.json", terminal)
    print(json.dumps(terminal, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if passed else 1


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(f"S2 recollection gate failed closed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
