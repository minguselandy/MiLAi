"""Export immutable complete-case response views while the Reader continues.

No model calls or budget writes. Measured export work is reconciled into the
original ledger by the final receipt-review tool after its HTTP owner closes.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def response_id(key: str) -> str:
    return "response-" + key.removeprefix("musique/shared/").removesuffix("/answer").zfill(6)


def export_closed_cases(root: Path, output: Path) -> dict[str, Any]:
    started, cpu = time.perf_counter(), time.process_time()
    protocol = read_json(root / "protocol.json")
    cases = [json.loads(x) for x in Path(protocol["cases"]).read_text().splitlines()]
    output.mkdir(parents=True, exist_ok=True)
    catalog = []
    for index, case in enumerate(cases):
        paths = [
            root / "reader/predictions" / arm / f"{case['case_id']}.json"
            for arm in protocol["arms"]
        ]
        if not all(p.exists() for p in paths):
            break
        results = {r["reader_call_key"]: r for r in map(read_json, paths)}
        keys = sorted(results)
        random.Random(20261019 + index).shuffle(keys)  # noqa: S311 -- fixed blinded-view order
        lines = [
            f"CASE {case['case_id']} | {case['question']}",
            "Method names hidden. ONLY delivered documents may support each answer.",
        ]
        seen: dict[tuple[str, str], str] = {}
        for key in keys:
            rid, result = response_id(key), results[key]
            folder = root / "reader/http" / key
            request, receipt = (
                read_json(folder / "request.json"),
                read_json(folder / "response.json"),
            )
            visible = json.loads(request["messages"][1]["content"])
            lines.append(
                f"\n{rid} | selected IDs: " + json.dumps([p["id"] for p in visible["documents"]])
            )
            for doc in visible["documents"]:
                identity = doc["title"], doc["text"]
                if identity in seen:
                    lines.append(f"[{doc['id']}] {doc['title']}: exact text as {seen[identity]}.")
                else:
                    seen[identity] = f"{rid}/{doc['id']}"
                    lines.append(f"[{doc['id']}] {doc['title']}\n{doc['text']}")
            lines.append("FIRST ANSWER: " + json.dumps(result["answer"], ensure_ascii=False))
            lines.append("FAILURE: " + json.dumps(result["failure"], ensure_ascii=False))
            if result["answer"] is None:
                lines.append(
                    "RAW FINAL CONTENT: " + str(receipt["choices"][0]["message"].get("content"))
                )
        text = "\n".join(lines) + "\n"
        path = output / f"{index:02d}-{case['case_id']}.txt"
        if path.exists():
            if path.read_text() != text:
                raise ValueError("A previously exported complete-case view changed")
        else:
            path.write_text(text)
        catalog.append(
            {
                "case": case["case_id"],
                "view": str(path),
                "response_ids": [response_id(k) for k in keys],
                "bytes": path.stat().st_size,
            }
        )
    report = {
        "status": "COMPLETE_CASE_VIEWS_EXPORTED_NOT_SEMANTICALLY_GRADED",
        "completed_cases": len(catalog),
        "planned_cases": len(cases),
        "catalog": catalog,
        "reviewer_is_independent": False,
        "model_calls": 0,
        "compute": {
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "exports": 1,
        },
    }
    write_json(output / "catalog.json", report)
    with (output / "export-compute.jsonl").open("a") as stream:
        stream.write(json.dumps(report["compute"]) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = export_closed_cases(args.root, args.output)
    print(json.dumps({k: result[k] for k in ("status", "completed_cases", "planned_cases")}))


if __name__ == "__main__":
    main()
