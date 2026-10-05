"""Compare fixed exposed v1 inputs with pure I1/I2 projections, without HTTP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

from transformers import AutoTokenizer

from milai_lab.datasets.edit_benchmarks import halumem_users
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.edit_memory import Arm, EditMemory
from milai_lab.runners.edit_benchmarks import BenchmarkRun


def prepare(suite: Path, selection: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Preserve the prior preflight; use a new output")
    chosen = read_json(selection)["fixed_samples"]
    if len(chosen) > 24 or len({r["input_id"] for r in chosen}) != len(chosen):
        raise ValueError("Fixed preflight must use at most 24 distinct original inputs")
    config = read_json(suite / "B0" / "actual-config.json")
    users = halumem_users(Path(config["halumem"]["path"]), config["halumem"]["users"])
    dates = {(u["uuid"], i): s["start_time"] for u in users for i, s in enumerate(u["sessions"])}
    execution = BenchmarkRun.__new__(BenchmarkRun)
    execution.settings = config
    execution.tokenizer = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
        config["tokenizer_path"], local_files_only=True
    )
    rows = []
    for sample in chosen:
        delivery = read_json(Path(sample["delivery_path"]))
        projected = {}
        for interface in ("I1", "I2"):
            # Projection is deliberately pure: no state restore, retrieval or issued mapping.
            method = EditMemory.__new__(EditMemory)
            method.arm = cast(Arm, sample["arm"])
            method.conditioned = sample["arm"] in {"B2", "M"}
            method.interface_version = cast(Any, interface)
            packet = method.preview_writer_view(delivery)["packet"]
            messages = execution._edit_messages(
                method, packet, dates[(sample["user"], sample["session"])], allow_create=True
            )
            tokens = execution.input_tokens(messages)
            projected[interface] = {
                "prompt_tokens": tokens,
                "fits_full_request_reserve": execution._fits(messages),
                "packet": packet,
                "messages": messages,
                "schema": method.envelope_schema(),
            }
        rows.append(
            {
                **sample,
                "original_v1_prompt_tokens": sample["prompt_tokens"],
                "projections": projected,
            }
        )
    report = {
        "status": "STAGE_A_FIXED_INPUT_CAPACITY_PREFLIGHT_ONLY",
        "actual_http_calls": 0,
        "unique_original_inputs": len(rows),
        "samples": rows,
        "candidate_selected": False,
        "limit": (
            "I1 changes schema/references; I2 also changes presentation. Same full records, "
            "original text, ranges and relations; these packets cannot authorize commits. "
            "Fits is a capacity result, not Writer syntax/reference or semantic success. "
            "Original v1 has its own prompt; counts are actual templates, not additive components."
        ),
    }
    write_json(output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("suite", "selection", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.suite, args.selection, args.output)
    print(
        json.dumps(
            {
                "unique_inputs": report["unique_original_inputs"],
                "actual_http_calls": 0,
                "fits": {
                    profile: sum(
                        r["projections"][profile]["fits_full_request_reserve"]
                        for r in report["samples"]
                    )
                    for profile in ("I1", "I2")
                },
            }
        )
    )


if __name__ == "__main__":
    main()
