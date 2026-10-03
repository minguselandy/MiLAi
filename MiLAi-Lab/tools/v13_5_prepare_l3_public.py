"""Rebuild exposed L3 inputs from three pinned public artifacts, without model calls.

Cohort membership was selected during the earlier evaluator audit. This builder
does not select failures or read results, answers, gold, or E*; the manifest
declares that selection and the changed formation instruction explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parents[1]
INPUTS = (
    "artifacts/v13-4/n2-formation/bank-before.json",
    "artifacts/v13-4/t0-runtime/queries.json",
    "artifacts/v13-4/t0-q0/prepare-trace.jsonl",
)
CANDIDATE_FIELDS = (
    "source_ref", "start", "end", "retrieval_score", "source_sha256",
    "body_text_sha256", "span_sha256",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def source_event(source: dict[str, Any]) -> dict[str, Any]:
    if sha(source["content"].encode()) != source["content_sha256"]:
        raise ValueError("ORIGINAL_SOURCE_HASH_CHANGED")
    return {
        "original_event_id": source["event_id"], "session_id": source["session"],
        "event_key": "v13-5-source-import:" + source["event_id"], "role": source["role"],
        "origin": source["origin"], "content": source["content"],
        "content_sha256": source["content_sha256"], "observed_at": source["observed_at"],
        "object_ref": source["object_ref"],
    }


def rebuild(old_lab: Path, manifest_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("OUTPUT_MUST_BE_NEW:" + str(output))
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if (manifest["schema"] != "v13_5_l3_public_rebuild_manifest_v1"
            or set(manifest["input_files"]) != set(INPUTS)):
        raise ValueError("PUBLIC_INPUT_SET_CHANGED")
    inputs = {}
    for relative in INPUTS:
        data = (old_lab / relative).read_bytes()
        if sha(data) != manifest["input_files"][relative]:
            raise ValueError("ORIGINAL_INPUT_HASH_CHANGED:" + relative)
        inputs[relative] = data
    bank = json.loads(inputs[INPUTS[0]])
    counts = {"sources": sum(len(row["sources"]) for row in bank.values()),
              "semantic_facts": sum(len(row["facts"]) for row in bank.values())}
    if counts != manifest["original_bank_counts"] or counts["semantic_facts"]:
        raise ValueError("ORIGINAL_BANK_COUNTS_CHANGED")
    sources = {s["event_id"]: s for row in bank.values() for s in row["sources"]}
    if len(sources) != counts["sources"]:
        raise ValueError("ORIGINAL_SOURCE_ID_COLLISION")
    queries = json.loads(inputs[INPUTS[1]])
    if any(set(q) != {"query_id", "origin_id", "question"} for q in queries):
        raise ValueError("PUBLIC_QUERY_FIELDS_CHANGED")
    by_query = {q["query_id"]: q for q in queries}
    pools = {}
    for line in inputs[INPUTS[2]].splitlines():
        event = json.loads(line)
        if event.get("event") == "correction_candidate_pool":
            pools[(event["snapshot"]["query"]["query_id"], event["snapshot_sha256"])] = event
    reading = []
    for selected in manifest["reading_queries"]:
        query_id = selected["query_id"]
        query = by_query[query_id]
        if query["origin_id"] != selected["origin_id"]:
            raise ValueError("ORIGINAL_QUERY_GROUP_CHANGED")
        pool = pools[(query_id, selected["snapshot_sha256"])]["snapshot"]
        if pool["query"]["question"] != query["question"]:
            raise ValueError("ORIGINAL_QUERY_TEXT_CHANGED")
        seeds = [source_event(s) for s in bank[query["origin_id"]]["sources"]]
        bodies = {s["original_event_id"]: s["content"] for s in seeds}
        candidates = [{k: c[k] for k in CANDIDATE_FIELDS if k in c}
                      for c in pool["candidates"]]
        if len(candidates) != selected["candidate_count"]:
            raise ValueError("ORIGINAL_CANDIDATE_COUNT_CHANGED")
        for candidate in candidates:
            body = bodies[candidate["source_ref"]]
            start, end = candidate["start"], candidate["end"]
            if (not 0 <= start < end <= len(body)
                    or sha(body[start:end].encode()) != candidate["span_sha256"]):
                raise ValueError("ORIGINAL_CANDIDATE_RANGE_CHANGED")
        reading.append({
            "case_id": query_id, "owner": "v13-5-l3-" + query_id,
            "workflow": "reservation", "initial_world": {},
            "messages": [{"message_id": query_id + "-m1", "session_id": "query-session",
                          "content": query["question"]}],
            "initial_sources": seeds, "retrieval_candidates": candidates,
        })
    formation = []
    size = manifest["formation_max_codepoints"]
    for selected in manifest["formation_requests"]:
        seed = source_event(sources[selected["original_event_id"]])
        body, start, candidates = seed["content"], 0, []
        while start < len(body):
            end = min(start + size, len(body))
            if end < len(body):
                paragraph = body.rfind("\n\n", start + 1, end)
                line = body.rfind("\n", start + 1, end)
                if paragraph > start:
                    end = paragraph + 2
                elif line > start:
                    end = line + 1
            candidates.append({
                "source_ref": seed["original_event_id"], "start": start, "end": end,
                "retrieval_score": 1, "source_sha256": seed["content_sha256"],
                "body_text_sha256": seed["content_sha256"],
                "span_sha256": sha(body[start:end].encode()),
            })
            start = end
        request_id = selected["request_id"]
        formation.append({
            "case_id": request_id, "owner": "v13-5-l3-formation-" + request_id,
            "workflow": "reservation", "initial_world": {}, "initial_sources": [seed],
            "retrieval_candidates": candidates,
            "messages": [{"session_id": "formation", "message_id": request_id + "-formation-m1",
                          "content": manifest["formation_instruction"]}],
        })
    products = {}
    for name, cohort, cases in (
        ("l3-reading-functional.json", "L3_fixed_old_public_candidate_pool", reading),
        ("l3-formation-functional.json", "L3_query_free_new_fragment_formation_instruction",
         formation),
    ):
        data = encoded({"kind": "V13_5_FUNCTIONAL_PUBLIC_CASES", "cohort": cohort,
                        "status": "INPUT_CANDIDATE_NOT_ADMITTED", "cases": cases})
        if sha(data) != manifest["expected_products"][name]:
            raise ValueError("REBUILT_PRODUCT_DIFFERS:" + name)
        products[name] = data
    # Validate every input and both complete products before creating any output.
    output.mkdir(parents=True)
    for name, data in products.items():
        (output / name).write_bytes(data)
    receipt = {"schema": "v13_5_l3_public_rebuild_receipt_v1", "status": "BYTE_IDENTICAL",
               "manifest_sha256": sha(manifest_bytes), "input_files": manifest["input_files"],
               "products": {name: sha(data) for name, data in products.items()},
               "formation_requests": len(formation), "reading_queries": len(reading),
               "new_http_calls": 0, "semantic_acceptance": "NOT_RUN"}
    (output / "rebuild-receipt.json").write_bytes(encoded(receipt))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-lab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path,
                        default=LAB / "data/manifests/v13-5-l3-public-inputs.json")
    args = parser.parse_args()
    print(json.dumps(rebuild(args.old_lab, args.manifest, args.output), ensure_ascii=False))
