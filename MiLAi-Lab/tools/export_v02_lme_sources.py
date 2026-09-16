"""Export whitelisted opened-development records; never decode the full population."""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import re
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parents[1]
TOKENS = re.compile(rb'"(?:[^"\\]|\\.)*"|[{}\[\]]')
QUESTION_ID = re.compile(rb'(?<!\\)"question_id"\s*:\s*"([^"\\]+)"')


def object_spans(raw: Any) -> Iterator[tuple[int, int]]:
    """Locate array record boundaries without decoding nonselected record fields."""
    depth = 0
    start = None
    for token in TOKENS.finditer(raw):
        value = token.group()
        if value.startswith(b'"'):
            continue
        if value in (b"{", b"["):
            if value == b"{" and depth == 1:
                start = token.start()
            depth += 1
        else:
            depth -= 1
            if value == b"}" and depth == 1 and start is not None:
                yield start, token.end()
                start = None
    if depth != 0 or start is not None:
        raise ValueError("Unbalanced dataset structure")


def source_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    sessions = record["haystack_sessions"]
    ids = record["haystack_session_ids"]
    dates = record["haystack_dates"]
    if not sessions or not len(sessions) == len(ids) == len(dates):
        raise ValueError("Invalid full history shape")
    history = []
    for index, (session, date) in enumerate(zip(sessions, dates, strict=True)):
        turns = []
        for ordinal, turn in enumerate(session):
            role, content = turn["role"], turn["content"]
            if role not in {"user", "assistant", "system", "tool"} or not isinstance(content, str):
                raise ValueError("Invalid source turn")
            turns.append({"turn_ordinal": ordinal, "role": role, "content": content})
        history.append({"session_ordinal": index, "session_id": f"session-{index}",
                        "observed_at": date, "turns": turns})
    return {"schema_version": "v02-lme-source-only-v1", "case_id": record["question_id"],
            "question": record["question"], "question_date": record["question_date"],
            "sessions": history}


def export(dataset: Path, expected_sha: str, wanted: set[str],
           allowed: set[str], output: Path) -> dict[str, Any]:
    if not wanted or not wanted <= allowed:
        raise ValueError("Requested case outside opened-development whitelist")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in ("sources", "labels"):
        (output / name).mkdir(mode=0o700)
    found: dict[str, Any] = {}
    scanned = 0
    with (dataset.open("rb") as handle,
          mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as raw):
        observed = hashlib.sha256(raw).hexdigest()
        if observed != expected_sha:
            raise ValueError("Underlying dataset identity mismatch")
        for start, end in object_spans(raw):
            scanned += 1
            chunk = raw[start:end]
            identity = QUESTION_ID.search(chunk)
            if identity is None or identity.group(1).decode() not in wanted:
                continue
            record = json.loads(chunk)
            case = record["question_id"]
            if case not in wanted or case in found:
                raise ValueError("Duplicate or ambiguous whitelisted record")
            source = source_projection(record)
            encoded = json.dumps(source, ensure_ascii=False, indent=2) + "\n"
            (output / "sources" / f"{case}.json").write_text(encoded, encoding="utf-8")
            labels = {"case_id": case, "reference_answer": record["answer"],
                      "answer_session_ids": record.get("answer_session_ids", []),
                      "question_type": record.get("question_type"),
                      "provenance": "Dataset reference; offline only, never in Host source bundle"}
            (output / "labels" / f"{case}.json").write_text(
                json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            found[case] = {"source_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                           "source_sessions": len(source["sessions"]),
                           "source_turns": sum(len(s["turns"]) for s in source["sessions"]),
                           "byte_span": [start, end]}
    if set(found) != wanted:
        raise ValueError("Missing whitelisted cases: " + ", ".join(sorted(wanted - set(found))))
    manifest = {"created_at": datetime.now(UTC).isoformat(), "dataset_path": str(dataset),
                "dataset_sha256": observed, "cases": found,
                "underlying_population_bytes_scanned": dataset.stat().st_size,
                "records_structurally_scanned": scanned,
                "records_json_decoded": len(found), "nonwhitelisted_records_decoded": 0,
                "access_scope": "Full-file byte hash/structural scan for restricted export; "
                                "only whitelisted record JSON decoded; not full population scoring",
                "formal_cases_scored": 0, "source_fields_projected": True,
                "original_session_ids_copied": False,
                "turn_annotation_fields_copied": False, "offline_labels_separate": True}
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads((LAB / "studies/active/MILA_V02_LME_INCREMENTAL_SELECTION.json").read_text())
    opened = json.loads((LAB / plan["opened_development_selection"]).read_text())
    if opened["opened_development_only"] is not True:
        raise ValueError("Selection is not opened development")
    manifest = json.loads((LAB / "data/manifests/longmemeval-s-cleaned-500.json").read_text())
    filename = manifest["split_files"]["population_500"]
    result = export(Path(manifest["external_root"]) / filename,
                    manifest["file_sha256"][filename], set(plan["D"] + plan["V"]),
                    {c["case_id"] for c in opened["cases"]}, args.output)
    print(json.dumps({"output": str(args.output), "case_count": len(result["cases"]),
                      "nonwhitelisted_records_decoded": 0}))


if __name__ == "__main__":
    main()
