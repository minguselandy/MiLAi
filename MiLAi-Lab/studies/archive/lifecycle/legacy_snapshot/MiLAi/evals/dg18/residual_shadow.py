"""Two-phase DG-18 R3 residual-refinding shadow and sealed scorer.

The product/shadow phase accepts only the label-free Q1R archive plus opened-
development question fields.  Evaluation labels are opened by the scorer only
after the product trace has been written into a digest-bound sealed archive.
Nothing in this module changes Runtime retrieval, Binding, Sufficiency, or an
MCP response.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, cast

from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_state import (
    acquisition_state_trace_summary,
    advance_acquisition_state,
    build_acquisition_action,
    initialize_acquisition_state,
    reserve_residual_controller_call,
)
from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.application.query_planner import QueryPlanner
from milai.application.residual_refinding import (
    ResidualHintShadowService,
    ResidualRefindingError,
    build_acquisition_observation,
    evaluate_residual_candidate_eligibility,
    validate_residual_search_hint,
)
from milai.application.semantic_hint import (
    SemanticHintCompletion,
    SemanticHintError,
    StructuredSemanticProvider,
)
from milai.domain.acquisition import (
    AcquisitionBudgetUse,
    AcquisitionPlan,
    AcquisitionResidualPolicy,
    AcquisitionState,
)
from milai.domain.residual_refinding import (
    ResidualControllerReceipt,
    ResidualControllerTiming,
    ResidualHintValidation,
    ResidualSearchHint,
)
from milai.domain.retrieval import RetrievalRequest
from milai.domain.semantic_query import EvidenceRequirementV02
from milai.domain.sufficiency import SufficiencyDecision
from milai.persistence.retrieval_repository import evidence_query_terms
from pydantic import ValidationError

from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg15.milai_mcp_adapter import compact_lme_source_ref
from evals.dg17.q1r_causality import canonical_sha256, validate_context_archive
from evals.paper.adapters.baselines import _bm25_scores

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_Q1R_ARCHIVE = (
    ROOT
    / "var/dg17/a2/dg17-a2-per-slot-fusion-20260827-004"
    / "product-contexts-001/contexts.json"
)
DEFAULT_LABELS_PATH = ROOT / "evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json"
PRODUCT_SHADOW_SCHEMA = "milai.dg18.r3-product-shadow.v0.1"
SEALED_SHADOW_SCHEMA = "milai.dg18.r3-sealed-shadow-archive.v0.1"
SCORE_SCHEMA = "milai.dg18.r3-shadow-score.v0.1"
POLICY = "DG17_QUERY_SPECIFIC_STOP"
TOKEN_BUDGET = 2_048
_FORBIDDEN_LABEL_KEYS = frozenset(
    {
        "answer",
        "answer_score",
        "atoms",
        "expected_answer",
        "gold",
        "gold_ir",
        "labels",
    }
)


class R3ShadowError(RuntimeError):
    """The R3 phase boundary, denominator, or sealed identity drifted."""


class _RecordingProvider:
    def __init__(self, delegate: StructuredSemanticProvider) -> None:
        self.delegate = delegate
        self.calls = 0
        self.last: SemanticHintCompletion | None = None

    def complete_structured(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        schema_name: str,
        schema: Mapping[str, Any],
        max_completion_tokens: int,
        seed: int,
    ) -> SemanticHintCompletion:
        self.calls += 1
        self.last = self.delegate.complete_structured(
            messages=messages,
            schema_name=schema_name,
            schema=schema,
            max_completion_tokens=max_completion_tokens,
            seed=seed,
        )
        return self.last


def opened_dev_questions() -> dict[str, dict[str, str]]:
    """Load question-time fields from the frozen label-free opened-dev input."""

    from evals.dg16.lme10 import load_public_dev_cases

    cases, _selection = load_public_dev_cases()
    return {
        str(case.case_id): {
            "question": str(case.question),
            "question_at": str(case.question_at),
        }
        for case in cases
    }


def run_product_shadow(
    *,
    run_id: str,
    q1r_archive_path: Path,
    questions: Mapping[str, Mapping[str, str]],
    provider: StructuredSemanticProvider | None,
    residual_capability_available: bool = True,
    candidate_cap: int = 8,
    provider_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run label-free product/shadow work and return an unsealed phase result."""

    if not run_id:
        raise ValueError("R3 shadow run ID is required")
    if candidate_cap < 1 or candidate_cap > 20:
        raise ValueError("R3 residual candidate cap must be between 1 and 20")
    archive = _load_object(q1r_archive_path)
    _reject_label_fields(archive)
    case_ids = list(questions)
    if len(case_ids) != 10 or len(set(case_ids)) != 10:
        raise R3ShadowError("R3 opened-development denominator must be ten cases")
    records = validate_context_archive(archive, case_ids=case_ids)
    deterministic = {
        str(record["case_id"]): record
        for record in records
        if record.get("policy") == POLICY
        and record.get("token_budget") == TOKEN_BUDGET
    }
    snapshots = _snapshot_index(archive, case_ids)
    if set(deterministic) != set(case_ids):
        raise R3ShadowError("R3 deterministic Q1R denominator drifted")

    rows: list[dict[str, Any]] = []
    for case_id in case_ids:
        question, question_at = _question_fields(questions[case_id])
        rows.append(
            _run_case_shadow(
                run_id=run_id,
                case_id=case_id,
                question=question,
                question_at=question_at,
                record=deterministic[case_id],
                snapshot=snapshots[case_id],
                provider=provider,
                residual_capability_available=residual_capability_available,
                candidate_cap=candidate_cap,
            )
        )
    provider_identities = sorted(
        {
            f"{controller['provider']}::{controller['model']}"
            for row in rows
            if isinstance((controller := row["controller"]).get("provider"), str)
            and isinstance(controller.get("model"), str)
        }
    )
    return {
        "schema": PRODUCT_SHADOW_SCHEMA,
        "status": "PRODUCT_SHADOW_COMPLETE_UNSCORED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / SHADOW_PRODUCT_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "label_fields_available": False,
        "labels_loaded": False,
        "q1r_archive": {
            "path": str(q1r_archive_path),
            "sha256": _sha256_file(q1r_archive_path),
            "run_id": archive.get("run_id"),
        },
        "fixed_controls": {
            "policy": POLICY,
            "token_budget": TOKEN_BUDGET,
            "candidate_cap": candidate_cap,
            "controller_calls_per_eligible_case_max": 1,
            "additional_passes_per_eligible_case_max": 1,
            "automatic_retry_max": 0,
            "product_result_consumes_hint": False,
        },
        "provider_identities": provider_identities,
        "provider_runtime_identity": (
            dict(provider_runtime_identity)
            if provider_runtime_identity is not None
            else None
        ),
        "case_count": len(rows),
        "rows": rows,
        "label_boundary": {
            "product_path_label_access_count": 0,
            "scorer_phase_started": False,
            "formal_holdout_consumed": False,
        },
    }


def seal_product_shadow(product_shadow: Mapping[str, Any], output_path: Path) -> dict[str, Any]:
    """Write a fresh digest-bound archive before any scoring label is opened."""

    if output_path.exists():
        raise R3ShadowError("R3 sealed shadow output already exists")
    payload = dict(product_shadow)
    _validate_product_shadow(payload)
    envelope = {
        "schema": SEALED_SHADOW_SCHEMA,
        "status": "SEALED_BEFORE_SCORING",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / SEALED_SHADOW_PRODUCT_PLANE",
        "formal_holdout_consumed": False,
        "label_fields_available": False,
        "product_shadow_sha256": canonical_sha256(payload),
        "product_shadow": payload,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as handle:
        handle.write(_canonical_bytes(envelope))
    return envelope


def score_sealed_shadow(
    sealed_shadow_path: Path,
    *,
    labels_path: Path = DEFAULT_LABELS_PATH,
) -> dict[str, Any]:
    """Open evaluation labels only after revalidating the sealed product archive."""

    envelope = _load_object(sealed_shadow_path)
    product = _validated_sealed_product(envelope)
    label_envelope, _cases, labels = _load_scoring_labels(labels_path)
    rows = product["rows"]
    if not isinstance(rows, list) or set(labels) != {
        str(row.get("case_id")) for row in rows if isinstance(row, Mapping)
    }:
        raise R3ShadowError("R3 scorer denominator drifted from sealed product rows")
    scored_rows = [
        _score_case(cast(Mapping[str, Any], row), labels[str(row["case_id"])])
        for row in rows
    ]
    aggregate = _aggregate_score(scored_rows)
    provider_identities = _string_list(
        product.get("provider_identities"), "provider identities"
    )
    aggregate["provider_identities"] = provider_identities
    runtime_identity = product.get("provider_runtime_identity")
    hard_gate = _hard_gate(
        scored_rows,
        aggregate,
        provider_identities,
        runtime_identity if isinstance(runtime_identity, Mapping) else None,
    )
    manipulation = _mapping(aggregate, "manipulation_check")
    treatment_delivered = manipulation.get("TreatmentDelivered") is True
    if not treatment_delivered:
        treatment_outcome = "TREATMENT_NOT_DELIVERED"
        residual_effect_outcome = "RESIDUAL_EFFECT_NOT_EVALUATED"
        disposition = "PARKED_PROVIDER_CONTRACT_INCOMPATIBLE"
    elif hard_gate["passed"]:
        treatment_outcome = "VALID_TREATMENT_DELIVERED"
        residual_effect_outcome = "MEDIATOR_GAIN_GATE_PASSED"
        disposition = "PASS_TO_R4_REVIEW"
    else:
        treatment_outcome = "VALID_TREATMENT_DELIVERED"
        residual_effect_outcome = (
            "MEDIATOR_GAIN_NOT_OBSERVED_AFTER_VALID_TREATMENT"
        )
        disposition = "PARKED_NO_MEDIATOR_GAIN"
    return {
        "schema": SCORE_SCHEMA,
        "status": "R3_SHADOW_SCORED",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "run_id": product["run_id"],
        "formal_holdout_consumed": False,
        "sealed_product_shadow": {
            "path": str(sealed_shadow_path),
            "sha256": _sha256_file(sealed_shadow_path),
            "product_shadow_sha256": envelope["product_shadow_sha256"],
        },
        "label_source": {
            "path": str(labels_path),
            "sha256": _sha256_file(labels_path),
            "schema": label_envelope.get("schema"),
        },
        "label_boundary": {
            "product_path_label_access_count": 0,
            "scorer_label_access_count": 1,
            "scoring_started_after_product_seal": True,
            "formal_holdout_consumed": False,
        },
        "aggregate": aggregate,
        "hard_gate": hard_gate,
        "treatment_delivery_outcome": treatment_outcome,
        "residual_effect_outcome": residual_effect_outcome,
        "disposition": disposition,
        "rows": scored_rows,
    }


def _run_case_shadow(
    *,
    run_id: str,
    case_id: str,
    question: str,
    question_at: datetime,
    record: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    provider: StructuredSemanticProvider | None,
    residual_capability_available: bool,
    candidate_cap: int,
) -> dict[str, Any]:
    mediators = _mapping(record, "semantic_mediators")
    requirements = _requirements(mediators)
    sufficiency = _mapping(mediators, "sufficiency")
    missing_ids = _string_list(sufficiency.get("missing_slots"), "missing slots")
    required_ids = [item.slot_id for item in requirements if item.required]
    if not set(missing_ids).issubset(required_ids):
        raise R3ShadowError("Q1R missing requirement is absent from typed requirements")
    sources = _sources(snapshot, case_id)
    source_by_ref = {str(item["compact_source_ref"]): item for item in sources}
    baseline_refs = _baseline_refs(mediators)
    if any(value not in source_by_ref for value in baseline_refs):
        raise R3ShadowError("Q1R selected candidate is absent from its sealed snapshot")
    baseline_binding = _binding_summary(
        requirements, [source_by_ref[value] for value in baseline_refs]
    )
    product_digest = canonical_sha256(
        {
            "semantic_mediator_digest": record.get("semantic_mediator_digest"),
            "selected_source_refs": baseline_refs,
            "sufficiency": sufficiency,
        }
    )
    activation_reason = "ELIGIBLE"
    if not missing_ids:
        activation_reason = (
            "DETERMINISTIC_COMPLETE"
            if sufficiency.get("status") == "COMPLETE"
            else "NO_TYPED_MISSING_REQUIREMENT"
        )
    elif not residual_capability_available or provider is None:
        activation_reason = "RESIDUAL_CAPABILITY_UNAVAILABLE"
    eligible = activation_reason == "ELIGIBLE"
    controller: dict[str, Any] = {
        "attempted": False,
        "schema_valid": None,
        "error": None,
        "model_call_count": 0,
        "automatic_retry_count": 0,
        "provider": None,
        "model": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "latency_ms": None,
        "transport_mode": None,
        "http_status": None,
        "stream_finish_state": None,
        "sse_error_observed": False,
        "error_classification_correct": None,
        "validation_error_field_path": None,
        "validation_error_type": None,
        "receipt": None,
    }
    validation: ResidualHintValidation | None = None
    governance_negative_lane: list[dict[str, Any]] = []
    simulation = _empty_simulation(
        baseline_refs=baseline_refs,
        binding=baseline_binding,
        candidate_cap=candidate_cap,
    )
    if eligible:
        plan, state = _shadow_plan_state(
            case_id=case_id,
            question=question,
            question_at=question_at,
            requirements=requirements,
            missing_ids=missing_ids,
            candidate_cap=candidate_cap,
            baseline_candidate_count=len(baseline_refs),
        )
        observation = build_acquisition_observation(
            query=question,
            requirements=requirements,
            candidates=[source_by_ref[value] for value in baseline_refs],
            state=state,
            plan=plan,
        )
        if provider is None:
            raise R3ShadowError("eligible R3 case lacks a controller provider")
        recording = _RecordingProvider(provider)
        controller["attempted"] = True
        controller["model_call_count"] = 1
        reservation = reserve_residual_controller_call(state, plan)
        if reservation.outcome != "APPLIED":
            raise R3ShadowError(
                f"R3 controller reservation failed: {reservation.reason_code}"
            )
        reserved_state = reservation.state
        governance_negative_lane = _governance_negative_lane(
            plan=plan,
            state=reserved_state,
            sources=sources,
        )
        try:
            receipt = ResidualHintShadowService(recording).generate(
                run_id=run_id,
                case_id=case_id,
                observation=observation,
                state=reserved_state,
                plan=plan,
            )
            if recording.last is not None:
                controller.update(_completion_fields(recording.last))
            controller.update(_controller_fields(receipt))
            controller["schema_valid"] = True
            controller["error_classification_correct"] = True
            controller["receipt"] = _durable_controller_receipt(receipt)
            validation = validate_residual_search_hint(
                hint=receipt.hint,
                state=reserved_state,
                plan=plan,
            )
            if validation.status == "ACCEPTED":
                simulation = _simulate_hint(
                    hint=receipt.hint,
                    requirements=requirements,
                    sources=sources,
                    baseline_refs=baseline_refs,
                    candidate_cap=min(
                        candidate_cap,
                        reserved_state.remaining_budget.candidate_count,
                    ),
                )
                simulation["state_transition"] = _residual_state_transition(
                    state=reserved_state,
                    plan=plan,
                    validation=validation,
                    simulation=simulation,
                )
        except (ResidualRefindingError, SemanticHintError) as exc:
            controller["schema_valid"] = False
            controller["error"] = _typed_controller_error_code(exc)
            if recording.last is not None:
                controller.update(_completion_fields(recording.last))
            controller.update(_controller_error_fields(exc))
        if recording.calls != 1:
            raise R3ShadowError("R3 controller logical call ceiling violated")
        if recording.last is not None and (
            recording.last.provider_calls != 1
            or recording.last.automatic_retry_count != 0
        ):
            raise R3ShadowError("R3 provider retry/call contract violated")

    return {
        "case_id": case_id,
        "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
        "total_source_turn_count": len(sources),
        "activation": {
            "assessed": True,
            "eligible": eligible,
            "activated": controller["attempted"],
            "reason": activation_reason,
        },
        "deterministic": {
            "candidate_refs": baseline_refs,
            "candidate_count": len(baseline_refs),
            "required_requirement_ids": required_ids,
            "missing_requirement_ids": missing_ids,
            "sufficiency_status": sufficiency.get("status"),
            "binding": baseline_binding,
        },
        "controller": controller,
        "hint_validation": (
            validation.model_dump(mode="json") if validation is not None else None
        ),
        "offline_simulation": simulation,
        "governance_negative_lane": governance_negative_lane,
        "product_result": {
            "before_sha256": product_digest,
            "after_sha256": product_digest,
            "changed": False,
            "hint_consumed_by_product": False,
            "canonical_mutation": False,
            "scope_or_authority_expanded": False,
            "sufficiency_status_after": sufficiency.get("status"),
        },
    }


def _governance_negative_lane(
    *,
    plan: AcquisitionPlan,
    state: AcquisitionState,
    sources: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Exercise every Goal 10.1 negative through a real schema or eligibility gate."""

    safe_control: dict[str, Any] | None = None
    safe = None
    for source in sources:
        candidate = dict(source)
        event_range = plan.global_constraints.event_occurrence_range
        if event_range is not None:
            candidate["event_occurrence_interval"] = {
                key: event_range[key] for key in ("start", "end") if key in event_range
            }
        source_range = plan.global_constraints.source_observed_range
        if source_range is not None:
            candidate["observed_at"] = source_range.get("start") or source_range.get("end")
        receipt = evaluate_residual_candidate_eligibility(raw=candidate, plan=plan)
        if receipt.eligible:
            safe_control = candidate
            safe = receipt
            break
    if safe_control is None or safe is None:
        raise R3ShadowError("R3 adversarial lane has no eligible control source")
    attacks: list[dict[str, Any]] = []

    def candidate_attack(name: str, source: Mapping[str, Any]) -> None:
        receipt = evaluate_residual_candidate_eligibility(raw=source, plan=plan)
        attacks.append(
            {
                "metric": name,
                "accepted": receipt.eligible,
                "disposition": receipt.reason_code,
            }
        )

    candidate_attack(
        "WrongScopeAcceptance",
        {**safe_control, "scope_predicate": {}},
    )
    candidate_attack(
        "UnauthorizedAuthorityExpansion",
        {**safe_control, "authority_class": "CANONICAL_STATE"},
    )
    candidate_attack(
        "RevokedEvidenceAcceptance",
        {**safe_control, "revoked_at": plan.global_constraints.system_as_of.isoformat()},
    )
    permission_unknown = dict(safe_control)
    permission_unknown["permission_snapshot"] = {}
    candidate_attack("PermissionUnknownAcceptance", permission_unknown)
    candidate_attack(
        "CrossTenantCandidateAcceptance",
        {**safe_control, "tenant_id": "adversarial-other-tenant"},
    )
    candidate_attack("HiddenFallback", {**safe_control, "fallback_used": True})

    base_hint = {
        "schema_version": "residual-search-hint-v0.1",
        "requirement_id": state.missing_requirement_ids[0],
        "action": "NO_ACTION",
        "lexical_cues": {},
        "temporal_cue": {"axis": "NO_CHANGE"},
        "source_preference": "NO_CHANGE",
        "cue_provenance": "OBSERVATION",
        "rationale_code": "NO_SAFE_ACTION",
    }

    def schema_attack(name: str, extra: Mapping[str, Any]) -> None:
        accepted = True
        disposition = "SCHEMA_ACCEPTED"
        try:
            ResidualSearchHint.model_validate({**base_hint, **extra})
        except ValidationError:
            accepted = False
            disposition = "SCHEMA_REJECTED"
        attacks.append(
            {"metric": name, "accepted": accepted, "disposition": disposition}
        )

    schema_attack("ModelSelectedFinalEvidence", {"evidence_id": "evidence-forged"})
    schema_attack("ModelDeclaredComplete", {"complete": True})

    wrong_complete = True
    wrong_complete_disposition = "RECEIPT_ACCEPTED"
    try:
        ResidualControllerReceipt.model_validate(
            {
                "hint": base_hint,
                "provider": "adversarial-provider",
                "model": "adversarial-model",
                "prompt_digest": "a" * 64,
                "schema_digest": "b" * 64,
                "observation_digest": "c" * 64,
                "seed": 0,
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "tokenizer_latency_ms": 0,
                "timing": ResidualControllerTiming(
                    queue_ms=0,
                    ttft_ms=0,
                    decode_ms=0,
                    total_ms=0,
                ).model_dump(mode="json"),
                "product_result_changed": True,
            }
        )
    except ValidationError:
        wrong_complete = False
        wrong_complete_disposition = "RECEIPT_REJECTED"
    attacks.append(
        {
            "metric": "WrongComplete",
            "accepted": wrong_complete,
            "disposition": wrong_complete_disposition,
        }
    )
    return attacks


def _shadow_plan_state(
    *,
    case_id: str,
    question: str,
    question_at: datetime,
    requirements: Sequence[EvidenceRequirementV02],
    missing_ids: Sequence[str],
    candidate_cap: int,
    baseline_candidate_count: int,
) -> tuple[AcquisitionPlan, AcquisitionState]:
    query_plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=question,
            requested_scope={"opened_dev_case_id": case_id},
            as_of=question_at,
            system_as_of=question_at,
        )
    )
    compiled = compile_acquisition_plan(
        query_plan,
        query=question,
        principal_scope={"opened_dev_case_id": case_id},
        authority_floor="INFORMATIONAL",
        candidate_limit=min(256, baseline_candidate_count + candidate_cap),
        context_tokens=TOKEN_BUDGET,
        tenant_id="opened-dev-public-v1",
        principal_id="dg18-shadow-controller-v01",
    )
    plan_payload = compiled.model_dump(mode="json")
    plan_payload["residual_policy"] = AcquisitionResidualPolicy(
        allowed=True,
        max_model_calls=1,
        max_extra_passes=1,
    ).model_dump(mode="json")
    plan = AcquisitionPlan.model_validate(plan_payload)
    initial = initialize_acquisition_state(plan, requirements)
    missing = list(dict.fromkeys(missing_ids))
    satisfied = [
        value for value in initial.required_requirement_ids if value not in set(missing)
    ]
    payload = initial.model_dump(mode="json")
    payload["missing_requirement_ids"] = missing
    payload["satisfied_requirement_ids"] = satisfied
    coverage = cast(dict[str, dict[str, Any]], payload["per_requirement_coverage"])
    for requirement_id, value in coverage.items():
        value["covered_by_sufficiency"] = requirement_id in satisfied
    initial = AcquisitionState.model_validate(payload)
    action = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=initial.missing_requirement_ids,
        probe_ids=[probe.probe_id for probe in plan.probes],
    )
    deterministic = advance_acquisition_state(
        initial,
        action,
        sufficiency_decision=SufficiencyDecision(
            status=("UNSATISFIED" if not satisfied else "PARTIAL"),
            covered_slots=satisfied,
            missing_slots=missing,
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        budget_use=AcquisitionBudgetUse(
            candidate_count=min(baseline_candidate_count, plan.budget.candidate_count)
        ),
    )
    if deterministic.outcome != "APPLIED":
        raise R3ShadowError(
            f"R3 deterministic state transition failed: {deterministic.reason_code}"
        )
    return plan, deterministic.state


def _simulate_hint(
    *,
    hint: ResidualSearchHint,
    requirements: Sequence[EvidenceRequirementV02],
    sources: Sequence[Mapping[str, Any]],
    baseline_refs: Sequence[str],
    candidate_cap: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    ranked = _hint_ranking(hint, sources, baseline_refs)
    baseline_set = set(baseline_refs)
    new_refs: list[str] = []
    repeated = 0
    for source_ref in ranked:
        if source_ref in baseline_set:
            repeated += 1
            continue
        if source_ref not in new_refs:
            new_refs.append(source_ref)
        if len(new_refs) >= candidate_cap:
            break
    combined = list(dict.fromkeys([*baseline_refs, *new_refs]))
    source_by_ref = {str(item["compact_source_ref"]): item for item in sources}
    wrong_scope = sum(
        value not in source_by_ref
        or not value.startswith(f"{sources[0]['case_id']!s}:s")
        for value in new_refs
    ) if sources else len(new_refs)
    binding = _binding_summary(
        requirements,
        [source_by_ref[value] for value in combined if value in source_by_ref],
    )
    context_token_count = sum(
        max(1, math.ceil(len(str(source_by_ref[value]["content"])) / 4))
        for value in new_refs
        if value in source_by_ref
    )
    return {
        "attempted": True,
        "candidate_cap": candidate_cap,
        "candidate_refs": new_refs,
        "new_candidate_refs": new_refs,
        "new_candidate_count": len(new_refs),
        "combined_candidate_refs": combined,
        "combined_candidate_count": len(combined),
        "repeated_region_count": repeated,
        "wrong_scope_candidate_count": wrong_scope,
        "latency_ms": round((time.perf_counter() - started) * 1_000, 6),
        "context_token_count": context_token_count,
        "binding": binding,
        "canonical_mutation": False,
        "product_result_changed": False,
    }


def _residual_state_transition(
    *,
    state: AcquisitionState,
    plan: AcquisitionPlan,
    validation: ResidualHintValidation,
    simulation: Mapping[str, Any],
) -> dict[str, Any]:
    action_kind = (
        validation.action
        if validation.action in {"EXPAND_NEIGHBORS", "EXPAND_EPISODE"}
        else "RESIDUAL_PASS"
    )
    action = build_acquisition_action(
        action_kind=cast(Any, action_kind),
        pass_index=1,
        requirement_ids=[validation.requirement_id],
        probe_ids=[probe.probe_id for probe in plan.probes],
    )
    transition = advance_acquisition_state(
        state,
        action,
        budget_use=AcquisitionBudgetUse(
            acquisition_passes=1,
            candidate_count=int(simulation["new_candidate_count"]),
            context_tokens=int(simulation["context_token_count"]),
            latency_ms=float(simulation["latency_ms"]),
        ),
    )
    return {
        "outcome": transition.outcome,
        "reason_code": transition.reason_code,
        "state": acquisition_state_trace_summary(transition.state),
    }


def _durable_controller_receipt(
    receipt: ResidualControllerReceipt,
) -> dict[str, Any]:
    """Persist controller identity/cost and cue digest, never hint text or snippets."""

    return {
        "schema_version": receipt.schema_version,
        "requirement_id": receipt.hint.requirement_id,
        "action": receipt.hint.action,
        "rationale_code": receipt.hint.rationale_code,
        "cue_provenance": receipt.hint.cue_provenance,
        "cue_digest": canonical_sha256(receipt.hint.model_dump(mode="json")),
        "provider": receipt.provider,
        "model": receipt.model,
        "prompt_digest": receipt.prompt_digest,
        "schema_digest": receipt.schema_digest,
        "observation_digest": receipt.observation_digest,
        "seed": receipt.seed,
        "prompt_tokens": receipt.prompt_tokens,
        "completion_tokens": receipt.completion_tokens,
        "tokenizer_latency_ms": receipt.tokenizer_latency_ms,
        "timing": receipt.timing.model_dump(mode="json"),
        "model_call_count": receipt.model_call_count,
        "automatic_retry_count": receipt.automatic_retry_count,
        "product_result_changed": receipt.product_result_changed,
        "canonical_mutation": receipt.canonical_mutation,
    }


def _typed_controller_error_code(exc: BaseException) -> str:
    prefix = str(exc).split(":", 1)[0].strip()
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", prefix):
        return prefix
    return re.sub(r"[^A-Z0-9]+", "_", type(exc).__name__.upper()).strip("_")


def _hint_ranking(
    hint: ResidualSearchHint,
    sources: Sequence[Mapping[str, Any]],
    baseline_refs: Sequence[str],
) -> list[str]:
    if hint.action == "SEARCH_LEXICAL":
        cues = hint.lexical_cues
        query = " ".join(
            [*cues.terms, *cues.phrases, *cues.entity_aliases, *cues.predicate_rephrasings]
        )
        query_terms = evidence_query_terms(query)
        corpus = [evidence_query_terms(str(item["content"])) for item in sources]
        scores = _bm25_scores(corpus, query_terms)
        order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
        return [
            str(sources[index]["compact_source_ref"])
            for index in order
            if scores[index] > 0
        ]
    if hint.action == "SEARCH_TEMPORAL":
        start = hint.temporal_cue.start
        end = hint.temporal_cue.end
        eligible: list[tuple[float, str]] = []
        for item in sources:
            observed = _aware_datetime(item.get("observed_at"))
            if observed is None:
                continue
            if start is not None and observed < start:
                continue
            if end is not None and observed > end:
                continue
            target = start or end or observed
            eligible.append(
                (abs((observed - target).total_seconds()), str(item["compact_source_ref"]))
            )
        return [value for _distance, value in sorted(eligible)]
    source_by_ref = {str(item["compact_source_ref"]): item for item in sources}
    anchors = [source_by_ref[value] for value in baseline_refs if value in source_by_ref]
    if hint.action == "EXPAND_NEIGHBORS":
        ranked: list[tuple[int, int, int, str]] = []
        for anchor in anchors:
            for item in sources:
                if item["original_session_id"] != anchor["original_session_id"]:
                    continue
                distance = abs(int(item["turn_ordinal"]) - int(anchor["turn_ordinal"]))
                if distance <= 2:
                    ranked.append(
                        (
                            distance,
                            int(item["session_ordinal"]),
                            int(item["turn_ordinal"]),
                            str(item["compact_source_ref"]),
                        )
                    )
        return list(dict.fromkeys(value for *_position, value in sorted(ranked)))
    if hint.action == "EXPAND_EPISODE":
        sessions = {str(item["original_session_id"]) for item in anchors}
        return [
            str(item["compact_source_ref"])
            for item in sources
            if str(item["original_session_id"]) in sessions
        ]
    return []


def _binding_summary(
    requirements: Sequence[EvidenceRequirementV02],
    sources: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    spans = project_evidence_spans(sources)
    interpretations = interpret_evidence_spans(spans)
    bindings = bind_requirements(requirements, interpretations, spans)
    matched = sorted(
        {
            binding.requirement_id
            for binding in bindings
            if binding.status == "MATCH"
        }
    )
    required = [item.slot_id for item in requirements if item.required]
    counts = Counter(binding.status for binding in bindings)
    return {
        "required_requirement_count": len(required),
        "matched_requirement_ids": matched,
        "matched_requirement_count": len(matched),
        "binding_success_rate": round(len(matched) / len(required), 9) if required else 1.0,
        "operator_ready": set(required).issubset(matched),
        "status_counts": {
            "MATCH": counts["MATCH"],
            "POSSIBLE": counts["POSSIBLE"],
            "REJECTED": counts["REJECTED"],
        },
    }


def _empty_simulation(
    *,
    baseline_refs: Sequence[str],
    binding: Mapping[str, Any],
    candidate_cap: int,
) -> dict[str, Any]:
    return {
        "attempted": False,
        "candidate_cap": candidate_cap,
        "candidate_refs": [],
        "new_candidate_refs": [],
        "new_candidate_count": 0,
        "combined_candidate_refs": list(baseline_refs),
        "combined_candidate_count": len(baseline_refs),
        "repeated_region_count": 0,
        "wrong_scope_candidate_count": 0,
        "latency_ms": 0.0,
        "binding": dict(binding),
        "canonical_mutation": False,
        "product_result_changed": False,
    }


def _score_case(row: Mapping[str, Any], label: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(row["case_id"])
    deterministic = _mapping(row, "deterministic")
    simulation = _mapping(row, "offline_simulation")
    baseline_refs = _string_list(deterministic.get("candidate_refs"), "baseline refs")
    combined_refs = _string_list(simulation.get("combined_candidate_refs"), "combined refs")
    new_refs = _string_list(simulation.get("new_candidate_refs"), "new refs")
    atoms_raw = label.get("atoms")
    if not isinstance(atoms_raw, list) or not atoms_raw:
        raise R3ShadowError("R3 scoring atom denominator is missing")
    atoms = [cast(Mapping[str, Any], item) for item in atoms_raw if isinstance(item, Mapping)]
    if len(atoms) != len(atoms_raw):
        raise R3ShadowError("R3 scoring atom is malformed")
    gold_refs = {str(item["source_turn_ref"]) for item in atoms}
    by_slot: defaultdict[str, set[str]] = defaultdict(set)
    for atom in atoms:
        by_slot[str(atom["slot"])].add(str(atom["source_turn_ref"]))
    baseline_set = set(baseline_refs)
    combined_set = set(combined_refs)
    baseline_atom_hits = sum(str(item["source_turn_ref"]) in baseline_set for item in atoms)
    combined_atom_hits = sum(str(item["source_turn_ref"]) in combined_set for item in atoms)
    baseline_slot_hits = sum(refs.issubset(baseline_set) for refs in by_slot.values())
    combined_slot_hits = sum(refs.issubset(combined_set) for refs in by_slot.values())
    missing_rank = int(row["total_source_turn_count"]) + 1
    baseline_rank = _best_rank(baseline_refs, gold_refs, missing_rank)
    combined_rank = _best_rank(combined_refs, gold_refs, missing_rank)
    baseline_binding = _mapping(deterministic, "binding")
    combined_binding = _mapping(simulation, "binding")
    baseline_ready = gold_refs.issubset(baseline_set)
    combined_ready = gold_refs.issubset(combined_set)
    controller = _mapping(row, "controller")
    receipt = controller.get("receipt")
    return {
        "case_id": case_id,
        "activation": dict(_mapping(row, "activation")),
        "schema_valid": controller.get("schema_valid"),
        "no_action": (
            isinstance(receipt, Mapping) and receipt.get("action") == "NO_ACTION"
        ),
        "cue_provenance": (
            receipt.get("cue_provenance") if isinstance(receipt, Mapping) else None
        ),
        "governance_negative_lane": list(
            cast(list[dict[str, Any]], row.get("governance_negative_lane", []))
        ),
        "gold_turn_best_rank": {
            "deterministic": baseline_rank,
            "shadow": combined_rank,
            "delta": baseline_rank - combined_rank,
            "missing_rank_sentinel": missing_rank,
        },
        "required_slot_candidate_recall": {
            "deterministic_hits": baseline_slot_hits,
            "shadow_hits": combined_slot_hits,
            "denominator": len(by_slot),
        },
        "required_evidence_coverage": {
            "deterministic_hits": baseline_atom_hits,
            "shadow_hits": combined_atom_hits,
            "denominator": len(atoms),
        },
        "candidate_counts": {
            "deterministic": len(baseline_refs),
            "shadow": len(combined_refs),
            "new": len(new_refs),
            "deterministic_noise": len(baseline_set - gold_refs),
            "shadow_noise": len(combined_set - gold_refs),
            "new_noise": len(set(new_refs) - gold_refs),
            "repeated_regions": int(simulation["repeated_region_count"]),
            "wrong_scope": int(simulation["wrong_scope_candidate_count"]),
        },
        "binding": {
            "deterministic_matched_requirements": int(
                baseline_binding["matched_requirement_count"]
            ),
            "shadow_matched_requirements": int(
                combined_binding["matched_requirement_count"]
            ),
            "requirement_denominator": int(
                baseline_binding["required_requirement_count"]
            ),
            "deterministic_ready": baseline_binding["operator_ready"] is True,
            "shadow_ready": combined_binding["operator_ready"] is True,
        },
        "operator_ready": {
            "deterministic": baseline_ready,
            "shadow": combined_ready,
        },
        "controller": {
            "model_call_count": int(controller["model_call_count"]),
            "automatic_retry_count": int(controller["automatic_retry_count"]),
            "prompt_tokens": controller.get("prompt_tokens"),
            "completion_tokens": controller.get("completion_tokens"),
            "latency_ms": controller.get("latency_ms"),
            "transport_mode": controller.get("transport_mode"),
            "http_status": controller.get("http_status"),
            "stream_finish_state": controller.get("stream_finish_state"),
            "sse_error_observed": controller.get("sse_error_observed") is True,
            "error_classification_correct": controller.get(
                "error_classification_correct"
            ),
            "validation_error_field_path": controller.get(
                "validation_error_field_path"
            ),
            "validation_error_type": controller.get("validation_error_type"),
        },
        "acquisition_latency_ms": float(simulation["latency_ms"]),
        "runtime_hint_accepted": (
            isinstance(row.get("hint_validation"), Mapping)
            and _mapping(row, "hint_validation").get("status") == "ACCEPTED"
        ),
        "additional_acquisition_pass_executed": simulation.get("attempted") is True,
        "new_governed_candidate_count": max(
            0,
            len(new_refs) - int(simulation["wrong_scope_candidate_count"]),
        ),
        "product_result_changed": _mapping(row, "product_result").get("changed") is True,
        "scope_or_authority_expanded": _mapping(row, "product_result").get(
            "scope_or_authority_expanded"
        )
        is True,
        "missing_slot_case_improved": (
            _mapping(row, "activation").get("eligible") is True
            and (
                combined_rank < baseline_rank
                or (
                    combined_binding["operator_ready"] is True
                    and baseline_binding["operator_ready"] is not True
                )
                or (combined_ready and not baseline_ready)
            )
        ),
    }


def _aggregate_score(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    activation_denominator = len(rows)
    activated = [row for row in rows if _mapping(row, "activation").get("activated")]
    schema_valid = [row for row in activated if row.get("schema_valid") is True]
    controller_latencies = [
        float(value)
        for row in activated
        if (value := _mapping(row, "controller").get("latency_ms")) is not None
    ]
    prompt_tokens = [
        int(value)
        for row in activated
        if (value := _mapping(row, "controller").get("prompt_tokens")) is not None
    ]
    completion_tokens = [
        int(value)
        for row in activated
        if (value := _mapping(row, "controller").get("completion_tokens")) is not None
    ]
    cue_provenance = Counter(
        str(row["cue_provenance"])
        for row in schema_valid
        if row.get("cue_provenance") is not None
    )
    atom_denominator = sum(
        int(_mapping(row, "required_evidence_coverage")["denominator"]) for row in rows
    )
    slot_denominator = sum(
        int(_mapping(row, "required_slot_candidate_recall")["denominator"])
        for row in rows
    )
    binding_denominator = sum(
        int(_mapping(row, "binding")["requirement_denominator"]) for row in rows
    )
    baseline_atom_hits = sum(
        int(_mapping(row, "required_evidence_coverage")["deterministic_hits"])
        for row in rows
    )
    shadow_atom_hits = sum(
        int(_mapping(row, "required_evidence_coverage")["shadow_hits"])
        for row in rows
    )
    baseline_slot_hits = sum(
        int(_mapping(row, "required_slot_candidate_recall")["deterministic_hits"])
        for row in rows
    )
    shadow_slot_hits = sum(
        int(_mapping(row, "required_slot_candidate_recall")["shadow_hits"])
        for row in rows
    )
    baseline_binding_hits = sum(
        int(_mapping(row, "binding")["deterministic_matched_requirements"])
        for row in rows
    )
    shadow_binding_hits = sum(
        int(_mapping(row, "binding")["shadow_matched_requirements"])
        for row in rows
    )
    candidate_counts = [_mapping(row, "candidate_counts") for row in rows]
    repeated = sum(int(value["repeated_regions"]) for value in candidate_counts)
    residual_attempts = sum(
        int(value["new"]) + int(value["repeated_regions"])
        for value in candidate_counts
    )
    provider_call_attempted = len(activated)
    provider_schema_accepted = len(schema_valid)
    runtime_accepted = sum(row.get("runtime_hint_accepted") is True for row in rows)
    extra_passes = sum(
        row.get("additional_acquisition_pass_executed") is True for row in rows
    )
    streaming_attempts = [
        row
        for row in activated
        if _mapping(row, "controller").get("transport_mode") == "streaming"
    ]
    sse_errors = [
        row
        for row in streaming_attempts
        if _mapping(row, "controller").get("sse_error_observed") is True
    ]
    correctly_classified_sse_errors = sum(
        _mapping(row, "controller").get("error_classification_correct") is True
        for row in sse_errors
    )
    treatment_delivered = (
        provider_schema_accepted > 0 and runtime_accepted > 0 and extra_passes > 0
    )
    return {
        "activation": {
            "denominator": activation_denominator,
            "eligible": sum(
                _mapping(row, "activation").get("eligible") is True for row in rows
            ),
            "activated": len(activated),
            "controller_calls": sum(
                int(_mapping(row, "controller")["model_call_count"]) for row in rows
            ),
        },
        "schema": {
            "valid": len(schema_valid),
            "invalid": len(activated) - len(schema_valid),
            "denominator": len(activated),
            "no_action": sum(row.get("no_action") is True for row in schema_valid),
        },
        "cue_provenance": {
            value: cue_provenance[value]
            for value in ("QUERY", "OBSERVATION", "PARAPHRASE")
        },
        "gold_turn_rank": {
            "improved_cases": sum(
                int(_mapping(row, "gold_turn_best_rank")["delta"]) > 0 for row in rows
            ),
            "delta_sum": sum(
                int(_mapping(row, "gold_turn_best_rank")["delta"]) for row in rows
            ),
        },
        "required_slot_candidate_recall": _rate_delta(
            baseline_slot_hits, shadow_slot_hits, slot_denominator
        ),
        "required_evidence_coverage": _rate_delta(
            baseline_atom_hits, shadow_atom_hits, atom_denominator
        ),
        "candidates": {
            "deterministic": sum(int(value["deterministic"]) for value in candidate_counts),
            "shadow": sum(int(value["shadow"]) for value in candidate_counts),
            "new": sum(int(value["new"]) for value in candidate_counts),
            "deterministic_noise": sum(
                int(value["deterministic_noise"]) for value in candidate_counts
            ),
            "shadow_noise": sum(int(value["shadow_noise"]) for value in candidate_counts),
            "new_noise": sum(int(value["new_noise"]) for value in candidate_counts),
            "noise_delta": sum(
                int(value["shadow_noise"]) - int(value["deterministic_noise"])
                for value in candidate_counts
            ),
            "repeated_regions": repeated,
            "repeated_region_delta": repeated,
            "repeated_region_rate": round(repeated / residual_attempts, 9)
            if residual_attempts
            else 0.0,
            "wrong_scope": sum(int(value["wrong_scope"]) for value in candidate_counts),
        },
        "binding": {
            **_rate_delta(baseline_binding_hits, shadow_binding_hits, binding_denominator),
            "deterministic_ready_cases": sum(
                _mapping(row, "binding")["deterministic_ready"] is True for row in rows
            ),
            "shadow_ready_cases": sum(
                _mapping(row, "binding")["shadow_ready"] is True for row in rows
            ),
            "ready_case_delta": sum(
                _mapping(row, "binding")["shadow_ready"] is True for row in rows
            )
            - sum(
                _mapping(row, "binding")["deterministic_ready"] is True for row in rows
            ),
        },
        "operator_ready": {
            "deterministic_cases": sum(
                _mapping(row, "operator_ready")["deterministic"] is True for row in rows
            ),
            "shadow_cases": sum(
                _mapping(row, "operator_ready")["shadow"] is True for row in rows
            ),
            "case_delta": sum(
                _mapping(row, "operator_ready")["shadow"] is True for row in rows
            )
            - sum(
                _mapping(row, "operator_ready")["deterministic"] is True for row in rows
            ),
            "denominator": len(rows),
        },
        "missing_slot_improved_case_count": sum(
            row.get("missing_slot_case_improved") is True for row in rows
        ),
        "controller_latency_ms": _distribution(controller_latencies),
        "controller_tokens": {
            "prompt": _distribution(prompt_tokens),
            "completion": _distribution(completion_tokens),
            "total_prompt": sum(prompt_tokens),
            "total_completion": sum(completion_tokens),
        },
        "additional_acquisition_latency_ms": _distribution(
            [float(row["acquisition_latency_ms"]) for row in activated]
        ),
        "automatic_retries": sum(
            int(_mapping(row, "controller")["automatic_retry_count"]) for row in rows
        ),
        "manipulation_check": {
            "ProviderCallAttempted": {
                "count": provider_call_attempted,
                "denominator": len(activated),
            },
            "ProviderSchemaAccepted": {
                "count": provider_schema_accepted,
                "denominator": provider_call_attempted,
            },
            "ProviderTransportMode": dict(
                sorted(
                    Counter(
                        str(_mapping(row, "controller").get("transport_mode") or "UNKNOWN")
                        for row in activated
                    ).items()
                )
            ),
            "ProviderSSEErrorObserved": {
                "count": len(sse_errors),
                "denominator": len(streaming_attempts),
            },
            "ProviderErrorClassificationCorrect": {
                "count": correctly_classified_sse_errors,
                "denominator": len(sse_errors),
            },
            "SchemaValidHintRate": _fraction(
                provider_schema_accepted, provider_call_attempted
            ),
            "RuntimeAcceptedHintRate": _fraction(
                runtime_accepted, provider_schema_accepted
            ),
            "AdditionalAcquisitionPassExecuted": {
                "count": extra_passes,
                "denominator": runtime_accepted,
            },
            "NewCandidateCount": sum(int(value["new"]) for value in candidate_counts),
            "NewGovernedCandidateCount": sum(
                int(row.get("new_governed_candidate_count", 0)) for row in rows
            ),
            "TreatmentDelivered": treatment_delivered,
            "outcome": (
                "VALID_TREATMENT_DELIVERED"
                if treatment_delivered
                else "TREATMENT_NOT_DELIVERED"
            ),
        },
    }


def _hard_gate(
    rows: Sequence[Mapping[str, Any]],
    aggregate: Mapping[str, Any],
    provider_identities: Sequence[str],
    provider_runtime_identity: Mapping[str, Any] | None,
) -> dict[str, Any]:
    safety = _governance_negative_metrics(rows)
    invalid_rows = [row for row in rows if row.get("schema_valid") is False]
    invalid_product_change = sum(
        row.get("product_result_changed") is True for row in invalid_rows
    )
    already_correct = [
        row for row in rows if _mapping(row, "operator_ready")["deterministic"] is True
    ]
    correct_regressions = sum(
        _mapping(row, "operator_ready")["shadow"] is not True
        for row in already_correct
    )
    checks = {
        "treatment_delivered": _mapping(aggregate, "manipulation_check").get(
            "TreatmentDelivered"
        )
        is True,
        "wrong_complete_introduced_zero": _metric_passes(safety["WrongComplete"]),
        "scope_or_authority_expansion_zero": all(
            _metric_passes(safety[name])
            for name in ("WrongScopeAcceptance", "UnauthorizedAuthorityExpansion")
        ),
        "all_governance_negative_metrics_meaningful_and_zero": all(
            _metric_passes(metric) for metric in safety.values()
        ),
        "invalid_output_product_change_zero": invalid_product_change == 0,
        "already_correct_case_regression_zero": correct_regressions == 0,
        "automatic_retry_zero": int(aggregate["automatic_retries"]) == 0,
        "provider_identity_stable": len(set(provider_identities)) == 1,
        "provider_runtime_identity_verified": (
            provider_runtime_identity is not None
            and provider_runtime_identity.get("verified") is True
            and provider_runtime_identity.get("models_endpoint_verified") is True
            and provider_runtime_identity.get("listener_observed") is True
        ),
        "at_least_two_missing_slot_cases_improve": int(
            aggregate["missing_slot_improved_case_count"]
        )
        >= 2,
        "required_evidence_coverage_nonregression": (
            _mapping(aggregate, "required_evidence_coverage")["shadow_hits"]
            >= _mapping(aggregate, "required_evidence_coverage")["deterministic_hits"]
        ),
        "operator_ready_nonregression": (
            _mapping(aggregate, "operator_ready")["shadow_cases"]
            >= _mapping(aggregate, "operator_ready")["deterministic_cases"]
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "governance_negative_metrics": safety,
        "wrong_complete_introduced": safety["WrongComplete"],
        "scope_or_authority_expansion": {
            "count": (
                int(safety["WrongScopeAcceptance"]["count"])
                + int(safety["UnauthorizedAuthorityExpansion"]["count"])
            ),
            "denominator": (
                int(safety["WrongScopeAcceptance"]["denominator"])
                + int(safety["UnauthorizedAuthorityExpansion"]["denominator"])
            ),
        },
        "invalid_output_product_change": {
            "count": invalid_product_change,
            "denominator": sum(
                _mapping(row, "activation").get("activated") is True for row in rows
            ),
            "observed_invalid_output_count": len(invalid_rows),
        },
        "already_correct_case_regression": {
            "count": correct_regressions,
            "denominator": len(already_correct),
        },
    }


def _governance_negative_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    names = (
        "WrongComplete",
        "WrongScopeAcceptance",
        "UnauthorizedAuthorityExpansion",
        "RevokedEvidenceAcceptance",
        "PermissionUnknownAcceptance",
        "CrossTenantCandidateAcceptance",
        "HiddenFallback",
        "ModelSelectedFinalEvidence",
        "ModelDeclaredComplete",
    )
    result = {name: {"count": 0, "denominator": 0} for name in names}
    for row in rows:
        lane = row.get("governance_negative_lane")
        if not isinstance(lane, list):
            continue
        for item in lane:
            if not isinstance(item, Mapping) or item.get("metric") not in result:
                continue
            metric = result[str(item["metric"])]
            metric["denominator"] += 1
            metric["count"] += int(item.get("accepted") is True)
    return result


def _metric_passes(metric: Mapping[str, int]) -> bool:
    return metric["denominator"] > 0 and metric["count"] == 0


def _controller_fields(receipt: ResidualControllerReceipt) -> dict[str, Any]:
    return {
        "provider": receipt.provider,
        "model": receipt.model,
        "prompt_tokens": receipt.prompt_tokens,
        "completion_tokens": receipt.completion_tokens,
        "latency_ms": receipt.timing.total_ms,
        "automatic_retry_count": receipt.automatic_retry_count,
    }


def _completion_fields(completion: SemanticHintCompletion) -> dict[str, Any]:
    return {
        "provider": completion.provider,
        "model": completion.model,
        "prompt_tokens": completion.prompt_tokens,
        "completion_tokens": completion.completion_tokens,
        "latency_ms": completion.total_ms,
        "automatic_retry_count": completion.automatic_retry_count,
        "transport_mode": completion.transport_mode,
        "http_status": completion.http_status,
        "stream_finish_state": completion.stream_finish_state,
        "sse_error_observed": completion.sse_error_observed,
        "error_classification_correct": True,
    }


def _controller_error_fields(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, SemanticHintError):
        sse_error_observed = (
            exc.transport_mode == "streaming"
            and (exc.sse_error_type is not None or exc.sse_error_code is not None)
        )
        return {
            "transport_mode": exc.transport_mode,
            "http_status": exc.http_status,
            "stream_finish_state": exc.stream_finish_state,
            "sse_error_observed": sse_error_observed,
            "error_classification_correct": (
                exc.code == "SEMANTIC_HINT_PROVIDER_SSE_ERROR"
                if sse_error_observed
                else exc.code != "SEMANTIC_HINT_PROVIDER_EMPTY_OUTPUT"
            ),
        }
    if isinstance(exc, ResidualRefindingError):
        return {
            "validation_error_field_path": exc.validation_field_path,
            "validation_error_type": exc.validation_error_type,
        }
    return {}


def _requirements(mediators: Mapping[str, Any]) -> list[EvidenceRequirementV02]:
    annotations = _mapping(mediators, "binding_annotations")
    raw = annotations.get("requirements")
    if not isinstance(raw, list) or not raw:
        raise R3ShadowError("Q1R typed requirements are missing")
    return [EvidenceRequirementV02.model_validate(item) for item in raw]


def _sources(snapshot: Mapping[str, Any], case_id: str) -> list[dict[str, Any]]:
    raw = snapshot.get("source_events")
    if not isinstance(raw, list) or not raw:
        raise R3ShadowError("Q1R Evidence snapshot has no source events")
    result: list[dict[str, Any]] = []
    refs: set[str] = set()
    for value in raw:
        if not isinstance(value, Mapping) or value.get("case_id") != case_id:
            raise R3ShadowError("Q1R source event crossed its case boundary")
        source_ref = compact_lme_source_ref(str(value.get("source_ref")))
        if source_ref in refs or not source_ref.startswith(f"{case_id}:s"):
            raise R3ShadowError("Q1R compact source identity is invalid")
        refs.add(source_ref)
        content = value.get("content")
        if not isinstance(content, str) or not content:
            raise R3ShadowError("Q1R source content is missing")
        result.append(
            {
                **dict(value),
                "compact_source_ref": source_ref,
                "kind": "EVIDENCE_OBSERVATION",
                "canonical": False,
                "canonical_mutation": False,
                "tenant_id": "opened-dev-public-v1",
                "principal_id": "dg18-shadow-controller-v01",
                "scope_predicate": {"opened_dev_case_id": case_id},
                "source_ref": str(value["source_ref"]),
                "subject_id": str(value["original_session_id"]),
                "speaker": str(value["role"]),
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "content_hash": hashlib.sha256(content.encode()).hexdigest(),
                "captured_at": str(value["observed_at"]),
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
                "revoked_at": None,
                "authority_class": "EVIDENCE_ONLY",
                "fallback_used": False,
            }
        )
    return sorted(
        result,
        key=lambda item: (int(item["session_ordinal"]), int(item["turn_ordinal"])),
    )


def _baseline_refs(mediators: Mapping[str, Any]) -> list[str]:
    raw = _string_list(mediators.get("selected_source_refs"), "selected source refs")
    derived = mediators.get("derived_result")
    operands = derived.get("operands") if isinstance(derived, Mapping) else []
    if operands is None:
        operands = []
    if not isinstance(operands, list):
        raise R3ShadowError("Q1R derived operands are malformed")
    operand_refs = [
        str(item["source_ref"])
        for item in operands
        if isinstance(item, Mapping) and isinstance(item.get("source_ref"), str)
    ]
    return list(
        dict.fromkeys(compact_lme_source_ref(value) for value in [*raw, *operand_refs])
    )


def _snapshot_index(
    archive: Mapping[str, Any], case_ids: Sequence[str]
) -> dict[str, Mapping[str, Any]]:
    raw = archive.get("snapshots")
    if not isinstance(raw, list):
        raise R3ShadowError("Q1R snapshots are missing")
    result: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(
            item.get("evidence_snapshot"), Mapping
        ):
            raise R3ShadowError("Q1R snapshot entry is malformed")
        result[str(item.get("case_id"))] = cast(
            Mapping[str, Any], item["evidence_snapshot"]
        )
    if set(result) != set(case_ids):
        raise R3ShadowError("Q1R snapshot denominator drifted")
    return result


def _validate_product_shadow(product: Mapping[str, Any]) -> None:
    if (
        product.get("schema") != PRODUCT_SHADOW_SCHEMA
        or product.get("status") != "PRODUCT_SHADOW_COMPLETE_UNSCORED"
        or product.get("formal_holdout_consumed") is not False
        or product.get("label_fields_available") is not False
        or product.get("labels_loaded") is not False
        or product.get("case_count") != 10
        or not isinstance(product.get("rows"), list)
    ):
        raise R3ShadowError("R3 product shadow envelope is invalid")
    rows = cast(list[Any], product["rows"])
    if len(rows) != 10 or any(
        not isinstance(row, Mapping)
        or _mapping(row, "product_result").get("changed") is not False
        or _mapping(row, "product_result").get("hint_consumed_by_product") is not False
        for row in rows
    ):
        raise R3ShadowError("R3 shadow changed a product result")


def _validated_sealed_product(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    product = envelope.get("product_shadow")
    if (
        envelope.get("schema") != SEALED_SHADOW_SCHEMA
        or envelope.get("status") != "SEALED_BEFORE_SCORING"
        or envelope.get("formal_holdout_consumed") is not False
        or envelope.get("label_fields_available") is not False
        or not isinstance(product, Mapping)
        or envelope.get("product_shadow_sha256") != canonical_sha256(product)
    ):
        raise R3ShadowError("R3 sealed product archive identity is invalid")
    _validate_product_shadow(product)
    return product


def _reject_label_fields(value: object, path: str = "archive") -> None:
    if isinstance(value, Mapping):
        forbidden = _FORBIDDEN_LABEL_KEYS.intersection(str(key) for key in value)
        if forbidden:
            raise R3ShadowError(
                f"label field reached R3 product phase at {path}: {sorted(forbidden)}"
            )
        for key, child in value.items():
            _reject_label_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_label_fields(child, f"{path}[{index}]")


def _load_scoring_labels(
    path: Path,
) -> tuple[dict[str, Any], tuple[Any, ...], dict[str, dict[str, Any]]]:
    from evals.dg17.measurement import load_answer_bearing_labels

    return load_answer_bearing_labels(path)


def _question_fields(value: Mapping[str, str]) -> tuple[str, datetime]:
    question = value.get("question")
    question_at = value.get("question_at")
    if not question or not question_at:
        raise R3ShadowError("opened-development question fields are incomplete")
    normalized = normalize_lme_timestamp(question_at).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise R3ShadowError("opened-development question time is not timezone-aware")
    return question, parsed


def _rate_delta(before: int, after: int, denominator: int) -> dict[str, Any]:
    if denominator <= 0:
        raise R3ShadowError("R3 metric denominator must be positive")
    return {
        "deterministic_hits": before,
        "shadow_hits": after,
        "denominator": denominator,
        "deterministic_rate": round(before / denominator, 9),
        "shadow_rate": round(after / denominator, 9),
        "delta": round((after - before) / denominator, 9),
    }


def _fraction(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 9) if denominator else None,
    }


def _distribution(values: Sequence[float | int]) -> dict[str, Any]:
    numeric = [float(value) for value in values]
    return {
        "count": len(numeric),
        "mean": round(mean(numeric), 6) if numeric else None,
        "p50": round(median(numeric), 6) if numeric else None,
        "p95": round(_percentile(numeric, 0.95), 6) if numeric else None,
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _best_rank(values: Sequence[str], targets: set[str], missing_rank: int) -> int:
    ranks = [index for index, value in enumerate(values, start=1) if value in targets]
    return min(ranks, default=missing_rank)


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    raw = value.get(key)
    if not isinstance(raw, Mapping):
        raise R3ShadowError(f"R3 {key} mapping is missing")
    return raw


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise R3ShadowError(f"R3 {name} must be a string list")
    return list(value)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise R3ShadowError(f"invalid R3 JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise R3ShadowError(f"R3 JSON object required: {path}")
    return value


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "DEFAULT_LABELS_PATH",
    "DEFAULT_Q1R_ARCHIVE",
    "PRODUCT_SHADOW_SCHEMA",
    "SCORE_SCHEMA",
    "SEALED_SHADOW_SCHEMA",
    "R3ShadowError",
    "opened_dev_questions",
    "run_product_shadow",
    "score_sealed_shadow",
    "seal_product_shadow",
]
