"""Single-process loopback Provider: count/time limits, no cumulative raw-token cap."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from replay_v0213_cost import save, sha, wire
from v02_local_provider import accounting, append_event, read_events

MODEL = "Qwen3.6-35B-A3B-FP8"
ENDPOINT = "http://127.0.0.1:7860"
TOKENIZE_KEYS = ("model", "messages", "chat_template_kwargs", "add_generation_prompt",
                 "add_special_tokens")


def payload(messages: list[dict], schema: dict) -> dict:
    return {"model": MODEL, "messages": messages,
            "chat_template_kwargs": {"enable_thinking": False},
            "add_generation_prompt": True, "add_special_tokens": False,
            "temperature": 0, "top_p": 1, "seed": 213,
            "max_tokens": 4096, "stream": False,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "visible_action_intent", "strict": True, "schema": schema}}}


class Provider:
    def __init__(self, root: Path, *, deadline: float, max_requests: int,
                 transport: httpx.BaseTransport | None = None):
        self.root, self.deadline, self.max_requests = root, deadline, max_requests
        root.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(base_url=ENDPOINT, trust_env=False, follow_redirects=False,
                                   timeout=60, transport=transport)
        self.ledger = root / "provider-ledger.jsonl"

    def timeout(self, cap: float) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("WALL_CLOCK_LIMIT")
        return min(cap, remaining)

    def verify(self) -> dict:
        response = self.client.get("/v1/models", timeout=self.timeout(5))
        response.raise_for_status()
        models = response.json()["data"]
        if [item["id"] for item in models] != [MODEL]:
            raise ValueError("MODEL_IDENTITY_CHANGED")
        self.context = models[0]["max_model_len"]
        save(self.root / "model.json", models[0])
        return models[0]

    def generate(self, session: str, body: dict) -> str:
        state = accounting(read_events(self.ledger))
        if state["pending"] or state["violations"]:
            raise ValueError("UNSETTLED_USAGE_NO_RETRY")
        if state["requests"] >= self.max_requests:
            raise ValueError("GENERATION_COUNT_LIMIT")
        if body["model"] != MODEL or body["max_tokens"] != 4096:
            raise ValueError("SEALED_MODEL_PARAMETERS_CHANGED")
        key = f"{session}-{state['requests'] + 1:02d}"
        response = self.client.post("/tokenize", json={k: body[k] for k in TOKENIZE_KEYS},
                                    timeout=self.timeout(5))
        response.raise_for_status()
        count = response.json()["count"]
        save(self.root / f"{key}-tokenize.json", {"count": count})
        if count + body["max_tokens"] > self.context:
            raise ValueError("MODEL_CONTEXT_LIMIT")
        raw = wire(body)
        (self.root / f"{key}-request.json").write_bytes(raw)
        append_event(self.ledger, {"event": "RESERVED", "request_id": key, "session": session,
                                  "prompt_tokens": count, "output_cap": body["max_tokens"],
                                  "raw_upper_bound": count + body["max_tokens"],
                                  "payload_sha256": sha(raw), "cumulative_raw_cap": None})
        start = time.monotonic()
        response = self.client.post("/v1/chat/completions", content=raw,
                                    headers={"Content-Type": "application/json"},
                                    timeout=self.timeout(60))
        save(self.root / f"{key}-http.json", {"status_code": response.status_code,
                                             "body": response.text})
        response.raise_for_status()
        value = response.json()
        usage = value.get("usage", {})
        prompt, output = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if (type(prompt) is not int or type(output) is not int or min(prompt, output) < 0
                or usage.get("total_tokens") != prompt + output):
            raise ValueError("USAGE_UNKNOWN_RESERVATION_RETAINED")
        if prompt != count or output > body["max_tokens"]:
            append_event(self.ledger, {"event": "BOUND_VIOLATION", "request_id": key,
                                      "usage": usage})
            raise ValueError("USAGE_BOUND_MISMATCH")
        append_event(self.ledger, {"event": "SETTLED", "request_id": key,
                                  "input_tokens": prompt, "output_tokens": output,
                                  "usage": usage, "seconds": time.monotonic() - start})
        content = value["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("MISSING_VISIBLE_OUTPUT")
        (self.root / f"{key}-visible.txt").write_text(content)
        return content

    def close(self) -> None:
        self.client.close()
