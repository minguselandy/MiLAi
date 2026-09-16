"""DG-19 sealed synthetic one-call residual treatment-delivery evaluation."""

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
from typing import Any, cast

from milai.application.acquisition_state import (
    acquisition_state_trace_summary,
    advance_acquisition_state,
    build_acquisition_action,
    build_acquisition_region,
    build_acquisition_window,
    initialize_acquisition_state,
    reserve_residual_controller_call,
)
from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
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
    AcquisitionBudget,
    AcquisitionBudgetUse,
    AcquisitionEvidenceSourcePolicy,
    AcquisitionFusion,
    AcquisitionGlobalConstraints,
    AcquisitionPlan,
    AcquisitionProbe,
    AcquisitionResidualPolicy,
    AcquisitionState,
    CandidateEnvelope,
)
from milai.domain.residual_refinding import (
    ResidualControllerReceipt,
    ResidualCueProposal,
    ResidualHintValidation,
    ResidualSearchHint,
)
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSpan,
    RequirementBinding,
)
from milai.domain.sufficiency import SufficiencyDecision
from milai.persistence.retrieval_repository import evidence_query_terms
from pydantic import ValidationError

from evals.paper.adapters.baselines import _bm25_scores

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = ROOT / "evals/dg19/fixtures/synthetic-treatment-cases.v0.1.json"
DEFAULT_SCORER_FIXTURE = (
    ROOT / "evals/dg19/fixtures/synthetic-treatment-scorer.v0.1.json"
)
FIXTURE_SCHEMA = "milai.dg19.synthetic-treatment-fixture.v0.1"
SCORER_FIXTURE_SCHEMA = "milai.dg19.synthetic-treatment-scorer.v0.1"
PRODUCT_SCHEMA = "milai.dg19.synthetic-treatment-product-shadow.v0.1"
SEALED_SCHEMA = "milai.dg19.synthetic-treatment-sealed-shadow.v0.1"
SCORE_SCHEMA = "milai.dg19.synthetic-treatment-score.v0.1"
_SCORER_ONLY_KEYS = frozenset(
    {
        "scorer",
        "expected_action_family",
        "expected_missing_requirement",
        "expected_answer_bearing_source_refs",
        "expected_cue_provenance",
        "gold",
        "labels",
    }
)


class DG19SyntheticError(RuntimeError):
    """The synthetic treatment boundary or executable invariant failed."""


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


def load_product_cases(path: Path = DEFAULT_FIXTURE) -> list[dict[str, Any]]:
    """Project product-only views without consulting scorer values."""

    fixture = _load_object(path)
    raw_cases = _fixture_cases(fixture)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_cases:
        case_id = raw.get("case_id")
        product = raw.get("product")
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id in seen
            or not isinstance(product, Mapping)
        ):
            raise DG19SyntheticError("synthetic product case identity is invalid")
        _reject_scorer_fields(product, f"case[{case_id}].product")
        normalized = _validated_product_view(case_id, product)
        result.append(normalized)
        seen.add(case_id)
    return result


def load_scorer_truth(
    path: Path = DEFAULT_SCORER_FIXTURE,
) -> dict[str, dict[str, Any]]:
    """Open scorer-only source-ref truth after the product trace is sealed."""

    fixture = _load_object(path)
    result: dict[str, dict[str, Any]] = {}
    for raw in _scorer_cases(fixture):
        case_id = raw.get("case_id")
        if not isinstance(case_id, str):
            raise DG19SyntheticError("synthetic scorer truth is malformed")
        refs = raw.get("expected_answer_bearing_source_refs")
        if not isinstance(refs, list) or any(
            not isinstance(value, str) for value in refs
        ):
            raise DG19SyntheticError("synthetic scorer source refs are malformed")
        action = raw.get("expected_action_family")
        if action not in {
            "SEARCH_LEXICAL",
            "SEARCH_TEMPORAL",
            "EXPAND_NEIGHBORS",
            "NO_ACTION",
        }:
            raise DG19SyntheticError("synthetic scorer action family is invalid")
        result[case_id] = {
            "expected_action_family": action,
            "expected_missing_requirement": raw.get("expected_missing_requirement"),
            "expected_answer_bearing_source_refs": list(refs),
            "expected_cue_provenance": raw.get("expected_cue_provenance"),
        }
    return result


def run_product_shadow(
    *,
    run_id: str,
    provider: StructuredSemanticProvider,
    fixture_path: Path = DEFAULT_FIXTURE,
    provider_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run only the product side; scorer truth remains unopened."""

    if not run_id:
        raise ValueError("DG-19 synthetic run ID is required")
    cases = load_product_cases(fixture_path)
    rows = [
        _run_product_case(run_id=run_id, case=case, provider=provider) for case in cases
    ]
    provider_identities = sorted(
        {
            f"{controller['provider']}/{controller['model']}"
            for row in rows
            if isinstance((controller := row.get("controller")), Mapping)
            and isinstance(controller.get("provider"), str)
            and isinstance(controller.get("model"), str)
        }
    )
    product = {
        "schema": PRODUCT_SCHEMA,
        "status": "PRODUCT_SHADOW_COMPLETE_UNSCORED",
        "classification": "SYNTHETIC_ONLY / EVALUATION_PLANE",
        "run_id": run_id,
        "fixture": _identity(fixture_path),
        "case_count": len(rows),
        "labels_loaded": False,
        "scorer_fields_available": False,
        "product_path_scorer_access_count": 0,
        "formal_holdout_consumed": False,
        "lme_executed": False,
        "product_result_change_count": 0,
        "canonical_mutation_count": 0,
        "provider_identities": provider_identities,
        "provider_runtime_identity": (
            dict(provider_runtime_identity)
            if provider_runtime_identity is not None
            else None
        ),
        "rows": rows,
    }
    _validate_product_shadow(product)
    return product


def seal_product_shadow(
    product: Mapping[str, Any], output_path: Path
) -> dict[str, Any]:
    _validate_product_shadow(product)
    envelope = {
        "schema": SEALED_SCHEMA,
        "status": "SEALED_BEFORE_SCORING",
        "formal_holdout_consumed": False,
        "lme_executed": False,
        "product_shadow_sha256": canonical_sha256(product),
        "product_shadow": dict(product),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_new(output_path, envelope)
    return envelope


def score_sealed_shadow(
    sealed_path: Path,
    *,
    fixture_path: Path = DEFAULT_FIXTURE,
    scorer_path: Path = DEFAULT_SCORER_FIXTURE,
) -> dict[str, Any]:
    envelope = _load_object(sealed_path)
    product = _validated_sealed_product(envelope)
    truth = load_scorer_truth(scorer_path)
    rows = product.get("rows")
    if not isinstance(rows, list) or set(truth) != {
        str(row.get("case_id")) for row in rows if isinstance(row, Mapping)
    }:
        raise DG19SyntheticError("synthetic scorer denominator drifted")
    scored_rows = [
        _score_case(cast(Mapping[str, Any], row), truth[str(row["case_id"])])
        for row in rows
    ]
    summary = _aggregate(scored_rows)
    hard_gate = _hard_gate(scored_rows, summary)
    return {
        "schema": SCORE_SCHEMA,
        "status": (
            "PASS_SYNTHETIC_TREATMENT_DELIVERY"
            if hard_gate["passed"]
            else _failed_status(scored_rows, summary, hard_gate)
        ),
        "classification": "SYNTHETIC_ONLY / SCORED_AFTER_SEAL",
        "run_id": product["run_id"],
        "formal_holdout_consumed": False,
        "lme_executed": False,
        "sealed_product_shadow": _identity(sealed_path),
        "fixture": _identity(fixture_path),
        "scorer_fixture": _identity(scorer_path),
        "label_boundary": {
            "product_path_scorer_access_count": 0,
            "scorer_access_count": 1,
            "scoring_started_after_product_seal": True,
            "formal_holdout_consumed": False,
        },
        "summary": summary,
        "hard_gate": hard_gate,
        "rows": scored_rows,
    }


def _run_product_case(
    *, run_id: str, case: Mapping[str, Any], provider: StructuredSemanticProvider
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    requirements = [
        EvidenceRequirementV02.model_validate(value)
        for value in cast(list[dict[str, Any]], case["requirements"])
    ]
    sources = [_hydrate_source(case, value) for value in _source_rows(case)]
    source_by_ref = {str(value["source_ref"]): value for value in sources}
    initial_refs = _string_list(case.get("initial_source_refs"), "initial source refs")
    if any(value not in source_by_ref for value in initial_refs):
        raise DG19SyntheticError("initial source ref is absent from evidence universe")
    plan = _build_plan(case, requirements)
    initial_sources: list[dict[str, Any]] = []
    initial_eligibility: list[dict[str, Any]] = []
    for source_ref in initial_refs:
        source = source_by_ref[source_ref]
        eligibility = evaluate_residual_candidate_eligibility(raw=source, plan=plan)
        initial_eligibility.append(
            _eligibility_trace(source_ref, source, eligibility.model_dump(mode="json"))
        )
        if not eligibility.eligible:
            raise DG19SyntheticError(
                "initial deterministic source failed governance gate"
            )
        initial_sources.append(source)
    initial_semantics = _semantic_bundle(requirements, initial_sources)
    initial_sufficiency = _requirement_sufficiency(requirements, initial_semantics)
    if not initial_sufficiency.missing_slots:
        raise DG19SyntheticError("synthetic case is complete before residual treatment")
    initial = initialize_acquisition_state(plan, requirements)
    deterministic_action = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=initial.missing_requirement_ids,
        probe_ids=[probe.probe_id for probe in plan.probes],
    )
    deterministic = advance_acquisition_state(
        initial,
        deterministic_action,
        candidates=_candidate_envelopes(
            initial_sources,
            plan=plan,
            semantics=initial_semantics,
        ),
        bindings=cast(list[RequirementBinding], initial_semantics["bindings"]),
        sufficiency_decision=initial_sufficiency,
        budget_use=AcquisitionBudgetUse(candidate_count=len(initial_sources)),
    )
    if deterministic.outcome != "APPLIED":
        raise DG19SyntheticError(
            f"deterministic acquisition transition failed: {deterministic.reason_code}"
        )
    reservation = reserve_residual_controller_call(deterministic.state, plan)
    if reservation.outcome != "APPLIED":
        raise DG19SyntheticError(
            f"controller reservation failed: {reservation.reason_code}"
        )
    reserved = reservation.state
    observation = build_acquisition_observation(
        query=str(case["query"]),
        requirements=requirements,
        candidates=initial_sources,
        state=reserved,
        plan=plan,
    )
    controller: dict[str, Any] = {
        "attempted": True,
        "schema_valid": False,
        "runtime_accepted": False,
        "runtime_status": None,
        "runtime_reason_code": None,
        "error": None,
        "provider": None,
        "model": None,
        "transport_mode": None,
        "http_status": None,
        "finish_reason": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "latency_ms": None,
        "model_call_count": 1,
        "automatic_retry_count": 0,
        "receipt": None,
    }
    additional = _empty_additional(initial_refs, initial_semantics, initial_sufficiency)
    recording = _RecordingProvider(provider)
    try:
        receipt = ResidualHintShadowService(recording).generate(
            run_id=run_id,
            case_id=case_id,
            observation=observation,
            state=reserved,
            plan=plan,
        )
        if recording.last is not None:
            controller.update(_completion_fields(recording.last))
        controller["schema_valid"] = True
        controller["receipt"] = _durable_controller_receipt(receipt)
        validation = validate_residual_search_hint(
            hint=receipt.hint,
            state=reserved,
            plan=plan,
        )
        controller["runtime_status"] = validation.status
        controller["runtime_reason_code"] = validation.reason_code
        controller["runtime_accepted"] = validation.status == "ACCEPTED"
        if validation.status == "ACCEPTED":
            additional = _execute_additional_acquisition(
                hint=receipt.hint,
                validation=validation,
                requirements=requirements,
                sources=sources,
                initial_refs=initial_refs,
                state=reserved,
                plan=plan,
                initial_semantics=initial_semantics,
                initial_sufficiency=initial_sufficiency,
            )
    except (ResidualRefindingError, SemanticHintError) as exc:
        controller["error"] = _typed_error_code(exc)
        controller.update(_error_fields(exc))
        if recording.last is not None:
            controller.update(_completion_fields(recording.last))
            try:
                ResidualCueProposal.model_validate_json(recording.last.content)
            except ValidationError:
                pass
            else:
                controller["schema_valid"] = True
        if isinstance(exc, ResidualRefindingError) and controller["schema_valid"]:
            controller["runtime_status"] = "REJECTED"
            controller["runtime_reason_code"] = exc.code
    if recording.calls != 1:
        raise DG19SyntheticError("synthetic controller logical call ceiling violated")
    if recording.last is not None and (
        recording.last.provider_calls != 1 or recording.last.automatic_retry_count != 0
    ):
        raise DG19SyntheticError("synthetic provider call/retry contract violated")
    negative_lane = _governance_negative_lane(case, plan, sources, reserved)
    return {
        "case_id": case_id,
        "product_input_digest": canonical_sha256(case),
        "activation": {
            "eligible": True,
            "activated": True,
            "reason": "TYPED_MISSING_REQUIREMENT",
        },
        "deterministic": {
            "action_digest": deterministic_action.action_digest,
            "initial_source_refs": initial_refs,
            "initial_source_digests": [
                _source_digest(value) for value in initial_sources
            ],
            "eligibility": initial_eligibility,
            "binding": _public_semantic_summary(initial_semantics),
            "sufficiency": initial_sufficiency.model_dump(mode="json"),
            "state": acquisition_state_trace_summary(deterministic.state),
        },
        "observation": {
            "digest": canonical_sha256(observation.model_dump(mode="json")),
            "missing_requirement_ids": [
                value.requirement_id for value in observation.missing_requirements
            ],
            "candidate_summary_count": len(observation.candidate_summaries),
            "canonical": False,
            "canonical_mutation": False,
        },
        "controller": controller,
        "additional_acquisition": additional,
        "governance_negative_lane": negative_lane,
        "product_result": {
            "changed": False,
            "canonical_mutation": False,
            "scope_or_authority_expanded": False,
        },
    }


def _execute_additional_acquisition(
    *,
    hint: ResidualSearchHint,
    validation: ResidualHintValidation,
    requirements: Sequence[EvidenceRequirementV02],
    sources: Sequence[Mapping[str, Any]],
    initial_refs: Sequence[str],
    state: AcquisitionState,
    plan: AcquisitionPlan,
    initial_semantics: Mapping[str, Any],
    initial_sufficiency: SufficiencyDecision,
) -> dict[str, Any]:
    started = time.perf_counter()
    ranked_refs = _rank_sources(hint, sources, initial_refs)
    source_by_ref = {str(value["source_ref"]): value for value in sources}
    initial_set = set(initial_refs)
    repeated: list[str] = []
    new_refs: list[str] = []
    eligibility_rows: list[dict[str, Any]] = []
    for source_ref in ranked_refs:
        source = source_by_ref[source_ref]
        if source_ref in initial_set:
            repeated.append(source_ref)
            continue
        eligibility = evaluate_residual_candidate_eligibility(raw=source, plan=plan)
        eligibility_rows.append(
            _eligibility_trace(source_ref, source, eligibility.model_dump(mode="json"))
        )
        if not eligibility.eligible or source_ref in new_refs:
            continue
        new_refs.append(source_ref)
        if len(new_refs) >= state.remaining_budget.candidate_count:
            break
    combined_refs = list(dict.fromkeys([*initial_refs, *new_refs]))
    combined_sources = [source_by_ref[value] for value in combined_refs]
    semantics = _semantic_bundle(requirements, combined_sources)
    sufficiency = _requirement_sufficiency(requirements, semantics)
    action_kind = (
        validation.action
        if validation.action == "EXPAND_NEIGHBORS"
        else "RESIDUAL_PASS"
    )
    action = build_acquisition_action(
        action_kind=cast(Any, action_kind),
        pass_index=1,
        requirement_ids=[validation.requirement_id],
        probe_ids=[probe.probe_id for probe in plan.probes],
    )
    windows = []
    regions = []
    if validation.action == "EXPAND_NEIGHBORS":
        for source_ref in initial_refs:
            source = source_by_ref[source_ref]
            ordinal = int(source["turn_ordinal"])
            window = build_acquisition_window(
                session_id=str(source["subject_id"]),
                turn_start=max(0, ordinal - 2),
                turn_end_exclusive=ordinal + 3,
            )
            windows.append(window)
            regions.append(
                build_acquisition_region(window, action, [validation.requirement_id])
            )
    latency_ms = (time.perf_counter() - started) * 1_000
    context_tokens = sum(
        max(1, math.ceil(len(str(source_by_ref[value]["content"])) / 4))
        for value in new_refs
    )
    transition = advance_acquisition_state(
        state,
        action,
        candidates=_candidate_envelopes(
            [source_by_ref[value] for value in new_refs],
            plan=plan,
            semantics=semantics,
        ),
        bindings=cast(list[RequirementBinding], semantics["bindings"]),
        windows=windows,
        inspected_regions=regions,
        sufficiency_decision=sufficiency,
        budget_use=AcquisitionBudgetUse(
            acquisition_passes=1,
            candidate_count=len(new_refs),
            context_tokens=context_tokens,
            latency_ms=latency_ms,
        ),
    )
    return {
        "attempted": True,
        "action": validation.action,
        "requirement_id": validation.requirement_id,
        "action_digest": action.action_digest,
        "cue_digest": canonical_sha256(hint.model_dump(mode="json")),
        "candidate_universe_digest": canonical_sha256(
            [_source_digest(value) for value in sources]
        ),
        "ranked_candidate_refs": ranked_refs,
        "eligibility_outcomes": eligibility_rows,
        "new_candidate_refs": new_refs,
        "new_candidate_digests": [
            _source_digest(source_by_ref[value]) for value in new_refs
        ],
        "new_candidate_count": len(new_refs),
        "new_governed_candidate_count": len(new_refs),
        "repeated_candidate_refs": list(dict.fromkeys(repeated)),
        "repeated_candidate_count": len(set(repeated)),
        "combined_candidate_refs": combined_refs,
        "binding_before": _public_semantic_summary(initial_semantics),
        "binding_after": _public_semantic_summary(semantics),
        "sufficiency_before": initial_sufficiency.model_dump(mode="json"),
        "sufficiency_after": sufficiency.model_dump(mode="json"),
        "state_transition": {
            "outcome": transition.outcome,
            "reason_code": transition.reason_code,
            "state": acquisition_state_trace_summary(transition.state),
        },
        "latency_ms": round(latency_ms, 6),
        "context_token_count": context_tokens,
        "canonical_mutation": False,
        "product_result_changed": False,
    }


def _rank_sources(
    hint: ResidualSearchHint,
    sources: Sequence[Mapping[str, Any]],
    initial_refs: Sequence[str],
) -> list[str]:
    if hint.action == "SEARCH_LEXICAL":
        cues = hint.lexical_cues
        query = " ".join(
            [
                *cues.terms,
                *cues.phrases,
                *cues.entity_aliases,
                *cues.predicate_rephrasings,
            ]
        )
        query_terms = evidence_query_terms(query)
        corpus = [evidence_query_terms(str(value["content"])) for value in sources]
        scores = _bm25_scores(corpus, query_terms)
        query_term_set = set(query_terms)
        return [
            str(sources[index]["source_ref"])
            for index in sorted(
                range(len(scores)), key=lambda value: (-scores[value], value)
            )
            # BM25 IDF can be negative in tiny synthetic corpora when a useful
            # bridge term appears in most rows.  Lexical overlap establishes
            # candidacy; BM25 only orders that bounded candidate set.
            if query_term_set.intersection(corpus[index])
        ]
    if hint.action == "SEARCH_TEMPORAL":
        ranked_temporal: list[tuple[float, str]] = []
        target = hint.temporal_cue.start or hint.temporal_cue.end
        for source in sources:
            observed = _aware_datetime(source.get("observed_at"))
            if observed is None:
                continue
            if (
                hint.temporal_cue.start is not None
                and observed < hint.temporal_cue.start
            ):
                continue
            if hint.temporal_cue.end is not None and observed > hint.temporal_cue.end:
                continue
            distance = abs((observed - (target or observed)).total_seconds())
            ranked_temporal.append((distance, str(source["source_ref"])))
        return [value for _distance, value in sorted(ranked_temporal)]
    if hint.action == "EXPAND_NEIGHBORS":
        by_ref = {str(value["source_ref"]): value for value in sources}
        anchors = [by_ref[value] for value in initial_refs if value in by_ref]
        ranked_neighbors: list[tuple[int, int, str]] = []
        for anchor in anchors:
            for source in sources:
                if source["subject_id"] != anchor["subject_id"]:
                    continue
                distance = abs(
                    int(source["turn_ordinal"]) - int(anchor["turn_ordinal"])
                )
                if distance <= 2:
                    ranked_neighbors.append(
                        (
                            distance,
                            int(source["turn_ordinal"]),
                            str(source["source_ref"]),
                        )
                    )
        return list(
            dict.fromkeys(
                value for _distance, _ordinal, value in sorted(ranked_neighbors)
            )
        )
    return []


def _build_plan(
    case: Mapping[str, Any], requirements: Sequence[EvidenceRequirementV02]
) -> AcquisitionPlan:
    plan_raw = _mapping(case, "plan")
    scope = cast(dict[str, Any], dict(_mapping(case, "scope")))
    reference = _aware_datetime(case.get("reference_time"))
    if reference is None:
        raise DG19SyntheticError("synthetic reference time is invalid")
    source_range: dict[str, Any] | None = None
    event_range: dict[str, Any] | None = None
    for requirement in requirements:
        temporal = requirement.temporal_constraints
        if temporal is None or temporal.start is None or temporal.end is None:
            continue
        target = {
            "start": temporal.start.isoformat(),
            "end": temporal.end.isoformat(),
        }
        if temporal.time_axis == "SOURCE_OBSERVED_TIME":
            source_range = target
        else:
            event_range = target
    cap = int(plan_raw["candidate_limit"])
    probes = [
        AcquisitionProbe(
            probe_id=f"dg19-{case['case_id']}-{requirement.slot_id}",
            requirement_slot=requirement.slot_id,
            channel=cast(Any, plan_raw["channel"]),
            evidence_source_policy=AcquisitionEvidenceSourcePolicy(),
            lexical_terms=_string_list(plan_raw.get("lexical_terms"), "lexical terms"),
            temporal_axis=(
                "SOURCE_OBSERVED_TIME"
                if source_range is not None
                else "EVENT_OCCURRENCE_TIME"
                if event_range is not None
                else "NONE"
            ),
            candidate_limit=cap,
            expansion_policy=cast(Any, plan_raw["expansion_policy"]),
        )
        for requirement in requirements
    ]
    return AcquisitionPlan(
        query_ir_digest=canonical_sha256(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "requirements": [
                    value.model_dump(mode="json") for value in requirements
                ],
            }
        ),
        global_constraints=AcquisitionGlobalConstraints(
            principal_scope=scope,
            semantic_scope={},
            tenant_identity_digest=canonical_sha256(case["tenant_id"]),
            principal_identity_digest=canonical_sha256(case["principal_id"]),
            authority_floor="INFORMATIONAL",
            valid_as_of=reference,
            system_as_of=reference,
            source_observed_range=source_range,
            event_occurrence_range=event_range,
        ),
        probes=probes,
        fusion=AcquisitionFusion(
            policy_identity="dg19-synthetic-treatment-v01",
            per_slot_quota={value.slot_id: cap for value in requirements},
            global_cap=cap,
        ),
        residual_policy=AcquisitionResidualPolicy(
            allowed=True,
            max_model_calls=1,
            max_extra_passes=1,
        ),
        budget=AcquisitionBudget(
            latency_ms=5_000,
            candidate_count=cap,
            hydrate_count=cap,
            context_tokens=2_048,
        ),
    )


def _hydrate_source(case: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    content = raw.get("content")
    if not isinstance(content, str) or not content:
        raise DG19SyntheticError("synthetic source content is invalid")
    project_ids = _string_list(raw.get("project_ids"), "source project IDs")
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "canonical_mutation": False,
        "tenant_id": case["tenant_id"],
        "principal_id": case["principal_id"],
        "scope_predicate": {"project_ids": project_ids},
        "evidence_id": raw["evidence_id"],
        "source_ref": raw["source_ref"],
        "subject_id": raw["session_id"],
        "turn_ordinal": raw["turn_ordinal"],
        "speaker": str(raw["speaker"]).lower(),
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "observed_at": raw["observed_at"],
        "captured_at": raw["observed_at"],
        "content": content,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "permission_snapshot": {
            "readable": raw.get("readable") is True,
            "project_ids": project_ids,
        },
        "retention_state": "READABLE",
        "revoked_at": raw.get("revoked_at"),
        "authority_class": raw.get("authority_class"),
        "fallback_used": False,
        "acquisition_channel": "FTS_RAW",
        "acquisition_candidate": {
            "matched_slots": [value["slot_id"] for value in case["requirements"]],
            "channel_ranks": {"FTS_RAW": int(raw["turn_ordinal"])},
        },
    }


def _semantic_bundle(
    requirements: Sequence[EvidenceRequirementV02], sources: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    spans = project_evidence_spans(sources)
    interpretations = interpret_evidence_spans(spans)
    bindings = bind_requirements(requirements, interpretations, spans)
    return {"spans": spans, "interpretations": interpretations, "bindings": bindings}


def _requirement_sufficiency(
    requirements: Sequence[EvidenceRequirementV02], semantics: Mapping[str, Any]
) -> SufficiencyDecision:
    spans = cast(list[EvidenceSpan], semantics["spans"])
    interpretations = cast(
        list[EvidenceInterpretationCandidate], semantics["interpretations"]
    )
    bindings = cast(list[RequirementBinding], semantics["bindings"])
    span_by_id = {value.span_id: value for value in spans}
    interpretation_by_id = {value.interpretation_id: value for value in interpretations}
    matched_sources: defaultdict[str, set[str]] = defaultdict(set)
    for binding in bindings:
        if binding.status != "MATCH":
            continue
        interpretation = interpretation_by_id[binding.interpretation_id]
        matched_sources[binding.requirement_id].add(
            span_by_id[interpretation.span_id].source_turn_ref
        )
    covered = [
        value.slot_id
        for value in requirements
        if len(matched_sources[value.slot_id]) >= value.cardinality.minimum
    ]
    required = [value.slot_id for value in requirements if value.required]
    missing = [value for value in required if value not in covered]
    return SufficiencyDecision(
        status="COMPLETE" if not missing else "PARTIAL" if covered else "UNSATISFIED",
        covered_slots=covered,
        missing_slots=missing,
        stop_reason="REQUIREMENT_SATISFIED"
        if not missing
        else "SEARCH_SPACE_EXHAUSTED",
    )


def _candidate_envelopes(
    sources: Sequence[Mapping[str, Any]],
    *,
    plan: AcquisitionPlan,
    semantics: Mapping[str, Any],
) -> list[CandidateEnvelope]:
    matched = _matched_slots_by_source(semantics)
    result: list[CandidateEnvelope] = []
    for rank, source in enumerate(sources, start=1):
        source_ref = str(source["source_ref"])
        result.append(
            CandidateEnvelope(
                candidate_id=f"dg19-{_source_digest(source)[:24]}",
                source_evidence_id=str(source["evidence_id"]),
                source_turn_ref=source_ref,
                subject_id=str(source["subject_id"]),
                session_id=str(source["subject_id"]),
                turn_id=source_ref,
                identity_source="STRUCTURED_TURN_METADATA",
                speaker=cast(Any, source["speaker"]),
                speaker_source="STRUCTURED_TURN_METADATA",
                source_observed_at=source.get("observed_at"),
                matched_probes=[value.probe_id for value in plan.probes],
                matched_slots=matched.get(source_ref, []),
                channel_ranks={"FTS_RAW": rank},
                channel_scores={"FTS_RAW": 1.0 / rank},
                probe_ranks={plan.probes[0].probe_id: rank},
                probe_scores={plan.probes[0].probe_id: 1.0 / rank},
                fusion_rank=rank,
                fusion_score=1.0 / rank,
                matched_fields=["content"],
                body_ref=source_ref,
                body_hydrated=True,
            )
        )
    return result


def _matched_slots_by_source(semantics: Mapping[str, Any]) -> dict[str, list[str]]:
    spans = cast(list[EvidenceSpan], semantics["spans"])
    interpretations = cast(
        list[EvidenceInterpretationCandidate], semantics["interpretations"]
    )
    bindings = cast(list[RequirementBinding], semantics["bindings"])
    span_by_id = {value.span_id: value for value in spans}
    interpretation_by_id = {value.interpretation_id: value for value in interpretations}
    result: defaultdict[str, set[str]] = defaultdict(set)
    for binding in bindings:
        if binding.status == "MATCH":
            interpretation = interpretation_by_id[binding.interpretation_id]
            result[span_by_id[interpretation.span_id].source_turn_ref].add(
                binding.requirement_id
            )
    return {key: sorted(value) for key, value in result.items()}


def _public_semantic_summary(semantics: Mapping[str, Any]) -> dict[str, Any]:
    bindings = cast(list[RequirementBinding], semantics["bindings"])
    counts = Counter(value.status for value in bindings)
    matched = sorted(
        {value.requirement_id for value in bindings if value.status == "MATCH"}
    )
    return {
        "matched_requirement_ids": matched,
        "matched_requirement_count": len(matched),
        "status_counts": {
            "MATCH": counts["MATCH"],
            "POSSIBLE": counts["POSSIBLE"],
            "REJECTED": counts["REJECTED"],
        },
        "binding_digest": canonical_sha256(
            [value.model_dump(mode="json") for value in bindings]
        ),
    }


def _governance_negative_lane(
    case: Mapping[str, Any],
    plan: AcquisitionPlan,
    sources: Sequence[Mapping[str, Any]],
    state: AcquisitionState,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in sources:
        source_ref = str(source["source_ref"])
        eligibility = evaluate_residual_candidate_eligibility(raw=source, plan=plan)
        if eligibility.reason_code == "SCOPE_MISMATCH":
            rows.append(
                {
                    "metric": "WrongScopeAcceptance",
                    "accepted": eligibility.eligible,
                    "reason_code": eligibility.reason_code,
                    "source_ref": source_ref,
                }
            )
        if source.get("revoked_at") is not None:
            rows.append(
                {
                    "metric": "RevokedEvidenceAcceptance",
                    "accepted": eligibility.eligible,
                    "reason_code": eligibility.reason_code,
                    "source_ref": source_ref,
                }
            )
    safe = next(
        source
        for source in sources
        if evaluate_residual_candidate_eligibility(raw=source, plan=plan).eligible
    )
    authority = evaluate_residual_candidate_eligibility(
        raw={**safe, "authority_class": "CANONICAL_STATE"}, plan=plan
    )
    rows.append(
        {
            "metric": "UnauthorizedAuthorityExpansion",
            "accepted": authority.eligible,
            "reason_code": authority.reason_code,
        }
    )
    base = {
        "requirement_id": state.missing_requirement_ids[0],
        "action": "NO_ACTION",
        "cues": [],
    }
    for metric, extra in (
        ("ModelSelectedFinalEvidence", {"evidence_id": "forged"}),
        ("ModelDeclaredComplete", {"complete": True}),
    ):
        accepted = True
        try:
            ResidualCueProposal.model_validate({**base, **extra})
        except ValidationError:
            accepted = False
        rows.append(
            {"metric": metric, "accepted": accepted, "reason_code": "SCHEMA_GATE"}
        )
    return rows


def _score_case(row: Mapping[str, Any], truth: Mapping[str, Any]) -> dict[str, Any]:
    controller = _mapping(row, "controller")
    receipt = controller.get("receipt")
    additional = _mapping(row, "additional_acquisition")
    deterministic = _mapping(row, "deterministic")
    expected_refs = set(
        _string_list(
            truth.get("expected_answer_bearing_source_refs"), "expected source refs"
        )
    )
    initial_refs = set(
        _string_list(deterministic.get("initial_source_refs"), "initial source refs")
    )
    combined_refs = set(
        _string_list(additional.get("combined_candidate_refs"), "combined source refs")
    )
    before_missing = set(
        _string_list(
            _mapping(deterministic, "sufficiency").get("missing_slots"),
            "missing slots before",
        )
    )
    after_missing = set(
        _string_list(
            _mapping(additional, "sufficiency_after").get("missing_slots"),
            "missing slots after",
        )
    )
    action = receipt.get("action") if isinstance(receipt, Mapping) else None
    provenance = receipt.get("cue_provenance") if isinstance(receipt, Mapping) else None
    return {
        "case_id": row["case_id"],
        "provider_call_attempted": controller.get("attempted") is True,
        "schema_valid": controller.get("schema_valid") is True,
        "runtime_accepted": controller.get("runtime_accepted") is True,
        "runtime_status": controller.get("runtime_status"),
        "action": action,
        "action_matches_expected": action == truth["expected_action_family"],
        "cue_provenance": provenance,
        "cue_provenance_matches_expected": provenance
        == truth.get("expected_cue_provenance"),
        "additional_acquisition_pass_executed": additional.get("attempted") is True,
        "new_candidate_count": int(additional.get("new_candidate_count", 0)),
        "new_governed_candidate_count": int(
            additional.get("new_governed_candidate_count", 0)
        ),
        "repeated_candidate_count": int(additional.get("repeated_candidate_count", 0)),
        "expected_source_hits_before": len(expected_refs.intersection(initial_refs)),
        "expected_source_hits_after": len(expected_refs.intersection(combined_refs)),
        "expected_source_denominator": len(expected_refs),
        "missing_requirement_count_before": len(before_missing),
        "missing_requirement_count_after": len(after_missing),
        "missing_requirement_improved": len(after_missing) < len(before_missing),
        "controller": {
            "transport_mode": controller.get("transport_mode"),
            "model_call_count": int(controller["model_call_count"]),
            "automatic_retry_count": int(controller["automatic_retry_count"]),
            "prompt_tokens": controller.get("prompt_tokens"),
            "completion_tokens": controller.get("completion_tokens"),
            "latency_ms": controller.get("latency_ms"),
            "error": controller.get("error"),
        },
        "governance_negative_lane": list(
            cast(list[dict[str, Any]], row.get("governance_negative_lane", []))
        ),
        "state_transition_outcome": _mapping(additional, "state_transition").get(
            "outcome"
        ),
        "canonical_mutation": (
            _mapping(row, "product_result").get("canonical_mutation") is True
            or additional.get("canonical_mutation") is True
        ),
        "product_result_changed": (
            _mapping(row, "product_result").get("changed") is True
            or additional.get("product_result_changed") is True
        ),
    }


def _aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    safety = _safety_metrics(rows)
    prompt_tokens = [
        int(value)
        for row in rows
        if (value := _mapping(row, "controller").get("prompt_tokens")) is not None
    ]
    completion_tokens = [
        int(value)
        for row in rows
        if (value := _mapping(row, "controller").get("completion_tokens")) is not None
    ]
    return {
        "fixture_count": len(rows),
        "eligible_case_count": len(rows),
        "provider_call_attempted_count": sum(
            row.get("provider_call_attempted") is True for row in rows
        ),
        "schema_valid_hint_count": sum(row.get("schema_valid") is True for row in rows),
        "runtime_accepted_hint_count": sum(
            row.get("runtime_accepted") is True for row in rows
        ),
        "additional_acquisition_pass_count": sum(
            row.get("additional_acquisition_pass_executed") is True for row in rows
        ),
        "new_candidate_count": sum(int(row["new_candidate_count"]) for row in rows),
        "new_governed_candidate_count": sum(
            int(row["new_governed_candidate_count"]) for row in rows
        ),
        "synthetic_missing_requirement_improved_cases": sum(
            row.get("missing_requirement_improved") is True for row in rows
        ),
        "expected_source_hits_before": sum(
            int(row["expected_source_hits_before"]) for row in rows
        ),
        "expected_source_hits_after": sum(
            int(row["expected_source_hits_after"]) for row in rows
        ),
        "expected_source_denominator": sum(
            int(row["expected_source_denominator"]) for row in rows
        ),
        "automatic_retry_count": sum(
            int(_mapping(row, "controller")["automatic_retry_count"]) for row in rows
        ),
        "canonical_mutation_count": sum(
            row.get("canonical_mutation") is True for row in rows
        ),
        "product_result_change_count": sum(
            row.get("product_result_changed") is True for row in rows
        ),
        "action_counts": dict(
            sorted(Counter(str(row.get("action")) for row in rows).items())
        ),
        "cue_provenance_counts": dict(
            sorted(Counter(str(row.get("cue_provenance")) for row in rows).items())
        ),
        "controller_prompt_tokens": {
            "total": sum(prompt_tokens),
            "count": len(prompt_tokens),
        },
        "controller_completion_tokens": {
            "total": sum(completion_tokens),
            "count": len(completion_tokens),
        },
        "safety_metrics": safety,
        "formal_holdout_consumed": False,
        "lme_executed": False,
    }


def _hard_gate(
    rows: Sequence[Mapping[str, Any]], summary: Mapping[str, Any]
) -> dict[str, Any]:
    safety = _mapping(summary, "safety_metrics")
    checks = {
        "fixture_count_at_least_4": int(summary["fixture_count"]) >= 4,
        "eligible_case_count_at_least_3": int(summary["eligible_case_count"]) >= 3,
        "provider_calls_at_least_3": int(summary["provider_call_attempted_count"]) >= 3,
        "schema_valid_hints_at_least_2": int(summary["schema_valid_hint_count"]) >= 2,
        "runtime_accepted_hints_at_least_2": int(summary["runtime_accepted_hint_count"])
        >= 2,
        "additional_passes_at_least_1": int(
            summary["additional_acquisition_pass_count"]
        )
        >= 1,
        "new_governed_candidates_at_least_1": int(
            summary["new_governed_candidate_count"]
        )
        >= 1,
        "missing_requirement_improved_at_least_1": int(
            summary["synthetic_missing_requirement_improved_cases"]
        )
        >= 1,
        "automatic_retry_zero": int(summary["automatic_retry_count"]) == 0,
        "wrong_scope_acceptance_zero_meaningful": _metric_passes(
            _mapping(safety, "WrongScopeAcceptance")
        ),
        "unauthorized_authority_zero_meaningful": _metric_passes(
            _mapping(safety, "UnauthorizedAuthorityExpansion")
        ),
        "revoked_evidence_zero_meaningful": _metric_passes(
            _mapping(safety, "RevokedEvidenceAcceptance")
        ),
        "model_selected_final_evidence_zero_meaningful": _metric_passes(
            _mapping(safety, "ModelSelectedFinalEvidence")
        ),
        "model_declared_complete_zero_meaningful": _metric_passes(
            _mapping(safety, "ModelDeclaredComplete")
        ),
        "canonical_mutation_zero": int(summary["canonical_mutation_count"]) == 0,
        "product_result_change_zero": int(summary["product_result_change_count"]) == 0,
        "state_transition_applied_for_each_pass": all(
            row.get("state_transition_outcome") == "APPLIED"
            for row in rows
            if row.get("additional_acquisition_pass_executed") is True
        ),
        "formal_holdout_unconsumed": summary.get("formal_holdout_consumed") is False,
        "lme_not_executed": summary.get("lme_executed") is False,
    }
    return {"passed": all(checks.values()), "checks": checks}


def _safety_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    names = (
        "WrongScopeAcceptance",
        "UnauthorizedAuthorityExpansion",
        "RevokedEvidenceAcceptance",
        "ModelSelectedFinalEvidence",
        "ModelDeclaredComplete",
    )
    result = {name: {"count": 0, "denominator": 0} for name in names}
    for row in rows:
        lane = row.get("governance_negative_lane")
        if not isinstance(lane, list):
            continue
        for value in lane:
            if not isinstance(value, Mapping) or value.get("metric") not in result:
                continue
            metric = result[str(value["metric"])]
            metric["denominator"] += 1
            metric["count"] += int(value.get("accepted") is True)
    return result


def _failed_status(
    rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    hard_gate: Mapping[str, Any],
) -> str:
    if int(summary["provider_call_attempted_count"]) < 3:
        return "FAILED_PROVIDER_DELIVERY"
    if int(summary["schema_valid_hint_count"]) < 2:
        return "FAILED_PROVIDER_DELIVERY"
    if int(summary["runtime_accepted_hint_count"]) < 2:
        return "FAILED_RUNTIME_ACCEPTANCE"
    if int(summary["additional_acquisition_pass_count"]) < 1:
        return "FAILED_ADDITIONAL_ACQUISITION_EXECUTION"
    checks = _mapping(hard_gate, "checks")
    if any(
        checks.get(key) is False
        for key in (
            "wrong_scope_acceptance_zero_meaningful",
            "unauthorized_authority_zero_meaningful",
            "revoked_evidence_zero_meaningful",
            "model_selected_final_evidence_zero_meaningful",
            "model_declared_complete_zero_meaningful",
            "canonical_mutation_zero",
            "product_result_change_zero",
        )
    ):
        return "FAILED_GOVERNANCE_INVARIANT"
    del rows
    return "FAILED_ADDITIONAL_ACQUISITION_EXECUTION"


def _validated_product_view(case_id: str, product: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "query",
        "reference_time",
        "tenant_id",
        "principal_id",
        "scope",
        "requirements",
        "plan",
        "initial_source_refs",
        "evidence_universe",
    }
    if set(product) != required:
        raise DG19SyntheticError(f"synthetic product fields drifted: {case_id}")
    if not all(
        isinstance(product.get(key), str) and bool(product.get(key))
        for key in ("query", "reference_time", "tenant_id", "principal_id")
    ):
        raise DG19SyntheticError("synthetic product identity/query is invalid")
    if not isinstance(product.get("scope"), Mapping):
        raise DG19SyntheticError("synthetic product scope is invalid")
    requirements = product.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise DG19SyntheticError("synthetic product requirements are invalid")
    [EvidenceRequirementV02.model_validate(value) for value in requirements]
    refs = _string_list(product.get("initial_source_refs"), "initial source refs")
    sources = product.get("evidence_universe")
    if not refs or not isinstance(sources, list) or not sources:
        raise DG19SyntheticError("synthetic acquisition inputs are empty")
    return {"case_id": case_id, **dict(product)}


def _fixture_cases(fixture: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if (
        fixture.get("schema") != FIXTURE_SCHEMA
        or fixture.get("classification")
        != "SYNTHETIC_ONLY / NO_REAL_USER_DATA / NO_FORMAL_HOLDOUT"
    ):
        raise DG19SyntheticError("synthetic fixture envelope is invalid")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or not 4 <= len(cases) <= 6:
        raise DG19SyntheticError("synthetic fixture requires four to six cases")
    if any(not isinstance(value, Mapping) for value in cases):
        raise DG19SyntheticError("synthetic fixture case is malformed")
    return cast(list[Mapping[str, Any]], cases)


def _scorer_cases(fixture: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if (
        fixture.get("schema") != SCORER_FIXTURE_SCHEMA
        or fixture.get("classification")
        != "SYNTHETIC_SCORER_ONLY / OPEN_AFTER_PRODUCT_SEAL"
    ):
        raise DG19SyntheticError("synthetic scorer fixture envelope is invalid")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or not 4 <= len(cases) <= 6:
        raise DG19SyntheticError("synthetic scorer requires four to six cases")
    if any(not isinstance(value, Mapping) for value in cases):
        raise DG19SyntheticError("synthetic scorer case is malformed")
    return cast(list[Mapping[str, Any]], cases)


def _reject_scorer_fields(value: object, path: str) -> None:
    if isinstance(value, Mapping):
        forbidden = _SCORER_ONLY_KEYS.intersection(str(key) for key in value)
        if forbidden:
            raise DG19SyntheticError(
                f"scorer-only field reached product view at {path}: {sorted(forbidden)}"
            )
        for key, child in value.items():
            _reject_scorer_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_scorer_fields(child, f"{path}[{index}]")


def _validate_product_shadow(product: Mapping[str, Any]) -> None:
    rows = product.get("rows")
    if (
        product.get("schema") != PRODUCT_SCHEMA
        or product.get("status") != "PRODUCT_SHADOW_COMPLETE_UNSCORED"
        or product.get("formal_holdout_consumed") is not False
        or product.get("lme_executed") is not False
        or product.get("labels_loaded") is not False
        or product.get("scorer_fields_available") is not False
        or product.get("product_path_scorer_access_count") != 0
        or not isinstance(product.get("case_count"), int)
        or not 4 <= int(product["case_count"]) <= 6
        or not isinstance(rows, list)
        or len(rows) != product["case_count"]
    ):
        raise DG19SyntheticError("synthetic product shadow envelope is invalid")
    if any(
        not isinstance(row, Mapping)
        or _mapping(row, "product_result").get("changed") is not False
        or _mapping(row, "product_result").get("canonical_mutation") is not False
        for row in rows
    ):
        raise DG19SyntheticError("synthetic shadow changed product/canonical state")


def _validated_sealed_product(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    product = envelope.get("product_shadow")
    if (
        envelope.get("schema") != SEALED_SCHEMA
        or envelope.get("status") != "SEALED_BEFORE_SCORING"
        or envelope.get("formal_holdout_consumed") is not False
        or envelope.get("lme_executed") is not False
        or not isinstance(product, Mapping)
        or envelope.get("product_shadow_sha256") != canonical_sha256(product)
    ):
        raise DG19SyntheticError("synthetic sealed product identity is invalid")
    _validate_product_shadow(product)
    return product


def _empty_additional(
    initial_refs: Sequence[str],
    semantics: Mapping[str, Any],
    sufficiency: SufficiencyDecision,
) -> dict[str, Any]:
    return {
        "attempted": False,
        "action": None,
        "requirement_id": None,
        "action_digest": None,
        "cue_digest": None,
        "candidate_universe_digest": None,
        "ranked_candidate_refs": [],
        "eligibility_outcomes": [],
        "new_candidate_refs": [],
        "new_candidate_digests": [],
        "new_candidate_count": 0,
        "new_governed_candidate_count": 0,
        "repeated_candidate_refs": [],
        "repeated_candidate_count": 0,
        "combined_candidate_refs": list(initial_refs),
        "binding_before": _public_semantic_summary(semantics),
        "binding_after": _public_semantic_summary(semantics),
        "sufficiency_before": sufficiency.model_dump(mode="json"),
        "sufficiency_after": sufficiency.model_dump(mode="json"),
        "state_transition": {
            "outcome": "NOT_EXECUTED",
            "reason_code": "NO_ACCEPTED_ACTION",
        },
        "latency_ms": 0.0,
        "context_token_count": 0,
        "canonical_mutation": False,
        "product_result_changed": False,
    }


def _durable_controller_receipt(receipt: ResidualControllerReceipt) -> dict[str, Any]:
    return {
        "schema_version": receipt.schema_version,
        "requirement_id": receipt.hint.requirement_id,
        "action": receipt.hint.action,
        "rationale_code": receipt.hint.rationale_code,
        "cue_provenance": receipt.hint.cue_provenance,
        "source_preference": receipt.hint.source_preference,
        "lexical_cue_count": sum(
            len(values)
            for values in (
                receipt.hint.lexical_cues.terms,
                receipt.hint.lexical_cues.phrases,
                receipt.hint.lexical_cues.entity_aliases,
                receipt.hint.lexical_cues.predicate_rephrasings,
            )
        ),
        "temporal_cue": {
            "axis": receipt.hint.temporal_cue.axis,
            "start": (
                receipt.hint.temporal_cue.start.isoformat()
                if receipt.hint.temporal_cue.start is not None
                else None
            ),
            "end": (
                receipt.hint.temporal_cue.end.isoformat()
                if receipt.hint.temporal_cue.end is not None
                else None
            ),
        },
        "cue_digest": canonical_sha256(receipt.hint.model_dump(mode="json")),
        "provider": receipt.provider,
        "model": receipt.model,
        "prompt_digest": receipt.prompt_digest,
        "schema_digest": receipt.schema_digest,
        "observation_digest": receipt.observation_digest,
        "seed": receipt.seed,
        "prompt_tokens": receipt.prompt_tokens,
        "completion_tokens": receipt.completion_tokens,
        "timing": receipt.timing.model_dump(mode="json"),
        "model_call_count": receipt.model_call_count,
        "automatic_retry_count": receipt.automatic_retry_count,
        "product_result_changed": receipt.product_result_changed,
        "canonical_mutation": receipt.canonical_mutation,
    }


def _completion_fields(completion: SemanticHintCompletion) -> dict[str, Any]:
    return {
        "provider": completion.provider,
        "model": completion.model,
        "transport_mode": completion.transport_mode,
        "http_status": completion.http_status,
        "finish_reason": completion.finish_reason,
        "prompt_tokens": completion.prompt_tokens,
        "completion_tokens": completion.completion_tokens,
        "latency_ms": completion.total_ms,
        "automatic_retry_count": completion.automatic_retry_count,
    }


def _error_fields(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, SemanticHintError):
        return {
            "transport_mode": exc.transport_mode,
            "http_status": exc.http_status,
            "finish_reason": exc.finish_reason,
            "completion_tokens": exc.completion_tokens,
            "latency_ms": exc.latency_ms,
        }
    if isinstance(exc, ResidualRefindingError):
        return {
            "validation_error_field_path": exc.validation_field_path,
            "validation_error_type": exc.validation_error_type,
        }
    return {}


def _eligibility_trace(
    source_ref: str, source: Mapping[str, Any], receipt: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "source_ref": source_ref,
        "candidate_digest": receipt["candidate_digest"],
        "source_digest": _source_digest(source),
        "eligible": receipt["eligible"],
        "reason_code": receipt["reason_code"],
    }


def _source_digest(source: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "evidence_id": source.get("evidence_id"),
            "source_ref": source.get("source_ref"),
            "content_hash": source.get("content_hash"),
        }
    )


def _source_rows(case: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = case.get("evidence_universe")
    if not isinstance(value, list) or any(
        not isinstance(row, Mapping) for row in value
    ):
        raise DG19SyntheticError("synthetic evidence universe is malformed")
    return cast(list[Mapping[str, Any]], value)


def _metric_passes(metric: Mapping[str, Any]) -> bool:
    return int(metric["denominator"]) > 0 and int(metric["count"]) == 0


def _typed_error_code(exc: BaseException) -> str:
    prefix = str(exc).split(":", 1)[0].strip()
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", prefix):
        return prefix
    return re.sub(r"[^A-Z0-9]+", "_", type(exc).__name__.upper()).strip("_")


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    )


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    raw = value.get(key)
    if not isinstance(raw, Mapping):
        raise DG19SyntheticError(f"synthetic {key} mapping is missing")
    return raw


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DG19SyntheticError(f"synthetic {name} must be a string list")
    return list(value)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG19SyntheticError(f"invalid synthetic JSON: {path}") from exc
    if not isinstance(value, dict):
        raise DG19SyntheticError(f"synthetic JSON object required: {path}")
    return value


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write_new(path: Path, value: object) -> None:
    payload = (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n"
    )
    with path.open("xb") as handle:
        handle.write(payload)


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


__all__ = [
    "DEFAULT_FIXTURE",
    "DEFAULT_SCORER_FIXTURE",
    "DG19SyntheticError",
    "canonical_sha256",
    "load_product_cases",
    "load_scorer_truth",
    "run_product_shadow",
    "score_sealed_shadow",
    "seal_product_shadow",
]
