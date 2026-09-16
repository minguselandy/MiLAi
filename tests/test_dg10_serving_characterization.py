from __future__ import annotations

from scripts import run_dg10_serving_characterization as serving


def _result(index: int, latency: float, ttft: float) -> serving.RequestResult:
    return serving.RequestResult(
        tier="T0",
        concurrency=1,
        request_index=index,
        case_id=f"case-{index}",
        success=True,
        latency_ms=latency,
        ttft_ms=ttft,
        input_tokens=100,
        output_tokens=11,
        native_request_id=f"chatcmpl-test-{index}",
        finish_reason="stop",
        model_rounds=1,
        mcp_rounds=0,
        output_sha256="a" * 64,
        failure_type=None,
        raw={"output": "raw forbidden output"},
    )


def test_cell_metrics_report_latency_ttft_tpot_and_native_denominators() -> None:
    results = [_result(index, 100.0 + index, 20.0 + index) for index in range(8)]
    metrics = serving._cell_metrics(
        results,
        2.0,
        [],
        {"status": "AVAILABLE", "running": 0.0},
        {"status": "AVAILABLE", "running": 0.0},
    )
    assert metrics["request_count"] == 8
    assert metrics["success_count"] == 8
    assert metrics["failure_count"] == 0
    assert metrics["request_throughput_per_second"] == 4.0
    assert metrics["latency_ms"]["p95"] == 106.0
    assert metrics["ttft_ms"]["availability"] == "NATIVE_STREAMING"
    assert metrics["tpot_or_mean_itl_ms"]["mean"] == 8.0
    assert metrics["native_telemetry"]["event_count"] == 0


def test_workload_is_eight_dev_cases_with_ability_coverage() -> None:
    cases, dataset = serving._workload_cases(serving.mcp_smoke.DEFAULT_LONGMEMEVAL_ROOT)
    assert len(cases) == 8
    assert len({case.case_id for case in cases}) == 8
    assert len({case.category for case in cases}) == 6
    assert dataset["selected_dev_case_count"] == 50


def test_t2_prompt_forbids_tool_use_and_keeps_raw_question_out_of_public_hashing() -> None:
    cases, _dataset = serving._workload_cases(
        serving.mcp_smoke.DEFAULT_LONGMEMEVAL_ROOT
    )
    prompt = serving._t2_prompt(cases[0])
    assert "6 multiplied by 7" in prompt
    assert "neutral serving padding" in prompt
    assert cases[0].question not in prompt
    assert prompt.endswith("x" * len(cases[0].question))
