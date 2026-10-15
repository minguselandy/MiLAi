"""Prepare identical source-grounded sequences for three matched SFT objectives."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai_lab.methods.semantic_delta import INSTRUCTIONS, delta_schema

WRAPPED_INSTRUCTIONS = INSTRUCTIONS + (
    " Wrap the edit envelope under delta and counterfactual outcomes under "
    "consequences. Counterfactuals ask about the rule; they do not change "
    "facts. Return {delta: ..., consequences: [...]}; use [] if absent. "
    "The supplied schema describes delta."
)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("references", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.references.read_text().splitlines() if line.strip()]
    prepared = []
    for row in rows:
        payload = {
            **row["input"],
            "response_schema": delta_schema(
                row["mapping"], allow_create=row["mapping"]["allow_create"]
            ),
            "counterfactuals": [
                {key: value for key, value in case.items() if key != "eligibility"}
                for case in row["consequence_targets"]
            ],
        }
        prepared.append(
            {
                "example_id": row["example_id"],
                "messages": [
                    {
                        "role": "system",
                        "content": WRAPPED_INSTRUCTIONS,
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    },
                ],
                "target": {
                    "delta": row["delta_target"],
                    "consequences": row["consequence_targets"],
                },
                "provenance": row["provenance"],
                "review": row["review"],
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in prepared))


if __name__ == "__main__":
    main()
