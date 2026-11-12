"""Complementary delivery comparisons use only already-offered complete legal bindings."""
from milai_lab.methods.memory_control import MemoryAction
from prepare_collected_handoff_comparison import complementary_deliveries


def action(name, indices):
    return MemoryAction(name, "HANDOFF", "selected acquired material",
                        {"delivery_indices": indices})


def test_legal_union_and_empty_control_use_actual_ids_not_array_positions():
    actions = [action("empty", []), action("a", [7]), action("b", [12]), action("ba", [12, 7]),
               action("other", [3]), MemoryAction("read", "READ", "new source", {})]
    assert complementary_deliveries(actions) == {
        "material_a": "a", "material_b": "b", "material_a_b": "ba", "empty_delivery": "empty"}


def test_nonfitting_union_is_never_fabricated_and_single_material_is_not_complementary():
    assert complementary_deliveries([action("a", [1]), action("b", [2])]) == {}
    assert complementary_deliveries([action("a", [1])]) == {}
