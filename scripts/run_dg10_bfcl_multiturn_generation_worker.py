from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.agent_efficiency import vllm_local_ab
from scripts import dg10_bfcl_multiturn_safety as safety
from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_multiturn_contract as contract
from scripts import run_dg10_bfcl_prompt_capability_probe as prompt_probe

DATE = "2026-08-21"
BUNDLE_CANDIDATE = "candidate.12"
MODEL_EXECUTION_NAME = dev_smoke.MODEL_ID.replace("/", "_").replace(
    "-", "_"
).replace(".", "_")


class GenerationWorkerError(RuntimeError):
    pass


class GenerationStepError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        model_request_sent: bool,
        response_sha256: str | None = None,
        native_request_id: str | None = None,
    ) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.model_request_sent = model_request_sent
        self.response_sha256 = response_sha256
        self.native_request_id = native_request_id


@dataclass(frozen=True, slots=True)
class GenerationCompletion:
    native_request_id: str
    text: str
    usage: Mapping[str, int | None]
    latency_ms: float
    native_receipt_sha256: str
    response_sha256: str
    finish_reason: str


class GenerationLocalClient:
    def __init__(self, base_url: str, identity_report: Path, timeout: float) -> None:
        try:
            verified = dev_smoke.LocalVllmClient(base_url, identity_report, timeout)
        except dev_smoke.DevSmokeError as exc:
            raise GenerationWorkerError(str(exc)) from exc
        self.base_url = verified.base_url
        self.timeout = timeout
        self.max_model_len = verified.max_model_len
        self.identity_evidence = dict(verified.identity_evidence)
        self.tokenizer_requests = 0
        self.completion_requests = 0

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        request_key: str,
    ) -> GenerationCompletion:
        self.tokenizer_requests += 1
        try:
            prompt_tokens = vllm_local_ab._tokenize(
                self.base_url, messages, (), timeout=self.timeout
            )
        except vllm_local_ab.LocalVllmCaptureError as exc:
            raise GenerationStepError(
                "TOKENIZER_REQUEST_FAILURE", str(exc), model_request_sent=False
            ) from exc
        if prompt_tokens > self.max_model_len:
            raise GenerationStepError(
                "PROMPT_CONTEXT_LIMIT_PRE_REQUEST",
                f"prompt_tokens={prompt_tokens} max_model_len={self.max_model_len}",
                model_request_sent=False,
            )
        payload = {
            "model": dev_smoke.MODEL_ID,
            "messages": list(messages),
            "temperature": 0,
            "max_tokens": prompt_probe.MAX_OUTPUT_TOKENS,
            "stream": False,
            "seed": 20260821,
            "chat_template_kwargs": {"enable_thinking": False},
            "include_reasoning": False,
            "cache_salt": dev_smoke._sha256_bytes(
                f"dg10-bfcl-multiturn-generation:{request_key}".encode()
            ),
        }
        self.completion_requests += 1
        started = time.perf_counter()
        try:
            response, headers = vllm_local_ab._post_json(
                self.base_url,
                "/v1/chat/completions",
                payload,
                timeout=self.timeout,
            )
        except vllm_local_ab.LocalVllmCaptureError as exc:
            raise GenerationStepError(
                "COMPLETION_REQUEST_FAILURE", str(exc), model_request_sent=True
            ) from exc
        latency_ms = (time.perf_counter() - started) * 1000
        response_sha256 = dev_smoke._json_sha256(response)
        try:
            text, usage, native_id, receipt, finish_reason = (
                dev_smoke._validate_benchmark_completion(
                    response,
                    headers,
                    expected_prompt_tokens=prompt_tokens,
                    max_output_tokens=prompt_probe.MAX_OUTPUT_TOKENS,
                )
            )
        except vllm_local_ab.LocalVllmCaptureError as exc:
            native_id = response.get("id")
            raise GenerationStepError(
                "COMPLETION_VALIDATION_FAILURE",
                str(exc),
                model_request_sent=True,
                response_sha256=response_sha256,
                native_request_id=(native_id if isinstance(native_id, str) else None),
            ) from exc
        return GenerationCompletion(
            native_request_id=native_id,
            text=text,
            usage=usage,
            latency_ms=latency_ms,
            native_receipt_sha256=receipt,
            response_sha256=response_sha256,
            finish_reason=finish_reason,
        )

    def post_identity_check(self) -> Mapping[str, Any]:
        try:
            verified = dev_smoke.LocalVllmClient(
                self.base_url, dev_smoke.IDENTITY_REPORT, self.timeout
            )
        except dev_smoke.DevSmokeError as exc:
            raise GenerationWorkerError("post-case vLLM identity check failed") from exc
        post = dict(verified.identity_evidence)
        if post != self.identity_evidence:
            raise GenerationWorkerError("pre/post vLLM identity evidence drift")
        return post


class ExclusiveJournal:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        try:
            validated_parent = dev_smoke._validate_capture_directory(self.path.parent)
        except dev_smoke.DevSmokeError as exc:
            raise GenerationWorkerError(str(exc)) from exc
        validated_parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise GenerationWorkerError(
                f"cannot exclusively create journal: {self.path}"
            ) from exc
        os.fchmod(descriptor, 0o600)
        self._stream = os.fdopen(descriptor, "wb", buffering=0)
        self.entries = 0

    def append(self, value: Mapping[str, Any]) -> None:
        raw = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        self._stream.write(raw)
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self.entries += 1

    def close(self) -> None:
        self._stream.close()


def _load_bundle(path: Path, case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerationWorkerError(f"invalid generation bundle: {path}") from exc
    if (
        not isinstance(bundle, dict)
        or bundle.get("schema")
        != "milai.dg10.bfcl-multiturn-label-free-generation-bundle.v1"
        or bundle.get("candidate") != BUNDLE_CANDIDATE
        or bundle.get("selected_case_count") != 80
        or bundle.get("test_material_present") is not False
        or bundle.get("development_answer_labels_present") is not False
        or bundle.get("population", {}).get(
            "official_population_helper_invocation_count"
        )
        != 1
    ):
        raise GenerationWorkerError("generation bundle boundary mismatch")
    records = bundle.get("records")
    if not isinstance(records, list) or len(records) != 80:
        raise GenerationWorkerError("generation bundle record count mismatch")
    selected = [item for item in records if item.get("case_id") == case_id]
    if len(selected) != 1:
        raise GenerationWorkerError(f"case does not occur exactly once: {case_id}")
    record = selected[0]
    if not isinstance(record, dict):
        raise GenerationWorkerError("generation record must be an object")
    return bundle, record


def _official_executor(
    test_entry: Mapping[str, Any], bfcl_root: Path
) -> Callable[[Sequence[str]], Sequence[str]]:
    root_string = str(bfcl_root.resolve())
    inserted = root_string not in sys.path
    if inserted:
        sys.path.insert(0, root_string)
    try:
        module = importlib.import_module(
            "bfcl_eval.eval_checker.multi_turn_eval.multi_turn_utils"
        )
    except Exception as exc:
        raise GenerationWorkerError("cannot import official BFCL executor") from exc
    finally:
        if inserted:
            sys.path.remove(root_string)
    execute = module.execute_multi_turn_func_call
    initial_config = test_entry.get("initial_config", {})
    involved_classes = test_entry.get("involved_classes")
    source_id = test_entry.get("id")
    if (
        not isinstance(initial_config, dict)
        or not isinstance(involved_classes, list)
        or not isinstance(source_id, str)
    ):
        raise GenerationWorkerError("invalid populated test entry")
    test_category = source_id.rsplit("_", 1)[0]
    long_context = "long_context" in test_category or "composite" in test_category
    try:
        execute(
            [],
            initial_config,
            involved_classes,
            MODEL_EXECUTION_NAME,
            source_id,
            long_context=long_context,
            is_evaL_run=False,
        )
    except Exception as exc:
        raise GenerationWorkerError("official executor initialization failed") from exc

    def run(calls: Sequence[str]) -> Sequence[str]:
        results, _instances = execute(
            list(calls),
            initial_config,
            involved_classes,
            MODEL_EXECUTION_NAME,
            source_id,
            long_context=long_context,
            is_evaL_run=False,
        )
        return results

    return run


def _tool_result_message(calls: Sequence[str], results: Sequence[str]) -> str:
    if len(calls) != len(results):
        raise GenerationWorkerError("official executor result count mismatch")
    return repr(
        [
            {"role": "tool", "name": call, "content": result}
            for call, result in zip(calls, results, strict=True)
        ]
    )


def _validated_frozen_schedule(
    test_entry: Mapping[str, Any], frozen_schedule: Mapping[str, Any]
) -> dict[str, Any]:
    recomputed = safety.build_case_turn_schedule(
        test_entry,
        (
            "{functions}\nI have updated some more functions you can choose from. "
            "What about now?"
        ),
    )
    if (
        frozen_schedule.get("initial_function_names")
        != recomputed["initial_function_names"]
        or frozen_schedule.get("all_function_names")
        != recomputed["all_function_names"]
    ):
        raise GenerationWorkerError("frozen schedule function closure drifted")
    frozen_turns = frozen_schedule.get("turns")
    recomputed_turns = recomputed["turns"]
    if not isinstance(frozen_turns, list) or len(frozen_turns) != len(
        recomputed_turns
    ):
        raise GenerationWorkerError("frozen schedule turn count drifted")
    for frozen, current in zip(frozen_turns, recomputed_turns, strict=True):
        if not isinstance(frozen, dict):
            raise GenerationWorkerError("frozen turn must be an object")
        for key in (
            "turn_index",
            "revealed_function_names",
            "exposed_function_names",
        ):
            if frozen.get(key) != current[key]:
                raise GenerationWorkerError(f"frozen schedule {key} drifted")
        messages = frozen.get("effective_messages")
        if (
            not isinstance(messages, list)
            or frozen.get("effective_messages_sha256")
            != dev_smoke._json_sha256(messages)
        ):
            raise GenerationWorkerError("frozen effective-message hash drifted")
        revealed = frozen["revealed_function_names"]
        if not revealed:
            if messages != current["effective_messages"]:
                raise GenerationWorkerError("ordinary turn messages drifted")
            continue
        if (
            len(messages) != 1
            or not isinstance(messages[0], dict)
            or messages[0].get("role") != "user"
            or not isinstance(messages[0].get("content"), str)
        ):
            raise GenerationWorkerError("dynamic reveal message shape drifted")
        suffix = (
            "\nI have updated some more functions you can choose from. What about now?"
        )
        content = messages[0]["content"]
        if not content.endswith(suffix):
            raise GenerationWorkerError("dynamic reveal prompt suffix drifted")
        try:
            docs = ast.literal_eval(content[: -len(suffix)])
        except (SyntaxError, ValueError) as exc:
            raise GenerationWorkerError("dynamic reveal docs are not literals") from exc
        if (
            not isinstance(docs, list)
            or sorted(
                item.get("name") for item in docs if isinstance(item, dict)
            )
            != revealed
        ):
            raise GenerationWorkerError("dynamic reveal function names drifted")
    return dict(frozen_schedule)


def run_case(
    *,
    bundle_path: Path,
    case_id: str,
    bfcl_root: Path,
    client: Any,
    journal_append: Callable[[Mapping[str, Any]], None],
    executor_override: Callable[[Sequence[str]], Sequence[str]] | None = None,
) -> dict[str, Any]:
    started = datetime.now(UTC)
    bundle, record = _load_bundle(bundle_path.resolve(), case_id)
    test_entry = record.get("test_entry")
    frozen_schedule = record.get("turn_schedule")
    if not isinstance(test_entry, dict) or not isinstance(frozen_schedule, dict):
        raise GenerationWorkerError("invalid label-free generation record")
    prompt_utils, decoder_sha256 = prompt_probe._load_official_prompt_utils(
        bfcl_root.resolve()
    )
    schedule = _validated_frozen_schedule(test_entry, frozen_schedule)
    initial_functions = test_entry.get("function")
    if not isinstance(initial_functions, list):
        raise GenerationWorkerError("initial function docs are absent")
    system_prompt = (
        prompt_utils.formulate_system_prompt(
            prompt_utils.DEFAULT_SYSTEM_PROMPT_FORMAT, initial_functions
        )
        + contract.SAFETY_PROMPT_SUFFIX
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt}
    ]
    executor = executor_override or _official_executor(test_entry, bfcl_root.resolve())
    decoder = prompt_utils.default_decode_execute_prompting
    native_records: list[dict[str, Any]] = []
    decoded_by_turn: list[list[list[str]]] = []
    case_failure_code: str | None = None
    request_failures: list[dict[str, Any]] = []
    evidence_complete = True
    completed_turns = 0
    for turn in schedule["turns"]:
        turn_index = turn["turn_index"]
        effective_messages = turn["effective_messages"]
        if not isinstance(effective_messages, list):
            raise GenerationWorkerError("effective turn messages must be a list")
        messages.extend(effective_messages)
        exposed = frozenset(turn["exposed_function_names"])
        machine = safety.SafeTurnStateMachine(exposed, decoder, executor)
        decoded_steps: list[list[str]] = []
        while not machine.complete and machine.failure_code is None:
            request_messages_sha256 = dev_smoke._json_sha256(messages)
            try:
                completion = client.complete(
                    messages,
                    request_key=(
                        f"dg10-bfcl-multiturn-generation:{case_id}:"
                        f"{turn_index}:{len(machine.records)}"
                    ),
                )
            except GenerationStepError as exc:
                failure = {
                    "schema": "milai.dg10.bfcl-multiturn-request-failure-journal.v1",
                    "case_id": case_id,
                    "turn_index": turn_index,
                    "native_step_index": len(machine.records),
                    "request_messages": list(messages),
                    "request_messages_sha256": request_messages_sha256,
                    "failure_code": exc.code,
                    "failure_detail": exc.detail,
                    "model_request_sent": exc.model_request_sent,
                    "response_sha256": exc.response_sha256,
                    "native_request_id": exc.native_request_id,
                }
                journal_append(failure)
                request_failures.append(
                    {
                        key: value
                        for key, value in failure.items()
                        if key not in {"request_messages", "failure_detail"}
                    }
                )
                case_failure_code = exc.code
                if exc.model_request_sent:
                    evidence_complete = False
                break
            native_receipt = {
                "native_request_id": completion.native_request_id,
                "usage": dict(completion.usage),
                "latency_ms": round(completion.latency_ms, 3),
                "native_receipt_sha256": completion.native_receipt_sha256,
                "response_sha256": completion.response_sha256,
                "finish_reason": getattr(completion, "finish_reason", "stop"),
            }
            outcome = machine.process_native_step(completion.text, native_receipt)
            if "canonical_calls" in outcome:
                decoded_steps.append(list(outcome["decoded_execution_calls"]))
            raw_record = {
                "schema": "milai.dg10.bfcl-multiturn-native-step-journal.v1",
                "case_id": case_id,
                "turn_index": turn_index,
                "native_step_index": outcome["native_step_index"],
                "request_messages": list(messages),
                "request_messages_sha256": request_messages_sha256,
                "response_text": completion.text,
                "response_text_sha256": dev_smoke._sha256_bytes(
                    completion.text.encode("utf-8")
                ),
                "native_receipt": native_receipt,
                "outcome": outcome,
            }
            journal_append(raw_record)
            redacted = {
                "turn_index": turn_index,
                "native_step_index": outcome["native_step_index"],
                "request_messages_sha256": request_messages_sha256,
                "response_text_sha256": raw_record["response_text_sha256"],
                "native_request_id": completion.native_request_id,
                "usage": dict(completion.usage),
                "latency_ms": round(completion.latency_ms, 3),
                "native_receipt_sha256": completion.native_receipt_sha256,
                "response_sha256": completion.response_sha256,
                "finish_reason": getattr(completion, "finish_reason", "stop"),
                "status": outcome["status"],
                "execution_permitted": outcome["execution_permitted"],
                "tool_results_emitted": outcome["tool_results_emitted"],
            }
            if machine.failure_code is not None:
                redacted["failure_code"] = machine.failure_code
            native_records.append(redacted)
            if machine.failure_code is not None:
                case_failure_code = machine.failure_code
                break
            if machine.complete:
                completed_turns += 1
                break
            execution_calls = decoded_steps[-1]
            tool_results = outcome["tool_results"]
            messages.append({"role": "assistant", "content": completion.text})
            messages.append(
                {
                    "role": "user",
                    "content": _tool_result_message(execution_calls, tool_results),
                }
            )
        decoded_by_turn.append(decoded_steps)
        if case_failure_code is not None:
            break
    identity_post: Mapping[str, Any] | str = "UNAVAILABLE_TEST_CLIENT"
    if hasattr(client, "post_identity_check"):
        identity_post = dict(client.post_identity_check())  # type: ignore[attr-defined]
    ended = datetime.now(UTC)
    native_ids = [item["native_request_id"] for item in native_records]
    if len(native_ids) != len(set(native_ids)):
        raise GenerationWorkerError("native request IDs are not unique within case")
    success = case_failure_code is None and completed_turns == len(schedule["turns"])
    completion_requests = int(getattr(client, "completion_requests", len(native_records)))
    if completion_requests != len(native_records) and not any(
        item.get("model_request_sent") is True for item in request_failures
    ):
        raise GenerationWorkerError("completion request accounting drift")
    return {
        "schema": "milai.dg10.bfcl-multiturn-generated-case.v1",
        "date": DATE,
        "case_id": case_id,
        "source_case_id": test_entry["id"],
        "category": test_entry["id"].rsplit("_", 1)[0],
        "status": "GENERATION_COMPLETE" if success else "GENERATION_FAILURE_LATCHED",
        "generation_success": success,
        "evidence_complete": evidence_complete,
        "failure_code": case_failure_code,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "test_material_opened": False,
        "development_answer_labels_opened": False,
        "bundle_sha256": dev_smoke._sha256_file(bundle_path.resolve()),
        "bundle_candidate": bundle["candidate"],
        "official_decoder_sha256": decoder_sha256,
        "system_prompt_sha256": dev_smoke._sha256_bytes(
            system_prompt.encode("utf-8")
        ),
        "turn_schedule_sha256": dev_smoke._json_sha256(schedule),
        "turns_planned": len(schedule["turns"]),
        "turns_completed": completed_turns,
        "native_model_requests": completion_requests,
        "validated_native_receipts": len(native_records),
        "tokenizer_requests": client.tokenizer_requests,
        "hidden_or_extra_model_calls": 0 if evidence_complete else "UNAVAILABLE",
        "retry_model_calls": 0,
        "unique_native_request_ids": len(native_ids),
        "input_tokens": sum(
            int(item["usage"].get("input_tokens") or 0) for item in native_records
        ),
        "output_tokens": sum(
            int(item["usage"].get("output_tokens") or 0) for item in native_records
        ),
        "identity_pre": dict(client.identity_evidence),
        "identity_post": identity_post,
        "native_records": native_records,
        "request_failures": request_failures,
        "decoded_execution_calls_by_turn": decoded_by_turn,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate one isolated BFCL multi-turn development case"
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument("--identity-report", type=Path, default=dev_smoke.IDENTITY_REPORT)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    journal = ExclusiveJournal(args.journal)
    try:
        client = GenerationLocalClient(
            args.base_url, args.identity_report, args.timeout
        )
        result = run_case(
            bundle_path=args.bundle,
            case_id=args.case_id,
            bfcl_root=args.bfcl_root,
            client=client,
            journal_append=journal.append,
        )
    finally:
        journal.close()
    result["journal"] = {
        "status": "WRITTEN_HASH_BOUND",
        "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        "sha256": dev_smoke._sha256_file(args.journal.resolve()),
        "size": args.journal.resolve().stat().st_size,
        "mode": "0600",
        "entry_count": journal.entries,
    }
    raw = dev_smoke._encoded_json(result)
    dev_smoke._write_new(args.output.resolve(), raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": dev_smoke._sha256_bytes(raw),
                "case_id": args.case_id,
                "status": result["status"],
                "native_model_requests": result["native_model_requests"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
