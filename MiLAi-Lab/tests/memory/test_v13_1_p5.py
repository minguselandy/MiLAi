"""Zero-network hard kills over the real Agent, SQLite Store/checkpoints and world."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig

TARGET = {"item_key": "parcel", "quantity": 1, "destination": "desk", "packing": "box"}


def permissions() -> list[dict[str, Any]]:
    return [
        {"operation_id": "reserve", "tool": "reserve_and_label", "args": TARGET, "target": TARGET},
        {
            "operation_id": "discover",
            "tool": "get_reservation",
            "args": {"item_key": "parcel"},
            "target": TARGET,
        },
        {
            "operation_id": "label",
            "tool": "complete_label",
            "args": {},
            "target": TARGET,
            "reservation_from": "discover",
            "retry": "no_effect",
            "recovery_retry": "confirmed_no_effect_v1",
            "precondition": {
                "query_operation_id": "discover",
                "status": "found",
                "label_status": "not_created",
            },
        },
    ]


class ScriptModel(LangMemRecipeChatModel):
    """Only mechanical test actions. No transport request, writer or injected Host labels."""

    script: str = "reserve"
    wire_path: Path

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._reserve_request()
        if self.script == "admission_failure":
            assert self.client.budget is not None
            self.client.budget.reserve("chat/completions", {"messages": [], "max_tokens": 2})
            raise RuntimeError("LOCAL_FAILURE_AFTER_DURABLE_ADMISSION")
        with self.wire_path.open("a") as stream:
            stream.write(json.dumps([row.model_dump(mode="json") for row in messages]) + "\n")
        human = next(row for row in reversed(messages) if isinstance(row, HumanMessage))
        current = messages[messages.index(human) + 1 :]
        tools = [row for row in current if isinstance(row, ToolMessage)]
        last = tools[-1] if tools else None
        calls: list[dict[str, Any]] = []
        if self.script == "read_loop":
            calls = [
                {
                    "name": "get_reservation",
                    "args": {"item_key": "parcel"},
                    "id": f"loop-{self.calls_in_message}",
                }
            ]
        elif not tools:
            if self.script in {"label", "mixed"}:
                calls = [{"name": "get_reservation", "args": {"item_key": "parcel"}, "id": "q"}]
            else:
                calls = [{"name": "reserve_and_label", "args": TARGET, "id": "reserve"}]
        elif last is not None and last.name == "get_reservation":
            raw = json.loads(str(last.content))
            native = raw.get("receipt", raw)
            calls = [
                {
                    "name": "complete_label",
                    "args": {"reservation_id": native["reservation_id"]},
                    "id": "label",
                }
            ]
            if self.script == "mixed":
                calls.append({"name": "search_memory", "args": {"query": "parcel"}, "id": "mixed"})
        elif last is not None and last.name in {"reserve_and_label", "complete_label"}:
            raw = json.loads(str(last.content))
            if raw.get("status") == "ORIGINAL_CALL_OUTCOME_UNKNOWN":
                observed = json.loads(raw["query_receipt"])
                if observed["label_status"] == "not_created" and self.script == "label":
                    calls = [
                        {
                            "name": "complete_label",
                            "args": {"reservation_id": observed["reservation_id"]},
                            "id": "remaining-label",
                        }
                    ]
                else:
                    raw = {"receipt": observed}
            if not calls:
                native = raw.get("receipt", raw)
                calls = (
                    [
                        {
                            "name": "manage_memory",
                            "args": {
                                "content": "parcel receipt preserved exactly",
                                "kind": "episodic",
                                "basis": "tool_observation",
                                "fields": {
                                    "status": native["status"],
                                    "label_status": native["label_status"],
                                },
                                **(
                                    {"action": "update", "target_query": "parcel"}
                                    if self.script == "label"
                                    else {}
                                ),
                            },
                            "id": f"{human.id}-memory",
                        }
                    ]
                    if "label_status" in native
                    else []
                )
        response = AIMessage(
            content="" if calls else "Observed actual result.",
            id=f"{human.id}-a{len([r for r in current if isinstance(r, AIMessage)])}",
            tool_calls=calls,
        )
        return ChatResult(generations=[ChatGeneration(message=response)])


def local_model(
    settings: dict[str, Any], budget: RunBudget, trace: Any, case_root: Path
) -> ScriptModel:
    def forbidden(_: httpx.Request) -> httpx.Response:
        raise AssertionError("NO_HTTP_ALLOWED")

    client = VLLMClient(
        VLLMConfig(**settings["host"]),
        emit=trace,
        budget=budget,
        transport=httpx.MockTransport(forbidden),
    )
    return ScriptModel(
        client=client,
        capacity_path=case_root / "host-capacity.json",
        max_calls_per_message=settings.get("max_calls_per_message", 12),
        script=os.environ.get("P5_TEST_SCRIPT", "reserve"),
        wire_path=case_root / "test-model-wire.jsonl",
    )


def prepared(
    tmp_path: Path, *, retry: bool = True, max_calls: int = 12, same_session: bool = False
) -> Path:
    from milai_lab.runners import v13_1_p5 as runner

    budget = RunBudget(RunLimits(1, 1, 100, 100000, 10000), tmp_path / "budget.json")
    # Persist an already charged temporary ledger, never touch the original run ledger.
    budget.reserve("chat/completions", {"messages": [], "max_tokens": 3})
    ops = permissions()
    if not retry:
        ops[-1].pop("recovery_retry")
    fixture = {
        "kind": "MILAI_V13_1_D0_NORMAL_USE",
        "cases": [
            {
                "case_id": "mechanical",
                "owner": "alice",
                "initial_world": {"label_available": False},
                "messages": [
                    {
                        "message_id": "m1",
                        "session_id": "s1",
                        "content": (
                            "Reserve parcel to desk in a box and remember the actual receipt."
                        ),
                        "application_binding": {"task_id": "public-permission", "operations": ops},
                    },
                    {
                        "message_id": "m2",
                        "session_id": "s1" if same_session else "s2",
                        "content": (
                            "Discover parcel and complete its pending label, then remember it."
                        ),
                        "application_binding": {"task_id": "public-permission", "operations": ops},
                    },
                ],
            }
        ],
    }
    config = {
        "host": {"base_url": "http://forbidden.invalid/v1", "model": "scripted-test"},
        "capacity": {},
        "budget_path": str(tmp_path / "budget.json"),
        "system_prompt": "Generic common assistant prompt.",
        "max_calls_per_message": max_calls,
    }
    write_json(tmp_path / "public.json", fixture)
    write_json(tmp_path / "config.json", config)
    root = tmp_path / "run"
    runner.prepare(tmp_path / "public.json", tmp_path / "config.json", root)
    return root


def child(
    root: Path,
    *,
    index: int = 0,
    phase: str = "start",
    window: str = "none",
    script: str = "reserve",
    retry_available: bool | None = None,
    attempt: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    from milai_lab.runners import v13_1_p5 as runner

    attempt = attempt or f"{index}-{phase}-{window}"
    env = {**os.environ, "P5_TEST_SCRIPT": script}
    process = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(Path(__file__).resolve()),
            str(root),
            str(index),
            phase,
            window,
            attempt,
            "unchanged" if retry_available is None else str(retry_available),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=40,
    )
    path = runner.case_path(root, "mechanical") / f"attempt-{attempt}.json"
    assert path.exists(), process.stderr
    return process, read_json(path)


@pytest.mark.parametrize("window", ["W1", "W2", "W3"])
def test_real_hard_exit_reopens_same_resources_and_preserves_window_truth(
    tmp_path: Path,
    window: str,
) -> None:
    from milai_lab.runners import v13_1_p5 as runner

    root = prepared(tmp_path)
    ledger = (tmp_path / "budget.json").read_bytes()
    killed, crash = child(root, window=window)
    assert killed.returncode == -signal.SIGKILL, killed.stderr
    assert crash["status"] == "hard_exit_armed"
    assert crash["checkpoint"]["next"] == ["tools"]
    assert crash["world"]["reservations"][0]["label_status"] == "not_created"
    original = next(row for row in crash["business_calls"] if row["name"] == "reserve_and_label")
    sources = [row for row in crash["sources"] if row["role"] == "tool"]
    assert original["status"] == ("pending" if window == "W1" else "complete")
    assert bool(sources) == (window != "W1")
    assert bool(crash["records"]) == (window == "W3")
    if window == "W3":
        assert crash["bank"][0]["value"]["_v13_1"]["proposals"]
    resumed, result = child(root, phase="resume")
    assert resumed.returncode == 0, resumed.stderr + str(result.get("error"))
    assert result["status"] == "completed"
    assert result["process_id"] != crash["process_id"]
    assert len(result["world"]["reservations"]) == 1
    assert len(result["world"]["attempts"]) == 1
    assert len(result["records"]) == 1
    assert len(result["bank"][0]["value"]["_v13_1"]["history"]) == 1
    assert (tmp_path / "budget.json").read_bytes() == ledger
    assert (
        read_json(runner.case_path(root, "mechanical") / f"attempt-0-start-{window}.json") == crash
    )
    if window == "W1":
        assert result["action_journal"][original["journal_key"]] == original
        recovery = result["action_journal"]["_application"]["recoveries"][original["journal_key"]]
        assert recovery["original_call_status"] == "UNKNOWN"
        assert recovery["effect"] == "partial"
        assert all(
            row["origin"] == "get_reservation" for row in result["sources"] if row["role"] == "tool"
        )
    wire = (runner.case_path(root, "mechanical") / "test-model-wire.jsonl").read_text()
    assert "application_binding" not in wire and "hard_exit" not in wire and window not in wire
    assert "remaining-label" not in wire
    assert result["checkpoint_history"]


@pytest.mark.parametrize("available,expected_effect", [(True, "confirmed"), (False, "none")])
def test_unknown_label_has_two_actual_backend_outcomes_and_separate_discovery(
    tmp_path: Path,
    available: bool,
    expected_effect: str,
) -> None:
    root = prepared(tmp_path)
    assert child(root)[0].returncode == 0
    killed, crash = child(root, index=1, window="W1", script="label", retry_available=available)
    assert killed.returncode == -signal.SIGKILL, killed.stderr
    pending = next(row for row in crash["business_calls"] if row["name"] == "complete_label")
    assert "result" not in pending and pending["effect"] == "unknown"
    assert crash["world"]["reservations"][0]["label_status"] == (
        "created" if available else "not_created"
    )
    assert not any(row["origin"] == "complete_label" for row in crash["sources"])
    process, result = child(root, index=1, phase="resume", script="label", retry_available=True)
    assert process.returncode == 0, process.stderr + str(result.get("error"))
    recovery = result["action_journal"]["_application"]["recoveries"][pending["journal_key"]]
    assert recovery["effect"] == expected_effect
    assert recovery["effect_source"] == "query_observation_not_original_execution_receipt"
    assert result["action_journal"][pending["journal_key"]] == pending
    assert result["world"]["reservations"][0]["label_status"] == "created"
    assert len(result["world"]["attempts"]) == 2
    assert any(row["origin"] == "get_reservation" for row in result["sources"])


def test_no_effect_does_not_grant_retry_without_explicit_contract(tmp_path: Path) -> None:
    root = prepared(tmp_path, retry=False)
    assert child(root)[0].returncode == 0
    assert child(root, index=1, window="W1", script="label")[0].returncode == -signal.SIGKILL
    process, result = child(root, index=1, phase="resume", script="label", retry_available=True)
    assert process.returncode == 0
    labels = [row for row in result["business_calls"] if row["name"] == "complete_label"]
    assert labels[-1]["executed"] is False
    assert labels[-1]["result"]["content"].find("APPLICATION_OPERATION_RETRY_NOT_ALLOWED") >= 0
    assert result["world"]["reservations"][0]["label_status"] == "not_created"


def test_mixed_batch_unresolved_does_not_skip_unexecuted_call(tmp_path: Path) -> None:
    root = prepared(tmp_path)
    assert child(root)[0].returncode == 0
    assert child(root, index=1, window="W1", script="mixed")[0].returncode == -signal.SIGKILL
    process, result = child(root, index=1, phase="resume", script="mixed")
    assert process.returncode == 1
    assert result["status"] == "interrupted"
    assert result["error"] == "APPLICATION_RECOVERY_OTHER_CALL_UNRESOLVED"
    assert result["first_error"]["error"] == result["error"]
    assert result["checkpoint"]["next"] == ["tools"]
    assert result["action_journal"]["_application"]["recoveries"] == {}


def test_update_replay_uses_durable_original_request_before_target_rebinding(
    tmp_path: Path,
) -> None:
    config = {"configurable": {"user_id": "alice", "v13_session": "s"}}
    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        service = MemoryService(store, ("test", "alice"), "alice", tmp_path / "lock")
        service.capture_user("s", "u", "I prefer coffee, then tea.")
        tool = create_service_tools(service, replay_requested=True)[0]
        created = json.loads(
            tool.invoke(
                {
                    "name": "manage_memory",
                    "id": "create",
                    "type": "tool_call",
                    "args": {"content": "coffee"},
                },
                config=config,
            ).content
        )
        request = {
            "name": "manage_memory",
            "id": "update",
            "type": "tool_call",
            "args": {"content": "tea", "action": "update", "target_query": "coffee"},
        }
        committed = json.loads(tool.invoke(request, config=config).content)
        assert committed["revision"] == 2
    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        service = MemoryService(store, ("test", "alice"), "alice", tmp_path / "lock")
        tool = create_service_tools(service, replay_requested=True)[0]
        replay = json.loads(tool.invoke(request, config=config).content)
        assert replay["ok"] and replay["replayed"] and replay["revision"] == 2
        assert replay["original_status"] == "committed"
        conflict = {**request, "args": {**request["args"], "content": "water"}}
        rejected = json.loads(tool.invoke(conflict, config=config).content)
        assert rejected["reason"] == "proposal_id_conflict"
        row = service.read(created["id"])
        assert row["value"]["revision"] == 2
        assert service.read(created["id"], 1)["value"]["content"] == "coffee"
        assert service.read(created["id"], 2)["value"]["content"] == "tea"
        attempts = service._rows(service.attempts_namespace)
        assert attempts[0]["value"]["raw"]["requested"]["content"] == "water"


def test_w3_actual_update_hard_kill_returns_persisted_revision_and_receipt(tmp_path: Path) -> None:
    from milai_lab.runners import v13_1_p5 as runner

    root = prepared(tmp_path)
    ledger = (tmp_path / "budget.json").read_bytes()
    assert child(root)[0].returncode == 0
    killed, crash = child(root, index=1, script="label", window="W3", retry_available=True)
    assert killed.returncode == -signal.SIGKILL, killed.stderr
    assert crash["final_answer"] is None
    bank = crash["bank"][0]["value"]["_v13_1"]
    assert bank["revision"] == 2 and len(bank["history"]) == 2
    proposal = next(p for p in bank["proposals"].values() if p["raw"]["action"] == "update")
    assert proposal["raw"]["requested"]["expected_revision"] is None
    assert proposal["raw"]["expected_revision"] == 1
    process, result = child(root, index=1, phase="resume", script="label")
    assert process.returncode == 0, process.stderr + str(result.get("error"))
    assert result["bank"][0]["value"]["_v13_1"] == bank
    assert result["world"] == crash["world"]
    events = [
        json.loads(line)
        for line in (runner.case_path(root, "mechanical") / "attempt-1-resume-none.jsonl")
        .read_text()
        .splitlines()
    ]
    replay = next(e["receipt"] for e in events if e["event"] == "v13_p5_memory_receipt")
    assert (
        replay["replayed"] and replay["original_status"] == "committed" and replay["revision"] == 2
    )
    assert result["generation_admissions"]["m2"] == 4
    assert (tmp_path / "budget.json").read_bytes() == ledger


def test_generation_cap_is_shared_across_crash_resume_and_later_attempts(tmp_path: Path) -> None:
    root = prepared(tmp_path, max_calls=12)
    ledger = (tmp_path / "budget.json").read_bytes()
    assert child(root)[0].returncode == 0
    assert child(root, index=1, script="label", window="W1")[0].returncode == -signal.SIGKILL
    process, result = child(root, index=1, phase="resume", script="read_loop", retry_available=True)
    assert process.returncode == 1
    assert result["error"] == "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"
    assert result["generation_admissions"] == {"m1": 3, "m2": 12}
    process, later = child(
        root, index=1, phase="resume", script="read_loop", attempt="another-resume"
    )
    assert (
        process.returncode == 1
        and later["generation_admissions"] == result["generation_admissions"]
    )
    assert later["first_error"] == result["first_error"]
    assert later["world"] == result["world"]
    assert (tmp_path / "budget.json").read_bytes() == ledger


def test_admitted_unknown_request_cannot_become_free_on_restart(tmp_path: Path) -> None:
    root = prepared(tmp_path, max_calls=1)
    before = read_json(tmp_path / "budget.json")
    process, failed = child(root, script="admission_failure")
    assert process.returncode == 1 and failed["error"] == "LOCAL_FAILURE_AFTER_DURABLE_ADMISSION"
    assert failed["generation_admissions"] == {"m1": 1}
    ledger = (tmp_path / "budget.json").read_bytes()
    after = read_json(tmp_path / "budget.json")
    assert after["generation_requests"] == before["generation_requests"] + 1
    assert after["generation"]["unknown_usage"] == before["generation"]["unknown_usage"] + 1
    process, resumed = child(root, phase="resume")
    assert process.returncode == 1
    assert resumed["error"] == "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"
    assert resumed["first_error"] == failed["first_error"]
    assert resumed["generation_admissions"] == {"m1": 1}
    assert (tmp_path / "budget.json").read_bytes() == ledger


def test_new_public_message_in_same_session_gets_own_cap_not_old_ai_history(tmp_path: Path) -> None:
    root = prepared(tmp_path, max_calls=4, same_session=True)
    process, first = child(root)
    assert process.returncode == 0 and first["generation_admissions"]["m1"] == 3
    process, second = child(root, index=1, script="label", retry_available=True)
    assert process.returncode == 0, process.stderr + str(second.get("error"))
    assert second["generation_admissions"] == {"m1": 3, "m2": 4}
    assert second["bank"][0]["value"]["_v13_1"]["revision"] == 2
    assert len(second["checkpoint"]["messages"]) > len(first["checkpoint"]["messages"])


def test_capture_failure_has_terminal_receipt_and_first_error_without_model_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.runners import v13_1_p5 as runner

    root = prepared(tmp_path)
    ledger = (tmp_path / "budget.json").read_bytes()

    def fail(*_: Any, **__: Any) -> Any:
        raise OSError("ACTUAL_CAPTURE_STORAGE_FAILURE")

    monkeypatch.setattr(MemoryService, "capture_user", fail)
    monkeypatch.setattr(runner, "make_model", local_model)
    result = runner.step(root, "mechanical", 0)
    assert result["status"] == "interrupted" and result["error"] == "ACTUAL_CAPTURE_STORAGE_FAILURE"
    assert result["generation_admissions"] == {} and result["sources"] == []
    assert result["first_error"]["error"] == result["error"]
    assert result["world"]["reservations"] == []
    assert (tmp_path / "budget.json").read_bytes() == ledger


def test_prepare_binds_effective_prompt_catalog_and_detects_frozen_source_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    from milai_lab.runners import v13_1_p5 as runner

    root = prepared(tmp_path)
    frozen = runner._frozen(root)
    assert (
        frozen["prompt_sha256"] == hashlib.sha256(b"Generic common assistant prompt.").hexdigest()
    )
    assert "tools/run_v13_1_p5.py" in frozen["source_sha256"]
    assert frozen["policy"]["checkpoint_durability"] == "sync"
    assert frozen["runtime_sdk"]["sqlite_modules"]["SqliteStore"]["sha256"]
    monkeypatch.setattr(
        runner, "_sources", lambda: {**frozen["source_sha256"], "changed.py": "new"}
    )
    with pytest.raises(ValueError, match="V13_P5_SOURCE_CHANGED_AFTER_FREEZE"):
        runner._frozen(root)


@pytest.mark.parametrize("value", [None, True, "generic_unknown_retry"])
def test_prepare_rejects_invalid_explicit_recovery_retry_contract(
    tmp_path: Path, value: Any
) -> None:
    from milai_lab.runners import v13_1_p5 as runner

    root = prepared(tmp_path)
    fixture = read_json(tmp_path / "public.json")
    fixture["cases"][0]["messages"][0]["application_binding"]["operations"][-1][
        "recovery_retry"
    ] = value
    write_json(tmp_path / "public.json", fixture)
    with pytest.raises(ValueError, match="APPLICATION_RECOVERY_RETRY_CONTRACT_INVALID"):
        runner.prepare(tmp_path / "public.json", tmp_path / "config.json", root / "rejected")


if __name__ == "__main__":
    from milai_lab.runners import v13_1_p5

    v13_1_p5.make_model = local_model
    change = sys.argv[6]
    output = v13_1_p5.step(
        Path(sys.argv[1]),
        "mechanical",
        int(sys.argv[2]),
        phase=sys.argv[3],
        window=sys.argv[4],
        attempt_id=sys.argv[5],
        window_tool="complete_label"
        if sys.argv[4] == "W1" and os.environ["P5_TEST_SCRIPT"] in {"label", "mixed"}
        else None,
        label_available=None if change == "unchanged" else change == "True",
        world_event_id=None if change == "unchanged" else sys.argv[5],
    )
    raise SystemExit(0 if output["status"] == "completed" else 1)
