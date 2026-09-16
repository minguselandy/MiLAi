from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg11_state
from scripts import run_dg10_f0 as package_gate
from scripts import run_dg10_f0_native as native_gate
from scripts import run_dg10_f1_openworker as f1_gate
from scripts import run_dg10_hardened_openworker as hardened_gate
from scripts import run_dg10_t2_openworker as t2_gate

RUNS_ROOT = ROOT / "var/dg11/runs"
LATEST_RESULT = ROOT / "var/dg11/functional/latest-result.json"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected an object in {path}")
    return value


def _configure_isolated_legacy_storage(run_root: Path) -> Path:
    steps_root = run_root / "steps"
    steps_root.mkdir()
    package_gate.RUNS_ROOT = steps_root
    package_gate.CURRENT_STATE = run_root / "legacy-current-state.json"
    package_gate.EXPERIMENTS = run_root / "legacy-experiments.jsonl"
    return steps_root


def _run_step(
    name: str,
    operation: Callable[[], dict[str, Any]],
    results: dict[str, dict[str, Any]],
) -> bool:
    result = operation()
    results[name] = result
    return result.get("status") == "PASS"


def _all_pass(cases: dict[str, Any], expected: tuple[str, ...]) -> bool:
    return set(cases) == set(expected) and all(
        cases[name] == "PASS" for name in expected
    )


def _classify(
    *,
    steps_root: Path,
    results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    package = results.get("package", {})
    native = results.get("f0_native", {})
    f1 = results.get("f1", {})
    t2 = results.get("t2", {})
    hardened = results.get("hardened", {})

    f0_cases = {**package.get("cases", {}), **native.get("cases", {})}
    f1_cases = {
        name: value
        for name, value in f1.get("cases", {}).items()
        if name.startswith("OW-F1-")
    }
    hardened_cases = hardened.get("cases", {})

    native_report_path = steps_root / "f0-native-step/native-e2e.json"
    f1_report_path = steps_root / "f1-openworker-step/openworker-e2e.json"
    hardened_report_path = (
        steps_root / "hardened-openworker-step/hardened-openworker.json"
    )
    native_report = (
        _read_json(native_report_path) if native_report_path.is_file() else {}
    )
    f1_report = _read_json(f1_report_path) if f1_report_path.is_file() else {}
    hardened_report = (
        _read_json(hardened_report_path) if hardened_report_path.is_file() else {}
    )
    scenarios = hardened_report.get("scenarios", {})

    secret_checks = {
        "native_cleanup": (native_report.get("cleanup") or {}).get(
            "secret_artifacts_absent"
        )
        is True,
        "f1_cleanup": f1_report.get("secret_artifacts_absent") is True,
        "t2_worker": (t2.get("security") or {}).get("secret_scan") == "PASS",
        "hardened_model_induced": (scenarios.get("S10") or {}).get(
            "milai_secret_absent"
        )
        is True,
    }
    expected_hardened = tuple(hardened_gate.SCENARIOS)
    provider_requests = sum(
        int(result.get("provider_requests", 0)) for result in (f1, t2, hardened)
    )
    expected_provider_requests = 4 + len(t2_gate.CASE_IDS) + 2
    gates = {
        "fresh_wheel_and_sdist_install": package.get("status") == "PASS",
        "f0_10_of_10": _all_pass(
            f0_cases, tuple(f"F0-{index:02d}" for index in range(1, 11))
        ),
        "f1_5_of_5": _all_pass(
            f1_cases, tuple(f"OW-F1-{index:02d}" for index in range(1, 6))
        ),
        "affected_t2_24_of_24": _all_pass(t2.get("cases", {}), t2_gate.CASE_IDS),
        "affected_s1_s10": _all_pass(hardened_cases, expected_hardened),
        "canonical_mutation_semantics_unchanged": (
            native.get("status") == "PASS"
            and (scenarios.get("S8b") or {}).get("canonical_changed") is False
        ),
        "secret_private_content_leakage_zero": all(secret_checks.values()),
        "provider_denominator_exact": provider_requests == expected_provider_requests,
        "hidden_provider_calls_zero": (
            t2.get("hidden_model_calls") == 0
            and provider_requests == expected_provider_requests
        ),
    }
    return {
        "status": "PASS" if all(gates.values()) else "FAILED",
        "gates": gates,
        "f0_cases": f0_cases,
        "f1_cases": f1_cases,
        "t2_cases": t2.get("cases", {}),
        "hardened_cases": hardened_cases,
        "secret_checks": secret_checks,
        "provider_requests": provider_requests,
        "expected_provider_requests": expected_provider_requests,
    }


def _record(result: dict[str, Any]) -> None:
    dg11_state.atomic_json(LATEST_RESULT, result)
    current = _read_json(dg11_state.CURRENT_STATE)
    current["phase"] = (
        "FUNCTIONAL_REGRESSION_PASSED"
        if result["status"] == "PASS"
        else "FUNCTIONAL_REGRESSION_FAILED"
    )
    current["work_packages"]["DG11-06"] = result["status"]
    current["latest_result"] = result["run_id"]
    current["development_ai_reviews"] = 0
    dg11_state.atomic_json(dg11_state.CURRENT_STATE, current)
    dg11_state.append_ledger(
        {
            "run_id": result["run_id"],
            "work_package": "DG11-06",
            "status": result["status"],
            "provider_requests": result["provider_requests"],
            "development_ai_reviews": 0,
            "metrics": result["classification"],
        }
    )


def run(run_id: str, *, endpoint: str = f1_gate.ENDPOINT) -> dict[str, Any]:
    if package_gate._RUN_ID.fullmatch(run_id) is None:
        raise package_gate.F0Error("run_id must be 8-96 lowercase URL-safe characters")
    run_root = RUNS_ROOT / run_id
    try:
        run_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise package_gate.F0Error(f"run_id already exists: {run_id}") from exc
    steps_root = _configure_isolated_legacy_storage(run_root)
    started = time.monotonic()
    results: dict[str, dict[str, Any]] = {}
    unexpected_error: str | None = None
    try:
        if not _run_step(
            "package",
            lambda: package_gate.run_f0_package("package-step"),
            results,
        ):
            raise package_gate.F0Error("fresh package/install step failed")
        if not _run_step(
            "f0_native",
            lambda: native_gate.run_f0_native("f0-native-step", "package-step"),
            results,
        ):
            raise package_gate.F0Error("native F0 step failed")
        if not _run_step(
            "f1",
            lambda: f1_gate.run_openworker(
                "f1-openworker-step", "package-step", endpoint=endpoint
            ),
            results,
        ):
            raise package_gate.F0Error("OpenWorker F1 step failed")
        if not _run_step(
            "t2",
            lambda: t2_gate.run_t2_openworker(
                "t2-openworker-step", "package-step", endpoint=endpoint
            ),
            results,
        ):
            raise package_gate.F0Error("affected T2 step failed")
        if not _run_step(
            "hardened",
            lambda: hardened_gate.run(
                "hardened-openworker-step",
                "package-step",
                "f1-openworker-step",
                endpoint=endpoint,
            ),
            results,
        ):
            raise package_gate.F0Error("hardened S1-S10 step failed")
    except Exception as exc:  # noqa: BLE001 - preserve the first failed terminal
        unexpected_error = f"{type(exc).__name__}: {exc}"

    classification = _classify(steps_root=steps_root, results=results)
    result = {
        "schema": "milai.dg11.functional-regression-result.v1",
        "run_id": run_id,
        "status": classification["status"],
        "classification": classification,
        "steps": {
            name: {
                "run_id": value.get("run_id"),
                "status": value.get("status"),
                "error": value.get("error"),
            }
            for name, value in results.items()
        },
        "provider_requests": classification["provider_requests"],
        "development_ai_reviews": 0,
        "runtime_database_suite": "NOT_RUN_UNAFFECTED",
        "error": unexpected_error,
        "duration_seconds": round(time.monotonic() - started, 6),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.atomic_json(run_root / "result.json", result)
    _record(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run isolated DG11-06 affected functional and safety regression"
    )
    parser.add_argument(
        "--run-id",
        default=(
            "dg11-functional-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
    parser.add_argument("--endpoint", default=f1_gate.ENDPOINT)
    args = parser.parse_args()
    result = run(args.run_id, endpoint=args.endpoint)
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "gates": result["classification"]["gates"],
                "provider_requests": result["provider_requests"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
