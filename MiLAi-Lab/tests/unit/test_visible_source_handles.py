"""Visible reference aliases preserve source facts, graph links, and original execution bindings."""
import copy

from milai_lab.methods.control_observation import control_texts, visible_source_handle_input

A = "source-00000000-0000-4000-8000-000000000001"
B = "source-00000000-0000-4000-8000-000000000002"
C = "source-00000000-0000-4000-8000-000000000003"


def example():
    return {"observation": {"task": {"request": "Find the relevant document"},
        "new_events": [{"source_ref": A, "content": "Alpha literal fact"},
                       {"source_ref": B, "content": "Beta literal fact"}],
        "by_source": {A: {"note": "same graph object"}},
        "observed_materials": [{"item_index": 0,
            "id": 'observed-source:{"source_ref":"' + A + '","start":0,"end":17}'}],
        "visible_evidence": [], "pending_candidates": [],
        "last_result": {"action": {"id": "previous", "kind": "READ", "target": A,
            "parameters": {"observed_source": {"source_ref": A, "source_revision": 2}}}}},
        "actions": [{"id": "read-b", "kind": "READ", "target": f"Read {B}",
            "parameters": {"observed_source": {"source_ref": B, "start": 3, "end": 19}}},
            {"id": "stop", "kind": "HANDOFF", "target": "Reader", "parameters": {}}],
        "offline_supervision": {"SECRET": C}, "provenance": {"SECRET": True}}


def replace_refs(value, replacements):
    if isinstance(value, dict):
        return {replace_refs(k, replacements): replace_refs(v, replacements)
                for k, v in value.items()}
    if isinstance(value, list):
        return [replace_refs(v, replacements) for v in value]
    if isinstance(value, str):
        for old, new in replacements.items():
            value = value.replace(old, new)
    return value


def test_visible_reference_alpha_renaming_keeps_facts_links_and_original_bindings():
    row = example()
    original = copy.deepcopy(row)
    projected = visible_source_handle_input(row)
    # Simultaneous bijection, including the structural dictionary key.
    other = replace_refs(row, {A: "source-00000000-0000-4000-8000-000000000004",
                               B: "source-00000000-0000-4000-8000-000000000005"})
    assert projected == visible_source_handle_input(other)
    assert projected == visible_source_handle_input(replace_refs(row, {A: "object-alpha",
                                                                     B: "object-beta"}))
    assert set(projected) == {"observation", "actions"} and "SECRET" not in str(projected)
    refs = [event["source_ref"] for event in projected["observation"]["new_events"]]
    assert refs == ["@source-handle:0", "@source-handle:1"]
    assert projected["observation"]["by_source"][refs[0]] == {"note": "same graph object"}
    assert A not in projected["observation"]["observed_materials"][0]["id"]
    assert projected["actions"][0]["parameters"]["observed_source"] == {
        "source_ref": refs[1], "start": 3, "end": 19}
    assert row == original and row["actions"][0]["parameters"]["observed_source"]["source_ref"] == B


def test_literal_identifiers_and_unobserved_binding_only_references_are_retained():
    row = example()
    row["observation"]["task"]["request"] += " exact token " + A
    row["observation"]["new_events"][1]["content"] += " reference " + B
    row["actions"].append({"id": "other", "kind": "READ", "target": C,
                           "parameters": {"observed_source": {"source_ref": C}}})
    projected = visible_source_handle_input(row)
    assert projected["observation"]["new_events"] == row["observation"]["new_events"]
    assert projected["observation"]["task"] == row["observation"]["task"]
    assert projected["actions"] == row["actions"]


def test_dictionary_order_menu_permutation_idempotence_and_alias_collisions():
    row = example()
    row["observation"]["new_events"][0]["content"] += " literal @source-handle:0"
    projected = visible_source_handle_input(row)
    assert projected["observation"]["new_events"][0]["source_ref"] == "@source-handle:1"
    assert visible_source_handle_input(projected) == projected
    changed = copy.deepcopy(row)
    changed["observation"] = dict(reversed(list(changed["observation"].items())))
    changed["actions"].reverse()
    state, actions = control_texts(projected)
    changed_state, changed_actions = control_texts(visible_source_handle_input(changed))
    assert state == changed_state and actions[::-1] == changed_actions
