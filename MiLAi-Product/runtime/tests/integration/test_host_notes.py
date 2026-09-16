"""Direct PG lifecycle coverage for the new ordinary-memory object."""
# ruff: noqa: F811 -- imported pytest fixture is injected by name

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from test_evidence_api import ACTOR_ID, TENANT_ID, _headers, evidence_app  # noqa: F401

from milai.persistence import SessionContext


def test_note_crud_replay_private_pagination_and_cas(evidence_app) -> None:  # type: ignore[no-untyped-def]
    client = evidence_app.test_client()
    binding = {"principal_binding_digest": "a" * 64, "project_id": "notes-" + uuid4().hex}
    other = {**binding, "principal_binding_digest": "b" * 64}
    content = " \r\n独立笔记 🧠\n```python\nx = 1\n```\t "
    add_body = {**binding, "operation": "ADD", "content": content}
    operation_id = uuid4().hex
    first = client.post("/v1/notes/write", json=add_body, headers=_headers(operation_id))
    assert first.status_code == 200, first.json
    note = first.json
    assert note["version"] == 1 and note["authority"] == "HOST_WORKING"
    assert "content" not in note
    second = client.post("/v1/notes/write", json=add_body, headers=_headers(uuid4().hex))
    assert second.status_code == 200
    assert note["memory_id"] != second.json["memory_id"]
    get_body = {**binding, "memory_id": note["memory_id"]}
    read = client.post("/v1/notes/get", json=get_body, headers=_headers("read"))
    assert read.json["content"] == content
    assert read.json["content_complete"] is True
    assert read.json["observed_at"] is None
    foreign = client.post("/v1/notes/get", json={**get_body, **other}, headers=_headers("read"))
    assert foreign.status_code == 404
    listed = client.post("/v1/notes/browse", json={**binding, "limit": 1}, headers=_headers("read"))
    assert listed.status_code == 200, listed.json
    assert listed.json["next_cursor"] is not None
    page = client.post("/v1/notes/browse", json={
        **binding, "limit": 1, "cursor": listed.json["next_cursor"],
    }, headers=_headers("read"))
    assert page.status_code == 200
    assert page.json["items"][0]["memory_id"] != listed.json["items"][0]["memory_id"]
    foreign_page = client.post("/v1/notes/browse", json={
        **other, "cursor": listed.json["next_cursor"],
    }, headers=_headers("read"))
    assert foreign_page.status_code == 400
    search = client.post("/v1/notes/browse", json={**binding, "query": "独立笔记"},
                         headers=_headers("read"))
    assert len(search.json["items"]) == 2

    def update(index: int) -> int:
        with evidence_app.test_client() as parallel:
            return parallel.post("/v1/notes/write", json={
                **get_body, "operation": "UPDATE", "expected_version": 1,
                "content": f"revised {index}",
            }, headers=_headers(uuid4().hex)).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update, [1, 2])) == [200, 409]
    replay = client.post("/v1/notes/write", json=add_body, headers=_headers(operation_id))
    assert replay.json["version"] == 1 and replay.json["replayed"]
    conflict = client.post("/v1/notes/write", json={**add_body, "content": "different intent"},
                           headers=_headers(operation_id))
    assert conflict.status_code == 409
    recorded = client.post("/v1/notes/operations/get", json={
        **binding, "operation_id": operation_id,
    }, headers=_headers("read"))
    assert recorded.status_code == 200, recorded.json
    assert recorded.json["version"] == 1
    history = client.post(
        "/v1/notes/get", json={**get_body, "version": 1}, headers=_headers("read"),
    )
    assert history.json["content"] == content
    delete_id = uuid4().hex
    delete_body = {**get_body, "operation": "DELETE", "expected_version": 2}
    deleted = client.post("/v1/notes/write", json=delete_body, headers=_headers(delete_id))
    assert deleted.status_code == 200, deleted.json
    assert deleted.json["status"] == "DELETED"
    assert deleted.json["deletion"]["primary_storage"] == "NOT_IMPLEMENTED"
    assert deleted.json["deletion"]["physical_deletion_supported"] is False
    repeated = client.post("/v1/notes/write", json=delete_body, headers=_headers(delete_id))
    assert repeated.json["version"] == deleted.json["version"] and repeated.json["replayed"]
    assert repeated.json["deletion"] == deleted.json["deletion"]
    hidden = client.post("/v1/notes/get", json={**get_body, "version": 1}, headers=_headers("read"))
    assert hidden.json["content"] is None
    replay = client.post("/v1/notes/write", json=add_body, headers=_headers(operation_id))
    assert replay.status_code == 200 and replay.json["status"] == "DELETED"
    assert replay.json["deletion"] == deleted.json["deletion"]
    assert "content_digest" not in replay.json
    unchanged = client.post("/v1/notes/get", json={
        **binding, "memory_id": second.json["memory_id"],
    }, headers=_headers("read"))
    assert unchanged.json["content"] == content

    def race(operation: str) -> int:
        args = {**binding, "memory_id": second.json["memory_id"],
                "expected_version": 1, "operation": operation}
        if operation == "UPDATE":
            args["content"] = "concurrent edit"
        with evidence_app.test_client() as parallel:
            return parallel.post("/v1/notes/write", json=args,
                                 headers=_headers(uuid4().hex)).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(race, ["DELETE", "UPDATE"])) == [200, 409]

    database = evidence_app.extensions["milai.database"]
    with database.connection(SessionContext(TENANT_ID, uuid4()), read_only=True) as connection:
        for table in ["host_note", "host_note_version", "host_note_evidence_ref"]:
            count = connection.execute(
                f"SELECT count(*) FROM milai.{table}",  # noqa: S608 -- fixed table names only
            ).fetchone()
            assert count[0] == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with database.connection(SessionContext(TENANT_ID, ACTOR_ID)) as connection:
            connection.execute("UPDATE milai.host_note SET current_version=1 WHERE false")


def test_note_search_late_match_survives_a_new_client_and_stays_private(evidence_app):
    binding = {"principal_binding_digest": "c" * 64, "project_id": "search-" + uuid4().hex}
    foreign = {**binding, "principal_binding_digest": "d" * 64}
    event = "会议在 2026-01-05 举行，不是本周。"  # noqa: RUF001 -- exact Chinese source
    content = "unrelated introduction " * 100 + event + " end" * 100
    with evidence_app.test_client() as writer:
        saved = writer.post("/v1/notes/write", json={
            **binding, "operation": "ADD", "content": content,
            "observed_at": "2026-01-05T09:00:00+08:00",
        }, headers=_headers(uuid4().hex))
        assert saved.status_code == 200
    with evidence_app.test_client() as reader:
        found = reader.post("/v1/notes/browse", json={**binding, "query": "会议"},
                            headers=_headers("read")).json
        assert len(found["items"]) == 1
        item = found["items"][0]
        assert item["memory_id"] == saved.json["memory_id"]
        assert event in item["snippet"]
        assert content[item["snippet_offset"]:item["snippet_end"]] == item["snippet"]
        assert item["observed_at"].startswith("2026-01-05")
        assert item["observed_at"] != item["recorded_at"]
        assert found["absence_confirmed"] is False
        not_matched = reader.post("/v1/notes/browse", json={
            **binding, "query": "这周会议 meetings this week",
        }, headers=_headers("read")).json
        assert not_matched["items"] == [] and not_matched["absence_confirmed"] is False
        denied = reader.post("/v1/notes/browse", json={**foreign, "query": "会议"},
                             headers=_headers("read")).json
        assert denied["items"] == []
