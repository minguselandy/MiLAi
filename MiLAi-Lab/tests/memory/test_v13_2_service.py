"""Offline actual Store/tool checks for opt-in exact evidence and read-time versions."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools


@contextmanager
def opened(
    root: Path, owner: str = "alice", contract: Any = "event_bound_v1"
) -> Iterator[MemoryService]:
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        yield MemoryService(
            store, ("bound", owner), owner, root / "memory.lock", mutation_contract=contract
        )


def user(service: MemoryService, key: str, text: str) -> str:
    return str(service.capture_user("s1", key, text)["source_ref"])


def invoke(service: MemoryService, name: str, args: dict[str, Any], key: str) -> dict[str, Any]:
    tools = {tool.name: tool for tool in create_service_tools(service, replay_requested=True)}
    result = tools[name].invoke(
        {"type": "tool_call", "name": name, "args": args, "id": key},
        config={"configurable": {"user_id": service.owner, "v13_session": "s1"}},
    )
    return json.loads(result.content)


def save(service: MemoryService, text: str, key: str, **args: Any) -> dict[str, Any]:
    return invoke(service, "manage_memory", {"content": text, **args}, key)


def test_current_boundary_never_selects_last_same_role_and_preserves_source_schema(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as service:
        current = user(service, "current", "I prefer concise replies")
        source_before = dict(service.source(current))
        service.bind_source_boundary("s1", "current", [current])
        later = user(service, "later-capture", "A different actual user event")
        first = save(service, "I prefer concise replies", "first")
        assert first["ok"] and first["source_ref"] == current != later
        assert first["source_bindings"] == [
            {
                "source_ref": current,
                "role": "user",
                "content_sha256": source_before["content_sha256"],
            }
        ]
        assert service.source(current) == source_before
        assert "source_refs" not in source_before
        assert save(service, "I prefer concise replies", "first")["replayed"]


def test_missing_boundary_preserves_pending_and_does_not_guess_from_history(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = user(service, "u1", "Existing source")
        result = save(service, "Unbound proposal", "unbound")
        assert result["reason"] == "source_selection_required"
        assert result["formation_status"] == "pending" and result["raw_preserved"]
        assert service.records() == []
        assert service.sources()[0]["formation_status"] == "pending"
        attempt = service.store.search(service.attempts_namespace)[0].value
        assert attempt["raw"]["requested"]["content"] == "Unbound proposal"
        assert save(service, "Explicitly selected", "explicit", source_ref=source)["reason"] == (
            "current_boundary_source_required")
        service.bind_source_boundary("s1", "actual-request", [source])
        assert save(service, "Explicitly selected", "bound", source_ref=source)["ok"]


def test_multiple_actual_events_require_selection_and_same_batch_accumulates(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as service:
        first = user(service, "u1", "I prefer concise replies")
        second = user(service, "u2", "Also retain code examples")
        service.bind_source_boundary("s1", "batch", [first])
        service.bind_source_boundary("s1", "batch", [second], append=True)
        assert service.boundary_sources("s1") == [first, second]
        assert (
            save(service, "Combined preferences", "ambiguous")["reason"]
            == "source_selection_required"
        )
        result = save(service, "Combined preferences", "selected", source_refs=[first, second])
        assert result["ok"] and result["source_refs"] == [first, second]
        assert all(row["formation_status"] == "formed" for row in service.sources())
        assert (
            save(service, "Duplicate ref", "duplicates", source_refs=[first, first])["reason"]
            == "source_selection_required"
        )
        service.bind_source_boundary("s1", "next", [second], append=True)
        assert service.boundary_sources("s1") == [second]


def test_mixed_roles_are_retained_and_cannot_be_promoted_to_user_statement(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        expressed = user(service, "u1", "Please investigate the draft")
        observed = service.capture_tool("s1", "t1", "public_lookup", '{"status":"pending"}', None)[
            "source_ref"
        ]
        sources = [expressed, observed]
        service.bind_source_boundary("s1", "actual-batch", sources)
        bad = save(service, "The user confirmed completion", "bad", source_refs=sources)
        assert bad["reason"] == "source_role_mismatch"
        good = save(
            service, "The draft may need follow-up", "good", source_refs=sources, basis="inference"
        )
        assert good["ok"] and good["content_verification"] == "unchecked"
        assert [row["role"] for row in good["source_bindings"]] == ["user", "tool"]
        assert service.read(good["id"])["value"]["basis"] == "inference"
        # A literal quote's existence does not establish semantic attribution.
        quote = save(
            service,
            '"Please investigate" means the user approved publication',
            "quote",
            source_ref=expressed,
        )
        assert quote["ok"] and quote["content_verification"] == "unchecked"


def test_actual_assistant_suggestion_stays_assistant_and_unchecked(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = service.capture_assistant("s1", "a1", "I suggest publishing next week")[
            "source_ref"
        ]
        service.bind_source_boundary("s1", "a1", [source])
        rejected = save(service, "The user decided to publish next week", "misattributed")
        assert rejected["reason"] == "source_role_mismatch"
        actual = save(service, "Assistant suggested publishing next week", "plan", basis="plan")
        assert actual["ok"] and actual["source_bindings"][0]["role"] == "assistant"
        assert actual["content_verification"] == "unchecked"
        assert service.source(source)["origin"] == "public_assistant_message"
    with opened(tmp_path, contract="legacy") as legacy:
        with pytest.raises(ValueError, match="ASSISTANT_CAPTURE_REQUIRES_EVENT_BOUND"):
            legacy.capture_assistant("s1", "a2", "Cannot silently add legacy assistant source")


def test_exact_sources_are_owner_bound_and_hash_checked(tmp_path: Path) -> None:
    with opened(tmp_path, "bob") as other:
        foreign = user(other, "u1", "Private preference")
    with opened(tmp_path) as service:
        assert (
            save(service, "Foreign claim", "foreign", source_refs=[foreign])["reason"]
            == "source_not_found_or_not_owned"
        )
        source = user(service, "u1", "Actual user bytes")
        with pytest.raises(ValueError, match="SOURCE_EVENT_CHANGED"):
            user(service, "u1", "Changed source body")
        with pytest.raises(ValueError, match="SOURCE_BOUNDARY_SCOPE_MISMATCH"):
            service.bind_source_boundary("different-session", "u1", [source])
        event = service.store.get(service.sources_namespace, source).value
        event["content"] = "Tampered source"
        service.store.put(service.sources_namespace, source, event, index=False)
        with pytest.raises(ValueError, match="SOURCE_INTEGRITY_FAILED"):
            save(service, "Tampered evidence", "tampered", source_ref=source)
        assert service.records() == []


def test_search_read_issue_handles_and_update_never_chooses_single_candidate(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as service:
        source = user(service, "u1", "Use concise replies")
        service.bind_source_boundary("s1", "u1", [source])
        first = save(service, "Concise replies", "create", source_ref=source)
        second = user(service, "u2", "Now include detail")
        service.bind_source_boundary("s1", "u2", [second])
        rejected = save(
            service, "Detailed replies", "automatic", action="update", target_query="Concise"
        )
        assert rejected["reason"] == "candidate_handle_required_or_invalid"
        read = invoke(service, "read_memory", {"id": first["id"]}, "read")
        search = invoke(service, "search_memory", {"query": "Concise"}, "search")
        assert read["candidate_handle"] == search["records"][0]["candidate_handle"]
        handle = read["candidate_handle"]
        for key, extra in [
            ("wrong-id", {"id": "wrong-record"}),
            ("wrong-version", {"expected_revision": 2}),
        ]:
            bad = save(
                service, "Detailed replies", key, action="update", candidate_handle=handle, **extra
            )
            assert bad["reason"] == "candidate_binding_mismatch"
        update = save(
            service, "Detailed replies", "update", action="update", candidate_handle=handle
        )
        assert update["revision"] == 2 and update["id"] == first["id"]
        assert service.read(first["id"], 1)["value"]["content"] == "Concise replies"
        assert save(
            service, "Detailed replies", "update", action="update", candidate_handle=handle
        )["replayed"]
        assert len(service.records()) == 1


def test_read_time_revision_conflicts_after_interleaved_update(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = user(service, "u1", "Initial preference")
        service.bind_source_boundary("s1", "u1", [source])
        first = save(service, "Preference", "create", source_ref=source)
        handle = service.read(first["id"])["candidate_handle"]
    with opened(tmp_path) as concurrent:
        source = user(concurrent, "u2", "Detailed preference")
        concurrent.bind_source_boundary("s1", "u2", [source])
        result = save(
            concurrent,
            "Detailed preference",
            "update-1",
            source_ref=source,
            action="update",
            candidate_handle=handle,
        )
        assert result["revision"] == 2
    with opened(tmp_path) as stale:
        source = user(stale, "u3", "Brief preference")
        stale.bind_source_boundary("s1", "u3", [source])
        result = save(
            stale,
            "Brief preference",
            "update-2",
            source_ref=source,
            action="update",
            candidate_handle=handle,
        )
        assert result["reason"] == "revision_conflict" and result["revision"] == 2
        assert stale.read(first["id"])["value"]["content"] == "Detailed preference"
        assert stale.read(first["id"], 1)["candidate_handle"] == handle
        assert len(stale.records()) == 1
        assert (
            next(row for row in stale.sources() if row["event_id"] == source)["formation_status"]
            == "pending"
        )


def test_handles_reopen_and_cannot_cross_owner_or_mutate_support(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = user(service, "u1", "Original source")
        service.bind_source_boundary("s1", "u1", [source])
        first = save(service, "Original card", "create", source_ref=source)
        handle = service.read(first["id"])["candidate_handle"]
        bound = service.candidate(handle)
        assert bound["owner"] == "alice" and bound["revision"] == 1
    with opened(tmp_path, "bob") as other:
        other.store.put(other.candidates_namespace, handle, bound, index=False)
        assert other.candidate(handle) is None
        ref = user(other, "u1", "Foreign update")
        assert (
            save(
                other,
                "Wrong owner",
                "bad",
                source_ref=ref,
                action="update",
                candidate_handle=handle,
            )["reason"]
            == "candidate_handle_required_or_invalid"
        )
    with opened(tmp_path) as reopened:
        assert reopened.candidate(handle) == bound
        changed = {
            **bound,
            "support_sources": [{**bound["support_sources"][0], "content_sha256": "fake"}],
        }
        reopened.store.put(reopened.candidates_namespace, handle, changed, index=False)
        assert reopened.candidate(handle) is None
        reopened.store.put(reopened.candidates_namespace, handle, bound, index=False)
        event = reopened.store.get(reopened.sources_namespace, source).value
        event["content"] = "Changed after read"
        reopened.store.put(reopened.sources_namespace, source, event, index=False)
        with pytest.raises(ValueError, match="SOURCE_INTEGRITY_FAILED"):
            reopened.candidate(handle)


@pytest.mark.parametrize("contract", [None, True, 1, [], {}, "event_bound_v2"])
def test_mutation_contract_rejects_invalid_values(tmp_path: Path, contract: Any) -> None:
    with (
        pytest.raises(ValueError, match="MUTATION_CONTRACT_INVALID"),
        opened(tmp_path, contract=contract),
    ):
        pass


def test_legacy_default_keeps_original_schema_and_latest_source_behavior(tmp_path: Path) -> None:
    with opened(tmp_path, contract="legacy") as service:
        user(service, "u1", "First event")
        latest = user(service, "u2", "Latest event")
        schema = create_service_tools(service)[0].tool_call_schema.model_json_schema()
        assert (
            "source_refs" not in schema["properties"]
            and "candidate_handle" not in schema["properties"]
        )
        first = save(service, "Legacy behavior", "create")
        assert first["source_ref"] == latest
        assert "source_refs" not in first and "mutation_contract" not in first
        assert "candidate_handle" not in service.read(first["id"])


@pytest.mark.parametrize("project", [False, True])
def test_p5_actual_runner_binds_current_user_and_observed_tool_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: bool
) -> None:
    from milai_lab.harness.artifact_io import read_json, write_json
    from milai_lab.runners import v13_1_p5 as runner

    path = Path(__file__).with_name("test_v13_1_p5.py")
    spec = importlib.util.spec_from_file_location("v13_2_p5_helpers", path)
    assert spec is not None and spec.loader is not None
    helpers = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helpers
    spec.loader.exec_module(helpers)
    helpers.prepared(tmp_path)
    settings = read_json(tmp_path / "config.json")
    capacity_helper = Path(__file__).parents[1] / "unit/test_v13_1_controls.py"
    capacity_spec = importlib.util.spec_from_file_location("source_index_capacity", capacity_helper)
    assert capacity_spec and capacity_spec.loader
    capacity_module = importlib.util.module_from_spec(capacity_spec)
    capacity_spec.loader.exec_module(capacity_module)
    settings["capacity"] = capacity_module.settings(tmp_path)["capacity"]
    settings["memory_mutation_contract"] = "event_bound_v1"
    if project:
        settings["memory_observation_profile"] = "reservation_v1"
    write_json(tmp_path / "config.json", settings)
    root = tmp_path / "bound-run"
    frozen = runner.prepare(tmp_path / "public.json", tmp_path / "config.json", root)
    assert frozen["memory_mutation_contract"] == "event_bound_v1"
    schema = frozen["tool_catalog"][0]["function"]["parameters"]
    assert "candidate_handle" in schema["properties"] and "source_refs" in schema["properties"]
    def local_model_with_capacity(*args: Any, **kwargs: Any) -> Any:
        from milai_lab.providers.contextual_capacity import HostCapacity

        model = helpers.local_model(*args, **kwargs)
        model.client.capacity = HostCapacity(settings["capacity"])
        return model

    monkeypatch.setattr(runner, "make_model", local_model_with_capacity)
    before = (tmp_path / "budget.json").read_bytes()
    result = runner.step(root, "mechanical", 0)
    assert result["status"] == "completed", result
    assert len(result["bank"]) == 1
    version = result["bank"][0]["value"]["_v13_1"]["current"]
    assert version["mutation_contract"] == "event_bound_v1"
    tool = next(row for row in result["sources"] if row["role"] == "tool")
    assert version["source_refs"] == [tool["event_id"]]
    assert version["source_bindings"][0]["content_sha256"] == tool["content_sha256"]
    assistant = next(row for row in result["sources"] if row["role"] == "assistant")
    assert assistant["content"] == result["final_answer"] == "Observed actual result."
    assert assistant["formation_status"] == "pending"
    assert (tmp_path / "budget.json").read_bytes() == before
    if project:
        assert len(result["observations"]["observations"]) == 2
        assert all(
            row["source_event_id"] == tool["event_id"]
            for row in result["observations"]["observations"]
        )
