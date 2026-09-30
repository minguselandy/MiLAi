"""Narrow zero-network evidence linkage, patches and actual projection crash windows."""

from __future__ import annotations

import importlib.util
import json
import signal
import sys
from pathlib import Path
from typing import Any

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.refs import observation_profile
from milai_lab.application.world import ApplicationWorld
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.runners import v13_1_p5 as runner


def helper(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bound = helper("delivery_bound_helpers", "test_v13_2_service.py")
old = helper("delivery_p5_helpers", "test_v13_1_p5.py")


@pytest.mark.parametrize("window", ["W2_projection", "W3_projection"])
def test_actual_projection_sigkill_reopens_without_repeating_business_mutation(
    tmp_path: Path, window: str
) -> None:
    old.prepared(tmp_path)
    settings = read_json(tmp_path / "config.json")
    settings.update(
        memory_mutation_contract="event_bound_v1", memory_observation_profile="reservation_v1"
    )
    write_json(tmp_path / "config.json", settings)
    root = tmp_path / "projection-crash"
    frozen = runner.prepare(tmp_path / "public.json", tmp_path / "config.json", root)
    process, crash = old.child(root, window=window, attempt="actual-projection-crash")
    assert process.returncode == -signal.SIGKILL, process.stderr
    assert crash["boundary"] == window and crash["status"] == "hard_exit_armed"
    assert crash["final_answer"] is None
    assert len(crash["world"]["attempts"]) == 1
    case = runner.case_path(root, "mechanical")
    namespace = ("langmem", frozen["run_id"], "field_grounded", "alice")
    with SqliteStore.from_conn_string(str(case / "memory.sqlite")) as store:
        service = MemoryService(
            store, namespace, "alice", case / "memory.lock", mutation_contract="event_bound_v1"
        )
        source = next(row for row in service.sources() if row["role"] == "tool")
        before = service.observations()
        assert len(before["observations"]) == (0 if window == "W2_projection" else 2)
        if window == "W2_projection":
            assert len(before["pending"]) == 1
            pending = service.projection_receipt(
                source["event_id"], observation_profile("reservation_v1")
            )
            assert pending["status"] == "pending" and pending["raw_preserved"]
            assert pending["reason"] == "projection_not_started"
        result = service.observe(source["event_id"], observation_profile("reservation_v1"))
        assert result["status"] == ("projected" if window == "W2_projection" else "no_change")
        assert len(service.observations()["observations"]) == 2
        assert service.records() == []  # no UPDATE masquerading as projection W3
    world = ApplicationWorld(case / "world.sqlite", False)
    try:
        assert world.snapshot() == crash["world"]
    finally:
        world.close()


def test_source_backlink_finds_cross_language_card_without_rewriting_business_key(
    tmp_path: Path,
) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(
            store,
            ("links", "alice"),
            "alice",
            tmp_path / "lock",
            mutation_contract="event_bound_v1",
            source_backlinks="enabled",
        )
        source = bound.user(service, "u1", "松林项目, 我偏好简短回答")
        first = bound.save(
            service,
            "Prefer concise Pine project replies",
            "create",
            source_ref=source,
            scope={"project": "Pine", "time_limit": "this project"},
        )
        found = service.search("松林", include_raw=False)["records"]
        assert [row["id"] for row in found] == [first["id"]]
        assert found[0]["value"]["scope"]["project"] == "Pine"
        assert found[0]["candidate_handle"]
        assert service.store.get(service.backlinks_namespace, source).value["records"] == {
            first["id"]: [1]
        }
        newer = bound.user(service, "u2", "松林项目回复要更详细")
        revised = service.revise(
            "s1",
            "patch",
            found[0]["candidate_handle"],
            {"content": "Detailed Pine project replies"},
            [newer],
        )
        assert revised["revision"] == 2
        assert service.read(first["id"])["value"]["scope"] == {
            "project": "Pine",
            "time_limit": "this project",
        }
        # Historical source links still reach the current record identity.
        assert service.backlink_candidates([source])[0]["value"]["revision"] == 2
        assert service.search("松林", include_raw=False)["records"][0]["id"] == first["id"]


def test_small_patch_preserves_scope_history_and_rejects_observation_fields_or_stale_handle(
    tmp_path: Path,
) -> None:
    with bound.opened(tmp_path) as service:
        source = bound.user(service, "u1", "Initial scoped preference")
        first = bound.save(
            service,
            "Concise replies",
            "create",
            source_ref=source,
            scope={"subject": "personal", "project": "A"},
            kind="episodic",
        )
        handle = service.read(first["id"])["candidate_handle"]
        newer = bound.user(service, "u2", "Add a date bound")
        tools = {tool.name: tool for tool in create_service_tools(service, replay_requested=True)}
        request = {
            "name": "revise_memory",
            "id": "patch",
            "type": "tool_call",
            "args": {
                "candidate_handle": handle,
                "semantic_patch": {"scope": {"valid_until": "2027"}},
                "source_refs": [newer],
            },
        }
        config = {"configurable": {"user_id": "alice", "v13_session": "s1"}}
        result = json.loads(tools["revise_memory"].invoke(request, config=config).content)
        assert result["revision"] == 2
        current = service.read(first["id"])["value"]
        assert current["content"] == "Concise replies" and current["kind"] == "episodic"
        assert current["scope"] == {"subject": "personal", "project": "A", "valid_until": "2027"}
        assert json.loads(tools["revise_memory"].invoke(request, config=config).content)["replayed"]
        assert (
            service.revise("s1", "stale", handle, {"content": "Changed"}, [newer])["reason"]
            == "revision_conflict"
        )
        new_handle = service.read(first["id"])["candidate_handle"]
        bad = service.revise("s1", "bad", new_handle, {"fields": {"status": "done"}}, [newer])
        assert bad["reason"] == "invalid_semantic_patch"
        none = service.revise("s1", "none", new_handle, {}, [newer], operation="no_change")
        assert none["status"] == "no_change" and service.read(first["id"])["value"]["revision"] == 2
        supersede = service.revise(
            "s1",
            "supersede",
            new_handle,
            {"content": "New preference"},
            [newer],
            operation="supersede",
        )
        assert supersede["revision"] == 3
        assert service.read(first["id"])["value"]["supersedes_revision"] == 2
        assert (
            len(service.store.get(service.namespace, first["id"]).value["_v13_1"]["history"]) == 3
        )
