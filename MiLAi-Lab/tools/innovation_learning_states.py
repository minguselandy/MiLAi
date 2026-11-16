"""Prepare source-only or actual prior-state banks, then apply saved outputs to copies."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, cast

from jsonschema import ValidationError  # type: ignore[import-untyped]
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_maintenance import parse_object
from milai_lab.methods.edit_memory import EditMemory, MaintenanceMode
from milai_lab.runners.method_architecture_diagnostic import _copy_bank
from prepare_innovation_sft import WRAPPED_INSTRUCTIONS


def components(store: SqliteStore, root: Path, case_id: str,
               mode: MaintenanceMode = "semantic_delta_v1") -> tuple[MemoryService, EditMemory]:
    service = MemoryService(
        store,
        ("innovation-learning-eval", case_id),
        case_id,
        root / "memory.lock",
        functional_contract="functional_v1",
    )
    method = EditMemory(
        service,
        "M",
        interface_version="I2",
        maintenance_mode=mode,
        features=EditFeatures(
            matter_organization=True,
            semantic_operations=True,
            bound_references=True,
            source_metadata=True,
            temporal_scope=True,
            proposition_updates=True,
            dependency_groups=True,
            single_record_changes=True,
        ),
    )
    return service, method


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("root", type=Path)
    parser.add_argument("--phase", choices=("prepare", "apply"), required=True)
    parser.add_argument("--generations", type=Path)
    parser.add_argument("--interface", choices=("wrapped", "native"), default="wrapped")
    parser.add_argument("--maintenance-mode", choices=("semantic_delta_v1", "semantic_delta_v2"),
                        default="semantic_delta_v1")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())["cases"]
    args.root.mkdir(parents=True, exist_ok=True)
    if args.phase == "prepare":
        inputs = []
        for case in cases:
            case_id = case["case_id"]
            folder = args.root / "source-banks" / case_id
            folder.mkdir(parents=True)
            if "before_bank" in case:
                _copy_bank(Path(case["before_bank"]), folder / "memory.sqlite")
            with SqliteStore.from_conn_string(str(folder / "memory.sqlite")) as store:
                service, method = components(store, folder, case.get("bank_case_id", case_id),
                                              cast(MaintenanceMode, args.maintenance_mode))
                ref = service.capture_user(
                    "evaluation",
                    case_id,
                    case["source"],
                    occurred_at=case["reported_at"],
                    calendar_context="Asia/Shanghai",
                )["source_ref"]
                service.bind_public_turn(
                    "evaluation", case_id, ref, config_version="learning-eval-v1", phase="start"
                )
                before = service.records()
                delivery = method.prepare([ref], "", selected_records=before,
                    redelivered_ranges=method.target_support_ranges(before) if before else None)
                view = method.writer_request(delivery, request_id=case_id)
                payload = {
                    "observed_date": case["reported_at"],
                    "delivery": view["packet"],
                    "response_schema": view["schema"],
                    "counterfactuals": [],
                }
                messages = [
                    {"role": "system", "content": WRAPPED_INSTRUCTIONS},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    },
                ]
                if args.interface == "native":
                    messages = method.edit_messages(
                        view["packet"],
                        case["reported_at"],
                        allow_create=True,
                        schema=view["schema"],
                    )
                inputs.append(
                    {
                        "example_id": case_id,
                        "messages": messages,
                        "interface": args.interface,
                        "maintenance_mode": args.maintenance_mode,
                        "mapping_id": view["mapping"]["mapping_id"],
                        "actual_before": service.records(),
                        "before_bank": case.get("before_bank"),
                    }
                )
        (args.root / "inputs.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in inputs)
        )
        return
    assert args.generations is not None
    by_id = {case["case_id"]: case for case in cases}
    reports = []
    for path in sorted(args.generations.glob("*.json")):
        output = json.loads(path.read_text())
        objective = output["objective"]
        for row in output["sequences"]:
            case_id = row["example_id"]
            folder = args.root / "applied" / objective / case_id
            shutil.copytree(args.root / "source-banks" / case_id, folder)
            with SqliteStore.from_conn_string(str(folder / "memory.sqlite")) as store:
                service, method = components(store, folder,
                    by_id[case_id].get("bank_case_id", case_id),
                                              cast(MaintenanceMode, args.maintenance_mode))
                report: dict[str, Any] = {
                    "objective": objective,
                    "case_id": case_id,
                    "before": service.records(),
                    "receipts": [],
                }
                service.bind_public_turn("evaluation", case_id,
                    service.event_id("evaluation", case_id, "user"),
                    config_version="learning-eval-v1", phase="resume")
                try:
                    if row["finish_reason"] != "stop":
                        raise ValueError("Provider output incomplete: " + row["finish_reason"])
                    envelope = parse_object(row["text"], reject_duplicate_keys=True)
                    if args.interface == "wrapped":
                        envelope = envelope["delta"]
                    proposals = method.envelope_proposals(envelope, "edit-map:" + case_id)
                    for index, proposal in enumerate(proposals):
                        receipt = method.apply(
                            "evaluation",
                            f"{case_id}:{index}",
                            method.decode_proposal(proposal, "edit-map:" + case_id),
                        )
                        report["receipts"].append(receipt)
                    report["status"] = (
                        "no_change"
                        if not proposals
                        else "applied"
                        if all(r["ok"] for r in report["receipts"])
                        else "rejected"
                    )
                    report["proposal_count"] = len(proposals)
                except (ValueError, KeyError, ValidationError, FunctionalRejection) as error:
                    report.update(status="invalid_or_rejected", error=str(error))
                report["after"] = service.records()
                reports.append(report)
    (args.root / "applied-results.json").write_text(
        json.dumps(
            {
                "results": reports,
                "semantic_review": "pending; committed/parsed does not mean correct",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
