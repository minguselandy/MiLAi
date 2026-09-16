"""Read-only terminal audit; never call a provider or dispatch a business action."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from v02_local_provider import read_events
from v0220_evidence import LAB, read, save, sha, validate
from v0220_provider_hardened import historical_usage, usage_state
from v0220_wire_contract import compile_contract, fingerprint

ROOT = Path("/cra/memory/mx_memory/evidence/v0221/20260911-http-r1-v2")
BINDING = "117100e25e6cf47a3d9db331b728ba77fb7790b1303b57117fb22691148b75b4"


def audit() -> dict:
    assert sha(ROOT / "execution-binding.json") == BINDING
    manifest = validate(ROOT)
    plan = manifest["contract"]
    prior = ROOT.parent / "20260911-http-r1"
    validate(prior)
    assert read(prior / "preflight/result.json")["model_requests"] == 0
    result = read(ROOT / "result.json")
    preflight = read(ROOT / "preflight/result.json")
    assert preflight["status"] == "G_PREFLIGHT_PASS"
    assert len(preflight["rows"]) == 96 and len(preflight["tokenize_calls"]) == 192
    assert all(r["status_code"] == 200 for r in preflight["tokenize_calls"])
    assert all(r["input_fits"] and r["reference_output_fits"] for r in preflight["rows"])
    with sqlite3.connect(f"file:{ROOT / 'batch.sqlite'}?mode=ro", uri=True) as db:
        reference_sha = db.execute(
            "SELECT value FROM meta WHERE key='reference_index'"
        ).fetchone()
        # The binding is also retained independently in prepared.json.
        assert (
            sha(ROOT / "reference-requests.json")
            == read(ROOT / "prepared.json")["reference_index_sha256"]
        )
        assert reference_sha is not None
        assert reference_sha[0] == sha(ROOT / "reference-requests.json")
        stop = db.execute("SELECT value FROM meta WHERE key='stop'").fetchone()[0]
        central = [
            json.loads(row[0]) for row in db.execute("SELECT event FROM events ORDER BY seq")
        ]
    assert stop == result["batch"]["stop"] == "LEGAL_JSON_INTENT_FIDELITY_FAILURE"
    for row in read(ROOT / "reference-requests.json"):
        for kind in ("canonical", "wire", "output"):
            assert sha(Path(row[kind])) == row["hashes"][kind]
    provider = ROOT / "episodes/w2-01/provider"
    local = read_events(provider / "provider-ledger-v2.jsonl")
    assert central == local
    cost = usage_state(central)
    assert cost == result["batch"]["cost"]
    assert cost["requests"] == 1 and cost["actual_total_raw_tokens"] == 27864
    assert cost["unresolved_reservations"] == [] and cost["violations"] == []
    reservation = next(e for e in local if e["event"] == "RESERVED")
    key = reservation["request_id"]
    http = read(provider / (key + "-http.json"))
    response = json.loads(http["body"])
    assert http["status_code"] == 200 and http["client_request_id"] == key
    assert response["id"] == "chatcmpl-" + key
    assert response["choices"][0]["finish_reason"] == "stop"
    usage = response["usage"]
    assert usage["prompt_tokens"] == read(provider / (key + "-tokenize.json"))["count"] == 27779
    assert usage["completion_tokens"] == 85 and usage["total_tokens"] == 27864
    assert usage == next(e["usage"] for e in local if e["event"] == "USAGE_KNOWN")
    binding = read(next(provider.glob("contract-*-binding.json")))
    original = binding["original_request"]
    assert original == read(ROOT / "W2-requests/w2-01.canonical.json")
    wire = read(provider / (key + "-request.json"))
    contract = compile_contract(original["response_format"]["json_schema"]["schema"])
    assert contract.prepare(original) == wire
    assert fingerprint(wire) == reservation["payload_sha256"] == http["request_wire_sha256"]
    value = contract.validate_output(response["choices"][0]["message"]["content"])
    expected = plan["W2"][0]["expected"]
    assert value["action"] == expected["action"] == "put_record"
    assert value["arguments"]["object_id"] == expected["arguments"]["object_id"]
    assert value["arguments"]["expected_version"] == expected["arguments"]["expected_version"]
    differences = [
        name
        for name in expected["arguments"]["data"]
        if value["arguments"]["data"][name] != expected["arguments"]["data"][name]
    ]
    assert set(differences) == {"recipient", "summary"}
    assert not (ROOT / "worlds").exists()
    assert sorted(p.name for p in (ROOT / "episodes").iterdir()) == ["w2-01"]
    assert len(result["unrun"]) == 39
    history = historical_usage([Path(p) for p in plan["historical_paths"]])
    assert history == result["historical_usage"]
    assert history["known_raw_tokens"] == 2221 and history["actual_total_raw_tokens"] is None
    return {
        "status": "BOUNDED_NON_PASS_AUDITED_NOT_GATE_PASS",
        "batch_root": str(ROOT),
        "binding_sha256": BINDING,
        "gates": {
            "G_AUTH": "PASS",
            "G_PREFLIGHT": "PASS",
            "G_LIVE_COMPAT": "NOT_MET",
            "G_KNOWN_INTENT_V0221": "NOT_TRIGGERED",
        },
        "failure": {
            "code": stop,
            "episode": "w2-01",
            "request_id": key,
            "HTTP": 200,
            "strict_JSON_full_schema": "PASS",
            "changed_fields": sorted(differences),
            "actual_recipient": value["arguments"]["data"]["recipient"],
            "actual_summary": value["arguments"]["data"]["summary"],
            "automatic_repair": False,
            "live_business_dispatches": 0,
        },
        "preflight": {
            "reference_requests": 96,
            "tokenize_calls": 192,
            "max_input_tokens": max(r["counts"]["input"] for r in preflight["rows"]),
            "max_reference_output_tokens": 838,
            "model_calls": 0,
        },
        "W2": {
            "planned": 16,
            "attempted": 1,
            "passed": 0,
            "unrun": 15,
            "full": {"planned": 8, "attempted": 1, "passed": 0},
            "finish": {"planned": 8, "attempted": 0, "passed": 0},
        },
        "W3": {"planned_chains": 24, "attempted": 0, "status": "NOT_TRIGGERED"},
        "unrun": result["unrun"],
        "cost_accounts": {
            "historical": history,
            "current_model": cost,
            "agent_work_snapshot": {
                "tokens": 187952,
                "as_of_UTC": "2026-09-11 13:29:14",
                "is_final_or_provider_billing": False,
            },
        },
        "stop_semantics": "Settled usage is not permission to resume; permanent batch stop applies",
        "http_only": True,
        "direct_device_or_container_calls": 0,
        "Judge": 0,
        "Memory": "NOT_ADMITTED",
        "V3_V5": "NOT_TRIGGERED",
        "evidence_sha256": {
            name: sha(ROOT / name)
            for name in (
                "manifest.json",
                "execution-binding.json",
                "reference-requests.json",
                "preflight/result.json",
                "result.json",
                "exits/w2-01.json",
            )
        },
    }


if __name__ == "__main__":
    outcome = audit()
    save(ROOT / "terminal-audit.json", outcome)
    save(LAB / "studies/active/MILA_V0221_HTTP_ONLY_RESULTS_20260911.json", outcome)
    print(outcome["status"])
