"""Bounded HTTP identity and exact P1 wire/reference capacity, zero generations."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx

from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import encoded, fingerprint
from v0222_batch import Batch
from v0222_diagnostic import observe, request
from v0222_http import bounded_request, http_identity, strict_http_json


def preflight(root: Path, binding: str) -> dict:
    batch = Batch(root, binding)
    batch.authorize("P1")
    if batch.snapshot()["stop"]:
        raise ProviderStop("BATCH_ALREADY_STOPPED")
    if batch.artifact("scope_review")["status"] != "G_AUTH_SCOPE_REVIEW_PASS":
        raise ProviderStop("INDEPENDENT_SCOPE_REVIEW_REQUIRED")
    directory = root / "P1-preflight"
    directory.mkdir(exist_ok=False)
    rows, reason, calls = [], None, []
    deadline = time.monotonic() + 600
    try:
        with httpx.Client(
            base_url=ENDPOINT, timeout=5, trust_env=False, follow_redirects=False
        ) as client:
            identity = http_identity(client, directory / "identity-start")
            if identity != batch.plan["http_identity"]:
                raise ProviderStop("HTTP_IDENTITY_DRIFT")
            for row in batch.references("P1"):
                batch.authorize("P1")
                for kind in ("canonical", "wire", "output"):
                    if sha(Path(row[kind])) != row["hashes"][kind]:
                        raise ProviderStop("FROZEN_REFERENCE_DRIFT")
                canonical, wire = request(row["fixture"], row["condition"])
                if fingerprint(canonical) != fingerprint(
                    read(Path(row["canonical"]))
                ) or fingerprint(wire) != fingerprint(read(Path(row["wire"]))):
                    raise ProviderStop("DIAGNOSTIC_CONTRAST_CHANGED")
                raw = read(Path(row["output"]))["raw"]
                if not observe(raw, row["fixture"])["exact_fidelity"]:
                    raise ProviderStop("REFERENCE_NOT_LEGAL_AND_EXACT")
                counts = {}
                for kind, body in (
                    ("input", {k: wire[k] for k in TOKENIZE_KEYS}),
                    ("output", {"model": MODEL, "prompt": raw, "add_special_tokens": False}),
                ):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProviderStop("PREFLIGHT_DEADLINE")
                    stem = directory / (row["episode"] + "-" + kind)
                    save(stem.with_suffix(".request.json"), body)
                    started = time.monotonic()
                    attempt = {
                        "episode": row["episode"],
                        "kind": kind,
                        "status_code": None,
                        "attempted": True,
                    }
                    calls.append(attempt)
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
                        attempt["exception_type"] = type(exc).__name__
                        save(
                            stem.with_suffix(".error.json"),
                            {**attempt, "seconds": time.monotonic() - started},
                        )
                        raise
                    attempt["status_code"] = response.status_code
                    save(
                        stem.with_suffix(".http.json"),
                        {
                            "status_code": response.status_code,
                            "body": response.text,
                            "seconds": time.monotonic() - started,
                        },
                    )
                    response.raise_for_status()
                    count = strict_http_json(response.text)["count"]
                    if type(count) is not int or count < 0:
                        raise ProviderStop("INVALID_TOKENIZE_COUNT")
                    counts[kind] = count
                if counts["input"] + 4096 > 65536 or counts["output"] + 1 > 4096:
                    raise ProviderStop("CAPACITY_NOT_ADMITTED")
                rows.append(
                    {"episode": row["episode"], "counts": counts, "reference_hashes": row["hashes"]}
                )
                print(f"capacity {len(rows)}/24 {row['episode']} {counts}", flush=True)
            if http_identity(client, directory / "identity-final") != identity:
                raise ProviderStop("HTTP_IDENTITY_DRIFT")
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
        batch.stop(reason)
    result = {
        "status": "G_PREFLIGHT_PASS" if reason is None and len(rows) == 24 else "NOT_MET",
        "rows": rows,
        "tokenize_calls": calls,
        "reason": reason,
        "model_requests": 0,
        "direct_device_calls": 0,
        "files": {str(path): sha(path) for path in sorted(directory.rglob("*.json"))},
    }
    save(directory / "result.json", result)
    if result["status"] == "G_PREFLIGHT_PASS":
        try:
            batch.freeze_artifact("P1_preflight", directory / "result.json", "G_PREFLIGHT_PASS")
        except Exception as exc:
            batch.stop(type(exc).__name__)
            save(
                directory / "admission-error.json",
                {"status": "NOT_ADMITTED", "exception_type": type(exc).__name__},
            )
            raise
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    args = parser.parse_args()
    preflight(args.root, args.binding_sha256)
