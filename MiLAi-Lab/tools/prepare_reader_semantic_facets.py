"""Project reviewed training-only semantic questions onto unchanged source text.

Facets and their explicit read states are offline annotations. They do not alter
the source's family/split or enter model-visible fields. Alias identities stay
fixed across the states of one facet; this is not a candidate permutation study.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.bounded_evidence import decision_payload
from reviewed_reader_supervision import reviewed_target


def facet_states(source: dict[str, Any], facet: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = source["metadata"]
    if metadata["split"] != "train" or facet["family"] != metadata["family"]:
        raise ValueError("Semantic facets must retain the original training family")
    paragraphs = {p["idx"]: p for p in source["source"]["paragraphs"]}
    pool = facet["pool_source_indices"]
    visible = [{"id": f"p{i}", "title": paragraphs[idx]["title"],
                "text": paragraphs[idx]["paragraph_text"]} for i, idx in enumerate(pool)]
    rows = []
    for index, opened in enumerate(facet["opened_states"]):
        target, status = reviewed_target(facet, pool, opened)
        payload = decision_payload(facet["question"],
            [p for idx, p in zip(pool, visible, strict=True) if idx in opened],
            [p for idx, p in zip(pool, visible, strict=True) if idx not in opened])
        rows.append({**payload, "gold": {"next": {"probabilities": target}} if target else {},
            "metadata": {"row": metadata["row"], "family": metadata["family"],
                "split": "train", "event_id": f"facet-{facet['facet']}-{index}",
                "facet": facet["facet"], "label_status": status,
                "pool_source_indices": pool, "opened_source_indices": opened,
                "training_allowed": True, "authored_question": True,
                "source_review_independent": False,
                "answer_for_offline_review_only": facet["expected_answer"]}})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path)
    parser.add_argument("facets", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sources = read_json(args.sources)
    protocol = read_json(args.facets)
    args.output.mkdir(parents=True, exist_ok=False)
    rows = [row for facet in protocol["facets"]
            for row in facet_states(sources[str(facet["source_row"])], facet)]
    (args.output / "train.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    write_json(args.output / "preparation.json", {
        "facets": len(protocol["facets"]), "states": len(rows),
        "families": len({r["metadata"]["family"] for r in rows}),
        "new_model_calls": 0, "training_started": False,
        "scope": "Author-reviewed training-only semantic contrasts; not benchmark QA."})


if __name__ == "__main__":
    main()
