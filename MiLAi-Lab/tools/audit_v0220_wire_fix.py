"""Verify the repaired full-schema gate and preserved historical stop with zero HTTP."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

from v0220_evidence import LAB, read, save, seal, sha, validate
from v0220_provider_hardened import ProviderStop, historical_usage
from v0220_wire_admission import WireSchemaAdmission, backend_identity
from v0220_wire_contract import compile_contract
from v0220_wire_provider import WireProvider


def run(matrix: Path, root: Path, container: str) -> dict:
    validate(matrix)
    base = Path("/cra/memory/mx_memory/evidence/v0220")
    ledgers = (
        base / "provider-compat-v1/provider-ledger.jsonl",
        base / "v2-candidate1-v1/episodes/v2c1-01/provider-ledger.jsonl",
    )
    hashes = {
        name: sha(matrix / name)
        for name in ("manifest.json", "result.json", "inventory.json", "probes.json")
    }
    seal(
        root,
        entries=[Path(__file__), LAB / "tests/unit/test_v0220_wire_compat.py"],
        inputs=[*(matrix / k for k in hashes), *ledgers],
        contract={
            "profile": "WIRE_ADMISSION_AND_HISTORICAL_STOP_AUDIT",
            "model_requests": 0,
            "HTTP_requests": 0,
            "historical_usage_waived": False,
            "matrix_hashes": hashes,
            "shared_service_changes": False,
        },
    )
    before = {str(p): sha(p) for p in ledgers}
    current = backend_identity(container)
    gate = WireSchemaAdmission(matrix, hashes=hashes, identity=lambda: current)
    admitted = []
    for row in read(matrix / "inventory.json"):
        body = read(matrix / "requests" / (row["id"] + "-canonical.json"))
        wire = compile_contract(body["response_format"]["json_schema"]["schema"]).prepare(body)
        gate(body, wire)
        admitted.append(row["id"])
    assert len(admitted) == 8 and backend_identity(container) == current
    usage = historical_usage(ledgers)
    assert usage["requests"] == 3 and usage["known_raw_tokens"] == 2221
    assert usage["actual_total_raw_tokens"] is None and len(usage["unresolved_reservations"]) == 1
    assert usage["reserved_raw_upper_bound"] == 28284
    calls = []

    def never_http(request):
        calls.append(request.url.path)
        raise AssertionError("ZERO_HTTP_AUDIT_MUST_NOT_SEND")

    provider = WireProvider(
        root / "no-dispatch-proof",
        deadline=time.monotonic() + 20,
        max_requests=1,
        historical_ledgers=ledgers,
        admission=gate,
        transport=httpx.MockTransport(never_http),
    )
    try:
        provider.generate("preserve-unknown", body)
    except ProviderStop as exc:
        stopped = str(exc)
    else:
        raise AssertionError("UNSETTLED_HISTORY_WAS_BYPASSED")
    finally:
        provider.close()
    assert stopped == "UNSETTLED_USAGE_NO_RETRY" and not calls
    assert not provider.provider.ledger.exists()
    assert before == {str(p): sha(p) for p in ledgers}
    result = {
        "status": "WIRE_CPU_ADMISSION_PASS_HISTORICAL_STOP_PRESERVED",
        "admitted_schema_variants": admitted,
        "historical_usage": usage,
        "history_guard": stopped,
        "new_HTTP_requests": calls,
        "new_model_requests": 0,
        "V2_resumed": False,
        "live_compatibility": "NOT_TESTED_NOT_AUTHORIZED_BY_CPU_PASS",
        "wire_schema_repair": (
            "All original targets accepted at CPU layer; business validation intact"
        ),
    }
    validate(root)
    validate(matrix)
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--container", required=True)
    args = parser.parse_args()
    result = run(args.matrix, args.root, args.container)
    print(json.dumps({k: v for k, v in result.items() if k != "historical_usage"}))
