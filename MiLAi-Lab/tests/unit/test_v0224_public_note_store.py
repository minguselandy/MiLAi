"""Durable Host operation accounting with a synthetic public client, no HTTP."""

import hashlib
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0224_public_note_store as module
from v0220_evidence import read, sha


@pytest.fixture
def store(tmp_path, monkeypatch):
    client = tmp_path / "public-client.py"
    client.write_text(
        "class Probe:\n"
        "    def __init__(self, *args): self.rows = []\n"
        "    def cold_call(self, *args): raise AssertionError('NO_HTTP_TEST_CLIENT')\n"
    )
    monkeypatch.setattr(module, "PUBLIC_CLIENT", client)
    credential = tmp_path / "credential"
    credential.write_text("synthetic-token-not-a-real-credential")
    credential.chmod(0o600)
    return module.PublicNoteStore(
        tmp_path / "session/note-store",
        origin="http://127.0.0.1:27337",
        credential_path=credential,
        credential_sha256=sha(credential),
        client_sha256=sha(client),
        validate_binding=lambda: None,
    )


@pytest.mark.parametrize("outcome", ["COMMITTED", "LOST_RECEIPT", "NOT_DURABLE"])
def test_durable_intent_precedes_send_and_unknown_blocks_another_operation(store, outcome):
    calls = []

    def public_call(token, tool, arguments):
        intent = next(store.directory.glob("operation-*.intent.json"))
        assert read(intent)["operation_id"] == arguments["operation_id"]
        assert read(intent)["content"] == arguments["content"]
        calls.append(arguments)
        if outcome == "LOST_RECEIPT":
            raise RuntimeError("SYNTHETIC_RECEIPT_LOSS")
        return {
            "commit_status": "COMMITTED",
            "durable": outcome == "COMMITTED",
            "operation": "ADD",
            "operation_id": arguments["operation_id"],
            "replayed": False,
            "version": 1,
            "memory_id": str(uuid4()),
            "content_digest": "sha256:" + hashlib.sha256(arguments["content"].encode()).hexdigest(),
        }

    store.client.cold_call = public_call
    assert not store.directory.exists()  # Construction cannot pre-create the Host directory.
    if outcome == "COMMITTED":
        result = store.write("Exact ordinary text.", operation_id="e:01")
        assert result["version_domain"] == "NOTE" and result["committed"]
        assert store.unresolved() == []
    else:
        with pytest.raises((RuntimeError, ValueError)):
            store.write("Exact ordinary text.", operation_id="e:01")
        assert store.unresolved() == ["e:01"]
        with pytest.raises(ValueError, match="UNKNOWN"):
            store.write("Do not send this.", operation_id="e:02")
    assert len(calls) == 1


def test_credential_drift_blocks_before_public_call(store):
    store.credential_path.write_text("changed")
    with pytest.raises(ValueError, match="CREDENTIAL"):
        store.write("Do not send.", operation_id="e:01")
    assert not store.directory.exists()
