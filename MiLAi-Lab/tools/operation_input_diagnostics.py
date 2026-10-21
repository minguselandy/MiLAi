"""Exact recorded-action baselines and native evaluation-wire witness positions.

No model is loaded. Whole reviewed source ranges are located, not minimal answer
spans. Static preference acceptance is not closed-loop policy or Host success.
"""
from __future__ import annotations

import argparse
import json
import time
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.memory.functional_state import body_text
from milai_lab.memory.literal_projection import expand_observation_state
from milai_lab.methods.cache_memory_policy import CacheMemoryPolicy
from milai_lab.methods.laya_memory_policy import payload_actions, project_operation_payload
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    FixedMemoryPolicy,
    MemoryAction,
    MemoryControlState,
    MemoryPolicy,
    RulesMemoryPolicy,
)
from milai_lab.methods.memory_control_learning import score_operation_predictions


def recorded_inputs(row: dict[str, Any]) -> tuple[MemoryControlState, list[MemoryAction]]:
    """Restore only recorded observations/options, never consult labels or reviews."""
    state = expand_observation_state(row["state"])
    actions = payload_actions(row)
    state.pop("action_bindings", None)
    return MemoryControlState(**state), actions


def simple_choices(row: dict[str, Any]) -> dict[str, str]:
    state, actions = recorded_inputs(row)
    policies: dict[str, MemoryPolicy] = {
        "fixed": FixedMemoryPolicy(4), "fixed_context": FixedContextMemoryPolicy(4),
        "rules": RulesMemoryPolicy(4), "view_cache": CacheMemoryPolicy(4, 0.35)}
    choices = {name: actions[0].id if len(actions) == 1 else policy.choose(state, actions)
               for name, policy in policies.items()}
    choices["first_offered"] = actions[0].id
    choices["handoff"] = (actions[0].id if len(actions) == 1 else
                          next(a.id for a in actions if a.kind == "HANDOFF" and not a.parameters))
    assert set(choices.values()) <= {a.id for a in actions}
    return choices


def serialized_strings(state: dict[str, Any], mask_token: str) -> tuple[
        str, list[dict[str, Any]]]:
    """Match native json.dumps exactly and retain value offsets after mask replacement."""
    pieces: list[str] = []
    spans: list[dict[str, Any]] = []
    position = 0

    def emit(text: str) -> None:
        nonlocal position
        rendered = text.replace(mask_token, " ")
        pieces.append(rendered)
        position += len(rendered)

    def visit(value: Any, path: tuple[Any, ...]) -> None:
        if isinstance(value, dict):
            emit("{")
            for index, (key, item) in enumerate(value.items()):
                if index:
                    emit(", ")
                emit(json.dumps(key, ensure_ascii=False))
                emit(": ")
                visit(item, (*path, key))
            emit("}")
        elif isinstance(value, list):
            emit("[")
            for index, item in enumerate(value):
                if index:
                    emit(", ")
                visit(item, (*path, index))
            emit("]")
        else:
            start = position
            emit(json.dumps(value, ensure_ascii=False))
            if isinstance(value, str):
                spans.append({"path": list(path), "text": value,
                              "start": start + 1, "end": position - 1})

    visit(state, ())
    text = "".join(pieces)
    assert text == json.dumps(state, ensure_ascii=False).replace(mask_token, " ")
    return text, spans


def observation_path(path: list[Any]) -> bool:
    return bool(path) and (path[0] != "task" or path[:2] == ["task", "known_evidence"])


def literal_value_path(projected: dict[str, Any], original: dict[str, Any],
                       path: list[Any]) -> tuple[Any, ...]:
    """Trace one original field through reversible tables, without matching unrelated text."""
    node: Any = projected
    reference: Any = original
    physical: tuple[Any, ...] = ()
    remaining = list(path)
    while True:
        if node == reference:
            return (*physical, *remaining)
        if isinstance(node, dict) and set(node) == {"meta"}:
            key = str(node["meta"])
            node = projected["metadata_table"][key]
            physical = ("metadata_table", key)
        elif isinstance(node, dict) and set(node) == {"table"}:
            index, field, *remaining = remaining
            table = node["table"]
            reference = reference[index][field]
            if field in table["shared"]:
                node = table["shared"][field]
                physical = (*physical, "table", "shared", field)
            else:
                column = table["columns"].index(field)
                node = table["rows"][index][column]
                physical = (*physical, "table", "rows", index, column)
        elif isinstance(node, dict) and set(node) == {"literal"}:
            field, *remaining = remaining
            index = next(i for i, (key, _) in enumerate(node["literal"]) if key == field)
            reference = reference[field]
            node = node["literal"][index][1]
            physical = (*physical, "literal", index, 1)
        else:
            field, *remaining = remaining
            reference, node = reference[field], node[field]
            physical = (*physical, field)


def source_fragments(state: dict[str, Any], sources: dict[str, dict[str, Any]],
                     ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """Require an explicit source ref or a unique role/clock/body-range identity."""
    fragments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    diagnostics: Counter[str] = Counter()

    def visit(value: Any, path: list[Any]) -> None:
        if isinstance(value, dict):
            content = value.get("content")
            if isinstance(content, str) and content and observation_path(path):
                direct = value.get("source_ref")
                candidates = ([sources[direct]] if isinstance(direct, str) and direct in sources
                              else [] if direct is not None else [s for s in sources.values()
                              if value.get("role") == s["role"]
                              and value.get("captured_at") is not None
                              and value["captured_at"] == s.get("observed_at")])
                matches: list[tuple[str, list[int]]] = []
                for source in candidates:
                    body = body_text(source)
                    span = cast(list[int], value.get(
                        "source_range", value.get("range", [0, len(body)])))
                    if (value.get("role", source["role"]) == source["role"]
                            and value.get("origin", source.get("origin")) == source.get("origin")
                            and 0 <= span[0] < span[1] <= len(body)
                            and body[span[0]:span[1]] == content):
                        matches.append((source["event_id"], span))
                if len(matches) == 1:
                    ref, span = matches[0]
                    fragments[ref].append({"text": content, "range": span,
                                           "observation_path": [*path, "content"]})
                else:
                    diagnostics["ambiguous_content_records" if matches
                                else "unbound_content_records"] += 1
            for key, item in value.items():
                visit(item, [*path, key])
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, [*path, index])

    visit(state, [])
    return dict(fragments), dict(diagnostics)


def coverage_end(fragments: list[dict[str, Any]], size: int) -> int | None:
    """Earliest native prefix containing a complete union of the original character ranges."""
    admitted = []
    for item in sorted(fragments, key=lambda x: x["token_end"]):
        if not item["fully_encoded"]:
            continue
        admitted.append(item["range"])
        cursor = 0
        for start, end in sorted(admitted):
            if start > cursor:
                break
            cursor = max(cursor, end)
        if size > 0 and cursor == size:
            return int(item["token_end"])
    return None


def witness_positions(row: dict[str, Any], sources: dict[str, dict[str, Any]], tok: Any, *,
                      projection: str = "shared", max_len: int = 12288,
                      head_max_len: int = 2048) -> dict[str, Any]:
    from laya.common import build_sequence, encode_text, serialize_state
    from laya.train import to_internal

    projected = project_operation_payload(row, projection)
    text, strings = serialized_strings(projected["state"], tok.mask_token)
    assert text == serialize_state(projected["state"]).replace(tok.mask_token, " ")
    encoded = encode_text(tok, text, add_special_tokens=False, return_offsets_mapping=True)
    question = to_internal("next", projected["questions"]["next"])
    ids, _, stats = build_sequence(tok, projected["state"], question, max_len=max_len,
        head_max_len=head_max_len, state_ids=encoded["input_ids"], return_truncation_stats=True)
    head = len(ids) - stats["state_tokens_used"] - 1
    offsets = [(i, a, b) for i, (a, b) in enumerate(encoded["offset_mapping"]) if b > a]
    token_starts, token_ends = [a for _, a, _ in offsets], [b for _, _, b in offsets]
    assert token_starts == sorted(token_starts) and token_ends == sorted(token_ends)
    by_path = {tuple(span["path"]): span for span in strings}
    full = expand_observation_state(row["state"])
    fragments, diagnostics = source_fragments(full, sources)
    review = row["metadata"].get("source_review", {})
    proofs = review.get("support_sets")
    witnesses: dict[str, dict[str, Any]] = {}
    proof_ends: list[int | None] = []
    for proof in proofs or []:
        witness_ends: list[int | None] = []
        for witness in proof:
            identity = (witness["session"], witness["event_key"], witness["role"])
            matches = [s for s in sources.values() if (
                s["session"], s["capture_key"], s["role"]) == identity]
            if len(matches) != 1:
                diagnostics["unresolved_witness_identity"] = (
                    diagnostics.get("unresolved_witness_identity", 0) + 1)
                witness_ends.append(None)
                continue
            source = matches[0]
            ref = source["event_id"]
            if ref not in witnesses:
                located = []
                for fragment in fragments.get(ref, []):
                    path = literal_value_path(projected["state"], full,
                                              fragment["observation_path"])
                    span = by_path[path]
                    assert span["text"] == fragment["text"]
                    first = bisect_right(token_ends, span["start"])
                    stop = bisect_left(token_starts, span["end"])
                    if first < stop:
                        start_token, end_token = offsets[first][0], offsets[stop - 1][0] + 1
                        located.append({"range": fragment["range"],
                            "observation_path": fragment["observation_path"],
                            "literal_path": span["path"], "token_start": head + start_token,
                            "token_end": head + end_token,
                            "sdk_mask_replaced": tok.mask_token in fragment["text"],
                            "fully_encoded": end_token <= stats["state_tokens_used"]})
                witnesses[ref] = {"identity": list(identity), "fragments": located,
                    "whole_body_end": coverage_end(located, len(body_text(source)))}
            witness_ends.append(witnesses[ref]["whole_body_end"])
        proof_ends.append(max(x for x in witness_ends if x is not None) if witness_ends
                          and all(x is not None for x in witness_ends) else None)
    available = [end for end in proof_ends if end is not None]
    completion = min(available) if available else None
    bucket = ("no_original_witness_contract" if not proofs else "unavailable_or_incomplete"
              if completion is None else
              ["first_quarter", "second_quarter", "third_quarter", "fourth_quarter"][
                  min(3, int(completion / len(ids) * 4))])
    return {"event_id": row["metadata"]["event_id"], "family": row["metadata"]["family"],
        "labelled": bool(row["gold"]), "sequence_tokens": len(ids), "head_tokens": head,
        "state_tokens_dropped": stats["state_tokens_dropped"],
        "length_bucket": "<=8192" if len(ids) <= 8192 else ">8192",
        "candidate_count": len(full["pending_candidates"]),
        "candidate_bucket": ("0" if not full["pending_candidates"] else "1-8"
            if len(full["pending_candidates"]) <= 8 else "9-16"
            if len(full["pending_candidates"]) <= 16 else "17+"),
        "proof_complete": review.get("proof_complete"),
        "witness_contract": "absent" if proofs is None else "empty" if not proofs else "present",
        "witnesses": witnesses, "witness_set_body_ends": proof_ends,
        "earliest_witness_set_body_end": completion, "position_bucket": bucket,
        "identity_diagnostics": diagnostics,
        "sdk_mask_replacements": serialize_state(projected["state"]).count(tok.mask_token),
        "scope": "Canonical evaluation input;whole reviewed source bodies/ranges,not minimal "
                 "fact spans,provenance-token completeness,Host delivery or answer sufficiency. "
                 "Native SDK mask replacement is preserved and counted."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("tokenizer", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--result-root", action="append", type=Path, required=True)
    parser.add_argument("--projection", choices=("shared", "shared_request_text"), default="shared")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
        args.tokenizer, local_files_only=True)

    @lru_cache(maxsize=32)
    def sources_for(raw_path: str) -> dict[str, dict[str, Any]]:
        path = Path(raw_path)
        paths = ([path] if path.is_absolute() else [root / path for root in args.result_root])
        found = [p for p in paths if p.exists()]
        if len(found) != 1:
            raise ValueError("Recorded result must resolve to one explicitly supplied root")
        return {s["event_id"]: s for s in read_json(found[0])["sources"]}

    started, cpu = time.perf_counter(), time.process_time()
    reports = {}
    for split in ("train", "dev"):
        rows = read_jsonl(args.data / f"{split}.jsonl")
        predictions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        positions = []
        for index, row in enumerate(rows):
            for name, choice in simple_choices(row).items():
                predictions[name].append({"event_id": row["metadata"]["event_id"],
                                          "choice": choice})
            positions.append(witness_positions(row, sources_for(row["metadata"]["result_path"]),
                                               tok, projection=args.projection))
            if (index + 1) % 256 == 0:
                print(json.dumps({"split": split, "rows": index + 1}), flush=True)
        write_json(args.output / f"{split}-positions.json", positions)
        write_json(args.output / f"{split}-baseline-predictions.json", dict(predictions))
        reports[split] = {"rows": len(rows), "labelled": sum(bool(x["gold"]) for x in rows),
            "baselines": {name: score_operation_predictions(rows, values)
                          for name, values in predictions.items()},
            "position_buckets": dict(Counter(x["position_bucket"] for x in positions)),
            "labelled_position_buckets": dict(Counter(x["position_bucket"]
                                                       for x in positions if x["labelled"])),
            "length_buckets": dict(Counter(x["length_bucket"] for x in positions)),
            "candidate_buckets": dict(Counter(x["candidate_bucket"] for x in positions)),
            "witness_contracts": dict(Counter(x["witness_contract"] for x in positions))}
        write_json(args.output / f"{split}-summary.json", reports[split])
    report = {"status": "COMPLETE_RECORDED_STATE_DIAGNOSTICS_NOT_ROLLOUTS", "splits": reports,
        "projection": args.projection, "model_calls": 0, "world_actions_executed": 0,
        "no_sha_validation": True, "ledger_recorded": False,
        "scope": "All six prespecified baselines retained;unaccepted choices are not certified "
                 "bad actions. Whole-source text positions do not certify semantic sufficiency.",
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}}
    write_json(args.output / "analysis.json", report)
    print(json.dumps({"status": report["status"], "compute": report["compute"]}), flush=True)


if __name__ == "__main__":
    main()
