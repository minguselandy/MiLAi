"""Soft targets bound score margins without relabelling unknowns or evaluation data."""
import copy
import math
import sys
from pathlib import Path

import pytest
from test_quality_feedback import example
from test_quality_fit_audit import closed_quality_fit
from test_saved_feedback_fit import emit_job
from test_saved_quality_fit import quality_fixture

from analyze_feedback_fit import analyze
from analyze_saved_feedback_fit import inputs_for_fit, select, verify_retention
from milai_lab.harness.artifact_io import read_json, write_json
from quality_feedback import quality_pair_loss


def directional_pairs():
    pairs = example()["feedback"]["comparisons"]
    pairs[0]["answer"] = "left"
    pairs[0]["basis"]["quality_before_resource_tiebreak"]["answer"] = "left"
    return pairs


@pytest.mark.parametrize("offset", [-1., 0., 1.])
def test_fixed_soft_target_has_finite_margin_optimum_and_no_unknown_gradient(offset):
    torch = pytest.importorskip("torch")
    margin = math.log(19) + offset
    logits = torch.tensor([margin, 0., 1000., -1000., -math.inf],
                          dtype=torch.float64, requires_grad=True)
    loss = quality_pair_loss(logits, ["read", "stop", "view", "unreviewed"],
                             directional_pairs(), "answer", "quality-direction",
                             label_smoothing=.05)
    loss.backward()
    gradient = logits.grad[0].item()
    assert gradient == pytest.approx(1 / (1 + math.exp(-margin)) - .95, abs=1e-14)
    assert (gradient < 0 if offset < 0 else gradient > 0 if offset > 0
            else abs(gradient) < 1e-14)
    assert logits.grad[2:].tolist() == [0., 0., 0.]
    assert torch.isfinite(loss) and torch.isfinite(logits.grad).all()


def test_smoothing_keeps_confirmed_ties_unknown_masks_and_input_data_unchanged():
    torch = pytest.importorskip("torch")
    pairs = example()["feedback"]["comparisons"]
    before = copy.deepcopy(pairs)
    keys = ["read", "stop", "view", "unreviewed"]
    for mode in ("quality-direction", "quality-tie"):
        results = []
        for epsilon in (0., .05):
            logits = torch.tensor([1000., 0., -1000., 7000.], requires_grad=True)
            loss = quality_pair_loss(logits, keys, pairs, "answer", mode,
                                     label_smoothing=epsilon)
            loss.backward()
            results.append((loss.item(), logits.grad.tolist()))
        assert results[0] == results[1]
        assert results[0][1][2:] == [0., 0.]
    assert pairs == before


def test_zero_is_legacy_loss_and_soft_loss_is_option_permutation_and_direction_symmetric():
    torch = pytest.importorskip("torch")
    pairs = directional_pairs()
    keys, values = ["read", "stop", "view", "unreviewed"], [2., -.3, 999., -999.]
    logits = torch.tensor(values, dtype=torch.float64, requires_grad=True)
    original = quality_pair_loss(logits, keys, pairs, "answer", "quality-direction")
    explicit = quality_pair_loss(logits, keys, pairs, "answer", "quality-direction",
                                 label_smoothing=0.)
    assert torch.equal(original, explicit)
    assert torch.equal(torch.autograd.grad(original, logits, retain_graph=True)[0],
                       torch.autograd.grad(explicit, logits)[0])
    results = []
    for order in ([0, 1, 2, 3], [3, 1, 0, 2]):
        shuffled = torch.tensor([values[i] for i in order], dtype=torch.float64,
                                requires_grad=True)
        loss = quality_pair_loss(shuffled, [keys[i] for i in order], pairs, "answer",
                                 "quality-direction", label_smoothing=.05)
        loss.backward()
        results.append((loss.item(), {keys[i]: shuffled.grad[j].item()
                                      for j, i in enumerate(order)}))
    assert results[0] == results[1]
    reversed_pair = copy.deepcopy(pairs[:1])
    reversed_pair[0].update(left="stop", right="read", answer="right")
    reversed_pair[0]["basis"]["quality_before_resource_tiebreak"]["answer"] = "right"
    reversed_loss = quality_pair_loss(torch.tensor(values, dtype=torch.float64), keys,
        reversed_pair, "answer", "quality-direction", label_smoothing=.05)
    assert reversed_loss.item() == pytest.approx(results[0][0])


@pytest.mark.parametrize("epsilon,mode", [
    ("nan", "quality-direction"), ("inf", "quality-direction"),
    ("-0.01", "quality-direction"), ("0.5", "quality-direction"),
    ("0.05", "legacy-direction"),
])
def test_cli_rejects_invalid_or_undeclared_smoothing_before_loading_weights(
    monkeypatch, capsys, epsilon, mode,
):
    import train_bounded_laya

    monkeypatch.setattr(sys, "argv", ["train_bounded_laya.py", "/data", "/checkpoint", "/out",
        "--budget", "/ledger",
        "--task", "memory_operation", "--objective", "pair", "--feedback-target", "answer",
        "--optimizer-updates", "192", "--feedback-dev-data", "/feedback",
        "--pair-supervision", mode, "--pair-label-smoothing", epsilon])
    with pytest.raises(SystemExit) as error:
        train_bounded_laya.main()
    assert error.value.code == 2
    assert "Pair label smoothing" in capsys.readouterr().err


def test_native_smoothing_requires_explicit_audit_and_checkpoint_identity(tmp_path):
    plan, root = closed_quality_fit(tmp_path, "quality-direction")
    original = analyze(plan, "unit", quality_mode="quality-direction")
    plan["plans"][0]["argv"].extend(["--pair-label-smoothing", ".05"])
    run = read_json(root / "run.json")
    run["pair_label_smoothing"] = .05
    write_json(root / "run.json", run)
    checkpoint = root / "checkpoints/update-1/rl_agent_config.json"
    config = read_json(checkpoint)
    config["training"]["milai_reader"]["pair_label_smoothing"] = .05
    write_json(checkpoint, config)
    with pytest.raises(ValueError, match="declared regularization audit"):
        analyze(plan, "unit", quality_mode="quality-direction")
    actual = analyze(plan, "unit", quality_mode="quality-direction", pair_label_smoothing=.05)
    assert actual["recipe"]["pair_label_smoothing"] == .05
    assert actual["curve"] == original["curve"]  # Same synthetic logits, unchanged dev labels.
    assert actual["in_memory_selection"] == original["in_memory_selection"]
    config["training"]["milai_reader"]["pair_label_smoothing"] = .1
    write_json(checkpoint, config)
    with pytest.raises(ValueError, match="checkpoint metadata"):
        analyze(plan, "unit", quality_mode="quality-direction", pair_label_smoothing=.05)


def test_saved_smoothing_identity_survives_selection_and_retention(tmp_path):
    plan, native = quality_fixture(tmp_path)
    native["recipe"]["pair_label_smoothing"] = .05
    root = Path(native["recipe"]["output"])
    run = read_json(root / "run.json")
    run["pair_label_smoothing"] = .05
    write_json(root / "run.json", run)
    with pytest.raises(ValueError, match="declared supervision and metric"):
        inputs_for_fit(plan, native)
    plan["fits"][0]["pair_label_smoothing"] = .05
    result = select(plan, native)
    assert result["pair_label_smoothing"] == .05
    job, = plan["fits"][0]["conditional_retention_jobs"]
    emit_job(plan, native, job)
    retained = verify_retention(plan, native, result)
    assert retained["pair_label_smoothing"] == .05
    result["pair_label_smoothing"] = .1
    with pytest.raises(ValueError, match="verified saved selection"):
        verify_retention(plan, native, result)
