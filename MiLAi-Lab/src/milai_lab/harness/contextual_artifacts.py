"""Local run identities, atomic artifacts, and contextual request traces."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any


class BudgetExceeded(RuntimeError):
    """The fixed run cannot admit another request within its remaining budget."""


@dataclass(frozen=True)
class RunLimits:
    questions: int = 12
    arms: int = 3
    generation_requests: int | None = 160
    generation_tokens: int | None = 1_000_000
    embedding_tokens: int | None = 2_000_000


class RunBudget:
    """One persisted budget shared by the run's Host, embedding and Judge clients.

    UTF-8 bytes plus message framing conservatively estimate incoming tokens; unknown
    usage keeps that reservation, including maximum output, rather than becoming zero.
    Reservations are saved before sending, so an interrupted request remains charged.
    """

    def __init__(self, limits: RunLimits, path: Path) -> None:
        self.limits, self.path, self.lock = limits, path, Lock()
        self.state: dict[str, Any] = {
            "limits": asdict(limits),
            "generation_requests": 0,
            "generation": {"charged_tokens": 0, "known_tokens": 0, "unknown_usage": 0},
            "embedding": {"charged_tokens": 0, "known_tokens": 0, "unknown_usage": 0},
        }
        if path.exists():
            self.state = read_json(path)
            if self.state["limits"] != asdict(limits):
                raise ValueError("Run budget limits changed on resume")

    def reserve(
        self, path: str, request: dict[str, Any], *,
        generation_holdback_tokens: int = 0, generation_holdback_requests: int = 0,
        generation_input_tokens: int | None = None,
    ) -> tuple[str, int]:
        if (type(generation_holdback_tokens) is not int or generation_holdback_tokens < 0
                or type(generation_holdback_requests) is not int
                or generation_holdback_requests < 0):
            raise ValueError("INVALID_GENERATION_HOLDBACK")
        if (generation_input_tokens is not None
                and (type(generation_input_tokens) is not int or generation_input_tokens < 0)):
            raise ValueError("INVALID_GENERATION_INPUT_TOKENS")
        kind = "embedding" if path == "embeddings" else "generation"
        if kind == "embedding":
            estimate = sum(
                len(item.encode()) + 2 if isinstance(item, str) else len(item)
                for item in request["input"]
            )
            cap = self.limits.embedding_tokens
        else:
            estimate = (
                (generation_input_tokens if generation_input_tokens is not None else
                 len(json.dumps(request, ensure_ascii=False).encode())
                 + 32 * len(request["messages"]))
                + request["max_tokens"]
            )
            cap = self.limits.generation_tokens
        with self.lock:
            if (
                kind == "generation"
                and self.limits.generation_requests is not None
                and self.state["generation_requests"] + 1 + generation_holdback_requests
                > self.limits.generation_requests
            ):
                raise BudgetExceeded("Generation request budget cannot preserve holdback")
            held = generation_holdback_tokens if kind == "generation" else 0
            if cap is not None and self.state[kind]["charged_tokens"] + estimate + held > cap:
                raise BudgetExceeded(f"{kind} token budget cannot fit next request reservation")
            if kind == "generation":
                self.state["generation_requests"] += 1
            self.state[kind]["charged_tokens"] += estimate
            self.state[kind]["unknown_usage"] += 1
            write_json(self.path, self.state)
        return kind, estimate

    def finish(self, reservation: tuple[str, int], usage: Any) -> None:
        total = usage.get("total_tokens") if isinstance(usage, dict) else None
        if type(total) is not int:
            return
        kind, estimate = reservation
        with self.lock:
            self.state[kind]["charged_tokens"] += total - estimate
            self.state[kind]["known_tokens"] += total
            self.state[kind]["unknown_usage"] -= 1
            write_json(self.path, self.state)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


class Trace:
    def __init__(self, path: Path, stage: str) -> None:
        self.path, self.stage = path, stage
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.usage: list[dict[str, Any]] = []
        self.redacted = False

    @staticmethod
    def _minimal(event: dict[str, Any]) -> dict[str, Any]:
        """Keep accounting and deletion receipts without retaining model or source text."""
        minimal = {key: event[key] for key in ("stage", "event") if key in event}
        kind = event["event"]
        if kind in {"vllm_response", "vllm_error", "vllm_capacity_rejected"}:
            minimal.update(
                {key: event[key] for key in (
                    "path", "usage", "wall_seconds", "http_status", "capacity",
                    "capacity_comparison",
                )
                 if key in event}
            )
            if isinstance(event.get("exception"), dict):
                minimal["exception"] = {"type": event["exception"].get("type")}
        elif kind == "embedding_cache":
            minimal.update(
                {key: event[key] for key in ("cold_input_tokens", "hits") if key in event}
            )
        elif kind in {"local_execution", "host_dispatch", "material_delivery",
                      "ingestion_settlement"}:
            minimal.update({key: value for key, value in event.items()
                            if type(value) in {int, float, bool}})
        elif kind == "host_tool_call":
            call = event["call"]
            result = call.get("result", {})
            minimal["call"] = {
                "name": call.get("name"), "ok": call.get("ok"),
                "reused": call.get("reused", False),
                "result": {key: result[key] for key in ("status", "refs") if key in result},
            }
        return minimal

    def redact(self) -> None:
        """Atomically remove earlier bodies and keep later events in minimal form."""
        self.redacted = True
        if self.path.exists():
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            with self.path.open() as source, temporary.open("w") as target:
                for line in source:
                    try:
                        event = self._minimal(json.loads(line))
                    except json.JSONDecodeError:
                        # An interrupted append cannot be restored as a complete receipt.
                        continue
                    target.write(json.dumps(event, ensure_ascii=False) + "\n")
            temporary.replace(self.path)
        self.usage = [self._minimal(item) for item in self.usage]

    def __call__(self, event: dict[str, Any]) -> None:
        if self.redacted:
            event = self._minimal(event)
        if event["event"] in {"vllm_response", "vllm_error", "vllm_capacity_rejected"}:
            self.usage.append(
                {
                    key: event.get(key)
                    for key in (
                        "event", "path", "usage", "wall_seconds", "exception",
                        "capacity", "capacity_comparison",
                    )
                }
            )
        with self.path.open("a") as stream:
            stream.write(json.dumps({"stage": self.stage, **event}, ensure_ascii=False) + "\n")
