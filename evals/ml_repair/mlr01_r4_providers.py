"""Separated local-Qwen answer and judge windows for ML-R01 R4."""

from __future__ import annotations

import ast
import hashlib
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any, cast

from evals.dg14.provider import MatchedVllmProvider, ReaderConformanceError
from evals.ml_repair.mlr01_r4_contexts import load_context_records
from evals.ml_repair.mlr01_r4_contract import (
    ANSWER_MAX_TOKENS,
    ANSWER_WORKERS,
    ARMS,
    DATASET_PATH,
    JUDGE_MAX_TOKENS,
    JUDGE_WORKERS,
    MEMORY_TOKEN_BUDGET,
    MODEL_ID,
    OFFICIAL_EVALUATOR,
    R4_ROOT,
    RUN_ID,
    SCHEMA_VERSION,
    VLLM_BASE_URL,
    MLR01R4Error,
    answer_path,
    atomic_json,
    capability_seal_digest,
    case_seed,
    judge_path,
    load_json,
    records_sha256,
    require_stage_seal,
    sha256_file,
    stage_seal_path,
    target_cases,
    valid_terminal,
)
from evals.paper.datasets.longmemeval import labels_from_dataset
from evals.paper.provider import _post_json

PROVIDER_RUN_ID = f"{RUN_ID}-r4"
SEALED_CONTEXT_TOKEN_ACCOUNTING = False


def _failure_metadata(error: Exception) -> dict[str, object]:
    value: dict[str, object] = {
        "failure_class": type(error).__name__,
        "failure_message_sha256": hashlib.sha256(str(error).encode()).hexdigest(),
    }
    if isinstance(error, ReaderConformanceError):
        value["reader_failure_class"] = error.failure_class
        value["reader_failure_metadata"] = dict(error.metadata)
    return value


def _valid_answer(
    *, context: Mapping[str, Any], seal_digest: str
) -> Mapping[str, Any] | None:
    value = valid_terminal(
        answer_path(str(context["arm"]), str(context["case_id"])),
        schema_suffix="answer",
        arm=str(context["arm"]),
        case_id=str(context["case_id"]),
        seal_digest=seal_digest,
    )
    if value is None or value.get("context_sha256") != context.get("context_sha256"):
        return None
    return value


def _ambiguous_answer(
    *, context: Mapping[str, Any], seal_digest: str, replaced_sha256: str
) -> dict[str, Any]:
    reason = "provider reservation existed without a valid answer terminal"
    return {
        "schema": f"{SCHEMA_VERSION}.answer-terminal",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "case_id": context["case_id"],
        "category": context["category"],
        "arm": context["arm"],
        "terminal_status": "FAILED",
        "provider_called": True,
        "provider_start_ambiguous": True,
        "answer": "",
        "answer_sha256": hashlib.sha256(b"").hexdigest(),
        "context_sha256": context["context_sha256"],
        "seed": case_seed(str(context["case_id"]), "answer"),
        "prompt_tokens": 0,
        "memory_tokens": 0,
        "completion_tokens": 0,
        "wall_ms": 0.0,
        "failure_class": "AmbiguousProviderStartNoRetry",
        "failure_message_sha256": hashlib.sha256(reason.encode()).hexdigest(),
        "replaced_checkpoint_sha256": replaced_sha256,
    }


def _answer_one(
    context: Mapping[str, Any],
    *,
    question: str,
    question_at: str,
    provider: MatchedVllmProvider,
    seal_digest: str,
) -> dict[str, Any]:
    arm = str(context["arm"])
    case_id = str(context["case_id"])
    path = answer_path(arm, case_id)
    atomic_json(
        path,
        {
            "schema": f"{SCHEMA_VERSION}.answer-reservation",
            "run_id": RUN_ID,
            "capability_seal_digest": seal_digest,
            "case_id": case_id,
            "arm": arm,
            "status": "PROVIDER_STARTED",
            "context_sha256": context["context_sha256"],
            "provider_called": True,
        },
    )
    started = time.perf_counter()
    try:
        result = provider.answer(
            run_id=PROVIDER_RUN_ID,
            case_id=case_id,
            method_id=arm,
            question=question,
            question_as_of=question_at,
            memory_context=str(context["context"]),
            token_budget=MEMORY_TOKEN_BUDGET,
            sampling_seed=case_seed(case_id, "answer"),
            exact_context=True,
            sealed_context_tokens=(
                int(context["context_tokens"])
                if SEALED_CONTEXT_TOKEN_ACCOUNTING
                else None
            ),
        )
        record = {
            "schema": f"{SCHEMA_VERSION}.answer-terminal",
            "run_id": RUN_ID,
            "capability_seal_digest": seal_digest,
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
            "sealed_context_tokens": result.sealed_context_tokens,
            "template_boundary_tokens": result.template_boundary_tokens,
            "completion_tokens": result.completion_tokens,
            "content_sha256": result.content_sha256,
            "content_byte_length": result.content_byte_length,
            "response_schema_sha256": result.response_schema_sha256,
            "context_truncated": result.context_truncated,
            "thinking_enabled": False,
            "max_output_tokens": ANSWER_MAX_TOKENS,
        }
    except Exception as exc:  # noqa: BLE001 - one model call becomes terminal
        record = {
            "schema": f"{SCHEMA_VERSION}.answer-terminal",
            "run_id": RUN_ID,
            "capability_seal_digest": seal_digest,
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
            "thinking_enabled": False,
            "max_output_tokens": ANSWER_MAX_TOKENS,
            **_failure_metadata(exc),
        }
    atomic_json(path, record)
    return record


def load_answer_records(target_count: int) -> tuple[dict[str, Any], ...]:
    seal_digest = capability_seal_digest()
    contexts = load_context_records(target_count)
    result: list[dict[str, Any]] = []
    for context in contexts:
        value = _valid_answer(context=context, seal_digest=seal_digest)
        if value is None:
            raise MLR01R4Error(
                f"R4 answer terminal is missing: {context['case_id']}/{context['arm']}"
            )
        result.append(dict(value))
    return tuple(result)


def run_answers(target_count: int) -> dict[str, Any]:
    seal_path = stage_seal_path("answer", target_count)
    if seal_path.is_file():
        return require_stage_seal("answer", target_count)
    context_seal = require_stage_seal("context", target_count)
    seal_digest = capability_seal_digest()
    contexts = load_context_records(target_count)
    if context_seal.get("records_digest") != records_sha256(contexts):
        raise MLR01R4Error("R4 context records drifted after their seal")
    case_by_id = {case.source_id: case for case in target_cases(target_count)}
    complete: dict[tuple[str, str], Mapping[str, Any]] = {}
    pending: list[Mapping[str, Any]] = []
    for context in contexts:
        key = str(context["case_id"]), str(context["arm"])
        path = answer_path(key[1], key[0])
        prior = _valid_answer(context=context, seal_digest=seal_digest)
        if prior is not None:
            complete[key] = prior
        elif path.is_file():
            record = _ambiguous_answer(
                context=context,
                seal_digest=seal_digest,
                replaced_sha256=sha256_file(path),
            )
            atomic_json(path, record)
            complete[key] = record
        else:
            pending.append(context)
    provider = MatchedVllmProvider(
        base_url=VLLM_BASE_URL, max_output_tokens=ANSWER_MAX_TOKENS
    )
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=ANSWER_WORKERS) as executor:
        futures = {}
        for pending_context in pending:
            case = case_by_id[str(pending_context["case_id"])]
            future = executor.submit(
                _answer_one,
                pending_context,
                question=case.question,
                question_at=case.question_at,
                provider=provider,
                seal_digest=seal_digest,
            )
            futures[future] = (
                str(pending_context["case_id"]),
                str(pending_context["arm"]),
            )
        for future in as_completed(futures):
            complete[futures[future]] = future.result()
    expected = {
        (case.source_id, arm) for case in target_cases(target_count) for arm in ARMS
    }
    if set(complete) != expected:
        raise MLR01R4Error("R4 answer lane did not terminalize every cell")
    records = [complete[key] for key in sorted(expected)]
    succeeded = sum(record.get("terminal_status") == "SUCCEEDED" for record in records)
    labels_marker_exists = (R4_ROOT / "labels-opened.json").exists()
    value = {
        "schema": f"{SCHEMA_VERSION}.answer-seal",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "target_count": target_count,
        "terminal_count": len(records),
        "status": "PASS" if succeeded == len(records) else "FAIL",
        "succeeded": succeeded,
        "failed": len(records) - succeeded,
        "new_provider_calls": len(pending),
        "provider_call_count_total": sum(
            record.get("provider_called") is True for record in records
        ),
        "workers": ANSWER_WORKERS,
        "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
        "records_digest": records_sha256(records),
        "context_records_digest": context_seal["records_digest"],
        "labels_opened_before_stage": labels_marker_exists,
        "label_fields_accessed_by_answer_code": False,
        "full_500_order_presealed_before_first_label_open": True,
        "max_output_tokens": ANSWER_MAX_TOKENS,
        "thinking_enabled": False,
    }
    atomic_json(stage_seal_path("answer", target_count), value)
    return value


def _official_prompt_function() -> Callable[..., str]:
    source = OFFICIAL_EVALUATOR.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(OFFICIAL_EVALUATOR))
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_anscheck_prompt"
    ]
    if len(nodes) != 1:
        raise MLR01R4Error("upstream get_anscheck_prompt is absent")
    module = ast.fix_missing_locations(
        ast.Module(body=cast(list[ast.stmt], nodes), type_ignores=[])
    )
    namespace: dict[str, Any] = {}
    exec(compile(module, str(OFFICIAL_EVALUATOR), "exec"), namespace)  # noqa: S102
    function = namespace.get("get_anscheck_prompt")
    if not callable(function):
        raise MLR01R4Error("upstream get_anscheck_prompt did not compile")
    return cast(Callable[..., str], function)


def _judge_reference(label: Mapping[str, Any]) -> object:
    answers = label.get("answers")
    if not isinstance(answers, list) or not answers:
        raise MLR01R4Error("LongMemEval judge reference is invalid")
    return answers[0] if len(answers) == 1 else list(answers)


def _valid_judge(
    *, answer: Mapping[str, Any], seal_digest: str, expected_prompt_sha256: str
) -> Mapping[str, Any] | None:
    value = valid_terminal(
        judge_path(str(answer["arm"]), str(answer["case_id"])),
        schema_suffix="judge",
        arm=str(answer["arm"]),
        case_id=str(answer["case_id"]),
        seal_digest=seal_digest,
    )
    if (
        value is None
        or value.get("answer_sha256") != answer.get("answer_sha256")
        or value.get("prompt_sha256") != expected_prompt_sha256
    ):
        return None
    return value


def _judge_one(
    answer: Mapping[str, Any],
    *,
    prompt: str,
    prompt_sha256: str,
    seal_digest: str,
) -> dict[str, Any]:
    arm = str(answer["arm"])
    case_id = str(answer["case_id"])
    path = judge_path(arm, case_id)
    atomic_json(
        path,
        {
            "schema": f"{SCHEMA_VERSION}.judge-reservation",
            "run_id": RUN_ID,
            "capability_seal_digest": seal_digest,
            "case_id": case_id,
            "arm": arm,
            "status": "PROVIDER_STARTED",
            "prompt_sha256": prompt_sha256,
            "answer_sha256": answer["answer_sha256"],
            "provider_called": True,
        },
    )
    started = time.perf_counter()
    try:
        cache_salt = hashlib.sha256(
            f"mlr01-r4-judge:{RUN_ID}:{case_id}:{arm}".encode()
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
            raise MLR01R4Error("R4 judge response envelope is invalid")
        content = str(choices[0]["message"]["content"]).strip()
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if (
            not isinstance(prompt_tokens, int)
            or isinstance(prompt_tokens, bool)
            or not isinstance(completion_tokens, int)
            or isinstance(completion_tokens, bool)
        ):
            raise MLR01R4Error("R4 judge token usage is invalid")
        record = {
            "schema": f"{SCHEMA_VERSION}.judge-terminal",
            "run_id": RUN_ID,
            "capability_seal_digest": seal_digest,
            "case_id": case_id,
            "category": answer["category"],
            "arm": arm,
            "terminal_status": "SUCCEEDED",
            "provider_called": True,
            "judge_correct": "yes" in content.casefold(),
            "judge_response": content,
            "judge_response_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "prompt_sha256": prompt_sha256,
            "answer_sha256": answer["answer_sha256"],
            "native_request_id": response.get("id") or headers.get("x-request-id"),
            "seed": case_seed(case_id, "judge"),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
            "temperature": 0,
            "thinking_enabled": False,
            "max_output_tokens": JUDGE_MAX_TOKENS,
        }
    except Exception as exc:  # noqa: BLE001 - one model call becomes terminal
        record = {
            "schema": f"{SCHEMA_VERSION}.judge-terminal",
            "run_id": RUN_ID,
            "capability_seal_digest": seal_digest,
            "case_id": case_id,
            "category": answer["category"],
            "arm": arm,
            "terminal_status": "FAILED",
            "provider_called": True,
            "judge_correct": False,
            "judge_response": "",
            "judge_response_sha256": hashlib.sha256(b"").hexdigest(),
            "prompt_sha256": prompt_sha256,
            "answer_sha256": answer["answer_sha256"],
            "seed": case_seed(case_id, "judge"),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
            "temperature": 0,
            "thinking_enabled": False,
            "max_output_tokens": JUDGE_MAX_TOKENS,
            **_failure_metadata(exc),
        }
    atomic_json(path, record)
    return record


def _label_access_marker(
    *, target_count: int, answer_seal: Mapping[str, Any], seal_digest: str
) -> dict[str, Any]:
    first_path = R4_ROOT / "labels-opened.json"
    if not first_path.is_file():
        first = {
            "schema": f"{SCHEMA_VERSION}.labels-opened",
            "run_id": RUN_ID,
            "capability_seal_digest": seal_digest,
            "status": "OPENED",
            "first_target_count": target_count,
            "opened_at": datetime.now(UTC).isoformat(),
            "dataset_sha256": sha256_file(DATASET_PATH),
            "fields": ["answer", "answer_session_ids"],
            "full_500_source_order_presealed": True,
            "formal_holdout": False,
        }
        atomic_json(first_path, first)
    else:
        first = load_json(first_path)
        if (
            not isinstance(first, dict)
            or first.get("schema") != f"{SCHEMA_VERSION}.labels-opened"
            or first.get("capability_seal_digest") != seal_digest
            or first.get("dataset_sha256") != sha256_file(DATASET_PATH)
        ):
            raise MLR01R4Error("R4 label-open marker drifted")
    access = {
        "schema": f"{SCHEMA_VERSION}.label-access",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "target_count": target_count,
        "answer_seal_records_digest": answer_seal["records_digest"],
        "answer_terminal_count": answer_seal["terminal_count"],
        "dataset_sha256": sha256_file(DATASET_PATH),
        "fields": ["answer", "answer_session_ids"],
        "accessed_after_target_answer_seal": True,
        "formal_holdout": False,
    }
    atomic_json(R4_ROOT / f"label-access-{target_count}.json", access)
    return access


def load_judge_records(target_count: int) -> tuple[dict[str, Any], ...]:
    seal_digest = capability_seal_digest()
    answers = load_answer_records(target_count)
    result: list[dict[str, Any]] = []
    for answer in answers:
        path = judge_path(str(answer["arm"]), str(answer["case_id"]))
        value = load_json(path)
        if (
            not isinstance(value, dict)
            or value.get("schema") != f"{SCHEMA_VERSION}.judge-terminal"
            or value.get("capability_seal_digest") != seal_digest
            or value.get("case_id") != answer["case_id"]
            or value.get("arm") != answer["arm"]
            or value.get("answer_sha256") != answer["answer_sha256"]
            or value.get("terminal_status") not in {"SUCCEEDED", "FAILED"}
        ):
            raise MLR01R4Error("R4 judge terminal is missing or invalid")
        result.append(value)
    return tuple(result)


def run_judges(target_count: int) -> dict[str, Any]:
    seal_path = stage_seal_path("judge", target_count)
    if seal_path.is_file():
        return require_stage_seal("judge", target_count)
    answer_seal = require_stage_seal("answer", target_count)
    seal_digest = capability_seal_digest()
    answers = load_answer_records(target_count)
    if answer_seal.get("records_digest") != records_sha256(answers):
        raise MLR01R4Error("R4 answer records drifted after their seal")
    cases = target_cases(target_count)
    case_by_id = {case.source_id: case for case in cases}
    _label_access_marker(
        target_count=target_count, answer_seal=answer_seal, seal_digest=seal_digest
    )
    labels = labels_from_dataset(DATASET_PATH, tuple(case.source_id for case in cases))
    prompt_function = _official_prompt_function()
    complete: dict[tuple[str, str], Mapping[str, Any]] = {}
    pending: list[tuple[Mapping[str, Any], str, str]] = []
    for answer in answers:
        case_id = str(answer["case_id"])
        arm = str(answer["arm"])
        prompt = prompt_function(
            str(answer["category"]),
            case_by_id[case_id].question,
            _judge_reference(labels[case_id]),
            str(answer["answer"]),
            abstention="_abs" in case_id,
        )
        prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
        path = judge_path(arm, case_id)
        prior = _valid_judge(
            answer=answer,
            seal_digest=seal_digest,
            expected_prompt_sha256=prompt_sha256,
        )
        if prior is not None:
            complete[(case_id, arm)] = prior
        elif path.is_file():
            reason = "provider reservation existed without a valid judge terminal"
            record = {
                "schema": f"{SCHEMA_VERSION}.judge-terminal",
                "run_id": RUN_ID,
                "capability_seal_digest": seal_digest,
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
                "answer_sha256": answer["answer_sha256"],
                "seed": case_seed(case_id, "judge"),
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "wall_ms": 0.0,
                "failure_class": "AmbiguousProviderStartNoRetry",
                "failure_message_sha256": hashlib.sha256(reason.encode()).hexdigest(),
                "replaced_checkpoint_sha256": sha256_file(path),
            }
            atomic_json(path, record)
            complete[(case_id, arm)] = record
        else:
            pending.append((answer, prompt, prompt_sha256))
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=JUDGE_WORKERS) as executor:
        futures = {
            executor.submit(
                _judge_one,
                answer,
                prompt=prompt,
                prompt_sha256=prompt_sha256,
                seal_digest=seal_digest,
            ): (str(answer["case_id"]), str(answer["arm"]))
            for answer, prompt, prompt_sha256 in pending
        }
        for future in as_completed(futures):
            complete[futures[future]] = future.result()
    expected = {(case.source_id, arm) for case in cases for arm in ARMS}
    if set(complete) != expected:
        raise MLR01R4Error("R4 judge lane did not terminalize every cell")
    records = [complete[key] for key in sorted(expected)]
    succeeded = sum(record.get("terminal_status") == "SUCCEEDED" for record in records)
    value = {
        "schema": f"{SCHEMA_VERSION}.judge-seal",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "target_count": target_count,
        "terminal_count": len(records),
        "status": "PASS" if succeeded == len(records) else "FAIL",
        "succeeded": succeeded,
        "failed": len(records) - succeeded,
        "new_provider_calls": len(pending),
        "provider_call_count_total": sum(
            record.get("provider_called") is True for record in records
        ),
        "workers": JUDGE_WORKERS,
        "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
        "records_digest": records_sha256(records),
        "answer_records_digest": answer_seal["records_digest"],
        "official_prompt_source_sha256": sha256_file(OFFICIAL_EVALUATOR),
        "judge_temperature": 0,
        "max_output_tokens": JUDGE_MAX_TOKENS,
        "thinking_enabled": False,
        "labels_opened_after_target_answer_seal": True,
    }
    atomic_json(stage_seal_path("judge", target_count), value)
    return value


__all__ = [
    "load_answer_records",
    "load_judge_records",
    "run_answers",
    "run_judges",
]
