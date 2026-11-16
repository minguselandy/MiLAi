"""Full synthetic two-pool cohort through real Stores, Reader and separate native scoring."""
import json
import socket

import httpx
import pytest
from test_lme_protocol import UPSTREAM
from test_retrieval_feedback_without_fingerprints import forbid_fingerprints
from test_v13_5_functional_integration import prepared

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.providers.chat_bridge import IncompleteChatResponse
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.lme_evaluation import predict_cohort, score_cohort


def fixture(tmp_path, monkeypatch):
    forbid_fingerprints(monkeypatch)
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("REAL_NETWORK_FORBIDDEN"))
    prepared(tmp_path, native=False, memory_method="milai_edit_m_v1",
        edit_interface_version="I2", edit_features={"source_metadata": True},
        memory_profile="unified_v1", evidence_policy="question_pack_v1",
        retrieval_tool="rich", business_tools=[], memory_view_mode="staged",
        memory_control={"policy": "fixed_context", "reads": 4, "max_control_steps": 6})
    snapshot = tmp_path/"snapshot"
    (snapshot/"haystacks").mkdir(parents=True)
    rows = [{"id": f"OFFLINE_ID_{i}", "domain": "enterprise" if i==1 else "web",
        "question": f"Public request number {i}\u2028literal separator", "image": None,
        "question_type": "errors-gotchas" if i==1 else "static-environment",
        "eval_function": "llm_gotchas_checker" if i==1 else "norm_phrase_set_match",
        "answer": "REFERENCE_ONLY_FOR_JUDGE" if i==1 else "blue",
        "PRIVATE_GOLD_SOURCE_FILTER": ["a"]} for i in range(3)]
    (snapshot/"questions.jsonl").write_text(
        "".join(json.dumps(q, ensure_ascii=False)+"\n" for q in rows))
    write_json(snapshot/"haystacks/lme_v2_small.json", {
        rows[0]["id"]:["b","a"], rows[1]["id"]:["c"], rows[2]["id"]:["b","a"]})
    trajectories = [{"id": name, "goal": "Recorded public task", "states": [{
        "screenshot": None, "accessibility_tree": "Marker "+name+" color blue"}]}
        for name in ("a","b","c")]
    (snapshot/"trajectories.jsonl").write_text("".join(json.dumps(t)+"\n" for t in trajectories))
    return snapshot


def response(content, finish="stop"):
    return httpx.Response(200, json={"choices":[{"finish_reason":finish,
        "message":{"role":"assistant","content":content}}],
        "usage":{"prompt_tokens":7,"completion_tokens":5,"total_tokens":12}})


def test_full_cohort_preserves_pools_privacy_and_separate_judge_phase(tmp_path, monkeypatch):
    snapshot = fixture(tmp_path, monkeypatch)
    output, scored = tmp_path/"predictions", tmp_path/"scores"
    wires = []

    def reader(request):
        payload = json.loads(request.content)
        wires.append(payload)
        text = request.content.decode()
        assert "REFERENCE_ONLY_FOR_JUDGE" not in text and "PRIVATE_GOLD_SOURCE_FILTER" not in text
        assert "OFFLINE_ID_" not in text
        if len(wires)==3:
            assert "Public request number 0" not in text
        return response("\\boxed{blue}")

    driver = predict_cohort(tmp_path/"settings.json", snapshot, UPSTREAM, output,
        source_version="mechanical", capacity_factory=HostCapacity,
        transport=httpx.MockTransport(reader))
    assert driver["status"] == "COMPLETED" and len(wires)==3
    cohort = read_json(output/"cohort.json")
    assert [p["trajectory_ids"] for p in cohort["pools"]] == [["b","a"],["c"]]
    sources = read_json(output/"memory/pool-0000/source-setup.json")["sources"]
    assert [s["original_event_id"] for s in sources] == [
        "b/trajectory","b/state-0","a/trajectory","a/state-0"]
    assert driver["cases"][2]["runtime"].endswith("pool-0000/cases/0001")
    assert not list(output.glob("**/score.json"))
    original_predictions = [(output/f"predictions/{i:04d}/prediction.json").read_bytes()
                            for i in range(3)]
    # Scoring must use the already retained reference input, not a mutable upstream file.
    (snapshot/"questions.jsonl").write_text("CHANGED_AFTER_PREDICTIONS\n")
    judge_wires = []

    def judge(request):
        judge_wires.append(json.loads(request.content))
        assert "REFERENCE_ONLY_FOR_JUDGE" in request.content.decode()
        assert all((output/f"predictions/{i:04d}/prediction.json").exists() for i in range(3))
        return response('{"label":1,"reason":"synthetic match"}')

    scores = score_cohort(output, scored, source_version="mechanical",
                          transport=httpx.MockTransport(judge))
    assert scores["status"] == "COMPLETED" and len(judge_wires)==1
    assert read_json(scored/"metrics.json")["native_complete_cohort_metrics"][
        "overall"]["overall_full_set"] == 1
    assert [q["score"] for q in scores["cases"]] == [1,1,1]
    assert original_predictions == [(output/f"predictions/{i:04d}/prediction.json").read_bytes()
                                     for i in range(3)]
    ledger = read_json(tmp_path/"isolated-mechanical-budget.json")
    assert ledger["generation_requests"] == 4 and ledger["generation"]["known_tokens"] == 48
    assert ledger["generation"]["unknown_usage"] == 0


def test_failed_reader_and_unattempted_tail_keep_full_denominator(tmp_path, monkeypatch):
    snapshot = fixture(tmp_path, monkeypatch)
    output = tmp_path/"predictions"
    calls = []

    def reader(request):
        calls.append(request)
        return response("\\boxed{blue}", "length" if len(calls)==2 else "stop")

    with pytest.raises(IncompleteChatResponse):
        predict_cohort(tmp_path/"settings.json", snapshot, UPSTREAM, output,
            source_version="mechanical", capacity_factory=HostCapacity,
            transport=httpx.MockTransport(reader))
    driver = read_json(output/"driver.json")
    assert driver["status"] == "FAILED" and len(calls)==2
    assert [c["status"] for c in driver["cases"]] == ["COMPLETED","FAILED_READING","NOT_RUN"]
    score_cohort(output, tmp_path/"scores", source_version="mechanical",
        transport=httpx.MockTransport(lambda _: pytest.fail("No successful LLM-metric prediction")))
    metrics = read_json(tmp_path/"scores/metrics.json")
    assert metrics["planned"] == 3 and metrics["scored"] == 1 and metrics["unscored"] == 2
    assert metrics["native_complete_cohort_metrics"] is None
    assert metrics["all_planned_score_bounds"] == [1/3,1]
    assert read_json(tmp_path/"isolated-mechanical-budget.json")["generation_requests"] == 2


def test_running_prediction_phase_cannot_be_scored(tmp_path):
    prediction = tmp_path/"prediction"
    write_json(prediction/"driver.json", {"status":"RUNNING"})
    with pytest.raises(ValueError, match="Finish the prediction phase"):
        score_cohort(prediction, tmp_path/"score", source_version="mechanical")
    assert not (tmp_path/"score").exists()
