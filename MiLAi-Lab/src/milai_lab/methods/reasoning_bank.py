"""Query-indexed ReasoningBank base port for native benchmark agents.

Reference: google-research/reasoning-bank@ed80611788292ea739f1effd31f16c53823b8a0d.
Local policies and embedding substitutions are recorded under configs/policies/reasoning_bank.
The native agent owns business actions and delivery. This module owns only working memory.
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from milai_lab.methods.controlled_workspace import MemoryCard
from milai_lab.methods.experience_utility import VersionUtility

METHOD_VERSION = "reasoningbank-base-port-v0.3"
BANK_FORMAT = "milai-experience-bank-v1"


class MemoryOutputError(ValueError):
    """A settled maintenance response could not be applied."""


@dataclass(frozen=True)
class MemoryCall:
    role: str
    messages: tuple[dict[str, str], ...]
    output_tokens: int
    temperature: float
    json_output: bool = False


@dataclass(frozen=True)
class BankConfig:
    embedding_model: str = "bge-m3"
    embedding_dimension: int = 1024
    encoding_version: str = "bge-query-instruct-cosine-v1"
    top_k: int = 1
    max_extracted_items: int = 3
    judge_output_tokens: int = 64
    extract_output_tokens: int = 2048
    maintenance_output_tokens: int = 2048
    read_chars: int = 4000


def normalized(vector: list[float], dimension: int) -> list[float]:
    if len(vector) != dimension or any(not math.isfinite(x) for x in vector):
        raise ValueError("EMBEDDING_CONTRACT_MISMATCH")
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise ValueError("ZERO_EMBEDDING")
    return [x / norm for x in vector]


def parse_memory_items(raw: str, maximum: int = 3) -> list[str]:
    """Split logical items, preserving body text and nonstandard field names.

    The reference stores raw Markdown fragments, not a validated Title schema.
    Logical item identifiers enable revision without rewriting model output.
    """
    blocks = re.split(r"(?mi)^# Memory Item\s+\d+\s*$", raw.strip())
    if len(blocks) < 2 or len(blocks) - 1 > maximum:
        raise MemoryOutputError("INVALID_EXTRACTED_MEMORY_ITEMS")
    result = []
    for block in blocks[1:]:
        text = block.strip().removesuffix("```").strip()
        if not text:
            raise MemoryOutputError("EMPTY_EXTRACTED_MEMORY_ITEM")
        result.append(text)
    return result


@dataclass
class ExperienceBank:
    scope: dict[str, str]
    contract: dict[str, Any]
    cards: dict[str, MemoryCard] = field(default_factory=dict)
    records: list[dict[str, Any]] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    historical_cards: dict[str, dict[str, Any]] = field(default_factory=dict)
    revision: int = 0
    next_card: int = 1
    next_source: int = 1
    completed_tasks: list[str] = field(default_factory=list)
    # Optional Lab-only, version-bound evidence; legacy banks keep their wire shape.
    utility_state: dict[str, Any] = field(default_factory=dict)

    def source(self, text: str) -> str:
        ref = f"source:{self.next_source}"
        self.next_source += 1
        self.sources[ref] = text
        return ref

    def checkpoint(self) -> dict[str, Any]:
        value = {"format": BANK_FORMAT, **copy.deepcopy(asdict(self))}
        if not self.utility_state:
            value.pop("utility_state")
        return value

    @classmethod
    def restore(
        cls, value: dict[str, Any], *, scope: dict[str, str], contract: dict[str, Any]
    ) -> ExperienceBank:
        if (
            value.get("format") != BANK_FORMAT
            or value.get("scope") != scope
            or value.get("contract") != contract
        ):
            raise ValueError("BANK_CHECKPOINT_BINDING_MISMATCH")
        data = copy.deepcopy(value)
        del data["format"]
        data["cards"] = {key: MemoryCard(**card) for key, card in data["cards"].items()}
        bank = cls(**data)
        for handle, card in bank.cards.items():
            if card.handle != handle or not set(card.source_refs) <= bank.sources.keys():
                raise ValueError("BANK_SOURCE_BINDING_MISMATCH")
        dimension = contract["config"]["embedding_dimension"]
        for record in bank.records:
            normalized(record["embedding"], dimension)
            if not set(record["handles"]) <= bank.cards.keys():
                raise ValueError("BANK_RECORD_BINDING_MISMATCH")
        if bank.utility_state:
            VersionUtility(bank.utility_state).validate(
                bank.cards, bank.historical_cards, bank.completed_tasks
            )
        return bank

    def fork(self, scope: dict[str, str]) -> ExperienceBank:
        """Explicitly copy a support artifact into an isolated task/stream work scope."""
        if any(
            scope.get(key) != self.scope.get(key)
            for key in ("experiment", "method", "model", "domain", "method_version")
        ):
            raise ValueError("CROSS_EXPERIMENT_OR_METHOD_BANK_FORK")
        value = self.checkpoint()
        value["scope"] = dict(scope)
        return self.restore(value, scope=scope, contract=self.contract)

    def select(self, vector: list[float], config: BankConfig) -> list[str]:
        query = normalized(vector, config.embedding_dimension)
        scored = [
            (sum(a * b for a, b in zip(query, record["embedding"], strict=True)), index)
            for index, record in enumerate(self.records)
        ]
        scored.sort(key=lambda item: -item[0])
        return [
            handle
            for _, index in scored[: config.top_k]
            for handle in self.records[index]["handles"]
            if not self.cards[handle].retired
        ]


class ReasoningBankSession:
    method_version = METHOD_VERSION

    def __init__(
        self,
        *,
        bank: ExperienceBank,
        config: BankConfig,
        policies: dict[str, str],
        generate: Callable[[MemoryCall], str],
        embed: Callable[[list[str]], list[list[float]]],
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.bank, self.config, self.policies = bank, config, dict(policies)
        self.generate, self.embed, self.emit = generate, embed, emit
        self.working = copy.deepcopy(bank)
        self.active = False
        self.task_id = ""
        self.query = ""
        self.query_vector: list[float] = []
        self.selected: list[str] = []
        self.feedback_refs: list[str] = []
        self.base_revision = bank.revision

    @staticmethod
    def contract(config: BankConfig, policies: dict[str, str]) -> dict[str, Any]:
        return {
            "config": asdict(config),
            "policy_sha256": {
                key: hashlib.sha256(text.encode()).hexdigest() for key, text in policies.items()
            },
            "base_algorithm": METHOD_VERSION,
        }

    def _event(self, event: str, **fields: Any) -> None:
        if self.emit:
            self.emit({"event": event, "task_id": self.task_id, **fields})

    def start(self, task_id: str, query: str) -> None:
        if self.active or task_id in self.bank.completed_tasks:
            raise ValueError("TASK_ALREADY_ACTIVE_OR_COMMITTED")
        if self.bank.contract != self.contract(self.config, self.policies):
            raise ValueError("METHOD_POLICY_OR_EMBEDDING_CHANGED")
        if self.bank.scope.get("method_version", self.method_version) != self.method_version:
            raise ValueError("BANK_METHOD_IMPLEMENTATION_CHANGED")
        self.working = copy.deepcopy(self.bank)
        self.base_revision = self.bank.revision
        self.task_id, self.query = task_id, query
        texts = [query]
        if self.bank.records:
            texts.append(
                f"Instruct: {self.policies['retrieval_instruction'].strip()}\nQuery: {query}"
            )
        vectors = self.embed(texts)
        if len(vectors) != len(texts):
            raise ValueError("EMBEDDING_BATCH_MISMATCH")
        self.query_vector = normalized(vectors[0], self.config.embedding_dimension)
        self.selected = self.bank.select(vectors[1], self.config) if len(vectors) == 2 else []
        self.feedback_refs = []
        self.active = True
        self.observe("query", query)
        self._event(
            "MEMORY_RETRIEVED",
            handles=self.selected,
            revisions={handle: self.working.cards[handle].revision for handle in self.selected},
            bank_revision=self.bank.revision,
        )

    def observe(self, kind: str, text: str) -> str:
        if not self.active:
            raise ValueError("NO_ACTIVE_MEMORY_TASK")
        ref = self.working.source(f"{kind}:\n{text}")
        self.feedback_refs.append(ref)
        self._event("MEMORY_SOURCE_ADDED", ref=ref, kind=kind)
        return ref

    def memory_context(self) -> str:
        return self._render_memory_context(self.selected)

    def _render_memory_context(self, handles: list[str]) -> str:
        if not handles:
            return ""
        cards = [self.working.cards[handle] for handle in handles]
        material = "\n\n".join(
            f"[{card.handle} revision={card.revision}; sources={','.join(card.source_refs)}]\n"
            + card.text
            for card in cards
            if not card.retired
        )
        self._event("MEMORY_PROJECTED", revisions={card.handle: card.revision for card in cards})
        return self.policies["consume"].strip() + "\n\n" + material

    def read(self, ref: str, start: int = 0, length: int | None = None) -> dict[str, Any]:
        length = self.config.read_chars if length is None else length
        if (
            type(start) is not int
            or type(length) is not int
            or start < 0
            or not 1 <= length <= 16000
        ):
            raise ValueError("INVALID_MEMORY_SOURCE_RANGE")
        if ref in self.working.sources:
            text = self.working.sources[ref]
        elif ref in self.working.cards:
            text = self.working.cards[ref].text
        elif ref in self.working.historical_cards:
            text = self.working.historical_cards[ref]["text"]
        else:
            raise ValueError("UNPUBLISHED_MEMORY_SOURCE")
        result = {
            "ref": ref,
            "start": start,
            "text": text[start : start + length],
            "total_chars": len(text),
            "has_more": start + length < len(text),
        }
        self._event("MEMORY_SOURCE_READ", **result)
        return result

    def _extract(self, trajectory: str) -> tuple[bool, str]:
        judgment = self.generate(
            MemoryCall(
                "self_judge",
                (
                    {"role": "system", "content": self.policies["judge_system"].strip()},
                    {
                        "role": "user",
                        "content": self.policies["judge_user"].format(
                            query=self.query, trajectory=trajectory
                        ),
                    },
                ),
                self.config.judge_output_tokens,
                0.0,
            )
        )
        # Preserve the selected official path's success-substring classification.
        successful = "success" in judgment.strip().lower()
        extraction = self.generate(self._extraction_call(trajectory, successful))
        return successful, extraction

    def _extraction_call(self, trajectory: str, successful: bool) -> MemoryCall:
        return MemoryCall(
            "extract",
            (
                {
                    "role": "system",
                    "content": self.policies[
                        "extract_success" if successful else "extract_failure"
                    ].strip(),
                },
                {
                    "role": "user",
                    "content": f"**Query:** {self.query}\n\n**Trajectory:**\n{trajectory}",
                },
            ),
            self.config.extract_output_tokens,
            1.0,
        )

    def _memory_items(self, extraction: str) -> list[str]:
        return parse_memory_items(extraction, self.config.max_extracted_items)

    def finish(self, trajectory: str, *, commit: bool) -> dict[str, Any]:
        if not self.active:
            raise ValueError("NO_ACTIVE_MEMORY_TASK")
        try:
            successful, extraction = self._extract(trajectory)
            items = self._memory_items(extraction)
        except MemoryOutputError as error:
            self._event("MEMORY_EXTRACTION_REJECTED", reason=str(error))
            self.active = False
            return {"status": "MAINTENANCE_FAILED", "committed": False, "reason": str(error)}
        trace_ref = self.working.source(f"Query:\n{self.query}\n\nTrajectory:\n{trajectory}")
        handles = []
        for item in items:
            handle = f"card:{self.working.next_card}"
            self.working.next_card += 1
            self.working.cards[handle] = MemoryCard(handle, item, [trace_ref])
            handles.append(handle)
        if handles:
            self.working.records.append(
                {
                    "task_id": self.task_id,
                    "query": self.query,
                    "embedding": self.query_vector,
                    "handles": handles,
                    "self_judgment": "success" if successful else "fail",
                    "trace_ref": trace_ref,
                }
            )
        self.working.completed_tasks.append(self.task_id)
        self.working.revision += 1
        if commit:
            self._commit_working()
        self.active = False
        result = {
            "status": "EXTRACTED" if handles else "NO_NEW_EXPERIENCE",
            "committed": commit,
            "handles": handles,
        }
        self._event("MEMORY_TASK_FINISHED", **result)
        return result

    def _commit_working(self) -> None:
        if self.bank.revision != self.base_revision:
            raise ValueError("BANK_CHANGED_DURING_TASK")
        committed = ExperienceBank.restore(
            self.working.checkpoint(), scope=self.bank.scope, contract=self.bank.contract
        )
        self.bank.__dict__.update(committed.__dict__)

    def checkpoint(self) -> dict[str, Any]:
        if self.active:
            raise ValueError("CHECKPOINT_REQUIRES_COMPLETED_TASK_BOUNDARY")
        return self.bank.checkpoint()
