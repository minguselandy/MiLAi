"""Harness-ingested ordinary Notes; public reads, no model-selected scope or gold."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid

TURN_FIELDS = frozenset(
    {"sample_id", "session_id", "turn_index", "role", "text", "attachments", "timestamp"}
)
ATTACHMENT_FIELDS = frozenset({"caption", "type", "image_id", "file_path"})
MAX_NOTE_BYTES = 65536
ORIGIN = "HARNESS_INGESTED"


def require(ok, why):
    if not ok:
        raise ValueError(why)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
        "utf-8"
    )


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def validate_turns(session_id, turns):
    require(type(turns) is list, "NORMALIZED_TURN_LIST_REQUIRED")
    for turn in turns:
        require(
            type(turn) is dict and set(turn) == TURN_FIELDS, "ONLY_OFFICIAL_NORMALIZED_TURN_FIELDS"
        )
        require(
            all(type(turn[k]) is str for k in ("sample_id", "session_id", "role", "text")),
            "NORMALIZED_TURN_STRING_FIELDS",
        )
        require(
            turn["session_id"] == session_id and type(turn["turn_index"]) is int,
            "EXACT_SESSION_AND_TURN_INDEX",
        )
        require(turn["timestamp"] is None or type(turn["timestamp"]) is str, "NORMALIZED_TIMESTAMP")
        require(type(turn["attachments"]) in (list, tuple), "OFFICIAL_ATTACHMENT_SEQUENCE")
        for item in turn["attachments"]:
            require(
                type(item) is dict and set(item) == ATTACHMENT_FIELDS,
                "ONLY_OFFICIAL_ATTACHMENT_FIELDS",
            )
            require(
                type(item["caption"]) is str
                and type(item["type"]) is str
                and all(item[k] is None or type(item[k]) is str for k in ("image_id", "file_path")),
                "OFFICIAL_ATTACHMENT_VALUES",
            )


def chunks(raw):
    """Split only at UTF-8 character boundaries; rejoining is byte-exact JSON."""
    offset = 0
    while offset < len(raw):
        end = min(offset + MAX_NOTE_BYTES, len(raw))
        while end < len(raw) and raw[end] & 0xC0 == 0x80:
            end -= 1
        require(end > offset, "UTF8_CHUNK_MUST_PROGRESS")
        yield raw[offset:end].decode("utf-8")
        offset = end


class NoteArchive:
    """One root's principal-bound call supplied by the trusted parent Host.

    No credential, scope argument, gold/question data or Product private API is
    accepted. A checkpoint cache contains only immutable bytes actually read via
    Note GET; it is not a cold-recovery or autonomous-save claim.
    """

    def __init__(self, root_id, call, record):
        require(type(root_id) is str and bool(root_id), "EXACT_ROOT_ID_REQUIRED")
        require(callable(call) and callable(record), "BOUND_PUBLIC_CALL_AND_RAW_RECORD_REQUIRED")
        self._root_id, self._call, self._record = root_id, call, record
        self._owner = (os.getpid(), threading.get_ident())
        self._sessions = []
        self._stopped = False
        self._checkpoint = None
        self._checkpoint_prefix = None
        self._checkpoint_bytes = None

    def _active(self):
        require(
            self._owner == (os.getpid(), threading.get_ident()), "SAME_ROOT_HOST_PROCESS_REQUIRED"
        )
        require(not self._stopped, "NOTE_ARCHIVE_STOPPED_NO_RETRY")

    def _invoke(self, tool, arguments):
        self._record(
            {
                "origin": ORIGIN,
                "root_id": self._root_id,
                "event": "PUBLIC_NOTE_REQUEST",
                "tool": tool,
                "arguments": json.loads(encoded(arguments)),
            }
        )
        # The caller receives a separate object, so it cannot mutate our retained descriptors.
        result = self._call(tool, json.loads(encoded(arguments)))
        require(type(result) is dict, "PUBLIC_NOTE_DICT_REQUIRED")
        result = json.loads(encoded(result))
        self._record(
            {
                "origin": ORIGIN,
                "root_id": self._root_id,
                "event": "PUBLIC_NOTE_RESPONSE",
                "tool": tool,
                "result": result,
            }
        )
        return result

    def append_session(self, session_id, turns):
        self._active()
        require(type(session_id) is str and bool(session_id), "EXACT_SESSION_ID_REQUIRED")
        require(
            not any(s["session_id"] == session_id for s in self._sessions),
            "SESSION_ALREADY_APPENDED",
        )
        validate_turns(session_id, turns)
        raw = encoded(turns)
        descriptor = {
            "session_id": session_id,
            "turn_count": len(turns),
            "digest": digest(raw),
            "bytes": len(raw),
            "notes": [],
        }
        for ordinal, content in enumerate(chunks(raw)):
            operation_id = uuid.uuid4().hex
            arguments = {
                "content": content,
                "format": "text",
                "tags": [],
                "operation_id": operation_id,
                "source_refs": [],
            }
            try:
                receipt = self._invoke("milai_note_add", arguments)
                require(
                    receipt.get("commit_status") == "COMMITTED"
                    and receipt.get("durable") is True
                    and receipt.get("operation") == "ADD"
                    and receipt.get("operation_id") == operation_id
                    and receipt.get("replayed") is False
                    and type(receipt.get("version")) is int
                    and receipt["version"] == 1
                    and type(receipt.get("memory_id")) is str
                    and bool(receipt["memory_id"])
                    and receipt.get("content_digest") == digest(content.encode("utf-8")),
                    "ACTUAL_DURABLE_NOTE_ADD_RECEIPT_REQUIRED",
                )
            except BaseException as primary:
                self._stopped = True
                # One public outcome query even if the request outcome is unknown;
                # a later COMMITTED observation never authorizes retry or continuation.
                try:
                    self._invoke("milai_note_operation_get", {"operation_id": operation_id})
                except BaseException as secondary:
                    primary.add_note("SECONDARY_NOTE_OPERATION_GET: " + type(secondary).__name__)
                raise
            descriptor["notes"].append(
                {"ordinal": ordinal, "receipt": receipt, "bytes": len(content.encode("utf-8"))}
            )
        self._sessions.append(descriptor)
        self._record(
            {
                "origin": ORIGIN,
                "root_id": self._root_id,
                "event": "SESSION_NOTES_COMMITTED",
                "session": json.loads(encoded(descriptor)),
            }
        )
        return json.loads(encoded(descriptor))

    def _read_note(self, note):
        receipt = note["receipt"]
        offset, pieces, metadata = 0, [], None
        while True:
            page = self._invoke(
                "milai_note_get",
                {
                    "memory_id": receipt["memory_id"],
                    "version": receipt["version"],
                    "offset": offset,
                    "length": 4096,
                    "source_offset": 0,
                    "source_limit": 8,
                },
            )
            require(
                page.get("memory_id") == receipt["memory_id"]
                and page.get("version") == receipt["version"]
                and page.get("status") == "ACTIVE"
                and page.get("offset") == offset,
                "NOTE_ID_VERSION_STATUS_OFFSET_DRIFT",
            )
            current = {
                k: page[k]
                for k in (
                    "content_digest",
                    "version",
                    "format",
                    "tags",
                    "observed_at",
                    "recorded_at",
                    "source_relation",
                    "origin",
                    "authority",
                    "object_type",
                    "schema_version",
                    "total_characters",
                    "total_source_refs",
                )
            }
            if metadata is None:
                metadata = current
            require(
                current == metadata
                and page["content_digest"] == receipt["content_digest"]
                and page["format"] == "text"
                and page["tags"] == [],
                "NOTE_METADATA_OR_DIGEST_DRIFT",
            )
            require(
                type(page.get("content")) is str
                and type(page["total_characters"]) is int
                and page["total_characters"] >= 0
                and page["total_source_refs"] == 0
                and page.get("source_refs") == []
                and page.get("source_offset") == 0
                and page.get("next_source_offset") is None
                and page.get("source_refs_complete") is True,
                "COMPLETE_EXPECTED_EMPTY_NOTE_SOURCES_REQUIRED",
            )
            end = offset + len(page["content"])
            require(end <= page["total_characters"], "NOTE_PAGE_OVERRUN")
            next_offset = page.get("next_offset")
            require(
                page.get("content_complete") is (offset == 0 and next_offset is None),
                "NOTE_COMPLETENESS_FLAG_DRIFT",
            )
            pieces.append(page["content"])
            if next_offset is None:
                require(end == page["total_characters"], "NOTE_TRUNCATED_FINAL_PAGE")
                break
            require(
                type(next_offset) is int and next_offset == end and next_offset > offset,
                "NOTE_PAGE_MUST_PROGRESS_WITHOUT_GAP",
            )
            offset = next_offset
        raw = "".join(pieces).encode("utf-8")
        require(
            len(raw) == note["bytes"] and digest(raw) == receipt["content_digest"],
            "PUBLIC_READBACK_HASH_DRIFT",
        )
        return raw

    def records_for_checkpoint(self, checkpoint_id):
        self._active()
        require(type(checkpoint_id) is str and bool(checkpoint_id), "EXACT_CHECKPOINT_ID_REQUIRED")
        prefix = tuple((s["session_id"], s["digest"]) for s in self._sessions)
        if checkpoint_id == self._checkpoint:
            require(prefix == self._checkpoint_prefix, "CHECKPOINT_PREFIX_CHANGED")
            return json.loads(self._checkpoint_bytes)
        records = []
        try:
            for session in self._sessions:
                raw = b"".join(self._read_note(note) for note in session["notes"])
                require(
                    len(raw) == session["bytes"] and digest(raw) == session["digest"],
                    "SESSION_READBACK_SEQUENCE_DRIFT",
                )
                turns = json.loads(raw)
                validate_turns(session["session_id"], turns)
                require(len(turns) == session["turn_count"], "COMPLETE_SESSION_TURNS_REQUIRED")
                records.extend(turns)
            self._checkpoint_bytes = encoded(records)
            self._checkpoint, self._checkpoint_prefix = checkpoint_id, prefix
            return json.loads(self._checkpoint_bytes)
        except BaseException:
            self._stopped = True
            raise
