from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_EVAL_DIRECTORY = Path(__file__).resolve().parent
if str(_EVAL_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIRECTORY))

import provider_ab
import vllm_local_identity as identity

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_post_r3_provider_gate as post_r3_gate

DATE = "2026-08-20"
DEFAULT_IDENTITY = ROOT / f"docs/reports/DG-10-vllm-local-identity-{DATE}.json"
DEFAULT_OUTPUT = ROOT / f"docs/reports/DG-10-vllm-local-ab-{DATE}.json"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
LOCAL_PROVIDER = "self-hosted-vllm"
LOCAL_INFERENCES = 1000
DATA_BOUNDARY = "synthetic-deidentified-only"
_NATIVE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}")
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REASON_CODE_POLICY = """Reason-code and output decision policy (these are mandatory output-contract rules, not memory data):
- DIRECT: if MILAI_MEMORY_DATA is absent, or if it is explicitly marked IRRELEVANT and the task does not depend on it, you must use DIRECT and must not abstain. Ignore all irrelevant memory and tool definitions, actually solve the requested arithmetic/text/boolean task, and put only its final answer in answer. For arithmetic, calculate the whole expression using normal operator precedence; never copy an operator or an unevaluated expression as the answer. No claim or issue reference is allowed.
- CURRENT_AUTHORIZED: current, in-scope ACTION_SAFE memory directly authorizes the answer. Copy only the exact current claim-* identifier into claim_refs.
- OPEN_CONFLICT: a live open issue has unresolved support and contradiction; abstain, copy its exact issue-* identifier, and copy only the exact target claim-* identifier.
- GROUNDING_BLOCKED: the only grounding is revoked/deleted/blocked and no current replacement exists; abstain, and claim_refs and open_issue_ids must both be empty.
- AUTHORITY_INSUFFICIENT: relevant memory is informational or lacks the confirmation/ACTION_SAFE authority needed for the requested action; abstain and copy only its exact claim-* identifier.
- SCOPE_MISMATCH: relevant memory belongs to a different scope; abstain, and claim_refs and open_issue_ids must both be empty.
Cardinality is exact: DIRECT has zero claims and zero issues; CURRENT_AUTHORIZED has exactly one claim and zero issues; OPEN_CONFLICT has exactly one target claim and exactly one open issue; GROUNDING_BLOCKED has zero claims and zero issues; AUTHORITY_INSUFFICIENT has exactly one claim and zero issues; SCOPE_MISMATCH has zero claims and zero issues. Every claim_refs item must be an exact identifier beginning claim-, never a label plus an identifier (for example, never include STATE or Claim). Every open_issue_ids item must be an exact identifier beginning issue-. A non-null answer must always be a JSON string: quote numeric results and encode boolean results as the lowercase strings "true" or "false". When abstaining, answer must be null. Use exactly one listed reason_code.
Unrelated format examples: a no-memory task "Return the exact token SAMPLE" maps to {"answer":"SAMPLE","abstained":false,"open_issue_ids":[],"claim_refs":[],"reason_code":"DIRECT"}; a no-memory task "Return the result of 2 + 3 * 4" maps to answer "14" with DIRECT and empty arrays; an OPEN issue-demo targeting claim-demo maps to {"answer":null,"abstained":true,"open_issue_ids":["issue-demo"],"claim_refs":["claim-demo"],"reason_code":"OPEN_CONFLICT"}."""
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": ["string", "null"]},
        "abstained": {"type": "boolean"},
        "open_issue_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^issue-[a-z0-9-]+$"},
        },
        "claim_refs": {
            "type": "array",
            "items": {"type": "string", "pattern": "^claim-[a-z0-9-]+$"},
        },
        "reason_code": {
            "type": "string",
            "enum": [
                "DIRECT",
                "CURRENT_AUTHORIZED",
                "OPEN_CONFLICT",
                "GROUNDING_BLOCKED",
                "AUTHORITY_INSUFFICIENT",
                "SCOPE_MISMATCH",
            ],
        },
    },
    "required": [
        "answer",
        "abstained",
        "open_issue_ids",
        "claim_refs",
        "reason_code",
    ],
    "additionalProperties": False,
}


class LocalVllmCaptureError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    return identity.sha256_file(path)


def _load_identity(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not path.is_absolute():
        raise LocalVllmCaptureError("identity report path must be absolute")
    actual = _sha256_file(path)
    if actual != expected_sha256:
        raise LocalVllmCaptureError("identity report SHA-256 mismatch")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalVllmCaptureError("identity report is invalid") from exc
    if not isinstance(value, dict):
        raise LocalVllmCaptureError("identity report must be an object")
    if (
        value.get("schema") != "milai.pvlocal.vllm-identity.v1"
        or value.get("status") != "LOCAL_TARGET_OBSERVED_REVERIFY_REQUIRED"
        or value.get("external_provider_requests") != 0
        or value.get("external_provider_cost") != 0
        or value.get("vllm_lifecycle_mutated") is not False
    ):
        raise LocalVllmCaptureError("identity report boundary mismatch")
    binding = value.get("binding")
    if not isinstance(binding, dict):
        raise LocalVllmCaptureError("identity binding is absent")
    if identity.sha256_bytes(identity.canonical_bytes(binding)) != value.get(
        "binding_sha256"
    ):
        raise LocalVllmCaptureError("identity binding digest mismatch")
    return value


def _post_json(
    base_url: str,
    path: str,
    value: Mapping[str, Any],
    *,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, str]]:
    base = identity.strict_base_url(base_url)
    if path not in {"/tokenize", "/v1/chat/completions"}:
        raise LocalVllmCaptureError("local vLLM path is not allowlisted")
    if path == "/v1/chat/completions":
        try:
            post_r3_gate.require_post_r3_provider_access()
        except post_r3_gate.PostR3ProviderGateError as exc:
            raise LocalVllmCaptureError(
                "non-bootstrap completion denied before R3 acceptance"
            ) from exc
    encoded = identity.canonical_bytes(value)
    request = urllib.request.Request(
        base + path,
        data=encoded,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with identity.local_opener().open(request, timeout=timeout) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            status = int(response.status)
            headers = {key.casefold(): item for key, item in response.headers.items()}
    except urllib.error.HTTPError as exc:
        reason = exc.read(4096)
        raise LocalVllmCaptureError(
            "local vLLM HTTP error "
            f"{exc.code}; body_sha256={hashlib.sha256(reason).hexdigest()}"
        ) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise LocalVllmCaptureError("local vLLM request failed") from exc
    if status != 200 or len(raw) > _MAX_RESPONSE_BYTES:
        raise LocalVllmCaptureError("local vLLM returned an invalid bounded response")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LocalVllmCaptureError("local vLLM response is not JSON") from exc
    if not isinstance(result, dict):
        raise LocalVllmCaptureError("local vLLM response is not an object")
    return result, headers


def _tokenize(
    base_url: str,
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]],
    *,
    timeout: float,
) -> int:
    request: dict[str, Any] = {
        "model": MODEL_ID,
        "messages": list(messages),
        "add_generation_prompt": True,
        "add_special_tokens": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if tools:
        request["tools"] = list(tools)
    response, _headers = _post_json(
        base_url, "/tokenize", request, timeout=timeout
    )
    count = response.get("count")
    tokens = response.get("tokens")
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or count <= 0
        or not isinstance(tokens, list)
        or len(tokens) != count
        or any(not isinstance(token, int) for token in tokens)
    ):
        raise LocalVllmCaptureError("vLLM tokenizer returned an invalid count")
    return count


def _messages_without_memory(
    messages: Sequence[Mapping[str, Any]], memory: str
) -> list[dict[str, Any]]:
    result = [dict(message) for message in messages]
    if not memory:
        return result
    suffix = f"\n\n<MILAI_MEMORY_DATA>\n{memory}\n</MILAI_MEMORY_DATA>"
    content = result[-1].get("content")
    if not isinstance(content, str) or not content.endswith(suffix):
        raise LocalVllmCaptureError("memory component cannot be isolated")
    result[-1]["content"] = content[: -len(suffix)]
    return result


def _effective_messages(
    messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = [dict(message) for message in messages]
    if not result or result[0].get("role") != "system":
        raise LocalVllmCaptureError("workload system message is absent")
    content = result[0].get("content")
    if not isinstance(content, str) or not content:
        raise LocalVllmCaptureError("workload system message is invalid")
    result[0]["content"] = content + "\n\n" + REASON_CODE_POLICY
    return result


def _component_counts(
    base_url: str,
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]],
    memory: str,
    *,
    timeout: float,
) -> tuple[int, dict[str, int]]:
    full = _tokenize(base_url, messages, tools, timeout=timeout)
    without_tools = _tokenize(base_url, messages, (), timeout=timeout)
    without_memory = _tokenize(
        base_url,
        _messages_without_memory(messages, memory),
        (),
        timeout=timeout,
    )
    tool_tokens = full - without_tools
    memory_tokens = without_tools - without_memory
    if tool_tokens < 0 or memory_tokens < 0:
        raise LocalVllmCaptureError("token component delta is negative")
    return full, {
        "memory_context_tokens": memory_tokens,
        "tool_schema_tokens": tool_tokens,
    }


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LocalVllmCaptureError(f"{label} is invalid")
    return value


def _validate_completion(
    response: Mapping[str, Any],
    headers: Mapping[str, str],
    *,
    expected_prompt_tokens: int,
    max_output_tokens: int,
) -> tuple[str, dict[str, int | None], str, str]:
    request_id = response.get("id")
    if not isinstance(request_id, str) or _NATIVE_ID.fullmatch(request_id) is None:
        raise LocalVllmCaptureError("vLLM native request ID is invalid")
    if response.get("model") != MODEL_ID:
        raise LocalVllmCaptureError("vLLM response model drift")
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise LocalVllmCaptureError("vLLM response choice count drift")
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
        raise LocalVllmCaptureError("vLLM response is not terminal stop")
    message = choice.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise LocalVllmCaptureError("vLLM response content is absent")
    tool_calls = message.get("tool_calls")
    if tool_calls is not None and tool_calls != []:
        raise LocalVllmCaptureError("vLLM unexpectedly emitted a tool call")
    usage_value = response.get("usage")
    if not isinstance(usage_value, dict):
        raise LocalVllmCaptureError("vLLM usage is absent")
    prompt_tokens = _nonnegative_int(usage_value.get("prompt_tokens"), "prompt usage")
    completion_tokens = _nonnegative_int(
        usage_value.get("completion_tokens"), "completion usage"
    )
    total_tokens = _nonnegative_int(usage_value.get("total_tokens"), "total usage")
    if prompt_tokens != expected_prompt_tokens:
        raise LocalVllmCaptureError("pre-count differs from vLLM prompt usage")
    if completion_tokens > max_output_tokens or total_tokens != (
        prompt_tokens + completion_tokens
    ):
        raise LocalVllmCaptureError("vLLM usage arithmetic or output cap failed")
    usage: dict[str, int | None] = {
        "input_tokens": prompt_tokens,
        "cached_input_tokens": 0,
        "output_tokens": completion_tokens,
        "reasoning_tokens": None,
    }
    native_receipt = {
        "response_id": request_id,
        "header_request_id": headers.get("x-request-id"),
        "model": MODEL_ID,
        "finish_reason": "stop",
        "usage": usage,
    }
    return (
        str(message["content"]),
        usage,
        request_id,
        identity.sha256_bytes(identity.canonical_bytes(native_receipt)),
    )


def _live_check(binding: Mapping[str, Any]) -> None:
    container = binding["container"]
    inspected = identity.run_json(
        ["docker", "container", "inspect", str(container["id"])]
    )
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise LocalVllmCaptureError("vLLM container disappeared")
    current = inspected[0]
    state = current.get("State") or {}
    if (
        current.get("Id") != container["id"]
        or current.get("Image") != container["image_id"]
        or current.get("Args") != container["argv"]
        or current.get("RestartCount") != container["restart_count"]
        or state.get("Status") != "running"
        or state.get("StartedAt") != container["started_at"]
    ):
        raise LocalVllmCaptureError("vLLM live container identity drift")
    service = binding["service"]
    version = identity.http_json(str(service["base_url"]), "/version")
    models = identity.http_json(str(service["base_url"]), "/v1/models")
    values = models.get("data")
    if (
        version.get("version") != service["vllm_version"]
        or not isinstance(values, list)
        or len(values) != 1
        or not isinstance(values[0], dict)
        or values[0].get("id") != service["served_model_id"]
        or values[0].get("root") != service["served_model_root"]
        or values[0].get("max_model_len") != service["max_model_len"]
    ):
        raise LocalVllmCaptureError("vLLM live service identity drift")


def _base_report(
    identity_report: Mapping[str, Any],
    identity_sha256: str,
    workload_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": "milai.pvlocal.vllm-ab-capture.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "RUNNING_LOCAL_CAPTURE",
        "data_boundary": DATA_BOUNDARY,
        "provider_class": LOCAL_PROVIDER,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "billing_reconciliation": "NOT_APPLICABLE_SELF_HOSTED",
        "oe_f06": "OPEN_EXTERNAL_BILLING_EVIDENCE_ABSENT",
        "vllm_lifecycle_mutated": False,
        "same_model_ab": True,
        "workload_sha256": workload_sha256,
        "uniform_reason_code_policy_sha256": identity.sha256_bytes(
            REASON_CODE_POLICY.encode()
        ),
        "closed_output_schema_sha256": identity.sha256_bytes(
            identity.canonical_bytes(OUTPUT_SCHEMA)
        ),
        "identity_report_sha256": identity_sha256,
        "identity_binding_sha256": identity_report["binding_sha256"],
        "model_id": MODEL_ID,
        "privacy": {
            "raw_prompt_retained": False,
            "raw_memory_retained": False,
            "raw_model_output_retained": False,
            "provider_credential_used": False,
            "report_fields": "normalized-output,hashes,counters,timings,quality",
        },
        "records": [],
        "aggregates": {},
        "gates": {},
        "execution": {
            "planned_local_inferences": LOCAL_INFERENCES,
            "validated_local_inferences": 0,
            "unique_native_ids": 0,
            "route": "http://127.0.0.1:7860 only",
        },
        "failure": None,
        "known_limits": [
            "Self-hosted vLLM has no upstream Provider bill and cannot close OE-F06.",
            "The existing vLLM has a writable model mount and a 0.0.0.0 listener; startup was not changed by user direction.",
            "GPU sharing makes wall time observational rather than an SLA.",
            "This author capture requires independent re-verification.",
        ],
    }


def _checkpoint(
    output: Path,
    base: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    native_ids: set[str],
    started: float,
    *,
    status: str,
    failure: Mapping[str, Any] | None = None,
) -> None:
    value = dict(base)
    value["generated_at"] = datetime.now(UTC).isoformat()
    value["status"] = status
    value["records"] = list(records)
    value["execution"] = {
        **dict(base["execution"]),
        "validated_local_inferences": len(records),
        "unique_native_ids": len(native_ids),
        "end_to_end_wall_ms": round((time.perf_counter() - started) * 1000, 3),
        "native_ids_sha256": identity.sha256_bytes(
            identity.canonical_bytes(sorted(native_ids))
        ),
    }
    value["failure"] = failure
    identity.atomic_write(output, value)


def run_capture(
    identity_path: Path,
    expected_identity_sha256: str,
    output: Path,
    *,
    timeout: float,
) -> dict[str, Any]:
    identity_report = _load_identity(identity_path, expected_identity_sha256)
    binding = identity_report["binding"]
    model_root = Path(str(binding["model"]["host_path"]))
    service_url = str(binding["service"]["base_url"])
    before = identity.collect_binding(
        str(binding["container"]["id"]),
        model_root,
        service_url,
        progress=True,
    )
    if before != binding:
        raise LocalVllmCaptureError("pre-capture vLLM binding drift")
    workload, workload_sha256 = provider_ab._load_workload()
    turns = provider_ab._turns(workload, 500)
    base = _base_report(identity_report, expected_identity_sha256, workload_sha256)
    records: list[dict[str, Any]] = []
    native_ids: set[str] = set()
    started = time.perf_counter()
    _checkpoint(
        output,
        base,
        records,
        native_ids,
        started,
        status="RUNNING_LOCAL_CAPTURE",
    )
    try:
        for turn in turns:
            order = (
                ("baseline", "optimized")
                if turn.turn_index % 2 == 0
                else ("optimized", "baseline")
            )
            for variant in order:
                request, private = provider_ab._request_payload(
                    workload,
                    workload_sha256,
                    turn,
                    variant,
                    LOCAL_PROVIDER,
                    MODEL_ID,
                )
                messages = request["messages"]
                tools = request["tools"]
                if not isinstance(messages, Sequence) or not isinstance(tools, Sequence):
                    raise LocalVllmCaptureError("workload request is malformed")
                effective_messages = _effective_messages(messages)
                count, components = _component_counts(
                    service_url,
                    effective_messages,
                    tools,
                    str(private["memory_context"]),
                    timeout=timeout,
                )
                if count > int(binding["service"]["max_model_len"]):
                    raise LocalVllmCaptureError("request exceeds served model context")
                payload: dict[str, Any] = {
                    "model": MODEL_ID,
                    "messages": effective_messages,
                    "temperature": workload["temperature"],
                    "max_tokens": workload["max_output_tokens"],
                    "stream": False,
                    "seed": int(
                        hashlib.sha256(request["request_id"].encode()).hexdigest()[:16],
                        16,
                    )
                    & ((1 << 63) - 1),
                    "tool_choice": "none",
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "milai_eval_output",
                            "strict": True,
                            "schema": OUTPUT_SCHEMA,
                        },
                    },
                    "chat_template_kwargs": {"enable_thinking": False},
                    "include_reasoning": False,
                    "cache_salt": hashlib.sha256(
                        ("milai-pvlocal:" + request["request_id"]).encode()
                    ).hexdigest(),
                }
                if tools:
                    payload["tools"] = list(tools)
                call_started = time.perf_counter()
                response, headers = _post_json(
                    service_url,
                    "/v1/chat/completions",
                    payload,
                    timeout=timeout,
                )
                wall_ms = (time.perf_counter() - call_started) * 1000
                text, usage, native_id, receipt_sha256 = _validate_completion(
                    response,
                    headers,
                    expected_prompt_tokens=count,
                    max_output_tokens=int(workload["max_output_tokens"]),
                )
                if native_id in native_ids:
                    raise LocalVllmCaptureError("duplicate vLLM native request ID")
                native_ids.add(native_id)
                normalized = provider_ab._normalize_output(text)
                quality = provider_ab._score_normalized(
                    normalized,
                    private["expected"],
                    private["forbidden_output_terms"],
                    private["safety_labels"],
                )
                output_source = (
                    text.encode()
                    if normalized is None
                    else identity.canonical_bytes(normalized)
                )
                records.append(
                    {
                        "request_id": request["request_id"],
                        "native_calls": [
                            {
                                "provider_request_id": native_id,
                                "model_id": MODEL_ID,
                                "usage": usage,
                                "terminal": True,
                                "finish_reason": "stop",
                                "native_receipt_sha256": receipt_sha256,
                            }
                        ],
                        "turn_index": turn.turn_index,
                        "case_id": turn.case_id,
                        "requires_memory": turn.requires_memory,
                        "variant": variant,
                        "workload_prompt_sha256": private["prompt_sha256"],
                        "prompt_sha256": identity.sha256_bytes(
                            identity.canonical_bytes(effective_messages)
                        ),
                        "tool_schema_sha256": private["tool_schema_sha256"],
                        "normalized_output": normalized,
                        "output_sha256": identity.sha256_bytes(output_source),
                        "finish_reason": "stop",
                        "usage": usage,
                        "component_tokens": components,
                        "wall_ms": round(wall_ms, 3),
                        "expected_cost": "0",
                        "quality": quality,
                    }
                )
                if len(records) % 20 == 0:
                    _live_check(binding)
                    _checkpoint(
                        output,
                        base,
                        records,
                        native_ids,
                        started,
                        status="RUNNING_LOCAL_CAPTURE",
                    )
                    print(
                        json.dumps(
                            {
                                "event": "PVLOCAL_PROGRESS",
                                "validated": len(records),
                                "planned": LOCAL_INFERENCES,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
        if len(records) != LOCAL_INFERENCES or len(native_ids) != LOCAL_INFERENCES:
            raise LocalVllmCaptureError("local inference coverage is not exact")
        after = identity.collect_binding(
            str(binding["container"]["id"]),
            model_root,
            service_url,
            progress=True,
        )
        if after != before:
            raise LocalVllmCaptureError("post-capture vLLM binding drift")
        aggregates = provider_ab._aggregates(
            records, workload["required_turn_counts"]
        )
        gates = provider_ab._gates(workload, aggregates)
        for name in list(gates):
            if name.endswith("_expected_cost_reduced"):
                del gates[name]
        gates.update(
            {
                "PVL-00_target_identity_pre_post": True,
                "PVL-01_literal_loopback_route": True,
                "PVL-01_external_provider_requests_zero": True,
                "PVL-01_external_provider_cost_zero": True,
                "PVL-02_all_precounts_match_native_usage": True,
                "PVL-02_all_native_ids_unique": True,
                "PVL-03_exact_1000_local_inferences": True,
                "PVL-04_agent_mcp_e2e": False,
                "PVL-05_independent_review": False,
            }
        )
        report = dict(base)
        report.update(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "status": (
                    "LOCAL_AB_CAPTURE_COMPLETE_REVIEW_REQUIRED"
                    if all(
                        value
                        for name, value in gates.items()
                        if not name.startswith(("PVL-04", "PVL-05"))
                    )
                    else "FAIL_COMPLETE"
                ),
                "records": records,
                "aggregates": aggregates,
                "gates": dict(sorted(gates.items())),
                "execution": {
                    **dict(base["execution"]),
                    "validated_local_inferences": len(records),
                    "unique_native_ids": len(native_ids),
                    "end_to_end_wall_ms": round(
                        (time.perf_counter() - started) * 1000, 3
                    ),
                    "native_ids_sha256": identity.sha256_bytes(
                        identity.canonical_bytes(sorted(native_ids))
                    ),
                    "pre_binding_sha256": identity.sha256_bytes(
                        identity.canonical_bytes(before)
                    ),
                    "post_binding_sha256": identity.sha256_bytes(
                        identity.canonical_bytes(after)
                    ),
                },
                "failure": None,
            }
        )
        identity.atomic_write(output, report)
        return report
    except (
        LocalVllmCaptureError,
        identity.LocalVllmIdentityError,
        provider_ab.ProviderEvidenceError,
        OSError,
    ) as exc:
        _checkpoint(
            output,
            base,
            records,
            native_ids,
            started,
            status="FAIL_PARTIAL",
            failure={
                "code": "PVLOCAL_CAPTURE_FAILED",
                "after_validated_local_inferences": len(records),
                "reason_sha256": identity.sha256_bytes(str(exc).encode()),
            },
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run exact same-model A/B against an existing local vLLM"
    )
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--expected-identity-sha256", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--max-local-inferences", type=int, required=True)
    parser.add_argument("--data-boundary-ack", required=True)
    parser.add_argument("--execute-local-vllm", action="store_true")
    args = parser.parse_args()
    if args.execute_local_vllm is not True:
        raise SystemExit("local vLLM execution requires --execute-local-vllm")
    if args.max_local_inferences != LOCAL_INFERENCES:
        raise SystemExit(f"max local inferences must be exactly {LOCAL_INFERENCES}")
    if args.data_boundary_ack != DATA_BOUNDARY:
        raise SystemExit("exact synthetic/deidentified data boundary is required")
    if args.timeout_seconds <= 0:
        raise SystemExit("timeout must be positive")
    report = run_capture(
        args.identity.resolve(),
        args.expected_identity_sha256,
        args.output.resolve(),
        timeout=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "status": report["status"],
                "validated_local_inferences": report["execution"][
                    "validated_local_inferences"
                ],
                "external_provider_requests": 0,
                "external_provider_cost": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
