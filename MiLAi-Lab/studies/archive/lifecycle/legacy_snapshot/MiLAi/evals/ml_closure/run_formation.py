"""Label-blind Formation runner for the lifecycle matched effect."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from milai.application.formation_extraction import build_formation_sidecar
from milai.application.formation_engine import DEFAULT_FORMATION_ENGINE
from milai.application.state_change_formation import build_state_change_sidecar
from milai.domain.requirement_state import canonical_sha256


class FormationRunError(RuntimeError):
    """A frozen input or output contract drifted."""


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("conversations"), list):
        raise FormationRunError("FORMATION_RAW_DATA_INVALID")
    return value


def _sources(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for turn in conversation["turns"]:
        source = dict(turn)
        source["case_id"] = conversation["conversation_id"]
        source["content_hash"] = canonical_sha256(source["content"])
        output.append(source)
    return output


def _run_one(conversation: dict[str, Any], arm: str) -> dict[str, Any]:
    sources = _sources(conversation)
    started = time.perf_counter()
    if arm == "V01":
        formation = build_formation_sidecar(sources)
        state = build_state_change_sidecar(sources)
        producer = "existing-v01"
    elif arm == "V02":
        bundle = DEFAULT_FORMATION_ENGINE.build(sources).generalized
        formation = bundle.formation
        state = bundle.state_changes
        producer = bundle.producer_identity
    else:
        raise FormationRunError(f"FORMATION_ARM_INVALID:{arm}")
    elapsed_ms = (time.perf_counter() - started) * 1_000
    return {
        "conversation_id": conversation["conversation_id"],
        "scope_id": conversation["scope_id"],
        "source_evidence_ids": [item["evidence_id"] for item in sources],
        "formation": formation.model_dump(mode="json"),
        "state_changes": state.model_dump(mode="json"),
        "producer_identity": producer,
        "wall_ms": round(elapsed_ms, 6),
        "query_fields_visible_to_formation": False,
        "model_calls": formation.model_calls,
        "reader_calls": 0,
        "canonical_mutations": 0,
        "database_writes": 0,
    }


def execute(raw_path: Path, arm: str, workers: int) -> dict[str, Any]:
    raw_bytes = raw_path.read_bytes()
    dataset = _load(raw_path)
    conversations = sorted(
        dataset["conversations"], key=lambda row: row["conversation_id"]
    )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(executor.map(lambda row: _run_one(row, arm), conversations))
    output: dict[str, Any] = {
        "schema": "milai.memory-lifecycle-formation-unscored.v0.1",
        "split": dataset.get("split"),
        "arm": arm,
        "raw_path": str(raw_path),
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "conversation_count": len(rows),
        "workers": workers,
        "query_fields_visible_to_formation": False,
        "formal_holdout_used": False,
        "rows": rows,
        "cost": {
            "formation_wall_ms": round(sum(row["wall_ms"] for row in rows), 6),
            "model_calls": sum(row["model_calls"] for row in rows),
            "reader_calls": 0,
            "canonical_mutations": 0,
            "database_writes": 0,
        },
    }
    output["output_digest"] = canonical_sha256(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--arm", choices=("V01", "V02"), required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.raw.resolve(), args.arm, args.workers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    print(result["output_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
