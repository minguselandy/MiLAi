"""The public benchmark task and the exact Reader packet used by planning and execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from string import ascii_uppercase
from typing import Any

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER
from milai_lab.datasets.memory_control_reader_task import ReaderTask
from milai_lab.methods.evidence_control import controlled_reader_packet
from milai_lab.providers.contextual_capacity import CapacityExceeded, HostCapacity

READER_PROTOCOL = "native_packet_reader_v1"
OUTPUT_TOKENS = 512
TEMPERATURE = 0.0
ENABLE_THINKING = False

_NATIVE_PROMPTS = {
    MUSIQUE: (
        "Decide whether the supplied material is sufficient to answer the question. "
        "Set answerable explicitly, give the direct answer if true, and use an empty answer "
        "if false. List only supporting evidence labels from the packet."
    ),
    QASPER: (
        "Give the direct answer. Use Yes or No for binary questions and Unanswerable "
        "when the supplied material cannot answer. List only supporting evidence labels "
        "from the packet."
    ),
    PERSONA: (
        "Choose the single best option using the conversation in the supplied material. "
        "Return its letter in selected_option."
    ),
}


@dataclass(frozen=True)
class PacketPlan:
    packet: dict[str, Any]
    material_tokens: int
    material_fits: bool
    wire: dict[str, Any] | None
    capacity: dict[str, Any] | None
    host_fits: bool | None
    failure_reason: str | None

    @property
    def feasible(self) -> bool | None:
        if not self.material_fits or self.host_fits is False:
            return False
        return self.host_fits


class DatasetReader:
    def __init__(self, config: Path) -> None:
        self.settings = json.loads(config.read_text())["entrypoints"]["functional"]
        self.config_path = config.resolve()
        self.capacity = HostCapacity(self.settings["capacity"])
        if self.settings["host"]["model"] != self.settings["capacity"]["model"]:
            raise ValueError("Reader and capacity tokenizer must describe the same model")
        if OUTPUT_TOKENS > self.capacity.output_tokens:
            raise ValueError("Reader output reserve exceeds the configured Host reserve")

    def plan(self, evidence: list[dict[str, Any]], public: ReaderTask, limit: int) -> PacketPlan:
        packet = controlled_reader_packet(evidence, "policy_handoff")
        serialized = json.dumps(packet, ensure_ascii=False)
        tokens = self.capacity.text_tokens(serialized)
        material_fits = tokens <= limit
        if public.invalid_reason:
            return PacketPlan(
                packet, tokens, material_fits, None, None, None, public.invalid_reason
            )
        payload = {
            "request": public.query,
            **(
                {
                    "options": dict(
                        zip(ascii_uppercase[: len(public.options)], public.options, strict=True)
                    )
                }
                if public.options
                else {}
            ),
            "memory": packet,
        }
        wire = {
            "model": self.settings["host"]["model"],
            "temperature": TEMPERATURE,
            "max_tokens": OUTPUT_TOKENS,
            "chat_template_kwargs": {"enable_thinking": ENABLE_THINKING},
            "messages": [
                {
                    "role": "system",
                    "content": self.settings["system_prompt"]
                    + "\n"
                    + _NATIVE_PROMPTS[public.source],
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "native_memory_answer", "schema": public.schema()},
            },
        }
        host_fits = True
        try:
            check = self.capacity.check(
                wire["messages"], output_tokens=OUTPUT_TOKENS, enable_thinking=ENABLE_THINKING
            )
        except CapacityExceeded as exc:
            check, host_fits = exc.receipt, False
        failure = (
            "material_budget_exhausted"
            if not material_fits
            else "host_request_capacity_exceeded"
            if not host_fits
            else None
        )
        return PacketPlan(packet, tokens, material_fits, wire, check, host_fits, failure)
