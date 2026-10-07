"""Common maintenance and explicit stored-history reading on ordinary memory.

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


def run_history(root: Path) -> dict[str, Any]:
    """Save, add an exception, withdraw it, then read its actual saved revision."""
    bank = root / "memory.sqlite"
    commits, calls = [], []
    with SqliteStore.from_conn_string(str(bank)) as store:
        memory = adapter(store, root)
        for index, (turn, text) in enumerate([
            ("save", "Save quiet meeting reminders throughout this quarter."),
            ("exception", "For Wednesday meetings only, save a chime reminder instead."),
            ("withdraw", "Withdraw the Wednesday exception; keep the quiet meeting rule."),
        ]):
            memory.service.capture_user(SESSION, turn, text)
            memory.context(SESSION, turn, VERSION)

            def transport(
                stage: str, messages: list[dict[str, str]], schema: dict[str, Any],
                *, phase: int = index, original: str = text,
            ) -> dict[str, Any]:
                calls.append(stage)
                if stage == "extract":
                    return {"changes": [{"subject": "meeting reminders", "statement": original,
                        "evidence": ["e1"], "time": None, "scope": None}]}
                packet = json.loads(messages[1]["content"])["delivery"]
                if phase == 0:
                    return {"creates": [{"action": "create", "matter": "Meeting reminders",
                        "clauses": [{**statement("Use quiet meeting reminders."), "conditions": [
                            {**statement("Throughout this quarter."),
                             "binding": {"evidence": ["e1"]}},
                        ]}]}], "records": {}}
                record = packet["records"][0]
                selected = record["clauses"][0] if phase == 1 else next(
                    clause for clause in record["clauses"] if clause.get("local_exception")
                )
                edit = {
                    **statement("Use a chime meeting reminder."),
                    "operation": "add_exception", "target_unit": selected["id"],
                    "condition": "Wednesday meetings only.",
                } if phase == 1 else {
                    "operation": "remove_exception", "target_unit": selected["id"],
                    "evidence": ["e1"],
                }
                return {"creates": [], "records": {
                    record["id"]: {"action": "edit", "edits": [edit]},
                }}

            result = memory.maintain_sources(
                config(turn), recipe="extract_then_edit", model_call=transport, allowed=True,
                fit=lambda messages: sum(len(m["content"]) for m in messages) <= 65000,
            )[0]
            assert result["status"] == "completed", result
            assert len(result["receipts"]) == 1 and result["receipts"][0]["ok"]
            commits.append(result["receipts"][0])
        assert [receipt["revision"] for receipt in commits] == [1, 2, 3]
        record_id = commits[0]["id"]
        assert all(receipt["id"] == record_id for receipt in commits)

    with SqliteStore.from_conn_string(str(bank)) as store:
        memory = adapter(store, root)
        memory.service.capture_user(
            SESSION, "history-question",
            "Read only: what is current, and what did the stored history previously contain?",
        )
        page = memory.context(SESSION, "history-question", VERSION)
        current = [unit for unit in page["items"] if unit["type"] == "record"]
        entry = next(unit["stored_history"] for unit in current if "stored_history" in unit)
        assert entry["revisions"] == [1, 2, 3] and entry["revision_count"] == 3
        assert all(unit["revision"] == 3 and unit["version_view"] == "current_at_snapshot"
                   for unit in current)
        assert all("chime" not in unit["content"] for unit in current)
        before = store.get(memory.service.namespace, record_id)
        assert before is not None

        def read(tool_name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
            tool = next(tool for tool in memory.tools() if tool.name == tool_name)
            result = tool.invoke({"type": "tool_call", "name": tool_name, "id": call_id,
                                  "args": arguments}, config=config("history-question"))
            packet: dict[str, Any] = json.loads(str(result.content))
            return packet

        history = read(entry["read"]["tool"], entry["read"]["arguments"], "history")
        assert history["ok"] and {unit["revision"] for unit in history["items"]} == {1, 2, 3}
        revision2 = read(entry["revision_tool"], {"record_id": record_id, "revision": 2}, "r2")
        assert revision2["ok"]
        assert any("chime" in unit["content"] for unit in revision2["items"])
        assert all(unit["revision"] == 2
                   and unit["version_view"] == "historical_exact_revision"
                   and unit["committed_at"] == memory.service.read(record_id, 2)["value"][
                       "committed_at"] for unit in revision2["items"])
        assert all(packet["semantic_write_performed"] is False for packet in (page, history,
                                                                              revision2))
        after = store.get(memory.service.namespace, record_id)
        assert after is not None and after.value == before.value
        # A new explicit forget request remains a separate visibility mutation.
        # The old history entry cannot expose any revoked body or original source.
        memory.service.capture_user(
            SESSION, "forget-history", "Forget the meeting memory and sources.",
        )
        memory.context(SESSION, "forget-history", VERSION)
        tool = next(tool for tool in memory.tools() if tool.name == "forget_memory")
        forgotten = json.loads(str(tool.invoke({"type": "tool_call", "name": "forget_memory",
            "id": "forget", "args": {
                "read_handle": memory.service.read(record_id)["candidate_handle"],
            }}, config=config("forget-history")).content))
        assert forgotten["ok"] and forgotten["effect"] == "visibility_only"
        memory.service.capture_user(SESSION, "after-forget", "Read only: is that history visible?")
        memory.context(SESSION, "after-forget", VERSION)
        tool = next(tool for tool in memory.tools() if tool.name == entry["read"]["tool"])
        hidden = json.loads(str(tool.invoke({"type": "tool_call", "name": tool.name,
            "id": "hidden-history", "args": entry["read"]["arguments"]},
            config=config("after-forget")).content))
        assert hidden["status"] == "visibility_revoked" and "chime" not in json.dumps(hidden)
        assert all(memory.service.source(ref) is None for ref in forgotten["revoked_source_refs"])
    return {"entry": "ordinary stored-history read", "scripted_calls": calls,
            "actual_commit_revisions": [receipt["revision"] for receipt in commits],
            "current_revision": 3, "read_history_revisions": [1, 2, 3],
            "read_exact_revision": 2, "read_semantic_mutation": False,
            "history_after_forget": hidden["status"]}


if __name__ == "__main__":
    with TemporaryDirectory(prefix="milai-maintenance-example-") as temporary:
        root = Path(temporary)
        (root / "host").mkdir()
        (root / "predict").mkdir()
        (root / "history").mkdir()
        observed = [run(root / "host", host=True), run(root / "predict", host=False)]
        assert sorted(view["units"][0]["text"] for view in observed[0]["current_views"]) == \
            sorted(view["units"][0]["text"] for view in observed[1]["current_views"])
        observed.append(run_history(root / "history"))
        print(json.dumps(observed, ensure_ascii=False, indent=2))
