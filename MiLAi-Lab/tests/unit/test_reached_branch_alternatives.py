"""Add a legal stop comparison only after material exists; old plans keep their rule."""

from collections import Counter

from feedback_choices import coverage_alternative, decision_actions, parameter_stratum
from milai_lab.harness.artifact_io import write_json
from milai_lab.methods.memory_control import MemoryControlState
from prepare_reached_feedback_branches import declared_alternative


def fixture(tmp_path, *, visible=False, observed=False):
    actions = [
        {"id": "read", "kind": "READ", "target": "source", "parameters": {"index": 0}},
        {"id": "search", "kind": "SEARCH", "target": "query", "parameters": {"limit": 16}},
        {"id": "handoff", "kind": "HANDOFF", "target": "opened", "parameters": {}},
        {
            "id": "context",
            "kind": "READ",
            "target": "source context",
            "parameters": {"index": 0, "expand_context": True},
        },
    ]
    state = MemoryControlState(
        task={"request": "facts"},
        visible_evidence=[{"kind": "original_source"}] if visible else [],
        observed_evidence=[{"kind": "original_source"}] if observed else [],
    ).project()
    write_json(tmp_path / "call.json", {"initial_observation": state, "initial_actions": actions})
    return {
        "capture": str(tmp_path),
        "argmax": actions[0],
        "baseline": actions[1],
        "raw_context": actions[1],
    }, actions


def test_existing_plan_does_not_change_and_empty_handoff_is_not_added(tmp_path):
    record, _ = fixture(tmp_path)
    assert declared_alternative(record, "fixed_context")[0] is None
    assert declared_alternative(record, "acquired_raw_delivery")[0] is None


def test_acquired_material_adds_one_actual_handoff_binding(tmp_path):
    record, actions = fixture(tmp_path, visible=True)
    assert declared_alternative(record, "fixed_context")[0] is None
    action, _ = declared_alternative(record, "acquired_raw_delivery")
    assert action == actions[2]


def test_controller_observed_material_counts_as_acquired(tmp_path):
    record, _ = fixture(tmp_path, observed=True)
    from milai_lab.harness.artifact_io import read_json

    call = read_json(tmp_path / "call.json")
    observed = {
        "id": "deliver-observed",
        "kind": "HANDOFF",
        "target": "observed material",
        "parameters": {"delivery_indices": [0]},
    }
    call["initial_actions"].append(observed)
    write_json(tmp_path / "call.json", call)
    assert declared_alternative(record, "acquired_raw_delivery")[0] == observed


def test_observation_without_an_admitted_nonempty_delivery_does_not_pad(tmp_path):
    record, _ = fixture(tmp_path, observed=True)
    assert declared_alternative(record, "acquired_raw_delivery")[0] is None


def test_same_delivery_binding_is_deduplicated_then_context_fallback_remains(tmp_path):
    record, actions = fixture(tmp_path, visible=True)
    record["argmax"] = {**actions[2], "id": "equivalent-id"}
    record["raw_context"] = actions[3]
    assert declared_alternative(record, "acquired_raw_delivery")[0] == actions[3]
    record["raw_context"] = actions[1]
    assert declared_alternative(record, "acquired_raw_delivery")[0] is None


def test_parameter_coverage_uses_legal_full_bindings_and_ignores_unknown_outcomes(tmp_path):
    from milai_lab.harness.artifact_io import read_json

    record, actions = fixture(tmp_path)
    call = read_json(tmp_path / "call.json")
    direct = {"id": "source_full_0", "kind": "READ", "target": "observed source full",
              "parameters": {"observed_source": {"source_ref": "s", "source_revision": 2,
                                                 "start": 0, "end": 800}}}
    call['initial_actions'].extend([direct, {**direct, 'id': 'observe-only',
                                           'parameters': {**direct['parameters'],
                                                          'observe_only': True}}])
    coverage = Counter({parameter_stratum(actions[3]): 8})
    before = read_json(tmp_path / 'call.json')
    chosen = coverage_alternative(call, [record['argmax'], record['baseline']], coverage, 0)
    assert chosen == direct
    call['answer'] = 'Hidden outcomes must never affect nomination'
    assert coverage_alternative(call, [record['argmax'], record['baseline']], coverage, 0) == direct
    logits = {a['id']: float(a['id'] == record['argmax']['id']) for a in call['initial_actions']}
    nominations = decision_actions(call, logits, record['baseline']['id'], [chosen['id']])
    assert len(nominations) == 3 and nominations[-1] == direct
    write_json(tmp_path / 'call.json', call)
    assert declared_alternative(record, 'parameter_coverage', coverage=coverage)[0] == direct
    # Nomination does not execute or edit any stored state.
    assert before['initial_actions'] == actions


def test_coverage_does_not_nominate_empty_handoff_as_a_material_set_alternative(tmp_path):
    from milai_lab.harness.artifact_io import read_json

    record, actions = fixture(tmp_path, visible=True)
    call = read_json(tmp_path / 'call.json')
    empty = {'id': 'empty', 'kind': 'HANDOFF', 'target': 'empty packet',
             'parameters': {'delivery_indices': []}}
    call['initial_actions'].append(empty)
    coverage = Counter({parameter_stratum(actions[3]): 10})
    action = coverage_alternative(call, [record['argmax'], record['baseline']], coverage, 0)
    assert action == actions[2]
