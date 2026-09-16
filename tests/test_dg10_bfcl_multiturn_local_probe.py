from __future__ import annotations

import json
from typing import Any

from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_multiturn_local_probe as local_probe
from scripts import run_dg10_bfcl_prompt_capability_probe as prior_probe


class _FakeClient:
    def __init__(self, *, unsafe_no_call: bool = False) -> None:
        self.tokenizer_requests = 0
        self.completion_requests = 0
        self.unsafe_no_call = unsafe_no_call
        self.identity_evidence = {"identity_status": "FROZEN_TEST_FIXTURE"}

    def complete(
        self, messages: Any, *, request_key: str
    ) -> prior_probe.PromptCompletion:
        self.tokenizer_requests += 1
        self.completion_requests += 1
        assert messages[0]["content"].endswith(
            "or nested function calls."
        )
        outputs = {
            "select_then_empty:0": (
                "[fetch_temperature(city='Zephyr-8', unit='celsius')]"
            ),
            "select_then_empty:1": "[]",
            "explicit_no_call:0": "[]",
            "parallel_then_empty:0": (
                "[sum_values(values=[2, 5, 8]), "
                "store_profile(profile={'name': 'Probe', 'active': True})]"
            ),
            "parallel_then_empty:1": "[]",
            "two_execution_steps_then_empty:0": (
                "[inspect_inventory(item_id='widget-syn-10')]"
            ),
            "two_execution_steps_then_empty:1": (
                "[reserve_inventory(item_id='widget-syn-10', quantity=2, "
                "authorization={'code': 'AUTH-SYN-8'})]"
            ),
            "two_execution_steps_then_empty:2": "[]",
        }
        key = next(item for item in outputs if item in request_key)
        text = outputs[key]
        if self.unsafe_no_call and key == "explicit_no_call:0":
            text = "READY"
        index = self.completion_requests
        return prior_probe.PromptCompletion(
            native_request_id=f"chatcmpl-strict-fixture-{index:04d}",
            text=text,
            usage={"input_tokens": 100 + index, "output_tokens": 10},
            latency_ms=float(index),
            native_receipt_sha256=f"{index:064x}",
            response_sha256=f"{index + 20:064x}",
        )


def test_strict_local_probe_passes_eight_rounds_with_explicit_empty_lists() -> None:
    client = _FakeClient()

    report, sidecar = local_probe.run_probe(
        contract_path=local_probe.DEFAULT_CONTRACT,
        bfcl_root=bfcl_contract.DEFAULT_BFCL_ROOT,
        client=client,
    )

    assert report["status"] == "STRICT_SYNTHETIC_LOCAL_VLLM_PROBE_PASS"
    assert report["aggregates"]["dialogues_passed"] == 4
    assert report["aggregates"]["model_rounds_executed"] == 8
    assert report["local_vllm_requests"] == 8
    assert report["local_tokenizer_requests"] == 8
    assert report["retry_model_calls"] == 0
    assert report["hidden_or_extra_model_calls"] == 0
    assert report["benchmark_material_opened_by_probe"] is False
    assert report["bfcl_dev_answer_labels_opened"] is False
    assert report["bfcl_test_labels_or_outputs_opened"] is False
    assert report["aggregates"]["safety_failure_dialogues"] == 0
    assert all(item["oracle_pass"] for item in report["records"])
    assert len(sidecar["records"]) == 4
    encoded = json.dumps(report)
    assert "Zephyr-8" not in encoded
    assert "AUTH-SYN-8" not in encoded


def test_strict_local_probe_rejects_old_ready_no_call_without_execution() -> None:
    client = _FakeClient(unsafe_no_call=True)

    report, _sidecar = local_probe.run_probe(
        contract_path=local_probe.DEFAULT_CONTRACT,
        bfcl_root=bfcl_contract.DEFAULT_BFCL_ROOT,
        client=client,
    )

    assert report["status"] == "STRICT_SYNTHETIC_LOCAL_VLLM_PROBE_FAIL"
    no_call = next(
        item for item in report["records"] if item["probe_id"] == "explicit_no_call"
    )
    step = no_call["steps"][0]
    assert step["failure_code"] == "RAW_EXPLICIT_LIST_REQUIRED"
    assert step["execution_permitted"] is False
    assert step["tool_results_emitted"] is False
    assert report["aggregates"]["safety_failure_dialogues"] == 1
