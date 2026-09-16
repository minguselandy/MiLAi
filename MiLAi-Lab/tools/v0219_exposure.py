"""Reconstruct positive corpus references without emitting prior task or transcript contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from v0219_inventory import LAB, digest, read, save, sha

SESSION = Path(
    "/root/.codex/sessions/2026/09/09/"
    "rollout-2026-09-09T18-39-06-01a085bf-f993-7ab1-914c-bc6e8b65a3b6.jsonl"
)


def references(text: str, lookup: dict[str, str]) -> set[str]:
    """Return known opaque IDs only; arbitrary matched strings cannot leave this function."""
    candidates = {
        f"{family}_task{number}"
        for family, number in re.findall(r"tasks/([a-z_]+)/task([0-9]+)(?:/|\b)", text)
    }
    candidates.update(re.findall(r"\b([a-z_]+_task[0-9]+)\b", text))
    return {lookup[value] for value in candidates if value in lookup}


def audit(inventory: Path, output: Path) -> dict:
    assert not output.exists()
    manifest = read(inventory / "neutral-manifest.json")
    lookup = {
        r["native_id"]: r["root_id"]
        for r in read(inventory / "private/source-map.json")["rows"]
        if r["root_id"].startswith("A-")
    }
    evidence, accessed = {}, []
    for directory in ("tools", "tests", "configs", "data/manifests", "studies/active", "docs"):
        for path in sorted((LAB / directory).rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".json", ".md"}:
                continue
            if "0219" in path.name:
                continue  # our neutral census must not manufacture historical exposure
            text = path.read_text(errors="replace")
            matches = references(text, lookup)
            accessed.append({"path": str(path.relative_to(LAB)), "sha256": sha(path)})
            for key in matches:
                evidence.setdefault(key, []).append(
                    {
                        "kind": "MAINTAINED_ARTIFACT_REFERENCE",
                        "path": str(path.relative_to(LAB)),
                        "sha256": sha(path),
                    }
                )
    # Freeze exact byte prefix: the active session may append while the audit is running.
    length = SESSION.stat().st_size
    with SESSION.open("rb") as stream:
        raw = stream.read(length)
    boundary = raw.rfind(b"\n") + 1
    raw = raw[:boundary]
    counts = Counter()
    for line_number, line in enumerate(raw.splitlines(), 1):
        event = json.loads(line)
        counts[event["type"]] += 1
        item = event.get("payload", {})
        if event["type"] != "response_item" or item.get("type") not in {
            "function_call",
            "custom_tool_call",
        }:
            continue
        text = item.get("input", item.get("arguments", ""))
        if not isinstance(text, str):
            continue
        for key in references(text, lookup):
            evidence.setdefault(key, []).append(
                {
                    "kind": "TOOL_INPUT_REFERENCE_NOT_AUTOMATIC_SEMANTIC_PROOF",
                    "session_prefix_line": line_number,
                    "call_id_hash": digest(item.get("call_id")),
                }
            )
    rows = []
    for row in manifest["rows"]:
        references_found = evidence.get(row["root_id"], [])
        rows.append(
            {
                "root_id": row["root_id"],
                "known_exposure": row["known_exposure"],
                "prior_reference_count": len(references_found),
                "evidence": references_found,
                "confirmation_exposure_eligible": False,
                "reason": "KNOWN_OLD_EXPOSED"
                if row["old_D"]
                else ("UNKNOWN_EXPOSURE_INCOMPLETE_HISTORICAL_ACCESS_COVERAGE"),
            }
        )
    output.mkdir(parents=True, mode=0o700)
    save(output / "exposure-manifest.json", {"rows": rows})
    save(output / "accessed-artifacts.json", {"rows": accessed})
    result = {
        "status": "F0_EXPOSURE_POSITIVES_RECONSTRUCTED_NEGATIVE_PROOF_UNAVAILABLE",
        "session_path": str(SESSION),
        "session_prefix_bytes": len(raw),
        "session_prefix_sha256": hashlib.sha256(raw).hexdigest(),
        "session_event_counts": dict(counts),
        "historical_tool_input_root_references": len(evidence),
        "history_complete": False,
        "C_exposure_eligible": 0,
        "limitation": (
            "Compaction and missing system-wide access journal prevent certifying never-opened "
            "tasks. No task/QA/gold text emitted; positive references are not all semantic reads."
        ),
        "inventory_sha256": sha(inventory / "neutral-manifest.json"),
        "exposure_manifest_sha256": sha(output / "exposure-manifest.json"),
        "accessed_artifacts_sha256": sha(output / "accessed-artifacts.json"),
        "implementation_sha256": sha(Path(__file__)),
        "new_model_requests": 0,
    }
    save(output / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.inventory, args.output)))
