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

from milai_lab.application.functional import FunctionalApplication
from milai_lab.application.journal import UnknownBusinessAction
from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.functional_state import FunctionalRejection, canonical, reference_key
from milai_lab.memory.service import MemoryService
from milai_lab.methods.functional_edit_memory import (
    FUNCTIONAL_B1_METHOD,
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
@pytest.mark.parametrize("arm", ["M", "B1"])
def test_actual_review_rejection_reopen_and_corrected_formation_or_local_revision(
    tmp_path: Path, stage: str, arm: str
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
            "conditioned_v1" if arm == "M" else "plain_v1"
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

    options = {"formation_support_review": review, "revision_support_review": review, "arm": arm}
    with (
        FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app,
        opened(tmp_path, **options) as memory,
    ):
        original = turn(memory, "u", "Use quiet reminders only during this exhibition.")
        saved = json.loads(
            invoke(
                memory, "save_memory", save_args(original) if arm == "M" else plain_args(original),
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
            else:
                assert current["value"]["edit_state"]["units"][1:] == (
                    initial["value"]["edit_state"]["units"][1:]
                )
            replay = memory.update_edit(
                cfg("correction"), "corrected", corrected_args["read_handle"],
                corrected_args["edits"],
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


@pytest.mark.parametrize("arm", ["M", "B1"])
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
@pytest.mark.parametrize("arm", ["M", "B1"])
def test_actual_wrapper_unknown_commit_reopen_same_identity_no_second_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    after_put: bool,
    arm: str,
) -> None:
    with FunctionalApplication.open(tmp_path / "app", "reservation", "alice") as app:
        with opened(tmp_path, arm=arm) as memory:
            hs = turn(memory, "u", "Use quiet reminders only during this exhibition.")
            args = save_args(hs) if arm == "M" else plain_args(hs)
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


@pytest.mark.parametrize("after_put", [False, True])
@pytest.mark.parametrize("arm", ["M", "B1"])
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


@pytest.mark.parametrize("arm", ["M", "B1"])
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
                {
                    "read_handle": old["candidate_handle"],
                    "edits": [{"operation": "retract" if arm == "M" else "delete",
                               "target_unit": unit, "evidence": [handle]}],
                },
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
                {
                    "read_handle": old["candidate_handle"],
                    "edits": [
                        {"operation": "retract" if arm == "M" else "delete",
                         "target_unit": unit, "evidence": cancellation}
                    ],
                },
                "retract",
                "cancel",
            ).content
        )
        assert result["ok"] and result["id"] == saved["id"] and result["revision"] == 2
        assert memory.service.read(saved["id"])["status"] == "retracted"
        current = memory.service.read(saved["id"], 2)["value"]
        assert current["retracted"] and current["edit_state"]["units"] == []
        assert memory.service.read(saved["id"], 1)["value"] == old["value"]
