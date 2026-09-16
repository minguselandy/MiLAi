"""Task-local adaptation of the existing v0213 HTTP client and accounting.

The inherited verify/timeout/close are unchanged. Generation adds configurable
output capacity and local/server tokenizer agreement; historical Provider source
stays byte-identical because frozen studies pin it. No admission stack or retries.
"""

from __future__ import annotations

import time

from replay_v0213_cost import save, sha, wire
from v02_local_provider import accounting, append_event, read_events
from v0213_provider import MODEL, TOKENIZE_KEYS
from v0213_provider import Provider as ExistingProvider


class Provider(ExistingProvider):
    def __init__(self, *args, output_cap=2048, allowed_output_caps=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_cap = output_cap
        self.allowed_output_caps = frozenset(allowed_output_caps or (output_cap,))
        if output_cap not in self.allowed_output_caps or any(
            type(n) is not int or not 1 <= n <= output_cap for n in self.allowed_output_caps
        ):
            raise ValueError("INVALID_ROLE_OUTPUT_CAPS")
        self.http_events = self.root / "http-events.jsonl"
        self.http_sequence = len(
            [r for r in read_events(self.http_events) if r["event"] == "HTTP_STARTED"]
        )
        self.client.event_hooks["request"].append(self._http_started)
        self.client.event_hooks["response"].append(self._http_returned)

    def _http_started(self, request):
        self.http_sequence += 1
        request.extensions["lab_http_id"] = self.http_sequence
        request.extensions["lab_http_start"] = time.monotonic()
        append_event(
            self.http_events,
            {
                "event": "HTTP_STARTED",
                "http_id": self.http_sequence,
                "method": request.method,
                "path": request.url.path,
                "started_monotonic": request.extensions["lab_http_start"],
            },
        )

    def _http_returned(self, response):
        request = response.request
        append_event(
            self.http_events,
            {
                "event": "HTTP_RETURNED",
                "http_id": request.extensions["lab_http_id"],
                "path": request.url.path,
                "status_code": response.status_code,
                "header_seconds": time.monotonic() - request.extensions["lab_http_start"],
            },
        )

    def generate(
        self,
        session: str,
        body: dict,
        *,
        expected_prompt_tokens: int | None = None,
    ) -> str:
        state = accounting(read_events(self.ledger))
        if state["pending"] or state["violations"]:
            raise ValueError("UNSETTLED_USAGE_NO_RETRY")
        if state["requests"] >= self.max_requests:
            raise ValueError("GENERATION_COUNT_LIMIT")
        if body["model"] != MODEL or body["max_tokens"] not in self.allowed_output_caps:
            raise ValueError("SEALED_MODEL_PARAMETERS_CHANGED")
        key = f"{session}-{state['requests'] + 1:02d}"
        response = self.client.post(
            "/tokenize", json={k: body[k] for k in TOKENIZE_KEYS}, timeout=self.timeout(5)
        )
        response.raise_for_status()
        count = response.json()["count"]
        save(self.root / f"{key}-tokenize.json", {"count": count})
        if expected_prompt_tokens is not None and count != expected_prompt_tokens:
            raise ValueError("LOCAL_SERVER_TOKENIZER_DISAGREEMENT")
        if count + body["max_tokens"] > self.context:
            raise ValueError("MODEL_CONTEXT_LIMIT")
        raw = wire(body)
        (self.root / f"{key}-request.json").write_bytes(raw)
        append_event(
            self.ledger,
            {
                "event": "RESERVED",
                "request_id": key,
                "session": session,
                "prompt_tokens": count,
                "output_cap": body["max_tokens"],
                "raw_upper_bound": count + body["max_tokens"],
                "payload_sha256": sha(raw),
                "cumulative_raw_cap": None,
            },
        )
        start = time.monotonic()
        response = self.client.post(
            "/v1/chat/completions",
            content=raw,
            headers={"Content-Type": "application/json"},
            timeout=self.timeout(60),
        )
        save(
            self.root / f"{key}-http.json",
            {"status_code": response.status_code, "body": response.text},
        )
        response.raise_for_status()
        value = response.json()
        usage = value.get("usage", {})
        prompt, output = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if (
            type(prompt) is not int
            or type(output) is not int
            or min(prompt, output) < 0
            or usage.get("total_tokens") != prompt + output
        ):
            raise ValueError("USAGE_UNKNOWN_RESERVATION_RETAINED")
        if prompt != count or output > body["max_tokens"]:
            append_event(
                self.ledger, {"event": "BOUND_VIOLATION", "request_id": key, "usage": usage}
            )
            raise ValueError("USAGE_BOUND_MISMATCH")
        append_event(
            self.ledger,
            {
                "event": "SETTLED",
                "request_id": key,
                "input_tokens": prompt,
                "output_tokens": output,
                "usage": usage,
                "seconds": time.monotonic() - start,
            },
        )
        content = value["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("MISSING_VISIBLE_OUTPUT")
        (self.root / f"{key}-visible.txt").write_text(content)
        return content
