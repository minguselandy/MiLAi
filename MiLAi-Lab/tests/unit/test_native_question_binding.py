"""Exercise real SDK preparation with a stubbed forward, without loading a model."""
from pathlib import Path

import pytest

from milai_lab.providers.laya_local import NativeDecision


@pytest.mark.parametrize("question_id", ["next", "applicability"])
def test_single_question_identity_survives_native_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, question_id: str,
) -> None:
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    train = pytest.importorskip("laya.train")
    vocab = tmp_path / "vocab.txt"
    vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nalpha\nbeta\n")
    decision = NativeDecision.__new__(NativeDecision)
    decision.tokenizer = transformers.BertTokenizer(vocab_file=str(vocab))
    decision.device = torch.device("cpu")
    decision.model = None
    decision.max_len, decision.head_max_len = 512, 256
    decision.counters = dict(forwards=0, sequence_rows=0, input_tokens=0,
                             state_tokenizations=0, state_tokens=0)
    observed = []
    convert = train.to_internal

    def capture(identity, schema):
        observed.append(identity)
        return convert(identity, schema)

    monkeypatch.setattr(train, "to_internal", capture)
    monkeypatch.setattr(train, "_forward", lambda *args: torch.tensor([[0.0, 1.0]]))
    result = decision.predict({"state": {"text": "alpha"}, "questions": {question_id: {
        "type": "choice", "instructions": "Choose", "criteria": {"a": "alpha", "b": "beta"}}}})
    assert observed == [question_id]
    assert result["choice"] == "b"
    assert set(result["probabilities"]) == {"a", "b"}
    assert result["truncated"] is False
