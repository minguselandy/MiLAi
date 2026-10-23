"""Evaluator-only snapshots of actual STATE dynamic retrieval decisions.

These are STATE captures, not functional-runner replay roots. The public Host
frame is observed before harness tool execution; the domain snapshot is taken
at retrieval time and can already include effects of earlier sibling tools.
"""
from __future__ import annotations

import copy
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import write_json
from milai_lab.runners.frozen_retrieval import RetrievalRecorder
from milai_lab.runners.state_bench_adapter import StateMemoryHook


def capture_state_retrieval(
    hook: StateMemoryHook, root: Path, *,
    domain_snapshot: Callable[[], dict[str, Any]],
    context: Callable[[], dict[str, Any]],
) -> RetrievalRecorder:
    """Install the existing recorder without changing requests or policy inputs.

    The runner owns serial harness execution. SQLite backup includes committed
    WAL contents; no raw database copy, fingerprint or forked ledger is used.
    Snapshot CPU is nested in the caller's already measured driver cost.
    """
    memory, service = hook.memory, hook.memory.service

    def snapshot(destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=False)
        with service._locked(), service.store.lock:
            with sqlite3.connect(destination / "memory.sqlite") as saved:
                service.store.conn.backup(saved)
        write_json(destination / "domain.json", domain_snapshot())

    def call_context() -> dict[str, Any]:
        return copy.deepcopy({**context(), "memory_protocol": "state_dynamic",
            "public_turn": hook.turn, "retrieval_ordinal": hook.calls,
            "runnable_config": hook.config, "known_references_before": hook.references,
            "admission_policy": memory._read_admission_policy(),
            "store": {"namespace": list(service.namespace), "owner": service.owner,
                "functional_contract": service.functional_contract,
                "memory_profile": service.memory_profile, "memory_ranking": service.memory_ranking},
            "config_version": hook.config_version,
            "frame_scope": "Actual public Host turn before its tool batch; domain snapshot at "
                "retrieval time. Sibling results appear only in later actual Host inputs. "
                "No answer feedback or counterfactual domain continuation is inferred."})

    recorder = RetrievalRecorder(root / "retrieval-snapshots", root, root,
        call_context, snapshot, capture_control_steps=True,
        call_schema="state_dynamic_retrieval_call_v1",
        decision_schema="state_dynamic_retrieval_decision_v1")
    memory.retrieval_observer = recorder
    memory.capture_control_steps = True
    return recorder
