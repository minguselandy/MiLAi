"""Compare cold and known-conditioned actual public retrieval receipts with explicit K."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import receipt_conditioned_packet_request

SCOPE = (
    "Constructed caller condition from actual public receipt items. Same known material with "
    "cold versus known-conditioned retrieval separates added context from retrieval behavior. "
    "Cold plus empty K is a separate baseline. No reconstructed Host conversation, new native "
    "execution, hidden answers, source writes, or claim of autonomous tool use."
)


def prepare_case(collection: Path, history: dict[str, Any], settings: dict[str, Any],
                 token_count: Any) -> dict[str, Any]:
    public = history["requests"][0]
    bank = collection / "banks" / history["id"]
    paths = {c: bank / f"{public['id']}-{c}-receipt.json" for c in ("cold", "known-first")}
    receipts = {c: read_json(p) for c, p in paths.items()}
    parent_path = Path(receipts["known-first"].get("known_reference_parent_receipt", paths["cold"]))
    parent = read_json(parent_path)
    actions = {}
    for condition in receipts:
        events = read_jsonl(bank / f"{public['id']}-{condition}-operations.jsonl")
        final = next(e for e in reversed(events) if e.get("phase") == "decision_output")
        actions[condition] = next(a for a in final["actions"] if a["id"] == final["selected"])
        if actions[condition]["kind"] != "HANDOFF":
            raise ValueError("Expected the actual terminal HANDOFF receipt")
    if not receipts["known-first"]["request"]["task_context"]["known_evidence_refs"]:
        raise ValueError("The selected case has no actual known-reference condition")
    event_id = f"{history['source_group']}/{public['id']}/receipt-conditioned"
    case: dict[str, Any] = {
        "family": history["source_group"], "event_id": event_id, "case_key": event_id,
        "request_id": public["id"], "source_split": history["split"],
        "choices": {}, "branches": [],
    }
    for name, request_condition, packet_condition in (
        ("cold", "cold", "cold"),
        ("known_with_cold_packet", "known-first", "cold"),
        ("known_with_conditioned_packet", "known-first", "known-first"),
    ):
        receipt = receipts[packet_condition]
        request = receipts[request_condition]["request"]
        wire = receipt_conditioned_packet_request(
            public, request, receipt["packet"], settings, [parent])
        case["choices"][name] = actions[packet_condition]["id"]
        case["branches"].append({
            "policies": [name], "action": actions[packet_condition],
            "execution_result": {"ok": receipt["packet"]["ok"]},
            "packet": receipt["packet"],
            "body_tokens": token_count(json.dumps(receipt["packet"], ensure_ascii=False)),
            "readout_request": wire,
            "condition_provenance": {
                "condition": name, "current_packet_receipt": str(paths[packet_condition]),
                "known_items_receipt": str(parent_path),
                "known_evidence_refs": request["task_context"]["known_evidence_refs"],
                "native_retrieval_request": receipt["request"],
                "reader_retrieval_request": request,
                "constructed_context": True, "natural_host_history": False,
                "native_request_matches_reader_request": request == receipt["request"],
                "earlier_packet_unreferenced_items_supplied": False,
            },
        })
    return case


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--families", type=int, default=8)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    original = read_json(args.collection / "run.json")
    if original["status"] != "COMPLETED":
        raise ValueError("Use a closed actual collection")
    histories = read_json(args.collection / "sources.json")["histories"]
    selected = histories[args.offset:args.offset + args.families]
    if len(selected) != args.families:
        raise ValueError("Requested source-family prefix is unavailable")
    settings = read_json(args.config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    cases = [prepare_case(args.collection.resolve(), h, settings, capacity.text_tokens)
             for h in selected]
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "cases.json", cases)
    write_json(args.output / "run.json", {
        "status": "COMPLETED", "collection": str(args.collection.resolve()),
        "config": str(args.config.resolve()), "readout_scope": SCOPE,
        "selection": "First question per source family in original order; no answer selection",
        "families": len({c["family"] for c in cases}), "states": len(cases),
        "source_roles": sorted({c["source_split"] for c in cases}),
        "prepared_readouts": sum(len(c["branches"]) for c in cases),
        "new_native_executions": 0, "Host_calls": 0, "no_sha_validation": True,
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started},
    })


if __name__ == "__main__":
    main()
