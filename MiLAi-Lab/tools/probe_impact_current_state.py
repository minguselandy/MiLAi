"""Read frozen post-states using questions that do not supply the update's premises.

This is a new exposed diagnostic. Original Writer and Reader results stay intact.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.harness.artifact_io import configure_runtime_directory, read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    args = parser.parse_args()
    configure_runtime_directory(args.runtime_dir)
    from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
    from milai_lab.runners.impact_comparison import TimedBenchmarkRun, state_reader_messages
    from milai_lab.runners.method_architecture_diagnostic import (
        _copy_bank,
        _service,
        diagnostic_costs,
    )

    config = read_json(args.config)
    arm_source = Path(config["arms"][args.arm])
    protocol = read_json(arm_source.parent / "prepared.json")
    answers = []
    for case in protocol["cases"]:
        case_source = arm_source / case["id"]
        read_json(case_source / "result.json")  # Only closed maintenance outcomes are probed.
        root = args.output / args.arm / case["id"]
        path = root / "result.json"
        if path.exists():
            answers.append(read_json(path))
            continue
        settings = read_json(case_source / "actual-config.json")
        settings.update(experiment_name=config["name"] + "-" + args.arm + "-" + case["id"],
                        read_usage_updates=False)
        run = TimedBenchmarkRun(settings, root, phase="predict")
        try:
            bank = root / "bank"
            bank.mkdir(exist_ok=True)
            if not (bank / "memory.sqlite").exists():
                _copy_bank(case_source / "bank/memory.sqlite", bank / "memory.sqlite")
            with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
                service = _service(run, store, case["owner"], bank)
                before = service.records()
                question = config["questions"][case["id"]]
                messages = state_reader_messages(
                    before, question, case["observations"]["update"]["date"])
                response = run.call("current-state", messages, structured=False,
                                    enable_thinking=run.stage_thinking("reader"))
                result = {"case": case["id"], "question": question, "answer": response,
                          "record_values_unchanged": before == service.records(),
                          "state_only": True, "original_source_delivered": False,
                          "scope": "exposed follow-up; old questions supplied update premises"}
        finally:
            run.close()
        result["costs"] = diagnostic_costs(root)
        write_json(path, result)
        answers.append(result)
    write_json(args.output / args.arm / "summary.json", {
        "status": "PROBES_CLOSED", "answers": answers})


if __name__ == "__main__":
    main()
