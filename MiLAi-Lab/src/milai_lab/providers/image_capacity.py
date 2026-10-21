"""Explicit local Qwen image-grid accounting for multimodal Reader requests."""
from __future__ import annotations

import base64
import io
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from milai_lab.providers.contextual_capacity import HostCapacity


class ImageHostCapacity(HostCapacity):
    """Expand each image placeholder using the local processor's actual patch grid.

    Applies to Qwen image-grid processors. Video and remote image fetching are outside
    this Reader path. Existing text-only callers continue using HostCapacity unchanged.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        from transformers import AutoImageProcessor

        processor_config = json.loads(
            (Path(config["tokenizer_path"])/"preprocessor_config.json").read_text())
        native = AutoImageProcessor.from_pretrained(  # type: ignore[no-untyped-call]
            config["tokenizer_path"], local_files_only=True, use_fast=False)
        # Both pinned slow processors reset size; from_pretrained applies pixel kwargs too late.
        # Pass the declared bounds to the resolved native constructor, preserving all other fields.
        settings = {**processor_config,
            "min_pixels": processor_config.get(
                "min_pixels", processor_config["size"]["shortest_edge"]),
            "max_pixels": processor_config.get(
                "max_pixels", processor_config["size"]["longest_edge"])}
        self.image_processor = type(native)(**settings)
        self.identity.update(image_processor=type(self.image_processor).__name__,
            declared_image_processor_config=processor_config,
            image_processor_config=self.image_processor.to_dict(),
            image_grid_rule="image_grid_thw product / merge_size squared",
            image_processor_use_fast=False)

    def count_messages(self, messages: Sequence[Mapping[str, Any]],
                       tools: Sequence[dict[str, Any]] | None = None, *,
                       enable_thinking: bool | None = None) -> int:
        from PIL import Image

        normalized = [deepcopy(dict(message)) for message in messages]
        extra_tokens = 0
        for message in normalized:
            if isinstance(message["content"], str) or message["content"] is None:
                continue
            parts = []
            for part in message["content"]:
                if part["type"] == "text":
                    parts.append(part)
                    continue
                if part["type"] != "image_url":
                    raise ValueError("The image Reader accepts text and inline image_url parts")
                header, payload = part["image_url"]["url"].split(",", 1)
                if not header.startswith("data:image/") or not header.endswith(";base64"):
                    raise ValueError("Image capacity requires the exact inline wire image")
                with Image.open(io.BytesIO(base64.b64decode(payload, validate=True))) as image:
                    inputs = self.image_processor(images=[image], return_tensors="np")
                grid = inputs["image_grid_thw"][0]
                tokens = int(grid.prod()) // self.image_processor.merge_size**2
                extra_tokens += tokens - 1  # The native text template already has one placeholder.
                parts.append({"type": "image"})
            message["content"] = parts
        return (super().count_messages(normalized, tools, enable_thinking=enable_thinking)
                + extra_tokens)
