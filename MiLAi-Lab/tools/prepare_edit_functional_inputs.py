"""Copy sealed r52 public inputs for the new candidate, without old digest metadata.

No model calls, memory initialization or scientific candidate admission occurs.
Original messages, source bodies/roles/IDs, retrieval ranges/order/scores and
offline controls are retained. Only retired source/candidate metadata is omitted.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json

COHORTS = (
    ("l1-r52", "l1-public"),
    ("l2-r52", "l2-public"),
    ("l3-formation-r52", "l3-formation-public"),
    ("l3-reading-r52", "l3-reading-public"),
    ("l4-r52", "l4-public"),
)


def prepare(legacy_root: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Use a new output directory; preserve earlier input copies")
    prepared = []
    for legacy_name, name in COHORTS:
        original_path = legacy_root / legacy_name / "input-freeze.json"
        frozen = read_json(original_path)
        fixture = copy.deepcopy(frozen["fixture"])
        sources, candidates, removed = 0, 0, 0
        for case in fixture["cases"]:
            for source in case.get("initial_sources", []):
                sources += 1
                if "content_sha256" in source:
                    source.pop("content_sha256")
                    removed += 1
            for candidate in case.get("retrieval_candidates", []):
                candidates += 1
                for field in ("source_sha256", "body_text_sha256", "span_sha256"):
                    if field in candidate:
                        candidate.pop(field)
                        removed += 1
        write_json(output / (name + ".json"), fixture)
        controls = frozen.get("evaluator_controls")
        if controls is not None:
            write_json(output / (name + "-controls.json"), controls)
        prepared.append({
            "original_input": str(original_path.resolve()),
            "fixture": name + ".json",
            "controls": name + "-controls.json" if controls is not None else None,
            "cases": len(fixture["cases"]),
            "public_messages": sum(len(c["messages"]) for c in fixture["cases"]),
            "raw_source_events": sources,
            "retrieval_candidates": candidates,
            "retired_digest_metadata_fields": removed,
        })
    manifest = {
        "input_version": "milai-edit-e5-historical-public-v1",
        "status": "PREPARED_INPUT_COPY_NOT_CANDIDATE_ADMISSION",
        "new_model_calls": 0,
        "semantic_memory_initialization": False,
        "new_post_freeze_stories": False,
        "cohorts": prepared,
    }
    write_json(output / "input-copy-manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.legacy_root, args.output)))


if __name__ == "__main__":
    main()
