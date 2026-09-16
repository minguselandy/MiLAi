from __future__ import annotations

import argparse
import copy
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_multiturn_scoring_remediation_v3 as orchestrator
from scripts import run_dg10_bfcl_multiturn_scoring_worker_v4 as worker

DATE = "2026-08-21"
CANDIDATE = "candidate.16"
FREEZE_ACK = "freeze-candidate16-five-case-remediation-with-sol-required-gates"
C13_CONTRACT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-contract-candidate.13-{DATE}.json"
)
C13_REPORT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-candidate.1-{DATE}.json"
)
C14_CONTRACT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-remediation-contract-candidate.14-{DATE}.json"
)
C15_CONTRACT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-remediation-contract-candidate.15-{DATE}.json"
)
SCORING_WORKER = ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_worker_v4.py"
SCORING_ORCHESTRATOR = (
    ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_remediation_v3.py"
)
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-remediation-contract-{CANDIDATE}-{DATE}.json"
)
SCHEDULE_FAILURE = "case is outside the frozen scoring schedule"


class RemediationContractV3Error(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationContractV3Error(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise RemediationContractV3Error(f"JSON object required: {path}")
    return value


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RemediationContractV3Error("ledger must be non-symlink mode 0600")
    try:
        rows = [
            json.loads(raw)
            for raw in path.read_text(encoding="utf-8").splitlines()
            if raw.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationContractV3Error("invalid ledger") from exc
    if any(not isinstance(row, dict) for row in rows):
        raise RemediationContractV3Error("ledger row must be an object")
    return rows


def _source(path: Path, relative_to: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(relative_to.resolve()).as_posix(),
        "sha256": dev_smoke._sha256_file(resolved),
        "size": resolved.stat().st_size,
    }


def _schedule_contract_valid(
    candidate: Any,
    scoring_ids: Any,
    remediation_ids: Any,
    full_ids: Any,
    expected_remediation_ids: list[str],
    expected_full_ids: list[str],
) -> bool:
    return bool(
        candidate == CANDIDATE
        and isinstance(scoring_ids, list)
        and isinstance(remediation_ids, list)
        and isinstance(full_ids, list)
        and scoring_ids == remediation_ids == expected_remediation_ids
        and full_ids == expected_full_ids
        and len(scoring_ids) == len(set(scoring_ids)) == 5
        and len(full_ids) == len(set(full_ids)) == 80
        and set(scoring_ids).issubset(full_ids)
    )


def _run_schedule_validation_matrix(
    remediation_ids: list[str], full_ids: list[str]
) -> dict[str, Any]:
    def valid(candidate=CANDIDATE, scoring=remediation_ids, remediation=remediation_ids, full=full_ids):
        return _schedule_contract_valid(
            candidate,
            scoring,
            remediation,
            full,
            remediation_ids,
            full_ids,
        )
    mutations = {
        "positive": valid(),
        "old_candidate_rejected": not valid(candidate="candidate.15"),
        "missing_alias_rejected": not valid(scoring=None),
        "non_list_rejected": not valid(scoring=tuple(remediation_ids)),
        "duplicate_rejected": not valid(
            scoring=remediation_ids[:4] + remediation_ids[:1],
            remediation=remediation_ids[:4] + remediation_ids[:1],
        ),
        "wrong_id_rejected": not valid(
            scoring=[*remediation_ids[:4], "bfcl_v4:unknown"],
            remediation=[*remediation_ids[:4], "bfcl_v4:unknown"],
        ),
        "changed_order_rejected": not valid(
            scoring=list(reversed(remediation_ids)),
            remediation=list(reversed(remediation_ids)),
        ),
        "unequal_alias_rejected": not valid(
            scoring=list(reversed(remediation_ids))
        ),
        "mutated_full_schedule_rejected": not valid(
            full=[*full_ids[:-1], "bfcl_v4:unknown"]
        ),
        "extra_authorization_rejected": not valid(
            scoring=[*remediation_ids, full_ids[5]],
            remediation=[*remediation_ids, full_ids[5]],
        ),
    }
    if not all(mutations.values()):
        raise RemediationContractV3Error("schedule validation matrix failed")
    return {
        "status": "PASS",
        "case_count": len(mutations),
        "results": mutations,
        "label_access": False,
        "model_or_provider_calls": 0,
    }


def _run_entrypoint_probes(
    remediation_ids: list[str], full_ids: list[str]
) -> dict[str, Any]:
    probe_contract = {
        "schema": worker.CONTRACT_SCHEMA,
        "candidate": CANDIDATE,
        "status": worker.CONTRACT_STATUS,
        "scoring_schedule": {"ordered_case_ids": remediation_ids},
        "remediation_schedule": {"ordered_case_ids": remediation_ids},
        "full_scoring_schedule": {"ordered_case_ids": full_ids},
    }
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="dg10-c16-schedule-") as temporary:
        contract_path = Path(temporary) / "serialized-contract.json"
        contract_path.write_bytes(dev_smoke._encoded_json(probe_contract))
        cases = [(case_id, 0, "WOULD_ENTER_LABEL_BOUNDARY") for case_id in remediation_ids]
        cases.extend(
            [
                ("bfcl_v4:unknown_candidate16_probe", 3, "REJECTED_AT_FROZEN_SCHEDULE"),
                (
                    next(case_id for case_id in full_ids if case_id not in remediation_ids),
                    3,
                    "REJECTED_AT_FROZEN_SCHEDULE",
                ),
            ]
        )
        for case_id, expected_exit, expected_status in cases:
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCORING_WORKER),
                    "--schedule-probe",
                    "--contract",
                    str(contract_path),
                    "--case-id",
                    case_id,
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            try:
                output = json.loads(process.stdout)
            except json.JSONDecodeError as exc:
                raise RemediationContractV3Error("schedule probe output invalid") from exc
            if (
                process.returncode != expected_exit
                or output.get("status") != expected_status
                or output.get("real_label_bytes_opened") is not False
                or output.get("official_checker_loaded") is not False
                or output.get("model_or_provider_calls") != 0
                or output.get("worker_sha256")
                != dev_smoke._sha256_file(SCORING_WORKER)
            ):
                raise RemediationContractV3Error("exact entrypoint probe failed")
            results.append(
                {
                    "case_id": case_id,
                    "exit_code": process.returncode,
                    "status": output["status"],
                    "stdout_sha256": dev_smoke._sha256_bytes(
                        process.stdout.encode("utf-8")
                    ),
                    "stderr_sha256": dev_smoke._sha256_bytes(
                        process.stderr.encode("utf-8")
                    ),
                    "worker_sha256": output["worker_sha256"],
                    "v1_worker_sha256": output["v1_worker_sha256"],
                }
            )
    return {
        "status": "PASS_BOUND",
        "probe_count": 7,
        "in_scope_label_boundary_count": 5,
        "out_of_scope_pre_label_rejection_count": 2,
        "results": results,
        "real_label_access": False,
        "official_checker_loads": 0,
        "model_or_provider_calls": 0,
    }


def _run_runtime_probes() -> dict[str, Any]:
    help_probe = subprocess.run(
        [sys.executable, str(SCORING_WORKER), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if (
        help_probe.returncode != 0
        or "Score one sealed BFCL multi-turn development case" not in help_probe.stdout
    ):
        raise RemediationContractV3Error("worker help/import probe failed")
    canonical_outputs: list[dict[str, Any]] = []
    for seed in ("1", "2", "random"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        process = subprocess.run(
            [sys.executable, str(SCORING_WORKER), "--canonicalizer-probe"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        if process.returncode != 0:
            raise RemediationContractV3Error("canonicalizer process probe failed")
        output = json.loads(process.stdout)
        if output.get("status") != "PASS" or output.get("algorithm") != worker.HASH_ALGORITHM:
            raise RemediationContractV3Error("canonicalizer probe evidence invalid")
        canonical_outputs.append(output)
    if len({dev_smoke._json_sha256(item) for item in canonical_outputs}) != 1:
        raise RemediationContractV3Error("canonicalizer is hash-seed dependent")
    return {
        "status": "PASS_BOUND",
        "help_probe": {
            "exit_code": help_probe.returncode,
            "stdout_sha256": dev_smoke._sha256_bytes(help_probe.stdout.encode()),
            "stderr_sha256": dev_smoke._sha256_bytes(help_probe.stderr.encode()),
        },
        "canonicalizer_cross_process": {
            **canonical_outputs[0],
            "python_hash_seed_runs": ["1", "2", "random"],
            "identical_output_count": 3,
        },
        "label_access": False,
        "model_or_provider_calls": 0,
    }


def _synthetic_row(case_id: str, *, complete: bool, candidate16: bool) -> dict[str, Any]:
    row = {
        "case_id": case_id,
        "evidence_complete": complete,
        "generation_success": False,
        "generation_failure_code": "SYNTHETIC_FAILURE",
        "final_valid": False,
        "official_checkers": {
            "multi_turn_checker": {"invocation_count": 1},
            "multi_turn_irrelevance_checker": {"invocation_count": 1},
        },
    }
    if candidate16:
        row.update(
            {
                "checker_result_hash_algorithm": worker.HASH_ALGORITHM,
                "final_valid_formula_id": worker.FINAL_VALID_FORMULA,
                "scoring_worker_candidate": CANDIDATE,
            }
        )
    return row


def _run_composite_rejection_matrix(
    full_ids: list[str], remediation_ids: list[str]
) -> dict[str, Any]:
    parent = [
        _synthetic_row(
            case_id,
            complete=case_id not in remediation_ids,
            candidate16=False,
        )
        for case_id in full_ids
    ]
    replacements = [
        _synthetic_row(case_id, complete=True, candidate16=True)
        for case_id in remediation_ids
    ]
    kwargs = {
        "full_ids": full_ids,
        "remediation_ids": remediation_ids,
        "parent_rows": parent,
        "remediation_rows": replacements,
        "candidate13_ledger_sha256": "1" * 64,
        "candidate13_contract_sha256": "2" * 64,
        "candidate16_ledger_sha256": "3" * 64,
        "candidate16_contract_sha256": "4" * 64,
        "generation_ledger_sha256": "5" * 64,
        "bundle_sha256": "6" * 64,
        "official_checker_sha256": "7" * 64,
    }
    positive = orchestrator.build_composite_rows(**kwargs)
    if len(positive) != 80:
        raise RemediationContractV3Error("positive composite dry run failed")
    mutations: dict[str, dict[str, Any]] = {
        "missing": {"remediation_rows": replacements[:-1]},
        "duplicate": {"remediation_rows": replacements[:-1] + replacements[:1]},
        "reordered": {"remediation_rows": list(reversed(replacements))},
        "incomplete": {
            "remediation_rows": [
                {**replacements[0], "evidence_complete": False},
                *replacements[1:],
            ]
        },
        "wrong_source": {
            "remediation_rows": [
                {**replacements[0], "scoring_worker_candidate": "candidate.15"},
                *replacements[1:],
            ]
        },
        "mixed_hash_provenance": {
            "remediation_rows": [
                {
                    **replacements[0],
                    "checker_result_hash_algorithm": orchestrator.LEGACY_HASH_ALGORITHM,
                },
                *replacements[1:],
            ]
        },
        "invocation_mismatch": {
            "remediation_rows": [
                {
                    **replacements[0],
                    "official_checkers": {
                        "multi_turn_checker": {"invocation_count": 1},
                        "multi_turn_irrelevance_checker": {"invocation_count": 0},
                    },
                },
                *replacements[1:],
            ]
        },
        "stale_partial_parent_selected": {
            "remediation_ids": [*remediation_ids[1:], full_ids[5]]
        },
    }
    passed = 0
    for mutation in mutations.values():
        candidate = {**kwargs, **mutation}
        try:
            orchestrator.build_composite_rows(**candidate)
        except orchestrator.RemediationV3Error:
            passed += 1
    if passed != len(mutations):
        raise RemediationContractV3Error("composite rejection matrix failed")
    return {
        "status": "PASS",
        "positive_case_count": 1,
        "negative_case_count": len(mutations),
        "negative_cases_rejected": passed,
        "negative_case_names": sorted(mutations),
        "label_access": False,
        "model_or_provider_calls": 0,
    }


def build_contract(
    *,
    candidate13_ledger: Path,
    candidate14_ledger: Path,
    candidate15_ledger: Path,
    candidate15_run_directory: Path,
    generation_ledger: Path,
    bundle_path: Path,
    bfcl_root: Path,
    sol_advisory_output: Path,
    sol_advisory_events: Path,
) -> dict[str, Any]:
    contract13 = _load_json(C13_CONTRACT)
    report13 = _load_json(C13_REPORT)
    contract14 = _load_json(C14_CONTRACT)
    contract15 = _load_json(C15_CONTRACT)
    rows13 = _read_ledger(candidate13_ledger)
    rows14 = _read_ledger(candidate14_ledger)
    rows15 = _read_ledger(candidate15_ledger)
    full_ids = contract13.get("scoring_schedule", {}).get("ordered_case_ids")
    remediation_ids = contract14.get("remediation_schedule", {}).get("ordered_case_ids")
    if (
        contract13.get("candidate") != "candidate.13"
        or report13.get("status")
        != "BFCL_MULTITURN_DEV_SCORING_COMPLETE_WITH_PROCESS_FAILURES"
        or report13.get("repo_external_scoring_ledger", {}).get("sha256")
        != dev_smoke._sha256_file(candidate13_ledger)
        or contract14.get("candidate") != "candidate.14"
        or contract15.get("candidate") != "candidate.15"
        or not isinstance(full_ids, list)
        or len(full_ids) != 80
        or not isinstance(remediation_ids, list)
        or len(remediation_ids) != 5
        or [row.get("case_id") for row in rows13] != full_ids
        or sum(row.get("evidence_complete") is True for row in rows13) != 75
        or [row.get("case_id") for row in rows14] != remediation_ids
        or [row.get("case_id") for row in rows15] != remediation_ids
        or any(row.get("evidence_complete") is not False for row in rows14 + rows15)
    ):
        raise RemediationContractV3Error("candidate.13-15 parent boundary mismatch")
    failed13 = {
        str(row["case_id"])
        for row in rows13
        if row.get("evidence_complete") is not True
    }
    complete13 = {
        str(row["case_id"])
        for row in rows13
        if row.get("evidence_complete") is True
    }
    if (
        failed13 != set(remediation_ids)
        or len(complete13) != 75
        or complete13 & failed13
        or complete13 | failed13 != set(full_ids)
    ):
        raise RemediationContractV3Error("metadata-only 75+5 partition failed")
    diagnostics15: list[dict[str, Any]] = []
    for row in rows15:
        case_id = str(row["case_id"])
        stderr_path = (
            candidate15_run_directory
            / "cases"
            / f"{case_id.replace(':', '__')}.worker-stderr.log"
        )
        stderr = stderr_path.read_text(encoding="utf-8")
        if (
            dev_smoke._sha256_file(stderr_path)
            != row.get("worker_stderr", {}).get("sha256")
            or SCHEDULE_FAILURE not in stderr
        ):
            raise RemediationContractV3Error("candidate.15 schedule failure drift")
        diagnostics15.append(
            {
                "case_id": case_id,
                "stderr_sha256": row["worker_stderr"]["sha256"],
                "failure_stage": "PRE_LABEL_FROZEN_SCHEDULE_LOOKUP",
                "label_selected": False,
                "official_checker_invocations": 0,
            }
        )
    if (
        report13.get("inputs", {}).get("sealed_generation_ledger_sha256")
        != dev_smoke._sha256_file(generation_ledger)
        or report13.get("inputs", {}).get("label_free_bundle_sha256")
        != dev_smoke._sha256_file(bundle_path)
    ):
        raise RemediationContractV3Error("generation binding drift")
    advisory = _load_json(sol_advisory_output)
    events = [
        json.loads(raw)
        for raw in sol_advisory_events.read_text(encoding="utf-8").splitlines()
        if raw.strip()
    ]
    thread_ids = [item["thread_id"] for item in events if item.get("type") == "thread.started"]
    if (
        advisory.get("review_type") != "AI_ADVISORY_NOT_HUMAN_APPROVAL"
        or advisory.get("verdict") != "PROCEED_WITH_REQUIRED_CHANGES"
        or advisory.get("compatibility_alias_sufficient") is not True
        or len(thread_ids) != 1
        or len(set(thread_ids)) != 1
    ):
        raise RemediationContractV3Error("Sol advisory boundary mismatch")
    root = bfcl_root.resolve()
    if bfcl_contract._git_head(root) != contract13.get("inputs", {}).get("bfcl_git_head"):
        raise RemediationContractV3Error("BFCL git HEAD drift")
    official_closure: dict[str, Any] = {}
    for key, descriptor in contract13.get("byte_closure", {}).items():
        if key.startswith(("official_", "function_source_")):
            current = _source(root / str(descriptor["path"]), root)
            if current["sha256"] != descriptor.get("sha256"):
                raise RemediationContractV3Error(f"official source drift: {key}")
            official_closure[key] = current
    schedule_matrix = _run_schedule_validation_matrix(remediation_ids, full_ids)
    entrypoint_probes = _run_entrypoint_probes(remediation_ids, full_ids)
    runtime_probes = _run_runtime_probes()
    composite_matrix = _run_composite_rejection_matrix(full_ids, remediation_ids)
    launch_assignments = [
        {
            "assignment_index": index,
            "case_id": case_id,
            "output_basename": f"{case_id.replace(':', '__')}.score.json",
            "worker_sha256": dev_smoke._sha256_file(SCORING_WORKER),
            "retry_allowance": 0,
            "fresh_process_required": True,
        }
        for index, case_id in enumerate(remediation_ids)
    ]
    scoring_policy = copy.deepcopy(contract13["scoring_policy"])
    scoring_policy["final_valid_formula_id"] = worker.FINAL_VALID_FORMULA
    return {
        "schema": worker.CONTRACT_SCHEMA,
        "date": DATE,
        "candidate": CANDIDATE,
        "status": worker.CONTRACT_STATUS,
        "quality_outcome": "PARENT_SCORING_EVIDENCE_INCOMPLETE",
        "bfcl_dev_answer_labels_opened": True,
        "bfcl_dev_case_count_semantically_opened": 80,
        "bfcl_test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "inputs": {
            "candidate13_contract_sha256": dev_smoke._sha256_file(C13_CONTRACT),
            "candidate13_scoring_report_sha256": dev_smoke._sha256_file(C13_REPORT),
            "candidate13_scoring_ledger_sha256": dev_smoke._sha256_file(
                candidate13_ledger
            ),
            "candidate14_contract_sha256": dev_smoke._sha256_file(C14_CONTRACT),
            "candidate14_remediation_ledger_sha256": dev_smoke._sha256_file(
                candidate14_ledger
            ),
            "candidate15_contract_sha256": dev_smoke._sha256_file(C15_CONTRACT),
            "candidate15_remediation_ledger_sha256": dev_smoke._sha256_file(
                candidate15_ledger
            ),
            "sealed_generation_ledger_sha256": dev_smoke._sha256_file(
                generation_ledger
            ),
            "label_free_bundle_sha256": dev_smoke._sha256_file(bundle_path),
            "bfcl_git_head": bfcl_contract._git_head(root),
            "sol_advisory_output_sha256": dev_smoke._sha256_file(sol_advisory_output),
            "sol_advisory_events_sha256": dev_smoke._sha256_file(sol_advisory_events),
            "sol_advisory_thread_id": thread_ids[0],
        },
        "full_scoring_schedule": {
            "ordered_case_ids": full_ids,
            "ordered_case_ids_sha256": dev_smoke._json_sha256(full_ids),
            "case_count": 80,
            "candidate13_complete_case_count": 75,
            "candidate13_failed_case_count": 5,
            "partition_disjoint_and_complete": True,
        },
        "scoring_schedule": {
            "ordered_case_ids": remediation_ids,
            "ordered_case_ids_sha256": dev_smoke._json_sha256(remediation_ids),
            "case_count": 5,
            "purpose": "FROZEN_V1_SCORE_ONE_CASE_COMPATIBILITY_ALIAS_ONLY",
            "authorization_expansion": False,
        },
        "remediation_schedule": {
            "ordered_case_ids": remediation_ids,
            "ordered_case_ids_sha256": dev_smoke._json_sha256(remediation_ids),
            "case_count": 5,
            "fresh_process_per_case": True,
            "worker_process_retries": 0,
            "merge_policy": "EXPLICIT_REPLACE_EXACT_FIVE_FAILED_ROWS_KEEP_75_IMMUTABLE",
        },
        "launch_manifest": {
            "status": "FROZEN_EXACT_FIVE_ZERO_RETRY",
            "assignment_count": 5,
            "assignments": launch_assignments,
            "contract_binding": "EXTERNAL_EXACT_SHA256_REQUIRED_AT_EXECUTION",
            "sixth_launch_authorized": False,
            "stale_output_policy": "REJECT",
        },
        "candidate15_failure_diagnostics": diagnostics15,
        "label_sources": contract13["label_sources"],
        "scoring_policy": scoring_policy,
        "hash_contract": {
            "algorithm": worker.HASH_ALGORITHM,
            "canonical_form": "RECURSIVE_TYPED_JSON_TAGGED_VALUES_V1",
            "legacy_complete_row_algorithm": orchestrator.LEGACY_HASH_ALGORITHM,
            "per_row_algorithm_required_in_composite": True,
            "unsupported_type_policy": "FAIL_CLOSED",
            "nonfinite_float_policy": "FAIL_CLOSED",
        },
        "pre_freeze_probes": {
            "schedule_contract_matrix": schedule_matrix,
            "exact_entrypoint_schedule": entrypoint_probes,
            "runtime_and_canonicalizer": runtime_probes,
            "composite_rejection_matrix": composite_matrix,
        },
        "sol_advisory": {
            "review_type": advisory["review_type"],
            "verdict": advisory["verdict"],
            "risk": advisory["risk"],
            "compatibility_alias_sufficient": True,
            "required_changes_implemented": len(advisory["required_changes"]),
            "human_approval_claim": False,
        },
        "change_control": {
            "candidate14_hash_fix_superseded_by_typed_versioned_canonicalizer": True,
            "candidate15_project_root_fix_retained": True,
            "candidate16_allowed_change": "ADD_EXACT_FIVE_SCORING_SCHEDULE_ALIAS_AND_SOL_REQUIRED_GATES",
            "checker_input_change": False,
            "official_checker_change": False,
            "turn_adapter_change": False,
            "final_valid_formula_change": False,
            "prompt_or_generation_change": False,
            "test_access_change": False,
        },
        "byte_closure": {
            "remediation_contract_builder": _source(Path(__file__), ROOT),
            "scoring_worker": _source(SCORING_WORKER, ROOT),
            "scoring_orchestrator": _source(SCORING_ORCHESTRATOR, ROOT),
            **official_closure,
        },
        "gate_results": {
            "candidate13_scoring": "INCOMPLETE_FIVE_POST_CHECKER_HASH_FAILURES_BOUND",
            "candidate14_remediation": "INCOMPLETE_FIVE_PRE_LABEL_IMPORT_FAILURES_BOUND",
            "candidate15_remediation": "INCOMPLETE_FIVE_PRE_LABEL_SCHEDULE_FAILURES_BOUND",
            "candidate16_pre_freeze_probes": "PASS_BOUND",
            "candidate16_execution": "AUTHORIZED_BY_EXACT_ACK_NOT_RUN",
            "test_execution": "NOT_AUTHORIZED",
            "BMG-03": "NO_GO_REMEDIATION_NOT_RUN",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
        },
        "known_limits": [
            "Candidate.13 through candidate.15 remain immutable and hash-bound.",
            "Candidate.16 may execute exactly five development workers and compose only after all five evidence rows complete.",
            "The contract digest is externally pinned and must be supplied exactly to the execution command.",
            "This is adapted prompt-mode development characterization, not an official leaderboard score or test authorization.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze Sol-gated candidate.16 five-case scoring remediation"
    )
    parser.add_argument("--freeze-remediation-contract", action="store_true")
    parser.add_argument("--freeze-ack")
    parser.add_argument("--candidate13-ledger", type=Path, required=True)
    parser.add_argument("--candidate14-ledger", type=Path, required=True)
    parser.add_argument("--candidate15-ledger", type=Path, required=True)
    parser.add_argument("--candidate15-run-directory", type=Path, required=True)
    parser.add_argument("--generation-ledger", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument("--sol-advisory-output", type=Path, required=True)
    parser.add_argument("--sol-advisory-events", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.freeze_remediation_contract or args.freeze_ack != FREEZE_ACK:
        raise RemediationContractV3Error(
            "remediation freeze requires the flag and exact acknowledgement"
        )
    report = build_contract(
        candidate13_ledger=args.candidate13_ledger.resolve(),
        candidate14_ledger=args.candidate14_ledger.resolve(),
        candidate15_ledger=args.candidate15_ledger.resolve(),
        candidate15_run_directory=args.candidate15_run_directory.resolve(),
        generation_ledger=args.generation_ledger.resolve(),
        bundle_path=args.bundle.resolve(),
        bfcl_root=args.bfcl_root.resolve(),
        sol_advisory_output=args.sol_advisory_output.resolve(),
        sol_advisory_events=args.sol_advisory_events.resolve(),
    )
    raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": dev_smoke._sha256_bytes(raw),
                "status": report["status"],
                "remediation_case_count": 5,
                "pre_freeze_probes": "PASS_BOUND",
                "test_access_authorized": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
