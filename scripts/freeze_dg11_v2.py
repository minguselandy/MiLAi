from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.benchmark import dg11_holdout, dg11_v2
from evals.benchmark import lme_product_smoke as benchmark
from scripts import dg11_state
from scripts import run_dg10_f0 as package_gate

DEFAULT_FREEZE_ROOT = ROOT / "var/dg11/holdout/v2"
SOURCE_IDS = ROOT / "var/dg11/splits/v1/generalization-v2/source-ids.json"
INPUTS = ROOT / "var/dg11/splits/v1/generalization-v2/label-free-inputs.json"
SPLIT_FREEZE = ROOT / "var/dg11/splits/v1/freeze-manifest.json"
SPLIT_BINDING = ROOT / "var/dg11/splits/v1/candidate-binding.json"
CANDIDATE_MANIFEST = ROOT / "var/dg11/freeze/candidate/candidate-manifest.json"
DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"


class V2FreezeError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V2FreezeError(f"required JSON is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise V2FreezeError(f"required JSON is not an object: {path}")
    return value


def code_identity() -> str:
    return package_gate._tree_identity(
        [
            ROOT / "evals/benchmark/dg11_holdout.py",
            ROOT / "evals/benchmark/dg11_v2.py",
            ROOT / "evals/benchmark/dg11_holdout_context_worker.py",
            ROOT / "evals/benchmark/lme_product_smoke.py",
            ROOT / "scripts/freeze_dg11_v2.py",
            ROOT / "scripts/run_dg11_v2.py",
        ]
    )


def _resolve_wheels(
    candidate: dict[str, Any], key: str, base: Path
) -> dict[str, dict[str, Any]]:
    raw = candidate.get(key)
    if not isinstance(raw, dict):
        raise V2FreezeError(f"candidate wheel group is absent: {key}")
    if key == "rollback":
        raw = raw.get("wheels")
        if not isinstance(raw, dict):
            raise V2FreezeError("DG10 rollback wheels are absent")
    expected = {
        "client_wheel": "milai_client-",
        "mcp_wheel": "milai_mcp-",
        "runtime_wheel": "milai_runtime-",
        "openworker_wheel": "milai_openworker_mcp-",
    }
    result: dict[str, dict[str, Any]] = {}
    if key == "rollback":
        by_prefix = {
            prefix: entry
            for filename, entry in raw.items()
            for prefix in expected.values()
            if str(filename).startswith(prefix)
        }
        entries = {name: by_prefix.get(prefix) for name, prefix in expected.items()}
    else:
        entries = {name: raw.get(name) for name in expected}
    for name, entry in entries.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise V2FreezeError(f"candidate wheel is absent: {key}/{name}")
        path = (base / str(entry["path"])).resolve()
        if not path.is_file() or dg11_state.sha256(path) != entry.get("sha256"):
            raise V2FreezeError(f"candidate wheel identity drifted: {key}/{name}")
        result[name] = {
            "path": str(path),
            "sha256": entry["sha256"],
            "bytes": path.stat().st_size,
        }
    return result


def freeze(freeze_root: Path = DEFAULT_FREEZE_ROOT) -> dict[str, Any]:
    if freeze_root.exists():
        raise V2FreezeError(f"V2 freeze already exists: {freeze_root}")
    source = _load(SOURCE_IDS)
    inputs = _load(INPUTS)
    split = _load(SPLIT_FREEZE)
    binding = _load(SPLIT_BINDING)
    candidate = _load(CANDIDATE_MANIFEST)
    if (
        source.get("split") != "DG11_GENERALIZATION_V2"
        or source.get("case_count") != dg11_v2.CASE_COUNT
        or source.get("status") != "FROZEN_UNCONSUMED"
        or inputs.get("label_fields_present") is not False
        or len(inputs.get("cases", [])) != dg11_v2.CASE_COUNT
        or inputs.get("source_ids") != source.get("source_ids")
        or dg11_holdout.digest(tuple(inputs["source_ids"]))
        != source.get("source_ids_sha256")
        or split.get("status") != "PASS"
        or binding.get("status") != "BOUND"
        or candidate.get("status") != "FROZEN"
        or binding.get("candidate_id") != candidate.get("candidate_id")
        or binding.get("candidate_manifest_sha256")
        != dg11_state.sha256(CANDIDATE_MANIFEST)
        or candidate.get("development_ai_reviews") != 0
    ):
        raise V2FreezeError("V2 split or candidate binding drifted")
    if dg11_state.sha256(INPUTS) != split["generalization_v2"]["label_free_inputs_sha256"]:
        raise V2FreezeError("V2 label-free input digest drifted")

    dg11_wheels = _resolve_wheels(candidate, "wheels", CANDIDATE_MANIFEST.parent)
    rollback = candidate.get("rollback")
    if not isinstance(rollback, dict):
        raise V2FreezeError("DG10 rollback identity is absent")
    dg10_wheels = _resolve_wheels(
        candidate,
        "rollback",
        ROOT,
    )
    schedules = [list(dg11_v2.schedule(index)) for index in range(dg11_v2.CASE_COUNT)]
    position_counts = {
        arm: [
            sum(schedule[position] == arm for schedule in schedules)
            for position in range(len(dg11_v2.ARMS))
        ]
        for arm in dg11_v2.ARMS
    }
    freeze_root.mkdir(parents=True, mode=0o700)
    manifest = {
        "schema": "milai.dg11.generalization-v2-freeze.v1",
        "status": "FROZEN",
        "frozen_at": datetime.now(UTC).isoformat(),
        "candidate_id": candidate["candidate_id"],
        "candidate_manifest_path": str(CANDIDATE_MANIFEST.relative_to(ROOT)),
        "candidate_manifest_sha256": dg11_state.sha256(CANDIDATE_MANIFEST),
        "split_freeze_sha256": dg11_state.sha256(SPLIT_FREEZE),
        "source_ids_path": str(SOURCE_IDS.relative_to(ROOT)),
        "source_ids_sha256": source["source_ids_sha256"],
        "inputs_path": str(INPUTS.relative_to(ROOT)),
        "inputs_sha256": dg11_state.sha256(INPUTS),
        "dataset_path": str(DATASET.resolve()),
        "dataset_sha256": dg11_state.sha256(DATASET),
        "case_count": dg11_v2.CASE_COUNT,
        "arms": list(dg11_v2.ARMS),
        "native_answer_requests": dg11_v2.CASE_COUNT * len(dg11_v2.ARMS),
        "answer_calls_per_arm_case": 1,
        "hidden_answer_calls": 0,
        "schedule": "FROZEN_FOUR_BY_FOUR_CYCLIC_LATIN_SQUARE",
        "schedule_sha256": dg11_v2.schedule_identity(),
        "schedule_position_counts_per_arm": position_counts,
        "generation_seed_namespace_sha256": hashlib.sha256(
            dg11_v2.GENERATION_SEED_NAMESPACE.encode()
        ).hexdigest(),
        "prompt_contract_sha256": benchmark.prompt_contract_sha256(),
        "model_id": benchmark.MODEL_ID,
        "memory_token_budget": benchmark.MEMORY_TOKEN_BUDGET,
        "max_output_tokens": benchmark.MAX_OUTPUT_TOKENS,
        "code_identity": code_identity(),
        "dg10_frozen_wheels": dg10_wheels,
        "dg11_frozen_wheels": dg11_wheels,
        "consumption_path": str((freeze_root / "consumption.json").relative_to(ROOT)),
        "labels_opened": False,
        "thresholds": {
            "dg11_minus_dg10_paired_f1_min": 0.04,
            "bootstrap_lower95_strictly_greater_than": 0,
            "dg11_minus_dg10_em_min": 0,
            "dg11_minus_custom_lexical_f1_min": 0.10,
            "single_assistant_delta_vs_custom_min": 0,
            "preference_delta_vs_custom_min": 0,
            "temporal_delta_vs_dg10_strictly_greater_than": 0,
            "prompt_token_ratio_vs_custom_max": 1.20,
            "safety_failures": 0,
        },
        "provider_requests": 0,
        "development_ai_reviews": 0,
    }
    dg11_state.atomic_json(freeze_root / "freeze-manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze DG11 generalization V2")
    parser.add_argument("--freeze-root", type=Path, default=DEFAULT_FREEZE_ROOT)
    args = parser.parse_args()
    manifest = freeze(args.freeze_root.resolve())
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
