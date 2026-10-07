"""Run declared exposed development histories on each arm's own empty bank."""

from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore

from milai_lab.datasets.edit_benchmarks import ObservedSession
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.runners.edit_benchmarks import BenchmarkRun


def observation(arm: str, ordinal: int, event: dict[str, Any]) -> ObservedSession:
    """Only observed speech and its date enter the Writer."""
    turns = (
        tuple({"role": turn["role"], "content": turn["content"],
               "timestamp": turn.get("timestamp")}
              for turn in event["observed_dialogue"])
        if "observed_dialogue" in event
        else ({"role": "user", "content": event["observed_user_text"],
               "timestamp": event["date"]},)
    )
    if any(turn["role"] not in {"user", "assistant"} for turn in turns):
        raise ValueError("This dialogue driver supports user and assistant observations only")
    return ObservedSession(
        f"r3-development:{arm}:{ordinal}", event["date"], turns,
    )


def reader_questions(event: dict[str, Any]) -> list[str]:
    """Questions are evaluated after maintenance, never included in observations."""
    if "reader_questions" in event:
        return list(event["reader_questions"])
    question = event.get("reader_question")
    return [] if question is None else [question]


def run_history(
    config: Path, inputs: Path, output: Path, source_version: str, *, prepare: bool = False
) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Preserve prior attempts; use a new declared output")
    settings, declared = read_json(config), read_json(inputs)
    if settings.get("method_version") != "milai_edit_v2":
        raise ValueError("Use the selected v2 common configuration")
    if settings.get("interface_version") not in {"I1", "I2"}:
        raise ValueError("Use a reviewed common interface")
    arms = declared["arms"]
    if arms != ["B0", "B1", "B2", "M"] or declared["candidate_selected"]:
        raise ValueError("This is four-arm development, not final candidate confirmation")
    expected = len(arms) * (
        len(declared["events"])
        + sum(len(reader_questions(event)) for event in declared["events"])
    )
    if expected != declared["expected_generation_calls"]:
        raise ValueError("Declared Writer and Reader counts differ")
    settings.pop("arms", None)
    variant = declared.get("variant", "UNRESTATED_PRESERVATION_AND_WITHDRAWAL")
    settings.update(
        arm="M", experiment_name="milai-edit-v2-exposed-r3-development-" + variant,
        evidence_kind="EXPOSED_R3_BEHAVIOR_DEVELOPMENT_NOT_CONFIRMATION",
    )
    metadata = {
        "source_version": source_version, "common_interface": settings["interface_version"],
        "config_version": settings["config_version"], "config": str(config),
        "declared_inputs": str(inputs), "story_clusters": declared["story_clusters"],
        "variant": variant, "expected_generation_calls": expected,
        "ideal_state_injected": False, "candidate_selected": False,
        "independent_confirmation": False,
    }
    if prepare:
        metadata.update(status="PREPARED_EXPOSED_DEVELOPMENT_NOT_RUN", actual_model_calls=0)
        write_json(output / "source-and-interface.json", metadata)
        write_json(output / "writer-observations.json", {
            arm: [asdict(observation(arm, index, event))
                  for index, event in enumerate(declared["events"])] for arm in arms
        })
        return metadata

    run = BenchmarkRun(settings, output)
    before = copy.deepcopy(run.budget.state)
    unknown_before = (before["generation"]["unknown_usage"], before["embedding"]["unknown_usage"])
    rows: list[dict[str, Any]] = []
    status = "STOPPED_EXPOSED_R3_DEVELOPMENT_FAILURE"
    try:
        write_json(output / "declared-inputs-evaluator-only.json", declared)
        write_json(output / "source-and-interface.json", {
            **metadata, "status": "RUNNING_EXPOSED_R3_DEVELOPMENT",
        })
        for arm in arms:
            root = output / "banks" / arm
            root.mkdir(parents=True)
            run.settings = {**settings, "arm": arm}
            with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
                service = MemoryService(
                    store, ("r3-development", arm, "owner"), "owner", root / "memory.lock",
                    mutation_contract="event_bound_v1", candidate_contract="read_handle_v1",
                    semantic_retriever=run._semantic_retriever(),
                )
                if service.records():
                    raise ValueError("Each arm must form its own initial state")
                for ordinal, event in enumerate(declared["events"]):
                    key = f"observed/{arm}/{ordinal}"
                    old_state = copy.deepcopy(service.records())
                    run.maintain(service, observation(arm, ordinal, event), key)
                    current_state = copy.deepcopy(service.records())
                    questions = reader_questions(event)
                    answers = []
                    for question_index, question in enumerate(questions):
                        qa_key = f"qa/{arm}/{ordinal}"
                        if len(questions) > 1:
                            qa_key += f"/{question_index}"
                        answers.append(run.answer(
                            service, question, event["date"], qa_key
                        ))
                        if service.records() != current_state:
                            raise RuntimeError("Reader changed stored records")
                    row = {
                        "arm": arm, "event": ordinal, "event_id": event["event_id"],
                        "before": old_state, "after": current_state,
                        "maintenance": read_json(output / "maintenance" / key / "complete.json"),
                        "reader_answer": answers[0] if len(answers) == 1 else None,
                        "reader_state_unchanged": True,
                    }
                    if len(questions) > 1:
                        row["reader_answers"] = [
                            {"question": question, "answer": answer}
                            for question, answer in zip(questions, answers, strict=True)
                        ]
                    rows.append(row)
                    write_json(output / "actual-behavior.json", rows)
                    state = run.budget.state
                    unknown_now = (
                        state["generation"]["unknown_usage"], state["embedding"]["unknown_usage"]
                    )
                    if unknown_now != unknown_before:
                        raise RuntimeError("New unknown model usage; stop without replay")
        status = "COMPLETED_EXPOSED_R3_ATTEMPTS_AWAITING_ROOT_SEMANTIC_REVIEW"
    except BaseException as error:
        write_json(output / "failure.json", {"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        end = run.budget.state
        terminal = {
            **metadata, "status": status, "completed_event_rows": len(rows),
            "new_generation_requests": end["generation_requests"] - before["generation_requests"],
            "new_known_tokens": (
                end["generation"]["known_tokens"] - before["generation"]["known_tokens"]
            ),
            "historical_generation_unknown_usage": unknown_before[0],
            "historical_embedding_unknown_usage": unknown_before[1],
            "new_generation_unknown_usage": end["generation"]["unknown_usage"] - unknown_before[0],
            "new_embedding_unknown_usage": end["embedding"]["unknown_usage"] - unknown_before[1],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        write_json(output / "terminal.json", terminal)
        run.close()
    return terminal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "inputs", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source-version", required=True, help="Ordinary recorded Git version")
    parser.add_argument("--prepare", action="store_true", help="Validate declaration without HTTP")
    args = parser.parse_args()
    run_history(args.config, args.inputs, args.output, args.source_version, prepare=args.prepare)


if __name__ == "__main__":
    main()
