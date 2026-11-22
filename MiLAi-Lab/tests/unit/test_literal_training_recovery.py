"""Exact local recovery binds observations, full actions and sparse label values."""

import copy
import json
import random
import sys
from pathlib import Path

import pytest

from training_recovery import make_scheduler, restore_training_state, save_training_state


def examples():
    return [
        {
            "sample_id": f"same-{i}",
            "group_id": f"source-{i}",
            "observation": {
                "text": f"Original report {i} 原始",
                "features": [0.2 + i, -0.3],
                "reported": True,
                "source_revision": 1,
            },
            "actions": [
                {"id": "read", "kind": "READ", "parameters": {"index": i}},
                {"id": "handoff", "kind": "HANDOFF", "parameters": {}},
            ],
            "offline_supervision": {"observed_values": {"read": float(i), "handoff": None}},
        }
        for i in range(2)
    ]


def stack(seed=17):
    torch = pytest.importorskip("torch")
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    random.seed(seed)
    model = torch.nn.Sequential(torch.nn.Dropout(0.2), torch.nn.Linear(2, 2))
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
    scheduler = make_scheduler(
        optimizer,
        6,
        warmup_fraction=0.3,
        warmup_max_updates=2,
        floor_ratio=0.1,
        mode="warmup-cosine",
    )
    return model, optimizer, scheduler


def updates(parts, rows, count):
    torch = pytest.importorskip("torch")
    model, optimizer, scheduler = parts
    for _ in range(count):
        row = rows[random.randrange(len(rows))]  # noqa: S311 -- seeded training schedule test
        inputs = torch.tensor(row["observation"]["features"])
        score = model(inputs)[0]
        target = torch.tensor(row["offline_supervision"]["observed_values"]["read"])
        optimizer.zero_grad(set_to_none=True)
        torch.nn.functional.binary_cross_entropy_with_logits(score, target).backward()
        optimizer.step()
        scheduler.step()


def recipe(tmp_path):
    return {
        "data": str(tmp_path / "same.jsonl"),
        "samples": ["same-0", "same-1"],
        "steps": 6,
        "deterministic": True,
    }


def test_real_cpu_optimization_resumes_with_identical_parameters_state_and_rng(tmp_path):
    torch = pytest.importorskip("torch")
    rows = examples()
    contract = recipe(tmp_path)
    continuous = stack()
    updates(continuous, rows, 6)
    save_training_state(
        tmp_path / "full/recovery.pt",
        *continuous,
        contract=contract,
        progress={"step": 6},
        data=rows,
    )
    interrupted = stack()
    updates(interrupted, rows, 2)
    path = tmp_path / "split/recovery.pt"
    save_training_state(path, *interrupted, contract=contract, progress={"step": 2}, data=rows)
    resumed = stack(99)
    assert restore_training_state(path, *resumed, contract=contract, data=copy.deepcopy(rows)) == {
        "step": 2
    }
    updates(resumed, rows, 4)
    save_training_state(
        tmp_path / "resumed/recovery.pt",
        *resumed,
        contract=contract,
        progress={"step": 6},
        data=rows,
    )
    left = torch.load(tmp_path / "full/recovery.pt", weights_only=False)
    right = torch.load(tmp_path / "resumed/recovery.pt", weights_only=False)
    assert left["schema"] == right["schema"] == "bounded-training-state-v2"
    assert all(torch.equal(v, right["model"][k]) for k, v in left["model"].items())
    assert left["scheduler"] == right["scheduler"]
    assert torch.equal(left["torch_rng"], right["torch_rng"])
    assert left["python_rng"] == right["python_rng"]
    for key, values in left["optimizer"]["state"].items():
        for name, value in values.items():
            other = right["optimizer"]["state"][key][name]
            assert torch.equal(value, other) if isinstance(value, torch.Tensor) else value == other


@pytest.mark.parametrize(
    "change", ["text", "binding", "revision", "value", "mask", "type", "order"]
)
def test_same_path_and_ids_cannot_hide_changed_training_values(tmp_path, change):
    torch = pytest.importorskip("torch")
    rows = examples()
    contract = recipe(tmp_path)
    original = stack()
    updates(original, rows, 2)
    path = tmp_path / "recovery.pt"
    save_training_state(path, *original, contract=contract, progress={"step": 2}, data=rows)
    changed = copy.deepcopy(rows)
    if change == "text":
        changed[0]["observation"]["text"] = "Different report with the same sample ID"
    elif change == "binding":
        changed[0]["actions"][0]["parameters"]["index"] = 9
    elif change == "revision":
        changed[0]["observation"]["source_revision"] = 2
    elif change == "value":
        changed[0]["offline_supervision"]["observed_values"]["read"] = 1.0
    elif change == "mask":
        changed[0]["offline_supervision"]["observed_values"]["handoff"] = False
    elif change == "type":
        changed[0]["observation"]["reported"] = 1  # Python equality alone conflates true/1.
    else:
        changed[0]["observation"] = dict(reversed(list(changed[0]["observation"].items())))
    assert [r["sample_id"] for r in changed] == contract["samples"]
    target = stack(99)
    parameters = {k: v.clone() for k, v in target[0].state_dict().items()}
    rng, python_rng = torch.get_rng_state().clone(), random.getstate()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="observations/bindings/supervision changed"):
        restore_training_state(path, *target, contract=contract, data=changed)
    assert all(torch.equal(v, target[0].state_dict()[k]) for k, v in parameters.items())
    assert not target[1].state_dict()["state"]
    assert torch.equal(rng, torch.get_rng_state()) and python_rng == random.getstate()
    assert path.read_bytes() == before


def test_snapshot_is_written_once_and_failed_save_does_not_overwrite_history(tmp_path, monkeypatch):
    rows = examples()
    parts = stack()
    path = tmp_path / "recovery.pt"
    contract = recipe(tmp_path)
    save_training_state(path, *parts, contract=contract, progress={"step": 0}, data=rows)
    snapshot = tmp_path / "training-data.literal.json"
    before = snapshot.read_bytes()
    real_open = Path.open

    def guarded_open(self, mode="r", *args, **kwargs):
        if self == snapshot and any(flag in mode for flag in "wa+"):
            raise AssertionError("Do not rewrite the complete historical training data")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    save_training_state(path, *parts, contract=contract, progress={"step": 1}, data=rows)
    checkpoint = path.read_bytes()
    changed = copy.deepcopy(rows)
    changed[0]["observation"]["text"] = "changed"
    with pytest.raises(ValueError, match="supervision changed"):
        save_training_state(path, *parts, contract=contract, progress={"step": 2}, data=changed)
    assert snapshot.read_bytes() == before and path.read_bytes() == checkpoint


def test_legacy_callers_work_but_strict_recovery_does_not_fabricate_missing_proof(tmp_path):
    torch = pytest.importorskip("torch")
    parts = stack()
    contract = recipe(tmp_path)
    legacy = tmp_path / "old/recovery.pt"
    save_training_state(legacy, *parts, contract=contract, progress={"step": 0})
    assert torch.load(legacy, weights_only=False)["schema"] == "bounded-training-state-v1"
    assert restore_training_state(legacy, *parts, contract=contract) == {"step": 0}
    with pytest.raises(ValueError, match="Legacy checkpoint lacks full"):
        restore_training_state(legacy, *parts, contract=contract, data=examples())
    current = tmp_path / "new/recovery.pt"
    save_training_state(current, *parts, contract=contract, progress={"step": 0}, data=examples())
    with pytest.raises(ValueError, match="original full training examples"):
        restore_training_state(current, *parts, contract=contract)
    with pytest.raises(ValueError, match="training recipe"):
        restore_training_state(
            current, *parts, contract={**contract, "deterministic": 1}, data=examples()
        )
    (tmp_path / "new/training-data.literal.json").unlink()
    with pytest.raises(ValueError, match="snapshot is unavailable"):
        restore_training_state(current, *parts, contract=contract, data=examples())


def test_real_small_trainer_marks_changed_mask_resume_terminal_failed(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    import run_small_memory_policy
    from milai_lab.methods.memory_control import MemoryControlState

    backbone = tmp_path / "backbone"
    backbone.mkdir()
    vocab = backbone / "vocab.txt"
    vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nread\nfinish\n")
    tokenizer = transformers.BertTokenizer(vocab_file=str(vocab))
    tokenizer.save_pretrained(backbone)
    encoder = transformers.BertModel(
        transformers.BertConfig(
            vocab_size=7,
            hidden_size=16,
            intermediate_size=24,
            num_hidden_layers=1,
            num_attention_heads=2,
            max_position_embeddings=512,
        )
    )
    encoder.save_pretrained(backbone)
    rows = [
        {
            "sample_id": "same",
            "group_id": "source",
            "split": "train",
            "observation": MemoryControlState(task={"request": "read"}).project(),
            "actions": [
                {"id": "read", "kind": "READ", "target": "candidate", "parameters": {"index": 0}},
                {"id": "handoff", "kind": "HANDOFF", "target": "Reader", "parameters": {}},
            ],
            "offline_supervision": {
                "observed_action_ids": ["read", "handoff"],
                "preferences": [],
                "observed_values": {"read": 1.0, "handoff": 0.0},
                "value_loss_weight": 0.5,
            },
        }
    ]
    data = tmp_path / "data.jsonl"
    data.write_text(json.dumps(rows[0]) + "\n")
    output = tmp_path / "run"
    args = [
        "run_small_memory_policy",
        "train",
        "--data",
        str(data),
        "--output",
        str(output),
        "--family",
        "frozen_mlp",
        "--backbone",
        str(backbone),
        "--device",
        "cpu",
        "--steps",
        "4",
        "--batch-states",
        "1",
        "--microbatch-states",
        "1",
        "--threads",
        "1",
        "--seed",
        "7",
        "--save-every",
        "2",
        "--chunk-tokens",
        "32",
        "--encode-batch-size",
        "2",
        "--deterministic",
    ]
    monkeypatch.setattr(sys, "argv", [*args, "--interrupt-after", "2"])
    run_small_memory_policy.main()
    assert json.loads((output / "run.json").read_text())["status"] == "INTERRUPTED"
    monkeypatch.setattr(
        sys, "argv", [*args, "--resume", str(output / "recovery.pt"), "--interrupt-after", "3"]
    )
    run_small_memory_policy.main()
    resumed = json.loads((output / "run.json").read_text())
    assert resumed["status"] == "INTERRUPTED" and resumed["step"] == 3
    checkpoint = (output / "recovery.pt").read_bytes()
    rows[0]["offline_supervision"]["observed_values"]["read"] = None
    data.write_text(json.dumps(rows[0]) + "\n")
    monkeypatch.setattr(sys, "argv", [*args, "--resume", str(output / "recovery.pt")])
    with pytest.raises(ValueError, match="supervision changed"):
        run_small_memory_policy.main()
    failed = json.loads((output / "run.json").read_text())
    assert failed["status"] == "FAILED" and failed["stage"] == "restore_training_state"
    assert failed["invocation"]["optimizer_updates_this_invocation"] == 0
    assert failed["invocation"]["states_exposed_this_invocation"] == 0
    assert (output / "recovery.pt").read_bytes() == checkpoint
    records = [json.loads(line) for line in (output / "invocations.jsonl").read_text().splitlines()]
    assert [r["status"] for r in records] == ["INTERRUPTED", "INTERRUPTED", "FAILED"]
    assert not torch.cuda.is_initialized()  # Run this CPU regression with CUDA_VISIBLE_DEVICES="".
