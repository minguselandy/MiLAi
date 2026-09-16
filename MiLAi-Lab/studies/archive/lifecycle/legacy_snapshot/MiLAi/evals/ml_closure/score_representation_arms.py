"""Score the frozen R/F/E outputs and select the minimal lifecycle candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

from milai.domain.requirement_state import canonical_sha256

BOOTSTRAP_SEED = 20260830
BOOTSTRAP_SAMPLES = 10_000


class RepresentationScoreError(RuntimeError):
    """A frozen identity, denominator, or matched-arm contract drifted."""


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RepresentationScoreError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _verify_digest(value: dict[str, Any], field: str) -> None:
    material = dict(value)
    observed = material.pop(field, None)
    if observed != canonical_sha256(material):
        raise RepresentationScoreError(f"DIGEST_INVALID:{field}")


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _score_arm(
    rows: list[dict[str, Any]],
    labels_by_query: dict[str, dict[str, Any]],
    raw_by_conversation: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    true_positive = false_positive = false_negative = 0
    accepted_total = expected_total = 0
    required_covered = expected_complete_count = operator_ready = 0
    temporal_count = temporal_ready = 0
    wrong_complete = authority_scope_violation = exact_cases = 0
    reported_complete_correct = abstention_correct = 0
    expected_abstentions = 0
    per_query: list[dict[str, Any]] = []
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        query_id = str(row["query_id"])
        conversation_id = str(row["conversation_id"])
        label = labels_by_query.get(query_id)
        conversation = raw_by_conversation.get(conversation_id)
        if label is None or conversation is None:
            raise RepresentationScoreError("ARM_QUERY_IDENTITY_MISMATCH")
        if not query_id.startswith(f"{conversation_id}:"):
            raise RepresentationScoreError("ARM_QUERY_CONVERSATION_MISMATCH")

        turns = cast(list[dict[str, Any]], conversation["turns"])
        admissible = {
            str(turn["evidence_id"])
            for turn in turns
            if turn.get("speaker") == "user"
            and turn.get("retention_state") == "READABLE"
            and turn.get("revoked_at") is None
            and turn.get("access_decision") == "ALLOWED"
            and cast(dict[str, Any], turn.get("permission_snapshot", {})).get(
                "readable"
            )
            is True
            and turn.get("scope_id") == conversation.get("scope_id")
        }
        accepted_list = cast(list[str], row["accepted_evidence_ids"])
        if len(accepted_list) != len(set(accepted_list)):
            raise RepresentationScoreError("DUPLICATE_ACCEPTED_BINDING")
        accepted = set(accepted_list)
        expected = set(cast(list[str], label["expected_bindings"]))
        obligations = set(cast(list[str], label["proof_obligations"]))
        invalid_authority = accepted - admissible
        valid = accepted & expected & admissible
        extra = accepted - expected
        missing = expected - valid
        proof_covered = obligations <= valid
        expected_complete = bool(label["expected_complete"])
        ready = proof_covered and not invalid_authority if expected_complete else not accepted
        declared_complete = bool(row["complete"])
        is_wrong_complete = declared_complete and (
            not expected_complete or not proof_covered or bool(extra | invalid_authority)
        )
        exact = accepted == expected and not invalid_authority

        true_positive += len(valid)
        false_positive += len(extra | invalid_authority)
        false_negative += len(missing)
        accepted_total += len(accepted)
        expected_total += len(expected)
        authority_scope_violation += len(invalid_authority)
        wrong_complete += int(is_wrong_complete)
        exact_cases += int(exact)
        reported_complete_correct += int(declared_complete == expected_complete)
        if expected_complete:
            expected_complete_count += 1
            required_covered += int(proof_covered)
            operator_ready += int(ready)
        else:
            expected_abstentions += 1
            abstention_correct += int(ready and not declared_complete)
        if label["expected_operator"] == "TEMPORAL_ORDER":
            temporal_count += 1
            temporal_ready += int(ready)

        query_metric = {
            "query_id": query_id,
            "conversation_id": conversation_id,
            "stratum": row["stratum"],
            "valid_binding_recall": _ratio(len(valid), len(expected)),
            "accepted_binding_precision": _ratio(len(valid), len(accepted)),
            "valid_binding_count": len(valid),
            "missing_binding_count": len(missing),
            "extra_binding_count": len(extra | invalid_authority),
            "proof_covered": proof_covered,
            "operator_ready": ready,
            "expected_complete": expected_complete,
            "declared_complete": declared_complete,
            "exact": exact,
        }
        per_query.append(query_metric)
        strata[str(row["stratum"])].append(query_metric)

    if len(rows) != 60 or len({row["query_id"] for row in rows}) != 60:
        raise RepresentationScoreError("ARM_DENOMINATOR_NOT_60")
    stratum_metrics = {
        name: {
            "queries": len(items),
            "ValidBindingRecall": sum(
                float(item["valid_binding_recall"]) for item in items
            )
            / len(items),
            "AcceptedBindingPrecision": sum(
                float(item["accepted_binding_precision"]) for item in items
            )
            / len(items),
            "OperatorReadyRate": sum(bool(item["operator_ready"]) for item in items)
            / len(items),
        }
        for name, items in sorted(strata.items())
    }
    return {
        "query_count": len(rows),
        "expected_binding_count": expected_total,
        "accepted_binding_count": accepted_total,
        "valid_binding_count": true_positive,
        "false_positive_binding_count": false_positive,
        "missing_binding_count": false_negative,
        "ValidBindingRecall": _ratio(true_positive, true_positive + false_negative),
        "AcceptedBindingPrecision": _ratio(
            true_positive, true_positive + false_positive
        ),
        "RequiredEvidenceCoverage": _ratio(
            required_covered, expected_complete_count
        ),
        "OperatorReadyRate": _ratio(operator_ready, expected_complete_count),
        "TemporalCompletenessRate": _ratio(temporal_ready, temporal_count),
        "AbstentionAccuracy": _ratio(abstention_correct, expected_abstentions),
        "ExactBindingCaseRate": _ratio(exact_cases, len(rows)),
        "ReportedCompleteAccuracy": _ratio(reported_complete_correct, len(rows)),
        "WrongCOMPLETE": wrong_complete,
        "AuthorityScopeViolation": authority_scope_violation,
        "strata": stratum_metrics,
        "per_query": per_query,
    }


def _paired_bootstrap(
    baseline: dict[str, Any], treatment: dict[str, Any]
) -> dict[str, float | int]:
    left = {
        str(row["conversation_id"]): float(row["valid_binding_recall"])
        for row in cast(list[dict[str, Any]], baseline["per_query"])
    }
    right = {
        str(row["conversation_id"]): float(row["valid_binding_recall"])
        for row in cast(list[dict[str, Any]], treatment["per_query"])
    }
    if left.keys() != right.keys() or len(left) != 60:
        raise RepresentationScoreError("PAIRED_CONVERSATION_MISMATCH")
    deltas = [right[key] - left[key] for key in sorted(left)]
    generator = random.Random(BOOTSTRAP_SEED)
    samples = sorted(
        sum(deltas[generator.randrange(len(deltas))] for _ in deltas) / len(deltas)
        for _ in range(BOOTSTRAP_SAMPLES)
    )
    return {
        "paired_conversations": len(deltas),
        "samples": BOOTSTRAP_SAMPLES,
        "seed": BOOTSTRAP_SEED,
        "mean_delta": sum(deltas) / len(deltas),
        "ci_lower": samples[int(BOOTSTRAP_SAMPLES * 0.025)],
        "ci_upper": samples[int(BOOTSTRAP_SAMPLES * 0.975)],
    }


def _opportunity_audit(
    raw_by_conversation: dict[str, dict[str, Any]],
    labels_by_query: dict[str, dict[str, Any]],
    f_metrics: dict[str, Any],
) -> dict[str, Any]:
    f_by_query = {
        str(row["query_id"]): row
        for row in cast(list[dict[str, Any]], f_metrics["per_query"])
    }
    cross_episode = raw_members_exist = simple_formed_discharged = 0
    residual_ids: list[str] = []
    for query_id, label in sorted(labels_by_query.items()):
        conversation_id = str(f_by_query[query_id]["conversation_id"])
        conversation = raw_by_conversation[conversation_id]
        turns = {
            str(turn["evidence_id"]): turn
            for turn in cast(list[dict[str, Any]], conversation["turns"])
        }
        obligations = cast(list[str], label["proof_obligations"])
        sessions = {
            str(turns[evidence_id]["session_id"])
            for evidence_id in obligations
            if evidence_id in turns
        }
        if len(sessions) < 2:
            continue
        cross_episode += 1
        members_exist = all(evidence_id in turns for evidence_id in obligations)
        raw_members_exist += int(members_exist)
        discharged = bool(f_by_query[query_id]["proof_covered"])
        simple_formed_discharged += int(discharged)
        if members_exist and not discharged:
            residual_ids.append(query_id)
    return {
        "cross_episode_requirement_count": cross_episode,
        "raw_member_evidence_exists_count": raw_members_exist,
        "simple_formed_discharged_count": simple_formed_discharged,
        "residual_oracle_opportunity_count": len(residual_ids),
        "residual_query_ids": residual_ids,
        "MF05": "NOT_NEEDED_BY_EVIDENCE"
        if not residual_ids
        else "OPPORTUNITY_PRESENT",
        "consolidation_code_required": bool(residual_ids),
    }


def _cost(
    raw: dict[str, Any],
    formation_output: dict[str, Any],
    candidate_r: dict[str, Any],
    net_additional_bindings: int,
) -> dict[str, Any]:
    conversations = cast(list[dict[str, Any]], raw["conversations"])
    formation_rows = cast(list[dict[str, Any]], formation_output["rows"])
    evidence_count = sum(
        len(cast(list[dict[str, Any]], conversation["turns"]))
        for conversation in conversations
    )
    source_bytes = sum(
        len(str(turn["content"]).encode("utf-8"))
        for conversation in conversations
        for turn in cast(list[dict[str, Any]], conversation["turns"])
    )
    sidecar_bytes = sum(
        len(
            json.dumps(
                {
                    "formation": row["formation"],
                    "state_changes": row["state_changes"],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        for row in formation_rows
    )
    formation_wall_ms = float(formation_output["cost"]["formation_wall_ms"])
    query_count = 60
    return {
        "write_time": {
            "FormationWallMs": formation_wall_ms,
            "FormationCostPerEvidenceMs": formation_wall_ms / evidence_count,
            "ModelCalls": int(formation_output["cost"]["model_calls"]),
            "CanonicalMutations": int(
                formation_output["cost"]["canonical_mutations"]
            ),
        },
        "read_time": {
            "OfficialAcquisitionCallsPerQuery": 1,
            "HydratedEvidenceCeiling": int(candidate_r["ceilings"]["max_results"]),
            "ModelCallsPerQuery": 0,
            "ReaderCallsPerQuery": 0,
        },
        "storage": {
            "RawContentBytes": source_bytes,
            "FormationSidecarBytes": sidecar_bytes,
            "SidecarToRawContentRatio": sidecar_bytes / source_bytes,
            "RawPlusSidecarAmplification": (source_bytes + sidecar_bytes)
            / source_bytes,
        },
        "amortized_horizon": {
            str(horizon): {
                "FormationMsPerQuery": formation_wall_ms
                / (query_count * horizon),
                "OfficialAcquisitionCallsPerQuery": 1,
            }
            for horizon in (1, 10, 100)
        },
        "IncrementalFormationMsPerAdditionalValidBinding": _ratio(
            round(formation_wall_ms * 1_000_000), net_additional_bindings
        )
        / 1_000_000,
        "baseline_replay_calls_excluded_from_effect_cost": int(
            candidate_r["cost"]["official_query_calls"]
        )
        - query_count,
    }


def score_and_select(
    *,
    raw_path: Path,
    labels_path: Path,
    arms_path: Path,
    formation_score_path: Path,
    candidate_r_path: Path,
    formation_output_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = _object(raw_path)
    labels = _object(labels_path)
    arms = _object(arms_path)
    formation_score = _object(formation_score_path)
    candidate_r = _object(candidate_r_path)
    formation_output = _object(formation_output_path)
    _verify_digest(arms, "output_digest")
    _verify_digest(formation_score, "result_digest")
    _verify_digest(candidate_r, "result_digest")
    _verify_digest(formation_output, "output_digest")

    raw_sha256 = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    labels_sha256 = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    if arms["matched_identity"]["raw_sha256"] != raw_sha256:
        raise RepresentationScoreError("RFE_RAW_IDENTITY_MISMATCH")
    if formation_score["treatment"]["labels_sha256"] != labels_sha256:
        raise RepresentationScoreError("FORMATION_LABEL_IDENTITY_MISMATCH")
    if arms["matched_identity"]["candidate_r_output_digest"] != candidate_r[
        "output_digest"
    ] or arms["matched_identity"]["formation_output_digest"] != formation_output[
        "output_digest"
    ]:
        raise RepresentationScoreError("RFE_UPSTREAM_IDENTITY_MISMATCH")

    raw_by_conversation = {
        str(row["conversation_id"]): row
        for row in cast(list[dict[str, Any]], raw["conversations"])
    }
    labels_by_query = {
        str(query["query_id"]): query
        for conversation in cast(list[dict[str, Any]], labels["conversations"])
        for query in cast(list[dict[str, Any]], conversation["queries"])
    }
    if len(raw_by_conversation) != 60 or len(labels_by_query) != 60:
        raise RepresentationScoreError("SEALED_DENOMINATOR_NOT_60")
    arm_metrics = {
        arm: _score_arm(
            cast(list[dict[str, Any]], arms["arms"][arm]),
            labels_by_query,
            raw_by_conversation,
        )
        for arm in ("R", "F", "E")
    }
    paired = _paired_bootstrap(arm_metrics["R"], arm_metrics["F"])
    f_metrics = arm_metrics["F"]
    r_metrics = arm_metrics["R"]
    e_metrics = arm_metrics["E"]
    net_additional = int(f_metrics["valid_binding_count"]) - int(
        r_metrics["valid_binding_count"]
    )
    r_correct = {
        str(row["query_id"])
        for row in cast(list[dict[str, Any]], r_metrics["per_query"])
        if row["exact"]
    }
    f_correct = {
        str(row["query_id"])
        for row in cast(list[dict[str, Any]], f_metrics["per_query"])
        if row["exact"]
    }
    correct_case_regression = len(r_correct - f_correct)
    matched = cast(dict[str, Any], arms["matched_identity"])
    same_official_actions = (
        matched["official_actions_per_query"]
        == candidate_r["ceilings"]["official_actions_per_query"]
        == 1
    )
    same_hydration = (
        matched["hydration_ceiling"] == candidate_r["ceilings"]["max_results"]
        and max(
            len(cast(list[str], row["accepted_evidence_ids"]))
            for arm in cast(dict[str, list[dict[str, Any]]], arms["arms"]).values()
            for row in arm
        )
        <= int(matched["hydration_ceiling"])
    )
    same_reader_ceiling = (
        candidate_r["ceilings"]["reader_calls"] == 0
        and matched["reader_calls_per_query"] == 0
    )
    direct_formation_pass = (
        formation_score["status"] == "PASS_C1_FORMATION_GENERALIZATION"
        and all(cast(dict[str, bool], formation_score["checks"]).values())
    )
    h1_checks = {
        "direct_formation_gates_pass": direct_formation_pass,
        "delta_f_at_least_005": float(f_metrics["ValidBindingRecall"])
        - float(r_metrics["ValidBindingRecall"])
        >= 0.05,
        "net_additional_valid_obligations_at_least_2": net_additional >= 2,
        "paired_bootstrap_ci_lower_positive": float(paired["ci_lower"]) > 0,
        "accepted_binding_precision_one": f_metrics["AcceptedBindingPrecision"]
        == 1.0,
        "wrong_complete_zero": f_metrics["WrongCOMPLETE"] == 0,
        "correct_case_regression_zero": correct_case_regression == 0,
        "authority_scope_violation_zero": f_metrics["AuthorityScopeViolation"] == 0,
        "same_official_actions": same_official_actions,
        "same_hydration_ceiling": same_hydration,
        "same_reader_ceiling": same_reader_ceiling,
    }
    h1 = "PASS" if all(h1_checks.values()) else "MISS"
    opportunity = _opportunity_audit(
        raw_by_conversation, labels_by_query, f_metrics
    )
    h2 = (
        "NOT_APPLICABLE"
        if opportunity["residual_oracle_opportunity_count"] == 0
        else "REQUIRES_CONDITIONAL_ARMS"
    )
    selected = "F" if h1 == "PASS" and h2 != "PASS" else "R"
    if h1 == "PASS" and h2 == "PASS":
        selected = "A"

    cost = _cost(raw, formation_output, candidate_r, net_additional)
    result: dict[str, Any] = {
        "schema": "milai.memory-lifecycle-representation-selection.v0.1",
        "input_identity": {
            "raw_sha256": raw_sha256,
            "labels_sha256": labels_sha256,
            "rfe_output_digest": arms["output_digest"],
            "formation_score_digest": formation_score["result_digest"],
            "candidate_r_result_digest": candidate_r["result_digest"],
        },
        "arms": arm_metrics,
        "effect": {
            "DeltaF": float(f_metrics["ValidBindingRecall"])
            - float(r_metrics["ValidBindingRecall"]),
            "net_additional_valid_obligations": net_additional,
            "paired_bootstrap": paired,
            "CorrectCaseRegression": correct_case_regression,
        },
        "information_loss_diagnostic": {
            "DeltaEvsF": float(e_metrics["ValidBindingRecall"])
            - float(f_metrics["ValidBindingRecall"]),
            "valid_obligations_lost_by_formed_only": int(
                f_metrics["valid_binding_count"]
            )
            - int(e_metrics["valid_binding_count"]),
            "product_eligible": False,
            "reason": "FORMED_ONLY_FORBIDDEN_RAW_AUTHORITY_AND_FALLBACK_INVARIANT",
        },
        "MLC_H1": {"status": h1, "checks": h1_checks},
        "MF05": opportunity,
        "MLC_H2": {
            "status": h2,
            "conditional_arms_run": False,
            "reason": "NO_UNRESOLVED_FORMED_REQUIREMENT"
            if h2 == "NOT_APPLICABLE"
            else "RESIDUAL_OPPORTUNITY_PRESENT",
        },
        "cost": cost,
        "selection": {
            "arm": selected,
            "candidate": {"R": "CANDIDATE_R", "F": "CANDIDATE_F", "A": "CANDIDATE_A"}[
                selected
            ],
            "rule": "H1_PASS_H2_NOT_APPLICABLE_SELECT_F"
            if selected == "F"
            else "MINIMAL_CANDIDATE_SELECTION_RULE",
        },
        "sealed_retuning_permitted": False,
        "formal_holdout_used": False,
        "status": "PASS_C2_METHOD_SELECTION"
        if selected in {"R", "F", "A"}
        else "MISS_C2_METHOD_SELECTION",
    }
    result["result_digest"] = canonical_sha256(result)
    selected_method: dict[str, Any] = {
        "schema": "milai.memory-lifecycle-selected-method.v0.1",
        "goal_identity": "MILA-ML-CLOSURE@0.2",
        "selected_arm": selected,
        "selected_candidate": result["selection"]["candidate"],
        "representation": "FORMED_PLUS_RAW_CANONICAL"
        if selected == "F"
        else "RAW_CANONICAL",
        "recollection": "SIMPLE",
        "adaptive_recollection": False,
        "consolidation": False,
        "raw_fallback_required": True,
        "product_flag_default": "OFF",
        "architecture_status": "ADR_REQUIRED_FOR_DURABLE_PROJECTION",
        "c2_result_digest": result["result_digest"],
        "sealed_retuning_permitted": False,
        "formal_validation": "NOT_RUN",
    }
    selected_method["selected_method_digest"] = canonical_sha256(selected_method)
    return result, selected_method


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--arms", type=Path, required=True)
    parser.add_argument("--formation-score", type=Path, required=True)
    parser.add_argument("--candidate-r", type=Path, required=True)
    parser.add_argument("--formation-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selected-method", type=Path, required=True)
    args = parser.parse_args()
    result, selected_method = score_and_select(
        raw_path=args.raw.resolve(),
        labels_path=args.labels.resolve(),
        arms_path=args.arms.resolve(),
        formation_score_path=args.formation_score.resolve(),
        candidate_r_path=args.candidate_r.resolve(),
        formation_output_path=args.formation_output.resolve(),
    )
    _write_exclusive(args.output.resolve(), result)
    _write_exclusive(args.selected_method.resolve(), selected_method)
    print(
        json.dumps(
            {
                "status": result["status"],
                "selection": result["selection"],
                "DeltaF": result["effect"]["DeltaF"],
                "paired_bootstrap": result["effect"]["paired_bootstrap"],
                "H1": result["MLC_H1"],
                "H2": result["MLC_H2"],
                "MF05": result["MF05"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "PASS_C2_METHOD_SELECTION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
