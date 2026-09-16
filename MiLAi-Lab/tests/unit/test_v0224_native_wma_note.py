"""Public-call simulations, no network or Product behavior claims."""

import copy
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0224_native_wma_note import NoteArchive


def turn(session="s1", text="hello"):
    return dict(
        sample_id="sample",
        session_id=session,
        turn_index=0,
        role="user",
        text=text,
        attachments=[
            dict(
                caption="完整caption",
                type="image_caption",
                image_id="image",
                file_path="/public/image.png",
            )
        ],
        timestamp=None,
    )


class PublicStore:
    def __init__(self):
        self.notes, self.calls = {}, []
        self.corrupt, self.unknown = False, False

    def bound(self, principal):
        def call(tool, args):
            self.calls.append((principal, tool, copy.deepcopy(args)))
            if tool == "milai_note_add":
                if self.unknown:
                    raise TimeoutError("uncertain commit")
                memory_id = str(len(self.notes))
                content = args["content"]
                self.notes[memory_id] = (principal, content)
                return dict(
                    memory_id=memory_id,
                    version=1,
                    commit_status="COMMITTED",
                    durable=True,
                    operation="ADD",
                    operation_id=args["operation_id"],
                    replayed=False,
                    content_digest="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
                )
            if tool == "milai_note_operation_get":
                return {"status": "UNKNOWN", "operation_id": args["operation_id"]}
            assert tool == "milai_note_get"
            owner, raw = self.notes[args["memory_id"]]
            if owner != principal:
                raise PermissionError("NOTE_NOT_FOUND")
            content = raw if not self.corrupt else "!" + raw[1:]
            offset = args["offset"]
            end = min(offset + 1007, len(content))
            next_offset = end if end < len(content) else None
            return dict(
                memory_id=args["memory_id"],
                version=1,
                status="ACTIVE",
                offset=offset,
                content=content[offset:end],
                content_digest="sha256:" + hashlib.sha256(raw.encode()).hexdigest(),
                total_characters=len(content),
                total_source_refs=0,
                source_refs=[],
                source_offset=0,
                next_offset=next_offset,
                next_source_offset=None,
                source_refs_complete=True,
                content_complete=offset == 0 and next_offset is None,
                format="text",
                tags=[],
                observed_at=None,
                recorded_at="now",
                source_relation=None,
                origin="AGENT",
                authority="INFORMATIONAL",
                object_type="NOTE",
                schema_version="public-v1",
            )

        return call


def test_all_fields_utf8_chunking_and_real_paged_readback():
    store, logs = PublicStore(), []
    archive = NoteArchive("root-a", store.bound("a"), logs.append)
    turns = [turn(text="汉🙂字" * 17000)]
    result = archive.append_session("s1", turns)
    assert len(result["notes"]) > 1
    assert all(len(raw.encode("utf-8")) <= 65536 for _, raw in store.notes.values())
    assert archive.records_for_checkpoint("cp1") == turns
    reads = sum(tool == "milai_note_get" for _, tool, _ in store.calls)
    assert reads > 2 and all(row["origin"] == "HARNESS_INGESTED" for row in logs)
    value = archive.records_for_checkpoint("cp1")
    value[0]["text"] = "caller mutation"
    assert archive.records_for_checkpoint("cp1") == turns
    assert sum(tool == "milai_note_get" for _, tool, _ in store.calls) == reads
    assert archive.records_for_checkpoint("cp2") == turns
    assert sum(tool == "milai_note_get" for _, tool, _ in store.calls) == 2 * reads


def test_readback_never_substitutes_local_saved_text_and_failure_stops():
    store = PublicStore()
    archive = NoteArchive("a", store.bound("a"), lambda _: None)
    archive.append_session("s1", [turn()])
    store.corrupt = True
    with pytest.raises(ValueError, match="PUBLIC_READBACK_HASH_DRIFT"):
        archive.records_for_checkpoint("cp")
    with pytest.raises(ValueError, match="STOPPED_NO_RETRY"):
        archive.append_session("s2", [turn("s2")])


def test_roots_have_distinct_principal_calls_and_no_scope_arguments():
    store = PublicStore()
    a = NoteArchive("a", store.bound("a"), lambda _: None)
    b = NoteArchive("b", store.bound("b"), lambda _: None)
    a.append_session("s1", [turn(text="root a")])
    b.append_session("s1", [turn(text="root b")])
    assert a.records_for_checkpoint("cp")[0]["text"] == "root a"
    assert b.records_for_checkpoint("cp")[0]["text"] == "root b"
    assert all("scope" not in args and "principal" not in args for _, _, args in store.calls)
    a._call = store.bound(
        "b"
    )  # Misbound Host cannot turn another principal's ID into readable text.
    with pytest.raises(PermissionError):
        a.records_for_checkpoint("next")


def test_unknown_commit_queries_operation_once_and_never_readds():
    store, logs = PublicStore(), []
    store.unknown = True
    archive = NoteArchive("a", store.bound("a"), logs.append)
    with pytest.raises(TimeoutError):
        archive.append_session("s1", [turn()])
    assert [tool for _, tool, _ in store.calls] == ["milai_note_add", "milai_note_operation_get"]
    assert store.calls[0][2]["operation_id"] == store.calls[1][2]["operation_id"]
    with pytest.raises(ValueError, match="STOPPED_NO_RETRY"):
        archive.append_session("s1", [turn()])
    assert len(store.calls) == 2


@pytest.mark.parametrize("field", ["gold", "questions", "private", "scope"])
def test_non_normalized_fields_refused_before_call(field):
    store = PublicStore()
    archive = NoteArchive("a", store.bound("a"), lambda _: None)
    value = turn()
    value[field] = "not-ingestion-data"
    with pytest.raises(ValueError, match="ONLY_OFFICIAL_NORMALIZED_TURN_FIELDS"):
        archive.append_session("s1", [value])
    assert store.calls == []


def test_cumulative_order_and_same_checkpoint_prefix_refusal():
    store = PublicStore()
    archive = NoteArchive("a", store.bound("a"), lambda _: None)
    archive.append_session("s1", [turn()])
    archive.records_for_checkpoint("c1")
    archive.append_session("s2", [turn("s2")])
    with pytest.raises(ValueError, match="CHECKPOINT_PREFIX_CHANGED"):
        archive.records_for_checkpoint("c1")
    assert archive.records_for_checkpoint("c2") == [turn(), turn("s2")]
