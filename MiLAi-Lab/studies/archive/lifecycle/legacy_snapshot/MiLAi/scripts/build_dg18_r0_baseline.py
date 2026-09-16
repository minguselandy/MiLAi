"""Validate and receipt the DG-18 R0 baseline and ownership freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import tomllib

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs/dg18/r0-baseline-ownership-manifest.v0.1.json"
DEFAULT_OUTPUT_ROOT = ROOT / "var/dg18/r0"
EXPECTED_MANIFEST_SHA256 = (
    "b142d4e9a5e8c92b5618a6b5b0183a8c93b882f52484469e1ea1d49b8d79dde3"
)
EXPECTED_MANIFEST_SCHEMA = "milai.dg18.r0-baseline-ownership-manifest.v0.1"
EXPECTED_CASE_IDS = [
    "gpt4_8279ba03",
    "9a707b82",
    "2a1811e2",
    "0bb5a684",
    "2e6d26dc",
    "4dfccbf7",
    "gpt4_88806d6e",
    "a89d7624",
    "a82c026e",
    "88432d0a",
]
EXPECTED_CASE_IDS_SHA256 = (
    "694e5584a791cfa42f4b2b7bbc59835bb4e2462cda333c2c69f2ea5124207c79"
)
EXPECTED_ARTIFACT_IDS = {
    "dg15_goal",
    "dg17_goal",
    "dg18_goal",
    "a0_receipt",
    "a1_receipt",
    "a1_runtime_full_gate",
    "a2_receipt",
    "a2_runtime_full_gate",
    "a3_receipt",
    "a4_receipt",
    "a5_receipt",
    "a6_focused_postgresql_gate",
    "a6_sealed_execution_plan",
    "a6_terminal_receipt",
    "q6_initial_negative_receipt",
    "q6_authoritative_receipt",
    "q8_failed_run_receipt",
    "q8_authoritative_receipt",
    "local_gate_024",
    "opened_dev_full_label_free_inputs",
    "opened_dev_public_split",
    "opened_dev_answer_bearing_annotation",
    "formal_paper_test_source_ids",
    "formal_generalization_source_ids",
    "provider_last_executed_contract_receipt",
    "runtime_pyproject",
    "runtime_lock",
    "runtime_dense_default_settings",
    "schema_head_migration",
    "mcp_pyproject",
    "mcp_lock",
    "mcp_server",
    "mcp_tool_contract",
}


class DG18R0BaselineError(RuntimeError):
    """Raised when the frozen R0 evidence boundary does not validate."""


JsonObject = dict[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise DG18R0BaselineError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise DG18R0BaselineError(f"JSON artifact must be an object: {path}")
    return cast(JsonObject, value)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DG18R0BaselineError(message)


def _value(document: JsonObject, dotted_path: str) -> Any:
    value: Any = document
    for component in dotted_path.split("."):
        if not isinstance(value, dict) or component not in value:
            raise DG18R0BaselineError(f"missing required field: {dotted_path}")
        value = value[component]
    return value


def _expect(document: JsonObject, dotted_path: str, expected: object) -> None:
    actual = _value(document, dotted_path)
    _require(
        actual == expected,
        f"field mismatch for {dotted_path}: expected {expected!r}, got {actual!r}",
    )


def _bound_path(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    _require(not candidate.is_absolute(), f"bound artifact path is absolute: {relative_path}")
    root_resolved = root.resolve()
    resolved = (root_resolved / candidate).resolve()
    _require(
        resolved.is_relative_to(root_resolved),
        f"bound artifact escapes repository root: {relative_path}",
    )
    _require(resolved.is_file(), f"bound artifact is missing: {relative_path}")
    return resolved


def _artifact_index(manifest: JsonObject) -> dict[str, JsonObject]:
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise DG18R0BaselineError("manifest artifacts must be a list")
    artifacts: dict[str, JsonObject] = {}
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, dict):
            raise DG18R0BaselineError("manifest artifact entry must be an object")
        artifact = cast(JsonObject, raw_artifact)
        artifact_id = artifact.get("id")
        if not isinstance(artifact_id, str):
            raise DG18R0BaselineError("manifest artifact id must be a string")
        _require(artifact_id not in artifacts, f"duplicate manifest artifact id: {artifact_id}")
        artifacts[artifact_id] = artifact
    _require(
        set(artifacts) == EXPECTED_ARTIFACT_IDS,
        "manifest artifact IDs do not match the frozen R0 set",
    )
    return artifacts


def _validate_bound_artifacts(
    *, root: Path, artifacts: dict[str, JsonObject]
) -> dict[str, JsonObject]:
    documents: dict[str, JsonObject] = {}
    for artifact_id in sorted(artifacts):
        artifact = artifacts[artifact_id]
        relative_path = artifact.get("path")
        expected_digest = artifact.get("sha256")
        if not isinstance(relative_path, str):
            raise DG18R0BaselineError(f"missing path for {artifact_id}")
        if not isinstance(expected_digest, str):
            raise DG18R0BaselineError(f"missing sha256 for {artifact_id}")
        path = _bound_path(root, relative_path)
        actual_digest = _sha256(path)
        _require(
            actual_digest == expected_digest,
            f"sha256 mismatch for {artifact_id}: {actual_digest}",
        )
        expected_schema = artifact.get("expected_schema")
        expected_status = artifact.get("expected_status")
        if path.suffix == ".json":
            document = _load_json(path)
            documents[artifact_id] = document
            if expected_schema is not None:
                _expect(document, "schema", expected_schema)
            if expected_status is not None:
                _expect(document, "status", expected_status)
    return documents


def _validate_dg17_history(documents: dict[str, JsonObject]) -> None:
    a0 = documents["a0_receipt"]
    for field, a0_expected in {
        "formal_holdout_consumed": False,
        "summary.unique_case_count": 10,
        "summary.unique_required_evidence_count": 23,
        "summary.record_count": 161,
        "summary.path_count": 7,
        "label_boundary.product_path_label_access_count": 0,
        "gates.required_evidence_attributed_23_of_23": True,
        "gates.every_path_has_23_of_23": True,
    }.items():
        _expect(a0, field, a0_expected)

    for artifact_id, packing_loss in (("a1_receipt", 1), ("a2_receipt", 2)):
        receipt = documents[artifact_id]
        for field, expected in {
            "formal_holdout_consumed": False,
            "summaries.2048.case_count": 10,
            "summaries.2048.required_evidence_atom_hits": 10,
            "summaries.2048.required_evidence_atom_denominator": 23,
            "summaries.2048.answer_bearing_source_turn_hits": 9,
            "summaries.2048.answer_bearing_source_turn_denominator": 21,
            "summaries.2048.operator_ready_case_count": 4,
            "summaries.2048.operator_ready_case_denominator": 10,
            "summaries.2048.packing_loss_count": packing_loss,
            "summaries.2048.wrong_complete_count": 0,
        }.items():
            _expect(receipt, field, expected)

    for artifact_id, test_count in (
        ("a1_runtime_full_gate", 430),
        ("a2_runtime_full_gate", 434),
    ):
        gate = documents[artifact_id]
        _expect(gate, "pytest_passed", test_count)
        _expect(gate, "pytest_exit_code", 0)

    a3 = documents["a3_receipt"]
    for field, a3_expected in {
        "formal_holdout_consumed": False,
        "disposition.default_retrieval_policy": "NEUTRAL_NO_SOURCE_SCORE",
        "disposition.source_aware_ranking": "PARKED_NOT_IDENTIFIABLE",
        "disposition.structured_speaker_lineage": "IMPLEMENTED",
        "efficiency.model_calls": 0,
    }.items():
        _expect(a3, field, a3_expected)

    a4 = documents["a4_receipt"]
    for field, a4_expected in {
        "formal_holdout_consumed": False,
        "delta.answer_bearing_atom_hits": 1,
        "delta.answer_bearing_source_turn_hits": 1,
        "delta.operator_ready_cases": 0,
        "delta.candidate_noise_count": -3,
        "disposition.product_default_changed": False,
        "policy.model_calls": 0,
    }.items():
        _expect(a4, field, a4_expected)

    a5 = documents["a5_receipt"]
    for field, a5_expected in {
        "formal_holdout_consumed": False,
        "disposition.A5": "SAFETY_PASS_EVENT_PROJECTION_PARKED",
        "disposition.EVENT_OCCURRENCE_TIME": "FAIL_CLOSED_WITHOUT_EVENT_PROJECTION",
        "disposition.SOURCE_OBSERVED_TIME": "EXECUTABLE_BOUNDED_SCAN",
        "disposition.event_projection": "PARKED_NO_GENERAL_STRUCTURED_PRODUCER",
        "disposition.product_event_count_default_enabled": False,
        "disposition.schema_added": False,
    }.items():
        _expect(a5, field, a5_expected)

    a6_gate = documents["a6_focused_postgresql_gate"]
    _expect(a6_gate, "pytest_exit_code", 0)
    _expect(a6_gate, "model_calls", 0)
    a6_plan = documents["a6_sealed_execution_plan"]
    _expect(a6_plan, "formal_holdout_consumed", False)
    a6 = documents["a6_terminal_receipt"]
    for field, a6_expected in {
        "formal_holdout_consumed": False,
        "matched_score.delta.answer_bearing_atom_hits": 1,
        "matched_score.delta.answer_bearing_source_turn_hits": 1,
        "matched_score.delta.operator_ready_cases": 1,
        "matched_score.delta.candidate_noise_count": 49,
        "disposition.raw_evidence_dense": "PARKED_NO_SAFE_MATCHED_MEDIATOR_GAIN",
        "disposition.conditional_reranker": (
            "PARKED_NO_INCREMENTAL_Q8_GAIN_AND_NO_REQUIREMENT_AWARE_RECEIPT"
        ),
        "disposition.next_lane_may_enable_dense": False,
        "disposition.product_default_changed": False,
        "product_path.product_default_changed": False,
    }.items():
        _expect(a6, field, a6_expected)


def _validate_failure_lineage(documents: dict[str, JsonObject]) -> None:
    q6_negative = documents["q6_initial_negative_receipt"]
    _expect(q6_negative, "gate.checks.wrong_complete_zero", False)
    _expect(q6_negative, "release_claim_authorized", False)
    _expect(q6_negative, "formal_holdout_consumed", False)

    q6 = documents["q6_authoritative_receipt"]
    for field, expected in {
        "gate.checks.wrong_complete_zero": True,
        "release_claim_authorized": False,
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": [],
    }.items():
        _expect(q6, field, expected)

    q8_failure = documents["q8_failed_run_receipt"]
    for field, expected in {
        "labels_loaded": False,
        "automatic_retries": 0,
        "completed_reader_calls": 0,
        "stage": "LABEL_FREE_CONTEXT_BUILD",
    }.items():
        _expect(q8_failure, field, expected)

    q8 = documents["q8_authoritative_receipt"]
    for field, expected in {
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": [],
        "summaries.STRONG_DENSE.case_count": 10,
        "summaries.STRONG_DENSE.required_evidence_atom_denominator": 23,
        "summaries.STRONG_DENSE.required_evidence_set_coverage": 0.782608696,
        "summaries.STRONG_DENSE.exact_match_count": 2,
        "summaries.STRONG_DENSE.normalized_f1": 0.277685951,
        "decision.production_default_frozen": False,
        "decision.status": "CHARACTERIZED_NOT_A_PRODUCT_DEFAULT_DECISION",
        "claim_boundary.production_default_authorized": False,
        "claim_boundary.release_claim_authorized": False,
    }.items():
        _expect(q8, field, expected)


def _validate_local_gate(documents: dict[str, JsonObject]) -> None:
    gate = documents["local_gate_024"]
    for field, expected in {
        "reported_passed_tests": 367,
        "external_model_calls": 0,
        "runtime_or_database_started": False,
        "formal_holdout_consumed": False,
    }.items():
        _expect(gate, field, expected)
    commands = gate.get("commands")
    if not isinstance(commands, list):
        raise DG18R0BaselineError("local gate commands must be a list")
    actual = {
        command["name"]: command["status"]
        for command in commands
        if isinstance(command, dict) and "name" in command and "status" in command
    }
    _require(
        actual
        == {
            "runtime-unit": "PASS",
            "runtime-contract": "PASS",
            "runtime-strict-mypy": "PASS",
            "runtime-ruff": "PASS",
            "dg17-tests": "PASS",
            "dg17-ruff": "PASS",
            "dg17-strict-mypy": "PASS",
        },
        "local gate command coverage/status mismatch",
    )


def _source_ids(document: JsonObject, *, artifact_id: str) -> list[str]:
    values = document.get("source_ids")
    if not isinstance(values, list):
        raise DG18R0BaselineError(f"source_ids missing from {artifact_id}")
    _require(
        all(isinstance(value, str) for value in values),
        f"non-string source_id in {artifact_id}",
    )
    return cast(list[str], values)


def _validate_opened_dev_and_holdout(
    *, root: Path, artifacts: dict[str, JsonObject], documents: dict[str, JsonObject]
) -> None:
    opened = documents["opened_dev_public_split"]
    annotation = documents["opened_dev_answer_bearing_annotation"]
    opened_ids = _source_ids(opened, artifact_id="opened_dev_public_split")
    _require(opened_ids[:10] == EXPECTED_CASE_IDS, "opened-dev first-10 identity changed")
    _expect(opened, "formal_holdout_consumed", False)
    _expect(opened, "formal_source_id_overlap", [])
    _expect(annotation, "case_ids", EXPECTED_CASE_IDS)
    compact_ids = json.dumps(
        EXPECTED_CASE_IDS,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    _require(
        hashlib.sha256(compact_ids).hexdigest() == EXPECTED_CASE_IDS_SHA256,
        "ordered opened-dev case identity digest changed",
    )

    formal_ids: set[str] = set()
    for artifact_id in ("formal_paper_test_source_ids", "formal_generalization_source_ids"):
        artifact = artifacts[artifact_id]
        path = _bound_path(root, cast(str, artifact["path"]))
        formal = _load_json(path)
        formal_ids.update(_source_ids(formal, artifact_id=artifact_id))
    _require(
        not set(EXPECTED_CASE_IDS).intersection(formal_ids),
        "opened-dev identity overlaps formal holdout source IDs",
    )


def _validate_dense_default(path: Path) -> None:
    settings_source = path.read_text(encoding="utf-8")
    _require(
        "retrieval_evidence_dense_enabled: bool = False" in settings_source,
        "A6 dense retrieval is not explicitly disabled by default",
    )
    _require(
        "retrieval_evidence_dense_enabled: bool = True" not in settings_source,
        "A6 dense retrieval is enabled by default",
    )


def _validate_current_identity(
    *, root: Path, artifacts: dict[str, JsonObject], documents: dict[str, JsonObject]
) -> None:
    runtime_project_path = _bound_path(
        root, cast(str, artifacts["runtime_pyproject"]["path"])
    )
    runtime_project = tomllib.loads(runtime_project_path.read_text(encoding="utf-8"))
    _require(
        runtime_project.get("project", {}).get("name") == "milai-runtime"
        and runtime_project.get("project", {}).get("version") == "0.1.0",
        "runtime package identity changed",
    )

    mcp_project_path = _bound_path(root, cast(str, artifacts["mcp_pyproject"]["path"]))
    mcp_project = tomllib.loads(mcp_project_path.read_text(encoding="utf-8"))
    _require(
        mcp_project.get("project", {}).get("name") == "milai-mcp"
        and mcp_project.get("project", {}).get("version") == "0.1.0",
        "MCP package identity changed",
    )

    settings_path = _bound_path(
        root, cast(str, artifacts["runtime_dense_default_settings"]["path"])
    )
    _validate_dense_default(settings_path)

    migration_path = _bound_path(
        root, cast(str, artifacts["schema_head_migration"]["path"])
    )
    migration = migration_path.read_text(encoding="utf-8")
    _require('revision = "0044_dg17_evidence_dense"' in migration, "schema code head changed")
    _require('down_revision = "0043_dg17_speaker"' in migration, "schema ancestry changed")

    contract = documents["mcp_tool_contract"]
    _expect(contract, "contract_version", "agent.v1")
    _expect(contract, "transport.default", "stdio")
    _expect(contract, "transport.remote", "disabled")
    reader_lite = _value(contract, "profiles.reader-lite")
    _require(
        isinstance(reader_lite, list) and "milai_memory_resolve" in reader_lite,
        "MCP reader-lite profile does not expose milai_memory_resolve",
    )

    provider = documents["provider_last_executed_contract_receipt"]
    for field, expected in {
        "configuration.generation_contract.endpoint": "http://127.0.0.1:7860",
        "configuration.generation_contract.model_id": "Qwen3.6-35B-A3B-FP8",
        "configuration.generation_contract_sha256": (
            "25e40b1a978251ddd08df317e16d85f111fdb00a725b928a300979e6f071cd72"
        ),
        "configuration.prompt_contract_sha256": (
            "1eac3c3723c00f48f714c06aad00174337685e2c765d349553138435db43631d"
        ),
    }.items():
        _expect(provider, field, expected)


def _validate_manifest_semantics(manifest: JsonObject) -> None:
    for field, expected in {
        "schema": EXPECTED_MANIFEST_SCHEMA,
        "status": "FROZEN_INPUT",
        "goal_id": "DG-18",
        "artifact_policy.historical_artifacts_are_read_only": True,
        "artifact_policy.formal_holdout_consumed": False,
        "artifact_policy.provider_calls": 0,
        "artifact_policy.database_started": False,
        "opened_dev_identity.ordered_case_ids": EXPECTED_CASE_IDS,
        "opened_dev_identity.ordered_case_ids_digest.sha256": EXPECTED_CASE_IDS_SHA256,
        "opened_dev_identity.formal_source_id_overlap": [],
        "opened_dev_identity.formal_holdout_consumed": False,
        "ownership.double_owner_forbidden": True,
        "current_identity.schema.status": "EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE",
        "current_identity.provider.evidence_strength": "LAST_EXECUTED_FROZEN_CONTRACT",
        "current_identity.provider.current_live_verified": False,
        "holdout_boundary.formal_holdout_consumed": False,
        "holdout_boundary.formal_source_id_overlap": [],
    }.items():
        _expect(manifest, field, expected)

    expected_mapping = [
        ("A7_SLOT_AWARE_EXPANSION_AND_CONTEXT_PACKING", "R1_RUNTIME_LOCAL_CONTEXT_AND_SLOT_AWARE_EXPANSION"),
        ("NO_DIRECT_COUNTERPART", "R2_ACQUISITION_STATE_AND_TYPED_EVIDENCE_NOTES"),
        ("A8_RESIDUAL_LEXICAL_HINT_SHADOW", "R3_RESIDUAL_SEARCH_HINT_SHADOW"),
        ("A9_ONE_CALL_LIVE_RESIDUAL_ACQUISITION", "R4_ONE_CALL_LIVE_RESIDUAL_REFINDING"),
        ("A10_MATCHED_Q6_SUCCESSOR_CONFIRMATION", "R4_MATCHED_MEDIATOR_AND_READER_CONFIRMATION"),
        ("A11_STRATIFIED_OPENED_DEV", "POST_R4_EXPANDED_OPENED_DEV_SECTION_9_6"),
        ("NO_DIRECT_COUNTERPART", "R5_OPTIONAL_TWO_ROUND_REFINDING_PARKED_NOT_NEEDED"),
    ]
    mapping = manifest.get("successor_mapping")
    if not isinstance(mapping, list):
        raise DG18R0BaselineError("successor_mapping must be a list")
    actual_mapping = [
        (entry.get("dg17"), entry.get("dg18", [None])[0])
        for entry in mapping
        if isinstance(entry, dict)
    ]
    _require(actual_mapping == expected_mapping, "DG-17 to DG-18 successor mapping changed")


def _validate_holdout_absence(*, root: Path, manifest: JsonObject) -> list[str]:
    raw_paths = _value(manifest, "holdout_boundary.consumption_markers_required_absent")
    _require(isinstance(raw_paths, list), "holdout absence markers must be a list")
    expected_paths = [
        "var/dg11/splits/v1/paper-test-v1/consumption.json",
        "var/dg11/splits/v1/generalization-v2/consumption.json",
    ]
    _require(raw_paths == expected_paths, "holdout absence marker set changed")
    for relative_path in expected_paths:
        path = root / relative_path
        _require(not path.exists(), f"formal holdout consumption marker exists: {relative_path}")
    return expected_paths


def validate_manifest(
    *, manifest_path: Path = MANIFEST_PATH, root: Path = ROOT
) -> tuple[JsonObject, list[JsonObject]]:
    """Validate every bound R0 artifact and return receipt-safe identities."""

    _require(manifest_path.is_file(), f"manifest missing: {manifest_path}")
    actual_manifest_digest = _sha256(manifest_path)
    _require(
        actual_manifest_digest == EXPECTED_MANIFEST_SHA256,
        f"R0 manifest digest mismatch: {actual_manifest_digest}",
    )
    manifest = _load_json(manifest_path)
    _validate_manifest_semantics(manifest)
    artifacts = _artifact_index(manifest)
    documents = _validate_bound_artifacts(root=root, artifacts=artifacts)
    _validate_dg17_history(documents)
    _validate_failure_lineage(documents)
    _validate_local_gate(documents)
    _validate_opened_dev_and_holdout(
        root=root,
        artifacts=artifacts,
        documents=documents,
    )
    _validate_current_identity(root=root, artifacts=artifacts, documents=documents)
    absent_markers = _validate_holdout_absence(root=root, manifest=manifest)
    verified = [
        {
            "id": artifact_id,
            "kind": artifacts[artifact_id]["kind"],
            "path": artifacts[artifact_id]["path"],
            "sha256": artifacts[artifact_id]["sha256"],
        }
        for artifact_id in sorted(artifacts)
    ]
    validation = {
        "manifest_sha256": actual_manifest_digest,
        "artifact_count": len(verified),
        "holdout_consumption_markers_absent": absent_markers,
    }
    return validation, verified


def _observed_head(root: Path) -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    _require(completed.returncode == 0, "could not inspect repository HEAD")
    return completed.stdout.strip()


def build_receipt(
    *,
    run_id: str,
    output_root: Path,
    manifest_path: Path = MANIFEST_PATH,
    root: Path = ROOT,
) -> JsonObject:
    """Build a terminal R0 receipt in a fresh output directory."""

    _require(bool(run_id.strip()), "run_id must not be empty")
    _require(not output_root.exists(), "output exists; choose a fresh run ID")
    validation, verified = validate_manifest(manifest_path=manifest_path, root=root)
    observed_head = _observed_head(root)
    manifest = _load_json(manifest_path)
    expected_head = _value(manifest, "current_identity.repository.observed_head")
    _require(observed_head == expected_head, f"repository HEAD changed: {observed_head}")

    receipt: JsonObject = {
        "schema": "milai.dg18.r0-baseline-freeze-receipt.v0.1",
        "status": "PASS",
        "classification": "LOCAL_READ_ONLY_BASELINE_FREEZE / OPENED_DEVELOPMENT_ONLY",
        "run_id": run_id,
        "manifest": {
            "path": str(manifest_path.resolve().relative_to(root.resolve())),
            "sha256": validation["manifest_sha256"],
            "status": manifest["status"],
        },
        "verified_artifact_count": validation["artifact_count"],
        "verified_artifacts": verified,
        "baseline_summary": manifest["baseline_summary"],
        "opened_dev_identity": manifest["opened_dev_identity"],
        "ownership": manifest["ownership"],
        "successor_mapping": manifest["successor_mapping"],
        "current_identity": manifest["current_identity"],
        "gates": {
            "all_bound_paths_and_digests_match": True,
            "all_expected_receipt_schemas_and_statuses_match": True,
            "historical_failure_lineage_preserved": True,
            "opened_dev_case_identity_matches": True,
            "formal_source_id_overlap_zero": True,
            "formal_holdout_consumption_markers_absent": True,
            "a6_dense_default_disabled": True,
            "a6_product_default_unchanged": True,
            "ownership_and_successor_mapping_frozen": True,
        },
        "holdout_boundary": {
            "consumption_markers_absent": validation[
                "holdout_consumption_markers_absent"
            ],
            "formal_holdout_consumed": False,
            "formal_source_id_overlap": [],
        },
        "execution": {
            "automatic_retries": 0,
            "external_model_calls": 0,
            "provider_calls": 0,
            "database_started": False,
            "runtime_started": False,
            "formal_holdout_consumed": False,
        },
        "limitations": manifest["limitations"],
    }
    payload = (
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode()
        .replace(b"</", b"<\\/")
        + b"\n"
    )
    output_root.mkdir(parents=True)
    temporary = output_root / ".receipt.json.tmp"
    temporary.write_bytes(payload)
    os.replace(temporary, output_root / "receipt.json")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    try:
        receipt = build_receipt(run_id=args.run_id, output_root=output_root)
    except DG18R0BaselineError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path.resolve().relative_to(ROOT.resolve())),
                "receipt_sha256": _sha256(receipt_path),
                "verified_artifact_count": receipt["verified_artifact_count"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
