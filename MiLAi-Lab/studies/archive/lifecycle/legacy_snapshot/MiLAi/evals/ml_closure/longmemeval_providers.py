"""Separated answer and official-semantics judge lanes for LongMemEval."""

from __future__ import annotations

import ast
import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from evals.dg14.provider import MatchedVllmProvider, ReaderConformanceError
from evals.paper.datasets.longmemeval import labels_from_dataset, load_inputs
from evals.paper.provider import _post_json

from .longmemeval_contexts import load_context_records
from .longmemeval_contract import (
    ANSWER_MAX_TOKENS,
    ANSWER_WORKERS,
    ARMS,
    CASE_COUNT,
    CHECKPOINT_ROOT,
    DATASET_PATH,
    INPUT_PATH,
    JUDGE_MAX_TOKENS,
    JUDGE_WORKERS,
    MEMORY_TOKEN_BUDGET,
    MODEL_ID,
    OFFICIAL_EVALUATOR,
    RUN_ID,
    SCHEMA_VERSION,
    VLLM_BASE_URL,
    LongMemEvalClosureError,
    atomic_json,
    canonical_json,
    case_seed,
    load_json,
    require_run_lock,
    sha256_file,
)


def _answer_path(arm: str, case_id: str) -> Path:
    return CHECKPOINT_ROOT / "full" / "answers" / arm / f"{case_id}.json"


def _judge_path(arm: str, case_id: str) -> Path:
    return CHECKPOINT_ROOT / "full" / "judges" / arm / f"{case_id}.json"


def _checkpoint(
    path: Path,
    *,
    expected_schema: str,
    arm: str,
    case_id: str,
    run_lock_digest: str,
) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = load_json(path)
    except LongMemEvalClosureError:
        return None
    if (
        not isinstance(value, dict)
        or value.get("schema") != expected_schema
        or value.get("arm") != arm
        or value.get("case_id") != case_id
        or value.get("run_lock_digest") != run_lock_digest
        or not isinstance(value.get("terminal_status"), str)
    ):
        return None
    return value


def _cell_key(value: Mapping[str, Any]) -> tuple[str, str]:
    return str(value["case_id"]), str(value["arm"])


def _records_digest(records: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(records, key=_cell_key)
    return hashlib.sha256(canonical_json(ordered)).hexdigest()


def _ambiguous_answer_terminal(
    context: Mapping[str, Any], *, run_lock_digest: str, path: Path
) -> dict[str, Any]:
    """Fail closed when a prior provider start cannot be disproved."""

    case_id, arm = _cell_key(context)
    reason = "provider checkpoint existed without a valid answer terminal"
    return {
        "schema": f"{SCHEMA_VERSION}.answer-terminal",
        "run_id": RUN_ID,
        "run_lock_digest": run_lock_digest,
        "case_id": case_id,
        "category": context["category"],
        "arm": arm,
        "terminal_status": "FAILED",
        "provider_called": True,
        "provider_start_ambiguous": True,
        "answer": "",
        "answer_sha256": hashlib.sha256(b"").hexdigest(),
        "context_sha256": context["context_sha256"],
        "seed": case_seed(case_id, "answer"),
        "wall_ms": 0.0,
        "prompt_tokens": 0,
        "memory_tokens": 0,
        "completion_tokens": 0,
        "failure_class": "AmbiguousProviderStartNoRetry",
        "failure_message_sha256": hashlib.sha256(reason.encode()).hexdigest(),
        "replaced_checkpoint_sha256": sha256_file(path),
    }


def _failure_metadata(error: Exception) -> dict[str, object]:
    result: dict[str, object] = {
        "failure_class": type(error).__name__,
        "failure_message_sha256": hashlib.sha256(str(error).encode()).hexdigest(),
    }
    if isinstance(error, ReaderConformanceError):
        result["reader_failure_class"] = error.failure_class
        result["reader_failure_metadata"] = dict(error.metadata)
    return result


def _answer_one(
    context: Mapping[str, Any],
    *,
    question: str,
    question_at: str,
    provider: MatchedVllmProvider,
    run_lock_digest: str,
) -> dict[str, Any]:
    arm = str(context["arm"])
    case_id = str(context["case_id"])
    path = _answer_path(arm, case_id)
    started = time.perf_counter()
    if context.get("terminal_status") != "SUCCEEDED":
        record = {
            "schema": f"{SCHEMA_VERSION}.answer-terminal",
            "run_id": RUN_ID,
            "run_lock_digest": run_lock_digest,
            "case_id": case_id,
            "category": context["category"],
            "arm": arm,
            "terminal_status": "NOT_CALLED_CONTEXT_TERMINAL",
            "provider_called": False,
            "answer": "",
            "answer_sha256": hashlib.sha256(b"").hexdigest(),
            "context_sha256": context["context_sha256"],
            "seed": case_seed(case_id, "answer"),
            "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
            "prompt_tokens": 0,
            "memory_tokens": 0,
            "completion_tokens": 0,
        }
        atomic_json(path, record)
        return record
    reservation = {
        "schema": f"{SCHEMA_VERSION}.answer-reservation",
        "run_id": RUN_ID,
        "run_lock_digest": run_lock_digest,
        "case_id": case_id,
        "arm": arm,
        "status": "PROVIDER_STARTED",
        "context_sha256": context["context_sha256"],
        "provider_called": True,
    }
    atomic_json(path, reservation)
    try:
        result = provider.answer(
            run_id=RUN_ID,
            case_id=case_id,
            method_id=arm,
            question=question,
            question_as_of=question_at,
            memory_context=str(context["context"]),
            token_budget=MEMORY_TOKEN_BUDGET,
            sampling_seed=case_seed(case_id, "answer"),
            exact_context=True,
        )
        record = {
            "schema": f"{SCHEMA_VERSION}.answer-terminal",
            "run_id": RUN_ID,
            "run_lock_digest": run_lock_digest,
            "case_id": case_id,
            "category": context["category"],
            "arm": arm,
            "terminal_status": "SUCCEEDED",
            "provider_called": True,
            "answer": result.answer,
            "answer_sha256": result.answer_sha256,
            "context_sha256": context["context_sha256"],
            "prompt_sha256": result.prompt_sha256,
            "seed": result.seed,
            "native_request_id": result.native_request_id,
            "finish_reason": result.finish_reason,
            "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
            "tokenize_ms": round(result.tokenize_latency_ms, 6),
            "provider_ms": round(result.provider_latency_ms, 6),
            "tokenizer_calls": result.tokenizer_calls,
            "prompt_tokens": result.prompt_tokens,
            "memory_tokens": result.memory_tokens,
            "completion_tokens": result.completion_tokens,
            "content_sha256": result.content_sha256,
            "content_byte_length": result.content_byte_length,
            "response_schema_sha256": result.response_schema_sha256,
            "context_truncated": result.context_truncated,
        }
    except Exception as exc:  # noqa: BLE001 - one attempt becomes a terminal
        record = {
            "schema": f"{SCHEMA_VERSION}.answer-terminal",
            "run_id": RUN_ID,
            "run_lock_digest": run_lock_digest,
            "case_id": case_id,
            "category": context["category"],
            "arm": arm,
            "terminal_status": "FAILED",
            "provider_called": True,
            "answer": "",
            "answer_sha256": hashlib.sha256(b"").hexdigest(),
            "context_sha256": context["context_sha256"],
            "seed": case_seed(case_id, "answer"),
            "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
            "prompt_tokens": 0,
            "memory_tokens": 0,
            "completion_tokens": 0,
            **_failure_metadata(exc),
        }
    atomic_json(path, record)
    return record


def run_answers() -> dict[str, Any]:
    """Seal all contexts, then issue at most one answer call per matched cell."""

    run_lock = require_run_lock()
    run_lock_digest = str(run_lock["run_lock_digest"])
    if (CHECKPOINT_ROOT / "full/labels-opened.json").exists():
        seal, _records = _validated_answer_seal(run_lock_digest)
        return seal
    contexts = load_context_records("full")
    if len(contexts) != CASE_COUNT * len(ARMS):
        raise LongMemEvalClosureError("answer context denominator is incomplete")
    _partition, cases = load_inputs(INPUT_PATH)
    case_by_id = {case.source_id: case for case in cases}
    terminal_schema = f"{SCHEMA_VERSION}.answer-terminal"
    complete: dict[tuple[str, str], Mapping[str, Any]] = {}
    pending: list[Mapping[str, Any]] = []
    for context in contexts:
        case_id, arm = _cell_key(context)
        path = _answer_path(arm, case_id)
        prior = _checkpoint(
            path,
            expected_schema=terminal_schema,
            arm=arm,
            case_id=case_id,
            run_lock_digest=run_lock_digest,
        )
        if prior is not None:
            complete[(case_id, arm)] = prior
        elif path.is_file():
            recovered = _ambiguous_answer_terminal(
                context, run_lock_digest=run_lock_digest, path=path
            )
            atomic_json(path, recovered)
            complete[(case_id, arm)] = recovered
        else:
            pending.append(context)
    provider = MatchedVllmProvider(
        base_url=VLLM_BASE_URL,
        max_output_tokens=ANSWER_MAX_TOKENS,
    )
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=ANSWER_WORKERS) as executor:
        futures = {}
        for pending_context in pending:
            case_id = str(pending_context["case_id"])
            case = case_by_id[case_id]
            future = executor.submit(
                _answer_one,
                pending_context,
                question=case.question,
                question_at=case.question_at,
                provider=provider,
                run_lock_digest=run_lock_digest,
            )
            futures[future] = _cell_key(pending_context)
        for future in as_completed(futures):
            complete[futures[future]] = future.result()
    expected = {(case.source_id, arm) for case in cases for arm in ARMS}
    if set(complete) != expected:
        raise LongMemEvalClosureError("answer lane did not terminalize every cell")
    ordered = [complete[(case_id, arm)] for case_id, arm in sorted(expected)]
    seal = {
        "schema": f"{SCHEMA_VERSION}.answer-seal",
        "run_id": RUN_ID,
        "run_lock_digest": run_lock_digest,
        "terminal_count": len(ordered),
        "provider_call_count": sum(
            record["provider_called"] is True for record in ordered
        ),
        "succeeded": sum(
            record["terminal_status"] == "SUCCEEDED" for record in ordered
        ),
        "failed": sum(record["terminal_status"] == "FAILED" for record in ordered),
        "context_terminal": sum(
            record["terminal_status"] == "NOT_CALLED_CONTEXT_TERMINAL"
            for record in ordered
        ),
        "workers": ANSWER_WORKERS,
        "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
        "records_digest": _records_digest(ordered),
        "labels_opened": False,
    }
    atomic_json(CHECKPOINT_ROOT / "full/answer-seal.json", seal)
    return seal


def load_answer_records() -> tuple[dict[str, Any], ...]:
    run_lock_digest = str(require_run_lock()["run_lock_digest"])
    _partition, cases = load_inputs(INPUT_PATH)
    result: list[dict[str, Any]] = []
    for case in sorted(cases, key=lambda value: value.source_id):
        for arm in ARMS:
            value = _checkpoint(
                _answer_path(arm, case.source_id),
                expected_schema=f"{SCHEMA_VERSION}.answer-terminal",
                arm=arm,
                case_id=case.source_id,
                run_lock_digest=run_lock_digest,
            )
            if value is None:
                raise LongMemEvalClosureError("answer terminal is missing")
            result.append(dict(value))
    return tuple(result)


def _validated_answer_seal(
    run_lock_digest: str,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    seal = load_json(CHECKPOINT_ROOT / "full/answer-seal.json")
    if (
        not isinstance(seal, dict)
        or seal.get("schema") != f"{SCHEMA_VERSION}.answer-seal"
        or seal.get("run_lock_digest") != run_lock_digest
        or seal.get("terminal_count") != CASE_COUNT * len(ARMS)
        or seal.get("labels_opened") is not False
    ):
        raise LongMemEvalClosureError("answers are not sealed before label access")
    records = load_answer_records()
    if seal.get("records_digest") != _records_digest(list(records)):
        raise LongMemEvalClosureError("answer seal digest differs from terminals")
    return dict(seal), records


def _official_prompt_function() -> Callable[..., str]:
    """Compile only the upstream prompt function, preserving its literal body."""

    source = OFFICIAL_EVALUATOR.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(OFFICIAL_EVALUATOR))
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_anscheck_prompt"
    ]
    if len(nodes) != 1:
        raise LongMemEvalClosureError("official judge prompt function is absent")
    module = ast.fix_missing_locations(
        ast.Module(body=cast(list[ast.stmt], nodes), type_ignores=[])
    )
    namespace: dict[str, Any] = {}
    exec(compile(module, str(OFFICIAL_EVALUATOR), "exec"), namespace)  # noqa: S102
    function = namespace.get("get_anscheck_prompt")
    if not callable(function):
        raise LongMemEvalClosureError("official judge prompt did not compile")
    return cast(Callable[..., str], function)


def _judge_one(
    answer: Mapping[str, Any],
    *,
    question: str,
    correct_answer: object,
    prompt_function: Callable[..., str],
    run_lock_digest: str,
) -> dict[str, Any]:
    arm = str(answer["arm"])
    case_id = str(answer["case_id"])
    path = _judge_path(arm, case_id)
    prompt = prompt_function(
        str(answer["category"]),
        question,
        correct_answer,
        str(answer["answer"]),
        abstention="_abs" in case_id,
    )
    prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
    atomic_json(
        path,
        {
            "schema": f"{SCHEMA_VERSION}.judge-reservation",
            "run_id": RUN_ID,
            "run_lock_digest": run_lock_digest,
            "case_id": case_id,
            "arm": arm,
            "status": "PROVIDER_STARTED",
            "prompt_sha256": prompt_sha256,
            "provider_called": True,
        },
    )
    started = time.perf_counter()
    try:
        cache_salt = hashlib.sha256(
            f"mlc-lme-judge:{RUN_ID}:{case_id}:{arm}".encode()
        ).hexdigest()
        response, headers = _post_json(
            VLLM_BASE_URL,
            "/v1/chat/completions",
            {
                "model": MODEL_ID,
                "messages": [{"role": "user", "content": prompt}],
                "n": 1,
                "temperature": 0,
                "top_p": 1,
                "max_tokens": JUDGE_MAX_TOKENS,
                "stream": False,
                "seed": case_seed(case_id, "judge"),
                "chat_template_kwargs": {"enable_thinking": False},
                "include_reasoning": False,
                "cache_salt": cache_salt,
            },
            timeout=240,
        )
        choices = response.get("choices")
        usage = response.get("usage")
        if (
            not isinstance(choices, list)
            or len(choices) != 1
            or not isinstance(choices[0], Mapping)
            or not isinstance(choices[0].get("message"), Mapping)
            or not isinstance(choices[0]["message"].get("content"), str)
            or not isinstance(usage, Mapping)
        ):
            raise LongMemEvalClosureError("judge response envelope is invalid")
        content = str(choices[0]["message"]["content"]).strip()
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if (
            not isinstance(prompt_tokens, int)
            or isinstance(prompt_tokens, bool)
            or not isinstance(completion_tokens, int)
            or isinstance(completion_tokens, bool)
        ):
            raise LongMemEvalClosureError("judge usage accounting is invalid")
        record = {
            "schema": f"{SCHEMA_VERSION}.judge-terminal",
            "run_id": RUN_ID,
            "run_lock_digest": run_lock_digest,
            "case_id": case_id,
            "category": answer["category"],
            "arm": arm,
            "terminal_status": "SUCCEEDED",
            "provider_called": True,
            "judge_correct": "yes" in content.lower(),
            "judge_response": content,
            "judge_response_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "prompt_sha256": prompt_sha256,
            "native_request_id": response.get("id") or headers.get("x-request-id"),
            "seed": case_seed(case_id, "judge"),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
        }
    except Exception as exc:  # noqa: BLE001 - one judge attempt becomes terminal
        record = {
            "schema": f"{SCHEMA_VERSION}.judge-terminal",
            "run_id": RUN_ID,
            "run_lock_digest": run_lock_digest,
            "case_id": case_id,
            "category": answer["category"],
            "arm": arm,
            "terminal_status": "FAILED",
            "provider_called": True,
            "judge_correct": False,
            "judge_response": "",
            "judge_response_sha256": hashlib.sha256(b"").hexdigest(),
            "prompt_sha256": prompt_sha256,
            "seed": case_seed(case_id, "judge"),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
            **_failure_metadata(exc),
        }
    atomic_json(path, record)
    return record


def _label_open_marker(
    *, run_lock_digest: str, answer_seal: Mapping[str, Any]
) -> dict[str, Any]:
    path = CHECKPOINT_ROOT / "full/labels-opened.json"
    expected = {
        "schema": f"{SCHEMA_VERSION}.label-open",
        "run_id": RUN_ID,
        "run_lock_digest": run_lock_digest,
        "purpose": "EXTERNAL_PUBLIC_BENCHMARK_JUDGE_AND_SCORING",
        "dataset_sha256": sha256_file(DATASET_PATH),
        "answer_seal_digest": answer_seal["records_digest"],
        "formal_holdout": "NOT_OPENED",
        "fields": ["answer", "answer_session_ids"],
    }
    if path.is_file():
        value = load_json(path)
        if (
            not isinstance(value, dict)
            or any(value.get(key) != item for key, item in expected.items())
            or value.get("status") not in {"OPEN_AUTHORIZED", "OPENED"}
            or not isinstance(value.get("opened_at"), str)
        ):
            raise LongMemEvalClosureError("label-open marker drifted")
        return dict(value)
    marker = {
        **expected,
        "status": "OPEN_AUTHORIZED",
        "opened_at": datetime.now(UTC).isoformat(),
    }
    atomic_json(path, marker)
    return marker


def _mark_labels_opened(marker: Mapping[str, Any]) -> dict[str, Any]:
    if marker.get("status") == "OPENED":
        return dict(marker)
    opened = {**dict(marker), "status": "OPENED"}
    atomic_json(CHECKPOINT_ROOT / "full/labels-opened.json", opened)
    return opened


def _judge_reference(label: Mapping[str, Any]) -> object:
    answers = label.get("answers")
    if not isinstance(answers, list) or not answers:
        raise LongMemEvalClosureError("judge answer label is invalid")
    return answers[0] if len(answers) == 1 else list(answers)


def _ambiguous_judge_terminal(
    answer: Mapping[str, Any],
    *,
    prompt_sha256: str,
    run_lock_digest: str,
    path: Path,
) -> dict[str, Any]:
    case_id, arm = _cell_key(answer)
    reason = "provider checkpoint existed without a valid judge terminal"
    return {
        "schema": f"{SCHEMA_VERSION}.judge-terminal",
        "run_id": RUN_ID,
        "run_lock_digest": run_lock_digest,
        "case_id": case_id,
        "category": answer["category"],
        "arm": arm,
        "terminal_status": "FAILED",
        "provider_called": True,
        "provider_start_ambiguous": True,
        "judge_correct": False,
        "judge_response": "",
        "judge_response_sha256": hashlib.sha256(b"").hexdigest(),
        "prompt_sha256": prompt_sha256,
        "seed": case_seed(case_id, "judge"),
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "wall_ms": 0.0,
        "failure_class": "AmbiguousProviderStartNoRetry",
        "failure_message_sha256": hashlib.sha256(reason.encode()).hexdigest(),
        "replaced_checkpoint_sha256": sha256_file(path),
    }


def run_judges() -> dict[str, Any]:
    """Open only scoring labels after the complete answer denominator is sealed."""

    run_lock = require_run_lock()
    run_lock_digest = str(run_lock["run_lock_digest"])
    answer_seal, answers = _validated_answer_seal(run_lock_digest)
    _partition, cases = load_inputs(INPUT_PATH)
    case_by_id = {case.source_id: case for case in cases}
    label_open = _label_open_marker(
        run_lock_digest=run_lock_digest, answer_seal=answer_seal
    )
    labels = labels_from_dataset(DATASET_PATH, tuple(case.source_id for case in cases))
    _mark_labels_opened(label_open)
    prompt_function = _official_prompt_function()
    terminal_schema = f"{SCHEMA_VERSION}.judge-terminal"
    complete: dict[tuple[str, str], Mapping[str, Any]] = {}
    pending: list[Mapping[str, Any]] = []
    for answer in answers:
        case_id, arm = _cell_key(answer)
        path = _judge_path(arm, case_id)
        prior = _checkpoint(
            path,
            expected_schema=terminal_schema,
            arm=arm,
            case_id=case_id,
            run_lock_digest=run_lock_digest,
        )
        if prior is not None:
            complete[(case_id, arm)] = prior
        elif path.is_file():
            prompt = prompt_function(
                str(answer["category"]),
                case_by_id[case_id].question,
                _judge_reference(labels[case_id]),
                str(answer["answer"]),
                abstention="_abs" in case_id,
            )
            recovered = _ambiguous_judge_terminal(
                answer,
                prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                run_lock_digest=run_lock_digest,
                path=path,
            )
            atomic_json(path, recovered)
            complete[(case_id, arm)] = recovered
        else:
            pending.append(answer)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=JUDGE_WORKERS) as executor:
        futures = {}
        for pending_answer in pending:
            case_id = str(pending_answer["case_id"])
            future = executor.submit(
                _judge_one,
                pending_answer,
                question=case_by_id[case_id].question,
                correct_answer=_judge_reference(labels[case_id]),
                prompt_function=prompt_function,
                run_lock_digest=run_lock_digest,
            )
            futures[future] = _cell_key(pending_answer)
        for future in as_completed(futures):
            complete[futures[future]] = future.result()
    expected = {(case.source_id, arm) for case in cases for arm in ARMS}
    if set(complete) != expected:
        raise LongMemEvalClosureError("judge lane did not terminalize every cell")
    ordered = [complete[(case_id, arm)] for case_id, arm in sorted(expected)]
    seal = {
        "schema": f"{SCHEMA_VERSION}.judge-seal",
        "run_id": RUN_ID,
        "run_lock_digest": run_lock_digest,
        "terminal_count": len(ordered),
        "provider_call_count": sum(
            record.get("provider_called") is True for record in ordered
        ),
        "succeeded": sum(
            record["terminal_status"] == "SUCCEEDED" for record in ordered
        ),
        "failed": sum(record["terminal_status"] == "FAILED" for record in ordered),
        "workers": JUDGE_WORKERS,
        "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
        "records_digest": _records_digest(ordered),
        "labels_opened_after_answer_seal": True,
        "official_prompt_source_sha256": sha256_file(OFFICIAL_EVALUATOR),
    }
    atomic_json(CHECKPOINT_ROOT / "full/judge-seal.json", seal)
    return seal


def load_judge_records() -> tuple[dict[str, Any], ...]:
    run_lock_digest = str(require_run_lock()["run_lock_digest"])
    _partition, cases = load_inputs(INPUT_PATH)
    result: list[dict[str, Any]] = []
    for case in sorted(cases, key=lambda value: value.source_id):
        for arm in ARMS:
            value = _checkpoint(
                _judge_path(arm, case.source_id),
                expected_schema=f"{SCHEMA_VERSION}.judge-terminal",
                arm=arm,
                case_id=case.source_id,
                run_lock_digest=run_lock_digest,
            )
            if value is None:
                raise LongMemEvalClosureError("judge terminal is missing")
            result.append(dict(value))
    return tuple(result)


__all__ = [
    "load_answer_records",
    "load_judge_records",
    "run_answers",
    "run_judges",
]
