"""HTTP-only identity/capacity gate over every actual wire reference request."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx

from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import compile_contract, encoded
from v0221_http_admission_v2 import HTTPAdmissionV2 as HTTPAdmission
from v0221_http_batch import Batch
from v0221_http_provider import http_identity


def preflight(root: Path, binding: str) -> dict:
    batch = Batch(root, binding)
    batch.authorize("W1")
    directory = root / "preflight"
    directory.mkdir(exist_ok=False)
    deadline = time.monotonic() + 600
    save(
        directory / "started.json",
        {"unix": time.time(), "seconds_bound": 600, "method": "HTTP_ONLY_NO_DEVICE_QUERY"},
    )
    references, rows, calls = batch.references(), [], []
    reason = None
    try:
        with httpx.Client(
            base_url=ENDPOINT, timeout=5, trust_env=False, follow_redirects=False
        ) as client:
            current = http_identity(client, directory / "identity")
            if current != batch.plan["http_identity"]:
                raise ProviderStop("HTTP_SERVICE_IDENTITY_MISMATCH")
            gate = HTTPAdmission(batch, directory, client)
            for i, row in enumerate(references, 1):
                batch.authorize("W1")
                if time.monotonic() >= deadline:
                    raise ProviderStop("PREFLIGHT_DEADLINE")
                for kind in ("canonical", "wire", "output"):
                    if sha(Path(row[kind])) != row["hashes"][kind]:
                        raise ProviderStop("FROZEN_REFERENCE_DRIFT")
                original, wire = read(Path(row["canonical"])), read(Path(row["wire"]))
                contract = compile_contract(original["response_format"]["json_schema"]["schema"])
                if contract.prepare(original) != wire:
                    raise ProviderStop("FULL_PREPARED_REQUEST_DRIFT")
                # All frozen historical CPU pairs/options checked, no container invocation.
                gate.validate_historical_pair(original, wire)
                raw = read(Path(row["output"]))["raw"]
                contract.validate_output(raw)
                requests = {
                    "input": {k: wire[k] for k in TOKENIZE_KEYS},
                    "output": {"model": MODEL, "prompt": raw, "add_special_tokens": False},
                }
                counts = {}
                for kind, request in requests.items():
                    stem = directory / f"{i:03d}-{kind}"
                    save(stem.with_suffix(".request.json"), request)
                    started = time.monotonic()
                    response = client.post(
                        "/tokenize",
                        content=encoded(request).encode(),
                        headers={"Content-Type": "application/json"},
                        timeout=min(5, max(0.01, deadline - time.monotonic())),
                    )
                    calls.append(
                        {"reference": i, "kind": kind, "status_code": response.status_code}
                    )
                    save(
                        stem.with_suffix(".http.json"),
                        {
                            "status_code": response.status_code,
                            "body": response.text,
                            "seconds": time.monotonic() - started,
                        },
                    )
                    response.raise_for_status()
                    count = response.json()["count"]
                    if type(count) is not int or count < 0:
                        raise ProviderStop("UNRELIABLE_TOKENIZE_COUNT")
                    counts[kind] = count
                outcome = {
                    "episode": row["episode"],
                    "stage": row["stage"],
                    "turn": row["turn"],
                    "counts": counts,
                    "wire_sha256": row["hashes"]["wire"],
                    "input_fits": counts["input"] + 4096 <= 65536,
                    "reference_output_fits": counts["output"] + 1 <= 4096,
                    "wire_contract": contract.manifest(),
                }
                rows.append(outcome)
                print(
                    f"capacity {i}/{len(references)} {row['episode']} "
                    f"input={counts['input']}+4096 output={counts['output']}",
                    flush=True,
                )
                if not outcome["input_fits"] or not outcome["reference_output_fits"]:
                    raise ProviderStop("CAPACITY_NOT_ADMITTED")
            final_identity = http_identity(client, directory / "final-identity")
            if final_identity != current:
                raise ProviderStop("HTTP_IDENTITY_DRIFT_DURING_PREFLIGHT")
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
        batch.stop(reason)
    result = {
        "status": "G_PREFLIGHT_PASS"
        if reason is None and len(rows) == len(references)
        else "G_PREFLIGHT_NOT_MET",
        "reason": reason,
        "rows": rows,
        "planned_reference_requests": len(references),
        "tokenize_calls": calls,
        "model_requests": 0,
        "direct_device_queries": 0,
        "CPU_proof": "FROZEN_HISTORICAL_MATRIX_REVALIDATED_NOT_NEW_INSTALLED_CODE_RUN",
        "identity_limit": "HTTP identity is not a fresh container/image/process attestation",
    }
    save(directory / "result.json", result)
    if result["status"] == "G_PREFLIGHT_PASS":
        batch.allow_preflight(directory / "result.json")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    args = parser.parse_args()
    preflight(args.root, args.binding_sha256)
