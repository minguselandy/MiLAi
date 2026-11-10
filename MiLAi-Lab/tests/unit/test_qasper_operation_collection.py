"""Native annotations supervise actual source ranges, never invented complete evidence."""

from types import SimpleNamespace

from collect_qasper_operation_states import (
    complete,
    covered_sources,
    reference_preferences,
    reference_proofs,
)
from milai_lab.methods.memory_control import MemoryAction


def material(ref, start=0, end=10):
    return {
        "kind": "original_source",
        "source_ranges": [{"source_ref": ref, "source_revision": 1, "start": start, "end": end}],
    }


def test_native_alternatives_unmatched_and_unanswerable_do_not_create_false_proofs():
    def annotation(groups, unanswerable=False):
        return {"answer": {"unanswerable": unanswerable}, "evidence": groups}

    a = {"status": "matched_text", "source_event_ids": ["a", "a-copy"]}
    b = {"status": "matched_text", "source_event_ids": ["b"]}
    unknown = {"status": "non_text_evidence", "source_event_ids": []}
    proofs = reference_proofs(
        {
            "annotations": [
                annotation([a, b]),
                annotation([a, unknown]),
                annotation([b], True),
                annotation([]),
            ]
        }
    )
    assert proofs == [[{"a", "a-copy"}, {"b"}]]
    assert complete(proofs, {"a-copy", "b"})
    assert not complete(proofs, {"a", "a-copy"})
    assert not complete([], {"a", "b"})


def test_partial_ranges_and_selective_handoff_keep_reference_witness():
    mapping, lengths = {"ra": "a", "rb": "b"}, {"ra": 10, "rb": 10}
    assert covered_sources([material("ra", 0, 5)], mapping, lengths) == set()
    assert covered_sources([material("ra", 0, 5), material("ra", 5, 10)], mapping, lengths) == {"a"}
    operations = SimpleNamespace(
        opened={0: material("ra"), 1: material("rb")},
        observed={0: material("ra"), 1: material("rb")},
    )
    actions = [
        MemoryAction("all", "HANDOFF", "current"),
        MemoryAction("drop_b", "HANDOFF", "selected", {"delivery_indices": [0]}),
        MemoryAction("read", "READ", "candidate", {"index": 2}),
    ]
    accepted, status = reference_preferences(
        actions, operations, [[{"a"}, {"b"}]], mapping, lengths
    )
    assert accepted == ["all"] and status == "reference_preserving_handoff"
    assert reference_preferences(actions, operations, [], mapping, lengths)[0] == []


def test_already_observed_support_can_be_handed_off_even_if_default_delivery_missed_it():
    mapping, lengths = {"ra": "a", "rb": "b"}, {"ra": 10, "rb": 10}
    operations = SimpleNamespace(opened={0: material("ra")},
                                 observed={0: material("ra"), 1: material("rb")})
    actions = [MemoryAction("current", "HANDOFF", "current"),
               MemoryAction("select_b", "HANDOFF", "selected", {"delivery_indices": [1]})]
    accepted, status = reference_preferences(actions, operations, [[{"b"}]], mapping, lengths)
    assert accepted == ["select_b"] and status == "reference_preserving_handoff"
