"""CLI orchestrator for the frozen ML-closure LongMemEval validation."""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .longmemeval_contexts import run_context_phase
from .longmemeval_contract import CHECKPOINT_ROOT, LongMemEvalClosureError, atomic_json
from .longmemeval_freeze import build_run_lock, freeze_run_lock
from .longmemeval_providers import run_answers, run_judges
from .longmemeval_score import score_and_finalize


class _ResourceMonitor:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples = 0
        self.max_load_1m = 0.0
        self.minimum_mem_available_kib: int | None = None
        self.max_gpu_memory_used_mib: dict[str, int] = {}
        self.max_gpu_utilization_percent: dict[str, int] = {}

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def close(self, wall_ms: float) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        value = {
            "stage": self.stage,
            "wall_ms": round(wall_ms, 6),
            "sample_count": self.samples,
            "max_load_1m": round(self.max_load_1m, 6),
            "minimum_mem_available_kib": self.minimum_mem_available_kib,
            "max_gpu_memory_used_mib": self.max_gpu_memory_used_mib,
            "max_gpu_utilization_percent": self.max_gpu_utilization_percent,
        }
        atomic_json(CHECKPOINT_ROOT / "resources" / f"{self.stage}.json", value)
        return value

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._sample()
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
            self._stop.wait(2)

    def _sample(self) -> None:
        load = float(Path("/proc/loadavg").read_text(encoding="utf-8").split()[0])
        self.max_load_1m = max(self.max_load_1m, load)
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                available = int(line.split()[1])
                self.minimum_mem_available_kib = (
                    available
                    if self.minimum_mem_available_kib is None
                    else min(self.minimum_mem_available_kib, available)
                )
                break
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        for line in result.stdout.splitlines():
            index, memory, utilization = [item.strip() for item in line.split(",")]
            self.max_gpu_memory_used_mib[index] = max(
                self.max_gpu_memory_used_mib.get(index, 0), int(memory)
            )
            self.max_gpu_utilization_percent[index] = max(
                self.max_gpu_utilization_percent.get(index, 0), int(utilization)
            )
        self.samples += 1


def _monitored(stage: str, operation: Callable[[], Any]) -> dict[str, Any]:
    monitor = _ResourceMonitor(stage)
    monitor.start()
    started = time.perf_counter()
    try:
        result = operation()
    finally:
        resources = monitor.close((time.perf_counter() - started) * 1_000)
    return {"result": result, "resources": resources}


def _verify_smoke(terminals: object) -> dict[str, Any]:
    if not isinstance(terminals, tuple) or len(terminals) != 8:
        raise LongMemEvalClosureError("technical smoke shard denominator drifted")
    if any(
        not isinstance(value, dict)
        or value.get("case_count") != 1
        or value.get("succeeded") != 1
        or value.get("failed") != 0
        for value in terminals
    ):
        raise LongMemEvalClosureError("label-free technical smoke failed")
    return {
        "status": "PASS_LABEL_FREE_TECHNICAL_SMOKE",
        "shard_terminals": list(terminals),
        "labels_opened": False,
    }


def execute(stage: str) -> Any:
    if stage == "preflight":
        return build_run_lock()
    if stage == "dev-smoke":
        return _monitored(
            "dev-smoke",
            lambda: _verify_smoke(
                run_context_phase(phase="dev-smoke", require_lock=False)
            ),
        )
    if stage == "freeze":
        return freeze_run_lock()
    if stage == "smoke":
        value = _monitored(
            "official-smoke",
            lambda: _verify_smoke(run_context_phase(phase="smoke")),
        )
        atomic_json(CHECKPOINT_ROOT / "smoke-terminal.json", value)
        return value
    if stage == "contexts":
        return _monitored("full-contexts", lambda: run_context_phase(phase="full"))
    if stage == "answers":
        return _monitored("full-answers", run_answers)
    if stage == "judges":
        return _monitored("full-judges", run_judges)
    if stage == "score":
        return score_and_finalize()
    if stage == "all":
        smoke = execute("smoke")
        contexts = execute("contexts")
        answers = execute("answers")
        judges = execute("judges")
        score = execute("score")
        return {
            "smoke": smoke,
            "contexts": contexts,
            "answers": answers,
            "judges": judges,
            "score": score,
        }
    raise ValueError(f"unknown LongMemEval stage: {stage}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        required=True,
        choices=(
            "preflight",
            "dev-smoke",
            "freeze",
            "smoke",
            "contexts",
            "answers",
            "judges",
            "score",
            "all",
        ),
    )
    args = parser.parse_args()
    print(json.dumps(execute(args.stage), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
