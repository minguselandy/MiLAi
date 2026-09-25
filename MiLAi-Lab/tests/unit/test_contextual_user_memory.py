from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from milai_lab.methods.contextual_memory.deletion import DeletionLedger
from milai_lab.methods.contextual_memory.material_view import (
    MaterialView,
    serialized_material_bytes,
)
from milai_lab.methods.contextual_memory.operations import TaskEnvelope
from milai_lab.methods.contextual_memory.write_contract import ordinary_save_schema
from milai_lab.methods.contextual_user_memory import (
    TOOLS,
    ContextualMemory,
    Observation,
    receipt_outcome,
)


def embed(texts: list[str]) -> list[list[float]]:
    return [[0.0, 1.0] if "client" in text else [1.0, 0.0] for text in texts]


def memory(user: str = "alice", ledger: DeletionLedger | None = None) -> ContextualMemory:
    result = ContextualMemory(
        user,
        host_id="host",
        embed=embed,
        embedding_dimension=2,
        deletion_ledger=ledger,
        state_policy="forced_legacy",
    )
    result.start_task("task-1", "presentation")
    return result


def trusted_forget(mem: ContextualMemory, ledger: DeletionLedger, refs: list[str]) -> None:
    envelope = TaskEnvelope(
        mem.user_id,
        mem.state.task_id,
        "lifecycle",
        frozenset({"delete"}),
        tuple(refs),
        "delete-1",
        "delete_only",
        scope_id=str(ledger.path.parent.resolve()),
    )
    mem.bind_envelope(envelope)
    mem.forget(refs, envelope=envelope)


def test_source_identity_revision_and_actual_author() -> None:
    mem = memory()
    event = Observation("1", "The user says prefer details", "assistant", "fixture")
    source = mem.publish(event)
    assert mem.publish(event) == source
    other = mem.publish(Observation("2", event.content, "assistant", "fixture"))
    assert other != source
    with pytest.raises(ValueError, match="SOURCE_IDENTITY"):
        mem.publish(Observation("1", "rewritten", "user", "fixture"))
    first = mem.save(content="prefers detail", source_ref=source)["record"]["ref"]
    second = mem.save(target_ref=first, content="detail in technical settings", context="technical")
    current = second["record"]["ref"]
    assert current != first
    assert mem.read(first)["status"] == "SUPERSEDED"
    assert mem.read(source)["role"] == "assistant"
    assert mem.read(source)["content"] == event.content
    assert mem.read(current)["author"] == "host"
    assert mem.save(target_ref=first, content="stale")["record"]["status"] == "VERSION_CONFLICT"
    assert mem.dispatch("memory_save", {"content": "fake", "author": "user"})["status"] == "ERROR"


def test_internal_read_does_not_authorize_record_or_recursive_source() -> None:
    mem = memory()
    source = mem.publish(Observation("read-source", "Exact source text", "user", "fixture"))
    record = mem.save(content="Exact claim", source_ref=source)["record"]["ref"]
    mem.start_task("task-2", "Later question")

    internal = mem.read(record, _visible=False)
    assert internal["sources"][0]["ref"] == source
    assert not mem.seen and not mem.visible_source_ranges

    mem.read(record)
    assert {record, source} <= mem.seen
    assert mem.visible_source_ranges[source] == {(0, len("Exact source text"))}


def test_state_prose_stays_out_of_query_and_revision_invalidates_dependency() -> None:
    mem = memory()
    technical = mem.save(content="technical detailed presentation")["record"]["ref"]
    client = mem.save(content="client concise presentation", context="client meeting")["record"][
        "ref"
    ]
    derived = mem.save(content="prepare deck", dependencies=[technical])["record"]["ref"]
    mem.update_state(context="client meeting", intentions=[client])
    result = mem.search("presentation", limit=1)
    assert result["materials"][0]["ref"] == technical
    assert result["query"] == "presentation"
    assert result["query_projection"]["sources"]["query"] == "tool_argument"
    changed = mem.save(target_ref=technical, content="technical diagrams only")["record"]["ref"]
    assert mem.read(derived)["dependency_status"] == [
        {
            "observed_ref": technical,
            "current_ref": changed,
            "status": "NEEDS_REVISION",
        }
    ]
    mem.update_state(context="technical", intentions=[changed])
    result = mem.search("technical", limit=1)
    assert result["materials"][0]["ref"] == changed
    assert technical not in mem.vectors


def test_source_expansion_deduplicates_and_preserves_whole_units() -> None:
    mem = memory()
    ref = mem.publish(
        Observation("1", "long-term detail; client meetings are an exception", "user", "x")
    )
    one = mem.save(content="detail normally", source_ref=ref)["record"]["ref"]
    two = mem.save(content="concise in client meetings", source_ref=ref)["record"]["ref"]
    mem.update_state(intentions=[one, two])
    result = mem.search("presentation")
    assert len([item for item in result["materials"] if item["ref"] == ref]) == 1
    assert result["independent_source_refs"] == [ref]
    assert "exception" in next(
        item["content"] for item in result["materials"] if item["ref"] == ref
    )
    small = mem.search("presentation", max_bytes=1)
    assert small["materials"] == []


def test_forget_removes_old_versions_and_dependent_interpretations(tmp_path: Path) -> None:
    ledger = DeletionLedger(tmp_path / "deletions.json", "alice")
    mem = memory(ledger=ledger)
    source = mem.publish(Observation("1", "sensitive detail", "user", "x"))
    first = mem.save(content="sensitive understanding", source_ref=source)["record"]["ref"]
    dependent = mem.save(content="derived secret", dependencies=[first])["record"]["ref"]
    mem.save(target_ref=first, content="revised secret", source_refs=[])
    mem.update_state(context="sensitive detail", intentions=[dependent])
    trusted_forget(mem, ledger, [source])
    checkpoint = json.dumps(mem.checkpoint())
    assert "sensitive" not in checkpoint and "secret" not in checkpoint
    assert not mem.workspace.cards
    assert mem.publish(Observation("1", "sensitive detail", "user", "x")) == source
    assert source not in mem.sources


def test_forget_rejects_older_handoff_without_restoring_text_or_task_objects(
    tmp_path: Path,
) -> None:
    ledger = DeletionLedger(tmp_path / "deletions.json", "alice")
    mem = memory(ledger=ledger)
    source = mem.publish(Observation("1", "private source", "user", "x"))
    card = mem.save(content="private note", source_ref=source, persistence="task")["record"]["ref"]
    mem.update_state(context="private context", intentions=[card])
    old_handoff = mem.handoff()
    trusted_forget(mem, ledger, [source])
    with pytest.raises(ValueError, match="HANDOFF_PRECEDES_FORGET"):
        mem.start_task("later", "question", handoff=old_handoff)
    assert source not in mem.sources and not mem.workspace.cards
    assert mem.state.context == ""
    restored = ContextualMemory.restore(
        mem.checkpoint(),
        user_id="alice",
        embed=embed,
        deletion_ledger=ledger,
    )
    with pytest.raises(ValueError, match="HANDOFF_PRECEDES_FORGET"):
        restored.start_task("later", "question", handoff=old_handoff)
    assert "private" not in json.dumps(restored.checkpoint())


def test_checkpoint_new_process_handoff_and_user_isolation(tmp_path) -> None:
    mem = memory()
    retained = mem.publish(Observation("1", "recorded fact", "user", "x"))
    ephemeral = mem.publish(Observation("2", "unretained fact", "user", "x"))
    card = mem.save(content="lasting understanding", source_ref=retained)["record"]["ref"]
    mem.save(content="task-only understanding", persistence="task")
    mem.update_state(context="technical", intentions=[card])
    path = tmp_path / "memory.json"
    path.write_text(json.dumps(mem.checkpoint()))
    assert ephemeral not in path.read_text()
    mem.start_task("task-2", "different question")
    assert ephemeral not in mem.sources
    assert "task-only understanding" not in json.dumps(mem.checkpoint(include_task=False))
    script = """
import json,sys
from milai_lab.methods.contextual_user_memory import ContextualMemory
m=ContextualMemory.restore(json.load(open(sys.argv[1])),
    user_id="alice",embed=lambda xs:[[1,0] for x in xs])
m.start_task("task-2","different question",handoff=m.handoff())
print(json.dumps({"task":m.state.task_id,"question":m.workspace.frame.question,"read":m.read(sys.argv[2])}))
"""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script, str(path), card],
        capture_output=True,
        text=True,
        check=True,
    )
    restored = json.loads(result.stdout)
    assert restored["task"] == "task-2"
    assert restored["question"] == "different question"
    assert restored["read"]["sources"][0]["content"] == "recorded fact"
    with pytest.raises(ValueError, match="CHECKPOINT_USER"):
        ContextualMemory.restore(mem.checkpoint(), user_id="bob", embed=embed)
    assert memory("bob").dispatch("memory_read", {"ref": card})["status"] == "ERROR"


def test_source_save_contract_error_has_no_partial_retention() -> None:
    mem = memory()
    source = mem.publish(Observation("1", "raw text", "tool", "x"))
    result = mem.dispatch(
        "memory_save",
        {
            "op": "CREATE",
            "certainty": "explicit",
            "about_ref": "unresolved",
            "content": "note",
            "source_refs": ["unpublished"],
        },
    )
    assert result["status"] == "ERROR"
    assert source not in mem.retained
    outcome = receipt_outcome("memory_save", result)
    assert outcome.completion == "failed"
    assert outcome.succeeded == ()
    assert outcome.usable_refs == ()
    assert not outcome.ok
    assert mem.dispatch("memory_read", {})["status"] == "ERROR"
    mem.dispatch("memory_save", {"op": "RETAIN_SOURCE", "source_ref": source})
    rejected = mem.dispatch(
        "memory_save",
        {
            "op": "CREATE",
            "certainty": "explicit",
            "about_ref": "unresolved",
            "content": "note",
            "source_refs": ["unpublished"],
        },
    )
    assert rejected["decision"] == "REJECTED"
    assert receipt_outcome("memory_save", rejected).succeeded == ()


def test_explicit_no_change_and_write_operation_shapes() -> None:
    mem = memory()
    before = mem.checkpoint()
    result = mem.dispatch("memory_save", {"op": "NO_CHANGE"})
    assert result["decision"] == "NO_CHANGE"
    assert receipt_outcome("memory_save", result).completion == "complete"
    assert receipt_outcome("memory_save", result).operation_id.startswith("save:")
    assert mem.checkpoint() == before
    empty_changeset = mem.dispatch("memory_save", {"changeset": {"groups": []}})
    assert empty_changeset["decision"] == "NO_CHANGE"
    assert empty_changeset["operation_id"] != result["operation_id"]
    assert empty_changeset["memory_changes"] == []
    assert receipt_outcome("memory_save", empty_changeset).succeeded == ()
    assert mem.checkpoint() == before
    rejected = mem.dispatch(
        "memory_save", {"op": "REVISE", "certainty": "explicit", "content": "No target"}
    )
    assert rejected["status"] == "ERROR"
    assert receipt_outcome("memory_save", rejected).operation_id.startswith("save:")
    assert rejected["operation_id"] not in {
        result["operation_id"],
        empty_changeset["operation_id"],
    }
    forged = mem.dispatch("memory_save", {"op": "NO_CHANGE", "operation_id": "model-id"})
    assert forged["status"] == "ERROR"
    assert forged["operation_id"] != "model-id"
    assert (
        mem.dispatch(
            "memory_save",
            {"op": "CREATE", "certainty": "explicit", "content": "New", "target_ref": "invented"},
        )["status"]
        == "ERROR"
    )
    assert mem.checkpoint() == before
    committed = mem.dispatch(
        "memory_save",
        {
            "op": "CREATE",
            "certainty": "explicit",
            "content": "Author's working note",
            "about_ref": "unresolved",
            "source_refs": [],
        },
    )
    assert receipt_outcome("memory_save", committed).operation_id.startswith("save:")
    assert receipt_outcome("memory_save", committed).decision == "COMMITTED"


def test_subject_identity_author_source_role_and_unbased_user_write() -> None:
    mem = memory()
    assistant_source = mem.publish(
        Observation(
            "assistant",
            "I published a paper",
            "assistant",
            "x",
        )
    )
    user_source = mem.publish(Observation("user", "I volunteer locally", "user", "x"))
    assistant = mem.dispatch(
        "memory_save",
        {
            "op": "CREATE",
            "certainty": "explicit",
            "content": "Speaker published a paper",
            "about_ref": f"speaker:{assistant_source}",
            "source_refs": [assistant_source],
            "subject": "publication",
        },
    )
    view = mem.read(assistant["record"]["ref"])
    assert view["author"] == "host"
    assert view["subject"] == "publication"
    assert view["about"] == {
        "kind": "source_speaker",
        "source_ref": assistant_source,
        "source_role": "assistant",
    }
    assert view["about_ref"] == f"speaker:{assistant_source}"
    before = mem.checkpoint()
    wrong_anchor = mem.dispatch(
        "memory_save",
        {
            "op": "CREATE",
            "certainty": "explicit",
            "content": "Uncited speaker",
            "about_ref": f"speaker:{assistant_source}",
            "source_refs": [user_source],
        },
    )
    no_basis = mem.dispatch(
        "memory_save",
        {
            "op": "CREATE",
            "certainty": "explicit",
            "content": "User prefers this",
            "about_ref": "current_user",
            "source_refs": [],
        },
    )
    assert wrong_anchor["decision"] == no_basis["decision"] == "REJECTED"
    assert wrong_anchor["error"] == "ABOUT_SOURCE_NOT_CITED"
    assert no_basis["error"] == "DURABLE_USER_FACT_REQUIRES_SOURCE"
    assistant_only = mem.dispatch(
        "memory_save",
        {
            "op": "CREATE",
            "certainty": "explicit",
            "content": "User published a paper",
            "about_ref": "current_user",
            "source_refs": [assistant_source],
        },
    )
    assert assistant_only["error"] == "DURABLE_USER_FACT_REQUIRES_NON_ASSISTANT_SOURCE"
    assert assistant_only["decision"] == "REJECTED"
    assert mem.checkpoint() == before
    user = mem.dispatch(
        "memory_save",
        {
            "op": "CREATE",
            "certainty": "explicit",
            "content": "User volunteers locally",
            "about_ref": "current_user",
            "source_refs": [user_source],
        },
    )
    assert mem.read(user["record"]["ref"])["about"] == {
        "kind": "current_user",
        "user_id": "alice",
    }
    before_revision = mem.checkpoint()
    invalid_revision = mem.dispatch(
        "memory_save",
        {
            "op": "REVISE",
            "certainty": "explicit",
            "target_ref": user["record"]["ref"],
            "content": "User follows the assistant's suggestion",
            "about_ref": "current_user",
            "source_refs": [assistant_source],
            "dependencies": [],
        },
    )
    assert invalid_revision["error"] == "DURABLE_USER_FACT_REQUIRES_NON_ASSISTANT_SOURCE"
    assert mem.checkpoint() == before_revision
    note = mem.dispatch(
        "memory_save",
        {
            "op": "CREATE",
            "certainty": "explicit",
            "content": "Consider asking about schedules",
            "about_ref": "unresolved",
            "source_refs": [],
        },
    )
    assert mem.read(note["record"]["ref"])["about"] == {"kind": "unresolved"}
    checkpoint = mem.checkpoint()
    restored = ContextualMemory.restore(checkpoint, user_id="alice", embed=mem.embed)
    assert restored.read(assistant["record"]["ref"])["about"]["source_role"] == "assistant"
    checkpoint["format"] = "contextual-user-memory-v8"
    with pytest.raises(ValueError, match="CHECKPOINT_USER_OR_VERSION_MISMATCH"):
        ContextualMemory.restore(checkpoint, user_id="alice", embed=mem.embed)


def test_external_revision_replaces_declared_relations_and_rejects_own_history() -> None:
    mem = memory()
    first_source = mem.publish(Observation("old", "Original account", "user", "x"))
    next_source = mem.publish(Observation("new", "Updated account", "user", "x"))
    prerequisite_source = mem.publish(Observation("basis", "Independent premise", "user", "x"))
    prerequisite = mem.dispatch(
        "memory_save",
        {
            "op": "CREATE",
            "certainty": "explicit",
            "content": "Independent premise",
            "about_ref": "current_user",
            "source_refs": [prerequisite_source],
        },
    )["record"]["ref"]
    initial = mem.dispatch(
        "memory_save",
        {
            "op": "CREATE",
            "certainty": "explicit",
            "content": "Initial account",
            "about_ref": "current_user",
            "source_refs": [first_source],
        },
    )["record"]["ref"]
    mem.read(initial)
    mem.read(prerequisite)
    before = mem.checkpoint()
    missing = mem.dispatch(
        "memory_save",
        {
            "op": "REVISE",
            "certainty": "explicit",
            "target_ref": initial,
            "content": "Updated account",
            "about_ref": "current_user",
            "source_refs": [next_source],
        },
    )
    self_dependent = mem.dispatch(
        "memory_save",
        {
            "op": "REVISE",
            "certainty": "explicit",
            "target_ref": initial,
            "content": "Updated account",
            "about_ref": "current_user",
            "source_refs": [next_source],
            "dependencies": [initial],
        },
    )
    source_as_dependency = mem.dispatch(
        "memory_save",
        {
            "op": "REVISE",
            "certainty": "explicit",
            "target_ref": initial,
            "content": "Updated account",
            "about_ref": "current_user",
            "source_refs": [next_source],
            "dependencies": [next_source],
        },
    )
    assert missing["error"] == "REVISION_REQUIRES_EXPLICIT_DEPENDENCIES"
    assert self_dependent["error"] == "REVISION_CANNOT_DEPEND_ON_OWN_VERSION"
    assert source_as_dependency["error"] == "DEPENDENCY_REQUIRES_INTERPRETATION"
    assert mem.checkpoint() == before
    revised = mem.dispatch(
        "memory_save",
        {
            "op": "REVISE",
            "certainty": "explicit",
            "target_ref": initial,
            "content": "Updated account",
            "about_ref": "current_user",
            "source_refs": [next_source],
            "dependencies": [prerequisite],
        },
    )["record"]["ref"]
    assert revised != initial
    assert mem.read(initial)["status"] == "SUPERSEDED"
    current = mem.read(revised)
    assert current["source_refs"] == [next_source]
    assert current["dependencies"] == [prerequisite]
    assert current["dependency_status"][0]["status"] == "CURRENT"
    prerequisite_new = mem.dispatch(
        "memory_save",
        {
            "op": "REVISE",
            "certainty": "explicit",
            "target_ref": prerequisite,
            "content": "Changed premise",
            "about_ref": "current_user",
            "source_refs": [prerequisite_source],
            "dependencies": [],
        },
    )["record"]["ref"]
    assert prerequisite_new != prerequisite
    assert mem.read(revised)["dependency_status"][0]["status"] == "NEEDS_REVISION"
    mem.read(revised)
    before = mem.checkpoint()
    old_version = mem.dispatch(
        "memory_save",
        {
            "op": "REVISE",
            "certainty": "explicit",
            "target_ref": revised,
            "content": "Again",
            "about_ref": "current_user",
            "source_refs": [next_source],
            "dependencies": [initial],
        },
    )
    assert old_version["error"] == "REVISION_CANNOT_DEPEND_ON_OWN_VERSION"
    assert mem.checkpoint() == before
    patched = mem.save(target_ref=revised, context="Internal metadata correction")["record"]["ref"]
    patch_view = mem.read(patched)
    assert patch_view["source_refs"] == [next_source]
    assert patch_view["dependencies"] == [prerequisite]
    assert patch_view["about_ref"] == "current_user"


def test_ordinary_write_branches_require_bound_subject_and_full_relations() -> None:
    parameters = next(
        tool["function"]["parameters"]
        for tool in TOOLS
        if tool["function"]["name"] == "memory_save"
    )
    branches = ordinary_save_schema(parameters)["oneOf"]
    assert [next(iter(branch["properties"])) for branch in branches] == ["op"] * 5
    create, patch, revise, retain, _ = branches
    assert list(create["properties"])[:5] == [
        "op",
        "about_ref",
        "source_refs",
        "certainty",
        "content",
    ]
    assert list(revise["properties"])[:7] == [
        "op",
        "target_ref",
        "about_ref",
        "source_refs",
        "dependencies",
        "certainty",
        "content",
    ]
    assert {"about_ref", "source_refs"} <= set(create["required"])
    assert {"about_ref", "source_refs", "dependencies"} <= set(revise["required"])
    assert set(patch["required"]) == (set(revise["required"]) - {"content"}) | {"content_patch"}
    assert "content" not in patch["properties"]
    assert "content_patch" not in revise["properties"]
    assert "content_patch" not in create["properties"]
    assert "description" not in revise["properties"]["dependencies"]
    assert "description" not in revise["properties"]["subject"]
    assert "source_ref" not in create["properties"]
    assert "source_ref" not in revise["properties"]
    assert retain["required"] == ["op", "source_ref"]


def test_trusted_actor_is_distinct_from_role_and_subject() -> None:
    mem = memory()
    unknown = mem.publish(Observation("one", "I need notes", "user", "fixture"))
    owner = mem.publish(
        Observation(
            "two",
            "I need a shorter answer",
            "user",
            "fixture",
            actor_ref="current_user",
        )
    )
    worker = mem.publish(
        Observation(
            "three",
            "The check failed",
            "tool",
            "fixture",
            actor_ref="worker-7",
        )
    )
    assert mem.source_subject(unknown) == f"speaker:{unknown}"
    assert mem.source_subject(owner) == "current_user"
    assert mem.source_subject(worker) == "actor:worker-7"
    assert mem.read(worker)["actor_ref"] == "worker-7"
    with pytest.raises(ValueError, match="SOURCE_IDENTITY_REUSED"):
        mem.publish(
            Observation(
                "one",
                "I need notes",
                "user",
                "fixture",
                actor_ref="current_user",
            )
        )
    created = mem.save(
        op="CREATE",
        content="This worker observed a failed check",
        about_ref="actor:worker-7",
        source_refs=[worker],
        certainty="explicit",
    )
    assert created["record"]["about"] == {
        "kind": "actor",
        "actor_ref": "worker-7",
    }
    with pytest.raises(ValueError, match="ABOUT_ACTOR_NOT_CITED"):
        mem.save(
            op="CREATE",
            content="Unanchored worker",
            about_ref="actor:worker-7",
            source_refs=[unknown],
            certainty="explicit",
        )


def test_advance_turn_keeps_session_source_and_state_but_resets_query_conditions() -> None:
    mem = ContextualMemory(
        "alice", host_id="host", embed=embed, embedding_dimension=2, state_policy="optional"
    )
    mem.start_task("session", "first question", task_conditions={"setting": "home"})
    source = mem.publish(Observation("one", "A session observation", "user", "fixture"))
    mem.save(source_ref=source, persistence="task")
    mem.update_state(context="A hypothesis to investigate", conditions={"setting": "home"})
    mem.search("first question")
    mem.update_state(coverage="GAP")
    mem.advance_turn("second question", conditions={"setting": "office"}, valid_at="2024-02-03")
    assert source in mem.sources and source in mem.task_sources
    assert mem.state.task_id == "session" and mem.state.context == "A hypothesis to investigate"
    assert mem.state.coverage == "UNKNOWN" and mem.state.conditions == {}
    projected = mem.search("", valid_at="2024-02-04")["query_projection"]
    assert projected["effective_query"] == "second question"
    assert projected["filters"]["valid_at"] == "2024-02-04"
    assert projected["sources"]["valid_at"] == "tool_argument"
    assert projected["sources"]["conditions"]["task_or_visible_evidence"] == ["setting"]


def test_exact_no_change_revision_has_no_new_version_or_memory_change() -> None:
    mem = memory()
    source = mem.publish(Observation("one", "Direct statement", "user", "fixture"))
    created = mem.save(
        op="CREATE",
        content="Direct statement",
        about_ref="current_user",
        source_refs=[source],
        certainty="explicit",
    )
    ref = created["record"]["ref"]
    assert set(created["memory_changes"]) == {source, ref}
    mem.read(ref, include_sources=False)
    no_change = mem.save(
        op="REVISE",
        target_ref=ref,
        content="Direct statement",
        about_ref="current_user",
        source_refs=[source],
        dependencies=[],
        certainty="explicit",
    )
    assert no_change["status"] == "NO_CHANGE"
    assert no_change["decision"] == "NO_CHANGE" and no_change["memory_changes"] == []
    assert no_change["record"]["ref"] == ref and mem.resolve(ref) == ref
    assert receipt_outcome("memory_save", no_change).succeeded == ()
    with pytest.raises(ValueError, match="EXPLICIT_CERTAINTY"):
        mem.save(
            op="REVISE",
            target_ref=ref,
            content="Changed",
            about_ref="current_user",
            source_refs=[source],
            dependencies=[],
        )
    temporary = mem.publish(Observation("two", "Later detail", "user", "fixture"))
    mem.save(source_ref=temporary, persistence="task")
    promoted = mem.save(
        op="CREATE", content="Later detail", about_ref="current_user",
        source_refs=[temporary], certainty="explicit",
    )
    assert temporary in promoted["memory_changes"] and temporary in mem.retained


def test_new_checkpoint_shares_write_history_across_state_policies_only_without_task() -> None:
    mem = ContextualMemory(
        "alice", host_id="host", embed=embed, embedding_dimension=2, state_policy="off"
    )
    mem.start_task("task", "question")
    source = mem.publish(Observation("one", "A source", "user", "fixture"))
    mem.save(source_ref=source)
    stored = mem.checkpoint(include_task=False)
    optional = ContextualMemory.restore(
        stored, user_id="alice", embed=embed, state_policy="optional"
    )
    assert optional.state_policy == "optional" and source in optional.sources
    with pytest.raises(ValueError, match="TASK_POLICY_MISMATCH"):
        ContextualMemory.restore(
            mem.checkpoint(), user_id="alice", embed=embed, state_policy="optional"
        )
    with pytest.raises(ValueError, match="CHECKPOINT_USER_OR_VERSION_MISMATCH"):
        ContextualMemory.restore(
            {**stored, "format": "contextual-user-memory-v10"}, user_id="alice", embed=embed
        )


def test_receipt_distinguishes_nested_conflict_from_dependency_warning() -> None:
    mem = memory()
    source = mem.publish(Observation("1", "original", "user", "fixture"))
    first = mem.save(content="initial interpretation", source_ref=source)["record"]["ref"]
    current = mem.save(target_ref=first, content="revised interpretation")["record"]["ref"]
    result = mem.save(target_ref=first, content="stale edit", source_ref=source)
    outcome = receipt_outcome("memory_save", result)
    assert outcome.completion == "failed"
    assert outcome.succeeded == ()
    assert outcome.failed == ("record:VERSION_CONFLICT",)
    assert outcome.usable_refs == ()
    assert current not in outcome.usable_refs

    replacement = mem.publish(Observation("2", "corrected", "user", "fixture", supersedes=source))
    viewed = mem.read(current)
    assert viewed["dependency_status"][0]["status"] == "NEEDS_REVISION"
    read_outcome = receipt_outcome("memory_read", viewed)
    assert read_outcome.ok
    assert current in read_outcome.usable_refs
    assert replacement not in read_outcome.usable_refs
    assert receipt_outcome("memory_save", {"status": "PARTIAL"}).completion == "failed"
    assert receipt_outcome("memory_save", {"status": "PENDING"}).completion == "pending"


def test_memory_state_failure_does_not_partially_update_state() -> None:
    mem = memory()
    first = mem.save(content="first")["record"]["ref"]
    for index in range(64):
        mem.save(content=f"record {index}")
    before = mem.checkpoint()
    with pytest.raises(ValueError, match="INVALID_FOCUS_FRAME"):
        mem.update_state(context=123)
    assert mem.checkpoint() == before
    result = mem.dispatch("memory_state", {"context": "uncommitted", "intentions": [first]})
    assert result["status"] == "UPDATED"
    assert mem.state.context == "uncommitted"
    assert mem.workspace.working_note == "uncommitted"
    assert before["task"]["state"]["context"] == ""


def test_historical_card_dependency_status_tracks_later_source_correction() -> None:
    mem = memory()
    source = mem.publish(Observation("first", "initial receipt", "tool", "fixture"))
    first = mem.save(content="initial interpretation", source_ref=source)["record"]["ref"]
    current = mem.save(target_ref=first, content="reworded interpretation")["record"]["ref"]
    replacement = mem.publish(
        Observation("second", "corrected receipt", "tool", "fixture", supersedes=source)
    )
    for ref in (first, current):
        assert mem.read(ref)["dependency_status"] == [
            {
                "observed_ref": source,
                "current_ref": replacement,
                "status": "NEEDS_REVISION",
            }
        ]


def test_coverage_is_bound_to_the_returned_query_and_cleared_on_handoff() -> None:
    def paired_embed(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "alpha" in text else [0.0, 1.0] for text in texts]

    mem = ContextualMemory(
        "alice",
        host_id="host",
        embed=paired_embed,
        embedding_dimension=2,
        embedding_identity="paired-toy-v1",
        state_policy="forced_legacy",
    )
    mem.start_task("first", "alpha")
    alpha = mem.save(content="alpha")["record"]["ref"]
    beta = mem.save(content="beta")["record"]["ref"]
    assert mem.dispatch("memory_state", {"coverage": "SUFFICIENT"})["status"] == "ERROR"
    assert mem.search("alpha", limit=1)["materials"][0]["ref"] == alpha
    mem.update_state(coverage="SUFFICIENT")
    assert mem.search("alpha", limit=1)["attention"]["coverage"] == "SUFFICIENT"
    changed = mem.search("beta", limit=1)
    assert changed["attention"]["coverage"] == "UNKNOWN"
    assert changed["materials"][0]["ref"] == beta
    assert mem.state.coverage == "UNKNOWN"
    mem.update_state(intentions=[alpha])
    reviewed = mem.search("beta", limit=1)
    assert reviewed["attention"]["field_status"]["memory_intentions"] == "CURRENT"
    assert reviewed["materials"][0]["ref"] == beta
    mem.update_state(coverage="SUFFICIENT")
    assert mem.search("beta", limit=1)["attention"]["coverage"] == "UNKNOWN"
    mem.update_state(intentions=[])
    mem.search("beta", limit=1)
    mem.update_state(coverage="SUFFICIENT")
    restored = ContextualMemory.restore(
        mem.checkpoint(),
        user_id="alice",
        embed=paired_embed,
        embedding_identity="paired-toy-v1",
    )
    assert restored.search("beta", limit=1)["attention"]["coverage"] == "SUFFICIENT"
    restored.start_task("second", "different question", handoff=restored.handoff())
    assert restored.state.coverage == "UNKNOWN"


def test_temporary_source_expires_and_handoff_preserves_conflict() -> None:
    mem = memory()
    source = mem.publish(Observation("task", "temporary fact", "user", "x"))
    mem.save(source_ref=source, persistence="task")
    a = mem.save(content="technical usual")["record"]["ref"]
    b = mem.save(content="client exception")["record"]["ref"]
    assert mem.save(content="technical usual")["record"]["ref"] == a
    mem.update_state(
        context="technical",
        uncertainty="unclear scope",
        conflicts=[a, b],
        intentions=[a],
    )
    mem.start_task("new-task", "new question", handoff=mem.handoff())
    assert source not in mem.sources
    assert mem.state.conflicts == [a, b]
    assert mem.state.uncertainty == "unclear scope"
    assert mem.state.coverage == "UNKNOWN"
    assert mem.workspace.frame.question == "new question"
    assert mem.search()["attention"]["mode"] == "CONFLICT"


def test_task_checkpoint_and_selected_handoff_keep_temporary_objects_scoped() -> None:
    mem = memory()
    source = mem.publish(Observation("temporary", "task fact", "user", "x"))
    card = mem.save(content="task inference", source_ref=source, persistence="task")["record"][
        "ref"
    ]
    mem.update_state(intentions=[card])
    restored = ContextualMemory.restore(mem.checkpoint(), user_id="alice", embed=embed)
    assert restored.read(card)["sources"][0]["content"] == "task fact"
    assert not restored.checkpoint(include_task=False)["cards"]
    restored.start_task("handoff-task", "new question", handoff=restored.handoff())
    assert restored.read(card)["persistence"] == "task"
    restored.start_task("later-task", "later question")
    assert not restored.sources and not restored.workspace.cards


def test_forgetting_old_version_and_exact_paged_source_read(tmp_path: Path) -> None:
    ledger = DeletionLedger(tmp_path / "deletions.json", "alice")
    mem = memory(ledger=ledger)
    old = mem.save(content="secret")["record"]["ref"]
    mem.save(target_ref=old, content="new secret")
    trusted_forget(mem, ledger, [old])
    assert not mem.workspace.cards and not mem.history
    text = "source fragment\n" * 2000
    source = mem.publish(Observation("long", text, "user", "x"))
    first = mem.read(source, length=4000)
    second = mem.read(source, start=4000, length=4000)
    assert first["content"] + second["content"] == text[:8000]
    assert first["page"]["content_sha256"] == second["page"]["content_sha256"]
    assert first["page"]["total_chars"] == len(text)
    assert not first["page"]["complete"]


def test_gap_executes_one_bounded_expansion_without_claiming_coverage() -> None:
    mem = memory()
    first = mem.save(content="first")["record"]["ref"]
    second = mem.save(content="other evidence")["record"]["ref"]
    mem.update_state(intentions=[first])
    mem.search("topic", limit=1, max_bytes=800)
    mem.update_state(coverage="GAP")
    result = mem.search("topic", limit=1, max_bytes=800)
    assert result["attention"]["expansion_attempts"] == 1
    assert result["attention"]["coverage"] == "UNKNOWN"
    assert result["attention"]["action"] == "CONTEXT"
    assert result["expanded_materials"][0]["ref"] == second
    assert not {item["ref"] for item in result["materials"]} & {
        item["ref"] for item in result["expanded_materials"]
    }
    projected = MaterialView("test", mem).project(result, max_bytes=800)
    assert serialized_material_bytes(projected) <= 800
    again = mem.search("topic", limit=1)
    assert again["attention"]["coverage"] == "UNKNOWN"
    assert mem.state.coverage == "UNKNOWN"


def test_acquisition_correction_preserves_old_source_and_marks_dependents() -> None:
    mem = memory()
    old = mem.publish(Observation("1", "incomplete receipt", "tool", "adapter"))
    note = mem.save(content="interpretation", source_ref=old)["record"]["ref"]
    new = mem.publish(Observation("2", "corrected receipt", "tool", "adapter", supersedes=old))
    assert mem.read(old)["content"] == "incomplete receipt"
    assert mem.read(old)["current_ref"] == new
    assert mem.read(note)["dependency_status"][0]["status"] == "NEEDS_REVISION"
    restored = ContextualMemory.restore(mem.checkpoint(), user_id="alice", embed=embed)
    assert restored.resolve(old) == new
    restored.update_state(intentions=[note])
    result = restored.search("receipt", limit=1)
    materials = result["materials"]
    assert [item["ref"] for item in materials if item["kind"] == "source"][:1] == [new]
    assert result["independent_source_refs"] == [new]
    assert restored.read(note)["sources"][0]["ref"] == new


def test_source_replacement_requires_tip_and_repeat_is_idempotent() -> None:
    mem = memory()
    first = mem.publish(Observation("1", "incorrect", "tool", "x"))
    second_event = Observation("2", "corrected", "tool", "x", supersedes=first)
    second = mem.publish(second_event)
    with pytest.raises(ValueError, match="SOURCE_REPLACEMENT_REQUIRES_CURRENT_REF"):
        mem.publish(Observation("3", "later", "tool", "x", supersedes=first))
    third = mem.publish(Observation("3", "later", "tool", "x", supersedes=second))
    assert mem.publish(second_event) == second
    assert mem.resolve(first) == third


def test_task_source_replacement_restores_and_expires_with_task() -> None:
    mem = memory()
    first = mem.publish(Observation("1", "incorrect task source", "tool", "x"))
    card = mem.save(content="task note", source_ref=first, persistence="task")["record"]["ref"]
    second = mem.publish(Observation("2", "correct task source", "tool", "x", supersedes=first))
    mem.update_state(intentions=[card])
    restored = ContextualMemory.restore(mem.checkpoint(), user_id="alice", embed=embed)
    assert restored.resolve(first) == second
    assert restored.read(card)["sources"][0]["content"] == "correct task source"
    restored.start_task("handoff", "new question", handoff=restored.handoff())
    assert restored.resolve(first) == second
    restored.start_task("later", "later question")
    assert first not in restored.sources and second not in restored.sources
    assert not restored.workspace.cards


def test_subject_only_revision_preserves_text_and_old_metadata() -> None:
    mem = memory()
    old = mem.save(content="Prefers concise answers")["record"]["ref"]
    updated = mem.save(target_ref=old, subject="colleague", context="client meeting")["record"]
    assert updated["ref"] != old
    assert updated["subject"] == "colleague"
    assert updated["text"] == "Prefers concise answers"
    assert mem.read(old)["subject"] == ""
    assert mem.read(old)["about"] == {"kind": "unresolved"}


def test_embedding_identity_rebuilds_vectors_and_invalidates_coverage() -> None:
    first = ContextualMemory(
        "alice",
        host_id="host",
        embed=embed,
        embedding_model="toy",
        embedding_dimension=2,
        embedding_identity="toy-weights-a-window-1",
        state_policy="forced_legacy",
    )
    first.start_task("one", "client")
    source = first.publish(Observation("source", "client source", "user", "fixture"))
    first.save(source_ref=source)
    task_card = first.save(content="task client", persistence="task")["record"]["ref"]
    first.search("client")
    first.update_state(coverage="SUFFICIENT")
    saved = first.checkpoint()
    assert saved["vectors"] and saved["task"]["overlay"]["vectors"]

    same = ContextualMemory.restore(
        saved,
        user_id="alice",
        embed=embed,
        embedding_identity="toy-weights-a-window-1",
        embedding_model="toy",
        embedding_dimension=2,
    )
    assert same.vectors
    assert same.search("client")["attention"]["coverage"] == "SUFFICIENT"

    changed = ContextualMemory.restore(
        saved,
        user_id="alice",
        embed=embed,
        embedding_identity="toy-weights-b-window-1",
        embedding_model="toy",
        embedding_dimension=2,
    )
    assert changed.vectors == {}
    assert changed.state.coverage == "UNKNOWN"
    assert changed.coverage_binding is None and changed.expansion == {}
    assert changed.read(source)["content"] == "client source"
    assert changed.read(task_card)["text"] == "task client"
    changed.search("client")
    assert changed.vectors

    transferred = ContextualMemory.restore(
        saved,
        user_id="alice",
        embed=embed,
        embedding_identity="toy-weights-b-window-1",
        embedding_model="toy",
        embedding_dimension=2,
    )
    transferred.start_task("two", "client", handoff=first.handoff())
    assert transferred.vectors == {}
    assert transferred.read(task_card)["text"] == "task client"

    unknown = ContextualMemory.restore(saved, user_id="alice", embed=embed)
    assert unknown.vectors == {}
    assert unknown.state.coverage == "UNKNOWN"

    other_dimension = ContextualMemory.restore(
        saved,
        user_id="alice",
        embed=lambda texts: [[1.0, 0.0, 0.0] for _ in texts],
        embedding_identity="toy-weights-a-window-1",
        embedding_model="toy",
        embedding_dimension=3,
    )
    assert other_dimension.embedding_dimension == 3
    assert other_dimension.vectors == {}


def test_long_source_range_is_discoverable_and_original_is_exact() -> None:
    mem = ContextualMemory(
        "alice",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        embedding_identity="flat-toy-v1",
    )
    mem.start_task("one", "locate")
    body = "ordinary words " * 7000 + "uniquephrase late source detail" + " trailing" * 200
    source = mem.publish(Observation("long", body, "user", "fixture"))
    mem.save(source_ref=source)
    found = mem.search("uniquephrase", limit=1, max_bytes=5000)
    item = found["materials"][0]
    assert item["ref"] == source
    assert "uniquephrase" in item["content"]
    assert item["page"]["complete"] is False
    assert item["content"] == body[item["page"]["start"] : item["page"]["end"]]
    assert item["page"]["content_sha256"] == mem.read(source, length=10)["page"]["content_sha256"]
    assert (
        mem.read(source, start=item["page"]["start"], length=len(item["content"]))["content"]
        == item["content"]
    )
    assert found["independent_source_refs"] == [source]
    assert any(key.startswith(f"{source}#") for key in mem.checkpoint()["vectors"])


def test_existing_records_are_current_complete_and_read_for_revision() -> None:
    mem = memory()
    old = mem.save(content="purple presentation", subject="current_user")["record"]["ref"]
    current = mem.save(target_ref=old, content="purple client presentation")["record"]["ref"]
    mem.save(content="other subject")
    mem.seen.clear()
    records = mem.suggest_existing_records("purple client", limit=1)
    assert [item["ref"] for item in records] == [current]
    assert records[0]["page"]["complete"] is True
    assert records[0]["status"] == "CURRENT"
    assert records[0]["text"] == "purple client presentation"
    assert current in mem.seen
    assert mem.save(target_ref=current, content="revised")["record"]["status"] == "SAVED"


def test_lexical_route_recalls_source_when_embedding_ranks_it_last() -> None:
    def misleading_embed(texts: list[str]) -> list[list[float]]:
        return [[0.0, 1.0] if "belongs to the source" in text else [1.0, 0.0] for text in texts]

    mem = ContextualMemory(
        "alice",
        host_id="host",
        embed=misleading_embed,
        embedding_dimension=2,
        state_policy="off",
        embedding_identity="misleading-toy-v1",
    )
    mem.start_task("one", "violetcode")
    source = mem.publish(Observation("source", "violetcode belongs to the source", "user", "x"))
    mem.save(source_ref=source)
    mem.save(content="unrelated record")
    result = mem.search("violetcode", limit=1)
    assert result["materials"][0]["ref"] == source
