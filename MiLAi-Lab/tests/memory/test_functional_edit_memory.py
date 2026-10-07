"""Local edit arms through actual functional tools, SQLite and wrapper; no HTTP."""

from __future__ import annotations

import copy
import json
import socket
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.sqlite import SqliteStore
from pydantic import ValidationError

from milai_lab.application.functional import FunctionalApplication
from milai_lab.application.journal import UnknownBusinessAction
from milai_lab.memory.edit_units import EditProposal, clause_proposal, form_state, render_state
from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.functional_state import (
    FunctionalRejection,
    canonical,
    namespace,
    reference_key,
)
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures, decorate_state
from milai_lab.methods.functional_edit_memory import (
    FUNCTIONAL_ARMS,
    FUNCTIONAL_B0_METHOD,
    FUNCTIONAL_B1_METHOD,
    FUNCTIONAL_B2_METHOD,
    FUNCTIONAL_METHOD,
    FunctionalEditMemory,
)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("SYNTHETIC_ENGINEERING_NO_NETWORK")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def cfg(turn: str = "u", owner: str = "alice") -> dict[str, Any]:
    return {
        "max_concurrency": 1,
        "configurable": {
            "user_id": owner,
            "thread_id": "functional-m-local-" + owner,
            "v13_session": "s",
            "v13_turn_id": turn,
            "v13_config_version": "functional-m-test-v1",
        },
    }


NEXT_FEATURES = EditFeatures(True, True, True, True, True)


def next_sdk_create():
    return clause_proposal(
        {
            "action": "create",
            "matter": "User's reminder sound",
            "units": [
                {
                    "text": "User reports quiet reminders.",
                    "evidence": ["e1"],
                    "assertion": {"source": "e1", "kind": "reported"},
                }
            ],
        },
        conditioned=True,
    )


def test_next_sdk_reopened_clause_support_enters_wrapper_without_old_source_delivery(tmp_path):
    with opened(tmp_path, arm="B2", interface_version="I2", features=NEXT_FEATURES) as memory:
        text = "Use quiet reminders.\nOnly on weekdays.\nOnly before 18:00."
        ref = memory.service.capture_user("s", "u", text)["source_ref"]
        source = memory.service.source(ref)
        bound = memory.service.bind_public_turn(
            "s", "u", ref, config_version="functional-m-test-v1", phase="start"
        )
        first, second = text.index("\n"), text.rindex("\n")
        handles = [
            memory.service.source_fragment_range(ref, start, end)["fragment_handle"]
            for start, end in (
                (0, first),
                (first + 1, second),
                (second + 1, len(text)),
                (0, second),
                (0, len(text)),
            )
        ]
        parsed = EditProposal.model_validate(
            {
                "action": "create",
                "units": [
                    {"text": "Use quiet reminders.", "evidence": [handles[0]]},
                    {"text": "Only on weekdays.", "role": "condition", "evidence": [handles[1]]},
                    {"text": "Only before 18:00.", "role": "condition", "evidence": [handles[2]]},
                ],
                "relations": [
                    {
                        "source": 1,
                        "target": 0,
                        "relation_type": "modifies",
                        "evidence": [handles[3]],
                    },
                    {
                        "source": 2,
                        "target": 0,
                        "relation_type": "modifies",
                        "evidence": [handles[4]],
                    },
                ],
            }
        )
        state = form_state(parsed, memory.service, conditioned=True)
        decorate_state(
            state,
            {
                "matter_description": "Reminder tone",
                "unit_assertions": [
                    {
                        "kind": "reported",
                        "source_ref": ref,
                        "source_revision": source["source_revision"],
                        "role": source["role"],
                        "observed_at": source["observed_at"],
                        "occurred_at": None,
                    }
                    for _ in parsed.units
                ],
            },
        )
        # A trusted Service import has real source/version support, without an SDK
        # source-read receipt. This avoids previous global delivery masking the bug.
        saved = memory.service.commit(
            "s",
            "import",
            {
                "action": "create",
                "id": None,
                "expected_revision": 0,
                "content": render_state(state),
                "kind": "semantic",
                "basis": "user_statement",
                "scope": {},
                "fields": {},
                "object_ref": None,
                "source_ref": ref,
                "source_refs": [ref],
                "edit_state": state,
                "field_support": {
                    field: {"source_refs": [ref]} for field in ("content", "scope", "basis", "kind")
                },
                "functional_support": {field: handles for field in ("content", "kind", "basis")},
                "trigger_binding": bound,
                "requested": {"operation": "synthetic_import"},
            },
        )
        assert saved["ok"], saved
        old = copy.deepcopy(memory.service.read(saved["id"])["value"])
        assert all(
            memory.service.store.get(namespace(memory.service), "edit-delivered:" + h) is None
            for h in handles
        )
    with FunctionalApplication.open(tmp_path, "reservation", "alice") as app:
        with opened(
            tmp_path,
            arm="B2",
            interface_version="I2",
            features=NEXT_FEATURES,
            retrieval_candidates=[],
        ) as memory:
            memory.service.capture_user("s", "u2", "Now use written reminders; retain the limits.")
            memory.writer_context("s", "u2", "functional-m-test-v1")
            page = json.loads(
                invoke(memory, "read_memory", {"record_id": saved["id"]}, "read-old", "u2").content
            )
            assert page["ok"] and all(item["type"] == "record" for item in page["items"])
            context = memory.writer_context("s", "u2", "functional-m-test-v1")
            record = context["writer_packet"]["records"][0]
            assert all(
                memory.service.store.get(namespace(memory.service), "edit-delivered:" + h) is None
                for h in handles
            )
            proposal = {
                "action": "rewrite",
                "target": "r1",
                "clauses": [
                    {
                        "text": "Use written reminders.",
                        "evidence": ["e1"],
                        "keep_support": record["clauses"][0]["support"],
                        "assertion": {"source": "e1", "kind": "reported"},
                        "conditions": [
                            {
                                "text": c["text"],
                                "evidence": [],
                                "keep_support": c["support"],
                                "assertion": {"keep": c["support"][0]},
                                "binding": {
                                    "evidence": [],
                                    "keep_support": c["binding"]["support"],
                                },
                            }
                            for c in record["clauses"][0]["conditions"]
                        ],
                    }
                ],
            }
            before = app.world.snapshot()
            updated = json.loads(
                invoke(
                    memory,
                    "update_memory",
                    {"proposal": proposal},
                    "rewrite-nested",
                    "u2",
                    app.call_wrapper(memory.service, "s", "u2"),
                ).content
            )
            assert updated["ok"], updated.get("reason", updated)
            assert updated["id"] == saved["id"] and updated["revision"] == 2
            op = memory.service.store.get(
                namespace(memory.service),
                "edit-writer-operation:"
                + reference_key([memory._binding(cfg("u2")), "rewrite-nested"]),
            )
            assert set(op.value["kept_support"]) == set(handles)
            candidate = memory.service.candidate(op.value["read_handle"])
            assert candidate["record_id"] == saved["id"] and candidate["revision"] == 1
            assert memory.service.read(saved["id"], 1)["value"] == old
            assert app.world.snapshot() == before


def test_sdk_reopened_rewrite_changes_condition_and_retains_its_existing_link(tmp_path):
    with opened(tmp_path, arm="B2", interface_version="I2", features=NEXT_FEATURES) as memory:
        old_ref = memory.service.capture_user(
            "s", "u", "Use quiet reminders during gallery hours."
        )["source_ref"]
        memory.writer_context("s", "u", "functional-m-test-v1")
        create = {
            "action": "create", "matter": "Reminder sound", "clauses": [{
                "text": "Use quiet reminders.", "evidence": ["e1"],
                "assertion": {"source": "e1", "kind": "reported"},
                "conditions": [{
                    "text": "During gallery hours.", "evidence": ["e1"],
                    "assertion": {"source": "e1", "kind": "reported"},
                    "binding": {"evidence": ["e1"]},
                }],
            }],
        }
        saved = json.loads(invoke(memory, "save_memory", {"proposal": create}, "save").content)
        assert saved["ok"]
        original = copy.deepcopy(memory.service.read(saved["id"], 1)["value"])

    with FunctionalApplication.open(tmp_path, "reservation", "alice") as app:
        with opened(
            tmp_path, arm="B2", interface_version="I2", features=NEXT_FEATURES,
            retrieval_candidates=[],
        ) as memory:
            new_ref = memory.service.capture_user(
                "s", "u2", "The reminder rule now applies during evening hours."
            )["source_ref"]
            memory.writer_context("s", "u2", "functional-m-test-v1")
            page = json.loads(
                invoke(memory, "read_memory", {"record_id": saved["id"]}, "record", "u2").content
            )
            assert page["ok"]
            packet = memory.writer_context("s", "u2", "functional-m-test-v1")["writer_packet"]
            clause = packet["records"][0]["clauses"][0]
            condition = clause["conditions"][0]
            rewrite = {
                "action": "rewrite", "target": "r1", "clauses": [{
                    "text": clause["text"], "evidence": [],
                    "keep_support": clause["support"],
                    "assertion": {"keep": clause["support"][0]},
                    "conditions": [{
                        "from_unit": condition["id"], "text": "During evening hours.",
                        "evidence": ["e1"],
                        "assertion": {"source": "e1", "kind": "reported"},
                        "binding": {
                            "evidence": [], "keep_support": condition["binding"]["support"]
                        },
                    }],
                }],
            }
            binding = copy.deepcopy(memory.service.public_turn("s"))
            boundary = copy.deepcopy(memory.service._source_boundaries)
            world = app.world.snapshot()
            result = json.loads(invoke(
                memory, "update_memory", {"proposal": rewrite}, "change-hours", "u2",
                app.call_wrapper(memory.service, "s", "u2"),
            ).content)
            assert result["ok"] and result["revision"] == 2, result.get("reason", result)
            state = memory.service.read(saved["id"])["value"]["edit_state"]
            assert [u["text"] for u in state["units"]] == [
                "Use quiet reminders.", "During evening hours."
            ]
            assert {e["source_ref"] for e in state["units"][1]["evidence_refs"]} == {new_ref}
            assert {e["source_ref"] for e in state["relations"][0]["evidence_refs"]} == {old_ref}
            assert memory.service.read(saved["id"], 1)["value"] == original
            assert memory.service.public_turn("s") == binding
            assert memory.service._source_boundaries == boundary
            assert app.world.snapshot() == world
    with opened(tmp_path, arm="B2", interface_version="I2", features=NEXT_FEATURES) as memory:
        assert memory.service.read(saved["id"])["value"]["edit_state"] == state


def test_sdk_real_old_source_page_becomes_e_without_rebinding_current_turn(tmp_path):
    with opened(tmp_path, arm="B2", interface_version="I2", features=NEXT_FEATURES) as memory:
        old_ref = memory.service.capture_user(
            "s", "u", "Remember quiet reminders, on weekdays before 18:00.",
            occurred_at="2025-02-03T00:00:00Z",
        )["source_ref"]
        memory.writer_context("s", "u", "functional-m-test-v1")
        units = [
            {
                "text": text,
                "role": role,
                "evidence": ["e1"],
                "assertion": {"source": "e1", "kind": "reported"},
            }
            for text, role in (
                ("Quiet reminders.", "content"), ("On weekdays before 18:00.", "condition")
            )
        ]
        create = clause_proposal(
            {
                "action": "create", "matter": "Reminder tone", "units": units,
                "relations": [
                    {"source": 1, "target": 0, "relation_type": "modifies", "evidence": ["e1"]}
                ],
            },
            conditioned=True,
        )
        saved = json.loads(invoke(memory, "save_memory", {"proposal": create}, "save").content)
        assert saved["ok"]
        old = copy.deepcopy(memory.service.read(saved["id"])["value"])
        handle = old["edit_state"]["units"][1]["evidence_refs"][0]["evidence_id"]

    with FunctionalApplication.open(tmp_path, "reservation", "alice") as app:
        with opened(
            tmp_path, arm="B2", interface_version="I2", features=NEXT_FEATURES,
            retrieval_candidates=[],
        ) as memory:
            current_ref = memory.service.capture_user(
                "s", "u2", "Remember bright reminders now.", occurred_at="2025-02-04T00:00:00Z"
            )["source_ref"]
            memory.writer_context("s", "u2", "functional-m-test-v1")
            invoke(memory, "read_memory", {"record_id": saved["id"]}, "record", "u2")
            before = memory.writer_context("s", "u2", "functional-m-test-v1")["writer_packet"]
            assert before["evidence"] and all(
                e["text"] == "Remember bright reminders now." for e in before["evidence"]
            )
            assert "delivery_kind" not in canonical(before)
            binding = copy.deepcopy(memory.service.public_turn("s"))
            boundary = copy.deepcopy(memory.service._source_boundaries)
            page = json.loads(
                invoke(memory, "read_source", {"fragment_handle": handle}, "source", "u2").content
            )
            assert page["ok"] and page["items"][0]["source_ref"] == old_ref
            packet = memory.writer_context("s", "u2", "functional-m-test-v1")["writer_packet"]
            by_kind = {
                kind: next(e["id"] for e in packet["evidence"] if e["delivery_kind"] == kind)
                for kind in ("current", "redelivered_support")
            }
            old_source = next(
                s for s in packet["source_table"] if "redelivered_support" in s["delivery_kinds"]
            )
            assert old_source["role"] == "user"
            assert old_source["occurred_at"] == "2025-02-03T00:00:00Z"
            assert memory.service.public_turn("s") == binding
            assert binding["source_ref"] == current_ref
            assert memory.service._source_boundaries == boundary
            clause = packet["records"][0]["clauses"][0]
            condition = clause["conditions"][0]
            rewrite = {
                "action": "rewrite", "target": "r1", "clauses": [
                    {
                        "text": "Bright reminders.",
                        "evidence": [by_kind["current"]], "keep_support": clause["support"],
                        "assertion": {"source": by_kind["current"], "kind": "reported"},
                        "conditions": [
                            {
                                "text": "Weekdays, earlier than 18:00.",
                                "evidence": [by_kind["redelivered_support"]],
                                "keep_support": condition["support"],
                                "assertion": {
                                    "source": by_kind["redelivered_support"], "kind": "reported"
                                },
                                "binding": {
                                    "evidence": [], "keep_support": condition["binding"]["support"]
                                },
                            }
                        ],
                    }
                ],
            }
            updated = json.loads(invoke(
                memory, "update_memory", {"proposal": rewrite}, "rewrite", "u2",
                app.call_wrapper(memory.service, "s", "u2"),
            ).content)
            assert updated["ok"] and updated["id"] == saved["id"] and updated["revision"] == 2
            assert memory.service.read(saved["id"], 1)["value"] == old


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
def test_next_sdk_real_tools_matter_delivery_scope_update_and_guard(tmp_path, arm):
    with FunctionalApplication.open(tmp_path, "reservation", "alice") as app:
        with opened(tmp_path, arm=arm, interface_version="I2", features=NEXT_FEATURES) as memory:
            memory.service.capture_user(
                "s", "u", "Remember my quiet reminders and bright Tuesday reminders.",
                occurred_at="2025-02-03T00:00:00Z"
            )
            context = memory.writer_context("s", "u", "functional-m-test-v1")
            assert context["writer_packet"]["records"] == []
            catalog = {t.name: t for t in memory.writer_tools(cfg())}
            assert "save_memory" in catalog and "update_memory" not in catalog
            raw = catalog["save_memory"].tool_call_schema
            assert "matter" in json.dumps(raw)
            clause_schema = raw["properties"]["proposal"]["properties"]["clauses"]["items"]
            variants = clause_schema["oneOf"] if memory.conditioned else [clause_schema]
            for variant in variants:
                assert variant["properties"]["evidence"]["items"]["enum"] == [
                    e["id"] for e in context["writer_packet"]["evidence"]
                ]
            before_world = app.world.snapshot()
            wrapper = app.call_wrapper(memory.service, "s", "u")
            args = {"proposal": next_sdk_create(), "scope": {"project": "gallery"}}
            if not memory.local:
                extra = copy.deepcopy(args["proposal"]["clauses"][0])
                extra["text"] = "User reports bright Tuesday reminders."
                args["proposal"]["clauses"].append(extra)
            if not memory.conditioned:
                for clause in args["proposal"]["clauses"]:
                    clause.pop("conditions")
            response = invoke(memory, "save_memory", args, "next-save", wrapper=wrapper)
            receipt = json.loads(response.content)
            assert receipt["ok"] and receipt["effect"] == "memory_only"
            old = copy.deepcopy(memory.service.read(receipt["id"])["value"])
            assert "Matter: User's reminder sound" in old["content"]
            assert old["edit_state"]["units"][0]["assertion"]["role"] == "user"
            assert invoke(memory, "save_memory", args, "next-save", wrapper=wrapper) == response
            memory.service.capture_user("s", "u2", "Remember my soft reminder tone now.")
            context = memory.writer_context("s", "u2", "functional-m-test-v1")
            assert context["writer_packet"]["records"][0]["matter"] == "User's reminder sound"
            new_unit = {
                "text": "User reports a soft reminder tone.",
                "evidence": ["e1"],
                "assertion": {"source": "e1", "kind": "reported"},
            }
            proposal = (
                {"action": "rewrite", "target": "r1", "units": [
                    new_unit,
                    {"text": "User reports bright Tuesday reminders.", "evidence": [],
                     "keep_support": ["h2"], "assertion": {"keep": "h2"}},
                ]}
                if not memory.local
                else {
                    "action": "edit",
                    "target": "r1",
                    "edits": [
                        {
                            **new_unit,
                            "operation": "change_value" if arm == "M" else "replace",
                            "target_unit": "u1",
                        }
                    ],
                }
            )
            changed = json.loads(
                invoke(
                    memory,
                    "update_memory",
                    {"proposal": clause_proposal(proposal, conditioned=memory.conditioned)},
                    "next-update",
                    "u2",
                    app.call_wrapper(memory.service, "s", "u2"),
                ).content
            )
            assert changed["ok"] and changed["id"] == receipt["id"] and changed["revision"] == 2
            assert memory.service.read(receipt["id"], 1)["value"] == old
            assert memory.service.read(receipt["id"])["value"]["scope"] == {"project": "gallery"}
            page = json.loads(invoke(
                memory, "read_memory", {"record_id": receipt["id"]}, "revision-read", "u2"
            ).content)
            evidence = page["items"][0]["revision_evidence"]
            assert [part["content"] for part in evidence] == ["Remember my soft reminder tone now."]
            assert evidence[0]["role"] == "user"
            assert app.world.snapshot() == before_world
            if not memory.local:
                memory.service.capture_user(
                    "s", "u3", "Withdraw bright Tuesday reminders; use the general soft tone."
                )
                context = memory.writer_context("s", "u3", "functional-m-test-v1")
                current = copy.deepcopy(memory.service.read(receipt["id"])["value"])
                partial = clause_proposal(
                    {"action": "rewrite", "target": "r1", "revision_evidence": ["e1"],
                     "units": [{"text": "User reports a soft reminder tone.", "evidence": [],
                                "keep_support": ["h1"], "assertion": {"keep": "h1"}}]},
                    conditioned=memory.conditioned,
                )
                wrapper = app.call_wrapper(memory.service, "s", "u3")
                response = invoke(
                    memory, "update_memory", {"proposal": partial}, "remove-local", "u3", wrapper
                )
                assert json.loads(response.content)["revision"] == 3
                assert invoke(
                    memory, "update_memory", {"proposal": partial}, "remove-local", "u3", wrapper
                ) == response
                kept = memory.service.read(receipt["id"])["value"]
                assert len(kept["edit_state"]["units"]) == 1
                assert {
                    k: v for k, v in kept["edit_state"]["units"][0].items() if k != "unit_id"
                } == {
                    k: v for k, v in current["edit_state"]["units"][0].items() if k != "unit_id"
                }
                page = json.loads(invoke(
                    memory, "read_memory", {"record_id": receipt["id"]}, "cancel-read", "u3"
                ).content)
                assert [part["content"] for part in page["items"][0]["revision_evidence"]] == [
                    "Withdraw bright Tuesday reminders; use the general soft tone."
                ]
                assert app.world.snapshot() == before_world
            memory.service.capture_user("s", "u4", "Keep the existing reminder memory unchanged.")
            memory.writer_context("s", "u4", "functional-m-test-v1")
            no_change = {"action": "no_change", "target": "r1"}
            first_confirm = memory.apply_writer_proposal(cfg("u4"), "one-container", no_change)
            assert first_confirm["ok"]
            assert memory.apply_writer_proposal(cfg("u4"), "one-container", no_change)["replayed"]
            with pytest.raises(FunctionalRejection, match="DUPLICATE_RECORD_CONTAINER"):
                memory.apply_writer_proposal(cfg("u4"), "second-container", no_change)


@pytest.mark.parametrize("after_put", [False, True])
def test_next_sdk_unknown_first_commit_reopen_exact_operation(tmp_path, monkeypatch, after_put):
    def lost_put(original):
        def put(ns, key, value, **kw):
            if isinstance(value, dict) and value.get("_v13_1") and not failed[0]:
                failed[0] = True
                if after_put:
                    original(ns, key, value, **kw)
                raise RuntimeError("SCRIPTED_COMMIT_WINDOW")
            return original(ns, key, value, **kw)

        return put

    failed = [False]
    args = {"proposal": next_sdk_create()}
    with FunctionalApplication.open(tmp_path, "reservation", "alice") as app:
        with opened(tmp_path, interface_version="I2", features=NEXT_FEATURES) as memory:
            memory.service.capture_user("s", "u", "Remember my quiet reminders.")
            memory.writer_context("s", "u", "functional-m-test-v1")
            monkeypatch.setattr(memory.service.store, "put", lost_put(memory.service.store.put))
            first = invoke(
                memory,
                "save_memory",
                args,
                "next-unknown",
                wrapper=app.call_wrapper(memory.service, "s", "u"),
            )
            unknown = json.loads(first.content)
            assert unknown["status"] == "outcome_unknown"
    with FunctionalApplication.open(tmp_path, "reservation", "alice") as app:
        with opened(tmp_path, interface_version="I2", features=NEXT_FEATURES) as memory:
            memory.writer_context("s", "u", "functional-m-test-v1")
            second = invoke(
                memory,
                "save_memory",
                args,
                "next-unknown",
                wrapper=app.call_wrapper(memory.service, "s", "u"),
            )
            assert second == first
            found = memory.service.search("reminders", limit=10, include_raw=False)["records"]
            assert len(found) == int(after_put)


@pytest.mark.parametrize("invalid", [False, True])
def test_next_real_langgraph_dynamic_catalog_after_hook_and_original_wrapper(tmp_path, invalid):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from langgraph.checkpoint.sqlite import SqliteSaver

    from milai_lab.baselines.langmem_agent import build_agent

    class ScriptModel(FakeMessagesListChatModel):
        tool_save_communication: str = "legacy"
        tool_schema_communication: str = "legacy"
        research_profile: Any = None
        unknown_tool_feedback: bool = False
        bound: list[Any]

        def bind_tools(self, tools, **kwargs):
            self.bound.append([convert_to_openai_tool(tool) for tool in tools])
            return self

    with FunctionalApplication.open(tmp_path, "reservation", "alice") as app:
        with opened(tmp_path, interface_version="I2", features=NEXT_FEATURES) as memory:
            memory.service.capture_user("s", "u", "Remember my quiet reminders.")
            proposal = next_sdk_create()
            if invalid:
                proposal["clauses"][0]["evidence"] = ["e99"]
            model = ScriptModel(
                bound=[],
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "save_memory",
                                "id": "scripted-save",
                                "type": "tool_call",
                                "args": {"proposal": proposal},
                            }
                        ],
                    ),
                    AIMessage(content="done"),
                ]
            )
            hooks = []

            def hook(state, config):
                memory.writer_context("s", "u", "functional-m-test-v1")
                hooks.append("actual_context")
                return {"llm_input_messages": state["messages"]}

            def catalog(config):
                assert hooks
                return memory.writer_tools(config)

            before = app.world.snapshot()
            with SqliteSaver.from_conn_string(str(tmp_path / "graph.sqlite")) as saver:
                agent = build_agent(
                    model,
                    memory.service.store,
                    saver,
                    memory_tools=memory.tools(),
                    benchmark_view_hook=hook,
                    model_tools_provider=catalog,
                    business_call_wrapper=app.call_wrapper(memory.service, "s", "u"),
                )
                final = agent.invoke(
                    {"messages": [HumanMessage(content="Remember my quiet reminders.")]}, cfg()
                )
            first_catalog = {t["function"]["name"]: t for t in model.bound[0]}
            assert "update_memory" not in first_catalog
            assert '"enum"' in json.dumps(first_catalog["save_memory"])
            assert '"e1"' in json.dumps(first_catalog["save_memory"])
            clause_schema = first_catalog["save_memory"]["function"]["parameters"]["properties"][
                "proposal"
            ]["properties"]["clauses"]["items"]
            for variant in clause_schema["oneOf"]:
                assert "binding" in variant["properties"]["conditions"]["items"]["oneOf"][0][
                    "properties"
                ]
            result = next(
                msg
                for msg in final["messages"]
                if getattr(msg, "tool_call_id", None) == "scripted-save"
            )
            assert result.status == ("error" if invalid else "success")
            assert len(memory.service.search("reminders", include_raw=False)["records"]) == int(
                not invalid
            )
            assert app.world.snapshot() == before


@contextmanager
def opened(root: Path, *, owner: str = "alice", **options: Any) -> Any:
    root.mkdir(exist_ok=True)
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        service = MemoryService(
            store,
            ("functional-m", owner),
            owner,
            root / "memory.lock",
            functional_contract="functional_v1",
        )
        yield FunctionalEditMemory(
            service, len, material_limit=30000, read_limit=12, existing_confirmation=True, **options
        )


def turn(memory: FunctionalEditMemory, message: str, text: str) -> list[str]:
    ref = memory.service.capture_user("s", message, text)["source_ref"]
    packet = memory.context("s", message, "functional-m-test-v1")
    return [
        u["fragment_handle"]
        for u in packet["items"]
        if u["type"] == "fragment" and u["source_ref"] == ref
    ]


def invoke(
    memory: FunctionalEditMemory,
    name: str,
    args: dict[str, Any],
    call_id: str,
    turn_id: str = "u",
    wrapper: Any = None,
) -> Any:
    call = {"name": name, "args": args, "id": call_id, "type": "tool_call"}
    tool = next(t for t in memory.tools() if t.name == name)
    config = cfg(turn_id, owner=memory.service.owner)
    if wrapper is None:
        return tool.invoke(call, config=config)
    request = SimpleNamespace(
        tool_call=call,
        runtime=SimpleNamespace(config=config),
        state={"messages": [AIMessage(content="", id="g-" + call_id, tool_calls=[call])]},
    )
    return wrapper(request, lambda request: tool.invoke(request.tool_call, config=config))


def save_args(handles: list[str]) -> dict[str, Any]:
    return {
        "units": [
            {"text": "Use quiet reminders", "evidence": handles},
            {"text": "Only during this exhibition", "role": "condition", "evidence": handles},
        ],
        "relations": [{"source": 1, "relation_type": "modifies", "target": 0, "evidence": handles}],
        "scope": {"project": "exhibition"},
    }


def plain_args(handles: list[str]) -> dict[str, Any]:
    return {
        "units": [
            {"text": "Use quiet reminders", "evidence": handles},
            {"text": "Keep supplier labels unchanged", "evidence": handles},
            {"text": "Only during this exhibition", "evidence": handles},
        ],
        "scope": {"project": "exhibition"},
    }


def whole_rewrite_args(
    row: dict[str, Any], text: str, evidence: list[str]
) -> dict[str, Any]:
    state = row["value"]["edit_state"]
    indexes = {unit["unit_id"]: i for i, unit in enumerate(state["units"])}
    units = [
        {"text": text if i == 0 else unit["text"], "role": unit["role"], "evidence": evidence}
        for i, unit in enumerate(state["units"])
    ]
    return {
        "read_handle": row["candidate_handle"],
        "units": units,
        "relations": [{
            "source": indexes[relation["source_unit"]],
            "target": indexes[relation["target_unit"]],
            "relation_type": relation["relation_type"], "evidence": evidence,
        } for relation in state["relations"]],
    }


def test_public_mapping_retains_the_default_m_identity(tmp_path: Path) -> None:
    assert FUNCTIONAL_ARMS == {
        FUNCTIONAL_B0_METHOD: "B0", FUNCTIONAL_B1_METHOD: "B1",
        FUNCTIONAL_B2_METHOD: "B2", FUNCTIONAL_METHOD: "M",
        "milai_fact_append_v1": "Append-only",
    }
    with opened(tmp_path) as memory:
        assert memory.arm == "M" and memory.policy["memory_method"] == FUNCTIONAL_METHOD
        assert memory.policy["integration_version"] == "functional_m_v1"
        assert memory.formation_support_review is None and memory.revision_support_review is None


def test_append_host_correction_keeps_old_report_and_original_assertion_times(tmp_path):
    with opened(tmp_path, arm="Append-only", interface_version="I2", features=NEXT_FEATURES,
                maintenance_recipe="single_pass") as memory:
        first = None
        for index, color in enumerate(["blue", "red"]):
            message_id = "u" if index == 0 else "u2"
            date = f"2030-01-0{index + 1}"
            memory.service.capture_user("s", message_id, f"My marker is now {color}.",
                                        occurred_at=date)
            memory.context("s", message_id, "functional-m-test-v1")

            def call(stage, messages, schema, reported=color):
                assert stage == "edit"
                packet = json.loads(messages[1]["content"])["delivery"]
                if reported == "red":
                    assert any("blue" in str(record) for record in packet["records"])
                return {"creates": [{"action": "create", "matter": "Marker", "clauses": [{
                    "text": f"My marker is now {reported}.", "evidence": ["e1"],
                    "assertion": {"source": "e1", "kind": "reported"},
                }]}], "records": {}}

            results = memory.maintain_sources(cfg(message_id), recipe="single_pass",
                                              model_call=call, allowed=True)
            assert results[0]["status"] == "completed" and results[0]["semantic_write_performed"]
            records = memory.service.records()
            if first is None:
                first = copy.deepcopy(records[0])
            assert memory.service.read(first["id"])["value"] == first["value"]
        assert len(records) == 2
        assert {r["value"]["method_arm"] for r in records} == {"Append-only"}
        assert {r["value"]["edit_state"]["units"][0]["assertion"]["occurred_at"]
                for r in records} == {"2030-01-01", "2030-01-02"}
        assert "update_memory" not in {tool.name for tool in memory.writer_tools(cfg("u2"))}
        with pytest.raises(FunctionalRejection, match="APPEND_ONLY_CREATE_REQUIRED"):
            memory.apply_writer_proposal(cfg("u2"), "rewrite", {"action": "rewrite"})
        assert memory.service.records() == records


def test_opt_in_actual_wrapper_save_confirmation_and_archived_continuation(tmp_path: Path) -> None:
    with FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app:
        with opened(tmp_path) as memory:
            handles = turn(
                memory, "u", "Remember: use quiet reminders only during this exhibition."
            )
            wrapper = app.call_wrapper(
                memory.service,
                "s",
                "u",
                memory_mutation_names=(
                    "save_memory",
                    "update_memory",
                    "confirm_existing_memory",
                    "forget_memory",
                ),
            )
            before = app.world.snapshot()
            args = save_args(handles)
            first_message = invoke(memory, "save_memory", args, "save", wrapper=wrapper)
            saved = json.loads(first_message.content)
            assert saved["ok"] and saved["effect"] == "memory_only"
            row = memory.service.read(saved["id"])
            state = row["value"]["edit_state"]
            assert state["representation"] == "conditioned_v1" and len(state["relations"]) == 1
            assert row["value"]["scope"] == {"project": "exhibition"}
            assert invoke(memory, "save_memory", args, "save", wrapper=wrapper) == first_message
            duplicate = json.loads(
                invoke(memory, "save_memory", args, "different-save-id", wrapper=wrapper).content
            )
            assert duplicate["duplicate_request"] and duplicate["id"] == saved["id"]
            confirmed = json.loads(
                invoke(
                    memory,
                    "confirm_existing_memory",
                    {"read_handle": row["candidate_handle"]},
                    "confirm",
                    wrapper=wrapper,
                ).content
            )
            assert confirmed["status"] == "no_change" and confirmed["revision"] == 1
            # New explicit public continuation reuses a genuinely delivered archived input.
            pending = turn(memory, "pending", "Remember another exhibition's quiet reminders.")
            pending_args = save_args(pending)
            pending_ref = memory.service.source_fragment(pending[0])["source_ref"]
            assert not memory.service.semantic_receipts(pending_ref)
            turn(memory, "continue", "Continue the prior explicit save request.")
            continuation = app.call_wrapper(memory.service, "s", "continue")
            resumed = json.loads(
                invoke(
                    memory, "save_memory", pending_args, "continue-save", "continue", continuation
                ).content
            )
            assert resumed["ok"] and resumed["id"] != saved["id"]
            assert resumed["source_refs"] == [pending_ref]
            assert app.world.snapshot() == before
            assert FunctionalMemory(memory.service, len).policy.get("memory_method") is None


@pytest.mark.parametrize("stage", ["formation", "revision"])
@pytest.mark.parametrize("arm", ["M", "B1", "B0", "B2"])
@pytest.mark.parametrize("bounded", [False, True])
def test_actual_review_rejection_reopen_and_corrected_formation_or_local_revision(
    tmp_path: Path, stage: str, arm: str, bounded: bool
) -> None:
    reviewed: list[dict[str, Any]] = []

    def review(evidence: dict[str, Any], delivered: Callable[[], None]) -> None:
        prepared = memory.service.store.get(
            (*memory.service.namespace, "prepared_proposals"),
            reference_key(["s", evidence["proposal_id"]]),
        )
        assert prepared is not None and prepared.value["owner"] == "alice"
        proposal = prepared.value["proposal"]
        content = next(c for c in evidence["changes"] if c["field"] == "content")
        assert content["after"] == proposal["content"]
        assert proposal["edit_state"]["representation"] == (
            "conditioned_v1" if arm in {"M", "B2"} else "plain_v1"
        )
        for change in evidence["changes"]:
            for quote in change["selected_original_fragments"]:
                original = memory.service.source_fragment(quote["fragment_handle"])
                assert quote["content"] == original["content"]
                assert quote["source_revision"] == original["source_revision"]
                assert quote["source_role"] == "user"
        reviewed.append(copy.deepcopy(evidence))
        delivered()
        if evidence["proposal_id"] == "unsupported":
            assert "Unsupported broad claim" in content["after"]
            raise FunctionalRejection("SCRIPTED_UNSUPPORTED_M_PROPOSAL")

    options = {"formation_support_review": review, "revision_support_review": review, "arm": arm,
               "semantic_reproposal_policy": "maintenance_two_proposals_v1" if bounded
               else "message_limit_only"}
    with (
        FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app,
        opened(tmp_path, **options) as memory,
    ):
        original = turn(memory, "u", "Use quiet reminders only during this exhibition.")
        saved = json.loads(
            invoke(
                memory, "save_memory",
                save_args(original) if memory.conditioned else plain_args(original),
                "initial",
                wrapper=app.call_wrapper(memory.service, "s", "u"),
            ).content
        )
        initial = memory.service.read(saved["id"])
        before_world = app.world.snapshot()
        correction = turn(memory, "correction", "On opening day use written reminders instead.")
        if stage == "formation":
            name = "save_memory"
            args = {"units": [{"text": "Unsupported broad claim", "evidence": correction}]}
            corrected_args = {"units": [{
                "text": "On opening day use written reminders instead.",
                "evidence": correction,
            }]}
        else:
            name = "update_memory"
            edit = {
                "operation": "override" if arm == "M" else "replace",
                "target_unit": initial["value"]["edit_state"]["units"][0]["unit_id"],
                "text": "Unsupported broad claim",
                "evidence": correction,
            }
            if arm == "M":
                edit["condition"] = "For all future events"
            args = {"read_handle": initial["candidate_handle"], "edits": [edit]}
            corrected_args = {"read_handle": initial["candidate_handle"], "edits": [{
                **edit, "text": "Only on opening day use written reminders",
            }]}
            if arm == "M":
                corrected_args["edits"][0]["condition"] = "Only on opening day"
            if not memory.local:
                rewrite = save_args(original) if memory.conditioned else plain_args(original)
                args = {"read_handle": initial["candidate_handle"],
                        "units": copy.deepcopy(rewrite["units"]),
                        "relations": rewrite.get("relations", [])}
                args["units"][0].update(text="Unsupported broad claim", evidence=correction)
                corrected_args = copy.deepcopy(args)
                corrected_args["units"][0]["text"] = "Only on opening day use written reminders"
        response = invoke(
            memory, name, args, "unsupported", "correction",
            app.call_wrapper(memory.service, "s", "correction"),
        )
        rejected = json.loads(response.content)
        assert rejected["status"] == "rejected" and rejected["effect"] == "none"
        assert "SCRIPTED_UNSUPPORTED_M_PROPOSAL" in rejected["reason"]
        assert len(memory.service.records()) == 1
        assert memory.service.read(saved["id"])["value"] == initial["value"]
        assert memory.service.read(saved["id"], 1)["value"] == initial["value"]
        assert not memory.service.read(saved["id"], 2)["ok"]
        prior_count = len(reviewed)
        prepared = memory.service.store.get(
            (*memory.service.namespace, "prepared_proposals"), reference_key(["s", "unsupported"])
        )
        assert prepared is not None
        rejected_proposal = copy.deepcopy(prepared.value)
        if stage == "revision":
            assert reviewed[-1]["old_content"] == initial["value"]["content"]
            assert reviewed[-1]["read_revision"] == 1
    with (
        FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app,
        opened(tmp_path, **options) as memory,
    ):
        memory.context("s", "correction", "functional-m-test-v1")
        wrapper = app.call_wrapper(memory.service, "s", "correction")
        assert invoke(memory, name, args, "unsupported", "correction", wrapper) == response
        assert len(reviewed) == prior_count
        recovered = memory.service.store.get(
            (*memory.service.namespace, "prepared_proposals"), reference_key(["s", "unsupported"])
        )
        assert recovered is not None and recovered.value == rejected_proposal
        assert memory.service.read(saved["id"])["value"] == initial["value"]
        accepted_message = invoke(
            memory, name, corrected_args, "corrected", "correction", wrapper
        )
        accepted = json.loads(accepted_message.content)
        assert accepted["ok"] and accepted["status"] == "committed"
        assert accepted["effect"] == "memory_only" and len(reviewed) == prior_count + 1
        assert memory.service.read(saved["id"], 1)["value"] == initial["value"]
        if stage == "revision":
            current = memory.service.read(saved["id"])
            assert accepted["id"] == saved["id"] and accepted["revision"] == 2
            assert current["value"]["scope"] == initial["value"]["scope"]
            if arm == "M":
                assert current["value"]["edit_state"]["units"][:2] == (
                    initial["value"]["edit_state"]["units"]
                )
            elif arm == "B1":
                assert current["value"]["edit_state"]["units"][1:] == (
                    initial["value"]["edit_state"]["units"][1:]
                )
            else:
                assert [u["text"] for u in current["value"]["edit_state"]["units"]][1:] == (
                    [u["text"] for u in initial["value"]["edit_state"]["units"]][1:]
                )
                assert not {u["unit_id"] for u in current["value"]["edit_state"]["units"]} & {
                    u["unit_id"] for u in initial["value"]["edit_state"]["units"]
                }
            if memory.local:
                replay = memory.update_edit(
                    cfg("correction"), "corrected", corrected_args["read_handle"],
                    corrected_args["edits"],
                )
            else:
                replay = memory.rewrite_edit(
                    cfg("correction"), "corrected", corrected_args["read_handle"],
                    corrected_args["units"], corrected_args["relations"],
                )
        else:
            assert accepted["id"] != saved["id"] and accepted["revision"] == 1
            replay = memory.save_edit(cfg("correction"), "corrected", corrected_args["units"])
        assert replay["replayed"] and replay["original_status"] == "committed"
        assert len(reviewed) == prior_count + 1
        assert invoke(memory, name, corrected_args, "corrected", "correction", wrapper) == (
            accepted_message
        )
        assert app.world.snapshot() == before_world


def test_same_id_override_retract_history_reader_and_forget_after_reopen(tmp_path: Path) -> None:
    with (
        FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app,
        opened(tmp_path) as memory,
    ):
        original = turn(memory, "u", "Use quiet reminders only during this exhibition.")
        saved = json.loads(invoke(memory, "save_memory", save_args(original), "save").content)
        old = memory.service.read(saved["id"])
        old_state = copy.deepcopy(old["value"]["edit_state"])
        evidence = turn(memory, "scope", "For opening day use written reminders instead.")
        edits = [
            {
                "operation": "override",
                "target_unit": old_state["units"][0]["unit_id"],
                "text": "Use written reminders",
                "condition": "Only on opening day",
                "shared_conditions": [old_state["units"][1]["unit_id"]],
                "evidence": evidence,
            }
        ]
        changed = json.loads(
            invoke(
                memory,
                "update_memory",
                {"read_handle": old["candidate_handle"], "edits": edits},
                "override",
                "scope",
                app.call_wrapper(memory.service, "s", "scope"),
            ).content
        )
        assert changed["ok"] and changed["id"] == saved["id"] and changed["revision"] == 2
        current = memory.service.read(saved["id"])
        state = current["value"]["edit_state"]
        assert state["units"][:2] == old_state["units"]
        assert current["value"]["scope"] == old["value"]["scope"]
        assert memory.service.read(saved["id"], 1)["value"]["edit_state"] == old_state
        page = json.loads(
            invoke(memory, "read_memory", {"record_id": saved["id"]}, "read", "scope").content
        )
        assert len(page["items"]) == len(state["units"])
        assert {u["edit_unit"]["unit_id"] for u in page["items"]} == {
            u["unit_id"] for u in state["units"]
        }
        assert {r["relation_id"] for u in page["items"] for r in u["edit_relations"]} == {
            r["relation_id"] for r in state["relations"]
        }
        assert len(canonical(page)) <= memory.material_limit
        nested = json.loads(
            invoke(
                memory,
                "update_memory",
                {
                    "read_handle": current["candidate_handle"],
                    "edits": [
                        {
                            "operation": "override",
                            "target_unit": next(
                                u["unit_id"]
                                for u in state["units"]
                                if u["text"] == "Use written reminders"
                            ),
                            "text": "Nested reminder",
                            "condition": "Nested scope",
                            "evidence": evidence,
                        }
                    ],
                },
                "nested",
                "scope",
                app.call_wrapper(memory.service, "s", "scope"),
            ).content
        )
        assert not nested["ok"] and memory.service.read(saved["id"])["value"] == current["value"]
        stale = json.loads(
            invoke(
                memory,
                "update_memory",
                {"read_handle": old["candidate_handle"], "edits": edits},
                "stale",
                "scope",
                app.call_wrapper(memory.service, "s", "scope"),
            ).content
        )
        assert stale["reason"] == "revision_conflict"
        scoped = next(u for u in state["units"] if u["text"] == "Use written reminders")
        cancellation = turn(memory, "cancel", "Cancel the opening-day exception.")
        canceled = json.loads(
            invoke(
                memory,
                "update_memory",
                {
                    "read_handle": current["candidate_handle"],
                    "edits": [
                        {
                            "operation": "retract",
                            "target_unit": scoped["unit_id"],
                            "evidence": cancellation,
                        }
                    ],
                },
                "cancel",
                "cancel",
                app.call_wrapper(memory.service, "s", "cancel"),
            ).content
        )
        assert canceled["revision"] == 3
        surviving = memory.service.read(saved["id"])["value"]["edit_state"]
        assert surviving["units"][:2] == old_state["units"]
        assert not any(r["relation_type"] == "overrides" for r in surviving["relations"])
        reader = FunctionalEditMemory(
            memory.service, len, interface_version="I2", features=NEXT_FEATURES,
            material_limit=memory.material_limit, read_limit=memory.read_limit,
        )
        page = json.loads(invoke(
            reader, "read_memory", {"record_id": saved["id"]}, "read-after-cancel", "cancel"
        ).content)
        prior_scope = [item["revision_scope"] for item in page["items"] if "revision_scope" in item]
        assert len(prior_scope) == 1
        assert prior_scope[0]["current_unit_id"] == old_state["units"][0]["unit_id"]
        assert prior_scope[0]["previous_revision"] == 2
        assert len(canonical(page)) <= reader.material_limit
        assert memory.service.read(saved["id"])["value"]["edit_state"] == surviving
    with opened(tmp_path) as memory:
        turn(memory, "forget", "Forget the exhibition memory and its supporting sources.")
        current = memory.service.read(saved["id"])
        receipt = json.loads(
            invoke(
                memory,
                "forget_memory",
                {"read_handle": current["candidate_handle"]},
                "forget",
                "forget",
            ).content
        )
        assert receipt["ok"] and not memory.service.read(saved["id"])["ok"]
        assert memory.service.source(saved["source_ref"]) is None
    with opened(tmp_path) as memory:
        assert not memory.service.read(saved["id"], 1)["ok"]


@pytest.mark.parametrize("arm", ["B0", "B2"])
def test_whole_rewrite_actual_sdk_reader_same_id_scope_relations_cas_and_reopen(
    tmp_path: Path, arm: str,
) -> None:
    with (
        FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app,
        opened(tmp_path, arm=arm) as memory,
    ):
        original = turn(memory, "u", "Exhibition-only quiet reminders; supplier labels unchanged.")
        formation_args = save_args(original) if memory.conditioned else plain_args(original)
        saved = json.loads(invoke(
            memory, "save_memory", formation_args, "save",
            wrapper=app.call_wrapper(memory.service, "s", "u"),
        ).content)
        assert saved["ok"] and saved["revision"] == 1
        initial = memory.service.read(saved["id"])
        assert initial["value"]["method_arm"] == arm
        before_world = app.world.snapshot()
        evidence = turn(memory, "rewrite", "Exhibition-only written reminders; labels unchanged.")
        args = whole_rewrite_args(initial, "Use written reminders", evidence)
        wrapper = app.call_wrapper(memory.service, "s", "rewrite")
        rewritten_message = invoke(memory, "update_memory", args, "rewrite", "rewrite", wrapper)
        rewritten = json.loads(rewritten_message.content)
        assert rewritten["ok"] and rewritten["id"] == saved["id"] and rewritten["revision"] == 2
        current = memory.service.read(saved["id"])
        state = current["value"]["edit_state"]
        old_state = initial["value"]["edit_state"]
        assert state["representation"] == ("conditioned_v1" if arm == "B2" else "plain_v1")
        assert [u["text"] for u in state["units"]] == [u["text"] for u in args["units"]]
        assert [u["role"] for u in state["units"]] == [u["role"] for u in old_state["units"]]
        assert not {u["unit_id"] for u in state["units"]} & {
            u["unit_id"] for u in old_state["units"]
        }  # Whole rewrite reissues even retained units; it never applies a selected local patch.
        for relation, expected in zip(state["relations"], args["relations"], strict=True):
            assert relation["source_unit"] == state["units"][expected["source"]]["unit_id"]
            assert relation["target_unit"] == state["units"][expected["target"]]["unit_id"]
            assert relation["relation_type"] == expected["relation_type"]
        assert current["value"]["scope"] == initial["value"]["scope"]
        assert current["value"]["functional_support"]["scope.project"] == (
            initial["value"]["functional_support"]["scope.project"]
        )
        assert memory.service.read(saved["id"], 1)["value"] == initial["value"]
        page = json.loads(invoke(memory, "read_memory", {
            "record_id": saved["id"]}, "read", "rewrite").content)
        assert {u["edit_unit"]["unit_id"] for u in page["items"]} == {
            u["unit_id"] for u in state["units"]
        }
        assert {r["relation_id"] for u in page["items"] for r in u["edit_relations"]} == {
            r["relation_id"] for r in state["relations"]
        }
        assert len(canonical(page)) <= memory.material_limit
        no_change = json.loads(invoke(memory, "update_memory", {
            "read_handle": current["candidate_handle"],
        }, "no-change", "rewrite", wrapper).content)
        assert no_change["status"] == "no_change" and no_change["effect"] == "none"
        assert no_change["revision"] == 2
        confirmed = json.loads(invoke(memory, "confirm_existing_memory", {
            "read_handle": current["candidate_handle"],
        }, "confirm", "rewrite", wrapper).content)
        assert confirmed["status"] == "no_change" and confirmed["revision"] == 2
        stale = json.loads(invoke(memory, "update_memory", {
            "read_handle": initial["candidate_handle"],
        }, "stale", "rewrite", wrapper).content)
        assert stale["reason"] == "revision_conflict"
        with pytest.raises(ValidationError):
            invoke(memory, "update_memory", {
                "read_handle": current["candidate_handle"], "edits": [],
            }, "local-edits", "rewrite")
        with pytest.raises(ValidationError):
            invoke(memory, "update_memory", {
                **args, "read_handle": current["candidate_handle"], "edits": [],
            }, "rewrite-and-local-edits", "rewrite")
        with pytest.raises(FunctionalRejection, match="FUNCTIONAL_EDIT_FULL_REWRITE_REQUIRED"):
            memory.update_edit(cfg("rewrite"), "local-direct", current["candidate_handle"], [])
        assert memory.service.read(saved["id"])["value"] == current["value"]
        assert app.world.snapshot() == before_world
    with opened(tmp_path, arm=arm) as memory:
        assert memory.service.read(saved["id"])["value"] == current["value"]
        assert memory.service.read(saved["id"], 1)["value"] == initial["value"]
        assert not memory.service.read(saved["id"], 3)["ok"]


@pytest.mark.parametrize("arm", ["B0", "B2"])
@pytest.mark.parametrize("after_put", [False, True])
def test_whole_rewrite_unknown_store_window_wrapper_recovery_never_recommits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str, after_put: bool,
) -> None:
    with (
        FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app,
        opened(tmp_path, arm=arm) as memory,
    ):
        original = turn(memory, "u", "Only the exhibition uses quiet reminders.")
        initial_args = save_args(original) if memory.conditioned else plain_args(original)
        saved = json.loads(invoke(memory, "save_memory", initial_args, "save").content)
        initial = memory.service.read(saved["id"])
        evidence = turn(memory, "rewrite", "Only the exhibition uses written reminders.")
        args = whole_rewrite_args(initial, "Use written reminders", evidence)
        real_put = memory.service.store.put
        entered = 0

        def failed(ns: tuple[str, ...], key: str, value: Any, **options: Any) -> None:
            nonlocal entered
            semantic = ns == memory.service.namespace and "_v13_1" in value
            if semantic:
                entered += 1
                if not after_put:
                    raise OSError("rewrite commit acknowledgement unavailable before put")
            real_put(ns, key, value, **options)
            if semantic:
                raise OSError("rewrite commit acknowledgement lost after put")

        monkeypatch.setattr(memory.service.store, "put", failed)
        wrapper = app.call_wrapper(memory.service, "s", "rewrite")
        response = invoke(memory, "update_memory", args, "rewrite", "rewrite", wrapper)
        receipt = json.loads(response.content)
        assert receipt["status"] == "outcome_unknown" and receipt["phase"] == "semantic_commit"
        assert entered == 1
        monkeypatch.setattr(memory.service.store, "put", real_put)
        assert invoke(memory, "update_memory", args, "rewrite", "rewrite", wrapper) == response
        assert memory.service.read(saved["id"])["value"]["revision"] == (2 if after_put else 1)
    with (
        FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app,
        opened(tmp_path, arm=arm) as memory,
    ):
        memory.context("s", "rewrite", "functional-m-test-v1")
        wrapper = app.call_wrapper(memory.service, "s", "rewrite")
        assert invoke(memory, "update_memory", args, "rewrite", "rewrite", wrapper) == response
        assert memory.service.read(saved["id"])["value"]["revision"] == (2 if after_put else 1)
        assert memory.service.read(saved["id"], 1)["value"] == initial["value"]
        assert not memory.service.read(saved["id"], 3)["ok"]
        if after_put:
            replay = memory.rewrite_edit(
                cfg("rewrite"), "rewrite", args["read_handle"], args["units"], args["relations"]
            )
            assert replay["replayed"] and replay["revision"] == 2
            assert replay["original_status"] == "committed"


@pytest.mark.parametrize("arm", ["B0", "B2"])
def test_whole_rewrite_rejects_undelivered_unit_or_relation_and_ambiguous_withdrawal(
    tmp_path: Path, arm: str,
) -> None:
    with opened(tmp_path, arm=arm) as memory:
        original = turn(memory, "u", "Exhibition-only quiet reminders.")
        saved = json.loads(invoke(
            memory, "save_memory",
            save_args(original) if memory.conditioned else plain_args(original),
            "save",
        ).content)
        row = memory.service.read(saved["id"])
        unseen = memory.service.capture_user("archive", "unseen", "Undelivered rewrite")
        handle = memory.service.source_fragments(unseen["source_ref"])[0]["fragment_handle"]
        args = whole_rewrite_args(row, "Undelivered rewrite", [handle])
        rejected = json.loads(invoke(memory, "update_memory", args, "unseen").content)
        assert rejected["reason"] == "FUNCTIONAL_EDIT_ACTUALLY_DELIVERED_FRAGMENT_REQUIRED"
        if memory.conditioned:
            args = whole_rewrite_args(row, "Use quiet reminders", original)
            args["relations"][0]["evidence"] = [handle]
            rejected = json.loads(invoke(memory, "update_memory", args, "unseen-relation").content)
            assert rejected["reason"] == "FUNCTIONAL_EDIT_ACTUALLY_DELIVERED_FRAGMENT_REQUIRED"
        for ordinal, invalid in enumerate([
            {"units": []}, {"units": None, "withdrawal_evidence": original},
            {"units": [{"text": "Still asserted", "evidence": original}],
             "withdrawal_evidence": original},
        ]):
            rejected = json.loads(invoke(memory, "update_memory", {
                "read_handle": row["candidate_handle"], **invalid,
            }, "ambiguous-" + str(ordinal)).content)
            assert rejected["status"] == "rejected" and rejected["effect"] == "none"
            assert memory.service.read(saved["id"])["value"] == row["value"]
        if memory.conditioned:
            rejected = json.loads(invoke(memory, "update_memory", {
                "read_handle": row["candidate_handle"], "units": [{
                    "text": "Only a dangling condition remains", "role": "condition",
                    "evidence": original,
                }],
            }, "condition-only-withdrawal").content)
            assert rejected["reason"] == "FUNCTIONAL_EDIT_WITHDRAWAL_REQUIRES_EMPTY_UNITS"
        assert memory.service.read(saved["id"])["value"] == row["value"]
        assert not memory.service.read(saved["id"], 2)["ok"]


def test_b1_actual_wrapper_same_id_replace_insert_delete_reader_and_reopen(tmp_path: Path) -> None:
    versions: list[dict[str, Any]] = []
    with (
        FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app,
        opened(tmp_path, arm="B1") as memory,
    ):
        assert memory.policy["memory_method"] == FUNCTIONAL_B1_METHOD
        assert "replace/insert/delete" in memory.instructions()
        assert "B1 plain" in next(t for t in memory.tools() if t.name == "save_memory").description
        handles = turn(memory, "u", "Quiet reminders; supplier labels unchanged; exhibition only.")
        before_world = app.world.snapshot()
        formation_args = plain_args(handles)
        wrapper = app.call_wrapper(memory.service, "s", "u")
        formation = invoke(memory, "save_memory", formation_args, "save", wrapper=wrapper)
        saved = json.loads(formation.content)
        assert saved["ok"] and saved["revision"] == 1
        assert invoke(memory, "save_memory", formation_args, "save", wrapper=wrapper) == formation
        initial = memory.service.read(saved["id"])
        state = initial["value"]["edit_state"]
        assert state["representation"] == "plain_v1" and not state["relations"]
        assert initial["value"]["method_arm"] == "B1"
        versions.append(copy.deepcopy(initial["value"]))
        target = state["units"][0]["unit_id"]
        edit_handles = turn(memory, "edit", "Use written reminders. Add an opening-day agenda.")
        wrapper = app.call_wrapper(memory.service, "s", "edit")
        replaced = json.loads(invoke(memory, "update_memory", {
            "read_handle": initial["candidate_handle"], "edits": [{
                "operation": "replace", "target_unit": target,
                "text": "Use written reminders", "evidence": edit_handles,
            }],
        }, "replace", "edit", wrapper).content)
        assert replaced["id"] == saved["id"] and replaced["revision"] == 2
        current = memory.service.read(saved["id"])
        changed_units = current["value"]["edit_state"]["units"]
        assert changed_units[0]["unit_id"] == target
        assert changed_units[1:] == state["units"][1:]
        versions.append(copy.deepcopy(current["value"]))
        page = json.loads(invoke(memory, "read_memory", {
            "record_id": saved["id"]}, "read-after-replace", "edit").content)
        assert [u["content"] for u in page["items"]] == [u["text"] for u in changed_units]
        assert all(u["method_arm"] == "B1" and not u["edit_relations"] for u in page["items"])
        inserted = json.loads(invoke(memory, "update_memory", {
            "read_handle": page["items"][0]["read_handle"], "edits": [{
                "operation": "insert", "target_unit": target,
                "text": "Provide an opening-day agenda", "evidence": edit_handles,
            }],
        }, "insert", "edit", wrapper).content)
        assert inserted["id"] == saved["id"] and inserted["revision"] == 3
        current = memory.service.read(saved["id"])
        inserted_units = current["value"]["edit_state"]["units"]
        assert inserted_units[0] == changed_units[0] and inserted_units[2:] == changed_units[1:]
        assert inserted_units[1]["unit_id"] not in {u["unit_id"] for u in changed_units}
        versions.append(copy.deepcopy(current["value"]))
        canceled = turn(memory, "cancel", "Remove only the opening-day agenda; retain the rest.")
        deleted = json.loads(invoke(memory, "update_memory", {
            "read_handle": current["candidate_handle"], "edits": [{
                "operation": "delete", "target_unit": inserted_units[1]["unit_id"],
                "evidence": canceled,
            }],
        }, "delete", "cancel", app.call_wrapper(memory.service, "s", "cancel")).content)
        assert deleted["id"] == saved["id"] and deleted["revision"] == 4
        final = memory.service.read(saved["id"])
        assert final["value"]["edit_state"]["units"] == changed_units
        assert final["value"]["scope"] == initial["value"]["scope"]
        for revision, version in enumerate(versions, 1):
            assert memory.service.read(saved["id"], revision)["value"] == version
        stale = json.loads(invoke(memory, "update_memory", {
            "read_handle": initial["candidate_handle"], "edits": [],
        }, "stale", "cancel").content)
        assert stale["reason"] == "revision_conflict"
        assert app.world.snapshot() == before_world
    with opened(tmp_path, arm="B1") as memory:
        memory.context("s", "cancel", "functional-m-test-v1")
        current = memory.service.read(saved["id"])
        assert current["value"] == final["value"]
        no_change = json.loads(invoke(memory, "update_memory", {
            "read_handle": current["candidate_handle"], "edits": [],
        }, "no-change", "cancel").content)
        assert no_change["status"] == "no_change" and no_change["revision"] == 4
        for revision, version in enumerate(versions, 1):
            assert memory.service.read(saved["id"], revision)["value"] == version


def test_b1_rejects_other_representations_and_conditioned_operations(tmp_path: Path) -> None:
    with opened(tmp_path, arm="B1") as memory:
        handles = turn(memory, "u", "Only this exhibition uses quiet reminders.")
        ordinary = FunctionalMemory(memory.service, len).save(
            cfg(), "ordinary", "Only this exhibition uses quiet reminders.", handles
        )
        conditioned = FunctionalEditMemory(memory.service, len).save_edit(
            cfg(), "conditioned", save_args(handles)["units"], save_args(handles)["relations"]
        )
        assert ordinary["ok"] and conditioned["ok"]
        for receipt in (ordinary, conditioned):
            row = memory.service.read(receipt["id"])
            rejected = json.loads(invoke(memory, "update_memory", {
                "read_handle": row["candidate_handle"], "edits": [],
            }, "wrong-representation-" + receipt["id"]).content)
            assert rejected["status"] == "rejected" and rejected["effect"] == "none"
            assert rejected["reason"] == "FUNCTIONAL_EDIT_EXPLICIT_B1_FORMATION_REQUIRED"
            assert memory.service.read(receipt["id"])["value"] == row["value"]
        invalid_formation = json.loads(invoke(memory, "save_memory", {
            "units": [{"text": "Only this exhibition", "role": "condition", "evidence": handles}],
        }, "condition-in-plain").content)
        assert not invalid_formation["ok"] and len(memory.service.records()) == 2
        saved = json.loads(invoke(memory, "save_memory", plain_args(handles), "plain").content)
        assert saved["ok"]
        row = memory.service.read(saved["id"])
        rejected = json.loads(invoke(memory, "update_memory", {
            "read_handle": row["candidate_handle"], "edits": [{
                "operation": "override", "target_unit": row["value"]["edit_state"]["units"][0][
                    "unit_id"], "text": "Changed reminder", "condition": "Opening day",
                "evidence": handles,
            }],
        }, "wrong-operation").content)
        assert rejected["reason"] == "FUNCTIONAL_EDIT_B1_OPERATION_REQUIRED"
        assert memory.service.read(saved["id"])["value"] == row["value"]
        page = json.loads(invoke(memory, "read_memory", {
            "record_id": conditioned["id"]}, "read-condition").content)
        assert all(u["method_arm"] == "M" for u in page["items"])


@pytest.mark.parametrize("arm", ["M", "B1", "B0", "B2"])
def test_reject_source_ref_unseen_fragment_and_foreign_owner(tmp_path: Path, arm: str) -> None:
    with opened(tmp_path, arm=arm) as memory:
        turn(memory, "u", "Remember the supplied material.")
        unseen = memory.service.capture_user("archive", "unseen", "Undelivered text")["source_ref"]
        handle = memory.service.source_fragments(unseen)[0]["fragment_handle"]
        for selected in [unseen, handle]:
            receipt = json.loads(
                invoke(
                    memory,
                    "save_memory",
                    {"units": [{"text": "Undelivered text", "evidence": [selected]}]},
                    selected,
                ).content
            )
            assert not receipt["ok"] and receipt["status"] == "rejected"
        assert not memory.service.records()
        visible = json.loads(invoke(memory, "read_source", {"source_ref": unseen}, "read").content)
        saved = json.loads(
            invoke(
                memory,
                "save_memory",
                {
                    "units": [
                        {
                            "text": "Undelivered text",
                            "evidence": [visible["items"][0]["fragment_handle"]],
                        }
                    ]
                },
                "save",
            ).content
        )
        assert saved["ok"]
        with opened(tmp_path, owner="bob", arm=arm) as other:
            turn(other, "u", "Remember the supplied material.")
            foreign = json.loads(
                invoke(
                    other,
                    "save_memory",
                    {"units": [{"text": "Undelivered text", "evidence": [handle]}]},
                    "foreign",
                ).content
            )
            assert not foreign["ok"] and not other.service.records()


@pytest.mark.parametrize("after_put", [False, True])
@pytest.mark.parametrize("arm", ["M", "B1", "B0", "B2"])
def test_actual_wrapper_unknown_commit_reopen_same_identity_no_second_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    after_put: bool,
    arm: str,
) -> None:
    with FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app:
        with opened(tmp_path, arm=arm) as memory:
            hs = turn(memory, "u", "Use quiet reminders only during this exhibition.")
            args = save_args(hs) if memory.conditioned else plain_args(hs)
            original = memory.service.store.put

            def failed(ns: tuple[str, ...], key: str, value: Any, **kwargs: Any) -> None:
                actual_commit = ns == memory.service.namespace and "_v13_1" in value
                if actual_commit and not after_put:
                    raise OSError("no acknowledged semantic commit")
                original(ns, key, value, **kwargs)
                if actual_commit:
                    raise OSError("semantic commit acknowledged response lost")

            monkeypatch.setattr(memory.service.store, "put", failed)
            wrapper = app.call_wrapper(memory.service, "s", "u")
            response = invoke(memory, "save_memory", args, "save", wrapper=wrapper)
            unknown = json.loads(response.content)
            assert unknown["status"] == "outcome_unknown" and unknown["phase"] == "semantic_commit"
            monkeypatch.setattr(memory.service.store, "put", original)
            assert invoke(memory, "save_memory", args, "save", wrapper=wrapper) == response
            assert len(memory.service.records()) == int(after_put)
    with FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app:
        with opened(tmp_path, arm=arm) as memory:
            memory.context("s", "u", "functional-m-test-v1")
            wrapper = app.call_wrapper(memory.service, "s", "u")
            assert invoke(memory, "save_memory", args, "save", wrapper=wrapper) == response
            assert len(memory.service.records()) == int(after_put)
            if after_put:
                actual = memory.save_edit(
                    cfg(), "save", args["units"], args.get("relations"), args["scope"]
                )
                assert actual["ok"] and actual["replayed"] and actual["revision"] == 1


def business(wrapper: Any, name: str, args: dict[str, Any], call_id: str) -> Any:
    call = {"name": name, "args": args, "id": call_id, "type": "tool_call"}
    request = SimpleNamespace(
        tool_call=call,
        runtime=SimpleNamespace(config=cfg()),
        state={
            "messages": [
                HumanMessage(content="Operate"),
                AIMessage(content="", id="g-" + call_id, tool_calls=[call]),
            ]
        },
    )
    tool = next(t for t in wrapper.app.tools if t.name == name)
    return wrapper(request, lambda request: tool.invoke(request.tool_call))


def test_actual_partial_business_delivery_memory_only_and_unknown_business_no_repeat(
    tmp_path: Path,
) -> None:
    args = {"item_key": "synthetic", "quantity": 1, "destination": "desk", "packing": "box"}
    with FunctionalApplication.open(
        tmp_path / "app", "reservation", "alice", initial_label_available=False
    ) as app:
        with opened(tmp_path) as memory:
            turn(memory, "u", "Reserve this synthetic item, then remember the actual outcome.")
            wrapper = app.call_wrapper(memory.service, "s", "u")
            delivered = business(wrapper, "reserve_and_label", args, "reserve")
            body = json.loads(delivered.content)
            assert body["business_outcome"] == "partial"
            hs = [r["fragment_handle"] for r in body["source_fragment_index"]]
            memory.note_delivered_fragment_handles(cfg(), hs)
            before = app.world.snapshot()
            saved = json.loads(
                invoke(
                    memory,
                    "save_memory",
                    {
                        "units": [
                            {
                                "text": "Reservation exists; label creation is unconfirmed.",
                                "evidence": hs,
                            }
                        ]
                    },
                    "save",
                    wrapper=wrapper,
                ).content
            )
            assert saved["ok"] and saved["effect"] == "memory_only"
            assert app.world.snapshot() == before and len(before["attempts"]) == 1
            assert business(wrapper, "reserve_and_label", args, "reserve") == delivered
            assert len(app.world.snapshot()["attempts"]) == 1

    def lost(row: Any, response: Any) -> None:
        raise RuntimeError("lost real business acknowledgement")

    with FunctionalApplication.open(
        tmp_path / "unknown", "reservation", "alice", response_hook=lost
    ) as app:
        with opened(tmp_path / "unknown") as memory:
            turn(memory, "u", "Reserve the synthetic item.")
            wrapper = app.call_wrapper(memory.service, "s", "u")
            with pytest.raises(RuntimeError, match="lost real business"):
                business(wrapper, "reserve_and_label", args, "reserve")
            app.journal.response_hook = None
            with pytest.raises(UnknownBusinessAction):
                business(wrapper, "reserve_and_label", args, "reserve")
            denied = json.loads(business(wrapper, "reserve_and_label", args, "new-id").content)
            assert denied["status"] == "outcome_unknown_query_required"
            assert len(app.world.snapshot()["attempts"]) == 1 and not memory.service.records()


@pytest.mark.parametrize("arm", ["M", "B2"])
def test_user_plan_accepts_actual_tool_result_and_keeps_user_condition(tmp_path, arm):
    """Mixed record provenance does not relabel either original assertion."""
    condition = "Notify me only after the label has been completed."
    request = "Reserve this synthetic item; remember the actual result. " + condition
    args = {"item_key": "synthetic", "quantity": 1, "destination": "desk", "packing": "box"}
    with (
        FunctionalApplication.open(
            tmp_path / "app", "reservation", "alice", initial_label_available=False
        ) as app,
        opened(tmp_path, arm=arm, interface_version="I2", features=NEXT_FEATURES) as memory,
    ):
        writer_turn(memory, "u", request)
        user_ref = memory._binding(cfg())["source_ref"]
        initial = memory.writer.prepare([user_ref], "", selected_records=[], redelivered_ranges=[])
        created = memory.maintain_delivery(
            cfg(), initial, request_id="user-plan", date="2026-10-07", recipe="single_pass",
            allowed=True, model_call=lambda stage, messages, schema: {
                "creates": [{"action": "create", "matter": "Reservation result", "clauses": [{
                    "text": "User requests a reservation and its actual result.",
                    "evidence": ["e1"], "assertion": {"source": "e1", "kind": "reported"},
                    "conditions": [{
                        "text": condition, "evidence": ["e1"],
                        "assertion": {"source": "e1", "kind": "reported"},
                        "binding": {"evidence": ["e1"]},
                    }],
                }]}], "records": {},
            },
        )
        assert created["status"] == "completed", created
        record_id = created["receipts"][0]["id"]
        before = copy.deepcopy(memory.service.read(record_id)["value"])
        assert before["basis"] == "user_statement"
        wrapper = app.call_wrapper(memory.service, "s", "u")
        delivered = json.loads(business(wrapper, "reserve_and_label", args, "reserve").content)
        assert delivered["business_outcome"] == "partial"
        fragments = delivered["source_fragment_index"]
        memory.note_delivered_fragment_handles(cfg(), [f["fragment_handle"] for f in fragments])
        tool_ref = fragments[0]["source_ref"]
        delivery = memory.writer.prepare([tool_ref], "", selected_records=[], redelivered_ranges=[])
        actual_text = "The tool reports a reservation exists; label completion is unconfirmed."

        def no_change(stage, messages, schema):
            return {"creates": [], "records": {"r1": {"action": "no_change"}}}

        unchanged = memory.maintain_delivery(
            cfg(), delivery, request_id="before-result-no-change", date="2026-10-07",
            recipe="single_pass", model_call=no_change, allowed=True,
        )
        assert unchanged["status"] == "completed", unchanged
        assert memory.service.read(record_id)["value"] == before

        def edit(stage, messages, schema):
            packet = json.loads(messages[1]["content"])["delivery"]
            assert packet["source_table"][0]["role"] == "tool"
            assert packet["source_table"][1]["role"] == "user"
            if arm == "M":
                proposal = {"action": "edit", "edits": [{
                    "operation": "change_value", "target_unit": "u1", "text": actual_text,
                    "evidence": ["e1"], "assertion": {"source": "e1", "kind": "observed"},
                }]}
            else:
                proposal = {"action": "rewrite", "revision_evidence": ["e1"], "clauses": [{
                    "text": actual_text, "evidence": ["e1"], "from_unit": "u1",
                    "assertion": {"source": "e1", "kind": "observed"},
                    "conditions": [{
                        "text": condition, "evidence": [], "keep_support": ["h2"],
                        "from_unit": "u2",
                        "assertion": {"keep": "h2"},
                        "binding": {"evidence": [], "keep_support": ["h3"]},
                    }],
                }]}
            return {"creates": [], "records": {"r1": proposal}}

        world = copy.deepcopy(app.world.snapshot())
        changed = memory.maintain_delivery(
            cfg(), delivery, request_id="actual-tool-result", date="2026-10-07",
            recipe="single_pass", model_call=edit, allowed=True,
        )
        assert changed["status"] == "completed", [r.get("reason") for r in changed["receipts"]]
        assert app.world.snapshot() == world and len(world["attempts"]) == 1
        current = memory.service.read(record_id)["value"]
        assert current["revision"] == 2 and current["basis"] == "inference"
        assert set(current["source_refs"]) == {user_ref, tool_ref}
        assert current["scope"] == before["scope"]
        assert current["fields"] == before["fields"]
        assert current["object_ref"] == before["object_ref"]
        actual, retained = current["edit_state"]["units"]
        assert actual["text"] == actual_text
        assert actual["assertion"]["kind"] == "observed"
        assert actual["assertion"]["role"] == "tool"
        assert actual["assertion"]["source_ref"] == tool_ref
        old_condition = before["edit_state"]["units"][1]
        assert {k: v for k, v in retained.items() if k != "unit_id"} == {
            k: v for k, v in old_condition.items() if k != "unit_id"
        }
        assert retained["assertion"]["kind"] == "reported"
        assert retained["assertion"]["source_ref"] == user_ref
        assert memory.service.read(record_id, 1)["value"] == before
        basis_refs = {memory.service.source_fragment(handle)["source_ref"]
                      for handle in current["functional_support"]["basis"]["fragment_handles"]}
        assert basis_refs == {user_ref, tool_ref}
        confirmed = memory.maintain_delivery(
            cfg(), delivery, request_id="after-result-no-change", date="2026-10-07",
            recipe="single_pass", model_call=no_change, allowed=True,
        )
        assert confirmed["status"] == "completed", confirmed
        assert memory.service.read(record_id)["value"] == current
    with opened(tmp_path, arm=arm, interface_version="I2", features=NEXT_FEATURES) as memory:
        assert memory.service.read(record_id)["value"] == current
        assert memory.service.read(record_id, 1)["value"] == before


@pytest.mark.parametrize("after_put", [False, True])
@pytest.mark.parametrize("arm", ["M", "B1", "B0", "B2"])
def test_read_receipt_unknown_does_not_mark_undelivered_body_as_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    after_put: bool,
    arm: str,
) -> None:
    with opened(tmp_path, arm=arm) as memory:
        turn(memory, "u", "Read the actual archived source before saving it.")
        ref = memory.service.capture_user("archive", "a", "Archived original")["source_ref"]
        handle = memory.service.source_fragments(ref)[0]["fragment_handle"]
        original = memory.service.store.put

        def failed(ns: tuple[str, ...], key: str, value: Any, **kwargs: Any) -> None:
            receipt = key.startswith("read-admission:") and "result" in value["calls"].get(
                "read", {}
            )
            if receipt and not after_put:
                raise OSError("read receipt not committed")
            original(ns, key, value, **kwargs)
            if receipt:
                raise OSError("read receipt committed acknowledgement lost")

        monkeypatch.setattr(memory.service.store, "put", failed)
        response = json.loads(
            invoke(memory, "read_source", {"fragment_handle": handle}, "read").content
        )
        assert response["status"] == "read_outcome_unknown"
        monkeypatch.setattr(memory.service.store, "put", original)
        args = {"units": [{"text": "Archived original", "evidence": [handle]}]}
        denied = json.loads(invoke(memory, "save_memory", args, "unread-save").content)
        assert denied["status"] == "rejected" and not memory.service.records()
        if after_put:
            delivered = json.loads(
                invoke(memory, "read_source", {"fragment_handle": handle}, "read").content
            )
            assert delivered["ok"] and delivered["items"][0]["content"] == "Archived original"
            assert json.loads(invoke(memory, "save_memory", args, "save").content)["ok"]
        else:
            with pytest.raises(ValueError, match="READ_OUTCOME_UNKNOWN"):
                invoke(memory, "read_source", {"fragment_handle": handle}, "read")


@pytest.mark.parametrize("arm", ["M", "B1", "B0", "B2"])
def test_reader_omitted_ranges_are_not_delivered_and_full_withdrawal_retains_history(
    tmp_path: Path, arm: str,
) -> None:
    with opened(tmp_path, fragment_chars=100, arm=arm) as memory:
        ref = memory.service.capture_user("s", "u", "Original text " * 400)["source_ref"]
        memory.material_limit = 2600
        memory.policy["material_limit"] = 2600
        packet = memory.context("s", "u", "functional-m-test-v1")
        assert packet["items"] and packet["omitted_units"] > 0
        assert len(canonical(packet)) <= memory.material_limit
        delivered = {u["fragment_handle"] for u in packet["items"]}
        unseen = next(
            f["fragment_handle"]
            for f in memory.service.source_fragments(ref, max_chars=100)
            if f["fragment_handle"] not in delivered
        )
        denied = json.loads(
            invoke(
                memory,
                "save_memory",
                {"units": [{"text": "Unavailable original portion", "evidence": [unseen]}]},
                "undelivered",
            ).content
        )
        assert not denied["ok"] and not memory.service.records()
        handle = next(iter(delivered))
        saved = json.loads(
            invoke(
                memory,
                "save_memory",
                {"units": [{"text": "Original text", "evidence": [handle]}]},
                "save",
            ).content
        )
        old = memory.service.read(saved["id"])
        unit = old["value"]["edit_state"]["units"][0]["unit_id"]
        same = json.loads(
            invoke(
                memory,
                "update_memory",
                ({
                    "read_handle": old["candidate_handle"],
                    "edits": [{"operation": "retract" if arm == "M" else "delete",
                               "target_unit": unit, "evidence": [handle]}],
                } if memory.local else {
                    "read_handle": old["candidate_handle"], "units": [],
                    "withdrawal_evidence": [handle],
                }),
                "affirmation-only",
            ).content
        )
        assert not same["ok"] and same["effect"] == "none"
        memory.material_limit = 30000
        memory.policy["material_limit"] = 30000
        cancellation = turn(memory, "cancel", "Withdraw the old remembered statement.")
        result = json.loads(
            invoke(
                memory,
                "update_memory",
                ({
                    "read_handle": old["candidate_handle"],
                    "edits": [
                        {"operation": "retract" if arm == "M" else "delete",
                         "target_unit": unit, "evidence": cancellation}
                    ],
                } if memory.local else {
                    "read_handle": old["candidate_handle"], "units": [],
                    "withdrawal_evidence": cancellation,
                }),
                "retract",
                "cancel",
            ).content
        )
        assert result["ok"] and result["id"] == saved["id"] and result["revision"] == 2
        assert memory.service.read(saved["id"])["status"] == "retracted"
        current = memory.service.read(saved["id"], 2)["value"]
        assert current["retracted"] and current["edit_state"]["units"] == []
        assert memory.service.read(saved["id"], 1)["value"] == old["value"]
        history = json.loads(invoke(memory, "read_memory", {
            "record_id": saved["id"], "history": True,
        }, "withdrawn-history", "cancel").content)
        assert {u["revision"] for u in history["items"]} == {1, 2}
        assert any(u["retracted"] for u in history["items"])
    with opened(tmp_path, arm=arm) as memory:
        turn(memory, "forget", "Forget the withdrawn record and its original sources.")
        withdrawn = memory.service.read(saved["id"], 2)
        assert withdrawn["ok"] and withdrawn["value"]["retracted"]
        removed = json.loads(invoke(memory, "forget_memory", {
            "read_handle": withdrawn["candidate_handle"],
        }, "forget", "forget").content)
        assert removed["ok"]
        assert not memory.service.read(saved["id"], 1)["ok"]
        assert not memory.service.read(saved["id"], 2)["ok"]
        assert memory.service.source(ref) is None
    with opened(tmp_path, arm=arm) as memory:
        assert not memory.service.read(saved["id"], 1)["ok"]


def writer_turn(memory, message, text):
    memory.service.capture_user("s", message, text)
    return memory.writer_context("s", message, "functional-m-test-v1")


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
@pytest.mark.parametrize("profile", ["I1", "I2"])
def test_v2_sdk_writer_formation_same_id_support_and_history(tmp_path, arm, profile):
    with opened(tmp_path, arm=arm, interface_version=profile) as memory:
        packet = writer_turn(memory, "u", "Use quiet reminders only during exhibition.")
        assert packet["writer_packet"]["records"] == []
        proposal = {
            "action": "create",
            "units": [
                {"text": "Use quiet reminders", "evidence": ["e1"]},
                {
                    "text": "Only during exhibition",
                    "role": "condition" if memory.conditioned else "content",
                    "evidence": ["e1"],
                },
            ],
        }
        if memory.conditioned:
            proposal["relations"] = [
                {"source": 1, "target": 0, "relation_type": "modifies", "evidence": ["e1"]}
            ]
        saved = json.loads(invoke(memory, "save_memory", {"proposal": proposal}, "v2-save").content)
        assert saved["ok"], saved
        old = copy.deepcopy(memory.service.read(saved["id"])["value"])
        packet = writer_turn(memory, "u2", "Use a soft tone instead; exhibition limit remains.")
        assert packet["writer_packet"]["records"][0]["id"] == "r1"
        assert saved["id"] not in canonical(packet["writer_packet"])
        if memory.local:
            update = {
                "action": "edit",
                "target": "r1",
                "edits": [
                    {
                        "operation": "replace",
                        "target_unit": "u1",
                        "text": "Use a soft tone",
                        "evidence": ["e1"],
                        "keep_support": ["h1"],
                    }
                ],
            }
        else:
            update = {
                "action": "rewrite",
                "target": "r1",
                "units": [
                    {"text": "Use a soft tone", "evidence": ["e1"], "keep_support": ["h1"]},
                    {
                        "text": "Only during exhibition",
                        "role": "condition" if memory.conditioned else "content",
                        "evidence": [],
                        "keep_support": ["h2"],
                    },
                ],
            }
            if memory.conditioned:
                update["relations"] = [
                    {
                        "source": 1,
                        "target": 0,
                        "relation_type": "modifies",
                        "evidence": [],
                        "keep_support": ["h3"],
                    }
                ]
        changed = json.loads(
            invoke(memory, "update_memory", {"proposal": update}, "v2-update", "u2").content
        )
        assert changed["ok"] and changed["revision"] == 2, changed
        assert changed["id"] == saved["id"]
        assert memory.service.read(saved["id"], 1)["value"] == old
        current = memory.service.read(saved["id"])["value"]
        assert current["scope"] == old["scope"]
        if memory.local:
            assert current["edit_state"]["units"][1:] == old["edit_state"]["units"][1:]
        repeat = json.loads(
            invoke(memory, "update_memory", {"proposal": update}, "v2-update", "u2").content
        )
        assert repeat["replayed"] and memory.service.read(saved["id"])["value"]["revision"] == 2


def test_v2_sdk_strict_arm_schema_unknown_short_ref_and_no_old_metadata_proof(tmp_path):
    with opened(tmp_path, arm="B0", interface_version="I2") as memory:
        writer_turn(memory, "u", "Use quiet reminders.")
        proposal = {"action": "create", "units": [{"text": "Quiet reminders", "evidence": ["e1"]}]}
        saved = json.loads(invoke(memory, "save_memory", {"proposal": proposal}, "save").content)
        assert saved["ok"]
        writer_turn(memory, "u2", "Quiet reminders remain unchanged.")
        bad = {
            "action": "rewrite",
            "target": "r1",
            "units": [{"text": "Loud reminders", "evidence": [], "keep_support": ["h1"]}],
        }
        rejected = json.loads(
            invoke(memory, "update_memory", {"proposal": bad}, "bad-h", "u2").content
        )
        assert not rejected["ok"] and "CHANGED_CLAIM" in rejected["reason"]
        bad = {"action": "edit", "target": "r1", "edits": []}
        rejected = json.loads(
            invoke(memory, "update_memory", {"proposal": bad}, "bad-edit", "u2").content
        )
        assert not rejected["ok"] and "PUBLIC_PROPOSAL" in rejected["reason"]
        with pytest.raises(ValidationError):
            invoke(
                memory,
                "update_memory",
                {"proposal": {"action": "no_change", "target": "r1"}, "edits": []},
                "extra",
                "u2",
            )
        assert memory.service.read(saved["id"])["value"]["revision"] == 1
        tools = {tool.name: tool for tool in memory.tools()}
        schema = tools["update_memory"].tool_call_schema.model_json_schema()
        assert "tool_call_id" not in schema["properties"] and "config" not in schema["properties"]
        assert "rewrite" in canonical(schema) and '"edit"' not in canonical(schema)
        assert "base_revision" not in canonical(schema)


@pytest.mark.parametrize("after_put", [False, True])
@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
def test_v2_actual_wrapper_unknown_reopen_uses_same_decoded_operation(
    tmp_path, monkeypatch, arm, after_put
):
    args = {
        "proposal": {"action": "create", "units": [{"text": "Quiet reminders", "evidence": ["e1"]}]}
    }
    with FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app:
        with opened(tmp_path, arm=arm, interface_version="I2") as memory:
            writer_turn(memory, "u", "Keep quiet reminders.")
            original = memory.service.store.put
            entered = 0

            def failed(ns, key, value, **kwargs):
                nonlocal entered
                semantic = ns == memory.service.namespace and "_v13_1" in value
                if semantic:
                    entered += 1
                    if not after_put:
                        raise OSError("Synthetic unavailable commit")
                original(ns, key, value, **kwargs)
                if semantic:
                    raise OSError("Synthetic lost commit acknowledgement")

            monkeypatch.setattr(memory.service.store, "put", failed)
            wrapper = app.call_wrapper(memory.service, "s", "u")
            response = invoke(memory, "save_memory", args, "save-v2-unknown", wrapper=wrapper)
            receipt = json.loads(response.content)
            assert receipt["status"] == "outcome_unknown" and receipt["phase"] == "semantic_commit"
            assert entered == 1
            monkeypatch.setattr(memory.service.store, "put", original)
            assert (
                invoke(memory, "save_memory", args, "save-v2-unknown", wrapper=wrapper) == response
            )
            assert len(memory.service.records()) == int(after_put)
    with FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app:
        with opened(tmp_path, arm=arm, interface_version="I2") as memory:
            memory.writer_context("s", "u", "functional-m-test-v1")
            wrapper = app.call_wrapper(memory.service, "s", "u")
            assert (
                invoke(memory, "save_memory", args, "save-v2-unknown", wrapper=wrapper) == response
            )
            if after_put:
                direct = memory.apply_writer_proposal(cfg(), "save-v2-unknown", args["proposal"])
                assert direct["replayed"] and direct["revision"] == 1
            assert len(memory.service.records()) == int(after_put)


def test_v2_whole_record_partial_and_undelivered_fragment_cannot_gain_alias(tmp_path):
    with opened(tmp_path, arm="B0", interface_version="I2", fragment_chars=80) as memory:
        writer_turn(memory, "u", "Quiet reminders.")
        text = "Quiet reminder conditions remain unchanged. " * 12
        args = {"proposal": {"action": "create", "units": [{"text": text, "evidence": ["e1"]}]}}
        saved = json.loads(invoke(memory, "save_memory", args, "save").content)
        assert saved["ok"]
        turn(memory, "u2", "Quiet reminders need maintenance.")
        row = memory.service.read(saved["id"])
        fragments = memory._record_units(row)
        assert len(fragments) > 1
        key = memory._writer_key(cfg("u2"), "edit-writer-delivery:")
        from milai_lab.memory.functional_state import namespace

        first = {"items": [fragments[0]]}
        memory.service.store.put(namespace(memory.service), key, first, index=False)
        partial = memory._writer_packet(cfg("u2"), {"ok": True})
        assert partial["writer_packet"]["records"] == []
        assert partial["unprocessed_records"][0]["reason"] == "complete_record_body_not_delivered"
        # Existing read SDK pages supply missing chunks. Mere capture/issued spans do not.
        extra = memory.service.capture_user("s", "not-delivered", "Unseen correction.")[
            "source_ref"
        ]
        handle = memory.service.source_fragment_range(extra, 0, len("Unseen correction."))[
            "fragment_handle"
        ]
        assert all(
            handle != e["evidence_id"]
            for e in memory.writer.load_mapping(
                memory.service.store.get(
                    namespace(memory.service), memory._writer_key(cfg("u2"), "edit-writer-active:")
                ).value["mapping_id"]
            )["evidence"].values()
        )
        read = json.loads(
            invoke(memory, "read_memory", {"record_id": saved["id"]}, "read-complete", "u2").content
        )
        assert read["ok"]
        complete = memory._writer_packet(cfg("u2"), {"ok": True})
        assert complete["writer_packet"]["records"][0]["units"][0]["text"] == text
        assert not complete["unprocessed_records"]


@pytest.mark.parametrize("arm", ["B0", "B2"])
def test_v2_actual_sdk_whole_withdrawal_history_and_forget(tmp_path, arm):
    with opened(tmp_path, arm=arm, interface_version="I2") as memory:
        writer_turn(memory, "u", "Use quiet reminders.")
        saved = json.loads(
            invoke(
                memory,
                "save_memory",
                {
                    "proposal": {
                        "action": "create",
                        "units": [{"text": "Quiet reminders", "evidence": ["e1"]}],
                    }
                },
                "save",
            ).content
        )
        assert saved["ok"]
        writer_turn(memory, "cancel", "Cancel quiet reminders.")
        canceled = json.loads(
            invoke(
                memory,
                "update_memory",
                {
                    "proposal": {
                        "action": "rewrite",
                        "target": "r1",
                        "units": [],
                        "withdrawal_evidence": ["e1"],
                    }
                },
                "cancel",
                "cancel",
            ).content
        )
        assert canceled["ok"] and canceled["revision"] == 2
        assert memory.service.read(saved["id"])["status"] == "retracted"
        history = json.loads(
            invoke(
                memory,
                "read_memory",
                {"record_id": saved["id"], "history": True},
                "history",
                "cancel",
            ).content
        )
        assert history["ok"] and history["items"]
        forgotten = json.loads(
            invoke(
                memory,
                "forget_memory",
                {
                    "read_handle": next(
                        item["read_handle"] for item in history["items"] if item["revision"] == 2
                    )
                },
                "forget",
                "cancel",
            ).content
        )
        assert forgotten["ok"]
        assert not memory.service.read(saved["id"], 1)["ok"]


def test_v2_review_uses_immutable_proposal_and_rejection_keeps_history(tmp_path):
    calls = []

    def review(evidence, delivered):
        item = memory.service.store.get(
            (*memory.service.namespace, "prepared_proposals"),
            reference_key(["s", evidence["proposal_id"]]),
        )
        assert item is not None and item.value["proposal"]["method_version"] == "milai_edit_v2"
        calls.append(evidence["proposal_id"])
        delivered()
        if evidence["proposal_id"] == "unsupported":
            raise FunctionalRejection("SYNTHETIC_UNSUPPORTED")

    with opened(
        tmp_path,
        interface_version="I2",
        formation_support_review=review,
        revision_support_review=review,
    ) as memory:
        writer_turn(memory, "u", "Quiet reminders.")
        saved = json.loads(
            invoke(
                memory,
                "save_memory",
                {
                    "proposal": {
                        "action": "create",
                        "units": [{"text": "Quiet reminders", "evidence": ["e1"]}],
                    }
                },
                "save",
            ).content
        )
        assert saved["ok"]
        before = copy.deepcopy(memory.service.read(saved["id"])["value"])
        writer_turn(memory, "u2", "Quiet reminders now use a soft tone.")
        proposal = {
            "action": "edit",
            "target": "r1",
            "edits": [
                {
                    "operation": "replace",
                    "target_unit": "u1",
                    "text": "Unsupported universal tone",
                    "evidence": ["e1"],
                }
            ],
        }
        failed = json.loads(
            invoke(memory, "update_memory", {"proposal": proposal}, "unsupported", "u2").content
        )
        assert not failed["ok"] and "SYNTHETIC_UNSUPPORTED" in failed["reason"]
        assert memory.service.read(saved["id"])["value"] == before
        assert memory.service.read(saved["id"], 1)["value"] == before
        proposal["edits"][0]["text"] = "Quiet reminders use a soft tone"
        accepted = json.loads(
            invoke(memory, "update_memory", {"proposal": proposal}, "supported", "u2").content
        )
        assert accepted["ok"] and accepted["revision"] == 2
        assert calls == ["save", "unsupported", "supported"]


def test_v2_nonmatching_representation_rejected_and_no_change_does_not_form(tmp_path):
    with opened(tmp_path, arm="B1") as old:
        evidence = turn(old, "u", "Quiet reminders.")
        saved = json.loads(
            invoke(
                old,
                "save_memory",
                {"units": [{"text": "Quiet reminders", "evidence": evidence}]},
                "save-old",
            ).content
        )
        assert saved["ok"]
    with opened(tmp_path, arm="M", interface_version="I2") as memory:
        writer_turn(memory, "u2", "Quiet reminders now use a soft tone.")
        update = {
            "action": "edit",
            "target": "r1",
            "edits": [
                {
                    "operation": "replace",
                    "target_unit": "u1",
                    "text": "Quiet soft reminders",
                    "evidence": ["e1"],
                }
            ],
        }
        rejected = json.loads(
            invoke(memory, "update_memory", {"proposal": update}, "wrong-repr", "u2").content
        )
        assert not rejected["ok"] and "EXPLICIT_M_FORMATION_REQUIRED" in rejected["reason"]
        assert memory.service.read(saved["id"])["value"]["revision"] == 1
        global_no_change = json.loads(
            invoke(
                memory, "update_memory", {"proposal": {"action": "no_change"}}, "none", "u2"
            ).content
        )
        assert global_no_change["ok"] and global_no_change["status"] == "no_change"
        assert global_no_change["id"] is None
        assert len(memory.service.records()) == 1


@pytest.mark.parametrize("fault", ["after_commit", "during_extract"])
def test_shared_recipe_recovery_preserves_effect_and_unknown_call(tmp_path, fault):
    from milai_lab.methods.edit_maintenance import maintain_event

    calls = []
    with opened(tmp_path, arm="B1", interface_version="I2") as memory:
        turn(memory, "u", "Remember the marker is blue.")
        ref = memory._binding(cfg())["source_ref"]
        delivery = memory.writer.prepare([ref], "", selected_records=[], redelivered_ranges=[])

        def call(stage, messages, schema):
            calls.append(stage)
            if stage == "extract":
                if fault == "during_extract":
                    raise OSError("lost extraction response")
                return {"changes": []}
            return {"proposals": [{"action": "create", "units": [
                {"text": "The marker is blue.", "evidence": ["e1"]}]}]}

        def commit(operation, proposal, mapping):
            memory.service.store.put(
                namespace(memory.service), memory._writer_key(cfg(), "edit-writer-active:"),
                {"mapping_id": mapping["mapping_id"]}, index=False,
            )
            receipt = memory.apply_writer_proposal(cfg(), operation, proposal)
            assert receipt["ok"]
            raise OSError("crash after durable commit")

        args = dict(session="s", request_id="batch", date="2026-10-07",
                    recipe="extract_then_edit", model_call=call, commit=commit)
        with pytest.raises(OSError):
            maintain_event(memory.writer, delivery, **args)
        count = len(calls)
    with opened(tmp_path, arm="B1", interface_version="I2") as memory:
        # Resume through the same functional mutation boundary and operation ID.
        memory.context("s", "u", "functional-m-test-v1")
        args["commit"] = lambda op, proposal, mapping: memory.apply_writer_proposal(
            cfg(), op, proposal)
        result = maintain_event(memory.writer, delivery, **args)
        assert len(calls) == count
        if fault == "after_commit":
            assert result["status"] == "completed" and result["semantic_write_performed"]
            assert len(memory.service.records()) == 1
            assert memory.service.records()[0]["value"]["revision"] == 1
        else:
            assert result["status"] == "incomplete" and result["phase"] == "extract_pending"
            assert result["unprocessed"][0]["reason"] == "model_outcome_unconfirmed"
            assert memory.service.records() == []


def test_shared_reader_expands_actual_exception_and_history_without_inheriting_scope(tmp_path):
    from milai_lab.memory.edit_units import read_applicability

    with opened(tmp_path, arm="M", interface_version="I2",
                maintenance_recipe="extract_then_edit") as memory:
        writer_turn(memory, "u", "Across the whole project, visit three times weekly this quarter.")
        saved = json.loads(invoke(memory, "save_memory", {"proposal": {
            "action": "create", "units": [
                {"text": "The whole project has three visits weekly.", "evidence": ["e1"]},
                {"text": "This quarter.", "role": "condition", "evidence": ["e1"]}],
            "relations": [{"source": 1, "target": 0, "relation_type": "modifies",
                           "evidence": ["e1"]}],
        }}, "save").content)
        assert saved["ok"], saved
        writer_turn(memory, "u2", "For branch A only, visit once weekly.")
        scoped = json.loads(invoke(memory, "update_memory", {"proposal": {
            "action": "edit", "target": "r1", "edits": [{
                "operation": "override", "target_unit": "u1", "text": "One visit weekly.",
                "condition": "Branch A only.", "evidence": ["e1"]}],
        }}, "override", "u2").content)
        assert scoped["ok"], scoped
        row = memory.service.read(saved["id"])
        before = copy.deepcopy(row["value"])
        views = [u["applicability"] for u in memory._record_units(row)]
        general = next(v for v in views if v["kind"] == "general_rule")
        exception = next(v for v in views if v["kind"] == "scoped_exception")
        assert [c["text"] for c in general["applies_under"]] == ["This quarter."]
        assert [c["text"] for c in exception["applies_under"]] == ["Branch A only."]
        assert exception["general_rules"][0]["text"] == general["text"]
        assert general["exceptions"][0]["text"] == exception["text"]
        assert memory.service.read(saved["id"])["value"] == before
        # A missing original rule is reported, never reconstructed from an exception.
        missing = copy.deepcopy(before["edit_state"])
        missing["relations"] = []
        missing["units"] = [dict(missing["units"][2], local_exception=True)]
        missing_view = next(iter(read_applicability(missing).values()))
        assert missing_view["general_rule_status"] == "not_stored"
        writer_turn(memory, "u3", "Cancel the branch A exception.")
        cancelled = json.loads(invoke(memory, "update_memory", {"proposal": {
            "action": "edit", "target": "r1", "edits": [
                {"operation": "retract", "target_unit": alias, "evidence": ["e1"]}
                for alias in ("u3", "u4")],
        }}, "cancel", "u3").content)
        assert cancelled["ok"], cancelled
        page = json.loads(invoke(memory, "read_memory", {
            "record_id": saved["id"], "revision": 2,
        }, "history", "u3").content)
        assert page["ok"], page
        assert any(u.get("applicability", {}).get("kind") == "scoped_exception"
                   for u in page["items"])
        current = memory._record_units(memory.service.read(saved["id"]))
        assert all(not u["applicability"].get("exceptions") for u in current)
        assert current[0]["applicability"]["text"] == general["text"]


def test_shared_extraction_context_is_old_visible_speech_not_current_evidence(tmp_path):
    with opened(tmp_path, arm="B1", interface_version="I2",
                maintenance_recipe="extract_then_edit", recent_context="bank_recent_v2") as memory:
        turn(memory, "old", "My reminder uses a chime.")
        turn(memory, "u", "Make that quiet instead.")
        seen = []

        def call(stage, messages, schema):
            payload = json.loads(messages[1]["content"])
            seen.append(payload)
            assert payload["prior_context"][0]["text"] == "My reminder uses a chime."
            assert payload["prior_context"][0]["kind"] == "prior_context"
            assert all(e["text"] == "Make that quiet instead."
                       for e in payload["delivery"]["evidence"])
            return {"changes": []} if stage == "extract" else {"proposals": []}

        results = memory.maintain_sources(cfg(), recipe="extract_then_edit",
                                          model_call=call, allowed=True)
        assert len(seen) == 2 and results[0]["status"] == "completed"
        assert memory.service.records() == []
