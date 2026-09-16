from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_agent_openapi_covers_every_typed_client_route_including_governed_review() -> None:
    document = yaml.safe_load((ROOT / "contracts/agent/v1/openapi.yaml").read_text())
    assert document["openapi"] == "3.1.0"
    paths = document["paths"]
    expected = {
        "/health/live",
        "/health/ready",
        "/v1/capabilities",
        "/v1/memory/query",
        "/v1/memory/resolve",
        "/v1/memory/get",
        "/v1/context-capsules",
        "/v1/claims/{claim_id}",
        "/v1/open-issues",
        "/v1/retrieval-traces/{trace_id}",
        "/v1/evidence",
        "/v1/evidence/{evidence_id}",
        "/v1/proposals",
        "/v1/proposals/{proposal_id}",
        "/v1/proposals/{proposal_id}/review",
        "/v1/causal-tokens",
        "/v1/evidence/{evidence_id}/revoke",
        "/v1/evidence/{evidence_id}/deletion-status",
        "/v1/episodes",
    }
    assert expected <= set(paths)
    assert all("settle" not in path for path in paths)
    task_context = document["components"]["schemas"]["TaskContextHint"]
    assert task_context["additionalProperties"] is False
    assert set(task_context["properties"]) == {
        "project_ids",
        "entities",
        "memory_types",
        "action_risk",
    }
    assert "authority" not in task_context["properties"]
    for path in (
        "/v1/evidence",
        "/v1/proposals",
        "/v1/proposals/{proposal_id}/review",
        "/v1/evidence/{evidence_id}/revoke",
        "/v1/episodes",
    ):
        parameters = paths[path]["post"].get("parameters", [])
        assert any(item.get("$ref", "").endswith("/IdempotencyKey") for item in parameters)


def test_tool_contract_profiles_are_exact_and_forbidden_tools_are_unreachable() -> None:
    document: dict[str, Any] = json.loads(
        (ROOT / "contracts/agent/v1/tool-contract.json").read_text()
    )
    reader = {
        "milai_status",
        "milai_recall",
        "milai_memory_resolve",
        "milai_memory_get",
        "milai_claim_get",
        "milai_open_issues_list",
        "milai_trace_get",
        "milai_evidence_metadata_get",
    }
    assert set(document["profiles"]["reader"]) == reader
    assert set(document["profiles"]["reader-detail"]) == reader
    assert set(document["profiles"]["reader-lite"]) == {
        "milai_recall",
        "milai_memory_resolve",
    }
    assert set(document["profiles"]["submitter"]) - reader == {
        "milai_evidence_capture",
        "milai_proposal_create",
    }
    assert set(document["profiles"]["operator"]) - reader == {
        "milai_evidence_revoke",
        "milai_deletion_status_get",
    }
    assert set(document["profiles"]["reviewer"]) - reader == {
        "milai_proposals_list",
        "milai_proposal_get",
        "milai_memory_review",
    }
    exposed = {name for values in document["profiles"].values() for name in values}
    assert exposed.isdisjoint(document["forbidden_tools"])
    assert document["transport"] == {"default": "stdio", "remote": "disabled"}
