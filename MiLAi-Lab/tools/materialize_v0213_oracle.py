"""Resolve pre-generation evaluator turn selections to exact original byte ranges."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from replay_v0213_cost import read, save, sha


def turn_ranges(text: str) -> list[tuple[int, int]]:
    decoder = json.JSONDecoder()
    cursor = text.index("[", text.index('"turns"')) + 1
    spans = []
    while True:
        while text[cursor].isspace() or text[cursor] == ",":
            cursor += 1
        if text[cursor] == "]":
            break
        _, end = decoder.raw_decode(text, cursor)
        spans.append((len(text[:cursor].encode()), len(text[:end].encode())))
        cursor = end
    return spans


def materialize(root: Path, spec_path: Path) -> None:
    spec = read(spec_path)
    for key, review in spec["tasks"].items():
        online = root / "online" / key
        index = read(online / "source-index.json")
        locations = []
        for selected in review["selections"]:
            sid = selected["source_id"]
            raw = (online / sid).read_bytes()
            assert sha(raw) == index[sid]
            spans = turn_ranges(raw.decode())
            locations.append({"source_id": sid, "source_version": sha(raw),
                              "start_byte": spans[selected["first_turn"]][0],
                              "end_byte": spans[selected["last_turn"]][1]})
        save(root / "evaluation" / key / "support-review.json", {
            **review, "locations": locations, "review_class": spec["review_class"],
            "spec_sha256": sha(spec_path.read_bytes())})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args()
    materialize(args.root, args.spec)
    print("ORACLE_ORIGINAL_SPANS_MATERIALIZED")
