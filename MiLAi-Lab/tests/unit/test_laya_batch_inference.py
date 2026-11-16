"""Batching must preserve complete menu bindings, padding masks and cached inputs."""

from pathlib import Path

import pytest


@pytest.fixture
def decision(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    train = pytest.importorskip("laya.train")
    from laya.common import DecisionModel

    from milai_lab.providers.laya_local import NativeDecision

    vocab = tmp_path / "vocab.txt"
    vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nread\nfinish\nevidence\na\nb\nc\n")
    tokenizer = transformers.BertTokenizer(vocab_file=str(vocab))
    torch.manual_seed(17)
    encoder = transformers.BertModel(transformers.BertConfig(
        vocab_size=11, hidden_size=16, intermediate_size=24, num_hidden_layers=1,
        num_attention_heads=2, max_position_embeddings=512))
    model = DecisionModel(encoder, head_layers=0, n_act=1)
    monkeypatch.setattr(train, "load_checkpoint", lambda _: (model, tokenizer, {}))
    return NativeDecision(Path("unused"), 512, 128)


def payload(repetitions, names):
    return {"state": {"request": "evidence " * repetitions},
            "questions": {"next": {"type": "choice", "instructions": "read evidence",
                                    "criteria": dict(names)}}}


def test_variable_menus_lengths_and_permutations_restore_original_results(decision):
    rows = [payload(100, [("c", "finish"), ("a", "read"), ("b", "evidence")]),
            payload(1, [("a", "read"), ("c", "finish")]),
            payload(40, [("b", "evidence"), ("c", "finish"), ("a", "read")]),
            payload(3, [("c", "finish")]), payload(10, [("c", "finish"), ("a", "read")])]
    single = [decision.predict(row) for row in rows]
    for batch_size in (1, 2, 4, 8):
        batched = decision.predict_batch(rows, batch_size)
        for expected, actual in zip(single, batched, strict=True):
            assert expected["choice"] == actual["choice"]
            assert list(actual["logits"]) == list(expected["logits"])
            assert actual["logits"] == pytest.approx(expected["logits"], abs=2e-5)
            assert actual["probabilities"] == pytest.approx(expected["probabilities"], abs=2e-5)
            assert sum(actual["probabilities"].values()) == pytest.approx(1)
            assert actual["input_tokens"] == expected["input_tokens"]


def test_cached_tokens_survive_model_updates_without_cached_logits(decision):
    import torch

    rows = [payload(2, [("a", "read"), ("b", "finish")])]
    prepared = decision.prepare_batch(rows)
    count = decision.counters["state_tokenizations"]
    first = decision.predict_prepared(prepared)
    with torch.no_grad():
        for name, parameter in decision.model.named_parameters():
            if not name.startswith("encoder."):
                parameter.add_(0.25)
    second = decision.predict_prepared(prepared)
    assert decision.counters["state_tokenizations"] == count
    assert first[0]["logits"] != second[0]["logits"]
    assert second[0]["logits"] == pytest.approx(decision.predict(rows[0])["logits"], abs=2e-5)


def test_capacity_and_empty_batch_keep_single_input_contract(decision):
    assert decision.predict_batch([]) == []
    long = payload(600, [("a", "read"), ("b", "finish")])
    for invoke in (lambda: decision.predict(long), lambda: decision.predict_batch([long])):
        with pytest.raises(ValueError, match="complete-input capacity"):
            invoke()
