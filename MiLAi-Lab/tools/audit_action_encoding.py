"""Measure native option-level clipping separately from state/head budget clipping."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_jsonl, write_json
from milai_lab.memory.literal_projection import expand_observation_state
from milai_lab.methods.laya_memory_policy import payload_actions, project_operation_payload


def option_encoding(row: dict[str, Any], tok: Any, projection: str = "shared",
                    head_max_len: int = 2048, max_len: int = 12288) -> dict[str, Any]:
    from laya.common import build_head, build_sequence, encode_text, render_options, serialize_state
    from laya.train import to_internal

    projected = project_operation_payload(row, projection)
    question = to_internal("next", projected["questions"]["next"])
    rendered = render_options(question)
    head, markers, stats = build_head(tok, question, head_max_len)
    criteria = list(projected["questions"]["next"]["criteria"])
    options = []
    for index, text in enumerate(rendered):
        tokens = encode_text(tok, " " + text.replace(tok.mask_token, " "),
                             add_special_tokens=False)["input_ids"]
        end = markers[index + 1] if index + 1 < len(markers) else len(head) - 1
        actual = head[markers[index] + 1:end]
        assert actual == tokens[:len(actual)]
        key = criteria[index]
        options.append({"id": key, "kind": row["metadata"]["action_kinds"][key],
            "uncapped_tokens": len(tokens), "encoded_tokens": len(actual),
            "dropped_tokens": len(tokens) - len(actual)})
    state = expand_observation_state(projected["state"])
    table = state.get("action_bindings")
    if table is not None:
        assert table == [asdict(action) for action in payload_actions(row)]
    original = expand_observation_state(row["state"])
    assert {k: v for k, v in state.items() if k != "action_bindings"} == {
        k: v for k, v in original.items() if k != "action_bindings"}
    assert projected["gold"] == row["gold"] and projected["metadata"] == row["metadata"]
    assert criteria == list(row["questions"]["next"]["criteria"])
    ids, _, sequence_stats = build_sequence(tok, projected["state"], question,
        max_len=max_len, head_max_len=head_max_len, return_truncation_stats=True)
    sequence_stats["head_tokens_dropped"] = len(build_head(tok, question, 100000)[0]) - len(head)
    return {"event_id": row["metadata"]["event_id"], "family": row["metadata"]["family"],
        "labelled": bool(row["gold"]), "options": options,
        "capped_options": sum(x["dropped_tokens"] > 0 for x in options),
        "head_stats": stats, "head_tokens": len(head),
        "sequence_tokens": len(ids), "sequence_stats": sequence_stats,
        "sdk_mask_replacements": serialize_state(projected["state"]).count(tok.mask_token),
        "literal_complete_action_table_present": table is not None,
        "scope": "Option text clipping;table presence is separate and still requires a complete "
                 "state-token audit. Some clipped text may appear elsewhere in observations; "
                 "absence of the table alone does not quantify uniquely lost semantic facts."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("tokenizer", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--feedback-dev", type=Path)
    parser.add_argument("--projection", default="shared")
    parser.add_argument("--max-len", type=int, default=12288)
    parser.add_argument("--head-max-len", type=int, default=2048)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
        args.tokenizer, local_files_only=True)
    started, cpu = time.perf_counter(), time.process_time()
    splits = [(name, args.data / f"{name}.jsonl") for name in ("train", "dev")]
    if args.feedback_dev is not None:
        splits.append(("feedback-dev", args.feedback_dev))
    summaries = {}
    for split, path in splits:
        records = [option_encoding(row, tok, args.projection, args.head_max_len, args.max_len)
                   for row in read_jsonl(path)]
        write_json(args.output / f"{split}.json", records)
        summaries[split] = {"rows": len(records),
            "rows_with_capped_options": sum(x["capped_options"] > 0 for x in records),
            "labelled_rows_with_capped_options": sum(x["labelled"] and x["capped_options"] > 0
                                                     for x in records),
            "rows_with_complete_action_table": sum(x["literal_complete_action_table_present"]
                                                     for x in records),
            "rows_capped_without_action_table": sum(x["capped_options"] > 0
                and not x["literal_complete_action_table_present"] for x in records),
            "capped_options_by_kind": dict(Counter(o["kind"] for x in records
                for o in x["options"] if o["dropped_tokens"])),
            "option_token_drops": sum(o["dropped_tokens"] for x in records for o in x["options"]),
            "native_state_truncated_rows": sum(x["sequence_stats"]["state_tokens_dropped"] > 0
                                                for x in records),
            "native_head_truncated_rows": sum(x["sequence_stats"]["head_tokens_dropped"] > 0
                                               for x in records),
            "max_sequence_tokens": max(x["sequence_tokens"] for x in records),
            "sequence_tokens": sum(x["sequence_tokens"] for x in records),
            "sdk_mask_replacements": sum(x["sdk_mask_replacements"] for x in records),
            "head_option_collision_rows": sum(x["head_stats"]["options_distinct"]
                                               < x["head_stats"]["options"] for x in records)}
        print(json.dumps({"split": split, **summaries[split]}), flush=True)
    write_json(args.output / "audit.json", {"status": "MEASURED_NATIVE_OPTION_ENCODING",
        "projection": args.projection, "splits": summaries, "model_calls": 0,
        "max_len": args.max_len, "head_max_len": args.head_max_len,
        "no_sha_validation": True, "ledger_recorded": False,
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}})


if __name__ == "__main__":
    main()
