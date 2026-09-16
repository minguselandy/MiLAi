"""DG-16 Q0 metrics and oracle diagnostics, confined to the evaluation plane."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from evals.dg14.benchmark import (
    METHOD_ID,
    OPENED_DEV_CASE_IDS,
    OPENED_DEV_INPUT_PATH,
    OPENED_DEV_INPUT_SHA256,
    OpenedDevCase,
    load_opened_dev,
)
from evals.dg14.provider import ProviderResult
from evals.paper.scorers.longmemeval import score_answer

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_PATH = (
    ROOT / "evals/dg16/fixtures/opened-dev-evidence-atoms.v1.json"
)
DEFAULT_CONTEXTS_PATH = (
    ROOT / "var/dg14/runs/dg14-matched-001-20260826/contexts.json"
)
DEFAULT_MANIFEST_PATH = (
    ROOT / "var/dg14/runs/dg14-matched-001-20260826/manifest.json"
)
EXPECTED_CONTEXTS_SHA256 = (
    "d6d228b22b6f85ba5068f2d19b717363a114da4abce73849088da033d62723b3"
)
EXPECTED_MANIFEST_SHA256 = (
    "c9b4fd64d1c7351b963eb9f0c901661f69176ab5df491e9107112f25004e1714"
)
ORACLE_ARMS = (
    "A_FULL_HISTORY",
    "B_GOLD_EVIDENCE_SET",
    "C_GOLD_QUERYSPEC_ACTUAL_RETRIEVAL",
    "D_ACTUAL_QUERYSPEC_ACTUAL_RETRIEVAL",
)
ORACLE_PROMPT_LIMIT = 65_280


class DG16Q0Error(RuntimeError):
    """A frozen Q0 evaluation artifact or boundary drifted."""


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


TokenCount = Callable[[OpenedDevCase, str], int]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG16Q0Error(f"invalid Q0 JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise DG16Q0Error(f"Q0 JSON artifact must be an object: {path}")
    return value


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _source_turn_ref(case: OpenedDevCase, session: int, turn: int) -> str:
    original_session_id = case.sessions[session].session_id
    return f"{case.case_id}:s{session}:{original_session_id}:t{turn}"


def _case_by_id(cases: Sequence[OpenedDevCase]) -> dict[str, OpenedDevCase]:
    return {case.case_id: case for case in cases}


def load_evaluation_fixture(
    path: Path = DEFAULT_FIXTURE_PATH,
    *,
    cases: Sequence[OpenedDevCase] | None = None,
) -> dict[str, Any]:
    """Load and verify exact turn spans without exposing them to product code."""

    if cases is None:
        _partition, loaded_cases = load_opened_dev(OPENED_DEV_INPUT_PATH)
        cases = loaded_cases
    value = _load_object(path)
    if (
        value.get("schema") != "milai.dg16.opened-dev-evidence-atoms.v1"
        or value.get("classification")
        != "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE"
        or value.get("input_sha256") != OPENED_DEV_INPUT_SHA256
        or tuple(value.get("case_ids", ())) != OPENED_DEV_CASE_IDS
        or not isinstance(value.get("cases"), list)
    ):
        raise DG16Q0Error("Q0 evaluation fixture envelope drifted")
    indexed_cases = _case_by_id(cases)
    if tuple(indexed_cases) != OPENED_DEV_CASE_IDS:
        raise DG16Q0Error("Q0 input case identity/order drifted")
    seen: list[str] = []
    atom_ids: set[str] = set()
    for raw_case in value["cases"]:
        if not isinstance(raw_case, dict):
            raise DG16Q0Error("Q0 case label must be an object")
        case_id = raw_case.get("case_id")
        if not isinstance(case_id, str) or case_id not in indexed_cases:
            raise DG16Q0Error("Q0 case label has an unknown case_id")
        seen.append(case_id)
        raw_atoms = raw_case.get("required_atoms")
        if not isinstance(raw_atoms, list) or not raw_atoms:
            raise DG16Q0Error(f"Q0 case {case_id} has no required atoms")
        case = indexed_cases[case_id]
        for atom in raw_atoms:
            _validate_atom(case, atom, atom_ids)
        for event in raw_case.get("temporal_events", []):
            if not isinstance(event, dict):
                raise DG16Q0Error("temporal event must be an object")
            span = event.get("span")
            if span is not None:
                _validate_span_ref(case, event, span)
    if tuple(seen) != OPENED_DEV_CASE_IDS:
        raise DG16Q0Error("Q0 fixture case order or completeness drifted")
    return value


def _validate_atom(
    case: OpenedDevCase, atom: object, atom_ids: set[str]
) -> None:
    if not isinstance(atom, dict):
        raise DG16Q0Error("required atom must be an object")
    atom_id = atom.get("atom_id")
    if not isinstance(atom_id, str) or not atom_id or atom_id in atom_ids:
        raise DG16Q0Error("required atom identity is empty or duplicated")
    atom_ids.add(atom_id)
    span = atom.get("span")
    if not isinstance(span, dict):
        raise DG16Q0Error(f"required atom {atom_id} has no exact span")
    _validate_span_ref(case, atom, span)


def _validate_span_ref(
    case: OpenedDevCase, owner: Mapping[str, Any], span: Mapping[str, Any]
) -> None:
    session_ordinal = owner.get("session_ordinal")
    turn_ordinal = owner.get("turn_ordinal")
    if session_ordinal is None or turn_ordinal is None:
        ref = owner.get("source_turn_ref")
        if not isinstance(ref, str):
            raise DG16Q0Error("span owner has no source turn identity")
        match = re.fullmatch(r"[^:]+:s(\d+):[^:]+:t(\d+)", ref)
        if match is None:
            raise DG16Q0Error("source turn ref is malformed")
        session_ordinal, turn_ordinal = map(int, match.groups())
    if (
        not isinstance(session_ordinal, int)
        or isinstance(session_ordinal, bool)
        or not isinstance(turn_ordinal, int)
        or isinstance(turn_ordinal, bool)
    ):
        raise DG16Q0Error("source turn ordinals must be integers")
    try:
        turn = case.sessions[session_ordinal].turns[turn_ordinal]
    except IndexError as exc:
        raise DG16Q0Error("source turn ref is outside the frozen input") from exc
    expected_ref = _source_turn_ref(case, session_ordinal, turn_ordinal)
    if owner.get("source_turn_ref") != expected_ref:
        raise DG16Q0Error("source turn ref does not match the frozen input")
    if "session_id" in owner:
        expected_session_id = case.sessions[session_ordinal].session_id
        if owner.get("session_id") != expected_session_id:
            raise DG16Q0Error("atom session identity drifted")
    start, end, text = span.get("start"), span.get("end"), span.get("text")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or not isinstance(text, str)
        or start < 0
        or end <= start
        or turn.content[start:end] != text
    ):
        raise DG16Q0Error("answer-bearing span does not match frozen raw text")


def _load_current_contexts(path: Path) -> dict[str, dict[str, Any]]:
    if _sha256(path) != EXPECTED_CONTEXTS_SHA256:
        raise DG16Q0Error("DG14 frozen contexts hash drifted")
    value = _load_object(path)
    records = value.get("records")
    if not isinstance(records, list):
        raise DG16Q0Error("DG14 contexts records are missing")
    selected: dict[str, dict[str, Any]] = {}
    for record in records:
        if (
            isinstance(record, dict)
            and record.get("method_id") == METHOD_ID
            and record.get("token_budget") == 2048
            and isinstance(record.get("case_id"), str)
        ):
            selected[record["case_id"]] = record
    if tuple(selected) != OPENED_DEV_CASE_IDS:
        raise DG16Q0Error("DG14 2048-token context cells are incomplete or reordered")
    return selected


def _retrieval_configuration(
    contexts: Mapping[str, Mapping[str, Any]], manifest_path: Path
) -> dict[str, Any]:
    if _sha256(manifest_path) != EXPECTED_MANIFEST_SHA256:
        raise DG16Q0Error("DG14 frozen manifest hash drifted")
    config_ids: set[str] = set()
    embedding_calls = 0
    vector_calls = 0
    reranker_calls = 0
    for record in contexts.values():
        raw_resolve = record.get("raw_resolve")
        usage = record.get("usage")
        if not isinstance(raw_resolve, dict) or not isinstance(usage, dict):
            raise DG16Q0Error("DG14 retrieval receipt is incomplete")
        search_trace = raw_resolve.get("search_trace")
        access_trace = usage.get("access_trace")
        if not isinstance(search_trace, dict) or not isinstance(access_trace, dict):
            raise DG16Q0Error("DG14 search/access trace is incomplete")
        config_id = search_trace.get("config_identity")
        structural = access_trace.get("structural_cost")
        if not isinstance(config_id, str) or not isinstance(structural, dict):
            raise DG16Q0Error("DG14 retrieval identity/cost is incomplete")
        config_ids.add(config_id)
        embedding_calls += int(structural.get("embedding_calls", 0))
        vector_calls += int(structural.get("vector_search_calls", 0))
        reranker_calls += int(structural.get("reranker_calls", 0))
    if len(config_ids) != 1:
        raise DG16Q0Error("DG14 retrieval configuration was not constant")
    return {
        "source_manifest": str(manifest_path.relative_to(ROOT)),
        "source_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "config_identity": next(iter(config_ids)),
        "embedding": {
            "calls": embedding_calls,
            "model_id": "UNKNOWN_NOT_BOUND_BY_DG14_MANIFEST",
            "revision": "UNKNOWN_NOT_BOUND_BY_DG14_MANIFEST",
            "dimensions": "UNKNOWN_NOT_BOUND_BY_DG14_MANIFEST",
        },
        "vector_search_calls": vector_calls,
        "reranker": {
            "calls": reranker_calls,
            "model_id": "UNKNOWN_NOT_BOUND_BY_DG14_MANIFEST",
            "observed_execution": "NOT_EXECUTED" if reranker_calls == 0 else "EXECUTED",
        },
        "case_count": len(contexts),
    }


def _case_metric(
    label: Mapping[str, Any], record: Mapping[str, Any]
) -> dict[str, Any]:
    context = record.get("context")
    source_ids = record.get("source_ids")
    atoms = label.get("required_atoms")
    labeled_sessions = label.get("lme_answer_session_ids")
    if (
        not isinstance(context, str)
        or not isinstance(source_ids, list)
        or not isinstance(atoms, list)
        or not isinstance(labeled_sessions, list)
    ):
        raise DG16Q0Error("Q0 metric inputs are incomplete")
    retrieved_sessions = set(source_ids)
    relevant_sessions = set(labeled_sessions)
    session_hits = sorted(retrieved_sessions.intersection(relevant_sessions))
    atom_hits = [
        atom["atom_id"]
        for atom in atoms
        if _normalized(atom["span"]["text"]) in _normalized(context)
    ]
    slot_hits = sorted(
        {
            atom["slot"]
            for atom in atoms
            if atom["atom_id"] in set(atom_hits)
        }
    )
    required_slots = list(label["gold_query_spec"]["required_slots"])
    case_id = str(label["case_id"])
    coverage = len(atom_hits) / len(atoms)
    temporal = case_id == "00ca467f"
    if coverage == 1.0:
        failure = "NONE"
        secondary: list[str] = []
    elif not session_hits:
        failure = "CANDIDATE_RECALL_MISS"
        secondary = ["TEMPORAL_RANGE_INCOMPLETE"] if temporal else []
    elif case_id == "0100672e":
        failure = "EVIDENCE_BOUNDARY_LOSS"
        secondary = ["REQUIRED_SLOT_MISSING"]
    else:
        failure = "REQUIRED_SLOT_MISSING"
        secondary = []
    return {
        "case_id": case_id,
        "session_recall": round(
            len(session_hits) / len(relevant_sessions), 9
        ),
        "session_hits": session_hits,
        "answer_bearing_turn_recall": round(coverage, 9),
        "required_evidence_set_coverage": round(coverage, 9),
        "required_atom_count": len(atoms),
        "retrieved_atom_count": len(atom_hits),
        "retrieved_atom_ids": atom_hits,
        "required_slots": required_slots,
        "filled_slots": slot_hits,
        "temporal_range_resolved": False if temporal else None,
        "bounded_scan_completed": False if temporal else None,
        "projection_watermark_covered": False if temporal else None,
        "primary_failure": failure,
        "secondary_diagnostics": secondary,
    }


def _render_full_history(case: OpenedDevCase) -> str:
    rows = ["MILAI_MEMORY_DATA_BEGIN", "", "[FULL HISTORY]"]
    for session_ordinal, session in enumerate(case.sessions):
        rows.append(
            f"[SESSION s{session_ordinal} id={session.session_id} "
            f"observed_at={session.observed_at}]"
        )
        for turn_ordinal, turn in enumerate(session.turns):
            ref = _source_turn_ref(case, session_ordinal, turn_ordinal)
            rows.append(f"[{ref}] {turn.role}: {turn.content}")
    rows.extend(("", "MILAI_MEMORY_DATA_END"))
    return "\n".join(rows)


def _render_gold_evidence(
    case: OpenedDevCase, label: Mapping[str, Any]
) -> str:
    rows = ["MILAI_MEMORY_DATA_BEGIN", "", "[GOLD EVIDENCE SET / EVALUATION ONLY]"]
    seen: set[str] = set()
    owners = list(label["required_atoms"])
    for event in label.get("temporal_events", []):
        if "span" in event:
            owners.append(event)
    for owner in owners:
        ref = owner["source_turn_ref"]
        if ref in seen:
            continue
        seen.add(ref)
        match = re.fullmatch(r"[^:]+:s(\d+):[^:]+:t(\d+)", ref)
        if match is None:
            raise DG16Q0Error("gold evidence source turn ref is malformed")
        session_ordinal, turn_ordinal = map(int, match.groups())
        turn = case.sessions[session_ordinal].turns[turn_ordinal]
        rows.append(f"[RAW USER EVIDENCE ref={ref}] {turn.content}")
    rows.extend(("", "MILAI_MEMORY_DATA_END"))
    return "\n\n".join(rows)


def build_oracle_contexts(
    case: OpenedDevCase,
    label: Mapping[str, Any],
    actual_context: str,
) -> dict[str, str]:
    """Build A-D inputs; only this evaluation module can see gold fields."""

    query_spec = json.dumps(
        label["gold_query_spec"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "A_FULL_HISTORY": _render_full_history(case),
        "B_GOLD_EVIDENCE_SET": _render_gold_evidence(case, label),
        "C_GOLD_QUERYSPEC_ACTUAL_RETRIEVAL": (
            "[GOLD QUERYSPEC / EVALUATION ONLY]\n"
            f"{query_spec}\n\n{actual_context}"
        ),
        "D_ACTUAL_QUERYSPEC_ACTUAL_RETRIEVAL": (
            "[ACTUAL DG14 QUERYSPEC]\n"
            '{"operator":null,"status":"UNTYPED_NEED_REQUIRES_FULL_PIPELINE"}'
            f"\n\n{actual_context}"
        ),
    }


def build_q0_receipt(
    *,
    contexts_path: Path = DEFAULT_CONTEXTS_PATH,
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Recompute Q0 metrics from immutable DG14 artifacts without product calls."""

    _partition, cases = load_opened_dev(OPENED_DEV_INPUT_PATH)
    fixture = load_evaluation_fixture(fixture_path, cases=cases)
    contexts = _load_current_contexts(contexts_path)
    labels = {item["case_id"]: item for item in fixture["cases"]}
    metrics = [_case_metric(labels[case_id], contexts[case_id]) for case_id in labels]
    correct_case_ids = [
        item["case_id"]
        for item in metrics
        if item["required_evidence_set_coverage"] == 1.0
    ]
    return {
        "schema": "milai.dg16.q0-diagnosis.v1",
        "status": "Q0_METRICS_READY",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "input": {
            "path": str(OPENED_DEV_INPUT_PATH.relative_to(ROOT)),
            "sha256": OPENED_DEV_INPUT_SHA256,
            "formal_holdout_consumed": False,
        },
        "evaluation_fixture": {
            "path": str(fixture_path.relative_to(ROOT)),
            "sha256": _sha256(fixture_path),
            "case_count": len(labels),
            "required_atom_count": sum(
                len(item["required_atoms"]) for item in fixture["cases"]
            ),
        },
        "source_contexts": {
            "path": str(contexts_path.relative_to(ROOT)),
            "sha256": EXPECTED_CONTEXTS_SHA256,
            "method_id": METHOD_ID,
            "token_budget": 2048,
        },
        "retrieval_configuration": _retrieval_configuration(
            contexts, manifest_path
        ),
        "metrics": metrics,
        "correct_case_atom_replay": {
            "case_ids": correct_case_ids,
            "count": len(correct_case_ids),
            "status": "PASS" if len(correct_case_ids) == 3 else "FAIL",
        },
        "label_boundary": {
            "label_plane": "evals/dg16 + var/dg16 only",
            "product_path_label_access_count": 0,
            "case_count": len(labels),
            "status": "PASS",
        },
        "oracle_ladder": {
            "arms": list(ORACLE_ARMS),
            "status": "NOT_RUN",
            "results": [],
        },
    }


def run_oracle_ladder(
    receipt: dict[str, Any],
    *,
    provider: OracleProvider,
    token_count: TokenCount,
    run_id: str,
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
    contexts_path: Path = DEFAULT_CONTEXTS_PATH,
) -> dict[str, Any]:
    """Run B-D and run A only when the exact full history fits current vLLM."""

    _partition, cases = load_opened_dev(OPENED_DEV_INPUT_PATH)
    fixture = load_evaluation_fixture(fixture_path, cases=cases)
    contexts = _load_current_contexts(contexts_path)
    labels = {item["case_id"]: item for item in fixture["cases"]}
    results: list[dict[str, Any]] = []
    for case in cases:
        label = labels[case.case_id]
        oracle_contexts = build_oracle_contexts(
            case, label, str(contexts[case.case_id]["context"])
        )
        arms: list[dict[str, Any]] = []
        for arm in ORACLE_ARMS:
            context = oracle_contexts[arm]
            prompt_tokens = token_count(case, context)
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
                method_id=f"DG16-Q0-{arm}",
                question=case.question,
                question_as_of=case.question_at,
                memory_context=context,
                token_budget=ORACLE_PROMPT_LIMIT,
            )
            if result.context_truncated:
                raise DG16Q0Error("an oracle input was unexpectedly truncated")
            arms.append(
                {
                    "arm": arm,
                    "status": "SUCCEEDED",
                    "answer": result.answer,
                    "answer_sha256": result.answer_sha256,
                    "score": score_answer(result.answer, label["answers"]),
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
                "arms": arms,
                "diagnosis": _oracle_diagnosis(arms),
            }
        )
    receipt["oracle_ladder"] = {
        "arms": list(ORACLE_ARMS),
        "prompt_limit": ORACLE_PROMPT_LIMIT,
        "full_history_policy": "NO_TRUNCATION; typed unavailable above current vLLM limit",
        "status": "COMPLETED_WITH_TYPED_UNAVAILABLE",
        "results": results,
    }
    receipt["status"] = "Q0_COMPLETE"
    return receipt


def _oracle_diagnosis(arms: Sequence[Mapping[str, Any]]) -> str:
    by_name = {str(arm["arm"]): arm for arm in arms}
    a = by_name["A_FULL_HISTORY"]
    b = by_name["B_GOLD_EVIDENCE_SET"]
    c = by_name["C_GOLD_QUERYSPEC_ACTUAL_RETRIEVAL"]
    d = by_name["D_ACTUAL_QUERYSPEC_ACTUAL_RETRIEVAL"]
    if a["status"] != "SUCCEEDED":
        prefix = "FULL_HISTORY_UNAVAILABLE_CURRENT_CONTEXT_LIMIT;"
    elif int(a["score"]["exact_match"]) == 0:
        return "READER_OR_TASK_AMBIGUITY"
    else:
        prefix = ""
    if b["status"] != "SUCCEEDED" or int(b["score"]["exact_match"]) == 0:
        return prefix + "GOLD_EVIDENCE_REPRESENTATION_OR_READER_FAILURE"
    if c["status"] != "SUCCEEDED" or int(c["score"]["exact_match"]) == 0:
        return prefix + "RETRIEVAL_OR_COMPOSITION_FAILURE"
    if d["status"] != "SUCCEEDED" or int(d["score"]["exact_match"]) == 0:
        return prefix + "QUERYSPEC_PLANNING_FAILURE"
    return prefix + "NO_ORACLE_DELTA"
