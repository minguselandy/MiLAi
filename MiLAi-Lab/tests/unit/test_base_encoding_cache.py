"""Actual encoder reuse retains bindings and rebuilds the current workspace."""
import copy
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel


def row():
    return {"observation": {"task": {"request": "alpha task", "query_time": "2032-05-02"},
        "budget": {"remaining_control_steps": 4}, "views": [], "visible_evidence": [],
        "pending_candidates": [{"index": 0, "id": "source-a", "kind": "original_source",
            "content": "alpha " * 80, "source_revision": 1, "visibility": "visible"}]},
        "actions": [{"id": "r", "kind": "READ", "target": "candidate 0",
                     "parameters": {"index": 0}},
                    {"id": "h", "kind": "HANDOFF", "target": None, "parameters": {}}]}


@pytest.fixture
def models(tmp_path):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    torch.set_num_threads(1)
    torch.manual_seed(42)
    backbone = tmp_path / "tiny"
    backbone.mkdir()
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "alpha", "beta",
             "task", "query", "passage", ":", "content", "read", "handoff"]
    (backbone / "vocab.txt").write_text("\n".join(vocab) + "\n")
    transformers.BertTokenizerFast(vocab_file=str(backbone / "vocab.txt")).save_pretrained(
        backbone)
    transformers.BertModel(transformers.BertConfig(vocab_size=len(vocab), hidden_size=16,
        intermediate_size=32, num_hidden_layers=1, num_attention_heads=2,
        max_position_embeddings=64)).save_pretrained(backbone)

    def build(architecture="latent_pointer", layout="literal_v1"):
        model = SmallControlModel(SmallControlConfig("frozen_mlp", str(backbone),
            readout="objects", object_architecture=architecture, object_width=16,
            object_heads=2, object_slots=2, object_blocks=1, object_ffn_width=32,
            object_dropout=0, maximum_memory_objects=4, chunk_tokens=32,
            object_feature_layout=layout))
        folder = tmp_path / (architecture + layout)
        model.save(folder)
        return model, SmallControlModel.load(folder), folder
    return build


@pytest.mark.parametrize("architecture", ["object_mlp", "latent_pointer"])
@pytest.mark.parametrize("layout", ["literal_v1", "dual_raw_v1", "dual_semantic_v1"])
def test_repeat_reuses_base_vectors_but_runs_full_head_and_preserves_scores(models, architecture,
                                                                          layout):
    torch = pytest.importorskip("torch")
    cached, baseline, _ = models(architecture, layout)
    cached.configure_base_encoding_cache(200_000)
    calls = []
    hook = cached.head.register_forward_hook(lambda *_: calls.append(1))
    original = copy.deepcopy(row())
    expected = baseline.score(original)
    first = cached.score(original)
    before = dict(cached.counters)
    second = cached.score(original)
    assert first.action_ids == second.action_ids == expected.action_ids
    assert torch.allclose(torch.tensor(first.scores), torch.tensor(expected.scores), atol=1e-6)
    assert second.scores == first.scores
    assert cached.counters == before
    assert len(calls) == 2 and cached.base_encoding_cache_report()["hits"] > 0
    assert original == row()
    hook.remove()


def test_query_budget_revision_changes_and_disappearance_never_reuse_stale_workspace(models):
    torch = pytest.importorskip("torch")
    cached, baseline, _ = models()
    cached.configure_base_encoding_cache(200_000)
    original = row()
    cached.score(original)
    oldkeys = set(cached._base_encoding_cache.entries)
    changed = copy.deepcopy(original)
    changed["observation"]["task"]["request"] = "beta task"
    changed["observation"]["budget"]["remaining_control_steps"] = 2
    changed["observation"]["pending_candidates"][0].update(
        content="beta " * 80, source_revision=2)
    expected = baseline.score(changed)
    before = cached.counters["forwards"]
    actual = cached.score(changed)
    assert cached.counters["forwards"] > before
    assert torch.allclose(torch.tensor(actual.scores), torch.tensor(expected.scores), atol=1e-6)
    assert cached.base_encoding_cache_report()["stale_input_removals"] > 0
    current = set(cached._base_encoding_cache.entries)
    assert not {key for key in oldkeys if '"source_revision":1' in key[2]} & current
    changed["observation"]["pending_candidates"] = []
    changed["actions"] = [changed["actions"][1]]
    actual = cached.score(changed)
    assert torch.allclose(torch.tensor(actual.scores),
                          torch.tensor(baseline.score(changed).scores), atol=1e-6)
    assert all('"source_revision":2' not in key[2] for key in cached._base_encoding_cache.entries)


def test_literal_text_role_and_conditional_prefix_are_all_identity_fields(models):
    torch = pytest.importorskip("torch")
    cached, baseline, _ = models()
    cached.train(False)
    baseline.train(False)
    cached.configure_base_encoding_cache(200_000)
    for role, prefix in [("query", "alpha"), ("passage", "alpha"), ("passage", "beta")]:
        before = cached.counters["forwards"]
        actual = cached.encode(["alpha beta"], prefixes=[prefix], text_role=role)
        expected = baseline.encode(["alpha beta"], prefixes=[prefix], text_role=role)
        assert cached.counters["forwards"] > before
        assert torch.allclose(actual, expected, atol=1e-6)
    with pytest.raises(ValueError, match="one actual prefix"):
        cached.encode(["alpha"], prefixes=[])
    assert cached.base_encoding_cache_report()["entries"] == 0


def test_eviction_and_oversized_inputs_encode_whole_body_without_dropping_tokens(models):
    torch = pytest.importorskip("torch")
    cached, baseline, _ = models()
    cached.configure_base_encoding_cache(100)
    actual = cached.score(row())
    expected = baseline.score(row())
    assert torch.allclose(torch.tensor(actual.scores), torch.tensor(expected.scores), atol=1e-6)
    report = cached.base_encoding_cache_report()
    assert report["accounted_bytes"] <= 100 and report["peak_accounted_bytes"] <= 100
    assert report["oversized_skips"] > 0
    assert cached.counters["input_tokens"] == baseline.counters["input_tokens"]
    cached.train(False)
    cached.configure_base_encoding_cache(150)
    cached.encode(["alpha", "beta", "task"])
    assert cached.base_encoding_cache_report()["evictions"] > 0
    assert cached.base_encoding_cache_report()["accounted_bytes"] <= 150


def test_frozen_encoder_native_mutation_versions_and_training_invalidate_cache(models):
    torch = pytest.importorskip("torch")
    cached, baseline, _ = models()
    cached.configure_base_encoding_cache(200_000)
    cached.score(row())
    before = cached.counters["forwards"]
    with torch.no_grad():
        next(cached.encoder.parameters()).add_(.01)
    baseline.encoder.load_state_dict(cached.encoder.state_dict())
    actual = cached.score(row())
    assert cached.counters["forwards"] > before
    assert torch.allclose(torch.tensor(actual.scores),
                          torch.tensor(baseline.score(row()).scores), atol=1e-6)
    cached.train(True)
    assert cached.base_encoding_cache_report()["entries"] == 0
    next(cached.encoder.parameters()).requires_grad_(True)
    with pytest.raises(ValueError, match="frozen eval encoder"):
        cached.features([row()])
    assert cached.base_encoding_cache_report()["entries"] == 0


def test_runtime_optin_not_saved_or_loaded_and_unsupported_adaptation_rejected(models):
    cached, _, folder = models()
    assert cached.base_encoding_cache_report() is None
    cached.configure_base_encoding_cache(200_000)
    cached.score(row())
    saved = folder / "again"
    cached.save(saved)
    assert "cache" not in str(json.loads((saved / "config.json").read_text())).lower()
    loaded = SmallControlModel.load(saved)
    assert loaded.base_encoding_cache_report() is None
    cached.configure_base_encoding_cache(0)
    assert cached.base_encoding_cache_report() is None
    for value in (-1, True):
        with pytest.raises(ValueError, match="nonnegative integer"):
            cached.configure_base_encoding_cache(value)
    cached.config = replace(cached.config, adaptation="full")
    with pytest.raises(ValueError, match="frozen independent encoder"):
        cached.configure_base_encoding_cache(1)


@pytest.mark.parametrize("architecture", ["object_mlp", "latent_pointer"])
def test_real_unselected_source_revoke_removes_cached_parent_vectors(models, tmp_path,
                                                                  architecture):
    from langgraph.store.sqlite import SqliteStore

    from milai_lab.memory.service import MemoryService
    from milai_lab.methods.control_observation import BOUND_VIEW_UNITS_V3
    from milai_lab.methods.evidence_control import EvidenceOperations
    from milai_lab.methods.memory_control import MemoryControlState
    from milai_lab.methods.query_structure import build_query_structure

    torch = pytest.importorskip("torch")
    cached, baseline, _ = models(architecture)
    for model in (cached, baseline):
        model.config = replace(model.config, maximum_memory_objects=16,
                               projection_version=BOUND_VIEW_UNITS_V3)
    cached.configure_base_encoding_cache(200_000)
    with SqliteStore.from_conn_string(str(tmp_path / "lifecycle.sqlite")) as store:
        service = MemoryService(store, ("base-cache", "alice"), "alice", tmp_path / "lock",
            functional_contract="functional_v1",
            clock=lambda: datetime(2032, 5, 2, tzinfo=UTC))
        alpha = service.capture_user("s", "alpha", "alpha is recorded.")["source_ref"]
        beta = service.capture_user("s", "beta", "beta is recorded.")["source_ref"]

        def build(messages, schema):
            aliases = [s["id"] for s in json.loads(messages[1]["content"])["sources"]]
            return {"scope": "alpha and beta records", "nodes": [
                {"id": "n0", "text": "alpha is recorded.", "kind": "reported",
                 "evidence": [aliases[0]]},
                {"id": "n1", "text": "beta is recorded.", "kind": "reported",
                 "evidence": [aliases[1]]}],
                "rules": [], "remove": [], "remove_rules": [], "unresolved": []}

        build_query_structure(service, "alpha task", "2032-05-02", [alpha, beta],
                              policy="incremental", call=build)
        state = MemoryControlState(task={"request": "alpha task", "query_time": "2032-05-02"})
        ops = EvidenceOperations(service, state, load_pool=lambda: [],
            refresh_call=lambda *_: pytest.fail("No model refresh admitted in this test"),
            fits=lambda _: True, view_updates=False, delivery_selection=True,
            source_directory_only=True, view_unit_selections={"current": [["n0"]]})
        action = next(a for a in ops.actions(state) if a.kind == "USE_VIEW"
                      and a.parameters.get("view_nodes") == ["n0"])
        assert ops.execute(action, state)["ok"]
        actions = ops.actions(state)
        before = {"observation": state.project(), "actions": [a.__dict__ for a in actions]}
        cached.score(before)
        assert any("beta is recorded" in key[2] for key in cached._base_encoding_cache.entries)
        fragments = [f["fragment_handle"] for f in service.source_fragments(beta)]
        assert service.forget("s", "withdraw-unselected-parent", fragment_handles=fragments)["ok"]
        actions = ops.actions(state)
        assert not any(a.kind == "USE_VIEW" for a in actions)
        assert ops.reader_evidence()[0]["visibility"] == "support_unavailable"
        after = {"observation": state.project(), "actions": [a.__dict__ for a in actions]}
        actual = cached.score(after)
        expected = baseline.score(after)
        assert torch.allclose(torch.tensor(actual.scores), torch.tensor(expected.scores), atol=1e-6)
        assert not any("beta is recorded" in key[2] for key in cached._base_encoding_cache.entries)
