"""Lossless released trajectories and public questions, without reference-answer access."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def public_question(row: dict[str, Any], data_root: Path) -> tuple[str, str | None]:
    """Only question text and its original image enter the online query/Reader path."""
    image = row["image"]
    return row["question"], str(asset_path(data_root, image)) if image is not None else None


def asset_path(data_root: Path, relative: str) -> Path:
    path = (data_root / relative).resolve()
    if not path.is_relative_to(data_root.resolve()):
        raise ValueError("A released image must remain inside its declared data root")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def trajectory_sources(trajectory: dict[str, Any]) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep every field, with an explicit screenshot locator before each complete state.

    The locator is duplicated public metadata, not an image caption or semantic label.
    Its codepoint range lets actual original-source delivery admit the associated image.
    Historical thoughts/outcomes remain attributed observations, not current instructions.
    """
    identity = trajectory["id"]
    rows, media = [], []

    def source(key: str, content: dict[str, Any] | str) -> dict[str, Any]:
        return {"session_id": identity, "event_key": key,
            "original_event_id": f"{identity}/{key}", "role": "tool",
            "origin": "lme_v2_released_trajectory", "occurred_at": None,
            "content": content}

    rows.append(source("trajectory", copy.deepcopy({
        key: value for key, value in trajectory.items() if key != "states"})))
    for index, state in enumerate(trajectory["states"]):
        locator = {"trajectory_id": identity, "state_index": index,
                   "screenshot": state["screenshot"]}
        prefix = json.dumps(locator, ensure_ascii=False)
        row = source(f"state-{index}", prefix + "\n" + json.dumps(state, ensure_ascii=False))
        rows.append(row)
        if state["screenshot"] is not None:
            media.append({"original_event_id": row["original_event_id"],
                "locator": locator, "locator_text": prefix, "range": [0, len(prefix)],
                "relative_image": state["screenshot"]})
    return rows, media


def bind_media(media: list[dict[str, Any]], imports: list[dict[str, Any]],
               data_root: Path) -> dict[str, dict[str, Any]]:
    """Join declared assets to actual source-import receipts; no content fingerprints."""
    receipts = {row["original_event_id"]: row["receipt"] for row in imports}
    return {receipts[row["original_event_id"]]["source_ref"]: {
        **copy.deepcopy(row), "source_revision": 1,
        "image": str(asset_path(data_root, row["relative_image"]))} for row in media}
