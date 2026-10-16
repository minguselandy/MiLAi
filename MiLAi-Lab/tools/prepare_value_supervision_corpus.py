"""Capture canonical LongMemEval histories and nominate offline outcome subsets.

No generation or embedding client is created. Gold support-session metadata is
used only after the actual pool exists, for offline supervision configurations.
"""

from __future__ import annotations

import argparse
import copy
import json
import time
import uuid
from pathlib import Path

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.datasets.edit_benchmarks import (
    history_components,
    longmemeval_cases,
    longmemeval_history,
)
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import build_evidence_packs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", type=Path)
    parser.add_argument("base_settings", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    protocol = read_json(args.selection)
    settings = copy.deepcopy(read_json(args.base_settings))
    settings.update(
        experiment_name=protocol["name"],
        config_version=protocol["name"],
        evidence_selection_policy="standard",
        evidence_variant="S0",
    )
    settings.pop("query_structure_policy", None)
    settings["longmemeval"].update(path=protocol["dataset"], questions=protocol["questions"])
    settings["alignment_bank_ids"] = {
        key: "value-supervision-" + uuid.uuid4().hex for key in protocol["questions"]
    }
    args.output.mkdir(parents=True)
    write_json(args.output / "actual-config.json", settings)
    cases = longmemeval_cases(Path(protocol["dataset"]), protocol["questions"])
    records = []
    for case in cases:
        started = time.perf_counter()
        owner = case["question_id"]
        bank_id = settings["alignment_bank_ids"][owner]
        bank = args.output / "banks" / bank_id
        bank.mkdir(parents=True)
        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
            service = MemoryService(
                store,
                ("edit", args.output.name, "ordinary", bank_id, owner),
                owner,
                bank / "memory.lock",
                functional_contract="functional_v1",
                memory_profile=settings["memory_profile"],
                memory_ranking=settings["memory_ranking"],
            )
            for observed in longmemeval_history(case):
                for index, turn in enumerate(observed.turns):
                    capture = (
                        service.capture_user
                        if turn["role"] == "user"
                        else service.capture_assistant
                    )
                    receipt = capture(
                        observed.session_id,
                        f"turn:{index}",
                        turn["content"],
                        occurred_at=turn["timestamp"],
                        calendar_context=settings.get("calendar_context"),
                    )
                    if not receipt["ok"]:
                        raise ValueError("Actual source capture did not complete")
                    if turn["role"] == "user":
                        service.bind_public_turn(
                            observed.session_id,
                            f"turn:{index}",
                            receipt["source_ref"],
                            config_version=protocol["name"],
                            phase="start",
                        )
            native = service.search_sources(
                case["question"],
                limit=settings["source_top_k"],
                tokenization=settings["source_tokenization"],
                granularity=settings["source_granularity"],
                include_scope=True,
            )
            materials = build_evidence_packs(
                service,
                case["question"],
                case["question_date"],
                native["source_materials"],
                [],
                tokenization=settings["source_tokenization"],
                calendar_context=settings.get("calendar_context"),
                source_scope=native["source_scope"],
            )
            write_json(
                args.output / "native/longmemeval" / owner / "answer/retrieval.json",
                {
                    "materials": materials,
                    "native_return": native,
                    "usage": {"model_calls": 0, "embedding_calls": 0},
                },
            )
            # This metadata is never inserted into Sources or Reader packets.
            support_sessions = list(dict.fromkeys(case["answer_session_ids"]))
            support = [
                next(i for i, material in enumerate(materials) if material["session_id"] == sid)
                for sid in support_sessions
            ]
            noise = next(
                i
                for i, material in enumerate(materials)
                if material["session_id"] not in support_sessions
            )
            conditions = [{"name": "empty", "indices": [], "expand_context": []}]

            def condition(name, indices):
                return {"name": name, "indices": indices, "expand_context": indices}

            if len(support) == 2:
                conditions.extend(
                    [
                        condition("support_0", [support[0]]),
                        condition("support_1", [support[1]]),
                        condition("both", support),
                        condition("both_plus_neighbor", [*support, noise]),
                    ]
                )
            else:
                second_noise = next(
                    i
                    for i, material in enumerate(materials)
                    if material["session_id"]
                    not in [*support_sessions, materials[noise]["session_id"]]
                )
                conditions.extend(
                    [
                        condition("support", support),
                        condition("neighbor", [noise]),
                        condition("support_plus_neighbor", [*support, noise]),
                        condition("second_neighbor", [second_noise]),
                    ]
                )
            equivalent = next(
                (
                    i
                    for i, material in enumerate(materials)
                    if material["session_id"] == support_sessions[0] and i != support[0]
                ),
                None,
            )
            if equivalent is not None:
                conditions.append(condition("equivalent_parent", [equivalent, *support[1:]]))
            outcome = {
                "name": f"{protocol['name']}-{owner}",
                "source_run": str(args.output),
                "question_id": owner,
                "conditions": conditions,
                "scope": "Offline support-session nominations on an actual saved pool; "
                "not a selector's achieved performance or a held-out result.",
            }
            write_json(args.output / "outcome-configs" / f"{owner}.json", outcome)
            records.append(
                {
                    "question_id": owner,
                    "sessions": len(case["haystack_sessions"]),
                    "sources": len(service.sources()),
                    "materials": len(materials),
                    "conditions": len(conditions),
                    "semantic_records": len(service.records()),
                    "wall_seconds": time.perf_counter() - started,
                }
            )
            write_json(args.output / "preparation.json", {"status": "RUNNING", "cases": records})
            print(json.dumps(records[-1]), flush=True)
    write_json(
        args.output / "preparation.json",
        {
            "status": "COMPLETED_ZERO_MODEL",
            "cases": records,
            "model_calls": 0,
            "embedding_calls": 0,
            "parameter_updates": 0,
            "history_overlap_components": history_components(cases),
            "scope": "Canonical observed histories omit has_answer metadata. Current questions are "
            "used only for read retrieval; support-session labels nominate offline subsets. "
            "No teacher outcomes, training or independent-accuracy result yet.",
        },
    )


if __name__ == "__main__":
    main()
