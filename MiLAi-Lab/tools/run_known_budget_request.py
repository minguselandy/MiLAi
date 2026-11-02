"""Execute one fresh-budget request from the pre-final bank; caller serializes model jobs."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.runners.frozen_host_message import memory_store_values
from milai_lab.runners.functional import message


def run_condition(preparation: dict[str, Any], output: Path, arm: str) -> dict[str, Any]:
    """One normal given-request invocation; no old cache, policy or allowance is rewritten."""
    if preparation["status"] != "FRESH_RAW_KNOWN_BUDGET_REQUESTS_PREPARED_NOT_EXECUTED":
        raise ValueError("Only an eligible explicit fresh-request preparation can execute")
    (condition,) = [c for c in preparation["conditions"] if c["arm"] == arm]
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {
        "status": "RUNNING",
        "arm": arm,
        "family": preparation["family"],
        "request": condition["request"],
        "source_snapshot": preparation["source_snapshot"],
        "source_snapshot_boundary": preparation["source_snapshot_boundary"],
        "automatic_retry": False,
        "host_request_generated": False,
        "Host_quality": None,
        "call_captures": [],
        "actual_initial_states": 0,
        "scope": "New controlled retrieval component call on the actual pre-final bank. "
        "No Host answer/readout is generated and no unexecuted action is labelled.",
    }
    write_json(output / "run.json", report)
    before = None
    try:
        runtime = output / "runtime"
        shutil.copytree(Path(preparation["source_snapshot"]), runtime)
        freeze = read_json(runtime / "input-freeze.json")
        if (
            freeze["source_version"] != preparation["source_version"]
            or freeze["config"]["budget_path"] != preparation["original_ledger"]
        ):
            raise ValueError("Fresh request changed the original runtime version or ledger")
        bank = runtime / preparation["source_bank_relative"]
        (public_source,) = [
            row
            for row in preparation["source_store_values"]
            if row["namespace"][-1] == "v13_1_sources"
            and row["key"] == preparation["source_public_source_ref"]
        ]
        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
            service = MemoryService(
                store,
                tuple(public_source["namespace"][:-1]),
                preparation["public_message"]["owner"],
                bank / "memory.lock",
                functional_contract="functional_v1",
            )
            if memory_store_values(service) != preparation["source_store_values"]:
                raise ValueError("Fresh request does not start from the exact closed bank values")
        before = read_json(Path(preparation["original_ledger"]))
        result = message(
            runtime,
            **preparation["public_message"],
            given_retrieval_request=condition["request"],
            retrieval_snapshots=output / "frozen-retrieval-calls",
            retrieval_step_snapshots=True,
        )
        captures = sorted((output / "frozen-retrieval-calls").glob("*/call.json"))
        report.update(
            status=result["status"],
            result=result,
            exact_starting_bank_values=True,
            call_captures=[str(p.parent) for p in captures],
            actual_initial_states=sum(
                read_json(p)["initial_observation"] is not None for p in captures
            ),
        )
        return report
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        captures = sorted((output / "frozen-retrieval-calls").glob("*/call.json"))
        report.update(
            call_captures=[str(path.parent) for path in captures],
            actual_initial_states=sum(
                read_json(path)["initial_observation"] is not None for path in captures
            ),
        )
        elapsed = time.process_time() - cpu
        report.update(cpu_seconds_nested=elapsed, wall_seconds=time.perf_counter() - started)
        if before is not None:
            after = read_json(Path(preparation["original_ledger"]))
            charged = sum(
                v.get("cpu_seconds", 0)
                - before.get("compute", {}).get(name, {}).get("cpu_seconds", 0)
                for name, v in after.get("compute", {}).items()
            )
            report.update(
                budget_before=before,
                budget_after=after,
                ledger_cpu_seconds_nested=charged,
                cpu_seconds_not_yet_recorded=elapsed - charged,
            )
        write_json(output / "run.json", report)


def compare_initial_conditions(
    preparation: dict[str, Any], outputs: dict[str, Path]
) -> dict[str, Any]:
    """Report all observed differences; timing telemetry is retained in the model inputs."""
    reports = {name: read_json(path / "run.json") for name, path in outputs.items()}
    calls = {}
    for condition in preparation["conditions"]:
        name = condition["arm"]
        paths = reports[name]["call_captures"]
        if len(paths) != 1:
            return {
                "status": "PAIR_INITIAL_STATE_UNAVAILABLE",
                "arm": name,
                "actual_call_count": len(paths),
                "quality_labels": [],
            }
        call = read_json(Path(paths[0]) / "call.json")
        if call["request"] != condition["request"]:
            raise ValueError("Executed fresh request differs from its declared condition")
        if call["initial_observation"] is None:
            return {
                "status": "PAIR_INITIAL_STATE_UNAVAILABLE",
                "arm": name,
                "call_status": call["status"],
                "quality_labels": [],
            }
        calls[name] = call
    left, right = calls["baseline"], calls["limited"]
    if (
        left["initial_observation"]["task"]["known_evidence"]
        != right["initial_observation"]["task"]["known_evidence"]
        or left["read_allowance"] != right["read_allowance"]
        or left["admission_policy"] != right["admission_policy"]
    ):
        raise ValueError("Fresh conditions do not share known evidence and fresh read admission")
    differences = []

    def compare(a: Any, z: Any, path: list[str]) -> None:
        if isinstance(a, dict) and isinstance(z, dict) and a.keys() == z.keys():
            for key in a:
                compare(a[key], z[key], [*path, key])
        elif a != z:
            differences.append({"path": path, "baseline": a, "limited": z})

    compare(left["initial_observation"], right["initial_observation"], [])
    budget_paths = [
        ["budget", "max_return_tokens"],
        ["task", "retrieval_request", "limits", "max_return_tokens"],
    ]
    other = [row for row in differences if row["path"] not in budget_paths]
    return {
        "status": "FRESH_PAIR_KNOWN_CONTEXT_VERIFIED_DIFFERENCES_RETAINED",
        "same_known_evidence": True,
        "same_read_admission_policy": True,
        "same_fresh_read_allowance": True,
        "initial_observation_differences": differences,
        "other_model_visible_differences": other,
        "only_return_budget_fields_differ": not other,
        "actual_initial_states": 2,
        "quality_labels": [],
        "scope": "Two actual fresh initial states. Observed timing or other input differences "
        "remain in raw captures; this is not automatically a pure budget causal effect. "
        "No Host readout or training-slot assignment is inferred.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preparation", type=Path)
    parser.add_argument(
        "output", type=Path, help="Run directory for --arm; comparison JSON for --compare"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--arm", choices=("baseline", "limited"))
    mode.add_argument("--compare", type=Path, nargs=2, metavar=("BASELINE", "LIMITED"))
    args = parser.parse_args()
    if args.compare:
        started = time.process_time()
        report = compare_initial_conditions(
            read_json(args.preparation),
            dict(zip(("baseline", "limited"), args.compare, strict=True)),
        )
        report.update(
            cpu_seconds_pending=time.process_time() - started,
            model_calls=0,
            ledger_recorded=False,
            no_sha_validation=True,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(report["status"])
        return
    report = run_condition(read_json(args.preparation), args.output, args.arm)
    print(
        json.dumps(
            {
                "status": report["status"],
                "arm": args.arm,
                "actual_initial_states": report["actual_initial_states"],
            }
        )
    )


if __name__ == "__main__":
    main()
