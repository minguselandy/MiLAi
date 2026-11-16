"""Cross-encoder sees the same visible state, without labels in any action row."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from ordinary_reader_reranker import encode_actions


class Tokenizer:
    cls_token_id = 1
    sep_token_id = 2

    def encode(self, text, **kwargs):
        return [ord(c) for c in text]


def test_action_expansion_reuses_state_and_does_not_consume_labels(monkeypatch):
    monkeypatch.setitem(sys.modules, "laya.common", SimpleNamespace(serialize_state=json.dumps))
    payload = {"state": {"question": "q", "read_evidence": [], "candidates": [{"id": "p0"}]},
               "questions": {"next": {"instructions": "choose", "criteria": {
                   "open_p0": "read", "stop_sufficient": "enough", "stop_exhausted": "missing"}}}}
    first = encode_actions(payload, Tokenizer())
    payload.update(gold={"next": {"probabilities": {"stop_sufficient": 1}}},
                   metadata={"answer": "private evaluator"})
    assert encode_actions(payload, Tokenizer()) == first
    assert first["state_tokenizations"] == 1
    assert first["action_tokenizations"] == 3
    tail = [*Tokenizer().encode(json.dumps(payload["state"])), 2]
    assert all(ids[-len(tail):] == tail for ids in first["sequences"])
    assert first["input_tokens"] == sum(map(len, first["sequences"]))
    with pytest.raises(ValueError, match="capacity"):
        encode_actions(payload, Tokenizer(), max_len=10)
