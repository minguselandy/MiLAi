"""Freeze the authorized task/arm schedule without sending any external request.

Only split metadata and existing DEV/VALID exposure receipts are read. Historical
scores never influence task selection. This allocation is not execution admission:
candidate/utility provenance and the implemented method must also be frozen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

BASE = Path("/cra/memory/mx_memory/evidence")
SPLIT = BASE / "experience-optimization-20260916/splits.json"
SPLIT_SHA = "45d48b75bac9dff70cd858bb1ff3f76ee41aa464f7dc814ebf22e3495aa389f9"
REPEAT_POSITIONS = (0, 3, 6, 9)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exposure_path(domain: str, split: str, task_id: str) -> Path:
    if split == "VALID":
        return BASE / (
            "experience-optimization-20260916/native-validation-v06/"
            f"valid-{domain}-milai/task-{task_id}/native-session.json"
        )
    if domain == "db_bench":
        return BASE / (
            "experience-optimization-20260916/dev-projection-complete/"
            f"p0-selected-db-{task_id}/task-{task_id}/native-session.json"
        )
    if task_id in {"120", "194"}:
        return BASE / (
            "reasoningbank-transfer-20260915-_7fzz854/"
            f"dev-current-v03-os_interaction-milai/task-{task_id}/native-session.json"
        )
    return BASE / (
        "evidence-utility-improvement-20260916/d1-native-smoke/"
        f"d1-os_interaction/task-{task_id}/native-session.json"
    )


def prepare() -> dict:
    if sha(SPLIT) != SPLIT_SHA:
        raise ValueError("FROZEN_SPLIT_CHANGED")
    split = json.loads(SPLIT.read_text())
    domains = {}
    for domain in ("db_bench", "os_interaction"):
        selected = []
        clusters: set[str] = set()
        # Existing frozen order, DEV before VALID; never rank by any result.
        for partition in ("DEV", "VALID"):
            for row in split["domains"][domain]["partitions"][partition]:
                proof = exposure_path(domain, partition, row["id"])
                if not proof.is_file() or row["cluster"] in clusters:
                    continue
                selected.append(
                    {
                        "id": row["id"],
                        "source_partition": partition,
                        "cluster": row["cluster"],
                        "exposure_receipt": str(proof),
                        "exposure_receipt_sha256": sha(proof),
                    }
                )
                clusters.add(row["cluster"])
                if len(selected) == 12:
                    break
            if len(selected) == 12:
                break
        if len(selected) != 12:
            raise ValueError(f"INSUFFICIENT_EXPOSED_INDEPENDENT_POSITIONS:{domain}")
        domains[domain] = selected
    schedule = []
    positions = [(i, False) for i in range(12)] + [(i, True) for i in REPEAT_POSITIONS]
    for position, repeat in positions:
        for domain_index, domain in enumerate(domains):
            arms = ["STATIC", "UTILITY"]
            if (position + domain_index + int(repeat)) % 2:
                arms.reverse()
            task = domains[domain][position]
            schedule.append(
                {
                    "pair_index": len(schedule),
                    "domain": domain,
                    "task_id": task["id"],
                    "source_partition": task["source_partition"],
                    "position": position,
                    "repeat": repeat,
                    "arms": arms,
                }
            )
    return {
        "schema": "milai-utility-first-batch-allocation-v1",
        "status": "SCHEDULE_FROZEN_METHOD_NOT_ADMITTED",
        "goal": "MILAI-POST-CLEANUP-DEVELOPMENT-01/3C-1",
        "authority": "Explicit user authorization, 2026-09-22; one new finite batch only",
        "base_commit": "3089ee11425f29e889bbc91b93ac1396314af41c",
        "arm_kind": "RESEARCH_PROTOTYPE",
        "split_manifest": str(SPLIT),
        "split_sha256": SPLIT_SHA,
        "selection_rule": (
            "Frozen DEV then VALID order; existing exposure receipt; first unique cluster"
        ),
        "domains": domains,
        "repeat_positions_zero_based": list(REPEAT_POSITIONS),
        "schedule": schedule,
        "paired_positions": 32,
        "arm_executions": 64,
        "solver": {
            "model": "Qwen3.6-35B-A3B-FP8",
            "base_url": "http://127.0.0.1:7860/v1",
            "profile": "M1",
            "actor_temperature": 0.0,
            "self_judge_temperature": 0.0,
            "extract_temperature": 1.0,
            "other_memory_role_temperature": 0.0,
            "top_p": 1,
            "seed": 213,
            "enable_thinking": False,
            "actor_output_cap": 4096,
            "self_judge_output_cap": 64,
            "other_memory_role_output_cap": 2048,
            "context_cap": 65536,
        },
        "embedding": {
            "model": "bge-m3",
            "base_url": "http://36.140.33.19:7861/v1",
            "contract": "existing bge-query-instruct-cosine-v1, dimension 1024",
            "use": "existing retrieval only, no new endpoint or contract",
        },
        "limits": {
            "text_generation_requests": 400,
            "embedding_requests": 128,
            "rerank_requests": 0,
            "total_external_requests": 528,
            "text_reported_tokens": 3_000_000,
            "embedding_tokens": 50_000,
            "wall_seconds_from_first_request": 14400,
            "failed_retry_maintenance_requests_count": True,
            "unknown_usage": "retain known upper bound, never zero",
            "deadline": (
                "stop new requests; preserve complete/failed/unfinished; no extension or makeup"
            ),
        },
        "prohibitions": [
            "TEST",
            "main confirmation set",
            "Travel new groups",
            "RESERVE",
            "SUPPORT",
            "result-dependent replacement",
            "second solver",
            "reranker",
            "changed common conditions",
        ],
        "method_admission": {
            "ready": False,
            "remaining": [
                "permitted exact candidate/utility evidence",
                "implemented selection-only rule",
                "native adapter and scorer/source pins",
                "connected global budget guard",
                "pre-outcome opportunity and failure/unknown-cost accounting",
            ],
        },
        "usage_at_schedule_freeze": {
            "text_generation_requests": 0,
            "embedding_requests": 0,
            "rerank_requests": 0,
            "first_request_at": None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = prepare()
    # Exclusive creation prevents replacing an allocation after seeing outcomes.
    with args.output.open("x") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": sha(args.output),
                "status": value["status"],
                "paired_positions": 32,
                "arm_executions": 64,
            }
        )
    )


if __name__ == "__main__":
    main()
