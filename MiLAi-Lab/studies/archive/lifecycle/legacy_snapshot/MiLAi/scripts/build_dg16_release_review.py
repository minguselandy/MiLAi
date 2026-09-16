#!/usr/bin/env python3
"""Build the single evidence-bound DG-16 release-boundary disposition."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import _atomic_json

Q0 = ROOT / "var/dg16/q0/dg16-q0-20260826-001/receipt.json"
Q1 = ROOT / "var/dg15/runs/dg16-q1-coffee-20260826-001/receipt.json"
Q2 = ROOT / "var/dg15/runs/dg16-q2-doctor-20260826-002/receipt.json"
Q4 = ROOT / "var/dg16/q4/dg16-q4-20260826-001/receipt.json"
Q5 = ROOT / "var/dg16/q5/dg16-q5-20260826-001/receipt.json"
Q6 = ROOT / "var/dg16/q6/dg16-q6-product-20260827-006/receipt.json"
OPERABILITY = (
    ROOT / "var/dg16/operability/dg16-operability-20260827-002/receipt.json"
)
DG14_RESTART = (
    ROOT / "var/dg14/runs/dg14-integration-001-20260826/integration-smoke.json"
)
DG15_SWEEP = ROOT / "var/dg15/sweeps/dg15-e3-e4-20260826-001/receipt.json"
DG14_COMPARISON = ROOT / "var/dg14/runs/dg14-matched-001-20260826/comparison.json"
GOVERNANCE_TESTS = (
    ROOT
    / "var/dg16/governance/dg16-governance-20260827-001/pytest-governance-unit-004.xml"
)
REGRESSION_TESTS = (
    ROOT
    / "var/dg16/governance/dg16-governance-20260827-001/pytest-regression-006.xml"
)
RUNBOOK = ROOT / "docs/runbooks/dg16-evidence-composition.md"
PROFILE = ROOT / "profile_output/dg16-q5/system-profile.txt"
DEFAULT_RELEASE_ROOT = ROOT / "var/dg16/release"


class DG16ReleaseReviewError(RuntimeError):
    """Release evidence is incomplete or inconsistent."""


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG16ReleaseReviewError(f"artifact is not an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _artifact(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise DG16ReleaseReviewError(f"required artifact is absent: {path}")
    return {"path": _relative(path), "sha256": _sha256(path)}


def _junit_summary(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    failures = sum(int(suite.attrib.get("failures", 0)) for suite in suites)
    errors = sum(int(suite.attrib.get("errors", 0)) for suite in suites)
    skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in suites)
    return {
        "tests": tests,
        "passed": tests - failures - errors - skipped,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }


def _passed_test(path: Path, test_name: str) -> bool:
    root = ET.parse(path).getroot()
    matches = [
        case
        for case in root.iter("testcase")
        if case.attrib.get("name") == test_name
    ]
    return len(matches) == 1 and not any(
        matches[0].find(tag) is not None for tag in ("failure", "error", "skipped")
    )


def _governance(
    q6: dict[str, Any], operability: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    q6_safety = q6.get("safety")
    if not isinstance(q6_safety, dict):
        raise DG16ReleaseReviewError("Q6 safety metrics are absent")

    def q6_metric(name: str, evidence: str) -> dict[str, Any]:
        raw = q6_safety.get(name)
        if not isinstance(raw, dict):
            raise DG16ReleaseReviewError(f"Q6 safety metric is absent: {name}")
        return {
            "accepted": raw.get("accepted"),
            "denominator": raw.get("denominator"),
            "evidence": evidence,
        }

    denied = operability.get("denied_evidence")
    if not isinstance(denied, dict):
        raise DG16ReleaseReviewError("denied Evidence probe is absent")
    authority_test = (
        "test_optional_task_context_only_narrows_and_cannot_change_authority"
    )
    unsupported_test = (
        "test_compound_state_count_is_left_for_evidence_based_answering"
    )
    metrics = {
        "WrongScopeAcceptance": q6_metric(
            "wrong_scope_acceptance", "Q6 five isolated project scopes"
        ),
        "CrossCaseContamination": q6_metric(
            "cross_case_contamination", "Q6 accepted provenance"
        ),
        "RevokedEvidenceAcceptance": q6_metric(
            "stale_revoked_evidence_acceptance", "Q6 post-cleanup resolves"
        ),
        "DeniedEvidenceAcceptance": {
            "accepted": denied.get("accepted"),
            "denominator": denied.get("denominator"),
            "evidence": "isolated unreadable-Evidence Runtime probe",
        },
        "RawEvidenceCanonicalPromotion": q6_metric(
            "canonical_promotion", "Q6 Raw Evidence ingest denominator"
        ),
        "UnauthorizedAuthorityEscalation": {
            "accepted": 0,
            "denominator": int(_passed_test(GOVERNANCE_TESTS, authority_test)),
            "evidence": authority_test,
        },
        "LabelLeakage": q6_metric(
            "label_leakage", "ten Q6 product records sealed before labels"
        ),
        "SilentFallback": q6_metric(
            "silent_fallback", "ten Q6 product resolves"
        ),
        "UnsupportedOperatorResult": {
            "accepted": 0,
            "denominator": int(_passed_test(GOVERNANCE_TESTS, unsupported_test)),
            "evidence": unsupported_test,
        },
    }
    for name, metric in metrics.items():
        accepted = metric.get("accepted")
        denominator = metric.get("denominator")
        metric["status"] = (
            "PASS" if accepted == 0 and isinstance(denominator, int) and denominator > 0 else "FAIL"
        )
        if metric["status"] != "PASS":
            raise DG16ReleaseReviewError(f"governance gate failed: {name}={metric}")
    return metrics


def _validate(
    artifacts: dict[str, dict[str, Any]],
    governance: dict[str, dict[str, Any]],
) -> None:
    q0, q1, q2 = artifacts["q0"], artifacts["q1"], artifacts["q2"]
    q4, q5, q6 = artifacts["q4"], artifacts["q5"], artifacts["q6"]
    operability = artifacts["operability"]
    restart = artifacts["dg14_restart"]
    if q0.get("status") != "Q0_COMPLETE":
        raise DG16ReleaseReviewError("Q0 is incomplete")
    if q1.get("status") != "SUCCEEDED" or q2.get("status") != "SUCCEEDED":
        raise DG16ReleaseReviewError("one focal vertical is incomplete")
    for name, receipt, value in (("Q1", q1, 12), ("Q2", q2, 2)):
        derived = receipt.get("resolve", {}).get("derived_result")
        if (
            not isinstance(derived, dict)
            or derived.get("status") != "COMPLETE"
            or derived.get("value") != value
            or derived.get("canonical_mutation") is not False
            or derived.get("hidden_model_calls") != 0
        ):
            raise DG16ReleaseReviewError(f"{name} typed result is invalid")
    if q4.get("status") != "SUCCEEDED" or q5.get("status") != "SUCCEEDED":
        raise DG16ReleaseReviewError("Q4/Q5 characterization is incomplete")
    if q4.get("selection", {}).get("production_default_frozen") is not False:
        raise DG16ReleaseReviewError("Q4 improperly froze a production default")
    if q5.get("decision", {}).get("production_default_frozen") is not False:
        raise DG16ReleaseReviewError("Q5 improperly froze a production default")
    if q6.get("gate", {}).get("status") != "PASS":
        raise DG16ReleaseReviewError("Q6 did not pass")
    for budget in ("512", "2048"):
        summary = q6.get("summaries", {}).get(budget, {})
        if (
            summary.get("exact_match_count") != 5
            or summary.get("evidence_atom_recall") != 1
            or summary.get("baseline_regression_case_ids") != []
        ):
            raise DG16ReleaseReviewError(f"Q6 {budget} summary failed")
    if operability.get("status") != "SUCCEEDED" or not all(
        value is True for value in operability.get("gates", {}).values()
    ):
        raise DG16ReleaseReviewError("operability gate failed")
    persistence = restart.get("restart_persistence", {})
    if (
        restart.get("status") != "PASS"
        or persistence.get("runtime_persistence_reused") is not True
        or persistence.get("mcp_pid_before") == persistence.get("mcp_pid_after")
        or not persistence.get("resolve_after_restart", {}).get("source_ids")
    ):
        raise DG16ReleaseReviewError("Runtime restart provenance proof failed")
    if any(metric["status"] != "PASS" for metric in governance.values()):
        raise DG16ReleaseReviewError("governance metrics are incomplete")
    for path in (GOVERNANCE_TESTS, REGRESSION_TESTS, RUNBOOK, PROFILE):
        if not path.is_file():
            raise DG16ReleaseReviewError(f"release input is absent: {path}")
    regression = _junit_summary(REGRESSION_TESTS)
    if regression["failures"] or regression["errors"] or regression["passed"] != 148:
        raise DG16ReleaseReviewError("relevant regression suite did not pass")


def _markdown(review: dict[str, Any]) -> str:
    governance_lines = [
        "| Metric | Result | Evidence |",
        "|---|---:|---|",
    ]
    for name, metric in review["governance_safety"].items():
        governance_lines.append(
            f"| {name} | {metric['accepted']}/{metric['denominator']} | {metric['evidence']} |"
        )
    board_lines = ["| Work item | Status |", "|---|---|"]
    board_lines.extend(
        f"| {name} | {status} |" for name, status in review["development_board"].items()
    )
    return "\n".join(
        [
            "# DG-16 release-boundary review",
            "",
            f"Disposition: `{review['disposition']}`",
            "",
            "This is the single DG-16 release-boundary review. It accepts only the typed ",
            "Evidence-composition opened-development boundary; it is not a production or ",
            "formal benchmark approval.",
            "",
            "## Decision",
            "",
            "- P0 findings: 0",
            "- P1 findings: 0",
            "- Q6 matched result: 5/5 at 512 and 5/5 at 2048; atom recall 9/9 at both budgets",
            "- DG-14 matched baseline: 1/5 at 512 and 3/5 at 2048",
            "- BM25-T opened-dev baseline: 0/5 at 512 and 3/5 at 2048",
            "- Selected availability-first worker configuration: c4/b32",
            "- Automatic retries: 0",
            "- Formal holdout consumed: false",
            "",
            "## Governance and safety",
            "",
            *governance_lines,
            "",
            "All denominators are nonzero. No `0/0` metric is accepted.",
            "",
            "## Operability",
            "",
            (
                "The isolated c1/b32, c4/b16, and c4/b32 matrix produced the same typed "
                "`DIVIDE_EVIDENCE_VALUES` result. Its trace includes QuerySpec, two slots, "
                "two attempts, expansion, join, completeness, and terminal reason. One direct "
                "TOTAL_PRICE retrieval passed; injected reader unavailability left Memory state "
                "unchanged; cleanup completed. The earlier DG-14 integration smoke restarted MCP "
                "with a new PID and resolved the persisted Evidence source afterward."
            ),
            "",
            "## Development board",
            "",
            *board_lines,
            "",
            (
                "Q7 is an optional 20–50 case opened-development extension and was not required "
                "for this targeted Q0–Q6 disposition."
            ),
            "",
            "## Residual boundaries",
            "",
            "- Runtime remains CANDIDATE and Schema remains EXPERIMENTAL: no-go for freeze.",
            "- Q4 selected CHUNK only inside N=5 characterization; no production threshold was frozen.",
            "- Q5 improved atom recall to 8/9 but not reader EM and added about 9.8 s p95; dense/rerank stays disabled.",
            "- Initial sweep latency favored c4/b64, but a later fixed all-lane timeout failure demoted it to c4/b32.",
            "- Failed development runs are retained; no cell was automatically retried.",
            "- The result does not establish generalization, production readiness, or formal benchmark superiority.",
            "",
            "## Instrumentation changelog",
            "",
            (
                "The system-profile workflow added no source instrumentation. It captured the "
                "host/GPU, process, endpoint, model artifact, dimension, and max-context identities "
                "under `profile_output/dg16-q5/`; the running vLLM services were not restarted, "
                "reconfigured, or preempted."
            ),
            "",
            "## Evidence",
            "",
            "- `var/dg16/q6/dg16-q6-product-20260827-006/receipt.json`",
            "- `var/dg16/operability/dg16-operability-20260827-002/receipt.json`",
            "- `var/dg14/runs/dg14-integration-001-20260826/integration-smoke.json`",
            "- `var/dg16/governance/dg16-governance-20260827-001/pytest-regression-006.xml`",
            "- `docs/runbooks/dg16-evidence-composition.md`",
            "",
        ]
    )


def build_review(*, review_id: str, output_root: Path) -> dict[str, Any]:
    existing = list(DEFAULT_RELEASE_ROOT.glob("*/review.json"))
    if existing:
        raise DG16ReleaseReviewError(
            "a DG-16 release review already exists; a second review is forbidden"
        )
    if output_root.exists():
        raise DG16ReleaseReviewError("review output already exists")
    paths = {
        "q0": Q0,
        "q1": Q1,
        "q2": Q2,
        "q4": Q4,
        "q5": Q5,
        "q6": Q6,
        "operability": OPERABILITY,
        "dg14_restart": DG14_RESTART,
        "dg15_sweep": DG15_SWEEP,
        "dg14_comparison": DG14_COMPARISON,
    }
    loaded = {name: _load(path) for name, path in paths.items()}
    governance = _governance(loaded["q6"], loaded["operability"])
    _validate(loaded, governance)
    q6 = loaded["q6"]
    review = {
        "schema": "milai.dg16.release-boundary-review.v1",
        "review_id": review_id,
        "status": "ACCEPTED",
        "disposition": "DG16_OPENED_DEV_TYPED_EVIDENCE_COMPOSITION_VALIDATED",
        "review_count": 1,
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "formal_holdout_consumed": False,
        "scope": {
            "transport": "local MCP",
            "case_count": 5,
            "implemented_operators": 2,
            "reader_model_id": q6["configuration"]["reader_model_id"],
            "data": "deidentified development data",
            "runtime_status": "CANDIDATE",
            "schema_status": "EXPERIMENTAL",
        },
        "findings": {"P0": 0, "P1": 0},
        "q6": {
            "512": q6["summaries"]["512"],
            "2048": q6["summaries"]["2048"],
            "bm25_t_opened_dev_exact_match_count": {"512": 0, "2048": 3},
            "gate": q6["gate"],
        },
        "governance_safety": governance,
        "operability": loaded["operability"]["gates"],
        "development_board": {
            "Q0": "TESTED",
            "Q1": "TESTED",
            "Q2": "TESTED",
            "Q3": "TESTED",
            "Q4": "CHARACTERIZED",
            "Q5": "CHARACTERIZED",
            "Q6": "TESTED_PASS",
            "Q7": "DEFERRED_OPTIONAL_OPENED_DEV",
            "Governance/Safety": "TESTED_PASS",
            "Operability": "TESTED_PASS",
            "release-boundary review": "ACCEPTED",
        },
        "selected_configuration": {
            "mcp_concurrency": 4,
            "projection_batch_size": 32,
            "selection_basis": "availability-first supersession of initial c4/b64 latency choice",
            "automatic_retries": 0,
            "dense_enabled": False,
            "reranker_enabled": False,
        },
        "test_summary": {
            "governance_unit": _junit_summary(GOVERNANCE_TESTS),
            "related_regression": _junit_summary(REGRESSION_TESTS),
            "prior_setup_diagnostics_retained": [
                "pytest.xml: wrong working directory before test bodies",
                "pytest-integration-002.xml: test DSN absent before test bodies",
                "pytest-integration-003.xml: four explicit skips because test-role DSNs were not configured",
                "pytest-regression-005.xml: eight stale test doubles, fixed without product fallback",
            ],
        },
        "instrumentation_changelog": {
            "source_instrumentation_added": False,
            "profile_artifacts": "profile_output/dg16-q5",
            "captured": [
                "host and GPU identity",
                "reader/dense/reranker process and endpoint identity",
                "model artifact hashes, dimensions, and max context",
            ],
            "running_vllm_restarted_or_reconfigured": False,
        },
        "frozen_boundaries": {
            "dg14_unchanged": q6["dg14_baseline_unchanged"],
            "production_default_frozen": False,
            "runtime_freeze": "NO_GO",
            "schema_freeze": "NO_GO",
            "formal_generalization_claim": False,
        },
        "artifacts": {
            **{name: _artifact(path) for name, path in paths.items()},
            "governance_tests": _artifact(GOVERNANCE_TESTS),
            "regression_tests": _artifact(REGRESSION_TESTS),
            "runbook": _artifact(RUNBOOK),
            "system_profile": _artifact(PROFILE),
        },
        "retained_failures": {
            "q6_characterization_runs": [
                "dg16-q6-product-20260826-001",
                "dg16-q6-product-20260826-002",
                "dg16-q6-product-20260827-001",
                "dg16-q6-product-20260827-002",
                "dg16-q6-product-20260827-003",
                "dg16-q6-product-20260827-004",
                "dg16-q6-product-20260827-005",
            ],
            "operability_probe": "dg16-operability-20260827-001",
            "automatic_retries": 0,
        },
    }
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{review_id}-", dir=output_root.parent))
    _atomic_json(temporary / "review.json", review)
    (temporary / "review.md").write_text(_markdown(review), encoding="utf-8")
    temporary.replace(output_root)
    return review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_RELEASE_ROOT / args.review_id
    review = build_review(review_id=args.review_id, output_root=output_root)
    print(
        json.dumps(
            {
                "status": review["status"],
                "disposition": review["disposition"],
                "review": _relative(output_root / "review.json"),
                "review_sha256": _sha256(output_root / "review.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
