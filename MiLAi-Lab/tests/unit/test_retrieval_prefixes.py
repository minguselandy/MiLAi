"""Recorded acquisition, missing snapshots and failed primary calls remain distinguishable."""
import copy
import json

import pytest

from milai_lab.analysis.retrieval_prefixes import (
    acquisition_steps,
    new_source_intervals,
    select_call_prefixes,
    select_collection_prefixes,
)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def state(*spans, delivered=True, kind="original_source"):
    return {"task": {"known_evidence": []}, "observed_materials": [{
        "kind": kind, "body_delivered": delivered, "source_ranges": [
            {"source_ref": source, "source_revision": revision, "start": start, "end": end}
            for source, revision, start, end in spans]}]}


def captured_call(path, transitions, *, missing=(), status="ORIGINAL_COMPLETED",
                  observation=True, source_root=None, epoch=1):
    actions = [{"id": "read", "kind": "READ", "parameters": {}},
               {"id": "search", "kind": "SEARCH", "parameters": {}}]
    initial = state()
    call = {"status": status, "source_version": {
        "implementation_version": "milai-unified-memory-v1", "git_commit": "test-v"},
        "call_id": path.name,
        "bank": "f1", "public_message": {"message_id": "p0"},
        "source_root": str(source_root or path.parent / "runtime"),
        "captured_epoch": epoch, "request": {"query": "original"},
        "initial_observation": initial if observation else None, "initial_actions": actions}
    write(path / "call.json", call)
    prefix = []
    before = initial
    for step, (action, ok, after) in enumerate(transitions):
        prefix.append({"step": step, "before": copy.deepcopy(before), "actions": actions,
                       "selected": action, "result": {"ok": ok}})
        before = after
        if step + 1 in missing:
            continue
        target = path / "steps" / f"step-{step + 1:04d}"
        write(target / "call.json", {**call, "control_step": step + 1,
            "control_checkpoint": "control.json", "initial_observation": after})
        write(target / "control.json", {"step": step + 1, "state": after,
                                        "prefix_trace": copy.deepcopy(prefix)})
    return call


def test_range_union_does_not_treat_overlap_or_alias_reordering_as_new():
    before = state(("s", 1, 0, 5), ("s", 1, 4, 8))
    assert new_source_intervals(before, state(("s", 1, 0, 8))) == []
    assert new_source_intervals(before, state(("s", 1, 0, 10))) == [
        {"source_ref": "s", "source_revision": 1, "start": 8, "end": 10}]
    assert new_source_intervals(before, state(("s", 2, 0, 8))) == [
        {"source_ref": "s", "source_revision": 2, "start": 0, "end": 8}]


@pytest.mark.parametrize("kwargs", [{"delivered": False}, {"kind": "stored_interpretation"}])
def test_navigation_or_interpretation_metadata_is_not_raw_source_acquisition(kwargs):
    assert new_source_intervals(state(), state(("s", 1, 0, 8), **kwargs)) == []


def test_selects_new_read_transitions_not_search_or_repeated_reads(tmp_path):
    first, both = state(("a", 1, 0, 8)), state(("a", 1, 0, 8), ("b", 1, 0, 9))
    captured_call(tmp_path, [("read", True, first), ("search", True, first),
                             ("read", True, first), ("read", True, both)])
    result = select_call_prefixes(tmp_path)
    assert result["slots"]["initial"]["control_step"] == 0
    assert result["slots"]["first_read"]["control_step"] == 1
    assert result["slots"]["second_read"]["control_step"] == 4
    assert result["slots"]["same_known_changed_requirement_or_return_limit"] is None
    assert [s["new_source_read_count"] for s in result["post_state_inventory"]] == [1, 1, 1, 2]


def test_failed_read_and_changed_metadata_alone_do_not_supply_successful_slot(tmp_path):
    captured_call(tmp_path, [("read", False, state(("a", 1, 0, 8))),
                             ("search", True, state(("a", 1, 0, 8), ("b", 1, 0, 9)))],
                  status="ORIGINAL_FAILED")
    result = select_call_prefixes(tmp_path)
    assert result["original_call_status"] == "ORIGINAL_FAILED"
    assert result["slots"]["initial"] is not None
    assert result["slots"]["first_read"] is result["slots"]["second_read"] is None


def test_missing_first_checkpoint_is_not_filled_from_later_trace(tmp_path):
    captured_call(tmp_path, [("read", True, state(("a", 1, 0, 8))),
        ("read", True, state(("a", 1, 0, 8), ("b", 1, 0, 9)))], missing=(1,))
    result = select_call_prefixes(tmp_path)
    assert result["slots"]["first_read"] is None
    assert result["slots"]["second_read"]["control_step"] == 2


def test_cached_call_without_decision_and_unclosed_capture_keep_missing_slots(tmp_path):
    captured_call(tmp_path, [], observation=False)
    assert all(x is None for x in select_call_prefixes(tmp_path)["slots"].values())
    call = json.loads((tmp_path / "call.json").read_text())
    call["status"] = "CAPTURE_FAILED"
    write(tmp_path / "call.json", call)
    assert select_call_prefixes(tmp_path)["status"] == "UNCLOSED_CAPTURE_RETAINED_WITHOUT_SELECTION"
    assert acquisition_steps({"step": 0, "prefix_trace": [], "state": state()}) == []


@pytest.mark.parametrize("mutation", ["request", "state", "gap"])
def test_other_call_state_or_unrecorded_steps_cannot_be_used(tmp_path, mutation):
    captured_call(tmp_path, [("read", True, state(("a", 1, 0, 8)))])
    file = tmp_path / "steps/step-0001" / ("call.json" if mutation == "request" else "control.json")
    value = json.loads(file.read_text())
    if mutation == "request":
        value["request"] = {"query": "other"}
    elif mutation == "state":
        value["state"] = state()
    else:
        value["prefix_trace"][0]["step"] = 2
    write(file, value)
    with pytest.raises(ValueError):
        select_call_prefixes(tmp_path)


def test_collection_never_replaces_first_failed_call_with_later_success(tmp_path):
    fixture = {"histories": [{"id": family, "source_group": family, "continuous": True,
        "requests": [{"id": "p0", "content": "question"}]} for family in ("f1", "f2")]}
    declared = tmp_path / "declared.json"
    collection = tmp_path / "collection"
    write(declared, fixture)
    write(collection / "fixture.json", fixture)
    write(collection / "driver.json", {"status": "FAILED", "source_version": "test-v",
        "completed": [{"history": "f1", "policy": "fixed_context", "interface": "rich",
                       "request": "p0", "status": "FAILED", "error": "retained failure"}]})
    root = collection / "fixed_context-rich"
    write(root / "input-freeze.json", {"source_version": {
        "implementation_version": "milai-unified-memory-v1", "git_commit": "test-v"}})
    captured_call(collection / "frozen-retrieval-calls/first", [], observation=False,
                  status="ORIGINAL_FAILED", source_root=root, epoch=1)
    captured_call(collection / "frozen-retrieval-calls/second",
                  [("read", True, state(("a", 1, 0, 8)))], source_root=root, epoch=2)
    plan = {"functional_source_version": "test-v", "histories": str(declared),
            "collectors": ["fixed_context"], "mapping": [
                {"family": family, "primary_public_position": "p0"} for family in ("f1", "f2")]}
    result = select_collection_prefixes(plan, collection)
    first, missing = result["records"]
    assert first["actual_call_count"] == 2
    assert first["selection"]["original_call_status"] == "ORIGINAL_FAILED"
    assert first["selection"]["slots"]["first_read"] is None
    assert first["public_position"]["status"] == "FAILED"
    assert missing["status"] == "NO_ACTUAL_PRIMARY_CALL" and missing["selection"] is None
    assert missing["public_position"]["status"] == "NOT_EXECUTED"
    second_file = collection / "frozen-retrieval-calls/second/call.json"
    second = json.loads(second_file.read_text())
    write(second_file, {**second, "captured_epoch": 1})
    ambiguous = select_collection_prefixes(plan, collection)["records"][0]
    assert ambiguous["status"] == "FIRST_CALL_ORDER_UNKNOWN" and ambiguous["selection"] is None
    write(second_file, second)
    driver = json.loads((collection / "driver.json").read_text())
    driver["active"] = {"history": "f2", "policy": "fixed_context", "interface": "rich",
                        "request": "p0"}
    write(collection / "driver.json", driver)
    entered = select_collection_prefixes(plan, collection)["records"][1]
    assert entered["public_position"]["status"] == "ENTERED_WITHOUT_COMPLETION_RECORD"
    write(root / "input-freeze.json", {"source_version": {
        "implementation_version": "other-implementation", "git_commit": "test-v"}})
    with pytest.raises(ValueError, match="version"):
        select_collection_prefixes(plan, collection)
    plan["functional_source_version"] = "other-version"
    with pytest.raises(ValueError, match="version"):
        select_collection_prefixes(plan, collection)
