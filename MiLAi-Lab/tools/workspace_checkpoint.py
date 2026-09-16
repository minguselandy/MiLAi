"""Public Working State checkpoint adapter; use only a supplied public SDK client.

The self-contained archive and its head are committed in the same State append.
Lossless compression keeps repeated receipt/history bytes out of the small head
budget without creating temporary-file dependencies. Evidence dependencies remain
declared outside the archive so Runtime disclosure checks still apply.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import tempfile
import zlib
from datetime import UTC, datetime
from pathlib import Path

NAMESPACE = "milai_rwc"
FORMAT = "milai-rwc-public-checkpoint-v1"
MAX_PAYLOAD_BYTES = 65536
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024


class CheckpointError(ValueError):
    pass


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class WorkingStateCheckpoint:
    """One trusted writer, explicit handoff, exact CAS, no write retries.

    ``client`` implements MilaiClient.get_working_state/update_working_state.
    Binding, provenance and the pending journal belong to the trusted caller.
    Unknown acknowledgements can be reconciled by a matching public head marker;
    an absent/different head is UNKNOWN, never permission to resend the operation.
    """

    def __init__(self, client, *, binding, journal, evidence_refs=(), emit=None):
        if set(binding) != {"principal_binding_digest", "project_id", "scope_type", "scope_ref"}:
            raise CheckpointError("INVALID_TRUSTED_CHECKPOINT_BINDING")
        self.client, self.binding = client, copy.deepcopy(binding)
        self.journal = Path(journal)
        self.evidence_refs = sorted(set(evidence_refs))
        self.emit = emit or (lambda _: None)

    def _event(self, event, **fields):
        self.emit({"event": event, **fields})

    def _head(self):
        head = self.client.get_working_state(self.binding)
        if head.get("payload_withheld") or head.get("warnings"):
            raise CheckpointError("CHECKPOINT_PAYLOAD_WITHHELD")
        if (
            head.get("authority") != "HOST_WORKING"
            or head.get("scope") != self.binding["scope_type"]
        ):
            raise CheckpointError("CHECKPOINT_AUTHORITY_OR_SCOPE_MISMATCH")
        if head.get("status") not in {"ACTIVE", "ABSENT"}:
            raise CheckpointError("CHECKPOINT_NOT_ACTIVE")
        if head["status"] == "ACTIVE":
            expires = datetime.fromisoformat(head["expires_at"].replace("Z", "+00:00"))
            if expires.tzinfo is None or expires <= datetime.now(UTC):
                raise CheckpointError("CHECKPOINT_EXPIRED")
        if not isinstance(head.get("payload"), dict):
            raise CheckpointError("INVALID_CHECKPOINT_PAYLOAD")
        return head

    def _pending(self):
        pending = json.loads(self.journal.read_text()) if self.journal.exists() else None
        if pending and pending.get("binding") != self.binding:
            raise CheckpointError("CHECKPOINT_JOURNAL_BINDING_MISMATCH")
        return pending

    def _assert_settled(self):
        pending = self._pending()
        if pending and pending["status"] == "UNKNOWN":
            raise CheckpointError("UNKNOWN_CHECKPOINT_WRITE_REQUIRES_RECONCILIATION")

    def save(self, artifact, *, operation_id):
        self._assert_settled()
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128:
            raise CheckpointError("INVALID_CHECKPOINT_OPERATION_ID")
        raw = canonical(artifact)
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise CheckpointError("CHECKPOINT_ARCHIVE_CAPACITY")
        head = self._head()
        payload = copy.deepcopy(head["payload"])
        previous_refs = payload.get(NAMESPACE, {}).get("evidence_refs", [])
        archive = {
            "format": FORMAT,
            "operation_id": operation_id,
            "encoding": "zlib-base64",
            "raw_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "archive": base64.b64encode(zlib.compress(raw)).decode("ascii"),
            "evidence_refs": sorted(set(previous_refs) | set(self.evidence_refs)),
        }
        payload[NAMESPACE] = archive
        if len(canonical(payload)) > MAX_PAYLOAD_BYTES:
            raise CheckpointError("PUBLIC_WORKING_STATE_CAPACITY")
        request = {
            **self.binding,
            "state_id": head["state_id"],
            "expected_version": head["version"],
            "payload": payload,
        }
        pending = {
            "status": "UNKNOWN",
            "binding": self.binding,
            "operation_id": operation_id,
            "sha256": archive["sha256"],
            "expected_version": head["version"],
        }
        # Persist uncertainty before sending; a process death must not turn into a retry.
        atomic_json(self.journal, pending)
        self._event(
            "PUBLIC_CHECKPOINT_WRITE_ATTEMPT",
            operation_id=operation_id,
            expected_version=head["version"],
            archive_bytes=len(raw),
        )
        try:
            result = self.client.update_working_state(request, operation_id=operation_id)
        except Exception as exc:
            if getattr(exc, "code", None) in {
                "STALE_WORKING_STATE",
                "OPERATION_CONFLICT",
                "EVIDENCE_REFERENCE_INVALID",
                "INVALID_REQUEST",
                "FORBIDDEN",
                "UNAUTHORIZED",
            }:
                atomic_json(self.journal, {**pending, "status": "REJECTED", "code": exc.code})
            self._event(
                "PUBLIC_CHECKPOINT_WRITE_FAILED",
                operation_id=operation_id,
                error_type=type(exc).__name__,
            )
            raise
        if result.get("payload_withheld") or result.get("warnings"):
            atomic_json(self.journal, {**pending, "status": "COMMITTED_WITHHELD"})
            raise CheckpointError("CHECKPOINT_PAYLOAD_WITHHELD")
        returned = result.get("payload", {}).get(NAMESPACE, {})
        if (
            returned.get("operation_id") != operation_id
            or returned.get("sha256") != archive["sha256"]
            or result.get("authority") != "HOST_WORKING"
            or result.get("scope") != self.binding["scope_type"]
            or result.get("status") != "ACTIVE"
            or type(result.get("version")) is not int
            or result["version"] != head["version"] + 1
        ):
            raise CheckpointError("UNCONFIRMED_CHECKPOINT_RECEIPT")
        atomic_json(self.journal, {**pending, "status": "COMMITTED", "version": result["version"]})
        self._event("PUBLIC_CHECKPOINT_SAVED", operation_id=operation_id, version=result["version"])
        return result

    def reconcile(self):
        pending = self._pending()
        if not pending or pending["status"] != "UNKNOWN":
            return pending
        if pending["binding"] != self.binding:
            raise CheckpointError("CHECKPOINT_JOURNAL_BINDING_MISMATCH")
        head = self._head()
        archive = head["payload"].get(NAMESPACE, {})
        if (
            archive.get("operation_id") != pending["operation_id"]
            or archive.get("sha256") != pending["sha256"]
            or head["version"] <= pending["expected_version"]
        ):
            raise CheckpointError("CHECKPOINT_WRITE_STILL_UNKNOWN_NO_RETRY")
        result = {**pending, "status": "COMMITTED_VISIBLE_HEAD", "version": head["version"]}
        atomic_json(self.journal, result)
        self._event(
            "PUBLIC_CHECKPOINT_RECONCILED",
            operation_id=pending["operation_id"],
            version=head["version"],
        )
        return result

    def load(self):
        self._assert_settled()
        head = self._head()
        archive = head["payload"].get(NAMESPACE)
        if archive is None:
            raise CheckpointError("PUBLIC_CHECKPOINT_ABSENT")
        if (
            archive.get("format") != FORMAT
            or archive.get("encoding") != "zlib-base64"
            or type(archive.get("raw_bytes")) is not int
            or not 0 <= archive["raw_bytes"] <= MAX_ARCHIVE_BYTES
        ):
            raise CheckpointError("INVALID_PUBLIC_CHECKPOINT_ARCHIVE")
        compressed = base64.b64decode(archive["archive"], validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, MAX_ARCHIVE_BYTES + 1)
        if (
            not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
            or len(raw) != archive["raw_bytes"]
            or hashlib.sha256(raw).hexdigest() != archive["sha256"]
        ):
            raise CheckpointError("PUBLIC_CHECKPOINT_BYTES_MISMATCH")
        artifact = json.loads(raw)
        if not isinstance(artifact, dict):
            raise CheckpointError("INVALID_PUBLIC_CHECKPOINT_ARTIFACT")
        self._event("PUBLIC_CHECKPOINT_LOADED", version=head["version"], archive_bytes=len(raw))
        return artifact
