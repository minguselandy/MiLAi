"""Explicit ancestry for LME continuation runs; earlier attempts are never rewritten."""

from pathlib import Path

from milai_lab.harness.artifact_io import read_json


def prediction_roots(predictions: Path) -> list[Path]:
    """Current collection and its declared parents, with the same frozen method and cohort."""
    current = predictions.resolve()
    original = read_json(current / "driver.json")
    ids = [c["question_id"] for c in original["cases"]]
    roots = [current]
    row = original
    while row.get("continued_from") is not None:
        current = Path(row["continued_from"]).resolve()
        if current in roots:
            raise ValueError("Prediction continuation ancestry contains a cycle")
        row = read_json(current / "driver.json")
        if (
            row["source_version"] != original["source_version"]
            or [c["question_id"] for c in row["cases"]] != ids
        ):
            raise ValueError("Continuation changed its frozen method or complete cohort")
        roots.append(current)
    return roots
