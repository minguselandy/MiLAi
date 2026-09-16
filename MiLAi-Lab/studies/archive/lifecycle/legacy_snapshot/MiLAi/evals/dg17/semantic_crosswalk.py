"""Q3A measurement bridge from immutable Q0 Atom labels to v0.2 semantics."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from milai.application.memory_query import MemoryQueryCompiler
from milai.application.query_ir_compat import (
    infer_operator_family,
    translate_memory_query_ir_v01,
)

from evals.dg17.measurement import (
    LABELS_PATH,
    ROOT,
    load_answer_bearing_labels,
    sha256_file,
)

EXPECTED_LABELS_SHA256 = (
    "4a88cb030e67cce456b1dfe159fce177a5ace4b972f11af2a6674639c52dc876"
)
IMMUTABLE_Q0_RECEIPT = (
    "var/dg17/q0/dg17-q0-measurement-20260827-001/receipt.json"
)
IMMUTABLE_Q0_RECEIPT_SHA256 = (
    "d4dada38b69a26681f2f8898dccd573823deef4af8b288da3f91b5bac1783132"
)
_EXPECTED_FAMILY = {
    "LOOKUP": "LOOKUP",
    "TEMPORAL_FILTER": "TEMPORAL_FILTER",
    "TEMPORAL_ORDER": "TEMPORAL_ORDER",
    "TEMPORAL_DISTANCE": "TEMPORAL_DISTANCE",
    "COUNT_DISTINCT": "COUNT",
    "DIVIDE_VALUES": "DIVIDE",
    "MULTI_EVIDENCE_JOIN": "MULTI_JOIN",
    "PREFERENCE_RESOLVE": "PREFERENCE_RESOLVE",
}


class SemanticCrosswalkError(RuntimeError):
    """The immutable label identity or prediction envelope is invalid."""


def build_semantic_crosswalk() -> dict[str, Any]:
    """Translate label semantics without rewriting or promoting Q0 labels."""

    if sha256_file(LABELS_PATH) != EXPECTED_LABELS_SHA256:
        raise SemanticCrosswalkError("immutable Q0 atom-label identity drifted")
    if sha256_file(ROOT / IMMUTABLE_Q0_RECEIPT) != IMMUTABLE_Q0_RECEIPT_SHA256:
        raise SemanticCrosswalkError("immutable Q0 measurement receipt identity drifted")
    _envelope, cases, labels = load_answer_bearing_labels()
    compiler = MemoryQueryCompiler()
    case_rows: list[dict[str, Any]] = []
    contract_rows: list[dict[str, Any]] = []
    span_ids: set[str] = set()
    interpretation_count = 0
    binding_count = 0
    for case_id, label in labels.items():
        spans: dict[str, dict[str, Any]] = {}
        interpretations: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []
        for atom in label["atoms"]:
            source = atom["span"]
            span_key = _span_key(
                str(atom["source_turn_ref"]),
                int(source["start"]),
                int(source["end"]),
                str(source["text"]),
            )
            span_id = f"expected-span:{span_key}"
            span_ids.add(span_id)
            spans.setdefault(
                span_id,
                {
                    "span_id": span_id,
                    "source_turn_ref": atom["source_turn_ref"],
                    "session_id": atom["session_id"],
                    "speaker": atom["speaker"],
                    "start": source["start"],
                    "end": source["end"],
                    "text": source["text"],
                    "measurement_only": True,
                },
            )
            interpretation_id = f"expected-interpretation:{atom['atom_id']}"
            interpretations.append(
                {
                    "interpretation_id": interpretation_id,
                    "span_id": span_id,
                    "kind": atom["atom_type"],
                    "legacy_atom_id": atom["atom_id"],
                    "measurement_only": True,
                }
            )
            bindings.append(
                {
                    "requirement_id": atom["slot"],
                    "interpretation_id": interpretation_id,
                    "expected_status": "MATCH",
                    "measurement_only": True,
                }
            )
            interpretation_count += 1
            binding_count += 1
        case_rows.append(
            {
                "case_id": case_id,
                "required_slots": list(label["required_slots"]),
                "spans": list(spans.values()),
                "interpretations": interpretations,
                "bindings": bindings,
            }
        )
    for case in cases:
        label = labels[case.case_id]
        reference = datetime.strptime(
            case.question_at, "%Y/%m/%d (%a) %H:%M"
        ).replace(tzinfo=UTC)
        legacy = compiler.compile_v01(case.question, reference_time=reference)
        translated = translate_memory_query_ir_v01(legacy, query=case.question)
        product = compiler.compile(case.question, reference_time=reference)
        expected_family = _EXPECTED_FAMILY[str(label["gold_ir"]["operator"])]
        translated_family = infer_operator_family(translated)
        product_family = infer_operator_family(product)
        translated_requirements = [
            requirement.model_dump(mode="json")
            for requirement in translated.requirements
        ]
        product_requirements = [
            requirement.model_dump(mode="json")
            for requirement in product.requirements
        ]
        target_event_present = any(
            requirement.slot_id == "TARGET_EVENT"
            and requirement.interpretation_kind == "EVENT"
            for requirement in product.requirements
        )
        contract_rows.append(
            {
                "case_id": case.case_id,
                "expected_operator_family": expected_family,
                "translated_operator_family": translated_family,
                "product_operator_family": product_family,
                "operator_family_expected": product_family == expected_family,
                "compatibility_operator_identity_preserved": (
                    translated_family == product_family
                ),
                "compatibility_requirement_identity_preserved": (
                    translated_requirements == product_requirements
                ),
                "target_event_identity_preserved": (
                    expected_family != "TEMPORAL_FILTER"
                    or (
                        target_event_present
                        and product_family == "TEMPORAL_FILTER"
                    )
                ),
                "generic_lookup_collapse": (
                    expected_family != "LOOKUP" and product_family == "LOOKUP"
                ),
                "auxiliary_model_calls": product.planner_trace.auxiliary_model_calls,
            }
        )
    contract_passed = all(
        row["operator_family_expected"]
        and row["compatibility_operator_identity_preserved"]
        and row["compatibility_requirement_identity_preserved"]
        and row["target_event_identity_preserved"]
        and not row["generic_lookup_collapse"]
        and row["auxiliary_model_calls"] == 0
        for row in contract_rows
    )
    return {
        "schema": "milai.dg17.semantic-measurement-crosswalk.v0.1",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "source": {
            "atom_labels": str(LABELS_PATH.relative_to(ROOT)),
            "atom_labels_sha256": EXPECTED_LABELS_SHA256,
            "immutable_q0_receipt": IMMUTABLE_Q0_RECEIPT,
            "immutable_q0_receipt_sha256": IMMUTABLE_Q0_RECEIPT_SHA256,
            "source_mutated": False,
        },
        "semantics": {
            "legacy_atom_is_measurement_label_only": True,
            "span_is_source_pointer_only": True,
            "interpretation_is_fallible_candidate": True,
            "binding_is_query_local": True,
            "canonical_authority_promoted": False,
            "product_path_labels_exposed": False,
        },
        "denominators": {
            "case_count": len(case_rows),
            "legacy_atom_count": interpretation_count,
            "unique_answer_bearing_span_count": len(span_ids),
            "expected_interpretation_count": interpretation_count,
            "expected_binding_count": binding_count,
            "typed_contract_case_count": len(contract_rows),
        },
        "typed_contract_gate": {
            "status": "PASS" if contract_passed else "FAIL",
            "operator_family_expected": sum(
                row["operator_family_expected"] for row in contract_rows
            ),
            "compatibility_operator_identity_preserved": sum(
                row["compatibility_operator_identity_preserved"]
                for row in contract_rows
            ),
            "compatibility_requirement_identity_preserved": sum(
                row["compatibility_requirement_identity_preserved"]
                for row in contract_rows
            ),
            "target_event_identity_preserved": sum(
                row["target_event_identity_preserved"] for row in contract_rows
            ),
            "generic_lookup_collapse": sum(
                row["generic_lookup_collapse"] for row in contract_rows
            ),
            "denominator": len(contract_rows),
            "annotation_review_boundary": "PROVISIONAL_OPENED_DEV_LABELS",
        },
        "typed_contract_rows": contract_rows,
        "cases": case_rows,
    }


def score_semantic_predictions(
    predictions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Score source spans, typed interpretations, bindings, and slot coverage.

    Predictions use runtime-local IDs. Matching therefore relies on exact source
    coordinates plus interpretation kind, never on immutable label IDs.
    """

    crosswalk = build_semantic_crosswalk()
    expected_cases = {row["case_id"]: row for row in crosswalk["cases"]}
    predicted_cases = {str(row.get("case_id")): row for row in predictions}
    if len(predicted_cases) != len(predictions):
        raise SemanticCrosswalkError("prediction case_id is missing or duplicated")

    expected_span_total = 0
    matched_span_total = 0
    expected_interpretation_total = 0
    matched_interpretation_total = 0
    predicted_match_bindings = 0
    correct_match_bindings = 0
    required_slot_total = 0
    covered_slot_total = 0
    case_metrics: list[dict[str, Any]] = []

    for case_id, expected in expected_cases.items():
        predicted = predicted_cases.get(case_id, {})
        predicted_spans = _prediction_list(predicted, "spans")
        predicted_interpretations = _prediction_list(predicted, "interpretations")
        predicted_bindings = _prediction_list(predicted, "bindings")
        expected_span_keys = {_row_span_key(row) for row in expected["spans"]}
        predicted_span_by_id = {
            str(row.get("span_id")): _row_span_key(row) for row in predicted_spans
        }
        predicted_span_keys = set(predicted_span_by_id.values())
        matched_spans = len(expected_span_keys & predicted_span_keys)

        expected_signatures = Counter(
            (
                _expected_span_key(expected, str(row["span_id"])),
                str(row["kind"]),
            )
            for row in expected["interpretations"]
        )
        predicted_signature_by_id: dict[str, tuple[str, str]] = {}
        for row in predicted_interpretations:
            span_key = predicted_span_by_id.get(str(row.get("span_id")))
            kind = row.get("kind")
            interpretation_id = row.get("interpretation_id")
            if span_key is None or not isinstance(kind, str) or not isinstance(
                interpretation_id, str
            ):
                continue
            predicted_signature_by_id[interpretation_id] = (span_key, kind)
        predicted_signatures = Counter(predicted_signature_by_id.values())
        matched_interpretations = sum(
            min(count, predicted_signatures[signature])
            for signature, count in expected_signatures.items()
        )
        expected_slots_by_signature: dict[tuple[str, str], set[str]] = defaultdict(set)
        expected_interpretation_by_id = {
            str(row["interpretation_id"]): row for row in expected["interpretations"]
        }
        for binding in expected["bindings"]:
            interpretation = expected_interpretation_by_id[
                str(binding["interpretation_id"])
            ]
            expected_signature = (
                _expected_span_key(expected, str(interpretation["span_id"])),
                str(interpretation["kind"]),
            )
            expected_slots_by_signature[expected_signature].add(
                str(binding["requirement_id"])
            )

        covered_slots: set[str] = set()
        case_predicted_bindings = 0
        case_correct_bindings = 0
        for binding in predicted_bindings:
            if binding.get("status") != "MATCH":
                continue
            case_predicted_bindings += 1
            predicted_signature = predicted_signature_by_id.get(
                str(binding.get("interpretation_id"))
            )
            requirement_id = binding.get("requirement_id")
            if (
                predicted_signature is not None
                and isinstance(requirement_id, str)
                and requirement_id
                in expected_slots_by_signature.get(predicted_signature, set())
            ):
                case_correct_bindings += 1
                covered_slots.add(requirement_id)

        required_slots = set(map(str, expected["required_slots"]))
        expected_span_total += len(expected_span_keys)
        matched_span_total += matched_spans
        expected_interpretation_total += sum(expected_signatures.values())
        matched_interpretation_total += matched_interpretations
        predicted_match_bindings += case_predicted_bindings
        correct_match_bindings += case_correct_bindings
        required_slot_total += len(required_slots)
        covered_slot_total += len(required_slots & covered_slots)
        case_metrics.append(
            {
                "case_id": case_id,
                "answer_bearing_span_recall": _ratio(
                    matched_spans, len(expected_span_keys)
                ),
                "answer_bearing_interpretation_recall": _ratio(
                    matched_interpretations, sum(expected_signatures.values())
                ),
                "requirement_binding_precision": _ratio(
                    case_correct_bindings, case_predicted_bindings
                ),
                "required_slot_coverage": _ratio(
                    len(required_slots & covered_slots), len(required_slots)
                ),
            }
        )

    return {
        "schema": "milai.dg17.semantic-measurement-score.v0.1",
        "denominators": {
            "answer_bearing_spans": expected_span_total,
            "answer_bearing_interpretations": expected_interpretation_total,
            "predicted_match_bindings": predicted_match_bindings,
            "required_slots": required_slot_total,
        },
        "aggregate": {
            "answer_bearing_span_recall": _ratio(
                matched_span_total, expected_span_total
            ),
            "answer_bearing_interpretation_recall": _ratio(
                matched_interpretation_total, expected_interpretation_total
            ),
            "requirement_binding_precision": _ratio(
                correct_match_bindings, predicted_match_bindings
            ),
            "required_slot_coverage": _ratio(
                covered_slot_total, required_slot_total
            ),
        },
        "metrics": case_metrics,
    }


def _span_key(source_ref: str, start: int, end: int, text: str) -> str:
    material = json.dumps(
        [source_ref, start, end, text],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _row_span_key(row: Mapping[str, Any]) -> str:
    return _span_key(
        str(row.get("source_turn_ref")),
        int(row.get("start", -1)),
        int(row.get("end", -1)),
        str(row.get("text")),
    )


def _expected_span_key(expected: Mapping[str, Any], span_id: str) -> str:
    return _row_span_key(
        next(row for row in expected["spans"] if row["span_id"] == span_id)
    )


def _prediction_list(
    predicted: Mapping[str, Any], key: str
) -> list[Mapping[str, Any]]:
    value = predicted.get(key, [])
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        raise SemanticCrosswalkError(f"prediction {key} must be a list of objects")
    return list(value)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 9) if denominator else 0.0


__all__ = [
    "EXPECTED_LABELS_SHA256",
    "IMMUTABLE_Q0_RECEIPT_SHA256",
    "SemanticCrosswalkError",
    "build_semantic_crosswalk",
    "score_semantic_predictions",
]
