from __future__ import annotations

import os
import time
from pathlib import Path
from uuid import UUID

import pytest

from milai.adapters.blob_store import BlobIntegrityError, LocalContentAddressedBlobStore

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")


def test_content_addressed_write_is_tenant_scoped_and_idempotent(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStore(tmp_path / "blobs")
    first = store.write(TENANT_ID, b"MiLAi evidence")
    second = store.write(TENANT_ID, b"MiLAi evidence")
    assert first.content_hash == second.content_hash
    assert first.storage_uri == second.storage_uri
    assert first.created is True
    assert second.created is False
    assert store.read(TENANT_ID, first.storage_uri, first.content_hash, first.byte_length) == (
        b"MiLAi evidence"
    )


def test_blob_integrity_failure_is_explicit(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStore(tmp_path / "blobs")
    stored = store.write(TENANT_ID, b"original")
    target = next((tmp_path / "blobs").rglob(stored.content_hash))
    target.write_bytes(b"tampered")
    with pytest.raises(BlobIntegrityError, match="verification"):
        store.read(TENANT_ID, stored.storage_uri, stored.content_hash, stored.byte_length)


def test_blob_uri_cannot_cross_tenants(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStore(tmp_path / "blobs")
    stored = store.write(TENANT_ID, b"tenant one")
    other_tenant = UUID("22222222-2222-4222-8222-222222222222")
    with pytest.raises(BlobIntegrityError, match="URI"):
        store.read(other_tenant, stored.storage_uri, stored.content_hash, stored.byte_length)


def test_blob_erasure_is_safe_and_idempotent(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStore(tmp_path / "blobs")
    stored = store.write(TENANT_ID, b"erase-me")
    first = store.erase(TENANT_ID, stored.storage_uri, stored.content_hash)
    replay = store.erase(TENANT_ID, stored.storage_uri, stored.content_hash)
    assert first.disposition == "ERASED_AND_VERIFIED_ABSENT"
    assert replay.disposition == "VERIFIED_ALREADY_ABSENT"
    assert first.proof_hash != replay.proof_hash
    assert first.content_hash == replay.content_hash == stored.content_hash
    other_tenant = UUID("22222222-2222-4222-8222-222222222222")
    with pytest.raises(BlobIntegrityError, match="URI"):
        store.erase(other_tenant, stored.storage_uri, stored.content_hash)


def test_blob_erasure_rejects_tamper_symlink_and_non_regular_target(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStore(tmp_path / "blobs")

    tampered = store.write(TENANT_ID, b"tamper-before-erase")
    tampered_path = next((tmp_path / "blobs").rglob(tampered.content_hash))
    tampered_path.write_bytes(b"changed")
    with pytest.raises(BlobIntegrityError, match="hash verification"):
        store.erase(TENANT_ID, tampered.storage_uri, tampered.content_hash)

    symlinked = store.write(TENANT_ID, b"symlink-before-erase")
    symlink_path = next((tmp_path / "blobs").rglob(symlinked.content_hash))
    symlink_path.unlink()
    symlink_path.symlink_to(tmp_path / "missing-target")
    with pytest.raises(BlobIntegrityError, match="regular file"):
        store.erase(TENANT_ID, symlinked.storage_uri, symlinked.content_hash)

    non_regular = store.write(TENANT_ID, b"directory-before-erase")
    directory_path = next((tmp_path / "blobs").rglob(non_regular.content_hash))
    directory_path.unlink()
    directory_path.mkdir()
    with pytest.raises(BlobIntegrityError, match="regular file"):
        store.erase(TENANT_ID, non_regular.storage_uri, non_regular.content_hash)


def test_missing_blob_returns_identity_bound_absence_proof(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStore(tmp_path / "blobs")
    content_hash = "a" * 64
    storage_uri = f"cas://sha256/{TENANT_ID}/{content_hash}"
    proof = store.erase(TENANT_ID, storage_uri, content_hash)
    assert proof.disposition == "VERIFIED_ALREADY_ABSENT"
    assert len(proof.proof_hash) == 64


def test_orphan_reconciliation_retains_references_and_defers_fresh_files(
    tmp_path: Path,
) -> None:
    store = LocalContentAddressedBlobStore(tmp_path / "blobs")
    retained = store.write(TENANT_ID, b"canonical")
    orphan = store.write(TENANT_ID, b"orphaned-before-db")
    fresh = store.write(TENANT_ID, b"still-in-flight")
    orphan_path = next((tmp_path / "blobs").rglob(orphan.content_hash))
    old = time.time() - 600
    os.utime(orphan_path, (old, old))

    result = store.reconcile_orphans(
        TENANT_ID,
        {retained.content_hash},
        min_age_seconds=300,
    )

    assert result == {
        "status": "RECONCILED",
        "scanned": 3,
        "retained": 1,
        "deferred": 1,
        "erased": 1,
    }
    assert store.read(
        TENANT_ID, retained.storage_uri, retained.content_hash, retained.byte_length
    ) == b"canonical"
    assert not orphan_path.exists()
    assert store.read(TENANT_ID, fresh.storage_uri, fresh.content_hash, fresh.byte_length) == (
        b"still-in-flight"
    )


def test_encrypted_blob_round_trip_hides_plaintext_and_is_idempotent(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStore(
        tmp_path / "blobs", kek=b"k" * 32, key_reference="test-kek-v1"
    )
    first = store.write(TENANT_ID, b"private evidence", "text/plain")
    second = store.write(TENANT_ID, b"private evidence", "text/plain")
    target = next((tmp_path / "blobs").rglob(first.content_hash))
    assert b"private evidence" not in target.read_bytes()
    assert second.created is False
    assert store.read(TENANT_ID, first.storage_uri, first.content_hash, first.byte_length) == (
        b"private evidence"
    )


def test_encrypted_blob_wrong_key_and_tamper_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    store = LocalContentAddressedBlobStore(root, kek=b"a" * 32, key_reference="test-kek-v1")
    stored = store.write(TENANT_ID, b"authenticated evidence")
    wrong = LocalContentAddressedBlobStore(root, kek=b"b" * 32, key_reference="test-kek-v1")
    with pytest.raises(BlobIntegrityError, match="authentication"):
        wrong.read(TENANT_ID, stored.storage_uri, stored.content_hash, stored.byte_length)

    target = next(root.rglob(stored.content_hash))
    raw = bytearray(target.read_bytes())
    raw[-5] ^= 1
    target.write_bytes(raw)
    with pytest.raises(BlobIntegrityError, match="authentication"):
        store.erase(TENANT_ID, stored.storage_uri, stored.content_hash)
    assert target.exists()


def test_personal_mode_store_rejects_legacy_plaintext(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    plaintext = LocalContentAddressedBlobStore(root)
    stored = plaintext.write(TENANT_ID, b"legacy plaintext")
    personal = LocalContentAddressedBlobStore(
        root,
        kek=b"k" * 32,
        key_reference="test-kek-v1",
        allow_plaintext_read=False,
    )
    with pytest.raises(BlobIntegrityError, match="plaintext blob is forbidden"):
        personal.read(TENANT_ID, stored.storage_uri, stored.content_hash, stored.byte_length)


def test_encrypted_key_rotation_is_atomic_and_resumable(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    old = LocalContentAddressedBlobStore(root, kek=b"a" * 32, key_reference="kek-v1")
    blobs = [old.write(TENANT_ID, value) for value in (b"one", b"two")]
    first = old.rotate_tenant_key(TENANT_ID, new_kek=b"b" * 32, new_key_reference="kek-v2")
    assert first["rotated"] == 2
    new = LocalContentAddressedBlobStore(root, kek=b"b" * 32, key_reference="kek-v2")
    replay = old.rotate_tenant_key(TENANT_ID, new_kek=b"b" * 32, new_key_reference="kek-v2")
    assert replay["already_rotated"] == 2
    assert new.read(TENANT_ID, blobs[0].storage_uri, blobs[0].content_hash, 3) == b"one"
    with pytest.raises(BlobIntegrityError, match="authentication"):
        old.read(TENANT_ID, blobs[0].storage_uri, blobs[0].content_hash, 3)
