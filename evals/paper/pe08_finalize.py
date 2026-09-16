"""Validate the label-free PE08 preference benchmark preparation and smoke."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.contracts import ContextRecord, read_context_archive
from evals.paper.datasets.extended import ExtendedCase, load_extended_inputs
from evals.paper.identity import sha256_file

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "var/dg11/paper/runs/pe08-preference-smoke-20260824-001"
METHOD_CONFIG = ROOT / "var/dg11/paper/method-configs/preference.json"
DEFAULT_OUTPUT = RUN / "result-001.json"
CANDIDATE_MANIFEST = ROOT / "var/dg11/freeze/candidate/candidate-manifest.json"
CANDIDATE_INVENTORY = ROOT / "var/dg11/final/candidate/inventory.json"
EXPECTED_CANDIDATE_ID = (
    "712577d17403951bdb6b7f6c7b6a2763b4b964427df33a857b02a316fbe74d51"
)
EXPECTED_CANDIDATE_MANIFEST_SHA256 = (
    "9812af51eeafac55e9ab250d37d6d4fe8217b73428b4543af74bbb7ad00cef5d"
)
EXPECTED_CANDIDATE_INVENTORY_SHA256 = (
    "b754b9cfed729192b02c9493c5cb3ff93a7961c72f440e5ddb358ef7785055bb"
)
METHODS = ("CTRL-NONE", "LME-BM25-S", "CTRL-TRUNC-FULL", "DG11-FULL")
CONTROLLED_METHODS = METHODS[:3]
EXPECTED_DATASETS: dict[str, dict[str, object]] = {
    "HorizonBench": {
        "formal_cases": 120,
        "formal_partition": "HORIZON-BALANCED-120",
        "formal_strata": {
            "gemini-3-flash:evolved": 20,
            "gemini-3-flash:static": 20,
            "o3:evolved": 20,
            "o3:static": 20,
            "sonnet-4.5:evolved": 20,
            "sonnet-4.5:static": 20,
        },
        "smoke_cases": 10,
        "smoke_partition": "HORIZON-OFFICIAL-SAMPLE-10-SMOKE",
        "smoke_strata": {
            "gemini-3-flash:evolved": 2,
            "gemini-3-flash:static": 2,
            "o3:evolved": 2,
            "o3:static": 1,
            "sonnet-4.5:evolved": 2,
            "sonnet-4.5:static": 1,
        },
    },
    "CUPID": {
        "formal_cases": 90,
        "formal_partition": "CUPID-BALANCED-90",
        "formal_strata": {"changing": 30, "consistent": 30, "contrastive": 30},
        "smoke_cases": 6,
        "smoke_partition": "CUPID-DISJOINT-SMOKE-6",
        "smoke_strata": {"changing": 2, "consistent": 2, "contrastive": 2},
    },
}


class PE08FinalizeError(RuntimeError):
    pass


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PE08FinalizeError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise PE08FinalizeError(f"expected JSON object: {path}")
    return value


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise PE08FinalizeError("PE08 result is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _bound_path(entry: object, *, label: str) -> Path:
    if not isinstance(entry, dict):
        raise PE08FinalizeError(f"missing {label} binding")
    raw_path = entry.get("path")
    expected_hash = entry.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(expected_hash, str):
        raise PE08FinalizeError(f"invalid {label} binding")
    path = (ROOT / raw_path).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise PE08FinalizeError(f"{label} leaves repository root") from exc
    if sha256_file(path) != expected_hash:
        raise PE08FinalizeError(f"{label} hash drifted")
    return path


def _label_free_envelope(path: Path) -> dict[str, Any]:
    value = _object(path)
    if (
        value.get("paper_labels_opened") is not False
        or value.get("answer_label_fields_read_by_preparer") is not False
        or value.get("forbidden_label_fields_present") is not False
        or value.get("selection_metadata_read_by_preparer") is not True
    ):
        raise PE08FinalizeError(f"label boundary drifted: {path}")
    return value


def _verify_inputs(
    benchmark: str, config: dict[str, Any]
) -> tuple[dict[str, Any], set[str]]:
    expected = EXPECTED_DATASETS[benchmark]
    formal_path = _bound_path(config.get("formal_inputs"), label=f"{benchmark} formal")
    smoke_path = _bound_path(config.get("smoke_inputs"), label=f"{benchmark} smoke")
    formal_raw = _label_free_envelope(formal_path)
    smoke_raw = _label_free_envelope(smoke_path)
    formal_partition, formal_cases = load_extended_inputs(formal_path)
    smoke_partition, smoke_cases = load_extended_inputs(smoke_path)
    if (
        formal_partition != expected["formal_partition"]
        or smoke_partition != expected["smoke_partition"]
        or len(formal_cases) != expected["formal_cases"]
        or len(smoke_cases) != expected["smoke_cases"]
        or formal_raw.get("stratum_counts") != expected["formal_strata"]
        or smoke_raw.get("stratum_counts") != expected["smoke_strata"]
    ):
        raise PE08FinalizeError(f"{benchmark} input denominator drifted")
    formal_ids = {case.case_id for case in formal_cases}
    smoke_ids = {case.case_id for case in smoke_cases}
    if formal_ids & smoke_ids:
        raise PE08FinalizeError(f"{benchmark} smoke overlaps formal selection")
    return (
        {
            "formal_case_count": len(formal_cases),
            "formal_partition": formal_partition,
            "formal_session_count": _session_count(formal_cases),
            "formal_strata": formal_raw["stratum_counts"],
            "paper_labels_opened": False,
            "smoke_case_count": len(smoke_cases),
            "smoke_disjoint_from_formal": True,
            "smoke_partition": smoke_partition,
            "smoke_session_count": _session_count(smoke_cases),
            "smoke_strata": smoke_raw["stratum_counts"],
        },
        smoke_ids,
    )


def _session_count(cases: tuple[ExtendedCase, ...]) -> int:
    return sum(len(case.sessions) for case in cases)


def _verify_context_envelope(
    *,
    path: Path,
    expected_partition: str,
    expected_ids: set[str],
    expected_methods: tuple[str, ...],
    expected_workers: int,
    dg11: bool,
) -> dict[str, Any]:
    envelope = _object(path)
    records = read_context_archive(path)
    expected_pairs = {
        (case_id, method_id)
        for case_id in expected_ids
        for method_id in expected_methods
    }
    if (
        envelope.get("benchmark_id") != expected_partition
        or envelope.get("status") != "PASS"
        or envelope.get("failure_count") != 0
        or envelope.get("paper_labels_opened") is not False
        or envelope.get("labels_accessed") is not False
        or envelope.get("answer_calls") != 0
        or envelope.get("maximum_concurrent_requests") != expected_workers
        or envelope.get("record_count") != len(expected_pairs)
        or len(records) != len(expected_pairs)
        or {(record.case_id, record.method_id) for record in records}
        != expected_pairs
    ):
        raise PE08FinalizeError(f"PE08 context denominator drifted: {path}")
    if dg11:
        if (
            envelope.get("candidate_id") != EXPECTED_CANDIDATE_ID
            or envelope.get("candidate_modified") is not False
        ):
            raise PE08FinalizeError("PE08 DG11 candidate binding drifted")
    elif envelope.get("token_budget") != 512:
        raise PE08FinalizeError("PE08 controlled token budget drifted")
    for record in records:
        _verify_record(record)
    return {
        "context_tokens_max": max(record.declared_tokens for record in records),
        "failure_count": 0,
        "methods": list(expected_methods),
        "record_count": len(records),
        "workers": expected_workers,
    }


def _verify_record(record: ContextRecord) -> None:
    if record.terminal_status != "SUCCEEDED" or not 0 <= record.declared_tokens <= 512:
        raise PE08FinalizeError("PE08 context record terminal/token drifted")
    usage = record.usage
    if any(
        usage.get(key) != 0
        for key in ("answer_calls", "ingest_extraction_calls", "judge_calls", "memory_query_model_calls")
    ):
        raise PE08FinalizeError("PE08 smoke made a forbidden model call")
    if record.method_id == "CTRL-NONE" and (
        record.context or record.source_ids or record.declared_tokens != 0
    ):
        raise PE08FinalizeError("PE08 no-memory context is not empty")


def _verify_candidate() -> dict[str, str]:
    if (
        sha256_file(CANDIDATE_MANIFEST) != EXPECTED_CANDIDATE_MANIFEST_SHA256
        or sha256_file(CANDIDATE_INVENTORY) != EXPECTED_CANDIDATE_INVENTORY_SHA256
        or _object(CANDIDATE_MANIFEST).get("candidate_id") != EXPECTED_CANDIDATE_ID
    ):
        raise PE08FinalizeError("frozen candidate identity drifted")
    return {
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "candidate_inventory_sha256": EXPECTED_CANDIDATE_INVENTORY_SHA256,
        "candidate_manifest_sha256": EXPECTED_CANDIDATE_MANIFEST_SHA256,
    }


def _verify_config(config: dict[str, Any]) -> None:
    if (
        config.get("schema") != "milai.dg11.paper-preference-method-config.v1"
        or config.get("status") != "PE08_CONTEXT_SMOKE_READY_FOR_PAPER_FREEZE"
        or config.get("methods") != list(METHODS)
        or config.get("candidate_id") != EXPECTED_CANDIDATE_ID
        or config.get("paper_labels_opened") is not False
        or config.get("development_ai_reviews") != 0
    ):
        raise PE08FinalizeError("PE08 method configuration drifted")
    runners = config.get("runners")
    if not isinstance(runners, dict):
        raise PE08FinalizeError("PE08 runner bindings are absent")
    _bound_path(runners.get("controlled"), label="PE08 controlled runner")
    _bound_path(runners.get("dg11"), label="PE08 DG11 runner")
    _bound_path(runners.get("dataset_loader"), label="PE08 dataset loader")
    datasets = config.get("datasets")
    if not isinstance(datasets, dict) or set(datasets) != set(EXPECTED_DATASETS):
        raise PE08FinalizeError("PE08 dataset configuration drifted")


def run(output: Path) -> dict[str, Any]:
    config = _object(METHOD_CONFIG)
    _verify_config(config)
    datasets = config["datasets"]
    input_results: dict[str, Any] = {}
    context_results: dict[str, Any] = {}
    artifact_hashes: dict[str, str] = {
        "method_config": sha256_file(METHOD_CONFIG)
    }
    for benchmark in EXPECTED_DATASETS:
        benchmark_config = datasets[benchmark]
        if not isinstance(benchmark_config, dict):
            raise PE08FinalizeError(f"{benchmark} configuration is invalid")
        input_result, smoke_ids = _verify_inputs(benchmark, benchmark_config)
        input_results[benchmark] = input_result
        expected_partition = str(EXPECTED_DATASETS[benchmark]["smoke_partition"])
        controlled_path = _bound_path(
            benchmark_config.get("controlled_smoke"),
            label=f"{benchmark} controlled smoke",
        )
        dg11_path = _bound_path(
            benchmark_config.get("dg11_smoke"), label=f"{benchmark} DG11 smoke"
        )
        context_results[benchmark] = {
            "controlled": _verify_context_envelope(
                path=controlled_path,
                expected_partition=expected_partition,
                expected_ids=smoke_ids,
                expected_methods=CONTROLLED_METHODS,
                expected_workers=2,
                dg11=False,
            ),
            "dg11": _verify_context_envelope(
                path=dg11_path,
                expected_partition=expected_partition,
                expected_ids=smoke_ids,
                expected_methods=("DG11-FULL",),
                expected_workers=1,
                dg11=True,
            ),
        }
        for artifact_name in (
            "formal_inputs",
            "smoke_inputs",
            "controlled_smoke",
            "dg11_smoke",
        ):
            entry = benchmark_config[artifact_name]
            path = _bound_path(entry, label=f"{benchmark} {artifact_name}")
            artifact_hashes[f"{benchmark}:{artifact_name}"] = sha256_file(path)
    result: dict[str, Any] = {
        "artifact_hashes": artifact_hashes,
        "candidate": _verify_candidate(),
        "candidate_modified": False,
        "context_smoke": context_results,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "development_ai_reviews": 0,
        "formal_answer_calls_started": 0,
        "inputs": input_results,
        "methods": list(METHODS),
        "paper_labels_opened": False,
        "run_id": "pe08-preference-smoke-20260824-001",
        "schema": "milai.dg11.pe08-preference-context-smoke.v1",
        "status": "PASS",
        "work_package": "DG11-PE08",
    }
    _atomic_json_once(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.output.resolve())
    print(
        json.dumps(
            {
                "paper_labels_opened": result["paper_labels_opened"],
                "status": result["status"],
                "work_package": result["work_package"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
