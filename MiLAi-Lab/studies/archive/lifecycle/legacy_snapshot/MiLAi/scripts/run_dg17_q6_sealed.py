#!/usr/bin/env python3
"""Score sealed Q1R same-snapshot generations as DG-17 Q6."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest

from evals.dg14.benchmark import _atomic_json
from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg16.lme10 import load_public_dev_cases, load_public_dev_labels
from evals.dg17.measurement import (
    DG16_RECEIPT_PATH,
    DG16_RECEIPT_SHA256,
    load_answer_bearing_labels,
)
from evals.dg17.q1r_causality import (
    POLICIES,
    Q1RCausalityError,
    audit_generation_pairs,
    validate_context_archive,
)
from evals.dg17.q6_matched import (
    evaluate_development_gate,
    score_matched_records,
    summarize_matched_records,
)
from evals.paper.provider import MODEL_ID
from scripts.run_dg17_q6_matched import _load_shadow, _shadow_cost_overlay

DEFAULT_OUTPUT_ROOT = ROOT / "var/dg17/q6"
LEGACY_POLICY, CURRENT_POLICY = POLICIES
PREFLIGHT_STATUS = "Q6_PREFLIGHT_COMPLETE_EXECUTION_AUTHORIZED"


class Q6SealedRunError(RuntimeError):
    """A bound Q6 predecessor, sealed denominator, or scoring contract failed."""


def run(
    *,
    run_id: str,
    output_root: Path,
    preflight: Path,
    preflight_sha256: str,
    q1r_context_archive: Path,
    q1r_context_archive_sha256: str,
    q1r_context_producer: Path,
    q1r_context_producer_sha256: str,
    q1r_generation_archive: Path,
    q1r_generation_archive_sha256: str,
    q1r_matched_receipt: Path,
    q1r_matched_receipt_sha256: str,
    q3c_shadow_report: Path,
    q3c_shadow_report_sha256: str,
) -> dict[str, Any]:
    if output_root.exists():
        raise Q6SealedRunError("output exists; choose a fresh run ID")
    preflight_value = _load_bound(
        preflight, preflight_sha256, expected_status=PREFLIGHT_STATUS
    )
    if preflight_value.get("execution_authorized") is not True:
        raise Q6SealedRunError("bound Q6 preflight does not authorize sealed scoring")

    contexts_value = _load_bound(
        q1r_context_archive,
        q1r_context_archive_sha256,
        expected_status="SUCCEEDED",
    )
    producer = _load_bound(
        q1r_context_producer,
        q1r_context_producer_sha256,
        expected_status="SUCCEEDED",
    )
    generations_value = _load_bound(
        q1r_generation_archive,
        q1r_generation_archive_sha256,
        expected_status="SUCCEEDED",
    )
    q1r = _load_bound(
        q1r_matched_receipt,
        q1r_matched_receipt_sha256,
        expected_status="Q1R_CONTEXT_STABILITY_PASS",
    )
    shadow = _load_bound(
        q3c_shadow_report,
        q3c_shadow_report_sha256,
        expected_status="Q3C_SHADOW_CHARACTERIZED",
    )
    _load_shadow(q3c_shadow_report)
    _validate_predecessor_bindings(
        preflight_value=preflight_value,
        q1r=q1r,
        producer=producer,
        context_sha256=q1r_context_archive_sha256,
        generation_sha256=q1r_generation_archive_sha256,
        shadow_sha256=q3c_shadow_report_sha256,
    )

    cases, selection = load_public_dev_cases()
    case_ids = [str(case.case_id) for case in cases]
    try:
        contexts = validate_context_archive(contexts_value, case_ids=case_ids)
    except Q1RCausalityError as exc:
        raise Q6SealedRunError("sealed Q1R Context archive failed Q6 validation") from exc
    raw_generations = generations_value.get("records")
    if not isinstance(raw_generations, list) or any(
        not isinstance(row, Mapping) for row in raw_generations
    ):
        raise Q6SealedRunError("sealed Q1R generation archive is malformed")
    generations = [dict(row) for row in raw_generations]
    questions = {
        str(case.case_id): (str(case.question), str(case.question_at)) for case in cases
    }
    try:
        pair_audits = audit_generation_pairs(generations, questions=questions)
    except Q1RCausalityError as exc:
        raise Q6SealedRunError("sealed Q1R Provider pairs failed Q6 validation") from exc
    if (
        len(pair_audits) != 20
        or any(row["quality_attribution"] != "CAUSALLY_VALID" for row in pair_audits)
        or generations_value.get("historical_answer_reuse") is not False
        or generations_value.get("labels_loaded") is not False
    ):
        raise Q6SealedRunError("Q6 same-snapshot causal denominator is incomplete")

    output_root.mkdir(parents=True)
    scoring_started = time.perf_counter()
    _envelope, labeled_cases, answer_labels = load_answer_bearing_labels()
    if tuple(case.case_id for case in labeled_cases) != tuple(case_ids):
        raise Q6SealedRunError("Q6 answer-bearing label order drifted")
    scoring_labels, scoring_identity = load_public_dev_labels(tuple(case_ids))
    plans = _plans(cases)
    contexts_by_cell = {
        (str(row["case_id"]), int(row["token_budget"]), str(row["policy"])): row
        for row in contexts
    }
    source_events_by_case = _source_events_by_case(contexts_value, case_ids=case_ids)
    scoring_records = [
        _scoring_record(
            generation,
            context=contexts_by_cell[
                (
                    str(generation["case_id"]),
                    int(generation["token_budget"]),
                    str(generation["policy"]),
                )
            ],
            source_events=source_events_by_case[str(generation["case_id"])],
        )
        for generation in generations
    ]
    scored_by_policy: dict[str, list[dict[str, Any]]] = {}
    summaries_by_policy: dict[str, dict[str, Any]] = {}
    for policy in POLICIES:
        policy_records = [row for row in scoring_records if row["policy"] == policy]
        scored = score_matched_records(
            policy_records,
            cases=cases,
            labels=answer_labels,
            scoring_labels=scoring_labels,
            plans=plans,
        )
        scored_by_policy[policy] = scored
        summaries_by_policy[policy] = summarize_matched_records(scored)

    current_records = scored_by_policy[CURRENT_POLICY]
    gate = evaluate_development_gate(
        summaries_by_policy[CURRENT_POLICY], current_records
    )
    gate["checks"]["same_snapshot_pair_count_20"] = len(pair_audits) == 20
    gate["checks"]["causally_valid_matched_cells_100_percent"] = all(
        row["quality_attribution"] == "CAUSALLY_VALID" for row in pair_audits
    )
    gate["status"] = "PASS" if all(gate["checks"].values()) else "PARTIAL"

    if _sha256(DG16_RECEIPT_PATH) != DG16_RECEIPT_SHA256:
        raise Q6SealedRunError("frozen DG16 reference receipt drifted")
    baseline = json.loads(DG16_RECEIPT_PATH.read_text(encoding="utf-8"))
    if not isinstance(baseline, dict):
        raise Q6SealedRunError("frozen DG16 reference receipt is malformed")
    current_summaries = summaries_by_policy[CURRENT_POLICY]
    semantic_cost_overlay = _shadow_cost_overlay(shadow, current_summaries)
    governance = _governance_from_sealed_contexts(contexts)
    scoring_wall_ms = (time.perf_counter() - scoring_started) * 1_000
    receipt = {
        "schema": "milai.dg17.q6-sealed-same-snapshot-confirmation.v0.2",
        "status": "Q6_MATCHED_PASS" if gate["status"] == "PASS" else "CHARACTERIZED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / MATCHED_CHARACTERIZATION",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": [],
        "configuration": {
            "case_count": 10,
            "token_budgets": [512, 2048],
            "policies": list(POLICIES),
            "reader_model_id": MODEL_ID,
            "automatic_retries": 0,
            "fresh_provider_calls_in_bound_window": 40,
            "provider_calls_during_q6_scoring": 0,
            "historical_answer_reuse": False,
            "same_snapshot_pair_count": 20,
        },
        "selection": selection,
        "bound_artifacts": {
            "preflight": _identity(preflight, preflight_sha256),
            "q1r_context_archive": _identity(
                q1r_context_archive, q1r_context_archive_sha256
            ),
            "q1r_context_producer": _identity(
                q1r_context_producer, q1r_context_producer_sha256
            ),
            "q1r_generation_archive": _identity(
                q1r_generation_archive, q1r_generation_archive_sha256
            ),
            "q1r_matched_receipt": _identity(
                q1r_matched_receipt, q1r_matched_receipt_sha256
            ),
            "q3c_shadow_report": _identity(
                q3c_shadow_report, q3c_shadow_report_sha256
            ),
        },
        "execution_identity": {
            "planned_window_id": generations_value["planned_window_id"],
            "prompt_contract_sha256": q1r["configuration"][
                "prompt_contract_sha256"
            ],
            "generation_contract_sha256": q1r["configuration"][
                "generation_contract_sha256"
            ],
            "reader_model_id": q1r["configuration"]["reader_model_id"],
        },
        "product_plane": {
            "labels_loaded_during_generation": False,
            "runtime_context_owner": "RUNTIME",
            "retrieval_executions": producer["retrieval_execution_count"],
            "policy_context_count": producer["policy_context_count"],
            "fresh_reader_calls": q1r["configuration"]["provider_main_calls"],
            "semantic_assist_calls": 0,
            "semantic_repair_calls": 0,
        },
        "scoring_plane": {
            "labels_opened_after_generation_archive_sealed": True,
            "label_source": scoring_identity,
            "scored_record_count": sum(len(rows) for rows in scored_by_policy.values()),
        },
        "arms": {
            "DG16_CURRENT": summaries_by_policy[LEGACY_POLICY],
            "BM25_T": baseline["summaries"]["LME-BM25-T"],
            "DG17_DETERMINISTIC_ONLY": current_summaries,
            "DG17_ONE_CALL_SEMANTIC_REPAIR": {"status": "PARKED_NOT_NEEDED"},
        },
        "arm_evidence_role": {
            "DG16_CURRENT": "FRESH_SAME_SNAPSHOT_CAUSAL_ARM",
            "DG17_DETERMINISTIC_ONLY": "FRESH_SAME_SNAPSHOT_CAUSAL_ARM",
            "BM25_T": "FROZEN_REFERENCE_NOT_Q6_CAUSAL_ARM",
            "DG17_ONE_CALL_SEMANTIC_REPAIR": "NOT_EXECUTED",
        },
        "counterfactual_cost_overlays": {
            "DG17_MINIMAL_SEMANTIC_QUERY_HINT_SHADOW_COST": semantic_cost_overlay
        },
        "records": [row for policy in POLICIES for row in scored_by_policy[policy]],
        "matched_causality": {
            "status": "PASS",
            "pair_count": len(pair_audits),
            "causally_valid_count": len(pair_audits),
            "pair_audits": pair_audits,
        },
        "gate": gate,
        "governance_safety": governance,
        "efficiency": {
            "context_production_wall_ms": producer["experiment_wall_ms"],
            "provider_window_wall_ms": q1r["experiment_wall_ms"],
            "q6_scoring_wall_ms": round(scoring_wall_ms, 6),
            "reader_calls": q1r["configuration"]["provider_main_calls"],
            "retrieval_executions": producer["retrieval_execution_count"],
            "automatic_retries": 0,
        },
        "release_claim_authorized": False,
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def _validate_predecessor_bindings(
    *,
    preflight_value: Mapping[str, Any],
    q1r: Mapping[str, Any],
    producer: Mapping[str, Any],
    context_sha256: str,
    generation_sha256: str,
    shadow_sha256: str,
) -> None:
    bindings = preflight_value.get("artifact_bindings")
    if not isinstance(bindings, Mapping):
        raise Q6SealedRunError("Q6 preflight lacks artifact bindings")
    expected = {
        "q1r_context_archive": context_sha256,
        "q1r_generation_archive": generation_sha256,
        "q3c_live_shadow": shadow_sha256,
    }
    if any(
        not isinstance(bindings.get(name), Mapping)
        or bindings[name].get("sha256") != digest
        for name, digest in expected.items()
    ):
        raise Q6SealedRunError("Q6 preflight predecessor binding drifted")
    if (
        q1r.get("context_archive", {}).get("sha256") != context_sha256
        or q1r.get("generation_archive", {}).get("sha256") != generation_sha256
        or q1r.get("gate", {}).get("status") != "PASS"
        or producer.get("context_archive", {}).get("sha256") != context_sha256
    ):
        raise Q6SealedRunError("Q1R sealed artifact lineage drifted")


def _plans(cases: Sequence[Any]) -> dict[str, Any]:
    planner = QueryPlanner()
    plans: dict[str, Any] = {}
    for case in cases:
        reference_time = datetime.fromisoformat(normalize_lme_timestamp(case.question_at))
        plans[str(case.case_id)] = planner.plan(
            RetrievalRequest(
                route="L1",
                query=str(case.question),
                as_of=reference_time,
                system_as_of=reference_time,
            )
        )
    return plans


def _source_events_by_case(
    archive: Mapping[str, Any], *, case_ids: Sequence[str]
) -> dict[str, dict[str, Mapping[str, Any]]]:
    snapshots = archive.get("snapshots")
    if not isinstance(snapshots, list):
        raise Q6SealedRunError("Q1R Context archive lacks Evidence snapshots")
    result: dict[str, dict[str, Mapping[str, Any]]] = {}
    for raw in snapshots:
        if not isinstance(raw, Mapping):
            raise Q6SealedRunError("Q1R Evidence snapshot is malformed")
        case_id = str(raw.get("case_id", ""))
        snapshot = raw.get("evidence_snapshot")
        events = snapshot.get("source_events") if isinstance(snapshot, Mapping) else None
        if not isinstance(events, list) or any(
            not isinstance(event, Mapping) for event in events
        ):
            raise Q6SealedRunError("Q1R source-event snapshot is malformed")
        indexed = {str(event["source_ref"]): event for event in events}
        if len(indexed) != len(events):
            raise Q6SealedRunError("Q1R source-event identity is not unique")
        result[case_id] = indexed
    if set(result) != set(case_ids):
        raise Q6SealedRunError("Q1R source-event snapshot denominator drifted")
    return result


def _scoring_record(
    generation: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    source_events: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    mediators = context.get("semantic_mediators")
    if not isinstance(mediators, Mapping):
        raise Q6SealedRunError("Q1R semantic mediator record is missing")
    selected = mediators.get("selected_source_refs")
    if not isinstance(selected, list) or any(not isinstance(ref, str) for ref in selected):
        raise Q6SealedRunError("Q1R selected source-ref trace is malformed")
    semantic_refs = _semantic_source_refs(mediators, selected=selected)
    missing = [ref for ref in semantic_refs if ref not in source_events]
    if missing:
        raise Q6SealedRunError("Q1R selected source ref is absent from sealed snapshot")
    evidence_items = []
    retrieval_trace = []
    for source_ref in semantic_refs:
        event = source_events[source_ref]
        role = str(event["role"])
        content = str(event["content"])
        session_id = str(event["original_session_id"])
        evidence_items.append(
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": str(event["evidence_id"]),
                "source_ref": source_ref,
                "session_id": session_id,
                "observed_at": str(event["observed_at"]),
                "captured_at": str(event["observed_at"]),
                "content": f"{role}: {content}",
            }
        )
        retrieval_trace.append(
            {
                "source_id": source_ref,
                "session_id": session_id,
                "source_ref": source_ref,
            }
        )
    return {
        **dict(generation),
        "context": context["context"],
        "context_identity": context["context_identity"],
        "query_latency_ms": context["query_latency_ms"],
        "retrieval_trace": retrieval_trace,
        "selected_source_refs": list(selected),
        "semantic_evidence_source_refs": semantic_refs,
        "evidence_items": evidence_items,
        "derived_result": mediators.get("derived_result"),
        "sufficiency_decision": mediators.get("sufficiency"),
    }


def _semantic_source_refs(
    mediators: Mapping[str, Any], *, selected: Sequence[str]
) -> list[str]:
    """Union Reader prose refs with exact Runtime operator operand refs."""

    refs = list(selected)
    derived = mediators.get("derived_result")
    operands = derived.get("operands") if isinstance(derived, Mapping) else None
    if isinstance(operands, list):
        for operand in operands:
            if not isinstance(operand, Mapping):
                continue
            source_ref = operand.get("source_ref")
            if isinstance(source_ref, str) and source_ref and source_ref not in refs:
                refs.append(source_ref)
    return refs


def _governance_from_sealed_contexts(
    contexts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected = [
        (str(row["case_id"]), str(source_ref))
        for row in contexts
        for source_ref in row["semantic_mediators"]["selected_source_refs"]
    ]
    contamination = sum(
        not source_ref.startswith(f"longmemeval://case/{case_id}/")
        for case_id, source_ref in selected
    )
    forbidden = frozenset(
        {
            "answers",
            "answer_session_ids",
            "atoms",
            "gold_ir",
            "gold_operator",
            "join_relations",
            "expected_route",
            "expected_family",
            "scoring_labels",
        }
    )
    label_leaks = sum(_contains_forbidden_keys(row, forbidden) for row in contexts)
    canonical_mutations = sum(
        bool(row["semantic_mediators"]["scope_authority"]["canonical_mutation"])
        or bool((row["semantic_mediators"].get("derived_result") or {}).get("canonical_mutation"))
        for row in contexts
    )
    return {
        "status": "PARTIAL_DENIED_EVIDENCE_LIVE_DENOMINATOR_PENDING",
        "zero_denominator_is_pass": False,
        "counters": {
            "cross_case_contamination": {
                "denominator": len(selected),
                "accepted": contamination,
            },
            "evaluation_label_leakage": {
                "denominator": len(contexts),
                "accepted": label_leaks,
            },
            "canonical_mutation": {
                "denominator": len(contexts),
                "accepted": canonical_mutations,
            },
            "opaque_reader_identity": {
                "denominator": len(contexts),
                "accepted": 0,
                "measurement": "Q1R_CONTEXT_ARCHIVE_VALIDATOR",
            },
            "denied_evidence": {
                "denominator": 0,
                "accepted": 0,
                "status": "PENDING_SUCCESSOR_LIVE_DENOMINATOR",
            },
        },
    }


def _contains_forbidden_keys(value: object, forbidden: frozenset[str]) -> bool:
    if isinstance(value, Mapping):
        return bool(forbidden.intersection(value)) or any(
            _contains_forbidden_keys(item, forbidden) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_keys(item, forbidden) for item in value)
    return False


def _load_bound(path: Path, expected_sha256: str, *, expected_status: str) -> dict[str, Any]:
    if _sha256(path) != expected_sha256:
        raise Q6SealedRunError(f"bound artifact drifted: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("status") != expected_status:
        raise Q6SealedRunError(f"bound artifact status drifted: {path}")
    return value


def _identity(path: Path, sha256: str) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--preflight-sha256", required=True)
    parser.add_argument("--q1r-context-archive", type=Path, required=True)
    parser.add_argument("--q1r-context-archive-sha256", required=True)
    parser.add_argument("--q1r-context-producer", type=Path, required=True)
    parser.add_argument("--q1r-context-producer-sha256", required=True)
    parser.add_argument("--q1r-generation-archive", type=Path, required=True)
    parser.add_argument("--q1r-generation-archive-sha256", required=True)
    parser.add_argument("--q1r-matched-receipt", type=Path, required=True)
    parser.add_argument("--q1r-matched-receipt-sha256", required=True)
    parser.add_argument("--q3c-shadow-report", type=Path, required=True)
    parser.add_argument("--q3c-shadow-report-sha256", required=True)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run(
        run_id=args.run_id,
        output_root=output_root,
        preflight=args.preflight,
        preflight_sha256=args.preflight_sha256,
        q1r_context_archive=args.q1r_context_archive,
        q1r_context_archive_sha256=args.q1r_context_archive_sha256,
        q1r_context_producer=args.q1r_context_producer,
        q1r_context_producer_sha256=args.q1r_context_producer_sha256,
        q1r_generation_archive=args.q1r_generation_archive,
        q1r_generation_archive_sha256=args.q1r_generation_archive_sha256,
        q1r_matched_receipt=args.q1r_matched_receipt,
        q1r_matched_receipt_sha256=args.q1r_matched_receipt_sha256,
        q3c_shadow_report=args.q3c_shadow_report,
        q3c_shadow_report_sha256=args.q3c_shadow_report_sha256,
    )
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
                "receipt_sha256": _sha256(receipt_path),
                "gate": receipt["gate"],
                "summaries": {
                    "DG16_CURRENT": receipt["arms"]["DG16_CURRENT"],
                    "DG17_DETERMINISTIC_ONLY": receipt["arms"][
                        "DG17_DETERMINISTIC_ONLY"
                    ],
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
