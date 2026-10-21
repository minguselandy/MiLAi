"""Explicit task mixtures without changing source splits or model-visible examples."""
from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict
from typing import Any


def event_weights(rows: list[dict[str, Any]]) -> list[float]:
    keys = [(r["metadata"]["family"],
             r["metadata"].get("training_event", r["metadata"]["row"])) for r in rows]
    counts = Counter(keys)
    events: dict[str, set[int | str]] = defaultdict(set)
    for family, event in counts:
        events[family].add(event)
    return [len(rows) / len(events) / len(events[family]) / counts[family, event]
            for family, event in keys]


def normalized_mixture(weights: dict[str, float]) -> dict[str, float]:
    if not weights or any(not math.isfinite(v) or v <= 0 for v in weights.values()):
        raise ValueError("Mixture components require positive finite loss weights")
    total = sum(weights.values())
    return {name: value / total for name, value in weights.items()}


def mixture_event_weights(rows: list[dict[str, Any]], masses: dict[str, float]) -> list[float]:
    """Uniform row draws, with declared loss mass per component then family/event."""
    masses = normalized_mixture(masses)
    indices: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        indices[row["metadata"]["component"]].append(i)
    if set(indices) != set(masses):
        raise ValueError("Labelled training components differ from the declared mixture")
    result = [0.0] * len(rows)
    for component, positions in indices.items():
        local = event_weights([rows[i] for i in positions])
        scale = len(rows) * masses[component] / len(positions)
        for index, weight in zip(positions, local, strict=True):
            result[index] = scale * weight
    return result


def combine_components(components: list[dict[str, Any]]) -> tuple[
    dict[str, list[dict[str, Any]]], dict[str, float],
]:
    """Retain every raw example, including masks; assign IDs before filtering."""
    data: dict[str, list[dict[str, Any]]] = {"train": [], "dev": []}
    weights: dict[str, float] = {}
    seen: set[tuple[str, str]] = set()
    family_splits: dict[str, str] = {}
    question_ids = {"memory_operation": "next", "instruction_applicability": "applicability"}
    for component in components:
        name, task = component["name"], component["task"]
        if name in weights:
            raise ValueError("Duplicate mixture component")
        weights[name] = float(component["loss_weight"])
        question_id = question_ids[task]
        for original in component["rows"]:
            row = copy.deepcopy(original)
            metadata = row["metadata"]
            split, family = metadata["split"], metadata["family"]
            if set(row["questions"]) != {question_id}:
                raise ValueError("Example question does not match its declared task")
            identity = (task, metadata["event_id"])
            if identity in seen:
                raise ValueError("Duplicate task example in the mixture")
            seen.add(identity)
            previous = family_splits.setdefault(family, split)
            if previous != split:
                raise ValueError("A source family crosses training and development")
            metadata.update(task=task, component=name)
            data[split].append(row)
    masses = normalized_mixture(weights)
    labelled_components = {r["metadata"]["component"] for r in data["train"] if r["gold"]}
    if labelled_components != set(masses):
        raise ValueError("Every mixture component needs labelled training examples")
    for state_identity, row in enumerate([*data["train"], *data["dev"]]):
        row["metadata"]["state_id"] = state_identity
    return data, masses


def project_mixed_row(row: dict[str, Any], projection: str) -> dict[str, Any]:
    from milai_lab.memory.request_text import project_request_text
    from milai_lab.methods.laya_memory_policy import project_operation_payload

    task = row["metadata"]["task"]
    if task == "memory_operation":
        return project_operation_payload(row, projection)
    if task == "instruction_applicability":
        return project_request_text(row) if projection in {
            "shared_request_text", "shared_actions_request_text"} else row
    raise ValueError(f"Unsupported retrieval training task: {task}")


def score_mixed_predictions(
    rows: list[dict[str, Any]], predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    from evaluate_bounded_laya import score_applicability_predictions
    from milai_lab.methods.memory_control_learning import score_operation_predictions

    scorers = {"memory_operation": score_operation_predictions,
               "instruction_applicability": score_applicability_predictions}
    tasks: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    components: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for row, prediction in zip(rows, predictions, strict=True):
        tasks[row["metadata"]["task"]].append((row, prediction))
        components[row["metadata"]["component"]].append((row, prediction))

    def score(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
        group_rows, group_predictions = zip(*pairs, strict=True)
        task = group_rows[0]["metadata"]["task"]
        return scorers[task](list(group_rows), list(group_predictions))

    return {"by_task": {name: score(pairs) for name, pairs in tasks.items()},
            "by_component": {name: score(pairs) for name, pairs in components.items()},
            "scope": "Task-specific native diagnostics; no combined memory score or Host success"}
