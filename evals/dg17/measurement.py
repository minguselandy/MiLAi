"""DG-17 Q0 measurement closure over the frozen DG-16 ten-case terminal run."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Any, Protocol

from milai.application.memory_query import MemoryQueryCompiler

from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg14.provider import ProviderResult
from evals.dg16.lme10 import (
    EXPECTED_FULL_INPUT_SHA256,
    load_public_dev_cases,
    load_public_dev_labels,
)
from evals.paper.scorers.longmemeval import score_answer

ROOT = Path(__file__).resolve().parents[2]
LABELS_PATH = ROOT / "evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json"
DG16_RECEIPT_PATH = (
    ROOT
    / "var/dg16/lme10/dg16-lme10-compare-20260827-002/receipt-rescored.json"
)
DG16_CONTEXTS_PATH = (
    ROOT / "var/dg16/lme10/dg16-lme10-compare-20260827-002/contexts.json"
)
DG16_REVIEW_PATH = (
    ROOT / "var/dg16/release/dg16-release-review-20260827-001/review.json"
)
DG16_RECEIPT_SHA256 = (
    "e02a647ee4ffbcf70b7a92d8245770d5533219a54e5ccb23b06520c28e686afd"
)
DG16_CONTEXTS_SHA256 = (
    "96c385f6236cb719978474402152eabf1c309909c0b6ebc6df6083d7112cf4e8"
)
DG16_REVIEW_SHA256 = (
    "11a9dd978ebb3ed7ee558cf24b2e1405d81b7aac7addc4f6c808e1dd8f6f65be"
)
ORACLE_ARMS = (
    "A_GOLD_EVIDENCE_GOLD_IR",
    "B_ACTUAL_EVIDENCE_GOLD_IR",
    "C_GOLD_EVIDENCE_PREDICTED_IR",
    "D_ACTUAL_EVIDENCE_PREDICTED_IR",
)
ORACLE_PROMPT_LIMIT = 65_280


class DG17MeasurementError(RuntimeError):
    """A frozen Q0 identity, label, or denominator drifted."""


class OracleProvider(Protocol):
    def answer(
        self,
        *,
        run_id: str,
        case_id: str,
        method_id: str,
        question: str,
        question_as_of: str,
        memory_context: str,
        token_budget: int,
    ) -> ProviderResult: ...


TokenCount = Callable[[Any, str], int]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG17MeasurementError(f"invalid DG-17 JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise DG17MeasurementError(f"DG-17 JSON artifact must be an object: {path}")
    return value


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


@lru_cache(maxsize=1)
def _public_dev_cases() -> tuple[tuple[Any, ...], dict[str, Any]]:
    return load_public_dev_cases()


@lru_cache(maxsize=1)
def _public_dev_scoring_labels(
    source_ids: tuple[str, ...],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    return load_public_dev_labels(source_ids)


def load_answer_bearing_labels(
    path: Path = LABELS_PATH,
) -> tuple[dict[str, Any], tuple[Any, ...], dict[str, dict[str, Any]]]:
    cases, selection = _public_dev_cases()
    case_ids = tuple(case.case_id for case in cases)
    labels = _load_object(path)
    if (
        labels.get("schema") != "milai.dg17.answer-bearing-labels.v0.1"
        or labels.get("classification")
        != "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE"
        or labels.get("source_receipt_sha256") != DG16_RECEIPT_SHA256
        or labels.get("input_sha256") != EXPECTED_FULL_INPUT_SHA256
        or tuple(labels.get("case_ids", ())) != case_ids
        or not isinstance(labels.get("cases"), list)
    ):
        raise DG17MeasurementError("DG-17 answer-bearing label envelope drifted")
    if selection["formal_source_id_overlap"] != []:
        raise DG17MeasurementError("formal holdout overlap is nonzero")
    indexed_cases = {case.case_id: case for case in cases}
    indexed_labels: dict[str, dict[str, Any]] = {}
    atom_ids: set[str] = set()
    for raw in labels["cases"]:
        if not isinstance(raw, dict) or raw.get("case_id") not in indexed_cases:
            raise DG17MeasurementError("answer-bearing label case is invalid")
        case_id = str(raw["case_id"])
        if case_id in indexed_labels:
            raise DG17MeasurementError("answer-bearing label case is duplicated")
        required_slots = raw.get("required_slots")
        join_relations = raw.get("join_relations")
        atoms = raw.get("atoms")
        if (
            not isinstance(required_slots, list)
            or not required_slots
            or not isinstance(join_relations, list)
            or not isinstance(atoms, list)
            or not atoms
        ):
            raise DG17MeasurementError(f"case {case_id} label is incomplete")
        for atom in atoms:
            _validate_atom(indexed_cases[case_id], atom, required_slots, atom_ids)
        indexed_labels[case_id] = raw
    if tuple(indexed_labels) != case_ids:
        raise DG17MeasurementError("answer-bearing label order/denominator drifted")
    return labels, cases, indexed_labels


def _validate_atom(
    case: Any,
    atom: object,
    required_slots: Sequence[object],
    atom_ids: set[str],
) -> None:
    if not isinstance(atom, dict):
        raise DG17MeasurementError("answer-bearing atom must be an object")
    atom_id = atom.get("atom_id")
    session_ordinal = atom.get("session_ordinal")
    turn_ordinal = atom.get("turn_ordinal")
    span = atom.get("span")
    if (
        not isinstance(atom_id, str)
        or not atom_id
        or atom_id in atom_ids
        or atom.get("slot") not in required_slots
        or atom.get("speaker") not in {"user", "assistant"}
        or not isinstance(session_ordinal, int)
        or isinstance(session_ordinal, bool)
        or not isinstance(turn_ordinal, int)
        or isinstance(turn_ordinal, bool)
        or not isinstance(span, dict)
    ):
        raise DG17MeasurementError("answer-bearing atom contract drifted")
    atom_ids.add(atom_id)
    try:
        session = case.sessions[session_ordinal]
        turn = session.turns[turn_ordinal]
    except IndexError as exc:
        raise DG17MeasurementError("answer-bearing atom is outside frozen input") from exc
    expected_ref = (
        f"{case.case_id}:s{session_ordinal}:{session.session_id}:t{turn_ordinal}"
    )
    start, end, text = span.get("start"), span.get("end"), span.get("text")
    if (
        atom.get("session_id") != session.session_id
        or atom.get("source_turn_ref") != expected_ref
        or atom.get("speaker") != turn.role
        or not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or not isinstance(text, str)
        or start < 0
        or end <= start
        or turn.content[start:end] != text
    ):
        raise DG17MeasurementError("answer-bearing span does not match frozen input")


def _frozen_sources() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if sha256_file(DG16_RECEIPT_PATH) != DG16_RECEIPT_SHA256:
        raise DG17MeasurementError("DG-16 terminal receipt identity drifted")
    if sha256_file(DG16_CONTEXTS_PATH) != DG16_CONTEXTS_SHA256:
        raise DG17MeasurementError("DG-16 terminal contexts identity drifted")
    if sha256_file(DG16_REVIEW_PATH) != DG16_REVIEW_SHA256:
        raise DG17MeasurementError("DG-16 release review identity drifted")
    receipt = _load_object(DG16_RECEIPT_PATH)
    contexts_raw = _load_object(DG16_CONTEXTS_PATH).get("records")
    if (
        receipt.get("status") != "CHARACTERIZED"
        or receipt.get("run_id") != "dg16-lme10-compare-20260827-002"
        or not isinstance(contexts_raw, list)
    ):
        raise DG17MeasurementError("DG-16 terminal artifact contract drifted")
    contexts: dict[str, dict[str, Any]] = {}
    for record in contexts_raw:
        if (
            isinstance(record, dict)
            and record.get("method_id") == "DG16-MILAI-MCP"
            and record.get("token_budget") == 2048
            and isinstance(record.get("case_id"), str)
        ):
            contexts[str(record["case_id"])] = record
    if len(contexts) != 10:
        raise DG17MeasurementError("DG-16 2048 context denominator drifted")
    return receipt, contexts


def _terminal_records(receipt: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    records = receipt.get("records")
    if not isinstance(records, list):
        raise DG17MeasurementError("DG-16 terminal records are missing")
    selected: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if (
            isinstance(record, dict)
            and record.get("method_id") == "DG16-MILAI-MCP"
            and record.get("token_budget") == 2048
            and isinstance(record.get("case_id"), str)
        ):
            selected[str(record["case_id"])] = record
    if len(selected) != 10:
        raise DG17MeasurementError("DG-16 answer record denominator drifted")
    return selected


def _case_metric(
    case_label: Mapping[str, Any],
    scoring_label: Mapping[str, Any],
    context_record: Mapping[str, Any],
    answer_record: Mapping[str, Any],
) -> dict[str, Any]:
    context = context_record.get("context")
    trace = context_record.get("retrieval_trace")
    selected_refs = context_record.get("selected_source_refs")
    atoms = case_label.get("atoms")
    if (
        not isinstance(context, str)
        or not isinstance(trace, list)
        or not isinstance(selected_refs, list)
        or not isinstance(atoms, list)
    ):
        raise DG17MeasurementError("DG-16 case measurement input is incomplete")
    retrieved_sessions = {
        str(item["session_id"])
        for item in trace
        if isinstance(item, dict) and isinstance(item.get("session_id"), str)
    }
    required_sessions = {
        str(value) for value in scoring_label["answer_session_ids"]
    }
    answer_session_hits = sorted(retrieved_sessions.intersection(required_sessions))
    normalized_context = _normalized(context)
    selected_ref_set = {str(value) for value in selected_refs}
    hit_atoms = [
        str(atom["atom_id"])
        for atom in atoms
        if str(atom["source_turn_ref"]) in selected_ref_set
        and _normalized(str(atom["span"]["text"])) in normalized_context
    ]
    hit_atom_set = set(hit_atoms)
    required_turns = {str(atom["source_turn_ref"]) for atom in atoms}
    hit_turns = {
        str(atom["source_turn_ref"])
        for atom in atoms
        if str(atom["atom_id"]) in hit_atom_set
    }
    required_slots = [str(value) for value in case_label["required_slots"]]
    slot_atoms: defaultdict[str, list[str]] = defaultdict(list)
    for atom in atoms:
        slot_atoms[str(atom["slot"])].append(str(atom["atom_id"]))
    covered_slots = sorted(
        slot for slot, values in slot_atoms.items() if hit_atom_set.intersection(values)
    )
    complete_slots = sorted(
        slot for slot, values in slot_atoms.items() if set(values).issubset(hit_atom_set)
    )
    boundary_eligible = [
        atom
        for atom in atoms
        if str(atom["session_id"]) in retrieved_sessions
    ]
    boundary_lost = [
        str(atom["atom_id"])
        for atom in boundary_eligible
        if str(atom["atom_id"]) not in hit_atom_set
    ]
    selected_turn_lost = [
        str(atom["atom_id"])
        for atom in atoms
        if str(atom["source_turn_ref"]) in selected_ref_set
        and str(atom["atom_id"]) not in hit_atom_set
    ]
    answer_score = answer_record.get("answer_score")
    if not isinstance(answer_score, dict):
        raise DG17MeasurementError("DG-16 answer score is missing")
    operator = str(case_label["gold_ir"]["operator"])
    operator_emitted = (
        "EVIDENCE_COMPOSITION_RESULT" in context
        or "DERIVED_QUERY_RESULT" in context
    )
    operator_correct: bool | None = None
    acquisition_status = (
        "COMPLETE"
        if len(answer_session_hits) == len(required_sessions)
        else "PARTIAL"
        if answer_session_hits
        else "UNSATISFIED"
    )
    evidence_coverage = len(hit_atoms) / len(atoms)
    boundary_loss_rate = (
        len(boundary_lost) / len(boundary_eligible)
        if boundary_eligible
        else None
    )
    compiler_status = (
        "COMPLETE"
        if evidence_coverage == 1.0
        else "PARTIAL"
        if hit_atoms
        else "UNSATISFIED"
    )
    reader_status = (
        "CORRECT" if int(answer_score.get("exact_match", 0)) == 1 else "INCORRECT"
    )
    if acquisition_status != "COMPLETE":
        primary_failure = "ACQUISITION"
    elif evidence_coverage < 1.0:
        primary_failure = "CONTEXT_BOUNDARY"
    elif reader_status != "CORRECT":
        primary_failure = "READER"
    else:
        primary_failure = "NONE"
    return {
        "case_id": str(case_label["case_id"]),
        "query_class": str(case_label["gold_ir"]["query_class"]),
        "operator": operator,
        "answer_session_coverage": round(
            len(answer_session_hits) / len(required_sessions), 9
        ),
        "required_answer_sessions": sorted(required_sessions),
        "retrieved_answer_sessions": answer_session_hits,
        "answer_bearing_turn_recall": round(len(hit_turns) / len(required_turns), 9),
        "required_evidence_set_coverage": round(evidence_coverage, 9),
        "required_atom_count": len(atoms),
        "retrieved_atom_count": len(hit_atoms),
        "retrieved_atom_ids": hit_atoms,
        "required_slots": required_slots,
        "covered_slots": covered_slots,
        "complete_slots": complete_slots,
        "join_relations": list(case_label["join_relations"]),
        "operator_execution": {
            "emitted": operator_emitted,
            "correct": operator_correct,
            "reason": "NOT_EXECUTED_NO_RUNTIME_DERIVED_RESULT_IN_DG16_CONTEXT",
        },
        "context_boundary_loss_rate": (
            round(boundary_loss_rate, 9)
            if boundary_loss_rate is not None
            else None
        ),
        "boundary_eligible_atom_count": len(boundary_eligible),
        "boundary_lost_atom_ids": boundary_lost,
        "selected_turn_lost_atom_ids": selected_turn_lost,
        "primary_failure_stage": primary_failure,
        "stage_trace": [
            {
                "stage": "ACQUISITION",
                "status": acquisition_status,
                "coverage": round(
                    len(answer_session_hits) / len(required_sessions), 9
                ),
            },
            {
                "stage": "QUERY_COMPILER_OPERATOR",
                "status": "NOT_EXECUTED",
                "operator": operator,
                "correct": operator_correct,
            },
            {
                "stage": "CONTEXT_COMPILER",
                "status": compiler_status,
                "required_evidence_set_coverage": round(evidence_coverage, 9),
                "boundary_loss_rate": (
                    round(boundary_loss_rate, 9)
                    if boundary_loss_rate is not None
                    else None
                ),
            },
            {
                "stage": "READER",
                "status": reader_status,
                "exact_match": int(answer_score.get("exact_match", 0)),
                "normalized_f1": float(answer_score.get("normalized_f1", 0.0)),
            },
        ],
    }


def _aggregate(metrics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    boundary_lost = sum(len(item["boundary_lost_atom_ids"]) for item in metrics)
    boundary_eligible = sum(
        int(item["boundary_eligible_atom_count"]) for item in metrics
    )
    return {
        "case_count": len(metrics),
        "answer_session_coverage": round(
            mean(float(item["answer_session_coverage"]) for item in metrics), 9
        ),
        "answer_bearing_turn_recall": round(
            mean(float(item["answer_bearing_turn_recall"]) for item in metrics), 9
        ),
        "required_evidence_set_coverage": round(
            sum(int(item["retrieved_atom_count"]) for item in metrics)
            / sum(int(item["required_atom_count"]) for item in metrics),
            9,
        ),
        "operator_execution_accuracy": None,
        "context_boundary_loss_rate": (
            round(boundary_lost / boundary_eligible, 9)
            if boundary_eligible
            else None
        ),
        "operator_execution_denominator": 0,
        "context_boundary_denominator": boundary_eligible,
    }


def build_q0_receipt() -> dict[str, Any]:
    label_envelope, cases, labels = load_answer_bearing_labels()
    source_receipt, contexts = _frozen_sources()
    source_records = _terminal_records(source_receipt)
    source_ids = tuple(case.case_id for case in cases)
    scoring_labels, scoring_identity = _public_dev_scoring_labels(source_ids)
    metrics = [
        _case_metric(
            labels[case.case_id],
            scoring_labels[case.case_id],
            contexts[case.case_id],
            source_records[case.case_id],
        )
        for case in cases
    ]
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        grouped[str(metric["query_class"])].append(metric)
    return {
        "schema": "milai.dg17.q0-measurement.v0.1",
        "status": "Q0_MEASUREMENT_READY",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "dg16_terminal_freeze": {
            "receipt_path": str(DG16_RECEIPT_PATH.relative_to(ROOT)),
            "receipt_sha256": DG16_RECEIPT_SHA256,
            "receipt_status": source_receipt["status"],
            "run_id": source_receipt["run_id"],
            "contexts_path": str(DG16_CONTEXTS_PATH.relative_to(ROOT)),
            "contexts_sha256": DG16_CONTEXTS_SHA256,
            "release_review_path": str(DG16_REVIEW_PATH.relative_to(ROOT)),
            "release_review_sha256": DG16_REVIEW_SHA256,
            "baseline_2048_exact_match_count": source_receipt["summaries"]
            ["DG16-MILAI-MCP"]["2048"]["exact_match_count"],
            "baseline_2048_normalized_f1": source_receipt["summaries"]
            ["DG16-MILAI-MCP"]["2048"]["normalized_f1"],
        },
        "labels": {
            "path": str(LABELS_PATH.relative_to(ROOT)),
            "sha256": sha256_file(LABELS_PATH),
            "case_count": len(labels),
            "answer_bearing_turn_count": len(
                {
                    atom["source_turn_ref"]
                    for case in label_envelope["cases"]
                    for atom in case["atoms"]
                }
            ),
            "atom_count": sum(len(case["atoms"]) for case in label_envelope["cases"]),
            "slot_count": sum(
                len(case["required_slots"]) for case in label_envelope["cases"]
            ),
            "join_relation_count": sum(
                len(case["join_relations"]) for case in label_envelope["cases"]
            ),
        },
        "metrics": metrics,
        "aggregate": _aggregate(metrics),
        "by_query_class": {
            query_class: _aggregate(values)
            for query_class, values in sorted(grouped.items())
        },
        "label_boundary": {
            "scoring_label_source": scoring_identity,
            "product_path_label_access_count": 0,
            "formal_holdout_consumed": False,
            "formal_source_id_overlap": [],
            "status": "PASS",
        },
        "oracle_ladder": {
            "arms": list(ORACLE_ARMS),
            "status": "NOT_RUN",
            "results": [],
        },
    }


def _gold_evidence(case: Any, label: Mapping[str, Any]) -> str:
    rows = ["MILAI_MEMORY_DATA_BEGIN", "", "[GOLD EVIDENCE / EVALUATION ONLY]"]
    for atom in label["atoms"]:
        ref = str(atom["source_turn_ref"])
        session = case.sessions[int(atom["session_ordinal"])]
        rows.append(
            f"[EVIDENCE_ATOM id={atom['atom_id']} slot={atom['slot']} "
            f"source={ref} observed_at={session.observed_at}] "
            f"{atom['speaker']}: {atom['span']['text']}"
        )
    rows.extend(("", "MILAI_MEMORY_DATA_END"))
    return "\n\n".join(rows)


def build_oracle_contexts(
    case: Any,
    label: Mapping[str, Any],
    actual_evidence: str,
) -> dict[str, str]:
    gold_evidence = _gold_evidence(case, label)
    gold_ir = json.dumps(
        label["gold_ir"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    predicted = MemoryQueryCompiler().compile(
        case.question,
        reference_time=datetime.fromisoformat(
            normalize_lme_timestamp(case.question_at)
        ),
    )
    predicted_ir = predicted.model_dump_json()

    def rendered(evidence: str, ir_name: str, ir: str) -> str:
        return f"[{ir_name}]\n{ir}\n\n{evidence}"

    return {
        "A_GOLD_EVIDENCE_GOLD_IR": rendered(gold_evidence, "GOLD IR", gold_ir),
        "B_ACTUAL_EVIDENCE_GOLD_IR": rendered(actual_evidence, "GOLD IR", gold_ir),
        "C_GOLD_EVIDENCE_PREDICTED_IR": rendered(
            gold_evidence, "PREDICTED IR", predicted_ir
        ),
        "D_ACTUAL_EVIDENCE_PREDICTED_IR": rendered(
            actual_evidence, "PREDICTED IR", predicted_ir
        ),
    }


def run_oracle_ladder(
    receipt: dict[str, Any],
    *,
    provider: OracleProvider,
    token_count: TokenCount,
    run_id: str,
) -> dict[str, Any]:
    _envelope, cases, labels = load_answer_bearing_labels()
    _source_receipt, actual_contexts = _frozen_sources()
    source_ids = tuple(case.case_id for case in cases)
    scoring_labels, _identity = _public_dev_scoring_labels(source_ids)
    results: list[dict[str, Any]] = []
    for case in cases:
        contexts = build_oracle_contexts(
            case,
            labels[case.case_id],
            str(actual_contexts[case.case_id]["context"]),
        )
        arms: list[dict[str, Any]] = []
        for arm in ORACLE_ARMS:
            memory_context = contexts[arm]
            prompt_tokens = token_count(case, memory_context)
            if prompt_tokens > ORACLE_PROMPT_LIMIT:
                arms.append(
                    {
                        "arm": arm,
                        "status": "UNAVAILABLE_CONTEXT_LIMIT",
                        "prompt_tokens": prompt_tokens,
                        "prompt_limit": ORACLE_PROMPT_LIMIT,
                        "provider_calls": 0,
                        "context_truncated": False,
                    }
                )
                continue
            result = provider.answer(
                run_id=run_id,
                case_id=case.case_id,
                method_id=f"DG17-Q0-{arm}",
                question=case.question,
                question_as_of=case.question_at,
                memory_context=memory_context,
                token_budget=ORACLE_PROMPT_LIMIT,
            )
            if result.context_truncated:
                raise DG17MeasurementError("oracle context was unexpectedly truncated")
            arms.append(
                {
                    "arm": arm,
                    "status": "SUCCEEDED",
                    "answer": result.answer,
                    "answer_sha256": result.answer_sha256,
                    "score": score_answer(
                        result.answer, scoring_labels[case.case_id]["answers"]
                    ),
                    "prompt_tokens": result.prompt_tokens,
                    "memory_tokens": result.memory_tokens,
                    "completion_tokens": result.completion_tokens,
                    "provider_calls": result.provider_calls,
                    "provider_latency_ms": round(result.provider_latency_ms, 3),
                    "context_truncated": result.context_truncated,
                    "seed": result.seed,
                }
            )
        results.append(
            {
                "case_id": case.case_id,
                "query_class": labels[case.case_id]["gold_ir"]["query_class"],
                "arms": arms,
                "diagnosis": _oracle_diagnosis(arms),
            }
        )
    receipt["oracle_ladder"] = {
        "arms": list(ORACLE_ARMS),
        "prompt_limit": ORACLE_PROMPT_LIMIT,
        "diagnostic_success_policy": "strict exact_match=1; raw F1 remains reported",
        "predicted_ir_source": "MemoryQueryCompiler actual v0.2 output",
        "single_run_causal_claim_authorized": False,
        "status": "COMPLETED_WITH_TYPED_UNAVAILABLE",
        "results": results,
    }
    receipt["status"] = "Q0_CHARACTERIZED"
    return receipt


def _oracle_diagnosis(arms: Sequence[Mapping[str, Any]]) -> str:
    by_name = {str(arm["arm"]): arm for arm in arms}
    a = by_name["A_GOLD_EVIDENCE_GOLD_IR"]
    b = by_name["B_ACTUAL_EVIDENCE_GOLD_IR"]
    c = by_name["C_GOLD_EVIDENCE_PREDICTED_IR"]
    d = by_name["D_ACTUAL_EVIDENCE_PREDICTED_IR"]

    def successful(arm: Mapping[str, Any]) -> bool:
        score = arm.get("score")
        return (
            arm.get("status") == "SUCCEEDED"
            and isinstance(score, Mapping)
            and int(score.get("exact_match", 0)) == 1
        )

    if not successful(a):
        return "READER_CEILING_OR_TASK_AMBIGUITY"
    if not successful(b):
        return "ACQUISITION_OR_COMPOSITION_FAILURE"
    if not successful(c):
        return "QUERY_COMPILER_OR_OPERATOR_FAILURE"
    if not successful(d):
        return "END_TO_END_INTERACTION_FAILURE"
    return "NO_ORACLE_DELTA"


__all__ = [
    "LABELS_PATH",
    "ORACLE_ARMS",
    "ORACLE_PROMPT_LIMIT",
    "DG17MeasurementError",
    "build_oracle_contexts",
    "build_q0_receipt",
    "load_answer_bearing_labels",
    "run_oracle_ladder",
]
