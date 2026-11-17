"""Behavioral boundaries of neutral scoring and genuinely sparse feedback."""
import copy

import pytest

from milai_lab.methods.control_observation import control_input, control_texts, legacy_control_input
from milai_lab.methods.laya_memory_policy import operation_payload
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState, run_memory_control
from milai_lab.methods.small_memory_policy import PolicyScores, SmallMemoryPolicy


def test_online_allowlist_and_action_alias_invariance():
    state = MemoryControlState(task={"request": "Whose limit applies?"},
        pending_candidates=[{"item_index": 0, "excerpt": "A only; B excluded"}])
    actions = [MemoryAction("r", "READ", "candidate", {"index": 0, "observe_only": True}),
               MemoryAction("h", "HANDOFF", "Reader", {"delivery_indices": [2]})]
    online = control_input(state, actions)
    record = {**online, "offline_supervision": {"reference": "SECRET"},
              "sample_id": "SECRET", "group_id": "SECRET"}
    original = copy.deepcopy(record)
    assert control_texts(record) == control_texts(online)
    renamed = copy.deepcopy(online)
    renamed["actions"].reverse()
    for i, action in enumerate(renamed["actions"]):
        action["id"] = f"renamed-{i}"
    state_text, texts = control_texts(online)
    assert control_texts(renamed) == (state_text, texts[::-1])
    assert "SECRET" not in str(control_texts(record))
    assert '"observe_only":true' in texts[0] and '"delivery_indices":[2]' in texts[1]
    assert record == original
    legacy = {**operation_payload(state, actions), "metadata": {
        "action_kinds": {a.id: a.kind for a in actions},
        "action_parameters": {a.id: a.parameters for a in actions}}, "gold": {"SECRET": 1}}
    assert legacy_control_input(legacy) == online


def test_real_selection_and_forced_state_do_not_invent_model_calls():
    class Scorer:
        calls = 0

        def score(self, online):
            self.calls += 1
            return PolicyScores([a["id"] for a in online["actions"]], [1., 2.])

    class Operations:
        def actions(self, state):
            return [MemoryAction("read", "READ", "c", {"index": 7}),
                    MemoryAction("handoff", "HANDOFF", "Reader")]

        def execute(self, action, state):
            raise AssertionError("Selected HANDOFF should not execute a READ")

    scorer = Scorer()
    policy = SmallMemoryPolicy(scorer)
    result = run_memory_control(MemoryControlState(task={}), policy, Operations())
    assert result["reason"] == "policy_handoff" and scorer.calls == 1
    assert result["trace"][0]["actions"][0]["parameters"] == {"index": 7}
    ops = Operations()
    ops.actions = lambda state: [MemoryAction("stop", "HANDOFF", "Reader")]
    result = run_memory_control(MemoryControlState(task={}), policy, ops)
    assert result["trace"][0]["selection_mode"] == "only_available_action"
    assert scorer.calls == 1


def test_sparse_loss_masks_unobserved_unknown_forced_and_empty_windows():
    torch = pytest.importorskip("torch")
    from milai_lab.methods.small_control_learning import state_loss, window_loss

    scores = torch.tensor([.1, -.1, 100.], requires_grad=True)
    supervision = {"observed_action_ids": ["a", "b"], "preferences": [
        {"left": "a", "right": "b", "outcome": "left"},
        {"left": "a", "right": "b", "outcome": "unknown"}]}
    loss = state_loss(scores, ["a", "b", "unobserved"], supervision)
    loss.backward()
    assert scores.grad[2] == 0 and scores.grad[0] < 0 and scores.grad[1] > 0
    assert state_loss(scores[:1], ["forced"], {}) is None
    assert state_loss(scores, ["a", "b", "u"], {"preferences": []}) is None
    assert window_loss([None, None], [1., 2.]) == (None, 0.)
    with pytest.raises(ValueError, match="actually observed"):
        state_loss(scores, ["a", "b", "u"], {**supervision, "observed_action_ids": ["a"]})


def test_accumulation_uses_global_valid_source_weight_and_not_microbatch_means():
    torch = pytest.importorskip("torch")
    from milai_lab.methods.small_control_learning import window_loss

    theta = torch.tensor(.3, requires_grad=True)
    terms = [(theta - target) ** 2 for target in [0., 1., 3.]]
    objective, denominator = window_loss([terms[0], None, terms[1], terms[2]], [1., 100., .5, .5])
    gradient = torch.autograd.grad(objective, theta, retain_graph=True)[0]
    # Two microbatches use the same window denominator, including an empty label slot.
    accumulated = torch.autograd.grad(terms[0] / denominator, theta, retain_graph=True)[0]
    accumulated += torch.autograd.grad((terms[1] * .5 + terms[2] * .5) / denominator, theta)[0]
    assert denominator == 2. and torch.allclose(gradient, accumulated)


def test_independent_and_set_heads_preserve_candidate_permutation():
    torch = pytest.importorskip("torch")
    from milai_lab.methods.small_control_model import build_action_head

    for interaction in (False, True):
        head = build_action_head(4, 8, set_interaction=interaction)
        states, actions = torch.randn(2, 4), torch.randn(5, 4)
        owners = torch.tensor([0, 0, 1, 1, 1])
        order = torch.tensor([1, 0, 4, 2, 3])
        original = head(states, actions, owners)
        permuted = head(states, actions[order], owners[order])
        assert torch.allclose(original[order], permuted, atol=1e-6)


def test_calibration_keeps_offline_expectations_separate_and_literal_positive_is_accepted():
    import json
    from collections import Counter

    from milai_lab.methods.control_calibration import calibration_cases
    from review_collected_operation_outcomes import parse_review

    cases = calibration_cases()
    assert len(cases) == 200 and len({c["sample_id"] for c in cases}) == 200
    assert Counter(c["stratum"] for c in cases) == {
        "complete": 40, "incomplete": 40, "incorrect": 40, "failed": 40, "unknown": 40}
    assert "expected" not in json.dumps([c["payload"] for c in cases])
    case = cases[0]
    source = case["payload"]["candidates"][0]["delivered_evidence"][0]["evidence"][0]["content"]
    review = {"reviews": [{"candidate": "candidate-A", "material_status": "sufficient",
        "answer_status": "complete", "answer_support": "supported",
        "evidence_quotes": [source], "rationale": "Both exact fields occur in the record."}]}
    parsed = parse_review(json.dumps(review), case["payload"])
    assert parsed["masked_candidates"] == 0 and parsed["reviews"][0]["answer_status"] == "complete"
    review["reviews"][0]["evidence_quotes"] = ["An invented value absent from this source"]
    assert parse_review(json.dumps(review), case["payload"])["masked_candidates"] == 1


def test_joint_readout_has_one_real_decoder_forward_and_ragged_binding_alignment():
    import json

    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    from milai_lab.memory.literal_projection import expand_observation_state
    from milai_lab.methods.control_observation import joint_control_texts
    from milai_lab.methods.small_control_model import (
        SmallControlConfig,
        SmallControlModel,
        build_action_head,
    )

    class Tokenizer:
        def encode(self, text, **kwargs):
            return [value + 1 for value in text.encode()]

        def pad(self, rows, **kwargs):
            width = max(len(row["input_ids"]) for row in rows)
            ids = torch.tensor([row["input_ids"] + [0] * (width - len(row["input_ids"]))
                                for row in rows])
            return transformers.BatchEncoding({"input_ids": ids,
                                               "attention_mask": ids.ne(0).long()})

    model = SmallControlModel.__new__(SmallControlModel)
    model.config = SmallControlConfig("decoder", "tiny-local-test", readout="joint",
                                      joint_max_tokens=8192)
    model.device = torch.device("cpu")
    model.tokenizer = Tokenizer()
    model.encoder = transformers.Qwen3Model(transformers.Qwen3Config(vocab_size=258,
        hidden_size=16, intermediate_size=32, num_hidden_layers=1,
        num_attention_heads=2, num_key_value_heads=2, head_dim=8))
    model.head = build_action_head(16, 8)
    model.counters = dict(forwards=0, input_tokens=0, padded_tokens=0, joint_sequences=0, texts=0)
    actions = [MemoryAction("SECRET-READ", "READ", "candidate", {"index": 3}),
               MemoryAction("SECRET-STOP", "HANDOFF", "Reader", {"delivery_indices": [2]})]
    row = control_input(MemoryControlState(task={"request": "Which source applies?"}), actions)
    prefix, _ = joint_control_texts({**row, "offline_supervision": {"reference": "SECRET"}})
    assert "SECRET" not in prefix
    shared = json.loads(prefix.split("State and complete action bindings:\n")[1].split(
        "\nScore each offered binding:\n")[0])
    assert isinstance(shared, dict)  # JSON text must not be serialized a second time.
    old_prefix, _ = joint_control_texts(row, wrapped_json=True)
    old_body = old_prefix.split("State and complete action bindings:\n")[1].split(
        "\nScore each offered binding:\n")[0]
    assert isinstance(json.loads(old_body), str)
    restored = expand_observation_state(shared)["action_bindings"]
    assert restored[0]["parameters"] == {"index": 3}
    assert restored[1]["parameters"] == {"delivery_indices": [2]}
    other = copy.deepcopy(row)
    other["actions"] = other["actions"][:1]
    forwards = []
    hook = model.encoder.register_forward_hook(lambda *args: forwards.append(1))
    state, candidates, owners, lengths = model.features([row, other])
    hook.remove()
    scores = model.head(state, candidates, owners)
    scores.sum().backward()
    assert len(forwards) == 1 and model.counters["forwards"] == 1
    assert lengths == [2, 1] and owners.tolist() == [0, 0, 1] and scores.shape == (3,)
    assert model.encoder.embed_tokens.weight.grad.abs().sum() > 0
    model.config.joint_max_tokens = 8
    with pytest.raises(ValueError, match="no tokens dropped"):
        model.features([row])


def test_unknown_calibration_revision_preserves_all_other_first_response_inputs():
    from milai_lab.methods.control_calibration import calibration_cases

    original = {c["sample_id"]: c for c in calibration_cases("literal_v1")}
    revised = calibration_cases("missing_fact_v2")
    reusable, novel = [], []
    for case in revised:
        if case["sample_id"] in original:
            assert case["payload"] == original[case["sample_id"]]["payload"]
            reusable.append(case)
        else:
            assert case["stratum"] == "unknown"
            assert case["expected"]["answer_status"] == "unknown"
            assert case["expected"]["material_status"] == "insufficient"
            assert case["payload"]["candidates"][0]["answer_status"] == "COMPLETED"
            novel.append(case)
    assert len(reusable) == 160 and len(novel) == 40


def test_resume_keeps_the_interrupted_invocation_cost_record(tmp_path):
    import json

    from training_recovery import record_training_invocation

    record_training_invocation(tmp_path, {"status": "INTERRUPTED", "step": 3}, {
        "initial_step": 0, "final_step": 3, "cpu_seconds": 2., "wall_seconds": 4.})
    record_training_invocation(tmp_path, {"status": "COMPLETED", "step": 8}, {
        "initial_step": 3, "final_step": 8, "cpu_seconds": 5., "wall_seconds": 7.})
    records = [json.loads(line)
               for line in (tmp_path / "invocations.jsonl").read_text().splitlines()]
    assert [row["status"] for row in records] == ["INTERRUPTED", "COMPLETED"]
    assert sum(row["cpu_seconds"] for row in records) == 7.
    assert json.loads((tmp_path / "run.json").read_text())["step"] == 8


def test_source_expansion_preserves_the_existing_training_and_development_roles(tmp_path):
    import argparse
    import json

    from run_small_memory_policy import prepare

    actions = [MemoryAction("r", "READ", "candidate", {"index": 0}),
               MemoryAction("h", "HANDOFF", "Reader")]
    rows = []
    for family in ["known_train", "known_dev", "new_source"]:
        rows.append({**operation_payload(MemoryControlState(task={"request": "Question"}), actions),
            "metadata": {"split": "train", "family": family, "event_id": family + ":step0",
                "action_kinds": {a.id: a.kind for a in actions},
                "action_parameters": {a.id: a.parameters for a in actions}},
            "feedback": {"comparisons": [{"left": "r", "right": "h", "delivery": "left"}]}})
    legacy = tmp_path / "legacy.jsonl"
    legacy.write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest = tmp_path / "prior.json"
    manifest.write_text(json.dumps({"groups": {"known_train": "train", "known_dev": "dev_fit",
                                               "untouched_confirmation": "confirm"}}))
    prepare(argparse.Namespace(output=tmp_path / "expanded", legacy=[legacy], target="delivery",
                               seed=0, overfit=2, split_manifest=manifest))
    assignments = json.loads((tmp_path / "expanded/manifest.json").read_text())["groups"]
    assert assignments["known_train"] == "train" and assignments["known_dev"] == "dev_fit"


def test_query_residual_uses_actual_query_without_extra_information_or_head_parameters():
    torch = pytest.importorskip("torch")
    from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel

    model = SmallControlModel.__new__(SmallControlModel)
    model.device = torch.device("cpu")
    model.config = SmallControlConfig("frozen_mlp", "test",
                                      state_representation="query_residual_v1")
    seen = []

    def encode(texts):
        seen.extend(texts)
        return torch.tensor([[1., 0.], [0., 1.], [1., 1.], [-1., 1.]])

    model.encode = encode
    row = control_input(MemoryControlState(task={"request": "Actual query"}), [
        MemoryAction("r", "READ", "candidate", {"index": 0}),
        MemoryAction("h", "HANDOFF", "Reader")])
    states, actions, owners, lengths = model.features([{**row, "expected": "SECRET"}])
    assert seen[1] == "Actual query" and "SECRET" not in str(seen)
    assert torch.allclose(states[0], torch.tensor([2**-.5, 2**-.5]))
    assert actions.shape == (2, 2) and owners.tolist() == [0, 0] and lengths == [2]


def test_declared_bound_prior_keeps_full_binding_after_menu_reorder_and_id_rename():
    torch = pytest.importorskip("torch")
    from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel

    model = SmallControlModel.__new__(SmallControlModel)
    model.config = SmallControlConfig("frozen_mlp", "test", prior_policy="fixed_context",
                                     prior_menu_order="bound_parameters_v2")
    state = MemoryControlState(task={"request": "Which report?"},
        pending_candidates=[{"item_index": 7, "control_pool_rank": 0},
                            {"item_index": 2, "control_pool_rank": 1}])
    actions = [MemoryAction("a", "READ", "candidate 7", {"index": 7}),
        MemoryAction("b", "READ", "candidate 2", {"index": 2}),
        MemoryAction("end", "HANDOFF", "Reader")]
    scored = model.with_prior(torch.zeros(3), control_input(state, actions))
    assert actions[int(scored.argmax())].parameters == {"index": 7}
    reversed_actions = [MemoryAction(f"new-{i}", a.kind, a.target, a.parameters)
                        for i, a in enumerate(reversed(actions))]
    other = model.with_prior(torch.zeros(3), control_input(state, reversed_actions))
    assert reversed_actions[int(other.argmax())].parameters == {"index": 7}
    assert [float(v) for v in other] == [float(v) for v in reversed(scored)]
    # Existing saved configurations keep their original offered-order semantics.
    model.config.prior_menu_order = "offered_v1"
    legacy = model.with_prior(torch.zeros(3), control_input(state, reversed_actions))
    assert reversed_actions[int(legacy.argmax())].parameters == {"index": 2}
