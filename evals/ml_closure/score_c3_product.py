"""Score the C3 product-path lifecycle output after label-blind acquisition."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from milai.domain.requirement_state import canonical_sha256


class C3ProductScoreError(RuntimeError):
    """A C3 input identity, denominator, or product invariant drifted."""


def score(
    *,
    raw_path: Path,
    labels_path: Path,
    product_path: Path,
    baseline_path: Path | None,
    off_diagnostic_path: Path | None = None,
) -> dict[str, Any]:
    raw = _object(raw_path)
    labels = _object(labels_path)
    product = _object(product_path)
    _verify_product_digest(product)
    raw_sha256 = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    labels_sha256 = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    if product.get("raw_sha256") != raw_sha256:
        raise C3ProductScoreError("C3_PRODUCT_RAW_IDENTITY_MISMATCH")

    conversations = cast(list[dict[str, Any]], raw.get("conversations"))
    label_conversations = cast(list[dict[str, Any]], labels.get("conversations"))
    rows = cast(list[dict[str, Any]], product.get("rows"))
    raw_by_id = {str(item["conversation_id"]): item for item in conversations}
    labels_by_query = {
        str(query["query_id"]): query
        for conversation in label_conversations
        for query in cast(list[dict[str, Any]], conversation["queries"])
    }
    rows_by_query = {str(item["query_id"]): item for item in rows}
    expected_count = len(conversations)
    if not (
        expected_count > 0
        and len(raw_by_id) == expected_count
        and len(labels_by_query) == expected_count
        and len(rows_by_query) == expected_count
        and len(rows) == expected_count
    ):
        raise C3ProductScoreError("C3_PRODUCT_DENOMINATOR_OR_IDENTITY_DRIFT")
    if set(rows_by_query) != set(labels_by_query):
        raise C3ProductScoreError("C3_PRODUCT_QUERY_IDENTITY_MISMATCH")

    true_positive = false_positive = false_negative = 0
    proof_covered_count = expected_complete_count = 0
    operator_correct_count = wrong_complete = 0
    authority_scope_violation = revoked_leak = derived_revocation_leak = 0
    reader_grounding_violation = stale_projection_read = 0
    exact_queries: set[str] = set()
    per_query: list[dict[str, Any]] = []

    for query_id in sorted(rows_by_query):
        row = rows_by_query[query_id]
        label = labels_by_query[query_id]
        conversation_id = str(row["conversation_id"])
        conversation = raw_by_id.get(conversation_id)
        if conversation is None or not query_id.startswith(f"{conversation_id}:"):
            raise C3ProductScoreError("C3_PRODUCT_QUERY_CONVERSATION_MISMATCH")
        turns = cast(list[dict[str, Any]], conversation["turns"])
        admissible, revoked = _source_sets(conversation, turns)
        accepted_list = cast(list[str], row.get("accepted_evidence_ids", []))
        if len(accepted_list) != len(set(accepted_list)):
            raise C3ProductScoreError("C3_PRODUCT_DUPLICATE_ACCEPTED_EVIDENCE")
        accepted = set(accepted_list)
        expected = set(cast(list[str], label["expected_bindings"]))
        obligations = set(cast(list[str], label["proof_obligations"]))
        valid = accepted.intersection(expected, admissible)
        extra = accepted - expected
        invalid = accepted - admissible
        missing = expected - valid
        proof_covered = obligations <= valid
        expected_complete = bool(label["expected_complete"])
        sufficiency = cast(dict[str, Any], row.get("sufficiency_decision") or {})
        declared_complete = (
            row.get("status") == "HIT"
            and sufficiency.get("status") == "COMPLETE"
            and not cast(list[object], sufficiency.get("missing_slots") or [])
        )
        operator_correct = _operator_correct(row, label)
        wrong = declared_complete and (
            not expected_complete
            or not proof_covered
            or bool(extra)
            or bool(invalid)
            or not operator_correct
        )
        exact = accepted == expected and not invalid
        if exact:
            exact_queries.add(query_id)
        reader_violation = _reader_grounding_violation(
            row,
            accepted=accepted,
            turns=turns,
            expected_complete=expected_complete,
        )
        trace = cast(dict[str, Any], row.get("formation_projection") or {})
        selected = int(trace.get("selected_source_count", 0))
        hydrated = int(trace.get("hydrated_source_count", 0))
        stale = bool(
            trace.get("applied") is True
            and (
                selected == 0
                or hydrated != selected
                or trace.get("access_snapshot_digest") is None
                or trace.get("source_watermark_digest") is None
                or trace.get("governance_rejected_source_count") != 0
            )
        )

        true_positive += len(valid)
        false_positive += len(extra | invalid)
        false_negative += len(missing)
        expected_complete_count += int(expected_complete)
        proof_covered_count += int(expected_complete and proof_covered)
        operator_correct_count += int(operator_correct)
        wrong_complete += int(wrong)
        authority_scope_violation += len(invalid)
        revoked_leak += len(accepted & revoked)
        derived_revocation_leak += int(
            bool(accepted & revoked) and row.get("derived_result") is not None
        )
        reader_grounding_violation += int(reader_violation)
        stale_projection_read += int(stale)
        per_query.append(
            {
                "query_id": query_id,
                "conversation_id": conversation_id,
                "stratum": row["stratum"],
                "valid_binding_count": len(valid),
                "missing_binding_count": len(missing),
                "extra_binding_count": len(extra | invalid),
                "proof_covered": proof_covered,
                "expected_complete": expected_complete,
                "declared_complete": declared_complete,
                "operator_correct": operator_correct,
                "reader_grounding_violation": reader_violation,
                "stale_projection_read": stale,
                "exact_binding": exact,
            }
        )

    baseline_exact = _baseline_exact_queries(
        baseline_path,
        raw_by_id=raw_by_id,
        labels_by_query=labels_by_query,
    )
    correct_case_regression = len(baseline_exact - exact_queries)
    product_checks = cast(dict[str, Any], product.get("checks") or {})
    off_diagnostic = _off_baseline_diagnostic(
        off_diagnostic_path,
        baseline_path=baseline_path,
        raw_sha256=raw_sha256,
    )
    frozen_off_identity = (
        product_checks.get("flag_off_matches_c0_frozen_baseline") in {True, None}
        or (
            off_diagnostic is not None
            and off_diagnostic["rows_equal"] is True
        )
    )
    negative_rows = [
        row
        for row in rows
        if not bool(labels_by_query[str(row["query_id"])]["expected_complete"])
    ]
    raw_fallback_success = sum(
        row.get("status") == "ABSENT"
        and cast(dict[str, Any], row.get("formation_projection") or {}).get(
            "fallback_taken"
        )
        is True
        for row in negative_rows
    )
    metrics: dict[str, Any] = {
        "query_count": expected_count,
        "expected_binding_count": true_positive + false_negative,
        "accepted_binding_count": true_positive + false_positive,
        "valid_binding_count": true_positive,
        "false_positive_binding_count": false_positive,
        "missing_binding_count": false_negative,
        "ValidBindingRecall": _ratio(true_positive, true_positive + false_negative),
        "AcceptedBindingPrecision": _ratio(
            true_positive,
            true_positive + false_positive,
        ),
        "RequiredEvidenceCoverage": _ratio(
            proof_covered_count,
            expected_complete_count,
        ),
        "OperatorReadyRate": _ratio(operator_correct_count, expected_count),
        "OperatorResultAccuracy": _ratio(operator_correct_count, expected_count),
        "FinalAnswerCorrectness": _ratio(operator_correct_count, expected_count),
        "CorrectCaseRegression": correct_case_regression,
        "WrongCOMPLETE": wrong_complete,
        "ReaderGroundingViolation": reader_grounding_violation,
        "DerivedArtifactRevocationLeak": derived_revocation_leak,
        "RevokedEvidenceRetrievalLeak": revoked_leak,
        "StaleProjectionRead": stale_projection_read,
        "AuthorityScopeViolation": authority_scope_violation,
        "RawFallbackSuccessRate": _ratio(raw_fallback_success, len(negative_rows)),
        "FlagOffIdentity": 1.0
        if product_checks.get("flag_off_behavior_identity") is True
        and frozen_off_identity
        else 0.0,
        "ImplementationRollback": (
            "PASS"
            if product_checks.get("rollback_to_off_identity") is True
            and product_checks.get("restart_empty_sidecar_raw_fallback") is True
            else "FAIL"
        ),
    }
    gates = {
        "accepted_binding_precision_one": metrics["AcceptedBindingPrecision"] == 1.0,
        "wrong_complete_zero": metrics["WrongCOMPLETE"] == 0,
        "correct_case_regression_zero": metrics["CorrectCaseRegression"] == 0,
        "operator_result_accuracy_one": metrics["OperatorResultAccuracy"] == 1.0,
        "reader_grounding_violation_zero": metrics["ReaderGroundingViolation"] == 0,
        "derived_artifact_revocation_leak_zero": (
            metrics["DerivedArtifactRevocationLeak"] == 0
        ),
        "revoked_evidence_retrieval_leak_zero": (
            metrics["RevokedEvidenceRetrievalLeak"] == 0
        ),
        "stale_projection_read_zero": metrics["StaleProjectionRead"] == 0,
        "raw_fallback_success_one": metrics["RawFallbackSuccessRate"] == 1.0,
        "flag_off_identity_one": metrics["FlagOffIdentity"] == 1.0,
        "implementation_rollback_pass": metrics["ImplementationRollback"] == "PASS",
        "raw_baseline_preserved": product_checks.get("raw_baseline_preserved_all") is True,
        "full_semantics_recomputed": (
            product_checks.get("full_semantics_recomputed_when_selected") is True
        ),
        "canonical_mutation_zero": product_checks.get("canonical_mutation_zero") is True,
        "model_calls_zero": product_checks.get("model_calls_zero") is True,
        "governance_rejected_zero": product_checks.get("governance_rejected_zero") is True,
        "canary_replay_reproducible": (
            product_checks.get("canary_replay_semantically_identical") is True
        ),
    }
    result: dict[str, Any] = {
        "schema": "milai.memory-lifecycle.c3-product-score.v0.1",
        "input_identity": {
            "raw_sha256": raw_sha256,
            "labels_sha256": labels_sha256,
            "product_output_digest": product["output_digest"],
            "baseline_result_digest": (
                _object(baseline_path).get("result_digest")
                if baseline_path is not None
                else None
            ),
            "off_baseline_diagnostic": off_diagnostic,
        },
        "candidate": "F",
        "representation": "FORMED_PLUS_RAW_CANONICAL",
        "recollection": "SIMPLE",
        "metrics": metrics,
        "gates": gates,
        "per_query": per_query,
        "labels_visible_to_acquisition": product.get("labels_visible_to_acquisition"),
        "formal_holdout_used": False,
        "protocol_repairs": (
            ["C3_ACCEPTED_EVIDENCE_ORDER_NORMALIZATION"]
            if product_checks.get("flag_off_matches_c0_frozen_baseline") is False
            and off_diagnostic is not None
            and off_diagnostic["rows_equal"] is True
            else []
        ),
        "status": (
            "PASS_C3_PRODUCT_INTEGRATION"
            if all(gates.values())
            else "NEEDS_REPAIR_C3_PRODUCT_INTEGRATION"
        ),
    }
    result["result_digest"] = canonical_sha256(result)
    return result


def _source_sets(
    conversation: Mapping[str, Any],
    turns: Sequence[Mapping[str, Any]],
) -> tuple[set[str], set[str]]:
    admissible: set[str] = set()
    revoked: set[str] = set()
    for turn in turns:
        evidence_id = str(turn["evidence_id"])
        permission = turn.get("permission_snapshot")
        eligible = (
            turn.get("speaker") == "user"
            and turn.get("retention_state") == "READABLE"
            and turn.get("revoked_at") is None
            and turn.get("access_decision") == "ALLOWED"
            and isinstance(permission, Mapping)
            and permission.get("readable") is True
            and turn.get("scope_id") == conversation.get("scope_id")
        )
        if eligible:
            admissible.add(evidence_id)
        if turn.get("revoked_at") is not None or turn.get("retention_state") != "READABLE":
            revoked.add(evidence_id)
    return admissible, revoked


def _operator_correct(row: Mapping[str, Any], label: Mapping[str, Any]) -> bool:
    expected_complete = bool(label["expected_complete"])
    expected_operator = str(label["expected_operator"])
    result = row.get("derived_result")
    if not expected_complete:
        return (
            expected_operator == "ABSTAIN"
            and row.get("status") == "ABSENT"
            and result is None
        )
    if not isinstance(result, Mapping) or result.get("status") != "OK":
        return False
    actual_operator = result.get("operator")
    operator_match = {
        "LOOKUP_CURRENT": "LATEST_VALID_STATE",
        "LOOKUP_CURRENT_WITH_HISTORY": "LATEST_VALID_STATE",
        "COMPARE_EVENT_IDENTITY": "COMPARE_EVENT_IDENTITY",
        "TEMPORAL_ORDER": "TEMPORAL_BEFORE_AFTER",
        "COMPOSE_STATE": "COMPOSE_STATE",
    }.get(expected_operator)
    if actual_operator != operator_match:
        return False
    return _normalized_operator_state(result, expected_operator) == label.get(
        "expected_current_state"
    )


def _normalized_operator_state(
    result: Mapping[str, Any],
    expected_operator: str,
) -> object:
    value = result.get("value")
    if not isinstance(value, Mapping):
        return None
    if expected_operator == "COMPARE_EVENT_IDENTITY":
        return {"same_event": value.get("same_event")}
    if expected_operator == "TEMPORAL_ORDER":
        events = value.get("events")
        return {
            "visit_date": events.get("EVENT_2") if isinstance(events, Mapping) else None
        }
    if expected_operator == "COMPOSE_STATE":
        return dict(value)
    if value.get("current_status") == "NO_CURRENT_STATE_ON_RECORD":
        return "no current allergy on record"
    predicate = value.get("state_predicate")
    state_value = value.get("state_value")
    scalar: object = state_value
    if isinstance(state_value, Mapping) and len(state_value) == 1:
        scalar = next(iter(state_value.values()))
    if expected_operator == "LOOKUP_CURRENT":
        return {str(predicate): scalar}
    return scalar


def _reader_grounding_violation(
    row: Mapping[str, Any],
    *,
    accepted: set[str],
    turns: Sequence[Mapping[str, Any]],
    expected_complete: bool,
) -> bool:
    context = row.get("memory_context")
    if not isinstance(context, Mapping):
        return expected_complete
    selected = set(
        str(value) for value in cast(Sequence[object], context.get("selected_evidence_ids") or [])
    )
    if selected != accepted:
        return True
    if context.get("required_evidence_packing_loss_count") not in {0, None}:
        return True
    if context.get("hidden_model_calls") not in {0, None}:
        return True
    if context.get("canonical_mutation") is True:
        return True
    text = context.get("text")
    if not isinstance(text, str):
        return expected_complete
    forbidden = [
        str(turn["content"])
        for turn in turns
        if str(turn["evidence_id"]) not in accepted and turn.get("content")
    ]
    return any(value in text for value in forbidden)


def _baseline_exact_queries(
    path: Path | None,
    *,
    raw_by_id: Mapping[str, Mapping[str, Any]],
    labels_by_query: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    if path is None:
        return set()
    baseline = _object(path)
    rows = cast(list[dict[str, Any]], baseline.get("rows"))
    exact: set[str] = set()
    for row in rows:
        query_id = str(row["query_id"])
        label = labels_by_query.get(query_id)
        conversation = raw_by_id.get(str(row["conversation_id"]))
        if label is None or conversation is None:
            raise C3ProductScoreError("C3_BASELINE_QUERY_IDENTITY_MISMATCH")
        admissible, _revoked = _source_sets(
            conversation,
            cast(list[dict[str, Any]], conversation["turns"]),
        )
        accepted = set(cast(list[str], row.get("accepted_evidence_ids", [])))
        if accepted == set(cast(list[str], label["expected_bindings"])) and accepted <= admissible:
            exact.add(query_id)
    return exact


def _verify_product_digest(value: Mapping[str, Any]) -> None:
    if "result_digest" in value:
        material = dict(value)
        observed = material.pop("result_digest")
        if observed != canonical_sha256(material):
            raise C3ProductScoreError("C3_PRODUCT_RESULT_DIGEST_INVALID")
    material = dict(value)
    observed_output = material.pop("output_digest", None)
    for key in (
        "process_exit_code",
        "fresh_ephemeral_database",
        "database_name_sha256",
        "cleanup",
        "credentials_recorded",
        "stderr_empty",
        "status",
        "result_digest",
    ):
        material.pop(key, None)
    if observed_output != canonical_sha256(material):
        raise C3ProductScoreError("C3_PRODUCT_OUTPUT_DIGEST_INVALID")


def _off_baseline_diagnostic(
    path: Path | None,
    *,
    baseline_path: Path | None,
    raw_sha256: str,
) -> dict[str, Any] | None:
    if path is None:
        return None
    if baseline_path is None:
        raise C3ProductScoreError("C3_OFF_DIAGNOSTIC_BASELINE_REQUIRED")
    diagnostic = _object(path)
    baseline = _object(baseline_path)
    _verify_candidate_r_digest(diagnostic)
    _verify_candidate_r_digest(baseline)
    checks = (
        diagnostic.get("raw_sha256") == raw_sha256
        and baseline.get("raw_sha256") == raw_sha256
        and diagnostic.get("labels_visible_to_acquisition") is False
        and diagnostic.get("formal_holdout_used") is False
        and diagnostic.get("baseline_replay_semantically_identical") is True
        and diagnostic.get("status") == "PASS_C0_CANDIDATE_R_REPRODUCTION"
        and cast(dict[str, Any], diagnostic.get("cleanup") or {}).get("status")
        == "PASS"
    )
    if not checks:
        raise C3ProductScoreError("C3_OFF_DIAGNOSTIC_CONTRACT_INVALID")
    diagnostic_rows = diagnostic.get("rows")
    baseline_rows = baseline.get("rows")
    if not isinstance(diagnostic_rows, list) or not isinstance(baseline_rows, list):
        raise C3ProductScoreError("C3_OFF_DIAGNOSTIC_ROWS_INVALID")
    rows_equal = diagnostic_rows == baseline_rows
    return {
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "result_digest": diagnostic.get("result_digest"),
        "baseline_result_digest": baseline.get("result_digest"),
        "row_count": len(diagnostic_rows),
        "rows_digest": canonical_sha256(diagnostic_rows),
        "rows_equal": rows_equal,
        "fresh_ephemeral_database": diagnostic.get("fresh_ephemeral_database"),
        "cleanup_status": cast(dict[str, Any], diagnostic["cleanup"]).get("status"),
    }


def _verify_candidate_r_digest(value: Mapping[str, Any]) -> None:
    material = dict(value)
    observed_result = material.pop("result_digest", None)
    if observed_result != canonical_sha256(material):
        raise C3ProductScoreError("C3_OFF_DIAGNOSTIC_RESULT_DIGEST_INVALID")
    observed_output = material.pop("output_digest", None)
    for key in (
        "process_exit_code",
        "fresh_ephemeral_database",
        "database_name_sha256",
        "cleanup",
        "credentials_recorded",
        "stderr_empty",
        "status",
    ):
        material.pop(key, None)
    if observed_output != canonical_sha256(material):
        raise C3ProductScoreError("C3_OFF_DIAGNOSTIC_OUTPUT_DIGEST_INVALID")


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise C3ProductScoreError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--off-diagnostic", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = score(
        raw_path=arguments.raw.resolve(),
        labels_path=arguments.labels.resolve(),
        product_path=arguments.product.resolve(),
        baseline_path=(
            arguments.baseline.resolve() if arguments.baseline is not None else None
        ),
        off_diagnostic_path=(
            arguments.off_diagnostic.resolve()
            if arguments.off_diagnostic is not None
            else None
        ),
    )
    _write_exclusive(arguments.output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS_C3_PRODUCT_INTEGRATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
