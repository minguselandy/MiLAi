from __future__ import annotations

import json
from typing import Any

from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_prompt_capability_probe as prompt_probe


class _FakeClient:
    def __init__(self, *, fail_multi_first: bool = False) -> None:
        self.tokenizer_requests = 0
        self.completion_requests = 0
        self.fail_multi_first = fail_multi_first
        self.identity_evidence = {"identity_status": "FROZEN_TEST_FIXTURE"}

    def complete(
        self,
        messages: Any,
        *,
        request_key: str,
    ) -> prompt_probe.PromptCompletion:
        self.tokenizer_requests += 1
        self.completion_requests += 1
        assert messages[0]["role"] == "system"
        outputs = {
            "select_one_of_two:0": (
                "fetch_temperature(city='Zephyr-7', unit='celsius')"
            ),
            "no_call:0": "READY",
            "parallel_two:0": (
                "[sum_values(values=[2, 5, 8]), "
                "store_profile(profile={'name': 'Probe', 'active': True})]"
            ),
            "multi_turn_tool_result:0": (
                "inspect_inventory(item_id='widget-syn-9')"
            ),
            "multi_turn_tool_result:1": (
                "reserve_inventory(item_id='widget-syn-9', quantity=2, "
                "authorization={'code': 'AUTH-SYN-7'})"
            ),
        }
        key = next(item for item in outputs if item in request_key)
        text = outputs[key]
        if self.fail_multi_first and key == "multi_turn_tool_result:0":
            text = "reserve_inventory(item_id='wrong', quantity=1, authorization={})"
        index = self.completion_requests
        return prompt_probe.PromptCompletion(
            native_request_id=f"chatcmpl-fixture-{index:04d}",
            text=text,
            usage={"input_tokens": 100 + index, "output_tokens": 10},
            latency_ms=float(index),
            native_receipt_sha256=f"{index:064x}",
            response_sha256=f"{index + 10:064x}",
        )


def test_prompt_probe_passes_all_frozen_synthetic_oracles() -> None:
    client = _FakeClient()
    report, sidecar = prompt_probe.run_probe(
        plan_path=prompt_probe.DEFAULT_PLAN,
        bfcl_root=bfcl_contract.DEFAULT_BFCL_ROOT,
        client=client,
    )

    assert report["status"].endswith("_PASS")
    assert report["aggregates"]["dialogues_passed"] == 4
    assert report["aggregates"]["model_rounds_executed"] == 5
    assert report["local_vllm_requests"] == 5
    assert report["local_tokenizer_requests"] == 5
    assert report["benchmark_material_opened_by_probe"] is False
    assert report["protocol"]["native_tools_field_present"] is False
    assert report["protocol"]["tool_choice_field_present"] is False
    assert report["external_provider_requests"] == 0
    assert all(item["oracle_pass"] for item in report["records"])
    encoded = json.dumps(report)
    assert "Zephyr-7" not in encoded
    assert "AUTH-SYN-7" not in encoded
    assert sidecar["records"][0]["user"].endswith("in celsius.")


def test_prompt_probe_skips_second_multi_turn_step_after_oracle_failure() -> None:
    client = _FakeClient(fail_multi_first=True)
    report, _sidecar = prompt_probe.run_probe(
        plan_path=prompt_probe.DEFAULT_PLAN,
        bfcl_root=bfcl_contract.DEFAULT_BFCL_ROOT,
        client=client,
    )

    assert report["status"].endswith("_FAIL")
    assert report["aggregates"]["dialogues_passed"] == 3
    assert report["aggregates"]["model_rounds_executed"] == 4
    multi = next(
        item for item in report["records"] if item["probe_id"] == "multi_turn_tool_result"
    )
    assert multi["steps"][1]["status"] == "SKIPPED_PREVIOUS_ORACLE_FAILURE"


def test_official_prompt_utils_execute_frozen_python_path() -> None:
    utils, digest = prompt_probe._load_official_prompt_utils(
        bfcl_contract.DEFAULT_BFCL_ROOT
    )

    assert digest == prompt_probe.dev_smoke._sha256_file(
        bfcl_contract.DEFAULT_BFCL_ROOT / "bfcl_eval/model_handler/utils.py"
    )
    assert utils.default_decode_ast_prompting("probe(value=3)") == [
        {"probe": {"value": 3}}
    ]
