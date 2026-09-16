#!/usr/bin/env python3
"""Freeze and validate DG-28 S0/S1 acquisition-only preparation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for source_root in (ROOT, RUNTIME_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from milai.domain.requirement_state import canonical_sha256

from evals.dg28.acquisition_shadow import (
    ATTRIBUTIONS,
    CHANNELS,
    OFFICIAL_PROBES,
    build_acquisition_shadow,
)

RUN_LOCK = ROOT / "var/dg28/run-lock.json"
RESULTS = ROOT / "var/dg28/results.json"
TERMINAL = ROOT / "var/dg28/terminal.json"
FAILURE_INDEX = ROOT / "var/dg28/failure-index.jsonl"
DG27_TERMINAL = ROOT / "var/dg27/v03/attempt-004/terminal.json"
DG26_LOCK = ROOT / "var/dg26/run-lock.json"
RUN_ID = "dg28-s0-s1-acquisition-preparation-20260830-001"

BOUND_PATHS = (
    "MiLAi_Memory_Lifecycle_总_GOALS.md",
    "MiLAi_DG-28_可行动作排序与一次主动检索_GOALS.md",
    "evals/dg28/acquisition_shadow.py",
    "scripts/run_dg28_preparation.py",
    "tests/test_dg28_acquisition_preparation.py",
    "runtime/src/milai/application/evidence_acquisition.py",
    "runtime/src/milai/application/retrieval_audit_probe.py",
    "runtime/src/milai/persistence/retrieval_repository.py",
    str(ATTRIBUTIONS),
    str(OFFICIAL_PROBES),
    "var/dg24/s0/dg24-s0-freeze-20260829-008/input-only-case-manifest-v0.1.json",
    "var/dg26/run-lock.json",
    "var/dg27/v03/attempt-004/terminal.json",
)


class DG28PreparationRunnerError(RuntimeError):
    """The acquisition-only freeze cannot proceed or replay safely."""


def freeze(path: Path = RUN_LOCK) -> dict[str, Any]:
    """Seal S0/S1 only; explicitly prohibit every decision stage."""

    if path.exists():
        raise DG28PreparationRunnerError("DG28_PREPARATION_LOCK_ALREADY_EXISTS")
    if any(value.exists() for value in (RESULTS, TERMINAL, FAILURE_INDEX)):
        raise DG28PreparationRunnerError("DG28_UNAUTHORIZED_EFFECT_ARTIFACT_PRESENT")
    quality = _quality()
    if any(item["returncode"] != 0 for item in quality.values()):
        raise DG28PreparationRunnerError("DG28_PREPARATION_QUALITY_FAILED")
    dg27 = _verified_digest_object(DG27_TERMINAL, "terminal_digest")
    h1 = _mapping(dg27.get("claims"), "DG27 claims").get(
        "DG27_H1_DECISION_BOUNDARY_REPAIR"
    )
    if h1 == "SUPPORTED":
        raise DG28PreparationRunnerError(
            "DG28_DG27_H1_NOW_SUPPORTED_USE_FINAL_EFFECT_FREEZE"
        )
    shadow = build_acquisition_shadow(ROOT)
    records = _sequence(shadow.get("records"), "shadow records")
    per_channel_caps = {
        channel: sorted(
            {
                int(call["requested_audit_cap"])
                for raw_record in records
                for record in [_mapping(raw_record, "shadow record")]
                for raw_call in _sequence(record.get("channel_calls"), "channel calls")
                for call in [_mapping(raw_call, "channel call")]
                if call.get("channel") == channel
                and isinstance(call.get("requested_audit_cap"), int)
            }
        )
        for channel in CHANNELS
    }
    config: dict[str, Any] = {
        "D0": "CURRENT_PRODUCT_FAITHFUL_ROUTE_REFERENCE_DG26_FTS_RAW_TOP8",
        "D1": "EACH_EXISTING_OFFICIAL_CHANNEL_ONCE_PLUS_IDENTITY_UNION",
        "official_channels": list(CHANNELS),
        "official_executor_identity": shadow["official_executor_identity"],
        "repository_identity": shadow["repository_identity"],
        "candidate_budget": {
            "per_channel_frozen_requested_caps": per_channel_caps,
            "maximum_theoretical_occurrences_per_query_requirement": 286,
            "actual_union_candidates_by_query_requirement": {
                f"{record['case_id']}:{record['requirement_id']}": record[
                    "union_candidate_count"
                ]
                for raw_record in records
                for record in [_mapping(raw_record, "shadow record")]
            },
            "identity_dedup_only": True,
        },
        "new_cue_generation": False,
        "model_action_selection": False,
        "second_search_round": False,
        "new_retriever": False,
        "reader_changed": False,
        "decision_boundary_changed": False,
        "candidate_feature_flag": "OFF",
    }
    material: dict[str, Any] = {
        "schema": "milai.dg28.acquisition-preparation.run-lock.v0.1",
        "goal_id": "DG-28",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "review_status": "INTERNAL_PROVISIONAL",
        "execution_authority": "MILA-ML-MASTER@1.2",
        "status": "S0_S1_ACQUISITION_ONLY_PREPARED",
        "entry": {
            "preparation_authorized": True,
            "final_effect_authorized": False,
            "final_effect_blocker": "DG27_H1_NOT_SUPPORTED",
            "DG27_status": dg27["status"],
            "DG27_reason_code": dg27["reason_code"],
            "DG27_H1": h1,
            "DG27_terminal": _identity(DG27_TERMINAL),
        },
        "S0_freeze": {
            "target_group_count": shadow["target_group_count"],
            "query_requirement_count": shadow["query_requirement_count"],
            "target_reasons": {
                "CHANNEL_ELIGIBLE_NOT_INVOKED": 6,
                "CHANNEL_CUTOFF_DROP": 1,
            },
            "target_groups": shadow["target_groups"],
            "D0_reference": _identity(DG26_LOCK),
            "channel_availability_frozen": True,
            "snapshot_frozen": True,
            "total_candidate_budget_frozen": True,
        },
        "S1_official_union": shadow,
        "config": config,
        "config_digest": canonical_sha256(config),
        "quality_gates": quality,
        "bound_identities": [_identity(ROOT / value) for value in BOUND_PATHS],
        "decision_boundary": {
            "gate_executed": False,
            "binding_executed": False,
            "requirement_state_derived": False,
            "sufficiency_executed": False,
            "complete_asserted": False,
            "reader_executed": False,
            "product_output_changed": False,
        },
        "effect_artifacts": {
            "results_json_written": False,
            "terminal_json_written": False,
            "failure_index_written": False,
        },
        "safety": {
            "candidate_feature_flag": "OFF",
            "new_official_calls": 0,
            "provider_calls": 0,
            "reader_calls": 0,
            "canonical_mutations": 0,
            "formal_holdout_used": False,
            "public_mcp_schema_changed": False,
            "postgresql_schema_changed": False,
            "architecture_v1_changed": False,
        },
        "next_authorized_action": (
            "STOP_AFTER_S1_DG27_H1_NOT_SUPPORTED_NO_FINAL_EFFECT"
        ),
    }
    material["lock_digest"] = canonical_sha256(material)
    _write_exclusive(path, material)
    return material


def validate(path: Path = RUN_LOCK) -> dict[str, Any]:
    lock = _verified_digest_object(path, "lock_digest")
    if lock.get("schema") != "milai.dg28.acquisition-preparation.run-lock.v0.1":
        raise DG28PreparationRunnerError("DG28_PREPARATION_SCHEMA_DRIFT")
    for raw in _sequence(lock.get("bound_identities"), "bound identities"):
        expected = _mapping(raw, "bound identity")
        if _identity(ROOT / str(expected["path"])) != expected:
            raise DG28PreparationRunnerError(f"DG28_BOUND_DRIFT:{expected['path']}")
    observed_shadow = build_acquisition_shadow(ROOT)
    frozen_shadow = _mapping(lock.get("S1_official_union"), "official union")
    if observed_shadow.get("shadow_digest") != frozen_shadow.get("shadow_digest"):
        raise DG28PreparationRunnerError("DG28_SHADOW_REPLAY_DRIFT")
    decision = _mapping(lock.get("decision_boundary"), "decision boundary")
    if any(decision.values()):
        raise DG28PreparationRunnerError("DG28_DECISION_CHAIN_WAS_ENTERED")
    if any(value.exists() for value in (RESULTS, TERMINAL, FAILURE_INDEX)):
        raise DG28PreparationRunnerError("DG28_UNAUTHORIZED_EFFECT_ARTIFACT_PRESENT")
    return {
        "valid": True,
        "status": lock["status"],
        "target_groups": frozen_shadow["target_group_count"],
        "union_candidates": sum(
            int(_mapping(item, "record")["union_candidate_count"])
            for item in _sequence(frozen_shadow.get("records"), "records")
        ),
        "target_groups_with_candidate_shadow_hits": sum(
            bool(_mapping(hit, "hit").get("candidate_evidence_ids"))
            for raw_record in _sequence(frozen_shadow.get("records"), "records")
            for record in [_mapping(raw_record, "record")]
            for hit in _sequence(
                record.get("target_group_candidate_hits"), "target hits"
            )
        ),
        "final_effect_authorized": False,
        "lock_digest": lock["lock_digest"],
    }


def _quality() -> dict[str, Any]:
    return {
        "targeted_tests": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/pytest"),
                "-q",
                "tests/test_dg28_acquisition_preparation.py",
            ]
        ),
        "lint": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/ruff"),
                "check",
                "evals/dg28/acquisition_shadow.py",
                "scripts/run_dg28_preparation.py",
                "tests/test_dg28_acquisition_preparation.py",
            ]
        ),
        "typecheck": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/mypy"),
                "--config-file",
                "runtime/pyproject.toml",
                "evals/dg28/acquisition_shadow.py",
                "scripts/run_dg28_preparation.py",
            ]
        ),
    }


def _run_quality(command: list[str]) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(RUNTIME_SRC), str(ROOT), environment.get("PYTHONPATH", "")]
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "stdout_tail": completed.stdout[-4_000:],
        "stderr_tail": completed.stderr[-4_000:],
    }


def _identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise DG28PreparationRunnerError(f"DG28_PATH_MISSING:{path}")
    return {
        "path": str(path.resolve().relative_to(ROOT)),
        "size": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verified_digest_object(path: Path, digest_key: str) -> dict[str, Any]:
    value = _object(path)
    material = dict(value)
    observed = material.pop(digest_key, None)
    if observed != canonical_sha256(material):
        raise DG28PreparationRunnerError(f"DG28_DIGEST_MISMATCH:{path}")
    return value


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG28PreparationRunnerError(f"DG28_JSON_OBJECT_REQUIRED:{path}")
    return value


def _mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DG28PreparationRunnerError(f"DG28_MAPPING_REQUIRED:{source}")
    return value


def _sequence(value: object, source: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DG28PreparationRunnerError(f"DG28_SEQUENCE_REQUIRED:{source}")
    return value


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "validate"))
    return parser


def main() -> int:
    args = _parser().parse_args()
    output = freeze() if args.command == "freeze" else validate()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
