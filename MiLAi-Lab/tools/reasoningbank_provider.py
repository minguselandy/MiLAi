"""Native text/tool messages using the existing local Provider usage ledger.

One Provider belongs to one sequential worker. Embedding requests have a separate
ledger and are never counted as free tools or text generations.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from finite_budget_transport import FiniteBudgetTransport
from milai_lab.methods.evidence_utility_session import messages_digest
from milai_lab.methods.reasoning_bank import MemoryCall, MemoryOutputError
from reasoningbank_tool_transport import decode_tool_completion
from replay_v0213_cost import save, sha, wire
from v02_local_provider import accounting, append_event, read_events
from v0213_provider import MODEL, TOKENIZE_KEYS
from workspace_task_provider import Provider as ExistingProvider


class NativeProvider(ExistingProvider):
    def __init__(
        self,
        root: Path,
        *,
        max_tokens: int,
        tool_transport="native_auto",
        request_timeout_seconds=180,
        batch_budget=None,
        **kwargs,
    ):
        if batch_budget is not None:
            kwargs["transport"] = FiniteBudgetTransport(
                batch_budget, kind="text", inner=kwargs.get("transport"), failure_root=root
            )
        super().__init__(root, output_cap=4096, allowed_output_caps=(64, 2048, 4096), **kwargs)
        self.max_total_tokens = max_tokens
        if tool_transport not in {"native_auto", "template_completion"}:
            raise ValueError("UNKNOWN_TOOL_TRANSPORT")
        self.tool_transport = tool_transport
        self.request_timeout_seconds = request_timeout_seconds
        self.unit_limits = None
        self.last_receipt = None

    def task_usage(self, session: str) -> dict:
        rows = [row for row in read_events(self.ledger) if row.get("session") == session]
        reserved = {row["request_id"]: row for row in rows if row["event"] == "RESERVED"}
        settled = {row["request_id"]: row for row in rows if row["event"] == "SETTLED"}
        roles = {}
        for row in settled.values():
            item = roles.setdefault(row["role"], {"requests": 0, "tokens": 0})
            item["requests"] += 1
            item["tokens"] += row["input_tokens"] + row["output_tokens"]
        unknown = reserved.keys() - settled.keys()
        return {
            "settled_requests": len(settled),
            "settled_tokens": sum(x["tokens"] for x in roles.values()),
            "unknown_requests": len(unknown),
            "unknown_token_upper_bound": sum(reserved[k]["raw_upper_bound"] for k in unknown),
            "roles": roles,
            "ledger": str(self.ledger),
        }

    def begin_unit(self, limits: dict | None) -> None:
        """Reset the declared task/group allowance within a bounded stream."""
        state = accounting(read_events(self.ledger))
        self.unit_limits = limits
        self.unit_start = (state["requests"], state["raw_tokens"], time.monotonic())

    def count_text(self, text: str) -> int:
        result = self.client.post(
            "/tokenize",
            json={"model": MODEL, "prompt": text, "add_special_tokens": False},
            timeout=self.timeout(10),
        )
        result.raise_for_status()
        return result.json()["count"]

    def count_messages(self, messages, tools=None) -> int:
        body = {
            "model": MODEL,
            "messages": list(messages),
            "chat_template_kwargs": {"enable_thinking": False},
            "add_generation_prompt": True,
            "add_special_tokens": False,
        }
        if tools:
            body["tools"] = tools
        result = self.client.post("/tokenize", json=body, timeout=self.timeout(10))
        result.raise_for_status()
        return result.json()["count"]

    def generate_message(
        self,
        session: str,
        messages: list[dict],
        *,
        role: str = "actor",
        tools: list[dict] | None = None,
        output_tokens: int = 4096,
        temperature: float = 0.0,
        json_output: bool = False,
    ) -> dict:
        self.last_receipt = None
        if role not in {
            "actor",
            "self_judge",
            "extract",
            "adopt",
            "revise",
            "observer",
            "reflector",
            "memrl_script",
            "memrl_reflection",
        }:
            raise ValueError("UNKNOWN_RESEARCH_ROLE")
        state = accounting(read_events(self.ledger))
        if state["pending"] or state["violations"]:
            raise ValueError("UNSETTLED_USAGE_NO_RETRY")
        if state["requests"] >= self.max_requests:
            raise ValueError("GENERATION_COUNT_LIMIT")
        if output_tokens not in self.allowed_output_caps:
            raise ValueError("ROLE_OUTPUT_CAP_CHANGED")
        body = {
            "model": MODEL,
            "messages": messages,
            "max_tokens": output_tokens,
            "temperature": temperature,
            "top_p": 1,
            "seed": 213,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "add_generation_prompt": True,
            "add_special_tokens": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_output:
            body["response_format"] = {"type": "json_object"}
        token_body = {key: body[key] for key in TOKENIZE_KEYS}
        if tools:
            token_body["tools"] = tools
        token_response = self.client.post("/tokenize", json=token_body, timeout=self.timeout(10))
        token_response.raise_for_status()
        tokenized = token_response.json()
        count = tokenized["count"]
        if count + output_tokens > self.context:
            raise ValueError("MODEL_CONTEXT_LIMIT")
        # The inherited ledger's settled raw token sum is authoritative.
        used = sum(
            row["input_tokens"] + row["output_tokens"]
            for row in read_events(self.ledger)
            if row["event"] == "SETTLED"
        )
        if used + count + output_tokens > self.max_total_tokens:
            raise ValueError("TOTAL_TOKEN_LIMIT")
        if self.unit_limits:
            requests, tokens, started = self.unit_start
            if state["requests"] - requests >= self.unit_limits["max_requests"]:
                raise ValueError("UNIT_GENERATION_LIMIT")
            if used - tokens + count + output_tokens > self.unit_limits["max_tokens"]:
                raise ValueError("UNIT_TOKEN_LIMIT")
            if time.monotonic() - started >= self.unit_limits["wall_seconds"]:
                raise ValueError("UNIT_TIME_LIMIT")
        key = f"{state['requests'] + 1:06d}-{role}"
        endpoint = "/v1/chat/completions"
        completion_transport = tools and self.tool_transport == "template_completion"
        if completion_transport:
            save(self.root / f"{key}-native-chat.json", body)
            save(self.root / f"{key}-tokenize.json", tokenized)
            body = {
                "model": MODEL,
                "prompt": tokenized["tokens"],
                "max_tokens": output_tokens,
                "temperature": temperature,
                "top_p": 1,
                "seed": 213,
                "stream": False,
                "add_special_tokens": False,
            }
            endpoint = "/v1/completions"
        raw = wire(body)
        (self.root / f"{key}-request.json").write_bytes(raw)
        append_event(
            self.ledger,
            {
                "event": "RESERVED",
                "request_id": key,
                "session": session,
                "role": role,
                "prompt_tokens": count,
                "output_cap": output_tokens,
                "raw_upper_bound": count + output_tokens,
                "payload_sha256": sha(raw),
                "cumulative_raw_cap": self.max_total_tokens,
                "transport": "template_completion" if completion_transport else "chat",
            },
        )
        start = time.monotonic()
        response = self.client.post(
            endpoint,
            content=raw,
            headers={"Content-Type": "application/json"},
            timeout=self.timeout(self.request_timeout_seconds),
            extensions={
                "milai_batch_reservation": {
                    "upper_tokens": count + output_tokens,
                    "role": role,
                }
            },
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
        if prompt != count or output > output_tokens:
            append_event(
                self.ledger, {"event": "BOUND_VIOLATION", "request_id": key, "usage": usage}
            )
            raise ValueError("USAGE_BOUND_MISMATCH")
        append_event(
            self.ledger,
            {
                "event": "SETTLED",
                "request_id": key,
                "role": role,
                "session": session,
                "input_tokens": prompt,
                "output_tokens": output,
                "usage": usage,
                "seconds": time.monotonic() - start,
            },
        )
        if completion_transport:
            message = decode_tool_completion(value["choices"][0]["text"], tools, key)
        else:
            message = value["choices"][0]["message"]
        save(self.root / f"{key}-message.json", message)
        self.last_receipt = {
            "session": session,
            "role": role,
            "status": "SETTLED",
            "request_id": key,
            "payload_sha256": sha(raw),
            "messages_sha256": messages_digest(messages),
        }
        return message

    def memory_call(self, session: str, call: MemoryCall) -> str:
        try:
            message = self.generate_message(
                session,
                list(call.messages),
                role=call.role,
                output_tokens=call.output_tokens,
                temperature=call.temperature,
                json_output=call.json_output,
            )
        except ValueError as error:
            # These checks run before reservation or HTTP generation. Unknown
            # usage and transport failures still propagate and stop the worker.
            if str(error) in {
                "MODEL_CONTEXT_LIMIT",
                "TOTAL_TOKEN_LIMIT",
                "GENERATION_COUNT_LIMIT",
                "UNIT_GENERATION_LIMIT",
                "UNIT_TOKEN_LIMIT",
                "UNIT_TIME_LIMIT",
            }:
                raise MemoryOutputError(str(error)) from error
            raise
        if not isinstance(message.get("content"), str):
            raise MemoryOutputError("NO_VISIBLE_MAINTENANCE_TEXT")
        return message["content"]


class EmbeddingProvider:
    def __init__(
        self,
        root: Path,
        *,
        max_requests: int = 512,
        batch_budget=None,
        token_upper_bound=None,
        transport=None,
    ):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.max_requests = max_requests
        self.ledger = root / "embedding-ledger.jsonl"
        self.batch_budget = batch_budget
        self.token_upper_bound = token_upper_bound
        if batch_budget is not None:
            if token_upper_bound is None:
                raise ValueError("VERIFIED_EMBEDDING_TOKEN_BOUND_REQUIRED")
            transport = FiniteBudgetTransport(
                batch_budget, kind="embedding", inner=transport, failure_root=root
            )
        self.client = httpx.Client(
            base_url="http://36.140.33.19:7861",
            timeout=60,
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )

    def embed(self, session: str, texts: list[str]) -> list[list[float]]:
        upper = self.token_upper_bound(texts) if self.batch_budget is not None else None
        rows = read_events(self.ledger)
        reserved = {row["request_id"] for row in rows if row["event"] == "RESERVED"}
        settled = {row["request_id"] for row in rows if row["event"] == "SETTLED"}
        if reserved != settled:
            raise ValueError("UNSETTLED_EMBEDDING_USAGE_NO_RETRY")
        if len(reserved) >= self.max_requests:
            raise ValueError("EMBEDDING_REQUEST_LIMIT")
        key = f"embedding-{len(reserved) + 1:06d}"
        body = {"model": "bge-m3", "input": texts, "encoding_format": "float"}
        save(self.root / f"{key}-request.json", body)
        append_event(
            self.ledger,
            {
                "event": "RESERVED",
                "request_id": key,
                "session": session,
                "kind": "EMBEDDING",
                "input_count": len(texts),
                "input_sha256": sha(wire(body)),
            },
        )
        start = time.monotonic()
        response = self.client.post(
            "/v1/embeddings",
            json=body,
            extensions={"milai_batch_reservation": {"upper_tokens": upper}},
        )
        save(
            self.root / f"{key}-http.json",
            {"status_code": response.status_code, "body": response.text},
        )
        response.raise_for_status()
        value = response.json()
        usage = value.get("usage")
        if not isinstance(usage, dict) or type(usage.get("total_tokens")) is not int:
            raise ValueError("EMBEDDING_USAGE_UNKNOWN")
        append_event(
            self.ledger,
            {
                "event": "SETTLED",
                "request_id": key,
                "session": session,
                "kind": "EMBEDDING",
                "usage": usage,
                "seconds": time.monotonic() - start,
            },
        )
        data = value["data"]
        if value.get("model") != "bge-m3" or sorted(row["index"] for row in data) != list(
            range(len(texts))
        ):
            raise ValueError("EMBEDDING_RESPONSE_IDENTITY_MISMATCH")
        return [row["embedding"] for row in sorted(data, key=lambda row: row["index"])]

    def close(self):
        self.client.close()
