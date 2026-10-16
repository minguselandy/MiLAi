"""Matched loss changes do not alter the source text, target tokens or empty-label meaning."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from train_innovation_adapter import OBJECTIVES, render_target, token_weights


def test_exact_unicode_json_has_distinct_quality_relation_and_consequence_loss():
    target = {
        "delta": {
            "creates": [
                {
                    "nodes": [
                        {
                            "id": "n0",
                            "text": '资格须培训且凭据有效"。',
                            "basis": "e1",
                            "kind": "reported",
                        }
                    ],
                    "rules": [{"target": "n0", "all": ["n1"], "any": [["n2"]], "basis": "e1"}],
                }
            ],
            "changes": {},
        },
        "consequences": [{"card": False, "pass": None, "training": True, "eligibility": "unknown"}],
    }
    text, spans = render_target(target)
    assert json.loads(text) == target
    offsets = [(i, i + 1) for i in range(len(text))]
    weights = {objective: token_weights(offsets, spans, objective) for objective in OBJECTIVES}
    assert len({len(value) for value in weights.values()}) == 1
    claim = text.index("资格")
    rule = text.index('"n1"') + 1
    consequence = text.index("unknown")
    assert [weights[o][claim] for o in OBJECTIVES] == [1, 2, 2]
    assert [weights[o][rule] for o in OBJECTIVES] == [1, 1, 2]
    assert [weights[o][consequence] for o in OBJECTIVES] == [0, 0, 1]


def test_missing_consequence_labels_are_not_trained_as_a_true_empty_answer():
    text, spans = render_target({"delta": {"creates": [], "changes": {}}, "consequences": []})
    start = text.index("[]", text.index("consequences"))
    for objective in OBJECTIVES:
        weights = token_weights([(start, start + 2)], spans, objective)
        assert weights == [0.0]


@pytest.mark.parametrize("format_name", ["indexed_separate", "indexed_sparse"])
def test_indexed_preparation_separates_auxiliary_labels_from_native_edit_request(
    tmp_path, monkeypatch, format_name
):
    from prepare_innovation_sft import main

    path, output = tmp_path / "references.jsonl", tmp_path / "prepared.jsonl"
    row = {
        "example_id": "source-rule",
        "input": {
            "delivery": {
                "evidence": [{"id": "e1", "text": "Training and either card or pass qualify."}]
            }
        },
        "mapping": {"allow_create": True, "evidence": {"e1": {}}, "records": {}, "units": {}},
        "delta_target": {
            "creates": [
                {
                    "matter": "Qualification",
                    "nodes": [
                        {
                            "id": "n7",
                            "text": "Training is complete.",
                            "basis": "e1",
                            "kind": "reported",
                        },
                        {"id": "n9", "text": "Qualified.", "basis": "e1", "kind": "inferred"},
                    ],
                    "rules": [{"target": "n9", "all": ["n7"], "any": [[]], "basis": "e1"}],
                }
            ],
            "changes": {},
        },
        "consequence_targets": [{"training": None, "eligibility": "unknown"}],
        "provenance": {"owner": "source-rule"},
        "review": {"type": "author"},
    }
    path.write_text(json.dumps(row) + "\n")
    monkeypatch.setattr(
        sys, "argv", ["prepare", str(path), str(output), "--format", format_name]
    )
    main()
    example = json.loads(output.read_text())
    payload = json.loads(example["messages"][1]["content"])
    assert "counterfactuals" not in payload and "delta" not in example["target"]
    assert "consequences" not in example["target"]
    create = example["target"]["creates"][0]
    assert "matter" not in create and all("id" not in node for node in create["nodes"])
    assert create["rules"][0]["target"] == 1 and create["rules"][0]["all"] == [0]
    auxiliary = example["auxiliary"]
    assert json.loads(auxiliary["messages"][1]["content"])["counterfactuals"] == [
        {"training": None}
    ]
    assert auxiliary["target"] == {"consequences": row["consequence_targets"]}
    if format_name == "indexed_sparse":
        from milai_lab.methods.semantic_delta import compile_delta, indexed_target

        assert "changes" not in example["target"]
        assert compile_delta(example["target"], row["mapping"], indexed=True) == compile_delta(
            indexed_target(row["delta_target"]), row["mapping"], indexed=True)


def test_alias_augmentation_preserves_credential_target_and_remaining_training_route():
    from augment_innovation_training import augment
    from milai_lab.methods.semantic_delta import compile_delta

    lab = Path(__file__).resolve().parents[2]
    rows = [json.loads(line) for line in (
        lab / "data/fixtures/milai-innovation-matched-training-v3.jsonl").read_text().splitlines()]
    original = next(row for row in rows
                    if row["example_id"] == "innovation-harbor-transition-1-reference")
    before = json.dumps(original, ensure_ascii=False)
    augmented = augment(original, {"杜桐": "柳澈", "湾口观测站": "溪岚观测站"}, 7, "variant")
    clauses = {clause["id"]: clause for record in augmented["input"]["delivery"]["records"]
               for clause in record["clauses"]}
    proposal = compile_delta(augmented["delta_target"], augmented["mapping"])[0]
    changed = proposal["edits"][0]
    assert "柳澈" in clauses[changed["target_unit"]]["text"]
    assert "有效年证" in clauses[changed["target_unit"]]["text"]
    assert "注销" in changed["text"] and "柳澈" in changed["text"]
    route = proposal["support_groups"][0]["alternatives"][0]
    assert len(route) == 2
    route_text = [clauses[alias]["text"] for alias in route]
    assert any("安全培训" in text for text in route_text)
    assert any("通行条" in text for text in route_text)
    assert not any("年证" in text for text in route_text)
    assert json.dumps(original, ensure_ascii=False) == before
    assert augmented["provenance"]["owner"] == original["provenance"]["owner"]


def test_preferences_distinguish_real_failures_and_counterfactual_holds(tmp_path, monkeypatch):
    from milai_lab.methods.semantic_delta import compile_delta
    from prepare_innovation_preferences import prepare
    from prepare_innovation_sft import main

    lab = Path(__file__).resolve().parents[2]
    rows = [json.loads(line) for line in (
        lab / "data/fixtures/milai-innovation-matched-training-v3.jsonl").read_text().splitlines()]
    missed = next(r for r in rows if r["example_id"] == "innovation-studio-transition-3-reference")
    request = tmp_path / "request.json"
    response = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
        "creates": [], "changes": {"r1": {"replace": {}, "append": [], "withdraw": {}}}})}}]}
    request.with_name("response.json").write_text(json.dumps(response))
    missed["provenance"]["request_path"] = str(request)
    paired = prepare(missed, "The actual no-op omits the sticker change.")
    assert len(paired["rejected"]) == 1
    assert paired["rejected"][0]["target"] == {}
    assert {o["observed_model_output"] for o in paired["rejected"][0]["origins"]} == {False, True}
    assert json.loads(request.with_name("response.json").read_text()) == response
    noop = prepare(next(r for r in rows if r["example_id"] == "innovation-grant-noop-ack"))
    assert not compile_delta(noop["delta_target"], noop["mapping"])
    assert compile_delta(noop["rejected"][0]["target"], noop["mapping"], indexed=True)
    refs, output = tmp_path / "refs.jsonl", tmp_path / "sft.jsonl"
    refs.write_text(json.dumps(paired) + "\n")
    monkeypatch.setattr(sys, "argv", ["sft", str(refs), str(output), "--format", "indexed_sparse"])
    main()
    example = json.loads(output.read_text())
    assert example["rejected"] and "rejected" not in json.dumps(example["messages"])
    assert "preference_reason" not in json.dumps(example["messages"])


def test_learning_evaluation_clones_actual_state_and_restores_current_source_binding(
    tmp_path, monkeypatch
):
    from langgraph.store.sqlite import SqliteStore

    from innovation_learning_states import components, main

    prior = tmp_path / "prior"
    prior.mkdir()
    with SqliteStore.from_conn_string(str(prior / "memory.sqlite")) as store:
        service, method = components(store, prior, "prior-owner", "semantic_delta_v2")
        ref = service.capture_user("evaluation", "seed", "胶带在蓝柜。",
                                   occurred_at="2039-03-02T09:00:00+08:00")["source_ref"]
        service.bind_public_turn("evaluation", "seed", ref,
                                 config_version="learning-eval-v1", phase="start")
        view = method.writer_request(method.prepare([ref], "", selected_records=[]),
                                     request_id="seed")
        proposals = method.envelope_proposals({"creates": [{"nodes": [
            {"text": "胶带在蓝柜。", "basis": "e1", "kind": "reported"}]}]},
            view["mapping"]["mapping_id"])
        for proposal in proposals:
            receipt = method.apply("evaluation", "seed-commit", method.decode_proposal(
                proposal, view["mapping"]["mapping_id"]))
            assert receipt["ok"]
        original = service.records()
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [{"case_id": "new-update", "bank_case_id": "prior-owner",
        "before_bank": str(prior / "memory.sqlite"), "source": "胶带移到白柜。",
        "reported_at": "2039-03-03T09:00:00+08:00",
        "review_dimensions": ["hidden evaluator label"]}]}))
    root = tmp_path / "evaluation"
    common = [str(cases), str(root), "--interface", "native",
              "--maintenance-mode", "semantic_delta_v2"]
    monkeypatch.setattr(sys, "argv", ["states", *common, "--phase", "prepare"])
    main()
    prepared = json.loads((root / "inputs.jsonl").read_text())
    assert prepared["actual_before"] == original
    assert "hidden evaluator label" not in json.dumps(prepared["messages"])
    generated = tmp_path / "generations"
    generated.mkdir()
    for name, envelope in (("edit", {"changes": {"r1": {"replace": {"u1": {
        "text": "胶带已移到白柜。", "basis": "e1", "kind": "reported"}}}}}), ("empty", {})):
        (generated / f"{name}.json").write_text(json.dumps({"objective": name, "sequences": [{
            "example_id": "new-update", "finish_reason": "stop", "text": json.dumps(envelope)}]}))
    monkeypatch.setattr(sys, "argv", ["states", *common, "--phase", "apply",
                                     "--generations", str(generated)])
    main()
    results = json.loads((root / "applied-results.json").read_text())["results"]
    updated = next(row for row in results if row["objective"] == "edit")
    unchanged = next(row for row in results if row["objective"] == "empty")
    assert updated["status"] == "applied" and updated["receipts"][0]["ok"]
    assert "白柜" in updated["after"][0]["value"]["content"]
    assert unchanged["status"] == "no_change" and unchanged["after"] == original
    with SqliteStore.from_conn_string(str(prior / "memory.sqlite")) as store:
        service, _ = components(store, prior, "prior-owner", "semantic_delta_v2")
        assert service.records() == original and len(service.sources()) == 1
