"""Pinned upstream prompt and metric functions on synthetic questions only."""
import base64
import shutil
from pathlib import Path

import pytest

from milai_lab.datasets.lme_protocol import NativeLmeProtocol

UPSTREAM = Path("/cra/memory/mx_memory/benchmarks/LongMemEval-V2")


@pytest.fixture
def protocol():
    return NativeLmeProtocol(UPSTREAM)


def options():
    return {"evaluator_model": "local-fixture", "evaluator_base_url": "http://fixture/v1",
        "evaluator_api_key": "unused-local-adapter", "evaluator_max_completion_tokens": 128,
        "evaluator_temperature": 1, "evaluator_top_p": None,
        "evaluator_reasoning_effort": None, "evaluator_timeout_seconds": 180}


@pytest.mark.parametrize("spec,answer,response,expected", [
    ("norm_phrase_set_match", "blue gate;red box", "\\boxed{red box and blue gate}", True),
    ("norm_phrase_set_match_ordered", "blue gate;red box", "red box then blue gate", False),
    ("norm_phrase_set_match_ordered", "blue gate;red box", "blue gate then red box", True),
    ("mc_choice_match", "A", "\\boxed{B} revised: \\boxed{A}", True),
    ("mc_choice_set_match", "AC", "Final answer: C and A", True),
    ("mc_choice_set_match", "AC", "A and B and C", False),
    ("norm_phrase_set_match|normalize_hyphen=false", "blue-gate", "blue gate", False),
    ("norm_phrase_set_match", "unknown", "\\boxed{UNKNOWN}", False),
])
def test_native_metrics_and_unknown_override(protocol, spec, answer, response, expected):
    value = protocol.score({"question": "Synthetic question", "question_type": "static-environment",
        "eval_function": spec, "answer": answer}, response, judge_options=options(),
        complete=lambda _: pytest.fail("Exact metric must not call a Judge"))
    assert value["score_bool"] is expected


@pytest.mark.parametrize("spec,qtype", [("llm_abstention_checker", "dynamic-environment-abs"),
                                       ("llm_gotchas_checker", "errors-gotchas")])
def test_native_judge_prompts_and_parser_use_injected_transport(protocol, spec, qtype):
    calls = []

    def complete(request):
        calls.append(request)
        assert request["model"] == "local-fixture"
        assert request["max_completion_tokens"] == 128
        assert request["timeout"] == 180
        assert "REFERENCE_ONLY_FOR_JUDGE" in request["messages"][1]["content"]
        assert "full explanation" in request["messages"][1]["content"]
        return '```json\n{"label": 1, "reason": "synthetic agreement"}\n```'

    value = protocol.score({"question": "Synthetic question", "question_type": qtype,
        "eval_function": spec, "answer": "REFERENCE_ONLY_FOR_JUDGE"},
        "full explanation \\boxed{a synthetic conclusion}",
        judge_options=options(), complete=complete)
    assert value["score_bool"] and len(calls) == 1
    assert value["is_abstention_problem"] == (spec == "llm_abstention_checker")


def test_native_prompt_preserves_all_memory_and_question_images(protocol, tmp_path):
    source, question = tmp_path / "source.png", tmp_path / "question.png"
    source.write_bytes(b"synthetic source pixels")
    question.write_bytes(b"synthetic question pixels")
    context = [{"type": "text", "value": "Actual returned text"},
               {"type": "image", "value": str(source)}]
    messages, logged = protocol.messages("web", "Original question", str(question), context)
    content = messages[1]["content"]
    assert [part["type"] for part in content] == ["text", "text", "image_url", "text", "image_url"]
    assert base64.b64decode(content[2]["image_url"]["url"].split(",")[1]) == source.read_bytes()
    assert base64.b64decode(content[4]["image_url"]["url"].split(",")[1]) == question.read_bytes()
    assert logged[1]["content"][2] == {"type": "image_path", "image_path": str(source)}
    assert "Original question" in content[3]["text"]


def test_failed_positions_are_unscored_not_fabricated_unknown(protocol):
    good = {"status": "COMPLETED", "score": 1.0, "score_bool": True, "is_unknown": False,
            "is_abstention_problem": False, "category": "static"}
    unknown = {**good, "score": 0.0, "score_bool": False, "is_unknown": True}
    failed = {"status": "FAILED_READER", "score": None}
    result = protocol.aggregate([good, unknown, failed])
    assert result["planned"] == 3 and result["scored"] == 2
    assert result["valid_model_UNKNOWN_answers"] == 1
    assert result["all_planned_score_bounds"] == [1/3, 2/3]
    assert result["native_complete_cohort_metrics"] is None
    assert result["native_scored_subset_metrics"]["overall"]["overall_full_set"] == .5
    complete = protocol.aggregate([good, unknown])
    assert complete["native_complete_cohort_metrics"]["overall"]["count_all_questions"] == 2


def test_malformed_judge_response_retains_native_failure(protocol):
    with pytest.raises(ValueError, match="Could not parse"):
        protocol.score({"question": "Synthetic", "question_type": "errors-gotchas",
            "eval_function": "llm_gotchas_checker", "answer": "reference"}, "answer",
            judge_options=options(), complete=lambda _: "not a binary judgement")


def test_unrelated_native_initialization_and_sdk_client_are_not_loaded(tmp_path):
    (tmp_path/"evaluation").mkdir()
    for name in ("harness.py", "qa_eval_metrics.py"):
        shutil.copyfile(UPSTREAM/"evaluation"/name, tmp_path/"evaluation"/name)
        with (tmp_path/"evaluation"/name).open("a") as stream:
            stream.write('\nraise AssertionError("UNRELATED_MODULE_INITIALIZATION")\n')
    protocol = NativeLmeProtocol(tmp_path)
    assert "_create_openai_client" not in protocol.metric_namespace
    assert "OPENAI_MAX_RETRIES" not in protocol.metric_namespace
    assert protocol.metrics.mc_choice_match("A", "A")


def test_new_import_in_selected_native_function_requires_explicit_dependency(tmp_path):
    (tmp_path/"evaluation").mkdir()
    source = (UPSTREAM/"evaluation/qa_eval_metrics.py").read_text()
    source = source.replace('    marker = "\\\\boxed{"',
                            '    import socket\n    marker = "\\\\boxed{"')
    assert "    import socket" in source
    (tmp_path/"evaluation/qa_eval_metrics.py").write_text(source)
    with pytest.raises(ValueError, match="explicitly supplied dependencies"):
        NativeLmeProtocol(tmp_path)
