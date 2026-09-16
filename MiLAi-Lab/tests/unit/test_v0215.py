"""Discovery allocation, evaluator separation and visible persistence without live models."""

import copy
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import run_v0215 as runner
from prepare_v0215 import prepare
from replay_v0213_cost import save, sha
from v02_local_provider import append_event


def config():
    value = json.loads((Path(__file__).resolve().parents[2] /
                       "configs/v0215-discovery-b1.json").read_text())
    value["host_acquisition"] = {"implementation": "LAB"}
    return value


def action(kind="final", *, note="", decision="WAIT_FOR_APPROVAL"):
    return {"action": kind, "source_ids": ["source-01.txt", "source-03.txt"]
        if kind == "read" else [], "query": "", "decision": decision if kind == "final" else "",
        "explanation": "Public evidence supports the pending next step.",
        "citations": ["source-03.txt"] if kind == "final" else [], "note": note}


def test_probe_exposure_and_online_evaluator_separation(tmp_path):
    prepare(tmp_path / "inputs")
    root = tmp_path / "inputs"
    assert set(json.loads((root / "provenance.json").read_text())["clusters"]) == {
        "pipeline", "grant"}
    for task in root.glob("*/online/phase-*/task.json"):
        value = json.loads(task.read_text())
        assert "expected_decision" not in value
        assert "required_current_source" not in value
        Draft202012Validator.check_schema(runner.action_schema(value["decisions"]))
    for key in ("pipeline", "grant"):
        paths = [root / key / "online" / f"phase-{i}" for i in range(3)]
        assert (paths[0] / "source-03.txt").read_bytes() == (
            paths[1] / "source-03.txt").read_bytes()
        assert (paths[1] / "source-03.txt").read_bytes() != (
            paths[2] / "source-03.txt").read_bytes()
        assert (paths[0] / "source-05.txt").read_bytes() != (
            paths[1] / "source-05.txt").read_bytes()


def test_all_arms_share_task_state_tools_and_capabilities():
    cfg = config()
    messages = [runner.initial_messages(cfg, arm, {"question": "same task"},
        [{"source_id": "source-01.txt"}], {"note": "same fallible note"}) for arm in cfg["arms"]]
    assert messages[0][1:] == messages[1][1:] == messages[2][1:]
    assert all(message[0]["content"].startswith(runner.SYSTEM) for message in messages)
    assert len({message[0]["content"] for message in messages}) == 3
    assert cfg["cumulative_raw_cap"] is None
    assert len(cfg["tasks"]) * len(cfg["arms"]) * len(cfg["phases"]) * cfg[
        "max_generations_per_phase"] <= cfg["max_batch_generations"]


def test_discovery_delivery_clarification_applies_identically_without_gold():
    cfg = config()
    cfg["common_delivery_policy"] = "A recommendation is not an executed action."
    for arm in cfg["arms"]:
        messages = runner.initial_messages(cfg, arm, {}, [], {})
        assert messages[0]["content"].endswith(cfg["common_delivery_policy"])
        assert "expected_decision" not in messages[0]["content"]


@pytest.mark.parametrize("mode", ["normal", "unknown_usage", "no_final"])
def test_cold_host_records_writes_transmission_and_failure(tmp_path, monkeypatch, mode):
    root = tmp_path / "run"
    root.mkdir()
    prepare(root / "cases")
    cfg = config()
    save(root / "manifest.json", {"config": cfg, "host_acquisition": {"implementation": "LAB"}})
    state = {"status": "ABSENT"}
    updates = []

    @contextmanager
    def fake_observer(*args, **kwargs):
        def call(name, arguments):
            nonlocal state
            if name == "milai_working_state_update":
                assert arguments["expected_version"] == state.get("version", 0)
                if state.get("version"):
                    assert arguments["state_id"] == state["state_id"]
                state = {"status": "ACTIVE", "version": state.get("version", 0) + 1,
                         "state_id": "current-state-id", "payload": arguments["payload"]}
                updates.append(copy.deepcopy(arguments))
            return copy.deepcopy(state)
        yield call

    class FakeProvider:
        def __init__(self, directory, **kwargs):
            self.root, self.sent = directory, 0

        def verify(self):
            return {"max_model_len": 65536}

        def generate(self, session, body):
            self.sent += 1
            rid = f"{session}-{self.sent:02d}"
            request = self.root / f"{rid}-request.json"
            save(request, body)
            append_event(self.root / "provider-ledger.jsonl", {
                "event": "RESERVED", "request_id": rid, "session": session,
                "raw_upper_bound": 4101, "prompt_tokens": 5, "output_cap": 4096,
                "payload_sha256": sha(request.read_bytes())})
            save(self.root / f"{rid}-http.json", {"status_code": 200})
            if mode == "unknown_usage":
                raise ValueError("USAGE_UNKNOWN_RESERVATION_RETAINED")
            append_event(self.root / "provider-ledger.jsonl", {
                "event": "SETTLED", "request_id": rid, "input_tokens": 5, "output_tokens": 5,
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}})
            value = action("read") if self.sent == 1 or mode == "no_final" else action(
                note="The approval source is pending; recheck if it changes.")
            return json.dumps(value)

        def close(self):
            pass

    class Tokenizer:
        @staticmethod
        def from_file(path):
            return Tokenizer()

        def encode(self, *args, **kwargs):
            return type("Encoded", (), {"ids": [1] * 5})()

    class Renderer:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            return Renderer()

        def apply_chat_template(self, *args, **kwargs):
            return "rendered"

    monkeypatch.setattr(runner, "observer", fake_observer)
    monkeypatch.setattr(runner, "Provider", FakeProvider)
    monkeypatch.setattr(runner, "Tokenizer", Tokenizer)
    monkeypatch.setattr(runner, "AutoTokenizer", Renderer)
    # Only this fixed text is needed with the mocked renderer.
    tokenizer_root = tmp_path / "tokenizer"
    tokenizer_root.mkdir()
    (tokenizer_root / "chat_template.jinja").write_text("template")
    cfg["tokenizer_snapshot"] = str(tokenizer_root)
    save(root / "manifest.json", {"config": cfg, "host_acquisition": {"implementation": "LAB"}})
    result = runner.cold(root, tmp_path / "owned", "pipeline", "NOTES", 0)
    assert result["initial_seed_writes"] == 1
    assert result["model_messages_inherited"] == 0
    if mode == "normal":
        assert result["status"] == "DELIVERED"
        assert result["state_writes"] == 1 and len(updates) == 2
        assert result["source_reads"] == 2
        assert not result["delivery_budget"]["pending"]
        path = root / "runs/pipeline/NOTES/phase-0/presentation.json"
        presentation = json.loads(path.read_text())
        assert len(presentation) == 2
    elif mode == "unknown_usage":
        assert result["status"] == "PROTOCOL_OR_RESOURCE_FAILURE"
        assert result["accounting"]["requests"] == 1
        assert result["accounting"]["pending"] and result["delivery_budget"]["pending"]
    else:
        assert result["status"] == "NO_FINAL_DELIVERY"
        assert result["source_reads"] == 8  # Final slot never executes another source tool.
    assert result["business_actions_executed"] == 0


def test_disabled_transport_stops_before_creating_run(tmp_path):
    save(tmp_path / "manifest.json", {"config": {"model_transport_enabled": False}})
    with pytest.raises(ValueError, match="MODEL_TRANSPORT_DISABLED"):
        runner.cold(tmp_path, tmp_path, "pipeline", "NOTES", 0)
    assert not (tmp_path / "runs").exists()


def test_public_cas_create_and_update_have_different_identity_contracts():
    create = runner.state_write_arguments({"status": "ABSENT"}, "note", "op-create")
    assert create["expected_version"] == 0 and "state_id" not in create
    update = runner.state_write_arguments({"status": "ACTIVE", "version": 7,
        "state_id": "actual-public-id"}, "revised", "op-update")
    assert update["state_id"] == "actual-public-id" and update["expected_version"] == 7


def test_readiness_protocol_forbids_empty_read_and_reserves_actual_final():
    decisions = ["WAIT_FOR_APPROVAL", "INSUFFICIENT_EVIDENCE"]
    value = {"assessment": {"basis": "Sources needed.", "readiness": "NEEDS_SOURCE"},
             "delivery": action("read")}
    ordinary = Draft202012Validator(runner.readiness_action_schema(decisions))
    final = Draft202012Validator(runner.readiness_action_schema(decisions, final_slot=True))
    assert ordinary.is_valid(value) and not final.is_valid(value)
    value["delivery"]["source_ids"] = []
    assert not ordinary.is_valid(value)
    value = {"assessment": {"basis": "A required observation is missing.",
                            "readiness": "NEEDS_CLARIFICATION"},
             "delivery": action(decision="INSUFFICIENT_EVIDENCE")}
    assert final.is_valid(value)
