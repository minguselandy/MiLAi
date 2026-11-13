"""Missing reference proofs and incomplete readouts must not become semantic negatives."""

import pytest

from compile_collected_operation_feedback import compile_case, witness_relation


@pytest.mark.parametrize(
    "left,right,expected",
    [
        (True, True, "tie"),
        (True, False, "left"),
        (False, True, "right"),
        (False, False, "unknown"),
        (None, False, "unknown"),
        (True, None, "unknown"),
    ],
)
def test_witness_proxy_preserves_unknown(left, right, expected):
    assert witness_relation(left, right) == expected


def test_semantic_reviews_do_not_inherit_witness_labels_or_failed_answers():
    row = {
        "gold": {},
        "metadata": {},
        "state": {},
        "questions": {"next": {"criteria": {"a": "READ", "b": "HANDOFF"}}},
    }
    branches = [
        {
            "action": {"id": key},
            "reference_proof_complete": value,
            "readout_status": status,
            "readout": key,
        }
        for key, value, status in [("a", True, "FAILED"), ("b", False, "COMPLETED")]
    ]
    proxy = compile_case(row, branches)
    assert proxy["feedback"]["comparisons"][0]["delivery"] == "left"
    reviews = {
        "a": {"answer_status": "complete", "material_status": "sufficient"},
        "b": {"answer_status": "incomplete", "material_status": "sufficient"},
    }
    semantic = compile_case(row, branches, reviews)
    pair = semantic["feedback"]["comparisons"][0]
    assert pair["delivery"] == "tie" and pair["answer"] == "unknown"
    missing = compile_case(row, branches, {})
    assert missing["feedback"]["comparisons"][0]["delivery"] == "unknown"
    assert "feedback" not in row


def test_query_once_continuation_preserves_executed_known_query_pool():
    from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
    from prepare_collected_operation_feedback import QueryOnceContextPolicy

    policy = QueryOnceContextPolicy()
    state = MemoryControlState(
        task={},
        last_result={"action": {"kind": "SEARCH", "parameters": {"query_from": "known_material"}}},
    )
    actions = [
        MemoryAction("search", "SEARCH", "original query"),
        MemoryAction("read", "READ", "returned candidate", {"index": 0}),
        MemoryAction("handoff", "HANDOFF", "packet"),
    ]
    assert policy.choose(state, actions) == "read"
    state.last_result = {"action": {"kind": "READ"}}
    assert policy.choose(state, actions) == "read"
    assert policy.choose(state, [actions[0], actions[2]]) == "handoff"


def test_query_once_continuation_can_search_after_an_observed_source_first_read():
    from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
    from prepare_collected_operation_feedback import QueryOnceContextPolicy

    policy = QueryOnceContextPolicy()
    state = MemoryControlState(task={}, last_result={"action": {"kind": "READ"}})
    actions = [
        MemoryAction("search", "SEARCH", "original query"),
        MemoryAction("handoff", "HANDOFF", "packet"),
    ]
    assert policy.choose(state, actions) == "search"
    state.last_result = {"action": {"kind": "SEARCH"}}
    assert policy.choose(state, actions) == "handoff"


def test_multiple_requests_stay_in_the_original_source_family():
    from prepare_collected_operation_feedback import request_units, select_events

    histories = [{"source_group": "paper-a", "requests": [{"id": "q0"}, {"id": "q1"}]},
                 {"source_group": "paper-b", "requests": [{"id": "q0"}]}]
    units = request_units(histories, 4)
    assert [(i, h["source_group"], q["id"]) for i, h, q in units] == [
        (4, "paper-a", "q0"), (4, "paper-a", "q1"), (5, "paper-b", "q0")]
    for i, _, request in units:
        initial = {"step": 0, "request_id": request["id"]}
        assert select_events([initial], i) == [initial]
    with pytest.raises(ValueError, match="family, request_id"):
        select_events([{"step": 0}, {"step": 0}], 0)


def test_legal_stop_nomination_is_opt_in_and_keeps_complete_binding(monkeypatch):
    from collections import Counter

    import prepare_collected_operation_feedback as preparation

    event = {"before": {}, "prediction": {"logits": {"read": 2., "stop": 1.}},
             "actions": [{"id": "read", "kind": "READ", "target": "source",
                          "parameters": {"observed_source": {"start": 4, "end": 8}}},
                         {"id": "stop", "kind": "HANDOFF", "target": "actual packet",
                          "parameters": {}}]}
    monkeypatch.setattr(preparation, "baseline", lambda *args: "read")
    monkeypatch.setattr(preparation, "coverage_alternative", lambda *args: None)
    assert set(preparation.nominate(event, Counter(), 0).values()) == {"read"}
    selected = preparation.nominate(event, Counter(), 0, include_legal_handoff=True)
    assert set(selected.values()) == {"read", "stop"}
    assert selected["legal_stop"] == "stop"


def test_incremental_case_stream_keeps_completed_bindings_between_full_snapshots(tmp_path):
    import json

    from prepare_collected_operation_feedback import append_completed_case

    cases = [{"event_id": "f/q0/0", "branches": [{"action": {"id": "a"}, "text": "A\u2028B"}]},
             {"event_id": "f/q1/0", "branches": [], "status": "SINGLETON_NOT_EXECUTED"}]
    for case in cases:
        append_completed_case(tmp_path, case)
    with (tmp_path / "completed-cases.jsonl").open() as stream:
        assert [json.loads(line) for line in stream] == cases
    assert not (tmp_path / "cases.json").exists()


@pytest.mark.parametrize("explicit_controls", [False, True])
@pytest.mark.parametrize("evaluation_only,changed_original", [(True, False), (False, False),
                                                           (False, True)])
def test_closed_dev_binding_keeps_native_controls_and_failed_first_without_train_export(
        tmp_path, monkeypatch, explicit_controls, evaluation_only, changed_original):
    import json

    from compile_collected_operation_feedback import main

    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    prepared, readouts, collection, output = [tmp_path / x for x in (
        "prepared", "readouts", "collection", "output")]
    controls = tmp_path / "original-controls.jsonl"
    split = "dev" if evaluation_only else "train"
    control = {"source_group": "f", "request_id": "q", "split": split,
               "native_answerable": False, "native_answer": "Original answer",
               "native_answer_aliases": ["Alias"]}
    controls.write_text(json.dumps(control) + "\n")
    save(collection / "run.json", {} if explicit_controls else {"controls": str(controls)})
    row = {"gold": {}, "state": {}, "questions": {"next": {"criteria": {"a": "HANDOFF"}}},
           "metadata": {"event_id": "f/q/0", "family": "f", "split": split,
                        "state_id": 0, "row": 0}}
    prepared.mkdir()
    (prepared / "states.jsonl").write_text(json.dumps(row) + "\n")
    if not evaluation_only:
        original = {**row, "state": {"changed": True}} if changed_original else row
        (collection / "states.jsonl").write_text(json.dumps(original) + "\n")
    action = {"id": "a", "kind": "HANDOFF", "target": "actual packet", "parameters": {}}
    wire = {"messages": [{"role": "user", "content": "Original question"}]}
    save(prepared / "cases.json", [{"state_index": 0, "event_id": "f/q/0", "family": "f",
        "request_id": "q", "case_key": "case", "before": {"task": {"request": "Original question"}},
        "branches": [{"policies": ["full"], "action": action, "readout_request": wire,
                      "reference_proof_complete": None, "execution_result": {"ok": True}}]}])
    save(prepared / "run.json", {"status": "COMPLETED", "collection": str(collection),
        "continuation_policy": "fixed_context", "continuation_steps": 0})
    path = readouts / "first.json"
    request = readouts / "request.json"
    save(request, wire)
    save(path, {"event_id": "f/q/0", "family": "f", "action": action,
                "request": str(request), "status": "FAILED", "answer": None})
    save(readouts / "readout-paths.json", {"full": {"case": str(path)}})
    save(readouts / "run.json", {"status": "COMPLETED_WITH_FAILURES", "prepared": str(prepared)})
    argv = ["compile", str(prepared), str(readouts), str(output)]
    if evaluation_only:
        argv += ["--evaluation-only"]
    if explicit_controls:
        argv += ["--controls", str(controls)]
    monkeypatch.setattr("sys.argv", argv)
    if changed_original:
        with pytest.raises(ValueError, match="actual model input"):
            main()
        assert not output.exists()
        return
    main()
    bound = json.loads((output / "review-inputs.json").read_text())[0]
    assert bound["native_control"] == control
    assert bound["branches"][0]["readout_status"] == "FAILED"
    assert bound["branches"][0]["readout"] == str(path.resolve())
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["controls"] == str(controls.resolve())
    assert manifest["training_exports_written"] is (not evaluation_only)
    assert manifest["source_matched_sft_constructed"] is (not evaluation_only)
    assert (output / "feedback-dev.jsonl").is_file() is evaluation_only
    assert (output / "delivery-known-fit.jsonl").exists() is (not evaluation_only)
