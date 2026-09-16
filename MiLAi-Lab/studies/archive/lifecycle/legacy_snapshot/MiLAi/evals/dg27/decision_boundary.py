"""Matched DG-27 D0-D3 effect and scorer over the frozen opened-development set."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote

from milai.adapters.grounded_interpretation import (
    GroundedInterpretationExecution,
    LoopbackGroundedInterpretationAdapter,
)
from milai.application.decision_boundary import (
    decide_deterministic_boundary,
    decide_semantic_boundary,
)
from milai.domain.acquisition import CandidateEnvelope
from milai.domain.decision_boundary import SemanticInterpretationSetV02
from milai.domain.requirement_state import canonical_sha256
from milai.domain.sufficiency import SufficiencyProof

from evals.dg26.stateview_reranking import ExperimentInputs, load_experiment_inputs

DG26_LOCK = Path("var/dg26/run-lock.json")
DG26_RESULTS = Path("var/dg26/results.json")
DG25_E1_OUTPUTS = Path(
    "var/dg25/s3a/dg25-s3a-e1-label-free-20260830-001/"
    "e1-label-free-arm-outputs.json"
)
GOLD_REGISTRY = Path(
    "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
    "gold-equivalence-registry-v0.1.json"
)
_LONG_SOURCE_REF = re.compile(
    r"^longmemeval://case/([^/]+)/session/(\d+)/([^/]+)/turn/(\d+)(?:\?|$)"
)
_D0_ARMS = (
    "R1",
    "R2",
    "R3",
    "R4",
    "R5_NO_SYNONYM_NORMALIZATION",
    "R_FINAL_DROP_OPTIONAL_CHANNEL_UNION",
    "R_FINAL_DROP_ROLE_RESERVATION",
    "R_FINAL_DROP_SOFT_LEXICAL_FEATURES",
)


class DG27EffectError(RuntimeError):
    """The frozen DG-27 effect contract or one input identity drifted."""


def load_run_lock(root: Path, path: Path) -> dict[str, Any]:
    root = root.resolve()
    lock = _object(path)
    if lock.get("schema") != "milai.dg27.v02.run-lock.v0.2":
        raise DG27EffectError("DG27_V02_RUN_LOCK_SCHEMA_DRIFT")
    material = dict(lock)
    observed = material.pop("lock_digest", None)
    if observed != canonical_sha256(material):
        raise DG27EffectError("DG27_V02_RUN_LOCK_DIGEST_MISMATCH")
    if lock.get("config_digest") != canonical_sha256(lock.get("config")):
        raise DG27EffectError("DG27_V02_CONFIG_DIGEST_MISMATCH")
    for identity in _sequence(lock.get("bound_identities"), "bound identities"):
        _verify_identity(root, _mapping(identity, "bound identity"))
    safety = _mapping(lock.get("safety"), "safety")
    budget = _mapping(lock.get("budget"), "budget")
    if (
        safety.get("candidate_feature_flag") != "OFF"
        or safety.get("canonical_mutations") != 0
        or lock.get("formal_holdout_used") is not False
        or budget.get("automatic_retries") != 0
    ):
        raise DG27EffectError("DG27_V02_SAFETY_BOUNDARY_DRIFT")
    return lock


def historical_wrong_complete_occurrences(root: Path) -> list[dict[str, str]]:
    """Return the exact DG-25 16-occurrence D0 replay denominator."""

    bundle = _object(root / DG25_E1_OUTPUTS)
    arms = _mapping(bundle.get("arm_outputs"), "DG25 arm outputs")
    occurrences: list[dict[str, str]] = []
    for arm_id in _D0_ARMS:
        arm = _mapping(arms.get(arm_id), f"DG25 arm {arm_id}")
        for record in _sequence(arm.get("records"), f"DG25 records {arm_id}"):
            row = _mapping(record, "DG25 record")
            for requirement in _sequence(row.get("requirements"), "DG25 requirements"):
                item = _mapping(requirement, "DG25 requirement")
                selected = [
                    _mapping(value, "DG25 selected occurrence")
                    for value in _sequence(
                        item.get("selected_occurrences"), "DG25 selected occurrences"
                    )
                ]
                has_match = any(value.get("binding_status") == "MATCH" for value in selected)
                if item.get("sufficiency") == "COMPLETE" and not has_match:
                    occurrences.append(
                        {
                            "arm_id": arm_id,
                            "query_id": str(row["query_id"]),
                            "requirement_id": str(item["requirement_id"]),
                        }
                    )
    expected = [
        (arm, query_id)
        for arm in _D0_ARMS
        for query_id in ("2e6d26dc", "88432d0a")
    ]
    observed = [(item["arm_id"], item["query_id"]) for item in occurrences]
    if observed != expected or any(
        item["requirement_id"] != "MATCHING_EVENTS_IN_RANGE"
        for item in occurrences
    ):
        raise DG27EffectError("DG27_D0_REPLAY_DENOMINATOR_DRIFT")
    return occurrences


def historical_baseline_accepted_sources(root: Path) -> list[dict[str, str]]:
    """Recover the label-free R0 Binding set used before DG-27."""

    bundle = _object(root / DG25_E1_OUTPUTS)
    arms = _mapping(bundle.get("arm_outputs"), "DG25 arm outputs")
    arm = _mapping(arms.get("R0"), "DG25 R0")
    accepted: set[tuple[str, str, str]] = set()
    for record in _sequence(arm.get("records"), "DG25 R0 records"):
        row = _mapping(record, "DG25 R0 record")
        for requirement in _sequence(row.get("requirements"), "DG25 R0 requirements"):
            item = _mapping(requirement, "DG25 R0 requirement")
            for occurrence in _sequence(
                item.get("selected_occurrences"), "DG25 R0 selected occurrences"
            ):
                selected = _mapping(occurrence, "DG25 R0 selected occurrence")
                if selected.get("binding_status") == "MATCH":
                    accepted.add(
                        (
                            str(row["query_id"]),
                            str(item["requirement_id"]),
                            str(selected["source_turn_ref"]),
                        )
                    )
    return [
        {"case_id": case_id, "requirement_id": requirement_id, "source_ref": source_ref}
        for case_id, requirement_id, source_ref in sorted(accepted)
    ]


def frozen_candidate_manifest(root: Path) -> list[dict[str, Any]]:
    """Return the 15-requirement / 110-candidate V02 freeze material."""

    inputs = load_experiment_inputs(root.resolve(), root.resolve() / DG26_LOCK)
    return _candidate_manifest(_case_inputs(inputs))


def execute_effect(
    root: Path,
    run_lock_path: Path,
    *,
    adapter: LoopbackGroundedInterpretationAdapter,
) -> dict[str, Any]:
    """Execute D0-D3 once, seal outputs, then open scorer labels."""

    root = root.resolve()
    lock = load_run_lock(root, run_lock_path)
    inputs = load_experiment_inputs(root, root / DG26_LOCK)
    cases = _case_inputs(inputs)
    expected_manifest = str(
        _mapping(lock["candidate_snapshot"], "candidate snapshot")["manifest_digest"]
    )
    manifest = _candidate_manifest(cases)
    if canonical_sha256(manifest) != expected_manifest:
        raise DG27EffectError("DG27_V02_CANDIDATE_SNAPSHOT_DRIFT")
    proof_by_case = _proofs_by_case(root)

    model_sets: dict[str, dict[str, tuple[SemanticInterpretationSetV02, ...]]] = {}
    model_usage: list[dict[str, Any]] = []
    for case_id in inputs.contexts:
        case = cases[case_id]
        context = inputs.contexts[case_id]
        model_sets[case_id] = {}
        requirement_by_id = {item.slot_id: item for item in context.query_ir.requirements}
        for requirement_id in context.requirement_ids:
            source_records = [
                case["source_by_id"][item.candidate_id]
                for item in case["candidates"]
                if requirement_id in item.matched_slots
            ]
            execution = adapter.interpret(
                query=context.query,
                requirement=requirement_by_id[requirement_id],
                candidates=source_records,
            )
            model_sets[case_id][requirement_id] = execution.interpretation_sets
            model_usage.append(_usage(case_id, requirement_id, execution))

    arms: dict[str, list[dict[str, Any]]] = {"D1": [], "D2": [], "D3": []}
    for case_id in inputs.contexts:
        case = cases[case_id]
        context = inputs.contexts[case_id]
        common = {
            "plan": context.acquisition_plan,
            "query_ir": context.query_ir,
            "acquisition_capability_digest": case["capability_digest"],
            "candidates": case["candidates"],
            "source_records": list(case["source_by_id"].values()),
            "completion_proof": proof_by_case[case_id],
        }
        d1 = decide_deterministic_boundary(**common)
        d2 = decide_semantic_boundary(
            **common,
            interpretation_sets_by_requirement=model_sets[case_id],
        )
        d3 = decide_semantic_boundary(
            **common,
            interpretation_sets_by_requirement={
                requirement_id: tuple(_single_best(item) for item in values)
                for requirement_id, values in model_sets[case_id].items()
            },
        )
        for arm_id, decision in (("D1", d1), ("D2", d2), ("D3", d3)):
            arms[arm_id].append(
                {
                    "case_id": case_id,
                    "decision": decision.model_dump(mode="json"),
                    "accepted_sources": [
                        {
                            "requirement_id": item.requirement_id,
                            "evidence_id": item.evidence_id,
                            "source_ref": str(
                                case["source_by_id"][item.evidence_id]["source_ref"]
                            ),
                        }
                        for item in decision.accepted_bindings
                    ],
                }
            )
    unscored = {
        "arm_order": ["D0", "D1", "D2", "D3"],
        "D0_replay": historical_wrong_complete_occurrences(root),
        "D0_baseline_accepted_sources": historical_baseline_accepted_sources(root),
        "arms": arms,
        "model_usage": model_usage,
    }
    unscored_seal_digest = canonical_sha256(unscored)

    gold = _object(root / GOLD_REGISTRY)
    scores = score_effect(unscored, gold)
    output: dict[str, Any] = {
        "schema": "milai.dg27.v02.results.v0.2",
        "goal_id": "DG-27",
        "run_id": lock["run_id"],
        "run_lock_digest": lock["lock_digest"],
        "arm_order": ["D0", "D1", "D2", "D3"],
        "label_boundary": {
            "model_visible_gold_labels": 0,
            "gold_registry_open_phase": "POST_D0_D3_OUTPUT_SEAL",
            "unscored_output_seal_digest": unscored_seal_digest,
            "registry_open_count": 1,
        },
        "unscored": unscored,
        "scores": scores,
        "cost": {
            "model_calls": len(model_usage),
            "interpreted_candidate_occurrences": sum(
                len(row["candidates"]) for row in manifest
            ),
            "final_validation_calls": 30,
            "prompt_tokens": sum(int(item["prompt_tokens"]) for item in model_usage),
            "completion_tokens": sum(
                int(item["completion_tokens"]) for item in model_usage
            ),
            "latency_ms": round(sum(float(item["latency_ms"]) for item in model_usage), 3),
            "automatic_retries": sum(
                int(item["automatic_retries"]) for item in model_usage
            ),
            "acquisition_calls": 0,
            "reader_calls": 0,
        },
        "safety": {
            "canonical_mutations": 0,
            "authority_violations": 0,
            "candidate_feature_flag": "OFF",
            "formal_holdout_used": False,
        },
    }
    output["results_digest"] = canonical_sha256(output)
    return output


def score_effect(unscored: Mapping[str, Any], gold: Mapping[str, Any]) -> dict[str, Any]:
    """Score final AcceptedBinding only; provisional candidates are never positives."""

    groups = _gold_groups(gold)
    baseline = _baseline_groups(unscored, groups)
    d0 = _sequence(unscored.get("D0_replay"), "D0 replay")
    arm_scores: dict[str, Any] = {
        "D0": {
            "wrong_complete": len(d0),
            "known_false_accepted_binding": None,
            "historical_occurrences_replayed": len(d0),
        }
    }
    replay_keys = {
        (str(item["query_id"]), str(item["requirement_id"]))
        for value in d0
        for item in [_mapping(value, "D0 occurrence")]
    }
    arms = _mapping(unscored.get("arms"), "DG27 arms")
    covered_by_arm: dict[str, set[str]] = {}
    for arm_id in ("D1", "D2", "D3"):
        records = [
            _mapping(item, f"{arm_id} record")
            for item in _sequence(arms.get(arm_id), f"{arm_id} records")
        ]
        accepted: list[tuple[str, str, str]] = []
        wrong_complete = 0
        operator_ready = 0
        provisional_hypotheses = 0
        ambiguous = 0
        for record in records:
            case_id = str(record["case_id"])
            decision = _mapping(record.get("decision"), f"{arm_id} decision")
            if decision.get("operator_ready") is True:
                operator_ready += 1
            provisional = [
                _mapping(item, f"{arm_id} provisional")
                for item in _sequence(
                    decision.get("provisional_bindings"), f"{arm_id} provisional"
                )
            ]
            provisional_hypotheses += sum(
                len(_sequence(item.get("supporting_interpretation_ids"), "support ids"))
                for item in provisional
            )
            ambiguous += sum(item.get("status") == "AMBIGUOUS" for item in provisional)
            record_accepted: set[tuple[str, str, str]] = set()
            for source in _sequence(record.get("accepted_sources"), "accepted sources"):
                item = _mapping(source, "accepted source")
                accepted_source = (
                    case_id,
                    str(item["requirement_id"]),
                    _compact_source_ref(str(item["source_ref"])),
                )
                accepted.append(accepted_source)
                record_accepted.add(accepted_source)
            sufficiency = _mapping(
                decision.get("sufficiency_decision"), f"{arm_id} sufficiency"
            )
            if sufficiency.get("status") == "COMPLETE":
                for key in replay_keys:
                    if key[0] != case_id:
                        continue
                    required_groups = [
                        refs
                        for (
                            group_case,
                            group_requirement,
                            _group_id,
                        ), refs in groups.items()
                        if group_case == key[0] and group_requirement == key[1]
                    ]
                    if not required_groups or any(
                        not any(
                            accepted_case == key[0]
                            and accepted_requirement == key[1]
                            and accepted_ref in refs
                            for (
                                accepted_case,
                                accepted_requirement,
                                accepted_ref,
                            ) in record_accepted
                        )
                        for refs in required_groups
                    ):
                        wrong_complete += 1
        accepted_unique = set(accepted)
        covered = {
            group_id
            for (case_id, requirement_id, group_id), source_refs in groups.items()
            if any(
                accepted_case == case_id
                and accepted_requirement == requirement_id
                and source_ref in source_refs
                for accepted_case, accepted_requirement, source_ref in accepted_unique
            )
        }
        covered_by_arm[arm_id] = covered
        false = {
            item
            for item in accepted_unique
            if not any(
                item[0] == case_id
                and item[1] == requirement_id
                and item[2] in source_refs
                for (case_id, requirement_id, _group_id), source_refs in groups.items()
            )
        }
        precision = (
            (len(accepted_unique) - len(false)) / len(accepted_unique)
            if accepted_unique
            else 1.0
        )
        arm_scores[arm_id] = {
            "accepted_binding_count": len(accepted_unique),
            "accepted_binding_precision": precision,
            "known_false_accepted_binding": len(false),
            "valid_binding_groups": len(covered),
            "valid_binding_recall": len(covered) / len(groups),
            "baseline_correct_groups_lost": len(baseline - covered),
            "wrong_complete": wrong_complete,
            "operator_ready_cases": operator_ready,
            "provisional_hypotheses": provisional_hypotheses,
            "ambiguous_provisional_bindings": ambiguous,
        }
    d2_gain = len(covered_by_arm["D2"] - covered_by_arm["D1"])
    d2_loss = len(covered_by_arm["D1"] - covered_by_arm["D2"])
    d3_gain = len(covered_by_arm["D3"] - covered_by_arm["D1"])
    checks = {
        "d0_exact_16_replayed": len(d0) == 16,
        "d1_wrong_complete_zero": arm_scores["D1"]["wrong_complete"] == 0,
        "d2_wrong_complete_zero": arm_scores["D2"]["wrong_complete"] == 0,
        "d3_wrong_complete_zero": arm_scores["D3"]["wrong_complete"] == 0,
        "d1_correct_group_non_regression": arm_scores["D1"][
            "baseline_correct_groups_lost"
        ]
        == 0,
        "d2_known_false_binding_zero": arm_scores["D2"][
            "known_false_accepted_binding"
        ]
        == 0,
        "d2_correct_group_non_regression": arm_scores["D2"][
            "baseline_correct_groups_lost"
        ]
        == 0,
    }
    if not all(
        checks[key]
        for key in (
            "d0_exact_16_replayed",
            "d1_wrong_complete_zero",
            "d2_wrong_complete_zero",
            "d3_wrong_complete_zero",
            "d1_correct_group_non_regression",
        )
    ):
        status, reason = "FAIL", "WRONG_COMPLETE_OR_CORRECT_CASE_REGRESSION"
    elif not checks["d2_known_false_binding_zero"]:
        status, reason = "FAIL", "KNOWN_FALSE_BINDING_ACCEPTED"
    elif not checks["d2_correct_group_non_regression"]:
        status, reason = "FAIL", "FINAL_CORRECT_CASE_REGRESSION"
    elif d2_gain >= 1 and d2_loss == 0:
        status, reason = "PASS", "PROVISIONAL_INTERPRETATION_GAIN"
    else:
        status, reason = "PASS", "DECISION_BOUNDARY_REPAIRED"
    result: dict[str, Any] = {
        "schema": "milai.dg27.v02.effect-score.v0.2",
        "denominators": {
            "queries": 10,
            "requirements": 15,
            "evidence_equivalence_groups": len(groups),
            "wrong_complete_occurrences": len(d0),
        },
        "baseline_valid_groups": len(baseline),
        "arms": arm_scores,
        "comparisons": {
            "d2_minus_d1_valid_groups": d2_gain - d2_loss,
            "d2_new_valid_groups": d2_gain,
            "d2_lost_d1_valid_groups": d2_loss,
            "d3_new_valid_groups_over_d1": d3_gain,
        },
        "checks": checks,
        "status": status,
        "reason_code": reason,
    }
    result["score_digest"] = canonical_sha256(result)
    return result


def _case_inputs(inputs: ExperimentInputs) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for case_id, context in inputs.contexts.items():
        selected_by_requirement: dict[str, list[dict[str, Any]]] = {}
        for requirement_id in context.requirement_ids:
            pool = inputs.pools[(case_id, requirement_id)]
            selected_by_requirement[requirement_id] = [
                dict(item) for item in pool.candidates[: min(8, len(pool.candidates))]
            ]
        source_by_id: dict[str, dict[str, Any]] = {}
        matched_slots: dict[str, set[str]] = defaultdict(set)
        ranks: dict[str, int] = {}
        for requirement_id, selected in selected_by_requirement.items():
            for rank, source in enumerate(selected, start=1):
                evidence_id = str(source["evidence_id"])
                source_by_id.setdefault(evidence_id, source)
                matched_slots[evidence_id].add(requirement_id)
                ranks[evidence_id] = min(ranks.get(evidence_id, rank), rank)
        ordered_sources = sorted(
            source_by_id.values(),
            key=lambda item: (ranks[str(item["evidence_id"])], str(item["evidence_id"])),
        )
        candidates = [
            _candidate(
                source,
                slots=sorted(matched_slots[str(source["evidence_id"])]),
                fusion_rank=index,
                source_rank=ranks[str(source["evidence_id"])],
            )
            for index, source in enumerate(ordered_sources, start=1)
        ]
        cases[case_id] = {
            "candidates": candidates,
            "source_by_id": {
                str(item["evidence_id"]): item for item in ordered_sources
            },
            "selected_by_requirement": selected_by_requirement,
            "capability_digest": canonical_sha256(
                {
                    "capability": "DG27_FIXED_DG26_R0_SELECTION",
                    "pools": [
                        inputs.pools[(case_id, requirement_id)].pool_digest
                        for requirement_id in context.requirement_ids
                    ],
                }
            ),
        }
    return cases


def _candidate(
    source: Mapping[str, Any],
    *,
    slots: list[str],
    fusion_rank: int,
    source_rank: int,
) -> CandidateEnvelope:
    evidence_id = str(source["evidence_id"])
    return CandidateEnvelope(
        candidate_id=evidence_id,
        source_evidence_id=evidence_id,
        source_turn_ref=str(source["source_ref"]),
        subject_id=str(source.get("subject_id") or source["session_id"]),
        session_id=str(source["session_id"]),
        turn_id=str(source.get("turn_id") or source["source_ref"]),
        identity_source="STRUCTURED_TURN_METADATA",
        speaker=cast(Any, source["speaker"]),
        speaker_source="STRUCTURED_TURN_METADATA",
        source_observed_at=cast(Any, source["observed_at"]),
        matched_probes=[f"dg27:{slot}:FTS_RAW" for slot in slots],
        matched_slots=slots,
        channel_ranks={"FTS_RAW": source_rank},
        channel_scores={"FTS_RAW": float(source.get("raw_score", 0.0))},
        probe_ranks={f"dg27:{slot}:FTS_RAW": source_rank for slot in slots},
        probe_scores={
            f"dg27:{slot}:FTS_RAW": float(source.get("raw_score", 0.0))
            for slot in slots
        },
        fusion_rank=fusion_rank,
        fusion_score=1.0 / (60 + source_rank),
        matched_fields=["lexical_text"],
        body_ref=str(source["source_ref"]),
        body_hydrated=True,
    )


def _candidate_manifest(cases: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_id, case in sorted(cases.items()):
        selected = _mapping(case.get("selected_by_requirement"), "selected requirements")
        for requirement_id, sources in sorted(selected.items()):
            rows.append(
                {
                    "case_id": case_id,
                    "requirement_id": requirement_id,
                    "candidates": [
                        {
                            "evidence_id": str(item["evidence_id"]),
                            "source_ref": str(item["source_ref"]),
                            "content_hash": str(item["content_hash"]),
                        }
                        for item in cast(Sequence[Mapping[str, Any]], sources)
                    ],
                }
            )
    return rows


def _proofs_by_case(root: Path) -> dict[str, SufficiencyProof]:
    bundle = _object(root / DG25_E1_OUTPUTS)
    arms = _mapping(bundle.get("arm_outputs"), "DG25 arm outputs")
    arm = _mapping(arms.get("R1"), "DG25 R1")
    values: dict[str, dict[str, bool]] = defaultdict(dict)
    for record in _sequence(arm.get("records"), "DG25 R1 records"):
        row = _mapping(record, "DG25 R1 record")
        case_id = str(row["query_id"])
        for requirement in _sequence(row.get("requirements"), "DG25 R1 requirements"):
            item = _mapping(requirement, "DG25 R1 requirement")
            for obligation in _sequence(
                item.get("proof_obligations"), "DG25 proof obligations"
            ):
                proof = _mapping(obligation, "DG25 proof obligation")
                suffix = str(proof["obligation_id"]).rsplit(":", 1)[-1]
                values[case_id][suffix] = proof.get("status") == "SATISFIED"
    return {
        case_id: SufficiencyProof(
            bounded_scan_completed=proofs.get("BOUNDED_RANGE_SCAN", False),
            source_partition_closed=proofs.get("SOURCE_PARTITION_CLOSURE", False),
            projection_watermark=(
                1 if proofs.get("PROJECTION_CLOSURE", False) else None
            ),
            deduplication_completed=proofs.get("DEDUP_COMPLETENESS", False),
            version_chain_complete=proofs.get("VERSION_CHAIN_COMPLETE", False),
        )
        for case_id, proofs in values.items()
    }


def _single_best(
    interpretation_set: SemanticInterpretationSetV02,
) -> SemanticInterpretationSetV02:
    if not interpretation_set.hypotheses:
        return interpretation_set
    best = max(
        enumerate(interpretation_set.hypotheses),
        key=lambda pair: (
            pair[1].confidence_feature if pair[1].confidence_feature is not None else -1.0,
            -pair[0],
        ),
    )[1]
    return interpretation_set.model_copy(update={"hypotheses": [best]})


def _usage(
    case_id: str,
    requirement_id: str,
    execution: GroundedInterpretationExecution,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "requirement_id": requirement_id,
        "model_id": execution.model_id,
        "response_id": execution.response_id,
        "prompt_tokens": execution.prompt_tokens,
        "completion_tokens": execution.completion_tokens,
        "latency_ms": round(execution.latency_ms, 3),
        "automatic_retries": execution.automatic_retries,
    }


def _gold_groups(gold: Mapping[str, Any]) -> dict[tuple[str, str, str], set[str]]:
    if gold.get("schema_version") != "gold-equivalence-registry-v0.1":
        raise DG27EffectError("DG27_GOLD_REGISTRY_SCHEMA_DRIFT")
    groups: dict[tuple[str, str, str], set[str]] = {}
    for query in _sequence(gold.get("queries"), "gold queries"):
        query_row = _mapping(query, "gold query")
        case_id = str(query_row["query_id"])
        for requirement in _sequence(query_row.get("requirements"), "gold requirements"):
            requirement_row = _mapping(requirement, "gold requirement")
            requirement_id = str(requirement_row["requirement_id"])
            for role in _sequence(requirement_row.get("evidence_roles"), "gold roles"):
                role_row = _mapping(role, "gold role")
                for group in _sequence(
                    role_row.get("equivalence_groups"), "gold equivalence groups"
                ):
                    group_row = _mapping(group, "gold equivalence group")
                    refs = {str(group_row["source_turn_ref"])}
                    refs.update(
                        str(value).removeprefix("source-ref:")
                        for value in _sequence(
                            group_row.get("acceptable_evidence_ids"),
                            "acceptable evidence ids",
                        )
                    )
                    groups[
                        (case_id, requirement_id, str(group_row["equivalence_group_id"]))
                    ] = refs
    if len(groups) != 23:
        raise DG27EffectError("DG27_GOLD_GROUP_DENOMINATOR_DRIFT")
    return groups


def _baseline_groups(
    unscored: Mapping[str, Any],
    groups: Mapping[tuple[str, str, str], set[str]],
) -> set[str]:
    accepted = {
        (
            str(source["case_id"]),
            str(source["requirement_id"]),
            _compact_source_ref(str(source["source_ref"])),
        )
        for raw_source in _sequence(
            unscored.get("D0_baseline_accepted_sources"), "D0 baseline accepted"
        )
        for source in [_mapping(raw_source, "D0 baseline accepted source")]
    }
    return {
        group_id
        for (case_id, requirement_id, group_id), refs in groups.items()
        if any(
            item_case == case_id and item_requirement == requirement_id and ref in refs
            for item_case, item_requirement, ref in accepted
        )
    }


def _compact_source_ref(value: str) -> str:
    match = _LONG_SOURCE_REF.match(value)
    if match is None:
        return value.split("?", 1)[0]
    case_id, session_ordinal, session_id, turn_ordinal = match.groups()
    return (
        f"{unquote(case_id)}:s{session_ordinal}:{unquote(session_id)}:t{turn_ordinal}"
    )


def _verify_identity(root: Path, identity: Mapping[str, Any]) -> None:
    path = root / str(identity["path"])
    if (
        not path.is_file()
        or path.stat().st_size != int(identity["size"])
        or _sha256_file(path) != identity["sha256"]
    ):
        raise DG27EffectError(f"DG27_BOUND_IDENTITY_DRIFT:{identity['path']}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG27EffectError(f"JSON object required: {path}")
    return value


def _mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DG27EffectError(f"mapping required: {source}")
    return value


def _sequence(value: object, source: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DG27EffectError(f"sequence required: {source}")
    return value


__all__ = [
    "DG27EffectError",
    "execute_effect",
    "frozen_candidate_manifest",
    "historical_baseline_accepted_sources",
    "historical_wrong_complete_occurrences",
    "load_run_lock",
    "score_effect",
]
