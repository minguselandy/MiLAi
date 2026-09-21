from __future__ import annotations

import os
import stat
from uuid import uuid4

import psycopg
import pytest
from test_projection_worker import _headers, _url
from test_projection_worker import worker_runtime as worker_runtime

pytestmark = pytest.mark.integration


@pytest.mark.integration
@pytest.mark.parametrize("worker_runtime", [False, True], indirect=True)
def test_directory_sync_failure_prevents_evidence_and_outbox_commit(
    worker_runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, app, _ = worker_runtime
    app.config["TESTING"] = False
    client = app.test_client()
    operation = "durable-blob-" + uuid4().hex
    content = " \tfirst field\r\n完整内容\nlast field\n\t "
    payload = {
        "source_type": "RUNTIME_OBSERVATION",
        "source_ref": "durability://" + operation,
        "subject_id": "durability-subject",
        "observed_at": "2026-09-06T10:00:00+08:00",
        "content": content,
        "permission_snapshot": {"readable": True},
    }
    real_sync = os.fsync

    def sync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected directory sync failure")
        real_sync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", sync)
        failed = client.post("/v1/evidence", headers=_headers(operation), json=payload)
        assert failed.status_code == 500

    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        counts = owner.execute(
            """
            SELECT
              (SELECT count(*) FROM milai.evidence_record WHERE tenant_id = %s),
              (SELECT count(*) FROM milai.outbox_event WHERE tenant_id = %s)
            """,
            (settings.tenant_id, settings.tenant_id),
        ).fetchone()
    assert counts == (0, 0)
    saved = client.post("/v1/evidence", headers=_headers(operation), json=payload)
    assert saved.status_code == 201 and saved.json["replayed"] is False
    replay = client.post("/v1/evidence", headers=_headers(operation), json=payload)
    assert replay.status_code == 200 and replay.json["replayed"] is True
    for key in ("evidence_id", "blob_id", "outbox_id"):
        assert saved.json[key] == replay.json[key]
    direct = client.get("/v1/evidence/" + saved.json["evidence_id"], headers=_headers())
    assert direct.status_code == 200 and direct.json["content"] == content
