"""Answer boundary, causal shift, padding and actual packet-only scoring."""
import sys
from pathlib import Path

import pytest

from milai_lab.providers.reader_teacher_scoring import (
    AnswerSequence,
    answer_batch,
    encode_answer,
    target_logprobs,
    teacher_messages,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_reader_utility import native_references, qasper_references


def test_selective_logits_equal_full_causal_cross_entropy_with_left_padding():
    torch = pytest.importorskip("torch")
    from transformers import Qwen3Config, Qwen3ForCausalLM

    torch.manual_seed(7)
    model = Qwen3ForCausalLM(Qwen3Config(
        vocab_size=31, hidden_size=16, intermediate_size=32, num_hidden_layers=1,
        num_attention_heads=2, num_key_value_heads=1, head_dim=8)).eval()
    sequences = [AnswerSequence([1, 2, 3, 4, 5, 6], 3), AnswerSequence([7, 8, 9], 2)]
    batch = answer_batch(sequences, 0, "cpu")
    targets, mask = batch.pop("targets"), batch.pop("target_mask")
    with torch.inference_mode():
        selected = model(**batch, use_cache=False).logits
        scores = target_logprobs(selected, targets, mask)
        for row, sequence in enumerate(sequences):
            ids = torch.tensor([sequence.input_ids])
            logits = model(ids, use_cache=False).logits[0, sequence.answer_start - 1:-1]
            expected = -torch.nn.functional.cross_entropy(
                logits.float(), ids[0, sequence.answer_start:], reduction="none")
            torch.testing.assert_close(torch.tensor(scores[row]), expected, atol=1e-6, rtol=1e-6)
    assert selected.shape == (2, 3, 31)  # Never projects the complete prompt vocabulary tensor.


def test_probability_uses_full_vocabulary_not_top_k_or_prompt_tokens():
    torch = pytest.importorskip("torch")
    logits = torch.tensor([[[10., -10., 1.], [2., 3., 4.]]])
    targets, mask = torch.tensor([[1, 2]]), torch.tensor([[True, False]])
    values = target_logprobs(logits, targets, mask)
    assert values[0][0] == pytest.approx((-10 - logits[0, 0].logsumexp(0)).item())
    assert len(values[0]) == 1


def test_packet_template_excludes_labels_but_retains_request_known_evidence_and_roles():
    wire = {"request": "current task", "known_evidence": [{"role": "user", "content": "A"}],
            "memory": {"evidence": [{"role": "tool", "content": "B"}]},
            "gold": "secret answer", "policy": "winning method"}
    messages = teacher_messages(wire)
    assert "secret answer" not in str(messages) and "winning method" not in str(messages)
    assert "current task" in str(messages) and '"role": "user"' in messages[1]["content"]


class CharacterTokenizer:
    """Test joint offsets, including a template with an explicit empty reasoning section."""
    def apply_chat_template(self, messages, **kwargs):
        assert kwargs["continue_final_message"] and messages[-1]["reasoning_content"] == ""
        return "assistant\n<think>\n\n</think>\n\n" + messages[-1]["content"]

    def __call__(self, text, **kwargs):
        assert not kwargs["truncation"] and not kwargs["add_special_tokens"]
        return {"input_ids": [ord(c) for c in text],
                "offset_mapping": [(i, i + 1) for i in range(len(text))]}


def test_only_reference_answer_is_masked_without_eos_or_empty_reasoning():
    result = encode_answer(CharacterTokenizer(), [], "Paris", 100)
    assert result.input_ids[result.answer_start:] == list(map(ord, "Paris"))
    assert result.answer_tokens == 5


def test_over_capacity_reference_is_not_truncated():
    with pytest.raises(ValueError, match="capacity_exceeded"):
        encode_answer(CharacterTokenizer(), [], "A long complete answer", 10)


def test_joint_token_crossing_boundary_is_rejected():
    class Crossing(CharacterTokenizer):
        def __call__(self, text, **kwargs):
            return {"input_ids": [0], "offset_mapping": [(0, len(text))]}
    with pytest.raises(ValueError, match="crosses_answer_boundary"):
        encode_answer(Crossing(), [], "Paris", 100)


def annotation(**kwargs):
    return {"answer": {"unanswerable": False, "yes_no": None, "free_form_answer": "",
                        "extractive_spans": [], **kwargs}}


def test_native_aliases_remain_separate_and_multi_part_references_complete():
    control = {"annotations": [annotation(extractive_spans=["A", "B"]),
                               annotation(free_form_answer="Alpha and Beta"),
                               annotation(free_form_answer="Alpha and Beta")]}
    assert qasper_references(control) == ["A, B", "Alpha and Beta"]


def test_no_is_not_missing_and_conflicting_or_unanswerable_targets_remain_unknown():
    assert qasper_references({"annotations": [annotation(yes_no=False)]}) == ["No"]
    for annotations in ([annotation(yes_no=False), annotation(yes_no=True)],
                        [annotation(unanswerable=True)], [annotation()]):
        assert qasper_references({"annotations": annotations}) == []


def test_native_reference_adapter_keeps_aliases_and_masks_missing_support_contexts():
    control = {"schema": "source_reference_witness_v1", "native_answerable": True,
               "native_answer": "Alpha", "native_answer_aliases": ["A", "Alpha"]}
    assert native_references(control) == ["Alpha", "A"]
    control["native_answerable"] = False
    assert native_references(control) == []
    assert native_references({"annotations": [annotation(yes_no=False)]}) == ["No"]
