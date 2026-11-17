"""Conditional unit boundaries, literal provenance and actual parent revocation."""

import copy
import json

import pytest

from milai_lab.methods.query_structure_projection import project_structure_units


def conditional_packet():
    nodes = {
        "n0": (
            "Whether training is complete is unknown; a question is not confirmation.",
            "uncertain",
            "e0",
        ),
        "n1": (
            "Permit validity is reported only until 2032-04-30; no later validity asserted.",
            "reported",
            "e0",
        ),
        "n2": ("Whether an exception waiver was approved is unknown.", "uncertain", "e0"),
        "n3": ("The sponsor reports approval, without confirming execution.", "reported", "e0"),
        "n4": (
            "Entry is allowed only if training AND (permit OR waiver AND sponsor) hold.",
            "inferred",
            "e0",
        ),
        "n5": (
            "Even if eligible, suspension overrides entry; this is not an executed denial.",
            "inferred",
            "e1",
        ),
        "n6": ("Whether suspension is effective after 2032-05-01 is unknown.", "uncertain", "e1"),
        "n7": (
            "An independent fee report e10 says 40; it does not assert payment.",
            "reported",
            "e10",
        ),
        "n8": ("An unrelated room preference remains tentative.", "reported", "e11"),
    }
    aliases = ["e0", "e1", "e10", "e11"]
    return {
        "label": "e3",
        "kind": "query_structure",
        "revision": 7,
        "query_time": "2032-05-02",
        "semantics": "source_bound_model_interpretation; unknown is not false",
        "interpretation": {
            "scope": "Entry conditions, fee report and tentative room preference",
            "unresolved": ["No current entry or payment execution has been established."],
            "nodes": {
                k: {
                    "text": text,
                    "kind": kind,
                    "evidence": [alias],
                    "temporal": (
                        "Use literal effective dates; report/ingestion clocks are not event dates."
                    ),
                }
                for k, (text, kind, alias) in nodes.items()
            },
            "rules": {
                "g0": {
                    "target": "n4",
                    "all": ["n0"],
                    "any": [["n1"], ["n2", "n3"]],
                    "evidence": ["e0"],
                },
                "g1": {"target": "n5", "all": ["n4"], "any": [["n6"]], "evidence": ["e1"]},
            },
        },
        "source_bindings": {a: "support_not_opened" for a in aliases},
        "source_locations": {
            a: {"source_ref": f"opaque-source-{a}", "source_revision": 2} for a in aliases
        },
        "source_metadata": {
            "shared": {"reported_at": None, "captured_at": "2032-05-02T12:00:00Z"},
            "by_alias": {
                a: {"role": "user" if a == "e0" else "tool", "origin": "fixture"} for a in aliases
            },
        },
    }


@pytest.mark.parametrize("requested", [["n4"], ["n0"], ["n6"], ["n3", "n3"]])
def test_all_routes_and_reverse_exception_context_stay_whole(requested):
    packet = conditional_packet()
    original = copy.deepcopy(packet)
    out = project_structure_units(packet, requested)
    assert list(out["interpretation"]["nodes"]) == [f"n{i}" for i in range(7)]
    assert out["interpretation"]["rules"] == packet["interpretation"]["rules"]
    for key, node in out["interpretation"]["nodes"].items():
        assert node == original["interpretation"]["nodes"][key]
    assert out["interpretation"]["unresolved"] == original["interpretation"]["unresolved"]
    assert out["source_metadata"]["shared"] == original["source_metadata"]["shared"]
    assert set(out["source_bindings"]) == {"e0", "e1"}
    assert out["unit_projection"]["known_rule_graph_closed"] is True
    assert out["unit_projection"]["semantic_completeness"] == "not_certified"
    assert packet == original
    out["interpretation"]["nodes"]["n0"]["text"] = "mutated copy"
    assert packet == original


@pytest.mark.parametrize("routes", [[], [[]], [["n1"], []]])
def test_empty_route_does_not_collapse_into_no_route(routes):
    packet = conditional_packet()
    packet["interpretation"]["rules"]["g0"]["any"] = routes
    out = project_structure_units(packet, ["n4"])
    assert out["interpretation"]["rules"]["g0"]["any"] == routes
    assert out["interpretation"]["nodes"]["n0"]["kind"] == "uncertain"


def test_cycle_terminates_without_evaluating_unknown_premises():
    packet = conditional_packet()
    packet["interpretation"]["rules"]["g2"] = {
        "target": "n0",
        "all": ["n5"],
        "any": [[]],
        "evidence": ["e0"],
    }
    out = project_structure_units(packet, ["n4"])
    assert set(out["interpretation"]["rules"]) == {"g0", "g1", "g2"}
    assert out["interpretation"]["nodes"]["n0"] == packet["interpretation"]["nodes"]["n0"]


def test_prose_aliases_and_global_qualifications_survive_without_prefix_collisions():
    packet = conditional_packet()
    out = project_structure_units(packet, ["n7"])
    assert list(out["source_bindings"]) == ["e10"]  # e1 is not a substring reference.
    packet["interpretation"]["unresolved"].append("Do not treat e1 as confirmed execution.")
    packet["producer_note"] = "The uncertainty in e11 also remains applicable."
    out = project_structure_units(packet, ["n7"])
    assert list(out["source_bindings"]) == ["e1", "e10", "e11"]
    assert set(out["source_locations"]) == set(out["source_bindings"])
    assert set(out["source_metadata"]["by_alias"]) == set(out["source_bindings"])
    assert out["producer_note"] == packet["producer_note"]


def test_full_selection_is_literal_identity_and_empty_selection_is_explicitly_partial():
    packet = conditional_packet()
    assert project_structure_units(packet, list(packet["interpretation"]["nodes"])) == packet
    empty = project_structure_units(packet, [])
    assert empty["interpretation"]["nodes"] == empty["interpretation"]["rules"] == {}
    assert empty["interpretation"]["unresolved"] == packet["interpretation"]["unresolved"]
    assert empty["unit_projection"]["partial"] is True
    assert empty["unit_projection"]["parent_node_count"] == 9


def test_global_and_linked_metadata_aliases_remain_available_without_new_bodies():
    packet = conditional_packet()
    packet["source_metadata"]["shared"]["note"] = "The uncertainty in e1 remains relevant."
    packet["source_metadata"]["by_alias"]["e1"]["note"] = "Context also refers to e11."
    packet["source_metadata"]["by_alias"]["e11"]["note"] = "This cycles back to e1."
    out = project_structure_units(packet, ["n7"])
    assert list(out["source_bindings"]) == ["e1", "e10", "e11"]
    assert set(out["source_bindings"].values()) == {"support_not_opened"}
    assert "evidence" not in out


@pytest.mark.parametrize(
    "fault", ["dangling_rule", "omitted_alias", "missing_node", "unavailable", "raw_store_view"]
)
def test_invalid_or_unavailable_parent_cannot_be_hidden_by_selection(fault):
    packet = conditional_packet()
    requested = ["n4"]
    if fault == "dangling_rule":
        packet["interpretation"]["rules"]["g0"]["any"].append(["absent"])
    elif fault == "omitted_alias":
        packet["interpretation"]["nodes"]["n8"]["evidence"] = ["absent"]
    elif fault == "missing_node":
        requested = ["absent"]
    elif fault == "unavailable":
        packet.update(visibility="support_unavailable", body_delivered=False)
    else:
        packet["structure"] = packet.pop("interpretation")
    with pytest.raises(ValueError):
        project_structure_units(packet, requested)


def test_literal_table_encoding_can_follow_partial_units_but_not_precede_them():
    from milai_lab.methods.evidence_reading import expand_view_tables, project_view_tables

    packet = conditional_packet()
    for i in range(9, 35):
        packet["interpretation"]["nodes"][f"n{i}"] = {
            "text": f"Independent whole report {i}; execution unknown.",
            "kind": "uncertain",
            "evidence": ["e0"],
            "temporal": packet["interpretation"]["nodes"]["n0"]["temporal"],
        }
    out = project_structure_units(packet, ["n4", *[f"n{i}" for i in range(9, 35)]])
    tables = project_view_tables([out])
    assert "literal_map_tables" in tables[0]
    assert expand_view_tables(json.loads(json.dumps(tables))) == [out]
    with pytest.raises(ValueError, match="plain"):
        project_structure_units(tables[0], ["n4"])


def test_actual_parent_visibility_is_checked_before_any_partial_reader_projection(tmp_path):
    from langgraph.store.sqlite import SqliteStore

    from milai_lab.memory.service import MemoryService
    from milai_lab.methods.evidence_reading import open_evidence_packs, project_packs
    from milai_lab.methods.query_structure import build_query_structure

    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(
            store,
            ("partial", "alice"),
            "alice",
            tmp_path / "lock",
            functional_contract="functional_v1",
        )
        ref = service.capture_user("s", "rule", "Entry only if training and permit are valid.")[
            "source_ref"
        ]
        other = service.capture_user("s", "other", "Room preference remains tentative.")[
            "source_ref"
        ]

        def call(messages, _schema):
            sources = json.loads(messages[1]["content"])["sources"]
            first, second = sources[0]["id"], sources[1]["id"]
            return {
                "scope": "Entry and room",
                "nodes": [
                    {
                        "id": "n0",
                        "text": "Whether training is valid is unknown.",
                        "kind": "uncertain",
                        "evidence": [first],
                    },
                    {
                        "id": "n1",
                        "text": "Whether permit is valid is unknown.",
                        "kind": "uncertain",
                        "evidence": [first],
                    },
                    {
                        "id": "n2",
                        "text": (
                            "Entry only if training and permit are valid; no execution established."
                        ),
                        "kind": "inferred",
                        "evidence": [first],
                    },
                    {
                        "id": "n3",
                        "text": "Room preference remains tentative.",
                        "kind": "reported",
                        "evidence": [second],
                    },
                ],
                "rules": [
                    {
                        "id": "g0",
                        "target": "n2",
                        "all": ["n0"],
                        "any": [["n1"]],
                        "evidence": [first],
                    }
                ],
                "remove": [],
                "remove_rules": [],
                "unresolved": ["Current entry is unknown."],
            }

        view, _ = build_query_structure(
            service, "Entry?", "2032-05-02", [ref, other], policy="incremental", call=call
        )
        opened = open_evidence_packs(service, [view])
        packet = project_packs(opened, [0])[0]
        partial = project_structure_units(packet, ["n2"])
        assert list(partial["interpretation"]["nodes"]) == ["n0", "n1", "n2"]
        handles = [x["fragment_handle"] for x in service.source_fragments(other)]
        assert service.forget("s", "withdraw-unselected-parent-source", fragment_handles=handles)[
            "ok"
        ]
        unavailable = project_packs(open_evidence_packs(service, [view]), [0])[0]
        assert unavailable["visibility"] == "support_unavailable"
        assert "interpretation" not in unavailable
        with pytest.raises(ValueError, match="visible"):
            project_structure_units(unavailable, ["n2"])
