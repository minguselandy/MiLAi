"""Measure outcomes of declared source subsets with one identical final Reader.

This is offline supervision/diagnosis on an exposed saved pool. It never forms
memory, searches for new sources, supplies gold to the Reader or regrades old answers.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai_lab.analysis.edit_official import LongMemEvalOfficial
from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.datasets.edit_benchmarks import longmemeval_cases
from milai_lab.harness.artifact_io import configure_runtime_directory, read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import (
    SOURCE_REUSE_INSTRUCTIONS,
    open_evidence_packs,
    pack_coverage,
    project_packs,
)
from milai_lab.runners.edit_benchmarks import BenchmarkRun, reader_messages
from milai_lab.runners.evidence_replay import _copied_bank
from milai_lab.runners.method_architecture_diagnostic import diagnostic_costs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    configure_runtime_directory(args.runtime_dir)
    protocol = read_json(args.config)
    source = Path(protocol["source_run"])
    settings = read_json(source / "actual-config.json")
    original_settings = dict(settings)
    settings.update(experiment_name=protocol["name"], config_version=protocol["name"])
    settings.pop("query_structure_policy", None)
    settings["evidence_selection_policy"] = "standard"
    question_id = protocol["question_id"]
    reference = longmemeval_cases(Path(settings["longmemeval"]["path"]), [question_id])[0]
    snapshot = read_json(source / "native" / "longmemeval" / question_id / "answer/retrieval.json")
    materials = snapshot["materials"]
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "protocol.json", protocol)
    bank = args.output / "bank"
    bank_id = original_settings["alignment_bank_ids"][question_id]
    _copied_bank(source / "banks" / bank_id / "memory.sqlite", bank / "memory.sqlite")
    execution = BenchmarkRun(settings, args.output)
    official = LongMemEvalOfficial(Path(settings["longmemeval"]["official_checkout"]))
    results = []
    try:
        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
            service = MemoryService(store,
                ("edit", source.name, "ordinary", bank_id, question_id), question_id,
                bank / "memory.lock", functional_contract="functional_v1",
                memory_profile=original_settings["memory_profile"],
                memory_ranking=original_settings["memory_ranking"])
            for condition in protocol["conditions"]:
                name, indices = condition["name"], condition["indices"]
                expanded = condition["expand_context"]
                opened = [open_evidence_packs(service, [materials[index]],
                                              expand_context=index in expanded)[0]
                          for index in indices]
                messages = reader_messages(reference["question"], reference["question_date"],
                    project_packs(opened, indices), memory_view="source_history")
                messages[0]["content"] += "\n" + SOURCE_REUSE_INSTRUCTIONS
                payload = json.loads(messages[1]["content"])
                payload["source_coverage"] = pack_coverage(materials, opened)
                messages[1]["content"] = json.dumps(payload, ensure_ascii=False,
                                                     separators=(",", ":"))
                key = f"longmemeval/{question_id}:{name}/answer"
                failure = None
                try:
                    answer = execution.call(key, messages, structured=False,
                                             enable_thinking=execution.stage_thinking("reader"))
                except ValueError as error:
                    failure = execution._known_reader_failure(
                        error, key, policy="record_known_readonly_failure")
                    if failure is None:
                        raise
                    answer = None
                row = {"condition": name, "question_id": question_id, "indices": indices,
                    "expand_context": expanded, "hypothesis": answer,
                    "source_intervals": sorted({(span["source_ref"], span["source_revision"],
                        span["start"], span["end"]) for item in opened
                        for span in item.get("source_ranges", [])}),
                    "reader_failure": failure}
                if answer is not None:
                    verdict = execution.call(f"longmemeval/{question_id}:{name}/judge",
                        [{"role": "user", "content": official.make_prompt(reference, answer)}],
                        structured=False, enable_thinking=execution.stage_thinking("reader"))
                    row.update(first_verdict=verdict, correct=official.label(verdict))
                results.append(row)
                write_json(args.output / "results.json", {"status": "RUNNING", "results": results})
    finally:
        execution.close()
    write_json(args.output / "results.json", {"status": "COMPLETED", "results": results,
        "costs": diagnostic_costs(args.output), "parameter_updates": 0,
        "scope": "One exposed query, nominated subsets and actual common-Reader outcomes. "
                 "Source choices are offline supervision, never main-method results."})


if __name__ == "__main__":
    main()
