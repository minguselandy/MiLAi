"""Replay a collected prefix against its original Source bank, then select actual delivery."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore

from collect_qasper_operation_states import no_refresh
from milai_lab.harness.artifact_io import read_json, read_jsonl
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations, controlled_reader_packet
from milai_lab.methods.evidence_reading import build_evidence_packs
from milai_lab.methods.memory_control import MemoryControlState
from milai_lab.methods.source_observations import SourceObservationBudget
from milai_lab.methods.source_ranges import SourceRangeBudget
from milai_lab.providers.contextual_capacity import HostCapacity


@contextmanager
def replay_collected_prefix(
    collection: Path,
    history: dict[str, Any],
    branch: dict[str, Any],
    settings: dict[str, Any],
    capacity: HostCapacity,
    on_state: Callable[..., None] | None = None,
) -> Iterator[tuple[EvidenceOperations, MemoryControlState]]:
    """Reexecute the recorded READ prefix once, without copying or repairing the Store.

    Recorded timing/budget projections are restored for exact input comparison;
    reexecution cost is measured by the caller, not substituted for original cost.
    Source revocation/revision or changed observations fail the actual replay.
    """
    root = collection / "banks" / history["id"]
    bank = Path(read_json(root / "report.json").get("source_bank_root", str(root)))
    request_id = branch["event_id"].rsplit("/", 2)[1]
    events = read_jsonl(root / f"{request_id}-operations.jsonl")
    mapping = read_json(root / "source-map.json")["mapping"]
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(
            store,
            ("scalable-evidence", history["id"], "collector"),
            "collector",
            bank / "lock",
            functional_contract="functional_v1",
        )
        state = MemoryControlState(**copy.deepcopy(events[0]["before"]))
        query = state.task["request"]
        ranges = SourceRangeBudget(
            256,
            capacity.text_tokens,
            lambda text: capacity.tokenizer(
                text, add_special_tokens=False, return_offsets_mapping=True
            )["offset_mapping"],
        )

        def pool() -> list[dict[str, Any]]:
            found = service.search_sources(
                query,
                source_refs=list(mapping),
                limit=16,
                tokenization="unicode_v1",
                include_scope=True,
            )
            return build_evidence_packs(
                service,
                query,
                state.task["query_time"],
                found["source_materials"],
                [],
                source_scope=found["source_scope"],
                source_range_budget=ranges,
                source_range_limit=16,
            )

        operations = EvidenceOperations(
            service,
            state,
            load_pool=pool,
            refresh_call=no_refresh,
            fits=lambda evidence: (
                capacity.text_tokens(
                    json.dumps(controlled_reader_packet(evidence, "collection"), ensure_ascii=False)
                )
                <= settings["ordinary_material_tokens"]
            ),
            internal_views=False,
            view_updates=False,
            delivery_selection=True,
            source_observation=SourceObservationBudget(2048, capacity.text_tokens),
        )
        for event in events:
            state.budget = copy.deepcopy(event["before"]["budget"])
            actions = operations.actions(state)
            if (
                state.project() != event["before"]
                or [asdict(a) for a in actions] != event["actions"]
            ):
                raise ValueError(
                    "Recorded Source prefix no longer recreates the same observation/menu"
                )
            if on_state is not None:
                on_state(operations, state, actions, event)
            action = next(a for a in actions if a.id == event["selected"])
            if action.kind == "HANDOFF":
                if (
                    state.project() != branch["before"]
                    or [asdict(a) for a in actions if a.kind == "HANDOFF"] != branch["actions"]
                ):
                    raise ValueError("Final acquired pool differs from its saved HANDOFF state")
                yield operations, state
                return
            actual = operations.execute(action, state)
            if actual != event["result"]:
                raise ValueError(
                    "Actual prefix result changed; do not repair the saved first outcome"
                )
            state.last_result = {"action": asdict(action), **actual}
        raise ValueError("The recorded prefix has no terminal HANDOFF")
