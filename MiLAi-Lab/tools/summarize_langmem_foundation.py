"""Summarize frozen LangMem results and attributed trace usage without model access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from milai_lab.harness.contextual_artifacts import read_json, write_json


def _empty_usage() -> dict[str, Any]:
    return {
        "generation_requests": 0,
        "generation_input_tokens": 0,
        "generation_output_tokens": 0,
        "generation_known_tokens": 0,
        "generation_unknown_usage": 0,
        "embedding_requests": 0,
        "embedding_input_tokens": 0,
        "embedding_output_tokens": 0,
        "embedding_known_tokens": 0,
        "embedding_unknown_usage": 0,
        "provider_wall_seconds": 0.0,
        "capacity_rejections": 0,
    }


def _usage(trace_path: Path, run_id: str) -> dict[str, Any]:
    by_episode: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in trace_path.read_text().splitlines():
        event = json.loads(line)
        if event["event"] == "foundation_context":
            current = event if event["run_id"] == run_id else None
            continue
        if current is None or event["event"] not in {
            "vllm_response", "vllm_error", "vllm_capacity_rejected",
        }:
            continue
        episode_key = f"{current['user_id']}/{current['episode_id']}"
        entry = by_episode.setdefault(episode_key, {
            **_empty_usage(), "user_id": current["user_id"], "public_messages": {},
        })
        public_index = str(current["public_index"])
        message = entry["public_messages"].setdefault(public_index, _empty_usage())
        if event["event"] == "vllm_capacity_rejected":
            entry["capacity_rejections"] += 1
            message["capacity_rejections"] += 1
            continue
        kind = "embedding" if event["path"] == "embeddings" else "generation"
        usage = event.get("usage")
        for target in (entry, message):
            target[f"{kind}_requests"] += 1
            target["provider_wall_seconds"] += event.get("wall_seconds", 0.0)
            if isinstance(usage, dict) and type(usage.get("total_tokens")) is int:
                target[f"{kind}_known_tokens"] += usage["total_tokens"]
            else:
                target[f"{kind}_unknown_usage"] += 1
            if isinstance(usage, dict):
                for source, destination in (("prompt_tokens", "input_tokens"),
                                            ("completion_tokens", "output_tokens")):
                    if type(usage.get(source)) is int:
                        target[f"{kind}_{destination}"] += usage[source]
    return by_episode


def summarize(
    mode: str, results: Path, trace: Path, run_id: str, budget: Path | None = None,
) -> dict[str, Any]:
    identity = read_json(results / "run-identity.json")
    if identity["run_id"] != run_id:
        raise ValueError("FOUNDATION_SUMMARY_RUN_ID_CHANGED")
    result_path = results / "result.json"
    if mode == "merit" and not result_path.exists():
        aggregate = read_json(results / "interruption.json")
        interrupted = True
    else:
        aggregate = read_json(result_path)
        interrupted = False
    usage = _usage(trace, run_id)
    if mode == "merit":
        paths = sorted(
            (path for path in (results / "episodes").glob("episode-*.json")
             if not path.name.endswith(".progress.json")),
            key=lambda path: int(path.stem.split("-")[1]),
        )
        rows = [read_json(path) for path in paths]
        items = [{
            "episode_index": row["episode_index"],
            "task_id": row["task_id"],
            "native_score": row["native_score"],
            "usage": usage.get(
                f"merit:{identity['arc_id']}/episode:{row['episode_index']}", {}
            ),
        } for row in rows]
        declared = (aggregate["original_denominator"] if interrupted
                    else aggregate["native_denominator"])
        terminal = len(items)
        interrupted_items = 1 if interrupted else 0
        executed = terminal + interrupted_items
    else:
        items = [{
            "case_id": case["id"],
            "status": case["status"],
            "sessions": [
                {"session_id": session["session_id"],
                 "usage": usage.get(
                     f"diagnostic:{case['id']}/session:{session['session_id']}", {}
                 )}
                for session in read_json(results / case["id"] / "result.json")["sessions"]
            ],
        } for case in aggregate["cases"]]
        declared = aggregate["declared_case_count"]
        executed = len(items)
        terminal = sum(item["status"] == "TERMINAL" for item in items)
        interrupted_items = executed - terminal
    return {
        "run_id": run_id,
        "mode": mode,
        "recipe_id": identity["recipe_id"],
        "result": aggregate,
        "status": "INTERRUPTED_UNSCORED" if interrupted else aggregate.get("status", "TERMINAL"),
        "declared_items": declared,
        "executed_items": executed,
        "terminal_items": terminal,
        "interrupted_items": interrupted_items,
        "items": items,
        "attributed_usage_by_episode": usage,
        "continuous_budget": read_json(budget) if budget is not None else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("merit", "diagnostic"), required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--budget", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.mode, args.results, args.trace, args.run, args.budget)
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output), "terminal_items": result["terminal_items"]}))


if __name__ == "__main__":
    main()
