from __future__ import annotations

from pathlib import Path

from flask.testing import FlaskClient

from milai.api.app import create_app
from milai.api.auth import authenticated_context, profile_actor_id
from milai.config import load_settings


class _Database:
    def ping(self) -> None:
        return None


def _client(tmp_path: Path) -> tuple[FlaskClient, dict[str, str]]:
    blob_root = tmp_path / "blobs"
    blob_root.mkdir()
    tokens = {
        "reader": "reader-token-with-at-least-32-characters",
        "submitter": "submitter-token-with-at-least-32-characters",
        "operator": "operator-token-with-at-least-32-characters",
        "reviewer": "reviewer-token-with-at-least-32-characters",
    }
    settings = load_settings(
        {
            "MILAI_DATABASE_URL": "postgresql://milai_api:secret@127.0.0.1:15432/milai",
            "MILAI_STEWARD_DATABASE_URL": "postgresql://milai_steward:secret@127.0.0.1:15432/milai",
            "MILAI_BLOB_ROOT": str(blob_root),
            "MILAI_TENANT_ID": "11111111-1111-4111-8111-111111111111",
            "MILAI_LOCAL_ACTOR_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "MILAI_API_TOKEN": "legacy-token-with-at-least-32-characters",
            "MILAI_CAUSAL_TOKEN_SECRET": "causal-secret-with-at-least-32-characters",
            "MILAI_AGENT_READER_TOKEN": tokens["reader"],
            "MILAI_AGENT_SUBMITTER_TOKEN": tokens["submitter"],
            "MILAI_AGENT_OPERATOR_TOKEN": tokens["operator"],
            "MILAI_AGENT_REVIEWER_TOKEN": tokens["reviewer"],
        }
    )
    database = _Database()
    app = create_app(settings, database=database, steward_database=database)  # type: ignore[arg-type]
    app.config["TESTING"] = True
    return app.test_client(), tokens


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_capabilities_return_only_effective_reader_scope(tmp_path: Path) -> None:
    client, tokens = _client(tmp_path)
    response = client.get("/v1/capabilities", headers=_auth(tokens["reader"]))
    assert response.status_code == 200
    assert response.get_json()["capabilities"] == ["memory:read"]
    assert response.get_json()["data_mode"] == "SYNTHETIC_ONLY"
    assert response.get_json()["api_version"] == "1"
    assert response.get_json()["contract_version"] == "agent.v1"
    assert response.get_json()["routes"] == ["L0", "L1"]
    assert response.get_json()["consistency_modes"] == [
        "EVENTUAL",
        "READ_YOUR_WRITES",
        "CANONICAL_REQUIRED",
    ]
    assert response.get_json()["limits"] == {
        "query_chars": 2_000,
        "max_results": 50,
        "max_evidence_bytes": 1_048_576,
    }
    assert response.get_json()["features"]["remote_access"] is False
    assert response.get_json()["features"]["memory_resolve_query_first"] is True
    assert response.get_json()["features"]["memory_exact_get"] is True
    assert response.get_json()["features"]["memory_state_view"] is True
    assert response.get_json()["features"]["memory_state_view_bitemporal"] is True
    assert response.get_json()["features"]["host_cognitive_state"] is True
    assert response.get_json()["features"]["host_cognitive_state_cas"] is True
    assert response.get_json()["features"]["host_cognitive_state_audit_default"] is True
    assert response.get_json()["features"]["host_execution_event_journal"] is True
    assert response.get_json()["features"]["host_execution_event_shadow_only"] is True
    assert response.get_json()["features"]["retrieval_continuation_v0_1"] is False
    assert response.get_json()["features"]["intra_source_acquisition_v0_1_mode"] == (
        "OFF"
    )
    assert response.get_json()["features"]["query_aware_bounded_search"] is True
    assert response.get_json()["features"]["possible_low_cost_probe"] is True
    assert response.get_json()["features"]["hard_partitioned_candidate_search"] is True
    assert response.get_json()["features"]["conditional_vector_reranker"] is True
    assert response.get_json()["features"]["governed_mcp_review"] is True
    assert response.get_json()["features"]["reviewer_actor_separation"] is True
    assert response.get_json()["features"]["incremental_projection_outbox"] is True
    assert response.get_json()["features"]["projection_rebuild"] is True
    assert response.get_json()["features"]["optional_task_context_narrowing"] is True
    assert response.get_json()["features"]["task_free_retrieval"] is True


def test_reader_cannot_capture_or_create_proposal(tmp_path: Path) -> None:
    client, tokens = _client(tmp_path)
    for path in ("/v1/evidence", "/v1/proposals"):
        response = client.post(path, headers=_auth(tokens["reader"]), json={})
        assert response.status_code == 403
        assert response.get_json()["error"]["code"] == "CAPABILITY_REQUIRED"


def test_reader_host_principal_binding_derives_stable_distinct_rls_actors(
    tmp_path: Path,
) -> None:
    client, tokens = _client(tmp_path)
    app = client.application

    @app.get("/_test/effective-reader-actor")
    def effective_reader_actor():  # type: ignore[no-untyped-def]
        return {"actor_id": str(authenticated_context(app).actor_id)}

    def actor(binding: str):
        return client.get(
            "/_test/effective-reader-actor",
            headers={
                **_auth(tokens["reader"]),
                "X-MiLA-Host-Principal-Binding-Digest": binding,
            },
        )

    first = actor("a" * 64)
    repeated = actor("a" * 64)
    second = actor("b" * 64)
    assert first.status_code == repeated.status_code == second.status_code == 200
    assert first.get_json()["actor_id"] == repeated.get_json()["actor_id"]
    assert first.get_json()["actor_id"] != second.get_json()["actor_id"]

    invalid = actor("not-a-digest")
    assert invalid.status_code == 403
    assert invalid.get_json()["error"]["code"] == "INVALID_HOST_PRINCIPAL_BINDING"


def test_submitter_cannot_review_and_operator_cannot_capture(tmp_path: Path) -> None:
    client, tokens = _client(tmp_path)
    review = client.post(
        "/v1/proposals/11111111-1111-4111-8111-111111111111/review",
        headers=_auth(tokens["submitter"]),
        json={},
    )
    capture = client.post("/v1/evidence", headers=_auth(tokens["operator"]), json={})
    assert review.status_code == 403
    assert capture.status_code == 403


def test_working_state_requires_submitter_host_cognition_capabilities(tmp_path: Path) -> None:
    client, tokens = _client(tmp_path)
    reader = client.post(
        "/v1/working-state/get", headers=_auth(tokens["reader"]), json={}
    )
    assert reader.status_code == 403
    assert reader.get_json()["error"]["details"] == {
        "required_capability": "working-state:read"
    }

    submitter = client.get("/v1/capabilities", headers=_auth(tokens["submitter"]))
    assert set(submitter.get_json()["capabilities"]) == {
        "memory:read",
        "evidence:capture",
        "proposal:create",
        "working-state:read",
        "working-state:write",
    }


def test_host_event_journal_reuses_host_cognition_capabilities(tmp_path: Path) -> None:
    client, tokens = _client(tmp_path)
    reader = client.post(
        "/v1/host-events/window", headers=_auth(tokens["reader"]), json={}
    )
    assert reader.status_code == 403
    assert reader.get_json()["error"]["details"] == {
        "required_capability": "working-state:read"
    }

    submitter = client.post(
        "/v1/host-events/append", headers=_auth(tokens["submitter"]), json={}
    )
    assert submitter.status_code == 400
    assert submitter.get_json()["error"]["code"] == "INVALID_REQUEST"


def test_proposal_inspection_requires_review_capability(tmp_path: Path) -> None:
    client, tokens = _client(tmp_path)
    paths = (
        "/v1/proposals?status=PENDING_REVIEW&limit=10",
        "/v1/proposals/11111111-1111-4111-8111-111111111111",
    )
    for profile in ("reader", "submitter", "operator"):
        for path in paths:
            response = client.get(path, headers=_auth(tokens[profile]))
            assert response.status_code == 403
            error = response.get_json()["error"]
            assert error["code"] == "CAPABILITY_REQUIRED"
            assert error["details"] == {"required_capability": "proposal:review"}


def test_reviewer_is_minimum_capability_and_named_profile_actors_are_distinct(
    tmp_path: Path,
) -> None:
    client, tokens = _client(tmp_path)
    response = client.get("/v1/capabilities", headers=_auth(tokens["reviewer"]))
    assert response.status_code == 200
    assert response.get_json()["capabilities"] == ["memory:read", "proposal:review"]

    settings = client.application.extensions["milai.settings"]
    submitter_actor = profile_actor_id(settings, "submitter")
    reviewer_actor = profile_actor_id(settings, "reviewer")
    assert submitter_actor != reviewer_actor
    assert reviewer_actor == profile_actor_id(settings, "reviewer")

    forbidden_capture = client.post(
        "/v1/evidence", headers=_auth(tokens["reviewer"]), json={}
    )
    forbidden_proposal = client.post(
        "/v1/proposals", headers=_auth(tokens["reviewer"]), json={}
    )
    assert forbidden_capture.status_code == 403
    assert forbidden_proposal.status_code == 403
