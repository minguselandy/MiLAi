"""Metadata-only inventory and prospective one-sample WMA pool; never imports task code."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path


def write_new(path: Path, value: dict) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)


def inventory(root: Path) -> dict:
    pool = json.loads((root / "clawmark/frozen-pool.json").read_text())
    tree = json.loads((root / "clawmark/tree.json").read_text())["tree"]
    rows = []
    for index, relative in enumerate(pool["selected_for_static_screen"]):
        path = root / "clawmark" / relative
        row = {"order": index + 1, "path": relative,
               "exposure": "EXPOSED_FOR_ADMISSION", "native_task_eligible": False}
        if not path.exists():
            row["status"] = "FETCH_FAILED_NOT_INSPECTED"
        else:
            raw = path.read_bytes()
            module = ast.parse(raw)
            metadata = next(node.value for node in module.body if isinstance(node, ast.Assign)
                            and any(isinstance(t, ast.Name) and t.id == "METADATA"
                                    for t in node.targets))
            # Extract only safe public fields, never credentials or task answer text.
            safe = {"id", "category", "environments", "timeout_seconds", "mm_level"}
            row["metadata"] = {key.value: ast.literal_eval(value)
                               for key, value in zip(metadata.keys, metadata.values, strict=True)
                               if isinstance(key, ast.Constant) and key.value in safe}
            row["sha256"] = hashlib.sha256(raw).hexdigest()
            row["status"] = "STATIC_METADATA_INSPECTED"
            row["fixture_selected"] = index < 2
            prefix = str(Path(relative).parent) + "/"
            assets = [item for item in tree if item["type"] == "blob"
                      and item["path"].startswith(prefix) and item["path"] != relative]
            row["asset_files_declared_in_tree"] = len(assets)
            row["asset_extensions"] = sorted({Path(item["path"]).suffix for item in assets})
            row["assets_downloaded"] = False
        rows.append(row)
    report = {"candidate_modules_in_tree": len(pool["universe"]),
              "screen_slots": len(rows), "downloaded_and_metadata_inspected": sum(
                  row["status"] == "STATIC_METADATA_INSPECTED" for row in rows),
              "fixture_families": 2, "native_task_eligible": 0, "rows": rows}
    write_new(root / "clawmark/static-inventory.json", report)
    entries = json.loads((root / "wma/hf-personal-tree.json").read_text())
    ordered = sorted((item for item in entries if item["type"] == "file"
                      and item["path"].endswith(".json") and item["size"] <= 4_000_000),
                     key=lambda item: hashlib.sha256(("217:" + item["path"]).encode()).hexdigest())
    sample_pool = {"revision": "e2148757921fc7e2d66d8ed899823b763227c341",
                   "universe_scope": "personal directory only, not all WMA",
                   "order": "sha256('217:' + path) ascending", "universe": ordered,
                   "stop": "first readable sample, at most one sample download attempt",
                   "eligibility": "JSON in listed personal directory, size <= 4000000",
                   "selected": ordered[0]["path"], "model_requests": 0,
                   "profile": "STRUCTURAL_ADMISSION_ONLY_NOT_TEXT_EQUIVALENCE"}
    write_new(root / "wma/frozen-personal-pool.json", sample_pool)
    return {"clawmark": report, "wma_selected": sample_pool["selected"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    print(json.dumps(inventory(parser.parse_args().root), indent=2))
