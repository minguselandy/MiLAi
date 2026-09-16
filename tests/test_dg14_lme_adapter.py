from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from evals.dg14 import (
    DG14AdapterConfig,
    DG14ContractError,
    DG14HistoryEvent,
    DG14LifecycleError,
    DG14MilaiMcpAdapter,
    deterministic_event_id,
    deterministic_history_session_id,
    deterministic_project_id,
)
from evals.dg14.contracts import McpProfile


class CaptureOnlyTransport:
    def __init__(self) -> None:
        self.opened = False
        self.calls: list[str] = []
        self.arguments: list[dict[str, object]] = []

    def open_case(self, _scope: Mapping[str, object]) -> None:
        self.opened = True

    def call(
        self,
        _profile: McpProfile,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        self.calls.append(tool_name)
        self.arguments.append(dict(arguments))
        if tool_name == "milai_evidence_capture":
            return {"evidence_id": "evidence-1"}
        if tool_name == "milai_evidence_revoke":
            return {"evidence_id": arguments["evidence_id"]}
        raise AssertionError(f"unexpected call in lifecycle test: {tool_name}")

    def close(self) -> None:
        self.opened = False


def _history_event(
    *,
    session_ordinal: int = 0,
    original_session_id: str = "session-repeated",
    turn_ordinal: int = 0,
) -> DG14HistoryEvent:
    return DG14HistoryEvent(
        case_id="001be529",
        session_ordinal=session_ordinal,
        original_session_id=original_session_id,
        turn_ordinal=turn_ordinal,
        role="user",
        content=f"memory-{session_ordinal}-{turn_ordinal}",
        observed_at="2026-08-26T01:02:03+00:00",
    )


def test_event_identity_binds_all_four_components_and_repeated_session_ids() -> None:
    first = _history_event(session_ordinal=0, turn_ordinal=0)
    duplicate_original_id = _history_event(session_ordinal=1, turn_ordinal=0)

    assert first.event_id == deterministic_event_id(
        "001be529", 0, "session-repeated", 0
    )
    assert first.event_id == _history_event(session_ordinal=0, turn_ordinal=0).event_id
    assert first.event_id != duplicate_original_id.event_id
    assert deterministic_history_session_id(
        first.case_id, first.session_ordinal, first.original_session_id
    ) != deterministic_history_session_id(
        duplicate_original_id.case_id,
        duplicate_original_id.session_ordinal,
        duplicate_original_id.original_session_id,
    )
    assert (
        len(
            {
                deterministic_event_id("001be529", 0, "session-repeated", 0),
                deterministic_event_id("different-case", 0, "session-repeated", 0),
                deterministic_event_id("001be529", 1, "session-repeated", 0),
                deterministic_event_id("001be529", 0, "different-session", 0),
                deterministic_event_id("001be529", 0, "session-repeated", 1),
            }
        )
        == 5
    )


def test_history_event_rejects_ambiguous_ordinals_and_naive_timestamps() -> None:
    with pytest.raises(DG14ContractError, match="session_ordinal"):
        _history_event(session_ordinal=-1)
    with pytest.raises(DG14ContractError, match="turn_ordinal"):
        _history_event(turn_ordinal=-1)
    with pytest.raises(DG14ContractError, match="timezone"):
        DG14HistoryEvent(
            case_id="001be529",
            session_ordinal=0,
            original_session_id="session-1",
            turn_ordinal=0,
            role="user",
            content="memory",
            observed_at="2026-08-26T01:02:03",
        )


def test_case_namespace_is_stable_per_run_and_case_and_distinct_across_cases() -> None:
    assert deterministic_project_id("run-1", "case-1") == deterministic_project_id(
        "run-1", "case-1"
    )
    assert deterministic_project_id("run-1", "case-1") != deterministic_project_id(
        "run-1", "case-2"
    )
    assert deterministic_project_id("run-1", "case-1") != deterministic_project_id(
        "run-2", "case-1"
    )


def test_adapter_config_requires_all_current_profiles_and_cannot_prebind_project_scope(
    tmp_path: Path,
) -> None:
    tokens: Mapping[McpProfile, str] = {
        "submitter": "submitter-token",
        "reviewer": "reviewer-token",
        "reader-detail": "reader-token",
        "operator": "operator-token",
    }
    config = DG14AdapterConfig(
        base_url="http://127.0.0.1:8765",
        executable=tmp_path / "milai-mcp",
        profile_tokens=tokens,
        scope={"workspaces": ["opened-dev"]},
    )
    assert config.allowed_budgets == (512, 2048)
    assert set(config.profile_tokens) == set(tokens)

    with pytest.raises(DG14ContractError, match="exactly"):
        DG14AdapterConfig(
            base_url=config.base_url,
            executable=config.executable,
            profile_tokens=cast(Mapping[McpProfile, str], {"submitter": "one"}),
        )
    with pytest.raises(DG14ContractError, match="project_ids"):
        DG14AdapterConfig(
            base_url=config.base_url,
            executable=config.executable,
            profile_tokens=tokens,
            scope={"project_ids": ["cross-case"]},
        )


def test_adapter_lifecycle_is_explicit_and_duplicate_replay_is_not_silent(
    tmp_path: Path,
) -> None:
    transport = CaptureOnlyTransport()
    adapter = DG14MilaiMcpAdapter(
        DG14AdapterConfig(
            base_url="http://127.0.0.1:8765",
            executable=tmp_path / "milai-mcp",
            profile_tokens={
                "submitter": "submitter-token",
                "reviewer": "reviewer-token",
                "reader-detail": "reader-token",
                "operator": "operator-token",
            },
        ),
        token_counter=lambda text: len(text.split()),
        transport=transport,
    )

    with pytest.raises(DG14LifecycleError, match="finalize"):
        adapter.finalize()
    with pytest.raises(DG14LifecycleError, match="query"):
        adapter.query("question", "2026-08-26T01:03:00+00:00", 512)
    with pytest.raises(DG14LifecycleError, match="no query result"):
        adapter.export_context()

    adapter.reset("run-unit", "001be529")
    with pytest.raises(DG14LifecycleError, match="at least one"):
        adapter.finalize()
    adapter.ingest(_history_event())
    with pytest.raises(
        DG14ContractError, match="duplicate deterministic Event identity"
    ):
        adapter.ingest(_history_event())
    with pytest.raises(DG14LifecycleError, match="finalized"):
        adapter.query("question", "2026-08-26T01:03:00+00:00", 512)

    assert adapter.cleanup() == ("evidence-1",)
    assert transport.calls == ["milai_evidence_capture", "milai_evidence_revoke"]
    source_context = transport.arguments[0]["source_context"]
    assert isinstance(source_context, dict)
    session_id = deterministic_history_session_id("001be529", 0, "session-repeated")
    assert source_context == {
        "session_id": session_id,
        "turn_id": f"{session_id}:turn:0",
        "turn_ordinal": 0,
        "round_id": f"{session_id}:round:0",
        "round_ordinal": 0,
        "previous_turn_id": None,
        "next_turn_id": None,
    }
    assert source_context["session_id"] != transport.arguments[0]["subject_id"]
    assert transport.opened is False
    with pytest.raises(DG14LifecycleError, match="active case"):
        adapter.cleanup()
