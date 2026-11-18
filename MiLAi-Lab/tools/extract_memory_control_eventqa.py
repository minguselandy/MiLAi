"""Export public full EventQA inputs and separate scoring references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pyarrow import parquet  # type: ignore[import-not-found] -- local Parquet export environment


def write_json(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(content, ensure_ascii=False, allow_nan=False) + "\n")
    part.replace(path)


def export(path: Path, revision: str, public: Path, references: Path) -> None:
    table = parquet.ParquetFile(path)
    inputs = table.read(columns=["context", "questions", "metadata"]).to_pylist()
    target_columns = table.read(columns=["answers"]).to_pylist()
    contexts = []
    labels = {}
    for ordinal, (row, scoring) in enumerate(zip(inputs, target_columns, strict=True)):
        metadata = row["metadata"]
        if metadata["source"] != "eventqa_full":
            continue
        native_ids = metadata["qa_pair_ids"]
        if len(set(native_ids)) != len(native_ids) or not native_ids:
            raise ValueError("EventQA question IDs must be unique within each source row")
        group = f"eventqa-full-row-{ordinal}"
        for native_id, _, answer in zip(
            native_ids, row["questions"], scoring["answers"], strict=True
        ):
            if (
                not isinstance(answer, list)
                or not answer
                or not all(isinstance(x, str) and x for x in answer)
            ):
                raise ValueError("EventQA references must contain nonempty answer text")
            labels[f"{group}/{native_id}"] = answer
        contexts.append(
            {
                "source_row": ordinal,
                "context": row["context"],
                "questions": row["questions"],
                "qa_pair_ids": native_ids,
            }
        )
    if not labels:
        raise ValueError("The Accurate Retrieval release contains no full EventQA rows")
    write_json(
        public,
        {
            "dataset": "ai-hyz/MemoryAgentBench",
            "source_revision": revision,
            "split": "Accurate_Retrieval",
            "source": "eventqa_full",
            "contexts": contexts,
        },
    )
    write_json(references, {"source_revision": revision, "labels": labels})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    args = parser.parse_args()
    if len({x.resolve() for x in (args.parquet, args.public, args.references)}) != 3:
        parser.error("use separate paths for Parquet, public inputs, and scoring references")
    export(args.parquet, args.source_revision, args.public, args.references)
    print(f"Exported EventQA public inputs to {args.public}")


if __name__ == "__main__":
    main()
