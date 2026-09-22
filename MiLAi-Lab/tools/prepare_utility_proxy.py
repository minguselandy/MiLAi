"""Offline provenance projection of exposed DEV/VALID banks and cached BGE queries.

Never reads native outcomes for selection. No new requests; no SUPPORT bank load.
The output is a proposal to be reviewed and source-pinned before execution.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from milai_lab.methods.bundle_adoption_proxy import VERSION, digest, select_bundles
from milai_lab.methods.reasoning_bank import normalized
from prepare_utility_first_batch import BASE, SPLIT, SPLIT_SHA, sha
from replay_v0213_cost import save

LAB = Path(__file__).resolve().parents[1]
ALLOCATION = LAB / "data/manifests/utility-first-batch-allocation-20260922.json"
ALLOCATION_SHA = "90877f1f6506974edb84b773ea356be687e59038136d0801a0b4d299ff392e26"


def prepare(root: Path) -> dict:
    start = time.monotonic()
    if sha(ALLOCATION) != ALLOCATION_SHA or sha(SPLIT) != SPLIT_SHA:
        raise ValueError("FROZEN_ALLOCATION_OR_SPLIT_CHANGED")
    allocation = json.loads(ALLOCATION.read_text())
    splits = json.loads(SPLIT.read_text())
    sources = {str(ALLOCATION): ALLOCATION_SHA, str(SPLIT): SPLIT_SHA}

    def read(path: Path):
        sources[str(path)] = sha(path)
        return json.loads(path.read_text())

    instruction_path = LAB / "configs/policies/reasoning_bank/retrieval_instruction.txt"
    consume_path = LAB / "configs/policies/reasoning_bank/consume.txt"
    sources.update({str(p): sha(p) for p in (instruction_path, consume_path)})
    instruction = instruction_path.read_text().strip()
    consume = consume_path.read_text().strip()
    tasks = []
    for domain, positions in allocation["domains"].items():
        permitted = {
            row["id"]: row
            for part in ("DEV", "VALID")
            for row in splits["domains"][domain]["partitions"][part]
        }
        bank_root = (
            BASE / f"experience-optimization-20260916/native-validation-v06/valid-{domain}-milai"
        )
        bank = read(bank_root / "bank.json")
        if bank["scope"]["split"] != "VALID" or bank["historical_cards"]:
            raise ValueError("UNSUPPORTED_BANK_PROVENANCE")
        by_handle = {h: r["task_id"] for r in bank["records"] for h in r["handles"]}
        ancestry: dict[str, set[str]] = {}
        feedback = []
        for task_id in bank["completed_tasks"]:
            sid = task_id.split(":", 1)[1]
            if sid not in permitted:
                raise ValueError("BANK_SOURCE_OUTSIDE_DEV_VALID")
            path = bank_root / f"task-{sid}/memory-events.jsonl"
            sources[str(path)] = sha(path)
            events = [json.loads(line) for line in path.read_text().splitlines()]
            parents = set()
            retrieved: tuple[str, ...] = ()
            for event in events:
                if event["event"] == "MEMORY_RETRIEVED":
                    retrieved = tuple(event["handles"])
                    for h in retrieved:
                        if bank["cards"][h]["revision"] != event["revisions"][h]:
                            raise ValueError("HISTORICAL_VERSION_MISMATCH")
                        parents |= ancestry[by_handle[h]]
                if event["event"] == "EXPERIENCE_PATCH_APPLIED":
                    if event["changed"]:
                        raise ValueError("REVISED_BANK_NOT_ADMITTED")
                    if event["role"] == "adopt" and retrieved:
                        selected = tuple(event["selected_refs"])
                        if not set(selected) <= set(retrieved):
                            raise ValueError("ADOPTION_OUTSIDE_RETRIEVED_BUNDLE")
                        feedback.append(
                            {
                                "task": task_id,
                                "full": retrieved,
                                "selected": selected,
                                "ref": str(path),
                            }
                        )
            ancestry[task_id] = parents | {task_id}
        for card in bank["cards"].values():
            if card["revision"] != 1 or card["retired"]:
                raise ValueError("ONLY_UNCHANGED_LIVE_VERSIONS_ADMITTED")

        for pos in positions:
            sid = pos["id"]
            # Exclude the task's whole source group, including indirect influence
            # through retrieved material or another task's adoption feedback.
            cluster = permitted[sid]["cluster"]
            forbidden = {f"{domain}:{k}" for k, v in permitted.items() if v["cluster"] == cluster}
            receipt = Path(pos["exposure_receipt"])
            if sha(receipt) != pos["exposure_receipt_sha256"]:
                raise ValueError("FROZEN_EXPOSURE_RECEIPT_CHANGED")
            historical = read(receipt)
            query = historical["chat_history"]["value"][2]["content"]
            expected = f"Instruct: {instruction}\nQuery: {query}"
            cache = Path(pos["exposure_receipt"]).parent.parent / "embedding"
            vector = None
            for path in sorted(cache.glob("*-request.json")):
                request = json.loads(path.read_text())
                if expected not in request.get("input", []):
                    continue
                request = read(path)
                response = read(path.with_name(path.name.replace("-request", "-http")))
                if response["status_code"] != 200:
                    continue
                value = json.loads(response["body"])
                if request["model"] != "bge-m3" or value["model"] != "bge-m3":
                    raise ValueError("CACHED_EMBEDDING_MODEL_MISMATCH")
                index = request["input"].index(expected)
                row = next(x for x in value["data"] if x["index"] == index)
                vector = normalized(row["embedding"], 1024)
                break
            candidates = []
            allowed_feedback = [f for f in feedback if not ancestry[f["task"]] & forbidden]
            for record in bank["records"]:
                if ancestry[record["task_id"]] & forbidden or vector is None:
                    continue
                full = tuple(record["handles"])
                variants = [full]
                for f in allowed_feedback:
                    if f["full"] == full and f["selected"] and f["selected"] not in variants:
                        variants.append(f["selected"])
                similarity = sum(
                    a * b
                    for a, b in zip(vector, normalized(record["embedding"], 1024), strict=True)
                )
                for handles in variants:
                    versions = [
                        {
                            "memory_ref": f"{domain}:{h}",
                            "version_id": "1",
                            "content_sha256": digest(bank["cards"][h]),
                        }
                        for h in handles
                    ]
                    accept = [f for f in allowed_feedback if f["selected"] == handles]
                    reject = [
                        f for f in allowed_feedback if f["full"] == handles and not f["selected"]
                    ]
                    material = "\n\n".join(
                        f"[{h} revision=1; sources={','.join(bank['cards'][h]['source_refs'])}]\n"
                        + bank["cards"][h]["text"]
                        for h in handles
                    )
                    candidates.append(
                        {
                            "bundle_id": digest(versions),
                            "source_task": record["task_id"],
                            "versions": versions,
                            "similarity": similarity,
                            "accepted": len(accept),
                            "rejected": len(reject),
                            "feedback_refs": sorted({f["ref"] for f in accept + reject}),
                            "source_query": record["query"],
                            "context": consume + "\n\n" + material,
                            "ancestry": sorted(ancestry[record["task_id"]]),
                        }
                    )
            candidates.sort(key=lambda item: -item["similarity"])
            selection = select_bundles(candidates)
            tasks.append(
                {
                    "domain": domain,
                    "id": sid,
                    "query": query,
                    "query_sha256": digest(query),
                    "candidates": candidates,
                    "selection": selection,
                    "cached_query_available": vector is not None,
                    "meaningful_alternatives_review": "PENDING",
                }
            )
    result = {
        "schema": "milai-utility-proxy-inputs-v1",
        "method_version": VERSION,
        "allocation": str(ALLOCATION),
        "allocation_sha256": ALLOCATION_SHA,
        "source_sha256": sources,
        "tasks": tasks,
        "new_embedding_requests": 0,
        "new_model_requests": 0,
        "preparation_seconds": time.monotonic() - start,
    }
    save(root / "inputs.proposal.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=False)
    value = prepare(args.output_root)
    print(
        json.dumps(
            {
                "root": str(args.output_root),
                "tasks": len(value["tasks"]),
                "cached_queries": sum(x["cached_query_available"] for x in value["tasks"]),
                "selection_changes": sum(
                    x["selection"]["STATIC"] != x["selection"]["UTILITY"] for x in value["tasks"]
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
