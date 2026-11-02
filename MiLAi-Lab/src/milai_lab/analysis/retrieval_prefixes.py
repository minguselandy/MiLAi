"""Select recorded acquisition prefixes without inferring semantic or Host success."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _read(path: Path) -> Any:
    return json.loads(path.read_text())


def _coverage(state: dict[str, Any]) -> dict[tuple[str, int], list[tuple[int, int]]]:
    spans: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    for material in state["observed_materials"]:
        if material["kind"] != "original_source" or not material["body_delivered"]:
            continue
        for span in material["source_ranges"]:
            start, end = span["start"], span["end"]
            if not 0 <= start <= end:
                raise ValueError("Recorded Source interval has invalid bounds")
            if start < end:
                spans[span["source_ref"], span["source_revision"]].append((start, end))
    merged: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for key, intervals in spans.items():
        result: list[tuple[int, int]] = []
        for start, end in sorted(intervals):
            if result and start <= result[-1][1]:
                result[-1] = (result[-1][0], max(end, result[-1][1]))
            else:
                result.append((start, end))
        merged[key] = result
    return merged


def new_source_intervals(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Subtract literal observed ranges; overlapping aliases do not add evidence twice.

    body_delivered is the recorded controller observation flag. This function
    does not certify source text, relevance, independent evidence, or Host receipt.
    """
    old, current = _coverage(before), _coverage(after)
    result = []
    for (source, revision), spans in sorted(current.items()):
        for start, end in spans:
            cursor = start
            for left, right in old.get((source, revision), []):
                if right <= cursor or left >= end:
                    continue
                if left > cursor:
                    result.append({"source_ref": source, "source_revision": revision,
                                   "start": cursor, "end": min(left, end)})
                cursor = max(cursor, right)
                if cursor >= end:
                    break
            if cursor < end:
                result.append({"source_ref": source, "source_revision": revision,
                               "start": cursor, "end": end})
    return result


def acquisition_steps(control: dict[str, Any]) -> list[dict[str, Any]]:
    """Inspect successful READ transitions in this exact saved execution prefix."""
    prefix = control["prefix_trace"]
    if [event["step"] for event in prefix] != list(range(control["step"])):
        raise ValueError("Saved prefix steps must preserve the actual contiguous execution")
    if not prefix:
        return []
    after = [event["before"] for event in prefix[1:]] + [control["state"]]
    result = []
    for event, state in zip(prefix, after, strict=True):
        action, = [a for a in event["actions"] if a["id"] == event["selected"]]
        if (action["kind"] == "READ" and "result" in event and event["result"]["ok"]):
            spans = new_source_intervals(event["before"], state)
            if spans:
                result.append({"step": event["step"], "action": action,
                               "new_source_intervals": spans})
    return result


def select_call_prefixes(captured: Path) -> dict[str, Any]:
    """Keep at most three recorded slots from one call, including failed calls.

    A missing post-READ checkpoint is not reconstructed from a later trace. The
    fourth requirement/return-budget condition needs a separate actual formation.
    """
    original = _read(captured / "call.json")
    slots: dict[str, Any] = {"initial": None, "first_read": None, "second_read": None,
                             "same_known_changed_requirement_or_return_limit": None}
    result = {"capture": str(captured), "original_call_status": original["status"],
              "slots": slots, "post_state_inventory": [],
              "fourth_slot_status": "PENDING_ACTUAL_RECEIPT_AND_LEGAL_CONDITION_BINDING"}
    if original["status"] not in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}:
        return {**result, "status": "UNCLOSED_CAPTURE_RETAINED_WITHOUT_SELECTION"}
    if original["initial_observation"] is not None:
        slots["initial"] = {"capture": str(captured), "control_step": 0,
                            "actions": len(original["initial_actions"])}
    snapshots = [(p.parent, _read(p)) for p in captured.glob("steps/*/call.json")]
    snapshots.sort(key=lambda item: item[1]["control_step"])
    if len({row["control_step"] for _, row in snapshots}) != len(snapshots):
        raise ValueError("A recorded control step has more than one snapshot")
    inventory = []
    for path, call in snapshots:
        if any(call[key] != original[key] for key in (
                "call_id", "bank", "public_message", "source_root", "source_version", "request")):
            raise ValueError("A post-state belongs to a different call or request")
        control = _read(path / call["control_checkpoint"])
        if (control["state"] != call["initial_observation"]
                or control["step"] != call["control_step"]
                or control["prefix_trace"][0]["before"] != original["initial_observation"]):
            raise ValueError("Saved state or initial prefix differs from the actual call")
        acquired = acquisition_steps(control)
        row = {"capture": str(path), "control_step": control["step"],
               "actual_call_status": call["status"], "acquisition_steps": acquired,
               "new_source_read_count": len(acquired), "actions": len(call["initial_actions"])}
        inventory.append(row)
        if (call["status"] not in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}
                or not acquired or acquired[-1]["step"] != control["step"] - 1):
            continue
        if len(acquired) in (1, 2):
            name = "first_read" if len(acquired) == 1 else "second_read"
            if slots[name] is None:
                slots[name] = row
    return {**result, "status": "ACTUAL_PREFIX_SLOTS_SELECTED_MISSING_RETAINED",
            "post_state_inventory": inventory}


def select_collection_prefixes(plan: dict[str, Any], collection: Path) -> dict[str, Any]:
    """Bind primary positions to their first actual call, never their first success."""
    driver = _read(collection / "driver.json")
    if driver["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES", "FAILED"}:
        raise ValueError("Prefix selection requires a terminal collection")
    if driver["source_version"] != plan["functional_source_version"]:
        raise ValueError("Collection code version differs from the declared prefix study")
    fixture = _read(Path(plan["histories"]))
    if fixture != _read(collection / "fixture.json"):
        raise ValueError("Collected histories differ from the declared source fixture")
    histories = {h["source_group"]: h for h in fixture["histories"]}
    calls: dict[tuple[str, str, str], list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    for path in collection.glob("frozen-retrieval-calls/*/call.json"):
        call = _read(path)
        key = (str(Path(call["source_root"]).resolve()), call["bank"],
               call["public_message"]["message_id"])
        calls[key].append((path.parent, call))
    records = []
    for mapping in plan["mapping"]:
        family, position = mapping["family"], mapping["primary_public_position"]
        history = histories[family]
        request, = [q for q in history["requests"] if q["id"] == position]
        bank = (history["id"] if history.get("continuous") and not request.get("independent")
                else history["id"] + "-" + position)
        for collector in plan["collectors"]:
            profile = collector + "-rich"
            matching = calls[str((collection / profile).resolve()), bank, position]
            matching.sort(key=lambda item: item[1]["captured_epoch"])
            identity = {"history": history["id"], "policy": collector,
                        "interface": "rich", "request": position}
            completed = [row for row in driver["completed"]
                         if all(row[key] == value for key, value in identity.items())]
            if len(completed) > 1:
                raise ValueError("The primary public position has multiple completion records")
            if completed:
                position_status = {"status": completed[0]["status"],
                                   "error": completed[0]["error"], "completion_record": True}
            elif driver["status"] == "FAILED" and driver.get("active") is not None and all(
                    driver["active"][key] == value for key, value in identity.items()):
                position_status = {"status": "ENTERED_WITHOUT_COMPLETION_RECORD",
                                   "completion_record": False}
            else:
                position_status = {"status": "NOT_EXECUTED", "completion_record": False}
            record = {"family": family, "primary_public_position": position,
                      "collector": collector, "actual_call_count": len(matching),
                      "all_call_captures": [str(path) for path, _ in matching],
                      "public_position": position_status}
            if not matching:
                record.update(status="NO_ACTUAL_PRIMARY_CALL", selection=None)
            elif len(matching) > 1 and matching[0][1]["captured_epoch"] == (
                    matching[1][1]["captured_epoch"]):
                record.update(status="FIRST_CALL_ORDER_UNKNOWN", selection=None)
            else:
                path, call = matching[0]
                version = _read(collection / profile / "input-freeze.json")["source_version"]
                if (version["git_commit"] != plan["functional_source_version"]
                        or call["source_version"] != version):
                    raise ValueError("Primary call has a different code version")
                record.update(status="FIRST_ACTUAL_CALL_RETAINED",
                              selection=select_call_prefixes(path))
            records.append(record)
    return {"status": "PRIMARY_PREFIX_INVENTORY_CREATED;NO_BRANCH_QUALITY_LABELS",
        "collection_status": driver["status"], "records": records,
        "scope": "Select recorded successful READ acquisition metadata, not source truth, "
                 "semantic complementarity or Host-known evidence. Missing/failed positions "
                 "remain. No later successful call or other native variant fills a slot. "
                 "Fourth same-known condition requires actual receipt formation separately."}
