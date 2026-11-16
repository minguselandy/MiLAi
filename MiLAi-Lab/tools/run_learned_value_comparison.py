"""Compare fixed top-k and learned selection on actual saved Source pools.

All predictions precede first scoring. The final Reader is identical; selectors
never receive reference answers or outcome labels. Model files are cross-fitted
without the evaluated question. This remains an exposed-pool mechanism study.
"""

from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

from transformers import AutoTokenizer

from milai_lab.analysis.edit_official import LongMemEvalOfficial
from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.datasets.edit_benchmarks import longmemeval_cases
from milai_lab.harness.artifact_io import configure_runtime_directory, read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import (
    SOURCE_REUSE_INSTRUCTIONS,
    admit_pack_indices,
    open_evidence_packs,
    pack_coverage,
    project_packs,
)
from milai_lab.methods.learned_evidence_value import LearnedValue, select_by_return
from milai_lab.runners.edit_benchmarks import BenchmarkRun, reader_messages
from milai_lab.runners.evidence_replay import _copied_bank
from milai_lab.runners.method_architecture_diagnostic import diagnostic_costs
from prepare_evidence_value_transitions import pack_intervals


def source_context_indices(materials):
    """Keep the first retrieved alias of each identical actual parent Source range."""
    seen, indices = set(), []
    for index, item in enumerate(materials):
        if item["kind"] != "original_source":
            continue
        intervals = pack_intervals(item, True)
        if intervals and intervals not in seen:
            seen.add(intervals)
            indices.append(index)
    return indices


class SelectionRun:
    """The shared token counter without constructing a provider or budget client."""

    input_tokens = BenchmarkRun.input_tokens
    stage_thinking = BenchmarkRun.stage_thinking

    def __init__(self, settings, root, tokenizer):
        self.settings, self.root, self.tokenizer = settings, root, tokenizer
        self.ranker_tokenizer = None


def run_case(execution, case, protocol, arm, phase):
    started, cpu_started = time.perf_counter(), time.process_time()
    qid = case["question_id"]
    prepared = read_json(Path(protocol["prepared_inputs"][qid]))
    original = read_json(Path(prepared["source_execution"]) / "protocol.json")
    source = Path(original["source_run"])
    settings = read_json(source / "actual-config.json")
    bank_id = settings["alignment_bank_ids"][qid]
    bank = execution.root / "banks" / qid
    if phase == "select":
        _copied_bank(source / "banks" / bank_id / "memory.sqlite", bank / "memory.sqlite")
    materials = read_json(source / "native/longmemeval" / qid / "answer/retrieval.json")[
        "materials"
    ]
    candidates = source_context_indices(materials)
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(
            store,
            ("edit", source.name, "ordinary", bank_id, qid),
            qid,
            bank / "memory.lock",
            functional_contract="functional_v1",
            memory_profile=settings["memory_profile"],
            memory_ranking=settings["memory_ranking"],
        )
        cache = {}

        def opened(indices, *, fresh=False):
            if fresh:
                return [
                    open_evidence_packs(service, [materials[i]], expand_context=True)[0]
                    for i in indices
                ]
            for index in indices:
                if index not in cache:
                    cache[index] = open_evidence_packs(
                        service, [materials[index]], expand_context=True
                    )[0]
            return [cache[index] for index in indices]

        def messages(indices, *, fresh=False):
            bodies = opened(indices, fresh=fresh)
            value = reader_messages(
                case["question"],
                case["question_date"],
                project_packs(bodies, indices),
                memory_view="source_history",
            )
            value[0]["content"] += "\n" + SOURCE_REUSE_INSTRUCTIONS
            payload = json.loads(value[1]["content"])
            payload["source_coverage"] = pack_coverage(materials, bodies)
            value[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            return value

        def measure(indices):
            return execution.input_tokens(
                messages(indices), enable_thinking=execution.stage_thinking("reader")
            )

        if phase == "select":
            limit = (
                execution.settings["context_tokens"]
                - execution.settings["model"]["max_tokens"]
                - 512
            )
            if arm in {"top1", "top2"}:
                count = 1 if arm == "top1" else 2
                decision = admit_pack_indices(
                    candidates[:count], lambda indices: measure(indices) <= limit
                )
                selected = decision["admitted_indices"]
            else:
                model_path = Path(protocol["crossquery_models"]) / qid / "conditional.json"
                model = LearnedValue.from_json(read_json(model_path))
                decision = select_by_return(
                    candidates,
                    payload_for=lambda indices: json.loads(messages(indices)[1]["content"]),
                    measure=measure,
                    predict_return=lambda payload: model.predict(payload)["answer_return"],
                    input_limit=limit,
                    pair_width=protocol["pair_width"] if arm == "value_bundle" else 0,
                )
                selected = decision["selected_indices"]
                decision["model_path"] = str(model_path)
            decision.update(
                selected_indices=selected,
                candidate_contexts=len(candidates),
                source_contexts_opened_for_selection=len(cache),
                total_selection_wall_seconds=time.perf_counter() - started,
                total_selection_cpu_seconds=time.process_time() - cpu_started,
                reading_scope=(
                    "Selection may inspect full Source bodies locally. Final Reader receives "
                    "only chosen original contexts, reopened under current visibility."
                ),
            )
            write_json(execution.root / "selections" / f"{qid}.json", decision)
            return {
                "question_id": qid,
                "method": arm,
                "selected_indices": selected,
                "model_http_calls": 0,
            }
        selected = read_json(execution.root / "selections" / f"{qid}.json")["selected_indices"]
        key = f"longmemeval/{qid}/answer"
        failure = None
        try:
            answer = execution.call(
                key,
                messages(selected, fresh=True),
                structured=False,
                enable_thinking=execution.stage_thinking("reader"),
            )
        except ValueError as error:
            failure = execution._known_reader_failure(
                error, key, policy="record_known_readonly_failure"
            )
            if failure is None:
                raise
            answer = None
        return {
            "question_id": qid,
            "method": arm,
            "hypothesis": answer,
            "selected_indices": selected,
            "reader_failure": failure,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--phase", choices=("select", "predict", "score"), required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    configure_runtime_directory(args.runtime_dir)
    protocol = read_json(args.protocol)
    base = read_json(Path(protocol["settings"]))
    cases = longmemeval_cases(Path(base["longmemeval"]["path"]), protocol["questions"])
    tokenizer = (
        AutoTokenizer.from_pretrained(base["tokenizer_path"], local_files_only=True)
        if args.phase == "select"
        else None
    )
    official = (
        LongMemEvalOfficial(Path(base["longmemeval"]["official_checkout"]))
        if args.phase == "score"
        else None
    )
    all_results = {}
    for arm in protocol["methods"]:
        settings = copy.deepcopy(base)
        settings.update(
            experiment_name=f"{protocol['name']}-{arm}", config_version=f"{protocol['name']}-{arm}"
        )
        execution = (
            SelectionRun(settings, args.output / arm, tokenizer)
            if args.phase == "select"
            else BenchmarkRun(settings, args.output / arm)
        )
        try:
            if args.phase in {"select", "predict"}:
                rows = []
                output = execution.root / (
                    "selection-results.json" if args.phase == "select" else "results.json"
                )
                for case in cases:
                    rows.append(run_case(execution, case, protocol, arm, args.phase))
                    write_json(output, {"status": args.phase.upper() + "ING", "rows": rows})
                    print(
                        json.dumps(
                            {"phase": args.phase, "method": arm, "question_id": case["question_id"]}
                        ),
                        flush=True,
                    )
                write_json(
                    output,
                    {
                        "status": (
                            "SELECTIONS_SAVED" if args.phase == "select" else "PREDICTIONS_SAVED"
                        ),
                        "rows": rows,
                    },
                )
                all_results[arm] = rows
            else:
                rows = read_json(execution.root / "results.json")["rows"]
                by_id = {case["question_id"]: case for case in cases}
                for row in rows:
                    if row["hypothesis"] is not None:
                        verdict = execution.call(
                            f"longmemeval/{row['question_id']}/judge",
                            [
                                {
                                    "role": "user",
                                    "content": official.make_prompt(
                                        by_id[row["question_id"]], row["hypothesis"]
                                    ),
                                }
                            ],
                            structured=False,
                            enable_thinking=execution.stage_thinking("reader"),
                        )
                        row.update(first_verdict=verdict, correct=official.label(verdict))
                    write_json(execution.root / "results.json", {"status": "SCORING", "rows": rows})
                write_json(execution.root / "results.json", {"status": "COMPLETED", "rows": rows})
                all_results[arm] = rows
        finally:
            if args.phase != "select":
                execution.close()
    result = {
        "status": "COMPLETED",
        "phase": args.phase,
        "methods": all_results,
        "scope": protocol["scope"],
        "parameter_updates": 0,
        "source_mutations": 0,
    }
    if args.phase == "score":
        result["costs"] = {arm: diagnostic_costs(args.output / arm) for arm in protocol["methods"]}
        write_json(args.output / "results.json", result)
    write_json(args.output / f"{args.phase}-terminal.json", result)


if __name__ == "__main__":
    main()
