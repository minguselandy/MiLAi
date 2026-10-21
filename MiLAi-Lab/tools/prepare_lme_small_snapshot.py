"""Copy the complete released Small haystacks and referenced images, without hashes."""
from __future__ import annotations

import argparse
import json
import resource
import shutil
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json


def prepare_snapshot(source: Path, output: Path) -> dict[str, Any]:
    """Retain every question and every state of every Small-selected trajectory."""
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {"status": "PREPARING", "source": str(source.resolve()),
        "output": str(output.resolve()), "tier": "small", "model_calls": 0,
        "checksum_verification": False, "ledger_recorded": False}
    write_json(output / "preparation.json", report)
    try:
        questions = read_jsonl(source / "questions.jsonl")
        haystacks = read_json(source / "haystacks/lme_v2_small.json")
        if set(haystacks) != {row["id"] for row in questions}:
            raise ValueError("Small mapping must cover every released question")
        selected = {identity for items in haystacks.values() for identity in items}
        report.update(questions=len(questions), selected_trajectories=len(selected),
                      retained_trajectories=0, scanned_trajectories=0, retained_states=0)
        (output / "haystacks").mkdir()
        shutil.copy2(source / "questions.jsonl", output / "questions.jsonl")
        shutil.copy2(source / "haystacks/lme_v2_small.json", output / "haystacks/lme_v2_small.json")
        assets = {row["image"] for row in questions if row["image"] is not None}
        report["question_images"] = len(assets)
        found = set()
        with (source / "trajectories.jsonl").open("rb") as stream, (
            output / "trajectories.jsonl").open("xb") as destination:
            for line in stream:
                row = json.loads(line)
                report["scanned_trajectories"] += 1
                if row["id"] not in selected:
                    continue
                destination.write(line)  # Keep the entire literal released record.
                found.add(row["id"])
                report["retained_trajectories"] += 1
                report["retained_states"] += len(row["states"])
                assets.update(state["screenshot"] for state in row["states"]
                              if state["screenshot"] is not None)
        if found != selected:
            raise ValueError("A Small-selected trajectory is missing from the release")
        report.update(assets=len(assets), copied_assets=0, copied_image_bytes=0)
        for name in sorted(assets):
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Released screenshot path must be relative to the data root")
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, target)
            report["copied_assets"] += 1
            report["copied_image_bytes"] += target.stat().st_size
            if report["copied_assets"] % 500 == 0:
                write_json(output / "preparation.json", report)
                print(json.dumps({"copied_assets": report["copied_assets"],
                                  "assets": report["assets"]}), flush=True)
        report.update(status="COMPLETE_SMALL_SNAPSHOT", scope=(
            "All released questions and their unchanged Small mappings; full selected "
            "trajectory records and all referenced images copied independently. "
            "Unselected trajectories belong to other tiers and are not in Small. "
            "No question/answer/history/image contents displayed or used for training."))
    except BaseException as error:
        report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        report.update(wall_seconds=time.perf_counter() - started,
                      cpu_seconds=time.process_time() - cpu,
                      peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        write_json(output / "preparation.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_snapshot(args.source, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
