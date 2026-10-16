"""One metered Impact boundary shared by the benchmark and ordinary Host."""
from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from urllib.parse import quote

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget
from milai_lab.methods.laya_impact import (
    LayaImpactClient,
    ModelCall,
    impact_payload,
    impact_selection,
)


class MeteredLayaImpactClient(LayaImpactClient):
    def __init__(self, config: dict[str, Any], budget: RunBudget, root: Path,
                 admit: Callable[[], None] | None = None) -> None:
        super().__init__(**config)
        self.budget, self.root, self.admit = budget, root, admit
        self.owner_config = {name: getattr(self, name) for name in (
            "base_url", "model", "max_len", "head_max_len", "timeout_seconds")}

    def decide(self, stage: str, messages: list[dict[str, str]],
               schema: dict[str, Any]) -> dict[str, Any]:
        owner = self.budget.http_owner
        if owner is not None:
            owner.register_client(self, self.budget, self.owner_config)
        context = (owner.request(self, self.budget, self.owner_config, self.base_url,
                   "v1/systemone", self.base_url.rstrip("/") + "/v1/systemone", self.model)
                   if owner is not None else nullcontext())
        try:
            with context:
                return self._decide_recorded(stage, messages, schema)
        finally:
            if owner is not None:
                with owner.closing_client(self):
                    pass

    def _decide_recorded(self, stage: str, messages: list[dict[str, str]],
                         schema: dict[str, Any]) -> dict[str, Any]:
        payload = {**impact_payload(messages, schema), "model": self.model,
                   "max_len": self.max_len, "head_max_len": self.head_max_len}
        folder = self.root / quote(stage, safe="")
        response_path = folder / "response.json"
        if response_path.exists():
            if read_json(folder / "request.json") != payload:
                raise ValueError("Laya replay input changed; use a new event identity")
            receipt = read_json(response_path)
            if receipt["status_code"] != 200:
                raise ValueError(f"Saved Laya HTTP failure: {receipt['status_code']}")
            return impact_selection(json.loads(receipt["response_text"]), schema)
        if (folder / "request.json").exists():
            raise RuntimeError(f"Unconfirmed Laya request: {folder}; do not repeat")
        if self.admit is not None:
            self.admit()
        # Use the existing model-compute budget, including zero-output decisions.
        reservation = self.budget.reserve(
            "systemone", {"messages": messages, "max_tokens": 0},
            generation_input_tokens=self.max_len * len(payload["questions"]),
        )
        write_json(folder / "request.json", payload)

        def receipt_hook(receipt: dict[str, Any]) -> None:
            write_json(response_path, receipt)
            try:
                response = json.loads(receipt["response_text"])
            except json.JSONDecodeError:
                response = {}
            usage = response.get("usage", {})
            tokens = usage.get("input_tokens")
            output = usage.get("output_tokens")
            if isinstance(tokens, int) and isinstance(output, int):
                self.budget.finish(reservation, {"total_tokens": tokens + output})
            self.budget.record_compute("laya_impact", {
                "wall_seconds": receipt["latency_seconds"],
                "requests": 1, "questions": receipt["unit_count"],
                "input_tokens": tokens or 0,
                "usage_unknown": int(tokens is None),
            })

        self.on_receipt = receipt_hook
        selection = super().decide(stage, messages, schema)
        write_json(folder / "selection.json", selection)
        return selection


def impact_model_call(original: ModelCall, settings: dict[str, Any], *,
                      budget: RunBudget, root: Path,
                      admit: Callable[[], None] | None = None) -> ModelCall:
    """Configure once per maintenance boundary; all other stages retain their provider."""
    config = settings.get("laya_impact")
    if config is None:
        return original
    return MeteredLayaImpactClient(config, budget, root, admit).wrap(original)
