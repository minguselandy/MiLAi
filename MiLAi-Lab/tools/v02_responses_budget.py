"""Stateless text Responses counting and reservations over the pinned local vLLM tokenizer."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import time
from pathlib import Path

import httpx

from v02_deadline import Deadline, DeadlineExpired
from v02_local_provider import (
    ENDPOINT,
    MODEL,
    LocalGateError,
    accounting,
    append_event,
    check_budget,
    read_events,
    write_json,
)


def text_tool_output(value):
    """vLLM's Responses converter cannot render native text-part tool outputs."""
    if not isinstance(value, list):
        return value
    if any(part.get("type") not in {"input_text", "output_text", "text"}
           or not isinstance(part.get("text"), str) for part in value):
        raise LocalGateError("TEXT_TOOL_OUTPUT_CONTRACT_ONLY")
    return "".join(part["text"] for part in value)


def render_input(request: dict) -> dict:
    """Mirror this deployment's text conversion; generation still receives original Responses."""
    if request.get("previous_response_id") or request.get("background"):
        raise LocalGateError("STATEFUL_RESPONSE_OUTSIDE_COLD_SESSION_CONTRACT")
    messages = []
    if request.get("instructions"):
        messages.append({"role": "system", "content": request["instructions"]})
    items = request["input"]
    if isinstance(items, str):
        items = [{"role": "user", "content": items}]
    for item in items:
        kind = item.get("type", "message")
        prior = messages[-1] if messages and messages[-1]["role"] == "assistant" else None
        if kind == "function_call":
            name = (item["namespace"] + "__" if item.get("namespace") else "") + item["name"]
            call = {"id": item["call_id"], "type": "function",
                    "function": {"name": name, "arguments": item["arguments"]}}
            if prior is not None:
                prior.setdefault("tool_calls", []).append(call)
            else:
                messages.append({"role": "assistant", "tool_calls": [call]})
        elif kind == "function_call_output":
            messages.append({"role": "tool", "tool_call_id": item["call_id"],
                             "content": text_tool_output(item["output"])})
        elif kind == "reasoning":
            if item.get("encrypted_content"):
                raise LocalGateError("VLLM_ENCRYPTED_REASONING_UNSUPPORTED")
            content = item.get("content") or item.get("summary") or [{"text": ""}]
            if prior is not None and "reasoning" not in prior:
                prior["reasoning"] = content[0]["text"]
            else:
                messages.append({"role": "assistant", "reasoning": content[0]["text"]})
        elif kind == "message":
            content = copy.deepcopy(item["content"])
            if isinstance(content, list):
                if any(part["type"] not in {"input_text", "output_text", "text"}
                       for part in content):
                    raise LocalGateError("TEXT_RENDER_CONTRACT_ONLY")
                if item["role"] == "assistant":
                    if len(content) != 1:
                        raise LocalGateError("VLLM_MULTIPART_ASSISTANT_LOSS_UNSUPPORTED")
                    content = content[0]["text"]
                else:
                    content = [{"type": "text", "text": part["text"]} for part in content]
            if item["role"] == "assistant" and prior is not None and "content" not in prior:
                prior["content"] = content
            else:
                messages.append({"role": item["role"], "content": content})
        else:
            raise LocalGateError("RESPONSE_ITEM_NOT_SUPPORTED_BY_TEXT_RENDER_CONTRACT")
    tools = []
    for tool in request.get("tools", []):
        members = tool["tools"] if tool["type"] == "namespace" else [tool]
        for member in members:
            if member["type"] != "function":
                raise LocalGateError("VLLM_FUNCTION_TOOL_CONTRACT_ONLY")
            function = {key: copy.deepcopy(member[key]) for key in (
                "name", "description", "parameters", "strict", "defer_loading") if key in member}
            if tool["type"] == "namespace":
                function["name"] = tool["name"] + "__" + member["name"]
            tools.append({"type": "function", "function": function})
    kwargs = dict(request.get("chat_template_kwargs") or {})
    effort = (request.get("reasoning") or {}).get("effort")
    kwargs.update(add_generation_prompt=True, continue_final_message=False, reasoning_effort=effort)
    if effort is not None:
        kwargs.setdefault("enable_thinking", effort != "none")
    return {"model": request["model"], "messages": messages, "tools": tools or None,
            "tool_choice": request.get("tool_choice", "auto"), "max_tokens": 1,
            "chat_template_kwargs": kwargs, "add_generation_prompt": True,
            "continue_final_message": False}


class ResponsesBudget:
    """One synchronous observed forwarding operation; interrupted sends retain reservations."""

    def __init__(self, root: Path, config: dict, session: str, *, transport=None,
                 session_end: float | None = None):
        self.root, self.config, self.session = root, config, session
        self.session_end = session_end
        if (config["provider_base_url"] != ENDPOINT or config["model"] != MODEL
                or config["paid_model_allocations_authorized"] != 0):
            raise LocalGateError("ONLY_PINNED_LOCAL_PROVIDER_ALLOWED")
        self.client = httpx.Client(base_url=ENDPOINT, trust_env=False, follow_redirects=False,
            timeout=config["request_timeout_seconds"], transport=transport)
        self.ledger = root / "provider-ledger.jsonl"

    def close(self):
        self.client.close()

    def forward(self, request: dict) -> tuple[int, bytes, str]:
        started = time.monotonic()
        seconds = self.config["request_timeout_seconds"]
        if self.session_end is not None:
            seconds = min(seconds, self.session_end - started)
        if seconds <= 0:
            raise DeadlineExpired("SESSION_DEADLINE_BEFORE_PROVIDER")
        with Deadline(started, seconds):
            return self._forward(request)

    def _forward(self, request: dict) -> tuple[int, bytes, str]:
        if (not self.config.get("model_transport_enabled")
                or self.config.get("new_model_tokens_authorized", 0) <= 0
                or self.config.get("new_model_allocations_authorized", 0) <= 0):
            raise LocalGateError("NO_NEW_MODEL_AUTHORIZATION")
        if request["model"] != MODEL:
            raise LocalGateError("MODEL_IDENTITY_DRIFT")
        with (self.root / "provider.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LocalGateError("ONE_REQUEST_IN_FLIGHT") from exc
            events = read_events(self.ledger)
            check_budget(self.config, events, self.session, 0)
            identity = f"{self.session}-{accounting(events)['requests'] + 1:03d}"
            attempts = read_events(self.root / "tokenize-events.jsonl")
            number = 1 + sum(event["event"] == "ATTEMPT" for event in attempts)
            preflight = f"{self.session}-preflight-{number:03d}"
            render = render_input(request)
            write_json(self.root / (preflight + "-render-request.json"), render)
            append_event(self.root / "tokenize-events.jsonl", {
                "session": self.session, "preflight_id": preflight,
                "event": "ATTEMPT", "time": time.time(),
                "request_sha256": hashlib.sha256(json.dumps(render).encode()).hexdigest()})
            response = self.client.post("/tokenize", json=render)
            write_json(self.root / (preflight + "-tokenize-http.json"), {
                "status": response.status_code, "body": response.text})
            response.raise_for_status()
            value = response.json()
            write_json(self.root / (preflight + "-render-result.json"), value)
            count = value["count"]
            append_event(self.root / "tokenize-events.jsonl", {"session": self.session,
                "preflight_id": preflight, "event": "RESULT", "count": count, "time": time.time()})
            if (type(count) is not int or count <= 0
                    or count > self.config["request_input_token_limit"]):
                raise LocalGateError("INPUT_TOKEN_LIMIT_BEFORE_GENERATION")
            cap = check_budget(self.config, events, self.session, count)
            if request.get("max_output_tokens") is not None:
                cap = min(cap, request["max_output_tokens"])
            if self.config.get("request_raw_token_limit") is not None:
                cap = min(cap, self.config["request_raw_token_limit"] - count)
            if cap <= 0:
                raise LocalGateError("INVALID_OUTPUT_CAP")
            forwarded = copy.deepcopy(request)
            forwarded["max_output_tokens"] = cap
            if isinstance(forwarded["input"], list):
                for item in forwarded["input"]:
                    if item.get("type") == "function_call_output":
                        item["output"] = text_tool_output(item["output"])
            codec = self.config.get("output_codec")
            if codec not in {None, "qwen_xml"}:
                raise LocalGateError("UNSUPPORTED_OUTPUT_CODEC")
            if codec:
                forwarded["stream"] = False
            write_json(self.root / (identity + "-request.json"), request)
            write_json(self.root / (identity + "-forwarded.json"), forwarded)
            digest = hashlib.sha256(json.dumps(forwarded, ensure_ascii=False).encode()).hexdigest()
            append_event(self.ledger, {"event": "RESERVED", "request_id": identity,
                "preflight_id": preflight,
                "session": self.session, "prompt_tokens": count, "output_cap": cap,
                "raw_upper_bound": count + cap, "payload_sha256": digest, "time": time.time()})
            append_event(self.ledger, {"event": "DISPATCH_ATTEMPT", "request_id": identity,
                "session": self.session, "payload_sha256": digest, "time": time.time()})
            response = self.client.post("/v1/responses", json=forwarded)
            raw = response.content
            (self.root / (identity + "-response.bin")).write_bytes(raw)
            completed = response.json() if not forwarded.get("stream") else next((
                event["response"] for line in raw.decode().splitlines()
                if line.startswith("data: ") and line[6:] != "[DONE]"
                and (event := json.loads(line[6:])).get("type") == "response.completed"), None)
            usage = completed.get("usage") if completed else None
            if not response.is_success or not usage:
                raise LocalGateError("RESPONSE_OUTCOME_UNKNOWN_RESERVATION_RETAINED")
            used_in, used_out = usage["input_tokens"], usage["output_tokens"]
            if (type(used_in) is not int or type(used_out) is not int
                    or used_in != count or not 0 <= used_out <= cap):
                append_event(self.ledger, {"event": "BOUND_VIOLATION", "request_id": identity,
                    "session": self.session, "usage": usage, "render_count": count})
                raise LocalGateError("RENDER_OR_OUTPUT_BOUND_VIOLATION")
            append_event(self.ledger, {"event": "SETTLED", "request_id": identity,
                "input_tokens": used_in, "output_tokens": used_out, "usage": usage,
                "response_id": completed["id"], "time": time.time()})
            if codec:
                from v02_qwen_response import decode_response, response_events

                if completed.get("status") != "completed":
                    raise LocalGateError("INCOMPLETE_GENERATION_NO_TOOL_EXECUTION")
                decoded = decode_response(completed, request.get("tools", []))
                write_json(self.root / (identity + "-decoded.json"), decoded)
                raw = (response_events(decoded) if request.get("stream")
                       else json.dumps(decoded, ensure_ascii=False).encode())
                (self.root / (identity + "-delivered.bin")).write_bytes(raw)
                return (response.status_code, raw,
                        "text/event-stream" if request.get("stream") else "application/json")
            return (response.status_code, raw,
                    response.headers.get("Content-Type", "application/json"))
