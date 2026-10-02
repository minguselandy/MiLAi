"""One-shot read-only research execution; no writer, tools, evaluator import or retry."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.contracts.correction_relation import (
    ChainResearchSnapshot,
    DeliveryReceipt,
    QueryView,
    SelectionPlan,
    canonical,
    check_sha,
    digest,
    text_sha256,
)
from milai_lab.harness.contextual_artifacts import current_http_budget
from milai_lab.methods.correction_evidence import chain_rag_plan, ordered_source_plan, pack_complete
from milai_lab.methods.correction_reader import FrozenBankReader
from milai_lab.providers.contextual_vllm import VLLMClient
from milai_lab.providers.generation_admission import DurableGenerationAdmission

Reader = Callable[[QueryView, str, DeliveryReceipt], dict[str, Any]]


class AccountedReader:
    """Adopt the Root-owned existing client/ledger/lease; never create a second budget.

    One admission file belongs to one owner/bank/config. A query is never retried,
    including after unknown transport outcomes or across process restarts.
    """

    def __init__(
        self, client: VLLMClient, *, admission_path: Path, reader_system_prompt: str,
        config_sha256: str,
    ) -> None:
        check_sha(config_sha256)
        if (client.budget is None or client.budget.http_owner is None
                or client.budget is not current_http_budget() or client.capacity is None
                or client.emit is None or not reader_system_prompt
                or client.config.response_format is not None):
            raise ValueError("CORRECTION_ACCOUNTED_READER_RESOURCES_REQUIRED")
        self.client = client
        self.admission_path = admission_path
        self.system_prompt = reader_system_prompt
        self.config_sha256 = config_sha256
        self._dispatch_sha256 = digest({"host": asdict(client.config),
                                        "capacity": client.capacity.identity,
                                        "system_prompt": reader_system_prompt})

    def __call__(
        self, query: QueryView, material: str, delivery: DeliveryReceipt,
    ) -> dict[str, Any]:
        client = self.client
        budget, capacity = client.budget, client.capacity
        if (budget is None or budget.http_owner is None or capacity is None
                or current_http_budget() is not budget or client.emit is None
                or query.config_sha256 != self.config_sha256
                or digest({"host": asdict(client.config), "capacity": capacity.identity,
                           "system_prompt": self.system_prompt}) != self._dispatch_sha256
                or digest(capacity.identity) != delivery.tokenizer_sha256
                or text_sha256(material) != delivery.material_sha256
                or capacity.text_tokens(material) != delivery.material_tokens
                or delivery.material_tokens > delivery.evidence_budget):
            raise ValueError("CORRECTION_READER_BINDING_CHANGED")
        budget.http_owner.assert_budget(budget)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": material},
            {"role": "user", "content": query.question},
        ]
        # Validate the exact request before durable admission; provider repeats this check.
        capacity.check(messages, client.config.max_tokens)
        gate = DurableGenerationAdmission(
            self.admission_path, query.query_id,
            {"owner": query.owner, "bank": list(query.bank), "session": "correction-readonly",
             "request_ref": "correction-query:" + query.query_id,
             "request_sha256": digest({"query": asdict(query), "messages": messages,
                                       "delivery": asdict(delivery)}),
             "config_sha256": query.config_sha256},
            asdict(client.config), 1, "start", 0,
        )
        gate.reserve(asdict(client.config), 1, "correction_final_reader")
        messages_sha = digest(messages)
        original_emit = client.emit
        wire_confirmed = False

        def observed(event: dict[str, Any]) -> None:
            nonlocal wire_confirmed
            original_emit(event)
            if event.get("event") in {"vllm_response", "vllm_error"}:
                request = event.get("request", {})
                if (event.get("path") != "chat/completions"
                        or request.get("messages") != messages or request.get("tools")):
                    raise ValueError("CORRECTION_READER_WIRE_CHANGED")
                wire_confirmed = True
                original_emit({"event": "correction_reader_wire_delivery",
                               "messages_sha256": messages_sha,
                               "delivery": asdict(delivery),
                               "transport_outcome": event["event"],
                               "http_status": event.get("http_status"),
                               "server_consumption_verified": False})

        client.emit = observed
        try:
            response = client.chat(messages)
        finally:
            client.emit = original_emit
        if not wire_confirmed:
            raise ValueError("CORRECTION_READER_WIRE_RECEIPT_MISSING")
        # Preserve response bytes through the existing transport trace; do not rewrite answers.
        return {"provider_response": response, "reader_calls": 1,
                "messages_sha256": messages_sha, "usage": response.get("usage", "unknown")}


def run_query(
    bank: FrozenBankReader, query: QueryView, reader: Reader, *, evidence_budget: int = 2048,
    candidate_limit: int = 32, method: str = "ordered_source_v1",
) -> dict[str, Any]:
    """Injected readers are mechanical controls; only AccountedReader is a real-model path."""
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    if method not in {"ordered_source_v1", "chain_rag_v1"}:
        raise ValueError("CORRECTION_METHOD_UNAVAILABLE")
    with bank.guard(query):
        snapshot = bank.retrieve(query, limit=candidate_limit)
        select_wall, select_cpu = time.perf_counter_ns(), time.process_time_ns()
        plan: SelectionPlan
        if method == "chain_rag_v1":
            if not isinstance(snapshot, ChainResearchSnapshot):
                raise ValueError("CORRECTION_CHAIN_SNAPSHOT_REQUIRED")
            plan = chain_rag_plan(snapshot, evidence_budget=evidence_budget,
                                  token_count=bank.token_count)
        else:
            plan = ordered_source_plan(snapshot, evidence_budget=evidence_budget,
                                       token_count=bank.token_count)
        bank.emit({"event": "correction_selection", "plan": asdict(plan),
                   "wall_ns": time.perf_counter_ns() - select_wall,
                   "cpu_ns": time.process_time_ns() - select_cpu})
        units = bank.read_selected(snapshot, plan.selected_ids)
        material, delivery = pack_complete(snapshot, plan, units, token_count=bank.token_count)
        bank.emit({"event": "correction_material_prepared", "delivery": asdict(delivery),
                   "material": material, "reader_consumption_verified": False})
        bank.emit({"event": "benchmark_phase", "phase": "correction_reader"})
        response = reader(query, material, delivery)
        result = {"schema": "correction_readonly_result_v1", "method": plan.strategy,
                  "query": asdict(query), "snapshot_sha256": snapshot.snapshot_sha256,
                  "plan": asdict(plan), "delivery": asdict(delivery),
                  "reader": response,
                  "accounted_provider_path": isinstance(reader, AccountedReader),
                  "execution_controls": {"evidence_budget": evidence_budget,
                                         "candidate_limit": candidate_limit},
                  "config_binding": "caller must bind controls to the outer config file freeze",
                  "query_planning_model_calls": 0,
                  "wall_ns": time.perf_counter_ns() - wall,
                  "cpu_ns": time.process_time_ns() - cpu,
                  "scientific_status": ("B1_MECHANICAL_ONLY_NOT_T0_RESULT"
                                         if method == "chain_rag_v1"
                                         else "N1_ENTRY_ONLY_NOT_CHAIN_RAG_OR_T0_RESULT")}
        # Check JSON serializability before completing the guarded path.
        canonical(result)
    bank.emit({"event": "correction_readonly_result", **result})
    return result
