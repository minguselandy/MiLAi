"""A task-wording intervention changes no delivered evidence or source request."""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.edit_benchmarks import BenchmarkRun
from prepare_meme_reader_confirmation import project_episode
from run_meme_reader_rules import messages_for


def test_paired_messages_only_add_generic_rule_task_to_system_instruction():
    request = {"messages": [{"role": "system", "content": "original instructions"},
                            {"role": "user", "content": '{"question":"q","facts":["if"]}'}],
               "private_reference": "EVALUATOR_ONLY"}
    original = copy.deepcopy(request)
    baseline = messages_for(request, None)
    treatment = messages_for(request, "Apply the supplied rules.")
    assert request == original
    assert baseline == request["messages"]
    assert treatment[1:] == baseline[1:]
    assert treatment[0]["content"] == baseline[0]["content"] + "\nApply the supplied rules."
    assert "EVALUATOR_ONLY" not in str(treatment)
    compact = messages_for(request, None, "Use reports as attributed premises.")
    assert compact[0]["content"] == "Use reports as attributed premises."
    assert compact[1:] == baseline[1:]
    assert request == original


def test_declared_sampling_reaches_wire_and_receipt_without_changing_defaults(tmp_path):
    import httpx

    wires = []

    def respond(request):
        wires.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": "answer"}}], "usage": {"total_tokens": 12}})

    run = BenchmarkRun.__new__(BenchmarkRun)
    run.root = tmp_path
    run.settings = {"model": {"max_tokens": 32}, "context_tokens": 1024,
                    "interface_version": "I2"}
    run.input_tokens = lambda *args, **kwargs: 10
    sampling = {"top_p": 0.95, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.5,
                "repetition_penalty": 1.0, "seed": 20261017}
    with VLLMClient(VLLMConfig("http://fixture/v1", "model", temperature=1.0, max_tokens=32),
                    transport=httpx.MockTransport(respond)) as client:
        run.client = client
        messages = [{"role": "user", "content": "fixture"}]
        assert run.call("explicit", messages, structured=False, **sampling) == "answer"
        assert run.call("default", messages, structured=False) == "answer"
    saved = json.loads((tmp_path / "http/explicit/request.json").read_text())
    assert all(wires[0][key] == saved[key] == value for key, value in sampling.items())
    assert wires[0]["temperature"] == wires[1]["temperature"] == 1.0
    assert not set(sampling) & set(wires[1])


def test_new_episode_projection_uses_only_arrived_source_prefix():
    episode = {"episode_id": "fixture", "root_change": "PRIVATE_ROOT", "edges": ["PRIVATE"],
        "sessions": [{"timestamp": "day1", "gold_facts": "PRIVATE", "conversation": [
            {"role": "user", "content": "old report"},
            {"role": "assistant", "content": "old response"}]},
            {"timestamp": "day2", "conversation": [{"role": "user", "content": "new report"}]}],
        "before_questions": {"position_after_session": 0, "timestamp": "day1", "questions": [
            {"question": "q", "task_type": "Cas", "entity": ["e"],
             "expected_answer": "PRIVATE_OLD"}]},
        "after_questions": {"position_after_session": 1, "timestamp": "day3", "questions": [
            {"question": "q", "task_type": "Cas", "entity": ["e"],
             "gold_answer": "PRIVATE_NEW"}]}}
    cases, references = project_episode(episode)
    before = json.loads(cases[0]["messages"][1]["content"])
    after = json.loads(cases[1]["messages"][1]["content"])
    assert [s["text"] for s in before["memories"]] == ["old report", "old response"]
    assert after["memories"][-1] == {"source": "s1-t0", "role": "user",
                                      "reported_at": "day2", "text": "new report"}
    assert "PRIVATE" not in str(cases)
    assert references[-1]["before_id"] == "before-0"
