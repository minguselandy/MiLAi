"""HTTP identity and complete16-reference capacity gate, without generation."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx

from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_evidence import save, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import encoded
from v0222_boundary_audit import validate_reference
from v0222_boundary_batch import Batch
from v0222_boundary_http import boundary_identity
from v0222_http import bounded_request, strict_http_json


def preflight(root: Path, binding: str, *, transport=None) -> dict:
    batch = Batch(root, binding)
    batch.authorize("R1")
    for name, status in (
        ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
        ("engineering_checks", "ENGINEERING_CHECKS_PASS"),
    ):
        if batch.artifact(name)["status"] != status:
            raise ProviderStop("BOUNDARY_REVIEW_AND_ENGINEERING_REQUIRED_BEFORE_HTTP")
    if batch.snapshot()["stop"]:
        raise ProviderStop("BOUNDARY_ALREADY_STOPPED")
    references = batch.references()
    if len(references) != 16 or [r["episode"] for r in references] != [
        s["id"] for s in batch.plan["episodes"]
    ]:
        raise ProviderStop("ALL_16_REFERENCE_POSITIONS_REQUIRED")
    directory = root / "preflight"
    directory.mkdir(exist_ok=False)
    deadline = time.monotonic() + 600
    rows, calls, reason = [], [], None

    def admit_http():
        batch.authorize("R1")
        with batch.transaction() as db:
            batch.check_journal(db)

    try:
        with httpx.Client(
            base_url=ENDPOINT,
            transport=transport,
            timeout=5,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            identity = boundary_identity(client, directory / "identity-start", admit=admit_http)
            if identity != batch.plan["http_identity"]:
                raise ProviderStop("HTTP_IDENTITY_DRIFT")
            for row, spec in zip(references, batch.plan["episodes"], strict=True):
                batch.authorize("R1")
                _, wire, raw = validate_reference(batch, row, spec)
                counts = {}
                for kind, body in (
                    ("input", {k: wire[k] for k in TOKENIZE_KEYS}),
                    ("output", {"model": MODEL, "prompt": raw, "add_special_tokens": False}),
                ):
                    admit_http()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProviderStop("BOUNDARY_PREFLIGHT_DEADLINE")
                    stem = directory / (spec["id"] + "-" + kind)
                    attempt = {
                        "episode": spec["id"],
                        "kind": kind,
                        "method": "POST",
                        "route": "/tokenize",
                    }
                    save(stem.with_suffix(".request.json"), body)
                    save(stem.with_suffix(".attempt.json"), attempt)
                    calls.append(attempt)
                    started = time.monotonic()
                    try:
                        response = bounded_request(
                            client,
                            "POST",
                            "/tokenize",
                            content=encoded(body).encode(),
                            headers={"Content-Type": "application/json"},
                            timeout=min(5, remaining),
                        )
                    except Exception as exc:
                        save(
                            stem.with_suffix(".error.json"),
                            {
                                "exception_type": type(exc).__name__,
                                "seconds": time.monotonic() - started,
                            },
                        )
                        raise
                    save(
                        stem.with_suffix(".http.json"),
                        {
                            "status_code": response.status_code,
                            "body": response.text,
                            "seconds": time.monotonic() - started,
                        },
                    )
                    if response.status_code != 200:
                        raise ProviderStop("TOKENIZE_REQUIRES_HTTP_200")
                    count = strict_http_json(response.text)["count"]
                    if type(count) is not int or count < 0:
                        raise ProviderStop("INVALID_TOKENIZE_COUNT")
                    counts[kind] = count
                if counts["input"] + 4096 > 65536 or counts["output"] + 1 > 4096:
                    raise ProviderStop("COMPLETE_BOUNDARY_CAPACITY_NOT_ADMITTED")
                rows.append(
                    {"episode": spec["id"], "counts": counts, "reference_hashes": row["hashes"]}
                )
                print(f"capacity {len(rows)}/16 {spec['id']} {counts}", flush=True)
            batch.authorize("R1")
            if (
                time.monotonic() >= deadline
                or boundary_identity(client, directory / "identity-final", admit=admit_http)
                != identity
            ):
                raise ProviderStop("HTTP_IDENTITY_DRIFT_OR_PREFLIGHT_DEADLINE")
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
        batch.stop(reason)
    try:
        result = {
            "status": "G_PREFLIGHT_PASS"
            if reason is None and len(rows) == 16 and not batch.snapshot()["stop"]
            else "NOT_MET",
            "rows": rows,
            "tokenize_calls": calls,
            "reason": reason,
            "model_requests": 0,
            "files": {str(p): sha(p) for p in sorted(directory.rglob("*.json"))},
        }
        save(directory / "result.json", result)
        if result["status"] == "G_PREFLIGHT_PASS":
            batch.freeze_artifact("preflight", directory / "result.json", "G_PREFLIGHT_PASS")
    except Exception as exc:
        batch.stop(type(exc).__name__)
        raise
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    args = parser.parse_args()
    preflight(args.root, args.binding_sha256)
