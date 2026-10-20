"""Place declared Host requests between original, ordered training-source arrivals."""
from __future__ import annotations

import argparse
import copy
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def prepare_streams(fixture: dict[str, Any], recipe: dict[str, Any]) -> dict[str, Any]:
    histories = {history["id"]: history for history in fixture["histories"]}
    streams = []
    for specification in recipe["streams"]:
        history = histories[specification["history_id"]]
        if history["split"] != "train" or not history.get("continuous"):
            raise ValueError("Short-flow development requires a continuous training history")
        arrivals = [source for request in history["requests"]
                    for source in request.get("incoming_sources", [])]
        previous = 0
        requests = []
        for position in specification["requests"]:
            end = position["after_sources"]
            if not previous <= end <= len(arrivals):
                raise ValueError("Arrival boundaries must preserve the source sequence")
            requests.append({**{key: copy.deepcopy(value) for key, value in position.items()
                                if key != "after_sources"},
                             "incoming_sources": copy.deepcopy(arrivals[previous:end])})
            previous = end
        if previous != len(arrivals):
            raise ValueError("The declared stream must retain all original arrivals")
        streams.append({"id": specification["id"], "source_group": history["source_group"],
                        "split": history["split"], "continuous": True,
                        "sources": copy.deepcopy(history["sources"]), "requests": requests})
    return {"schema": "host_intent_stream_histories_v1",
            "scope": recipe["scope"], "histories": streams}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("histories", type=Path)
    parser.add_argument("recipe", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    fixture, recipe = read_json(args.histories), read_json(args.recipe)
    streams = prepare_streams(fixture, recipe)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "histories.json", streams)
    write_json(args.output / "preparation.json", {
        "status": "PREPARED_NOT_EXECUTED", "source_fixture": str(args.histories),
        "recipe": str(args.recipe),
        "source_groups": [h["source_group"] for h in streams["histories"]],
        "positions": sum(len(h["requests"]) for h in streams["histories"]),
        "original_source_order_and_content": "Retained by direct slicing; no source rewriting",
        "prebuilt_views": 0, "model_calls": 0,
        "compute": {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu},
        "ledger_recorded": False})


if __name__ == "__main__":
    main()
