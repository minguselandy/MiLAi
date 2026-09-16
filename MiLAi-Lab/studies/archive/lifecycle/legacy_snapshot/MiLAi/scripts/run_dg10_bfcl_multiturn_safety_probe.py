from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_bfcl_multiturn_safety as safety
from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_multiturn_contract as contract
from scripts import run_dg10_bfcl_prompt_capability_probe as prior_probe

DATE = "2026-08-21"
CANDIDATE = "candidate.1"
DEFAULT_CONTRACT = contract.DEFAULT_OUTPUT
DEFAULT_OUTPUT = (
    contract.ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-safety-probe-{CANDIDATE}-{DATE}.json"
)


class MultiTurnSafetyProbeError(RuntimeError):
    pass


def _load_contract(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MultiTurnSafetyProbeError(f"invalid safety contract: {path}") from exc
    if (
        not isinstance(report, dict)
        or report.get("schema") != "milai.dg10.bfcl-multiturn-safety-contract.v1"
        or report.get("candidate") != "candidate.7"
        or report.get("status")
        != "STATIC_NO_LABEL_SAFETY_CLOSURE_PASS_PROBES_NOT_RUN"
        or report.get("test_access_authorized") is not False
        or report.get("bfcl_dev_answer_labels_opened") is not False
        or report.get("bfcl_test_labels_or_outputs_opened") is not False
        or report.get("gate_results", {}).get("static_no_label_closure") != "PASS"
        or report.get("repo_external_generation_bundle", {}).get("status")
        != "WRITTEN_HASH_BOUND"
    ):
        raise MultiTurnSafetyProbeError("safety contract boundary mismatch")
    closure = report.get("local_harness_byte_closure", {})
    expected = {
        "safety_gate": contract.ROOT / "scripts/dg10_bfcl_multiturn_safety.py",
        "contract_builder": (
            contract.ROOT / "scripts/run_dg10_bfcl_multiturn_contract.py"
        ),
        "offline_scripted_probe": Path(__file__).resolve(),
    }
    for key, source in expected.items():
        if closure.get(key, {}).get("sha256") != dev_smoke._sha256_file(source):
            raise MultiTurnSafetyProbeError(f"local closure drift: {key}")
    return report


def _expect(
    records: list[dict[str, Any]],
    *,
    case_id: str,
    raw: str,
    exposed: set[str],
    decoder: Callable[[str], Any],
    expected_code: str | None,
) -> None:
    try:
        result = safety.attest_dual_gate(raw, exposed, decoder)
    except safety.SafetyGateError as exc:
        if expected_code is None or exc.code != expected_code:
            raise MultiTurnSafetyProbeError(
                f"unexpected result for {case_id}: {exc.code}, expected {expected_code}"
            ) from exc
        records.append(
            {
                "case_id": case_id,
                "expected": expected_code,
                "observed": exc.code,
                "pass": True,
                "raw_sha256": dev_smoke._sha256_bytes(raw.encode("utf-8")),
            }
        )
        return
    if expected_code is not None:
        raise MultiTurnSafetyProbeError(
            f"unsafe corpus case unexpectedly passed: {case_id}"
        )
    records.append(
        {
            "case_id": case_id,
            "expected": "PASS",
            "observed": "PASS",
            "pass": True,
            "call_count": len(result.execution_calls),
            "raw_sha256": result.raw_response_sha256,
        }
    )


def _offline_corpus(official_decoder: Callable[[str], Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    exposed = {"foo", "bar"}
    official_cases = (
        ("safe_empty", "[]", None),
        ("safe_keyword", "[foo(value=3)]", None),
        (
            "safe_parallel_nested",
            (
                "[foo(profile={'name':'Probe','active':True}), "
                "bar(values=[1, -2, 3.5], point=(4, 5), empty=None)]"
            ),
            None,
        ),
        ("reject_old_ready_no_call", "READY", "RAW_EXPLICIT_LIST_REQUIRED"),
        ("reject_bare_call", "foo(value=3)", "RAW_EXPLICIT_LIST_REQUIRED"),
        ("reject_top_tuple", "(foo(value=3),)", "RAW_EXPLICIT_LIST_REQUIRED"),
        ("reject_prose", "calls: [foo(value=3)]", "RAW_EXPLICIT_LIST_REQUIRED"),
        (
            "reject_fence",
            "```python\n[foo(value=3)]\n```",
            "RAW_EXPLICIT_LIST_REQUIRED",
        ),
        ("reject_comment", "[foo(value=3) # hidden\n]", "RAW_COMMENT_FORBIDDEN"),
        ("reject_positional", "[foo(3)]", "POSITIONAL_ARGUMENT_FORBIDDEN"),
        ("reject_attribute", "[obj.foo(value=3)]", "BARE_FUNCTION_NAME_REQUIRED"),
        ("reject_unknown", "[unknown(value=3)]", "FUNCTION_NOT_EXPOSED"),
        ("reject_duplicate_kw", "[foo(value=3, value=4)]", "DUPLICATE_KEYWORD"),
        ("reject_kw_unpack", "[foo(**{'value':3})]", "KEYWORD_UNPACK_FORBIDDEN"),
        ("reject_name_value", "[foo(value=other)]", "NON_LITERAL_ARGUMENT"),
        ("reject_nested_call", "[foo(value=bar(x=1))]", "NON_LITERAL_ARGUMENT"),
        ("reject_subscript", "[foo(value=items[0])]", "NON_LITERAL_ARGUMENT"),
        ("reject_binop", "[foo(value=1+2)]", "NON_LITERAL_ARGUMENT"),
        ("reject_lambda", "[foo(value=lambda: 1)]", "NON_LITERAL_ARGUMENT"),
        ("reject_comprehension", "[foo(value=[x for x in []])]", "NON_LITERAL_ARGUMENT"),
        ("reject_starred", "[foo(value=[*[1]])]", "NON_LITERAL_ARGUMENT"),
        ("reject_fstring", "[foo(value=f'{3}')]", "NON_LITERAL_ARGUMENT"),
        ("reject_set", "[foo(value={1, 2})]", "NON_LITERAL_ARGUMENT"),
        ("reject_bytes", "[foo(value=b'x')]", "UNSUPPORTED_CONSTANT"),
        ("reject_complex", "[foo(value=1j)]", "UNSUPPORTED_CONSTANT"),
        ("reject_ellipsis", "[foo(value=...)]", "UNSUPPORTED_CONSTANT"),
        (
            "reject_dict_unpack",
            "[foo(value={'x':1, **{'y':2}})]",
            "DICT_UNPACK_FORBIDDEN",
        ),
        (
            "reject_duplicate_dict_key",
            "[foo(value={'x':1, 'x':2})]",
            "DUPLICATE_DICT_KEY",
        ),
        ("reject_unary_plus", "[foo(value=+3)]", "NON_LITERAL_ARGUMENT"),
    )
    for case_id, raw, expected in official_cases:
        _expect(
            records,
            case_id=case_id,
            raw=raw,
            exposed=exposed,
            decoder=official_decoder,
            expected_code=expected,
        )
    injected_decoder_cases: tuple[
        tuple[str, str, Callable[[str], Any], str], ...
    ] = (
        (
            "post_decode_attribute",
            "[foo(value=3)]",
            lambda _raw: ["obj.foo(value=3)"],
            "BARE_FUNCTION_NAME_REQUIRED",
        ),
        (
            "post_decode_positional",
            "[foo(value=3)]",
            lambda _raw: ["foo(3)"],
            "POSITIONAL_ARGUMENT_FORBIDDEN",
        ),
        (
            "post_decode_nested_call",
            "[foo(value=3)]",
            lambda _raw: ["foo(value=bar(x=3))"],
            "NON_LITERAL_ARGUMENT",
        ),
        (
            "post_decode_type_change",
            "[foo(value=3)]",
            lambda _raw: ["foo(value=3.0)"],
            "RAW_DECODED_CANONICAL_MISMATCH",
        ),
        (
            "post_decode_list_tuple_change",
            "[foo(value=[1, 2])]",
            lambda _raw: ["foo(value=(1, 2))"],
            "RAW_DECODED_CANONICAL_MISMATCH",
        ),
        (
            "post_decode_non_list",
            "[foo(value=3)]",
            lambda _raw: "foo(value=3)",
            "DECODED_LIST_OF_STRINGS_REQUIRED",
        ),
        (
            "post_decode_exception",
            "[foo(value=3)]",
            lambda _raw: (_ for _ in ()).throw(ValueError("synthetic")),
            "OFFICIAL_DECODER_FAILURE",
        ),
    )
    for case_id, raw, decoder, expected in injected_decoder_cases:
        _expect(
            records,
            case_id=case_id,
            raw=raw,
            exposed=exposed,
            decoder=decoder,
            expected_code=expected,
        )
    return records


def _scripted_state_machine(
    official_decoder: Callable[[str], Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    executed: list[tuple[str, ...]] = []

    def executor(calls: Any) -> list[str]:
        executed.append(tuple(calls))
        return [f"synthetic-result-{index}" for index, _call in enumerate(calls)]

    machine = safety.SafeTurnStateMachine(
        frozenset({"foo"}), official_decoder, executor
    )
    first = machine.process_native_step(
        "[foo(value=1)]", {"native_request_id": "synthetic-valid-1"}
    )
    final = machine.process_native_step(
        "[]", {"native_request_id": "synthetic-valid-2"}
    )
    if (
        first["status"] != "EXECUTED_ATTESTED_CALLS"
        or not first["tool_results_emitted"]
        or final["status"] != "TURN_COMPLETE_EXPLICIT_EMPTY_LIST"
        or not machine.complete
        or len(executed) != 1
    ):
        raise MultiTurnSafetyProbeError("valid state-machine path failed")
    records.append({"case_id": "valid_execute_then_empty", "pass": True})

    executed_before = len(executed)
    unsafe = safety.SafeTurnStateMachine(
        frozenset({"foo"}), official_decoder, executor
    )
    unsafe_record = unsafe.process_native_step(
        "READY", {"native_request_id": "synthetic-unsafe"}
    )
    if (
        unsafe_record["status"] != "SAFETY_GATE_FAILURE"
        or unsafe_record["tool_results_emitted"]
        or len(executed) != executed_before
        or unsafe.failure_code != "RAW_EXPLICIT_LIST_REQUIRED"
    ):
        raise MultiTurnSafetyProbeError("unsafe response reached executor")
    records.append({"case_id": "unsafe_no_executor_no_tool_result", "pass": True})

    mismatch = safety.SafeTurnStateMachine(
        frozenset({"foo"}), lambda _raw: ["foo(value=1.0)"], executor
    )
    mismatch_record = mismatch.process_native_step(
        "[foo(value=1)]", {"native_request_id": "synthetic-mismatch"}
    )
    if (
        mismatch.failure_code != "RAW_DECODED_CANONICAL_MISMATCH"
        or mismatch_record["execution_permitted"]
        or len(executed) != executed_before
    ):
        raise MultiTurnSafetyProbeError("decoder mismatch reached executor")
    records.append({"case_id": "decoder_mismatch_no_executor", "pass": True})

    boundary = safety.SafeTurnStateMachine(
        frozenset({"foo"}), official_decoder, executor, max_execution_steps=2
    )
    boundary.process_native_step(
        "[foo(value=1)]", {"native_request_id": "synthetic-boundary-1"}
    )
    boundary.process_native_step(
        "[foo(value=2)]", {"native_request_id": "synthetic-boundary-2"}
    )
    executions_at_limit = len(executed)
    boundary_record = boundary.process_native_step(
        "[foo(value=3)]", {"native_request_id": "synthetic-boundary-3"}
    )
    if (
        boundary_record["status"] != "STEP_LIMIT_BOUNDARY_FORCE_QUIT"
        or boundary_record["tool_results_emitted"]
        or boundary_record["execution_permitted"]
        or len(executed) != executions_at_limit
        or len(boundary.records) != 3
    ):
        raise MultiTurnSafetyProbeError("step-limit boundary was executed or lost")
    records.append({"case_id": "n_plus_1_preserved_never_executed", "pass": True})

    malformed = safety.SafeTurnStateMachine(
        frozenset({"foo"}), official_decoder, lambda _calls: []
    )
    malformed_record = malformed.process_native_step(
        "[foo(value=1)]", {"native_request_id": "synthetic-malformed"}
    )
    if (
        malformed.failure_code != "EXECUTOR_RESULT_SHAPE_FAILURE"
        or malformed_record["tool_results_emitted"]
    ):
        raise MultiTurnSafetyProbeError("malformed executor result was emitted")
    records.append({"case_id": "malformed_executor_result_latched", "pass": True})

    populated_case = {
        "function": [{"name": "initial_tool"}],
        "missed_function": {"1": [{"name": "revealed_tool"}]},
        "question": [[{"role": "user", "content": "first"}], []],
    }
    schedule = safety.build_case_turn_schedule(
        populated_case,
        "{functions}\nI have updated some more functions you can choose from. What about now?",
    )
    if (
        schedule["turns"][0]["exposed_function_names"] != ["initial_tool"]
        or schedule["turns"][1]["exposed_function_names"]
        != ["initial_tool", "revealed_tool"]
        or schedule["turns"][1]["revealed_function_names"] != ["revealed_tool"]
        or schedule["turns"][1]["effective_messages"][0]["content"]
        != (
            "[{'name': 'revealed_tool'}]\nI have updated some more functions you "
            "can choose from. What about now?"
        )
    ):
        raise MultiTurnSafetyProbeError("cumulative reveal schedule drifted")
    records.append({"case_id": "exact_cumulative_missed_function_reveal", "pass": True})
    return records


def run_probe(
    *,
    contract_path: Path = DEFAULT_CONTRACT,
    bfcl_root: Path = bfcl_contract.DEFAULT_BFCL_ROOT,
) -> dict[str, Any]:
    frozen_contract = _load_contract(contract_path.resolve())
    official_utils, decoder_sha256 = prior_probe._load_official_prompt_utils(
        bfcl_root.resolve()
    )
    expected_decoder_sha256 = frozen_contract["official_upstream_byte_closure"][
        "core"
    ]["prompt_decoder_and_serializer"]["sha256"]
    if decoder_sha256 != expected_decoder_sha256:
        raise MultiTurnSafetyProbeError("official decoder bytes drifted")
    official_decoder = official_utils.default_decode_execute_prompting
    offline = _offline_corpus(official_decoder)
    scripted = _scripted_state_machine(official_decoder)
    if not all(item["pass"] for item in offline + scripted):
        raise MultiTurnSafetyProbeError("safety probe contains a failed record")
    return {
        "schema": "milai.dg10.bfcl-multiturn-safety-probe.v1",
        "candidate": CANDIDATE,
        "date": DATE,
        "status": "OFFLINE_AST_AND_SCRIPTED_STATE_MACHINE_PASS",
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "local_vllm_requests": 0,
        "benchmark_material_opened_by_probe": False,
        "bfcl_dev_answer_labels_opened": False,
        "bfcl_test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "inputs": {
            "safety_contract_sha256": dev_smoke._sha256_file(
                contract_path.resolve()
            ),
            "official_prompt_decoder_sha256": decoder_sha256,
            "safety_gate_sha256": dev_smoke._sha256_file(
                contract.ROOT / "scripts/dg10_bfcl_multiturn_safety.py"
            ),
            "probe_script_sha256": dev_smoke._sha256_file(Path(__file__).resolve()),
        },
        "aggregates": {
            "offline_corpus_count": len(offline),
            "offline_corpus_passed": sum(item["pass"] for item in offline),
            "scripted_state_machine_count": len(scripted),
            "scripted_state_machine_passed": sum(item["pass"] for item in scripted),
            "model_rounds": 0,
            "executor_invocations_from_rejected_responses": 0,
            "tool_results_emitted_from_rejected_responses": 0,
        },
        "required_observations": {
            "old_READY_no_call_is_failure": True,
            "explicit_empty_list_is_valid_no_call": True,
            "raw_gate_precedes_official_decoder": True,
            "post_decoder_gate_exercised": True,
            "typed_canonical_mismatch_rejected": True,
            "n_plus_1_native_response_preserved": True,
            "n_plus_1_native_response_executed": False,
            "missed_function_exposure_cumulative": True,
        },
        "offline_records": offline,
        "scripted_records": scripted,
        "gate_results": {
            "static_no_label_closure": "PASS_BOUND",
            "offline_ast_corpus": "PASS",
            "scripted_state_machine": "PASS",
            "revised_synthetic_local_vllm": "NOT_RUN",
            "BMG-03": "NO_GO_REVISED_LOCAL_MODEL_PROBE_AND_DEV_NOT_RUN",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
        },
        "known_limits": [
            "This probe uses synthetic strings and scripted executors only; it opens no benchmark labels and performs no model call.",
            "A revised strict-output local-vLLM synthetic probe is still required before the 80-case generation ledger may start.",
            "This is development harness evidence, not BFCL quality, native function calling, MCP transport, or formal CRG evidence.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the BFCL multi-turn offline safety corpus and state machine"
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run_probe(
        contract_path=args.contract,
        bfcl_root=args.bfcl_root,
    )
    report_raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), report_raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": dev_smoke._sha256_bytes(report_raw),
                "status": report["status"],
                "offline_corpus_count": report["aggregates"][
                    "offline_corpus_count"
                ],
                "scripted_state_machine_count": report["aggregates"][
                    "scripted_state_machine_count"
                ],
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
