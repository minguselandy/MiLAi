"""No-run and input-alias conditions retain their denominators without fake ledgers."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from finalize_v0213 import finalize, unrun_outcome
from replay_v0213_cost import save, sha
from v02_local_provider import accounting, append_event


def test_alias_reuses_score_without_adding_request_or_independent_observation():
    original = {"key": "task", "arm": "R1", "outcome": "CORRECT",
                "intent": [{"name": "call", "arguments": {}}]}
    row = unrun_outcome({"key": "task", "arm": "O", "status": "IDENTICAL_INPUT_ALIAS",
                         "alias_of": "R1"}, [original])
    assert row["outcome"] == "CORRECT" and row["intent"] == original["intent"]
    assert row["requests"] == row["raw_tokens"] == 0
    assert not row["independent_observation"] and not row["attempted"]


def test_invalid_oracle_and_unrun_time_finalize_without_arm_files(tmp_path):
    admission, run = tmp_path / "admission", tmp_path / "run"
    evaluation, online = admission / "evaluation/task", admission / "online/task"
    for path in (evaluation, online, run / "product"):
        path.mkdir(parents=True)
    save(admission / "accepted.json", {"accepted": [{"key": "task"}], "first_wave": ["task"]})
    save(evaluation / "evaluation-contract.json", {})
    save(evaluation / "support-review.json", {"sufficient": False})
    save(online / "source-index.json", {})
    seal = {"accepted_sha256": sha((admission / "accepted.json").read_bytes()),
            "implementation": {}, "entries": [{"key": "task", "support_review_sha256":
                sha((evaluation / "support-review.json").read_bytes())}]}
    save(admission / "seal-b.json", seal)
    save(admission / "seal-b-sha256.json", {
        "sha256": sha((admission / "seal-b.json").read_bytes())})
    save(run / "result.json", {"requests": 0, "raw_tokens": 0, "results": [
        {"key": "task", "arm": "A0", "status": "NOT_RUN_TIME"},
        {"key": "task", "arm": "R1", "status": "NOT_RUN_TIME"},
        {"key": "task", "arm": "O", "status": "ORACLE_INSUFFICIENT"}]})
    save(run / "evaluation-outcome-review.json", {"selected_followup": "UNRESOLVED"})
    save(run / "product/cleanup.json", {"api_stopped": True, "compose_stop_returncode": 0})
    result = finalize(admission, run)
    assert result["status"] == "UNRESOLVED_NO_GENERATIONS"
    assert result["attempted_clusters"] == 0
    assert result["counts"]["O"]["ORACLE_INSUFFICIENT"] == 1
    assert result["counts"]["A0"]["attempted"] == 0
    assert result["paired_parameter_scored"] == {"A0_R1": 0, "A0_O": 0, "R1_O": 0}
    assert not (run / "task").exists()


def test_unscored_intent_is_structurally_valid_but_not_parameter_scored(tmp_path):
    admission, run = tmp_path / "admission", tmp_path / "run"
    evaluation, online = admission / "evaluation/task", admission / "online/task"
    arm = run / "task/R1"
    for path in (evaluation, online, run / "product", arm):
        path.mkdir(parents=True)
    save(admission / "accepted.json", {"accepted": [{"key": "task"}], "first_wave": ["task"]})
    save(evaluation / "evaluation-contract.json", {"expected_intent": []})
    save(evaluation / "support-review.json", {"sufficient": False, "adjudicable": False})
    save(online / "source-index.json", {})
    save(arm / "request-request.json", {"messages": []})
    payload_sha = sha((arm / "request-request.json").read_bytes())
    usage = {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
    records = [
        {"event": "RESERVED", "request_id": "request", "session": "task",
         "prompt_tokens": 5, "output_cap": 4096, "raw_upper_bound": 4101,
         "payload_sha256": payload_sha},
        {"event": "SETTLED", "request_id": "request", "input_tokens": 5,
         "output_tokens": 2, "usage": usage},
    ]
    for record in records:
        append_event(arm / "provider-ledger.jsonl", record)
    save(arm / "request-tokenize.json", {"count": 5})
    save(arm / "request-http.json", {"body": json.dumps({"usage": usage})})
    result = {"key": "task", "arm": "R1", "status": "ANSWERED",
              "intent": [{"name": "lookup", "arguments": {"id": 0}}],
              "accounting": accounting(records)}
    save(arm / "result.json", result)
    seal = {"accepted_sha256": sha((admission / "accepted.json").read_bytes()),
            "implementation": {}, "entries": [{"key": "task", "support_review_sha256":
                sha((evaluation / "support-review.json").read_bytes()),
                "arms": {"R1": {"sha256": payload_sha, "prompt_tokens": 5}}}]}
    save(admission / "seal-b.json", seal)
    save(admission / "seal-b-sha256.json", {
        "sha256": sha((admission / "seal-b.json").read_bytes())})
    save(run / "result.json", {"requests": 1, "raw_tokens": 7, "results": [
        {"key": "task", "arm": "A0", "status": "NOT_RUN_TIME"}, result,
        {"key": "task", "arm": "O", "status": "ORACLE_INSUFFICIENT"}]})
    save(run / "evaluation-outcome-review.json", {
        "selected_followup": "TASK_CONTRACT_CANDIDATE", "task": {"R1": {}}})
    save(run / "product/cleanup.json", {"api_stopped": True, "compose_stop_returncode": 0})
    terminal = finalize(admission, run)
    assert terminal["status"] == "COMPLETED_BOUNDED_DECOMPOSITION_KEEP_A0"
    assert terminal["counts"]["R1"]["valid_intents"] == 1
    assert terminal["counts"]["R1"]["parameter_scored"] == 0
    assert terminal["counts"]["R1"]["UNSCORED"] == 1
    assert terminal["paired_parameter_scored"] == {"A0_R1": 0, "A0_O": 0, "R1_O": 0}
