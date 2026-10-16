"""Classify fixed range and lookup controls without evidence or reference answers."""

from __future__ import annotations

import argparse
from pathlib import Path

from jsonschema import Draft202012Validator

from milai_lab.harness.artifact_io import configure_runtime_directory, read_json, write_json
from milai_lab.methods.edit_maintenance import parse_object
from milai_lab.methods.reader_task import task_request
from milai_lab.runners.edit_benchmarks import BenchmarkRun
from milai_lab.runners.method_architecture_diagnostic import diagnostic_costs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    configure_runtime_directory(args.runtime_dir)
    protocol = read_json(args.protocol)
    settings = read_json(Path(protocol["settings"]))
    settings.update(experiment_name=protocol["name"], config_version=protocol["name"])
    execution = BenchmarkRun(settings, args.output)
    rows = []
    try:
        for case in protocol["cases"]:
            messages, schema = task_request(case["question"], case["date"])
            output = execution.call(
                f"diagnostic/{case['case_id']}/task",
                messages,
                structured=True,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "reader_task", "schema": schema},
                },
                enable_thinking=False,
            )
            response = parse_object(output, reject_duplicate_keys=True)
            Draft202012Validator(schema).validate(response)
            rows.append(
                {
                    "case_id": case["case_id"],
                    "question": case["question"],
                    "predicted": response["task"],
                    "expected": case["expected"],
                }
            )
            write_json(args.output / "results.json", {"status": "RUNNING", "rows": rows})
    finally:
        execution.close()
    write_json(
        args.output / "results.json",
        {
            "status": "COMPLETED",
            "rows": rows,
            "costs": diagnostic_costs(args.output),
            "scope": "Exposed question-only routing diagnostic. Expected labels are used only "
            "after responses; no Sources, answers or candidate labels enter the request. "
            "Not an answer-quality or independent generalization result.",
        },
    )


if __name__ == "__main__":
    main()
