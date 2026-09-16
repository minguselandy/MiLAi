from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from scripts import dg10_memory_fixture as fixture
from scripts import dg10_runtime_fixture as runtime_fixture


class Response:
    status_code = 201

    def __init__(self, value: Mapping[str, Any]) -> None:
        self.value = value

    def get_json(self, *, silent: bool = False) -> Mapping[str, Any]:
        del silent
        return self.value


class Client:
    def __init__(self) -> None:
        self.posts: list[tuple[str, Mapping[str, Any]]] = []

    def post(self, path: str, *, headers: Mapping[str, str], json: Mapping[str, Any]) -> Response:
        del headers
        self.posts.append((path, json))
        if path == "/v1/evidence":
            return Response({"evidence_id": "evidence-1"})
        return Response({"proposal_id": "proposal-1"})


class Worker:
    def run_once(self) -> int:
        return 1


def _gateway() -> runtime_fixture.RuntimeCanonicalGateway:
    return runtime_fixture.RuntimeCanonicalGateway(
        client=Client(),  # type: ignore[arg-type]
        worker=Worker(),  # type: ignore[arg-type]
        base_url="http://127.0.0.1:1",
        tokens={"submitter": "s", "reviewer": "r", "reader": "q"},
        run_id="case-1",
        expected_scope={"project_ids": ["milai-agent-e2e"]},
        ledger=None,
    )


def test_runtime_gateway_submits_full_session_content_and_scope() -> None:
    gateway = _gateway()
    session = fixture.CorpusSession(
        session_id="session-1",
        observed_at="2026-08-22T00:00:00+00:00",
        turns=(fixture.SessionTurn("user", "full content"),),
    )
    evidence_id = gateway.create_evidence(
        case_id="case-1",
        session=session,
        scope={"project_ids": ["milai-agent-e2e"]},
    )
    gateway.create_proposal(
        case_id="case-1",
        session=session,
        evidence_id=evidence_id,
        scope={"project_ids": ["milai-agent-e2e"]},
    )
    client = gateway.client
    assert isinstance(client, Client)
    assert client.posts[0][1]["content"] == session.render()
    patch = client.posts[1][1]["proposed_patch"]
    assert patch["payload"]["memory_text"] == session.render()
    assert client.posts[1][1]["scope_predicate"] == {"project_ids": ["milai-agent-e2e"]}


def test_runtime_gateway_rejects_scope_or_case_drift() -> None:
    gateway = _gateway()
    session = fixture.CorpusSession(
        session_id="session-1",
        observed_at="2026-08-22T00:00:00+00:00",
        turns=(fixture.SessionTurn("user", "content"),),
    )
    with pytest.raises(fixture.FixtureError, match="scope drift"):
        gateway.create_evidence(
            case_id="foreign",
            session=session,
            scope={"project_ids": ["wrong"]},
        )
