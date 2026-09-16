import copy
import json
import random
from pathlib import Path

import pytest

from milai_lab.methods.evidence_utility_session import messages_digest
from milai_lab.methods.memrl_port import (
    METHOD_VERSION,
    MemRLBank,
    MemRLConfig,
    MemRLSession,
    memory_context,
    restore_rng,
    retrieve,
)
from milai_lab.methods.reasoning_bank import MemoryOutputError

POLICIES = {
    p.stem: p.read_text()
    for p in (Path(__file__).resolve().parents[2] / "configs/policies/memrl").glob("*.txt")
}


def make_bank(**config):
    cfg = MemRLConfig(embedding_dimension=2, **config)
    scope = {
        "experiment": "unit",
        "method": METHOD_VERSION,
        "model": "test",
        "domain": "db_bench",
        "method_version": METHOD_VERSION,
        "protocol": "O",
        "split": "DEV",
        "stream": "one",
        "feedback_regime": "R",
    }
    return MemRLBank(scope, MemRLSession.contract(cfg, POLICIES)), cfg


def session(bank, cfg, *, generate=None, embed=None, **kwargs):
    return MemRLSession(
        bank=bank,
        config=cfg,
        policies=POLICIES,
        generate=generate or (lambda c: "1. Use the observed inputs."),
        embed=embed or (lambda texts: [[1.0, 0.0] for _ in texts]),
        **kwargs,
    )


def form(bank, cfg, task, query, reward):
    s = session(bank, cfg)
    s.start(task, query)
    messages = [
        {"role": "system", "content": s.actor_system("common budget")},
        {"role": "user", "content": query},
    ]
    s.prepare_actor_input(messages)
    s.confirm_actor_input(
        {
            "status": "SETTLED",
            "role": "actor",
            "session": task,
            "request_id": task + "-actor",
            "payload_sha256": "a" * 64,
            "messages_sha256": messages_digest(messages),
        }
    )
    s.seal_result(task + ".json", reward)
    s.finish("user: task\nassistant: actual command\nuser: actual receipt", commit=True)
    return s


def test_actual_receipts_q_update_append_and_query_grouping_survive_json_restore():
    bank, cfg = make_bank(epsilon=0)
    first = form(bank, cfg, "one", "query one", True)
    assert first.selected == []
    second = form(bank, cfg, "two", "query two", False)
    assert second.selected == ["memrl:1"]
    assert bank.memories["memrl:1"]["q"] == pytest.approx(0.35)
    assert bank.memories["memrl:1"]["visits"] == 1
    assert bank.memories["memrl:2"]["q"] == 0.5
    assert bank.memories["memrl:2"]["related_ids"] == ["memrl:1"]
    assert len(bank.queries) == 1  # identical embeddings exceed .99 query matching threshold
    third = session(bank, cfg)
    third.start("three", "query three")
    assert third.retrieval["selected"] == ["memrl:2", "memrl:1"]  # Q participates in ranking
    assert "Failed approach:" not in third.memory_context()
    assert "Failed approach:" in bank.memories["memrl:2"]["content"]
    checkpoint = json.loads(json.dumps(bank.checkpoint()))
    restored = MemRLBank.restore(checkpoint, scope=bank.scope, contract=bank.contract)
    assert restored.checkpoint() == checkpoint
    assert restored.task_records[1]["actual_receipts"][0]["selected"] == ["memrl:1"]
    corrupt = copy.deepcopy(checkpoint)
    corrupt["memories"]["memrl:1"]["content"] += "tampered"
    with pytest.raises(ValueError, match="MEMORY_BINDING"):
        MemRLBank.restore(corrupt, scope=bank.scope, contract=bank.contract)


def test_missing_result_is_not_failure_and_frozen_evaluation_keeps_every_bank_field():
    bank, cfg = make_bank(epsilon=1)
    form(bank, cfg, "seed", "seed query", True)
    before = bank.checkpoint()
    s = session(bank, cfg, generate=lambda c: pytest.fail("missing result must not form"))
    s.start("missing", "new query")
    s.seal_result("terminal-missing.json")
    assert s.finish("visible trajectory", commit=True)["status"] == "MISSING_NATIVE_RESULT"
    assert bank.memories == before["memories"] and bank.queries == before["queries"]
    assert bank.task_records[-1]["native_result"] is None
    frozen = bank.fork({**bank.scope, "protocol": "F", "split": "TEST", "stream": "fixed"})
    initial = frozen.checkpoint()
    rng = restore_rng(frozen.rng_state)
    rng_before = rng.getstate()
    for name in ("test one", "test two"):
        evaluation = session(
            frozen,
            cfg,
            evaluation_rng=rng,
            generate=lambda c: pytest.fail("F must not form or update"),
        )
        evaluation.start(name, "same retrieved query")
        with pytest.raises(ValueError, match="FEEDBACK_NOT_ALLOWED"):
            evaluation.seal_result("terminal.json", True)
        evaluation.seal_result("terminal.json")
        assert evaluation.finish("trajectory", commit=False)["status"] == "FROZEN"
        assert frozen.checkpoint() == initial
    assert rng.getstate() != rng_before  # volatile stream sampling advances, seed bank does not
    with pytest.raises(ValueError, match="CROSS_MEMRL"):
        bank.fork({**bank.scope, "feedback_regime": "H"})


def test_q_stats_precede_threshold_and_empty_results_do_not_draw_randomness():
    bank, cfg = make_bank(epsilon=0, q_floor=-1, q_min=0)
    form(bank, cfg, "one", "query", True)
    form(bank, cfg, "two", "query", True)
    bank.memories["memrl:1"]["q"] = -0.5
    bank.memories["memrl:2"]["q"] = 0.5
    rng = random.Random(213)  # noqa: S311
    out = retrieve(bank, [1, 0], cfg, rng)
    assert out["selected"] == ["memrl:2"]
    assert out["candidates"][0]["q_z"] == 1.0
    state = rng.getstate()
    empty = retrieve(bank, [-1, 0], cfg, rng)
    assert empty["selected"] == [] and empty["queries"] == []
    assert rng.getstate() == state


def test_settled_formation_error_keeps_q_and_position_unknown_failure_does_not_commit():
    bank, cfg = make_bank(epsilon=0)
    form(bank, cfg, "one", "query", True)

    def fail_settled(call):
        raise MemoryOutputError("NO_VISIBLE_MAINTENANCE_TEXT")

    s = session(bank, cfg, generate=fail_settled)
    s.start("two", "query")
    s.seal_result("terminal-two.json", False)
    result = s.finish("trajectory", commit=True)
    assert result["status"] == "NO_VISIBLE_MAINTENANCE_TEXT"
    assert bank.memories["memrl:1"]["q"] == pytest.approx(0.35)
    assert bank.completed_tasks == ["one", "two"]
    before = bank.checkpoint()

    def fail_unknown(call):
        raise RuntimeError("unknown transport usage")

    s = session(bank, cfg, generate=fail_unknown)
    s.start("three", "query")
    s.seal_result("terminal-three.json", True)
    with pytest.raises(RuntimeError, match="unknown"):
        s.finish("trajectory", commit=True)
    assert bank.checkpoint() == before


def test_unsettled_or_wrong_actual_input_cannot_be_a_use_receipt():
    bank, cfg = make_bank()
    form(bank, cfg, "seed", "query", True)
    s = session(bank, cfg)
    s.start("next", "query")
    with pytest.raises(ValueError, match="NOT_IN_ACTUAL_REQUEST"):
        s.prepare_actor_input([{"role": "user", "content": "missing memory"}])
    s.prepare_actor_input([{"role": "system", "content": s.actor_system("")}])
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        s.confirm_actor_input({"status": "RESERVED"})
    assert not s.receipts
    text = memory_context([bank.memories["memrl:1"]])
    assert "SCRIPT:" in text and "TRAJECTORY:" in text
