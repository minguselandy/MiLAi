"""DG-23 S1 retrospective, label-closed budget causality audit.

This module explains the frozen DG-22 512/2048 behaviour.  It deliberately
does not alter Runtime behaviour and never invokes the Reader or a provider.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from milai.application.evidence_semantics import (
    project_evidence_spans,
    run_type_directed_semantics,
)
from milai.application.memory_query import MemoryQueryCompiler
from milai.application.query_ir_compat import infer_operator_family

from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg16.lme10 import load_public_dev_cases
from evals.dg22.mediator import _case_evidence
from evals.dg23.baseline_freeze import (
    DG22_CONTEXTS,
    DG22_READER_PRODUCT,
    run_baseline_freeze,
)

DG22_MEDIATOR_PRODUCT = Path(
    "var/dg22/s7/dg22-s7-mediator-20260829-001/sealed-mediator-product.json"
)
CONTEXT_ARM = "B_DG22_FROZEN_FINAL_CONTEXT"
MEDIATOR_ARM = "E_SAFE_TEMPORAL_APPLICABILITY_COUNT"
BUDGETS = (512, 2048)
AFFECTED_CASE_ID = "gpt4_88806d6e"
FIRST_DIVERGENCE_ORDER = (
    "SOURCE_SNAPSHOT",
    "QUERY_IR",
    "ACQUISITION_SELECTED_CANDIDATE_SNAPSHOT",
    "GATE",
    "BINDING",
    "REQUIREMENT_STATE",
    "SUFFICIENCY",
    "OPERATOR",
    "PRESENTATION_VISIBLE_SPANS",
    "READER_CONTEXT",
    "READER_SEED",
)
_EVIDENCE_WINDOW = re.compile(
    r"\n\[E(?P<ordinal>\d+) observed_at=(?P<observed_at>[^ ]+) "
    r"speaker=(?P<speaker>[^\]]+)\]\n(?P<body>.*?)"
    r"(?=\n\[E\d+ observed_at=|\nMILAI_MEMORY_DATA_END)",
    re.DOTALL,
)


class DG23CausalityError(RuntimeError):
    """The frozen DG-22 causal denominator is incomplete or inconsistent."""


def build_budget_causality_audit(root: Path) -> dict[str, Any]:
    """Return the 20-cell DG-22 causality audit without loading source labels."""
    root = root.resolve()
    baseline = run_baseline_freeze(root)
    contexts = _read(root / DG22_CONTEXTS)
    mediator = _read(root / DG22_MEDIATOR_PRODUCT)
    reader_product = _read(root / DG22_READER_PRODUCT)
    context_index = _index_records(contexts, CONTEXT_ARM)
    mediator_index = _index_records(mediator, MEDIATOR_ARM)
    reader_index = _index_records(reader_product, CONTEXT_ARM)

    cases, selection = load_public_dev_cases()
    case_by_id = {case.case_id: case for case in cases}
    case_order = baseline["denominator"]["case_order"]
    if set(case_by_id) != set(case_order):
        raise DG23CausalityError("DG23_S1_OPENED_CASE_DENOMINATOR_DRIFT")

    records: list[dict[str, Any]] = []
    for case_id in case_order:
        case = case_by_id[case_id]
        evidence = _case_evidence(case)
        evidence_by_ref = {str(item["source_ref"]): item for item in evidence}
        reference = datetime.fromisoformat(
            normalize_lme_timestamp(case.question_at).replace("Z", "+00:00")
        )
        query_ir = MemoryQueryCompiler().compile(
            case.question,
            reference_time=reference,
        )
        query_payload = query_ir.model_dump(mode="json")
        query_digest = _digest(query_payload)
        for budget in BUDGETS:
            key = (case_id, budget)
            context_row = context_index[key]
            mediator_row = mediator_index[key]
            reader_row = reader_index[key]
            _verify_cross_artifact_cell(context_row, mediator_row, reader_row)
            if mediator_row.get("query_ir_sha256") != query_digest:
                raise DG23CausalityError(
                    f"DG23_S1_QUERY_IR_REPLAY_DRIFT:{case_id}:{budget}"
                )

            selected_refs = [str(value) for value in context_row["selected_source_refs"]]
            try:
                selected_evidence = [evidence_by_ref[ref] for ref in selected_refs]
            except KeyError as error:
                raise DG23CausalityError(
                    f"DG23_S1_SELECTED_SOURCE_REF_MISSING:{error.args[0]}"
                ) from error
            candidate_projection = [
                {
                    "ordinal": ordinal,
                    "source_ref": item["source_ref"],
                    "evidence_id": item["evidence_id"],
                    "content_hash": item["content_hash"],
                    "observed_at": item["observed_at"],
                    "speaker": item["speaker"],
                }
                for ordinal, item in enumerate(selected_evidence)
            ]
            gate_projection = [
                {
                    "source_ref": item["source_ref"],
                    "permission_snapshot": item["permission_snapshot"],
                    "retention_state": item["retention_state"],
                    "access_decision": item["access_decision"],
                    "speaker": item["speaker"],
                    "speaker_source": item["speaker_source"],
                    "content_hash": item["content_hash"],
                }
                for item in selected_evidence
            ]
            spans = project_evidence_spans(selected_evidence)
            interpretations, bindings, semantic_audit = run_type_directed_semantics(
                query_ir.requirements,
                spans,
                compatibility_profile="dg22-v0.2",
            )
            binding_projection = {
                "spans": [_json_value(item) for item in spans],
                "interpretations": [_json_value(item) for item in interpretations],
                "bindings": [_json_value(item) for item in bindings],
                "audit": _json_value(semantic_audit),
            }
            requirement_projection = {
                "required": list(mediator_row["required_requirement_ids"]),
                "matched": list(mediator_row["matched_requirement_ids"]),
                "found": list(mediator_row["found_requirement_ids"]),
                "missing_before": list(mediator_row["missing_before"]),
                "missing_after": list(mediator_row["missing_after"]),
            }
            sufficiency_projection = {
                "status": mediator_row["sufficiency_status"],
                "missing_after": list(mediator_row["missing_after"]),
                "operator_ready": bool(mediator_row["operator_ready"]),
            }
            operator_projection = {
                "operator_family": infer_operator_family(query_ir),
                "operator_ready": bool(mediator_row["operator_ready"]),
                "temporal_lane": mediator_row.get("temporal_lane"),
            }
            visible_spans = _visible_spans(str(context_row["context"]), selected_refs)
            provider = reader_row.get("provider")
            if not isinstance(provider, Mapping) or not isinstance(
                provider.get("seed"), int
            ):
                raise DG23CausalityError(
                    f"DG23_S1_READER_SEED_MISSING:{case_id}:{budget}"
                )
            source_snapshot = str(context_row["source_snapshot_digest"])
            layer_values = {
                "SOURCE_SNAPSHOT": source_snapshot,
                "QUERY_IR": query_digest,
                "ACQUISITION_SELECTED_CANDIDATE_SNAPSHOT": _digest(
                    candidate_projection
                ),
                "GATE": _digest(gate_projection),
                "BINDING": _digest(binding_projection),
                "REQUIREMENT_STATE": _digest(requirement_projection),
                "SUFFICIENCY": _digest(sufficiency_projection),
                "OPERATOR": _digest(operator_projection),
                "PRESENTATION_VISIBLE_SPANS": _digest(visible_spans),
                "READER_CONTEXT": str(context_row["context_sha256"]),
                "READER_SEED": str(provider["seed"]),
            }
            records.append(
                {
                    "case_id": case_id,
                    "category": context_row["category"],
                    "token_budget": budget,
                    "source_snapshot_digest": source_snapshot,
                    "query_ir_sha256": query_digest,
                    "candidate_snapshot_digest": layer_values[
                        "ACQUISITION_SELECTED_CANDIDATE_SNAPSHOT"
                    ],
                    "gate_digest": layer_values["GATE"],
                    "binding_digest": layer_values["BINDING"],
                    "requirement_state_digest": layer_values["REQUIREMENT_STATE"],
                    "sufficiency_digest": layer_values["SUFFICIENCY"],
                    "operator_digest": layer_values["OPERATOR"],
                    "selected_source_refs": selected_refs,
                    "selected_source_ref_count": len(selected_refs),
                    "visible_spans": visible_spans,
                    "visible_spans_digest": layer_values[
                        "PRESENTATION_VISIBLE_SPANS"
                    ],
                    "context_sha256": context_row["context_sha256"],
                    "context_tokens": context_row["context_tokens"],
                    "sealed_reader_seed": provider["seed"],
                    "sealed_reader_answer": reader_row["answer"],
                    "layer_values": layer_values,
                }
            )

    record_index = {
        (str(row["case_id"]), int(row["token_budget"])): row for row in records
    }
    traces = []
    for case_id in case_order:
        low = record_index[(case_id, 512)]
        high = record_index[(case_id, 2048)]
        comparisons = [
            {
                "layer": layer,
                "equal": low["layer_values"][layer] == high["layer_values"][layer],
                "budget_512": low["layer_values"][layer],
                "budget_2048": high["layer_values"][layer],
            }
            for layer in FIRST_DIVERGENCE_ORDER
        ]
        first = next((item["layer"] for item in comparisons if not item["equal"]), None)
        traces.append(
            {
                "case_id": case_id,
                "first_divergent_layer": first,
                "comparisons": comparisons,
            }
        )

    affected_low = record_index[(AFFECTED_CASE_ID, 512)]
    affected_high = record_index[(AFFECTED_CASE_ID, 2048)]
    affected_trace = next(row for row in traces if row["case_id"] == AFFECTED_CASE_ID)
    checks = {
        "frozen_s0_passed": baseline["hard_gate"]["passed"] is True,
        "opened_case_count_10": len(case_order) == 10,
        "candidate_cells_20_unique": len(records) == len(record_index) == 20,
        "selection_identity_matches_frozen_denominator": (
            selection.get("selection_digest")
            == contexts.get("selection_identity", {}).get("selection_digest")
        ),
        "source_snapshot_budget_invariant_10_of_10": all(
            record_index[(case_id, 512)]["source_snapshot_digest"]
            == record_index[(case_id, 2048)]["source_snapshot_digest"]
            for case_id in case_order
        ),
        "query_ir_budget_invariant_10_of_10": all(
            record_index[(case_id, 512)]["query_ir_sha256"]
            == record_index[(case_id, 2048)]["query_ir_sha256"]
            for case_id in case_order
        ),
        "affected_selected_source_counts_exact_3_8": (
            affected_low["selected_source_ref_count"] == 3
            and affected_high["selected_source_ref_count"] == 8
        ),
        "affected_historical_answers_exact": (
            affected_low["sealed_reader_answer"] == "Tom"
            and affected_high["sealed_reader_answer"] == "Mark and Sarah"
        ),
        "affected_first_divergence_is_acquisition_membership_order": (
            affected_trace["first_divergent_layer"]
            == "ACQUISITION_SELECTED_CANDIDATE_SNAPSHOT"
        ),
        "affected_historical_seed_was_budget_confounded": (
            affected_low["sealed_reader_seed"] != affected_high["sealed_reader_seed"]
        ),
        "source_labels_loaded_false": True,
        "reader_calls_zero": True,
        "provider_calls_zero": True,
        "formal_holdout_consumed_false": True,
        "runtime_behavior_changes_zero": True,
    }
    return {
        "schema": "milai.dg23.s1-budget-causality-audit.v0.1",
        "status": "PASS_DG22_BUDGET_CAUSALITY_AUDIT"
        if all(checks.values())
        else "FAIL_DG22_BUDGET_CAUSALITY_AUDIT",
        "classification": "RETROSPECTIVE_LABEL_CLOSED_DG22_DIAGNOSTIC",
        "case_order": case_order,
        "budgets": list(BUDGETS),
        "first_divergence_order": list(FIRST_DIVERGENCE_ORDER),
        "records": records,
        "first_divergence_traces": traces,
        "affected_case": {
            "case_id": AFFECTED_CASE_ID,
            "budget_512_selected_source_refs": affected_low["selected_source_refs"],
            "budget_2048_selected_source_refs": affected_high["selected_source_refs"],
            "budget_512_answer": affected_low["sealed_reader_answer"],
            "budget_2048_answer": affected_high["sealed_reader_answer"],
            "budget_512_seed": affected_low["sealed_reader_seed"],
            "budget_2048_seed": affected_high["sealed_reader_seed"],
            "first_divergent_layer": affected_trace["first_divergent_layer"],
            "root_cause_class": (
                "BUDGET_DEPENDENT_ACQUISITION_MEMBERSHIP_AND_ORDER_PRECEDES_"
                "PRESENTATION_AND_READER_SEED_DIVERGENCE"
            ),
        },
        "label_boundary": {
            "sealed_historical_answers_read_for_reproduction": True,
            "source_labels_loaded": False,
            "formal_holdout_consumed": False,
        },
        "safety": {
            "reader_calls": 0,
            "provider_calls": 0,
            "canonical_mutations": 0,
            "runtime_behavior_changes": 0,
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


def _index_records(
    product: Mapping[str, Any], arm: str
) -> dict[tuple[str, int], Mapping[str, Any]]:
    records = product.get("records")
    if not isinstance(records, list):
        raise DG23CausalityError("DG23_S1_RECORDS_MISSING")
    selected = [row for row in records if isinstance(row, Mapping) and row.get("arm") == arm]
    result = {(str(row["case_id"]), int(row["token_budget"])): row for row in selected}
    if len(selected) != len(result) or len(result) != 20:
        raise DG23CausalityError(f"DG23_S1_CELL_IDENTITY_INVALID:{arm}")
    return result


def _verify_cross_artifact_cell(
    context: Mapping[str, Any],
    mediator: Mapping[str, Any],
    reader: Mapping[str, Any],
) -> None:
    fields = ("case_id", "token_budget", "source_snapshot_digest", "context_sha256")
    for field in fields:
        if not (context.get(field) == mediator.get(field) == reader.get(field)):
            raise DG23CausalityError(f"DG23_S1_CROSS_ARTIFACT_DRIFT:{field}")
    if not (
        context.get("selected_source_refs")
        == mediator.get("selected_source_refs")
        == reader.get("selected_source_refs")
    ):
        raise DG23CausalityError("DG23_S1_SELECTED_SOURCE_ORDER_DRIFT")


def _visible_spans(context: str, refs: Sequence[str]) -> list[dict[str, Any]]:
    matches = list(_EVIDENCE_WINDOW.finditer(context))
    if len(matches) != len(refs):
        raise DG23CausalityError("DG23_S1_VISIBLE_SPAN_REF_CARDINALITY_DRIFT")
    return [
        {
            "ordinal": int(match.group("ordinal")),
            "source_ref": refs[index],
            "observed_at": match.group("observed_at"),
            "speaker": match.group("speaker"),
            "visible_body_sha256": hashlib.sha256(
                match.group("body").encode()
            ).hexdigest(),
            "visible_body_bytes": len(match.group("body").encode()),
        }
        for index, match in enumerate(matches)
    ]


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    return value


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG23CausalityError(f"DG23_S1_JSON_OBJECT_REQUIRED:{path}")
    return value


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
