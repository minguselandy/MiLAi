"""Read frozen functional-run artifacts; write separate mechanical/manual review packs.

Standard library only: no runtime import, SDK, model, database mutation or network.
Mechanical receipts never establish semantic PASS. Original attempts stay in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

CRITICAL_BLOCKERS = (
    "owner_exposure",
    "false_save_claim",
    "wrong_object_effect",
    "duplicate_effect",
    "unrecoverable_corruption",
    "unresolved_core_revision_defect",
)
STAGES = (
    "source_event",
    "proposal",
    "committed_memory",
    "actual_delivery",
    "business_action",
    "final_answer",
    "post_maintenance_state",
    "artifact_integrity",
    "accounting",
)
TERMINALS = {"COMPLETED", "FAILED", "BUDGET_EXHAUSTED", "PROVIDER_ERROR", "UNKNOWN", "NOT_RUN"}


def ordinary_inputs(freeze: dict[str, Any]) -> bool:
    return freeze.get("schema") == "functional_run_inputs_v2"


def canonical_hash(value: Any) -> str:
    """Match the runner freeze/hash contract, including its ordinary JSON separators."""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class ArtifactReader:
    def __init__(self, *, ordinary: bool = False) -> None:
        self.ordinary = ordinary
        self.inputs: dict[str, dict[str, Any]] = {}
        self._read_bytes: dict[str, bytes] = {}

    def bytes(self, path: Path) -> bytes:
        data = path.read_bytes()
        key = str(path.resolve())
        if self.ordinary:
            if key in self._read_bytes and self._read_bytes[key] != data:
                raise ValueError("ARTIFACT_CHANGED_DURING_READ:" + key)
            self._read_bytes[key] = data
            self.inputs.setdefault(key, {"input_ordinal": len(self.inputs), "bytes": len(data)})
            return data
        identity = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        if key in self.inputs and self.inputs[key] != identity:
            raise ValueError("ARTIFACT_CHANGED_DURING_READ:" + key)
        self.inputs[key] = identity
        return data

    def json(self, path: Path) -> Any:
        return json.loads(self.bytes(path))

    def lines(self, path: Path) -> tuple[list[dict[str, Any]], list[int]]:
        rows, broken = [], []
        for number, line in enumerate(self.bytes(path).decode().splitlines(), 1):
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("trace row is not an object")
                rows.append(value)
            except ValueError:
                broken.append(number)
        return rows, broken


def check(name: str, status: str, stage: str, detail: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "stage": stage, "detail": detail}


def yes_no(value: bool) -> str:
    return "PASS" if value else "FAIL"


def public_projection(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": c["case_id"],
            "owner": c["owner"],
            "initial_world": c.get("initial_world", {}),
            "messages": [
                {k: m[k] for k in ("session_id", "message_id", "content")} for m in c["messages"]
            ],
        }
        for c in fixture["cases"]
    ]


def accounts(state: dict[str, Any]) -> dict[str, int | None]:
    output: dict[str, int | None] = {}
    for key in ("generation_requests",):
        value = state.get(key)
        output[key] = value if type(value) is int else None
    for kind in ("generation", "embedding"):
        for field in ("known_tokens", "charged_tokens", "unknown_usage"):
            value = state.get(kind, {}).get(field)
            output[kind + "." + field] = value if type(value) is int else None
    return output


def ledger_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int | None]:
    a, b = accounts(before), accounts(after)
    result: dict[str, int | None] = {}
    for key, previous in a.items():
        current = b[key]
        result[key] = current - previous if previous is not None and current is not None else None
    return result


def trace_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        k: {"request_events": 0, "known_tokens": 0, "unknown_usage_events": 0}
        for k in ("generation", "embedding")
    }
    for event in events:
        if event.get("event") not in {"vllm_response", "vllm_error"}:
            continue
        kind = "embedding" if "embeddings" in event.get("path", "") else "generation"
        result[kind]["request_events"] += 1
        usage = event.get("usage")
        total = usage.get("total_tokens") if isinstance(usage, dict) else None
        if type(total) is not int or total < 0:
            result[kind]["unknown_usage_events"] += 1
        else:
            result[kind]["known_tokens"] += total
    return result


def final_linkage(
    answer: Any, events: list[dict[str, Any]], *, ordinary: bool = False,
) -> dict[str, Any]:
    matches, inconsistent = [], []
    for index, event in enumerate(events):
        if event.get("event") != "vllm_response" or event.get("http_status") != 200:
            continue
        raw = event.get("response_text")
        if not isinstance(raw, str):
            continue
        try:
            receipt = json.loads(raw)
        except ValueError:
            inconsistent.append(index)
            continue
        if event.get("receipt") is not None and receipt != event["receipt"]:
            inconsistent.append(index)
            continue
        for choice in receipt.get("choices", []):
            content = choice.get("message", {}).get("content")
            decoded = content
            if isinstance(content, str):
                try:
                    action = json.loads(content)
                    if isinstance(action, dict) and isinstance(action.get("answer"), str):
                        decoded = action["answer"]
                except ValueError:
                    pass
            if answer is not None and decoded == answer:
                matches.append(
                    {
                        "trace_ordinal": index,
                        "provider_id": receipt.get("id"),
                        **({} if ordinary else {"raw_response_sha256": text_hash(raw)}),
                    }
                )
    return {
        "status": "FAIL" if inconsistent else "PASS" if matches else "UNKNOWN",
        "matches": matches,
        "inconsistent_response_ordinals": inconsistent,
        "limitation": "Exact recorded HTTP linkage only; does not judge answer semantics. "
        "Absent/redacted raw responses remain unknown.",
    }


def record_snapshot(
    records: list[dict[str, Any]], *, ordinary: bool = False,
) -> list[dict[str, Any]]:
    result = []
    for row in records:
        value = row.get("value")
        result.append(
            {
                "id": row.get("id"),
                "status": row.get("status"),
                "ok": row.get("ok"),
                "revision": value.get("revision") if isinstance(value, dict) else None,
                **({} if ordinary else {"value_sha256": canonical_hash(value)}),
                "value": value,
            }
        )
    return result


def record_changes(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    old, new = {r["id"]: r for r in before}, {r["id"]: r for r in after}
    changes = []
    for rid in sorted(set(old) | set(new), key=str):
        a, b = old.get(rid), new.get(rid)
        if a != b:
            av, bv = (a or {}).get("value") or {}, (b or {}).get("value") or {}
            changes.append(
                {
                    "id": rid,
                    "before_revision": (a or {}).get("revision"),
                    "after_revision": (b or {}).get("revision"),
                    "changed_value_fields": sorted(
                        k for k in set(av) | set(bv) if av.get(k) != bv.get(k)
                    ),
                    "kind": "created"
                    if a is None
                    else "no_longer_visible"
                    if b is None
                    else "changed",
                }
            )
    return changes


def source_checks(
    sources: list[dict[str, Any]], owner: str, *, ordinary: bool = False,
) -> list[dict[str, Any]]:
    wrong: list[Any] = []
    invalid: list[Any] = []
    missing: list[Any] = []
    for source in sources:
        sid = source.get("event_id")
        if source.get("owner") != owner:
            wrong.append(sid)
        if ordinary:
            if not isinstance(sid, str) or type(source.get("source_revision")) is not int:
                missing.append(sid)
            elif (source["source_revision"] < 1
                  or not isinstance(source.get("content"), (str, dict))):
                invalid.append(sid)
            continue
        content, digest = source.get("content"), source.get("content_sha256")
        if not isinstance(content, str) or not isinstance(digest, str):
            missing.append(sid)
        elif text_hash(content) != digest:
            invalid.append(sid)
    return [
        check("source_owner_binding", yes_no(not wrong), "source_event", wrong),
        check(
            "source_id_revision_recorded" if ordinary else "source_content_hash",
            "FAIL" if invalid else "UNKNOWN" if missing else "PASS",
            "source_event",
            {"invalid": invalid, "unverifiable": missing},
        ),
    ]


def quote_checks(
    value: Any, sources: list[dict[str, Any]], *, ordinary: bool = False,
) -> dict[str, Any]:
    """Verify only explicitly serialized quote+source_ref bindings, never infer entailment."""
    bodies = {s.get("event_id"): s.get("content") for s in sources}
    versions = {s.get("event_id"): s.get("source_revision") for s in sources}
    rows = []

    def visit(item: Any, pointer: str) -> None:
        if isinstance(item, dict):
            if ordinary and "source_ref" in item and "source_revision" in item:
                body = bodies.get(item["source_ref"])
                if isinstance(body, dict):
                    body = json.dumps(body, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"), allow_nan=False)
                start, end = item.get("start"), item.get("end")
                ranged = any(k in item for k in ("start", "end", "quote"))
                status = "UNKNOWN" if body is None else yes_no(
                    versions[item["source_ref"]] == item["source_revision"]
                    and (not ranged or (
                        isinstance(body, str) and type(start) is int and type(end) is int
                        and 0 <= start < end <= len(body)
                        and ("quote" not in item or body[start:end] == item["quote"]))))
                rows.append({"pointer": pointer, "source_ref": item["source_ref"],
                             "source_revision": item["source_revision"],
                             "reference_kind": "exact_range" if ranged else "source_revision",
                             **({"start": start, "end": end} if ranged else {}), "status": status})
            elif isinstance(item.get("quote"), str) and "source_ref" in item:
                body, quote = bodies.get(item["source_ref"]), item["quote"]
                status = "UNKNOWN"
                if isinstance(body, str):
                    start, end = item.get("start"), item.get("end")
                    if type(start) is int and type(end) is int:
                        status = yes_no(0 <= start <= end <= len(body) and body[start:end] == quote)
                    else:
                        status = yes_no(quote in body)
                rows.append(
                    {
                        "pointer": pointer,
                        "source_ref": item["source_ref"],
                        "status": status,
                        **({} if ordinary else {"quote_sha256": text_hash(quote)}),
                    }
                )
            for key, child in item.items():
                visit(child, pointer + "/" + key)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, pointer + "/" + str(index))

    visit(value, "")
    return {
        "structured_quotes": rows,
        "status": "FAIL"
        if any(r["status"] == "FAIL" for r in rows)
        else "UNKNOWN"
        if not rows or any(r["status"] == "UNKNOWN" for r in rows)
        else "PASS",
        "semantic_support": "UNREVIEWED",
    }


def compact_world(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {"status": "UNAVAILABLE"}
    journal = snapshot.get("journal", {})
    entries = [
        {"journal_key": key, **value}
        for key, value in journal.items()
        if isinstance(value, dict) and "status" in value
    ]
    return {
        "workflow": snapshot.get("workflow"),
        "owner": snapshot.get("owner"),
        "world": snapshot.get("world"),
        "journal_entries": entries,
        "journal_status_counts": dict(Counter(r.get("status", "UNKNOWN") for r in entries)),
        "journal_effect_counts": dict(Counter(r.get("effect", "UNKNOWN") for r in entries)),
        "receipt_progress": snapshot.get("receipt_progress"),
        "semantic_authorization_and_effect_verdict": "UNREVIEWED",
    }


def review_slot(case_id: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "semantic_verdict": "UNREVIEWED",
        "utility": None,
        "raw_capture": None,
        "semantic_formation": None,
        "source_quote_support": None,
        "same_id_revision": None,
        "scope_time_negation": None,
        "actual_delivery_and_history": None,
        "business_effect_and_recovery": None,
        "answer_satisfies_request": None,
        "post_maintenance_state": None,
        "critical_blockers": dict.fromkeys(CRITICAL_BLOCKERS),
        "earliest_proven_breakpoint": None,
        "rationale": None,
        "output_quote": None,
        "evidence_refs": [],
        "uncertainties": [],
        "reviewer": None,
        "independent_review": False,
    }


def hidden_program_capture(
    reader: ArtifactReader, bank_root: Path, row: dict[str, Any],
) -> dict[str, Any] | None:
    """Audit a hidden confirmation from a closed SQLite snapshot, never redisclose it.

    Visibility filtering deliberately omits this assistant Source from the public
    snapshot. A capture receipt alone is insufficient: require its actual stored
    event and durable capture hash. Uncheckpointed WAL is not an immutable snapshot.
    """
    capture = row.get("final_capture", {})
    if capture.get("ok") is not True or capture.get("visibility") != "revoked":
        return None
    ref = capture.get("source_ref")
    database = bank_root / "memory.sqlite"
    wal = bank_root / "memory.sqlite-wal"
    if not isinstance(ref, str) or not database.is_file() or (wal.exists() and wal.stat().st_size):
        return None
    reader.bytes(database)
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as store:
        rows = store.execute("SELECT key, value FROM store WHERE key IN (?, ?)",
                             (ref, "capture:" + ref)).fetchall()
    reader.bytes(database)  # Reject evidence changed during the read.
    events = [json.loads(value) for key, value in rows if key == ref]
    captures = [json.loads(value) for key, value in rows if key == "capture:" + ref]
    if len(events) != 1 or len(captures) != 1:
        return None
    if reader.ordinary:
        version = events[0].get("source_revision")
        if type(version) is not int or version < 1 or captures[0] != {
            "source_ref": ref, "source_revision": version,
        }:
            return None
    else:
        event_hash = text_hash(json.dumps(events[0], ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":"), allow_nan=False))
        if captures[0] != {"source_ref": ref, "event_sha256": event_hash}:
            return None
    return cast(dict[str, Any], events[0])


def captured_public_delivery_linkage(
    row: dict[str, Any], events: list[dict[str, Any]], freeze: dict[str, Any],
    metadata: dict[str, Any], event_name: str,
    captured_source: dict[str, Any] | None = None,
    *, response_id: str | None = None,
) -> dict[str, Any]:
    """Link a delivered public answer to its actual capture and delivery event."""
    policy = freeze.get("config", {}).get("finalization")
    if not freeze.get("run_id"):
        return {"status": "UNKNOWN", "reason": "missing_public_delivery_run_identity"}
    answer = row.get("final_answer")
    if not isinstance(answer, str) or not answer.strip():
        return {"status": "FAIL", "reason": "missing_program_text"}
    ordinary = ordinary_inputs(freeze)
    if ordinary:
        source_ref = row.get("final_capture", {}).get("source_ref")
        if not isinstance(source_ref, str):
            return {"status": "FAIL", "reason": "missing_stored_final_capture_reference"}
    else:
        identity = [["functional", freeze["run_id"], row.get("bank"), row.get("owner")],
                    row.get("session"), str(row.get("message_id")) + ":final", "assistant"]
        source_ref = "src-" + text_hash(json.dumps(
            identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    sources = [s for s in row.get("sources", []) if s.get("event_id") == source_ref]
    hidden = not sources and captured_source is not None and (
        row.get("final_capture", {}).get("visibility") == "revoked")
    if hidden:
        sources = [captured_source]
    matched = len(sources) == 1 and all(sources[0].get(k) == v for k, v in {
        "event_id": source_ref, "owner": row.get("owner"),
        "session": row.get("session"), "role": "assistant",
        "origin": "public_assistant_message", "content": answer,
        **({} if ordinary else {"content_sha256": text_hash(answer)}),
    }.items())
    renders = [e for e in events if e.get("event") == event_name]
    matched = matched and len(renders) == 1 and all(
        renders[0].get(k) == v for k, v in metadata.items())
    if matched and ordinary:
        matched = (type(sources[0].get("source_revision")) is int
                   and sources[0]["source_revision"] > 0
                   and response_id is not None and renders[0].get("response_id") == response_id)
    elif matched and ("final_text_sha256" in renders[0] or policy in {
            "receipt_business_response_v2", "receipt_business_response_v3",
            "receipt_or_agent_response_v1"}):
        matched = renders[0].get("final_text_sha256") == text_hash(answer)
    messages = row.get("messages", [])
    matched = matched and bool(messages) and messages[-1].get("type") == "ai" and (
        messages[-1].get("content") == answer and not messages[-1].get("tool_calls"))
    if "final_capture" in row:
        matched = matched and row["final_capture"].get("ok") is True and (
            row["final_capture"].get("source_ref") == source_ref)
    return {"status": yes_no(bool(matched)), "method": "captured_public_delivery",
            "hidden_source_checked_in_readonly_sqlite": bool(hidden),
            "source_ref": source_ref, "render_text_hash_recorded": bool(
                renders and "final_text_sha256" in renders[0]),
            "limitation": "Captured public delivery provenance only; effects/support/answer "
                          "semantics still require separate review. No model final HTTP expected."}


def program_final_linkage(
    row: dict[str, Any], events: list[dict[str, Any]], freeze: dict[str, Any],
    captured_source: dict[str, Any] | None = None,
    *, response_id: str | None = None,
) -> dict[str, Any]:
    """Bind a program-rendered delivery to its captured public assistant event.

    This is provenance, not validation of task completion or the renderer's meaning.
    Old cohorts have source capture but no explicit render text hash; retain that
    narrower provenance scope instead of pretending there was a model response.
    """
    metadata = {"status": "response_rendered", "attempts": 0, "tools_available": False,
                "execution_candidate_delivered": False,
                "protocol": "receipt_business_response_v1", "model_generation": False}
    policy = freeze.get("config", {}).get("finalization")
    if (policy not in {"receipt_business_response_v1", "receipt_business_response_v2",
                      "receipt_business_response_v3", "receipt_or_agent_response_v1"}
            or row.get("finalization") != metadata or not freeze.get("run_id")):
        return {"status": "UNKNOWN", "reason": "unrecognized_program_final_contract"}
    result = captured_public_delivery_linkage(
        row, events, freeze, metadata, "functional_receipt_finalization", captured_source,
        response_id=response_id)
    return {**result, "method": "captured_program_delivery"} if "method" in result else result


def retained_agent_final_linkage(
    row: dict[str, Any], events: list[dict[str, Any]], freeze: dict[str, Any],
    *, response_id: str | None = None, captured_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """No new finalization generation still requires the actual Agent HTTP text."""
    metadata = {"status": "agent_response_retained", "attempts": 0,
                "tools_available": False, "execution_candidate_delivered": True,
                "protocol": "agent_response_v1", "model_generation": False}
    finalization = row.get("finalization")
    appended = False
    if isinstance(finalization, dict) and "observation_receipts_appended" in finalization:
        # Old retained deliveries omit this field. Explicit False still means
        # the whole delivered answer must match the original Agent HTTP text.
        # An appended program receipt is not additional model-generated text.
        appended = finalization["observation_receipts_appended"]
        if type(appended) is not bool:
            return {"status": "UNKNOWN", "reason": "unrecognized_retained_agent_contract"}
        metadata["observation_receipts_appended"] = appended
    if (freeze.get("config", {}).get("finalization") != "receipt_or_agent_response_v1"
            or row.get("finalization") != metadata):
        return {"status": "UNKNOWN", "reason": "unrecognized_retained_agent_contract"}
    answer = row.get("final_answer")
    if not isinstance(answer, str):
        return {"status": "FAIL", "reason": "missing_agent_text"}
    delivery = [e for e in events if e.get("event") == "functional_agent_finalization"]
    messages = row.get("messages", [])
    ordinary = ordinary_inputs(freeze)
    if appended:
        candidate = row.get("execution_candidate_answer")
        provider = (final_linkage(candidate, events, ordinary=ordinary)
                    if isinstance(candidate, str) and candidate.strip() else {
                        "status": "UNKNOWN", "reason": "missing_execution_candidate_answer"})
        retained = None if provider.get("reason") == "missing_execution_candidate_answer" else (
            len(messages) >= 2 and messages[-2].get("type") == "ai"
            and messages[-2].get("content") == candidate and not messages[-2].get("tool_calls")
            and answer.startswith(candidate + "\n\n") and bool(answer[len(candidate) + 2:]))
        public = captured_public_delivery_linkage(
            row, events, freeze, metadata, "functional_agent_finalization", captured_source,
            response_id=response_id)
        statuses = {provider["status"], public["status"]}
        status = ("FAIL" if retained is False or "FAIL" in statuses else
                  "PASS" if retained is True and statuses == {"PASS"} else "UNKNOWN")
        return {"status": status, "method": "retained_agent_with_captured_public_delivery",
                "actual_http": provider, "captured_public_delivery": public,
                "candidate_retained": retained,
                "limitation": "Candidate actual HTTP and captured public delivery provenance "
                              "only; appended text is not model HTTP. Query/effect meaning, "
                              "answer correctness and task completion remain UNREVIEWED."}
    matched = (len(delivery) == 1
               and all(delivery[0].get(k) == v for k, v in metadata.items())
               and (response_id is not None and delivery[0].get("response_id") == response_id
                    if ordinary else delivery[0].get("final_text_sha256") == text_hash(answer))
               and bool(messages) and messages[-1].get("type") == "ai"
               and messages[-1].get("content") == answer and not messages[-1].get("tool_calls"))
    provider = final_linkage(answer, events, ordinary=ordinary)
    return {"status": provider["status"] if matched else "FAIL",
            "method": "retained_agent_actual_http_delivery", "actual_http": provider,
            "limitation": "No additional finalization generation; original Agent response "
                          "must match actual HTTP. This is provenance, not semantic acceptance."}


def evaluate_attempt(
    reader: ArtifactReader, path: Path, expected: dict[str, Any], freeze: dict[str, Any],
) -> dict[str, Any]:
    row = reader.json(path)
    checks = []
    mismatch = {
        k: {"expected": v, "actual": row.get(k)} for k, v in expected.items() if row.get(k) != v
    }
    checks.append(
        check("public_identity_text", yes_no(not mismatch), "artifact_integrity", mismatch)
    )
    checks.append(
        check(
            "terminal_recorded",
            yes_no(row.get("status") in TERMINALS),
            "artifact_integrity",
            row.get("status"),
        )
    )
    checks.append(
        check(
            "recorded_process_id",
            yes_no(type(row.get("process_id")) is int),
            "artifact_integrity",
            row.get("process_id"),
        )
    )
    snapshot = row.get("snapshot_before_close") is True
    checks.append(
        check(
            "snapshot_before_close_recorded",
            "PASS" if snapshot else "UNKNOWN",
            "post_maintenance_state",
            "Runner assertion; not independent SDK reopen.",
        )
    )
    sources, records = row.get("sources"), row.get("records")
    if isinstance(sources, list) and isinstance(records, list):
        checks.extend(source_checks(sources, expected["owner"], ordinary=reader.ordinary))
    else:
        sources, records = [], []
        checks.append(
            check(
                "state_snapshots_available",
                "UNKNOWN",
                "post_maintenance_state",
                "Missing source/record snapshot; do not substitute an empty bank.",
            )
        )
    trace_path = path.with_name(
        path.name.replace("-attempt-", "-trace-").removesuffix(".json") + ".jsonl"
    )
    events, broken = reader.lines(trace_path) if trace_path.exists() else ([], [])
    checks.append(
        check(
            "trace_complete_jsonl",
            "FAIL" if broken else "PASS" if trace_path.exists() else "UNKNOWN",
            "artifact_integrity",
            {"broken_lines": broken},
        )
    )
    retained = row.get("finalization", {}).get("protocol") == "agent_response_v1"
    program = row.get("finalization", {}).get("model_generation") is False and not retained
    response_id = path.name.split("-attempt-", 1)[0]
    if retained:
        linkage = retained_agent_final_linkage(
            row, events, freeze, response_id=response_id,
            captured_source=(hidden_program_capture(reader, path.parent, row)
                if row["finalization"].get("observation_receipts_appended") is True else None))
    elif program:
        linkage = program_final_linkage(
            row, events, freeze, hidden_program_capture(reader, path.parent, row),
            response_id=response_id)
    else:
        linkage = final_linkage(row.get("final_answer"), events, ordinary=reader.ordinary)
    if row.get("status") == "COMPLETED":
        checks.append(check("final_program_delivery_link" if program else "final_actual_http_link",
                            linkage["status"], "final_answer", linkage))
    usage = trace_usage(events)
    delta = ledger_delta(row.get("budget_before", {}), row.get("budget_after", {}))
    for kind in ("generation", "embedding"):
        actual = delta[kind + ".known_tokens"]
        valid = actual == usage[kind]["known_tokens"] if actual is not None else None
        checks.append(
            check(
                kind + "_known_usage_matches_trace",
                "UNKNOWN" if valid is None else yes_no(valid),
                "accounting",
                {"delta": actual, "trace": usage[kind]},
            )
        )
    actual_calls = delta["generation_requests"]
    checks.append(
        check(
            "generation_requests_match_trace",
            "UNKNOWN"
            if actual_calls is None
            else yes_no(actual_calls == usage["generation"]["request_events"]),
            "accounting",
            {"delta": actual_calls, "trace": usage["generation"]["request_events"]},
        )
    )
    material_by_identity: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(events):
        if event.get("event") != "functional_material_delivery":
            continue
        value = event.get("material")
        key = f"delivery-{index}" if reader.ordinary else canonical_hash(value)
        entry = material_by_identity.setdefault(
            key,
            {
                "delivery_id" if reader.ordinary else "material_sha256": key,
                "material": value,
                "prepared_trace_ordinals": [],
                "actual_http_request_ordinals": [],
            },
        )
        entry["prepared_trace_ordinals"].append(index)
        literal = json.dumps(value, ensure_ascii=False)
        for request_index, request_event in enumerate(events):
            if (
                request_event.get("event") != "vllm_response"
                or request_event.get("http_status") != 200
            ):
                continue
            request = request_event.get("request", {})
            if any(
                isinstance(m.get("content"), str) and literal in m["content"]
                for m in request.get("messages", [])
            ):
                entry["actual_http_request_ordinals"].append(request_index)
        entry["actual_http_request_ordinals"] = sorted(set(entry["actual_http_request_ordinals"]))
        entry["delivery_verification"] = (
            "EXACT_RECORDED_HTTP_INPUT"
            if entry["actual_http_request_ordinals"]
            else "PREPARED_ONLY_UNVERIFIED_HTTP_INPUT"
        )
    material = list(material_by_identity.values())
    messages = row.get("messages", [])
    tools = [
        {"position": i, **m}
        for i, m in enumerate(messages)
        if m.get("type") == "tool" or m.get("role") == "tool"
    ]
    return {
        "artifact": str(path.resolve()),
        "attempt": row.get("attempt"),
        "execution_status": row.get("status", "UNKNOWN"),
        "process_id": row.get("process_id"),
        "error_category": row.get("error_category"),
        "error": row.get("error"),
        "checks": checks,
        "capture": row.get("capture"),
        "evaluator_control_state": row.get("evaluator_control_state"),
        "source_import_receipts": row.get("source_import_receipts", []),
        "record_snapshot": record_snapshot(records, ordinary=reader.ordinary),
        "source_inventory": [
            {
                k: s.get(k)
                for k in (
                    "event_id",
                    "owner",
                    "session",
                    "role",
                    "origin",
                    "source_revision" if reader.ordinary else "content_sha256",
                    "formation_status",
                )
            }
            | {
                "codepoints": len(s.get("content", ""))
                if isinstance(s.get("content"), str)
                else None
            }
            for s in sources
        ],
        "quote_check": quote_checks(records, sources, ordinary=reader.ordinary),
        "world": compact_world(row.get("world")),
        "tool_messages": tools,
        "memory_mutation_receipts": row.get("memory_mutation_receipts", []),
        "final_answer": row.get("final_answer"),
        "actual_http_linkage": linkage,
        "material_deliveries": material,
        "trace_path": str(trace_path.resolve()),
        "usage_from_trace": usage,
        "ledger_delta": delta,
        "ledger_before": accounts(row.get("budget_before", {})),
        "ledger_after": accounts(row.get("budget_after", {})),
        "semantic_verdict": "UNREVIEWED",
    }


def l3_inputs(fixture: dict[str, Any], *, ordinary: bool = False) -> dict[str, Any]:
    rows = []
    for case in fixture["cases"]:
        originals = {s.get("original_event_id"): s for s in case.get("initial_sources", [])}
        checks = []
        for index, candidate in enumerate(case.get("retrieval_candidates", [])):
            source = originals.get(candidate.get("source_ref"), {})
            body = source.get("content")
            start, end = candidate.get("start"), candidate.get("end")
            valid = (
                isinstance(body, str)
                and type(start) is int
                and type(end) is int
                and 0 <= start < end <= len(body)
            )
            if ordinary:
                checks.append({"ordinal": index, "source_range_valid": bool(valid)})
            else:
                hashes = valid and all(
                    candidate.get(key) in (None, text_hash(body))
                    for key in ("source_sha256", "body_text_sha256")
                )
                span = valid and candidate.get("span_sha256") in (None, text_hash(body[start:end]))
                checks.append(
                    {"ordinal": index, "range_and_hash_valid": bool(valid and hashes and span)}
                )
        rows.append(
            {
                "case_id": case["case_id"],
                "source_count": len(originals),
                "candidate_count": len(checks),
                "candidate_checks": checks,
                "declared_quote_and_candidate_delivery_status": "REQUIRES_ACTUAL_OUTPUT_REVIEW",
            }
        )
    label = str(fixture.get("cohort", ""))
    unit = "formation_request" if "formation" in label else "reading_query"
    return {
        "unit": unit,
        "planned_count": len(rows),
        "cases": rows,
        "warning": "Do not add formation requests, query cases, responses and histories "
        "as independent samples. Input ranges do not prove actual delivery.",
    }


def stored_bank(reader: ArtifactReader, root: Path, case: dict[str, Any]) -> Path:
    index = root / "bank-index.json"
    entries = reader.json(index) if index.exists() else []
    ids = [r["id"] for r in entries
           if r.get("identity") == {"bank": case["case_id"], "owner": case["owner"]}]
    if not ids:
        ids = [folder.name for folder in (root / "banks").glob("*") if folder.is_dir()
               and any(reader.json(p).get("bank") == case["case_id"]
                       and reader.json(p).get("owner") == case["owner"]
                       for p in folder.glob("*-attempt-*.json"))]
    if len(ids) > 1:
        raise ValueError("Ambiguous stored bank identity")
    return root / "banks" / (str(ids[0]) if ids else ".not-recorded-bank")


def stored_message(reader: ArtifactReader, bank: Path, message: dict[str, Any]) -> str:
    identity = {"session": message["session_id"], "message_id": message["message_id"]}
    index = bank / "message-index.json"
    entries = reader.json(index) if index.exists() else []
    ids = [r["id"] for r in entries if r.get("identity") == identity]
    if not ids:
        ids = [p.name.removesuffix("-input.json") for p in bank.glob("*-input.json")
               if all(reader.json(p).get(k) == v for k, v in identity.items())]
    if len(ids) > 1:
        raise ValueError("Ambiguous stored message identity")
    return str(ids[0]) if ids else ".not-recorded-message"


def evaluate(
    root: Path,
    *,
    cohort: str,
    original_fixture: Path | None = None,
    grades_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    metadata = json.loads((root / "input-freeze.json").read_bytes())
    reader = ArtifactReader(ordinary=ordinary_inputs(metadata))
    freeze = reader.json(root / "input-freeze.json")
    fixture = freeze["fixture"]
    if not isinstance(fixture, dict) or not isinstance(fixture.get("cases"), list):
        raise ValueError("Frozen fixture must contain cases; no denominator can be inferred.")
    case_ids = [c["case_id"] for c in fixture["cases"]]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Duplicate planned case IDs")
    top = [check(
        "recorded_input_versions",
        yes_no(isinstance(freeze.get("config_version"), str)
               and freeze["config_version"] == freeze["config"].get(
                   "config_version",
                   freeze["config"].get("revision", freeze["config"].get("profile")))
               and isinstance(freeze.get("source_version"), dict)
               and bool(freeze["source_version"].get("implementation_version"))),
        "artifact_integrity",
        {"config_version": freeze.get("config_version"),
         "source_version": freeze.get("source_version"),
         "scope": "Recorded configuration/source versions; no content fingerprint certification."},
    )] if reader.ordinary else [
        check(
            "frozen_fixture_hash",
            yes_no(canonical_hash(fixture) == freeze["fixture_sha256"]),
            "artifact_integrity",
            "Canonical frozen public fixture",
        ),
        check(
            "frozen_config_hash",
            yes_no(canonical_hash(freeze["config"]) == freeze["config_sha256"]),
            "artifact_integrity",
            "Canonical frozen configuration",
        ),
    ]
    if cohort == "L1":
        if original_fixture is None:
            raise ValueError("L1 requires the original frozen normal24 fixture")
        original = reader.json(original_fixture)
        matching = public_projection(fixture) == public_projection(original)
        matching = matching and len(original["cases"]) == 24
        top.append(
            check(
                "original_E0_public_ID_text_freeze",
                yes_no(matching),
                "artifact_integrity",
                {"original_fixture": str(original_fixture.resolve()), "expected_trajectories": 24},
            )
        )
    controls = freeze.get("evaluator_controls")
    if not reader.ordinary and "evaluator_controls_sha256" in freeze:
        top.append(
            check(
                "frozen_evaluator_controls_hash",
                yes_no(canonical_hash(controls) == freeze["evaluator_controls_sha256"]),
                "artifact_integrity",
                "Offline controls are not public method inputs.",
            )
        )
    control_by_id = {c["case_id"]: c for c in (controls or {}).get("cases", [])}
    result_rows = (
        reader.json(root / "results.json").get("results", [])
        if (root / "results.json").exists()
        else []
    )
    declared = {(r["case_id"], r["message_index"]): r for r in result_rows}
    if len(declared) != len(result_rows):
        top.append(
            check(
                "aggregate_duplicate_message_keys",
                "FAIL",
                "artifact_integrity",
                "Duplicate result entries; all raw entries remain in source artifact.",
            )
        )
    packs, all_attempts = [], []
    orphan_trace_paths: list[str] = []
    missing_terminal_messages: list[str] = []
    for case in fixture["cases"]:
        bank_root = (stored_bank(reader, root, case) if reader.ordinary else
                     root / "banks" / canonical_hash([case["case_id"], case["owner"]])[:24])
        messages: list[dict[str, Any]] = []
        case_checks: list[dict[str, Any]] = []
        previous_records: list[dict[str, Any]] = []
        pids = []
        for index, message in enumerate(case["messages"]):
            identity = (stored_message(reader, bank_root, message) if reader.ordinary else
                        canonical_hash([message["session_id"], message["message_id"]]))
            expected = {
                "owner": case["owner"],
                "bank": case["case_id"],
                "session": message["session_id"],
                "message_id": message["message_id"],
                "content": message["content"],
                "workflow": case.get("workflow", "reservation"),
            }
            paths = sorted(
                bank_root.glob(identity + "-attempt-*.json"),
                key=lambda p: int(p.stem.rsplit("-", 1)[-1]),
            )
            attempts = [evaluate_attempt(reader, path, expected, freeze) for path in paths]
            all_attempts.extend(attempts)
            ordinals = [a["attempt"] for a in attempts]
            matched_traces = {Path(a["trace_path"]) for a in attempts}
            orphans = [
                p.resolve()
                for p in bank_root.glob(identity + "-trace-*.jsonl")
                if p.resolve() not in matched_traces
            ]
            orphan_rows = []
            for orphan in orphans:
                events, broken = reader.lines(orphan)
                orphan_rows.append(
                    {
                        "path": str(orphan),
                        "usage": trace_usage(events),
                        "broken_lines": broken,
                        "status": "TRACE_WITHOUT_TERMINAL_ATTEMPT",
                    }
                )
            orphan_trace_paths.extend(str(p) for p in orphans)
            input_path = bank_root / (identity + "-input.json")
            input_seen = input_path.exists()
            if input_seen:
                captured = reader.json(input_path)
                case_checks.append(
                    check(
                        "persisted_public_input:" + message["message_id"],
                        yes_no(
                            all(captured.get(k) == v for k, v in expected.items() if k != "bank")
                        ),
                        "artifact_integrity",
                        str(input_path),
                    )
                )
            if attempts:
                case_checks.append(
                    check(
                        "attempt_sequence:" + message["message_id"],
                        yes_no(ordinals == list(range(len(attempts)))),
                        "artifact_integrity",
                        ordinals,
                    )
                )
                latest_path = bank_root / (identity + "-result.json")
                same = latest_path.exists() and reader.json(latest_path) == reader.json(paths[-1])
                case_checks.append(
                    check(
                        "latest_preserves_attempt:" + message["message_id"],
                        yes_no(same),
                        "artifact_integrity",
                        str(latest_path),
                    )
                )
                latest = attempts[-1]
                pids.append(latest["process_id"])
                changes = record_changes(previous_records, latest["record_snapshot"])
                previous_records = latest["record_snapshot"]
            else:
                latest, changes = None, []
            claim = declared.get((case["case_id"], index))
            status = (
                latest["execution_status"]
                if latest
                else (
                    "UNKNOWN"
                    if orphans or input_seen
                    else "NOT_RUN"
                    if claim is None or claim.get("status") == "NOT_RUN"
                    else "UNKNOWN"
                )
            )
            if not attempts and (
                input_seen or orphans or (claim and claim.get("status") != "NOT_RUN")
            ):
                missing_terminal_messages.append(case["case_id"] + ":" + message["message_id"])
            if orphans:
                status = "UNKNOWN"
                case_checks.append(
                    check(
                        "orphan_trace:" + message["message_id"],
                        "UNKNOWN",
                        "artifact_integrity",
                        orphan_rows,
                    )
                )
            if claim and latest:
                latest_record = reader.json(paths[-1])
                agrees = all(claim.get(k) == value for k, value in latest_record.items())
                case_checks.append(
                    check(
                        "aggregate_matches_latest:" + message["message_id"],
                        yes_no(agrees),
                        "artifact_integrity",
                        claim.get("status"),
                    )
                )
            messages.append(
                {
                    "message_index": index,
                    "public_message": message,
                    "execution_status": status,
                    "aggregate_declared_status": claim.get("status") if claim else None,
                    "attempts": attempts,
                    "orphan_traces": orphan_rows,
                    "record_changes_since_previous_message": changes,
                    "semantic_verdict": "UNREVIEWED",
                }
            )
        valid_pids = [p for p in pids if type(p) is int]
        case_checks.append(
            check(
                "distinct_recorded_message_processes",
                "UNKNOWN"
                if len(valid_pids) < 2
                else yes_no(len(valid_pids) == len(set(valid_pids))),
                "post_maintenance_state",
                valid_pids,
            )
        )
        control = control_by_id.get(case["case_id"], {})
        declared_fault = control.get("one_shot_fault")
        states = [
            a.get("evaluator_control_state")
            for m in messages
            for a in m["attempts"]
            if isinstance(a.get("evaluator_control_state"), dict)
        ]
        observed_faults = [state["fault"] for state in states if state.get("fault")]
        applied = bool(
            declared_fault
            and any(
                fault.get("applied") is True
                and fault.get("boundary") == declared_fault["boundary"]
                and fault.get("tool") == declared_fault["target_operation"]
                and fault.get("message_index") == declared_fault["message_index"]
                for fault in observed_faults
            )
        )
        if declared_fault:
            case_checks.append(
                check(
                    "declared_fault_applied",
                    "PASS" if applied else "UNKNOWN",
                    "business_action",
                    {
                        "declared": declared_fault,
                        "observed": observed_faults,
                        "condition_status": "APPLIED"
                        if applied
                        else "NOT_RUN_CONDITION_NOT_REACHED",
                    },
                )
            )
        expected_events = {e["event_id"] for e in control.get("before_message_events", [])}
        observed_events = {key for state in states for key in state.get("events", {})}
        if expected_events:
            case_checks.append(
                check(
                    "declared_backend_events_applied",
                    "PASS" if expected_events <= observed_events else "UNKNOWN",
                    "business_action",
                    {"missing_event_ids": sorted(expected_events - observed_events)},
                )
            )
        checks = [*case_checks, *(c for m in messages for a in m["attempts"] for c in a["checks"])]
        failures = [c for c in checks if c["status"] == "FAIL"]
        earliest = min(failures, key=lambda c: STAGES.index(c["stage"])) if failures else None
        statuses = [m["execution_status"] for m in messages]
        packs.append(
            {
                "case_id": case["case_id"],
                "owner": case["owner"],
                "workflow": case.get("workflow"),
                "declared_fault_execution": {
                    "planned": declared_fault is not None,
                    "observed_applied": applied,
                    "last_message_status": statuses[-1] if statuses else None,
                    "recovery_semantics": "UNREVIEWED",
                },
                "messages": messages,
                "execution_status": "COMPLETED"
                if all(s == "COMPLETED" for s in statuses)
                else "NOT_RUN"
                if all(s == "NOT_RUN" for s in statuses)
                else "INCOMPLETE",
                "mechanical_checks": case_checks,
                "mechanical_failure_count": len(failures),
                "earliest_mechanically_proven_breakpoint": earliest,
                "semantic_verdict": "UNREVIEWED",
                "acceptance_evidence_complete": all(
                    m["attempts"]
                    and all(c["status"] == "PASS" for c in m["attempts"][-1]["checks"])
                    for m in messages
                )
                and not failures
                and not any(m["orphan_traces"] for m in messages),
                "manual_grade": review_slot(case["case_id"]),
                "independent_sdk_reopen": "NOT_VERIFIED_BY_THIS_READONLY_AGGREGATOR",
            }
        )
    usage_totals: dict[str, Any] = {}
    for key in accounts({}):
        values = [a["ledger_delta"][key] for a in all_attempts]
        usage_totals[key] = (
            sum(values)
            if all(type(v) is int for v in values)
            and not orphan_trace_paths
            and not missing_terminal_messages
            else None
        )
    ordered = sorted(
        all_attempts,
        key=lambda a: (
            a["ledger_before"].get("generation_requests") or 0,
            a["ledger_before"].get("generation.known_tokens") or 0,
        ),
    )
    gaps = [
        {"previous": a["artifact"], "next": b["artifact"]}
        for a, b in pairwise(ordered)
        if a["ledger_after"] != b["ledger_before"]
    ]
    grades = reader.json(grades_path) if grades_path else None
    gate = (
        l1_gate(packs, top, grades)
        if cohort == "L1"
        else {"status": "NOT_EVALUATED", "reason": "Manual semantic and effect review required."}
    )
    result = {
        "schema": "v13_5_readonly_evaluation_v1",
        "identity_contract": "ordinary_stored_ids_and_source_versions" if reader.ordinary else
        "historical_digest_contract",
        "cohort": cohort,
        "root": str(root),
        "new_model_calls": 0,
        "new_http_calls": 0,
        "automatic_semantic_pass": False,
        "input_checks": top,
        "denominators": {
            "planned_cases": len(packs),
            "planned_public_messages": sum(len(c["messages"]) for c in fixture["cases"]),
            "retained_attempts": len(all_attempts),
            "orphan_traces_without_terminal_attempt": len(orphan_trace_paths),
        },
        "case_execution_counts": dict(Counter(p["execution_status"] for p in packs)),
        "message_execution_counts": dict(
            Counter(m["execution_status"] for p in packs for m in p["messages"])
        ),
        "attempt_terminal_counts": dict(Counter(a["execution_status"] for a in all_attempts)),
        "attempt_ledger_delta_sum": usage_totals,
        "orphan_trace_paths": orphan_trace_paths,
        "missing_terminal_messages": missing_terminal_messages,
        "continuous_ledger_chain": {
            "status": "UNKNOWN_GAPS"
            if gaps
            else "CONTIGUOUS_RECORDED_ATTEMPTS"
            if all_attempts
            else "NO_ATTEMPTS",
            "gaps": gaps,
            "scope": "Sum unique retained attempts; do not count latest-result copies twice. "
            "Shared-ledger gaps may contain other calls; not assigned to cohort.",
        },
        "L1_gate": gate if cohort == "L1" else None,
        "L3_input_audit": l3_inputs(fixture, ordinary=reader.ordinary) if cohort == "L3" else None,
        "limitations": [
            "Snapshot-before-close is checked as recorded, not an independent reopen.",
            "No regex, keyword, HTTP status or source hash grants semantic PASS.",
            "Unknown quote schemas and absent/redacted traces stay unknown.",
            "Business guards, attempts, effects and semantic authorization "
            "require separate review.",
        ],
        "case_packs": packs,
        "grading_template": {
            "schema": "v13_5_manual_grades_v1",
            "cases": [review_slot(c) for c in case_ids],
        },
        "inputs": reader.inputs,
    }
    return result


def l1_gate(
    packs: list[dict[str, Any]], checks: list[dict[str, Any]], grades: dict[str, Any] | None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "NOT_EVALUATED",
        "minimum_pass": 22,
        "denominator": 24,
        "manual_pass_count": 0,
        "blockers": [],
        "unknown_cases": [],
        "semantic_unknown_cases": [],
    }
    if grades is None:
        return result
    rows = grades.get("cases", [])
    byid = {r["case_id"]: r for r in rows}
    planned = {p["case_id"] for p in packs}
    if len(byid) != len(rows) or set(byid) != planned or len(planned) != 24:
        result.update(status="NOT_PASSED", blockers=["MANUAL_GRADE_DENOMINATOR_MISMATCH"])
        return result
    if any(c["status"] != "PASS" for c in checks):
        result["blockers"].append("INPUT_IDENTITY_NOT_VERIFIED")
    for pack in packs:
        row = byid[pack["case_id"]]
        verdict = row.get("semantic_verdict")
        flags = row.get("critical_blockers", {})
        if (
            verdict not in {"PASS", "FAIL", "UNKNOWN"}
            or not row.get("evidence_refs")
            or not row.get("reviewer")
        ):
            result["unknown_cases"].append(pack["case_id"])
        if verdict == "UNKNOWN":
            result["semantic_unknown_cases"].append(pack["case_id"])
        if any(type(flags.get(k)) is not bool for k in CRITICAL_BLOCKERS):
            result["unknown_cases"].append(pack["case_id"])
        for key in CRITICAL_BLOCKERS:
            if flags.get(key) is True:
                result["blockers"].append(pack["case_id"] + ":" + key)
        if verdict == "PASS":
            if (
                pack["execution_status"] != "COMPLETED"
                or pack["mechanical_failure_count"]
                or not pack.get("acceptance_evidence_complete", False)
            ):
                result["blockers"].append(
                    pack["case_id"] + ":PASS_WITH_INCOMPLETE_OR_FAILED_EVIDENCE"
                )
            else:
                result["manual_pass_count"] += 1
    result["unknown_cases"] = sorted(set(result["unknown_cases"]))
    result["status"] = (
        "NOT_PASSED"
        if result["blockers"]
        else "NOT_EVALUATED"
        if result["unknown_cases"]
        else "PASSED_SCOPED"
        if result["manual_pass_count"] >= 22
        else "NOT_PASSED"
    )
    result["scope"] = (
        "Original normal24 gate only; all FUNC capabilities require their own evidence."
    )
    return result


def write_report(output: Path, result: dict[str, Any]) -> None:
    frozen_root = Path(result["root"]).resolve()
    if output.resolve() == frozen_root or frozen_root in output.resolve().parents:
        raise ValueError("Output must be outside the frozen run root")
    output.mkdir(parents=True, exist_ok=False)
    summary = {
        k: v for k, v in result.items() if k not in {"case_packs", "grading_template", "inputs"}
    }
    for name, value in (
        ("summary.json", summary),
        ("grading-template.json", result["grading_template"]),
        ("input-manifest.json", result["inputs"]),
    ):
        with (output / name).open("x") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    with (output / "case-packs.jsonl").open("x") as stream:
        for pack in result["case_packs"]:
            stream.write(json.dumps(pack, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cohort", choices=("L1", "L2", "L3", "L4"), required=True)
    parser.add_argument("--original-fixture", type=Path)
    parser.add_argument("--grades", type=Path)
    args = parser.parse_args()
    if (
        args.output.resolve() == args.root.resolve()
        or args.root.resolve() in args.output.resolve().parents
    ):
        parser.error("Output must be a new directory outside the frozen run root")
    result = evaluate(
        args.root,
        cohort=args.cohort,
        original_fixture=args.original_fixture,
        grades_path=args.grades,
    )
    write_report(args.output, result)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "denominators": result["denominators"],
                "semantic_status": "MANUAL_REVIEW_REQUIRED",
                "new_http_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
