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
