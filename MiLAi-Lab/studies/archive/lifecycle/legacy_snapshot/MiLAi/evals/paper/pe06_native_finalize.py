"""Validate and freeze PE06 native baseline readiness evidence."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.identity import sha256_file
from evals.paper.lme_v2_adapter import EXPECTED_BENCHMARK_COMMIT, EXPECTED_CANDIDATE_ID

ROOT = Path(__file__).resolve().parents[2]
METHOD_CONFIG = ROOT / "var/dg11/paper/method-configs/lme-v2.json"
PROTOCOL = ROOT / "evals/paper/experiment-protocol.yaml"
NATIVE_RAG_RESULT = (
    ROOT / "var/dg11/paper/runs/pe06-native-rag-smoke-20260824-003/result.json"
)
NATIVE_RAG_FAILURES = (
    ROOT
    / "var/dg11/paper/runs/pe06-native-rag-smoke-20260824-001/failure-disclosure.json",
    ROOT
    / "var/dg11/paper/runs/pe06-native-rag-smoke-20260824-002/failure-disclosure.json",
)
CONTROLLER_RUN = ROOT / "var/dg11/paper/runs/pe06-native-controller-smoke-20260824-001"
CONTROLLER_RESULT = CONTROLLER_RUN / "result.json"
DEFAULT_OUTPUT = CONTROLLER_RUN / "verification.json"
CANDIDATE_MANIFEST = ROOT / "var/dg11/freeze/candidate/candidate-manifest.json"
CANDIDATE_INVENTORY = ROOT / "var/dg11/final/candidate/inventory.json"
EXPECTED_CANDIDATE_MANIFEST_SHA256 = (
    "9812af51eeafac55e9ab250d37d6d4fe8217b73428b4543af74bbb7ad00cef5d"
)
EXPECTED_CANDIDATE_INVENTORY_SHA256 = (
    "b754b9cfed729192b02c9493c5cb3ff93a7961c72f440e5ddb358ef7785055bb"
)
EXPECTED_VLLM_IDENTITY_SHA256 = (
    "0463fff90754f54c887ed79e54b5db5593b1860cf593c4a89a66c1828eaa3f0e"
)
EXPECTED_TARGET_SCREENSHOT_SHA256 = (
    "2042d1bdfc5f6ae6f8c195a62195efee05897ac4023a339ed77d12e0f3994820"
)
EXPECTED_CONTROLLER_SOURCE = ROOT / "evals/paper/services/controller_gateway.py"
EXPECTED_EMBEDDING_SOURCE = ROOT / "evals/paper/services/embedding_server.py"
EXPECTED_NATIVE_RUNNER = ROOT / "evals/paper/runners/lme_v2_native.py"


class PE06NativeFinalizeError(RuntimeError):
    pass


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PE06NativeFinalizeError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise PE06NativeFinalizeError(f"expected JSON object: {path}")
    return value


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise PE06NativeFinalizeError("PE06 native verification is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _candidate_hashes() -> dict[str, str]:
    observed = {
        "inventory_sha256": sha256_file(CANDIDATE_INVENTORY),
        "manifest_sha256": sha256_file(CANDIDATE_MANIFEST),
    }
    expected = {
        "inventory_sha256": EXPECTED_CANDIDATE_INVENTORY_SHA256,
        "manifest_sha256": EXPECTED_CANDIDATE_MANIFEST_SHA256,
    }
    if observed != expected:
        raise PE06NativeFinalizeError("frozen candidate drifted")
    return observed


def _validate_failures() -> list[dict[str, str]]:
    expected_classes = (
        "OFFICIAL_MEMORY_REGISTRY_IMPORT_ORDER",
        "OPENAI_SDK_BASE64_EMBEDDING_ENCODING_UNSUPPORTED",
    )
    records = []
    for path, expected_class in zip(NATIVE_RAG_FAILURES, expected_classes):
        value = _object(path)
        if (
            value.get("schema") != "milai.dg11.pe06-native-rag-failure.v1"
            or value.get("status") != "FAIL_EXCLUDED"
            or value.get("result_use") != "EXCLUDED_DEVELOPMENT_SMOKE"
            or value.get("classification") != expected_class
            or value.get("candidate_id") != EXPECTED_CANDIDATE_ID
            or value.get("labels_accessed") is not False
            or value.get("paper_question_rows_read") != 0
        ):
            raise PE06NativeFinalizeError("native RAG failure disclosure drifted")
        records.append(
            {
                "classification": expected_class,
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256_file(path),
            }
        )
    return records


def _validate_native_rag(candidate: dict[str, str]) -> dict[str, Any]:
    value = _object(NATIVE_RAG_RESULT)
    contract = value.get("benchmark_contract")
    embedding = value.get("embedding_service")
    rag = value.get("rag")
    metrics = embedding.get("metrics") if isinstance(embedding, dict) else None
    item_records = rag.get("item_records") if isinstance(rag, dict) else None
    if (
        value.get("schema") != "milai.dg11.pe06-native-rag-smoke.v1"
        or value.get("status") != "PASS"
        or value.get("candidate_id") != EXPECTED_CANDIDATE_ID
        or value.get("candidate_before") != candidate
        or value.get("candidate_after") != candidate
        or value.get("labels_accessed") is not False
        or value.get("paper_question_rows_read") != 0
        or not isinstance(contract, dict)
        or contract.get("commit") != EXPECTED_BENCHMARK_COMMIT
        or contract.get("paper_data_opened") is not False
        or contract.get("question_rows_read") != 0
        or not isinstance(embedding, dict)
        or embedding.get("source_sha256") != sha256_file(EXPECTED_EMBEDDING_SOURCE)
        or not isinstance(metrics, dict)
        or metrics.get("request_count") != 4
        or metrics.get("item_count") != 5
        or not isinstance(rag, dict)
        or rag.get("embedding_dimensions") != 128
        or rag.get("selected_target_screenshot") is not True
        or not isinstance(item_records, list)
        or EXPECTED_TARGET_SCREENSHOT_SHA256
        not in {
            item.get("sha256")
            for item in item_records
            if isinstance(item, dict) and item.get("type") == "image"
        }
    ):
        raise PE06NativeFinalizeError("native raw RAG result drifted")
    identity = ROOT / str(embedding["identity"])
    if not identity.is_file() or sha256_file(identity) != embedding.get(
        "identity_sha256"
    ):
        raise PE06NativeFinalizeError("native raw RAG embedding identity drifted")
    return {
        "embedding_items": metrics["item_count"],
        "embedding_requests": metrics["request_count"],
        "result_sha256": sha256_file(NATIVE_RAG_RESULT),
        "target_screenshot_sha256": EXPECTED_TARGET_SCREENSHOT_SHA256,
    }


def _validate_controller_result(candidate: dict[str, str]) -> dict[str, Any]:
    value = _object(CONTROLLER_RESULT)
    contract = value.get("benchmark_contract")
    controller = value.get("controller")
    embedding = value.get("embedding")
    controller_metrics = (
        controller.get("metrics") if isinstance(controller, dict) else None
    )
    embedding_metrics = (
        embedding.get("metrics") if isinstance(embedding, dict) else None
    )
    methods = value.get("methods")
    vllm = value.get("vllm")
    runner = value.get("runner")
    if (
        value.get("schema") != "milai.dg11.pe06-native-controller-smoke.v1"
        or value.get("status") != "PASS"
        or value.get("candidate_id") != EXPECTED_CANDIDATE_ID
        or value.get("candidate_before") != candidate
        or value.get("candidate_after") != candidate
        or value.get("labels_accessed") is not False
        or value.get("paper_question_rows_read") != 0
        or value.get("service_process_limit") != 2
        or not isinstance(contract, dict)
        or contract.get("commit") != EXPECTED_BENCHMARK_COMMIT
        or contract.get("paper_data_opened") is not False
        or not isinstance(controller, dict)
        or controller.get("source_sha256") != sha256_file(EXPECTED_CONTROLLER_SOURCE)
        or not isinstance(controller_metrics, dict)
        or controller_metrics.get("request_count") != 8
        or controller_metrics.get("successful_count") != 8
        or controller_metrics.get("failed_count") != 0
        or controller_metrics.get("total_tokens") != 9115
        or not isinstance(embedding, dict)
        or embedding.get("source_sha256") != sha256_file(EXPECTED_EMBEDDING_SOURCE)
        or embedding.get("projection_dimensions") != 128
        or not isinstance(embedding_metrics, dict)
        or embedding_metrics.get("request_count") != 26
        or embedding_metrics.get("item_count") != 28
        or not isinstance(vllm, dict)
        or vllm.get("identity_sha256") != EXPECTED_VLLM_IDENTITY_SHA256
        or vllm.get("max_model_len") != 65536
        or vllm.get("vllm_lifecycle_mutated") is not False
        or not isinstance(runner, dict)
        or runner.get("sha256") != sha256_file(EXPECTED_NATIVE_RUNNER)
        or not isinstance(methods, dict)
        or set(methods) != {"rag_query_to_slice_notes", "agentrunbook_r"}
    ):
        raise PE06NativeFinalizeError("native controller result drifted")
    for name, method in methods.items():
        item_records = method.get("item_records") if isinstance(method, dict) else None
        dimensions = (
            method.get("embedding_dimensions") if isinstance(method, dict) else None
        )
        if (
            not isinstance(method, dict)
            or method.get("method") != name
            or method.get("paper_data_opened") is not False
            or method.get("question_rows_read") != 0
            or method.get("query_image_passed") is not True
            or method.get("selected_target_screenshot") is not True
            or not isinstance(dimensions, dict)
            or dimensions.get("raw_states") != 128
            or dimensions.get("procedure_notes") != 128
            or not isinstance(item_records, list)
            or EXPECTED_TARGET_SCREENSHOT_SHA256
            not in {
                item.get("sha256")
                for item in item_records
                if isinstance(item, dict) and item.get("type") == "image"
            }
        ):
            raise PE06NativeFinalizeError(f"native controller method drifted: {name}")
    identities = value.get("identities")
    if not isinstance(identities, dict):
        raise PE06NativeFinalizeError("native controller identities are absent")
    for record in identities.values():
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise PE06NativeFinalizeError(
                "native controller identity record is invalid"
            )
        path = ROOT / record["path"]
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            raise PE06NativeFinalizeError("native controller identity file drifted")
    for log in (CONTROLLER_RUN / "raw").glob("*.log"):
        if log.stat().st_size != 0:
            raise PE06NativeFinalizeError("native controller service log is nonempty")
    return {
        "controller_requests": controller_metrics["request_count"],
        "controller_tokens": controller_metrics["total_tokens"],
        "embedding_items": embedding_metrics["item_count"],
        "embedding_requests": embedding_metrics["request_count"],
        "methods": sorted(methods),
        "result_sha256": sha256_file(CONTROLLER_RESULT),
    }


def _validate_method_config() -> dict[str, Any]:
    value = _object(METHOD_CONFIG)
    common = value.get("common")
    methods = value.get("methods")
    evidence = value.get("smoke_evidence")
    if (
        value.get("status") != "READY_FOR_PAPER_FREEZE"
        or value.get("paper_labels_opened") is not False
        or not isinstance(common, dict)
        or common.get("memory_context_max_tokens") != 49152
        or common.get("reader_max_completion_tokens") != 8192
        or common.get("reader_max_concurrent_requests") != 2
        or common.get("prompt_build_max_workers") != 2
        or not isinstance(methods, dict)
        or methods.get("rag_query_to_slice_notes", {}).get("status")
        != "ADAPTER_SMOKE_PASS"
        or methods.get("AgentRunbook-R", {}).get("status") != "ADAPTER_SMOKE_PASS"
        or methods.get("AgentRunbook-C", {}).get("core_status")
        != "EXCLUDED_PRE_FREEZE_RESOURCE_CEILING"
        or methods.get("AgentRunbook-C", {}).get("maximum_codex_provider_calls") != 0
        or not isinstance(evidence, dict)
        or evidence.get("native_rag_result_sha256") != sha256_file(NATIVE_RAG_RESULT)
        or evidence.get("native_controller_result_sha256")
        != sha256_file(CONTROLLER_RESULT)
        or evidence.get("native_runner_sha256") != sha256_file(EXPECTED_NATIVE_RUNNER)
    ):
        raise PE06NativeFinalizeError("PE06 method config is not freeze-ready")
    return {
        "memory_context_max_tokens": common["memory_context_max_tokens"],
        "reader_max_completion_tokens": common["reader_max_completion_tokens"],
        "sha256": sha256_file(METHOD_CONFIG),
        "status": value["status"],
    }


def _validate_protocol() -> dict[str, Any]:
    value = _object(PROTOCOL)
    matrices = value.get("core_matrices")
    pe06 = matrices.get("DG11-PE06") if isinstance(matrices, dict) else None
    smoke = pe06.get("native_controller_smoke") if isinstance(pe06, dict) else None
    cap = pe06.get("reader_context_cap") if isinstance(pe06, dict) else None
    agent_c = pe06.get("agentrunbook_c") if isinstance(pe06, dict) else None
    if (
        not isinstance(pe06, dict)
        or pe06.get("leaderboard_equivalence") is not False
        or not isinstance(smoke, dict)
        or smoke.get("status") != "PASS"
        or smoke.get("result_sha256") != sha256_file(CONTROLLER_RESULT)
        or smoke.get("labels_accessed") is not False
        or smoke.get("paper_question_rows_read") != 0
        or smoke.get("service_process_limit") != 2
        or not isinstance(cap, dict)
        or cap.get("official_default_tokens") != 200000
        or cap.get("local_formal_value") != 49152
        or cap.get("local_model_context_tokens") != 65536
        or cap.get("reader_max_completion_tokens") != 8192
        or cap.get("reserved_non_memory_prompt_and_image_tokens") != 8192
        or not isinstance(agent_c, dict)
        or agent_c.get("status") != "EXCLUDED_PRE_FREEZE_RESOURCE_CEILING"
        or agent_c.get("maximum_codex_provider_calls") != 0
    ):
        raise PE06NativeFinalizeError("PE06 experiment protocol drifted")
    return {
        "leaderboard_equivalence": False,
        "sha256": sha256_file(PROTOCOL),
    }


def validate_native_gate() -> dict[str, Any]:
    candidate = _candidate_hashes()
    return {
        "candidate": candidate,
        "controller": _validate_controller_result(candidate),
        "failure_disclosures": _validate_failures(),
        "method_config": _validate_method_config(),
        "native_rag": _validate_native_rag(candidate),
        "protocol": _validate_protocol(),
        "status": "PASS",
    }


def run(output: Path) -> dict[str, Any]:
    validation = validate_native_gate()
    payload = {
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "labels_accessed": False,
        "paper_question_rows_read": 0,
        "schema": "milai.dg11.pe06-native-readiness-verification.v1",
        "status": "PASS",
        "validation": validation,
        "verification_source_sha256": sha256_file(Path(__file__)),
    }
    _atomic_json_once(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "schema": payload["schema"],
                "status": payload["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
