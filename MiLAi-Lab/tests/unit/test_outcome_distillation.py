"""Executed support, action permutation and optimizer-window semantics."""
import copy
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from outcome_distillation import (
    active_support,
    align_utilities,
    attach_utilities,
    component_weights,
    mixed_windows,
    normalized_micro_loss,
    utility_distillation,
    window_normalizers,
)
from retrieval_feedback import encoding_row
from train_bounded_laya import training_stages


def row(index, main=True, scores=(-1., -2.)):
    result = {"state": {"public": "observation"},
        "questions": {"next": {"criteria": {"read": "READ", "stop": "HANDOFF", "other": "READ"}}},
        "metadata": {"family": f"family-{index // 2}", "event_id": f"event-{index}",
                     "training_event": index, "row": index},
        "gold": {} if main else {"next": {"probabilities": {"read": 1.}}}}
    if main:
        result["utility"] = {"candidates": [
            {"action": {"id": key}, "score_known": True, "mean_logprob": score}
            for key, score in zip(("read", "stop"), scores, strict=True)]}
    return result


def test_subset_kl_matches_manual_distribution_and_detaches_teacher():
    torch = pytest.importorskip("torch")
    logits = torch.tensor([[.2, -.4, 50.]], requires_grad=True)
    scores = torch.tensor([[-1., -2., 0.]], requires_grad=True)
    known = torch.tensor([[True, True, False]])
    result = utility_distillation(logits, scores, known)
    q = (scores[0, :2].detach() / .5).softmax(-1)
    expected = (q * (q.log() - logits[0, :2].log_softmax(-1))).sum()
    torch.testing.assert_close(result.per_state[0], expected)
    result.per_state.sum().backward()
    assert scores.grad is None and logits.grad[0, 2] == 0 and logits.grad[0, 0] < 0


def test_explicit_unexecuted_score_stays_outside_both_gradient_and_window_support():
    torch = pytest.importorskip("torch")
    sample = row(0)
    sample["utility"]["candidates"].append({"action": {"id": "other"},
        "score_known": True, "mean_logprob": float("nan"), "execution_status": "failed"})
    logits = torch.tensor([[0., 0., 30.]], requires_grad=True)
    scores, known = align_utilities([sample], [["read", "stop", "other"]], logits)
    utility_distillation(logits, scores, known).per_state.sum().backward()
    assert known.tolist() == [[True, True, False]] and logits.grad[0, 2] == 0
    sample["utility"]["candidates"][1]["execution_status"] = "not_executed"
    assert not active_support(sample, "utility-kl", None, False, 1e-6)


@pytest.mark.parametrize("known,scores", [
    ([False, False, False], [0., 0., 0.]),
    ([True, False, False], [-1., 0., 0.]),
    ([True, True, False], [-1., -1., 0.]),
])
def test_empty_single_and_flat_support_have_finite_zero_loss_and_gradient(known, scores):
    torch = pytest.importorskip("torch")
    logits = torch.tensor([[1., 2., float('-inf')]], requires_grad=True)
    result = utility_distillation(logits, torch.tensor([scores]), torch.tensor([known]))
    assert not result.active.item() and result.per_state.item() == 0
    result.per_state.sum().backward()
    assert torch.equal(logits.grad, torch.zeros_like(logits))


def test_action_permutation_preserves_loss_and_full_action_gradient():
    torch = pytest.importorskip("torch")
    rows = [row(0)]
    original = torch.tensor([[.5, -.2, 8.]], requires_grad=True)
    order = [2, 0, 1]
    permuted = original.detach()[:, order].requires_grad_()
    for logits, keys in ((original, [["read", "stop", "other"]]),
                         (permuted, [["other", "read", "stop"]])):
        scores, known = align_utilities(rows, keys, logits)
        utility_distillation(logits, scores, known).per_state.sum().backward()
    torch.testing.assert_close(original.grad[:, order], permuted.grad)


def test_common_teacher_constant_does_not_change_kl():
    torch = pytest.importorskip("torch")
    logits, scores = torch.tensor([[.5, 1., 2.]]), torch.tensor([[-4., -3., -2.]])
    known = torch.tensor([[True, True, True]])
    torch.testing.assert_close(utility_distillation(logits, scores, known).per_state,
                               utility_distillation(logits, scores + 7., known).per_state)


@pytest.mark.parametrize("temperature", [0., -1., float("inf"), float("nan")])
def test_invalid_temperature_rejected(temperature):
    torch = pytest.importorskip("torch")
    with pytest.raises(ValueError, match="Temperatures"):
        utility_distillation(torch.zeros(1, 2), torch.zeros(1, 2),
                             torch.ones(1, 2, dtype=torch.bool), temperature)


def test_weak_only_encoding_has_no_fabricated_semantic_label_or_model_input_leak():
    original = row(0)
    frozen = copy.deepcopy(original)
    codec = encoding_row(original)
    assert original == frozen and original["gold"] == {}
    assert codec["state"] == original["state"] and codec["questions"] == original["questions"]
    assert "utility" not in str({k: codec[k] for k in ("state", "questions")})


def test_attach_checks_full_binding_and_preserves_all_student_inputs():
    source = row(0)
    source.pop("utility")
    source["metadata"].update(split="train", action_kinds={"read": "READ"},
                              action_parameters={"read": {"start": 0}})
    source["questions"]["next"]["criteria"] = {"read": 'READ source {"start":0}'}
    score = {"event_id": "event-0", "family": "family-0", "research_split": "train",
             "action": {"id": "read", "kind": "READ", "target": "source",
                        "parameters": {"start": 0}},
             "reference_set_id": "offline-only", "teacher": "local", "template_version": "v1",
             "continuation": {"steps": 2}, "score_known": True, "mean_logprob": -1.}
    result = attach_utilities([source], [score])[0]
    assert {k: result[k] for k in ("state", "questions", "gold")} == {
        k: source[k] for k in ("state", "questions", "gold")}
    score["action"]["parameters"]["start"] = 1
    with pytest.raises(ValueError, match="full action"):
        attach_utilities([source], [score])


def test_three_thousand_exact_passes_have_declared_375_windows_and_3000_replay():
    rows = [row(i) for i in range(3000)] + [row(3000 + i, False) for i in range(37)]
    windows = mixed_windows(rows, 3, 7)
    assert len(windows) == 375 and all(len(w) == 32 for w in windows)
    counts = Counter(i for w in windows for _, i in w)
    assert all(counts[i] == 3 for i in range(3000))
    assert sum(counts[i] for i in range(3000, len(rows))) == 3000
    assert windows == mixed_windows(rows, 3, 7)
    stages = training_stages(len(rows), 3, 7, 375, [63, 125, 250],
                             explicit_windows=windows)
    assert [cut for cut, _ in stages] == [63, 125, 250, 375]
    assert [w for _, batch in stages for w in batch] == windows


def test_tail_does_not_repeat_or_drop_primary_rows_and_unknown_control_pool_stays_same():
    rows = [row(i) for i in range(25)] + [row(25, False)]
    windows = mixed_windows(rows, 1, 0)
    assert [len(w) for w in windows] == [32, 2]
    weights = component_weights(rows, "pair", "delivery", True, 1e-6)
    assert weights[:25] == [0.] * 25 and weights[25] > 0
    assert [sum(i < 25 for _, i in w) for w in windows] == [24, 1]


@pytest.mark.parametrize("sizes", [[6], [1, 2, 3], [2, 2, 2]])
def test_full_window_and_microbatch_gradients_match_with_unknown_and_replay(sizes):
    torch = pytest.importorskip("torch")
    rows = [row(0), row(1, scores=(-1., -1.)), row(2), row(3), row(4, False), row(5, False)]
    weights = component_weights(rows, "utility-kl", None, False, 1e-6)
    window = [(1, i) for i in range(len(rows))]
    denominators = window_normalizers(window, rows, weights)
    source = torch.tensor([[.3, -.2, 1.]] * 6)

    def gradient(parts):
        logits = source.clone().requires_grad_()
        offset = 0
        for size in parts:
            indices = list(range(offset, offset + size))
            subset = [rows[i] for i in indices]
            local = logits[indices]
            scores, known = align_utilities(subset, [["read", "stop", "other"]] * size, local)
            utility = utility_distillation(local, scores, known).per_state
            replay = -local.log_softmax(-1)[:, 0]
            losses = torch.where(torch.tensor([i < 4 for i in indices]), utility, replay)
            normalized_micro_loss(losses, indices, rows, weights, denominators, .25).backward()
            offset += size
        return logits.grad

    torch.testing.assert_close(gradient(sizes), gradient([6]), atol=1e-7, rtol=1e-6)


@pytest.mark.parametrize("objective", ["utility-kl", "pair"])
def test_gpu_native_trainer_keeps_weak_only_rows_and_component_counts(
    tmp_path, monkeypatch, objective,
):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "3" or not torch.cuda.is_available():
        pytest.skip("New component trainer regression uses allocated physical GPU3")
    from laya.common import DecisionModel
    from laya.train import save_checkpoint

    import train_bounded_laya
    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits

    vocab = tmp_path / "vocab.txt"
    vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nread\nstop\nobservation\n")
    tokenizer = transformers.BertTokenizer(vocab_file=str(vocab))
    encoder = transformers.BertModel(transformers.BertConfig(
        vocab_size=8, hidden_size=16, intermediate_size=24, num_hidden_layers=1,
        num_attention_heads=2, max_position_embeddings=512))
    base = tmp_path / "base"
    save_checkpoint(DecisionModel(encoder, head_layers=0, n_act=1), tokenizer,
                    {"head_layers": 0, "act_costs": {}}, str(base))
    rows = [row(0), row(1, scores=(-1., -1.)), row(2, False)]
    rows[0]["feedback"] = {"comparisons": [{"left": "read", "right": "stop",
                                             "delivery": "left", "answer": "unknown"}]}
    for i, item in enumerate(rows):
        item["questions"]["next"].update(type="choice", instructions="Choose")
        item["metadata"].update(state_id=i, split="train", label_status="reviewed", action_kinds={
            "read": "READ", "stop": "HANDOFF", "other": "READ"})
    dev = copy.deepcopy(rows[2])
    dev["metadata"].update(family="dev", split="dev", event_id="dev/0")
    data = tmp_path / "data"
    data.mkdir()
    (data / "train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (data / "dev.jsonl").write_text(json.dumps(dev) + "\n")
    budget = tmp_path / "budget.json"  # Isolated tiny test ledger.
    budget.write_text(json.dumps(RunBudget(RunLimits(), budget).state))
    output = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["train_bounded_laya", str(data), str(base), str(output),
        "--budget", str(budget), "--task", "memory_operation", "--objective", objective,
        "--component-windows", "--main-rows-per-window", "2", "--effective-batch-rows", "3",
        "--epochs", "2", "--optimizer-updates", "2", "--eval-at-updates", "1",
        "--micro-batch-size", "1", "--parallel-mode", "single", "--precision", "bf16",
        "--shuffle-options", "--max-len", "512", "--head-max-len", "128",
        "--replay-objective", "set", "--save-training-state-every", "1",
        *(["--feedback-target", "delivery", "--include-reviewed-ties"]
          if objective == "pair" else [])])
    train_bounded_laya.main()
    run = json.loads((output / "run.json").read_text())
    assert run["status"] == "COMPLETED" and run["optimizer_updates"] == 2
    assert run["sampled_main_rows"] == 4 and run["sampled_main_active_rows"] == 2
    assert run["sampled_window_replay_rows"] == 2 and run["train_sequence_rows"] == 6
    assert (output / "checkpoint/model.safetensors").exists()
    assert (output / "recovery/training-state.pt").exists()
    # Verify the new window/sampling contract survives real optimizer/RNG restoration.
    full_argv = sys.argv.copy()
    interrupted = tmp_path / "interrupted"
    interrupted_argv = [*full_argv, "--stop-after-updates", "1"]
    interrupted_argv[3] = str(interrupted)
    monkeypatch.setattr(sys, "argv", interrupted_argv)
    train_bounded_laya.main()
    assert json.loads((interrupted / "run.json").read_text())["status"] == "INTERRUPTED"
    resumed = tmp_path / "resumed"
    resumed_argv = [*full_argv, "--resume-training-state",
                    str(interrupted / "recovery/training-state.pt")]
    resumed_argv[3] = str(resumed)
    monkeypatch.setattr(sys, "argv", resumed_argv)
    train_bounded_laya.main()
    from laya.train import load_checkpoint

    expected, _, _ = load_checkpoint(str(output / "checkpoint"))
    actual, _, _ = load_checkpoint(str(resumed / "checkpoint"))
    assert all(torch.equal(p, q) for p, q in zip(expected.parameters(), actual.parameters(),
                                                 strict=True))
