from __future__ import annotations

import inspect

import pytest

from scripts import run_dg10_bfcl_multiturn_contract as contract


def _build_historical_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], dict[str, object]]:
    # candidate.12 is immutable historical evidence.  Rehydrate its already-bound
    # closure for pure contract assertions; the live-environment refusal is tested
    # separately and the historical freeze digest is deliberately unchanged.
    monkeypatch.setattr(
        contract,
        "_runtime_mpmath_closure",
        lambda: {
            "package": "mpmath",
            "version": "1.3.0",
            "source": "OFFICIAL_BFCL_PYPROJECT_PIN_OFFLINE_UV_CACHE",
            "package_path_class": "REPOSITORY_RUNTIME_VENV",
            "tree_file_count": 87,
            "tree_sha256": (
                "376efeae63abdfd9378ce98ddb38509387ba0237c82e8e70429ddea11089079b"
            ),
            "worker_environment_freeze_sha256": (
                "e21b21a1df79293faa2dcf1bca352a82d44f5910767f22b5e34d0b847661ec39"
            ),
        },
    )
    return contract.build_contract()


def test_multiturn_contract_builds_exact_label_free_80_case_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report, bundle = _build_historical_contract(monkeypatch)

    assert report["status"] == (
        "DEPENDENCY_REMEDIATION_FROZEN_FULL_RERUN_NOT_RUN"
    )
    assert report["selection"]["case_count"] == 80
    assert report["selection"]["category_counts"] == {
        "multi_turn_base": 20,
        "multi_turn_long_context": 20,
        "multi_turn_miss_func": 20,
        "multi_turn_miss_param": 20,
    }
    assert report["bfcl_dev_answer_labels_opened"] is False
    assert report["bfcl_test_labels_or_outputs_opened"] is False
    assert report["test_access_authorized"] is False
    assert report["population_contract"]["official_helper_invocation_count"] == 1
    assert report["dual_ast_gate_contract"][
        "explicit_empty_list_is_only_no_call_representation"
    ] is True
    assert report["gate_results"]["offline_ast_corpus"] == "PASS_BOUND"
    assert report["gate_results"]["scripted_state_machine"] == "PASS_BOUND"
    assert report["strict_synthetic_local_probe_contract"][
        "total_model_rounds"
    ] == 8
    assert report["strict_synthetic_local_probe_contract"]["status"] == "PASS_BOUND"
    assert report["gate_results"]["revised_synthetic_local_vllm"] == "PASS_BOUND"
    assert len(report["generation_execution_schedule"]["ordered_case_ids"]) == 80
    assert len(
        report["generation_execution_schedule"]["operational_prefix_case_ids"]
    ) == 4
    assert report["generation_execution_schedule"][
        "prior_attempt_local_model_requests"
    ] == 479
    assert report["worker_runtime_dependency_closure"]["version"] == "1.3.0"
    assert bundle["selected_case_count"] == 80
    assert bundle["development_answer_labels_present"] is False
    assert len(bundle["records"]) == 80
    assert len({item["case_id"] for item in bundle["records"]}) == 80
    assert contract._forbidden_label_key(bundle) is None


def test_multiturn_contract_freezes_exact_selected_backend_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report, _bundle = _build_historical_contract(monkeypatch)
    closure = report["official_upstream_byte_closure"]

    assert set(closure["function_docs"]) == set(
        contract.EXPECTED_SELECTED_CLASS_TO_DOC
    )
    assert set(closure["function_sources"]) == {
        *contract.EXPECTED_SELECTED_CLASS_TO_SOURCE,
        "_shared_long_context",
    }
    assert set(closure["core"]) >= {
        "base_handler",
        "base_oss_prompt_handler",
        "default_prompts_and_step_limit",
        "executable_backend_config",
        "multi_turn_checker_and_irrelevance_checker",
        "multi_turn_executor",
        "population_helper",
        "prompt_decoder_and_serializer",
    }


def test_multiturn_contract_schedules_cumulative_missed_function_reveals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _report, bundle = _build_historical_contract(monkeypatch)
    missed_records = [
        item
        for item in bundle["records"]
        if item["test_entry"].get("missed_function")
    ]

    assert len(missed_records) == 20
    for record in missed_records:
        schedule = record["turn_schedule"]
        previous: set[str] = set()
        revealed = 0
        for turn in schedule["turns"]:
            current = set(turn["exposed_function_names"])
            assert previous <= current
            previous = current
            revealed += len(turn["revealed_function_names"])
        assert revealed > 0


def test_historical_contract_refuses_a_different_live_worker_environment() -> None:
    source = inspect.getsource(contract._runtime_mpmath_closure)
    assert "e21b21a1df79293faa2dcf1bca352a82d44f5910767f22b5e34d0b847661ec39" in source
    with pytest.raises(contract.MultiTurnContractError, match="closure drifted"):
        contract._runtime_mpmath_closure()
