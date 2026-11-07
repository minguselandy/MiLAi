"""Project all reserved64 native condition/candidate cells after the protocol freeze."""
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from milai_lab.datasets.conditional_applicability import compile_condition_union, native_observations
from milai_lab.datasets.followir import applicability_input
from retrieval_mixture import project_applicability_row

protocol_path = Path(sys.argv[1]).resolve()
read = lambda p: json.loads(Path(p).read_text())
protocol = read(protocol_path)
for binding in protocol["code_bindings"]:
    assert Path(binding["frozen"]).read_bytes() == binding["literal_utf8"].encode()
root = protocol_path.parent
output = Path(protocol["prepared_inputs"])
assert not output.exists() and not Path(protocol["semantic_projection_receipt"]).exists()
groups = read(protocol["reservation"])["groups"]
assert groups == protocol["reserved64_metadata"] and len(groups) == 64
selected = {index for group in groups for index in group["rows"]}
assert len(selected) == 127
output.mkdir()
raw_rows, raw_lines = {}, {}
with Path(protocol["raw_source"]).open(encoding="utf-8") as stream:
    for index, line in enumerate(stream):
        if index in selected:
            raw_rows[index], raw_lines[index] = json.loads(line), line
assert raw_rows.keys() == selected
with (output / "selected-original-raw-rows.jsonl").open("x", encoding="utf-8") as stream:
    for index in sorted(selected):
        stream.write(raw_lines[index])
with (output / "selected-original-row-indices.json").open("x") as stream:
    json.dump(sorted(selected), stream)
    stream.write("\n")
projection = {"status": "PROTECTED_QUERY_AND_LABEL_SEMANTICS_PROJECTED_AFTER_FROZEN_PROTOCOL",
    "timestamp_utc": datetime.now(timezone.utc).isoformat(), "protocol": str(protocol_path),
    "frozen_protocol_timestamp": protocol["timestamp_utc"], "native_raw_rows": 127,
    "reserved_query_semantics_opened": True, "native_TEST_semantics_opened": False,
    "new_model_HTTP_calls": 0, "ledger_opened_or_written": False, "no_sha_validation": True}
with Path(protocol["semantic_projection_receipt"]).open("x") as stream:
    json.dump(projection, stream, indent=2)
    stream.write("\n")
result = compile_condition_union(raw_rows, groups, "promptriever")
observations = {}
for group in groups:
    observations[group["source_group"]] = [item for index in group["rows"]
        for item in native_observations(raw_rows[index], index, "promptriever")]
public = []
for index, row in enumerate(result["matrix"]):
    projected = project_applicability_row(row, protocol["operation_state"])
    assert projected["state"] == row["state"] and projected["questions"] == row["questions"]
    family = row["metadata"]["family"]
    task = row["state"]["task"]["retrieval_request"]
    originals = observations[family]
    assert any(item["query"] == task["query"] and item["instruction"] == task["read_goal"]["purpose"] for item in originals)
    assert any(item["candidate"] == row["state"]["candidate"] for item in originals)
    expected = applicability_input(task["query"], task["read_goal"]["purpose"], row["state"]["candidate"])
    assert {k: projected[k] for k in ("state", "questions")} == expected
    assert list(expected["questions"]["applicability"]["criteria"]) == ["satisfies", "does_not_satisfy"]
    public.append({"index": index, "family": family, "payload": expected})
for filename, rows in [("public-inputs.jsonl", public), ("offline-native-matrix.jsonl", result["matrix"]),
                       ("offline-native-condition-pairs.jsonl", result["pairs"])]:
    with (output / filename).open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
with (output / "offline-native-query-units.json").open("x") as stream:
    json.dump({"units": result["units"]}, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
prepared = {"status": "ALL64_NATIVE_CONDITION_CANDIDATE_UNIONS_PUBLIC_INPUT_AND_OFFLINE_MASKS_PREPARED",
    "protocol": str(protocol_path), "counts": result["counts"], "positions": len(public), "families": 64,
    "public_inputs": str(output / "public-inputs.jsonl"),
    "offline_matrix": str(output / "offline-native-matrix.jsonl"),
    "offline_pairs": str(output / "offline-native-condition-pairs.jsonl"),
    "all64_reserved_metadata_records": groups,
    "family_cell_counts": dict(Counter(row["family"] for row in public)),
    "all_native_candidate_titles_text_queries_purposes_literal_preserved": True,
    "all_matrix_cells_including_unknowns_predicted_no_gold_filter": True,
    "public_payload_contains_only_original_state_and_question": True,
    "semantic_projection_receipt": protocol["semantic_projection_receipt"],
    "native_membership_labels_not_independent_factuality": True,
    "shared_corpus_query_family_scope_not_source_disjoint_confirmation": True,
    "new_model_HTTP_calls": 0, "ledger_opened_or_written": False, "no_sha_validation": True}
with Path(protocol["prepared_receipt"]).open("x") as stream:
    json.dump(prepared, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
print("RESERVED64_ALL_NATIVE_CELLS_PREPARED", result["counts"], "modelHTTP0, offline masks unchanged")
