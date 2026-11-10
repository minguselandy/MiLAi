"""Token reuse must preserve full capacity accounting, option markers and shuffled targets."""

import copy
import random

import pytest

from train_laya_matched import audit
from training_token_reuse import prepare_training_rows


@pytest.mark.parametrize("max_len,head_len,words,options", [(512, 160, 8, 3), (32, 24, 100, 7)])
def test_sdk_sequence_and_permuted_targets_stay_exact(tmp_path, max_len, head_len, words, options):
    transformers = pytest.importorskip("transformers")
    sdk = pytest.importorskip("laya.train")
    vocab = tmp_path / "vocab.txt"
    vocab.write_text(
        "[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nread\nfinish\nevidence\n"
        + "\n".join(map(str, range(options)))
        + "\n"
    )
    tokenizer = transformers.BertTokenizer(vocab_file=str(vocab))
    rows = [
        {
            "state": {"text": "evidence " * words + " [MASK] evidence"},
            "questions": {
                "next": {
                    "type": "choice",
                    "instructions": "read [MASK] evidence",
                    "criteria": {str(i): "read " + str(i) for i in range(options)},
                }
            },
            "gold": {"next": {"probabilities": {"0": 0.25, str(options - 1): 0.75}}},
            "metadata": {"event_id": str(row)},
        }
        for row in range(2)
    ]
    original = copy.deepcopy(rows)
    expected_lengths = audit(rows, tokenizer, max_len, head_len)
    expected_items, expected_skipped = sdk.items_from_rows(tokenizer, rows, max_len, head_len)
    expected = [sdk.encode_item(tokenizer, item, max_len, head_len) for item in expected_items]
    lengths, items, skipped, encoded, cached = prepare_training_rows(
        tokenizer, rows, max_len, head_len
    )
    assert lengths == expected_lengths and items == expected_items
    assert skipped == expected_skipped and encoded == expected
    assert cached.counters["state_tokenizations"] == len(rows)
    assert cached.counters["state_cache_hits"] == len(rows)
    assert not cached.state_tokens and cached.state_text is None
    calls = cached.counters["question_tokenizations"]
    for seed in range(3):
        for item in items:
            order = sdk.draw_option_order(item, random.Random(seed), ("choice",))  # noqa: S311
            assert sdk.encode_item(cached, item, max_len, head_len, option_order=order) == (
                sdk.encode_item(tokenizer, item, max_len, head_len, option_order=order)
            )
    assert cached.counters["question_tokenizations"] == calls
    assert rows == original
