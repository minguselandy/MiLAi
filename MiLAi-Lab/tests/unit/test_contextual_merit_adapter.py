from __future__ import annotations

import json
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from milai_lab.harness.contextual_artifacts import digest, read_json, write_json
from milai_lab.runners.contextual_host import HostResult

_ADAPTER_PATH = Path(__file__).resolve().parents[2] / "tools/run_contextual_merit.py"
_SPEC = spec_from_file_location("run_contextual_merit", _ADAPTER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
merit_adapter = module_from_spec(_SPEC)
_SPEC.loader.exec_module(merit_adapter)


def pinned_inputs(tmp_path: Path) -> tuple[Any, ...]:
    # The v7 freeze stays immutable while these offline adapter tests follow v8 source edits.
    freeze = read_json(merit_adapter.DEFAULT_FREEZE)
    freeze["source_sha256"] = {
        relative: merit_adapter.sha256(merit_adapter.LAB / relative)
        for relative in freeze["source_sha256"]
    }
    freeze["source_mapping_sha256"] = digest(freeze["source_sha256"])
    current_freeze = tmp_path / "current-source-freeze.json"
    write_json(current_freeze, freeze)
    selection = read_json(merit_adapter.DEFAULT_SELECTION)
    selection["repair_freeze_sha256"] = freeze["source_mapping_sha256"]
    selection["previous_selection_sha256"] = merit_adapter.sha256(
        merit_adapter.DEFAULT_SELECTION
    )
    current_selection = tmp_path / "current-source-selection.json"
    write_json(current_selection, selection)
    return merit_adapter.prepared_inputs(
        current_selection,
        merit_adapter.DEFAULT_CONFIG,
        current_freeze,
    )


def test_v8_selection_requires_declared_config_and_matching_freeze(tmp_path: Path) -> None:
    config_path = merit_adapter.LAB / "configs/contextual-memory-v8-off.json"
    selection = read_json(merit_adapter.DEFAULT_SELECTION)
    selection["execution_plan"]["arms"] = ["ordinary_v8_off"]
    selection["config_path"] = "configs/contextual-memory-v8-off.json"
    selection["config_sha256"] = merit_adapter.sha256(config_path)
    freeze = read_json(merit_adapter.DEFAULT_FREEZE)
    freeze["source_sha256"] = {
        relative: merit_adapter.sha256(merit_adapter.LAB / relative)
        for relative in freeze["source_sha256"]
    }
    freeze["source_mapping_sha256"] = digest(freeze["source_sha256"])
    freeze["config_sha256"][selection["config_path"]] = selection["config_sha256"]
    selection["development_freeze_sha256"] = freeze["source_mapping_sha256"]
    selected_path = tmp_path / "selection.json"
    freeze_path = tmp_path / "freeze.json"
    write_json(selected_path, selection)
    write_json(freeze_path, freeze)
    prepared = merit_adapter.prepared_inputs(selected_path, config_path, freeze_path)
    assert prepared[0]["execution_plan"]["arms"] == ["ordinary_v8_off"]
    with pytest.raises(ValueError, match="MERIT_CONTROLLER_CONFIG_CHANGED"):
        merit_adapter.prepared_inputs(
            selected_path, merit_adapter.DEFAULT_CONFIG, freeze_path,
        )
    selection["config_sha256"] = "0" * 64
    write_json(selected_path, selection)
    with pytest.raises(ValueError, match="MERIT_CONTROLLER_CONFIG_CHANGED"):
        merit_adapter.prepared_inputs(selected_path, config_path, freeze_path)
    selection["config_sha256"] = merit_adapter.sha256(config_path)
    selection["development_freeze_sha256"] = "0" * 64
    write_json(selected_path, selection)
    with pytest.raises(ValueError, match="MERIT_SELECTED_FREEZE_MISMATCH"):
        merit_adapter.prepared_inputs(selected_path, config_path, freeze_path)
    selection.pop("config_path")
    selection.pop("config_sha256")
    selection["development_freeze_sha256"] = freeze["source_mapping_sha256"]
    write_json(selected_path, selection)
    with pytest.raises(ValueError, match="MERIT_SELECTION_CONFIG_REQUIRED"):
        merit_adapter.prepared_inputs(selected_path, config_path, freeze_path)


def test_pinned_prepare_preserves_native_tools_and_visible_memory_gate(tmp_path: Path) -> None:
    selection, _, identity, arc, native_tools, _, _, diagnostic, _ = pinned_inputs(tmp_path)
    assert (
        diagnostic["episode_count"],
        diagnostic["user_message_count"],
        diagnostic["dependent_episode_count"],
    ) == (5, 7, 2)
    assert identity["arc_sha256"] == selection["private_artifacts"]["arc_sha256"]
    world = arc.make_world()
    try:
        calls: list[dict[str, Any]] = []
        business = merit_adapter.business_tools(world, native_tools, calls)
        result = business["get_order"].execute({"order_id": "missing"}, "session:1:0")
        assert result.status == "failed"
        assert result.output == native_tools.get_order(world, "missing")
        assert result.observation is not None
        assert result.observation.content == result.output
        assert calls[0]["args"] == {"order_id": "missing"}
    finally:
        world.conn.close()

    shown = {
        "operation_receipt": {},
        "result": {
            "materials": [
                {"kind": "interpretation", "text": "visible agreed amount"},
            ]
        },
    }
    unseen = {
        "operation_receipt": {},
        "result": {
            "materials": [
                {"kind": "source", "content": "not yet sent"},
            ]
        },
    }
    transcript = [
        {"role": "user", "content": "current request secret"},
        {"role": "user", "content": "json_action tool result: " + json.dumps(shown)},
        {"role": "assistant", "content": "continue"},
        {"role": "user", "content": "json_action tool result: " + json.dumps(unseen)},
    ]
    assert merit_adapter.visible_memory_bodies(transcript) == ["visible agreed amount"]


def test_prefetched_current_memory_counts_only_delivered_projected_bodies() -> None:
    projected = {
        "view": merit_adapter.VIEW_PROTOCOL,
        "query": "query-only private value",
        "status": "status-only private value",
        "content": "top-level private value",
        "materials": [
            {"kind": "interpretation", "text": "old decision", "status": "CURRENT"},
        ],
        "expanded_materials": [
            {"kind": "source", "content": "older source wording"},
        ],
    }
    transcript = [
        {"role": "user", "content": "Current request with a new private value"},
        {"role": "user", "content": "Relevant current memory: " + json.dumps(projected)},
        {"role": "assistant", "content": "Use the delivered memory."},
        {"role": "user", "content": "Relevant current memory: " + json.dumps({
            "view": merit_adapter.VIEW_PROTOCOL,
            "materials": [{"kind": "source", "content": "not yet seen by Host"}],
        })},
    ]
    assert merit_adapter.visible_memory_bodies(transcript) == [
        "old decision", "older source wording",
    ]


def test_arc_interrupts_on_incomplete_public_turn_without_closing_or_scoring(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    selection, config, _, arc, native_tools, metrics, native_runner, _, _ = pinned_inputs(tmp_path)
    delivered: list[tuple[str, str, bool, str]] = []
    closed: list[str] = []

    @contextmanager
    def fake_runtime(*args: Any, **kwargs: Any) -> Any:
        memory = SimpleNamespace(checkpoint=lambda **_: {"format": "offline-test"})
        host = SimpleNamespace(prompt="")
        yield memory, host, {"budget": {"generation_requests": 0}}

    def fake_session(
        turns: Any, *, session_id: str, session: Any = None, **kwargs: Any
    ) -> tuple[Any, list[HostResult]]:
        turn = turns[0]
        delivered.append(
            (session_id, turn.question, session is not None, turn.observations[0].actor_ref)
        )
        session = session or SimpleNamespace(close=lambda: closed.append(session_id))
        status = "incomplete" if len(delivered) == 2 else "complete"
        result = HostResult("", status, [], {}, 0.0, [{"role": "assistant", "content": status}])
        return session, [result]

    monkeypatch.setattr(merit_adapter, "task_runtime", fake_runtime)
    monkeypatch.setattr(merit_adapter, "run_task_session", fake_session)
    with pytest.raises(RuntimeError, match="PUBLIC_TURN_INCOMPLETE: incomplete"):
        merit_adapter.run_arc(
            tmp_path, selection, config, arc, native_tools, metrics, native_runner,
        )
    assert len(delivered) == 2
    assert delivered[0][0] != delivered[1][0]  # next episode starts a new session
    assert all(actor == "" for _, _, _, actor in delivered)
    assert closed == [delivered[0][0]]
    assert (tmp_path / "episodes/episode-0.json").exists()
    assert not (tmp_path / "episodes/episode-1.json").exists()
    assert not (tmp_path / "result.json").exists()
    interrupted = read_json(tmp_path / "interruption.json")
    assert interrupted["episode_index"] == 1
    assert interrupted["public_turn_index"] == 0
    assert interrupted["phase"] == "public_turn_incomplete"
    assert interrupted["native_score"] == {"status": "unscored"}
    assert interrupted["host_results"][0]["status"] == "incomplete"


def test_interruption_preserves_live_world_session_and_unscored_status(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    selection, config, _, arc, native_tools, metrics, native_runner, _, _ = pinned_inputs(tmp_path)
    captured: dict[str, Any] = {}

    @contextmanager
    def fake_runtime(*args: Any, **kwargs: Any) -> Any:
        captured["business"] = kwargs["business_tools"]
        memory = SimpleNamespace(
            checkpoint=lambda **options: {
                "format": "offline-test",
                "task_included": options["include_task"],
            }
        )
        host = SimpleNamespace(prompt="", last_session=None)
        captured["host"] = host
        yield memory, host, {"budget": {"generation_requests": 1}}

    def interrupted_session(turns: Any, **kwargs: Any) -> Any:
        captured["business"]["get_order"].execute({"order_id": "missing"}, "call-1")
        captured["after_world"] = captured["world"].snapshot()
        captured["host"].last_session = SimpleNamespace(
            session_id="arc0-000:episode:0", turn_id="message-0",
            transcript=[{"role": "user", "content": "real delivered request"}],
            maintenance={"pending": {"source:one": {"status": "pending"}}},
        )
        raise RuntimeError("transport interrupted")

    original_make_world = arc.make_world

    def tracked_world() -> Any:
        world = original_make_world()
        captured["world"] = world
        return world

    monkeypatch.setattr(arc, "make_world", tracked_world)
    monkeypatch.setattr(merit_adapter, "task_runtime", fake_runtime)
    monkeypatch.setattr(merit_adapter, "run_task_session", interrupted_session)
    with pytest.raises(RuntimeError, match="transport interrupted"):
        merit_adapter.run_arc(
            tmp_path / "interrupted", selection, config, arc, native_tools, metrics, native_runner,
        )
    interrupted = read_json(tmp_path / "interrupted/interruption.json")
    assert interrupted["status"] == "interrupted"
    assert interrupted["native_score"] == {"status": "unscored"}
    assert interrupted["episode_index"] == 0
    assert interrupted["public_turn_index"] == 0
    assert interrupted["after_world"] == captured["after_world"]
    assert interrupted["memory_checkpoint"]["task_included"] is True
    assert interrupted["session"]["transcript"][0]["content"] == "real delivered request"
    assert interrupted["maintenance_pending"] is True
    assert interrupted["business_calls"][0]["status"] == "failed"
    assert interrupted["runtime_budget"]["generation_requests"] == 1
    assert interrupted["error"]["type"] == "RuntimeError"
    assert merit_adapter.maintenance_pending(
        SimpleNamespace(maintenance={"unsettled_operations": {"op:one": {}}}), []
    )
    assert not (tmp_path / "interrupted/result.json").exists()
