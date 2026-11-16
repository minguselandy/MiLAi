"""Seed the complete released InstructIR corpus into the existing source Store."""
from __future__ import annotations

import argparse
import json
import os
import resource
import time
from pathlib import Path
from typing import Any

from milai_lab.datasets.instructir import corpus_sources
from milai_lab.harness.artifact_io import write_json
from milai_lab.runners.functional import frozen, prepare
from milai_lab.runners.retrieval_histories import prepare_history_bank


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {"status": "PREPARING", "pid": os.getpid(),
        "source_version": args.source_version,
        "source_corpus": str(args.corpus.resolve()), "captured_sources": 0,
        "bank": "released-corpus", "owner": "instructir-evaluation",
        "model_calls": 0, "queries_loaded": 0, "qrels_loaded": 0, "ledger_recorded": False}
    write_json(args.output / "preparation.json", report)

    def progress(completed: int) -> None:
        report["captured_sources"] = completed
        if completed % 100 == 0 or completed == report["planned_sources"]:
            write_json(args.output / "preparation.json", report)
            print(json.dumps({"captured_sources": completed,
                              "planned_sources": report["planned_sources"]}), flush=True)

    try:
        rows = [json.loads(line) for line in args.corpus.read_text().splitlines()]
        public = corpus_sources(rows)
        report["planned_sources"] = len(public)
        template = args.output / "template"
        prepare(template, args.config, source_version=args.source_version)
        report["ledger"] = frozen(template)["config"]["budget_path"]
        report["namespace_id"] = frozen(template)["run_id"]
        setup = prepare_history_bank(template, bank=report["bank"], owner=report["owner"],
            history={"source_group": "instructir-released-common-corpus", "sources": public},
            source_progress=progress)
        mapping = {row["receipt"]["source_ref"]: row["original_event_id"]
                   for row in setup["sources"]}
        if len(mapping) != len(public):
            raise ValueError("Each released document must have its own captured source")
        if setup["stored_records"]:
            raise ValueError("Corpus ingestion must not create semantic interpretations")
        write_json(args.output / "source-map.json", mapping)
        write_json(args.output / "source-setup.json", setup)
        report.update(status="COMPLETE_SOURCE_STORE", template=str(template.resolve()),
            namespace=frozen(template)["run_id"],
            template_bytes=sum(p.stat().st_size for p in template.rglob("*") if p.is_file()),
            source_documents=len(mapping), stored_semantic_records=0,
            scope="All corpus documents, full title/text, neutral handles and literal roles. "
                  "Native document IDs stay in the offline map. No query, qrel, ranking or model "
                  "run. Future query/arm isolation and scoring must be declared separately.")
    except BaseException as error:
        report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        report.update(wall_seconds=time.perf_counter() - started,
                      cpu_seconds=time.process_time() - cpu,
                      peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        write_json(args.output / "preparation.json", report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
