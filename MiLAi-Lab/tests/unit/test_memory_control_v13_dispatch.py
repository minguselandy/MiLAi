"""Exercise paired windows and native packet billing with an in-memory Reader."""

import importlib
import json
import sqlite3
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from milai_lab.runners import memory_control_episode as native
from milai_lab.runners import memory_control_reader_timing as timing


def test_fixed_windows_resume_without_reissuing_or_double_billing(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    driver = importlib.import_module("dispatch_memory_control_v13")
    evaluation = importlib.import_module("run_memory_control_v13_evaluation")
    costs = importlib.import_module("report_memory_control_v13_project_cost")
    readout = importlib.import_module("report_memory_control_v13_deployment")
    arms = [
        {
            "name": n,
            "policy": "B1",
            "observation_protocol": evaluation.DELTA_NAVIGATION,
            "environment": "qrag_milai_v13",
        }
        for n in ("A", "B", "C")
    ]
    tasks = [
        {"task_id": i, "dataset": source, "native_group": source + "-fixture"}
        for i, source in enumerate(
            ("musique_full", "musique_full", "qasper", "qasper", "personamem_v2", "personamem_v2"),
            1,
        )
    ]
    data = tmp_path / "fixture.sqlite"
    with sqlite3.connect(data) as db:
        db.execute(
            "CREATE TABLE experiment_tasks(id INTEGER, dataset TEXT, native_group TEXT,"
            " experiment_role TEXT)"
        )
        db.executemany(
            "INSERT INTO experiment_tasks VALUES(?,?,?,'confirm')",
            [(r["task_id"], r["dataset"], r["native_group"]) for r in tasks],
        )
    reg = tmp_path / "frozen"
    reg.mkdir()
    order = driver.order_contract(arms, 2, 123)
    slots = driver.schedule(order, len(tasks))
    pop = {
        "role": "confirm",
        "v13_role": "confirm_fresh",
        "v13_dispatch": order,
        "protocol": native.EVALUATION_PROTOCOL,
        "seed": 11,
        "dataset_path": str(data),
        "dataset_run_id": "synthetic",
        "material_budget": 2048,
        "tasks": tasks,
        "arms": arms,
    }
    settings = {
        "dispatch": order,
        "run_directories": {a["name"]: a["name"] for a in arms},
        "max_reader_calls": 18,
    }
    for name, obj in [
        ("population", pop),
        ("registration", settings),
        ("dispatch-schedule", slots),
    ]:
        (reg / f"{name}.json").write_text(json.dumps(obj))
    host = SimpleNamespace(settings={"host": {}}, capacity=None)
    ds = SimpleNamespace(
        path=data,
        host=host,
        revision={},
        run_id="synthetic",
        numeric_observation=True,
        observation_protocol=evaluation.DELTA_NAVIGATION,
    )
    budget = SimpleNamespace(state={"generation_requests": 0})
    monkeypatch.setattr(native, "comparison_protocol", lambda ds: {})
    monkeypatch.setattr(native, "make_policy", lambda *_: (object(), None))
    monkeypatch.setattr(native, "ownership_client_configs", lambda _: ())
    monkeypatch.setattr(native, "VLLMConfig", lambda **_: None)
    monkeypatch.setattr(native, "VLLMClient", lambda *args, **kwargs: nullcontext(None))
    monkeypatch.setattr(native, "http_budget_scope", lambda *args, **kwargs: nullcontext(budget))
    monkeypatch.setattr(native, "remaining_reader_capacity", lambda _: {})
    monkeypatch.setattr(timing, "snapshot", lambda _: None)
    monkeypatch.setattr(timing, "interval", lambda *args: {})
    by_id = {t["task_id"]: t for t in tasks}

    def prepare(_ds, _db, row, arm, _policy, _model, _budget, seed):
        return {
            **by_id[row["id"]],
            "status": "ready",
            "capacity": {},
            "costs": {"episode_local_wall_ms": 1.0},
            "reader_wire": {"seed": seed, "arm": arm["name"]},
        }

    attempted = []

    def request(_client, _host, wire, _capacity, *, on_metered_request):
        key = (wire["arm"], wire["seed"] - 11)
        assert key not in attempted
        attempted.append(key)
        budget.state["generation_requests"] += 1
        on_metered_request()
        if len(attempted) == 1:
            raise RuntimeError("process interrupted after reservation")
        return {"status": "reader_completed", "response": {"id": f"fixture-{len(attempted)}"}}, {
            "reader_request_attempted": True,
            "reader_client_wall_ms": 2.0,
            "reader_usage_source": "provider",
            "reader_input_tokens": 4,
            "reader_output_tokens": 1,
        }

    def score(_ds, _db, row, record):
        record.update(
            status="scored",
            grade={
                "native_metrics": {
                    "gold_answerable": row["id"] % 2 == 1,
                    "sufficiency_correct": True,
                    "answer_f1": 1.0,
                    "support_f1": 1.0,
                    "answer_em": 1.0,
                    "accuracy": 1.0,
                }
            },
        )

    monkeypatch.setattr(native, "episode_before_reader", prepare)
    monkeypatch.setattr(native, "request_reader", request)
    monkeypatch.setattr(native, "score_episode", score)
    args = SimpleNamespace(
        registration=reg, runs=tmp_path / "runs", device="cpu", limit_windows=None
    )

    def run():
        return driver.dispatch(args, dataset_factory=lambda *a, **kw: ds)

    with pytest.raises(RuntimeError, match="after reservation"):
        run()
    first = slots[0]["arm"]
    # The open invocation is already chargeable from its atomically written packet.
    assert costs.aggregate(args.runs)["totals"]["settled_new_requests"] == 1
    real_append = driver.append_window

    def interrupt_cursor(path, row):
        if path.name == "dispatch-windows.jsonl":
            raise RuntimeError("lost cursor after native window")
        return real_append(path, row)

    monkeypatch.setattr(driver, "append_window", interrupt_cursor)
    with pytest.raises(RuntimeError, match="lost cursor"):
        run()
    assert len(attempted) == 2
    monkeypatch.setattr(driver, "append_window", real_append)
    args.limit_windows = 1
    assert run()["completed_slots"] == 1
    assert len(attempted) == 2
    args.limit_windows = None
    native_append = evaluation.append_window

    def lose_log(path, receipt):
        if receipt.get("dispatch_slot") == 1 and receipt.get("window_complete"):
            raise RuntimeError("native settlement written but log append lost")
        return native_append(path, receipt)

    monkeypatch.setattr(evaluation, "append_window", lose_log)
    with pytest.raises(RuntimeError, match="log append lost"):
        run()
    assert len(attempted) == 4
    monkeypatch.setattr(evaluation, "append_window", native_append)
    assert run()["status"] == "COMPLETED" and len(attempted) == 18
    assert run()["windows_advanced"] == 0 and len(attempted) == 18
    chron = [(e["arm"], t["task_id"]) for e in slots for t in tasks[slice(*e["span"])]]
    assert attempted == chron
    assert all(len({e["position"] for e in slots if e["arm"] == a["name"]}) == 3 for a in arms)
    report = costs.aggregate(args.runs)
    assert report["totals"]["settled_new_requests"] == 18 == report["distinct_checked_slots"]
    assert report["distinct_observed_provider_requests"] == 17
    assert report["totals"]["paid_error_packets"] == 1
    assert readout.summarize_run(args.runs / first)["policy_load_ms_per_attempt"] is None
    received = [
        json.loads(line) for line in (args.runs / "dispatch-windows.jsonl").read_text().splitlines()
    ]
    assert [r["slot"] for r in received] == list(range(9)) and received[0]["recovered_cursor"]


def test_partial_window_charge_attribution(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    billing = importlib.import_module("report_memory_control_v13_project_cost")
    ws = [
        {
            "invocation_id": "a",
            "reader_requests_this_invocation": 2,
            "ledger_before": 10,
            "ledger_after": 12,
        }
    ]
    packets = {}
    for i, (inv, start, end) in enumerate(
        [("a", 10, 11), ("a", 11, 12), ("b", 14, 15), ("c", 17, None)]
    ):
        packets[i] = {
            "reader_charge": {"invocation_id": inv, "ledger_before": start, "ledger_after": end}
        }
    counts, slots = billing.readout_charge_evidence(ws, packets)
    assert slots == {10, 11, 14} and counts["settled_new_requests"] == 3
    assert counts["packet_only_new_requests"] == 1 and counts["unknown_charge_records"] == 1
    ws.append(
        {"invocation_id": "b", "reader_requests_this_invocation": 1, "ledger_intervals": [[14, 15]]}
    )
    ws.append(
        {
            "invocation_id": "c",
            "reader_requests_this_invocation": 0,
            "ledger_intervals": [],
            "reader_charge_unknown_records": 1,
        }
    )
    counts, slots = billing.readout_charge_evidence(ws, packets)
    assert counts["packet_only_new_requests"] == 0 and counts["settled_new_requests"] == 3
    assert counts["unknown_charge_records"] == 1
    assert billing.slot_set({"ledger_before": 3, "ledger_after": float("inf")}) is None
    with pytest.raises(ValueError, match="twice"):
        billing.readout_charge_evidence(ws, {**packets, 9: packets[0]})


@pytest.mark.parametrize(("arms", "blocks", "replicates"), [(4, 4, 1), (3, 6, 2)])
def test_registered_order_balances_slot_and_predecessor(arms, blocks, replicates, monkeypatch):
    from collections import Counter
    from itertools import pairwise

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    module = importlib.import_module("dispatch_memory_control_v13")
    names = [{"name": str(i)} for i in range(arms)]
    order = module.schedule(module.order_contract(names, 1, 42), blocks)
    pairs = Counter()
    positions = Counter()
    for block in range(blocks):
        row = [s for s in order if s["block"] == block]
        pairs.update(pairwise(s["arm"] for s in row))
        positions.update((s["arm"], s["position"]) for s in row)
    assert len(positions) == arms**2 and set(positions.values()) == {replicates}
    assert len(pairs) == arms * (arms - 1) and set(pairs.values()) == {replicates}
