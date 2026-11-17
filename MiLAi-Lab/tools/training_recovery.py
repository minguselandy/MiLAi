"""Training-state persistence beside existing inference checkpoints, without digests."""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any, cast

from milai_lab.harness.artifact_io import write_json


def record_training_invocation(root: Path, record: dict[str, Any],
                               measures: dict[str, Any]) -> None:
    """Retain every measured invocation when resume advances the current run record.

    This is execution evidence, not a second budget ledger or a native charge.
    Incomplete historical invocations without timings remain unmeasured.
    """
    write_json(root / "run.json", {**record, "invocation": measures})
    with (root / "invocations.jsonl").open("a") as stream:
        stream.write(json.dumps({"status": record["status"], **measures}) + "\n")


class TrainingInterruption(Exception):
    """An explicitly requested update-boundary interruption, used for recovery checks."""


def make_scheduler(optimizer: Any, steps: int, *, warmup_fraction: float,
                   warmup_max_updates: int, floor_ratio: float, mode: str) -> Any:
    import torch

    if mode == "legacy-cosine":
        return torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, steps, eta_min=1e-6)
    warmup = min(warmup_max_updates, round(steps * warmup_fraction), max(0, steps - 1))

    def factor(step: int) -> float:
        if step < warmup:
            return (step + 1) / warmup
        progress = min(1.0, (step - warmup + 1) / max(1, steps - warmup))
        return floor_ratio + (1 - floor_ratio) * (1 + math.cos(math.pi * progress)) / 2

    return torch.optim.lr_scheduler.LambdaLR(optimizer, factor)


def _data_literal(data: list[dict[str, Any]]) -> str:
    # The complete values, including JSON types and field order, not a digest.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"


def _bind_data(path: Path, data: list[dict[str, Any]]) -> dict[str, str]:
    literal = _data_literal(data)
    snapshot = path.parent / "training-data.literal.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    try:
        with snapshot.open("x", encoding="utf-8") as stream:
            stream.write(literal)
    except FileExistsError:
        if snapshot.read_text(encoding="utf-8") != literal:
            raise ValueError("Full training observations/bindings/supervision changed") from None
    return {"format": "full-json-values-v1", "path": str(snapshot.resolve())}


def _validate_data(binding: dict[str, str], data: list[dict[str, Any]]) -> None:
    if binding.get("format") != "full-json-values-v1":
        raise ValueError("Unsupported full training data snapshot")
    try:
        literal = Path(binding["path"]).read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("Original full training data snapshot is unavailable") from error
    if literal != _data_literal(data):
        raise ValueError("Full training observations/bindings/supervision changed")


def save_training_state(path: Path, model: Any, optimizer: Any, scheduler: Any,
                        *, contract: dict[str, Any], progress: dict[str, Any],
                        data: list[dict[str, Any]] | None = None) -> None:
    """Save actual FP32 parameters; the SDK's FP16 inference export is insufficient.

    The temporary file and atomic rename use the existing artifact directory.
    Only load these locally produced training-state files, not untrusted pickles.
    """
    import torch

    binding = _bind_data(path, data) if data is not None else None
    state = {"schema": "bounded-training-state-v2" if binding else "bounded-training-state-v1",
             "contract": contract,
             "model": {key: value.detach().cpu() for key, value in model.state_dict().items()},
             "optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(),
             "torch_rng": torch.get_rng_state(),
             "cuda_rng": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
             "python_rng": random.getstate(), "progress": progress}
    if binding is not None:
        state["data_snapshot"] = binding
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    torch.save(state, temporary)
    temporary.replace(path)


def restore_training_state(path: Path, model: Any, optimizer: Any, scheduler: Any,
                           *, contract: dict[str, Any],
                           data: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    import torch

    state = torch.load(path, map_location="cpu", weights_only=False)
    schema = state["schema"]
    if schema not in {"bounded-training-state-v1", "bounded-training-state-v2"}:
        raise ValueError("Unsupported training recovery schema")
    if data is not None:
        if schema != "bounded-training-state-v2":
            raise ValueError("Legacy checkpoint lacks full training data evidence; use its "
                             "original frozen trainer or initialize a new stage")
        _validate_data(state["data_snapshot"], data)
    elif schema == "bounded-training-state-v2":
        raise ValueError("Exact recovery requires the original full training examples")
    # Legacy callers keep their original recipe contract. New data-bound states
    # also distinguish JSON true/1 and other recipe value types without hashes.
    recipe_equal = (json.dumps(state["contract"], sort_keys=True, allow_nan=False) ==
                    json.dumps(contract, sort_keys=True, allow_nan=False)
                    if schema == "bounded-training-state-v2" else state["contract"] == contract)
    if not recipe_equal:
        raise ValueError("Recovery requires the original data IDs, sampling and training recipe")
    model.load_state_dict(state["model"])
    optimizer.load_state_dict(state["optimizer"])
    scheduler.load_state_dict(state["scheduler"])
    random.setstate(state["python_rng"])
    torch.set_rng_state(state["torch_rng"])
    if state["cuda_rng"]:
        torch.cuda.set_rng_state_all(state["cuda_rng"])
    return cast(dict[str, Any], state["progress"])
