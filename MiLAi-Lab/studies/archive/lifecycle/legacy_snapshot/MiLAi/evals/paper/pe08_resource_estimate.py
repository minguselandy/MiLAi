"""Pre-freeze resource estimate for the PE08 preference matrix."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

from evals.paper.contracts import read_context_archive
from evals.paper.datasets.extended import ExtendedCase, load_extended_inputs
from evals.paper.identity import sha256_file

ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "var/dg11/paper/freeze"
RUN = ROOT / "var/dg11/paper/runs/pe08-preference-smoke-20260824-001"
DEFAULT_OUTPUT = RUN / "resource-estimate-002.json"
METHOD_COUNT = 4
RESOURCE_CEILINGS = {
    "estimated_dg11_embedding_calls": 1_000_000,
    "formal_answer_and_evaluator_calls": 3_000,
    "formal_source_payload_bytes": 100_000_000,
    "maximum_concurrent_requests": 2,
}
DATASETS = {
    "HorizonBench": {
        "formal": FREEZE / "horizon-subset-inputs.json",
        "smoke": FREEZE / "horizon-smoke-inputs.json",
        "dg11": RUN / "horizon-dg11-contexts-004.json",
    },
    "CUPID": {
        "formal": FREEZE / "cupid-subset-inputs.json",
        "smoke": FREEZE / "cupid-smoke-inputs.json",
        "dg11": RUN / "cupid-dg11-contexts-003.json",
    },
}


class PE08ResourceError(RuntimeError):
    pass


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise PE08ResourceError("PE08 resource estimate is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _input_stats(cases: tuple[ExtendedCase, ...]) -> dict[str, int]:
    sessions = [session for case in cases for session in case.sessions]
    turns = [turn for session in sessions for turn in session.turns]
    return {
        "case_count": len(cases),
        "session_count": len(sessions),
        "source_payload_bytes": sum(len(turn.content.encode()) for turn in turns),
        "turn_count": len(turns),
    }


def _dataset_estimate(name: str, paths: dict[str, Path]) -> dict[str, Any]:
    formal_partition, formal_cases = load_extended_inputs(paths["formal"])
    smoke_partition, smoke_cases = load_extended_inputs(paths["smoke"])
    formal = _input_stats(formal_cases)
    smoke = _input_stats(smoke_cases)
    envelope = json.loads(paths["dg11"].read_text(encoding="utf-8"))
    records = read_context_archive(paths["dg11"])
    if (
        not isinstance(envelope, dict)
        or envelope.get("status") != "PASS"
        or envelope.get("failure_count") != 0
        or envelope.get("paper_labels_opened") is not False
        or envelope.get("labels_accessed") is not False
        or len(records) != smoke["case_count"]
        or any(record.terminal_status != "SUCCEEDED" for record in records)
    ):
        raise PE08ResourceError(f"{name} DG11 smoke is incomplete")
    smoke_embedding_calls = sum(
        int(record.usage.get("embedding_calls", 0)) for record in records
    )
    if smoke_embedding_calls <= 0 or smoke["turn_count"] <= 0:
        raise PE08ResourceError(f"{name} smoke accounting is absent")
    turn_scale = formal["turn_count"] / smoke["turn_count"]
    estimated_embeddings = math.ceil(smoke_embedding_calls * turn_scale)
    return {
        "dg11_context_records": formal["case_count"],
        "estimated_dg11_embedding_calls": estimated_embeddings,
        "formal": formal,
        "formal_input_sha256": sha256_file(paths["formal"]),
        "formal_partition": formal_partition,
        "method_context_records": formal["case_count"] * METHOD_COUNT,
        "smoke": smoke,
        "smoke_dg11_embedding_calls": smoke_embedding_calls,
        "smoke_dg11_sha256": sha256_file(paths["dg11"]),
        "smoke_input_sha256": sha256_file(paths["smoke"]),
        "smoke_partition": smoke_partition,
        "turn_scale_factor": round(turn_scale, 6),
    }


def run(output: Path) -> dict[str, Any]:
    estimates = {
        name: _dataset_estimate(name, paths) for name, paths in DATASETS.items()
    }
    total_embeddings = sum(
        int(value["estimated_dg11_embedding_calls"]) for value in estimates.values()
    )
    total_bytes = sum(
        int(value["formal"]["source_payload_bytes"]) for value in estimates.values()
    )
    horizon_cases = int(estimates["HorizonBench"]["formal"]["case_count"])
    cupid_cases = int(estimates["CUPID"]["formal"]["case_count"])
    provider_plan = {
        "cupid_generation_answer_calls": cupid_cases * METHOD_COUNT,
        "cupid_generation_judge_calls": cupid_cases * METHOD_COUNT,
        "cupid_inference_calls": cupid_cases * METHOD_COUNT,
        "cupid_preference_decomposition_calls": cupid_cases * METHOD_COUNT,
        "cupid_preference_matcher_calls": cupid_cases * METHOD_COUNT * 2,
        "horizon_answer_calls": horizon_cases * METHOD_COUNT,
    }
    total_provider_calls = sum(provider_plan.values())
    observed = {
        "estimated_dg11_embedding_calls": total_embeddings,
        "formal_answer_and_evaluator_calls": total_provider_calls,
        "formal_source_payload_bytes": total_bytes,
        "maximum_concurrent_requests": 2,
    }
    gates = {
        key: observed[key] <= ceiling
        for key, ceiling in RESOURCE_CEILINGS.items()
    }
    result: dict[str, Any] = {
        "datasets": estimates,
        "development_ai_reviews": 0,
        "estimation_policy": "LINEAR_BY_LABEL_FREE_SOURCE_TURN_COUNT_FROM_DISJOINT_SMOKE",
        "formal_provider_call_plan": provider_plan,
        "gate_results": gates,
        "paper_labels_opened": False,
        "resource_ceilings": RESOURCE_CEILINGS,
        "resource_totals": observed,
        "schema": "milai.dg11.pe08-resource-estimate.v1",
        "status": "PASS" if all(gates.values()) else "RESOURCE_GATE_FAIL",
        "work_package": "DG11-PE08",
    }
    _atomic_json_once(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.output.resolve())
    print(json.dumps({"status": result["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
