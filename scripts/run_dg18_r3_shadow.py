"""Run DG-18 R3 one-call residual shadow, seal it, then score opened-dev."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

DEFAULT_OUTPUT_ROOT = ROOT / "var/dg18/r3"
DEFAULT_Q1R_ARCHIVE = (
    ROOT
    / "var/dg17/a2/dg17-a2-per-slot-fusion-20260827-004"
    / "product-contexts-001/contexts.json"
)


def run(
    *,
    run_id: str,
    output_root: Path,
    q1r_archive_path: Path,
    base_url: str,
    model: str,
    candidate_cap: int,
    provider_conformance_receipt_path: Path,
    treatment_delivery_receipt_path: Path,
) -> dict[str, object]:
    from milai.adapters.semantic_hint import LoopbackVllmSemanticProvider

    from evals.dg18.residual_shadow import (
        opened_dev_questions,
        run_product_shadow,
        score_sealed_shadow,
        seal_product_shadow,
    )

    if output_root.exists():
        raise FileExistsError("R3 output exists; choose a fresh run ID")
    provider_gate = _validated_provider_conformance(
        provider_conformance_receipt_path,
        base_url=base_url,
        model=model,
    )
    treatment_gate = _validated_treatment_delivery(treatment_delivery_receipt_path)
    output_root.mkdir(parents=True)
    provider_runtime_identity = _provider_runtime_identity(base_url, model)
    product = run_product_shadow(
        run_id=run_id,
        q1r_archive_path=q1r_archive_path,
        questions=opened_dev_questions(),
        provider=LoopbackVllmSemanticProvider(
            base_url=base_url,
            model=model,
            transport_mode="non-streaming",
        ),
        candidate_cap=candidate_cap,
        provider_runtime_identity=provider_runtime_identity,
    )
    shadow_path = output_root / "sealed-product-shadow.json"
    seal_product_shadow(product, shadow_path)
    score = score_sealed_shadow(shadow_path)
    score_path = output_root / "score.json"
    _write_new(score_path, score)
    receipt = {
        "schema": "milai.dg18.r3-shadow-receipt.v0.1",
        "status": "R3_SHADOW_COMPLETE",
        "classification": "OPENED_DEVELOPMENT_ONLY / SHADOW_EVALUATION_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "runtime_retrieval_live_path_changed": False,
        "product_hint_consumption_count": 0,
        "automatic_retries": score["aggregate"]["automatic_retries"],
        "provider_identities": product["provider_identities"],
        "provider_runtime_identity": provider_runtime_identity,
        "artifacts": {
            "sealed_product_shadow": _identity(shadow_path),
            "score": _identity(score_path),
            "q1r_archive": _identity(q1r_archive_path),
        },
        "hard_gate": score["hard_gate"],
        "treatment_delivery_outcome": score["treatment_delivery_outcome"],
        "residual_effect_outcome": score["residual_effect_outcome"],
        "disposition": score["disposition"],
        "label_boundary": score["label_boundary"],
        "entry_gates": {
            "provider_conformance": {
                **_identity(provider_conformance_receipt_path),
                "status": provider_gate["status"],
            },
            "synthetic_treatment_delivery": {
                **_identity(treatment_delivery_receipt_path),
                "status": treatment_gate["status"],
            },
        },
    }
    receipt_path = output_root / "receipt.json"
    _write_new(receipt_path, receipt)
    return receipt


def _provider_runtime_identity(base_url: str, model: str) -> dict[str, object]:
    """Bind the configured controller to the live loopback model and listener."""

    parsed = urlparse(base_url.rstrip("/"))
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port is None
    ):
        raise ValueError("R3 provider identity requires an explicit loopback endpoint")
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    try:
        connection.request("GET", "/v1/models")
        response = connection.getresponse()
        response_status = response.status
        body = response.read(1_048_576)
    finally:
        connection.close()
    if response_status != 200:
        raise RuntimeError(f"R3 /v1/models identity failed with HTTP {response_status}")
    decoded = json.loads(body)
    data = decoded.get("data") if isinstance(decoded, dict) else None
    model_values = data if isinstance(data, list) else []
    model_ids = sorted(
        str(item["id"])
        for item in model_values
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
    )
    if model not in model_ids:
        raise RuntimeError("configured R3 model is absent from the live /v1/models identity")
    version_connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    try:
        version_connection.request("GET", "/version")
        version_response = version_connection.getresponse()
        version_body = version_response.read(1_048_576)
    finally:
        version_connection.close()
    if version_response.status != 200:
        raise RuntimeError(
            f"R3 /version identity failed with HTTP {version_response.status}"
        )
    version_decoded = json.loads(version_body)
    provider_version = (
        version_decoded.get("version")
        if isinstance(version_decoded, dict)
        else None
    )
    if not isinstance(provider_version, str) or not provider_version:
        raise RuntimeError("R3 provider version identity is invalid")
    listener = subprocess.run(
        ["ss", "-ltnp", f"sport = :{parsed.port}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    listener_output = listener.stdout.strip()
    listener_observed = listener.returncode == 0 and "LISTEN" in listener_output
    if not listener_observed:
        raise RuntimeError("R3 provider listener identity is not observable")
    return {
        "schema": "milai.dg18.provider-runtime-identity.v0.1",
        "verified": True,
        "base_url": base_url.rstrip("/"),
        "configured_model": model,
        "models_endpoint_verified": True,
        "available_model_ids": model_ids,
        "models_response_sha256": hashlib.sha256(body).hexdigest(),
        "provider_version": provider_version,
        "version_response_sha256": hashlib.sha256(version_body).hexdigest(),
        "listener_observed": True,
        "listener_receipt_sha256": hashlib.sha256(listener_output.encode()).hexdigest(),
    }


def _validated_provider_conformance(
    path: Path, *, base_url: str, model: str
) -> dict[str, object]:
    value = _load_object(path)
    identity = value.get("provider_runtime_identity")
    if (
        value.get("schema") != "milai.dg18.provider-conformance-receipt.v0.1"
        or value.get("status") != "PASS_PROVIDER_CONFORMANCE"
        or value.get("formal_holdout_consumed") is not False
        or value.get("lme_executed") is not False
        or not isinstance(identity, dict)
        or identity.get("base_url") != base_url.rstrip("/")
        or identity.get("configured_model") != model
    ):
        raise RuntimeError("R3 provider conformance entry gate is not satisfied")
    return value


def _validated_treatment_delivery(path: Path) -> dict[str, object]:
    value = _load_object(path)
    summary = value.get("summary")
    if (
        value.get("schema") != "milai.dg18.synthetic-treatment-delivery-receipt.v0.1"
        or value.get("status") != "PASS_SYNTHETIC_TREATMENT_DELIVERY"
        or value.get("formal_holdout_consumed") is not False
        or not isinstance(summary, dict)
        or int(summary.get("schema_valid_hint_count", 0)) < 2
        or int(summary.get("runtime_accepted_hint_count", 0)) < 2
        or int(summary.get("additional_acquisition_pass_count", 0)) < 1
    ):
        raise RuntimeError("R3 synthetic treatment-delivery entry gate is not satisfied")
    return value


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("R3 entry-gate receipt must be a JSON object")
    return value


def _identity(path: Path) -> dict[str, str]:
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_new(path: Path, value: object) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    with path.open("xb") as handle:
        handle.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--q1r-archive", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--model", required=True)
    parser.add_argument("--candidate-cap", type=int, default=8)
    parser.add_argument("--provider-conformance-receipt", type=Path, required=True)
    parser.add_argument("--treatment-delivery-receipt", type=Path, required=True)
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run(
        run_id=args.run_id,
        output_root=output_root,
        q1r_archive_path=args.q1r_archive,
        base_url=args.base_url,
        model=args.model,
        candidate_cap=args.candidate_cap,
        provider_conformance_receipt_path=args.provider_conformance_receipt,
        treatment_delivery_receipt_path=args.treatment_delivery_receipt,
    )
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "run_id": args.run_id,
                "receipt": str(receipt_path),
                "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                "disposition": receipt["disposition"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
