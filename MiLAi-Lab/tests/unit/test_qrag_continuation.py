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


def test_masked_qr_batch_leaves_the_rollout_actor_in_eval_mode():
    torch = pytest.importorskip("torch")
    from milai_lab.runners.qrag_milai_train import update_batch

    model = torch.nn.Sequential(torch.nn.Dropout(0.5), torch.nn.Linear(8, 2)).eval()
    optimizer = torch.optim.AdamW(model.parameters())
    inputs = torch.ones(1, 8)
    with torch.inference_mode():
        expected = model(inputs)
    rng = torch.get_rng_state().clone()
    versions = [p._version for p in model.parameters()]
    assert (
        update_batch(model, None, optimizer, [([{"action_id": "handoff"}], None, None)], None)
        is None
    )
    assert not model.training and not optimizer.state
    with torch.inference_mode():
        assert torch.equal(expected, model(inputs))
    assert torch.equal(rng, torch.get_rng_state())
    assert [p._version for p in model.parameters()] == versions


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


def test_shared_warm_and_peer_aliases_quote_and_charge_each_measurement_once(tmp_path, monkeypatch):
    from milai_lab.runners import control_policy_iteration as it

    warm, peer, local = (tmp_path / name for name in ("warm", "peer", "local"))
    wire = {"messages": ["packet"], "seed": 11}
    for directory, key, tid in (
        (warm, "warm-branch", 1),
        (peer, "a", 2),
        (peer, "b", 2),
        (peer, "peer-branch", 3),
    ):
        it.write_gzip(
            directory / (key + ".json.gz"),
            dict(
                task_id=tid,
                status="scored",
                reader_wire=wire,
                reader_result=key,
                grade={"score": 1},
                feedback_exposure=1,
                actual_requests=1,
                costs={},
            ),
        )
    warm_origin = warm / "warm-branch.json.gz"
    it.write_gzip(
        peer / "peer-copy.json.gz",
        dict(
            it.read_gzip(warm_origin),
            actual_requests=0,
            measurement_reused_from=str(warm_origin),
        ),
    )
    monkeypatch.setattr(it, "score_episode", lambda ds, db, task, r: r.update(grade={"score": 1}))
    receipts = it.Receipts(local, None, None, [peer], credited_dir=warm)
    tasks_and_keys = [
        (1, "companion"),
        (1, "peer-copy"),
        (2, "b"),
        (2, "alternate"),
        (2, "a"),
        (3, "other"),
    ]
    jobs = [
        it.TerminalJob({"id": tid, "native_group": "g"}, None, None, 11, key)
        for tid, key in tasks_and_keys
    ]
    prepared = [({"reader_wire": wire, "costs": {}}, True) for _ in jobs]
    assert receipts.quote(jobs, prepared) == dict(
        independent_feedback_units=2,
        expected_arm_exposure=3,
        expected_new_requests=0,
        exposure_upper_bound=3,
    )
    rows = receipts.measure_batch(jobs, prepared)
    assert [r["reader_result"] for r in rows] == [
        "warm-branch",
        "warm-branch",
        "b",
        "b",
        "a",
        "peer-branch",
    ]
    assert [r["feedback_exposure"] for r in rows] == [0, 0, 1, 0, 1, 1]
    restored = it.Receipts(local, None, None, [peer], credited_dir=warm)
    assert (restored.calls, restored.new_requests) == (3, 0)
    other_seed = {"reader_wire": {**wire, "seed": 12}}
    assert restored.quote(jobs[:1], [(other_seed, True)])["expected_new_requests"] == 1


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


def test_quote_distinguishes_cached_exposure_from_shared_physical_calls(tmp_path):
    from milai_lab.runners.control_policy_iteration import Receipts, TerminalJob, write_gzip

    wire = {"seed": 11, "messages": ["same terminal packet"]}
    task = {"id": 1}
    jobs = [TerminalJob(task, None, None, 11, "a"), TerminalJob(task, None, None, 11, "b")]
    prepared = [({"reader_wire": wire}, True) for _ in jobs]
    local = Receipts(tmp_path / "arm", None, None)
    cost = local.quote(jobs, prepared)
    assert cost == {
        "independent_feedback_units": 1,
        "expected_arm_exposure": 1,
        "expected_new_requests": 1,
        "exposure_upper_bound": 2,
    }
    peer = tmp_path / "peer"
    for job in jobs:
        write_gzip(
            peer / (job.key + ".json.gz"),
            dict(
                task_id=1,
                reader_wire=wire,
                grade={"status": "scored"},
                actual_requests=1,
                feedback_exposure=1,
            ),
        )
    reused = Receipts(tmp_path / "other_arm", None, None, [peer])
    cost = reused.quote(jobs, prepared)
    assert cost == {
        "independent_feedback_units": 1,
        "expected_arm_exposure": 2,
        "expected_new_requests": 0,
        "exposure_upper_bound": 2,
    }


def test_source_pool_caps_selected_roots_and_corrects_source_exposure():
    import random
    import sqlite3

    from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER
    from milai_lab.runners.control_acquisition_pool import NativeRootPool

    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE experiment_tasks (dataset,native_group,id,experiment_role,clean_role)")
    source_rows = [
        (s, f"g{g}", k * 1000 + g * 12 + i, "train", "train")
        for k, s in enumerate((MUSIQUE, QASPER, PERSONA))
        for g in range(20)
        for i in range(12)
    ]
    db.executemany("INSERT INTO experiment_tasks VALUES (?,?,?,?,?)", source_rows)
    pool = NativeRootPool(db)
    # Every not-yet-selected task can enter a slate until that group exhausts its six slots.
    assert len(pool.available[PERSONA]["g0"]) == 12
    for i in range(6):
        pool.accept(dict(source=PERSONA, native_group_id="g0", task_id=2000 + i))
    assert "g0" not in pool.available[PERSONA]
    for i in range(94):
        slate, _ = pool.slate(8, random.Random(i))  # noqa: S311 -- repeatable pool test
        s, g, t = slate[0]
        pool.accept(dict(source=s, native_group_id=g, task_id=t))
    assert pool.source_counts == {MUSIQUE: 60, QASPER: 30, PERSONA: 10}
    db.close()


def test_qr_round_roster_uses_actual_exposure_and_restores_the_same_suffix():
    import sqlite3
    from collections import Counter
    from contextlib import closing

    from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER
    from milai_lab.runners.control_policy_iteration import qr_roster_positions

    limits = (80, 160, 320)
    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        db.execute(
            "CREATE TABLE experiment_tasks(id INTEGER PRIMARY KEY, dataset, native_group, "
            "experiment_role, clean_role)"
        )
        for src, groups, tasks in ((MUSIQUE, 120, 2), (QASPER, 20, 6), (PERSONA, 1, 12)):
            db.executemany(
                "INSERT INTO experiment_tasks VALUES (NULL,?,?, 'train','train')",
                [(src, str(g)) for g in range(groups) for _ in range(tasks)],
            )

        def replay(start=0, after=-1):
            paid = start
            rows = []
            visits = Counter()
            counts = Counter()
            stages = Counter()
            roster = qr_roster_positions(
                db,
                11,
                lambda: paid,
                limits[-1],
                staged=True,
                after_position=after,
                checkpoints=limits,
            )
            for pos, (src, group, tid) in roster:
                boundary = next(n for n in limits if n > paid)
                stages[boundary] += 1
                counts[boundary, src] += 1
                visits[boundary, src, group] += 1
                assert counts[boundary, PERSONA] <= stages[boundary] // 10
                assert visits[boundary, src, group] <= (4 if src == MUSIQUE else 6)
                charge = 0 if pos % 17 == 0 else 1 + int(src == MUSIQUE)
                paid += charge
                assert paid <= boundary
                rows.append((boundary, pos, src, tid, charge))
            assert paid == limits[-1]
            return rows

        rows = replay()
        for boundary in limits:
            part = [x for x in rows if x[0] == boundary]
            assert len({x[3] for x in part}) == len(part)
            assert any(x[2] == PERSONA for x in part)
        saved_position = max(x[1] for x in rows if x[0] == 160)
        assert replay(160, saved_position) == [x for x in rows if x[0] == 320]


def test_interrupted_paid_feedback_keeps_confirmed_charge_and_unknown_quality(tmp_path):
    from milai_lab.datasets.memory_control_report import write_json
    from milai_lab.runners.control_policy_iteration import Receipts, read_gzip

    write_json(
        tmp_path / "known.inflight",
        {
            "metered_request_recorded": True,
            "feedback_exposure": 1,
            "actual_requests": 1,
            "ledger_before": 4,
            "ledger_after": 5,
        },
    )
    write_json(tmp_path / "uncertain.inflight", {"feedback_exposure": 0, "actual_requests": 0})
    receipts = Receipts(tmp_path, None, None)
    assert (receipts.calls, receipts.new_requests) == (2, 1)
    known = read_gzip(receipts.path("known"))
    unknown = read_gzip(receipts.path("uncertain"))
    assert known["actual_requests"] == 1 and known["ledger_after"] == 5 and "grade" not in known
    assert unknown["actual_requests"] is None and unknown["feedback_exposure"] == 1
