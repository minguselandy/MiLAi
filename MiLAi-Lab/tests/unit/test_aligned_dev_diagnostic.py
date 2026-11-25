"""An aligned capture recomputes the companion, including when the two HANDOFFs hit cache."""

import importlib
import json
import sqlite3
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest


def dump(path, obj):
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(obj))


@pytest.fixture
def trial(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    tool = importlib.import_module("diagnose_memory_control_v13_evidence")
    transport = importlib.import_module("milai_lab.runners.control_policy_iteration")
    source = tool.MUSIQUE
    data = tmp_path / "native.sqlite"
    with sqlite3.connect(data) as db:
        db.execute("CREATE TABLE experiment_tasks(id, dataset,native_group,experiment_role)")
        db.executemany(
            "INSERT INTO experiment_tasks VALUES(?,?,?,?)",
            [(i, source, "g", "dev") for i in (1, 2)],
        )
    ds = SimpleNamespace(
        path=data,
        run_id="dataset",
        observation_protocol="legal",
        host=SimpleNamespace(settings={"host": {}}, capacity={}),
    )
    proto = {"scorer": "native", "provider_seed": "wire_seed_recorded"}
    learned = str(tmp_path / "weights/checkpoint")
    monkeypatch.setattr(tool, "MemoryControlDataset", lambda _: ds)
    monkeypatch.setattr(tool, "comparison_protocol", lambda *a: proto)
    opts = SimpleNamespace(
        output=tmp_path / "out",
        reuse_capture=tmp_path / "donor",
        data=data,
        population=tmp_path / "roster.json",
        target_round=tmp_path / "round",
        per_source=1,
        tolerance=64,
        device="cpu",
        reuse_only=False,
    )
    dump(
        opts.population,
        dict(
            role="dev",
            v13_role="curve",
            material_budget=2048,
            seed=11,
            dataset_run_id="dataset",
            tasks=[{"dataset": source, "native_group": "g", "task_id": 1}],
        ),
    )
    dump(
        opts.reuse_capture / "registration.json",
        dict(
            population=str(opts.population.resolve()),
            seed=11,
            role="TUNE_diagnostic",
            dataset_run_id="dataset",
            material_budget=2048,
            budget_tolerance=64,
            cap_per_source=1,
            max_operations=6,
            continuation="pi0-fixedcontext-4",
        ),
    )
    dump(
        opts.reuse_capture / "capture.json",
        dict(groups={source: 1}, unmatched={}, feedback_calls=5),
    )
    (opts.reuse_capture / ".lock").touch()
    dump(
        opts.target_round / "round.json",
        dict(
            dataset_run="dataset",
            observation="legal",
            environment=dict(retrieval=32, scored=8, max_operations=6, gamma=1.0),
            material_budget=2048,
            reader=proto,
            continuation_mode="full_episode",
            continuation_policy_id=learned,
            seed=47,
            round=3,
            utility_lambda=0.1,
        ),
    )
    dump(opts.target_round / "progress.json", {"state": "complete"})
    monkeypatch.setattr(tool, "matched_prefixes", lambda *a: (("p", "q"), "r", 1, None))

    def cold(ds, db, task, budget, prefix=("search",), pool=None):
        env = SimpleNamespace(
            tid=task["id"], prefix=list(prefix), online=lambda m: {"prefix": list(prefix)}
        )
        return env, [SimpleNamespace(id="handoff"), SimpleNamespace(id="r")], {}

    monkeypatch.setattr(tool, "cold_root", cold)

    def terminal(env, policy, seed, first=None, **_):
        aid = first.id if first else "rollout"
        pi = "shared" if aid == "handoff" else "new" if policy == learned else "old"
        return dict(
            reader_wire={
                "seed": seed,
                "model": "m",
                "prefix": env.prefix,
                "action": aid,
                "pi": pi,
                "tid": env.tid,
            },
            status="ready",
            termination_reason="handoff",
            action_trace=[aid, pi],
            immediate_cost=0,
            visible_source_aliases={},
            capacity={},
            costs=dict(incremental_material_tokens=0),
        )

    monkeypatch.setattr(tool, "collect_terminal", terminal)
    monkeypatch.setattr(transport, "collect_terminal", terminal)
    loads = []

    def load(ds, path, device, penalty):
        loads.append((str(path), device, penalty))
        return str(path), None

    monkeypatch.setattr(tool, "load_policy", load)

    def score(ds, db, task, record):
        response = record["reader_result"]["response"]
        record.update(
            status="scored",
            grade={
                "training_quality": 1.0,
                "native_metrics": {
                    "gold_answerable": task["id"] == 1,
                    "sufficiency_correct": response["answer"] == "right",
                    "answer_f1": 1.0,
                    "answer_em": 1.0,
                    "support_f1": 1.0,
                },
            },
        )

    monkeypatch.setattr(tool, "score_episode", score)
    monkeypatch.setattr(transport, "score_episode", score)
    budget = SimpleNamespace(state={"generation_requests": 99})
    monkeypatch.setattr(transport, "reader_lease", lambda _: nullcontext(budget))
    monkeypatch.setattr(transport, "VLLMConfig", lambda **kw: None)
    monkeypatch.setattr(transport, "VLLMClient", lambda *a, **kw: nullcontext(None))
    issued = []

    def response(w, ident):
        return dict(
            status="reader_completed",
            response={
                "model": "m",
                "id": ident,
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
                "answer": "wrong" if w["tid"] == 2 and w["pi"] == "new" else "right",
            },
        )

    def read(client, host, wire, capacity, on_metered_request):
        issued.append(wire)
        budget.state["generation_requests"] += 1
        on_metered_request()
        return response(wire, "new" + str(len(issued))), dict(
            reader_input_tokens=5, reader_output_tokens=1
        )

    monkeypatch.setattr(transport, "request_reader", read)
    states = []
    slot = 0
    for tid, prefix, aid in [(2, ("search",), None)] + [
        (1, ("search", x), y) for x in ("p", "q") for y in ("handoff", "r")
    ]:
        env, _, _ = cold(ds, None, {"id": tid}, 2048, prefix)
        rec = terminal(env, None, 12, SimpleNamespace(id=aid) if aid else None)
        key = f"1_{prefix[-1]}_{aid}" if aid else "companion_2"
        rec.update(
            receipt_id=key,
            native_group_id="g",
            task_id=tid,
            actual_requests=1,
            ledger_before=slot,
            ledger_after=slot + 1,
            feedback_exposure=1,
            reader_result=response(rec["reader_wire"], "original" + str(slot)),
        )
        rec["costs"].update(
            reader_input_tokens=5, reader_output_tokens=1, reader_usage_source="provider"
        )
        score(ds, None, {"id": tid}, rec)
        tool.write_gzip(opts.reuse_capture / "receipts" / (key + ".json.gz"), rec)
        slot += 1
    for prefix in ("p", "q"):
        states.append(
            dict(
                prefix=prefix,
                online={"prefix": ["search", prefix]},
                labels={
                    aid: {"reader_quality": 1.0, "companion_receipt_id": "companion_2"}
                    for aid in ("handoff", "r")
                },
            )
        )
    tool.write_gzip(
        opts.reuse_capture / "pairs/1.json.gz",
        dict(
            task_id=1,
            native_group="g",
            dataset=source,
            split_role="dev",
            candidate="r",
            material_tokens_difference=1,
            states=states,
        ),
    )
    return tool, opts, issued, loads, learned


def test_changed_continuation_reuses_only_transport_and_rebuilds_native_pair(trial):
    tool, opts, issued, loads, learned = trial
    tool.collect(opts)
    assert loads == [(learned, "cpu", 0.1)]
    assert len(issued) == 3 and all(r["pi"] == "new" and r["seed"] == 12 for r in issued)
    assert sum(r["tid"] == 2 for r in issued) == 1
    assert tool.read_json(opts.output / "registration.json")["continuation"] == learned
    summary = tool.read_json(opts.output / "capture.json")
    assert (
        summary["feedback_calls"],
        summary["actual_new_requests"],
        summary["reused_responses"],
    ) == (5, 3, 2)
    assert summary["by_kind"]["handoff"]["new_requests"] == 0
    pair = tool.read_gzip(opts.output / "pairs/1.json.gz")
    for state in pair["states"]:
        assert all(
            o["reader_quality"] == 0 and o["quality_observed"] for o in state["labels"].values()
        )
    tool.collect(opts)
    assert len(issued) == 3 and len(loads) == 1


def test_bad_donor_score_or_wire_is_explicitly_billed(trial):
    tool, opts, issued, _, _ = trial
    for prefix, damage in (("p", "grade"), ("q", "seed")):
        path = opts.reuse_capture / "receipts" / f"1_{prefix}_handoff.json.gz"
        r = tool.read_gzip(path)
        if damage == "grade":
            r["grade"]["training_quality"] = 0.123
        else:
            r["reader_wire"]["seed"] += 1
        tool.write_gzip(path, r)
    tool.collect(opts)
    assert len(issued) == 5
    assert (
        tool.read_json(opts.output / "preflight.json")["new_request_upper_bound_given_handoffs"]
        == 5
    )


def test_changed_prefix_or_candidate_is_rejected_before_dispatch(trial):
    tool, opts, issued, _, _ = trial
    path = opts.reuse_capture / "pairs/1.json.gz"
    row = tool.read_gzip(path)
    row["candidate"] = "unknown"
    tool.write_gzip(path, row)
    with pytest.raises(ValueError, match="candidate"):
        tool.collect(opts)
    assert issued == []


def test_offline_mode_cannot_buy_changed_wires(trial):
    tool, opts, issued, _, _ = trial
    opts.reuse_only = True
    with pytest.raises(RuntimeError, match="cannot issue HTTP"):
        tool.collect(opts)
    assert issued == []


def test_failed_new_companion_masks_all_four_pair_targets_but_charges_attempt(trial, monkeypatch):
    tool, opts, _, _, _ = trial
    transport = importlib.import_module("milai_lab.runners.control_policy_iteration")
    actual = transport.request_reader

    def failure(client, host, wire, capacity, on_metered_request):
        result, cost = actual(client, host, wire, capacity, on_metered_request)
        if wire["tid"] == 2:
            return {"status": "reader_error", "error_type": "test_timeout"}, {
                "reader_request_attempted": True
            }
        return result, cost

    monkeypatch.setattr(transport, "request_reader", failure)
    tool.collect(opts)
    summary = tool.read_json(opts.output / "capture.json")
    assert summary["actual_new_requests"] == 3 and summary["feedback_calls"] == 5
    assert summary["by_kind"]["companion"]["masked_single_task_results"] == 1
    assert summary["masked_quality_labels"] == 4 and summary["masked_future_cost_labels"] == 0


def test_overread_signed_errors_cost_mask_and_zero_denominator(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    tool = importlib.import_module("diagnose_memory_control_v13_evidence")
    # Observed quality gap +.1, total cost gap 300, lambda .05 and scale 100: utility -.05.
    labels = {
        "r": dict(
            quality_observed=True,
            reader_quality=0.6,
            immediate_cost=120,
            future_cost=230,
            future_cost_observed=True,
        ),
        "handoff": dict(
            quality_observed=True,
            reader_quality=0.5,
            immediate_cost=0,
            future_cost=50,
            future_cost_observed=True,
        ),
    }
    truth = tool.native_deltas(labels, "r", 0.05, 100)
    a = tool.overread_error_terms(truth, 0.08, 0.03, True)
    assert a == pytest.approx(
        dict(net_gain_error=0.08, quality_gain_error=-0.02, cost_underestimate_contribution=0.1)
    )
    b = tool.overread_error_terms(truth, 0.30, 0.10, True)
    assert b == pytest.approx(
        dict(net_gain_error=0.15, quality_gain_error=0.20, cost_underestimate_contribution=-0.05)
    )
    summary = tool.summarize_overreads([a, b])
    assert summary["n"] == 2
    assert summary["mean"] == pytest.approx(
        {
            "net_gain_error": 0.115,
            "quality_gain_error": 0.09,
            "cost_underestimate_contribution": 0.025,
        }
    )
    assert tool.overread_error_terms(truth, 0.08, 0, False) is None
    assert tool.overread_error_terms(truth, 0.08, 0, True)["net_gain_error"] == pytest.approx(0.05)
    assert tool.overread_error_terms({"quality": 0, "utility": 0}, 0.1, 0.1, True) is None
    labels["r"]["future_cost_observed"] = False
    assert (
        tool.overread_error_terms(tool.native_deltas(labels, "r", 0.05, 100), 0.3, 0.1, True)
        is None
    )
    empty = tool.summarize_overreads([])
    assert empty["n"] == 0 and all(x is None for x in empty["mean"].values())
