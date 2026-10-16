"""Decision-letter rendering and explicit full-context capacity."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from logits_reader import encode_decision


class Tokenizer:
    def apply_chat_template(self, messages, **kwargs):
        self.messages = messages
        assert kwargs == {"tokenize": True, "add_generation_prompt": True}
        return list(range(12))

    def encode(self, letter, **kwargs):
        return [ord(letter)]


def test_letters_map_to_actual_actions_and_labels_never_enter_prompt():
    payload = {"state": {"question": "q", "read_evidence": [], "candidates": []},
               "questions": {"next": {"instructions": "choose", "criteria": {
                   "open_p9": "next source", "stop_exhausted": "insufficient"}}},
               "gold": {"next": {"probabilities": {"stop_exhausted": 1}}},
               "metadata": {"answer": "private reference"}}
    tokenizer = Tokenizer()
    encoded = encode_decision(payload, tokenizer, 20)
    assert encoded["keys"] == ["open_p9", "stop_exhausted"]
    assert encoded["letter_ids"] == [65, 66]
    assert json.loads(tokenizer.messages[1]["content"]) == {
        "state": payload["state"], "options": [
            {"letter": "A", "action": "open_p9", "meaning": "next source"},
            {"letter": "B", "action": "stop_exhausted", "meaning": "insufficient"}]}
    with pytest.raises(ValueError, match="capacity"):
        encode_decision(payload, tokenizer, 10)
