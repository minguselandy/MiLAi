"""Training-state persistence beside existing inference checkpoints, without digests."""
from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any


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


def save_training_state(path: Path, model: Any, optimizer: Any, scheduler: Any,
                        *, contract: dict[str, Any], progress: dict[str, Any]) -> None:
    """Save actual FP32 parameters; the SDK's FP16 inference export is insufficient.

    The temporary file and atomic rename use the existing artifact directory.
    Only load these locally produced training-state files, not untrusted pickles.
    """
    import torch

    state = {"schema": "bounded-training-state-v1", "contract": contract,
             "model": {key: value.detach().cpu() for key, value in model.state_dict().items()},
             "optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(),
             "torch_rng": torch.get_rng_state(),
             "cuda_rng": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
             "python_rng": random.getstate(), "progress": progress}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    torch.save(state, temporary)
    temporary.replace(path)


def restore_training_state(path: Path, model: Any, optimizer: Any, scheduler: Any,
                           *, contract: dict[str, Any]) -> dict[str, Any]:
    import torch

    state = torch.load(path, map_location="cpu", weights_only=False)
    if state["schema"] != "bounded-training-state-v1" or state["contract"] != contract:
        raise ValueError("Recovery requires the original data IDs, sampling and training recipe")
    model.load_state_dict(state["model"])
    optimizer.load_state_dict(state["optimizer"])
    scheduler.load_state_dict(state["scheduler"])
    random.setstate(state["python_rng"])
    torch.set_rng_state(state["torch_rng"])
    if state["cuda_rng"]:
        torch.cuda.set_rng_state_all(state["cuda_rng"])
    return state["progress"]
