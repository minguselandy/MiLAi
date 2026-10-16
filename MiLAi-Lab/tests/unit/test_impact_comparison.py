"""Same actual seed/arrival, no evaluator input to Writer, and state-only separation."""
import copy
import json
from pathlib import Path

from test_method_architecture_diagnostic import StubRun

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.impact_comparison import (
    comparison_settings,
    prepare_comparison,
    run_comparison_arm,
    state_reader_messages,
)
from milai_lab.runners.method_architecture_diagnostic import (
    _prepare_arrival,
    prepare_diagnostic,
    run_seed,
)


class PilotStub(StubRun):
    def call(self, key, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        assert set(payload) == {"question", "observed_date", "retained_state"}
        assert all(set(row) == {"id", "revision", "content", "scope"}
                   for row in payload["retained_state"])
        return "State diagnostic fixture"


def test_pilot_reuses_original_seed_and_separates_writer_from_all_queries(tmp_path):
    lab = Path(__file__).resolve().parents[2]
    config = read_json(lab / "configs/milai-method-architecture-paired-v1.json")
    for key in ("plain_config", "candidate_config", "sources"):
        config[key] = str(lab / config[key])
    config["queries"] = [{"id": "q", "kind": "current", "question": "READER_ONLY",
                           "gold": "EVALUATOR_ONLY"}]
    source = tmp_path / "source"
    case_root = source / "case"
    prior = prepare_diagnostic(config, case_root)
    prior["settings"]["plain"] = copy.deepcopy(prior["settings"]["candidate"])
    seed = run_seed(prior, case_root, run_class=PilotStub)
    _prepare_arrival(prior, case_root)
    write_json(source / "prepared.json", {"settings": prior["settings"]["candidate"],
        "cases": [{"id": "case", "owner": config["owner"],
                   "observations": prior["observations"], "queries": config["queries"]}]})
    output = tmp_path / "comparison"
    protocol = prepare_comparison({"source_run": str(source), "name": "test-pilot",
        "cases": ["case"], "laya": {"D2-Laya-0": {"model": "base"},
                                   "D2-Laya-CE": {"model": "trained"}}}, output)
    PilotStub.requests = []
    for arm in ("D0", "D1"):
        result = run_comparison_arm(protocol, output, arm, run_class=PilotStub)
        case = result["cases"]["case"]
        assert case["before"] == seed["actual_state"]
        assert case["after"] != case["before"]
        assert case["read_values_unchanged"]
        assert {a["mode"] for a in case["answers"]} == {"mixed", "state_only"}
        assert case["state_correct"] is None
        calls = len(PilotStub.requests)
        assert run_comparison_arm(protocol, output, arm, run_class=PilotStub) == result
        assert len(PilotStub.requests) == calls
    assert "EVALUATOR_ONLY" not in json.dumps(PilotStub.requests)
    assert "READER_ONLY" not in json.dumps(PilotStub.requests)
    assert read_json(case_root / "seed/result.json") == seed
    settings = [comparison_settings(protocol, arm, "case") for arm in (
        "D0", "D1", "D2-Laya-0", "D2-Laya-CE")]
    for selected in settings:
        assert selected["model"] == protocol["settings"]["model"]
        assert selected["dependency_reading"] is False
    assert [s["edit_features"]["dependency_updates"] for s in settings] == [False, True, True, True]
    assert [s.get("laya_impact", {}).get("model") for s in settings] == [
        None, None, "base", "trained"]


def test_state_diagnostic_never_copies_original_or_support_text():
    records = [{"id": "real-id", "value": {"revision": 2, "content": "current proposition",
        "scope": {}, "original_source": "ORIGINAL_SECRET", "support_turns": ["SUPPORT_SECRET"]}}]
    before = copy.deepcopy(records)
    messages = state_reader_messages(records, "question", "2032-06-03")
    assert "current proposition" in json.dumps(messages)
    assert "ORIGINAL_SECRET" not in json.dumps(messages)
    assert "SUPPORT_SECRET" not in json.dumps(messages)
    assert records == before


def test_local_arm_reuses_the_identical_choice_without_another_provider_call(tmp_path):
    from urllib.parse import quote

    import pytest

    from milai_lab.methods.laya_impact import impact_payload
    from milai_lab.runners.impact_comparison import comparison_costs
    from milai_lab.runners.laya_impact import replay_impact_selection

    schema = {"properties": {"roots": {"items": {"enum": ["u1", "u2"]}}}}
    messages = [{"role": "user", "content": json.dumps({"observed_date": "2032-06-02",
                "delivery": {"current_event": "A changes; B stays"}})}]
    selection = {"roots": ["u1"], "preserve": ["u2"]}
    stage, http_folder, stage_path = "impact:work-0", "maintenance/update/batch-0", "impact/work-0"
    for provider in ("generative", "laya"):
        source = tmp_path / provider / "source"
        output = tmp_path / provider / "local"
        folder = (source / "typed-http" / http_folder / quote(stage, safe="")
                  if provider == "laya" else source / "http" / http_folder / stage_path)
        if provider == "laya":
            write_json(folder / "request.json", {**impact_payload(messages, schema), "model": "ce"})
            write_json(folder / "selection.json", selection)
            write_json(folder / "response.json", {"response_text": json.dumps({
                "usage": {"input_tokens": 77, "output_tokens": 0}})})
        else:
            write_json(folder / "request.json", {"messages": messages})
            write_json(folder / "response.json", {"choices": [{"finish_reason": "stop",
                "message": {"content": json.dumps(selection)}}], "usage": {"total_tokens": 88}})
        config = {"root": str(source), "provider": provider}
        selected = replay_impact_selection(stage, messages, schema, config=config,
                    http_folder=http_folder, stage_path=stage_path, output=output)
        assert selected == selection
        assert not list(output.rglob("request.json"))
        costs = comparison_costs(output)
        assert costs["reused_controller"][0]["original_compute_tokens"] == (
            77 if provider == "laya" else 88)
        changed = [{"role": "user", "content": json.dumps({"observed_date": "2032-06-03",
                    "delivery": {"current_event": "B changes"}})}]
        with pytest.raises(ValueError, match="different event/candidate"):
            replay_impact_selection(stage, changed, schema, config=config,
                http_folder=http_folder, stage_path=stage_path, output=output)
