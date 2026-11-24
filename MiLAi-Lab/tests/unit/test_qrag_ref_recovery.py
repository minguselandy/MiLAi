"""A reboot can remove staged native checkpoints while leaving verified actors on disk."""

import importlib
import json
from pathlib import Path

import pytest
import torch
from safetensors.torch import save_file


def test_terminal_rehydration_and_interrupted_evaluation(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    settle = importlib.import_module("qrag_ref_result")
    codec = importlib.import_module("qrag_ref_actor_delta")
    run = tmp_path / "run"
    mirror = run / "retained-actors"
    mirror.mkdir(parents=True)
    logs = run / "tb_logs"
    logs.mkdir()
    stages = tmp_path / "staging"
    (run / "config.yaml").write_text("checkpoint_dir: " + str(stages))
    base = tmp_path / "base.safetensors"
    save_file({"layer": torch.tensor([2.0, 3.0])}, str(base))
    curve_file = logs / "reference-curve.jsonl"
    curve = [
        {
            "optimizer_updates": i,
            "gt_dev_return": 1 if i == 400 else 0.5,
            "gt_train_return": 0.5,
            "elapsed_seconds": i + 2,
            "critic_transitions": i * 96 + 12,
            "peak_gpu_allocated_bytes": 10,
        }
        for i in range(0, 10001, 100)
    ]
    curve_file.write_text(json.dumps(curve[0]) + "\n")
    with pytest.raises(ValueError, match="incomplete"):
        settle.prepare_terminal(run)
    assert not stages.exists()
    curve_file.write_text("".join(json.dumps(v) + "\n" for v in curve))
    pointers = {}
    for kind, step in (("best", 400), ("last", 10000)):
        actor = {
            "format": "qrag_reference_actor",
            "alpha": 0.005,
            "policy": {"state_embed.model.layer": torch.tensor([float(step), 3.0])},
            "action_embed": {
                "model.model.layer": torch.tensor([2.0, 3.0]),
                "extra": torch.tensor([1]),
            },
        }
        source = tmp_path / (kind + ".pt")
        torch.save(actor, source)
        dest = mirror / (kind + ".zip")
        record = codec.compact_trained(source, base, dest)
        record.update(
            archive=str(dest), bytes=dest.stat().st_size, optimizer_updates=step, kind=kind
        )
        pointers[kind] = record
        source.unlink()
    (mirror / "index.json").write_text(json.dumps({"actors": pointers}))
    settle.prepare_terminal(run)
    restored = torch.load(stages / "model_best.pt", weights_only=True)
    assert torch.equal(restored["policy"]["state_embed.model.layer"], torch.tensor([400.0, 3.0]))
    assert not (stages / "model_last.pt").exists()
    assert (run / "actors/last.zip").samefile(mirror / "last.zip")
    (stages / "model_best.pt").unlink()
    settle.archive_terminal(run, base)
    assert not (stages / "model_best.pt").exists()
    packets = run / "eval_seed42.jsonl"
    packets.write_bytes(b'{"id":"0","em":1,"f1":1,"return":1}\n{"id":')
    settle.begin_validation(run)
    assert packets.read_bytes().endswith(b"}\n")
    assert list(run.glob("eval_seed42.interrupted-tail-*"))
    with packets.open("a") as f:
        for i in range(1, 300):
            f.write(json.dumps({"id": str(i), "em": 1, "f1": 1, "return": 1}) + "\n")
    roster = tmp_path / "roster.json"
    roster.write_text(
        json.dumps({"groups": [str(i) for i in range(300)], "n": 300, "role": "TUNE"})
    )
    (run / "validation-resource.jsonl").write_text('{"exit_code":0,"elapsed_seconds":3}\n')
    result = settle.summarize(run, roster, [])
    assert result["fit_duration_scope"].startswith("Lower bound")
    assert result["best_actor_support_f1"] == 1
    assert result["evaluated_groups"] == 300
