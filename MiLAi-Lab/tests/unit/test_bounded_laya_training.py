"""Derived prefixes and event multiplicity must not inflate a family's loss."""

import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from train_bounded_laya import (
    compute_counts,
    decision_loss,
    event_weights,
    state_option_seed,
    training_forward,
    training_microbatches,
    training_stages,
)


def test_shared_linear_checkpoint_roundtrip_keeps_option_scores(tmp_path):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    from linear_reader_classifier import save_linear_checkpoint
    from milai_lab.providers.linear_local import LinearDecision, build_linear_model

    vocab = tmp_path / "vocab.txt"
    vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nalpha\nbeta\n")
    tokenizer = transformers.BertTokenizer(vocab_file=str(vocab))
    torch.manual_seed(3)
    encoder = transformers.BertModel(transformers.BertConfig(
        vocab_size=7, hidden_size=8, intermediate_size=12,
        num_hidden_layers=1, num_attention_heads=2))
    model = build_linear_model(encoder).eval()
    inputs = dict(input_ids=torch.tensor([[2, 5, 4, 6, 4, 3]]),
        attention_mask=torch.ones(1, 6, dtype=torch.long), marker_pos=torch.tensor([[2, 4]]),
        marker_mask=torch.ones(1, 2, dtype=torch.bool), qtype=torch.tensor([0]))
    with torch.no_grad():
        before = model(**inputs)[0]
    save_linear_checkpoint(model, tokenizer, {"operation_state": "mechanical"},
                           str(tmp_path / "checkpoint"))
    loaded = LinearDecision.load(tmp_path / "checkpoint", 128, 64)
    with torch.no_grad():
        after = loaded.model(**inputs)[0]
    assert torch.allclose(before, after, atol=1e-3)
    assert loaded.config["operation_state"] == "mechanical"
    assert loaded.counters["forwards"] == 0


def test_fixed_update_budget_keeps_full_windows_across_different_masks():
    for size in (17, 37):
        stages = training_stages(size, epochs=2, seed=7, update_budget=5)
        assert [step for step, _ in stages] == [2, 5]
        windows = [w for _, batch in stages for w in batch]
        assert len(windows) == 5 and all(len(w) == 16 for w in windows)
        draws = [pair for window in windows for pair in window]
        for data_pass in range(1, len(draws) // size + 1):
            assert sorted(i for p, i in draws if p == data_pass) == list(range(size))
        assert stages == training_stages(size, epochs=9, seed=7, update_budget=5)


@pytest.mark.parametrize("size", [3, 16])
def test_microbatch_accumulation_preserves_the_weighted_full_window_gradient(size):
    torch = pytest.importorskip("torch")
    inputs = torch.arange(size * 3, dtype=torch.float64).reshape(size, 3) / 31
    target = torch.zeros(size, 5, dtype=torch.float64)
    target[:, :2] = .5
    mask = torch.arange(5).unsqueeze(0) < (torch.arange(size) % 4 + 2).unsqueeze(1)
    weights = torch.arange(1, size + 1, dtype=torch.float64) / size
    initial = torch.arange(15, dtype=torch.float64).reshape(3, 5) / 10
    full = initial.clone().requires_grad_()
    (decision_loss(inputs @ full, target, mask, "soft-ce") * weights).mean().backward()
    window = [(1, i) for i in range(size)]
    for micro_size in (1, 2, 4, 8, 16):
        current = initial.clone().requires_grad_()
        batches = training_microbatches(window, micro_size)
        assert [pair for batch in batches for pair in batch] == window
        for batch in batches:
            indices = [i for _, i in batch]
            loss = decision_loss(inputs[indices] @ current, target[indices], mask[indices],
                                 "soft-ce")
            ((loss * weights[indices]).sum() / size).backward()
        assert torch.allclose(current.grad, full.grad, atol=1e-12)


def test_legacy_epoch_order_and_partial_windows_remain_unchanged():
    rng = random.Random(19)  # noqa: S311 -- compare the frozen sampling order
    stages = training_stages(35, epochs=2, seed=19)
    for epoch, windows in stages:
        expected = list(range(35))
        rng.shuffle(expected)
        assert [len(w) for w in windows] == [16, 16, 3]
        assert [i for w in windows for p, i in w] == expected
        assert {p for w in windows for p, _ in w} == {epoch}


@pytest.mark.parametrize("rows", [1, 2, 3])
def test_actual_gpu_microbatches_preserve_logits_and_gradients(rows):
    torch = pytest.importorskip("torch")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "2,3" or torch.cuda.device_count() != 2:
        pytest.skip("This GPU regression uses only explicitly allocated physical GPUs2,3")
    from laya.train import _forward

    class TinyDecision(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.weight = torch.nn.Parameter(
                torch.arange(6, dtype=torch.float32).reshape(3, 2) / 10)

        def forward(self, input_ids, attention_mask, marker_pos, marker_mask, qtype,
                    detach_encoder=False):
            return (input_ids * attention_mask) @ self.weight, None

    device = torch.device("cuda:0")
    model, reference = TinyDecision().to(device), TinyDecision().to(device)
    parallel = torch.nn.DataParallel(model, device_ids=[0, 1])
    batch = {"input_ids": torch.arange(rows * 3, dtype=torch.float32).reshape(rows, 3) / 31,
             "attention_mask": torch.ones(rows, 3), "marker_pos": torch.zeros(rows, 2).long(),
             "marker_mask": torch.ones(rows, 2).bool(), "qtype": torch.zeros(rows).long()}
    expected = _forward(reference, batch, device, False, False)
    actual = training_forward(model, parallel, batch, device)
    expected.square().mean().backward()
    actual.square().mean().backward()
    assert torch.allclose(actual, expected, atol=1e-6)
    assert torch.allclose(model.weight.grad, reference.weight.grad, atol=1e-6)


def test_shared_state_option_order_is_independent_of_filtered_list_position():
    laya = pytest.importorskip("laya.train")
    item = {"q": {"t": "choice"}, "k": 8}

    def orders(ids):
        result = {}
        for i in ids:
            rng = random.Random(state_option_seed(2, 3, i))  # noqa: S311
            result[i] = laya.draw_option_order(item, rng, ("choice",))
        return result

    source, reference = orders([7, 101, 409]), orders([2, 7, 90, 101, 409, 800])
    assert all(source[i] == reference[i] for i in source)
    assert all(sorted(order) == list(range(8)) for order in source.values())


def test_loss_mass_is_equal_by_family_then_event_not_prefix_count():
    rows = [{"metadata": {"family": family, "row": event}}
            for family, event, copies in (("a", 0, 7), ("a", 1, 2), ("b", 2, 1))
            for _ in range(copies)]
    weights = event_weights(rows)
    mass = defaultdict(float)
    for row, weight in zip(rows, weights, strict=True):
        mass[row["metadata"]["family"], row["metadata"]["row"]] += weight
    assert sum(weights) == pytest.approx(len(rows))
    assert mass["a", 0] == pytest.approx(2.5)
    assert mass["a", 1] == pytest.approx(2.5)
    assert mass["b", 2] == pytest.approx(5)


def test_semantic_questions_on_one_source_row_do_not_inherit_prefix_multiplicity():
    rows = [{"metadata": {"family": "a", "row": 4, "training_event": event}}
            for event, copies in (("birth", 7), ("death", 2)) for _ in range(copies)]
    rows.append({"metadata": {"family": "b", "row": 9}})
    weights = event_weights(rows)
    assert sum(weights[:7]) == pytest.approx(2.5)
    assert sum(weights[7:9]) == pytest.approx(2.5)
    assert weights[9] == pytest.approx(5)


def test_set_loss_accepts_mass_on_either_positive_and_ignores_padding():
    torch = pytest.importorskip("torch")
    logits = torch.tensor([[2.0, -1.0, 0.5, 100.0]], requires_grad=True)
    target = torch.tensor([[0.5, 0.5, 0.0, 0.0]])
    mask = torch.tensor([[True, True, True, False]])
    actual = decision_loss(logits, target, mask, "set")
    expected = -torch.log(torch.softmax(logits[0, :3], 0)[:2].sum())
    assert actual.item() == pytest.approx(expected.item())
    actual.sum().backward()
    assert logits.grad[0, 3] == 0
    assert logits.grad[0, 2] > 0
    assert torch.isfinite(logits.grad).all()


def test_single_positive_set_equals_ce_and_multiple_positives_differ():
    torch = pytest.importorskip("torch")
    logits = torch.tensor([[4.0, -2.0, 0.0]])
    mask = torch.ones_like(logits, dtype=torch.bool)
    single = torch.tensor([[1.0, 0.0, 0.0]])
    assert decision_loss(logits, single, mask, "set").item() == pytest.approx(
        decision_loss(logits, single, mask, "soft-ce").item(), abs=1e-6)
    multiple = torch.tensor([[0.5, 0.5, 0.0]])
    assert decision_loss(logits, multiple, mask, "set").item() < 0.02
    assert decision_loss(logits, multiple, mask, "soft-ce").item() > 3


def test_train_evaluation_does_not_overwrite_optimization_or_partial_attempts():
    run = {"train_sequence_rows": 208, "train_input_tokens": 579397,
           "train_batch_forwards": 53, "train_device_forwards": 106,
           "train_batch_attempts": 54, "train_offered_rows": 212,
           "train_offered_tokens": 590488}
    counts = compute_counts(run, {
        "train": Counter(forwards=258, sequence_rows=258, input_tokens=715857),
        "dev": Counter(forwards=90, sequence_rows=90, input_tokens=233571)})
    assert all(counts[k] == value for k, value in run.items())
    assert counts["train_eval_forwards"] == counts["train_eval_sequence_rows"] == 258
    assert counts["train_eval_input_tokens"] == 715857
    assert counts["dev_input_tokens"] == 233571
    assert counts["train_input_tokens"] + counts["train_eval_input_tokens"] == 1295254
