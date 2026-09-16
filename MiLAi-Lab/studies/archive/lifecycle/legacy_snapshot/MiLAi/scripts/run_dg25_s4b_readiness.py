#!/usr/bin/env python3
"""Build a fresh pre-label DG-25 S4B scoring-readiness package."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_SCRIPT_PATH = Path(__file__)
ROOT = _SCRIPT_PATH.resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (str(ROOT), str(RUNTIME_SRC)):
    if value not in sys.path:
        sys.path.insert(0, value)

from evals.dg25.s4b_readiness import (
    READINESS_ARTIFACT_FILENAMES,
    S4B_READINESS_ROOT,
    authorization_request,
    build_s4b_readiness_materials,
    file_identity,
)

SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
QUALITY_ROOT = Path("var/dg25/quality")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--quality-receipt", type=Path, required=True)
    args = parser.parse_args()
    return run_readiness(
        run_id=str(args.run_id), quality_receipt=args.quality_receipt, root=ROOT
    )


def run_readiness(*, run_id: str, quality_receipt: Path, root: Path) -> int:
    root = root.resolve()
    output = _validated_output(root, run_id)
    quality_path = _validated_quality_path(root, quality_receipt)
    if output.is_symlink() or output.exists():
        raise FileExistsError("DG25_S4B_READINESS_EXISTING_OUTPUT_REJECTED")

    materials = build_s4b_readiness_materials(
        root=root, run_id=run_id, quality_receipt_path=quality_path
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=output.parent))
    try:
        artifact_identities: dict[str, dict[str, Any]] = {}
        for key, filename in READINESS_ARTIFACT_FILENAMES.items():
            path = temporary / filename
            _write_json(path, materials[key])
            identity = file_identity(root, path)
            identity["path"] = (output / filename).relative_to(root).as_posix()
            artifact_identities[key] = identity

        execution = materials["execution_manifest"]
        bindings = _mapping(
            execution.get("authorization_bindings"), "authorization bindings"
        )
        request = authorization_request(bindings)
        receipt: dict[str, Any] = {
            "schema": "milai.dg25.s4b-readiness-receipt.v0.1",
            "run_id": run_id,
            "status": (
                "PASS_DG25_S4B_READINESS_PENDING_FRESH_INDEPENDENT_"
                "SCORING_AUTHORIZATION"
            ),
            "artifacts": artifact_identities,
            "quality_receipt": file_identity(root, quality_path),
            "failure_index_snapshot": dict(execution["failure_index_snapshot"]),
            "authorization_request": request,
            "checks": dict(materials["validation_report"]["checks"]),
            "labels_loaded": False,
            "registry_content_loaded": False,
            "effect_scoring_executed": False,
            "reader_model_provider_controller_calls": 0,
            "formal_holdout_consumed": False,
            "candidate_default": False,
            "automatic_retries": 0,
        }
        _write_json(temporary / "receipt.json", receipt)
        temporary.rename(output)
    except Exception:
        _remove_partial_directory(temporary)
        raise

    print(
        json.dumps(
            {
                "status": receipt["status"],
                "output": output.relative_to(root).as_posix(),
                "authorization_request_digest": request["request_digest"],
                "scorer_source_amendment_digest": materials[
                    "scorer_source_amendment"
                ]["amendment_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


def _validated_output(root: Path, run_id: str) -> Path:
    if run_id in {".", ".."} or SAFE_COMPONENT.fullmatch(run_id) is None:
        raise ValueError("DG25_S4B_READINESS_RUN_ID_NOT_SAFE")
    parent = root / S4B_READINESS_ROOT
    if parent.resolve(strict=False) != parent.absolute():
        raise ValueError("DG25_S4B_READINESS_ROOT_SYMLINK_OR_DRIFT")
    output = parent / run_id
    if output.absolute().parent != parent.absolute():
        raise ValueError("DG25_S4B_READINESS_OUTPUT_NOT_DIRECT_CHILD")
    return output


def _validated_quality_path(root: Path, requested: Path) -> Path:
    if requested.is_absolute() or not requested.parts or ".." in requested.parts:
        raise ValueError("DG25_S4B_QUALITY_RECEIPT_PATH_INVALID")
    quality_root = (root / QUALITY_ROOT).resolve(strict=False)
    path = root / requested
    if path.is_symlink() or not path.is_file():
        raise ValueError("DG25_S4B_QUALITY_RECEIPT_NOT_REGULAR_FILE")
    try:
        path.resolve(strict=True).relative_to(quality_root)
    except ValueError as exc:
        raise ValueError("DG25_S4B_QUALITY_RECEIPT_OUTSIDE_QUALITY_ROOT") from exc
    return path


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _remove_partial_directory(path: Path) -> None:
    if not path.exists() or path.is_symlink():
        return
    for child in path.iterdir():
        if child.is_file() and not child.is_symlink():
            child.unlink()
    path.rmdir()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
