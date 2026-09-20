#!/usr/bin/env python3
"""Build and verify the current Product conformance receipt.

The frozen logical-architecture bundle is intentionally not edited by this
tool.  It resolves the bundle crosswalk against the current Product tree and
records what is, and is not, behaviorally verified.  Reference presence is
not treated as behavioral proof: current goals, invariants, transactions and
roles remain ``UNVERIFIED`` until an execution receipt is attached to them.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUS_VALUES = {"PASS", "NOT_APPLICABLE", "DEVIATION", "UNVERIFIED"}
CURRENT_CATEGORIES = ("goals", "invariants", "transactions", "roles")
ALL_CATEGORIES = (*CURRENT_CATEGORIES, "freeze_gates")
SCHEMA = "milai-architecture-conformance-v1"
MAP_SCHEMA = "milai-invariant-test-map-v1"

# This is the external trust anchor already used by the Product extraction
# workflow.  The frozen bundle must keep this digest stable until a new
# architecture version is intentionally published.
FROZEN_ARCHITECTURE_MANIFEST_SHA256 = (
    "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
)

SCRIPT = Path(__file__).resolve()
PRODUCT_ROOT = SCRIPT.parents[1]
WORKSPACE_ROOT = PRODUCT_ROOT.parent
ARCHITECTURE_ROOT = PRODUCT_ROOT / "architecture" / "v1.0"
CROSSWALK_PATH = ARCHITECTURE_ROOT / "crosswalk.json"
ARCHITECTURE_MANIFEST_PATH = ARCHITECTURE_ROOT / "architecture_manifest.json"
PRODUCT_MANIFEST_PATH = PRODUCT_ROOT / "product.manifest.json"
CONFORMANCE_ROOT = PRODUCT_ROOT / "docs" / "conformance"
RECEIPT_PATH = CONFORMANCE_ROOT / "current-conformance.json"
MAP_PATH = CONFORMANCE_ROOT / "invariant-test-map.json"
REPORT_PATH = CONFORMANCE_ROOT / "CURRENT_ARCHITECTURE_CONFORMANCE.md"
REVALIDATION_ROOT = PRODUCT_ROOT / "docs" / "revalidation"
REVALIDATION_SCHEMA = "milai-behavior-revalidation-v1"
REVALIDATION_COVERAGE = {"SCOPED", "COMPLETE"}
ARCHIVE_CLASSIFICATION_PATH = (
    WORKSPACE_ROOT / "MiLAi-Artifact-Archive" / "manifests" / "source-classification.jsonl"
)


class ConformanceError(RuntimeError):
    """A structural or identity check prevented receipt verification."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConformanceError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConformanceError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git_commit() -> str:
    git = shutil.which("git")
    if git is None:
        raise ConformanceError("git executable is not available")
    result = subprocess.run(  # noqa: S603
        [git, "rev-parse", "HEAD"],
        cwd=WORKSPACE_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ConformanceError(
            "cannot determine Product source commit: "
            + (result.stderr.strip() or f"git exited {result.returncode}")
        )
    commit = result.stdout.strip()
    if len(commit) != 40:
        raise ConformanceError(f"unexpected Product source commit: {commit!r}")
    return commit


def _commit_exists(commit: str) -> bool:
    git = shutil.which("git")
    if git is None:
        return False
    result = subprocess.run(  # noqa: S603
        [git, "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=WORKSPACE_ROOT,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _path_part(reference: str) -> str:
    return reference.split("#", 1)[0].split("::", 1)[0]


def _safe_product_path(reference: str) -> Path | None:
    path_text = _path_part(reference)
    candidate = Path(path_text)
    if not path_text or candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved_root = PRODUCT_ROOT.resolve()
    resolved = (resolved_root / candidate).resolve(strict=False)
    if not resolved.is_relative_to(resolved_root):
        return None
    return resolved


def _test_node(reference: str) -> str | None:
    if "::" not in reference:
        return None
    return reference.rsplit("::", 1)[1]


def _validate_revalidation_test_reference(
    reference: Any,
    *,
    function_cache: dict[Path, set[str]],
) -> str:
    if not isinstance(reference, str) or not reference.strip():
        raise ConformanceError("revalidation test reference must be a non-empty string")
    path = _safe_product_path(reference)
    node = _test_node(reference)
    if path is None or node is None or not path.is_file():
        raise ConformanceError(
            f"revalidation test reference is not a current Product test: {reference}"
        )
    names = function_cache.setdefault(path, _function_names(path))
    if node not in names:
        raise ConformanceError(f"revalidation test node does not exist: {reference}")
    return reference


def _load_revalidation_receipts(
    *,
    crosswalk: dict[str, Any],
    product_manifest_sha256: str,
    product_tree_sha256: str,
    architecture_manifest_sha256: str,
) -> dict[str, list[dict[str, Any]]]:
    """Validate behavior receipts and return their explicit architecture claims."""

    known_ids = {
        item.get("id")
        for category in CURRENT_CATEGORIES
        for item in crosswalk.get(category, [])
        if isinstance(item, dict)
    }
    claims_by_id: dict[str, list[dict[str, Any]]] = {}
    if not REVALIDATION_ROOT.is_dir():
        return claims_by_id

    function_cache: dict[Path, set[str]] = {}
    seen_debt_ids: set[str] = set()
    for receipt_path in sorted(REVALIDATION_ROOT.glob("*/receipt.json")):
        receipt = _read_json(receipt_path)
        if receipt.get("schema_version") != REVALIDATION_SCHEMA:
            raise ConformanceError(f"revalidation receipt schema mismatch: {receipt_path}")
        debt_id = receipt.get("debt_id")
        state = receipt.get("state")
        if not isinstance(debt_id, str) or not debt_id:
            raise ConformanceError(f"revalidation receipt has no debt_id: {receipt_path}")
        if debt_id in seen_debt_ids:
            raise ConformanceError(f"duplicate revalidation debt_id: {debt_id}")
        seen_debt_ids.add(debt_id)
        if state not in {"OPEN", "FIXED", "OBSOLETE", "NEEDS_REVALIDATION"}:
            raise ConformanceError(f"invalid revalidation state for {debt_id}: {state!r}")
        decision = receipt.get("decision")
        if not isinstance(decision, dict) or decision.get("state") != state:
            raise ConformanceError(f"revalidation {debt_id} decision/state mismatch")

        baseline = receipt.get("baseline")
        if not isinstance(baseline, dict):
            raise ConformanceError(f"revalidation baseline is missing: {receipt_path}")
        expected_identity = {
            "architecture_version": "1.0.0",
            "architecture_manifest_sha256": architecture_manifest_sha256,
            "product_manifest_sha256": product_manifest_sha256,
            "product_tree_sha256": product_tree_sha256,
        }
        for field, expected in expected_identity.items():
            if baseline.get(field) != expected:
                raise ConformanceError(f"revalidation {debt_id} is bound to a different {field}")
        baseline_commit = baseline.get("product_commit")
        if not isinstance(baseline_commit, str) or not _commit_exists(baseline_commit):
            raise ConformanceError(f"revalidation {debt_id} baseline commit is not in Git")

        execution = receipt.get("execution")
        execution_status = execution.get("status") if isinstance(execution, dict) else None
        if execution_status not in {"PASS", "FAIL"}:
            raise ConformanceError(f"revalidation {debt_id} has no valid execution result")
        if state == "FIXED" and execution_status != "PASS":
            raise ConformanceError(f"revalidation {debt_id} marks FIXED without PASS")
        if state == "OPEN" and execution_status != "FAIL":
            raise ConformanceError(f"revalidation {debt_id} marks OPEN without FAIL")
        reproduction = receipt.get("reproduction")
        if not isinstance(reproduction, dict):
            raise ConformanceError(f"revalidation {debt_id} reproduction is missing")
        commands = reproduction.get("commands")
        if not isinstance(commands, list) or not commands:
            raise ConformanceError(f"revalidation {debt_id} has no reproduction command")
        for command in commands:
            if not isinstance(command, dict) or command.get("status") != "PASS":
                raise ConformanceError(f"revalidation {debt_id} has a non-passing command")
            if command.get("exit_code") != 0:
                raise ConformanceError(f"revalidation {debt_id} has a non-zero command")
        test_references = reproduction.get("tests")
        if not isinstance(test_references, list) or not test_references:
            raise ConformanceError(f"revalidation {debt_id} has no test references")
        for reference in test_references:
            _validate_revalidation_test_reference(reference, function_cache=function_cache)

        case_ids: dict[str, set[str]] = {"positive_cases": set(), "negative_cases": set()}
        case_statuses: dict[str, str] = {}
        for case_field in case_ids:
            cases = receipt.get(case_field)
            if not isinstance(cases, list) or not cases:
                raise ConformanceError(f"revalidation {debt_id} has no {case_field}")
            for case in cases:
                if not isinstance(case, dict):
                    raise ConformanceError(
                        f"revalidation {debt_id} has an invalid {case_field} entry"
                    )
                case_id = case.get("case_id")
                if not isinstance(case_id, str) or not case_id or case_id in case_ids[case_field]:
                    raise ConformanceError(f"revalidation {debt_id} has a duplicate case id")
                case_status = case.get("status")
                if case_status not in {"PASS", "FAIL"}:
                    raise ConformanceError(f"revalidation {debt_id} has an invalid case status")
                case_tests = case.get("tests")
                if not isinstance(case_tests, list) or not case_tests:
                    raise ConformanceError(f"revalidation case {case_id} has no tests")
                for reference in case_tests:
                    _validate_revalidation_test_reference(reference, function_cache=function_cache)
                case_ids[case_field].add(case_id)
                case_statuses[case_id] = case_status

        failed_case_ids = {
            case_id for case_id, case_status in case_statuses.items() if case_status == "FAIL"
        }
        if execution_status == "PASS" and failed_case_ids:
            raise ConformanceError(f"revalidation {debt_id} passes despite failed behavior cases")
        if execution_status == "FAIL" and not failed_case_ids:
            raise ConformanceError(f"revalidation {debt_id} fails without a failed behavior case")

        claims = receipt.get("conformance_claims")
        if not isinstance(claims, list) or not claims:
            raise ConformanceError(f"revalidation {debt_id} has no conformance claims")
        receipt_reference = receipt_path.relative_to(PRODUCT_ROOT).as_posix()
        for claim in claims:
            if not isinstance(claim, dict):
                raise ConformanceError(f"revalidation {debt_id} has an invalid conformance claim")
            architecture_id = claim.get("architecture_id")
            coverage = claim.get("coverage")
            claim_status = claim.get("status")
            if architecture_id not in known_ids:
                raise ConformanceError(
                    f"revalidation {debt_id} claims unknown architecture id: {architecture_id}"
                )
            if coverage not in REVALIDATION_COVERAGE or claim_status not in {"PASS", "FAIL"}:
                raise ConformanceError(f"revalidation {debt_id} has an invalid claim status")
            if (
                not isinstance(claim.get("covered_statement"), str)
                or not claim["covered_statement"]
            ):
                raise ConformanceError(f"revalidation {debt_id} claim lacks covered_statement")
            for side in ("positive_case_ids", "negative_case_ids"):
                case_field = "positive_cases" if side.startswith("positive") else "negative_cases"
                case_values = claim.get(side)
                if not isinstance(case_values, list) or not case_values:
                    raise ConformanceError(f"revalidation {debt_id} claim lacks {side}")
                if not set(case_values).issubset(case_ids[case_field]):
                    raise ConformanceError(
                        f"revalidation {debt_id} claim references an unknown {side}"
                    )
            referenced_case_ids = set(claim["positive_case_ids"]) | set(claim["negative_case_ids"])
            referenced_failures = referenced_case_ids & failed_case_ids
            if claim_status == "PASS" and referenced_failures:
                raise ConformanceError(
                    f"revalidation {debt_id} PASS claim references a failed case"
                )
            if claim_status == "FAIL" and not referenced_failures:
                raise ConformanceError(f"revalidation {debt_id} FAIL claim has no failed case")
            claim_record = dict(claim)
            claim_record["debt_id"] = debt_id
            claim_record["receipt"] = receipt_reference
            claim_record["execution_status"] = execution_status
            claims_by_id.setdefault(str(architecture_id), []).append(claim_record)
    return claims_by_id


def _function_names(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return set()
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }


def _archive_manifest_records() -> dict[str, dict[str, Any]]:
    if not ARCHIVE_CLASSIFICATION_PATH.is_file():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for line in ARCHIVE_CLASSIFICATION_PATH.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            records[value["path"]] = value
    return records


def _is_archive_only_reference(reference: str) -> bool:
    path = _path_part(reference)
    return path.startswith("docs/reviews/submissions/") and path.endswith((".tar.gz", ".zip"))


def _reference_record(
    reference: Any,
    *,
    kind: str,
    archive_records: dict[str, dict[str, Any]],
    function_cache: dict[Path, set[str]],
) -> dict[str, Any]:
    if not isinstance(reference, str) or not reference.strip():
        return {"reference": reference, "status": "DEVIATION", "reason": "empty reference"}

    path_text = _path_part(reference)
    path = _safe_product_path(reference)
    if path is None:
        return {
            "reference": reference,
            "status": "DEVIATION",
            "reason": "unsafe Product-relative path",
        }

    if path.is_file():
        record: dict[str, Any] = {
            "reference": reference,
            "path": path.relative_to(PRODUCT_ROOT).as_posix(),
            "status": "PASS",
        }
        node = _test_node(reference)
        if node is not None:
            names = function_cache.setdefault(path, _function_names(path))
            if node not in names:
                record["status"] = "DEVIATION"
                record["reason"] = f"test node does not exist: {node}"
            else:
                record["node"] = node
        return record

    if kind == "freeze_evidence" and _is_archive_only_reference(reference):
        archive_record = archive_records.get(path_text)
        record = {
            "reference": reference,
            "status": "UNVERIFIED",
            "availability": "ARCHIVE_MANIFEST_ONLY",
            "archive_owner": "MiLAi-Artifact-Archive",
            "archive_manifest": "MiLAi-Artifact-Archive/manifests/source-classification.jsonl",
        }
        if archive_record is None:
            record["status"] = "DEVIATION"
            record["reason"] = "archive classification record is missing"
        else:
            record["declared_sha256"] = archive_record.get("sha256")
        return record

    return {
        "reference": reference,
        "path": path_text,
        "status": "DEVIATION",
        "reason": "reference target does not exist in current Product",
    }


def _reference_group(
    references: Any,
    *,
    kind: str,
    required: bool,
    archive_records: dict[str, dict[str, Any]],
    function_cache: dict[Path, set[str]],
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(references, list) or not references:
        return [], "DEVIATION" if required else "NOT_APPLICABLE"
    records = [
        _reference_record(
            reference,
            kind=kind,
            archive_records=archive_records,
            function_cache=function_cache,
        )
        for reference in references
    ]
    statuses = {record["status"] for record in records}
    if "DEVIATION" in statuses:
        return records, "DEVIATION"
    if "UNVERIFIED" in statuses:
        return records, "UNVERIFIED"
    return records, "PASS"


def _category_item(
    item: dict[str, Any],
    *,
    category: str,
    archive_records: dict[str, dict[str, Any]],
    function_cache: dict[Path, set[str]],
    behavioral_claims: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    identifier = item.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ConformanceError(f"{category} item has no valid id")

    implementation_evidence, implementation_status = _reference_group(
        item.get("implementations"),
        kind="implementation",
        required=True,
        archive_records=archive_records,
        function_cache=function_cache,
    )
    test_evidence, test_status = _reference_group(
        item.get("tests"),
        kind="test",
        required=True,
        archive_records=archive_records,
        function_cache=function_cache,
    )
    positive_evidence, positive_status = _reference_group(
        item.get("positive_tests", []),
        kind="test",
        required=False,
        archive_records=archive_records,
        function_cache=function_cache,
    )
    negative_evidence, negative_status = _reference_group(
        item.get("negative_tests", []),
        kind="test",
        required=False,
        archive_records=archive_records,
        function_cache=function_cache,
    )

    # Current behavior is deliberately not inferred from reference presence.
    # Only an identity-bound execution receipt with explicit COMPLETE coverage
    # can promote an item to PASS.  Scoped receipts remain evidence without
    # becoming a broad architecture claim.
    reference_statuses = {
        implementation_status,
        test_status,
        positive_status,
        negative_status,
    }
    if "DEVIATION" in reference_statuses:
        status = "DEVIATION"
    else:
        status = "UNVERIFIED"

    execution_receipts = [
        {
            "receipt": claim["receipt"],
            "debt_id": claim["debt_id"],
            "coverage": claim["coverage"],
            "status": claim["status"],
            "execution_status": claim["execution_status"],
            "covered_statement": claim["covered_statement"],
            "positive_case_ids": claim["positive_case_ids"],
            "negative_case_ids": claim["negative_case_ids"],
            "limits": claim.get("limits", []),
        }
        for claim in behavioral_claims
    ]
    complete_claims = [
        claim
        for claim in behavioral_claims
        if claim["coverage"] == "COMPLETE"
        and claim["status"] == "PASS"
        and claim["execution_status"] == "PASS"
    ]
    failed_claims = [
        claim
        for claim in behavioral_claims
        if claim["status"] == "FAIL" or claim["execution_status"] == "FAIL"
    ]
    if failed_claims:
        verification = {
            "behavioral_execution": "FAIL",
            "method": "identity-bound behavior revalidation receipt",
            "execution_receipts": execution_receipts,
            "reason": (
                "A current behavior gap was reproduced. The frozen item remains "
                "UNVERIFIED because the receipt does not itself assert an "
                "architecture DEVIATION."
            ),
        }
    elif status != "DEVIATION" and complete_claims:
        status = "PASS"
        verification = {
            "behavioral_execution": "PASS",
            "method": "identity-bound behavior revalidation receipt",
            "execution_receipts": execution_receipts,
            "reason": (
                "At least one receipt explicitly covers the frozen item with "
                "passing positive and negative cases."
            ),
        }
    elif behavioral_claims:
        verification = {
            "behavioral_execution": "SCOPED",
            "method": "identity-bound behavior revalidation receipt",
            "execution_receipts": execution_receipts,
            "reason": (
                "The receipts prove scoped subclaims; the frozen item remains "
                "UNVERIFIED until a COMPLETE claim covers it."
            ),
        }
    else:
        verification = {
            "behavioral_execution": "UNVERIFIED",
            "method": "crosswalk reference resolution only",
            "reason": (
                "Mapped implementation and test references resolve, but this "
                "receipt does not treat test count or test presence as behavioral "
                "conformance proof."
            ),
        }

    result: dict[str, Any] = {
        "id": identifier,
        "name": item.get("name"),
        "statement": item.get("statement"),
        "owner_plane": item.get("owner_plane"),
        "design_refs": item.get("design_refs", []),
        "implementation_evidence": implementation_evidence,
        "test_evidence": test_evidence,
        "positive_test_evidence": positive_evidence,
        "negative_test_evidence": negative_evidence,
        "reference_integrity": ("DEVIATION" if "DEVIATION" in reference_statuses else "PASS"),
        "status": status,
        "verification": verification,
    }
    return {key: value for key, value in result.items() if value is not None}


def _freeze_gate_item(
    item: dict[str, Any],
    *,
    archive_records: dict[str, dict[str, Any]],
    function_cache: dict[Path, set[str]],
) -> dict[str, Any]:
    evidence, evidence_status = _reference_group(
        item.get("evidence"),
        kind="freeze_evidence",
        required=True,
        archive_records=archive_records,
        function_cache=function_cache,
    )
    result_status = evidence_status
    result: dict[str, Any] = {
        "id": item.get("id"),
        "name": item.get("name"),
        "declared_status": item.get("status"),
        "evidence": evidence,
        "reference_integrity": evidence_status,
        "status": result_status,
        "verification": {
            "scope": "frozen architecture evidence",
            "method": "bundle lock plus evidence reference resolution",
            "behavioral_execution": "NOT_APPLICABLE",
        },
    }
    return result


def _status_summary(categories: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    counts = {status: 0 for status in sorted(STATUS_VALUES)}
    category_counts: dict[str, dict[str, int]] = {}
    for category, items in categories.items():
        current = {status: 0 for status in sorted(STATUS_VALUES)}
        for item in items:
            status = item.get("status")
            if status not in STATUS_VALUES:
                raise ConformanceError(f"invalid conformance status: {status!r}")
            counts[status] += 1
            current[status] += 1
        category_counts[category] = current
    return {"total": sum(counts.values()), "counts": counts, "by_category": category_counts}


def _aggregate_status(items: Iterable[dict[str, Any]]) -> str:
    statuses = {item.get("status") for item in items}
    if "DEVIATION" in statuses:
        return "DEVIATION"
    if "UNVERIFIED" in statuses:
        return "UNVERIFIED"
    if statuses and statuses <= {"NOT_APPLICABLE"}:
        return "NOT_APPLICABLE"
    return "PASS"


def _build_map(
    *,
    crosswalk: dict[str, Any],
    product_commit: str,
    product_manifest_sha256: str,
    product_tree_sha256: str,
    revalidation_claims: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    archive_records = _archive_manifest_records()
    function_cache: dict[Path, set[str]] = {}
    categories: dict[str, list[dict[str, Any]]] = {}
    for category in CURRENT_CATEGORIES:
        raw_items = crosswalk.get(category)
        if not isinstance(raw_items, list):
            raise ConformanceError(f"crosswalk.{category} must be a list")
        categories[category] = [
            _category_item(
                item,
                category=category,
                archive_records=archive_records,
                function_cache=function_cache,
                behavioral_claims=revalidation_claims.get(str(item.get("id")), []),
            )
            for item in raw_items
        ]
    raw_gates = crosswalk.get("freeze_gates")
    if not isinstance(raw_gates, list):
        raise ConformanceError("crosswalk.freeze_gates must be a list")
    categories["freeze_gates"] = [
        _freeze_gate_item(
            item,
            archive_records=archive_records,
            function_cache=function_cache,
        )
        for item in raw_gates
    ]
    return {
        "schema_version": MAP_SCHEMA,
        "architecture_version": crosswalk.get("architecture_version"),
        "source": {
            "crosswalk": "architecture/v1.0/crosswalk.json",
            "crosswalk_sha256": _sha256_file(CROSSWALK_PATH),
            "product_commit": product_commit,
            "product_manifest_sha256": product_manifest_sha256,
            "product_tree_sha256": product_tree_sha256,
        },
        "status_semantics": {
            "PASS": (
                "Current evidence has been behaviorally verified by a recorded execution receipt."
            ),
            "NOT_APPLICABLE": (
                "The invariant or gate does not apply; the reason must be recorded."
            ),
            "DEVIATION": (
                "The current implementation or evidence mapping differs from the frozen claim."
            ),
            "UNVERIFIED": (
                "The claim is applicable, but the current receipt lacks sufficient "
                "behavioral evidence."
            ),
        },
        "categories": categories,
        "summary": _status_summary(categories),
        "current_implementation_status": _aggregate_status(
            item for category in CURRENT_CATEGORIES for item in categories[category]
        ),
    }


def _run_command(display: str, arguments: Sequence[str]) -> tuple[dict[str, Any], str]:
    result = subprocess.run(  # noqa: S603
        list(arguments),
        cwd=PRODUCT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    output = (result.stdout + "\n" + result.stderr).strip()
    return (
        {
            "command": display,
            "status": "PASS" if result.returncode == 0 else "DEVIATION",
            "exit_code": result.returncode,
        },
        output,
    )


def _verification_commands() -> tuple[list[dict[str, Any]], list[str]]:
    python = sys.executable
    commands: list[dict[str, Any]] = []
    fatal: list[str] = []

    revalidation_command, revalidation_output = _run_command(
        "python3 tools/verify_revalidation_receipts.py --check",
        [python, "tools/verify_revalidation_receipts.py", "--check"],
    )
    commands.append(revalidation_command)
    if revalidation_command["status"] != "PASS":
        fatal.append(revalidation_output or "behavior revalidation receipt check failed")

    manifest_command, manifest_output = _run_command(
        "python3 tools/build_product_manifest.py --check",
        [python, "tools/build_product_manifest.py", "--check"],
    )
    commands.append(manifest_command)
    if manifest_command["status"] != "PASS":
        fatal.append(manifest_output or "Product manifest check failed")

    lock_command, lock_output = _run_command(
        "python3 architecture/v1.0/scripts/verify_lock.py "
        "--scope bundle --mode release "
        "--expected-manifest-sha256 <frozen-anchor>",
        [
            python,
            "architecture/v1.0/scripts/verify_lock.py",
            "--scope",
            "bundle",
            "--mode",
            "release",
            "--expected-manifest-sha256",
            FROZEN_ARCHITECTURE_MANIFEST_SHA256,
        ],
    )
    commands.append(lock_command)
    if lock_command["status"] != "PASS":
        fatal.append(lock_output or "frozen architecture lock failed")

    bundle_command, bundle_output = _run_command(
        "python3 architecture/v1.0/scripts/validate_bundle.py",
        [python, "architecture/v1.0/scripts/validate_bundle.py"],
    )
    if bundle_command["status"] != "PASS":
        known_archive_gap = all(
            marker in bundle_output
            for marker in (
                "AF-09.evidence target does not exist: "
                "docs/reviews/submissions/AF-09-candidate.4-13d0a948-"
                "submission.tar.gz",
                "AF-09.evidence target does not exist: "
                "docs/reviews/submissions/AF-09-candidate.5-ece90366-"
                "submission.tar.gz",
            )
        )
        if known_archive_gap:
            bundle_command["status"] = "UNVERIFIED"
            bundle_command["reason"] = (
                "AF-09 historical submission tarballs are archive-owned and "
                "ignored by the Product Git tree; only their tracked archive "
                "classification records are available here."
            )
        else:
            fatal.append(bundle_output or "frozen architecture bundle validation failed")
    commands.append(bundle_command)
    return commands, fatal


def _package_version(relative_path: str) -> str:
    path = PRODUCT_ROOT / relative_path
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConformanceError(f"cannot read package metadata {path}: {exc}") from exc
    project = data.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise ConformanceError(f"project.version is missing: {path}")
    return project["version"]


def _migration_heads() -> list[str]:
    revisions: dict[str, str] = {}
    referenced: set[str] = set()
    migration_root = PRODUCT_ROOT / "runtime" / "migrations" / "versions"
    for path in sorted(migration_root.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise ConformanceError(f"cannot parse migration {path}: {exc}") from exc
        values: dict[str, Any] = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name) or target.id not in {
                    "revision",
                    "down_revision",
                }:
                    continue
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    raise ConformanceError(
                        f"migration metadata is not literal: {path}:{target.id}"
                    ) from None
        revision = values.get("revision")
        if not isinstance(revision, str):
            continue
        if revision in revisions:
            raise ConformanceError(f"duplicate migration revision: {revision}")
        revisions[revision] = path.name
        down_revision = values.get("down_revision")
        if isinstance(down_revision, str):
            referenced.add(down_revision)
        elif isinstance(down_revision, (list, tuple)):
            referenced.update(value for value in down_revision if isinstance(value, str))
    heads = sorted(set(revisions) - referenced)
    if not heads:
        raise ConformanceError("migration graph has no head")
    return heads


def _build_receipt(
    *,
    product_commit: str,
    product_manifest: dict[str, Any],
    architecture_manifest: dict[str, Any],
    conformance_map: dict[str, Any],
    commands: list[dict[str, Any]],
    verified_at: str,
) -> dict[str, Any]:
    current_status = conformance_map["current_implementation_status"]
    behavioral_claims = []
    for category in CURRENT_CATEGORIES:
        for item in conformance_map["categories"][category]:
            behavioral_claims.extend(item.get("verification", {}).get("execution_receipts", []))
    revalidation_receipts = sorted({claim["receipt"] for claim in behavioral_claims})
    failed_behavioral_claims = [
        claim
        for claim in behavioral_claims
        if claim["status"] == "FAIL" or claim["execution_status"] == "FAIL"
    ]
    return {
        "schema_version": SCHEMA,
        "status": current_status,
        "product_commit": product_commit,
        "product_version": product_manifest["product_version"],
        "product_manifest_sha256": _sha256_file(PRODUCT_MANIFEST_PATH),
        "product_tree_sha256": product_manifest["tree_sha256"],
        "architecture_version": architecture_manifest["architecture_version"],
        "architecture_manifest_sha256": _sha256_file(ARCHITECTURE_MANIFEST_PATH),
        "runtime_version": _package_version("runtime/pyproject.toml"),
        "client_version": _package_version("integrations/python-client/pyproject.toml"),
        "mcp_version": _package_version("integrations/mcp/pyproject.toml"),
        "openworker_version": _package_version("integrations/openworker-mcp/pyproject.toml"),
        "migration_head": _migration_heads(),
        "crosswalk_sha256": conformance_map["source"]["crosswalk_sha256"],
        "invariant_test_map_sha256": _sha256_bytes(_canonical_json(conformance_map)),
        "verified_at": verified_at,
        "verification_commands": commands,
        "behavior_revalidation": {
            "index": "docs/revalidation/INDEX.md",
            "receipts": revalidation_receipts,
            "claims": behavioral_claims,
            "failed_claim_count": len(failed_behavioral_claims),
        },
        "current_implementation": {
            "status": current_status,
            "categories": list(CURRENT_CATEGORIES),
            "map": "docs/conformance/invariant-test-map.json",
        },
        "claim_policy": {
            "architecture_conformant": current_status == "PASS",
            "release_candidate": current_status == "PASS",
            "schema_freeze": current_status == "PASS",
            "blocked_by": (
                []
                if current_status == "PASS"
                else [
                    "ARCHITECTURE_CONFORMANT",
                    "RELEASE_CANDIDATE",
                    "SCHEMA_FREEZE",
                ]
            ),
        },
        "known_limitations": [
            (
                "Behavior revalidation receipts are identity-bound and may only "
                "promote an item when they explicitly declare COMPLETE coverage."
            ),
            (
                "AF-09 historical tarballs are archive-owned and are represented by "
                "tracked classification metadata, not Product Git bytes."
            ),
            (
                "architecture/v1.0 remains frozen; this receipt is a separate "
                "current-implementation evidence layer."
            ),
        ],
    }


def _render_markdown(receipt: dict[str, Any], conformance_map: dict[str, Any]) -> str:
    summary = conformance_map["summary"]
    counts = summary["counts"]
    lines = [
        "# Current Architecture Conformance",
        "",
        "> This receipt validates the current Product against frozen Logical "
        "Architecture 1.0 without modifying `architecture/v1.0/`.",
        "> `UNVERIFIED` is an intentional state; reference presence and aggregate "
        "test counts are not conformance proof.",
        "",
        "## Result",
        "",
        f"- Current implementation status: `{receipt['status']}`",
        f"- Product source commit: `{receipt['product_commit']}`",
        f"- Verified at: `{receipt['verified_at']}`",
        f"- Architecture: `{receipt['architecture_version']}`",
        f"- Migration heads: `{', '.join(receipt['migration_head'])}`",
        "",
        "The current receipt is not an `ARCHITECTURE_CONFORMANT`, "
        "`RELEASE_CANDIDATE`, or `SCHEMA_FREEZE` declaration. Those claims remain "
        "blocked until every applicable current item has a recorded behavioral "
        "execution receipt and no item is `DEVIATION` or `UNVERIFIED`.",
        "",
        "## Identity",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Product version | `{receipt['product_version']}` |",
        f"| Product manifest SHA-256 | `{receipt['product_manifest_sha256']}` |",
        f"| Product tree SHA-256 | `{receipt['product_tree_sha256']}` |",
        f"| Architecture manifest SHA-256 | `{receipt['architecture_manifest_sha256']}` |",
        f"| Runtime / Client / MCP / OpenWorker | `{receipt['runtime_version']}` / "
        f"`{receipt['client_version']}` / `{receipt['mcp_version']}` / "
        f"`{receipt['openworker_version']}` |",
        "",
        "## Evidence matrix",
        "",
        "| Category | PASS | NOT_APPLICABLE | DEVIATION | UNVERIFIED |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for category in ALL_CATEGORIES:
        category_counts = summary["by_category"][category]
        row = (
            f"| `{category}` | {category_counts['PASS']} | "
            f"{category_counts['NOT_APPLICABLE']} | "
            f"{category_counts['DEVIATION']} | {category_counts['UNVERIFIED']} |"
        )
        lines.append(row)
    lines.extend(
        [
            f"| **total** | **{counts['PASS']}** | "
            f"**{counts['NOT_APPLICABLE']}** | **{counts['DEVIATION']}** | "
            f"**{counts['UNVERIFIED']}** |",
            "",
            "The detailed G/I/TX/role/gate mapping is in "
            "[`invariant-test-map.json`](invariant-test-map.json). Each current item "
            "contains implementation evidence, mapped tests, reference-integrity "
            "status, and the separate behavioral-verification status.",
            "",
            "## Verification commands",
            "",
        ]
    )
    for command in receipt["verification_commands"]:
        reason = f" — {command['reason']}" if command.get("reason") else ""
        lines.append(f"- `{command['status']}` `{command['command']}`{reason}")
    lines.extend(
        [
            "",
            "## Behavior revalidation",
            "",
            "Receipts are validated against the current Product tree and manifest. "
            "`SCOPED` claims are recorded as execution evidence but do not promote "
            "the broad frozen item; only passing `COMPLETE` claims without a current "
            "failed receipt can produce `PASS`. Failed receipts remain valid "
            "diagnostic evidence without implying `DEVIATION`.",
            "",
            "- Index: [`docs/revalidation/INDEX.md`](../revalidation/INDEX.md)",
            f"- Receipt count: `{len(receipt['behavior_revalidation']['receipts'])}`",
            f"- Explicit claim count: `{len(receipt['behavior_revalidation']['claims'])}`",
            f"- Failed diagnostic claim count: "
            f"`{receipt['behavior_revalidation']['failed_claim_count']}`",
            "",
            "## Status semantics",
            "",
            "- `PASS`: current evidence is behaviorally verified by a recorded execution receipt.",
            "- `NOT_APPLICABLE`: the claim does not apply and the reason is recorded.",
            "- `DEVIATION`: the current implementation or evidence mapping differs "
            "from the frozen claim.",
            "- `UNVERIFIED`: the claim applies, but the receipt does not yet contain "
            "sufficient behavioral evidence.",
            "",
            "The frozen bundle remains the historical logical-architecture "
            "authority. This document is the current implementation conformance "
            "layer; changing a logical invariant requires a new architecture "
            "version rather than an edit to `architecture/v1.0/`.",
            "",
        ]
    )
    return "\n".join(lines)


def _identity_for_write() -> tuple[str, dict[str, Any], dict[str, Any]]:
    product_manifest = _read_json(PRODUCT_MANIFEST_PATH)
    architecture_manifest = _read_json(ARCHITECTURE_MANIFEST_PATH)
    crosswalk = _read_json(CROSSWALK_PATH)
    if product_manifest.get("schema_version") != "milai-product-manifest-v1":
        raise ConformanceError("unexpected Product manifest schema")
    if architecture_manifest.get("architecture_version") != "1.0.0":
        raise ConformanceError("unexpected frozen architecture version")
    if crosswalk.get("architecture_version") != "1.0.0":
        raise ConformanceError("crosswalk architecture version mismatch")
    return _git_commit(), product_manifest, architecture_manifest


def _build_current() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
    product_commit, product_manifest, architecture_manifest = _identity_for_write()
    commands, fatal = _verification_commands()
    if fatal:
        raise ConformanceError("\n".join(fatal))
    crosswalk = _read_json(CROSSWALK_PATH)
    revalidation_claims = _load_revalidation_receipts(
        crosswalk=crosswalk,
        product_manifest_sha256=_sha256_file(PRODUCT_MANIFEST_PATH),
        product_tree_sha256=str(product_manifest["tree_sha256"]),
        architecture_manifest_sha256=_sha256_file(ARCHITECTURE_MANIFEST_PATH),
    )
    conformance_map = _build_map(
        crosswalk=crosswalk,
        product_commit=product_commit,
        product_manifest_sha256=_sha256_file(PRODUCT_MANIFEST_PATH),
        product_tree_sha256=str(product_manifest["tree_sha256"]),
        revalidation_claims=revalidation_claims,
    )
    receipt = _build_receipt(
        product_commit=product_commit,
        product_manifest=product_manifest,
        architecture_manifest=architecture_manifest,
        conformance_map=conformance_map,
        commands=commands,
        verified_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
    )
    return conformance_map, receipt, commands, []


def _check_payloads() -> list[str]:
    errors: list[str] = []
    if not RECEIPT_PATH.is_file():
        errors.append(f"missing receipt: {RECEIPT_PATH}")
    if not MAP_PATH.is_file():
        errors.append(f"missing invariant-test map: {MAP_PATH}")
    if not REPORT_PATH.is_file():
        errors.append(f"missing report: {REPORT_PATH}")
    if errors:
        return errors

    stored_receipt = _read_json(RECEIPT_PATH)
    stored_map = _read_json(MAP_PATH)
    if stored_receipt.get("schema_version") != SCHEMA:
        errors.append("current-conformance.json schema mismatch")
    if stored_map.get("schema_version") != MAP_SCHEMA:
        errors.append("invariant-test-map.json schema mismatch")
    product_commit = stored_receipt.get("product_commit")
    map_commit = stored_map.get("source", {}).get("product_commit")
    if not isinstance(product_commit, str) or product_commit != map_commit:
        errors.append("receipt and invariant-test map product_commit mismatch")
    elif not _commit_exists(product_commit):
        errors.append(f"receipt product_commit is not present in Git: {product_commit}")

    try:
        expected_map, expected_receipt, _, _ = _build_current()
    except ConformanceError as exc:
        return [str(exc)]

    # The receipt is allowed to outlive documentation-only commits.  Product
    # source identity is checked by manifest/tree digests; the source commit is
    # retained as the exact baseline used to create the receipt.
    expected_map["source"]["product_commit"] = product_commit
    expected_receipt["product_commit"] = product_commit
    expected_receipt["verified_at"] = stored_receipt.get("verified_at")
    expected_receipt["invariant_test_map_sha256"] = _sha256_bytes(_canonical_json(expected_map))
    if stored_map != expected_map:
        errors.append("invariant-test-map.json is stale; regenerate with --write")
    if stored_receipt != expected_receipt:
        errors.append("current-conformance.json is stale; regenerate with --write")

    expected_report = _render_markdown(stored_receipt, stored_map)
    actual_report = REPORT_PATH.read_text(encoding="utf-8")
    if actual_report != expected_report:
        errors.append("CURRENT_ARCHITECTURE_CONFORMANCE.md is stale; regenerate with --write")
    return errors


def _write_payloads() -> int:
    try:
        conformance_map, receipt, commands, _ = _build_current()
    except ConformanceError as exc:
        print(f"Architecture conformance: FAILED\n- {exc}", file=sys.stderr)
        return 1
    _write_json(MAP_PATH, conformance_map)
    _write_json(RECEIPT_PATH, receipt)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(_render_markdown(receipt, conformance_map), encoding="utf-8")
    print(
        "Architecture conformance receipt: "
        f"{receipt['status']} ({len(commands)} verification commands; "
        f"{conformance_map['summary']['total']} mapped items)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help="generate the current map, receipt and Markdown report",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="verify generated artifacts and current Product identity without writing",
    )
    arguments = parser.parse_args()
    if arguments.write or not arguments.check:
        return _write_payloads()
    errors = _check_payloads()
    if errors:
        print("Architecture conformance receipt: FAILED", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    receipt = _read_json(RECEIPT_PATH)
    print(
        "Architecture conformance receipt: "
        f"PASS (receipt fresh; current status={receipt['status']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
