"""Fixed-code classification is complete, label-blind and one-position forward only."""

from types import SimpleNamespace

import pytest

from local_fixed_choice_review import (
    CODES,
    choices,
    prepare_requests,
    resource_ready,
    score_request,
)


class Tokenizer:
    def encode(self, text, **_kwargs):
        return [CODES.index(text)] if text in CODES else list(range(len(text) // 4))

    def apply_chat_template(self, messages, **_kwargs):
        return "\n".join(row["content"] for row in messages)


def test_all_joint_choices_permutations_no_private_labels_and_no_prompt_truncation():
    cases = [{"case_code": f"J{i:03d}", "question": "Which fact?", "packet": {}} for i in range(10)]
    pilot = [r["case_code"] for r in cases]
    rubric = {"rules": ["Return one JSON object matching the schema without markdown."]}
    requests = prepare_requests(cases, pilot, rubric, Tokenizer())
    assert len(requests) == 20
    assert requests == prepare_requests(cases, pilot, rubric, Tokenizer())
    assert requests[0]["code_options"] != requests[1]["code_options"]
    assert len({str(v) for v in choices(1).values()}) == 27
    assert "Return one JSON object" not in requests[0]["rendered_prompt"]
    assert "expected" not in requests[0]["rendered_prompt"]
    with pytest.raises(ValueError, match="no truncation"):
        prepare_requests(cases, pilot, rubric, Tokenizer(), maximum_input=2)
    cases[0]["expected"] = "PRIVATE"
    with pytest.raises(ValueError, match="Private"):
        prepare_requests(cases, pilot, rubric, Tokenizer())
    assert resource_ready({0: 40000, 1: 40000, 2: 35840, 3: 35840})
    assert not resource_ready({0: 40000, 1: 40000, 2: 35839, 3: 35840})


def test_only_one_forward_position_scored_and_invalid_joint_choice_not_repaired():
    torch = pytest.importorskip("torch")
    calls = []

    class Model:
        def __call__(self, **kwargs):
            calls.append(kwargs)
            assert kwargs["use_cache"] is False and kwargs["logits_to_keep"] == 1
            return SimpleNamespace(logits=torch.arange(27.0)[None, None, :])

    mapping = choices(1)
    mapping[CODES[-1]] = {
        "material_status": "UNKNOWN",
        "task_resolution": True,
        "answer_grounding": False,
    }
    request = {
        "case_code": "J000",
        "encoding": 0,
        "input_token_ids": [1, 2, 3],
        "input_tokens": 3,
        "code_token_ids": dict(zip(CODES, range(27), strict=True)),
        "code_options": mapping,
    }
    result = score_request(Model(), request, device="cpu")
    assert len(calls) == 1 and result["decision_positions"] == 1
    assert result["predicted_code"] == CODES[-1]
    assert result["valid_joint_combination"] is False
    assert result["predicted_axes"] == mapping[CODES[-1]]
    assert result["text_generation_tokens"] == 0 and len(result["all_code_logits"]) == 27
