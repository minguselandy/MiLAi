"""Seal the full-schema refusal and historical-usage stop without any model request."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx

from v0220_evidence import LAB, read, save, seal, sha, validate
from v0220_provider_hardened import Provider, ProviderStop, historical_usage
from v0220_schema_admission import FullSchemaPreflight


def run(root: Path) -> dict:
    base = Path("/cra/memory/mx_memory/evidence")
    diagnostic = base / "v0220-provider-hardening"
    matrix = diagnostic / "full-schema-v1"
    localization = diagnostic / "error-localization-v2"
    source = base / "v0220/v2-candidate1-v1"
    ledgers = (
        base / "v0220/provider-compat-v1/provider-ledger.jsonl",
        source / "episodes/v2c1-01/provider-ledger.jsonl",
    )
    request = source / "episodes/v2c1-01/v2c1-01-01-request.json"
    validate(matrix)
    validate(localization)
    hashes = {
        name: sha(matrix / name)
        for name in ("manifest.json", "result.json", "inventory.json", "probes.json")
    }
    seal(
        root,
        entries=[Path(__file__), LAB / "tests/unit/test_v0220_provider_hardened.py"],
        inputs=[
            *ledgers,
            request,
            localization / "result.json",
            *[matrix / name for name in hashes],
        ],
        contract={
            "user_goal": "Full Schema Provider compatibility, error localization and unknown "
            "usage handling before deciding whether V2 can resume; no new tasks/State",
            "model_requests": 0,
            "raw_token_cap": None,
            "no_historical_usage_waiver": True,
            "no_shared_service_changes": True,
            "matrix_hashes": hashes,
        },
    )
    before = {str(p): sha(p) for p in ledgers}
    usage = historical_usage(ledgers)
    save(root / "historical-usage.json", usage)
    assert usage["requests"] == 3 and usage["known_raw_tokens"] == 2221
    assert usage["actual_total_raw_tokens"] is None
    assert usage["reserved_raw_upper_bound"] == 28284
    assert len(usage["unresolved_reservations"]) == 1
    gate = FullSchemaPreflight(matrix, hashes=hashes)
    try:
        gate(read(request))
    except ProviderStop as exc:
        schema_stop = str(exc)
    else:
        raise AssertionError("FAILED_FULL_SCHEMA_WAS_ADMITTED")
    assert schema_stop == "FULL_SCHEMA_PROVIDER_INCOMPATIBLE_NO_DISPATCH"
    calls = []

    def never_http(request):
        calls.append(request.url.path)
        raise AssertionError("NO_HTTP_ALLOWED_IN_ACCOUNTING_AUDIT")

    provider = Provider(
        root / "no-dispatch-proof",
        deadline=time.monotonic() + 10,
        max_requests=1,
        historical_ledgers=ledgers,
        preflight=gate,
        transport=httpx.MockTransport(never_http),
    )
    try:
        provider.generate("no-dispatch-proof", read(request))
    except ProviderStop as exc:
        usage_stop = str(exc)
    else:
        raise AssertionError("HISTORICAL_UNKNOWN_WAS_BYPASSED")
    finally:
        provider.close()
    assert usage_stop == "UNSETTLED_USAGE_NO_RETRY" and not calls
    assert not provider.ledger.exists()
    assert before == {str(p): sha(p) for p in ledgers}
    result = {
        "status": "PROVIDER_PREFLIGHT_AND_UNKNOWN_USAGE_HARDENING_VERIFIED",
        "V2_decision": "DO_NOT_RESUME",
        "full_schema_cpu": {
            "roots": 4,
            "full_pass": 1,
            "full_rejected": 3,
            "finish_control_pass": 4,
            "business_targets_covered": 25,
        },
        "error_localization": "Actual installed validator and AsyncLLM error wrapper reproduce "
        "uniqueItems ValueError -> empty EngineGenerateError -> identical public HTTP500 body",
        "historical_attribution_limit": "Controlled CPU reproduction, not recovered original "
        "stack or usage receipt; no retroactive zero settlement",
        "schema_guard": schema_stop,
        "historical_usage_guard": usage_stop,
        "http_calls_this_audit": calls,
        "new_model_requests": 0,
        "historical_usage": usage,
        "frozen_V2_integration": "NOT_MODIFIED: prospective Provider, not silently installed",
        "public_schema": "Unchanged, including uniqueItems and all legal targets",
        "live_generation_compatibility": "NOT_TESTED_AFTER_FAILED_CPU_GATE",
        "remaining_admission_requirements": [
            "A versioned compatible backend or explicitly reviewed wire-grammar strategy "
            "without weakening execution semantics or filtering targets",
            "All four full schemas pass prospective Provider validation, then an authorized "
            "bounded live compatibility probe with exact model/image/schema binding",
            "Authentic historical usage receipt, or explicit new authority for a separate "
            "diagnostic allocation while retaining the old unknown; never automatic waiver",
        ],
        "scope": "No new business task, State, Product change, "
        "protected-pool opening or service restart",
    }
    validate(root)
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    run(parser.parse_args().root)
