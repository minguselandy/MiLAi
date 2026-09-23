"""Offline, source-pinned input review for the separately authorized joint batch.

No Provider import or endpoint probe. Native outcomes are not review inputs.
Raw evidence stays in an exclusive private output directory outside Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from milai_lab.methods.reasoning_bank import normalized
from prepare_utility_first_batch import BASE, SPLIT, SPLIT_SHA, sha

LAB = Path(__file__).resolve().parents[1]
OLD_ALLOCATION = LAB / "data/manifests/utility-first-batch-allocation-20260922.json"
OLD_SHA = "90877f1f6506974edb84b773ea356be687e59038136d0801a0b4d299ff392e26"
ALLOCATION = LAB / "data/manifests/revision-attention-allocation-20260923.json"
ALLOCATION_SHA = "02d316916799358ca39e37559037400919b5abb5228f56e769dc3799b5117576"
OLD_INPUT = BASE / "post-cleanup-utility-proxy-20260922/admitted/inputs.proposal.json"
OLD_INPUT_SHA = "6005b0f7ed8c8fa8e21cde57981625f1338428ba1cbb468257208d22f09b4fd3"
BANKS = (
    (
        "experience-optimization-20260916/native-validation-v06/valid-db_bench-milai",
        "de1fc0eb17769df6c77f967f71f305d9a83498d399ba2cc33167e9db49d31b51",
    ),
    (
        "experience-optimization-20260916/native-validation-v06/valid-os_interaction-milai",
        "36dbd50ecf49b3f0da0a18b693bbfb1bd18ca5a007158a63b4af552b836384be",
    ),
    (
        "evidence-utility-improvement-20260916/d1-native-smoke/d1-db_bench",
        "2ea351c83dffc6c815da8987f2260c241db880a41fd569eb5c02f153154b69ad",
    ),
    (
        "evidence-utility-improvement-20260916/d1-native-smoke/d1-os_interaction",
        "0a0e960fac146f0594a2483c216b7274945e7d80ebf1b627baee81986918f4bb",
    ),
)


def verify_allocation() -> dict:
    if sha(ALLOCATION) != ALLOCATION_SHA:
        raise ValueError("FROZEN_JOINT_ALLOCATION_CHANGED")
    if sha(OLD_ALLOCATION) != OLD_SHA or sha(SPLIT) != SPLIT_SHA:
        raise ValueError("FROZEN_SOURCE_METADATA_CHANGED")
    value = json.loads(ALLOCATION.read_text())
    old = json.loads(OLD_ALLOCATION.read_text())
    for field in ("domains", "solver", "embedding", "limits", "prohibitions"):
        if value[field] != old[field]:
            raise ValueError(f"JOINT_CONTRACT_CHANGED:{field}")
    if len(value["schedule"]) != 32:
        raise ValueError("JOINT_PAIR_COUNT_CHANGED")
    expected = []
    for pos in (0, 6, 1, 7, 2, 8, 3, 9, 4, 10, 5, 11):
        for repeat in (False, True) if pos in (0, 3, 6, 9) else (False,):
            for di, domain in enumerate(("db_bench", "os_interaction")):
                task = value["domains"][domain][pos]
                mechanism = "REVISION" if pos < 6 else "ATTENTION"
                arms = ["APPEND_ONLY", "REVISION"] if pos < 6 else ["STATIC", "ATTENTION"]
                if (pos + di + repeat) % 2:
                    arms.reverse()
                expected.append(
                    dict(
                        pair_index=len(expected),
                        domain=domain,
                        task_id=task["id"],
                        source_partition=task["source_partition"],
                        position=pos,
                        mechanism=mechanism,
                        repeat=repeat,
                        arms=arms,
                    )
                )
    if value["schedule"] != expected:
        raise ValueError("FROZEN_JOINT_SCHEDULE_CHANGED")
    for positions in value["domains"].values():
        for pos in positions:
            if sha(Path(pos["exposure_receipt"])) != pos["exposure_receipt_sha256"]:
                raise ValueError("FROZEN_EXPOSURE_RECEIPT_CHANGED")
    return value


def review_bank(
    root: Path,
    bank: dict,
    permitted: dict,
    targets: list,
    sources: dict,
    lineage: dict | None = None,
) -> list:
    owners = {r["trace_ref"]: r["task_id"] for r in bank["records"]}
    card_owners = {h: r["task_id"] for r in bank["records"] for h in r["handles"]}
    events_by_task = {}
    for task in bank["completed_tasks"]:
        if task.split(":", 1)[1] not in permitted:
            raise ValueError("SOURCE_OUTSIDE_EXPOSED_DEV_VALID")
        path = root / f"task-{task.split(':', 1)[1]}/memory-events.jsonl"
        sources[str(path)] = sha(path)
        events = [json.loads(line) for line in path.read_text().splitlines()]
        events_by_task[task] = events
        for event in events:
            if event["event"] == "MEMORY_SOURCE_ADDED":
                owners[event["ref"]] = task
    ancestry = {}
    windows = []
    for task, events in events_by_task.items():
        inherited = set()
        retrieved = {}
        feedback = {}
        query_refs = []
        for index, event in enumerate(events):
            if event["event"] == "MEMORY_RETRIEVED":
                for handle in event["handles"]:
                    card = bank["cards"][handle]
                    if card["revision"] != event["revisions"][handle] or card["retired"]:
                        raise ValueError("SOURCE_VERSION_CHANGED")
                    inherited |= ancestry[card_owners[handle]]
                    for ref in card["source_refs"]:
                        owner = owners[ref]
                        inherited |= ancestry.get(owner, {owner})
                    retrieved.setdefault(handle, index)
            if event["event"] == "MEMORY_SOURCE_ADDED":
                if event["kind"] == "tool":
                    feedback[event["ref"]] = index
                elif event["kind"] == "query":
                    query_refs.append(event["ref"])
        ancestry[task] = inherited | {task}
        clusters = sorted({permitted[t.split(":", 1)[1]]["cluster"] for t in ancestry[task]})
        for handle, retrieved_at in retrieved.items():
            refs = [ref for ref, index in feedback.items() if index > retrieved_at]
            if not refs:
                continue
            card = bank["cards"][handle]
            windows.append(
                {
                    "window_id": f"{root.name}/{task}/{handle}",
                    "bank": str(root / "bank.json"),
                    "card": card,
                    "feedback_task": task,
                    "original_evidence": {ref: bank["sources"][ref] for ref in card["source_refs"]},
                    "visible_query": {ref: bank["sources"][ref] for ref in query_refs},
                    "visible_feedback": {ref: bank["sources"][ref] for ref in refs},
                    "formation_ancestry": sorted(ancestry[task]),
                    "lineage_clusters": clusters,
                    "independent_revision_targets": [
                        p["id"] for p in targets[:6] if p["cluster"] not in clusters
                    ],
                    "support": "NOT_REVIEWED",
                    "kind": None,
                    "note": "Later feedback alone proves neither contradiction nor memory use.",
                }
            )
    if lineage is not None:
        lineage.update({task: sorted(parents) for task, parents in ancestry.items()})
    return windows


def cached_query(bank: dict, domain: str, task_id: str, query: str, instruction_sha: str) -> list:
    """Only a pre-action query vector may cross from this task's own history."""
    config = bank["contract"]["config"]
    if (
        bank["scope"]["domain"] != domain
        or bank["scope"]["split"] not in {"DEV", "VALID"}
        or config["embedding_model"] != "bge-m3"
        or config["embedding_dimension"] != 1024
        or config["encoding_version"] != "bge-query-instruct-cosine-v1"
        or bank["contract"]["policy_sha256"]["retrieval_instruction"] != instruction_sha
    ):
        raise ValueError("HISTORICAL_QUERY_ENCODING_CHANGED")
    rows = [
        r for r in bank["records"] if r["task_id"] == f"{domain}:{task_id}" and r["query"] == query
    ]
    if len(rows) != 1:
        raise ValueError("EXACT_HISTORICAL_QUERY_VECTOR_REQUIRED")
    return normalized(rows[0]["embedding"], 1024)


def prepare_queries(allocation: dict, sources: dict) -> list:
    if sha(OLD_INPUT) != OLD_INPUT_SHA:
        raise ValueError("FROZEN_QUERY_INPUT_CHANGED")
    sources[str(OLD_INPUT)] = OLD_INPUT_SHA
    old = json.loads(OLD_INPUT.read_text())
    queries = {(r["domain"], r["id"]): r["query"] for r in old["tasks"]}
    instruction_path = LAB / "configs/policies/reasoning_bank/retrieval_instruction.txt"
    instruction = instruction_path.read_text().strip()
    instruction_sha = sha(instruction_path)
    sources[str(instruction_path)] = instruction_sha
    result = []
    for domain, positions in allocation["domains"].items():
        for task in positions:
            query = queries[domain, task["id"]]
            encoded = f"Instruct: {instruction}\nQuery: {query}"
            historical_root = Path(task["exposure_receipt"]).parent.parent
            vector, origin = None, None
            for path in sorted((historical_root / "embedding").glob("*-request.json")):
                request = json.loads(path.read_text())
                if encoded not in request.get("input", []):
                    continue
                response_path = path.with_name(path.name.replace("-request", "-http"))
                response = json.loads(response_path.read_text())
                if response["status_code"] != 200:
                    continue
                value = json.loads(response["body"])
                if request["model"] != "bge-m3" or value["model"] != "bge-m3":
                    raise ValueError("CACHED_QUERY_MODEL_CHANGED")
                index = request["input"].index(encoded)
                row = next(r for r in value["data"] if r["index"] == index)
                vector, origin = normalized(row["embedding"], 1024), str(path)
                sources.update({str(path): sha(path), str(response_path): sha(response_path)})
                break
            if vector is None:
                path = historical_root / "bank.json"
                bank = json.loads(path.read_text())
                vector = cached_query(bank, domain, task["id"], query, instruction_sha)
                origin = str(path) + f"#query-vector:{domain}:{task['id']}"
                sources[str(path)] = sha(path)
            result.append(
                {
                    "domain": domain,
                    "id": task["id"],
                    "cluster": task["cluster"],
                    "query": query,
                    "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                    "embedding": vector,
                    "query_vector_origin": origin,
                    "own_task_material_imported": "query vector only; no cards/results",
                }
            )
    return result


def prepare(root: Path) -> dict:
    started = time.monotonic()
    allocation = verify_allocation()
    if root.resolve().is_relative_to(LAB.parent.resolve()):
        raise ValueError("RAW_INPUT_OUTPUT_MUST_BE_OUTSIDE_REPOSITORY")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    sources = {
        str(ALLOCATION): sha(ALLOCATION),
        str(OLD_ALLOCATION): OLD_SHA,
        str(SPLIT): SPLIT_SHA,
    }
    splits = json.loads(SPLIT.read_text())
    windows = []
    lineages = {}
    for relative, expected in BANKS:
        path = BASE / relative / "bank.json"
        if sha(path) != expected:
            raise ValueError("REVIEW_BANK_CHANGED")
        sources[str(path)] = expected
        bank = json.loads(path.read_text())
        domain = bank["scope"]["domain"]
        permitted = {
            r["id"]: r
            for part in ("DEV", "VALID")
            for r in splits["domains"][domain]["partitions"][part]
        }
        lineages[str(path)] = {}
        windows.extend(
            review_bank(
                path.parent,
                bank,
                permitted,
                allocation["domains"][domain],
                sources,
                lineages[str(path)],
            )
        )
    queries = prepare_queries(allocation, sources)
    result = {
        "schema": "milai-revision-attention-review-inputs-v1",
        "status": "PRE_OUTCOME_SEMANTIC_REVIEW_REQUIRED",
        "allocation_sha256": sha(ALLOCATION),
        "source_sha256": sources,
        "windows": windows,
        "queries": queries,
        "formation_ancestry": lineages,
        "preparation_seconds": time.monotonic() - started,
        "new_external_requests": 0,
    }
    with (root / "review-inputs.json").open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    value = prepare(args.output_root)
    print(
        json.dumps(
            {
                "windows": len(value["windows"]),
                "allocation_sha256": value["allocation_sha256"],
                "new_external_requests": 0,
            }
        )
    )
