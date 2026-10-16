"""Extract complete paired states and literal source bindings for author review.

Reads original SQLite banks in read-only mode. Saved ingestion outputs and
retrieved revisions are compared with post-arrival histories. A rejected/no-op
ingestion can return no new memories while the previous state remains present.
No semantic judgments are automated.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json


def inspect(run: Path, arm: str, owner: str) -> dict:
    root = run / arm / "MiLAi-memory-only"
    namespace = f"edit.MiLAi-memory-only.{'B1' if arm == 'plain' else 'M'}.{owner}"
    path = root / "banks" / owner / "memory.sqlite"
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        records = {
            key: json.loads(value)["_v13_1"]
            for key, value in db.execute("SELECT key,value FROM store WHERE prefix=?", (namespace,))
        }
        sources = {
            key: json.loads(value)
            for key, value in db.execute(
                "SELECT key,value FROM store WHERE prefix=?", (namespace + ".v13_1_sources",)
            )
        }
    aliases = {key: f"S{source['session'].rsplit(':', 1)[1]}" for key, source in sources.items()}
    unit_aliases = {}
    for record in records.values():
        for version in record["history"]:
            for unit in version["edit_state"]["units"]:
                unit_aliases.setdefault(unit["unit_id"], f"U{len(unit_aliases)}")

    def expand(value):
        if isinstance(value, list):
            return [expand(v) for v in value]
        if not isinstance(value, dict):
            return unit_aliases.get(value, value) if isinstance(value, str) else value
        result = {
            key: expand(item)
            for key, item in value.items()
            if key not in {"evidence_id", "observed_at"}
        }
        if "source_ref" in value:
            source = sources[value["source_ref"]]
            assert value["source_revision"] == source["source_revision"]
            if "role" in value:
                assert value["role"] == source["role"]
            result["source_ref"] = aliases[value["source_ref"]]
            if "start" in value:
                assert 0 <= value["start"] <= value["end"] <= len(source["content"])
                result["literal_support"] = source["content"][value["start"] : value["end"]]
        return result

    arrivals = []
    for session in range(4):
        states = []
        for key, record in records.items():
            history = [
                v for v in record["history"] if int(v["session"].rsplit(":", 1)[1]) <= session
            ]
            if history:
                states.append((key, max(history, key=lambda v: v["revision"])))
        rendered = sorted(v["content"] for _, v in states if not v["retracted"])
        ingestion = read_json(root / "native/halumem" / owner / str(session) / "ingestion.json")
        extracted = ingestion["native_return"]["extracted_memories"]
        assert all(text in rendered for text in extracted), (arm, owner, session)
        retrieved = read_json(
            root / "native/halumem" / owner / str(session) / "qa/0/retrieval.json"
        )["materials"]
        current = dict(states)
        semantic = [m for m in retrieved if m["kind"] == "semantic_view"]
        for material in semantic:
            version = current[material["record_id"]]
            assert material["revision"] == version["revision"]
            units = {u["unit_id"]: u for u in version["edit_state"]["units"]}
            for unit in material["applicability"]["units"]:
                assert unit["text"] == units[unit["unit_id"]]["text"]
        arrivals.append(
            {
                "session": session,
                "ingestion_output_matches_full_state": rendered == sorted(extracted),
                "ingestion_outputs_present_in_state": True,
                "retrieved_semantic_revisions_match": len(semantic),
                "retrieved_applicability": [
                    {
                        "record_id": material["record_id"],
                        "revision": material["revision"],
                        "units": [
                            {
                                "unit_id": unit_aliases[unit["unit_id"]],
                                "text": unit["text"],
                                "temporal": unit["temporal"],
                                "declared_scope": unit["declared_scope"],
                                "scope_status": unit["scope_status"],
                                "quantity_scope": unit["quantity_scope"],
                            }
                            for unit in material["applicability"]["units"]
                        ],
                    }
                    for material in semantic
                ],
                "records": [
                    {
                        "record_id": key,
                        "revision": v["revision"],
                        "retracted": v["retracted"],
                        "scope": v["scope"],
                        "basis": v["basis"],
                        "edit_state": expand(v["edit_state"]),
                        "source_bindings": expand(v["source_bindings"]),
                    }
                    for key, v in states
                ],
                "receipts": [
                    {
                        key: r[key]
                        for key in ("ok", "status", "reason", "id", "revision")
                        if key in r
                    }
                    for r in ingestion["native_return"]["receipts"]
                ],
            }
        )
    return {
        "arm": arm,
        "owner": owner,
        "source_bank": str(path),
        "sources": [
            {
                "label": aliases[key],
                **{
                    k: source[k]
                    for k in ("event_id", "role", "content", "source_revision", "occurred_at")
                },
            }
            for key, source in sources.items()
        ],
        "unit_aliases": unit_aliases,
        "arrivals": arrivals,
        "coverage": "All actual history units, relations, groups, assertion metadata and "
        "literal evidence ranges. Source observed_at and mechanical evidence IDs "
        "are omitted from this review projection; originals remain in the bank. "
        "Known identity/range validity does not establish semantic support.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    owners = read_json(args.run / "plain.json")["entrypoints"]["benchmark"]["halumem"]["users"]
    plain_sources = {}
    for arm in ("plain", "delta"):
        for owner in owners:
            packet = inspect(args.run, arm, owner)
            observed = sorted(
                (s["label"], s["role"], s["occurred_at"], s["content"]) for s in packet["sources"]
            )
            if arm == "plain":
                plain_sources[owner] = observed
            else:
                assert observed == plain_sources[owner], owner
            write_json(args.output / arm / f"{owner}.json", packet)
    print(
        json.dumps(
            {
                "arms": 2,
                "source_chains": len(owners),
                "verified_post_arrival_states": 8 * len(owners),
                "model_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
