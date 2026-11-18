"""The public benchmark task and the exact Reader packet used by planning and execution."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from string import ascii_uppercase
from typing import Any

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER
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
class ReaderTask:
    source: str
    query: str
    options: tuple[str, ...] = ()
    invalid_reason: str | None = None

    def schema(self) -> dict[str, Any]:
        if self.source == PERSONA:
            fields: dict[str, Any] = {
                "selected_option": {"enum": list(ascii_uppercase[:len(self.options)])}
            }
        else:
            fields = {"answer": {"type": "string"},
                      "evidence": {"type": "array", "items": {"type": "string"}}}
            if self.source == MUSIQUE:
                fields["answerable"] = {"type": "boolean"}
        return {"type": "object", "properties": fields,
                "required": list(fields), "additionalProperties": False}


def reader_task(
    source: str, query: str, task_id: int, annotation: dict[str, Any], option_seed: int,
) -> tuple[ReaderTask, frozenset[str]]:
    if source != PERSONA:
        return ReaderTask(source, query), frozenset()
    wrong, correct = annotation["incorrect_answers"], annotation.get("correct_answer")
    choices = [correct, *wrong] if isinstance(wrong, list) else []
    if (not 2 <= len(choices) <= len(ascii_uppercase)
            or any(not isinstance(text, str) or not text.strip() for text in choices)):
        return ReaderTask(source, query, invalid_reason="invalid_options"), frozenset()
    rng = random.Random(option_seed + task_id)  # noqa: S311 -- fixed public option order
    rng.shuffle(choices)
    # Match the original evaluator even if an identical option text occurs twice.
    correct_letters = frozenset(letter for letter, text in zip(ascii_uppercase, choices)
                                if text == correct)
    return ReaderTask(source, query, tuple(choices)), correct_letters


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
            return PacketPlan(packet, tokens, material_fits, None, None, None,
                              public.invalid_reason)
        payload = {"request": public.query, **({"options": dict(zip(ascii_uppercase, public.options))}
                                              if public.options else {}), "memory": packet}
        wire = {
            "model": self.settings["host"]["model"],
            "temperature": TEMPERATURE,
            "max_tokens": OUTPUT_TOKENS,
            "chat_template_kwargs": {"enable_thinking": ENABLE_THINKING},
            "messages": [
                {"role": "system", "content": self.settings["system_prompt"] + "\n"
                 + _NATIVE_PROMPTS[public.source]},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "native_memory_answer", "schema": public.schema()}},
        }
        host_fits = True
        try:
            check = self.capacity.check(wire["messages"], output_tokens=OUTPUT_TOKENS,
                                        enable_thinking=ENABLE_THINKING)
        except CapacityExceeded as exc:
            check, host_fits = exc.receipt, False
        failure = ("material_budget_exhausted" if not material_fits else
                   "host_request_capacity_exceeded" if not host_fits else None)
        return PacketPlan(packet, tokens, material_fits, wire, check, host_fits, failure)
