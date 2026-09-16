"""V0.5 exact-output reservations for static, dynamic and cold-session callers.

Only the trusted allocation controls limits. Each request uses the same durable
ledger across processes, no retries and no output-cap shrinking.
"""

from __future__ import annotations

import fcntl
import json
import time
from pathlib import Path

import httpx

from check_v0210_control import ENDPOINT, TOKENIZE_KEYS, write
from milai_lab.methods.state_control import MODEL, ControlStop, canonical, check_envelope, digest
from run_v0210_control import request_window
from v02_deadline import Deadline
from v02_local_provider import accounting, append_event, read_events


class V05Provider:
    def __init__(self, root: Path, limits: dict, deadline: Deadline,
                 transport: httpx.BaseTransport | None = None):
        self.root, self.limits, self.deadline = root, limits, deadline
        self.client = httpx.Client(base_url=ENDPOINT, trust_env=False,
                                   follow_redirects=False, timeout=60, transport=transport)
        self.ledger = root / "provider-ledger.jsonl"
        path = root / "provider-limits.json"
        if path.exists():
            if json.loads(path.read_text()) != limits:
                raise ControlStop("V05_ALLOCATION_CHANGED")
        else:
            write(path, limits)

    def close(self) -> None:
        self.client.close()

    def verify(self) -> dict:
        response = self.client.get("/v1/models", timeout=min(5, self.deadline.check("identity")))
        response.raise_for_status()
        models = response.json()["data"]
        if [item["id"] for item in models] != [MODEL]:
            raise ControlStop("V05_MODEL_IDENTITY_CHANGED")
        self.context = models[0]["max_model_len"]
        return models[0]

    def generate(self, session: str, messages: list[dict], *, schema: dict | None = None) -> str:
        with (self.root / "provider.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ControlStop("V05_ONE_IN_FLIGHT") from exc
            state = accounting(read_events(self.ledger))
            if state["pending"] or state["violations"]:
                raise ControlStop("V05_UNRESOLVED_RESERVATION")
            allowed = self.limits["sessions"].get(session, 0)
            used = state["sessions"].get(session, {}).get("requests", 0)
            if used >= allowed or state["requests"] >= self.limits["max_generations"]:
                raise ControlStop("V05_GENERATION_LIMIT")
            body = {"model": MODEL, "messages": messages,
                    "chat_template_kwargs": {"enable_thinking": False},
                    "add_generation_prompt": True, "add_special_tokens": False,
                    "temperature": 0, "top_p": 1, "seed": self.limits["seed"],
                    "max_tokens": 1024, "stream": False}
            if schema is not None:
                body["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": "visible_host_action", "strict": True, "schema": schema}}
            start = time.monotonic()
            response = self.client.post(
                "/tokenize", json={key: body[key] for key in TOKENIZE_KEYS},
                timeout=min(5, self.deadline.check("tokenize")))
            response.raise_for_status()
            count = response.json()["count"]
            upper = check_envelope(count, model_context=self.context)
            if state["raw_tokens"] + upper > self.limits["max_raw_tokens"]:
                raise ControlStop("V05_FULL_RESERVATION_OVER_BUDGET")
            key = f"{session}-{used + 1:02d}"
            write(self.root / f"{key}-tokenize.json", {
                "count": count, "seconds": time.monotonic() - start})
            wire = canonical(body).encode()
            (self.root / f"{key}-request.json").write_bytes(wire)
            self.deadline.check("before_reservation")
            append_event(self.ledger, {"event": "RESERVED", "request_id": key, "session": session,
                                      "prompt_tokens": count, "output_cap": 1024,
                                      "raw_upper_bound": upper, "payload_sha256": digest(wire),
                                      "time": time.time()})
            start = time.monotonic()
            with request_window(self.deadline):
                response = self.client.post("/v1/chat/completions", content=wire,
                                            headers={"Content-Type": "application/json"},
                                            timeout=min(60, self.deadline.check("generation")))
            write(self.root / f"{key}-http.json", {
                "status_code": response.status_code, "body": response.text})
            response.raise_for_status()
            value = response.json()
            usage = value.get("usage", {})
            prompt, output = usage.get("prompt_tokens"), usage.get("completion_tokens")
            if (type(prompt) is not int or type(output) is not int or min(prompt, output) < 0
                    or usage.get("total_tokens") != prompt + output):
                raise ControlStop("V05_USAGE_UNKNOWN_RESERVATION_RETAINED")
            if prompt != count or output > 1024:
                append_event(self.ledger, {"event": "BOUND_VIOLATION", "request_id": key,
                                          "usage": usage})
                raise ControlStop("V05_USAGE_BOUND_MISMATCH")
            append_event(self.ledger, {"event": "SETTLED", "request_id": key,
                                      "input_tokens": prompt, "output_tokens": output,
                                      "usage": usage, "seconds": time.monotonic() - start})
            self.deadline.check("settled")
            choice = value["choices"][0]
            content = choice["message"].get("content")
            if not isinstance(content, str):
                raise ControlStop("V05_MISSING_VISIBLE_OUTPUT")
            write(self.root / f"{key}-outcome.json", {"finish_reason": choice["finish_reason"]})
            (self.root / f"{key}-visible.txt").write_text(content)
            return content
