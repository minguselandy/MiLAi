"""Owned Host Note writes through the separately pinned public MCP client only.

No service request on import/construction. Unknown commits remain unresolved;
no automatic retry, implicit update, or mutation of a treatment source Note.
"""

import hashlib
import os
import threading
import types
from pathlib import Path

from v0220_evidence import read, save, sha

PUBLIC_CLIENT = Path(
    "/cra/memory/mx_memory/evidence/v0224/20260913-e0-public-completion-v1/"
    "e0-public-oauth-note-probe.py"
)


def require(value, reason):
    if not value:
        raise ValueError(reason)


class PublicNoteStore:
    def __init__(
        self,
        directory,
        *,
        origin,
        credential_path,
        credential_sha256,
        client_sha256,
        validate_binding,
        max_notes=16,
        max_http=128,
    ):
        require(origin == "http://127.0.0.1:27337", "FIXED_OWNED_NOTE_ENDPOINT_REQUIRED")
        require(type(max_notes) is int and 0 < max_notes <= 16, "BOUNDED_NOTE_WRITES_REQUIRED")
        require(type(max_http) is int and 0 < max_http <= 128, "BOUNDED_NOTE_HTTP_REQUIRED")
        self.directory, self.origin = Path(directory), origin
        require(not self.directory.exists(), "FRESH_NOTE_STORE_JOURNAL_REQUIRED")
        self.credential_path, self.credential_sha256 = Path(credential_path), credential_sha256
        self.client_sha256, self.validate_binding = client_sha256, validate_binding
        self.max_notes, self.max_http = max_notes, max_http
        self.owner = (os.getpid(), threading.get_ident())
        self.active_operation = None
        self.validate()
        raw = PUBLIC_CLIENT.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == client_sha256, "PUBLIC_CLIENT_PIN_DRIFT")
        module = types.ModuleType("v0224_pinned_public_mcp")
        module.__file__ = str(PUBLIC_CLIENT)
        # Compile only the exact bytes whose external digest was checked above.
        exec(compile(raw, str(PUBLIC_CLIENT), "exec"), module.__dict__)  # noqa: S102 - fixed reviewed source, exact external byte pin
        module.MAX_HTTP = max_http
        store = self

        class RecordedClient(module.Probe):
            def request(client, method, path, **kwargs):
                store.validate()
                count = len(client.rows)
                stem = store.directory / f"http-{count + 1:03d}"
                save(
                    stem.with_suffix(".intent.json"),
                    {
                        "method": method,
                        "path": path,
                        "body": module.redact(kwargs.get("body")),
                        "operation_id": store.active_operation,
                        "status": "PREPARED_NOT_PROOF_OF_SEND",
                    },
                )
                primary = None
                try:
                    return super().request(method, path, **kwargs)
                except BaseException as exc:
                    primary = exc
                    raise
                finally:
                    row = client.rows[-1] if len(client.rows) > count else {"status": "NOT_SENT"}
                    try:
                        save(stem.with_suffix(".observation.json"), row)
                    except BaseException as secondary:
                        if primary is None:
                            raise
                        primary.add_note(
                            "SECONDARY_NOTE_HTTP_REPORT_FAILURE: " + type(secondary).__name__
                        )

        self.client = RecordedClient(origin, self.directory, None, None)

    def unresolved(self):
        result = []
        for path in self.directory.glob("operation-*.intent.json"):
            intent = read(path)
            require(
                set(intent) == {"operation_id", "operation", "content", "content_sha256", "status"}
                and type(intent["operation_id"]) is str
                and 0 < len(intent["operation_id"]) <= 128
                and intent["operation"] == "ADD"
                and intent["status"] == "RESERVED_NOT_COMMIT_EVIDENCE"
                and type(intent["content"]) is str
                and 0 < len(intent["content"].encode()) <= 65536
                and hashlib.sha256(intent["content"].encode()).hexdigest()
                == intent["content_sha256"]
                and path.name
                == "operation-"
                + hashlib.sha256(intent["operation_id"].encode()).hexdigest()
                + ".intent.json",
                "NOTE_INTENT_JOURNAL_DRIFT",
            )
            outcome = path.with_name(path.name.replace(".intent.json", ".result.json"))
            receipt = path.with_name(path.name.replace(".intent.json", ".receipt.json"))
            failure = path.with_name(path.name.replace(".intent.json", ".failure.json"))
            if failure.exists() or not outcome.is_file() or not receipt.is_file():
                result.append(intent["operation_id"])
                continue
            response = self.committed_response(intent, read(receipt))
            require(
                read(outcome) == {"status": "COMMITTED", "response": response},
                "NOTE_RESULT_JOURNAL_DRIFT",
            )
        return result

    @staticmethod
    def committed_response(intent, receipt):
        require(
            type(receipt) is dict
            and receipt.get("commit_status") == "COMMITTED"
            and receipt.get("durable") is True
            and receipt.get("operation") == "ADD"
            and receipt.get("operation_id") == intent["operation_id"]
            and receipt.get("replayed") is False
            and type(receipt.get("version")) is int
            and receipt["version"] == 1
            and type(receipt.get("memory_id")) is str
            and bool(receipt["memory_id"])
            and receipt.get("content_digest") == "sha256:" + intent["content_sha256"],
            "ACTUAL_PUBLIC_NOTE_COMMIT_REQUIRED",
        )
        return {
            "status": "PERSISTENT_NOTE_COMMITTED",
            "version_domain": "NOTE",
            "committed": True,
            "business_effect": False,
            "task_outcome": "NOT_EVALUATED",
            "memory_id": receipt["memory_id"],
            "version": receipt["version"],
            "content_sha256": intent["content_sha256"],
        }

    def validate(self):
        require(self.owner == (os.getpid(), threading.get_ident()), "NOTE_HOST_OWNER_DRIFT")
        self.validate_binding()
        require(
            self.credential_path.is_file()
            and self.credential_path.resolve() == self.credential_path
            and not self.credential_path.stat().st_mode & 0o077
            and sha(self.credential_path) == self.credential_sha256,
            "PRIVATE_BOUND_NOTE_CREDENTIAL_REQUIRED",
        )
        require(sha(PUBLIC_CLIENT) == self.client_sha256, "PUBLIC_CLIENT_PIN_DRIFT")
        pending = self.unresolved()
        require(
            not pending or (len(pending) == 1 and pending[0] == self.active_operation),
            "NOTE_COMMIT_UNKNOWN_NO_NEW_OPERATION",
        )

    def write(self, content, *, operation_id):
        self.validate()
        require(self.active_operation is None, "ONE_NOTE_OPERATION_AT_A_TIME")
        require(
            type(content) is str and 0 < len(content.encode()) <= 65536, "PUBLIC_NOTE_CONTENT_BOUND"
        )
        require(
            type(operation_id) is str and 0 < len(operation_id) <= 128,
            "STABLE_NOTE_OPERATION_REQUIRED",
        )
        require(
            len(list(self.directory.glob("operation-*.intent.json"))) < self.max_notes,
            "NOTE_WRITE_CAP",
        )
        key = hashlib.sha256(operation_id.encode()).hexdigest()
        stem = self.directory / ("operation-" + key)
        content_sha = hashlib.sha256(content.encode()).hexdigest()
        save(
            stem.with_suffix(".intent.json"),
            {
                "operation_id": operation_id,
                "operation": "ADD",
                "content": content,
                "content_sha256": content_sha,
                "status": "RESERVED_NOT_COMMIT_EVIDENCE",
            },
        )
        self.active_operation = operation_id
        primary = None
        try:
            credential_raw = self.credential_path.read_bytes()
            require(
                hashlib.sha256(credential_raw).hexdigest() == self.credential_sha256,
                "PRIVATE_BOUND_NOTE_CREDENTIAL_REQUIRED",
            )
            token = credential_raw.decode().strip()
            # Principal/scope are server-bound to this credential, never model arguments.
            receipt = self.client.cold_call(
                token,
                "milai_note_add",
                {
                    "content": content,
                    "format": "text",
                    "tags": [],
                    "source_refs": [],
                    "operation_id": operation_id,
                },
            )
            save(stem.with_suffix(".receipt.json"), receipt)
            response = self.committed_response(
                {"operation_id": operation_id, "content_sha256": content_sha}, receipt
            )
            save(stem.with_suffix(".result.json"), {"status": "COMMITTED", "response": response})
            return response
        except BaseException as exc:
            primary = exc
            raise
        finally:
            self.active_operation = None
            if primary is not None:
                try:
                    save(
                        stem.with_suffix(".failure.json"),
                        {
                            "status": "UNRESOLVED_NO_RETRY",
                            "exception_type": type(primary).__name__,
                        },
                    )
                except BaseException as secondary:
                    primary.add_note("SECONDARY_NOTE_FAILURE_REPORT: " + type(secondary).__name__)
