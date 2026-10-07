"""One employment/health correction through Host and common predict maintenance.

Uses scripted transport, local embeddings and reopened SQLite. This observes
engineering behavior, not model accuracy or benchmark advantage. Run with
PYTHONPATH=src; no external service, private fixture or evaluator truth is used.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.runnables import RunnableConfig
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.retrieval import SemanticRetriever
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_maintenance import (
    maintain_event,
    plan_source_batches,
    resume_maintenance,
)
from milai_lab.methods.functional_edit_memory import FunctionalEditMemory

SESSION, VERSION = "ordinary-example", "unified-maintenance-example-v1"


class LocalEmbeddings(Embeddings):
    """A transparent synthetic dense transport, never a method-side topic rule."""

    def embed_query(self, text: str) -> list[float]:
        lower = text.lower()
        return [1.0, float("employment" in lower), float("walk" in lower)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


def statement(text: str) -> dict[str, Any]:
    return {"text": text, "evidence": ["e1"], "assertion": {
        "source": "e1", "kind": "reported", "evidence_links": {"supports": ["e1"]},
    }}


class ScriptedTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(
        self, stage: str, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(stage)
        packet = json.loads(messages[1]["content"])["delivery"]
        original = packet["evidence"][0]["text"]
        if stage == "extract":
            return {"changes": [
                {"subject": "employment", "statement": original, "evidence": ["e1"],
                 "time": None, "scope": None},
                {"subject": "health", "statement": original, "evidence": ["e1"],
                 "time": None, "scope": None},
            ]}
        if original.startswith("My employment status"):
            return {"creates": [
                {"action": "create", "matter": "Employment status", "clauses": [
                    {**statement("User reports being unemployed."), "conditions": []}]},
                {"action": "create", "matter": "Health walking plan", "clauses": [
                    {**statement("User plans fifteen-minute evening walks."), "conditions": []}]},
            ], "records": {}}
        updates = {}
        for record in packet["records"]:
            text = (
                "User reports accepting an editor position."
                if record["matter"] == "Employment status" else
                "User plans thirty-minute morning walks."
            )
            updates[record["id"]] = {"action": "edit", "edits": [{
                **statement(text), "operation": "change_value",
                "target_unit": record["clauses"][0]["id"],
            }]}
        return {"creates": [], "records": updates}


def config(turn: str) -> RunnableConfig:
    return {"max_concurrency": 1, "configurable": {
        "user_id": "example-owner", "v13_session": SESSION,
        "v13_turn_id": turn, "v13_config_version": VERSION,
    }}


def adapter(store: Any, root: Path) -> FunctionalEditMemory:
    service = MemoryService(
        store, ("unified-maintenance", "example-owner"), "example-owner", root / "memory.lock",
        functional_contract="functional_v1", mutation_contract="event_bound_v1",
        candidate_contract="read_handle_v1", memory_profile="unified_v1",
        semantic_retriever=SemanticRetriever(LocalEmbeddings(), 3),
        clock=lambda: datetime(2026, 10, 7, 12, tzinfo=UTC),
    )
    return FunctionalEditMemory(
        service, lambda text: max(1, len(text) // 4), read_limit=6,
        material_limit=30000, interface_version="I2", maintenance_recipe="extract_then_edit",
        features=EditFeatures(True, True, True, True, True, True),
        read_interface="explicit_selectors_v1", recent_context="bank_recent_v2",
    )


def run(root: Path, *, host: bool) -> dict[str, Any]:
    transport = ScriptedTransport()
    bank = root / "memory.sqlite"
    with SqliteStore.from_conn_string(str(bank)) as store:
        memory = adapter(store, root)
        for turn, text in [
            ("first", "My employment status is unemployed. My health plan is "
             "fifteen-minute walks in the evening."),
            ("change", "My employment has changed: I accepted an editor position. "
             "Change my health plan to thirty-minute walks in the morning."),
        ]:
            ref = memory.service.capture_user(SESSION, turn, text)["source_ref"]
            memory.context(SESSION, turn, VERSION)
            if host:
                result = memory.maintain_sources(
                    config(turn), recipe="extract_then_edit", model_call=transport, allowed=True,
                    fit=lambda messages: sum(len(m["content"]) for m in messages) <= 65000,
                )[0]
                fresh = memory.context(SESSION, turn, VERSION)
                assert any(item.get("revision") == 2 for item in fresh["items"]) or turn == "first"
            else:
                delivery = memory.writer.prepare(
                    [ref], "", selected_records=[], redelivered_ranges=[]
                )
                if turn == "change":
                    first_ref = memory.service.event_id(SESSION, "first", "user")
                    delivery["prior_context"] = memory.writer.prepare(
                        [first_ref], "", selected_records=[], redelivered_ranges=[]
                    )["sources"]
                result = maintain_event(
                    memory.writer, delivery, session=SESSION, request_id=turn,
                    date="2026-10-07", recipe="extract_then_edit", model_call=transport,
                )
            assert result["status"] == "completed", result
        rows = memory.service.records()
        assert len(rows) == 2 and all(row["value"]["revision"] == 2 for row in rows)
        current = [memory.writer.revision_view(row["value"], query_time="2026-10-07")
                   for row in rows]
        past = [memory.service.read(row["id"], 1)["value"]["content"] for row in rows]
        assert any("unemployed" in text for text in past)
        assert any("evening" in text for text in past)
        assert all(episode["descriptions"] for episode in memory.service.episodes())

    with SqliteStore.from_conn_string(str(bank)) as store:
        memory = adapter(store, root)
        memory.service.capture_user(SESSION, "question", "What changed in employment and walks?")
        page = memory.context(SESSION, "question", VERSION)
        record_id = memory.service.records()[0]["id"]
        read = next(tool for tool in memory.tools() if tool.name == "read_memory")
        receipt = read.invoke({"type": "tool_call", "name": "read_memory", "id": "read-again",
                               "args": {"record_id": record_id}}, config=config("question"))
        progress = json.loads(str(receipt.content)).get("read_progress")
        assert progress and progress["status"] == "no_new_evidence", progress
        assert any("thirty-minute" in row["value"]["content"]
                   for row in memory.service.records())
        change_ref = memory.service.event_id(SESSION, "change", "user")
        selected_delivery = memory.writer.prepare(
            [change_ref], "", selected_records=[], redelivered_ranges=[]
        )
        scoped = memory.maintain_delivery(
            config("question"), {**selected_delivery, "replay": True,
                                 "new_independent_support": False},
            request_id="selected-record-consolidation", date="2026-10-07",
            recipe="single_pass", allowed=True, selected_record_ids=[record_id],
            model_call=lambda stage, messages, schema:
            {"creates": [], "records": {"r1": {"action": "no_change"}}},
        )
        assert scoped["status"] == "completed" and scoped["receipts"][0]["id"] == record_id
        # The source planner uses the full real schema/old view and never drops
        # original characters or shrinks the candidate K to make a request fit.
        long_ref = memory.service.capture_user(
            SESSION, "long", "One work note. " * 900 + "\n" + "One walking note. " * 900
        )["source_ref"]
        memory.context(SESSION, "long", VERSION)
        delivery = memory.writer.prepare([long_ref], "", selected_records=[], redelivered_ranges=[])
        batches = plan_source_batches(
            memory.writer, delivery, date="2026-10-07", recipe="single_pass",
            fit=lambda messages: sum(len(m["content"]) for m in messages) <= 40000,
        )
        recovered = "".join(source["text"] for batch in batches for source in batch["sources"])
        source = memory.service.source(long_ref)
        assert source and recovered == source["content"]
        assert len(batches) > 1
        delivered_bodies: list[str] = []

        def batch_transport(
            stage: str, messages: list[dict[str, str]], schema: dict[str, Any]
        ) -> dict[str, Any]:
            assert sum(len(m["content"]) for m in messages) <= 40000
            packet = json.loads(messages[1]["content"])["delivery"]
            delivered_bodies.extend(evidence["text"] for evidence in packet["evidence"])
            return {"creates": [], "records": {}}

        batched = maintain_event(
            memory.writer, delivery, session=SESSION, request_id="lossless-batches",
            date="2026-10-07", recipe="single_pass", model_call=batch_transport,
            fit=lambda messages: sum(len(m["content"]) for m in messages) <= 40000,
        )
        assert batched["status"] == "completed", batched
        assert "".join(delivered_bodies) == source["content"]
        assert batched["source_batch_count"] == len(batches)

        def lost(stage: str, messages: list[dict[str, str]], schema: dict[str, Any]) -> Any:
            raise OSError("Scripted response loss; original attempt remains pending")

        try:
            maintain_event(
                memory.writer, delivery, session=SESSION, request_id="first-attempt",
                date="2026-10-07", recipe="extract_then_edit", model_call=lost,
            )
        except OSError:
            pass
        resumed = resume_maintenance(
            memory.writer, delivery, session=SESSION, prior_request_id="first-attempt",
            new_attempt_id="explicit-new-attempt", date="2026-10-07",
            recipe="extract_then_edit", model_call=lambda stage, messages, schema:
            {"changes": []} if stage == "extract" else {"creates": [], "records": {}},
        )
        assert resumed["status"] == "completed", resumed
        original = maintain_event(
            memory.writer, delivery, session=SESSION, request_id="first-attempt",
            date="2026-10-07", recipe="extract_then_edit", model_call=lost, execute=False,
        )
        assert original["phase"] == "extract_pending"
    return {"entry": "Host" if host else "common predict", "calls": transport.calls,
            "current_views": current, "historical_bodies": past,
            "read_progress": progress, "source_batches": len(batches),
            "explicit_resume": resumed["status"], "original_phase": original["phase"],
            "ordinary_snapshot_units": len(page["items"])}


if __name__ == "__main__":
    with TemporaryDirectory(prefix="milai-maintenance-example-") as temporary:
        root = Path(temporary)
        (root / "host").mkdir()
        (root / "predict").mkdir()
        observed = [run(root / "host", host=True), run(root / "predict", host=False)]
        assert sorted(view["units"][0]["text"] for view in observed[0]["current_views"]) == \
            sorted(view["units"][0]["text"] for view in observed[1]["current_views"])
        print(json.dumps(observed, ensure_ascii=False, indent=2))
