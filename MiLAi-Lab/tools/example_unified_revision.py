"""Synthetic SQLite revision lifecycle; no model, encoder or business transport.

Run with PYTHONPATH=src python tools/example_unified_revision.py. The explicit
proposals stand in for a caller's transport to demonstrate actual committed
relations and supported metadata, not natural-language model quality.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_memory import EditMemory


def statement(text: str, **applicability: str) -> dict[str, Any]:
    assertion: dict[str, Any] = {
        "source": "e1", "kind": "reported", "evidence_links": {"supports": ["e1"]},
    }
    if applicability:
        assertion["applicability"] = applicability
    return {"text": text, "evidence": ["e1"], "assertion": assertion}


def event(
    service: MemoryService,
    method: EditMemory,
    key: str,
    text: str,
    reported_at: str,
    proposal: dict[str, Any],
    record_id: str | None = None,
) -> dict[str, Any]:
    ref = service.capture_user("example", key, text, occurred_at=reported_at)["source_ref"]
    service.bind_source_boundary("example", key, [ref])
    rows = [service.read(record_id)] if record_id else []
    request = method.writer_request(
        method.prepare([ref], text, selected_records=rows), request_id=key
    )
    envelope = (
        {"creates": [proposal], "records": {}}
        if record_id is None else {"creates": [], "records": {"r1": proposal}}
    )
    decoded = method.decode_envelope(envelope, request["mapping"])[0]
    receipt = method.apply("example", "commit-" + key, decoded)
    assert receipt["ok"], receipt
    return receipt


def run(root: Path) -> dict[str, Any]:
    features = EditFeatures(
        matter_organization=True, semantic_operations=True, bound_references=True,
        single_record_changes=True, source_metadata=True, temporal_scope=True,
    )
    with SqliteStore.from_conn_string(str(root / "revision.sqlite")) as store:
        service = MemoryService(
            store, ("unified-example", "shift-worker"), "shift-worker", root / "lock",
            mutation_contract="event_bound_v1", candidate_contract="read_handle_v1",
        )
        method = EditMemory(service, "M", interface_version="I2", features=features)
        saved = event(
            service, method, "general",
            "From October 1 inclusive to October 8 exclusive, each shift has two training "
            "rounds and starts training at 08:00.",
            "2025-10-01T07:00:00Z",
            {
                "action": "create", "matter": "Training rounds by shift",
                "clauses": [{
                    **statement("User reports two training rounds per shift.", scope="each shift"),
                    "conditions": [
                        {
                            **statement(
                                "For each shift, October 1 inclusive to October 8 exclusive.",
                                effective_from="2025-10-01", effective_until="2025-10-08",
                                scope="each shift",
                            ),
                            "binding": {"evidence": ["e1"]},
                        },
                        {
                            **statement("Each shift starts training at 08:00.", scope="each shift"),
                            "binding": {"evidence": ["e1"]},
                        },
                    ],
                }],
            },
        )
        record_id = saved["id"]
        original = copy.deepcopy(service.read(record_id)["value"]["edit_state"])
        event(
            service, method, "night",
            "For the night shift only, use one training round per shift instead; "
            "the October validity period and 08:00 start remain shared.",
            "2025-10-02T07:00:00Z",
            {"action": "edit", "edits": [{
                **statement(
                    "User reports one training round per night shift.", scope="night shift"
                ),
                "operation": "add_exception", "target_unit": "u1",
                "condition": "Night shift only.", "shared_conditions": ["u2", "u3"],
            }]},
            record_id,
        )
        with_exception = copy.deepcopy(service.read(record_id)["value"])
        event(
            service, method, "start",
            "Change the shared training start to 09:00 for all shifts; "
            "the round counts and October validity period stay unchanged.",
            "2025-10-03T07:00:00Z",
            {"action": "edit", "edits": [{
                **statement("Each shift starts training at 09:00.", scope="each shift"),
                "operation": "change_condition", "target_unit": "u3",
            }]},
            record_id,
        )
        changed = copy.deepcopy(service.read(record_id)["value"]["edit_state"])
        assert changed["units"][:2] == original["units"][:2]
        assert changed["relations"] == with_exception["edit_state"]["relations"]
        event(
            service, method, "cancel", "Cancel only the night-shift exception.",
            "2025-10-06T07:00:00Z",
            {"action": "edit", "edits": [{
                "operation": "remove_exception", "target_unit": "u4", "evidence": ["e1"],
            }]},
            record_id,
        )
        current = service.read(record_id)["value"]
        assert current["revision"] == 4
        assert current["edit_state"]["units"] == changed["units"][:3]
        assert service.read(record_id, 2)["value"] == with_exception
        current_view = method.revision_view(current, query_time="2025-10-07T10:00:00Z")
        history_view = method.revision_view(
            service.read(record_id, 2)["value"], query_time="2025-10-02T10:00:00Z"
        )
        expired_view = method.revision_view(current, query_time="2025-10-09T10:00:00Z")
        assert current_view["units"][0]["temporal"]["status"] == "within_explicit_limits"
        assert expired_view["units"][0]["temporal"]["status"] == "expired"
        assert any(u["kind"] == "scoped_exception" for u in history_view["units"])
        assert not any(u["kind"] == "scoped_exception" for u in current_view["units"])
        assert len(history_view["common_conditions"]) == 2
        assert current_view["units"][0]["evidence_status"] == "supported"
        totals = event(
            service, method, "total",
            "Looking back at October 1 through October 3, the whole team completed "
            "three joint visits in total. Individual member totals were not recorded.",
            "2025-10-10T12:00:00Z",
            {"action": "create", "matter": "Team's joint visits", "clauses": [{
                **statement(
                    "User reports three joint visits for the whole team in total.",
                    event_at="2025-10-03", effective_from="2025-10-01",
                    effective_until="2025-10-04", scope="whole team", quantity_scope="overall",
                ),
                "conditions": [],
            }]},
        )
        totals_view = method.revision_view(
            service.read(totals["id"])["value"], query_time="2025-10-03T12:00:00Z"
        )
        total = totals_view["units"][0]
        assert total["member_quantities"] == "not_implied_by_overall_total"
        assert total["temporal"]["retrospective"]
        assert total["temporal"]["reported_after_query"]
        assert current_view["units"][2]["temporal"]["effective_from"] is None
        return {
            "kind": "synthetic_engineering_example", "model_calls": 0,
            "current": current_view, "history_revision_2": history_view,
            "after_expiry": expired_view, "retrospective_overall_total": totals_view,
        }


def main() -> None:
    with TemporaryDirectory(prefix="milai-unified-revision-") as temporary:
        trace = run(Path(temporary))
        print(json.dumps({"kind": trace["kind"], "model_calls": trace["model_calls"]}))
        for label in ("current", "history_revision_2", "after_expiry",
                      "retrospective_overall_total"):
            view = trace[label]
            print(json.dumps({
                "view": label, "query_time": view["query_time"],
                "version_time": view["version_time"], "relations": view["relations"],
                "common_conditions": view["common_conditions"],
                "statements": [{
                    "unit_id": item["unit_id"], "kind": item["kind"], "text": item["text"],
                    "applies_under": item["applies_under"], "temporal": item["temporal"],
                    "evidence_status": item["evidence_status"],
                    "quantity_scope": item["quantity_scope"],
                    **({"member_quantities": item["member_quantities"]}
                       if "member_quantities" in item else {}),
                } for item in view["units"]],
            }, ensure_ascii=False))


if __name__ == "__main__":
    main()
