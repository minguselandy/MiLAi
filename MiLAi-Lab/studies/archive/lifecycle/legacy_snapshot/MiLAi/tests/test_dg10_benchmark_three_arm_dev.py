from __future__ import annotations

from pathlib import Path

from scripts import run_dg10_benchmark_adapter_contract as adapter_contract
from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_benchmark_three_arm_dev as three_arm


def _case() -> dev_smoke.BenchmarkCase:
    return dev_smoke.BenchmarkCase(
        case_id="longmemeval:test-001",
        source_case_id="test-001",
        dataset="LONGMEMEVAL_CLEANED_500",
        category="single-session-user",
        question="raw forbidden question",
        answers=("raw forbidden answer",),
        sessions=(("session-1", "raw forbidden memory"),),
    )


def test_calibration_adapter_enforces_frozen_generation_parameters(
    tmp_path: Path,
) -> None:
    generated, identity = three_arm._materialize_calibration_adapter(tmp_path)
    source = generated.read_text(encoding="utf-8")
    assert 'payload["temperature"] = 0' in source
    assert 'payload["max_tokens"] = 256' in source
    assert 'payload["seed"] = 20260821' in source
    assert identity["enforced_max_output_tokens_per_native_call"] == 256
    assert identity["integration_adapter_bytes_changed"] is False
    assert identity["generated_adapter_sha256"] == three_arm._sha256_file(
        generated
    )
    compile(source, str(generated), "exec")


def test_record_has_exact_adapter_schema_and_keeps_raw_content_out_of_report() -> None:
    case = _case()
    native = three_arm._native_call(
        native_id="chatcmpl-test-0001",
        role="ANSWER",
        finish_reason="stop",
        input_tokens=100,
        output_tokens=10,
        latency_ms=1.0,
        receipt_sha256="a" * 64,
    )
    observation = three_arm.ArmObservation(
        case_id=case.case_id,
        arm="NO_MEMORY",
        raw_output="raw forbidden answer",
        prompt_sha256="b" * 64,
        native_calls=(native,),
        latency_ms=1.0,
        model_rounds=1,
        mcp_rounds=0,
        memory_context="",
        evidence_ids=(),
        trace={"retrieval": "NONE"},
        raw_trace={"messages": "raw forbidden question"},
    )
    report, raw = three_arm._record(case, observation, "run-test")
    assert set(report) == set(
        adapter_contract._adapter_output_schema()["required"]
    )
    assert report["answer_record"]["exact_match"] == 1
    assert "raw forbidden" not in str(report)
    assert "raw forbidden question" in str(raw)
    assert "raw forbidden answer" in str(raw)


def test_quality_delta_uses_normalized_f1_then_exact_match() -> None:
    aggregates = {
        "LONGMEMEVAL_CLEANED_500/NO_MEMORY": {
            "normalized_f1_mean": 0.2,
            "exact_match_mean": 0.1,
        },
        "LONGMEMEVAL_CLEANED_500/NAIVE_RAG": {
            "normalized_f1_mean": 0.3,
            "exact_match_mean": 0.0,
        },
        "LONGMEMEVAL_CLEANED_500/MILAI_MCP": {
            "normalized_f1_mean": 0.4,
            "exact_match_mean": 0.2,
        },
    }
    delta = three_arm._quality_delta(aggregates)
    assert delta["strongest_fixed_baseline"] == "NAIVE_RAG"
    assert delta["milai_minus_strongest_baseline"] == {
        "exact_match_mean": 0.2,
        "normalized_f1_mean": 0.1,
    }


def test_mcp_prompt_reuses_frozen_system_template_and_names_exact_arm() -> None:
    prompt = three_arm._mcp_prompt(_case(), "dg10benchtest001")
    assert adapter_contract._prompt_templates()["system_template"] in prompt
    assert "Arm: MILAI_MCP" in prompt
    assert "milai_recall exactly once" in prompt
