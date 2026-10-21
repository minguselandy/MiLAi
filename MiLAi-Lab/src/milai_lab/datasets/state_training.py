"""Public STATE train observations, without task oracles or fabricated live authority.

An executed domain call is evidence, never a Jev action label. Results remain whole:
preview, failure and committed changes are not merged into a guessed object state.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json


def identity_bindings(call: dict[str, Any]) -> list[dict[str, Any]]:
    """Index explicit top-level IDs only; these are not verified object references."""
    bindings: list[dict[str, Any]] = []
    for location in ("arguments", "result"):
        value = call[location]
        if isinstance(value, dict):
            bindings.extend({"location": location, "field": key, "value": item}
                for key, item in value.items()
                if key.endswith("_id") and isinstance(item, (str, int)))
    return bindings


def training_stream(conversation: list[dict[str, Any]], domain: str,
                    ordinal: int) -> dict[str, Any]:
    """Keep public user/tool occurrences in order and cuts before each user request."""
    session = f"state-train-{domain}-{ordinal:03d}"
    sources: list[dict[str, Any]] = []
    checkpoints = []
    observations = []
    previous_calls: list[dict[str, Any]] | None = None
    for index, message in enumerate(conversation):
        role = message["role"]
        if role == "user":
            content = message["content"]
            checkpoints.append({"id": f"message-{index}", "content": content,
                "source_count": len(sources), "terminal": "[TASK_DONE]" in content})
            sources.append({"session_id": session, "event_key": f"message-{index}",
                "original_event_id": f"{session}/message-{index}", "role": "user",
                "content": content, "occurred_at": None})
            previous_calls = None
        elif role == "assistant":
            previous_calls = message.get("tool_calls") or []
            for number, call in enumerate(previous_calls):
                event = f"message-{index}-tool-{number}"
                # Only the executed call enters evidence, not the assistant's prose.
                public_call = {key: copy.deepcopy(call[key])
                               for key in ("name", "arguments", "result")}
                observations.append({"source_index": len(sources),
                    "message_index": index, "call_index": number,
                    "tool_name": call["name"], "bindings": identity_bindings(public_call)})
                sources.append({"session_id": session, "event_key": event,
                    "original_event_id": f"{session}/{event}", "role": "tool",
                    "origin": "state_public_training_tool_result", "occurred_at": None,
                    "content": json.dumps(public_call, ensure_ascii=False)})
        elif role == "tool":
            # STATE's runtime may repeat the preceding assistant's executed records.
            if previous_calls is None or message["content"] != previous_calls:
                raise ValueError("STATE tool row is not the preceding executed-call copy")
            previous_calls = None
        elif role == "system":
            # Domain policy remains the real Host's system prompt, not a fake tool source.
            previous_calls = None
        else:
            raise ValueError(f"Unsupported STATE conversation role: {role}")
    return {"schema": "state_train_material_stream_v1", "id": session,
        "source_group": session, "split": "train", "domain": domain,
        "sources": sources, "checkpoints": checkpoints, "observations": observations,
        "operation_labels": [], "object_authority": "historical observations only",
        "time_basis": "conversation order; no occurrence timestamps supplied",
        "source_group_scope": "trajectory identity, not proven statistical independence"}


def source_cut(stream: dict[str, Any], checkpoint_index: int) -> dict[str, Any]:
    """Material available before an actual public user turn, excluding future calls."""
    checkpoint = stream["checkpoints"][checkpoint_index]
    return {"request": copy.deepcopy(checkpoint),
            "sources": copy.deepcopy(stream["sources"][:checkpoint["source_count"]])}


def load_training_streams(root: Path, domains: list[str]) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]]]:
    """Check native membership before opening train bodies; never load task/env files."""
    streams, provenance = [], []
    for domain in domains:
        split = read_json(root / "state_bench/domains" / domain / "splits/train_test.json")
        train, test = split["splits"]["train"], split["splits"]["test"]
        directory = root / "datasets/train_task_trajectories" / domain
        if (len(set(train)) != len(train) or set(train) & set(test)
                or {path.stem for path in directory.glob("*.json")} != set(train)):
            raise ValueError("STATE public trajectories do not match the native train split")
        for ordinal, task_id in enumerate(train):
            path = directory / (task_id + ".json")
            stream = training_stream(read_json(path)["conversation"], domain, ordinal)
            streams.append(stream)
            provenance.append({"id": stream["id"], "domain": domain,
                "native_task_id": task_id, "native_split": "train", "source": str(path)})
    return streams, provenance
