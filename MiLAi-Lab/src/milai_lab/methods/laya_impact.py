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


@dataclass(slots=True)
class LayaImpactClient:
    """Thin client for Laya's POST /v1/systemone endpoint."""

    base_url: str = "http://127.0.0.1:8000"
    model: str = "multilingual"
    timeout_seconds: float = 120.0
    max_len: int = 4096
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
        # These aliases come from the real MiLAi impact_request schema.
        aliases: list[str] = list(schema["properties"]["roots"]["items"]["enum"])
        supplied = json.loads(messages[-1]["content"])
        state = {
            "observed_date": supplied["observed_date"],
            "delivery": supplied["delivery"],
        }
        questions = {
            f"unit_{i}": {
                "type": "choice",
                "instructions": (
                    f"For memory unit {alias}, what is its role under the CURRENT "
                    "new event? Do not infer change solely from topic similarity."
                ),
                "criteria": CRITERIA,
            }
            for i, alias in enumerate(aliases)
        }
        payload = {
            "state": state,
            "questions": questions,
            "model": self.model,
            "max_len": self.max_len,
        }
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
        response.raise_for_status()
        result = response.json()
        answers = result["answers"]
        selection: dict[str, list[str]] = {"roots": [], "preserve": []}
        for i, alias in enumerate(aliases):
            label = answers[f"unit_{i}"]["choice"]
            if label == "direct_root":
                selection["roots"].append(alias)
            elif label == "preserve_successor":
                selection["preserve"].append(alias)
            elif label != "other":
                raise ValueError(f"Unrecognized Laya impact category for {alias}: {label}")
        receipt = {
            "stage": stage,
            "model": result.get("model", self.model),
            "unit_count": len(aliases),
            "usage": result.get("usage", {}),
            "latency_seconds": time.perf_counter() - started,
            "answers": {alias: answers[f"unit_{i}"] for i, alias in enumerate(aliases)},
            "selection": selection,
        }
        self.receipts.append(receipt)
        if self.on_receipt is not None:
            self.on_receipt(receipt)
        return selection

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
