"""Run one bounded real-PostgreSQL smoke through each unified loader/Slot path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from evals.dg12.runtime_slot import (
    CohortRuntimeSlot,
    RuntimeSlot,
    SlotState,
    SlotWork,
    bounded_representative_work,
    load_slot_work,
)
from evals.paper.identity import sha256_file
from evals.paper.runners.memora_milai_contexts import _verify_install

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUTS = (
    ROOT / "var/dg11/paper/freeze/cupid-smoke-inputs.json",
    ROOT / "var/dg11/paper/freeze/horizon-smoke-inputs.json",
    ROOT / "var/dg11/paper/freeze/beam-128k-inputs.json",
    ROOT / "var/dg11/paper/freeze/memora-inputs.json",
)
DEFAULT_ENV = ROOT / "runtime/.env"
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
DEFAULT_RUNTIME_WHEEL = (
    ROOT / "var/dg11/freeze/candidate/packages/milai_runtime-0.1.0-py3-none-any.whl"
)
DEFAULT_INSTALL_MANIFEST = (
    ROOT / "var/dg11/paper/runs/pe04-milai-smoke-20260824-001/"
    "dg11-install-manifest.json"
)


class SlotSmokeError(RuntimeError):
    pass


def _smallest_work(path: Path) -> tuple[str, SlotWork]:
    partition, work = load_slot_work(path)
    selected = min(
        work,
        key=lambda item: (
            sum(
                len(turn.content.encode())
                for session in item.history.sessions
                for turn in session.turns
            ),
            item.history.history_id,
        ),
    )
    return partition, bounded_representative_work(selected)


def _failure(exc: Exception, *, input_path: Path, wall_time_ms: float) -> dict[str, Any]:
    return {
        "input_path": str(input_path.relative_to(ROOT)),
        "input_sha256": sha256_file(input_path),
        "terminal_status": "INFRASTRUCTURE_FAILURE",
        "failure_class": type(exc).__name__,
        "failure_message_sha256": hashlib.sha256(str(exc).encode()).hexdigest(),
        "wall_time_ms": round(wall_time_ms, 3),
    }


def run(
    *,
    run_id: str,
    inputs: tuple[Path, ...],
    output: Path,
    env_file: Path,
    tokenizer_path: Path,
    runtime_wheel: Path,
    install_manifest: Path,
) -> dict[str, Any]:
    if output.exists():
        raise SlotSmokeError("RuntimeSlot smoke output is write-once")
    if not output.parent.is_dir():
        raise SlotSmokeError("RuntimeSlot smoke run directory is absent")
    if len(inputs) != 4:
        raise SlotSmokeError("RuntimeSlot smoke requires exactly four loader inputs")
    _verify_install(
        method_id="DG11-FULL",
        runtime_wheel=runtime_wheel,
        install_manifest=install_manifest,
    )
    results: list[dict[str, Any]] = []
    previous_mcp_python = os.environ.get("DG10_MCP_HOST_PYTHON")
    os.environ["DG10_MCP_HOST_PYTHON"] = str(Path(sys.executable).absolute())
    try:
        for index, input_path in enumerate(inputs):
            started = time.perf_counter()
            slot: RuntimeSlot | None = None
            try:
                partition, work = _smallest_work(input_path)
                history = work.history
                question = work.questions[0]
                slot = CohortRuntimeSlot(
                    slot_id=f"dg12-bhe01-{index}",
                    env_file=env_file,
                    tokenizer_path=tokenizer_path,
                )
                slot.start()
                slot.load(history)
                record = slot.query(question)
                stats = slot.stats(question_count=1)
                slot.drain()
                slot.reset()
                if slot.state is not SlotState.EMPTY:
                    raise SlotSmokeError("RuntimeSlot did not return to EMPTY")
                results.append(
                    {
                        "input_path": str(input_path.relative_to(ROOT)),
                        "input_sha256": sha256_file(input_path),
                        "partition": partition,
                        "loader_kind": history.loader_kind.value,
                        "history_id": history.history_id,
                        "session_count": len(history.sessions),
                        "turn_count": sum(
                            len(session.turns) for session in history.sessions
                        ),
                        "question_count": 1,
                        "case_id": question.case_id,
                        "context_sha256": hashlib.sha256(
                            record.context.encode()
                        ).hexdigest(),
                        "source_ids": list(record.source_ids),
                        "terminal_status": record.terminal_status,
                        "slot_state_after_reset": slot.state.value,
                        "wall_time_ms": round(
                            (time.perf_counter() - started) * 1_000, 3
                        ),
                        "stats": stats,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - all four denominators are retained
                results.append(
                    _failure(
                        exc,
                        input_path=input_path,
                        wall_time_ms=(time.perf_counter() - started) * 1_000,
                    )
                )
            finally:
                if slot is not None:
                    try:
                        slot.close()
                    except Exception as exc:  # noqa: BLE001 - cleanup failure is terminal
                        results[-1] = _failure(
                            exc,
                            input_path=input_path,
                            wall_time_ms=(time.perf_counter() - started) * 1_000,
                        )
    finally:
        if previous_mcp_python is None:
            os.environ.pop("DG10_MCP_HOST_PYTHON", None)
        else:
            os.environ["DG10_MCP_HOST_PYTHON"] = previous_mcp_python
    failures = sum(item["terminal_status"] != "SUCCEEDED" for item in results)
    payload = {
        "schema": "milai.dg12.runtime-slot-smoke.v1",
        "run_id": run_id,
        "work_package": "DG12-BHE01",
        "status": "PASS" if len(results) == 4 and failures == 0 else "FAIL",
        "mode": "REFERENCE_COHORT_REUSE_ADAPTED_SMOKE",
        "paper_labels_opened": False,
        "labels_accessed": False,
        "answer_calls": 0,
        "judge_calls": 0,
        "hidden_provider_calls": 0,
        "candidate_modified": False,
        "loader_count": len(results),
        "failure_count": failures,
        "selection_policy": "minimum source bytes, then history_id; first session and first question",
        "results": results,
        "identity": {
            "runner_sha256": sha256_file(Path(__file__)),
            "slot_contract_sha256": sha256_file(Path(__file__).with_name("runtime_slot.py")),
            "runtime_wheel_sha256": sha256_file(runtime_wheel),
            "install_manifest_sha256": sha256_file(install_manifest),
            "env_sha256": sha256_file(env_file),
        },
    }
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, nargs=4, default=DEFAULT_INPUTS)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--runtime-wheel", type=Path, default=DEFAULT_RUNTIME_WHEEL)
    parser.add_argument(
        "--install-manifest", type=Path, default=DEFAULT_INSTALL_MANIFEST
    )
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        inputs=tuple(args.inputs),
        output=args.output,
        env_file=args.env_file,
        tokenizer_path=args.tokenizer,
        runtime_wheel=args.runtime_wheel,
        install_manifest=args.install_manifest,
    )
    print(
        json.dumps(
            {
                "failure_count": result["failure_count"],
                "loader_count": result["loader_count"],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
