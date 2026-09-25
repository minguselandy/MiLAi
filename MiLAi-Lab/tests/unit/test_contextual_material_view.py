"""The Host projection binds accurate spans and keeps corrections with old material."""

from __future__ import annotations

import hashlib
from typing import Any

from milai_lab.methods.contextual_memory.material_view import (
    MaterialView,
    serialized_material_bytes,
)
from milai_lab.methods.contextual_memory.models import Observation
from milai_lab.methods.contextual_user_memory import ContextualMemory


def source(
    ref: str, body: str, *, start: int = 0, total: str | None = None,
) -> dict[str, Any]:
    full = total if total is not None else body
    return {
        "ref": ref,
        "kind": "source",
        "content": body,
        "role": "user",
        "status": "CURRENT",
        "current_ref": ref,
        "page": {
            "start": start,
            "end": start + len(body),
            "total_chars": len(full),
            "complete": body == full,
            "content_sha256": hashlib.sha256(full.encode()).hexdigest(),
        },
    }


def test_response_dedup_preserves_exact_events_and_overlapping_ranges() -> None:
    first_ref = "user/source:first"
    second_ref = "user/source:second"
    result = {
        "materials": [
            source(first_ref, "abcde", total="abcdefghij"),
            source(first_ref, "defgh", start=3, total="abcdefghij"),
            source(second_ref, "abcde"),
        ]
    }
    view = MaterialView("task")
    projected = view.project(result)
    rows = projected["materials"]
    assert len(rows) == 3
    assert [row["content"] for row in rows] == ["abcde", "fgh", "abcde"]
    assert [view.binding(row["ref"]).spans for row in rows] == [
        ((0, 5),),
        ((5, 8),),
        ((0, 5),),
    ]
    assert view.resolve_ref(rows[0]["ref"]) == view.resolve_ref(rows[1]["ref"])
    assert view.resolve_ref(rows[0]["ref"]) != view.resolve_ref(rows[2]["ref"])


def test_common_status_and_required_correction_with_h2_only_recorded_extra() -> None:
    old = source("user/source:old", "Old plan")
    old.update(status="SUPERSEDED", current_ref="user/source:new")
    replacement = source("user/source:new", "Corrected plan")
    replacement["relation"] = "source_replacement"
    revised = {
        "ref": "user/card:one@2",
        "kind": "interpretation",
        "text": "Current view",
        "status": "CURRENT",
        "current_ref": "user/card:one@2",
        "relation": "revised_interpretation",
        "retired": True,
    }
    revised_ref = str(revised["ref"])
    provenance = source("user/source:origin", "Original evidence")
    provenance["relation"] = "source_provenance"
    old["associated_materials"] = [replacement, revised, provenance]

    ordinary = MaterialView("ordinary")
    common = ordinary.project(old, linked=False)
    root = common["materials"][0]
    assert root["status"] == "SUPERSEDED"
    assert ordinary.resolve_ref(root["current_ref"]) == replacement["ref"]
    assert {ordinary.resolve_ref(row["ref"]): row for row in common["materials"]}[
        replacement["ref"]
    ]["content"] == "Corrected plan"
    assert {row["relation"]: row["expanded"] for row in root["related"]} == {
        "source_replacement": True,
        "revised_interpretation": True,
        "source_provenance": False,
    }
    assert {ordinary.resolve_ref(row["ref"]): row for row in common["materials"]}[
        revised_ref
    ]["text"] == "Current view"
    assert {ordinary.resolve_ref(row["ref"]): row for row in common["materials"]}[
        revised_ref
    ]["retired"] is True
    linked = MaterialView("h2")
    extra = linked.project(old, linked=True)
    assert {linked.resolve_ref(row["ref"]): row for row in extra["materials"]}[revised_ref][
        "text"
    ] == "Current view"
    assert "Original evidence" not in str(extra)


def test_partial_current_revision_never_leaves_old_source_body_alone() -> None:
    old = source("user/source:old", "Outdated requirement")
    revised = {
        "ref": "user/card:one@2", "kind": "interpretation",
        "text": "Current requirement " * 100,
        "status": "CURRENT", "relation": "revised_interpretation",
    }
    old["associated_materials"] = [revised]
    projected = MaterialView("small").project(old, max_bytes=650)
    assert projected.get("status") == "INSUFFICIENT_MATERIAL_BUDGET" or (
        "content" not in projected["materials"][0]
        and projected["materials"][0]["correction_status"] == "REQUIRES_EXPANSION"
    )


def test_explicit_source_read_keeps_optional_prior_unexpanded() -> None:
    current = {
        "ref": "user/card:one@2", "kind": "interpretation", "text": "Current decision",
        "status": "CURRENT", "sources": [source("user/source:basis", "Basis body")],
        "associated_materials": [{
            "ref": "user/card:one@1", "kind": "interpretation", "text": "Prior decision",
            "status": "SUPERSEDED", "relation": "prior_interpretation",
        }],
    }
    view = MaterialView("task")
    projected = view.project(current, include_sources=True)
    assert [row.get("content", row.get("text")) for row in projected["materials"]] == [
        "Current decision", "Basis body",
    ]
    assert {link["relation"]: link["expanded"]
            for link in projected["materials"][0]["related"]} == {
        "prior_interpretation": False, "source_provenance": True,
    }
    assert view.binding(projected["materials"][1]["ref"]).spans == ((0, 10),)


def test_current_target_body_and_old_basis_relations_have_distinct_delivery() -> None:
    text = "Current outcome"
    target = {
        "ref": "user/card:one@2", "kind": "interpretation", "text": text,
        "status": "CURRENT", "source_refs": ["user/source:old"],
        "dependencies": ["user/card:premise@1"],
        "dependency_status": [{
            "observed_ref": "user/card:premise@1",
            "current_ref": "user/card:premise@1", "status": "CURRENT",
        }],
        "page": {"start": 0, "end": len(text), "total_chars": len(text),
                 "complete": True, "content_sha256": hashlib.sha256(text.encode()).hexdigest()},
    }
    view = MaterialView("target")
    row = view.project(target)["materials"][0]
    assert row["body_delivery"] == "full"
    assert view.binding(row["ref"]).spans == ((0, len(text)),)
    assert row["basis_relation_use"] == "existing_lineage_not_body_read"
    assert view.binding(row["source_refs"][0]).spans == ()
    assert view.binding(row["dependency_refs"][0]).spans == ()
    assert row["dependency_status"][0]["status"] == "CURRENT"
    partial = dict(target)
    partial["text"] = text[:5]
    partial["page"] = {**target["page"], "end": 5, "complete": False}
    assert MaterialView("partial").project(partial)["materials"][0]["body_delivery"] == "partial"


def test_partial_budget_and_alias_lifetime() -> None:
    ref = "user/source:large"
    packet = source(ref, "x" * 1000)
    view = MaterialView("task")
    assert view.project(packet, max_bytes=4)["status"] == "INSUFFICIENT_MATERIAL_BUDGET"
    assert set(view._bindings) == {"unknown"}
    projected = view.project(packet, max_bytes=450)
    assert serialized_material_bytes(projected) <= 450
    row = projected["materials"][0]
    assert row["expand_ref"] == row["ref"]
    assert view.binding(row["ref"]).spans == ((0, len(row["content"])),)
    assert len(row["content"]) < 1000
    later = view.project(packet, max_bytes=16000)["materials"][0]["ref"]
    assert later != row["ref"]
    assert view.binding(row["ref"]).spans != view.binding(later).spans
    view.revoke({row["ref"]})
    try:
        view.resolve_ref(row["ref"])
    except ValueError as exc:
        assert str(exc) == "MATERIAL_REF_NOT_DELIVERED"
    else:
        raise AssertionError("revoked alias remained usable")


def test_preview_does_not_publish_refs_and_write_receipt_uses_same_binding_table() -> None:
    view = MaterialView("task")
    record = {
        "ref": "user/card:one@2",
        "kind": "interpretation",
        "text": "Updated view",
        "status": "SAVED",
        "current_ref": "user/card:one@2",
        "source_refs": ["user/source:a"],
    }
    preview = view.preview(record)
    assert preview["materials"][0]["text"] == "Updated view"
    assert set(view._bindings) == {"unknown"}
    write = view.project_write(
        {
            "operation_id": "op1",
            "decision": "COMMITTED",
            "completion": "COMPLETE",
            "source": {"status": "RETAINED", "ref": "user/source:a"},
            "record": record,
            "changeset": {
                "groups": [
                    {
                        "status": "APPLIED",
                        "metrics": {"internal": "x"},
                        "operations": [
                            {"op": "claim", "status": "SAVED", "ref": "user/card:one@2"}
                        ],
                    }
                ],
                "aliases": {"new:c": "user/card:one@2"},
                "pending_refs": [],
            },
            "cleanup_effects": {"internal": "do not deliver"},
        }
    )
    material = write["record"]["material"]
    row = material["materials"][0]
    assert write["record"]["status"] == "SAVED"
    assert row["status"] == "CURRENT"
    assert view.binding(row["ref"]).spans == ((0, len("Updated view")),)
    assert view.resolve_ref(write["record"]["ref"]) == record["ref"]
    assert view.resolve_ref(write["source"]["ref"]) == "user/source:a"
    assert write["changeset"]["aliases"]["new:c"] == row["ref"]
    assert "metrics" not in str(write) and "cleanup_effects" not in str(write)
    assert write["operation_id"] == "op1" and write["completion"] == "COMPLETE"
    old_version = {**record, "status": "REUSED", "current_ref": "user/card:one@3"}
    superseded = view.project_write({"record": old_version})["record"]
    assert superseded["status"] == "REUSED"
    assert superseded["material"]["materials"][0]["status"] == "SUPERSEDED"
    rejected = view.project_write({"status": "ERROR", "decision": "REJECTED",
                                   "error": "REVISION_REQUIRES_READ_TARGET"})
    assert rejected["error"] == "REVISION_REQUIRES_READ_TARGET"
    unsafe = view.project_write({"status": "ERROR", "error": "hidden user/source:ref"})
    assert unsafe["error"] == "MEMORY_OPERATION_ERROR"


def test_ordinary_projector_recovers_recorded_time_limits() -> None:
    memory = ContextualMemory(
        "alice",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        state_policy="off",
    )
    memory.start_task("one", "When did this apply?")
    original = memory.publish(
        Observation("e", "Earlier preference", "user", "fixture", actor_ref="current_user")
    )
    record = memory.save(
        content="Earlier preference", source_ref=original, valid_until="2024-12-31"
    )["record"]["ref"]
    internal = memory.read(record, include_sources=False)
    assert "valid_until" not in internal  # v7 ordinary internal view elided it.
    projection = MaterialView("task", memory).project(internal)
    row = projection["materials"][0]
    assert row["valid_until"] == "2024-12-31"
    assert row["structured_scope"] == "DECLARED"


def test_source_speaker_catalogue_requires_delivered_body_and_about_is_readable() -> None:
    memory = ContextualMemory(
        "alice",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        state_policy="off",
    )
    ref = memory.publish(
        Observation(
            "event",
            "I published an article",
            "assistant",
            "fixture",
            "session-1",
        )
    )
    record_ref = memory.save(content="Article author", source_ref=ref)["record"]["ref"]
    view = MaterialView("task", memory)
    original = source(ref, "I published an article")
    original.update(role="assistant", session_id="session-1")
    assert [row["ref"] for row in view.subject_catalogue()] == ["unknown"]
    view.preview(original)
    assert [row["ref"] for row in view.subject_catalogue()] == ["unknown"]
    projected = view.project(original)
    row = projected["materials"][0]
    assert row["source_sequence"] == memory.source_sequence[ref]
    assert row["session_id"] == "session-1"
    speaker = row["speaker_ref"]
    assert speaker.startswith("p")
    assert view.binding(speaker).exact_ref == f"speaker:{ref}"
    assert view.subject_catalogue()[-1] == {
        "ref": speaker,
        "kind": "source_speaker",
        "source_ref": row["ref"],
        "source_role": "assistant",
    }
    interpretation = {
        "ref": record_ref,
        "kind": "interpretation",
        "text": "Article author",
        "status": "CURRENT",
        "author": "host",
        "source_refs": [ref],
        "about": {"kind": "source_speaker", "source_ref": ref, "source_role": "assistant"},
    }
    related = view.project(interpretation)["materials"][0]
    assert related["about_ref"] == speaker
    assert related["about"] == {
        "kind": "source_speaker",
        "source_ref": related["source_refs"][0],
        "source_role": "assistant",
    }
    assert related["author"] == "host"
    assert related["source_roles"] == {related["source_refs"][0]: "assistant"}
    combined = view.project({"materials": [interpretation, original]})["materials"]
    assert combined[0]["source_refs"] == [combined[1]["ref"]]
    assert combined[0]["source_roles"] == {combined[1]["ref"]: "assistant"}
    assert view.resolve_ref(combined[1]["ref"]) == ref
    assert "not current world state" in projected["status_meaning"]
    for index, text in enumerate(("I used to cycle.", "My friend now swims.")):
        user_ref = memory.publish(
            Observation(str(index), text, "user", "fixture", actor_ref="current_user")
        )
        user_row = view.project(memory.read(user_ref))["materials"][0]
        assert user_row["speaker_ref"] == "u0"
    assert [row["ref"] for row in view.subject_catalogue()] == ["u0", "unknown", speaker]
    other = memory.publish(
        Observation("other", "I made a film.", "assistant", "fixture"),
        sequence=memory.source_sequence[ref],
    )
    fresh = MaterialView("another-task", memory)
    other_speaker = fresh.project(memory.read(other))["materials"][0]["speaker_ref"]
    assert other_speaker != speaker
    assert fresh.project(original)["materials"][0]["speaker_ref"] == speaker
