"""Build and verify the one-way DG-11 paper harness freeze."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper import pe05_finalize, pe06_finalize, pe06_native_finalize
from evals.paper.evaluator_identity import verify_identity as verify_evaluator_identity
from evals.paper.identity import (
    git_tracked_identity,
    sha256_file,
    source_inventory,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "var/dg11/paper/freeze/paper-freeze-manifest.json"
EXPECTED_CANDIDATE_ID = (
    "712577d17403951bdb6b7f6c7b6a2763b4b964427df33a857b02a316fbe74d51"
)
BENCHMARK_ROOTS = {
    "LongMemEval": Path("/cra/memory/mx_memory/benchmarks/LongMemEval"),
    "Memora": Path("/cra/memory/mx_memory/benchmarks/Memora"),
    "LongMemEval-V2": Path("/cra/memory/mx_memory/benchmarks/LongMemEval-V2"),
}
EXPECTED_BENCHMARK_COMMITS = {
    "LongMemEval": "9e0b455f4ef0e2ab8f2e582289761153549043fc",
    "Memora": "a6493188efc836d6511ed5e4163fe3ba87da30ff",
    "LongMemEval-V2": "2cc8c540bdb87fe6761629b585e727e1c4704520",
}
PAPER_RUNTIME_DEPENDENCIES = (
    ROOT / "evals/__init__.py",
    ROOT / "evals/agent_efficiency/provider_ab.py",
    ROOT / "evals/agent_efficiency/vllm_local_ab.py",
    ROOT / "evals/agent_efficiency/vllm_local_identity.py",
    ROOT / "evals/agent_integration/e2e.py",
    ROOT / "evals/agent_integration/mcp_host.py",
    ROOT / "evals/benchmark/lme_product_smoke.py",
    ROOT / "scripts/__init__.py",
    ROOT / "scripts/dg10_ai_provenance.py",
    ROOT / "scripts/dg10_authorization.py",
    ROOT / "scripts/dg10_post_r3_provider_gate.py",
    ROOT / "scripts/dg10_remediation.py",
    ROOT / "scripts/dg10_stage_ledger.py",
    ROOT / "scripts/run_dg10_benchmark_adapter_contract.py",
    ROOT / "scripts/run_dg10_benchmark_dev_smoke.py",
)
FROZEN_MILAI_WHEELS = tuple(
    ROOT / root / filename
    for root in (
        "var/dg10/final/candidate/packages",
        "var/dg11/freeze/candidate/packages",
    )
    for filename in (
        "milai_client-0.1.0-py3-none-any.whl",
        "milai_mcp-0.1.0-py3-none-any.whl",
        "milai_openworker_mcp-0.1.0-py3-none-any.whl",
        "milai_runtime-0.1.0-py3-none-any.whl",
    )
)
PE06_FAILURE = (
    ROOT
    / "var/dg11/paper/runs/pe06-milai-adapter-smoke-20260824-001/failure-disclosure.json"
)
PE06_RESULT = (
    ROOT / "var/dg11/paper/runs/pe06-milai-adapter-smoke-20260824-002/result.json"
)
PE06_VERIFICATION = (
    ROOT / "var/dg11/paper/runs/pe06-milai-adapter-smoke-20260824-002/verification.json"
)
PE06_METHOD_CONFIG = ROOT / "var/dg11/paper/method-configs/lme-v2.json"
PE06_NATIVE_RAG_ROOT = ROOT / "var/dg11/paper/runs/pe06-native-rag-smoke-20260824-003"
PE06_NATIVE_CONTROLLER_ROOT = (
    ROOT / "var/dg11/paper/runs/pe06-native-controller-smoke-20260824-001"
)
PE06_NATIVE_VERIFICATION = PE06_NATIVE_CONTROLLER_ROOT / "verification.json"
EVALUATOR_IDENTITY = ROOT / "var/dg11/paper/freeze/evaluator-identity.json"
PE05_ROOT = ROOT / "var/dg11/paper/runs/pe05-memora-smoke-20260824-001"
PE05_RESULT = PE05_ROOT / "result-002.json"
PE05_METHOD_CONFIG = ROOT / "var/dg11/paper/method-configs/memora.json"
PE05_FINAL_CONTEXTS = (
    PE05_ROOT / "controlled-contexts.json",
    PE05_ROOT / "dg11-contexts.json",
    PE05_ROOT / "mem0-contexts-002.json",
    PE05_ROOT / "hindsight-contexts-005.json",
    PE05_ROOT / "graphiti-contexts-003.json",
    PE05_ROOT / "reme-contexts-002.json",
)
PE05_FINAL_ANSWERS = (
    PE05_ROOT / "answers-all-methods-001/raw-generations.json",
    PE05_ROOT / "answers-all-methods-001/usage-ledger.jsonl",
)


class PaperFreezeError(RuntimeError):
    pass


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaperFreezeError(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise PaperFreezeError(f"expected JSON object: {path}")
    return value


def _identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PaperFreezeError(f"required frozen file is absent: {path}")
    return {
        "bytes": path.stat().st_size,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
    }


def _required_files(smoke_results: list[Path]) -> list[Path]:
    paths = [
        ROOT / "evals/paper/claim-matrix.yaml",
        ROOT / "evals/paper/experiment-protocol.yaml",
        ROOT / "var/dg11/paper/method-configs/longmemeval-baselines.json",
        ROOT / "var/dg11/paper/freeze/external-identities.json",
        ROOT / "var/dg11/paper/freeze/method-inclusion.json",
        ROOT / "var/dg11/freeze/candidate/candidate-manifest.json",
        ROOT / "var/dg11/final/candidate/inventory.json",
        ROOT / "var/dg11/splits/v1/freeze-manifest.json",
        ROOT / "var/dg11/splits/v1/paper-test-v1/source-ids.json",
        ROOT / "var/dg11/splits/v1/paper-test-v1/label-free-inputs.json",
        ROOT / "var/dg11/paper/freeze/longmemeval-holdout-inputs.json",
        ROOT / "var/dg11/paper/freeze/longmemeval-full-inputs.json",
        ROOT / "var/dg11/paper/runs/pe01-smoke-20260824-002/result.json",
        ROOT / "var/dg11/paper/runs/pe02-baseline-smoke-20260824-007/result.json",
        ROOT
        / "var/dg11/paper/runs/pe02-baseline-smoke-20260824-004/dense-contexts.json",
        ROOT
        / "var/dg11/paper/runs/pe02-baseline-smoke-20260824-006/characterization-contexts.json",
        ROOT
        / "var/dg11/paper/runs/pe04-harness-smoke-20260824-003/controlled-contexts.json",
        ROOT / "var/dg11/paper/runs/pe04-harness-smoke-20260824-002/inputs.json",
        ROOT / "var/dg11/paper/runs/pe04-answer-smoke-20260824-001/result.json",
        ROOT
        / "var/dg11/paper/runs/pe04-answer-smoke-20260824-001/raw-generations.json",
        ROOT / "var/dg11/paper/runs/pe04-answer-smoke-20260824-001/usage-ledger.jsonl",
        ROOT / "var/dg11/paper/runs/pe04-milai-smoke-20260824-001/dg10-contexts.json",
        ROOT / "var/dg11/paper/runs/pe04-milai-smoke-20260824-001/dg11-contexts.json",
        ROOT
        / "var/dg11/paper/runs/pe04-milai-smoke-20260824-001/dg10-env-identity.json",
        ROOT
        / "var/dg11/paper/runs/pe04-milai-smoke-20260824-001/dg10-install-manifest.json",
        ROOT
        / "var/dg11/paper/runs/pe04-milai-smoke-20260824-001/dg11-install-manifest.json",
        ROOT
        / "var/dg11/paper/runs/pe04-milai-smoke-20260824-002/failure-disclosure.json",
        ROOT / "var/dg11/paper/runs/pe04-milai-smoke-20260824-003/dg10-contexts.json",
        ROOT / "var/dg11/paper/runs/pe04-milai-smoke-20260824-003/dg11-contexts.json",
        ROOT / "var/dg11/paper/runs/pe04-milai-smoke-20260824-004/dg10-contexts.json",
        ROOT / "var/dg11/paper/runs/pe04-milai-smoke-20260824-004/dg11-contexts.json",
        ROOT / "var/dg11/paper/runs/pe04-milai-smoke-20260824-005/dg10-contexts.json",
        ROOT / "var/dg11/paper/runs/pe04-milai-smoke-20260824-005/dg11-contexts.json",
        ROOT / "var/dg11/paper/runs/pe04-milai-smoke-20260824-005/result.json",
        ROOT / "var/dg11/paper/runs/pe03-external-feasibility-20260824-001/result.json",
        PE05_RESULT,
        *PE05_FINAL_CONTEXTS,
        *PE05_FINAL_ANSWERS,
        PE05_ROOT / "raw/reme-contexts-002-cohort-00.log",
        PE06_FAILURE,
        PE06_RESULT,
        PE06_VERIFICATION,
        ROOT
        / "var/dg11/paper/runs/pe06-native-rag-smoke-20260824-001/failure-disclosure.json",
        ROOT
        / "var/dg11/paper/runs/pe06-native-rag-smoke-20260824-002/failure-disclosure.json",
        PE06_NATIVE_RAG_ROOT / "result.json",
        PE06_NATIVE_RAG_ROOT / "embedding-service-identity.json",
        PE06_NATIVE_RAG_ROOT / "synthetic-trajectories.json",
        PE06_NATIVE_RAG_ROOT / "raw/embedding-server.log",
        PE06_NATIVE_CONTROLLER_ROOT / "result.json",
        PE06_NATIVE_CONTROLLER_ROOT / "verification.json",
        PE06_NATIVE_CONTROLLER_ROOT / "embedding-service-identity.json",
        PE06_NATIVE_CONTROLLER_ROOT / "controller-gateway-identity.json",
        PE06_NATIVE_CONTROLLER_ROOT / "synthetic-trajectories.json",
        PE06_NATIVE_CONTROLLER_ROOT / "raw/embedding-server.log",
        PE06_NATIVE_CONTROLLER_ROOT / "raw/controller-gateway.log",
        Path("/cra/qwen36-35B/config.json"),
        Path("/cra/qwen36-35B/tokenizer.json"),
        Path("/cra/qwen36-35B/chat_template.jinja"),
        Path("/cra/qwen36-35B/preprocessor_config.json"),
        *PAPER_RUNTIME_DEPENDENCIES,
        *FROZEN_MILAI_WHEELS,
        *sorted(
            (
                ROOT
                / "var/dg11/paper/runs/pe06-milai-adapter-smoke-20260824-002/synthetic"
            ).glob("**/*.png")
        ),
        *smoke_results,
    ]
    pretest_required = [
        EVALUATOR_IDENTITY,
        ROOT / "var/dg11/paper/freeze/lme-v2-modality-feasibility.json",
    ]
    paths.extend(pretest_required)
    method_configs = sorted((ROOT / "var/dg11/paper/method-configs").glob("*.json"))
    paths.extend(path for path in method_configs if path not in paths)
    return paths


def _verify_pe05_adapter_gate(protocol: dict[str, Any]) -> dict[str, Any]:
    matrix = protocol.get("core_matrices")
    pe05 = matrix.get("DG11-PE05") if isinstance(matrix, dict) else None
    smoke = pe05.get("all_method_smoke") if isinstance(pe05, dict) else None
    method_binding = pe05.get("method_config") if isinstance(pe05, dict) else None
    result = _object(PE05_RESULT)
    config = _object(PE05_METHOD_CONFIG)
    if (
        not isinstance(smoke, dict)
        or smoke.get("status") != "PASS"
        or smoke.get("result_sha256") != sha256_file(PE05_RESULT)
        or smoke.get("paper_labels_opened") is not False
        or smoke.get("method_count") != 7
        or smoke.get("external_native_method_count") != 4
        or smoke.get("answer_calls") != 14
        or smoke.get("maximum_concurrent_requests") != 2
        or not isinstance(method_binding, dict)
        or method_binding.get("sha256") != sha256_file(PE05_METHOD_CONFIG)
        or config.get("status") != "MEMORA_ALL_METHODS_READY_FOR_PAPER_FREEZE"
    ):
        raise PaperFreezeError("PE05 all-method smoke is not bound to the protocol")
    validated = {
        "all_method_answer_smoke": pe05_finalize._verify_all_method_answers(),
        "answer_smoke": pe05_finalize._verify_answers(),
        "context_smoke": pe05_finalize._verify_contexts(),
        "external_native_context_smoke": pe05_finalize._verify_external_contexts(),
        "formal_inputs": pe05_finalize._verify_formal_inputs(),
        "hashes": pe05_finalize._verify_hashes(),
        "method_config": pe05_finalize._verify_method_config(),
    }
    if (
        result.get("schema") != "milai.dg11.pe05-memora-all-method-smoke.v2"
        or result.get("status") != "PASS"
        or result.get("candidate_id") != EXPECTED_CANDIDATE_ID
        or result.get("candidate_modified") is not False
        or result.get("development_ai_reviews") != 0
        or result.get("paper_labels_opened") is not False
        or any(result.get(key) != value for key, value in validated.items())
    ):
        raise PaperFreezeError("PE05 all-method smoke verification drifted")
    return {
        "all_method_answer_result_sha256": sha256_file(PE05_FINAL_ANSWERS[0]),
        "method_config_sha256": sha256_file(PE05_METHOD_CONFIG),
        "result_sha256": sha256_file(PE05_RESULT),
        "status": "PASS",
    }


def _verify_pe06_adapter_gate(protocol: dict[str, Any]) -> dict[str, Any]:
    matrix = protocol.get("core_matrices")
    pe06 = matrix.get("DG11-PE06") if isinstance(matrix, dict) else None
    smoke = pe06.get("adapter_smoke") if isinstance(pe06, dict) else None
    config = _object(PE06_METHOD_CONFIG)
    if (
        not isinstance(smoke, dict)
        or smoke.get("status") != "PASS"
        or smoke.get("result_sha256") != sha256_file(PE06_RESULT)
        or smoke.get("failure_disclosure_sha256") != sha256_file(PE06_FAILURE)
        or smoke.get("verification_sha256") != sha256_file(PE06_VERIFICATION)
    ):
        raise PaperFreezeError("PE06 adapter smoke is not bound to the protocol")
    result = pe06_finalize._validate_result(PE06_RESULT)
    failure = pe06_finalize._validate_failure()
    databases = pe06_finalize._remaining_smoke_databases()
    verification = _object(PE06_VERIFICATION)
    native_validation = pe06_native_finalize.validate_native_gate()
    native_verification = _object(PE06_NATIVE_VERIFICATION)
    if (
        databases
        or verification.get("schema") != "milai.dg11.pe06-milai-adapter-verification.v1"
        or verification.get("status") != "PASS"
        or verification.get("labels_accessed") is not False
        or verification.get("paper_question_rows_read") != 0
        or verification.get("verification_source_sha256")
        != sha256_file(ROOT / "evals/paper/pe06_finalize.py")
        or verification.get("result") != result
        or verification.get("failure_disclosure") != failure
        or native_verification.get("schema")
        != "milai.dg11.pe06-native-readiness-verification.v1"
        or native_verification.get("status") != "PASS"
        or native_verification.get("labels_accessed") is not False
        or native_verification.get("paper_question_rows_read") != 0
        or native_verification.get("verification_source_sha256")
        != sha256_file(ROOT / "evals/paper/pe06_native_finalize.py")
        or native_verification.get("validation") != native_validation
    ):
        raise PaperFreezeError("PE06 adapter or native verification drifted")
    if config.get("status") != "READY_FOR_PAPER_FREEZE":
        raise PaperFreezeError(
            "PE06 native baseline runtime and reader cap are not frozen"
        )
    return {
        "failure_disclosure_sha256": sha256_file(PE06_FAILURE),
        "method_config_sha256": sha256_file(PE06_METHOD_CONFIG),
        "result_sha256": sha256_file(PE06_RESULT),
        "status": "PASS",
        "native_controller_result_sha256": native_validation["controller"][
            "result_sha256"
        ],
        "native_rag_result_sha256": native_validation["native_rag"]["result_sha256"],
        "native_verification_sha256": sha256_file(PE06_NATIVE_VERIFICATION),
        "verification_sha256": sha256_file(PE06_VERIFICATION),
    }


def _dataset_identities() -> dict[str, Any]:
    lme_v2_data = BENCHMARK_ROOTS["LongMemEval-V2"] / "data/longmemeval-v2"
    lme_v2_paths = [
        lme_v2_data / "checksums.sha256",
        lme_v2_data / "questions.jsonl",
        lme_v2_data / "trajectories.jsonl",
        lme_v2_data / "haystacks/lme_v2_small.json",
        lme_v2_data / "trajectory_screenshots/web_screenshots.tar.gz",
        lme_v2_data / "trajectory_screenshots/enterprise_screenshots_base.tar.gz",
    ]
    return {
        "LongMemEval": {
            "dataset": _identity(
                BENCHMARK_ROOTS["LongMemEval"] / "data/longmemeval_s_cleaned.json"
            )
        },
        "Memora": {
            "data_inventory": source_inventory(BENCHMARK_ROOTS["Memora"] / "data")
        },
        "LongMemEval-V2": {
            "required_files": [_identity(path) for path in lme_v2_paths]
        },
    }


def build_manifest(output: Path, smoke_results: list[Path]) -> dict[str, Any]:
    if output.exists():
        raise PaperFreezeError("paper freeze manifest already exists; it is one-way")
    candidate = _object(ROOT / "var/dg11/freeze/candidate/candidate-manifest.json")
    if candidate.get("candidate_id") != EXPECTED_CANDIDATE_ID:
        raise PaperFreezeError("candidate identity drifted")
    claim = _object(ROOT / "evals/paper/claim-matrix.yaml")
    protocol = _object(ROOT / "evals/paper/experiment-protocol.yaml")
    inclusion = _object(ROOT / "var/dg11/paper/freeze/method-inclusion.json")
    if (
        claim.get("status") != "PREREGISTERED"
        or protocol.get("status") != "PREREGISTERED_PRE_TEST"
        or inclusion.get("paper_labels_opened") is not False
    ):
        raise PaperFreezeError("paper preregistration state is invalid")
    pe05_gate = _verify_pe05_adapter_gate(protocol)
    pe06_gate = _verify_pe06_adapter_gate(protocol)
    frozen_files = [
        _identity(path.resolve()) for path in _required_files(smoke_results)
    ]
    benchmark_sources = {
        name: git_tracked_identity(path)
        for name, path in sorted(BENCHMARK_ROOTS.items())
    }
    for name, expected in EXPECTED_BENCHMARK_COMMITS.items():
        if benchmark_sources[name]["commit"] != expected:
            raise PaperFreezeError(f"{name} benchmark commit drifted")
    paper_source = source_inventory(ROOT / "evals/paper")
    payload: dict[str, Any] = {
        "benchmark_datasets": _dataset_identities(),
        "benchmark_sources": benchmark_sources,
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "development_ai_reviews": 0,
        "frozen_files": frozen_files,
        "paper_labels_opened_before_freeze": False,
        "paper_source_inventory": paper_source,
        "pre_freeze_gates": {
            "DG11-PE05": pe05_gate,
            "DG11-PE06": pe06_gate,
        },
        "schema": "milai.dg11.paper-freeze-manifest.v1",
        "status": "PAPER_HARNESS_FROZEN",
    }
    _atomic_json(output, payload)
    return payload


def require_paper_evaluation_ready(
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    manifest = _object(manifest_path)
    if (
        manifest.get("schema") != "milai.dg11.paper-freeze-manifest.v1"
        or manifest.get("status") != "PAPER_HARNESS_FROZEN"
        or manifest.get("candidate_id") != EXPECTED_CANDIDATE_ID
        or manifest.get("paper_labels_opened_before_freeze") is not False
    ):
        raise PaperFreezeError("paper freeze state is not evaluation-ready")
    expected_source = manifest.get("paper_source_inventory")
    observed_source = source_inventory(ROOT / "evals/paper")
    if not isinstance(expected_source, dict) or observed_source[
        "inventory_root_sha256"
    ] != expected_source.get("inventory_root_sha256"):
        raise PaperFreezeError("paper harness source changed after freeze")
    frozen_files = manifest.get("frozen_files")
    if not isinstance(frozen_files, list):
        raise PaperFreezeError("paper frozen-file inventory is absent")
    for item in frozen_files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise PaperFreezeError("paper frozen-file record is invalid")
        path = Path(item["path"])
        if (
            not path.is_file()
            or path.stat().st_size != item.get("bytes")
            or sha256_file(path) != item.get("sha256")
        ):
            raise PaperFreezeError(f"frozen file changed after paper freeze: {path}")
    return manifest


def verify_full(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = require_paper_evaluation_ready(manifest_path)
    datasets = manifest.get("benchmark_datasets")
    if not isinstance(datasets, dict):
        raise PaperFreezeError("benchmark dataset identities are absent")
    observed = _dataset_identities()
    if observed != datasets:
        raise PaperFreezeError("a benchmark dataset changed after paper freeze")
    evaluator = verify_evaluator_identity(EVALUATOR_IDENTITY, workers=2)
    return {
        "evaluator_identity": evaluator,
        "manifest_sha256": sha256_file(manifest_path),
        "schema": "milai.dg11.paper-freeze-verification.v1",
        "status": "PASS",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--output", type=Path, default=DEFAULT_MANIFEST)
    build_parser.add_argument("--smoke-result", action="append", type=Path, default=[])
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    if args.command == "build":
        result = build_manifest(
            args.output.resolve(), [path.resolve() for path in args.smoke_result]
        )
    else:
        result = verify_full(args.manifest.resolve())
    print(
        json.dumps(
            {"schema": result["schema"], "status": result["status"]},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
