"""Durable finite admission for an opt-in functional queue, above the cost ledger.

Reservations are retained after unknown outcomes and process death. This is a
safety quota, not another usage ledger: actual usage stays in RunBudget.
"""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from pathlib import Path
from typing import Any

from milai_lab.harness.contextual_artifacts import BudgetExceeded
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient


class FunctionalQueue:
    def __init__(self, path: Path, *, requests: int, reserved_tokens: int) -> None:
        if type(requests) is not int or requests <= 0:
            raise ValueError("FUNCTIONAL_QUEUE_REQUEST_LIMIT_INVALID")
        if type(reserved_tokens) is not int or reserved_tokens <= 0:
            raise ValueError("FUNCTIONAL_QUEUE_TOKEN_LIMIT_INVALID")
        self.path = path
        self.limits = {"requests": requests, "reserved_tokens": reserved_tokens}

    def reserve(self, request: dict[str, Any], capacity: dict[str, Any]) -> None:
        tokens = capacity["total_reserved_tokens"]
        if type(tokens) is not int or tokens <= 0:
            raise ValueError("FUNCTIONAL_QUEUE_CAPACITY_REQUIRED")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state: dict[str, Any] = (
                json.loads(self.path.read_text())
                if self.path.exists()
                else {
                    "schema": "functional_queue_v1",
                    "limits": self.limits,
                    "requests": 0,
                    "reserved_tokens": 0,
                    "reservations": [],
                }
            )
            if state["limits"] != self.limits or state["schema"] != "functional_queue_v1":
                raise ValueError("FUNCTIONAL_QUEUE_CONFIGURATION_CHANGED")
            if (
                type(state.get("requests")) is not int
                or state["requests"] < 0
                or type(state.get("reserved_tokens")) is not int
                or state["reserved_tokens"] < 0
                or not isinstance(state.get("reservations"), list)
                or len(state["reservations"]) != state["requests"]
            ):
                raise ValueError("FUNCTIONAL_QUEUE_STATE_INVALID")
            for ordinal, row in enumerate(state["reservations"], start=1):
                if (
                    not isinstance(row, dict)
                    or row.get("ordinal") != ordinal
                    or type(row.get("reserved_tokens")) is not int
                    or row["reserved_tokens"] <= 0
                    or not isinstance(row.get("attempt_id", row.get("request_sha256")), str)
                ):
                    raise ValueError("FUNCTIONAL_QUEUE_RESERVATION_INVALID")
            if (
                sum(row["reserved_tokens"] for row in state["reservations"])
                != state["reserved_tokens"]
            ):
                raise ValueError("FUNCTIONAL_QUEUE_TOTAL_CHANGED")
            if (
                state["requests"] + 1 > self.limits["requests"]
                or state["reserved_tokens"] + tokens > self.limits["reserved_tokens"]
            ):
                raise BudgetExceeded("FUNCTIONAL_QUEUE_BUDGET_EXHAUSTED")
            state["requests"] += 1
            state["reserved_tokens"] += tokens
            state["reservations"].append(
                {
                    "ordinal": state["requests"],
                    "reserved_tokens": tokens,
                    "attempt_id": str(uuid.uuid4()),
                }
            )
            temporary = self.path.with_suffix(".tmp")
            with temporary.open("w") as stream:
                json.dump(state, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


class FunctionalVLLMClient(VLLMClient):
    """Use unchanged provider accounting, ownership and exact request capacity."""

    queue: FunctionalQueue
    declaration_capacity: HostCapacity | None = None
    declaration_tool_names: frozenset[str] = frozenset()
    declaration_temperature: float | None = None

    def _post(
        self, path: str, request: dict[str, Any], *, capacity_receipt: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if path != "chat/completions" or capacity_receipt is None:
            raise ValueError("FUNCTIONAL_GENERATION_CAPACITY_REQUIRED")
        self._check_owner()
        catalog = request.get("tools", [])
        if (
            self.declaration_capacity is not None
            and request.get("tool_choice") in ("auto", "required")
            and len(catalog) == 1
            and catalog[0].get("function", {}).get("name") in self.declaration_tool_names
        ):
            # Runner opts in exact public declaration phases. The initial host
            # check remains conservative; recompute the actual final wire template
            # before queue reservation, accounting or HTTP. No second model/cap.
            if self.declaration_capacity.enable_thinking is not False:
                raise ValueError("FUNCTIONAL_DECLARATION_CAPACITY_MUST_DISABLE_THINKING")
            request = {**request, "chat_template_kwargs": {"enable_thinking": False}}
            if self.declaration_temperature is not None:
                request["temperature"] = self.declaration_temperature
            capacity_receipt = self.declaration_capacity.check(
                request["messages"], self.config.max_tokens, catalog
            )
        self.queue.reserve(request, capacity_receipt)
        return super()._post(path, request, capacity_receipt=capacity_receipt)
