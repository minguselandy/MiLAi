"""Apply saved-CPU inference settings while running an unchanged original Host entry."""

from __future__ import annotations

import json
import os
import runpy
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def saved_cpu_loading(
    decision: Any,
    torch: Any,
    record: Callable[[dict[str, Any]], None],
) -> Iterator[None]:
    """Set the same per-instance compile flag used by the frozen saved evaluator.

    The old scorer's inputs, loader, predictor and checkpoint bytes are unchanged.
    This process-local constructor wrapper records actual loaded inference conditions.
    """
    original = decision.__init__

    def initialize(
        self: Any, checkpoint: Path, max_len: int, head_max_len: int, device: str = "cpu"
    ) -> None:
        original(self, checkpoint, max_len, head_max_len, device)
        self.model.encoder.config.reference_compile = False
        actual = {
            "checkpoint": str(Path(checkpoint).resolve()),
            "device": str(self.device),
            "visible_cuda_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "threads": torch.get_num_threads(),
            "max_len": self.max_len,
            "head_max_len": self.head_max_len,
            "loaded_weight_dtype": str(next(self.model.parameters()).dtype),
            "mha_fastpath_enabled": torch.backends.mha.get_fastpath_enabled(),
            "reference_compile_override": self.model.encoder.config.reference_compile,
        }
        expected = {
            "device": "cpu",
            "visible_cuda_devices": "",
            "threads": 4,
            "max_len": 16384,
            "head_max_len": 2048,
            "loaded_weight_dtype": "torch.float32",
            "mha_fastpath_enabled": False,
            "reference_compile_override": False,
        }
        actual["status"] = (
            "VERIFIED"
            if all(actual[k] == v for k, v in expected.items())
            else "INFERENCE_CONDITION_MISMATCH"
        )
        record(actual)
        if actual["status"] != "VERIFIED":
            raise ValueError("Actual autonomous Host scorer differs from saved CPU conditions")

    decision.__init__ = initialize
    try:
        yield
    finally:
        decision.__init__ = original


def main() -> None:
    # Usage: original attention wrapper -> this wrapper RECEIPT ORIGINAL_ENTRY [entry args].
    receipt, entry = Path(sys.argv[1]), Path(sys.argv[2])
    original_argv = sys.argv[:]
    started = time.process_time()
    report: dict[str, Any] = {
        "status": "RUNNING",
        "entry": str(entry.resolve()),
        "argv": sys.argv[2:],
        "model_loads": [],
        "automatic_retry": False,
        "scope": "Explicit process-local inference settings, not a changed operation policy, "
        "Host prompt, input projection, checkpoint or runtime source file. This receipt is "
        "an inference audit; native runner and the shared ledger own actual model costs.",
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x") as stream:
        json.dump(report, stream, indent=2)

    def save(row: dict[str, Any]) -> None:
        report["model_loads"].append(row)
        receipt.write_text(json.dumps(report, indent=2) + "\n")

    try:
        import torch  # type: ignore[import-not-found]

        from milai_lab.providers.laya_local import NativeDecision

        report["native_decision_module_file"] = sys.modules[NativeDecision.__module__].__file__
        torch.set_num_threads(4)
        torch.backends.mha.set_fastpath_enabled(False)
        sys.path.insert(0, str(entry.parent))
        sys.argv = sys.argv[2:]
        with saved_cpu_loading(NativeDecision, torch, save):
            runpy.run_path(str(entry), run_name="__main__")
        report["status"] = "COMPLETED"
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        sys.argv = original_argv
        report["cpu_seconds_nested"] = time.process_time() - started
        report["cpu_accounting"] = "Nested wrapper + runner CPU; do not add native costs twice."
        receipt.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
