from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from milai.adapters.agent_prefetch import SYSTEM_PROMPT, prepare_compact_prefetch
from milai_openworker_mcp import TargetTokenizerCounter

from evals.agent_integration import f1
from evals.serving import minimal_baseline

MODEL_ID = "Qwen3.6-35B-A3B-FP8"
ENDPOINT = "http://127.0.0.1:7860"
TOKENIZER_JSON = Path("/cra/qwen36-35B/tokenizer.json")
MCP_EXECUTABLE = ROOT / "integrations/mcp/.venv/bin/milai-mcp"
ADAPTER_PYTHON = ROOT / "integrations/openworker-mcp/.venv/bin/python"
ENV_FILE = ROOT / "runtime/.env"
SOURCE_RECORDS = ROOT / "var/dg10/runs/lme-confirmation-20260823-003/raw-records.json"
RUNS_ROOT = ROOT / "var/dg11/runs"
CURRENT_STATE = ROOT / "var/dg11/current-state.json"
REPETITIONS = 101
CACHE_WARM_SAMPLES = 100


class EfficiencyError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_canonical(value) + b"\n")
    os.replace(temporary, path)


def _percentile(values: Sequence[float], percentile: float) -> float:
    result = minimal_baseline.nearest_rank(values, percentile)
    if result is None:
        raise EfficiencyError("percentile denominator is empty")
    return result


def _token_evidence() -> dict[str, Any]:
    source = json.loads(SOURCE_RECORDS.read_text(encoding="utf-8"))
    records = source.get("records")
    if not isinstance(records, list):
        raise EfficiencyError("frozen token source records are absent")
    milai = {
        str(record["case_id"]): record
        for record in records
        if isinstance(record, dict) and record.get("arm") == "MILAI_T3A"
    }
    rag = {
        str(record["case_id"]): record
        for record in records
        if isinstance(record, dict) and record.get("arm") == "NAIVE_RAG"
    }
    if len(milai) != 50 or set(milai) != set(rag):
        raise EfficiencyError("frozen 50-case token denominator drifted")
    counter = TargetTokenizerCounter(TOKENIZER_JSON)
    details: list[dict[str, Any]] = []
    for case_id in sorted(milai):
        record = milai[case_id]
        raw_context = record.get("memory_context")
        if not isinstance(raw_context, str) or "MILAI_MEMORY_DATA=" not in raw_context:
            raise EfficiencyError("MiLAi memory context is malformed")
        encoded = raw_context.split("MILAI_MEMORY_DATA=", 1)[1]
        payload = json.loads(encoded)
        items = payload.get("memory_items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise EfficiencyError("MiLAi memory items are absent")
        compact = prepare_compact_prefetch(
            {
                "status": "OK",
                "items": items,
                "open_issue_ids": [],
                "degraded_components": [],
                "trace_id": None,
            },
            query=str(record["question"]),
        )
        memory_tokens = counter.count_text(compact.rendered)
        old_prompt = int(record["prompt_tokens_recount"])
        old_memory = int(record["memory_tokens"])
        system_query = old_prompt - old_memory
        prompt_tokens = system_query + memory_tokens
        details.append(
            {
                "case_id": case_id,
                "system_query_tokens": system_query,
                "memory_tokens": memory_tokens,
                "prompt_tokens": prompt_tokens,
                "rag_prompt_tokens": int(rag[case_id]["prompt_tokens_recount"]),
                "session_refs_sidecar_count": len(compact.session_refs),
                "compiler_version": compact.compiler_version,
            }
        )
    prompt_values = [int(record["prompt_tokens"]) for record in details]
    rag_values = [int(record["rag_prompt_tokens"]) for record in details]
    memory_values = [int(record["memory_tokens"]) for record in details]
    ratio = mean(prompt_values) / mean(rag_values)
    gates = {
        "prompt_token_ratio_vs_rag_le_1_20": ratio <= 1.20,
        "mean_memory_tokens_le_300": mean(memory_values) <= 300,
        "max_memory_tokens_le_512": max(memory_values) <= 512,
        "sidecar_session_refs_present": all(
            int(record["session_refs_sidecar_count"]) > 0 for record in details
        ),
    }
    return {
        "source_run_id": str(source.get("run_id")),
        "logical_cases": len(details),
        "tokenizer_id": counter.tokenizer_id,
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "prompt_tokens": {
            "mean": round(mean(prompt_values), 3),
            "p95": _percentile([float(value) for value in prompt_values], 0.95),
        },
        "rag_prompt_tokens": {"mean": round(mean(rag_values), 3)},
        "prompt_token_ratio_vs_rag": round(ratio, 9),
        "memory_tokens": {
            "mean": round(mean(memory_values), 3),
            "max": max(memory_values),
        },
        "system_query_tokens": {
            "mean": round(
                mean(int(record["system_query_tokens"]) for record in details), 3
            )
        },
        "gates": gates,
        "status": "PASS" if all(gates.values()) else "FAILED",
        "records": details,
    }


def _provider_manifest(
    tier_run_id: str,
    dataset_digest: str,
    prompt_digest: str,
    endpoint: str,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "schema": "milai.provider.dev-run.v1",
        "run_id": tier_run_id,
        "phase": "serving",
        "provider": "local_vllm",
        "endpoint_identity": endpoint,
        "model_id": MODEL_ID,
        "dataset_manifest_sha256": dataset_digest,
        "prompt_template_sha256": prompt_digest,
        "max_native_requests": REPETITIONS,
        "max_prompt_tokens": REPETITIONS * minimal_baseline.PROMPT_TOKEN_BUDGET,
        "max_completion_tokens": REPETITIONS
        * minimal_baseline.COMPLETION_TOKEN_BUDGET,
        "deadline": (now + timedelta(hours=2)).isoformat(),
        "expires_at": (now + timedelta(hours=3)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
    }


def _serving_evidence(run_id: str, run_dir: Path, endpoint: str) -> dict[str, Any]:
    dataset_contract = {
        "task": "synthetic governed runtime version lookup",
        "tiers": list(minimal_baseline.TIERS),
        "repetitions_per_tier": REPETITIONS,
        "cold_samples_per_tier": 1,
        "warm_samples_per_tier": REPETITIONS - 1,
        "schedule": "latin-square",
        "persistent_openworker": True,
    }
    prompt_contract = {
        "system_prompt": SYSTEM_PROMPT,
        "response_rules": f1.RESPONSE_RULES,
        "user_template": (
            "Use the available milai_recall capability when memory is enabled. "
            "What runtime Python version is recorded for synthetic project {marker}? "
            "Return only the required JSON answer and preserve uncertainty."
        ),
        "generation": {
            "model": MODEL_ID,
            "temperature": 0,
            "max_tokens": minimal_baseline.COMPLETION_TOKEN_BUDGET,
            "stream": False,
            "enable_thinking": False,
        },
    }
    dataset_digest = _digest(dataset_contract)
    prompt_digest = _digest(prompt_contract)
    manifests: dict[str, Path] = {}
    ledgers: dict[str, Path] = {}
    traces: dict[str, Path] = {}
    for tier in minimal_baseline.TIERS:
        tier_dir = run_dir / tier.casefold()
        tier_dir.mkdir(mode=0o700)
        manifest = tier_dir / "provider-manifest.json"
        _atomic_write(
            manifest,
            _provider_manifest(
                f"{run_id}-{tier.casefold()}", dataset_digest, prompt_digest, endpoint
            ),
        )
        manifests[tier] = manifest
        if tier != "T0":
            ledgers[tier] = tier_dir / "provider-ledger.jsonl"
        if tier in {"T2", "T3a"}:
            traces[tier] = tier_dir / "openworker-adapter-trace.jsonl"
    _atomic_write(
        run_dir / "manifest.json",
        {
            "schema": "milai.dg11.efficiency-manifest.v1",
            "run_id": run_id,
            "dataset_contract": dataset_contract,
            "dataset_contract_sha256": dataset_digest,
            "prompt_contract": prompt_contract,
            "prompt_contract_sha256": prompt_digest,
            "expected_native_requests": len(minimal_baseline.TIERS) * REPETITIONS,
            "development_ai_reviews": 0,
        },
    )
    report = minimal_baseline.run(
        env_file=ENV_FILE,
        manifests=manifests,
        ledgers=ledgers,
        traces=traces,
        mcp_executable=MCP_EXECUTABLE,
        tokenizer_json=TOKENIZER_JSON,
        adapter_python=ADAPTER_PYTHON,
        repetitions=REPETITIONS,
        persistent_openworker=True,
        cache_probe_warm_samples=CACHE_WARM_SAMPLES,
    )
    _atomic_write(run_dir / "serving-report.json", report)
    return report


def _classify(token: Mapping[str, Any], serving: Mapping[str, Any]) -> dict[str, Any]:
    aggregates = serving.get("aggregates")
    cache = serving.get("validated_cache")
    overhead = serving.get("derived_warm_overhead_ms")
    provider = serving.get("provider_trace")
    if not all(isinstance(value, Mapping) for value in (aggregates, cache, overhead, provider)):
        raise EfficiencyError("serving evidence is incomplete")
    assert isinstance(aggregates, Mapping)
    assert isinstance(cache, Mapping)
    assert isinstance(overhead, Mapping)
    assert isinstance(provider, Mapping)
    terminal_count = sum(
        int(aggregates[tier]["success_count"]) for tier in minimal_baseline.TIERS
    )
    expected = len(minimal_baseline.TIERS) * REPETITIONS
    dg11_04 = {
        **dict(token["gates"]),
        "validated_cache_hit_correctness_100": cache.get("hit_correctness") == 1.0,
        "validated_cache_warm_p95_le_12_ms": (
            float((cache.get("warm_ms") or {}).get("p95", float("inf"))) <= 12
        ),
        "stale_cache_policy_bypass_zero": cache.get("stale_or_policy_bypass") == 0,
    }
    dg11_05 = {
        "warm_samples_per_tier_ge_100": all(
            int(aggregates[tier]["warm_request_count"]) >= 100
            for tier in minimal_baseline.TIERS
        ),
        "terminal_rate_100": terminal_count == expected,
        "memory_control_warm_p95_le_75_ms": (
            float(aggregates["T3a"]["warm_memory_control_ms"]["p95"]) <= 75
        ),
        "t2_minus_t1_warm_mean_le_100_ms": (
            float(overhead["agent_integration_mean"]) <= 100
        ),
        "t3a_minus_t2_warm_mean_le_100_ms": (
            float(overhead["memory_incremental_mean"]) <= 100
        ),
        "p99_reported": all(
            aggregates[tier]["warm_e2e_ms"].get("p99") is not None
            for tier in minimal_baseline.TIERS
        ),
        "hidden_provider_calls_zero": provider.get("hidden_model_calls") == 0,
        "persistent_client": (
            serving.get("openworker_client_lifecycle")
            == "PERSISTENT_DOCKER_EXEC_HTTP_BRIDGE"
        ),
    }
    return {
        "DG11-04": {
            "gates": dg11_04,
            "status": "PASS" if all(dg11_04.values()) else "FAILED",
        },
        "DG11-05": {
            "gates": dg11_05,
            "status": "PASS" if all(dg11_05.values()) else "FAILED",
        },
    }


def _update_state(run_id: str, classification: Mapping[str, Any]) -> None:
    state = json.loads(CURRENT_STATE.read_text(encoding="utf-8"))
    packages = dict(state["work_packages"])
    for package in ("DG11-04", "DG11-05"):
        packages[package] = str(classification[package]["status"])
    state.update(
        {
            "phase": (
                "EFFICIENCY_FIXED"
                if packages["DG11-04"] == packages["DG11-05"] == "PASS"
                else "EFFICIENCY_IN_PROGRESS"
            ),
            "latest_result": run_id,
            "work_packages": packages,
        }
    )
    _atomic_write(CURRENT_STATE, state)


def run(run_id: str, endpoint: str) -> dict[str, Any]:
    if not run_id or len(run_id) > 96 or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in run_id
    ):
        raise EfficiencyError("run_id must be lowercase URL-safe text")
    for path in (TOKENIZER_JSON, MCP_EXECUTABLE, ADAPTER_PYTHON, ENV_FILE, SOURCE_RECORDS):
        if not path.is_file():
            raise EfficiencyError(f"required input is absent: {path}")
    run_dir = RUNS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(run_dir, 0o700)
    started = datetime.now(UTC)
    token = _token_evidence()
    _atomic_write(run_dir / "token-report.json", token)
    serving = _serving_evidence(run_id, run_dir, endpoint)
    classification = _classify(token, serving)
    result = {
        "schema": "milai.dg11.efficiency-result.v1",
        "run_id": run_id,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "development_ai_reviews": 0,
        "token": token,
        "serving_summary": {
            "aggregates": serving["aggregates"],
            "derived_warm_overhead_ms": serving["derived_warm_overhead_ms"],
            "validated_cache": serving["validated_cache"],
            "provider_trace": serving["provider_trace"],
            "openworker_client_lifecycle": serving["openworker_client_lifecycle"],
        },
        "classification": classification,
        "status": (
            "PASS"
            if all(classification[key]["status"] == "PASS" for key in classification)
            else "FAILED"
        ),
    }
    _atomic_write(run_dir / "result.json", result)
    _atomic_write(ROOT / "var/dg11/efficiency/latest-result.json", result)
    _update_state(run_id, classification)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DG11 prompt/cache/persistent serving gates")
    parser.add_argument(
        "--run-id",
        default="dg11-efficiency-"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ").casefold()
        + "-"
        + uuid.uuid4().hex[:8],
    )
    parser.add_argument("--endpoint", default=ENDPOINT)
    args = parser.parse_args()
    result = run(args.run_id, args.endpoint)
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "classification": result["classification"],
            },
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
