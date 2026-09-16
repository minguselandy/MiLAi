"""Join public import receipts/timing and bound readiness; no SQL or new requests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from check_v02_service_concurrency import distribution, write


def observations(captures, physical, runtime, readiness, imports_per_round):
    rows = []
    for item in captures:
        receipt = item["receipt"]
        phase = "drain-" + str(item["index"] // imports_per_round)
        ready = readiness[phase]
        assert ready["status"] == "READY" and not ready["projection_work_started"]
        assert receipt["outbox_id"] in ready["target_outbox_ids"]
        assert any(p["projection"] == "evidence" and p["projection_version"] ==
                   "evidence-search-v1" and p["ready"] and p["version_match"]
                   and p["current_watermark"] >= p["target_watermark"]
                   for p in ready["projections"])
        barriers = [p for p in physical if p["phase"] == phase and p["method"] == "POST"
                    and p["path"] == "/v1/system/projection-readiness"]
        assert len(barriers) == 1 and barriers[0].get("status") == 200
        ack = item["committed_response_s"]
        call_start = ack - item["save_ms"] / 1000
        writes = [p for p in physical if p["method"] == "POST" and p["path"] == "/v1/evidence"
                  and p["phase"] == "round-" + str(item["index"] // imports_per_round)
                  and call_start <= p["start_s"] <= p["end_s"] <= ack]
        assert writes and all(p.get("status") == 201 for p in writes)
        end = barriers[0]["end_s"]
        assert ack <= barriers[0]["start_s"] <= end
        fingerprint = hashlib.sha256(receipt["request_id"].encode()).hexdigest()[:16]
        timings = [r["safe_metadata"] for r in runtime
                   if r.get("request_id_fingerprint") == fingerprint]
        # Missing logs are unknown, never zero; ambiguous association cannot be scored.
        assert len(timings) <= 1
        rows.append({
            "index": item["index"], "evidence_id": receipt["evidence_id"],
            "outbox_id": receipt["outbox_id"], "request_id_fingerprint": fingerprint,
            "save_call_ms": item["save_ms"],
            "public_call_start_s": call_start, "ack_s": ack,
            "physical_request_association": "UNIQUE_INTERVAL" if len(writes) == 1
                                            else "AMBIGUOUS_OVERLAP",
            "ready_observed_s": end,
            "ack_to_ready_observation_ms": 1000 * (end - ack),
            "commit_to_ready_upper_bound_ms": 1000 * (end - call_start),
            "actual_commit_to_ready_ms": None,
            "runtime_timing": timings[0] if timings else None,
        })
    return rows


def run(root: Path):
    config = json.loads((root / "config.json").read_text())
    captures = json.loads((root / "capture-receipts.json").read_text())
    physical = [json.loads(line) for line in (root / "sdk-physical.jsonl").read_text().splitlines()]
    service = root / (root.name + "-product")
    runtime = [json.loads(line) for line in (service / "api.log").read_text().splitlines()
               if '"event":"runtime_request_timing"' in line]
    readiness = {"drain-" + p.stem.split("-")[-1]: json.loads(p.read_text())
                 for p in root.glob("readiness-*.json")}
    rows = observations(captures, physical, runtime, readiness, config["imports_per_round"])
    report = {
        "status": "PUBLIC_OBSERVATION_UPPER_BOUNDS_NOT_EXACT_INDEX_LATENCY",
        "model_calls": 0, "new_service_requests": 0, "rows": rows,
        "completed_imports": len(rows),
        "upper_bounds": distribution([r["commit_to_ready_upper_bound_ms"] for r in rows]),
        "slowest_imports": sorted(rows, key=lambda r: r["save_call_ms"], reverse=True)[:5],
        "limitation": "Bound starts at public SDK call, since actual commit precedes ack. "
                      "Round-end readiness cannot identify exact ready time or query recall. "
                      "Unsent/failed imports stay in arrival-events, outside this subset.",
    }
    write(root / "import-readiness-observations.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    result = run(parser.parse_args().root.resolve())
    print(json.dumps({k: v for k, v in result.items() if k not in {"rows", "slowest_imports"}}))
