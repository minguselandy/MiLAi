"""Regression coverage for masking, token quotas and per-root paired gradients."""

import pytest

from milai_lab.methods.control_state_text import control_sequences


def outcomes():
    return dict(
        split_role="train",
        continuation_mode="full_episode",
        online={"actions": [{"id": "read"}, {"id": "handoff"}, {"id": "unknown"}]},
        comparisons=[["read", "handoff"], ["read", "unknown"]],
        outcomes=[
            dict(
                first_action_id="read",
                quality_observed=True,
                reader_quality=0.8,
                future_cost_observed=True,
                future_cost=100,
            ),
            dict(
                first_action_id="handoff",
                quality_observed=True,
                reader_quality=0.3,
                future_cost_observed=False,
                future_cost=None,
            ),
            dict(
                first_action_id="unknown",
                quality_observed=False,
                reader_quality=None,
                future_cost_observed=False,
                future_cost=None,
            ),
        ],
    )


def test_measured_pairs_and_microbatch_gradient():
    torch = pytest.importorskip("torch")
    from milai_lab.methods.pretrained_objective import root_loss

    row = outcomes()
    q = torch.full((3, 4), 0.5, requires_grad=True)
    c = torch.ones_like(q, requires_grad=True)
    direct, _ = root_loss(row, q, c, [1] * 4, 100, pair_weight=0.0)
    paired, n = root_loss(row, q, c, [1] * 4, 100, pair_weight=0.2)
    assert direct.item() == pytest.approx((0.3**2 + 0.2**2) / 4)
    assert n == 1 and (paired - direct).item() == pytest.approx(0.2 * 0.5 * 0.5**2)
    monolithic = torch.autograd.grad((paired + 2 * direct) / 3, q, retain_graph=True)[0]
    (paired / 3).backward(retain_graph=True)
    (2 * direct / 3).backward()
    torch.testing.assert_close(q.grad, monolithic)
    assert not q.grad[2].any()


class Tokens:
    @staticmethod
    def encode(text, *, max_length, **kwargs):
        return text.split()[:max_length]

    @staticmethod
    def build_inputs_with_special_tokens(a, b):
        return ["<s>", *a, "</s>", *b, "</s>"]

    @staticmethod
    def num_special_tokens_to_add(*, pair):
        return 3


def test_legal_roles_quotas_and_shared_levels():
    online = dict(
        observation=dict(
            task="question",
            budget={},
            last_result={},
            action_history=["search"],
            visible_evidence=[{"label": "delivered", "evidence": ["public"]}],
            observed_evidence=[{"label": "acquired", "evidence": ["controller_only"]}],
            pending_candidates=[
                {"item_index": 0, "excerpt": "unique_candidate", "unread_body": "hidden_sentinel"}
            ],
        ),
        actions=[
            dict(id="r2", kind="READ", parameters={"index": 0}),
            dict(id="r3", kind="READ", parameters={"index": 0, "expand_context": True}),
            dict(id="stop", kind="HANDOFF", parameters={}),
        ],
    )
    ids, owners, levels = control_sequences(Tokens(), online, 128)
    assert owners == [0, 0, 1] and levels == [1, 2, 0]
    assert len(ids) == 2 and max(map(len, ids)) <= 128
    text = " ".join(ids[0])
    assert "unique_candidate" in text and "hidden_sentinel" not in text
    assert "Acquired only" in text
    assert "Delivered" in text and "public" in text and "controller_only" in text


def test_group_first_schedule_preserves_small_sources_until_late_updates():
    import random

    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from milai_lab.runners.pretrained_control_train import TrainingRoots

    data = TrainingRoots.__new__(TrainingRoots)
    sizes = {"musique_full": (128, 8), "qasper": (8, 8), "personamem_v2": (4, 8)}
    data.groups = {
        source: {g: [f"{source}/{g}/{j}" for j in range(per_group)] for g in range(groups)}
        for source, (groups, per_group) in sizes.items()
    }
    weights = {"musique_full": 0.5, "qasper": 0.35, "personamem_v2": 0.15}
    order = list(data.epoch(random.Random(11), weights, allocation_window=64))  # noqa: S311
    assert len(order) == 1120
    assert len({key for key, _, _ in order}) == len(order)
    for i in range(4):
        quarter = order[i * len(order) // 4 : (i + 1) * len(order) // 4]
        assert {source for _, source, _ in quarter} == set(weights)
