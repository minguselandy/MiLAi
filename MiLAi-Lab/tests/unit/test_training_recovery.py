"""An interrupted run must resume actual FP32 optimization, RNG and sample exposure."""

import json
import os
import sys

import pytest

from train_bounded_laya import training_stages
from training_recovery import make_scheduler


def test_explicit_checkpoint_schedule_keeps_all_epoch_tails():
    stages = training_stages(35, 3, 1, 6, [1, 2, 4, 6], batch_rows=32, full_passes=True)
    windows = [window for _, stage in stages for window in stage]
    assert [len(window) for window in windows] == [32, 3] * 3
    assert sum(map(len, windows)) == 105
    for data_pass in (1, 2, 3):
        assert sorted(i for window in windows for p, i in window if p == data_pass) == list(
            range(35)
        )
    with pytest.raises(ValueError, match="tail"):
        training_stages(35, 3, 1, 5, batch_rows=32, full_passes=True)


def test_warmup_and_cosine_preserve_per_group_lr_ratios():
    torch = pytest.importorskip("torch")
    p, q = torch.nn.Parameter(torch.ones(1)), torch.nn.Parameter(torch.ones(1))
    optimizer = torch.optim.AdamW([{"params": [p], "lr": 1e-5}, {"params": [q], "lr": 1e-4}])
    scheduler = make_scheduler(
        optimizer,
        10,
        warmup_fraction=0.3,
        warmup_max_updates=2,
        floor_ratio=0.1,
        mode="warmup-cosine",
    )
    rates = []
    for _ in range(10):
        rates.append([group["lr"] for group in optimizer.param_groups])
        optimizer.step()
        scheduler.step()
    assert rates[0] == pytest.approx([5e-6, 5e-5])
    assert rates[1] == pytest.approx([1e-5, 1e-4])
    assert rates[-1] == pytest.approx([1e-6, 1e-5])
    assert all(row[1] / row[0] == pytest.approx(10) for row in rates)


@pytest.mark.parametrize("stop", [2, 3])
def test_real_cuda_trainer_resumes_midstage_or_before_evaluation_exactly(
    tmp_path, monkeypatch, stop
):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    if (
        os.environ.get("CUDA_VISIBLE_DEVICES") not in {"2", "3", "2,3"}
        or not torch.cuda.is_available()
    ):
        pytest.skip("This recovery regression requires the allocated research GPUs")
    from laya.common import DecisionModel
    from laya.train import save_checkpoint

    import train_bounded_laya
    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits

    vocab = tmp_path / "vocab.txt"
    vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nread\nfinish\nevidence\n")
    tok = transformers.BertTokenizer(vocab_file=str(vocab))
    torch.manual_seed(9)
    encoder = transformers.BertModel(
        transformers.BertConfig(
            vocab_size=8,
            hidden_size=16,
            intermediate_size=24,
            num_hidden_layers=1,
            num_attention_heads=2,
            max_position_embeddings=512,
        )
    )
    base = tmp_path / "base"
    save_checkpoint(
        DecisionModel(encoder, head_layers=0, n_act=1),
        tok,
        {"head_layers": 0, "act_costs": {}},
        str(base),
    )
    data = tmp_path / "data"
    data.mkdir()
    for split, count in (("train", 37), ("dev", 3)):
        rows = [
            {
                "state": {"task": {"request": "evidence " * (1 + i % 5)}},
                "questions": {
                    "next": {
                        "type": "choice",
                        "instructions": "Choose",
                        "criteria": {"read": "READ", "finish": "HANDOFF"},
                    }
                },
                "gold": {"next": {"probabilities": {"read" if i % 2 else "finish": 1.0}}},
                "metadata": {
                    "split": split,
                    "family": split + str(i % 2),
                    "row": i,
                    "state_id": i,
                    "event_id": f"{split}/{i}",
                    "label_status": "synthetic_test",
                    "action_kinds": {"read": "READ", "finish": "HANDOFF"},
                },
            }
            for i in range(count)
        ]
        (data / f"{split}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps(RunBudget(RunLimits(), budget).state))

    def run(name, *extra):
        output = tmp_path / name
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "train_bounded_laya",
                str(data),
                str(base),
                str(output),
                "--budget",
                str(budget),
                "--compute-phase",
                name,
                "--parallel-mode",
                "single",
                "--task",
                "memory_operation",
                "--objective",
                "set",
                "--seed",
                "7",
                "--optimizer-updates",
                "6",
                "--eval-at-updates",
                "3",
                "6",
                "--effective-batch-rows",
                "8",
                "--micro-batch-size",
                "2",
                "--eval-batch-size",
                "2",
                "--full-dev-data",
                str(data / "dev.jsonl"),
                "--aux-dev-data",
                str(data / "dev.jsonl"),
                "--full-dev-at",
                "3",
                "6",
                "--log-every-updates",
                "3",
                "--shuffle-options",
                "--max-len",
                "512",
                "--head-max-len",
                "128",
                "--scheduler",
                "warmup-cosine",
                "--warmup-fraction",
                ".5",
                "--warmup-max-updates",
                "2",
                "--save-training-state-every",
                "2",
                *extra,
            ],
        )
        train_bounded_laya.main()
        return output

    continuous = run("continuous")
    first = run("interrupted", "--stop-after-updates", str(stop))
    assert json.loads((first / "run.json").read_text())["status"] == "INTERRUPTED"
    resumed = run("resumed", "--resume-training-state", str(first / "recovery/training-state.pt"))
    baseline = torch.load(continuous / "recovery/training-state.pt", weights_only=False)
    recovered = torch.load(resumed / "recovery/training-state.pt", weights_only=False)
    assert all(
        torch.equal(value, recovered["model"][key]) for key, value in baseline["model"].items()
    )
    assert baseline["scheduler"] == recovered["scheduler"]
    assert baseline["progress"]["option_orders"] == recovered["progress"]["option_orders"]
    assert torch.equal(baseline["torch_rng"], recovered["torch_rng"])
    assert all(
        torch.equal(a, b) for a, b in zip(baseline["cuda_rng"], recovered["cuda_rng"], strict=True)
    )
    for key, values in baseline["optimizer"]["state"].items():
        for name, value in values.items():
            other = recovered["optimizer"]["state"][key][name]
            assert torch.equal(value, other) if isinstance(value, torch.Tensor) else value == other
    history = json.loads((resumed / "history.json").read_text())
    assert [point["optimizer_updates"] for point in history] == [0, 3, 6]
    assert (resumed / "dev/0").is_symlink()
    assert [point["optimizer_updates"] for point in history if "full-dev" in point] == [3, 6]
    assert (resumed / "full-dev/6/predictions.jsonl").is_file()
    assert all("aux-dev" in point for point in history)
    assert (resumed / "aux-dev/0").is_symlink()
    actual = json.loads((resumed / "compute.json").read_text())
    assert actual["train_sequence_rows"] == (6 - stop) * 8  # No old CPU/token re-billing.
    assert json.loads((resumed / "run.json").read_text())["train_sequence_rows"] == 48
    assert len(list((resumed / "option-orders").iterdir())) == 2  # Cross-pass resume.
