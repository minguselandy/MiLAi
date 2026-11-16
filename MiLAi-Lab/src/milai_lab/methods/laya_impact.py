"""Open Jev-compatible Laya decisions for MiLAi's existing Impact stage.

Replaces only root/preserve selection. The Writer, source binding and actual
memory commit stay with MiLAi. A failed request never means no change.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

ModelCall = Callable[[str, list[dict[str, str]], dict[str, Any]], dict[str, Any]]
ReceiptHook = Callable[[dict[str, Any]], None]

CRITERIA = {
    "direct_root": (
        "The new event directly changes, corrects, retracts, or scopes this "
        "existing claim or condition. Reconsider this unit."
    ),
    "preserve_successor": (
        "This unit is related to the event, but its claim remains valid because "
        "its scope is disjoint or an independent support path remains valid."
    ),
    "other": "Neither directly changed nor a specifically preserved successor.",
}


def impact_payload(
    messages: list[dict[str, str]], schema: dict[str, Any],
) -> dict[str, Any]:
    """The identical model input for serving and event-level training exports."""
    supplied = json.loads(messages[-1]["content"])
    aliases = schema["properties"]["roots"]["items"]["enum"]
    state = {"observed_date": supplied["observed_date"], "delivery": supplied["delivery"]}
    # FunctionalEditMemory appends this JSON string to the System instruction.
    # Keep attempt controls distinct from fact evidence for the typed provider too.
    scope_marker = ("\nCurrent maintenance scope (instructions for this attempt, "
                    "not fact evidence):\n")
    for message in messages:
        if message["role"] == "system" and scope_marker in message["content"]:
            state["maintenance_scope"] = json.loads(message["content"].split(scope_marker, 1)[1])
    return {
        "state": state,
        "questions": {
            f"unit_{i}": {
                "type": "choice",
                "instructions": (
                    f"For memory unit {alias}, what is its role under the CURRENT "
                    "new event? Do not infer change solely from topic similarity."
                ),
                "criteria": dict(CRITERIA),
            }
            for i, alias in enumerate(aliases)
        },
    }


def impact_selection(result: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Interpret a saved response without repeating inference or its accounting."""
    if result.get("usage", {}).get("truncated"):
        raise ValueError("Laya impact input was truncated")
    aliases = schema["properties"]["roots"]["items"]["enum"]
    selection: dict[str, list[str]] = {"roots": [], "preserve": []}
    for i, alias in enumerate(aliases):
        label = result["answers"][f"unit_{i}"]["choice"]
        if label == "direct_root":
            selection["roots"].append(alias)
        elif label == "preserve_successor":
            selection["preserve"].append(alias)
        elif label != "other":
            raise ValueError(f"Unrecognized Laya impact category for {alias}: {label}")
    return selection


@dataclass(slots=True)
class LayaImpactClient:
    """Thin client for Laya's POST /v1/systemone endpoint."""

    base_url: str = "http://127.0.0.1:8000"
    model: str = "multilingual"
    timeout_seconds: float = 120.0
    max_len: int = 2048
    head_max_len: int = 256
    api_key: str | None = None
    on_receipt: ReceiptHook | None = None
    http_client: httpx.Client | None = None
    receipts: list[dict[str, Any]] = field(default_factory=list)

    def decide(
        self,
        stage: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {**impact_payload(messages, schema),
                   "model": self.model, "max_len": self.max_len,
                   "head_max_len": self.head_max_len}
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        started = time.perf_counter()
        if self.http_client is not None:
            response = self.http_client.post(
                self.base_url.rstrip("/") + "/v1/systemone",
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        else:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    self.base_url.rstrip("/") + "/v1/systemone",
                    json=payload,
                    headers=headers,
                )
        receipt = {
            "stage": stage, "requested_model": self.model,
            "unit_count": len(payload["questions"]),
            "latency_seconds": time.perf_counter() - started,
            "status_code": response.status_code,
            "response_text": response.text,
        }
        # Persist the actual response before HTTP/JSON/semantic validation.
        self.receipts.append(receipt)
        if self.on_receipt is not None:
            self.on_receipt(receipt)
        response.raise_for_status()
        return impact_selection(response.json(), schema)

    def wrap(self, existing_model_call: ModelCall) -> ModelCall:
        """Route impact and impact:child stages; leave every other stage alone."""

        def wrapped(
            stage: str,
            messages: list[dict[str, str]],
            schema: dict[str, Any],
        ) -> dict[str, Any]:
            if stage.split(":", 1)[0] == "impact":
                return self.decide(stage, messages, schema)
            return existing_model_call(stage, messages, schema)

        return wrapped
