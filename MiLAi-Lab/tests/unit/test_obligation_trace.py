"""Offline contract provenance and manual-result composition; no runtime inference."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from milai_lab.analysis.obligation_trace import LAYERS, compose_obligation_trace, main


def _inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    text = "保存计划。\nOnly this reply must be short. Recall the plan without changing it."
    obligations = [{
        "id": "ob-" + str(index), "case_id": "case", "target_message_id": "message",
        "layer": layer, "description": "human-declared requirement " + str(index),
        "task_failing": index != 3,
        "basis": [{"message_id": "message", "quote": text[:5]}] if index != 3 else [],
    } for index, layer in enumerate(LAYERS)]
    contract = {"schema_version": 1, "runtime_must_not_read": True,
        "legacy_score": {"frozen": "fail", "score": "5/6"},
        "cases": [{"case_id": "case", "messages": [{"message_id": "message", "text": text}],
                   "obligations": obligations}]}
    observations = {"schema_version": 1, "legacy_score": ["unchanged", 0.5], "observations": [
        {"case_id": "case", "obligation_id": "ob-0", "result": "pass",
         "answer_contains": "no", "earliest_breakpoint": None,
         "note": "Negative scope requirement: absence is correct; manual judgment.",
         "evidence": [{"path": "trace.jsonl", "sha256": "a" * 64,
                       "location": {"line": 3}}]},
        {"case_id": "case", "obligation_id": "ob-1", "result": "pass",
         "memory_formed": "no", "note": "No persistence is the declared requirement."},
        {"case_id": "case", "obligation_id": "ob-3", "result": "fail",
         "earliest_breakpoint": "manual_diagnostic", "legacy_score": {"frozen": "fail"}},
    ]}
    return contract, observations


def test_manual_verdicts_diagnostics_missing_and_legacy_remain_separate() -> None:
    contract, observations = _inputs()
    original = copy.deepcopy((contract, observations))
    output = compose_obligation_trace(contract, observations)
    case = output["cases"][0]
    diagnostic = case["layers"][LAYERS[3]][0]
    assert diagnostic["result"] == "fail" and not diagnostic["task_failing"]
    assert output["layer_counts"][LAYERS[3]]["fail"] == 1
    assert output["task_failing_counts"] == {
        "total": 3, "pass": 2, "fail": 0, "unknown": 1, "not_applicable": 0, "missing": 1}
    missing = case["layers"][LAYERS[2]][0]
    assert missing["result"] == "unknown" and missing["observation_status"] == "missing"
    assert set(missing["chain"].values()) == {"unknown"}
    assert case["layers"][LAYERS[0]][0]["chain"]["answer_contains"] == "no"
    assert case["layers"][LAYERS[0]][0]["earliest_breakpoint"] is None
    assert case["layers"][LAYERS[0]][0]["chain"]["present_in_user_request"] == "unknown"
    assert case["layers"][LAYERS[1]][0]["result"] == "pass"
    assert output["contract_metadata"]["legacy_score"] == contract["legacy_score"]
    assert output["observation_metadata"]["legacy_score"] == observations["legacy_score"]
    assert diagnostic["legacy_score"] == {"frozen": "fail"}
    assert "task_score" not in output
    # Output mutation cannot mutate either input, including nested basis/evidence/legacy values.
    case["layers"][LAYERS[0]][0]["basis"].clear()
    case["layers"][LAYERS[0]][0]["evidence"][0]["location"]["line"] = 999
    output["contract_metadata"]["legacy_score"]["frozen"] = "changed"
    assert (contract, observations) == original


def test_later_use_explicit_summary_counts_identity_once_and_scopes_case_ids() -> None:
    contract, observations = _inputs()
    second = copy.deepcopy(contract["cases"][0])
    second["case_id"] = "second"
    for row in second["obligations"]:
        row["case_id"] = "second"
    contract["cases"].append(second)
    output = compose_obligation_trace(contract, observations)
    assert output["cases"][0]["explicit_current_including_later_use_counts"]["total"] == 2
    assert output["explicit_current_including_later_use_counts"]["total"] == 4
    assert output["layer_counts"][LAYERS[2]]["total"] == 2
    assert output["cases"][1]["task_failing_counts"]["missing"] == 3
    assert output["cases"][1]["layers"][LAYERS[0]][0]["result"] == "unknown"


def test_manual_failure_does_not_need_a_no_stage_and_partial_observation_stays_unknown() -> None:
    contract, observations = _inputs()
    observations["observations"][0].update(result="fail", answer_contains="yes",
                                         earliest_breakpoint="human_checked_contract")
    observations["observations"][1].pop("result")
    output = compose_obligation_trace(contract, observations)
    assert output["task_failing_counts"]["fail"] == 1
    partial = output["cases"][0]["layers"][LAYERS[1]][0]
    assert partial["observation_status"] == "provided" and partial["result"] == "unknown"
    assert partial["chain"]["memory_formed"] == "no"


def test_basis_can_use_past_but_never_future_public_messages() -> None:
    contract, observations = _inputs()
    case = contract["cases"][0]
    case["messages"].append({"message_id": "later", "text": "Later report."})
    case["obligations"][1]["target_message_id"] = "later"
    assert compose_obligation_trace(contract, observations)["task_failing_counts"]["pass"] == 2
    # Diagnostics cannot present future quotes as then-visible evidence either.
    for index in (0, 3):
        row = case["obligations"][index]
        row["basis"] = [{"message_id": "later", "quote": "Later report."}]
        with pytest.raises(ValueError, match=r"^OBLIGATION_BASIS_NOT_YET_VISIBLE$"):
            compose_obligation_trace(contract, observations)
        row["basis"] = [] if index == 3 else [{"message_id": "message", "quote": "保存计划。"}]


@pytest.mark.parametrize(("change", "reason"), [
    ("case", "DUPLICATE_OBLIGATION_CASE"),
    ("message", "DUPLICATE_OBLIGATION_MESSAGE"),
    ("obligation", "DUPLICATE_OBLIGATION_ID"),
    ("observation", "DUPLICATE_OBLIGATION_OBSERVATION"),
    ("foreign-case", "DANGLING_OBLIGATION_OBSERVATION"),
    ("foreign-obligation", "DANGLING_OBLIGATION_OBSERVATION"),
    ("foreign-target", "DANGLING_OBLIGATION_MESSAGE"),
    ("unhashable-target", "INVALID_OBLIGATION_TRACE_TEXT"),
    ("quote", "OBLIGATION_BASIS_NOT_EXACT_VISIBLE_QUOTE"),
    ("basis", "OBLIGATION_REQUIRES_VISIBLE_BASIS"),
    ("diagnostic", "DIAGNOSTIC_CANNOT_BE_TASK_FAILING"),
    ("stage", "INVALID_OBLIGATION_STAGE_VALUE"),
    ("hash", "INVALID_OBLIGATION_EVIDENCE_HASH"),
    ("version", "INVALID_OBLIGATION_TRACE_VERSION"),
    ("runtime", "OBLIGATION_CONTRACT_MUST_BE_OFFLINE"),
])
def test_duplicates_dangling_hidden_obligations_and_invalid_shapes_are_rejected(
    change: str, reason: str,
) -> None:
    contract, observations = _inputs()
    case = contract["cases"][0]
    row = case["obligations"][0]
    if change in {"case", "message", "obligation", "observation"}:
        rows = (contract["cases"] if change == "case" else case["messages"]
                if change == "message" else case["obligations"] if change == "obligation"
                else observations["observations"])
        rows.append(copy.deepcopy(rows[0]))
    elif change in {"foreign-case", "foreign-obligation"}:
        observations["observations"][0][
            "case_id" if change == "foreign-case" else "obligation_id"] = "foreign"
    elif change in {"foreign-target", "unhashable-target"}:
        row["target_message_id"] = "foreign" if change == "foreign-target" else []
    elif change == "quote":
        row["basis"][0]["quote"] = "保存 计划"  # Not a contiguous original quote.
    elif change == "basis":
        row["basis"] = []
    elif change == "diagnostic":
        case["obligations"][3]["task_failing"] = True
    elif change == "stage":
        observations["observations"][0]["answer_contains"] = "inferred-pass"
    elif change == "hash":
        observations["observations"][0]["evidence"][0]["sha256"] = "g" * 64
    elif change == "version":
        contract["schema_version"] = True
    elif change == "runtime":
        contract["runtime_must_not_read"] = False
    before = copy.deepcopy((contract, observations))
    with pytest.raises(ValueError, match="^" + reason + "$"):
        compose_obligation_trace(contract, observations)
    assert (contract, observations) == before


def test_module_cli_writes_only_output_and_refuses_input_aliases(tmp_path: Path) -> None:
    contract, observations = _inputs()
    paths = [tmp_path / name for name in ("contract.json", "observations.json", "output.json")]
    for path, value in zip(paths, (contract, observations), strict=False):
        path.write_text(json.dumps(value, ensure_ascii=False))
    before = [path.read_bytes() for path in paths[:2]]
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    result = subprocess.run([sys.executable, "-m", "milai_lab.analysis.obligation_trace",  # noqa: S603 - Fixed module and synthetic input paths.
        "--contract", str(paths[0]), "--observations", str(paths[1]), "--output", str(paths[2])],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(paths[2].read_text()) == compose_obligation_trace(contract, observations)
    assert [path.read_bytes() for path in paths[:2]] == before
    with pytest.raises(ValueError, match="OUTPUT_CANNOT_REPLACE_INPUT"):
        main(["--contract", str(paths[0]), "--observations", str(paths[1]),
              "--output", str(paths[0])])
    alias = tmp_path / "alias.json"
    os.link(paths[1], alias)
    with pytest.raises(ValueError, match="OUTPUT_CANNOT_REPLACE_INPUT"):
        main(["--contract", str(paths[0]), "--observations", str(paths[1]), "--output", str(alias)])
