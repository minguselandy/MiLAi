"""Finalize the label-free frozen MiLAi context smoke and resume proof."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.contracts import read_context_archive
from evals.paper.identity import sha256_file

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "var/dg11/paper/runs/pe04-harness-smoke-20260824-002/inputs.json"
METHOD_CONFIG = ROOT / "var/dg11/paper/method-configs/milai-frozen.json"
FAILURE_DISCLOSURE = (
    ROOT / "var/dg11/paper/runs/pe04-milai-smoke-20260824-002/failure-disclosure.json"
)
DG10_ENV = Path("/tmp/milai-dg11-paper-config-smoke-20260824-001/dg10.env")
METHODS = {
    "DG10-FROZEN": {
        "compiler": "DG10_LEGACY",
        "contexts": ROOT
        / "var/dg11/paper/runs/pe04-milai-smoke-20260824-005/dg10-contexts.json",
        "env": DG10_ENV,
        "install": ROOT
        / "var/dg11/paper/runs/pe04-milai-smoke-20260824-001/dg10-install-manifest.json",
        "python": Path("/tmp/milai-dg11-paper-dg10-smoke-20260824-001/bin/python"),
        "reranker_calls": 0,
        "run_id": "pe04-milai-smoke-20260824-005-dg10",
        "runtime_wheel": ROOT
        / "var/dg10/final/candidate/packages/milai_runtime-0.1.0-py3-none-any.whl",
        "runtime_wheel_sha256": (
            "2a22e5d1dadc7dc8716a017845be9adc059962eb6ea653a766db048d8c499f8e"
        ),
        "mcp_wheel_sha256": (
            "08a08d13be792fc34cd9eb2e1b99b8b9f0a7ed00c5b5c51c30c4b85d0494ee66"
        ),
    },
    "DG11-FULL": {
        "compiler": "DG11_GROUPED_COMPACT_V3",
        "contexts": ROOT
        / "var/dg11/paper/runs/pe04-milai-smoke-20260824-005/dg11-contexts.json",
        "env": ROOT / "runtime/.env",
        "install": ROOT
        / "var/dg11/paper/runs/pe04-milai-smoke-20260824-001/dg11-install-manifest.json",
        "python": Path("/tmp/milai-dg11-paper-dg11-smoke-20260824-001/bin/python"),
        "reranker_calls": 1,
        "run_id": "pe04-milai-smoke-20260824-005-dg11",
        "runtime_wheel": ROOT
        / "var/dg11/freeze/candidate/packages/milai_runtime-0.1.0-py3-none-any.whl",
        "runtime_wheel_sha256": (
            "7fc0b1ab3babed5d99daca1ef92a7160ba0de729a34ccc1b1a10c5c82641e25a"
        ),
        "mcp_wheel_sha256": (
            "7ef5b1038f38a47fdffa4c9f73e39072a0525174b7220022dbf1ae6ebfc089a2"
        ),
    },
}
EXPECTED_CANDIDATE_ID = (
    "712577d17403951bdb6b7f6c7b6a2763b4b964427df33a857b02a316fbe74d51"
)
EXPECTED_INPUT_SHA256 = (
    "dd1c6fb5c137b16780965b5637562cdfdc8e69ef8d1f1e02e94ce92c754b5a5b"
)
EXPECTED_PRODUCT_ADAPTER_SHA256 = (
    "b69a65280cdeeb6c9ece91cf96c759632961b4e1506755e818090da2d8c04fa9"
)
EXPECTED_MCP_HOST_SHA256 = (
    "eca20a37abdea47b9205be8a40dd365cfe1bb97b630536d2ca09c23cac588588"
)
SESSION_ID = re.compile(r"session-[0-9a-f]{24}")


class PE04MiLAiFinalizeError(RuntimeError):
    pass


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PE04MiLAiFinalizeError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise PE04MiLAiFinalizeError(f"expected JSON object: {path}")
    return value


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise PE04MiLAiFinalizeError("MiLAi smoke result is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _usage_int(usage: Any, key: str) -> int:
    value = usage.get(key) if isinstance(usage, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PE04MiLAiFinalizeError(f"invalid MiLAi usage field: {key}")
    return value


def _validate_install(method_id: str, config: dict[str, Any]) -> dict[str, Any]:
    path = Path(config["install"])
    value = _object(path)
    expected_identity = "dg10" if method_id == "DG10-FROZEN" else "dg11"
    environment = Path(str(value.get("environment"))).resolve()
    runtime = (
        value.get("wheels", {}).get("runtime")
        if isinstance(value.get("wheels"), dict)
        else None
    )
    mcp = (
        value.get("wheels", {}).get("mcp")
        if isinstance(value.get("wheels"), dict)
        else None
    )
    distributions = value.get("distributions")
    if (
        value.get("schema") != "milai.dg11.paper-milai-install.v1"
        or value.get("status") != "PASS"
        or value.get("fresh_install") is not True
        or value.get("identity") != expected_identity
        or environment != Path(config["python"]).parent.parent.resolve()
        or not isinstance(runtime, dict)
        or runtime.get("sha256") != config["runtime_wheel_sha256"]
        or not isinstance(mcp, dict)
        or mcp.get("sha256") != config["mcp_wheel_sha256"]
        or not isinstance(distributions, list)
        or len(distributions) < 50
    ):
        raise PE04MiLAiFinalizeError(f"{method_id} install identity drifted")
    origin = Path(str(value.get("milai_origin"))).resolve()
    if not origin.is_relative_to(environment):
        raise PE04MiLAiFinalizeError(f"{method_id} imported outside fresh install")
    return {
        "distribution_count": len(distributions),
        "environment": str(environment),
        "manifest_sha256": sha256_file(path),
        "mcp_wheel_sha256": config["mcp_wheel_sha256"],
        "milai_origin": str(origin),
        "runtime_wheel_sha256": config["runtime_wheel_sha256"],
    }


def _validate_archive(method_id: str, config: dict[str, Any]) -> dict[str, Any]:
    path = Path(config["contexts"])
    envelope = _object(path)
    records = read_context_archive(path)
    identity = envelope.get("worker_identity")
    worker_sha256 = sha256_file(ROOT / "evals/paper/runners/milai_contexts.py")
    if (
        envelope.get("schema") != "milai.dg11.paper-context-archive.v1"
        or envelope.get("status") != "PASS"
        or envelope.get("failure_count") != 0
        or envelope.get("record_count") != 5
        or envelope.get("worker_count") != 1
        or envelope.get("labels_accessed") is not False
        or envelope.get("paper_labels_opened") is not False
        or envelope.get("run_id") != config["run_id"]
        or not isinstance(identity, dict)
        or identity.get("candidate_id") != EXPECTED_CANDIDATE_ID
        or identity.get("input_sha256") != EXPECTED_INPUT_SHA256
        or identity.get("method_id") != method_id
        or identity.get("mcp_host_python") != str(Path(config["python"]).absolute())
        or identity.get("mcp_host_source_sha256") != EXPECTED_MCP_HOST_SHA256
        or identity.get("mcp_wheel_sha256") != config["mcp_wheel_sha256"]
        or identity.get("paper_worker_sha256") != worker_sha256
        or identity.get("product_adapter_sha256") != EXPECTED_PRODUCT_ADAPTER_SHA256
        or identity.get("runtime_wheel_sha256") != config["runtime_wheel_sha256"]
        or len(records) != 5
    ):
        raise PE04MiLAiFinalizeError(f"{method_id} context identity drifted")
    mcp_origin = Path(str(identity.get("mcp_origin"))).resolve()
    if not mcp_origin.is_relative_to(Path(config["python"]).parent.parent.resolve()):
        raise PE04MiLAiFinalizeError(f"{method_id} MCP origin is not isolated")
    context_tokens: list[int] = []
    embedding_calls: list[int] = []
    index_ms: list[float] = []
    retrieval_ms: list[float] = []
    storage_bytes: list[int] = []
    reranker_total = 0
    for record in records:
        usage = dict(record.usage)
        embedding_parts = [
            _usage_int(usage, "embedding_calls_api_query"),
            _usage_int(usage, "embedding_calls_api_warmup"),
            _usage_int(usage, "embedding_calls_parent_inference"),
            _usage_int(usage, "embedding_calls_parent_warmup"),
        ]
        total_embedding = _usage_int(usage, "embedding_calls")
        reranker_calls = _usage_int(usage, "reranker_calls")
        if (
            record.method_id != method_id
            or record.track != "CONTROLLED"
            or record.terminal_status != "SUCCEEDED"
            or not record.context
            or not 0 < record.declared_tokens <= 512
            or not record.source_ids
            or len(record.source_ids) > 3
            or any(SESSION_ID.fullmatch(source) is None for source in record.source_ids)
            or usage.get("compiler_version") != config["compiler"]
            or usage.get("memory_status") != "AVAILABLE"
            or usage.get("embedding_call_accounting")
            != "DIRECT_PARENT_COUNTER_PLUS_FROZEN_API_PATH_V1"
            or total_embedding != sum(embedding_parts)
            or total_embedding <= 0
            or _usage_int(usage, "retriever_calls") != 1
            or _usage_int(usage, "ingest_extraction_calls") != 0
            or _usage_int(usage, "memory_query_model_calls") != 0
            or reranker_calls != config["reranker_calls"]
        ):
            raise PE04MiLAiFinalizeError(f"{method_id} context record drifted")
        context_tokens.append(record.declared_tokens)
        embedding_calls.append(total_embedding)
        index_ms.append(float(usage["index_time_ms"]))
        retrieval_ms.append(record.latency_ms)
        storage_bytes.append(_usage_int(usage, "adapter_storage_bytes"))
        reranker_total += reranker_calls
    return {
        "archive_sha256": sha256_file(path),
        "case_count": len(records),
        "compiler_version": config["compiler"],
        "context_tokens_max": max(context_tokens),
        "embedding_calls_max": max(embedding_calls),
        "embedding_calls_min": min(embedding_calls),
        "embedding_calls_total": sum(embedding_calls),
        "index_time_ms_total": round(sum(index_ms), 3),
        "reranker_calls_total": reranker_total,
        "retrieval_time_ms_total": round(sum(retrieval_ms), 3),
        "storage_bytes_total": sum(storage_bytes),
    }


def _resume_command(method_id: str, config: dict[str, Any]) -> list[str]:
    return [
        str(config["python"]),
        "-m",
        "evals.paper.runners.milai_contexts",
        "--run-id",
        str(config["run_id"]),
        "--inputs",
        str(INPUTS),
        "--output",
        str(config["contexts"]),
        "--env-file",
        str(config["env"]),
        "--method-id",
        method_id,
        "--runtime-wheel",
        str(config["runtime_wheel"]),
        "--install-manifest",
        str(config["install"]),
        "--workers",
        "1",
        "--max-case-attempts",
        "2",
        "--allow-unfrozen-smoke",
    ]


def _prove_resume(method_id: str, config: dict[str, Any]) -> dict[str, Any]:
    path = Path(config["contexts"])
    before = sha256_file(path)
    completed = subprocess.run(
        _resume_command(method_id, config),
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PE04MiLAiFinalizeError("MiLAi resume output is invalid") from exc
    after = sha256_file(path)
    if (
        before != after
        or not isinstance(output, dict)
        or output.get("status") != "PASS"
        or output.get("record_count") != 5
        or output.get("failure_count") != 0
        or output.get("run_id") != config["run_id"]
    ):
        raise PE04MiLAiFinalizeError(f"{method_id} resume changed its archive")
    return {"sha256_after": after, "sha256_before": before, "status": "UNCHANGED"}


def _remaining_smoke_databases() -> list[str]:
    code = """
import json
import os
import sys
from pathlib import Path
import psycopg
from milai.operations.cli import _load_environment_file
_load_environment_file(Path(sys.argv[1]))
owner = os.environ["MILAI_MIGRATION_DATABASE_URL"]
connection = psycopg.connect(owner, autocommit=True, connect_timeout=5)
rows = connection.execute(
    "SELECT datname FROM pg_database WHERE datname LIKE %s ORDER BY datname",
    ("milai_smoke_%",),
).fetchall()
connection.close()
print(json.dumps([row[0] for row in rows]))
"""
    completed = subprocess.run(
        [str(METHODS["DG10-FROZEN"]["python"]), "-c", code, str(DG10_ENV)],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PE04MiLAiFinalizeError("smoke database inventory is invalid") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PE04MiLAiFinalizeError("smoke database inventory drifted")
    return value


def _validate_failure_disclosure() -> dict[str, Any]:
    value = _object(FAILURE_DISCLOSURE)
    cleanup = value.get("cleanup")
    records = cleanup.get("records") if isinstance(cleanup, dict) else None
    if (
        value.get("schema") != "milai.dg11.paper-milai-smoke-failure-disclosure.v1"
        or value.get("status") != "DISCLOSED_CLEANED_NOT_SCORED"
        or value.get("paper_labels_opened") is not False
        or value.get("answer_provider_calls") != 0
        or value.get("candidate_modified") is not False
        or not isinstance(cleanup, dict)
        or cleanup.get("remaining_after_cleanup") != []
        or cleanup.get("temporary_database_count") != 14
        or not isinstance(records, list)
        or len(records) != 14
        or any(
            not isinstance(record, dict)
            or record.get("status") != "PASS"
            or record.get("owner") != "milai_owner"
            or record.get("connections_before_drop") != 0
            for record in records
        )
    ):
        raise PE04MiLAiFinalizeError("MiLAi failure disclosure drifted")
    return {
        "failure_class": value["failure"]["class"],
        "orphan_databases_cleaned": len(records),
        "score_use": value["failure"]["score_use"],
        "sha256": sha256_file(FAILURE_DISCLOSURE),
        "status": value["status"],
    }


def _validate_superseded() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for run, reason in (
        (
            "pe04-milai-smoke-20260824-001",
            "WORKER_IDENTITY_AND_USAGE_FIELDS_INCOMPLETE",
        ),
        ("pe04-milai-smoke-20260824-003", "EMBEDDING_CALLS_NOT_YET_INSTRUMENTED"),
        (
            "pe04-milai-smoke-20260824-004",
            "MCP_HOST_USED_EDITABLE_INTEGRATION_NOT_FROZEN_WHEEL",
        ),
    ):
        paths = [
            ROOT / f"var/dg11/paper/runs/{run}/dg10-contexts.json",
            ROOT / f"var/dg11/paper/runs/{run}/dg11-contexts.json",
        ]
        values = [_object(path) for path in paths]
        if any(
            value.get("status") != "PASS"
            or value.get("paper_labels_opened") is not False
            for value in values
        ):
            raise PE04MiLAiFinalizeError(f"superseded smoke drifted: {run}")
        result.append(
            {
                "archive_sha256": [sha256_file(path) for path in paths],
                "reason": reason,
                "run": run,
                "score_use": "EXCLUDED",
            }
        )
    return result


def run(output: Path) -> dict[str, Any]:
    if sha256_file(INPUTS) != EXPECTED_INPUT_SHA256:
        raise PE04MiLAiFinalizeError("label-free smoke inputs drifted")
    candidate = _object(ROOT / "var/dg11/freeze/candidate/candidate-manifest.json")
    method_config = _object(METHOD_CONFIG)
    common = method_config.get("common")
    if (
        candidate.get("candidate_id") != EXPECTED_CANDIDATE_ID
        or method_config.get("schema") != "milai.dg11.paper-milai-method-config.v1"
        or method_config.get("status") != "READY_FOR_PAPER_FREEZE"
        or method_config.get("candidate_id") != EXPECTED_CANDIDATE_ID
        or method_config.get("paper_labels_opened") is not False
        or method_config.get("candidate_modified_by_paper_harness") is not False
        or not isinstance(common, dict)
        or common.get("paper_worker_sha256")
        != sha256_file(ROOT / "evals/paper/runners/milai_contexts.py")
        or common.get("mcp_host_source_sha256") != EXPECTED_MCP_HOST_SHA256
        or common.get("mcp_host_python_policy") != "CURRENT_ISOLATED_METHOD_ENVIRONMENT"
    ):
        raise PE04MiLAiFinalizeError("MiLAi paper method preregistration drifted")
    installations = {
        method_id: _validate_install(method_id, config)
        for method_id, config in METHODS.items()
    }
    summaries = {
        method_id: _validate_archive(method_id, config)
        for method_id, config in METHODS.items()
    }
    resume = {
        method_id: _prove_resume(method_id, config)
        for method_id, config in METHODS.items()
    }
    remaining_databases = _remaining_smoke_databases()
    if remaining_databases:
        raise PE04MiLAiFinalizeError("MiLAi smoke left temporary databases")
    dg10_env_identity_path = (
        ROOT
        / "var/dg11/paper/runs/pe04-milai-smoke-20260824-001/dg10-env-identity.json"
    )
    dg10_env_identity = _object(dg10_env_identity_path)
    if (
        dg10_env_identity.get("schema") != "milai.dg11.paper-dg10-env-derivation.v1"
        or dg10_env_identity.get("status") != "PASS"
        or dg10_env_identity.get("derived_env_sha256") != sha256_file(DG10_ENV)
        or dg10_env_identity.get("source_env_sha256")
        != sha256_file(ROOT / "runtime/.env")
        or len(dg10_env_identity.get("removed_keys", [])) != 8
    ):
        raise PE04MiLAiFinalizeError("DG10 secret-safe config derivation drifted")
    result: dict[str, Any] = {
        "answer_provider_calls": 0,
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "candidate_modified": False,
        "case_count_per_method": 5,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "development_ai_reviews": 0,
        "dg10_env_derivation": {
            "derived_env_sha256": dg10_env_identity["derived_env_sha256"],
            "identity_sha256": sha256_file(dg10_env_identity_path),
            "removed_key_count": 8,
            "source_env_sha256": dg10_env_identity["source_env_sha256"],
        },
        "failure_disclosure": _validate_failure_disclosure(),
        "gates": {
            "candidate_unchanged": True,
            "context_budget_enforced": True,
            "embedding_calls_accounted": True,
            "failure_denominator_complete": True,
            "fresh_wheel_installs": True,
            "global_context_concurrency_at_most_two": True,
            "labels_opened": False,
            "one_worker_per_milai_process": True,
            "resume_write_once": True,
            "temporary_database_cleanup": True,
        },
        "installations": installations,
        "method_config_sha256": sha256_file(METHOD_CONFIG),
        "methods": summaries,
        "paper_labels_opened": False,
        "provider_call_totals": {
            "answer": 0,
            "embedding": sum(
                int(summary["embedding_calls_total"]) for summary in summaries.values()
            ),
            "ingest_extraction": 0,
            "memory_query_model": 0,
            "reranker": sum(
                int(summary["reranker_calls_total"]) for summary in summaries.values()
            ),
            "retriever": 10,
        },
        "remaining_smoke_databases": remaining_databases,
        "resume_proof": resume,
        "schema": "milai.dg11.paper-milai-harness-smoke.v1",
        "source_artifacts": {
            "finalizer_sha256": sha256_file(Path(__file__)),
            "input_sha256": sha256_file(INPUTS),
            "method_config_sha256": sha256_file(METHOD_CONFIG),
            "mcp_host_sha256": sha256_file(
                ROOT / "evals/agent_integration/mcp_host.py"
            ),
            "paper_worker_sha256": sha256_file(
                ROOT / "evals/paper/runners/milai_contexts.py"
            ),
            "product_adapter_sha256": sha256_file(
                ROOT / "evals/benchmark/lme_product_smoke.py"
            ),
            "protocol_sha256": sha256_file(
                ROOT / "evals/paper/experiment-protocol.yaml"
            ),
        },
        "status": "PASS",
        "superseded_smokes": _validate_superseded(),
        "work_package": "DG11-PE04-MILAI-HARNESS-SMOKE",
    }
    _atomic_json_once(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve())
    print(json.dumps({"schema": result["schema"], "status": result["status"]}))


if __name__ == "__main__":
    main()
