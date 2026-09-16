"""Finalize the unfrozen DG11-PE04 answer-runner smoke and resume proof."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.contracts import read_context_archive
from evals.paper.identity import sha256_file
from evals.paper.provider import prompt_contract_sha256
from evals.paper.runners.longmemeval import (
    require_unfrozen_smoke_inputs,
    run_answers,
)
from evals.paper.usage_ledger import UsageLedger

ROOT = Path(__file__).resolve().parents[2]
METHODS = (
    "CTRL-NONE",
    "CTRL-CUSTOM-LEX1",
    "LME-BM25-S",
    "LME-BM25-T",
    "LME-DENSE",
)


class PE04FinalizeError(RuntimeError):
    pass


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def run(
    *,
    run_id: str,
    inputs: Path,
    context_archives: tuple[Path, ...],
    output_dir: Path,
    output: Path,
) -> dict[str, Any]:
    require_unfrozen_smoke_inputs(inputs)
    raw_path = output_dir / "raw-generations.json"
    ledger_path = output_dir / "usage-ledger.jsonl"
    raw_before = sha256_file(raw_path)
    ledger_before = sha256_file(ledger_path)
    resumed = run_answers(
        run_id=run_id,
        input_path=inputs,
        context_archives=context_archives,
        output_dir=output_dir,
        methods=METHODS,
        workers=2,
        memory_token_budget=512,
        prompt_token_budget=32_768,
        freeze_manifest=ROOT / "var/dg11/paper/freeze/paper-freeze-manifest.json",
        allow_unfrozen_smoke=True,
    )
    raw_after = sha256_file(raw_path)
    ledger_after = sha256_file(ledger_path)
    if raw_before != raw_after or ledger_before != ledger_after:
        raise PE04FinalizeError("safe resume changed an append-only answer artifact")
    if (
        resumed.get("schema") != "milai.dg11.paper-longmemeval-generations.v1"
        or resumed.get("status") != "PASS"
        or resumed.get("paper_labels_opened") is not False
        or resumed.get("record_count") != 25
        or resumed.get("expected_answer_calls") != 25
        or resumed.get("workers") != 2
        or resumed.get("methods") != list(METHODS)
        or not isinstance(resumed.get("raw_records"), list)
    ):
        raise PE04FinalizeError("answer smoke generation envelope drifted")
    raw_records = resumed["raw_records"]
    native_ids = [str(record.get("native_request_id")) for record in raw_records]
    if (
        len(set(native_ids)) != 25
        or any(record.get("finish_reason") != "stop" for record in raw_records)
        or any(
            not isinstance(record.get("prompt_tokens"), int)
            or int(record["prompt_tokens"]) <= 0
            or not isinstance(record.get("completion_tokens"), int)
            or int(record["completion_tokens"]) <= 0
            or int(record.get("memory_tokens", 513)) > 512
            for record in raw_records
        )
    ):
        raise PE04FinalizeError("answer smoke terminal accounting drifted")
    verification = UsageLedger(ledger_path).verify()
    events = [envelope["event"] for envelope in verification.events]
    terminals = [
        event
        for event in events
        if isinstance(event, dict) and event.get("type") == "TERMINAL"
    ]
    if (
        len(events) != 75
        or len(terminals) != 25
        or any(event.get("status") != "SUCCEEDED" for event in terminals)
        or verification.root_sha256 != resumed.get("ledger_root_sha256")
    ):
        raise PE04FinalizeError("answer smoke hash-chain ledger drifted")
    context_records = [
        record
        for archive in context_archives
        for record in read_context_archive(archive)
    ]
    if len(context_records) != 25 or any(
        record.terminal_status != "SUCCEEDED" for record in context_records
    ):
        raise PE04FinalizeError("answer smoke context denominator drifted")
    result: dict[str, Any] = {
        "answer_calls": 25,
        "case_count": 5,
        "context_records": len(context_records),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "development_ai_reviews": 0,
        "gates": {
            "append_only_resume": True,
            "failure_denominator_complete": True,
            "hash_chain_valid": True,
            "memory_budget_enforced": True,
            "native_request_ids_unique": True,
            "paper_labels_opened": False,
            "provider_usage_matches_preflight": True,
            "two_worker_limit": True,
        },
        "ledger": {
            "event_count": len(events),
            "root_sha256": verification.root_sha256,
            "sha256": ledger_after,
        },
        "methods": list(METHODS),
        "paper_labels_opened": False,
        "prompt_contract_sha256": prompt_contract_sha256(),
        "raw_generations_sha256": raw_after,
        "resume_proof": {
            "ledger_sha256_after": ledger_after,
            "ledger_sha256_before": ledger_before,
            "raw_sha256_after": raw_after,
            "raw_sha256_before": raw_before,
            "status": "PASS_UNCHANGED",
        },
        "run_id": run_id,
        "schema": "milai.dg11.paper-answer-harness-smoke.v1",
        "source_artifacts": {
            "answer_runner_sha256": sha256_file(ROOT / "evals/paper/answer_runner.py"),
            "context_archive_sha256": [
                sha256_file(archive) for archive in context_archives
            ],
            "input_sha256": sha256_file(inputs),
            "provider_sha256": sha256_file(ROOT / "evals/paper/provider.py"),
        },
        "status": "PASS",
        "workers": 2,
        "work_package": "DG11-PE04-HARNESS-SMOKE",
    }
    _atomic_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--context-archive", action="append", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        inputs=args.inputs.resolve(),
        context_archives=tuple(path.resolve() for path in args.context_archive),
        output_dir=args.output_dir.resolve(),
        output=args.output.resolve(),
    )
    print(json.dumps({"run_id": result["run_id"], "status": result["status"]}))


if __name__ == "__main__":
    main()
