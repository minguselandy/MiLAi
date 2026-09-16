"""Independent small journal-boundary checks; no actual public requests."""

import hashlib
import json
from uuid import uuid4

import pytest
from test_v0224_public_note_store import store as shared_store

from v0220_evidence import read, save

store = shared_store  # pytest fixture discovery


def known_call(token, tool, arguments):
    return {
        "commit_status": "COMMITTED",
        "durable": True,
        "operation": "ADD",
        "operation_id": arguments["operation_id"],
        "replayed": False,
        "version": 1,
        "memory_id": str(uuid4()),
        "content_digest": "sha256:" + hashlib.sha256(arguments["content"].encode()).hexdigest(),
    }


def test_repeated_id_never_overwrites_original_intent_or_sends_again(store):
    calls = []

    def call(*args):
        calls.append(args)
        return known_call(*args)

    store.client.cold_call = call
    store.write("original", operation_id="same")
    path = next(store.directory.glob("operation-*.intent.json"))
    before = path.read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        store.write("changed", operation_id="same")
    assert path.read_bytes() == before and len(calls) == 1


def test_unknown_cannot_be_released_by_local_committed_string(store):
    def lost(*args):
        raise RuntimeError("lost")

    store.client.cold_call = lost
    with pytest.raises(RuntimeError):
        store.write("original", operation_id="one")
    intent = next(store.directory.glob("operation-*.intent.json"))
    save(
        intent.with_name(intent.name.replace(".intent.json", ".result.json")),
        {"status": "COMMITTED"},
    )
    with pytest.raises(ValueError):
        store.validate()


@pytest.mark.parametrize("which", ["intent", "receipt", "result"])
def test_committed_triplet_must_remain_consistent(store, which):
    store.client.cold_call = known_call
    store.write("original", operation_id="one")
    path = next(store.directory.glob("operation-*." + which + ".json"))
    value = read(path)
    if which == "intent":
        value["content"] = "drift"
    elif which == "receipt":
        value["content_digest"] = "sha256:" + "0" * 64
    else:
        value["response"]["memory_id"] = str(uuid4())
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        store.validate()


def test_credential_bytes_used_for_send_must_match_external_pin(store, monkeypatch):
    original = type(store.credential_path).read_bytes
    reads, sends = [], []

    def read_bytes(path):
        if path == store.credential_path:
            reads.append(path)
            if len(reads) >= 2:
                return b"different-token-between-validation-and-use"
        return original(path)

    monkeypatch.setattr(type(store.credential_path), "read_bytes", read_bytes)
    store.client.cold_call = lambda *args: sends.append(args)
    with pytest.raises(ValueError, match="CREDENTIAL"):
        store.write("no send", operation_id="one")
    assert sends == []
