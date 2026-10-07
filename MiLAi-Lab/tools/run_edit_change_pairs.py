"""Run exposed change diagnostics from four original actual-before states.

Preparation is offline; execute preserves the original extraction-only protocol.
Compare runs both common recipes on separate copies of each prepared bank using
the existing serial lease, continuous ledger, editor and Reader. New diagnostic
attempts never overwrite the original baseline or prepared states.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, cast

from jsonschema.exceptions import ValidationError as SchemaError
from langgraph.store.sqlite import SqliteStore
from pydantic import ValidationError
from transformers import AutoTokenizer

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_maintenance import MaintenanceRecipe, maintain_event
from milai_lab.methods.edit_memory import EditMemory
from milai_lab.runners.edit_benchmarks import BenchmarkRun, parse_object

ORDINALS = (3, 6, 7, 4)


def service_for(store: SqliteStore, path: Path, owner: str, retriever: Any = None) -> MemoryService:
    return MemoryService(
        store,
        ("edit", "B0", "B0", owner),
        owner,
        path / "memory.lock",
        mutation_contract="event_bound_v1",
        candidate_contract="read_handle_v1",
        semantic_retriever=retriever,
    )


def bind(service: MemoryService, case: dict[str, Any]) -> list[str]:
    refs = list(dict.fromkeys(s["source_ref"] for s in case["delivery"]["sources"]))
    service.bind_source_boundary(case["session"], f"change-pair:{case['ordinal']}", refs)
    return refs


def prepare(baseline: Path, prepared: Path, config: Path, source_version: str) -> None:
    if prepared.exists() or config.exists():
        raise ValueError("Preserve prior preparation; use new output and config paths")
    settings = read_json(baseline / "actual-config.json")
    owner = settings["halumem"]["users"][0]
    settings["experiment_name"] = "milai-post87c-four-actual-before-change-pairs"
    settings["provenance"] = {
        "status": "PREPARED_NOT_ADMITTED",
        "source_commit": source_version,
        "original_source_commit": "072af2e38507ad8593afab66c10e3400591534d0",
        "declaration": "milai-post87c-change-extraction-paired-development-20261007.json",
        "purpose": "four independently cloned actual B0 before states, one extraction then editor",
    }
    projection = BenchmarkRun.__new__(BenchmarkRun)
    projection.settings = settings
    projection.tokenizer = AutoTokenizer.from_pretrained(
        settings["tokenizer_path"], local_files_only=True
    )
    cases = []
    for ordinal in ORDINALS:
        path = prepared / str(ordinal)
        path.mkdir(parents=True)
        original = baseline / "maintenance/halumem" / owner / str(ordinal) / "batch-0000"
        before = read_json(original / "before.json")
        delivery = read_json(original / "delivery.json")
        http = read_json(baseline / "http/halumem" / owner / str(ordinal) / "writer/0/request.json")
        payload = json.loads(http["messages"][1]["content"])
        with (
            sqlite3.connect(
                f"file:{baseline / 'banks' / owner / 'memory.sqlite'}?mode=ro", uri=True
            ) as source,
            sqlite3.connect(path / "memory.sqlite") as dest,
        ):
            source.backup(dest)
        with SqliteStore.from_conn_string(str(path / "memory.sqlite")) as store:
            service = service_for(store, path, owner)
            # Restore ONLY actual, immutable historical values on the independent copy.
            # Future revisions/creation receipts must not affect the diagnostic.
            wanted = {r["id"]: r["value"] for r in before}
            for row in service.records():
                if row["id"] not in wanted:
                    store.delete(service.namespace, row["id"])
                    continue
                value = wanted[row["id"]]
                raw = copy.deepcopy(store.get(service.namespace, row["id"]).value)
                metadata = raw["_v13_1"]
                assert value in metadata["history"]
                metadata["history"] = [
                    v for v in metadata["history"] if v["revision"] <= value["revision"]
                ]
                metadata["current"] = copy.deepcopy(value)
                metadata["revision"] = value["revision"]
                metadata["proposals"] = {
                    k: v
                    for k, v in metadata["proposals"].items()
                    if v["receipt"].get("revision", 0) <= value["revision"]
                }
                raw["content"] = value["content"]
                store.put(service.namespace, row["id"], raw, index=False)
            actual = {r["id"]: r["value"] for r in service.records()}
            assert actual == wanted
            session = service.source(delivery["sources"][0]["source_ref"])["session"]
            method = EditMemory(
                service,
                "B0",
                interface_version="I2",
                features=EditFeatures.from_settings(settings["edit_features"]),
            )
            extraction = method.change_request(delivery, payload["observed_date"])
            assert all(
                e["delivery_kind"] == "current"
                for e in json.loads(extraction["messages"][1]["content"])["delivery"]["evidence"]
            )
            tokens = projection.input_tokens(extraction["messages"])
            assert projection._fits(extraction["messages"])
            evaluation = read_json(
                baseline / "evaluation/halumem" / owner / str(ordinal) / "complete.json"
            )
            # Question only, read AFTER maintenance. No gold answer/reference enters either model.
            questions = [q["question"] for q in evaluation["prediction"]["questions"]]
            case = {
                "ordinal": ordinal,
                "owner": owner,
                "path": str(path),
                "session": session,
                "date": payload["observed_date"],
                "delivery": delivery,
                "extraction": extraction,
                "extraction_input_tokens": tokens,
                "before_records": len(before),
                "questions": questions,
                "original_input_tokens": http["prompt_tokens"],
                "baseline_proposals": read_json(original / "proposals.json"),
            }
            write_json(path / "before.json", before)
            write_json(path / "input.json", case)
            cases.append(case)
    write_json(config, settings)
    write_json(
        prepared / "inputs.json",
        {"status": "PREPARED_NOT_ADMITTED", "cases": cases, "additional_model_calls": 0},
    )
    print(
        json.dumps(
            {
                "status": "PREPARED_NOT_ADMITTED",
                "model_calls": 0,
                "cases": [
                    {
                        "ordinal": c["ordinal"],
                        "before_records": c["before_records"],
                        "extraction_input_tokens": c["extraction_input_tokens"],
                        "original_questions": len(c["questions"]),
                    }
                    for c in cases
                ],
            }
        ),
        flush=True,
    )


def execute(prepared: Path, config: Path, output: Path) -> None:
    settings = read_json(config)
    assert settings["provenance"]["status"] == "ADMITTED_OWN_FAST_SERIAL_LEASE_AVAILABLE"
    assert settings["provenance"]["own_Fast"]["conclusion"] == "success"
    assert not output.exists()
    cases = read_json(prepared / "inputs.json")["cases"]
    assert [c["ordinal"] for c in cases] == list(ORDINALS)
    run = BenchmarkRun(settings, output)  # Existing serial lease and continuous ledger.
    write_json(
        output / "process.json",
        {
            "pid": os.getpid(),
            "status": "RUNNING_CHANGE_PAIRS",
            "source_commit": settings["provenance"]["source_commit"],
        },
    )
    rows = []
    status = "STOPPED_CHANGE_PAIRS"
    try:
        for case in cases:
            ordinal, path = case["ordinal"], Path(case["path"])
            folder = output / "cases" / str(ordinal)
            with SqliteStore.from_conn_string(str(path / "memory.sqlite")) as store:
                service = service_for(store, path, case["owner"], run._semantic_retriever())
                before = service.records()
                assert {r["id"]: r["value"] for r in before} == {
                    r["id"]: r["value"] for r in read_json(path / "before.json")
                }
                refs = bind(service, case)
                method = EditMemory(
                    service,
                    "B0",
                    interface_version="I2",
                    features=EditFeatures.from_settings(settings["edit_features"]),
                )
                extraction = case["extraction"]
                stage, failure, receipts = "extract", None, []
                try:
                    result = run.call(
                        f"pairs/{ordinal}/extract",
                        extraction["messages"],
                        structured=True,
                        response_format={
                            "type": "json_schema",
                            "json_schema": {
                                "name": "milai_changes",
                                "schema": extraction["schema"],
                            },
                        },
                    )
                    envelope = parse_object(result, reject_duplicate_keys=True)
                    write_json(folder / "extraction-envelope.json", envelope)
                    changes = method.decode_changes(envelope, extraction)
                    write_json(folder / "change-candidates.json", changes)
                    query = method.changes_query(
                        changes, "\n".join(s["text"] for s in case["delivery"]["sources"])
                    )
                    stage = "locate"
                    selected = service.search(
                        query, limit=settings["retrieval_limit"], include_raw=False
                    )["records"]
                    delivery = method.prepare(
                        refs,
                        query,
                        source_ranges=[
                            {k: s[k] for k in ("source_ref", "start", "end")}
                            for s in case["delivery"]["sources"]
                        ],
                        selected_records=selected,
                        redelivered_ranges=[],
                    )
                    for new, old in zip(
                        delivery["sources"], case["delivery"]["sources"], strict=True
                    ):
                        if "timestamp" in old:
                            new["timestamp"] = old["timestamp"]
                    subset, support_plan = run._old_support_plan(
                        method, delivery, delivery["records"], case["date"], allow_create=True
                    )
                    view = method.writer_request(subset, request_id=f"change-pair:{ordinal}")
                    hints = method.writer_changes(changes, view["mapping"])
                    messages = run._edit_messages(
                        method,
                        view["packet"],
                        case["date"],
                        allow_create=True,
                        schema=view["schema"],
                        change_candidates=hints,
                    )
                    write_json(folder / "writer-view.json", view)
                    write_json(folder / "delivery.json", subset)
                    write_json(folder / "old-support-plan.json", support_plan)
                    stage = "edit"
                    result = run.call(
                        f"pairs/{ordinal}/writer",
                        messages,
                        structured=True,
                        response_format={
                            "type": "json_schema",
                            "json_schema": {"name": "milai_edit_b0", "schema": view["schema"]},
                        },
                    )
                    envelope = parse_object(result, reject_duplicate_keys=True)
                    write_json(folder / "writer-envelope.json", envelope)
                    proposals = method.envelope_proposals(envelope, view["mapping"])
                    for i, proposal in enumerate(proposals):
                        try:
                            decoded = method.decode_proposal(proposal, view["mapping"])
                            receipt = method.apply(
                                case["session"], f"change-pair:{ordinal}:{i}", decoded
                            )
                        except (ValidationError, FunctionalRejection) as error:
                            receipt = {
                                "ok": False,
                                "reason": type(error).__name__ + ": " + str(error),
                            }
                        receipts.append(receipt)
                        write_json(folder / f"receipt-{i}.json", receipt)
                except (ValueError, ValidationError, SchemaError, FunctionalRejection) as error:
                    failure = {"stage": stage, "type": type(error).__name__, "message": str(error)}
                    write_json(folder / "first-failure.json", failure)
                after = service.records()
                answers = []
                for i, question in enumerate(case["questions"]):
                    try:
                        answer = run.answer(
                            service, question, case["date"], f"pairs/{ordinal}/QA/{i}"
                        )
                        answers.append({"question": question, "answer": answer})
                    except ValueError as error:
                        answers.append({"question": question, "first_failure": str(error)})
                    write_json(folder / "answers.json", answers)
                row = {
                    "ordinal": ordinal,
                    "before": before,
                    "after": after,
                    "receipts": receipts,
                    "failure": failure,
                    "answers": answers,
                }
                rows.append(row)
                write_json(output / "actual-behavior.json", rows)
        status = "COMPLETED_FIRST_ATTEMPT_PAIRS_AWAITING_ROOT_REVIEW"
    finally:
        run.close()
        end = read_json(output / "accounting-end.json")
        terminal = {
            "status": status,
            "case_rows": len(rows),
            "source_commit": settings["provenance"]["source_commit"],
            "generation_requests": end["generation_requests"] - run.before["generation_requests"],
            "generation_known_tokens": end["generation"]["known_tokens"]
            - run.before["generation"]["known_tokens"],
            "new_generation_unknown": end["generation"]["unknown_usage"]
            - run.before["generation"]["unknown_usage"],
            "embedding_known_tokens": end["embedding"]["known_tokens"]
            - run.before["embedding"]["known_tokens"],
        }
        write_json(output / "terminal.json", terminal)
        print(json.dumps(terminal), flush=True)


def compare_recipes(prepared: Path, config: Path, output: Path, source_version: str) -> None:
    """Compare both common recipes from independent copies of each actual before bank."""
    if output.exists():
        raise ValueError("Preserve prior comparison; use a new output directory")
    cases = read_json(prepared / "inputs.json")["cases"]
    if [case["ordinal"] for case in cases] != list(ORDINALS):
        raise ValueError("Expected the four original exposed cases in their declared order")
    original = read_json(config)
    for recipe in ("single_pass", "extract_then_edit"):
        settings = copy.deepcopy(original)
        settings.update(
            experiment_name="milai-build-first-recipe-pairs-" + recipe,
            config_version="milai-build-first-recipe-pairs-v1", maintenance_recipe=recipe,
        )
        settings["provenance"] = {
            "source_commit": source_version,
            "original_source_commit": original["provenance"]["original_source_commit"],
            "prepared_inputs": str(prepared),
            "purpose": "same original sources, actual before states and editor; recipe contrast",
            "claim": "four exposed development cases, not independent confirmation",
        }
        root = output / recipe
        run = BenchmarkRun(settings, root)
        rows = []
        status = "STOPPED_RECIPE_COMPARISON"
        try:
            for case in cases:
                ordinal = case["ordinal"]
                source_bank = prepared / str(ordinal) / "memory.sqlite"
                folder = root / "cases" / str(ordinal)
                folder.mkdir(parents=True)
                with (
                    sqlite3.connect(
                        source_bank.resolve().as_uri() + "?mode=ro", uri=True
                    ) as source,
                    sqlite3.connect(folder / "memory.sqlite") as destination,
                ):
                    source.backup(destination)
                with SqliteStore.from_conn_string(str(folder / "memory.sqlite")) as store:
                    service = service_for(store, folder, case["owner"], run._semantic_retriever())
                    before = service.records()
                    expected = read_json(prepared / str(ordinal) / "before.json")
                    if {r["id"]: r["value"] for r in before} != {
                        r["id"]: r["value"] for r in expected
                    }:
                        raise ValueError("Prepared bank changed from its original actual before")
                    bind(service, case)
                    method = EditMemory(service, "B0", interface_version="I2",
                                        features=EditFeatures.from_settings(settings["edit_features"]))

                    def call(
                        stage: str, messages: list[dict[str, str]], schema: dict[str, Any],
                        execution: BenchmarkRun = run, pair: int = ordinal,
                    ) -> dict[str, Any]:
                        return parse_object(execution.call(
                            f"pairs/{pair}/{stage}", messages, structured=True,
                            response_format={"type": "json_schema", "json_schema": {
                                "name": "milai_" + stage, "schema": schema}},
                        ), reject_duplicate_keys=True)

                    def prepare_delivery(
                        delivery: dict[str, Any], execution: BenchmarkRun = run,
                        editor: EditMemory = method, date: str = case["date"],
                    ) -> dict[str, Any]:
                        return execution._old_support_plan(
                            editor, delivery, delivery["records"], date, allow_create=True
                        )[0]

                    result = maintain_event(
                        method, case["delivery"], session=case["session"],
                        request_id=f"recipe-pair:{ordinal}", date=case["date"],
                        recipe=cast(MaintenanceRecipe, recipe), model_call=call,
                        retrieval_limit=settings["retrieval_limit"], fit=run._fits,
                        prepare_delivery=prepare_delivery,
                    )
                    row: dict[str, Any] = {
                        "ordinal": ordinal, "before": before, "after": service.records(),
                        "maintenance": result, "answers": [],
                    }
                    write_json(folder / "result.json", row)
                    for index, question in enumerate(case["questions"]):
                        try:
                            answer = run.answer(
                                service, question, case["date"], f"pairs/{ordinal}/QA/{index}"
                            )
                            row["answers"].append({"question": question, "answer": answer})
                        except ValueError as error:
                            row["answers"].append({
                                "question": question, "first_failure": str(error)})
                        write_json(folder / "result.json", row)
                    rows.append(row)
                    write_json(root / "actual-behavior.json", rows)
            status = "COMPLETED_FIRST_ATTEMPT_PAIRS_AWAITING_ROOT_REVIEW"
        finally:
            run.close()
            end = read_json(root / "accounting-end.json")
            write_json(root / "terminal.json", {
                "status": status, "recipe": recipe, "case_rows": len(rows),
                "source_commit": source_version,
                "generation_requests": end["generation_requests"]
                - run.before["generation_requests"],
                "generation_known_tokens": end["generation"]["known_tokens"]
                - run.before["generation"]["known_tokens"],
                "new_generation_unknown": end["generation"]["unknown_usage"]
                - run.before["generation"]["unknown_usage"],
                "embedding_known_tokens": end["embedding"]["known_tokens"]
                - run.before["embedding"]["known_tokens"],
            })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prepare_parser = commands.add_parser("prepare", help="Clone actual before states without HTTP")
    prepare_parser.add_argument("original", type=Path, help="Closed original B0 arm directory")
    prepare_parser.add_argument("prepared", type=Path, help="New independent input directory")
    prepare_parser.add_argument("config", type=Path, help="New private prepared config")
    prepare_parser.add_argument("--source-version", required=True)
    execute_parser = commands.add_parser("execute", help="Run admitted first-attempt pairs")
    execute_parser.add_argument("prepared", type=Path)
    execute_parser.add_argument("config", type=Path, help="Reviewed, admitted private config")
    execute_parser.add_argument("output", type=Path, help="New actual run directory")
    compare_parser = commands.add_parser("compare", help="Compare common recipes from equal states")
    compare_parser.add_argument("prepared", type=Path)
    compare_parser.add_argument("config", type=Path)
    compare_parser.add_argument("output", type=Path, help="New isolated comparison directory")
    compare_parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.original, args.prepared, args.config, args.source_version)
    elif args.action == "execute":
        execute(args.prepared, args.config, args.output)
    else:
        compare_recipes(args.prepared, args.config, args.output, args.source_version)


if __name__ == "__main__":
    main()
