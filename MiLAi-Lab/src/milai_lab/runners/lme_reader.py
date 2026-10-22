"""Separate fixed Reader and LME scoring phases on the existing owned ledger/queue."""
from __future__ import annotations

import copy
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from milai_lab.datasets.lme_protocol import NativeLmeProtocol
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import (
    RunLimits,
    Trace,
    entry_budget,
    http_budget_scope,
)
from milai_lab.providers.chat_bridge import IncompleteChatResponse
from milai_lab.providers.contextual_capacity import CapacityExceeded, HostCapacity
from milai_lab.providers.contextual_vllm import VLLMConfig
from milai_lab.providers.functional_queue import FunctionalQueue, FunctionalVLLMClient
from milai_lab.providers.generation_admission import DurableGenerationAdmission
from milai_lab.runners.functional import frozen


def final_text(response: dict[str, Any]) -> str:
    """Actual final content only; unfinished reasoning is not an answer or a repaired retry."""
    choices = response["choices"]
    if len(choices) != 1 or choices[0]["finish_reason"] != "stop":
        raise IncompleteChatResponse("LME_INCOMPLETE_FINAL_RESPONSE")
    message = choices[0]["message"]
    if message["role"] != "assistant" or message.get("tool_calls"):
        raise IncompleteChatResponse("LME_EXPECTED_FINAL_ANSWER")
    content = message["content"]
    if isinstance(content, list):
        content = "\n".join(part["text"].strip() for part in content
                            if isinstance(part, dict) and isinstance(part.get("text"), str))
    if not isinstance(content, str) or not content.strip():
        raise IncompleteChatResponse("LME_EMPTY_FINAL_RESPONSE")
    return content.strip()


def run_completion(runtime: Path, output: Path, request: dict[str, Any],
                   capacity: HostCapacity, *, phase: str, source_version: str,
                   transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """One native request, same query queue and continuous ledger; no SDK retry or new service."""
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {"status": "RUNNING", "phase": phase,
        "source_version": source_version, "actual_http_attempts": 0, "automatic_retry": False,
        "http_usage_recorded_by_existing_client": True, "cpu_ledger_recorded": False}
    trace = Trace(output / "trace.jsonl", "lme_"+phase)
    budget = None

    def dispatched(event: dict[str, Any]) -> None:
        if event["event"] == "vllm_request":
            report["actual_http_attempts"] += 1
            trace(event)

    try:
        settings = frozen(runtime)["config"]
        if capacity.config != settings["capacity"]:
            raise ValueError("Completion capacity differs from the frozen runtime")
        host = VLLMConfig(**settings["host"])
        report["host"] = asdict(host)
        payload = copy.deepcopy(request)
        if payload.pop("timeout") != host.timeout:
            raise ValueError("Native evaluator timeout differs from the declared client")
        payload.update(payload.pop("extra_body", {}))
        payload.setdefault("chat_template_kwargs", {"enable_thinking": capacity.enable_thinking})
        write_json(output / "request.json", payload)
        limits = RunLimits(**read_json(Path(settings["budget_path"]))["limits"])
        configs = [asdict(host)]
        if "embedding" in settings:
            configs.append(asdict(VLLMConfig(**settings["embedding"])))
        with http_budget_scope(settings, limits, client_configs=configs):
            budget = entry_budget(limits, Path(settings["budget_path"]))
            report["budget_before"] = copy.deepcopy(budget.state)
            if phase == "reader":
                admission_path, = runtime.glob("banks/*/message-admission.json")
                entry, = read_json(admission_path)["messages"].values()
                identity = entry["identity"]
                admission = DurableGenerationAdmission(admission_path,
                    identity["public_message_id"], identity, asdict(host),
                    settings["max_calls_per_message"], "resume", 0)
                report["generation_calls_before"] = admission.count
                admission.reserve(asdict(host), settings["max_calls_per_message"],
                                  "lme_fixed_reader")
                report["generation_calls_after"] = admission.count
            else:
                report["admission_scope"] = (
                    "One offline Judge call; same queue/ledger, separate from Host task allowance")
            client = FunctionalVLLMClient(host, emit=trace, budget=budget, capacity=capacity,
                                         transport=transport)
            with client:
                client.queue = FunctionalQueue(runtime / "queue-admission.json",
                                               **settings["queue_limits"])
                response = client.native_post("chat/completions", payload, on_event=dispatched)
                write_json(output / "response.json", response)
                report.update(status="COMPLETED", response_text=final_text(response))
    except BaseException as error:
        report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        if isinstance(error, CapacityExceeded):
            report["capacity_rejection"] = error.receipt
        raise
    finally:
        report.update(cpu_seconds=time.process_time()-cpu,
                      wall_seconds=time.perf_counter()-started, usage=trace.usage)
        if budget is not None:
            report["budget_after"] = copy.deepcopy(budget.state)
        write_json(output / "call.json", report)
    return report


def predict_reader(runtime: Path, output: Path, protocol: NativeLmeProtocol,
                   capacity: HostCapacity, *, domain: str, query: str, query_image: str | None,
                   context: list[dict[str, str]], source_version: str,
                   transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """Public inputs only. No reference-answer or evaluation-spec argument exists here."""
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {"status": "RUNNING", "source_version": source_version,
        "runtime": str(runtime.resolve()), "query": query, "query_image": query_image,
        "domain": domain, "automatic_retry": False, "reference_accessed": False,
        "memory_context_truncated": False, "native_source_files": protocol.source_files}
    try:
        settings = frozen(runtime)["config"]
        wire, logged = protocol.messages(domain, query, query_image, context)
        write_json(output / "prompt.json", logged)
        write_json(output / "memory-context.json", context)
        call = run_completion(runtime, output / "reader", protocol.reader_request(
            wire, asdict(VLLMConfig(**settings["host"])), capacity.enable_thinking), capacity,
            phase="reader", source_version=source_version, transport=transport)
        parsed = protocol.metrics.extract_boxed_answer(call["response_text"])
        report.update(status="COMPLETED", response_raw=call["response_text"],
            response_parsed_boxed=parsed, is_unknown=protocol.metrics.is_unknown(parsed))
    except BaseException as error:
        report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        elapsed = time.process_time()-cpu
        call_cpu = (read_json(output/"reader/call.json")["cpu_seconds"]
                    if (output/"reader/call.json").exists() else 0.0)
        report.update(cpu_seconds_nested=elapsed, wall_seconds=time.perf_counter()-started,
            orchestration_cpu_seconds=elapsed-call_cpu, cpu_ledger_recorded=False,
            accounting="Exclusive prompt/preparation CPU excludes separately measured request CPU. "
                       "Whole-stage CPU and wall are nested. No remote compute time is invented.")
        write_json(output / "prediction.json", report)
    return report


def score_reader(prediction_root: Path, output: Path, question: dict[str, Any],
                 protocol: NativeLmeProtocol, capacity: HostCapacity, *, source_version: str,
                 transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """Offline scoring of a retained completed prediction; no Reader regeneration."""
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {"status": "RUNNING", "score": None,
        "source_version": source_version, "prediction_root": str(prediction_root),
        "reader_regenerated": False, "automatic_retry": False}
    try:
        prediction = read_json(prediction_root / "prediction.json")
        if prediction["status"] != "COMPLETED" or prediction["query"] != question["question"]:
            raise ValueError("Scoring needs a completed prediction for this exact public question")
        response = final_text(read_json(prediction_root / "reader/response.json"))
        if response != prediction["response_raw"]:
            raise ValueError("Scoring response differs from the retained actual Reader response")
        runtime = Path(prediction["runtime"])
        host = VLLMConfig(**frozen(runtime)["config"]["host"])
        write_json(output / "reference.json", question)

        def complete(request: dict[str, Any]) -> str:
            call = run_completion(runtime, output / "judge", request, capacity,
                phase="judge", source_version=source_version, transport=transport)
            return str(call["response_text"])

        options = {"evaluator_model": host.model, "evaluator_base_url": host.base_url,
            "evaluator_api_key": "unused-local-adapter", "evaluator_reasoning_effort": None,
            "evaluator_max_completion_tokens": host.max_tokens,
            "evaluator_temperature": host.temperature, "evaluator_top_p": None,
            "evaluator_timeout_seconds": host.timeout}
        report.update(protocol.score(question, response, judge_options=options, complete=complete))
        report["status"] = "COMPLETED"
    except BaseException as error:
        report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        elapsed = time.process_time()-cpu
        call_cpu = (read_json(output/"judge/call.json")["cpu_seconds"]
                    if (output/"judge/call.json").exists() else 0.0)
        report.update(cpu_seconds_nested=elapsed, wall_seconds=time.perf_counter()-started,
            orchestration_cpu_seconds=elapsed-call_cpu, cpu_ledger_recorded=False,
            accounting="Exclusive scorer CPU excludes measured Judge request CPU. Exact metrics "
                       "make no Judge call. Actual HTTP usage remains in the same original ledger.")
        write_json(output / "score.json", report)
    return report
