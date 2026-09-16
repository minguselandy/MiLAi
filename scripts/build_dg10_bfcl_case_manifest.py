from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

PLAN = ROOT / "docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.5-2026-08-21.json"
PLAN_SHA256 = "f8ca77115d3f881ead6a0a0d5f12aa3e8f0b209662ace79c641ac90b5d834ce4"
ACCEPTANCE = ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.18.json"
)
DEFAULT_CLOSURE = ROOT / (
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.13-2026-08-22.json"
)
EXECUTION_IDENTITY = ROOT / (
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.13-2026-08-22.json"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.15-2026-08-22.json"
)


class BfclManifestError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise BfclManifestError(reason)


def _fixed_material(path: Path, *, expected: Path, label: str) -> Path:
    lexical = path.absolute()
    _require(
        lexical == expected.absolute()
        and lexical.is_relative_to(ROOT.absolute())
        and not remediation.has_symlink_component(lexical)
        and lexical.is_file(),
        f"{label} is missing, unsafe, or not the fixed material",
    )
    return lexical


def build_manifest(*, closure: Path, frozen_at: str) -> dict[str, Any]:
    _require(remediation.sha256_file(PLAN) == PLAN_SHA256, "historical BFCL dev plan drift")
    closure = _fixed_material(
        closure,
        expected=DEFAULT_CLOSURE,
        label="BFCL dependency closure",
    )
    execution_identity = _fixed_material(
        EXECUTION_IDENTITY,
        expected=EXECUTION_IDENTITY,
        label="BFCL execution identity",
    )
    acceptance = _fixed_material(
        ACCEPTANCE,
        expected=ACCEPTANCE,
        label="active acceptance amendment",
    )
    try:
        parsed_frozen_at = datetime.fromisoformat(frozen_at)
    except ValueError as exc:
        raise BfclManifestError("BFCL manifest frozen_at invalid") from exc
    _require(
        parsed_frozen_at.tzinfo is not None and parsed_frozen_at.utcoffset() is not None,
        "BFCL manifest frozen_at lacks timezone",
    )
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    split = plan.get("split")
    _require(isinstance(split, dict), "historical BFCL split missing")
    case_ids = split.get("dev_case_ids")
    categories = split.get("categories")
    _require(
        isinstance(case_ids, list)
        and len(case_ids) == 216
        and len(case_ids) == len(set(case_ids))
        and isinstance(categories, dict),
        "historical BFCL dev case set drift",
    )
    category_by_case: dict[str, str] = {}
    for category, descriptor in categories.items():
        _require(isinstance(descriptor, dict), "historical BFCL category descriptor drift")
        values = descriptor.get("dev_case_ids")
        _require(isinstance(values, list), "historical BFCL category case list drift")
        for case_id in values:
            _require(
                isinstance(case_id, str) and case_id not in category_by_case,
                "historical BFCL category membership drift",
            )
            category_by_case[case_id] = str(category)
    _require(set(category_by_case) == set(case_ids), "historical BFCL category coverage drift")
    supported = {"irrelevance", "multiple", "parallel", "parallel_multiple", "simple_python"}
    cases: list[dict[str, Any]] = []
    for case_id in case_ids:
        category = category_by_case[case_id]
        language = (
            "java"
            if category == "simple_java"
            else "javascript"
            if category == "simple_javascript"
            else "python"
        )
        cases.append(
            {
                "case_id": case_id,
                "supported_single_turn": category in supported,
                "multi_turn": category.startswith("multi_turn_"),
                "irrelevance_no_call": category == "irrelevance",
                "language": language,
            }
        )
    _require(sum(item["supported_single_turn"] for item in cases) == 122, "BFCL supported denominator drift")
    _require(sum(item["multi_turn"] for item in cases) == 80, "BFCL multi-turn denominator drift")
    _require(sum(item["irrelevance_no_call"] for item in cases) == 24, "BFCL no-call denominator drift")
    closure_reference = {
        "path": closure.relative_to(ROOT.absolute()).as_posix(),
        "sha256": remediation.sha256_file(closure),
    }
    return {
        "schema": "milai.dg10.bfcl-case-manifest.v2",
        "candidate_id": remediation.CANDIDATE,
        "frozen_at": parsed_frozen_at.isoformat(),
        "acceptance_contract": {
            "path": acceptance.relative_to(ROOT.absolute()).as_posix(),
            "sha256": remediation.sha256_file(acceptance),
        },
        "case_count": len(cases),
        "cases": cases,
        "execution_identity": {
            "path": execution_identity.relative_to(ROOT.absolute()).as_posix(),
            "sha256": remediation.sha256_file(execution_identity),
        },
        "dependency_closure": {
            "python": closure_reference,
            "javascript": closure_reference,
            "java": closure_reference,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze candidate.4 BFCL dev case manifest")
    parser.add_argument("--closure", type=Path, default=DEFAULT_CLOSURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--frozen-at", default=datetime.now(UTC).isoformat())
    args = parser.parse_args()
    output = args.output.absolute()
    value = build_manifest(closure=args.closure.absolute(), frozen_at=args.frozen_at)
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "case_count": 216}, sort_keys=True))


if __name__ == "__main__":
    main()
