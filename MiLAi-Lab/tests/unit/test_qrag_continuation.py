"""Hand-computed return boundaries and package comparisons specific to V13."""

from types import SimpleNamespace

import pytest

from milai_lab.methods.memory_control import (
    FirstActionIntervention,
    MemoryAction,
    MemoryControlState,
    run_memory_control,
)
from milai_lab.runners.qrag_milai_env import outcome_label


def test_full_continuation_keeps_acting_until_normal_cap():
    read = MemoryAction("read", "READ", "source")
    handoff = MemoryAction("handoff", "HANDOFF", "host")
    ops = SimpleNamespace(actions=lambda s: [read, handoff], execute=lambda a, s: {"ok": True})
    read_policy = SimpleNamespace(choose=lambda s, a: "read")
    state = MemoryControlState({"request": "query"})
    full = run_memory_control(
        state, read_policy, ops, max_steps=5, intervention=FirstActionIntervention(read, None)
    )
    short = run_memory_control(
        state, read_policy, ops, max_steps=5, intervention=FirstActionIntervention(read, 2)
    )
    assert [r["selected"] for r in full["trace"]] == ["read"] * 5
    assert [r["selected"] for r in short["trace"]] == ["read"] * 3 + ["handoff"]


def test_mu_requires_companion_and_distinguishes_unknown_cost():
    grade = {
        "training_quality": 1.0,
        "native_metrics": {
            "gold_answerable": True,
            "sufficiency_correct": True,
            "answer_f1": 0.75,
            "answer_em": 0.0,
            "support_f1": 1.0,
        },
    }
    before = {
        "grade": grade,
        "costs": {
            "incremental_material_tokens": 10,
            "reader_input_tokens": 50,
            "reader_output_tokens": 2,
        },
        "immediate_cost": 4,
        "action_trace": [],
        "status": "scored",
        "termination_reason": "max_operations",
    }
    assert outcome_label("musique_full", before, None)["reader_quality"] is None
    other = {"grade": {"native_metrics": {"gold_answerable": False, "sufficiency_correct": True}}}
    result = outcome_label("musique_full", before, other)
    assert result["reader_quality"] == 0.75
    assert result["future_cost"] == 58
    other["grade"]["native_metrics"]["sufficiency_correct"] = False
    assert outcome_label("musique_full", before, other)["reader_quality"] == 0
    del before["costs"]["reader_output_tokens"]
    assert outcome_label("musique_full", before, other)["future_cost"] is None


def test_td_boundaries_lambda_endpoints():
    torch = pytest.importorskip("torch")
    from milai_lab.methods.qrag_dual_control import td_lambda

    r = torch.tensor([0.0, 0.0, 0.75])
    v = torch.tensor([0.2, 0.4, 100.0])
    ended = torch.tensor([False, False, True])
    torch.testing.assert_close(td_lambda(r, v, ended, 0), torch.tensor([0.2, 0.4, 0.75]))
    torch.testing.assert_close(td_lambda(r, v, ended, 1), torch.tensor([0.75] * 3))
    # A collection window ending before HANDOFF still bootstraps.
    torch.testing.assert_close(td_lambda(r[:2], v[:2], ended[:2], 1), torch.tensor([0.4, 0.4]))


def test_structured_margin_uses_whole_pack_cost():
    import numpy as np

    from milai_lab.runners.control_policy_iteration import sampler_priority
    from milai_lab.runners.qrag_milai_env import ComparisonPack

    pack = ComparisonPack(("handoff", "read_1"), (("read_1", "handoff"),), ())
    online = {"actions": [{"id": "handoff"}, {"id": "read_1"}]}
    net = np.array([[0.0] * 4, [-2.0, -1.0, 1.0, 2.0]])
    assert sampler_priority("structured", net, online, pack, 5) == pytest.approx(0.5)
    assert sampler_priority("structured", net + np.array([[0], [5.0]]), online, pack, 5) == 0


def test_registered_peer_action_precedes_equivalent_prior_wire(tmp_path, monkeypatch):
    from milai_lab.runners import control_policy_iteration as iteration

    local = tmp_path / "local"
    peer = tmp_path / "peer"
    wire = {"seed": 11, "messages": ["same packet"]}

    def measured(result, tokens):
        return {
            "task_id": 1,
            "grade": {"quality": 1.0},
            "reader_wire": wire,
            "actual_requests": 1,
            "feedback_exposure": 1,
            "status": "scored",
            "reader_result": {"response": result},
            "costs": {"reader_output_tokens": tokens},
        }

    iteration.write_gzip(local / "action1.json.gz", measured("first", 76))
    iteration.write_gzip(peer / "action2.json.gz", measured("repeat", 94))
    monkeypatch.setattr(
        iteration, "collect_terminal", lambda *args, **kwargs: {"reader_wire": wire, "costs": {}}
    )
    monkeypatch.setattr(
        iteration, "score_episode", lambda ds, db, task, r: r.update(grade={"quality": 1.0})
    )
    ledger = iteration.Receipts(local, None, None, [peer])
    receipt = ledger.measure({"id": 1, "native_group": "same-group"}, None, None, 11, "action2")
    assert receipt["reader_result"]["response"] == "repeat"
    assert receipt["costs"]["reader_output_tokens"] == 94
    assert receipt["actual_requests"] == 0 and receipt["feedback_exposure"] == 1


def test_12k_resume_preserves_actor_target_optimizer_and_rng(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    from milai_lab.datasets.memory_control_report import read_json, write_json
    from milai_lab.runners import qrag_resume
    from milai_lab.runners.control_policy_iteration import write_gzip

    class TinyControl(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.tensor([0.25, 0.5]))
            self.device = self.weight.device

        def net(self, online, penalty):
            return self.weight * torch.tensor(online["features"]) - penalty

    def take_step(model, optimizer, noise):
        optimizer.zero_grad()
        ((model.weight - noise) ** 2).sum().backward()
        optimizer.step()

    model, target = TinyControl(), TinyControl()
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
    take_step(model, optimizer, torch.tensor([0.1, 0.2]))
    with torch.no_grad():
        target.weight.lerp_(model.weight, 0.5)
    run = tmp_path
    checkpoint = tmp_path / "checkpoint-12000"
    checkpoint.mkdir()
    online = {"features": [1.0, 2.0]}
    payload = {"transitions": [{"online": online}]}
    write_gzip(tmp_path / "receipt.json.gz", payload)
    binding = dict(calls=12000, optimizer_updates=1, dataset_run_id="train", fitted_groups=["g"])
    probe = dict(
        receipt_id="receipt",
        utility_lambda=0.05,
        transition_index=0,
        saved_live_scores=model.net(online, 0.05).detach().tolist(),
    )
    write_json(checkpoint / "training.json", binding)
    write_json(checkpoint / "controller.json", {"cost_scale": 1.0})
    write_json(checkpoint / "score_probe.json", probe)
    contract = {"dataset_run_id": "train"}
    monkeypatch.setattr(qrag_resume, "free_bytes", lambda _: 3 * 1024**3)
    qrag_resume.save_resume(run, checkpoint, model, target, optimizer, contract)
    assert not (run / "resume-12000.pt").exists()
    assert read_json(run / "resume-storage.json")["status"] == "replay_required_insufficient_space"
    monkeypatch.setattr(qrag_resume, "free_bytes", lambda _: 8 * 1024**3)
    qrag_resume.save_resume(run, checkpoint, model, target, optimizer, contract)
    noise = torch.rand(2)
    take_step(model, optimizer, noise)
    restored, restored_target = TinyControl(), TinyControl()
    restored_opt = torch.optim.AdamW(restored.parameters(), lr=0.1)
    receipts = SimpleNamespace(path=lambda _: tmp_path / "receipt.json.gz")
    assert (
        qrag_resume.restore_resume(
            run, checkpoint, restored, restored_target, restored_opt, contract, receipts
        )
        == binding
    )
    torch.testing.assert_close(restored_target.weight, target.weight, rtol=0, atol=0)
    next_noise = torch.rand(2)
    torch.testing.assert_close(next_noise, noise, rtol=0, atol=0)
    take_step(restored, restored_opt, next_noise)
    torch.testing.assert_close(model.weight, restored.weight, rtol=0, atol=0)


def test_phase_drains_online_group_before_admitting_reader(tmp_path):
    import threading
    import time

    from milai_lab.runners.v13_phase import activate, phase_directory, phase_unit, state

    activate(tmp_path, ["qr"])
    gate = phase_directory(tmp_path / "qr-11")
    assert gate is not None
    reader_entered = threading.Event()

    def read():
        with phase_unit(gate, "reader"):
            reader_entered.set()

    with phase_unit(gate, "qr"):
        change = threading.Thread(target=activate, args=(tmp_path, ["reader"]), daemon=True)
        change.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and state(gate)["state"] != "draining":
            time.sleep(0.01)
        assert state(gate)["state"] == "draining"
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        assert not reader_entered.wait(0.05)
    change.join(3)
    reader.join(3)
    assert state(gate)["allow"] == ["reader"] and reader_entered.is_set()
