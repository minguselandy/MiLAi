"""Supplementary semantic features retain complete metadata and matched controls."""
import copy
import json

import pytest

from milai_lab.methods.memory_object_policy import object_control_texts, object_semantic_texts
from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel


def online():
    return {"observation": {"task": {"request": "Who may approve?", "as_of": "2030-03-01"},
        "budget": {"remaining_control_steps": 4},
        "pending_candidates": [{"item_index": 7, "excerpt": "Nurses only, unless revoked."}],
        "visible_evidence": [{"label": "e7", "kind": "original_source", "revision": 2,
            "evidence": [{"content": "Li cannot approve on Friday.", "role": "user",
                          "reported_at": "2030-02-01", "range": [0, 28]}]}]},
        "actions": [{"id": "read", "kind": "READ", "target": "candidate",
                     "parameters": {"index": 7}},
                    {"id": "stop", "kind": "HANDOFF", "target": "Reader",
                     "parameters": {"delivery_indices": [7]}}],
        "offline_supervision": {"answer": "DO_NOT_EMBED_GOLD_X"}}


def test_text_lane_preserves_negation_and_uses_only_already_supplied_content():
    row = online()
    original = copy.deepcopy(row)
    objects, actions = object_control_texts(row)
    memories, choices = object_semantic_texts(objects, actions)
    assert memories == ["Who may approve?", "", "Nurses only, unless revoked.",
                        "Li cannot approve on Friday."]
    assert choices == ["Nurses only, unless revoked.", "Li cannot approve on Friday."]
    assert row == original
    assert "DO_NOT_EMBED_GOLD_X" not in json.dumps([objects, actions, memories, choices])
    # The original lane still carries source roles, time, revision and exact binding.
    assert '"reported_at":"2030-02-01"' in objects[3]
    assert '"revision":2' in objects[3] and '"role":"user"' in objects[3]
    assert '"delivery_indices":[7]' in actions[1]
    unavailable = copy.deepcopy(objects)
    body = json.loads(unavailable[3])
    body["object"]["body_delivered"] = False
    unavailable[3] = json.dumps(body)
    assert object_semantic_texts(unavailable, actions)[0][3] == ""


def projected_features(layout):
    torch = pytest.importorskip("torch")
    model = SmallControlModel.__new__(SmallControlModel)
    model.config = SmallControlConfig("frozen_mlp", "unused", readout="objects",
        maximum_memory_objects=3, object_feature_layout=layout)
    model.device = torch.device("cpu")
    calls = []

    def encode(texts, **kwargs):
        calls.append(list(texts))
        return torch.full((len(texts), 4), float(len(calls)))

    model.encode = encode
    return model, calls


def test_same_raw_lane_capacity_availability_and_complete_menu_in_both_controls():
    torch = pytest.importorskip("torch")
    legacy, oldcalls = projected_features("literal_v1")
    duplicate, dupcalls = projected_features("dual_raw_v1")
    semantic, semcalls = projected_features("dual_semantic_v1")
    old, oldactions, _, oldlengths = legacy.features([online()])
    raw, rawa, owners, lengths = duplicate.features([online()])
    sem, sema, _, semlengths = semantic.features([online()])
    assert lengths == semlengths == oldlengths == [2]
    assert owners.tolist() == [0, 0] and old.shape == (1, 5, 4)
    assert raw.shape == sem.shape == (1, 5, 8)
    assert torch.equal(old, raw[..., :4]) and torch.equal(old, sem[..., :4])
    assert torch.equal(oldactions, rawa[:, :4]) and torch.equal(oldactions, sema[:, :4])
    assert torch.equal(raw[..., 4:] != 0, sem[..., 4:] != 0)
    assert torch.equal(rawa[:, 4:] != 0, sema[:, 4:] != 0)
    assert raw[0, 1, 4:].eq(0).all() and sem[0, 1, 4:].eq(0).all()
    assert raw[0, -1].eq(0).all() and sem[0, -1].eq(0).all()
    assert oldcalls[0] == dupcalls[0] == semcalls[0]
    assert len(oldcalls) == len(dupcalls) == 1 and len(semcalls) == 2
    assert semcalls[1][0] == "Who may approve?"
    for model in [duplicate, semantic]:
        model.config.maximum_memory_objects = 1
        with pytest.raises(ValueError, match="MEMORY_OBJECT_CAPACITY"):
            model.features([online()])
