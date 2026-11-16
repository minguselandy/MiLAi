"""Training compatibility exports for the shared ordinary action-marker head."""
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import write_json
from milai_lab.providers.linear_local import LinearDecision, build_linear_model
from ordinary_reader_reranker import save_model

__all__ = ["LinearDecision", "build_linear_model", "save_linear_checkpoint"]


def save_linear_checkpoint(model: Any, tokenizer: Any, config: dict, path: str) -> None:
    save_model(model, tokenizer, Path(path))
    write_json(Path(path) / "linear_config.json", config)
