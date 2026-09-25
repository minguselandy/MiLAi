from __future__ import annotations

from typing import Any

import pytest
from jsonschema import ValidationError, validate  # type: ignore[import-untyped]

from milai_lab.methods.contextual_memory.models import Observation
from milai_lab.methods.contextual_memory.write_contract import (
    apply_content_patch,
    normalize_basis_delta,
    ordinary_save_schema,
)
from milai_lab.methods.contextual_user_memory import TOOLS, ContextualMemory


def test_patch_requires_unique_nonoverlapping_original_and_visible_ranges() -> None:
    text = "Requirements: A; B; C. Amount: 30."
    patches = [{"old": "30", "new": "40"}, {"old": "B", "new": "B2"}]
    assert apply_content_patch(text, patches) == "Requirements: A; B2; C. Amount: 40."
    assert apply_content_patch("abcd", [{"old": "bc", "new": "X"}],
                               visible_spans=[(0, 2), (2, 4)]) == "aXd"
    with pytest.raises(ValueError, match="CONTENT_PATCH_OLD_NOT_DELIVERED"):
        apply_content_patch("abcd", [{"old": "bc", "new": "X"}],
                            visible_spans=[(0, 2), (3, 4)])
    with pytest.raises(ValueError, match="CONTENT_PATCH_OLD_AMBIGUOUS"):
        apply_content_patch("aaaa", [{"old": "aaa", "new": "X"}])
    with pytest.raises(ValueError, match="CONTENT_PATCH_OVERLAP"):
        apply_content_patch("abcd", [{"old": "abc", "new": "X"},
                                     {"old": "bcd", "new": "Y"}])
    with pytest.raises(ValueError, match="CONTENT_PATCH_OLD_NOT_FOUND"):
        apply_content_patch(text, [{"old": "missing", "new": "X"}])
    with pytest.raises(ValueError, match="INVALID_CONTENT_PATCH"):
        apply_content_patch(text, [{"old": "", "new": "X"}])


def test_revise_patch_keeps_unmodified_text_sources_and_exact_cas() -> None:
    memory = ContextualMemory(
        "owner", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
    )
    old_source = memory.publish(Observation("old", "A; B; C; amount 30", "user", "test"))
    new_source = memory.publish(Observation("new", "B2; amount 40", "user", "test"))
    original = "Requirements: A; B; C. Amount: 30."
    old_ref = memory.save(
        op="CREATE", content=original, about_ref="unresolved", source_refs=[old_source],
        certainty="explicit",
    )["record"]["ref"]
    memory.read(old_ref, include_sources=False)
    arguments: dict[str, Any] = {
        "op": "REVISE", "target_ref": old_ref, "about_ref": "unresolved",
        "source_refs": [old_source, new_source], "dependencies": [],
        "certainty": "explicit",
        "content_patch": [{"old": "30", "new": "40"}, {"old": "B", "new": "B2"}],
    }
    revised = memory.dispatch("memory_save", arguments)
    new_ref = revised["record"]["ref"]
    assert new_ref != old_ref
    assert memory.read(new_ref, include_sources=False)["text"] == (
        "Requirements: A; B2; C. Amount: 40."
    )
    assert memory.workspace.cards[memory._handle(new_ref)].source_refs == [old_source, new_source]
    assert memory.dispatch("memory_save", arguments)["record"]["status"] == "VERSION_CONFLICT"
    missing = {**arguments, "target_ref": new_ref,
               "content_patch": [{"old": "missing", "new": "X"}]}
    assert memory.dispatch("memory_save", missing)["status"] == "ERROR"
    assert memory.read(new_ref, include_sources=False)["status"] == "CURRENT"
    assert memory.dispatch("memory_save", {**missing, "content": original})["status"] == "ERROR"
    assert memory.dispatch("memory_save", {
        **arguments, "op": "CREATE", "target_ref": None,
    })["status"] == "ERROR"


def test_ordinary_schema_selects_patch_then_full_rewrite_without_mixing() -> None:
    parameters = next(tool["function"]["parameters"] for tool in TOOLS
                      if tool["function"]["name"] == "memory_save")
    schema = ordinary_save_schema(parameters)
    revise = [branch for branch in schema["oneOf"]
              if branch["properties"]["op"]["const"] == "REVISE"]
    assert ["content_patch" in branch["required"] for branch in revise] == [True, True, False]
    base: dict[str, Any] = {
        "op": "REVISE", "target_ref": "r0", "about_ref": "unknown",
        "source_refs": ["s0"], "dependencies": [], "certainty": "explicit",
    }
    validate({**base, "content_patch": [{"old": "B", "new": "B2"}]}, schema)
    validate({**base, "content": "full replacement"}, schema)
    validate({
        "op": "REVISE", "basis_mode": "delta", "target_ref": "r0",
        "content_patch": [{"old": "B", "new": "B2"}],
        "source_delta": {"add": ["s1"], "remove": []},
    }, schema)
    with pytest.raises(ValidationError):
        validate({**base, "basis_mode": "delta",
                  "content_patch": [{"old": "B", "new": "B2"}],
                  "source_delta": {"add": [], "remove": []}}, schema)
    with pytest.raises(ValidationError):
        validate({**base, "content": "full", "content_patch": [{"old": "B", "new": "B2"}]},
                 schema)
    with pytest.raises(ValidationError):
        validate({"op": "CREATE", "about_ref": "unknown", "source_refs": ["s0"],
                  "certainty": "explicit", "content": "new",
                 "content_patch": [{"old": "B", "new": "B2"}]}, schema)


def test_delta_inherits_without_marking_old_basis_read_and_records_actual_ranges() -> None:
    memory = ContextualMemory(
        "owner", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
    )
    old_source = memory.publish(Observation("old", "Earlier basis", "user", "test"))
    dep_source = memory.publish(Observation("dep", "Independent premise", "user", "test"))
    prerequisite = memory.save(op="CREATE", content="Premise", about_ref="unresolved",
                               source_refs=[dep_source], certainty="explicit")["record"]["ref"]
    target = memory.save(op="CREATE", content="Waiting for result", about_ref="unresolved",
                         source_refs=[old_source], certainty="explicit",
                         dependencies=[prerequisite])["record"]["ref"]
    memory.start_task("delta", "Update the result")
    new_source = memory.publish(Observation("new", "New result", "user", "test"))
    memory.read(target, include_sources=False)
    memory.read(new_source, include_sources=False, start=0, length=3)
    assert old_source not in memory.seen and prerequisite not in memory.seen
    arguments: dict[str, Any] = {
        "op": "REVISE", "basis_mode": "delta", "target_ref": target,
        "content_patch": [{"old": "Waiting", "new": "Completed"}],
        "source_delta": {"add": [new_source], "remove": []},
    }
    receipt = memory.dispatch("memory_save", arguments)
    assert receipt["record"]["status"] == "SAVED"
    current = receipt["record"]["ref"]
    assert memory.read(current, include_sources=False)["text"] == "Completed for result"
    assert memory.workspace.cards[memory._handle(current)].source_refs == [old_source, new_source]
    assert memory.details[memory._handle(current)].dependencies == [prerequisite]
    change = receipt["basis_change"]
    assert change["target_ref"] == target
    assert change["sources"] == {
        "inherited": [old_source], "added": [new_source], "removed": [],
    }
    assert change["dependencies"] == {
        "inherited": [prerequisite], "added": [], "removed": [],
    }
    assert change["reviewed_source_ranges"] == {new_source: [[0, 3]]}
    assert memory.history[target]["source_refs"] == [old_source]
    assert memory.dispatch("memory_save", arguments)["record"]["status"] == "VERSION_CONFLICT"
    assert normalize_basis_delta([old_source, new_source],
                                 {"add": [], "remove": [old_source]},
                                 kind="source")[0] == [new_source]


def test_delta_rejects_stale_inherited_basis_and_mixed_metadata() -> None:
    memory = ContextualMemory(
        "owner", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
    )
    old_source = memory.publish(Observation("old", "Original", "user", "test"))
    target = memory.save(op="CREATE", content="Pending", about_ref="unresolved",
                         source_refs=[old_source], certainty="explicit")["record"]["ref"]
    memory.start_task("delta", "Update")
    memory.read(target, include_sources=False)
    changed_source = memory.publish(Observation(
        "new", "Corrected", "user", "test", supersedes=old_source,
    ))
    memory.read(changed_source, include_sources=False)
    base: dict[str, Any] = {
        "op": "REVISE", "basis_mode": "delta", "target_ref": target,
        "content_patch": [{"old": "Pending", "new": "Done"}],
        "source_delta": {"add": [changed_source], "remove": []},
    }
    stale = memory.dispatch("memory_save", base)
    assert stale["error"] == "INHERITED_SOURCE_SUPERSEDED"
    assert memory.dispatch("memory_save", {**base, "subject": "changed"})["status"] == "ERROR"
    assert memory.dispatch("memory_save", {
        **base, "source_delta": {"add": [changed_source], "remove": [old_source]},
    })["record"]["status"] == "SAVED"


def test_delta_can_remove_stale_dependency_from_target_metadata_without_reading_it() -> None:
    memory = ContextualMemory(
        "owner", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
    )
    source = memory.publish(Observation("old", "Original", "user", "test"))
    prerequisite = memory.save(op="CREATE", content="Premise", about_ref="unresolved",
                               source_refs=[source], certainty="explicit")["record"]["ref"]
    target = memory.save(op="CREATE", content="Pending", about_ref="unresolved",
                         source_refs=[source], certainty="explicit",
                         dependencies=[prerequisite])["record"]["ref"]
    memory.read(prerequisite, include_sources=False)
    memory.save(target_ref=prerequisite, content="Corrected premise")
    memory.start_task("delta", "Update")
    memory.read(target, include_sources=False)
    arguments: dict[str, Any] = {
        "op": "REVISE", "basis_mode": "delta", "target_ref": target,
        "content_patch": [{"old": "Pending", "new": "Done"}],
        "source_delta": {"add": [], "remove": []},
    }
    assert prerequisite not in memory.seen
    assert memory.dispatch("memory_save", arguments)["error"] == (
        "INHERITED_DEPENDENCY_SUPERSEDED"
    )
    receipt = memory.dispatch("memory_save", {
        **arguments, "dependency_delta": {"add": [], "remove": [prerequisite]},
    })
    assert receipt["record"]["status"] == "SAVED"
    assert receipt["basis_change"]["dependencies"]["removed"] == [prerequisite]
