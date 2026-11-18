"""View binding context is public, action-specific, and explicitly checkpoint-versioned."""
import copy
import json
from dataclasses import replace

import pytest

from milai_lab.methods.control_observation import (
    BOUND_VIEW_UNITS_V3,
    VISIBLE_SOURCE_HANDLES_V2,
    control_texts,
    joint_control_texts,
    proposed_view_unit_projection,
)
from milai_lab.methods.memory_object_policy import object_control_texts, object_semantic_texts
from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel


def online():
    view = {"id": "view-seven", "slot": "current", "revision": 7, "visibility": "visible",
        "query_time": "2032-04-30", "interpretation_semantics": "Not verified truth",
        "interpretation": {"scope": "Entry and fee", "unresolved": ["No entry execution known."],
            "nodes": {"n0": {"text": "Training completion is unknown.", "kind": "uncertain",
                             "evidence": ["e0"]},
                      "n1": {"text": "Permit expires 2032-05-03.", "kind": "reported",
                             "temporal": "No later validity", "evidence": ["e0"]},
                      "n2": {"text": "Entry requires training and permit.", "kind": "inferred",
                             "evidence": ["e0"]},
                      "n3": {"text": "Fee preview42; payment unknown.", "kind": "reported",
                             "evidence": ["e1"]}},
            "rules": {"g0": {"target": "n2", "all": ["n0"], "any": [["n1"]],
                             "evidence": ["e0"]}}},
        "source_bindings": {"e0": {"source_ref": "source-a", "source_revision": 1},
                            "e1": {"source_ref": "source-b", "source_revision": 2}},
        "source_metadata": {"e0": {"role": "user", "captured_at": "2032-05-02"},
                            "e1": {"role": "tool", "captured_at": "2032-05-02"}}}
    return {"observation": {"task": {"request": "What are the entry conditions?",
                                     "query_time": "2032-05-02"},
        "budget": {"remaining_control_steps": 3}, "views": [view],
        "visible_evidence": [], "pending_candidates": []}, "actions": [
            {"id": "entry", "kind": "USE_VIEW", "target": "view-seven",
             "parameters": {"slot": "current", "view_revision": 7, "view_nodes": ["n2"]}},
            {"id": "fee", "kind": "USE_VIEW", "target": "view-seven",
             "parameters": {"slot": "current", "view_revision": 7, "view_nodes": ["n3"]}}],
        "offline_supervision": {"answer": "DO_NOT_EMBED_GOLD"},
        "provenance": {"root_id": "DO_NOT_EMBED_ROOT"}}


def test_action_context_contains_exact_selected_closure_metadata_and_full_binding():
    row = online()
    original = copy.deepcopy(row)
    legacy = control_texts(row, delivery_context=True)
    state, texts = control_texts(row, delivery_context=True, view_unit_context=True)
    assert state == legacy[0]
    assert all("proposed_view_units" not in json.loads(text) for text in legacy[1])
    entry, fee = [json.loads(text) for text in texts]
    selected = entry["proposed_view_units"]
    assert [r["node_id"] for r in selected["interpretation"]["nodes"]] == ["n0", "n1", "n2"]
    assert selected["node_map_encoding"] == "ordered_node_rows_v1"
    assert selected["interpretation"]["rules"] == row["observation"]["views"][0][
        "interpretation"]["rules"]
    assert selected["source_metadata"]["by_alias"]["e0"]["role"] == "user"
    assert selected["parent_query_time"] == "2032-04-30"
    assert selected["requested_query_time"] == "2032-05-02"
    assert selected["unit_projection"]["semantic_completeness"] == "not_certified"
    assert [r["node_id"] for r in fee["proposed_view_units"]["interpretation"]["nodes"]] == ["n3"]
    assert entry["parameters"] == row["actions"][0]["parameters"]
    assert "DO_NOT_EMBED" not in str(texts)
    assert row == original


@pytest.mark.parametrize("mutation,status", [
    ("missing", "unresolved_parent"), ("invisible", "parent_unavailable"),
    ("tombstone", "parent_unavailable"), ("revision", "parent_revision_mismatch"),
])
def test_missing_stale_or_unavailable_parent_does_not_supply_action_body(mutation, status):
    row = online()
    view = row["observation"]["views"][0]
    if mutation == "missing":
        row["observation"]["views"] = []
    elif mutation == "invisible":
        view["visibility"] = "support_unavailable"
    elif mutation == "tombstone":
        view["body_delivered"] = False
    else:
        row["actions"][0]["parameters"]["view_revision"] = 6
    result = proposed_view_unit_projection(row["observation"], row["actions"][0])
    assert result["status"] == status
    assert "interpretation" not in result and "Training" not in str(result)


def test_semantic_lane_and_menu_permutation_follow_node_contents_not_action_ids():
    row = online()
    objects, actions = object_control_texts(row, view_unit_context=True)
    _, semantic = object_semantic_texts(objects, actions)
    assert "Training completion is unknown" in semantic[0] and "Fee preview42" not in semantic[0]
    assert semantic[1] == "Fee preview42; payment unknown."
    other = copy.deepcopy(row)
    other["actions"] = list(reversed(other["actions"]))
    for index, action in enumerate(other["actions"]):
        action["id"] = f"arbitrary-{index}"
    assert object_control_texts(other, view_unit_context=True)[1] == actions[::-1]
    legacy_actions = object_control_texts(row)[1]
    assert object_semantic_texts(objects, legacy_actions)[1] == ["", ""]
    joint, _ = joint_control_texts(row, view_unit_context=True)
    assert "proposed_view_units" in joint
    assert "proposed_view_units" not in joint_control_texts(row)[0]


def test_consistent_node_alias_renaming_preserves_semantics_and_conflicts_are_rejected():
    row = online()
    before = object_control_texts(row, view_unit_context=True)
    changed = json.dumps(row)
    for old, new in [("n0", "training-node"), ("n1", "permit-node"),
                     ("n2", "entry-node"), ("n3", "fee-node")]:
        changed = changed.replace('"' + old + '"', '"' + new + '"')
    other = object_control_texts(json.loads(changed), view_unit_context=True)
    assert object_semantic_texts(*before)[1] == object_semantic_texts(*other)[1]
    row["observation"]["views"].append(copy.deepcopy(row["observation"]["views"][0]))
    with pytest.raises(ValueError, match="Conflicting public View"):
        proposed_view_unit_projection(row["observation"], row["actions"][0])


def test_v3_small_local_encoder_features_save_load_and_old_input_remain_distinct(tmp_path):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    torch.set_num_threads(1)
    torch.manual_seed(2)
    backbone = tmp_path / "tiny"
    backbone.mkdir()
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "training", "entry", "fee"]
    (backbone / "vocab.txt").write_text("\n".join(vocab) + "\n")
    tokenizer = transformers.BertTokenizerFast(vocab_file=str(backbone / "vocab.txt"))
    tokenizer.save_pretrained(backbone)
    encoder = transformers.BertModel(transformers.BertConfig(vocab_size=len(vocab),
        hidden_size=16, intermediate_size=32, num_hidden_layers=1, num_attention_heads=2,
        max_position_embeddings=128))
    encoder.save_pretrained(backbone)
    config = SmallControlConfig("frozen_mlp", str(backbone), projection_version=BOUND_VIEW_UNITS_V3,
        chunk_tokens=64, readout="objects", object_architecture="object_mlp", object_width=16,
        object_heads=2, object_blocks=1, object_ffn_width=32, object_dropout=0,
        maximum_memory_objects=4)
    model = SmallControlModel(config)
    row = online()
    assert torch.equal(model.features([row])[1], model.features([
        {"observation": row["observation"], "actions": row["actions"]}])[1])
    scored = model.score(row)
    model.save(tmp_path / "saved")
    loaded = SmallControlModel.load(tmp_path / "saved")
    assert loaded.config.projection_version == BOUND_VIEW_UNITS_V3
    assert loaded.score(row).scores == scored.scores
    old = SmallControlModel(replace(config, projection_version=VISIBLE_SOURCE_HANDLES_V2))
    assert old.config.projection_version != loaded.config.projection_version
