"""Verify and freeze the label-free PE06 MiLAi adapter smoke evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.identity import sha256_file
from evals.paper.lme_v2_adapter import (
    EXPECTED_BENCHMARK_COMMIT,
    EXPECTED_CANDIDATE_ID,
    official_contract_identity,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULT = (
    ROOT / "var/dg11/paper/runs/pe06-milai-adapter-smoke-20260824-002/result.json"
)
DEFAULT_OUTPUT = (
    ROOT / "var/dg11/paper/runs/pe06-milai-adapter-smoke-20260824-002/verification.json"
)
FAILURE_DISCLOSURE = (
    ROOT
    / "var/dg11/paper/runs/pe06-milai-adapter-smoke-20260824-001/failure-disclosure.json"
)
MODALITY_ARTIFACT = ROOT / "var/dg11/paper/freeze/lme-v2-modality-feasibility.json"
CANDIDATE_MANIFEST = ROOT / "var/dg11/freeze/candidate/candidate-manifest.json"
CANDIDATE_INVENTORY = ROOT / "var/dg11/final/candidate/inventory.json"
FROZEN_PYTHON = Path("/tmp/milai-dg11-paper-dg11-smoke-20260824-001/bin/python")
EXPECTED_CANDIDATE_MANIFEST_SHA256 = (
    "9812af51eeafac55e9ab250d37d6d4fe8217b73428b4543af74bbb7ad00cef5d"
)
EXPECTED_CANDIDATE_INVENTORY_SHA256 = (
    "b754b9cfed729192b02c9493c5cb3ff93a7961c72f440e5ddb358ef7785055bb"
)
EXPECTED_MODALITY_SHA256 = (
    "fafe0917e5fb23a1f1bacfa30ee6327d2121a7b42688b0575a9db4904e23be4f"
)
EXPECTED_LOSSINESS = {
    "question_image_passed_to_memory_query": True,
    "question_image_used_for_visual_retrieval": False,
    "reader_receives_question_image_independently": True,
    "retrieved_screenshot_pixels_preserved": True,
    "visual_only_retrieval_supported": False,
}


class PE06FinalizeError(RuntimeError):
    pass


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PE06FinalizeError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise PE06FinalizeError(f"expected JSON object: {path}")
    return value


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise PE06FinalizeError("PE06 verification is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _validate_file_record(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise PE06FinalizeError("PE06 file identity is invalid")
    path = Path(value["path"])
    if (
        not path.is_file()
        or path.stat().st_size != value.get("bytes")
        or sha256_file(path) != value.get("sha256")
    ):
        raise PE06FinalizeError(f"PE06 file identity drifted: {path}")
    return {
        "bytes": path.stat().st_size,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
    }


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
""".strip()
    completed = subprocess.run(
        [str(FROZEN_PYTHON), "-c", code, str(ROOT / "runtime/.env")],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=30,
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PE06FinalizeError("PE06 database inventory is invalid") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PE06FinalizeError("PE06 database inventory contract drifted")
    return value


def _validate_failure() -> dict[str, Any]:
    value = _object(FAILURE_DISCLOSURE)
    database = value.get("database_cleanup")
    attempts = value.get("development_attempts")
    if (
        value.get("schema") != "milai.dg11.pe06-milai-adapter-failure.v1"
        or value.get("status") != "FAIL_EXCLUDED"
        or value.get("result_use") != "EXCLUDED_DEVELOPMENT_SMOKE"
        or value.get("labels_accessed") is not False
        or value.get("paper_question_rows_read") != 0
        or not isinstance(database, dict)
        or database.get("remaining_milai_smoke_databases") != 0
        or not isinstance(attempts, list)
        or len(attempts) != 3
    ):
        raise PE06FinalizeError("PE06 superseded failure disclosure drifted")
    return {
        "classification": value["classification"],
        "path": str(FAILURE_DISCLOSURE.relative_to(ROOT)),
        "sha256": sha256_file(FAILURE_DISCLOSURE),
    }


def _validate_result(path: Path) -> dict[str, Any]:
    value = _object(path)
    adapter = value.get("adapter")
    modality = value.get("modality_feasibility")
    registration = value.get("official_registration")
    query = value.get("query_metadata")
    contract = value.get("synthetic_contract")
    candidate_expected = {
        "candidate_inventory_sha256": EXPECTED_CANDIDATE_INVENTORY_SHA256,
        "candidate_manifest_sha256": EXPECTED_CANDIDATE_MANIFEST_SHA256,
    }
    if (
        value.get("schema") != "milai.dg11.pe06-milai-adapter-smoke.v1"
        or value.get("status") != "PASS"
        or value.get("candidate_id") != EXPECTED_CANDIDATE_ID
        or value.get("labels_accessed") is not False
        or value.get("paper_question_rows_read") != 0
        or value.get("test_data_only") is not True
        or value.get("candidate_before") != candidate_expected
        or value.get("candidate_after") != candidate_expected
        or not isinstance(adapter, dict)
        or adapter.get("source_sha256")
        != sha256_file(ROOT / "evals/paper/lme_v2_adapter.py")
        or adapter.get("wrapper_sha256")
        != sha256_file(ROOT / "evals/paper/runners/lme_v2.py")
        or not isinstance(modality, dict)
        or modality.get("sha256") != EXPECTED_MODALITY_SHA256
        or not isinstance(registration, dict)
        or registration.get("commit") != EXPECTED_BENCHMARK_COMMIT
        or registration.get("registered_type") != "milai"
        or registration.get("paper_data_opened") is not False
        or registration.get("question_rows_read") != 0
        or not isinstance(query, dict)
        or query.get("labels_accessed") is not False
        or query.get("paper_question_rows_read_by_adapter") != 0
        or query.get("context_status") != "AVAILABLE"
        or query.get("modality_lossiness") != EXPECTED_LOSSINESS
        or not isinstance(contract, dict)
        or contract.get("expected_trajectory_id") != "trajectory-target"
        or contract.get("expected_state_index") != 1
    ):
        raise PE06FinalizeError("PE06 adapter smoke contract drifted")

    retrieved_ids = query.get("retrieved_trajectory_ids")
    screenshots = query.get("retrieved_screenshots")
    expected_sha256 = contract.get("expected_screenshot_sha256")
    if (
        not isinstance(retrieved_ids, list)
        or not retrieved_ids
        or retrieved_ids[0] != "trajectory-target"
        or not isinstance(screenshots, list)
        or not screenshots
        or not isinstance(screenshots[0], dict)
        or screenshots[0].get("trajectory_id") != "trajectory-target"
        or screenshots[0].get("state_index") != 1
        or screenshots[0].get("sha256") != expected_sha256
    ):
        raise PE06FinalizeError("PE06 target screenshot evidence drifted")
    verified_screenshots = [_validate_file_record(item) for item in screenshots]

    assets = value.get("synthetic_assets")
    if not isinstance(assets, list) or len(assets) != 5:
        raise PE06FinalizeError("PE06 synthetic asset denominator drifted")
    verified_assets = [_validate_file_record(item) for item in assets]
    if expected_sha256 not in {item["sha256"] for item in verified_assets}:
        raise PE06FinalizeError("PE06 expected screenshot is absent from assets")

    context_identity = value.get("context_identity")
    context_items = (
        context_identity.get("items") if isinstance(context_identity, dict) else None
    )
    if (
        not isinstance(context_identity, dict)
        or not isinstance(context_identity.get("root_sha256"), str)
        or not isinstance(context_items, list)
        or [item.get("type") for item in context_items if isinstance(item, dict)]
        != ["text", "text", "image", "text", "image", "text", "image"]
    ):
        raise PE06FinalizeError("PE06 memory context identity drifted")
    for item in context_items:
        if isinstance(item, dict) and item.get("type") == "image":
            _validate_file_record(item)

    usage = query.get("runtime_usage")
    accounting = usage.get("embedding_accounting") if isinstance(usage, dict) else None
    if (
        not isinstance(usage, dict)
        or usage.get("compiler_version") != "DG11_GROUPED_COMPACT_V3"
        or usage.get("governed_claim_count") != 3
        or not isinstance(accounting, dict)
        or accounting.get("total_calls")
        != sum(
            accounting.get(key, -1000)
            for key in (
                "api_query_calls",
                "api_warmup_calls",
                "direct_parent_inference_calls",
                "direct_parent_warmup_calls",
            )
        )
    ):
        raise PE06FinalizeError("PE06 Runtime usage accounting drifted")
    return {
        "asset_count": len(verified_assets),
        "context_item_count": len(context_items),
        "embedding_calls": accounting["total_calls"],
        "result_sha256": sha256_file(path),
        "screenshot_count": len(verified_screenshots),
        "target_screenshot_sha256": expected_sha256,
    }


def run(result_path: Path, output: Path) -> dict[str, Any]:
    if sha256_file(CANDIDATE_MANIFEST) != EXPECTED_CANDIDATE_MANIFEST_SHA256:
        raise PE06FinalizeError("candidate manifest drifted")
    if sha256_file(CANDIDATE_INVENTORY) != EXPECTED_CANDIDATE_INVENTORY_SHA256:
        raise PE06FinalizeError("candidate inventory drifted")
    if sha256_file(MODALITY_ARTIFACT) != EXPECTED_MODALITY_SHA256:
        raise PE06FinalizeError("modality feasibility artifact drifted")
    official = official_contract_identity()
    result = _validate_result(result_path)
    failure = _validate_failure()
    databases = _remaining_smoke_databases()
    if databases:
        raise PE06FinalizeError("PE06 left temporary Runtime databases")
    payload = {
        "adapter_source_sha256": sha256_file(ROOT / "evals/paper/lme_v2_adapter.py"),
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "database_cleanup": {"remaining": databases, "status": "PASS"},
        "failure_disclosure": failure,
        "labels_accessed": False,
        "official_contract": official,
        "paper_question_rows_read": 0,
        "result": result,
        "schema": "milai.dg11.pe06-milai-adapter-verification.v1",
        "status": "PASS",
        "verification_source_sha256": sha256_file(Path(__file__)),
    }
    _atomic_json_once(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(args.result.resolve(), args.output.resolve())
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
