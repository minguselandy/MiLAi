"""Semantic navigation sees legal excerpts and preserves complete read bindings."""
from dataclasses import asdict

import pytest

from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.small_memory_policy import EncoderCosineMemoryPolicy


def test_cosine_navigation_permissions_binding_order_roles_stop_and_model_failure():
    torch = pytest.importorskip("torch")

    class Encoder:
        def __init__(self):
            self.seen = []
            self.fail = False

        def encode(self, texts, *, text_role="query"):
            self.seen.append((texts, text_role))
            if self.fail:
                raise RuntimeError("Encoder unavailable")
            return torch.tensor([[1., 0.] if text in {"Question", "Relevant visible excerpt"}
                                 else [0., 1.] for text in texts])

    state = MemoryControlState(task={"request": "Question"},
        observed_materials=[{"item_index": 0, "kind": "original_source"}],
        pending_candidates=[{"item_index": 0, "kind": "original_source", "excerpt": "Acquired"},
            {"item_index": 1, "kind": "original_source", "excerpt": "Distractor excerpt"},
            {"item_index": 2, "kind": "original_source", "excerpt": "Relevant visible excerpt"}])
    actions = [MemoryAction("stop", "HANDOFF", "Reader"),
        MemoryAction("again", "READ", "candidate 0", {"index": 0}),
        MemoryAction("other", "READ", "candidate 1", {"index": 1}),
        MemoryAction("narrow", "READ", "candidate 2", {"index": 2}),
        MemoryAction("context", "READ", "candidate 2", {"index": 2, "expand_context": True})]
    encoder = Encoder()
    policy = EncoderCosineMemoryPolicy(encoder, reads=4)
    assert policy.choose(state, actions) == "context"
    assert encoder.seen == [(["Question"], "query"),
        (["Distractor excerpt", "Relevant visible excerpt"], "passage")]
    renamed = [MemoryAction(f"alias{i}", a.kind, a.target, a.parameters)
               for i, a in enumerate(reversed(actions))]
    choice = policy.choose(state, renamed)
    selected = next(a for a in renamed if a.id == choice)
    assert asdict(selected) | {"id": "context"} == asdict(actions[-1])
    calls = len(encoder.seen)
    state.budget["remaining_control_steps"] = 1
    assert policy.choose(state, actions) == "stop" and len(encoder.seen) == calls
    state.budget["remaining_control_steps"] = 4
    encoder.fail = True
    with pytest.raises(RuntimeError, match="Encoder unavailable"):
        policy.choose(state, actions)
