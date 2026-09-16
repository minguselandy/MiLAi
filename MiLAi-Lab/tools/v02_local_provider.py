"""Loopback-only vLLM transport with durable, single-in-flight token reservations.

This validates a local simulation, not any cloud billing or native Host contract.
No SDK, retries, proxy inheritance, redirects, tools with model access, or fallback.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from v02_deadline import Deadline, DeadlineExpired

ENDPOINT = "http://127.0.0.1:7860"
MODEL = "Qwen3.6-35B-A3B-FP8"


class LocalGateError(RuntimeError):
    """An explicit stop; never an invitation to retry automatically."""


def write_json(path: Path, value: Any) -> None:
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def append_event(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def accounting(events: list[dict]) -> dict:
    pending: dict[str, dict] = {}
    sessions: dict[str, dict] = {}
    violations = []
    for event in events:
        kind, key = event["event"], event["request_id"]
        if kind == "RESERVED":
            pending[key] = event
            session = sessions.setdefault(event["session"], {"requests": 0, "raw_tokens": 0,
                                                             "input_tokens": 0,
                                                             "output_tokens": 0})
            session["requests"] += 1
        elif kind == "SETTLED":
            reservation = pending.pop(key)
            session = sessions[reservation["session"]]
            session["input_tokens"] += event["input_tokens"]
            session["output_tokens"] += event["output_tokens"]
            session["raw_tokens"] += event["input_tokens"] + event["output_tokens"]
        elif kind == "BOUND_VIOLATION":
            violations.append(event)
    return {"sessions": sessions, "raw_tokens": sum(s["raw_tokens"] for s in sessions.values()),
            "requests": sum(s["requests"] for s in sessions.values()),
            "pending": list(pending.values()), "violations": violations}


def budget_observation(config: dict, events: list[dict], session: str) -> dict:
    """Mechanical remaining allowance, before paying for the next complete input."""
    state = accounting(events)
    current = state["sessions"].get(session, {"requests": 0, "raw_tokens": 0})
    batch_limit = min(config["batch_token_limit"], config.get(
        "new_model_tokens_authorized", config["batch_token_limit"]))
    return {
        "session_raw_tokens_used": current["raw_tokens"],
        "batch_raw_tokens_used": state["raw_tokens"],
        "raw_tokens_remaining_before_next_input": min(
            config["session_token_limit"] - current["raw_tokens"],
            batch_limit - state["raw_tokens"]),
        "requests_remaining": config["max_requests_per_session"] - current["requests"],
        "max_output_tokens_per_request": config["max_output_tokens"],
        "minimum_output_reservation": 256,
        "unresolved_requests": len(state["pending"]),
        "bound_violations": len(state["violations"]),
    }


def check_budget(config: dict, events: list[dict], session: str, prompt_tokens: int) -> int:
    state = accounting(events)
    if session not in config["local_sessions"]:
        raise LocalGateError("SESSION_NOT_AUTHORIZED")
    if state["pending"] or state["violations"]:
        raise LocalGateError("UNRESOLVED_OR_BOUND_VIOLATION")
    current = state["sessions"].get(session, {"requests": 0, "raw_tokens": 0})
    if (session not in state["sessions"] and len(state["sessions"])
            >= config.get("new_model_allocations_authorized", len(config["local_sessions"]))):
        raise LocalGateError("NEW_ALLOCATION_LIMIT")
    if current["requests"] >= config["max_requests_per_session"]:
        raise LocalGateError("REQUEST_LIMIT")
    available = min(config["session_token_limit"] - current["raw_tokens"],
                    min(config["batch_token_limit"], config.get(
                        "new_model_tokens_authorized", config["batch_token_limit"]))
                    - state["raw_tokens"]) - prompt_tokens
    output_cap = min(config["max_output_tokens"], available)
    if output_cap < 256:
        raise LocalGateError("TOKEN_LIMIT_BEFORE_DISPATCH")
    return output_cap


class LocalProvider:
    def __init__(self, config: dict, root: Path, session: str,
                 transport: httpx.BaseTransport | None = None, deadline: Deadline | None = None):
        if config["provider_base_url"] != ENDPOINT or config["model"] != MODEL:
            raise LocalGateError("ONLY_PINNED_LOOPBACK_MODEL_ALLOWED")
        if config["paid_model_allocations_authorized"] != 0:
            raise LocalGateError("PAID_CALLS_FORBIDDEN")
        if config.get("transport_kind") == "MOCK_ONLY" and not isinstance(
            transport, httpx.MockTransport
        ):
            raise LocalGateError("MOCK_PROFILE_CANNOT_USE_NETWORK_TRANSPORT")
        if (not config.get("model_transport_enabled", False)
                or config.get("new_model_allocations_authorized", 0) <= 0
                or config.get("new_model_tokens_authorized", 0) <= 0):
            raise LocalGateError("NO_NEW_MODEL_AUTHORIZATION")
        self.enable_thinking = config.get("enable_thinking", False)
        if type(self.enable_thinking) is not bool:
            raise LocalGateError("THINKING_MODE_MUST_BE_BOOLEAN")
        self.config, self.root, self.session = config, root, session
        self.deadline = deadline
        self.client = httpx.Client(base_url=ENDPOINT, trust_env=False, follow_redirects=False,
                                   timeout=config["request_timeout_seconds"], transport=transport)
        self.ledger = root / "provider-ledger.jsonl"

    def close(self) -> None:
        self.client.close()

    def verify(self) -> dict:
        if self.deadline:
            self.deadline.check("provider_identity")
        response = self.client.get("/v1/models")
        response.raise_for_status()
        models = response.json()["data"]
        if len(models) != 1 or models[0]["id"] != MODEL:
            raise LocalGateError("MODEL_IDENTITY_DRIFT")
        return models[0]

    def complete(self, messages: list[dict], schema: dict, directory: Path) -> str:
        if self.deadline:
            self.deadline.check("before_tokenize")
        # Lock remains held across reservation, network dispatch and settlement.
        # Reopening a ledger after a crash cannot free an unresolved reservation.
        with (self.root / "provider.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LocalGateError("ONE_REQUEST_IN_FLIGHT") from exc
            events = read_events(self.ledger)
            check_budget(self.config, events, self.session, 0)
            chat = {"model": MODEL, "messages": messages,
                    "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
                    "add_generation_prompt": True, "add_special_tokens": False}
            trace_path = directory / "budget-preflights.jsonl"
            trace = {"session": self.session, "status": "TOKENIZE_ATTEMPT",
                     "time": time.time(), "budget": budget_observation(
                         self.config, events, self.session),
                     "chat_sha256": hashlib.sha256(json.dumps(
                         chat, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
            append_event(trace_path, trace)
            try:
                tokenized = self.client.post("/tokenize", json=chat)
                tokenized.raise_for_status()
                count = tokenized.json()["count"]
                trace["prompt_tokens"] = count
                if self.deadline:
                    self.deadline.check("after_tokenize_before_reservation")
                if type(count) is not int or count <= 0:
                    raise LocalGateError("INVALID_TOKEN_COUNT")
                cap = check_budget(self.config, events, self.session, count)
                trace.update(status="BUDGET_ACCEPTED_NOT_DISPATCHED", output_cap=cap)
            except (Exception, DeadlineExpired) as exc:
                trace.update(status="STOPPED_BEFORE_GENERATION", error_type=type(exc).__name__)
                if isinstance(exc, LocalGateError):
                    trace["reason"] = str(exc)
                raise
            finally:
                trace["finished_at"] = time.time()
                append_event(trace_path, trace)
            request = {**chat, "temperature": 0, "top_p": 1, "seed": self.config["seed"],
                       "max_tokens": cap, "stream": False,
                       "response_format": {"type": "json_schema", "json_schema": {
                           "name": "local_host_action", "strict": True, "schema": schema}}}
            request_id = f"{self.session}-{accounting(events)['requests'] + 1:03d}"
            payload_bytes = json.dumps(request, ensure_ascii=False).encode()
            write_json(directory / f"{request_id}-request.json", request)
            append_event(self.ledger, {"event": "RESERVED", "request_id": request_id,
                         "session": self.session, "prompt_tokens": count, "output_cap": cap,
                         "raw_upper_bound": count + cap, "time": time.time(),
                         "payload_sha256": hashlib.sha256(payload_bytes).hexdigest()})
            started = time.monotonic()
            try:
                if self.deadline:
                    self.deadline.check("generation_dispatch")
                append_event(self.ledger, {"event": "DISPATCH_ATTEMPT", "request_id": request_id,
                    "session": self.session, "time": time.time(),
                    "payload_sha256": hashlib.sha256(payload_bytes).hexdigest()})
                response = self.client.post("/v1/chat/completions", content=payload_bytes,
                                            headers={"Content-Type": "application/json"})
                write_json(directory / f"{request_id}-http.json", {
                    "status_code": response.status_code, "body": response.text})
                response.raise_for_status()
                value = response.json()
                usage = value["usage"]
                input_tokens, output_tokens = usage["prompt_tokens"], usage["completion_tokens"]
                if (type(input_tokens) is not int or type(output_tokens) is not int
                        or input_tokens < 0 or output_tokens < 0
                        or usage.get("total_tokens") != input_tokens + output_tokens):
                    raise LocalGateError("USAGE_UNVERIFIABLE")
                if input_tokens != count or output_tokens > cap:
                    append_event(self.ledger, {"event": "BOUND_VIOLATION",
                                 "request_id": request_id, "actual_usage": usage})
                    raise LocalGateError("TOKEN_BOUND_MISMATCH")
                append_event(self.ledger, {"event": "SETTLED", "request_id": request_id,
                             "session": self.session, "input_tokens": input_tokens,
                             "output_tokens": output_tokens, "usage": usage,
                             "elapsed_seconds": time.monotonic() - started,
                             "provider_request_id": value.get("id")})
            except (Exception, DeadlineExpired) as exc:
                append_event(self.ledger, {"event": "OUTCOME_UNKNOWN", "request_id": request_id,
                             "error_type": type(exc).__name__,
                             "elapsed_seconds": time.monotonic() - started})
                if isinstance(exc, DeadlineExpired):
                    raise
                raise LocalGateError("REQUEST_UNRESOLVED_NO_RETRY") from exc
            if self.deadline:
                # A late, valid receipt settles cost but does not authorize a late task action.
                self.deadline.check("generation_response_settled")
            choice = value["choices"][0]
            if choice["finish_reason"] != "stop":
                raise LocalGateError("INCOMPLETE_OUTPUT_USAGE_RETAINED")
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise LocalGateError("MISSING_OUTPUT_USAGE_RETAINED")
            return content
