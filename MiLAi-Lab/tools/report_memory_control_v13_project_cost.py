"""Aggregate V13 Reader charges from the physical collection receipts and native readout windows."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from milai_lab.datasets.memory_control_report import write_json
from milai_lab.scorers.memory_control_episode_metrics import input_result
from report_memory_control_v13_feedback import load


def sources(root):
    for folder, children, files in os.walk(root):
        path = Path(folder)
        # These subtrees contain static inputs, fitted tensors, or aliases of the
        # operational logs. Read each producer through its registered output root.
        if path == root:
            children[:] = [
                c
                for c in children
                if c not in {"models", "weights", "staging", "reference", "fresh-sources", "ref"}
            ]
        if "receipts" in children:
            yield path, "collection"
        if "protocol.json" in files and ("episodes" in children or "episode-archive.json" in files):
            yield path, "readout"
        children[:] = [
            c
            for c in children
            if not c.startswith(".")
            and c
            not in {
                "packs",
                "receipts",
                "native-receipts",
                "episodes",
                "checkpoint",
                "updates",
                "compute",
            }
        ]


def read_json(path):
    return json.loads(path.read_text())


def tokens(counts, packet):
    costs = packet.get("costs", {})
    for axis in ("reader_input_tokens", "reader_output_tokens"):
        value = costs.get(axis)
        if type(value) is int:
            kind = (
                "provider" if costs.get("reader_usage_source") == "provider" else "other_reported"
            )
            counts[kind + "_" + axis] += value
            counts[kind + "_" + axis + "_records"] += 1
    counts["observed_attempt_packets"] += 1
    counts["paid_error_packets"] += int(
        packet["status"] in {"action_failed", "reader_error", "reader_interrupted", "scorer_error"}
    )
    counts["paid_format_failure_packets"] += int(packet["status"] == "scored_format_failure")


def slot_set(row, charges=None):
    ranges = row.get("ledger_intervals")
    if ranges is None:
        if "ledger_before" not in row or "ledger_after" not in row:
            return None
        ranges = [[row["ledger_before"], row["ledger_after"]]]
    result = set()
    for start, end in ranges:
        if type(start) is not int or type(end) is not int:
            return None
        if end < start or start < 0:
            raise ValueError("Invalid physical ledger interval")
        if charges is not None and end - start > charges:
            raise ValueError("Invalid physical ledger interval")
        positions = range(start, end)
        if result.intersection(positions):
            raise ValueError("Overlapping intervals within a single native receipt")
        result.update(positions)
    if charges is not None and len(result) != charges:
        raise ValueError("Physical interval and recorded charge disagree")
    return result


def claim(slots, positions):
    if slots.intersection(positions):
        raise ValueError("A native Reader charge was claimed twice")
    slots.update(positions)


def span(row, charges, slots):
    positions = slot_set(row, charges)
    if positions is None:
        return 0
    claim(slots, positions)
    return len(positions)


def readout_charge_evidence(windows, packets):
    """Union window and packet reservations. Provider IDs and imported labels remain separate."""
    counts = Counter()
    positions = set()
    by_invocation = {}
    anonymous_slots = set()
    for w in windows:
        paid = w["reader_requests_this_invocation"]
        counts["settled_new_requests"] += paid
        part = slot_set(w, paid)
        if part is not None:
            claim(positions, part)
        elif paid:
            counts["window_charges_without_bounded_slots"] += paid
        unknown = w.get("reader_charge_unknown_records", 0)
        counts["unknown_charge_records"] += unknown
        if key := w.get("invocation_id"):
            if key in by_invocation:
                raise ValueError("Duplicate invocation settlement")
            by_invocation[key] = (part, unknown, paid)
        elif part is not None:
            anonymous_slots.update(part)
    packet_positions = set()
    attributed_unlocated = Counter()
    for packet in packets.values():
        charge = packet.get("reader_charge")
        if not charge or packet.get("measurement_reused_from"):
            continue
        key = charge.get("invocation_id")
        part = slot_set(charge)
        window = by_invocation.get(key)
        if part is None:
            counts["unknown_packet_intervals"] += 1
            if window is None:
                counts["unknown_charge_records"] += 1
            continue
        claim(packet_positions, part)
        if window:
            if window[0] is not None:
                if not part <= window[0]:
                    raise ValueError("Packet charge lies outside its settled window")
            else:
                claim(positions, part)
                attributed_unlocated[key] += len(part)
                if attributed_unlocated[key] > window[2]:
                    raise ValueError("Packet reservations exceed the unlocated window charge")
            counts["packet_slots_already_in_window"] += len(part)
        elif part and part <= (positions if key is None else anonymous_slots):
            counts["packet_slots_already_in_window"] += len(part)
        else:
            claim(positions, part)
            counts["packet_only_new_requests"] += len(part)
            counts["settled_new_requests"] += len(part)
    counts["checked_ledger_slots"] = len(positions)
    return counts, positions


def window_records(path):
    contents = path.read_bytes()
    lines = contents.splitlines(keepends=True)
    partial = bool(lines and not lines[-1].endswith(b"\n"))
    return [json.loads(line) for line in (lines[:-1] if partial else lines)], partial


def aggregate(root):
    slots = set()
    response_ids = set()
    runs = []
    grand = Counter()

    def register_packet(counts, packet):
        tokens(counts, packet)
        response = (packet.get("reader_result") or {}).get("response") or {}
        rid = response.get("id")
        if not rid:
            return
        if rid in response_ids:
            raise ValueError(f"Duplicate provider response ID claimed as newly measured: {rid}")
        response_ids.add(rid)
        counts["provider_response_ids"] += 1

    for directory, kind in sorted(sources(root)):
        counts = Counter()
        if kind == "collection":
            receipts = directory / "receipts"
            if not receipts.exists():
                raise FileNotFoundError(receipts)
            for path in sorted(receipts.glob("*.json.gz")):
                row = load(path)
                charges = row["actual_requests"]
                if charges is None:
                    counts["unknown_charge_records"] += 1
                elif charges:
                    counts["settled_new_requests"] += charges
                    counts["checked_ledger_slots"] += span(row, charges, slots)
                    register_packet(counts, row)
                elif row.get("measurement_reused_from"):
                    counts["reused_results"] += 1
            counts["dispatch_markers_at_snapshot"] = len(list(receipts.glob("*.inflight")))
            if (directory / "round.json").is_file():
                meta = read_json(directory / "round.json")
                detail = meta["sampler"]
            else:
                detail = "terminal_feedback"
        else:
            protocol, packets = input_result(directory)
            if protocol["arm"].get("environment") != "qrag_milai_v13":
                continue
            pop = protocol["population"]
            detail = pop.get("v13_role", pop["role"])
            info = read_json(directory / "run.json") if (directory / "run.json").exists() else {}
            log = directory / "windows.jsonl"
            if log.is_file():
                windows, partial = window_records(log)
                counts["incomplete_window_log"] = int(partial)
            else:
                # S0 used the native single-invocation runner directly.
                windows = [info] if info else []
            billing, owned = readout_charge_evidence(windows, packets)
            claim(slots, owned)
            counts.update(billing)
            for packet in packets.values():
                if packet.get("measurement_reused_from"):
                    counts["reused_results"] += 1
                elif packet.get("costs", {}).get("reader_request_attempted") is True:
                    register_packet(counts, packet)
                elif charge := packet.get("reader_charge"):
                    positions = slot_set(charge)
                    if positions:
                        counts["paid_without_observed_http_attempt"] += 1
                    elif packet.get("status") == "dispatching":
                        counts["dispatch_markers_at_snapshot"] += 1
                elif packet.get("status") == "dispatching":
                    counts["dispatch_markers_at_snapshot"] += 1
            gap = (
                counts["observed_attempt_packets"]
                + counts["paid_without_observed_http_attempt"]
                - counts["settled_new_requests"]
            )
            if info.get("status") == "COMPLETED" and gap:
                counts["closed_readouts_with_charge_gap"] += 1
            if gap:
                # A live readout can have receipts ahead of its window settlement. Unknown or
                # multi-charge failures in closed runs also remain visible to the final audit.
                counts["attempt_packets_above_settlement"] += max(0, gap)
                counts["settlement_above_attempt_packets"] += max(0, -gap)
        grand.update(counts)
        runs.append(dict(path=str(directory.relative_to(root)), kind=kind, scope=detail, **counts))

    return dict(
        snapshot_utc=datetime.now(UTC).isoformat(),
        root=str(root),
        runs=runs,
        totals=grand,
        reconciled_observed_requests=(
            grand["settled_new_requests"]
            if not any(
                grand[k]
                for k in (
                    "attempt_packets_above_settlement",
                    "settlement_above_attempt_packets",
                    "unknown_charge_records",
                    "incomplete_window_log",
                    "dispatch_markers_at_snapshot",
                )
            )
            else None
        ),
        fully_attributed_new_reader_slots=(
            len(slots)
            if len(slots) == grand["settled_new_requests"]
            and not any(
                grand[k]
                for k in (
                    "unknown_charge_records",
                    "incomplete_window_log",
                    "dispatch_markers_at_snapshot",
                )
            )
            else None
        ),
        distinct_checked_slots=len(slots),
        distinct_observed_provider_requests=len(response_ids),
        scope="Settled, newly billed V13 Reader requests. Prior labels and arm exposure "
        "are accounted separately. Token totals cover observed attempt packets, "
        "including any open window whose ledger delta has not yet been written.",
        sha_validation=False,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    write_json(args.out, aggregate(args.root.resolve()))
