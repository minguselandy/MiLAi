from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from scripts import dg10_bfcl_multiturn_safety as safety
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_multiturn_generation_worker as worker
from scripts import run_dg10_bfcl_prompt_capability_probe as prompt_probe


class _EmptyListClient:
    def __init__(self) -> None:
        self.tokenizer_requests = 0
        self.completion_requests = 0
        self.identity_evidence = {"identity_status": "FROZEN_TEST_FIXTURE"}

    def complete(
        self, messages: Any, *, request_key: str
    ) -> prompt_probe.PromptCompletion:
        self.tokenizer_requests += 1
        self.completion_requests += 1
        assert request_key.endswith(":0:0")
        assert messages[-1] == {"role": "user", "content": "finish without a call"}
        return prompt_probe.PromptCompletion(
            native_request_id="chatcmpl-worker-fixture-0001",
            text="[]",
            usage={"input_tokens": 100, "output_tokens": 1},
            latency_ms=1.0,
            native_receipt_sha256="1" * 64,
            response_sha256="2" * 64,
        )


def test_generation_worker_completes_explicit_empty_turn_and_journals(
    tmp_path: Path,
) -> None:
    case_id = "bfcl_v4:multi_turn_base_fixture"
    test_entry = {
        "id": "multi_turn_base_fixture",
        "initial_config": {},
        "involved_classes": ["MathAPI"],
        "function": [{"name": "calculate", "parameters": {}}],
        "question": [[{"role": "user", "content": "finish without a call"}]],
    }
    schedule = safety.build_case_turn_schedule(
        test_entry,
        (
            "{functions}\nI have updated some more functions you can choose from. "
            "What about now?"
        ),
    )
    records = [
        {"case_id": case_id, "test_entry": test_entry, "turn_schedule": schedule}
    ]
    records.extend(
        {
            "case_id": f"bfcl_v4:dummy_{index}",
            "test_entry": {},
            "turn_schedule": {},
        }
        for index in range(79)
    )
    bundle = {
        "schema": "milai.dg10.bfcl-multiturn-label-free-generation-bundle.v1",
        "candidate": "candidate.12",
        "selected_case_count": 80,
        "test_material_present": False,
        "development_answer_labels_present": False,
        "population": {"official_population_helper_invocation_count": 1},
        "records": records,
    }
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    journal: list[dict[str, Any]] = []
    executor_calls = 0

    def executor(_calls: Any) -> list[str]:
        nonlocal executor_calls
        executor_calls += 1
        return []

    client = _EmptyListClient()
    result = worker.run_case(
        bundle_path=bundle_path,
        case_id=case_id,
        bfcl_root=bfcl_contract.DEFAULT_BFCL_ROOT,
        client=client,
        journal_append=journal.append,
        executor_override=executor,
    )

    assert result["status"] == "GENERATION_COMPLETE"
    assert result["generation_success"] is True
    assert result["turns_completed"] == 1
    assert result["native_model_requests"] == 1
    assert result["unique_native_request_ids"] == 1
    assert result["decoded_execution_calls_by_turn"] == [[[]]]
    assert executor_calls == 0
    assert len(journal) == 1
    assert journal[0]["outcome"]["status"] == (
        "TURN_COMPLETE_EXPLICIT_EMPTY_LIST"
    )


class _VerifiedClientFixture:
    base_url = "http://127.0.0.1:7860"
    max_model_len = 100
    identity_evidence: ClassVar[dict[str, str]] = {
        "identity_status": "FROZEN_TEST_FIXTURE"
    }


def test_generation_client_preserves_terminal_length_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker.dev_smoke,
        "LocalVllmClient",
        lambda *_args, **_kwargs: _VerifiedClientFixture(),
    )
    monkeypatch.setattr(worker.vllm_local_ab, "_tokenize", lambda *_args, **_kwargs: 5)
    response = {
        "id": "chatcmpl-generation-fixture",
        "model": worker.dev_smoke.MODEL_ID,
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": "[calculate(value=", "tool_calls": []},
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 512, "total_tokens": 517},
    }
    monkeypatch.setattr(
        worker.vllm_local_ab,
        "_post_json",
        lambda *_args, **_kwargs: (response, {"x-request-id": "fixture-header"}),
    )
    client = worker.GenerationLocalClient(
        "http://127.0.0.1:7860", Path("identity.json"), 10.0
    )

    completion = client.complete(
        [{"role": "user", "content": "fixture"}], request_key="fixture"
    )

    assert completion.finish_reason == "length"
    assert completion.native_request_id == "chatcmpl-generation-fixture"
    assert completion.usage["output_tokens"] == 512
    assert client.completion_requests == 1


def test_generation_client_fails_context_before_completion_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker.dev_smoke,
        "LocalVllmClient",
        lambda *_args, **_kwargs: _VerifiedClientFixture(),
    )
    monkeypatch.setattr(
        worker.vllm_local_ab, "_tokenize", lambda *_args, **_kwargs: 101
    )
    completion_called = False

    def post(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal completion_called
        completion_called = True
        raise AssertionError("completion must not be sent")

    monkeypatch.setattr(worker.vllm_local_ab, "_post_json", post)
    client = worker.GenerationLocalClient(
        "http://127.0.0.1:7860", Path("identity.json"), 10.0
    )

    with pytest.raises(worker.GenerationStepError) as caught:
        client.complete(
            [{"role": "user", "content": "fixture"}], request_key="fixture"
        )

    assert caught.value.code == "PROMPT_CONTEXT_LIMIT_PRE_REQUEST"
    assert caught.value.model_request_sent is False
    assert client.completion_requests == 0
    assert completion_called is False


def test_worker_validates_frozen_dynamic_prompt_across_sorted_json_order() -> None:
    test_entry = {
        "function": [{"name": "initial_tool", "description": "initial"}],
        "missed_function": {
            "0": [
                {
                    "name": "revealed_tool",
                    "description": "revealed",
                    "parameters": {"type": "dict"},
                }
            ]
        },
        "question": [[]],
    }
    template = (
        "{functions}\nI have updated some more functions you can choose from. "
        "What about now?"
    )
    frozen = safety.build_case_turn_schedule(test_entry, template)
    reloaded = json.loads(json.dumps(test_entry, sort_keys=True))

    validated = worker._validated_frozen_schedule(reloaded, frozen)

    assert validated == frozen
    assert validated["turns"][0]["revealed_function_names"] == ["revealed_tool"]
