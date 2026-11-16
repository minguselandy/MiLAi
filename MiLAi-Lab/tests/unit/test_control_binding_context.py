"""Binding context must preserve observation permissions and exact delivery scope."""
import copy
import json

import pytest

from milai_lab.methods.control_observation import control_texts, proposed_delivery_projection
from milai_lab.methods.small_control_model import conditioned_chunks


def item(index, text):
    return {"label": f"e{index}", "kind": "original_source",
            "evidence": [{"content": text}]}


def test_bound_selection_uses_observed_body_and_exact_retrieved_scope():
    observation = {"visible_evidence": [item(4, "full currently selected body")],
        "observed_evidence": [item(2, "acquired but not selected")],
        "retrieved_scopes": [{"item_index": 4, "evidence": item(4, "actual narrow range")}]}
    action = {"parameters": {"delivery_indices": [2, 4, 99],
                              "retrieved_scope_indices": [4, 99]}}
    original = copy.deepcopy(observation)
    result = proposed_delivery_projection(observation, action)
    assert result["material_projection"] == [item(2, "acquired but not selected"),
                                               item(4, "actual narrow range")]
    assert result["unresolved_indices"] == [99]
    assert observation == original
    plain = proposed_delivery_projection(observation, {"parameters": {}})
    assert plain["material_projection"] == observation["visible_evidence"]
    repeated = {"visible_evidence": [{**item(0, "one actual body"),
                                      "also_selected_as": ["e1"]}]}
    result = proposed_delivery_projection(repeated, {
        "parameters": {"delivery_indices": [0, 1]}})
    assert len(result["material_projection"]) == 1 and not result["unresolved_indices"]


def test_readout_context_has_no_offline_or_local_action_id_feature():
    observation = {"task": {"request": "Find the current owner"},
        "visible_evidence": [], "observed_evidence": [item(2, "current owner Ada")],
        "pending_candidates": [], "new_events": []}
    actions = [{"id": "a", "kind": "HANDOFF", "target": "selected evidence",
                "parameters": {"delivery_indices": [2]}},
               {"id": "b", "kind": "HANDOFF", "target": "current evidence", "parameters": {}}]
    row = {"observation": observation, "actions": actions,
           "offline_supervision": {"answer": "SECRET"}, "provenance": {"SECRET": True}}
    original = copy.deepcopy(row)
    _, texts = control_texts(row, delivery_context=True)
    assert "SECRET" not in str(texts)
    assert json.loads(texts[0])["proposed_delivery"]["material_projection"] == observation[
        "observed_evidence"]
    row["actions"] = list(reversed(row["actions"]))
    for i, action in enumerate(row["actions"]):
        action["id"] = f"alias-{i}"
    assert control_texts(row, delivery_context=True)[1] == texts[::-1]
    assert original["observation"] == row["observation"]


def test_long_query_and_body_are_fully_kept_in_bounded_conditioned_chunks():
    body, context, limit = list(range(19)), list(range(100, 113)), 8
    chunks = conditioned_chunks(body, context, limit)
    assert all(len(chunk) <= limit for chunk in chunks)
    assert set(context) | set(body) == {token for chunk in chunks for token in chunk}
    # Every query fragment co-occurs with the whole body across its bounded chunks.
    for token in context:
        assert {x for chunk in chunks if token in chunk for x in chunk if x < 100} == set(body)
    assert conditioned_chunks(body, [], limit) == [body[:8], body[8:16], body[16:]]
    assert conditioned_chunks([], context, limit)
    with pytest.raises(ValueError, match="capacity"):
        conditioned_chunks(body, context, 3)


def test_query_prefix_alignment_is_per_binding_with_old_route_unchanged():
    torch = pytest.importorskip("torch")
    from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel

    row = {"observation": {"task": {"request": "actual task query"},
            "visible_evidence": [item(0, "delivered fact")], "pending_candidates": [],
            "new_events": []}, "actions": [
                {"id": "x", "kind": "HANDOFF", "target": "Reader", "parameters": {}}]}
    for representation in ["binding_v1", "query_pair_v2", "query_delivery_pair_v3"]:
        model = SmallControlModel.__new__(SmallControlModel)
        model.config = SmallControlConfig("frozen_mlp", "unused",
                                           action_representation=representation)
        model.device = torch.device("cpu")
        captured = {}
        def encode(texts, *, prefixes=None, _captured=captured):
            _captured.update(texts=texts, prefixes=prefixes)
            return torch.ones(len(texts), 4)
        model.encode = encode
        _, actions, owners, lengths = model.features([row])
        assert actions.shape == (1, 4) and owners.tolist() == [0] and lengths == [1]
        assert captured["prefixes"] == (None if representation == "binding_v1"
                                       else ["", "actual task query"])
        action = json.loads(captured["texts"][1])
        assert ("proposed_delivery" in action) == (representation == "query_delivery_pair_v3")


def test_parameter_free_block_normalization_keeps_permutation_and_zero_gradients_finite():
    torch = pytest.importorskip("torch")
    from milai_lab.methods.small_control_model import build_action_head

    torch.manual_seed(2)
    raw = build_action_head(4, 8)
    torch.manual_seed(2)
    normalized = build_action_head(4, 8, feature_normalization="block_layernorm_v2")
    assert raw.state_dict().keys() == normalized.state_dict().keys()
    assert all(torch.equal(value, normalized.state_dict()[key])
               for key, value in raw.state_dict().items())
    state, actions = torch.randn(1, 4), torch.randn(3, 4)
    owners = torch.zeros(3, dtype=torch.long)
    order = torch.tensor([2, 0, 1])
    assert torch.allclose(normalized(state, actions, owners)[order],
                          normalized(state, actions[order], owners))
    zeros = torch.zeros(3, 4, requires_grad=True)
    loss = normalized(torch.zeros(1, 4), zeros, owners).sum()
    loss.backward()
    assert torch.isfinite(loss) and torch.isfinite(zeros.grad).all()


def test_frozen_and_lora_encoder_start_with_same_head_despite_adapter_rng(monkeypatch):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    pytest.importorskip("peft")
    from types import SimpleNamespace

    from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel

    def tiny_backbone(*args, **kwargs):
        return transformers.BertModel(transformers.BertConfig(vocab_size=32, hidden_size=16,
            intermediate_size=32, num_hidden_layers=1, num_attention_heads=2))
    monkeypatch.setattr(transformers.AutoModel, "from_pretrained", tiny_backbone)
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained",
                        lambda *args, **kwargs: SimpleNamespace(pad_token_id=0))
    torch.manual_seed(11)
    frozen = SmallControlModel(SmallControlConfig("frozen_mlp", "unused"))
    torch.manual_seed(11)
    adapted = SmallControlModel(SmallControlConfig("encoder", "unused", adaptation="lora",
        lora_target_modules=("query", "value")))
    assert all(torch.equal(tensor, adapted.head.state_dict()[key])
               for key, tensor in frozen.head.state_dict().items())
    assert not any(p.requires_grad for p in adapted.encoder.get_input_embeddings().parameters())
    assert any("lora_B" in name and p.requires_grad
               for name, p in adapted.encoder.named_parameters())
