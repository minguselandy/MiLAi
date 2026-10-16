"""Profile one real HaluMem saved pool, replaying original replies without HTTP.

PYTHONPATH selects the implementation under measurement. Output is an offline
CPU comparison and exact message trace, never a fresh model-quality result.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace

from transformers import AutoTokenizer

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.runners.edit_benchmarks import BenchmarkRun
from milai_lab.runners.evidence_replay import _copied_bank


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_run", type=Path)
    parser.add_argument("key")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    settings = read_json(args.source_run / "actual-config.json")
    saved = read_json(args.source_run / "native" / args.key / "retrieval.json")
    first = next((args.source_run / "http" / args.key).rglob("request.json"))
    payload = json.loads(read_json(first)["messages"][1]["content"])
    owner = args.key.split("/")[1]
    bank = args.output / "bank"
    _copied_bank(args.source_run / "banks" / owner / "memory.sqlite", bank / "memory.sqlite")
    # Only the measured Reader functions and actual tokenizer are needed here.
    # No provider client or Budget is constructed and no model dispatch is possible.
    run = BenchmarkRun.__new__(BenchmarkRun)
    run.root, run.settings = args.output, settings
    run.client = SimpleNamespace(config=SimpleNamespace(max_calls=settings["model"]["max_calls"]))
    run.tokenizer = AutoTokenizer.from_pretrained(settings["tokenizer_path"], local_files_only=True)
    requests, measurements = [], 0

    def measure(messages, **kwargs):
        nonlocal measurements
        measurements += 1
        return BenchmarkRun.input_tokens(run, messages, **kwargs)

    def replay(key, messages, **kwargs):
        requests.append({"key": key, "messages": messages, "options": kwargs})
        return BenchmarkRun.completed_content(read_json(
            args.source_run / "http" / key / "response.json"))

    run.input_tokens = measure
    run.call = replay
    started, cpu_started = time.perf_counter(), time.process_time()
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(store,
            ("edit", args.source_run.name, settings["arm"], owner), owner, bank / "memory.lock",
            functional_contract="functional_v1", memory_profile=settings["memory_profile"],
            memory_ranking=settings["memory_ranking"])
        answer, _ = run.answer_material(payload["question"], payload["date"], args.key,
            saved["materials"], snapshot_id=f"native/{args.key}/retrieval.json",
            material_reader=lambda items: run._live_materials(service, items))
    result = {"status": "COMPLETED_OFFLINE_REPLAY", "model_http_calls": 0,
        "source_run": str(args.source_run), "key": args.key,
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_started,
        "token_measurements": measurements, "replayed_responses": len(requests),
        "answer": answer, "implementation": str(__import__(
            "milai_lab.methods.evidence_reading", fromlist=["read_question_pack"]).__file__),
        "scope": "Original replies reused only to traverse the read path. No fresh quality score."}
    write_json(args.output / "requests.json", requests)
    write_json(args.output / "result.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
