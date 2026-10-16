"""Project chronologically arrived MemOps dialogue into the existing Writer runner.

Gold operations select offline diagnostic cut points only. Writer inputs contain
literal role/content and an explicit unknown source date, never gold targets,
operation labels, questions, corrected memory or generated dependency graphs.
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json

UNKNOWN_DATE = "unknown (source conversation calendar date not supplied)"


def project_prefix(sample: dict, segment: int, turn: int, identity: str) -> dict:
    seeds = []
    current = None
    coordinates = []
    for original in sorted(sample["conversations"], key=lambda row: row["segment_index"]):
        sid = original["segment_index"]
        if sid > segment:
            break
        past = original["dialogue"] if sid < segment else original["dialogue"][:turn - 1]
        if past:
            seeds.append({"session_id": f"{identity}-history-{sid}", "date": UNKNOWN_DATE,
                          "turns": [{"role": row["role"], "content": row["content"],
                                     "timestamp": "unknown"} for row in past]})
            coordinates.extend((sid, i + 1) for i in range(len(past)))
        if sid == segment:
            event = original["dialogue"][turn - 1]
            if event["role"] != "user":
                raise ValueError("The declared diagnostic arrival must be a real user turn")
            current = {"session_id": f"{identity}-arrival", "date": UNKNOWN_DATE,
                       "turns": [{"role": event["role"], "content": event["content"],
                                  "timestamp": "unknown"}]}
    if current is None:
        raise ValueError("Declared source turn is absent")
    return {"observations": {"seed": seeds, "update": current},
            "source_coordinates": {"seed": coordinates, "update": [segment, turn]},
            "calendar_policy": "Original data has no calendar timestamps. Do not invent an anchor.",
            "formation_policy": "Real Writer formation on chronological prior segment batches; "
                                "not an independent per-turn trajectory."}


def prepare(config: dict, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    settings = copy.deepcopy(read_json(Path(config["settings_source"]))["settings"])
    settings["halumem"] = {"reader_failure_policy": "record_known_readonly_failure"}
    settings.update(read_usage_updates=False, dependency_reading=False)
    cases, evaluation = [], []
    assignments = read_json(Path(config["family_manifest"]))["families"]
    for index, selection in enumerate(config["cases"]):
        source = Path(config["data_root"]) / selection["file"]
        family = source.stem.split("_", 1)[0]
        if assignments[family] != "train":
            raise ValueError("This source-reviewed development slice uses training families only")
        sample = read_json(source)
        projected = project_prefix(sample, *selection["arrival"], f"history-{index + 1:02d}")
        case = {"id": selection["id"], "owner": f"jev-writer-{index + 1:02d}",
                "observations": projected["observations"], "queries": selection["queries"]}
        cases.append(case)
        evaluation.append({"id": case["id"], "source": str(source.resolve()),
                           "family": family, "split": assignments[family],
                           **{k: v for k, v in projected.items() if k != "observations"},
                           "operations_at_arrival": [op for op in sample["operations"]
                               if [op["trigger_span"]["segment_index"],
                                   op["trigger_span"]["turn_index"]] == selection["arrival"]],
                           "review": selection["review"]})
    protocol = {"status": "PREPARED_ZERO_MODEL", "config": {"name": config["name"]},
                "settings": settings, "cases": cases,
                "scope": "MemOps training-family shared-before diagnostic; no gold-state repair",
                "queries_to_writer": False, "unknown_retry": False}
    write_json(output / "prepared.json", protocol)
    write_json(output / "evaluation-only.json", evaluation)
    write_json(output / "source-config.json", config)
    return protocol


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(read_json(args.config), args.output)


if __name__ == "__main__":
    main()
