"""Attach declared local images only when their source locator is actually delivered."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from milai_lab.memory.functional_state import namespace
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import open_evidence_packs


def delivered_image_context(service: MemoryService, packet: dict[str, Any],
                            media: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Native text/image context, preserving the entire receipt and current source visibility.

    This renderer has no access to question IDs, gold sources or answers. A View citation,
    offered-but-unread action or partial locator does not authorize an image attachment.
    Complete multimodal token accounting/admission belongs to the caller before Reader I/O.
    """
    context = [{"type": "text", "value": json.dumps(packet, ensure_ascii=False)}]
    emitted: set[tuple[str, int]] = set()
    for evidence in packet["evidence"]:
        ref = evidence["ref"]
        snapshot = service.store.get(namespace(service), ref["snapshot_id"])
        if (snapshot is None or snapshot.value["schema"] != "milai_retrieval_snapshot_v1"
                or ref["item_index"] not in snapshot.value["delivered_indices"]):
            raise ValueError("An image requires an actually delivered material reference")
        material = snapshot.value["materials"][ref["item_index"]]
        if material["kind"] not in {"original_source", "semantic_view"}:
            continue
        opened = open_evidence_packs(service, [material])[0]
        if opened.get("body_delivered") is False:
            continue
        turns = (json.loads(opened["text"]) if opened["kind"] == "original_source"
                 else opened.get("support_turns", []))
        for turn in turns:
            binding = media.get(turn["source_ref"])
            if binding is None or binding["source_revision"] != turn.get("source_revision", 1):
                continue
            identity = (turn["source_ref"], binding["source_revision"])
            if identity in emitted:
                continue
            start, end = turn["range"]
            left, right = binding["range"]
            if not start <= left < right <= end:
                continue
            if turn["content"][left-start:right-start] != binding["locator_text"]:
                raise ValueError("The delivered source locator differs from its declared asset")
            image = Path(binding["image"])
            if not image.is_file():
                raise FileNotFoundError(image)
            context.append({"type": "text", "value": json.dumps({
                "image_for_delivered_material": ref, "source_locator": binding["locator"]},
                ensure_ascii=False)})
            context.append({"type": "image", "value": str(image)})
            emitted.add(identity)
    return context
