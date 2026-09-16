from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import stat
import tempfile
import time
from collections.abc import Iterator, Set
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_ENVELOPE_MAGIC = b"MILAI-AEAD-V1\n"


class BlobStoreError(RuntimeError):
    """Base class for safe local blob failures."""


class BlobIntegrityError(BlobStoreError):
    pass


@dataclass(frozen=True, slots=True)
class StoredBlob:
    content_hash: str
    storage_uri: str
    byte_length: int
    created: bool


@dataclass(frozen=True, slots=True)
class ErasureProof:
    disposition: str
    content_hash: str
    storage_uri: str
    proof_hash: str


class LocalContentAddressedBlobStore:
    def __init__(
        self,
        root: Path,
        *,
        kek: bytes | None = None,
        key_reference: str = "local-kek-v1",
        allow_plaintext_read: bool = True,
    ) -> None:
        self._root = root.resolve(strict=False)
        if kek is not None and len(kek) != 32:
            raise BlobStoreError("KEK must contain exactly 32 bytes")
        self._kek = kek
        self._key_reference = key_reference
        self._allow_plaintext_read = allow_plaintext_read

    def write(
        self,
        tenant_id: UUID,
        content: bytes,
        media_type: str = "application/octet-stream",
    ) -> StoredBlob:
        content_hash = hashlib.sha256(content).hexdigest()
        with self._blob_lock(tenant_id, content_hash):
            return self._write_locked(tenant_id, content, media_type, content_hash)

    def _write_locked(
        self,
        tenant_id: UUID,
        content: bytes,
        media_type: str,
        content_hash: str,
    ) -> StoredBlob:
        target = self._path(tenant_id, content_hash)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.parent.chmod(0o700)

        if target.exists():
            self._verify_file(target, tenant_id, content_hash, len(content))
            return StoredBlob(content_hash, self._uri(tenant_id, content_hash), len(content), False)

        file_descriptor, temporary_name = tempfile.mkstemp(prefix=".staging-", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(file_descriptor, 0o600)
            with os.fdopen(file_descriptor, "wb", closefd=True) as handle:
                stored_content = (
                    self._encrypt(tenant_id, content_hash, content, media_type)
                    if self._kek is not None
                    else content
                )
                handle.write(stored_content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            target.chmod(0o600)
            self._verify_file(target, tenant_id, content_hash, len(content))
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return StoredBlob(content_hash, self._uri(tenant_id, content_hash), len(content), True)

    def read(
        self,
        tenant_id: UUID,
        storage_uri: str,
        expected_hash: str,
        expected_length: int,
    ) -> bytes:
        if storage_uri != self._uri(tenant_id, expected_hash):
            raise BlobIntegrityError("blob URI does not match its canonical identity")
        target = self._path(tenant_id, expected_hash)
        if target.is_symlink() or not target.is_file():
            raise BlobIntegrityError("blob is missing or is not a regular file")
        content = self._decode_file(target, tenant_id, expected_hash)
        if len(content) != expected_length or hashlib.sha256(content).hexdigest() != expected_hash:
            raise BlobIntegrityError("blob hash or length verification failed")
        return content

    def erase(self, tenant_id: UUID, storage_uri: str, expected_hash: str) -> ErasureProof:
        if storage_uri != self._uri(tenant_id, expected_hash):
            raise BlobIntegrityError("blob URI does not match its canonical identity")
        with self._blob_lock(tenant_id, expected_hash):
            return self._erase_locked(tenant_id, storage_uri, expected_hash)

    def _erase_locked(
        self, tenant_id: UUID, storage_uri: str, expected_hash: str
    ) -> ErasureProof:
        target = self._path(tenant_id, expected_hash)
        try:
            metadata = os.lstat(target)
        except FileNotFoundError:
            return self._erasure_proof(
                tenant_id, storage_uri, expected_hash, "VERIFIED_ALREADY_ABSENT"
            )
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise BlobIntegrityError("blob target is not a regular file")
        content = self._decode_file(target, tenant_id, expected_hash)
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise BlobIntegrityError("blob hash verification failed before erasure")
        target.unlink()
        directory_descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        try:
            os.lstat(target)
        except FileNotFoundError:
            return self._erasure_proof(
                tenant_id, storage_uri, expected_hash, "ERASED_AND_VERIFIED_ABSENT"
            )
        raise BlobIntegrityError("blob remained present after erasure")

    def reconcile_orphans(
        self,
        tenant_id: UUID,
        referenced_hashes: Set[str],
        *,
        min_age_seconds: int = 300,
    ) -> dict[str, int | str]:
        """Erase finalized CAS files that never acquired a canonical DB reference.

        The grace window protects in-flight Blob-before-DB writes. A per-hash
        cross-process lock closes the remaining race with concurrent ingestion.
        """
        if min_age_seconds < 1:
            raise ValueError("orphan reconciliation grace must be positive")
        tenant_root = (self._root / str(tenant_id)).resolve(strict=False)
        if not tenant_root.is_relative_to(self._root):
            raise BlobIntegrityError("tenant blob path escapes configured root")
        cutoff = time.time() - min_age_seconds
        scanned = retained = deferred = erased = 0
        for target in sorted(tenant_root.glob("*/*")) if tenant_root.exists() else []:
            content_hash = target.name
            if len(content_hash) != 64 or any(
                character not in "0123456789abcdef" for character in content_hash
            ):
                continue
            scanned += 1
            if content_hash in referenced_hashes:
                retained += 1
                continue
            with self._blob_lock(tenant_id, content_hash):
                try:
                    metadata = os.lstat(target)
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise BlobIntegrityError("orphan candidate is not a regular file")
                if metadata.st_mtime > cutoff:
                    deferred += 1
                    continue
                proof = self._erase_locked(
                    tenant_id,
                    self._uri(tenant_id, content_hash),
                    content_hash,
                )
                if proof.disposition == "ERASED_AND_VERIFIED_ABSENT":
                    erased += 1
        return {
            "status": "RECONCILED",
            "scanned": scanned,
            "retained": retained,
            "deferred": deferred,
            "erased": erased,
        }

    @contextmanager
    def _blob_lock(self, tenant_id: UUID, content_hash: str) -> Iterator[None]:
        # Validate the hash through the canonical path builder before creating
        # a lock file derived from it.
        self._path(tenant_id, content_hash)
        # Locks are operational state, not blob data: keep them beside the CAS
        # root so backup/restore manifests contain only durable blob payloads.
        lock_root = self._root.parent / f".{self._root.name}.locks"
        lock_dir = lock_root / str(tenant_id) / content_hash[:2]
        lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_dir.chmod(0o700)
        lock_path = lock_dir / f"{content_hash}.lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def rotate_tenant_key(
        self, tenant_id: UUID, *, new_kek: bytes, new_key_reference: str
    ) -> dict[str, object]:
        """Atomically rotate each envelope; already-rotated files make retries resumable."""
        if self._kek is None:
            raise BlobStoreError("current KEK is required for key rotation")
        replacement = LocalContentAddressedBlobStore(
            self._root,
            kek=new_kek,
            key_reference=new_key_reference,
            allow_plaintext_read=False,
        )
        tenant_root = (self._root / str(tenant_id)).resolve(strict=False)
        if not tenant_root.is_relative_to(self._root):
            raise BlobIntegrityError("tenant blob path escapes configured root")
        rotated = 0
        already_rotated = 0
        for target in sorted(tenant_root.glob("*/*")) if tenant_root.exists() else []:
            if target.is_symlink() or not target.is_file():
                raise BlobIntegrityError("rotation target is not a regular file")
            content_hash = target.name
            raw = target.read_bytes()
            media_type = "application/octet-stream"
            current_reference: str | None = None
            if raw.startswith(_ENVELOPE_MAGIC):
                try:
                    envelope = json.loads(raw[len(_ENVELOPE_MAGIC) :].decode("utf-8"))
                    current_reference = str(envelope["key_reference"])
                    media_type = str(envelope["media_type"])
                except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    raise BlobIntegrityError("encrypted blob envelope is invalid") from exc
            if current_reference == new_key_reference:
                replacement._decode_file(target, tenant_id, content_hash)
                already_rotated += 1
                continue
            if current_reference not in {None, self._key_reference}:
                raise BlobIntegrityError("blob uses an unexpected key reference")
            content = self._decode_file(target, tenant_id, content_hash)
            encoded = replacement._encrypt(tenant_id, content_hash, content, media_type)
            descriptor, temporary_name = tempfile.mkstemp(prefix=".rotation-", dir=target.parent)
            temporary = Path(temporary_name)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "wb", closefd=True) as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                replacement._decode_file(temporary, tenant_id, content_hash)
                os.replace(temporary, target)
                target.chmod(0o600)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            rotated += 1
        return {
            "status": "ROTATED",
            "tenant_id": str(tenant_id),
            "new_key_reference": new_key_reference,
            "rotated": rotated,
            "already_rotated": already_rotated,
        }

    def _path(self, tenant_id: UUID, content_hash: str) -> Path:
        if len(content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in content_hash
        ):
            raise BlobIntegrityError("invalid content hash")
        # Resolve the parent, but deliberately do not resolve the final component.
        # Erasure must inspect a final-component symlink with lstat instead of
        # following it. Resolving the parent still rejects a directory symlink
        # that would escape the private blob root.
        parent = (self._root / str(tenant_id) / content_hash[:2]).resolve(strict=False)
        if not parent.is_relative_to(self._root):
            raise BlobIntegrityError("blob path escapes configured root")
        return parent / content_hash

    @staticmethod
    def _uri(tenant_id: UUID, content_hash: str) -> str:
        return f"cas://sha256/{tenant_id}/{content_hash}"

    def _verify_file(
        self, path: Path, tenant_id: UUID, expected_hash: str, expected_length: int
    ) -> None:
        if path.is_symlink() or not path.is_file():
            raise BlobIntegrityError("blob target is not a regular file")
        content = self._decode_file(path, tenant_id, expected_hash)
        if len(content) != expected_length or hashlib.sha256(content).hexdigest() != expected_hash:
            raise BlobIntegrityError("existing blob failed integrity verification")

    def _encrypt(
        self,
        tenant_id: UUID,
        content_hash: str,
        content: bytes,
        media_type: str,
    ) -> bytes:
        assert self._kek is not None
        metadata = {
            "algorithm": "AES-256-GCM",
            "content_hash": content_hash,
            "key_reference": self._key_reference,
            "media_type": media_type,
            "plaintext_length": len(content),
            "tenant_id": str(tenant_id),
            "version": 1,
        }
        aad = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
        dek = AESGCM.generate_key(bit_length=256)
        content_nonce = os.urandom(12)
        wrap_nonce = os.urandom(12)
        ciphertext = AESGCM(dek).encrypt(content_nonce, content, aad)
        wrapped_dek = AESGCM(self._kek).encrypt(wrap_nonce, dek, aad)
        envelope = {
            **metadata,
            "content_nonce": base64.b64encode(content_nonce).decode("ascii"),
            "wrap_nonce": base64.b64encode(wrap_nonce).decode("ascii"),
            "wrapped_dek": base64.b64encode(wrapped_dek).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        return (
            _ENVELOPE_MAGIC + json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        )

    def _decode_file(self, path: Path, tenant_id: UUID, expected_hash: str) -> bytes:
        raw = path.read_bytes()
        if not raw.startswith(_ENVELOPE_MAGIC):
            if not self._allow_plaintext_read:
                raise BlobIntegrityError("plaintext blob is forbidden by the active data mode")
            return raw
        if self._kek is None:
            raise BlobIntegrityError("encrypted blob key is unavailable")
        try:
            envelope = json.loads(raw[len(_ENVELOPE_MAGIC) :].decode("utf-8"))
            if not isinstance(envelope, dict):
                raise ValueError
            metadata = {
                key: envelope[key]
                for key in (
                    "algorithm",
                    "content_hash",
                    "key_reference",
                    "media_type",
                    "plaintext_length",
                    "tenant_id",
                    "version",
                )
            }
            if metadata != {
                **metadata,
                "algorithm": "AES-256-GCM",
                "content_hash": expected_hash,
                "key_reference": self._key_reference,
                "tenant_id": str(tenant_id),
                "version": 1,
            }:
                raise ValueError
            aad = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
            wrap_nonce = base64.b64decode(str(envelope["wrap_nonce"]), validate=True)
            content_nonce = base64.b64decode(str(envelope["content_nonce"]), validate=True)
            wrapped_dek = base64.b64decode(str(envelope["wrapped_dek"]), validate=True)
            ciphertext = base64.b64decode(str(envelope["ciphertext"]), validate=True)
            dek = AESGCM(self._kek).decrypt(wrap_nonce, wrapped_dek, aad)
            content = AESGCM(dek).decrypt(content_nonce, ciphertext, aad)
        except (KeyError, TypeError, ValueError, InvalidTag, json.JSONDecodeError) as exc:
            raise BlobIntegrityError("encrypted blob authentication failed") from exc
        if len(content) != int(metadata["plaintext_length"]):
            raise BlobIntegrityError("encrypted blob length verification failed")
        return content

    @staticmethod
    def _erasure_proof(
        tenant_id: UUID,
        storage_uri: str,
        expected_hash: str,
        disposition: str,
    ) -> ErasureProof:
        canonical = (
            f"milai-erasure-proof-v1\n{tenant_id}\n{storage_uri}\n{expected_hash}\n{disposition}"
        ).encode()
        return ErasureProof(
            disposition=disposition,
            content_hash=expected_hash,
            storage_uri=storage_uri,
            proof_hash=hashlib.sha256(canonical).hexdigest(),
        )
