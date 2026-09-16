"""Run and seal the DG-19 real-provider synthetic treatment-delivery gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

DEFAULT_OUTPUT_ROOT = ROOT / "var/dg19/synthetic-treatment"
DEFAULT_FIXTURE = ROOT / "evals/dg19/fixtures/synthetic-treatment-cases.v0.1.json"
DEFAULT_SCORER_FIXTURE = (
    ROOT / "evals/dg19/fixtures/synthetic-treatment-scorer.v0.1.json"
)
DEFAULT_PROVIDER_RECEIPT = (
    ROOT
    / "var/dg18/provider-conformance"
    / "dg18-provider-conformance-20260828-002/receipt.json"
)
EXPECTED_PROVIDER_RECEIPT_SHA256 = (
    "2e7bc6f96baa0ba22479c7b952eb8864d6714836c0b13d7783d04d16c750f53e"
)
RECEIPT_SCHEMA = "milai.dg18.synthetic-treatment-delivery-receipt.v0.1"


def run(
    *,
    run_id: str,
    output_root: Path,
    fixture_path: Path,
    scorer_path: Path = DEFAULT_SCORER_FIXTURE,
    base_url: str,
    model: str,
    provider_conformance_receipt_path: Path,
) -> dict[str, Any]:
    """Execute one fresh non-streaming run and return its terminal receipt."""

    from milai.adapters.semantic_hint import LoopbackVllmSemanticProvider

    from evals.dg19.synthetic_treatment_delivery import (
        run_product_shadow,
        score_sealed_shadow,
        seal_product_shadow,
    )
    from scripts.run_dg18_r3_shadow import (
        _provider_runtime_identity,
        _validated_provider_conformance,
        _validated_treatment_delivery,
    )

    if not run_id:
        raise ValueError("DG-19 run ID is required")
    if output_root.exists():
        raise FileExistsError("DG-19 output exists; choose a fresh run ID")
    provider_receipt_identity = _required_provider_receipt_identity(
        provider_conformance_receipt_path
    )
    provider_gate = _validated_provider_conformance(
        provider_conformance_receipt_path,
        base_url=base_url,
        model=model,
    )
    provider_runtime_identity = _provider_runtime_identity(base_url, model)
    output_root.mkdir(parents=True)
    try:
        product = run_product_shadow(
            run_id=run_id,
            provider=LoopbackVllmSemanticProvider(
                base_url=base_url,
                model=model,
                timeout_seconds=120.0,
                transport_mode="non-streaming",
            ),
            fixture_path=fixture_path,
            provider_runtime_identity=provider_runtime_identity,
        )
        sealed_path = output_root / "sealed-product-shadow.json"
        seal_product_shadow(product, sealed_path)
        score = score_sealed_shadow(
            sealed_path,
            fixture_path=fixture_path,
            scorer_path=scorer_path,
        )
        score_path = output_root / "score.json"
        _write_new(score_path, score)
        failure_path = _write_failure_ledger_if_needed(output_root, score)
        receipt = _build_receipt(
            run_id=run_id,
            product=product,
            score=score,
            fixture_path=fixture_path,
            scorer_path=scorer_path,
            sealed_path=sealed_path,
            score_path=score_path,
            failure_path=failure_path,
            provider_gate=provider_gate,
            provider_receipt_identity=provider_receipt_identity,
            provider_runtime_identity=provider_runtime_identity,
        )
        receipt_path = output_root / "receipt.json"
        _write_new(receipt_path, receipt)
        if receipt["status"] == "PASS_SYNTHETIC_TREATMENT_DELIVERY":
            _validated_treatment_delivery(receipt_path)
        return receipt
    except BaseException as exc:
        _write_execution_failure_if_absent(output_root, run_id=run_id, exc=exc)
        raise


def _required_provider_receipt_identity(path: Path) -> dict[str, str]:
    identity = _identity(path)
    if identity["sha256"] != EXPECTED_PROVIDER_RECEIPT_SHA256:
        raise RuntimeError("DG-19 provider conformance receipt hash drifted")
    return identity


def _build_receipt(
    *,
    run_id: str,
    product: Mapping[str, Any],
    score: Mapping[str, Any],
    fixture_path: Path,
    scorer_path: Path,
    sealed_path: Path,
    score_path: Path,
    failure_path: Path | None,
    provider_gate: Mapping[str, Any],
    provider_receipt_identity: Mapping[str, str],
    provider_runtime_identity: Mapping[str, Any],
) -> dict[str, Any]:
    summary = _mapping(score, "summary")
    hard_gate = _mapping(score, "hard_gate")
    artifacts: dict[str, Any] = {
        "fixture": _identity(fixture_path),
        "scorer_fixture": _identity(scorer_path),
        "sealed_product_shadow": _identity(sealed_path),
        "score": _identity(score_path),
    }
    if failure_path is not None:
        artifacts["failure_ledger"] = _identity(failure_path)
    return {
        "schema": RECEIPT_SCHEMA,
        "status": score["status"],
        "classification": "SYNTHETIC_ONLY / SHADOW_EVALUATION_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "lme_executed": False,
        "transport_mode": "non-streaming",
        "automatic_retry_count": int(summary["automatic_retry_count"]),
        "provider_identities": list(product["provider_identities"]),
        "provider_runtime_identity": dict(provider_runtime_identity),
        "summary": dict(summary),
        "hard_gate": dict(hard_gate),
        "label_boundary": dict(_mapping(score, "label_boundary")),
        "product_result_change_count": int(summary["product_result_change_count"]),
        "canonical_mutation_count": int(summary["canonical_mutation_count"]),
        "entry_gates": {
            "provider_conformance": {
                **dict(provider_receipt_identity),
                "status": provider_gate["status"],
                "exact_bound_hash": True,
            },
            "provider_runtime_identity": {
                "verified": provider_runtime_identity.get("verified") is True,
                "base_url": provider_runtime_identity.get("base_url"),
                "configured_model": provider_runtime_identity.get("configured_model"),
            },
        },
        "executables": {
            "evaluator": _identity(ROOT / "evals/dg19/synthetic_treatment_delivery.py"),
            "runner": _identity(
                ROOT / "scripts/run_dg19_synthetic_treatment_shadow.py"
            ),
        },
        "artifacts": artifacts,
    }


def _write_failure_ledger_if_needed(
    output_root: Path, score: Mapping[str, Any]
) -> Path | None:
    if score.get("status") == "PASS_SYNTHETIC_TREATMENT_DELIVERY":
        return None
    hard_gate = _mapping(score, "hard_gate")
    checks = _mapping(hard_gate, "checks")
    rows = score.get("rows")
    failed_cases = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            controller = row.get("controller")
            failed_cases.append(
                {
                    "case_id": row.get("case_id"),
                    "schema_valid": row.get("schema_valid"),
                    "runtime_status": row.get("runtime_status"),
                    "action": row.get("action"),
                    "new_governed_candidate_count": row.get(
                        "new_governed_candidate_count"
                    ),
                    "missing_requirement_improved": row.get(
                        "missing_requirement_improved"
                    ),
                    "error": (
                        controller.get("error")
                        if isinstance(controller, Mapping)
                        else None
                    ),
                }
            )
    path = output_root / "failure-ledger.json"
    _write_new(
        path,
        {
            "schema": "milai.dg19.synthetic-treatment-failure-ledger.v0.1",
            "status": score["status"],
            "failed_checks": sorted(
                str(key) for key, value in checks.items() if value is False
            ),
            "cases": failed_cases,
            "automatic_retry_count": _mapping(score, "summary").get(
                "automatic_retry_count"
            ),
            "formal_holdout_consumed": False,
        },
    )
    return path


def _write_execution_failure_if_absent(
    output_root: Path, *, run_id: str, exc: BaseException
) -> None:
    path = output_root / "failure-ledger.json"
    if path.exists():
        return
    _write_new(
        path,
        {
            "schema": "milai.dg19.synthetic-treatment-failure-ledger.v0.1",
            "status": "FAILED_PROVIDER_DELIVERY",
            "run_id": run_id,
            "failure_owner": "EXECUTION_OR_PROVIDER",
            "error_type": type(exc).__name__,
            "error_code": str(exc).split(":", 1)[0][:256],
            "automatic_retry_count": 0,
            "formal_holdout_consumed": False,
        },
    )


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    result = value.get(key)
    if not isinstance(result, Mapping):
        raise TypeError(f"DG-19 {key} must be a mapping")
    return result


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write_new(path: Path, value: object) -> None:
    payload = (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n"
    )
    with path.open("xb") as handle:
        handle.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--scorer-fixture", type=Path, default=DEFAULT_SCORER_FIXTURE)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--model", default="Qwen3.6-35B-A3B-FP8")
    parser.add_argument(
        "--provider-conformance-receipt",
        type=Path,
        default=DEFAULT_PROVIDER_RECEIPT,
    )
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run(
        run_id=args.run_id,
        output_root=output_root,
        fixture_path=args.fixture,
        scorer_path=args.scorer_fixture,
        base_url=args.base_url,
        model=args.model,
        provider_conformance_receipt_path=args.provider_conformance_receipt,
    )
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "run_id": args.run_id,
                "receipt": str(receipt_path),
                "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return int(receipt["status"] != "PASS_SYNTHETIC_TREATMENT_DELIVERY")


if __name__ == "__main__":
    raise SystemExit(main())
