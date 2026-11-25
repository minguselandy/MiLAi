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
            "gt_dev_return": 1 if i == 400 else 0.25 if i == 10000 else 0.5,
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
    roster = tmp_path / "roster.json"
    roster.write_text(
        json.dumps({"groups": [str(i) for i in range(300)], "n": 300, "role": "TUNE"})
    )
    common = {
        "seed": 42,
        "groups": 300,
        "max_steps": 4,
        "dataset": "musique",
        "feedback": "GroundTruthFeedback",
        "never_terminate": False,
        "penalize_extra_steps": False,
        "per_fact_reward": 0.0,
        "completion_reward": 1.0,
        "reader_calls": 0,
    }
    # A selected early peak and a real final drop must remain distinguishable.
    for stage, step, n in (("initial", 0, 150), ("best", 400, 300), ("final", 10000, 75)):
        d = run / "retrieval" / stage
        d.mkdir(parents=True)
        (d / "actor-binding.json").write_text(
            json.dumps({"stage": stage, "optimizer_updates": step})
        )
        (d / "native-protocol.json").write_text(
            json.dumps(
                {"stage": stage, "optimizer_updates": step, "actor_origin": {}, "common": common}
            )
        )
        records = [
            {
                "id": str(i),
                "f1": int(i < n),
                "em": int(i < n),
                "return": int(i < n),
                "sf_idx": [0],
                "pred_idx": [0] if i < n else [1],
            }
            for i in range(300)
        ]
        (d / "eval_seed42.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
        (d / "validation-launches.jsonl").write_text('{"started_ns":1}\n')
        (d / "validation-resource.jsonl").write_text('{"exit_code":0,"elapsed_seconds":3}\n')
    result = settle.summarize(run, roster, [])
    assert result["fit_duration_scope"].startswith("Lower bound")
    assert result["best_actor_support_f1"] == 1
    assert result["evaluated_groups"] == 300
    comparison = result["native_retrieval"]
    assert comparison["all_three_gt_readbacks_agree"]
    assert comparison["observed_pattern"] == "selected_best_gain_with_final_degradation"
    assert (
        comparison["best_improved_both_support_metrics"]
        and comparison["final_regressed_both_support_metrics"]
    )
    assert comparison["sustained_gain_on_fixed_tune"] == "not_established"
    paired = comparison["paired_differences"]["final_minus_initial"]["support_f1"]
    assert (paired["mean_delta"], paired["regressed"], paired["tied"]) == (-0.25, 75, 225)
    assert result["retrieval_validation_settled_invocations"] == 3
    assert result["one_gpu_retrieval_job_hours"] == pytest.approx(9 / 3600)
    final_rows = run / "retrieval/final/eval_seed42.jsonl"
    complete = [json.loads(line) for line in final_rows.read_text().splitlines()]
    for item in complete:
        hit = int(int(item["id"]) < 225)
        item.update(f1=hit, em=hit, pred_idx=[0] if hit else [1])
        item["return"] = hit
    final_rows.write_text("".join(json.dumps(v) + "\n" for v in complete))
    stale = settle.summarize(run, roster, [])["native_retrieval"]
    assert stale["observed_pattern"] == "unestablished_logged_GT_readback_disagreement"
    for row in curve[-5:]:
        row["gt_dev_return"] = 0.75
    curve_file.write_text("".join(json.dumps(v) + "\n" for v in curve))
    sustained = settle.summarize(run, roster, [])["native_retrieval"]
    assert sustained["sustained_gain_on_fixed_tune"] == "observed"
    final_protocol = run / "retrieval/final/native-protocol.json"
    protocol = json.loads(final_protocol.read_text())
    protocol["common"]["max_steps"] = 5
    final_protocol.write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match="Retrieval settings"):
        settle.summarize(run, roster, [])


def test_terminal_diagnostic_uses_matched_legal_edges_and_frozen_trigger(tmp_path, monkeypatch):
    import random

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    analysis = importlib.import_module("qrag_ref_td_diagnostic")
    retrieval = importlib.import_module("qrag_ref_retrieval")
    fact_ids = {1, 3}
    sample = {"sf_idx": [1, 1, 3], "chunks": ["chunk"] * 8}
    rng = random.Random(42)  # noqa: S311 -- deterministic fixture
    prefix, pos, neg = analysis.prefix_pair(sample, rng)
    assert len(set(prefix)) == 3 and pos not in prefix and neg not in prefix
    assert (
        not fact_ids <= set(prefix)
        and fact_ids <= set(prefix) | {pos}
        and not fact_ids <= set(prefix) | {neg}
    )
    assert analysis.prefix_pair({"sf_idx": [0, 1, 2, 3], "chunks": ["x"] * 4}, rng) is None
    for label, gt in (("decline", 0.1), ("gain", 0.8)):
        run = tmp_path / label
        run.mkdir()
        (run / "config.yaml").write_text("checkpoint_dir: /tmp/fixture-ref\nseed: 42")
        curve = [
            {"optimizer_updates": i, "gt_dev_return": (0.5 if i == 0 else gt)}
            for i in range(0, 601, 100)
        ]
        inputs = run, run / "optional-initial-index.json", tmp_path / "base"
        retrieval.register(*inputs, curve[:1], initial_only=True)
        initial = run / "retrieval/initial/actor-binding.json"
        assert json.loads(initial.read_text())["terminal_td_probe"]["awaiting_terminal_curve"]
        assert not (run / "retrieval/best").exists() and not (run / "retrieval/final").exists()
        retrieval.register(*inputs, curve)
        sealed = initial.read_bytes()
        retrieval.register(*inputs, curve[:1], initial_only=True)
        assert initial.read_bytes() == sealed
        designs = [
            json.loads((run / "retrieval" / s / "actor-binding.json").read_text())[
                "terminal_td_probe"
            ]
            for s in retrieval.STAGES
        ]
        assert designs[0] == designs[1] == designs[2]
        assert designs[0]["enabled"] == (label == "decline") and designs[0]["pairs"] == 32
    fit = analysis.target_fit(
        [{"twice_q1": [3.0, 2.0], "twice_q2": [2.0, 1.0], "terminal_rewards": [0.75, 0.0]}]
    )
    assert fit["twice_q1"]["both_residuals_positive_fraction"] == 1.0
    assert fit["twice_q1"]["mean_residuals"] == [2.25, 2.0]


def test_progress_reads_only_complete_validation_points(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    result = importlib.import_module("qrag_ref_result")
    logs = tmp_path / "tb_logs"
    logs.mkdir()
    row = {"optimizer_updates": 0, "gt_train_return": 0.0, "gt_dev_return": 0.5}
    path = logs / "reference-curve.jsonl"
    path.write_bytes((json.dumps(row) + "\n" + '{"optimizer_updates":100').encode())
    assert result.measured_curve(tmp_path) == [row]
    assert path.read_bytes().endswith(b":100")
    with pytest.raises(ValueError, match="incomplete"):
        result.complete_curve(tmp_path)
