"""Offline byte-range support evidence and conservative failure-map proposals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from replay_v0213_cost import read, save, sha
from summarize_v0215 import summarize
from v02_local_provider import read_events


def support_coverage(sources: dict[str, bytes], facts: list[str], pages: list[dict]) -> list[bool]:
    """Require matching current bytes and continuous coverage, never just a source ID."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    for page in pages:
        source = sources.get(page["source_id"])
        if source is None or page["version"] != sha(source):
            continue
        start, raw = page["cursor"], page["text"].encode()
        if raw and source[start:start + len(raw)] == raw:
            ranges.setdefault(page["source_id"], []).append((start, start + len(raw)))
    coverage = []
    for fact in facts:
        found = False
        for name, source in sources.items():
            start = source.find(fact.encode())
            if start < 0:
                continue
            reached, end = start, start + len(fact.encode())
            for left, right in sorted(ranges.get(name, [])):
                if left <= reached:
                    reached = max(reached, right)
            found |= reached >= end
        coverage.append(found)
    return coverage


def failure_map(root: Path) -> dict:
    observations = summarize(root)
    cfg = read(root / "manifest.json")["config"]
    for row in observations["rows"]:
        if row["status"] == "NOT_RUN":
            row["earliest_layer_proposal"] = "NOT_TESTED"
            continue
        key, arm, phase = row["key"], row["arm"], row["phase"]
        directory = root / "runs" / key / arm / f"phase-{phase}"
        contract = read(root / "cases" / key / "evaluation" / f"phase-{phase}.json")
        online = root / "cases" / key / "online" / f"phase-{phase}"
        sources = {path.name: path.read_bytes() for path in online.glob("source-*.txt")}
        required = contract["required_support"]
        acquired = [item["page"] for item in read(directory / "acquisition-calls.json")]
        sent = []
        for event in read_events(directory / "provider-ledger.jsonl"):
            if event["event"] != "RESERVED":
                continue
            rid = event["request_id"]
            request = directory / f"{rid}-request.json"
            response = directory / f"{rid}-http.json"
            if not response.exists():
                continue
            pages = []
            for message in read(request)["messages"]:
                if message["role"] == "user":
                    pages.extend(json.loads(message["content"]).get("source_pages", []))
            sent.append({"request_id": rid, "coverage": support_coverage(sources, required, pages),
                "request_file": str(request.relative_to(root)),
                "request_sha256": sha(request.read_bytes()),
                "response_file": str(response.relative_to(root)),
                "response_sha256": sha(response.read_bytes())})
        actions = read_events(directory / "actions.jsonl")
        final_event = next((item for item in reversed(actions)
                            if item["action"]["action"] == "final"), None)
        final_send = next((item for item in sent if final_event and item["request_id"] ==
                           final_event["request_id"]), None)
        acquired_coverage = support_coverage(sources, required, acquired)
        final_coverage = final_send["coverage"] if final_send else [False] * len(required)
        previous = root / "runs" / key / arm / f"phase-{phase - 1}/result.json"
        old_final = read(previous).get("final") if previous.exists() else None
        restored = read(directory / "cold-resume.json")["state"]
        full = all(final_coverage)
        reads = {name for action in actions if action["action"]["action"] == "read"
                 for name in action["action"]["source_ids"]}
        needed = {name for name, raw in sources.items()
                  if any(fact.encode() in raw for fact in required)}
        reason = read(directory / "result.json").get("reason", "")
        if row["decision_correct"]:
            layer = "NO_DECISION_FAILURE"
        elif row["status"] != "DELIVERED":
            layer = ("RESOURCE_LIMIT" if any(word in reason.upper() for word in
                     ("LIMIT", "BUDGET", "TIMEOUT", "DEADLINE")) else "ATTRIBUTION_UNKNOWN")
        elif not full and not needed.issubset(reads):
            layer = "ACQUISITION_NOT_ATTEMPTED"
        elif not all(acquired_coverage):
            layer = "RETRIEVAL_OR_REPRESENTATION_FAILURE"
        elif not full:
            layer = "PRESENTATION_FAILURE_OR_UNKNOWN"
        else:
            layer = "PRESENTED_SUPPORT_USE_FAILURE"
        persistence = bool(phase == 2 and full and old_final and row["final"] and
                           not row["decision_correct"] and
                           row["final"]["decision"] == old_final["decision"])
        row.update(pressure=contract["pressure"], root_cluster=contract["root_cluster"],
            baseline_revision=cfg["revision"], required_support=required,
            acquired_support=acquired_coverage, final_presented_support=final_coverage,
            support_send_evidence=sent, final_event=final_event,
            earliest_layer_proposal=layer, earliest_layer_review="PENDING_NONBLIND_REVIEW",
            old_final=old_final, restored_note=restored.get("payload", {}).get("note"),
            restored_state_version=restored.get("version"),
            post_update_old_premise_candidate=persistence,
            persistence_limit="Candidate requires semantic review; never memory-induced causality",
            first_failure_event=(final_event["request_id"] if final_event and not
                                 row["decision_correct"] else None),
            reason=reason,
            evidence_directory=str(directory.relative_to(root)))
    observations.update(measurement_version="V0216_BYTE_SUPPORT_V1_POST_HOC_EXPLORATORY",
        evaluation_scope="Exact label and byte support; semantic judgments reviewed separately",
        independent_root_clusters=cfg["tasks"], raw_cap=None,
        memory_causality="NOT_TESTED", researcher_review="NONBLIND_NO_JUDGE_MODEL")
    return observations


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    target = args.root / "failure-map-v1.json"
    if target.exists():
        raise ValueError("PRESERVE_PREVIOUS_MAP_USE_NEW_VERSION")
    report = failure_map(args.root)
    save(target, report)
    print(json.dumps({key: report[key] for key in
                      ("requests", "raw_tokens", "unknown_requests", "violations", "arms")}))
