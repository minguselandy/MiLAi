from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from types import ModuleType
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_adapter_contract as adapter_contract
from scripts import run_dg10_benchmark_dev_smoke as dev_smoke

DATE = "2026-08-21"
CANDIDATE = "candidate.3"
DATASET = "LONGMEMEVAL_V2_ADAPTED_TEXT_ONLY"
SUPPORTED_ARMS = ("NO_MEMORY", "NAIVE_RAG")
DETERMINISTIC_EVAL_NAMES = {
    "mc_choice_match",
    "mc_choice_set_match",
    "norm_phrase_set_match",
    "norm_phrase_set_match_ordered",
}
LLM_EVAL_NAMES = {"llm_abstention_checker", "llm_gotchas_checker"}
FROZEN_QA_EVALUATOR_SHA256 = (
    "f8ba659e237c4282a07a92538090ea500ce8483820b390b1d19af187c01417ac"
)
DEFAULT_DATASET_LOCK = (
    ROOT / f"docs/reports/DG-10-benchmark-dataset-lock-candidate.3-{DATE}.json"
)
DEFAULT_ADAPTER_REPORT = (
    ROOT / f"docs/reports/DG-10-benchmark-adapter-contract-candidate.4-{DATE}.json"
)
DEFAULT_CALIBRATION_PLAN = (
    ROOT / f"docs/reports/DG-10-benchmark-calibration-plan-candidate.4-{DATE}.json"
)
DEFAULT_LONGMEMEVAL_V2_ROOT = WORKSPACE_ROOT / "benchmarks/LongMemEval-V2"
DEFAULT_QA_EVALUATOR = DEFAULT_LONGMEMEVAL_V2_ROOT / "evaluation/qa_eval_metrics.py"
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-benchmark-lme-v2-dev-smoke-{CANDIDATE}-{DATE}.json"
)
DEFAULT_SUPERSEDED_ATTEMPT_RECEIPT = (
    ROOT
    / f"docs/reports/DG-10-benchmark-lme-v2-dev-failed-attempt-candidate.2-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = (
    WORKSPACE_ROOT / "evidence/dg10-benchmark-lme-v2-dev-smoke"
)
MAX_INITIAL_MEMORY_CHARACTERS = 32_000
RETRIEVAL_K = 1


class LmeV2SmokeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TextChunk:
    evidence_id: str
    text: str


@dataclass(frozen=True, slots=True)
class LmeV2Case:
    case_id: str
    source_case_id: str
    dataset: str
    category: str
    domain: str
    question: str
    answer: str
    eval_function: str
    chunks: tuple[TextChunk, ...]


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LmeV2SmokeError(f"{label} must be an object")
    return value


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LmeV2SmokeError(f"invalid JSON file: {path}") from exc


def _require_locked_file(path: Path, lock: Mapping[str, Any], label: str) -> None:
    if not path.is_file():
        raise LmeV2SmokeError(f"missing {label}: {path}")
    if path.stat().st_size != lock.get("size"):
        raise LmeV2SmokeError(f"{label} size differs from dataset lock")
    if dev_smoke._sha256_file(path) != lock.get("sha256"):
        raise LmeV2SmokeError(f"{label} SHA-256 differs from dataset lock")


def _load_superseded_attempt_receipt(path: Path) -> dict[str, Any]:
    receipt = _require_object(_load_json(path), "superseded attempt receipt")
    execution = _require_object(receipt.get("execution"), "failed-attempt execution")
    retry = _require_object(
        receipt.get("supersession_and_retry_accounting"),
        "failed-attempt retry accounting",
    )
    if (
        receipt.get("schema")
        != "milai.dg10.benchmark-lme-v2-failed-attempt-receipt.v1"
        or receipt.get("status")
        != "INVALIDATED_FAILED_ATTEMPT_EXCLUDED_FROM_CALIBRATION"
        or receipt.get("test_labels_or_outputs_opened") is not False
        or execution.get("local_vllm_completion_http_200_requests") != 1
        or execution.get("validated_records") != 0
        or retry.get("cross_attempt_repeated_case_arm_requests_expected") != 1
    ):
        raise LmeV2SmokeError("superseded failed-attempt receipt boundary mismatch")
    return {
        "status": "BOUND_INVALIDATED_ATTEMPT_EXCLUDED_FROM_DENOMINATORS",
        "receipt_sha256": dev_smoke._sha256_file(path),
        "prior_completion_http_200_requests": 1,
        "prior_validated_records": 0,
        "cross_attempt_repeated_case_arm_requests": 1,
        "current_candidate_internal_retries": 0,
    }


def _load_dataset_lock(
    path: Path,
    adapter: Mapping[str, Any],
    calibration: Mapping[str, Any],
) -> dict[str, Any]:
    lock = _require_object(_load_json(path), "dataset lock")
    if (
        lock.get("schema") != "milai.dg10.benchmark-dataset-lock.v1"
        or lock.get("status") != "DATASET_LOCK_CANDIDATE_REVIEW_REQUIRED"
    ):
        raise LmeV2SmokeError("dataset lock boundary mismatch")
    lock_sha256 = dev_smoke._sha256_file(path)
    adapter_inputs = _require_object(adapter.get("inputs"), "adapter inputs")
    calibration_inputs = _require_object(
        calibration.get("inputs"), "calibration inputs"
    )
    if (
        adapter_inputs.get("dataset_lock_report_sha256") != lock_sha256
        or calibration_inputs.get("dataset_lock_report_sha256") != lock_sha256
    ):
        raise LmeV2SmokeError("dataset-lock report binding mismatch")
    datasets = _require_object(lock.get("datasets"), "locked datasets")
    return _require_object(datasets.get("longmemeval_v2"), "LongMemEval-V2 lock")


def _selected_dev_ids(
    calibration: Mapping[str, Any],
    *,
    case_limit: int,
    requested_case_ids: Sequence[str] | None,
) -> tuple[list[str], list[str]]:
    split = _require_object(calibration.get("dev_split"), "dev split")
    planned = [
        item
        for item in split["dev_case_ids"]
        if isinstance(item, str) and item.startswith("longmemeval_v2:")
    ]
    per_dataset = _require_object(split.get("per_dataset"), "per-dataset split")
    dataset_split = _require_object(
        per_dataset.get(DATASET), "LongMemEval-V2 dev split"
    )
    if (
        dataset_split.get("dev") != len(planned)
        or dataset_split.get("dev_case_ids_sha256") != dev_smoke._json_sha256(planned)
    ):
        raise LmeV2SmokeError("LongMemEval-V2 dev split drift")
    if requested_case_ids:
        requested = list(requested_case_ids)
        if len(set(requested)) != len(requested) or any(
            item not in planned for item in requested
        ):
            raise LmeV2SmokeError("requested case IDs must be unique planned V2 dev IDs")
        selected = [item for item in planned if item in set(requested)]
    else:
        if case_limit <= 0 or case_limit > len(planned):
            raise LmeV2SmokeError("case limit exceeds the planned V2 dev split")
        selected = planned[:case_limit]
    return planned, selected


def _read_questions(
    path: Path,
    file_lock: Mapping[str, Any],
    question_counts: Mapping[str, Any],
    selected_case_ids: Sequence[str],
    expected_text_count: int,
) -> dict[str, dict[str, Any]]:
    _require_locked_file(path, file_lock, "LongMemEval-V2 questions")
    selected = set(selected_case_ids)
    all_ids: list[str] = []
    text_ids: list[str] = []
    rows: dict[str, dict[str, Any]] = {}
    with path.open("rb") as stream:
        for line_no, raw in enumerate(stream, start=1):
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise LmeV2SmokeError(
                    f"invalid LongMemEval-V2 question line {line_no}"
                ) from exc
            if not isinstance(row, dict):
                raise LmeV2SmokeError("LongMemEval-V2 question row must be an object")
            source_id = row.get("id")
            if not isinstance(source_id, str) or not source_id:
                raise LmeV2SmokeError("LongMemEval-V2 question ID is invalid")
            all_ids.append(source_id)
            if row.get("image") is None:
                text_ids.append(source_id)
            case_id = f"longmemeval_v2:{source_id}"
            if case_id in selected:
                rows[case_id] = row
    if (
        len(all_ids) != question_counts.get("total")
        or len(set(all_ids)) != len(all_ids)
        or dev_smoke._json_sha256(sorted(all_ids))
        != question_counts.get("all_case_ids_sha256")
        or len(text_ids) != expected_text_count
        or len(text_ids) != question_counts.get("text_only")
        or dev_smoke._json_sha256(sorted(text_ids))
        != question_counts.get("text_only_case_ids_sha256")
        or set(rows) != selected
    ):
        raise LmeV2SmokeError("LongMemEval-V2 question identity/coverage drift")
    for case_id, row in rows.items():
        required_strings = (
            "id",
            "domain",
            "environment",
            "question_type",
            "question",
            "answer",
            "eval_function",
        )
        if row.get("image") is not None or any(
            not isinstance(row.get(key), str) or not str(row[key]).strip()
            for key in required_strings
        ):
            raise LmeV2SmokeError(f"selected V2 case is not valid text-only data: {case_id}")
    return rows


def _render_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _render_chunks(trajectory: Mapping[str, Any]) -> tuple[TextChunk, ...]:
    trajectory_id = str(trajectory["id"])
    chunks: list[TextChunk] = []
    metadata_parts = []
    for key in ("goal", "outcome", "start_url"):
        rendered = _render_value(trajectory.get(key))
        if rendered:
            metadata_parts.append(f"{key}: {rendered}")
    if metadata_parts:
        chunks.append(
            TextChunk(
                evidence_id=f"{trajectory_id}:metadata",
                text=f"[trajectory_id={trajectory_id}]\n" + "\n".join(metadata_parts),
            )
        )
    states = trajectory.get("states")
    if not isinstance(states, list) or not states:
        raise LmeV2SmokeError(f"trajectory {trajectory_id} has no states")
    for offset, state in enumerate(states):
        if not isinstance(state, dict):
            raise LmeV2SmokeError(f"trajectory {trajectory_id} state is invalid")
        state_index = state.get("state_index", offset)
        parts = [f"[trajectory_id={trajectory_id} state_index={state_index}]"]
        for key in ("url", "thought", "action", "accessibility_tree"):
            rendered = _render_value(state.get(key))
            if rendered:
                parts.append(f"{key}: {rendered}")
        chunks.append(
            TextChunk(
                evidence_id=f"{trajectory_id}:state:{state_index}",
                text="\n".join(parts),
            )
        )
    return tuple(chunks)


def _scan_selected_trajectories(
    path: Path,
    lock: Mapping[str, Any],
    needed_ids: set[str],
) -> tuple[dict[str, tuple[TextChunk, ...]], dict[str, Any]]:
    if not path.is_file():
        raise LmeV2SmokeError(f"missing LongMemEval-V2 trajectories: {path}")
    if path.stat().st_size != lock.get("size"):
        raise LmeV2SmokeError("LongMemEval-V2 trajectory size differs from dataset lock")
    digest = hashlib.sha256()
    seen_ids: set[str] = set()
    selected: dict[str, tuple[TextChunk, ...]] = {}
    with path.open("rb") as stream:
        for line_no, raw in enumerate(stream, start=1):
            digest.update(raw)
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise LmeV2SmokeError(f"invalid trajectory line {line_no}") from exc
            if not isinstance(row, dict):
                raise LmeV2SmokeError("trajectory row must be an object")
            trajectory_id = row.get("id")
            if not isinstance(trajectory_id, str) or not trajectory_id:
                raise LmeV2SmokeError("trajectory ID is invalid")
            if trajectory_id in seen_ids:
                raise LmeV2SmokeError(f"duplicate trajectory ID: {trajectory_id}")
            seen_ids.add(trajectory_id)
            if trajectory_id in needed_ids:
                selected[trajectory_id] = _render_chunks(row)
    if (
        digest.hexdigest() != lock.get("sha256")
        or len(seen_ids) != lock.get("trajectory_count_from_data_card")
        or set(selected) != needed_ids
    ):
        raise LmeV2SmokeError("LongMemEval-V2 trajectory identity/coverage drift")
    return selected, {
        "sha256": digest.hexdigest(),
        "size": path.stat().st_size,
        "scan_mode": "SINGLE_PASS_JSONL_HASH_AND_SELECTED_ID_COLLECTION",
        "total_trajectory_count": len(seen_ids),
        "selected_unique_trajectory_count": len(selected),
    }


def _load_cases(
    *,
    root: Path,
    dataset_lock: Mapping[str, Any],
    calibration: Mapping[str, Any],
    case_limit: int,
    requested_case_ids: Sequence[str] | None,
) -> tuple[list[LmeV2Case], dict[str, Any]]:
    planned, selected_ids = _selected_dev_ids(
        calibration,
        case_limit=case_limit,
        requested_case_ids=requested_case_ids,
    )
    files = _require_object(dataset_lock.get("files"), "LongMemEval-V2 locked files")
    question_lock = _require_object(
        files.get("data/longmemeval-v2/questions.jsonl"), "questions lock"
    )
    haystack_lock = _require_object(
        files.get("data/longmemeval-v2/haystacks/lme_v2_small.json"),
        "small haystack lock",
    )
    trajectory_lock = _require_object(
        files.get("data/longmemeval-v2/trajectories.jsonl"), "trajectories lock"
    )
    data_root = root / "data/longmemeval-v2"
    questions_path = data_root / "questions.jsonl"
    haystack_path = data_root / "haystacks/lme_v2_small.json"
    trajectories_path = data_root / "trajectories.jsonl"
    split = _require_object(calibration.get("dev_split"), "dev split")
    dataset_split = _require_object(
        _require_object(split.get("per_dataset"), "per-dataset split").get(DATASET),
        "V2 split",
    )
    question_rows = _read_questions(
        questions_path,
        question_lock,
        _require_object(dataset_lock.get("question_counts"), "question counts"),
        selected_ids,
        int(dataset_split["total"]),
    )
    _require_locked_file(haystack_path, haystack_lock, "LongMemEval-V2 small haystack")
    haystack = _require_object(_load_json(haystack_path), "small haystack")
    source_ids = [case_id.split(":", 1)[1] for case_id in selected_ids]
    trajectory_ids_by_case: dict[str, list[str]] = {}
    needed_ids: set[str] = set()
    for source_id in source_ids:
        values = haystack.get(source_id)
        if (
            not isinstance(values, list)
            or len(values) != 100
            or len(set(values)) != len(values)
            or any(not isinstance(item, str) or not item for item in values)
        ):
            raise LmeV2SmokeError(f"invalid small haystack for {source_id}")
        trajectory_ids_by_case[source_id] = values
        needed_ids.update(values)
    trajectories, trajectory_evidence = _scan_selected_trajectories(
        trajectories_path, trajectory_lock, needed_ids
    )
    cases: list[LmeV2Case] = []
    for case_id in selected_ids:
        row = question_rows[case_id]
        source_id = str(row["id"])
        chunks: list[TextChunk] = []
        for trajectory_id in trajectory_ids_by_case[source_id]:
            trajectory_chunks = trajectories[trajectory_id]
            chunks.extend(trajectory_chunks)
        if not chunks:
            raise LmeV2SmokeError(f"selected case has no text chunks: {case_id}")
        cases.append(
            LmeV2Case(
                case_id=case_id,
                source_case_id=source_id,
                dataset=DATASET,
                category=str(row["question_type"]),
                domain=str(row["domain"]),
                question=str(row["question"]),
                answer=str(row["answer"]),
                eval_function=str(row["eval_function"]),
                chunks=tuple(chunks),
            )
        )
    return cases, {
        "path_class": "REPO_EXTERNAL_PUBLIC_BENCHMARK_INPUT",
        "adapter_protocol": "TEXT_ONLY_LOSSY_NOT_OFFICIAL_FULL_SMALL",
        "official_total_case_count": dataset_lock["question_counts"]["total"],
        "adapted_text_only_case_count": dataset_split["total"],
        "planned_dev_case_count": len(planned),
        "selected_dev_case_count": len(cases),
        "selected_dev_case_ids_sha256": dev_smoke._json_sha256(selected_ids),
        "questions_sha256": question_lock["sha256"],
        "small_haystack_sha256": haystack_lock["sha256"],
        "trajectory_evidence": trajectory_evidence,
    }


def _terms(text: str) -> Counter[str]:
    return Counter(
        token.casefold()
        for token in dev_smoke._WORD.findall(text)
        if len(token) > 1
    )


def _retrieve(case: LmeV2Case, k: int = RETRIEVAL_K) -> tuple[str, list[str]]:
    query = _terms(case.question)
    ranked: list[tuple[int, str, str]] = []
    for chunk in case.chunks:
        chunk_terms = _terms(chunk.text)
        overlap = sum(
            min(count, chunk_terms.get(token, 0)) for token, count in query.items()
        )
        ranked.append((-overlap, chunk.evidence_id, chunk.text))
    ranked.sort(key=lambda item: (item[0], item[1]))
    selected = ranked[:k]
    memory = "\n\n".join(item[2] for item in selected)
    return memory[:MAX_INITIAL_MEMORY_CHARACTERS], [item[1] for item in selected]


def _load_evaluator(path: Path) -> tuple[ModuleType, str]:
    evaluator_sha256 = dev_smoke._sha256_file(path)
    if evaluator_sha256 != FROZEN_QA_EVALUATOR_SHA256:
        raise LmeV2SmokeError("official QA evaluator differs from the audited frozen byte")
    spec = importlib.util.spec_from_file_location("dg10_lme_v2_qa_eval_metrics", path)
    if spec is None or spec.loader is None:
        raise LmeV2SmokeError("cannot load official QA evaluator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in (*DETERMINISTIC_EVAL_NAMES, "eval_from_spec", "eval_name"):
        if not callable(getattr(module, name, None)):
            raise LmeV2SmokeError(f"official QA evaluator is missing {name}")
    return module, evaluator_sha256


def _score(
    evaluator: ModuleType,
    *,
    eval_function: str,
    prediction: str,
    answer: str,
) -> dict[str, Any]:
    eval_name = str(evaluator.eval_name(eval_function))
    fallback_phrase = bool(
        evaluator.norm_phrase_set_match(prediction, answer, require_non_empty=True)
    )
    fallback_f1 = round(dev_smoke._f1(prediction, answer), 6)
    if eval_name in DETERMINISTIC_EVAL_NAMES:
        official_local_score = bool(
            evaluator.eval_from_spec(eval_function, prediction, answer)
        )
        lane = "OFFICIAL_LOCAL_DETERMINISTIC_FUNCTION"
    elif eval_name in LLM_EVAL_NAMES:
        official_local_score = None
        lane = "ADAPTED_FALLBACK_EXTERNAL_LLM_JUDGE_PROHIBITED"
    else:
        raise LmeV2SmokeError(f"unsupported V2 eval function: {eval_name}")
    return {
        "eval_function_name": eval_name,
        "eval_function_spec_sha256": dev_smoke._sha256_bytes(eval_function.encode()),
        "scoring_lane": lane,
        "official_local_deterministic_score": official_local_score,
        "fallback_normalized_phrase_match": fallback_phrase,
        "fallback_normalized_f1": fallback_f1,
        "external_judge_called": False,
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _aggregates(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["arm"])].append(record)
    result: dict[str, Any] = {}
    for arm, group in sorted(grouped.items()):
        deterministic = [
            bool(item["answer_record"]["official_local_deterministic_score"])
            for item in group
            if item["answer_record"]["official_local_deterministic_score"] is not None
        ]
        phrase = [
            bool(item["answer_record"]["fallback_normalized_phrase_match"])
            for item in group
        ]
        f1 = [float(item["answer_record"]["fallback_normalized_f1"]) for item in group]
        truncated = [bool(item["answer_record"]["output_truncated"]) for item in group]
        latency = [float(item["latency_ms"]) for item in group]
        result[f"{DATASET}/{arm}"] = {
            "case_count": len(group),
            "official_local_deterministic_denominator": len(deterministic),
            "official_local_deterministic_accuracy": (
                round(mean(deterministic), 6) if deterministic else None
            ),
            "adapted_fallback_denominator": len(group),
            "fallback_normalized_phrase_match_mean": round(mean(phrase), 6),
            "fallback_normalized_f1_mean": round(mean(f1), 6),
            "truncated_output_count": sum(truncated),
            "truncated_output_rate": round(mean(truncated), 6),
            "input_tokens": sum(int(item["usage"]["input_tokens"]) for item in group),
            "output_tokens": sum(int(item["usage"]["output_tokens"]) for item in group),
            "latency_ms": {
                "mean": round(mean(latency), 3),
                "p50_nearest_rank": _percentile(latency, 0.50),
                "p95_nearest_rank": _percentile(latency, 0.95),
            },
        }
    return result


def _validate_record(record: Mapping[str, Any]) -> None:
    required = set(adapter_contract._adapter_output_schema()["required"])
    if set(record) != required:
        raise LmeV2SmokeError("adapter output record fields differ from candidate.4 Schema")
    arm = str(record["arm"])
    if (
        record["planned_model_rounds"] != adapter_contract.PLANNED_MODEL_ROUNDS[arm]
        or record["planned_mcp_calls"] != adapter_contract.PLANNED_MCP_CALLS[arm]
        or len(record["native_calls"]) != 1
        or record["usage"]["hidden_or_extra_model_calls"] != 0
    ):
        raise LmeV2SmokeError("adapter output record violates arm accounting")


def run_smoke(
    *,
    dataset_lock_path: Path,
    adapter_report_path: Path,
    calibration_plan_path: Path,
    longmemeval_v2_root: Path,
    qa_evaluator_path: Path,
    case_limit: int,
    requested_case_ids: Sequence[str] | None,
    arms: Sequence[str],
    client: dev_smoke.CompletionClient,
    superseded_attempt_receipt_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = datetime.now(UTC)
    requested_arms = tuple(arms)
    superseded_attempt = (
        _load_superseded_attempt_receipt(superseded_attempt_receipt_path.resolve())
        if superseded_attempt_receipt_path is not None
        else {"status": "NOT_BOUND_TEST_OR_LIBRARY_INVOCATION"}
    )
    if (
        not requested_arms
        or len(set(requested_arms)) != len(requested_arms)
        or any(arm not in (*SUPPORTED_ARMS, "MILAI_MCP") for arm in requested_arms)
    ):
        raise LmeV2SmokeError("requested smoke arms are invalid")
    if "MILAI_MCP" in requested_arms:
        raise LmeV2SmokeError("MILAI_MCP is not implemented by the V2 two-arm smoke")
    try:
        adapter, calibration = dev_smoke._load_contracts(
            adapter_report_path.resolve(), calibration_plan_path.resolve()
        )
    except dev_smoke.DevSmokeError as exc:
        raise LmeV2SmokeError(str(exc)) from exc
    dataset_lock = _load_dataset_lock(
        dataset_lock_path.resolve(), adapter, calibration
    )
    cases, dataset_evidence = _load_cases(
        root=longmemeval_v2_root.resolve(),
        dataset_lock=dataset_lock,
        calibration=calibration,
        case_limit=case_limit,
        requested_case_ids=requested_case_ids,
    )
    evaluator, evaluator_sha256 = _load_evaluator(qa_evaluator_path.resolve())
    run_id = f"dg10-lme-v2-dev-smoke-{DATE}-{uuid4().hex[:12]}"
    records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    native_ids: set[str] = set()
    for case in cases:
        scheduled = adapter_contract._latin_square_order(case.case_id)
        for arm in (item for item in scheduled if item in requested_arms):
            if arm == "NAIVE_RAG":
                raw_memory, evidence_ids = _retrieve(case)
                try:
                    memory, memory_tokens = dev_smoke._fit_memory(
                        client, case, raw_memory
                    )
                except dev_smoke.DevSmokeError as exc:
                    raise LmeV2SmokeError(str(exc)) from exc
            else:
                memory = ""
                memory_tokens = 0
                evidence_ids = []
            messages = dev_smoke._messages(case, memory)
            prompt_tokens = client.count_tokens(messages)
            if prompt_tokens > client.max_model_len:
                raise LmeV2SmokeError("V2 smoke prompt exceeds frozen vLLM max_model_len")
            request_key = f"{run_id}:{case.case_id}:{arm}"
            completion = client.complete(
                messages,
                request_key=request_key,
                expected_prompt_tokens=prompt_tokens,
            )
            if completion.native_request_id in native_ids:
                raise LmeV2SmokeError("duplicate native vLLM request ID")
            native_ids.add(completion.native_request_id)
            parsed = dev_smoke._parse_answer(completion.text)
            score = _score(
                evaluator,
                eval_function=case.eval_function,
                prediction=parsed,
                answer=case.answer,
            )
            usage = {
                "input_tokens": int(completion.usage["input_tokens"] or 0),
                "output_tokens": int(completion.usage["output_tokens"] or 0),
                "model_rounds": 1,
                "mcp_rounds": 0,
                "hidden_or_extra_model_calls": 0,
            }
            record = {
                "run_id": run_id,
                "case_id": case.case_id,
                "source_case_id": case.source_case_id,
                "dataset": case.dataset,
                "category": case.category,
                "arm": arm,
                "model_id": dev_smoke.MODEL_ID,
                "planned_model_rounds": adapter_contract.PLANNED_MODEL_ROUNDS[arm],
                "planned_mcp_calls": adapter_contract.PLANNED_MCP_CALLS[arm],
                "native_calls": [
                    {
                        "native_request_id": completion.native_request_id,
                        "model_id": dev_smoke.MODEL_ID,
                        "planned_role": "ANSWER",
                        "terminal": True,
                        "finish_reason": completion.finish_reason,
                        "usage": {
                            "input_tokens": usage["input_tokens"],
                            "output_tokens": usage["output_tokens"],
                        },
                        "latency_ms": round(completion.latency_ms, 3),
                        "native_receipt_sha256": completion.native_receipt_sha256,
                    }
                ],
                "status": (
                    "TERMINAL_LOCAL_VLLM_ADAPTED_TEXT_ONLY_OUTPUT_TRUNCATED"
                    if completion.finish_reason == "length"
                    else "TERMINAL_LOCAL_VLLM_ADAPTED_TEXT_ONLY_SMOKE"
                ),
                "usage": usage,
                "latency_ms": round(completion.latency_ms, 3),
                "prompt_sha256": dev_smoke._json_sha256(messages),
                "trace": {
                    "latin_square_order": list(scheduled),
                    "retrieval": "NONE" if arm == "NO_MEMORY" else "LOCAL_LEXICAL_TEXT_CHUNK_V1",
                    "retrieval_k": 0 if arm == "NO_MEMORY" else RETRIEVAL_K,
                    "retrieved_evidence_ids": evidence_ids,
                    "retrieved_evidence_ids_sha256": dev_smoke._json_sha256(evidence_ids),
                    "memory_context_sha256": dev_smoke._sha256_bytes(memory.encode()),
                    "memory_context_tokens_attribution": memory_tokens,
                    "question_image_used": False,
                    "trajectory_screenshot_used": False,
                    "mcp_called": False,
                    "hidden_or_extra_model_calls": 0,
                },
                "answer_record": {
                    "gold_answer_sha256": dev_smoke._sha256_bytes(case.answer.encode()),
                    "raw_model_output_sha256": dev_smoke._sha256_bytes(
                        completion.text.encode()
                    ),
                    "parsed_answer_sha256": dev_smoke._sha256_bytes(parsed.encode()),
                    "raw_question_in_report": False,
                    "raw_gold_answer_in_report": False,
                    "raw_model_output_in_report": False,
                    "output_truncated": completion.finish_reason == "length",
                    **score,
                },
            }
            _validate_record(record)
            records.append(record)
            raw_records.append(
                {
                    "case_id": case.case_id,
                    "source_case_id": case.source_case_id,
                    "dataset": case.dataset,
                    "category": case.category,
                    "domain": case.domain,
                    "arm": arm,
                    "question": case.question,
                    "gold_answer": case.answer,
                    "eval_function": case.eval_function,
                    "memory_context": memory,
                    "retrieved_evidence_ids": evidence_ids,
                    "messages": messages,
                    "raw_model_output": completion.text,
                    "parsed_answer": parsed,
                }
            )
    ended = datetime.now(UTC)
    expected_records = len(cases) * len(requested_arms)
    if len(records) != expected_records or len(native_ids) != expected_records:
        raise LmeV2SmokeError("V2 smoke denominator or native-ID coverage failed")
    deterministic_case_count = sum(
        case.eval_function.split("|", 1)[0] in DETERMINISTIC_EVAL_NAMES
        for case in cases
    )
    report = {
        "schema": "milai.dg10.benchmark-lme-v2-dev-smoke.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "run_id": run_id,
        "status": "LME_V2_ADAPTED_TEXT_ONLY_TWO_ARM_DEV_SMOKE_COMPLETE_NOT_CALIBRATION",
        "quality_outcome": "CHARACTERIZED_ONLY",
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "data_boundary": "PUBLIC_DEV_LABELS_OPENED_RAW_CONTENT_REPO_EXTERNAL_HASHED_ONLY",
        "calibration_dev_labels_opened": True,
        "test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "local_vllm_requests": len(records),
        "local_tokenizer_requests": client.tokenizer_requests,
        "unique_native_request_ids": len(native_ids),
        "hidden_or_extra_model_calls": 0,
        "model_id": dev_smoke.MODEL_ID,
        "identity": dict(client.identity_evidence),
        "superseded_failed_attempt": superseded_attempt,
        "inputs": {
            "dataset_lock_report_sha256": dev_smoke._sha256_file(
                dataset_lock_path.resolve()
            ),
            "adapter_report_sha256": dev_smoke._sha256_file(
                adapter_report_path.resolve()
            ),
            "adapter_contract_canonical_sha256": dev_smoke._json_sha256(adapter),
            "calibration_plan_sha256": dev_smoke._sha256_file(
                calibration_plan_path.resolve()
            ),
            "qa_evaluator_sha256": evaluator_sha256,
            "dataset": dataset_evidence,
        },
        "execution": {
            "selected_dev_case_count": len(cases),
            "selected_dev_case_ids": [case.case_id for case in cases],
            "selected_dev_case_ids_sha256": dev_smoke._json_sha256(
                [case.case_id for case in cases]
            ),
            "arms_executed": list(requested_arms),
            "records": len(records),
            "records_per_case": len(requested_arms),
            "retrieval_unit": "TRAJECTORY_TEXT_STATE_CHUNK",
            "retrieval_k_smoke_candidate": RETRIEVAL_K,
            "memory_context_tokens_max": dev_smoke.MAX_MEMORY_CONTEXT_TOKENS,
            "generation_contract_sha256": adapter["generation_contract_sha256"],
            "prompt_templates_sha256": adapter["prompt_templates_sha256"],
            "latin_square_dev_schedule_sha256": calibration["schedule"][
                "dev_case_arm_schedule_sha256"
            ],
        },
        "adapted_protocol": {
            "claim_label": "ADAPTED_PROTOCOL_ONLY_NOT_LEADERBOARD",
            "information_loss": "LOSSY_RELATIVE_TO_OFFICIAL_FULL_SMALL",
            "question_text_used": True,
            "question_images_used": False,
            "trajectory_text_fields_used": [
                "goal",
                "outcome",
                "start_url",
                "state.url",
                "state.thought",
                "state.action",
                "state.accessibility_tree",
            ],
            "trajectory_screenshots_used": False,
            "official_full_small_claim": False,
            "leaderboard_claim": False,
        },
        "scoring": {
            "selected_case_count": len(cases),
            "official_local_deterministic_case_count": deterministic_case_count,
            "adapted_fallback_case_count": len(cases) - deterministic_case_count,
            "external_llm_judge_calls": 0,
            "denominators_separated": True,
        },
        "records": records,
        "aggregates": _aggregates(records),
        "repo_external_sidecar": {
            "status": "PENDING_BIND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        },
        "gate_results": {
            "BMG-02": "NO_GO_PARTIAL_DEV_SMOKE_NOT_THREE_ARM_CALIBRATION",
            "BMG-03": adapter["gate_results"]["BMG-03"],
            "BMG-05": "NO_GO_THRESHOLDS_NOT_FROZEN",
            "dev_smoke": "V2_ADAPTED_TEXT_ONLY_TWO_ARM_LOCAL_VLLM_COMPLETE",
        },
        "known_limits": [
            "This is a bounded two-arm V2 dev smoke, not the <=10% three-arm calibration.",
            "MILAI_MCP is not executed by this runner.",
            "Question and trajectory screenshots are omitted, so this is not official full-small or leaderboard-compatible evaluation.",
            "Cases whose official eval_function requires an LLM judge use separately reported adapted fallback metrics only.",
            "A terminal length response is retained, marked output_truncated, and scored as the observed capped output rather than retried.",
            "No threshold, retrieval k, aggregate token ceiling, test authorization, BMG-02, or BMG-05 gate is frozen or accepted.",
        ],
    }
    sidecar = {
        "schema": "milai.dg10.benchmark-lme-v2-dev-smoke-raw-sidecar.v1",
        "run_id": run_id,
        "created_at": ended.isoformat(),
        "data_classification": "PUBLIC_BENCHMARK_DEV_RAW_PROMPT_MEMORY_LABEL_AND_MODEL_OUTPUT",
        "repository_retention": "PROHIBITED_RAW_REPO_EXTERNAL_ONLY",
        "records": raw_records,
    }
    return report, sidecar


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a bounded two-arm DG-10 LongMemEval-V2 text-only dev smoke"
    )
    parser.add_argument("--execute-local-vllm", action="store_true")
    parser.add_argument("--data-boundary-ack")
    parser.add_argument("--dataset-lock", type=Path, default=DEFAULT_DATASET_LOCK)
    parser.add_argument("--adapter-report", type=Path, default=DEFAULT_ADAPTER_REPORT)
    parser.add_argument(
        "--calibration-plan", type=Path, default=DEFAULT_CALIBRATION_PLAN
    )
    parser.add_argument(
        "--longmemeval-v2-root", type=Path, default=DEFAULT_LONGMEMEVAL_V2_ROOT
    )
    parser.add_argument("--qa-evaluator", type=Path, default=DEFAULT_QA_EVALUATOR)
    parser.add_argument("--identity-report", type=Path, default=dev_smoke.IDENTITY_REPORT)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--case-limit", type=int, default=1)
    parser.add_argument("--case-ids", nargs="+")
    parser.add_argument("--arms", nargs="+", default=list(SUPPORTED_ARMS))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--superseded-attempt-receipt",
        type=Path,
        default=DEFAULT_SUPERSEDED_ATTEMPT_RECEIPT,
    )
    args = parser.parse_args()
    if (
        not args.execute_local_vllm
        or args.data_boundary_ack != dev_smoke.DATA_BOUNDARY_ACK
    ):
        raise LmeV2SmokeError(
            "real model calls require --execute-local-vllm and exact --data-boundary-ack"
        )
    try:
        capture_directory = dev_smoke._validate_capture_directory(
            args.capture_directory
        )
        client = dev_smoke.LocalVllmClient(
            args.base_url, args.identity_report, args.timeout
        )
    except dev_smoke.DevSmokeError as exc:
        raise LmeV2SmokeError(str(exc)) from exc
    report, sidecar = run_smoke(
        dataset_lock_path=args.dataset_lock,
        adapter_report_path=args.adapter_report,
        calibration_plan_path=args.calibration_plan,
        longmemeval_v2_root=args.longmemeval_v2_root,
        qa_evaluator_path=args.qa_evaluator,
        case_limit=args.case_limit,
        requested_case_ids=args.case_ids,
        arms=args.arms,
        client=client,
        superseded_attempt_receipt_path=args.superseded_attempt_receipt,
    )
    sidecar_raw = dev_smoke._encoded_json(sidecar)
    sidecar_path = capture_directory / f"{report['run_id']}.raw.json"
    dev_smoke._write_new(sidecar_path, sidecar_raw)
    report["repo_external_sidecar"] = {
        "status": "WRITTEN_HASH_BOUND",
        "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        "sha256": dev_smoke._sha256_bytes(sidecar_raw),
        "size": len(sidecar_raw),
        "mode": "0600",
    }
    report_raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), report_raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": dev_smoke._sha256_bytes(report_raw),
                "sidecar": str(sidecar_path),
                "sidecar_sha256": dev_smoke._sha256_bytes(sidecar_raw),
                "status": report["status"],
                "local_vllm_requests": report["local_vllm_requests"],
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
