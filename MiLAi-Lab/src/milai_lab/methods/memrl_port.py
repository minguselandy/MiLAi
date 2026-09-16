"""Local, sequential R-only MemRL LLB port; not an upstream score reproduction.

Adapted from MemTensor/MemRL c1b322ca43de36ddf64c6712f89d0095bfc35ce0:
MemoryService.retrieve_query/add_memories, QValueUpdater, AdjustmentUpdater.
Copyright (c) 2026 jiaqian, MIT; configs/policies/memrl/LICENSE.upstream.
Provider/storage substitutions and exact parameters belong to the bank contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import statistics
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from milai_lab.methods.evidence_utility_session import messages_digest
from milai_lab.methods.memrl_text import sanitize_llb_env_preamble
from milai_lab.methods.reasoning_bank import MemoryCall, MemoryOutputError, normalized

METHOD_VERSION = "MEMRL_LLB_PORT_v0.1"
UPSTREAM_COMMIT = "c1b322ca43de36ddf64c6712f89d0095bfc35ce0"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class MemRLConfig:
    embedding_model: str = "bge-m3"
    embedding_dimension: int = 1024
    encoding_version: str = "raw-task-query-cosine-v1"
    k_retrieve: int = 10
    topk: int = 5
    epsilon: float = 0.01
    alpha: float = 0.3
    gamma: float = 0.0
    q_init_pos: float = 0.5
    q_init_neg: float = 0.5
    q_floor: float = 0.0
    q_min: float = -0.8
    weight_sim: float = 0.5
    weight_q: float = 0.5
    sim_mean: float = 0.39
    sim_std: float = 0.14
    normalize_scores: bool = True
    db_threshold: float = 0.37
    os_threshold: float = 0.50
    add_similarity_threshold: float = 0.99
    formation_output_tokens: int = 2048
    seed: int = 213

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"NONFINITE_MEMRL_CONFIG:{key}")
        if (
            any(
                type(v) is not int or v < 1
                for v in (
                    self.embedding_dimension,
                    self.k_retrieve,
                    self.topk,
                    self.formation_output_tokens,
                )
            )
            or not 0 <= self.epsilon <= 1
            or not 0 <= self.alpha <= 1
            or self.gamma != 0
            or self.embedding_model != "bge-m3"
            or self.encoding_version != "raw-task-query-cosine-v1"
            or type(self.seed) is not int
            or type(self.normalize_scores) is not bool
        ):
            raise ValueError("INVALID_MEMRL_CONFIG")


@dataclass
class MemRLBank:
    scope: dict[str, str]
    contract: dict[str, Any]
    queries: dict[str, dict[str, Any]] = field(default_factory=dict)
    memories: dict[str, dict[str, Any]] = field(default_factory=dict)
    completed_tasks: list[str] = field(default_factory=list)
    task_records: list[dict[str, Any]] = field(default_factory=list)
    rng_state: Any = None

    def checkpoint(self) -> dict[str, Any]:
        # A JSON-stable RNG state is part of the same atomic task commit.
        value: dict[str, Any] = json.loads(
            json.dumps({"format": "memrl-local-bank-v1", **asdict(self)})
        )
        return value

    @classmethod
    def restore(
        cls, value: dict[str, Any], *, scope: dict[str, str], contract: dict[str, Any]
    ) -> MemRLBank:
        if (
            value.get("format") != "memrl-local-bank-v1"
            or value.get("scope") != scope
            or value.get("contract") != contract
            or scope.get("feedback_regime") != "R"
            or scope.get("method") != METHOD_VERSION
            or scope.get("method_version") != METHOD_VERSION
        ):
            raise ValueError("MEMRL_BANK_BINDING_MISMATCH")
        data = copy.deepcopy(value)
        data.pop("format")
        bank = cls(**data)
        if set(bank.memories) != {f"memrl:{i + 1}" for i in range(len(bank.memories))}:
            raise ValueError("MEMRL_MEMORY_ID_SEQUENCE_MISMATCH")
        ids = []
        for query, entry in bank.queries.items():
            if not query or not entry["ids"]:
                raise ValueError("MEMRL_QUERY_BINDING_MISMATCH")
            normalized(entry["embedding"], contract["config"]["embedding_dimension"])
            ids.extend(entry["ids"])
            if any(bank.memories[i]["query_key"] != query for i in entry["ids"]):
                raise ValueError("MEMRL_QUERY_BINDING_MISMATCH")
        if len(set(ids)) != len(ids) or set(ids) != set(bank.memories):
            raise ValueError("MEMRL_MEMORY_INDEX_MISMATCH")
        for mid, item in bank.memories.items():
            if (
                item["id"] != mid
                or item["content_sha256"] != digest(item["content"])
                or type(item["success"]) is not bool
                or type(item["visits"]) is not int
                or item["visits"] < 0
                or not math.isfinite(item["q"])
                or not math.isfinite(item["reward_ma"])
                or not set(item["related_ids"]) <= bank.memories.keys()
            ):
                raise ValueError("MEMRL_MEMORY_BINDING_MISMATCH")
        if (
            len(set(bank.completed_tasks)) != len(bank.completed_tasks)
            or [x["task_id"] for x in bank.task_records] != bank.completed_tasks
        ):
            raise ValueError("MEMRL_COMPLETION_POSITION_MISMATCH")
        if bank.rng_state is not None:
            restore_rng(bank.rng_state)
        return bank

    def fork(self, scope: dict[str, str]) -> MemRLBank:
        if any(
            scope.get(k) != self.scope.get(k)
            for k in (
                "experiment",
                "method",
                "model",
                "domain",
                "method_version",
                "feedback_regime",
            )
        ):
            raise ValueError("CROSS_MEMRL_SCOPE")
        value = self.checkpoint()
        value["scope"] = dict(scope)
        return self.restore(value, scope=scope, contract=self.contract)


def restore_rng(state: Any) -> random.Random:
    rng = random.Random()  # noqa: S311 -- scientific epsilon sampling, not security
    rng.setstate((state[0], tuple(state[1]), state[2]))
    return rng


def retrieve(
    bank: MemRLBank, vector: list[float], config: MemRLConfig, rng: random.Random
) -> dict[str, Any]:
    """LLB query shortlist, expansion, Q normalization, then epsilon selection."""
    query_vector = normalized(vector, config.embedding_dimension)
    threshold = config.db_threshold if bank.scope["domain"] == "db_bench" else config.os_threshold
    queries = []
    for query, entry in bank.queries.items():
        stored = normalized(entry["embedding"], config.embedding_dimension)
        similarity = sum(a * b for a, b in zip(query_vector, stored, strict=True))
        if similarity >= threshold:
            queries.append((query, similarity))
    queries.sort(key=lambda row: row[1], reverse=True)
    queries = queries[: config.k_retrieve]
    candidates = [
        {
            "memory_id": mid,
            "similarity": sim,
            "q_estimate": max(config.q_floor, bank.memories[mid]["q"]),
        }
        for query, sim in queries
        for mid in bank.queries[query]["ids"]
    ]
    values = [c["q_estimate"] for c in candidates]
    mean_q = statistics.fmean(values) if values else 0.0
    std_q = statistics.pstdev(values) if len(values) > 1 else 1.0
    # Upstream computes Q statistics BEFORE filtering by q_min.
    candidates = [c for c in candidates if c["q_estimate"] >= config.q_min]
    for item in candidates:
        sim_z, q_z = item["similarity"], item["q_estimate"]
        if config.normalize_scores:
            sim_z = (sim_z - config.sim_mean) / (config.sim_std if config.sim_std > 1e-9 else 1.0)
            q_z = max(-3.0, min(3.0, (q_z - mean_q) / (std_q if std_q > 1e-9 else 1.0)))
        item.update(
            similarity_z=sim_z, q_z=q_z, score=config.weight_sim * sim_z + config.weight_q * q_z
        )
    candidates.sort(key=lambda row: row["score"], reverse=True)
    topk = min(config.topk, len(candidates))
    # Upstream returns before drawing RNG and omits the query list on empty results.
    explore = bool(candidates) and rng.random() < config.epsilon
    chosen = rng.sample(candidates, topk) if explore else candidates[:topk]
    return {
        "queries": queries if candidates else [],
        "candidates": candidates,
        "selected": [c["memory_id"] for c in chosen],
        "exploration": explore,
    }


def memory_context(items: list[dict[str, Any]]) -> str:
    """Upstream LLB success/failure formatting, including failure-tail removal."""
    if not items:
        return ""
    lines = ["[Retrieved Memory Context]"]
    for success, title, label in (
        (True, "SUCCESSFUL EXPERIENCES (Learn from these)", "SUCCESS"),
        (False, "FAILED EXPERIENCES (Avoid these mistakes)", "FAILURE"),
    ):
        group = [m for m in items if m["success"] == success]
        if not group:
            continue
        lines.append(f"\n=== {title} ===")
        for position, item in enumerate(group, 1):
            content = sanitize_llb_env_preamble(item["content"])
            if not success:
                offset = content.lower().find("failed approach:")
                if offset >= 0:
                    content = content[:offset].rstrip()
            if content:
                kind = "procedure" if success else "adjustment"
                lines.append(f"[{label} {position}] [TYPE: {kind}]\n{content}\n")
    return "\n".join(lines)


class MemRLSession:
    method_version = METHOD_VERSION

    @staticmethod
    def contract(config: MemRLConfig, policies: dict[str, str]) -> dict[str, Any]:
        return {
            "method": METHOD_VERSION,
            "upstream_commit": UPSTREAM_COMMIT,
            "config": asdict(config),
            "policies_sha256": digest(policies),
            "feedback": "R-native-bit-after-terminal",
            "schedule": "one-pass-sequential",
            "query_embedding_cache": "eager-before-atomic-commit",
            "failure_policy": "unknown-stops;settled-formation-error-retains-Q-and-position",
        }

    def __init__(
        self,
        *,
        bank: MemRLBank,
        config: MemRLConfig,
        policies: dict[str, str],
        generate: Callable[[MemoryCall], str],
        embed: Callable[[list[str]], list[list[float]]],
        emit: Callable[[dict[str, Any]], None] | None = None,
        evaluation_rng: random.Random | None = None,
    ) -> None:
        if (
            bank.scope.get("feedback_regime") != "R"
            or bank.scope.get("domain") not in {"db_bench", "os_interaction"}
            or bank.contract != self.contract(config, policies)
        ):
            raise ValueError("MEMRL_REQUIRES_BOUND_R_CONTRACT")
        self.bank, self.config, self.policies = bank, config, dict(policies)
        self.generate, self.embed, self.emit = generate, embed, emit
        self.working = MemRLBank.restore(
            bank.checkpoint(), scope=bank.scope, contract=bank.contract
        )
        self.rng = (
            restore_rng(bank.rng_state)
            if bank.rng_state is not None
            else random.Random(config.seed)  # noqa: S311 -- scientific epsilon sampling
        )
        self.frozen = bank.scope["protocol"] == "F"
        if evaluation_rng is not None:
            if not self.frozen:
                raise ValueError("MEMRL_EVALUATION_RNG_REQUIRES_FROZEN_BANK")
            self.rng = evaluation_rng
        self.active = False
        self.sealed = False
        self.receipts: list[dict[str, Any]] = []
        self.prepared: str | None = None

    def _event(self, event: str, **data: Any) -> None:
        if self.emit:
            self.emit({"event": event, **data})

    def start(self, task_id: str, query: str) -> None:
        if self.active or task_id in self.bank.completed_tasks or not query:
            raise ValueError("MEMRL_INVALID_OR_REPEATED_TASK")
        self.active, self.task_id, self.query = True, task_id, query
        self.retrieval: dict[str, Any] = (
            retrieve(self.working, self.embed([query])[0], self.config, self.rng)
            if self.bank.queries
            else {"queries": [], "candidates": [], "selected": [], "exploration": False}
        )
        self.selected = sorted(
            self.retrieval["selected"], key=lambda mid: not self.working.memories[mid]["success"]
        )
        self.context = memory_context([self.working.memories[mid] for mid in self.selected])
        self._event("MEMRL_RETRIEVAL", task_id=task_id, **self.retrieval)

    def observe(self, kind: str, text: str) -> None:
        # Native trajectory is supplied at finish; no extra within-task maintenance.
        if not self.active:
            raise ValueError("MEMRL_SESSION_NOT_ACTIVE")

    def memory_context(self) -> str:
        return self.context

    def actor_system(self, runtime_context: str) -> str:
        constraint = self.policies[
            "db_constraint" if self.bank.scope["domain"] == "db_bench" else "os_constraint"
        ]
        return "\n\n".join(
            x.strip()
            for x in (self.policies["actor_base"], runtime_context, self.context, constraint)
            if x
        )

    def prepare_actor_input(self, messages: list[dict[str, Any]]) -> None:
        if self.context and not any(self.context in (m.get("content") or "") for m in messages):
            raise ValueError("MEMRL_CONTEXT_NOT_IN_ACTUAL_REQUEST")
        self.prepared = messages_digest(messages)

    def confirm_actor_input(self, receipt: dict[str, Any] | None) -> None:
        if (
            not receipt
            or receipt.get("status") != "SETTLED"
            or receipt.get("role") != "actor"
            or receipt.get("session") != self.task_id
            or not self.prepared
            or receipt.get("messages_sha256") != self.prepared
        ):
            raise ValueError("MEMRL_ACTOR_RECEIPT_MISMATCH")
        record = {
            "receipt": copy.deepcopy(receipt),
            "selected": list(self.selected),
            "context_sha256": digest(self.context),
            "content_sha256": {
                mid: self.working.memories[mid]["content_sha256"] for mid in self.selected
            },
        }
        self.receipts.append(record)
        self.prepared = None
        self._event("MEMRL_ACTOR_EXPOSURE", **record)

    def seal_result(self, result_ref: str, native_result: bool | None = None) -> None:
        if (
            not self.active
            or self.sealed
            or not result_ref
            or (native_result is not None and type(native_result) is not bool)
            or (self.frozen and native_result is not None)
        ):
            raise ValueError("MEMRL_RESULT_FEEDBACK_NOT_ALLOWED")
        self.result_ref, self.native_result, self.sealed = result_ref, native_result, True

    def finish(self, trajectory: str, *, commit: bool) -> dict[str, Any]:
        if not self.active or not self.sealed or (self.frozen and commit):
            raise ValueError("MEMRL_FINISH_REQUIRES_SEALED_ALLOWED_RESULT")
        if self.frozen:
            self.active = False
            return {"status": "FROZEN", "committed": False, "selected": self.selected}
        reward = self.native_result
        updates = []
        formed = None
        formation_status = "MISSING_NATIVE_RESULT"
        if reward is not None:
            for mid in self.selected:
                item = self.working.memories[mid]
                before = item["q"]
                item["q"] = max(
                    self.config.q_floor,
                    (1 - self.config.alpha) * before + self.config.alpha * float(reward),
                )
                item["reward_ma"] = (1 - self.config.alpha) * item[
                    "reward_ma"
                ] + self.config.alpha * float(reward)
                item["visits"] += 1
                item["last_reward"] = float(reward)
                updates.append({"id": mid, "before": before, "after": item["q"]})
            self._event(
                "MEMRL_Q_UPDATE",
                result_ref=self.result_ref,
                native_result=reward,
                updates=updates,
                attribution="selected-association-not-causal",
            )
            try:
                formed = self._form(trajectory, reward)
                formation_status = "ADDED"
            except MemoryOutputError as error:
                formation_status = str(error)
        self.working.completed_tasks.append(self.task_id)
        self.working.task_records.append(
            {
                "task_id": self.task_id,
                "result_ref": self.result_ref,
                "native_result": reward,
                "selected": self.selected,
                "updates": updates,
                "formed": formed,
                "formation_status": formation_status,
                "actual_receipts": self.receipts,
            }
        )
        self.working.rng_state = self.rng.getstate()
        if commit:
            complete = MemRLBank.restore(
                self.working.checkpoint(), scope=self.bank.scope, contract=self.bank.contract
            )
            self.bank.__dict__.update(complete.__dict__)
        self.active = False
        return {
            "status": formation_status,
            "committed": commit,
            "updates": updates,
            "formed": formed,
        }

    def _form(self, trajectory: str, success: bool) -> str:
        task = self.query[:4096]  # The upstream builder truncates the task, not the index key.
        prompt = self.policies["success" if success else "failure"].format(
            task_description=task, trajectory=trajectory
        )
        text = self.generate(
            MemoryCall(
                "memrl_script" if success else "memrl_reflection",
                ({"role": "user", "content": prompt},),
                self.config.formation_output_tokens,
                0.0 if success else 0.3,
            )
        )
        if not isinstance(text, str) or not text.strip():
            raise MemoryOutputError("MEMRL_EMPTY_FORMATION")
        content = (
            f"Task: {task}\n\nSCRIPT:\n{text}\n\nTRAJECTORY:\n{trajectory}"
            if success
            else (
                f"TASK REFLECTION:\nTask: {task}\n\nWhat went wrong:\n{text}\n\n"
                f"Failed approach:\n{trajectory}\n"
            )
        )
        matching = [
            (q, sim)
            for q, sim in self.retrieval["queries"]
            if sim >= self.config.add_similarity_threshold
        ]
        key = max(matching, key=lambda item: item[1])[0] if matching else self.query
        if key not in self.working.queries:
            vector = self.embed([key])[0]
            normalized(vector, self.config.embedding_dimension)
            self.working.queries[key] = {"embedding": vector, "ids": []}
        mid = f"memrl:{len(self.working.memories) + 1}"
        self.working.memories[mid] = {
            "id": mid,
            "query_key": key,
            "task_id": self.task_id,
            "task_query": self.query,
            "content": content,
            "content_sha256": digest(content),
            "success": success,
            "q": self.config.q_init_pos if success else self.config.q_init_neg,
            "visits": 0,
            "reward_ma": 0.0,
            "related_ids": list(self.selected),
            "result_ref": self.result_ref,
        }
        self.working.queries[key]["ids"].append(mid)
        self._event(
            "MEMRL_FORMED",
            id=mid,
            query_key=key,
            success=success,
            content_sha256=digest(content),
            result_ref=self.result_ref,
        )
        return mid

    def checkpoint(self) -> dict[str, Any]:
        return self.bank.checkpoint()
