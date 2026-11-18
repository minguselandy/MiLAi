"""Reopen recorded before states and prepare matched native Reader requests."""

from __future__ import annotations

import json
import time
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.dataset_corpus_runtime import CorpusExecution
from milai_lab.methods.evidence_control import controlled_reader_packet
from milai_lab.methods.memory_control import (
    FirstActionIntervention,
    FixedContextMemoryPolicy,
    run_memory_control,
)
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import given_packet_request, separate_answer_fields


def prepare_branches(
    dataset: MemoryControlDataset,
    state_id: int,
    action_ids: list[str] | None = None,
    *,
    before_search: bool = False,
) -> dict[str, Any]:
    """Invoke the real control/READ executor, stopping at each ready-to-send Host wire."""
    settings = json.loads(Path(dataset.config["views"]["reader_config"]).read_text())
    settings = settings["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    with closing(connect(dataset.path)) as db:
        observation, baseline, actions = dataset.replay(db, state_id)
        steps = observation["control_steps"]
        if before_search:
            baseline = CorpusExecution(
                baseline.pool,
                observation["query"],
                baseline.focus,
                dataset.reader,
                dataset.material_limit,
            )
            actions = baseline.menu(steps)
        before = baseline.online(actions)
        bound_by_id = {action.id: action for action in actions}
        if action_ids is None:
            contexts = [a for a in actions if a.parameters.get("expand_context")]
            chosen = contexts[0].parameters["index"] if contexts else None
            prefix = [f"read_{chosen}"] if f"read_{chosen}" in bound_by_id else []
            first = next((a.id for a in actions if a.kind != "HANDOFF"), None)
            action_ids = list(
                dict.fromkeys(
                    [
                        *(prefix or ([first] if first else [])),
                        *([contexts[0].id] if contexts else []),
                        "handoff",
                    ]
                )
            )
        if (
            not action_ids
            or len(set(action_ids)) != len(action_ids)
            or not set(action_ids) <= bound_by_id.keys()
        ):
            raise ValueError("Choose unique action IDs bound to this before state")
        results = []
        for action_id in action_ids:
            started, cpu_started = time.perf_counter(), time.process_time()
            _, branch, bound = dataset.replay(db, state_id, baseline.pool)
            if before_search:
                branch = CorpusExecution(
                    branch.pool,
                    observation["query"],
                    branch.focus,
                    dataset.reader,
                    dataset.material_limit,
                )
                bound = branch.menu(steps)
            if branch.online(bound) != before:
                raise ValueError("Branches require the identical legal before state")
            start_step = len(branch.prefix)
            continuation_steps = 2
            decision = run_memory_control(
                branch.state,
                FixedContextMemoryPolicy(4),
                branch,
                max_steps=steps,
                start_step=start_step,
                intervention=FirstActionIntervention(bound_by_id[action_id], continuation_steps),
            )
            if decision["trace"][0]["selected"] != action_id:
                raise ValueError("Executor chose a different bound intervention")
            # The next decision's before snapshot is the immediate post-action state.
            trace = decision["trace"]
            next_state = trace[1]["before"] if len(trace) > 1 else decision["state"]
            first_packet = controlled_reader_packet(
                next_state["visible_evidence"], "policy_handoff"
            )
            first_tokens = capacity.text_tokens(json.dumps(first_packet, ensure_ascii=False))
            packet = controlled_reader_packet(branch.ops.reader_evidence(), "policy_handoff")
            query = branch.state.task["request"]
            request = branch.state.task["retrieval_request"]
            wire = separate_answer_fields(
                given_packet_request({"content": query}, request, packet, settings)
            )
            checked = capacity.check(wire["messages"])
            material_tokens = capacity.text_tokens(json.dumps(packet, ensure_ascii=False))
            if material_tokens > dataset.material_limit:
                raise ValueError("Handoff exceeds the actual Reader material allowance")
            results.append(
                {
                    "bound_action": asdict(bound_by_id[action_id]),
                    "next_state": next_state,
                    "terminal_state": decision["state"],
                    "first_step_material": first_packet,
                    "trace": trace,
                    "control_reason": decision["reason"],
                    "delivered_material": packet,
                    "reader_wire": wire,
                    "reader_capacity_check": checked,
                    "execution_status": "reader_pending",
                    "task_result": None,
                    "costs": {
                        "material_tokens": material_tokens,
                        "first_step_material_tokens": first_tokens,
                        "local_wall_seconds": time.perf_counter() - started,
                        "local_cpu_seconds": time.process_time() - cpu_started,
                        "reader_input_tokens": None,
                        "reader_output_tokens": None,
                        "reader_wall_seconds": None,
                    },
                }
            )
        return {
            "dataset_run_id": dataset.run_id,
            "state_id": state_id,
            "before_search_derived": before_search,
            "task_id": observation["task_id"],
            "original_split": observation["split"],
            "group_id": observation["native_group"],
            "dataset": observation["dataset"],
            "continuation": "fixed_context_4_reads_two_more_decisions_then_handoff",
            "reader_calls": 0,
            "before": before,
            "branches": results,
        }
