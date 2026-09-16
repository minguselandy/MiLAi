from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from milai.adapters.agent_prefetch import PrefetchContext
from milai.adapters.provider_execution import (
    JsonCompletionTransport,
    ProviderExecutionGateway,
    ProviderRequest,
)

from evals.benchmark import dg11_holdout, dg11_measurement
from evals.benchmark import lme_product_smoke as benchmark
from scripts import dg11_state
from scripts import run_dg10_benchmark_dev_smoke as scorer_v1

SOURCE_IDS = ("94f70d80", "9aaed6a3", "37d43f65", "cc539528", "6222b6eb")
SOURCE_INPUTS = ROOT / "var/dg11/holdout/v1/holdout-inputs.json"
DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
ENDPOINT = "http://127.0.0.1:7860"
ENV_FILE = ROOT / "runtime/.env"
PYTHON = ROOT / "runtime/.venv/bin/python"


def _context(value: dict[str, str]) -> PrefetchContext:
    return PrefetchContext(
        status=value["status"],
        rendered=value["rendered"],
        context_sha256=value["context_sha256"],
        trace_id=None,
        request_id=None,
        claim_refs=(),
        evidence_refs=(),
        open_issue_ids=(),
        degraded_components=(),
        abstention_reason=None,
    )


def run(run_id: str, *, source_ids: tuple[str, ...] = SOURCE_IDS) -> dict[str, object]:
    if not source_ids or len(source_ids) != len(set(source_ids)):
        raise ValueError("source_ids must be non-empty and unique")
    unknown = sorted(set(source_ids).difference(SOURCE_IDS))
    if unknown:
        raise ValueError(f"source_ids are not opened holdout failures: {unknown}")
    run_dir = ROOT / "var/dg11/runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    source = json.loads(SOURCE_INPUTS.read_text(encoding="utf-8"))
    cases = {case["source_id"]: case for case in source["cases"]}
    processes: list[tuple[subprocess.Popen[bytes], Path]] = []
    batches = tuple(source_ids[index : index + 3] for index in range(0, len(source_ids), 3))
    for batch_index, batch in enumerate(batches, start=1):
        inputs = {
            "schema": "milai.dg11.holdout-inputs.v1",
            "label_fields_present": False,
            "source_ids": list(batch),
            "cases": [cases[source_id] for source_id in batch],
        }
        input_path = run_dir / f"inputs-{batch_index}.json"
        output_path = run_dir / f"contexts-{batch_index}.json"
        dg11_state.atomic_json(input_path, inputs)
        environment = dict(os.environ)
        environment.update(
            {
                "DG10_MCP_HOST_PYTHON": str(
                    ROOT / "integrations/mcp/.venv/bin/python"
                ),
                "PYTHONPATH": str(ROOT),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        command = [
            str(PYTHON),
            "-m",
            "evals.benchmark.dg11_holdout_context_worker",
            "--inputs",
            str(input_path),
            "--output",
            str(output_path),
            "--env-file",
            str(ENV_FILE),
            "--identity",
            "current",
            "--workers",
            "1",
            "--expected-cases",
            str(len(batch)),
        ]
        processes.append((subprocess.Popen(command, cwd=ROOT, env=environment), output_path))
    for process, _output in processes:
        if process.wait() != 0:
            raise dg11_holdout.HoldoutError("targeted context batch failed")
    context_records = [
        record
        for _process, output in processes
        for record in json.loads(output.read_text(encoding="utf-8"))["records"]
    ]
    contexts = {record["source_id"]: record for record in context_records}

    now = datetime.now(UTC)
    manifest = {
        "schema": "milai.provider.dev-run.v1",
        "run_id": run_id,
        "phase": "dev",
        "provider": "local_vllm",
        "endpoint_identity": ENDPOINT,
        "model_id": benchmark.MODEL_ID,
        "dataset_manifest_sha256": dg11_state.sha256(SOURCE_INPUTS),
        "prompt_template_sha256": benchmark.prompt_contract_sha256(),
        "max_native_requests": len(source_ids),
        "max_prompt_tokens": len(source_ids) * benchmark.PROMPT_TOKEN_BUDGET,
        "max_completion_tokens": len(source_ids) * benchmark.MAX_OUTPUT_TOKENS,
        "deadline": (now + timedelta(minutes=15)).isoformat(),
        "expires_at": (now + timedelta(minutes=20)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
    }
    manifest_path = run_dir / "provider-manifest.json"
    ledger_path = run_dir / "provider-ledger.jsonl"
    dg11_state.atomic_json(manifest_path, manifest)
    gateway = ProviderExecutionGateway(manifest_path, ledger_path)
    transport = JsonCompletionTransport()
    rows = json.loads(DATASET.read_text(encoding="utf-8"))
    labels = {
        row["question_id"]: benchmark.scoring._answer_values(row["answer"])
        for row in rows
        if row.get("question_id") in source_ids
    }
    records = []
    for index, source_id in enumerate(source_ids):
        case = dg11_holdout.product_case(cases[source_id])
        context = _context(contexts[source_id]["context"])
        messages = benchmark._messages(case.question, case.question_at, context)
        prompt_tokens = benchmark._count_prompt_tokens(ENDPOINT, messages)
        completion = gateway.execute(
            ProviderRequest(
                logical_request_id=f"{run_id}-{index + 1:02d}-current",
                transport="json",
                payload=benchmark._payload(messages, f"{run_id}-{source_id}"),
                prompt_token_budget=benchmark.PROMPT_TOKEN_BUDGET,
                completion_token_budget=benchmark.MAX_OUTPUT_TOKENS,
                timeout_seconds=180,
            ),
            transport,
            benchmark._parse,
        )
        answer = str(completion.value)
        records.append(
            {
                "source_id": source_id,
                "category": case.category,
                "answer": answer,
                "scorer_v1": scorer_v1._score(answer, labels[source_id]),
                "scorer_v2": dg11_measurement.score_v2(answer, labels[source_id]),
                "prompt_tokens": prompt_tokens,
                "context_status": context.status,
            }
        )
    events = gateway.read_ledger()
    terminals = [event for event in events if event.get("event") == "PROVIDER_TERMINAL"]
    post = [event for event in events if event.get("event") == "POST_PROVIDER_TERMINAL"]
    valid = len(terminals) == len(post) == len(records) == len(source_ids)
    result: dict[str, object] = {
        "schema": "milai.dg11.holdout-failure-dev.v1",
        "run_id": run_id,
        "status": "PASS" if valid else "FAILED",
        "provider_requests": len(terminals),
        "hidden_provider_calls": 0,
        "records": records,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.atomic_json(run_dir / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--source-id", action="append", choices=SOURCE_IDS)
    args = parser.parse_args()
    started = time.monotonic()
    result = run(
        args.run_id,
        source_ids=tuple(args.source_id) if args.source_id else SOURCE_IDS,
    )
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
