"""Engineering stories for the four arms, without benchmark examples or labels."""

from __future__ import annotations

import copy
from contextlib import contextmanager
from pathlib import Path

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.edit_units import issue_evidence, source_evidence
from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_memory import EditMemory


@contextmanager
def opened(root: Path, arm: str):
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        service = MemoryService(
            store,
            ("edit-method", arm, "alice"),
            "alice",
            root / "lock",
            mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1",
        )
        yield service, EditMemory(service, arm)


def incoming(service, key, text):
    ref = service.capture_user("session", key, text)["source_ref"]
    service.bind_source_boundary("session", key, [ref])
    return issue_evidence(service, ref, 0, len(text))["evidence_id"]


def initial(method, source, *, conditioned=False):
    units = [
        {"text": "Project P trial: two runs weekly.", "role": "content", "evidence": [source]},
        {
            "text": "Start week unknown.",
            "role": "condition" if conditioned else "content",
            "evidence": [source],
        },
        {
            "text": "Pause on holidays.",
            "role": "condition" if conditioned else "content",
            "evidence": [source],
        },
    ]
    relations = (
        [
            {"source": index, "relation_type": "modifies", "target": 0, "evidence": [source]}
            for index in (1, 2)
        ]
        if conditioned
        else []
    )
    return method.apply(
        "session", "formation", {"action": "create", "units": units, "relations": relations}
    )


def proposal(record, operations):
    return {
        "action": "edit",
        "target_record": record["id"],
        "base_revision": record["value"]["revision"],
        "edits": operations,
    }


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
def test_initial_formation_and_same_id_history_use_one_service(tmp_path, arm):
    with opened(tmp_path, arm) as (service, method):
        source = incoming(
            service, "first", "Project P trial twice weekly; start unknown; holidays pause."
        )
        saved = initial(method, source, conditioned=arm in {"B2", "M"})
        assert saved["ok"] and saved["revision"] == 1
        record = service.read(saved["id"])
        assert record["value"]["method_arm"] == arm
        assert method.render(record["value"]) == record["value"]["content"]
        old = copy.deepcopy(record["value"])
        change = incoming(
            service, "change", "Frequency becomes three weekly; other conditions unchanged."
        )
        if arm in {"B0", "B2"}:
            units = [
                {
                    "text": "Project P trial: three runs weekly.",
                    "role": "content",
                    "evidence": [change],
                }
            ]
            for unit in old["edit_state"]["units"][1:]:
                units.append({"text": unit["text"], "role": unit["role"], "evidence": [source]})
            body = {
                "action": "rewrite",
                "target_record": saved["id"],
                "base_revision": 1,
                "units": units,
                "relations": [
                    {
                        "source": index,
                        "relation_type": "modifies",
                        "target": 0,
                        "evidence": [source],
                    }
                    for index in (1, 2)
                ]
                if arm == "B2"
                else [],
            }
        else:
            body = proposal(
                record,
                [
                    {
                        "operation": "replace",
                        "target_unit": old["edit_state"]["units"][0]["unit_id"],
                        "text": "Project P trial: three runs weekly.",
                        "evidence": [change],
                    }
                ],
            )
        updated = method.apply("session", "update", body)
        assert updated["ok"] and updated["id"] == saved["id"] and updated["revision"] == 2
        assert service.read(saved["id"], 1)["value"] == old
        if arm in {"B1", "M"}:
            assert (
                service.read(saved["id"])["value"]["edit_state"]["units"][1:]
                == old["edit_state"]["units"][1:]
            )
        assert len([row for row in service.records() if row["ok"]]) == 1
    with opened(tmp_path, arm) as (service, method):
        assert service.read(saved["id"])["value"]["revision"] == 2
        assert service.read(saved["id"], 1)["value"] == old
        replay = method.apply("session", "update", body)
        assert replay["replayed"] and replay["original_status"] == "committed"
        assert service.read(saved["id"])["value"]["revision"] == 2


def test_plain_insert_delete_preserve_non_target_units(tmp_path):
    with opened(tmp_path, "B1") as (service, method):
        source = incoming(
            service, "first", "Project P trial twice weekly; start unknown; holidays pause."
        )
        saved = initial(method, source)
        record = service.read(saved["id"])
        unchanged = copy.deepcopy(record["value"]["edit_state"]["units"])
        change = incoming(service, "change", "Add a Friday reminder, then cancel holiday pauses.")
        inserted = method.apply(
            "session",
            "insert",
            proposal(
                record,
                [
                    {
                        "operation": "insert",
                        "target_unit": unchanged[0]["unit_id"],
                        "text": "Reminder on Friday.",
                        "evidence": [change],
                    }
                ],
            ),
        )
        record = service.read(inserted["id"])
        assert record["value"]["edit_state"]["units"][0] == unchanged[0]
        assert record["value"]["edit_state"]["units"][2:] == unchanged[1:]
        deleted = method.apply(
            "session",
            "delete",
            proposal(
                record,
                [
                    {
                        "operation": "delete",
                        "target_unit": unchanged[2]["unit_id"],
                        "evidence": [change],
                    }
                ],
            ),
        )
        state = service.read(deleted["id"])["value"]["edit_state"]
        assert unchanged[2]["unit_id"] not in {unit["unit_id"] for unit in state["units"]}
        assert state["units"][0] == unchanged[0] and state["units"][2] == unchanged[1]
        with pytest.raises(FunctionalRejection, match="OPERATION_NOT_AVAILABLE"):
            method.apply(
                "session",
                "wrong-op",
                proposal(
                    service.read(saved["id"]),
                    [
                        {
                            "operation": "override",
                            "target_unit": unchanged[0]["unit_id"],
                            "text": "Four weekly.",
                            "condition": "Night shift only",
                            "evidence": [change],
                        }
                    ],
                ),
            )


def test_conditioned_override_preserves_general_conditions_and_explicit_cancellation(tmp_path):
    with opened(tmp_path, "M") as (service, method):
        source = incoming(
            service, "first", "Project P trial twice weekly; start unknown; holidays pause."
        )
        saved = initial(method, source, conditioned=True)
        record = service.read(saved["id"])
        original = copy.deepcopy(record["value"]["edit_state"])
        general, date, holidays = original["units"]
        change = incoming(
            service, "night", "Night shift four weekly; share pending start and holiday pause."
        )
        updated = method.apply(
            "session",
            "override",
            proposal(
                record,
                [
                    {
                        "operation": "override",
                        "target_unit": general["unit_id"],
                        "text": "Project P trial: four runs weekly.",
                        "condition": "Night shift only",
                        "shared_conditions": [date["unit_id"], holidays["unit_id"]],
                        "evidence": [change],
                    }
                ],
            ),
        )
        record = service.read(updated["id"])
        state = record["value"]["edit_state"]
        assert state["units"][:3] == original["units"]
        assert state["relations"][:2] == original["relations"]
        override, scope = state["units"][3:]
        assert "outside explicit override scopes" in record["value"]["content"]
        assert (
            "Scoped override" in record["value"]["content"]
            and "Night shift only" in record["value"]["content"]
        )
        incoming(service, "nested", "Only one particular night occasion should use five.")
        rejected = method.apply(
            "session",
            "nested",
            proposal(
                record,
                [
                    {
                        "operation": "override",
                        "target_unit": override["unit_id"],
                        "text": "Five weekly.",
                        "condition": "One night occasion",
                        "evidence": [change],
                    }
                ],
            ),
        )
        assert not rejected["ok"] and rejected["reason"] == "EDIT_MULTILEVEL_OVERRIDE_UNSUPPORTED"
        assert service.read(saved["id"])["value"]["revision"] == 2
        cancellation = incoming(
            service, "cancel", "Cancel the night-shift exception; general trial remains."
        )
        result = method.apply(
            "session",
            "retract-scope",
            proposal(
                record,
                [
                    {
                        "operation": "retract",
                        "target_unit": override["unit_id"],
                        "evidence": [cancellation],
                    },
                    {
                        "operation": "retract",
                        "target_unit": scope["unit_id"],
                        "evidence": [cancellation],
                    },
                ],
            ),
        )
        state = service.read(result["id"])["value"]["edit_state"]
        assert state == original
        assert not any("opposite" in unit["text"] for unit in state["units"])
        assert (
            source_evidence(service, [cancellation])[0]["source_ref"]
            in (service.read(result["id"])["value"]["source_refs"])
        )
        assert service.read(saved["id"], 2)["value"]["edit_state"]["units"][3] == override


def test_shared_condition_edit_and_retraction_apply_to_both_scopes(tmp_path):
    with opened(tmp_path, "M") as (service, method):
        source = incoming(
            service, "first", "Project P trial twice weekly; start unknown; holidays pause."
        )
        saved = initial(method, source, conditioned=True)
        record = service.read(saved["id"])
        general, date, holidays = record["value"]["edit_state"]["units"]
        change = incoming(
            service, "night", "Night shift four weekly with the same start and holiday constraints."
        )
        method.apply(
            "session",
            "override",
            proposal(
                record,
                [
                    {
                        "operation": "override",
                        "target_unit": general["unit_id"],
                        "text": "Four weekly.",
                        "condition": "Night shift",
                        "shared_conditions": [date["unit_id"], holidays["unit_id"]],
                        "evidence": [change],
                    }
                ],
            ),
        )
        record = service.read(saved["id"])
        start = incoming(
            service, "start", "All shifts start next Monday and no longer pause on holidays."
        )
        updated = method.apply(
            "session",
            "conditions",
            proposal(
                record,
                [
                    {
                        "operation": "replace",
                        "target_unit": date["unit_id"],
                        "text": "From next Monday.",
                        "evidence": [start],
                    },
                    {
                        "operation": "retract",
                        "target_unit": holidays["unit_id"],
                        "evidence": [start],
                    },
                ],
            ),
        )
        state = service.read(updated["id"])["value"]["edit_state"]
        assert sum(r["source_unit"] == date["unit_id"] for r in state["relations"]) == 2
        assert not any(
            holidays["unit_id"] in {r["source_unit"], r["target_unit"]} for r in state["relations"]
        )
        assert state["units"][0] == general
        assert service.read(saved["id"])["value"]["content"].count("From next Monday.") == 2


def test_append_condition_and_stale_revision_leave_unselected_text_unchanged(tmp_path):
    with opened(tmp_path, "M") as (service, method):
        source = incoming(
            service, "first", "Project P trial twice weekly; start unknown; holidays pause."
        )
        saved = initial(method, source, conditioned=True)
        record = service.read(saved["id"])
        original = copy.deepcopy(record["value"]["edit_state"])
        change = incoming(
            service, "condition", "Use this plan only while permission remains valid."
        )
        body = proposal(
            record,
            [
                {
                    "operation": "append",
                    "role": "condition",
                    "text": "Only while permission remains valid.",
                    "attach_to": [original["units"][0]["unit_id"]],
                    "evidence": [change],
                }
            ],
        )
        receipt = method.apply("session", "append", body)
        assert receipt["revision"] == 2
        current = service.read(saved["id"])["value"]["edit_state"]
        assert current["units"][:3] == original["units"]
        stale = method.apply("session", "stale", body)
        assert not stale["ok"] and stale["reason"] == "revision_conflict"
        assert service.read(saved["id"])["value"]["edit_state"] == current
        with pytest.raises(FunctionalRejection, match="SOURCE_UNAVAILABLE"):
            method.apply(
                "session",
                "bad-source",
                proposal(
                    service.read(saved["id"]),
                    [
                        {
                            "operation": "replace",
                            "target_unit": original["units"][0]["unit_id"],
                            "text": "Unsupported text.",
                            "evidence": ["foreign-source"],
                        }
                    ],
                ),
            )
        assert service.read(saved["id"])["value"]["revision"] == 2


def test_no_change_without_record_is_durable_and_global_retraction_keeps_history(tmp_path):
    with opened(tmp_path, "B1") as (service, method):
        incoming(service, "empty", "A question with no durable assertion.")
        result = method.apply("session", "nothing", {"action": "no_change"})
        assert result["ok"] and result["effect"] == "none" and service.records() == []
        source = incoming(service, "fact", "One supported arrangement.")
        saved = method.apply(
            "session",
            "save",
            {
                "action": "create",
                "units": [{"text": "One supported arrangement.", "evidence": [source]}],
            },
        )
        record = service.read(saved["id"])
        cancellation = incoming(
            service, "withdraw", "Withdraw that arrangement; replacement is unknown."
        )
        deleted = method.apply(
            "session",
            "delete",
            proposal(
                record,
                [
                    {
                        "operation": "delete",
                        "target_unit": record["value"]["edit_state"]["units"][0]["unit_id"],
                        "evidence": [cancellation],
                    }
                ],
            ),
        )
        assert deleted["revision"] == 2
        assert service.read(saved["id"], 2)["value"]["edit_state"]["units"] == []
        assert service.read(saved["id"], 1)["value"]["content"] == "One supported arrangement."
    with opened(tmp_path, "B1") as (service, method):
        assert method.apply("session", "nothing", {"action": "no_change"})["replayed"]


def test_atomic_multiple_targets_reject_overlap_without_partial_write(tmp_path):
    with opened(tmp_path, "M") as (service, method):
        source = incoming(
            service, "first", "Project P trial twice weekly; start unknown; holidays pause."
        )
        saved = initial(method, source, conditioned=True)
        record = service.read(saved["id"])
        original = copy.deepcopy(record["value"])
        target = original["edit_state"]["units"][0]["unit_id"]
        correction = incoming(service, "change", "A proposed correction.")
        with pytest.raises(FunctionalRejection, match="OVERLAPPING_TARGET"):
            method.apply(
                "session",
                "overlap",
                proposal(
                    record,
                    [
                        {
                            "operation": "replace",
                            "target_unit": target,
                            "text": "Changed.",
                            "evidence": [correction],
                        },
                        {"operation": "retract", "target_unit": target, "evidence": [correction]},
                    ],
                ),
            )
        assert service.read(saved["id"])["value"] == original


def test_prepare_delivers_only_current_range_and_persists_exact_evidence(tmp_path):
    with opened(tmp_path, "B1") as (service, method):
        old = incoming(service, "first", "Historical original material. " * 1000)
        saved = initial(method, old)
        prior = service.read(saved["id"])["value"]
        current = "甲方本轮说明。\n乙方下轮说明。"
        source_ref = service.capture_user("session", "range", current)["source_ref"]
        service.bind_source_boundary("session", "range", [source_ref])
        end = current.index("乙")
        prepared = method.prepare(
            [source_ref],
            "Project P",
            source_ranges=[
                {
                    "source_ref": source_ref,
                    "start": 0,
                    "end": end,
                }
            ],
        )
        assert len(prepared["sources"]) == 1
        delivered = prepared["sources"][0]
        assert delivered["text"] == current[:end]
        assert delivered["source_ref"] == source_ref and delivered["body_delivered"]
        assert all(
            "text" not in ref and not ref["body_delivered"]
            for ref in prepared["historical_evidence"]
        )
        assert prepared["records"][0]["edit_state"] == prior["edit_state"]
        with pytest.raises(FunctionalRejection, match="SOURCE_UNAVAILABLE"):
            source_evidence(service, [source_ref])
        evidence = delivered["evidence_id"]
        receipt = method.apply(
            "session",
            "part",
            proposal(
                service.read(saved["id"]),
                [
                    {
                        "operation": "replace",
                        "target_unit": prior["edit_state"]["units"][0]["unit_id"],
                        "text": "甲方本轮安排。",
                        "evidence": [evidence],
                    }
                ],
            ),
        )
        assert receipt["ok"]
        current_state = service.read(saved["id"])["value"]["edit_state"]
        assert current_state["units"][0]["evidence_refs"] == [
            {
                "evidence_id": evidence,
                "source_ref": source_ref,
                "source_revision": 1,
                "start": 0,
                "end": end,
            }
        ]
        assert current_state["units"][1:] == prior["edit_state"]["units"][1:]
    with opened(tmp_path, "B1") as (service, method):
        assert source_evidence(service, [evidence])[0]["end"] == end
        assert service.read(saved["id"], 1)["value"] == prior


def test_prepare_requires_explicit_range_for_every_current_source(tmp_path):
    with opened(tmp_path, "B0") as (service, method):
        a = service.capture_user("session", "a", "First current event.")["source_ref"]
        b = service.capture_user("session", "b", "Second current event.")["source_ref"]
        with pytest.raises(FunctionalRejection, match="RANGES_MISMATCH"):
            method.prepare(
                [a, b],
                "event",
                source_ranges=[
                    {
                        "source_ref": a,
                        "start": 0,
                        "end": 3,
                    }
                ],
            )
        prepared = method.prepare([a, b], "event")
        assert [source["text"] for source in prepared["sources"]] == [
            "First current event.",
            "Second current event.",
        ]
