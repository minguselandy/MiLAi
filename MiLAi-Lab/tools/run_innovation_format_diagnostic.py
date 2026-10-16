"""Compare two native edit formats with identical demonstrations and actual empty source banks.

This opt-in diagnostic replaces both production prompts with one common semantic
task plus format instructions. It tests formation, not a full memory lifecycle.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from jsonschema import ValidationError  # type: ignore[import-untyped]

from innovation_learning_states import components
from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.harness.artifact_io import configure_runtime_directory, read_json, write_json
from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.methods.edit_features import compact_prompt_schema
from milai_lab.methods.edit_maintenance import parse_object
from milai_lab.methods.semantic_delta import compile_delta, indexed_target
from milai_lab.runners.edit_benchmarks import BenchmarkRun
from milai_lab.runners.method_architecture_diagnostic import _copy_bank, diagnostic_costs

COMMON = (
    "Maintain source-bound memory from the actual delivery and old state. Preserve each "
    "independently changeable fact, its subject, scope, time, uncertainty and attribution. "
    "Preserve unchanged units without restating them. A future change is different from a "
    "correction of earlier history. A report date alone is not an effective date. Missing "
    "evidence is unknown, not false. Shared prerequisites and alternative routes must retain "
    "their meanings; rules express source-supported implications, not premise truth. "
    "Plain self-contained claims are allowed when no relation is supported. "
    "Demonstrations are separate tasks: their facts and aliases do not enter the actual bank. "
    "Return only the actual task's JSON envelope following its response_schema. "
)
ENCODING = {
    "operations": (
        "Use creates and records. Creates contain create actions with clauses and optional "
        "support_groups; records are keyed by actual r aliases. Each clause has text, evidence, "
        "assertion and conditions. Existing edits use replace/append/retract with target_unit. "
        "Support group alternatives are OR of AND lists; generated create units use their "
        "zero-based positions. New matters can use the label Source claims."
    ),
    "delta": (
        "Use creates and changes. Creates contain nodes; changes keyed by r contain replace "
        "keyed by old u, append, withdraw and optional rules. Nodes contain text, basis and kind; "
        "also names additional source aliases. The service supplies labels and identities. "
        "Rules have target, all shared prerequisites and any alternative AND routes; new nodes "
        "use zero-based positions. any=[[]] requires only all; any=[] leaves no route."
    ),
}


def reference_target(row, role):
    if role == "delta":
        return indexed_target(row["delta_target"])
    target = {"creates": [], "records": {}}
    for proposal in compile_delta(row["delta_target"], row["mapping"]):
        if proposal["action"] == "create":
            target["creates"].append({**proposal, "matter": "Source claims"})
        else:
            proposal = copy.deepcopy(proposal)
            target["records"][proposal.pop("target")] = proposal
    return target


def matched_messages(role, demonstrations, payload):
    return [{"role": "system", "content": COMMON + ENCODING[role]},
            {"role": "user", "content": json.dumps({
                "demonstrations": [{"input": row["input"], "output": reference_target(row, role)}
                                   for row in demonstrations],
                "actual_task": payload,
            }, ensure_ascii=False, separators=(",", ":"))}]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    configure_runtime_directory(args.runtime_dir)
    protocol = read_json(args.config)
    settings = read_json(Path(protocol["model_config"]))["entrypoints"]["benchmark"]
    settings.update(experiment_name=protocol["name"], config_version=protocol["name"])
    settings["model"].update(max_tokens=2048, temperature=0, enable_thinking=False)
    references = {row["example_id"]: row
                  for line in Path(protocol["references"]).read_text().splitlines()
                  if line.strip() for row in [json.loads(line)]}
    demonstrations = [references[key] for key in protocol["example_ids"]]
    cases = read_json(Path(protocol["cases"]))["cases"]
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "protocol.json", protocol)
    run = BenchmarkRun(settings, args.output)
    results = []
    try:
        for role, mode in (("operations", "event_delta_v1"), ("delta", "semantic_delta_v2")):
            for case in cases:
                case_id = case["case_id"]
                bank = args.output / role / case_id
                bank.mkdir(parents=True)
                _copy_bank(Path(protocol["source_banks"]) / case_id / "memory.sqlite",
                           bank / "memory.sqlite")
                with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
                    service, method = components(store, bank, case_id, mode)
                    ref = service.event_id("evaluation", case_id, "user")
                    service.bind_public_turn("evaluation", case_id, ref,
                                             config_version="learning-eval-v1", phase="resume")
                    request_id = "format-" + case_id
                    view = method.writer_request(method.prepare([ref], "", selected_records=[]),
                                                 request_id=request_id)
                    payload = {"observed_date": case["reported_at"], "delivery": view["packet"],
                               "response_schema": compact_prompt_schema(view["schema"])}
                    messages = matched_messages(role, demonstrations, payload)
                    row = {"role": role, "case_id": case_id, "before": service.records(),
                           "receipts": []}
                    key = f"maintenance/{role}/{case_id}"
                    try:
                        content = run.call(key, messages, structured=True,
                            response_format={"type": "json_schema", "json_schema": {
                                "name": "milai_format_diagnostic", "schema": view["schema"]}},
                            enable_thinking=False)
                    except ValueError as error:
                        failure = run._known_reader_failure(
                            error, key, policy="record_known_readonly_failure")
                        if failure is None:
                            raise
                        row.update(status="generation_incomplete", failure=failure)
                    else:
                        try:
                            proposals = method.envelope_proposals(
                                parse_object(content, reject_duplicate_keys=True),
                                view["mapping"]["mapping_id"])
                            for index, proposal in enumerate(proposals):
                                row["receipts"].append(method.apply("evaluation",
                                    f"{role}:{case_id}:{index}", method.decode_proposal(
                                        proposal, view["mapping"]["mapping_id"])))
                            row["status"] = "no_change" if not proposals else (
                                "applied" if all(r["ok"] for r in row["receipts"]) else "rejected")
                        except (ValueError, KeyError, ValidationError,
                                FunctionalRejection) as error:
                            row.update(status="invalid_or_rejected", error=str(error))
                    row["after"] = service.records()
                    results.append(row)
                    write_json(args.output / "results.json",
                               {"status": "RUNNING", "results": results})
    finally:
        run.close()
    write_json(args.output / "results.json", {"status": "COMPLETED", "results": results,
        "costs": diagnostic_costs(args.output), "semantic_review": "pending",
        "scope": "Two formats, same two demonstrations and four exposed actual source banks. "
                 "Common prompt replaces both original prompts; not a full recipe comparison."})


if __name__ == "__main__":
    main()
