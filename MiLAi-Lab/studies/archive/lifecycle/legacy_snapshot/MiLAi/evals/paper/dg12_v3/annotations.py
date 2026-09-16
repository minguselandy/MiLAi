"""Strict validation and deterministic consensus for blinded DG-12 annotations."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


class AnnotationError(RuntimeError):
    pass


ROW_FIELDS = {
    "schema",
    "annotator_id",
    "benchmark",
    "partition",
    "case_id",
    "category",
    "question_sha256",
    "screening_status",
    "ineligibility_codes",
    "operator",
    "unit",
    "required_operands",
    "latest_required_operand_id",
    "latest_state_semantically_distinct",
    "unrelated_numeric_distractor",
    "rationale",
    "confidence",
}
OPERAND_FIELDS = {
    "operand_id",
    "numeric_text",
    "unit",
    "conversion_required",
    "source_pointer",
    "semantic_role",
}
POINTER_FIELDS = {"session_id", "turn_index", "role", "numeric_occurrence_index"}
DISTRACTOR_FIELDS = {"numeric_text", "unit", "source_pointer", "unrelated_reason"}
STATUSES = ("ELIGIBLE", "INELIGIBLE", "AMBIGUOUS")
CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnnotationError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise AnnotationError(f"expected JSON object: {path}")
    return value


def _case_index(lme_input: Path, beam_input: Path) -> list[dict[str, Any]]:
    lme = _read_json(lme_input)
    beam = _read_json(beam_input)
    if (
        lme.get("forbidden_label_fields_present") is not False
        or lme.get("paper_labels_opened") is not False
        or lme.get("label_fields_accessed") is not False
        or beam.get("forbidden_label_fields_present") is not False
        or beam.get("paper_labels_opened") is not False
        or beam.get("answer_label_fields_read_by_preparer") is not False
    ):
        raise AnnotationError("annotation input is not label-free")
    indexed: list[dict[str, Any]] = []
    for case in lme.get("cases", []):
        indexed.append(
            {
                "benchmark": "LongMemEval",
                "partition": lme["partition"],
                "case_id": case["source_id"],
                "category": case["category"],
                "question": case["question"],
                "sessions": {
                    session["session_id"]: session["turns"]
                    for session in case["sessions"]
                },
            }
        )
    histories = {item["history_id"]: item for item in beam.get("histories", [])}
    for case in beam.get("cases", []):
        history = histories.get(case["history_id"])
        if not isinstance(history, dict):
            raise AnnotationError("BEAM case references a missing history")
        indexed.append(
            {
                "benchmark": "BEAM",
                # The public claim stratum is frozen as BEAM-128K while the
                # preparer envelope retains its source label BEAM-128K-FULL.
                "partition": "BEAM-128K",
                "case_id": case["case_id"],
                "category": case["category"],
                "question": case["question"],
                "sessions": {
                    session["session_id"]: session["messages"]
                    for session in history["sessions"]
                },
            }
        )
    if len(indexed) != 500 or len({item["case_id"] for item in indexed}) != 500:
        raise AnnotationError("bound annotation denominator drifted")
    return indexed


def _validate_pointer(pointer: Any, case: Mapping[str, Any]) -> tuple[Any, ...]:
    if not isinstance(pointer, dict) or set(pointer) != POINTER_FIELDS:
        raise AnnotationError("source pointer field set drifted")
    session_id = pointer["session_id"]
    turns = case["sessions"].get(session_id)
    turn_index = pointer["turn_index"]
    occurrence = pointer["numeric_occurrence_index"]
    if (
        not isinstance(session_id, str)
        or not isinstance(turns, list)
        or not isinstance(turn_index, int)
        or isinstance(turn_index, bool)
        or not 0 <= turn_index < len(turns)
        or not isinstance(occurrence, int)
        or isinstance(occurrence, bool)
        or occurrence < 0
        or pointer["role"] != turns[turn_index].get("role")
    ):
        raise AnnotationError("source pointer does not resolve in the bound case")
    return (session_id, turn_index, pointer["role"], occurrence)


def load_annotation_rows(
    path: Path,
    *,
    annotator_id: str,
    lme_input: Path,
    beam_input: Path,
) -> tuple[dict[str, Any], ...]:
    cases = _case_index(lme_input, beam_input)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise AnnotationError(f"cannot read annotation: {path}") from exc
    if len(lines) != len(cases) or any(not line.strip() for line in lines):
        raise AnnotationError("annotation must contain exactly 500 nonblank rows")
    rows: list[dict[str, Any]] = []
    for ordinal, (line, case) in enumerate(zip(lines, cases, strict=True)):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AnnotationError(f"invalid annotation JSON at row {ordinal}") from exc
        if not isinstance(row, dict) or set(row) != ROW_FIELDS:
            raise AnnotationError(f"annotation row field set drifted at {ordinal}")
        if (
            row["schema"] != "milai.dg12.aggregation-annotation-row.v3"
            or row["annotator_id"] != annotator_id
            or row["benchmark"] != case["benchmark"]
            or row["partition"] != case["partition"]
            or row["case_id"] != case["case_id"]
            or row["category"] != case["category"]
            or row["question_sha256"] != _sha256_text(case["question"])
            or row["screening_status"] not in STATUSES
            or row["confidence"] not in CONFIDENCE
            or not isinstance(row["ineligibility_codes"], list)
            or not all(isinstance(item, str) for item in row["ineligibility_codes"])
            or not isinstance(row["required_operands"], list)
            or not isinstance(row["rationale"], str)
            or len(row["rationale"]) > 500
        ):
            raise AnnotationError(f"annotation row identity/type drifted at {ordinal}")
        operands: list[dict[str, Any]] = row["required_operands"]
        pointers: list[tuple[Any, ...]] = []
        operand_ids: list[str] = []
        for operand in operands:
            if not isinstance(operand, dict) or set(operand) != OPERAND_FIELDS:
                raise AnnotationError(f"operand field set drifted at {ordinal}")
            pointer = _validate_pointer(operand["source_pointer"], case)
            if (
                not isinstance(operand["operand_id"], str)
                or not isinstance(operand["numeric_text"], str)
                or not operand["numeric_text"].strip()
                or not isinstance(operand["unit"], str)
                or not isinstance(operand["conversion_required"], bool)
                or not isinstance(operand["semantic_role"], str)
            ):
                raise AnnotationError(f"operand type drifted at {ordinal}")
            pointers.append(pointer)
            operand_ids.append(operand["operand_id"])
        if len(set(pointers)) != len(pointers) or len(set(operand_ids)) != len(
            operand_ids
        ):
            raise AnnotationError(f"duplicate operand at {ordinal}")
        distractor = row["unrelated_numeric_distractor"]
        distractor_pointer = None
        if distractor is not None:
            if not isinstance(distractor, dict) or set(distractor) != DISTRACTOR_FIELDS:
                raise AnnotationError(f"distractor field set drifted at {ordinal}")
            distractor_pointer = _validate_pointer(distractor["source_pointer"], case)
            if distractor_pointer in pointers:
                raise AnnotationError(f"distractor is a required operand at {ordinal}")
        if row["screening_status"] == "ELIGIBLE" and (
            row["operator"] != "SUM_VALUES"
            or not isinstance(row["unit"], str)
            or not row["unit"].strip()
            or len(operands) < 2
            or row["ineligibility_codes"]
            or row["latest_required_operand_id"] not in operand_ids
            or row["latest_state_semantically_distinct"] is not True
            or distractor is None
        ):
            raise AnnotationError(f"eligible row contract failed at {ordinal}")
        rows.append(row)
    return tuple(rows)


def _pointer_key(value: Mapping[str, Any] | None) -> tuple[Any, ...] | None:
    if value is None:
        return None
    return tuple(value[field] for field in sorted(POINTER_FIELDS))


def _eligible_signature(row: Mapping[str, Any]) -> tuple[Any, ...]:
    operands = tuple(
        sorted(
            _pointer_key(item["source_pointer"]) for item in row["required_operands"]
        )
    )
    by_id = {item["operand_id"]: item for item in row["required_operands"]}
    latest = by_id[row["latest_required_operand_id"]]
    distractor = row["unrelated_numeric_distractor"]
    return (
        row["operator"],
        str(row["unit"]).strip().casefold(),
        operands,
        _pointer_key(latest["source_pointer"]),
        _pointer_key(distractor["source_pointer"]),
    )


def _cohen_kappa(a: Iterable[str], b: Iterable[str]) -> float:
    left = tuple(a)
    right = tuple(b)
    if len(left) != len(right) or not left:
        raise AnnotationError("agreement vectors are invalid")
    observed = sum(x == y for x, y in zip(left, right, strict=True)) / len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum(left_counts[label] * right_counts[label] for label in STATUSES) / (
        len(left) ** 2
    )
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def build_consensus(
    rows_a: tuple[dict[str, Any], ...], rows_b: tuple[dict[str, Any], ...]
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    if len(rows_a) != 500 or len(rows_b) != 500:
        raise AnnotationError("consensus denominator must be 500 by 2")
    confusion = {left: {right: 0 for right in STATUSES} for left in STATUSES}
    consensus_rows: list[dict[str, Any]] = []
    eligible_by_partition: Counter[str] = Counter()
    for a, b in zip(rows_a, rows_b, strict=True):
        if (a["benchmark"], a["partition"], a["case_id"]) != (
            b["benchmark"],
            b["partition"],
            b["case_id"],
        ):
            raise AnnotationError("annotator case order differs")
        status_a = a["screening_status"]
        status_b = b["screening_status"]
        confusion[status_a][status_b] += 1
        exact_eligible = status_a == status_b == "ELIGIBLE" and _eligible_signature(
            a
        ) == _eligible_signature(b)
        if exact_eligible:
            consensus_status = "ELIGIBLE_CONSENSUS"
            eligible_by_partition[a["partition"]] += 1
        elif status_a == status_b == "INELIGIBLE":
            consensus_status = "INELIGIBLE_CONSENSUS"
        else:
            consensus_status = "DISAGREEMENT_OR_AMBIGUOUS"
        consensus_rows.append(
            {
                "schema": "milai.dg12.aggregation-consensus-row.v3",
                "benchmark": a["benchmark"],
                "partition": a["partition"],
                "case_id": a["case_id"],
                "annotator_a_status": status_a,
                "annotator_b_status": status_b,
                "consensus_status": consensus_status,
                "eligible_signature_exact_match": exact_eligible,
            }
        )
    raw_agreement = sum(confusion[label][label] for label in STATUSES) / len(rows_a)
    minimum = 8
    required_partitions = ("LME-PAPER-HOLDOUT-100", "BEAM-128K")
    prevalence_pass = all(
        eligible_by_partition[item] >= minimum for item in required_partitions
    )
    report = {
        "schema": "milai.dg12.annotation-agreement.v3",
        "status": "PASS_PREVALENCE"
        if prevalence_pass
        else "FAIL_PREVALENCE_CLAIM_UNSUPPORTED",
        "row_count_per_annotator": 500,
        "screened_case_count": 500,
        "confusion_matrix": confusion,
        "raw_agreement": round(raw_agreement, 9),
        "cohen_kappa": round(
            _cohen_kappa(
                (row["screening_status"] for row in rows_a),
                (row["screening_status"] for row in rows_b),
            ),
            9,
        ),
        "eligible_consensus_by_partition": {
            item: eligible_by_partition[item] for item in required_partitions
        },
        "minimum_eligible_per_partition": minimum,
        "prevalence_gate_pass": prevalence_pass,
        "formal_labels_opened": False,
        "method_outputs_visible_during_annotation": False,
        "replacement_sampling_allowed": False,
    }
    return report, tuple(consensus_rows)


def write_consensus_artifacts(
    *,
    report: Mapping[str, Any],
    rows: tuple[dict[str, Any], ...],
    report_path: Path,
    rows_path: Path,
) -> None:
    if len(rows) != 500 or report.get("screened_case_count") != 500:
        raise AnnotationError("refusing to write an incomplete consensus")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    report_temporary = report_path.with_name(f".{report_path.name}.{os.getpid()}.tmp")
    rows_temporary = rows_path.with_name(f".{rows_path.name}.{os.getpid()}.tmp")
    with report_temporary.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    with rows_temporary.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(report_temporary, 0o600)
    os.chmod(rows_temporary, 0o600)
    os.replace(report_temporary, report_path)
    os.replace(rows_temporary, rows_path)
