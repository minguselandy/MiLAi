"""Serial Stage A Writer checks: fixed old/new inputs plus actual empty-bank paths.

Uses the existing shared lease/ledger; no extra semantic Judge or method selection.
Old/new frozen-input probes are never committed; normal paths own separate banks.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, exceptions  # type: ignore[import-untyped]
from langgraph.store.sqlite import SqliteStore

from milai_lab.datasets.edit_benchmarks import ObservedSession
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_memory import Arm
from milai_lab.runners.edit_benchmarks import BenchmarkRun, parse_object

NORMAL_EVENTS = (
    "南岸项目每周二整理索引。北港项目的标签全部用小写字母。",
    "南岸项目整理索引改到每周四。北港项目标签继续只用小写字母。",
    "谢谢。",
)


def alias_errors(envelope: dict[str, Any], packet: dict[str, Any]) -> list[str]:
    """Namespace check only; no semantic support certification or mutation."""
    records = {r["id"] for r in packet["records"]}
    units = {u["id"] for r in packet["records"] for u in r.get("units", [])}
    evidence = {e["id"] for e in packet["evidence"]}
    support = {h["id"] for h in packet["historical_support"]}
    errors: list[str] = []

    def inspect(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                inspect(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                allowed = (
                    records
                    if key == "target" and isinstance(item, str)
                    else units
                    if key == "target_unit"
                    else evidence
                    if key in {"evidence", "withdrawal_evidence"}
                    else support
                    if key == "keep_support"
                    else units
                    if key in {"attach_to", "shared_conditions"}
                    else None
                )
                if allowed is not None:
                    selected = item if isinstance(item, list) else [item]
                    errors.extend(
                        f"{key}: {ref}"
                        for ref in selected
                        if ref is not None and ref not in allowed
                    )
                inspect(item)

    inspect(envelope)
    return errors


def execute(config: Path, preflight: Path, output: Path) -> None:
    settings = read_json(config)
    settings.update({"experiment_name": "milai-edit-v2-stage-a-v1", "arm": "M"})
    settings.pop("arms", None)
    run = BenchmarkRun(settings, output)
    try:
        samples = read_json(preflight)["samples"]
        selected = [
            r
            for category in ("unsupported_action", "wrong_reference", "normal_control")
            for r in [s for s in samples if s["category"] == category][:2]
        ]
        selection = output / "selected-inputs.json"
        declared = {
            "fixed_input_ids": [r["input_id"] for r in selected],
            "normal_events": list(NORMAL_EVENTS),
            "normal_arms": ["B0", "B1", "B2", "M"],
            "old_new_probes": 12,
            "normal_source_opportunities": 12,
            "selection": "first two fixed inputs per error/control category; before any output",
            "exposure": "constructed common development stories; not confirmation histories",
        }
        if selection.exists() and read_json(selection) != declared:
            raise ValueError("Stage A declared input selection changed")
        write_json(selection, declared)
        rows = []
        suite = Path(read_json(preflight)["samples"][0]["delivery_path"]).parents[6]
        for sample_ordinal, sample in enumerate(selected):
            for condition in ("v1", "I2"):
                if condition == "I2":
                    projected = sample["projections"]["I2"]
                    messages, schema = projected["messages"], projected["schema"]
                    response_format = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "edit_interface_" + sample["arm"].lower(),
                            "schema": schema,
                        },
                    }
                else:
                    batch = Path(sample["delivery_path"]).parent
                    original = (
                        suite
                        / sample["arm"]
                        / "http"
                        / "halumem"
                        / sample["user"]
                        / str(sample["session"])
                        / "writer"
                        / str(int(batch.name.split("-")[1]))
                    )
                    messages = read_json(original / "request.json")["messages"]
                    response_format = {"type": "json_object"}
                key = f"fixed/{sample_ordinal}/{condition}"
                result: dict[str, Any] = {
                    "input_id": sample["input_id"],
                    "condition": condition,
                    "arm": sample["arm"],
                    "status": "COMPLETE_RESPONSE",
                }
                try:
                    envelope = parse_object(
                        run.call(key, messages, structured=True, response_format=response_format)
                    )
                    result["output"] = envelope
                    if condition == "I2":
                        Draft202012Validator(schema).validate(envelope)
                        result["reference_errors"] = alias_errors(envelope, projected["packet"])
                        result["schema_valid"] = True
                except (ValueError, exceptions.ValidationError) as error:
                    http = output / "http" / key
                    if (http / "request.json").exists() and not (http / "response.json").exists():
                        raise
                    result.update({"status": "FIRST_ATTEMPT_FAILED", "error": str(error)})
                rows.append(result)
                write_json(output / "fixed-probes.json", rows)
        normal = []
        for arm in cast(list[Arm], ["B0", "B1", "B2", "M"]):
            root = output / "normal" / arm
            root.mkdir(parents=True, exist_ok=True)
            run.settings = {**settings, "arm": arm}
            with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
                service = MemoryService(
                    store,
                    ("stage-a", arm, "owner"),
                    "owner",
                    root / "memory.lock",
                    mutation_contract="event_bound_v1",
                    candidate_contract="read_handle_v1",
                )
                for ordinal, text in enumerate(NORMAL_EVENTS):
                    observed = ObservedSession(
                        f"stage-a:{arm}:{ordinal}",
                        "2030-01-01",
                        ({"role": "user", "content": text, "timestamp": "2030-01-01"},),
                    )
                    key = f"normal/{arm}/{ordinal}"
                    run.maintain(service, observed, key)
                    normal.append(
                        {
                            "arm": arm,
                            "event": ordinal,
                            "maintenance": read_json(
                                output / "maintenance" / key / "complete.json"
                            ),
                            "state_after": service.records(),
                        }
                    )
                    write_json(output / "normal-paths.json", normal)
        write_json(
            output / "terminal.json",
            {
                "status": "COMPLETED_INTERFACE_CHECK_ATTEMPTS",
                "fixed_probes": len(rows),
                "normal_source_opportunities": len(normal),
                "candidate_selected": False,
                "limit": (
                    "Syntax/references/actual path diagnostics; "
                    "semantic quality and all plan phases remain."
                ),
            },
        )
    finally:
        run.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "preflight", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    execute(args.config, args.preflight, args.output)


if __name__ == "__main__":
    main()
