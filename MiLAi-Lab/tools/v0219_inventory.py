"""F0 neutral inventory: hash bytes, whitelist static metadata, never execute task code."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
CORPUS = Path("/cra/memory/mx_memory/benchmarks/v0218-pinned")
PRIOR = Path("/cra/memory/mx_memory/evidence/v0217-admission/20260910")
PINS = {
    "clawmark": "d1b641b3171e584e69a3763c269069f32a13b574",
    "wma-code": "15ea25b723d9c4fb35e8062037aec6a5601e4442",
    "supersede": "677993d3713c265329ac935262d3c08cbfa4cd63",
    "wma-data": "e2148757921fc7e2d66d8ed899823b763227c341",
}
ENVIRONMENTS = {
    "filesystem",
    "email",
    "notion",
    "google_sheets",
    "calendar",
    "browser",
    "terminal",
    "slack",
    "github",
}
EXPOSURE_LEVELS = {
    "HASH_ONLY",
    "NEUTRAL_METADATA_ONLY",
    "TASK_TEXT_OPENED",
    "EVENT_OR_GOLD_OPENED",
    "MODEL_RUN",
    "UNKNOWN_EXPOSURE",
}


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def read(path: Path):
    return json.loads(path.read_text())


def metadata(raw: bytes) -> dict:
    """Only bounded neutral enums/numbers leave the parser; errors never include source text."""
    try:
        module = ast.parse(raw)
        values = [
            node.value
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "METADATA" for t in node.targets)
        ]
        if len(values) != 1 or not isinstance(values[0], ast.Dict):
            return {"parse_status": "METADATA_UNAVAILABLE"}
        result = {"parse_status": "STATIC_AST_ONLY"}
        for key, node in zip(values[0].keys, values[0].values, strict=True):
            if not isinstance(key, ast.Constant):
                continue
            if key.value not in {"environments", "timeout_seconds", "mm_level"}:
                continue
            try:
                value = ast.literal_eval(node)
            except (ValueError, TypeError):
                result["parse_status"] = "NONLITERAL_METADATA_HELD"
                continue
            if key.value == "environments" and isinstance(value, list):
                valid = all(isinstance(x, str) and x in ENVIRONMENTS for x in value)
            elif key.value == "mm_level":
                valid = isinstance(value, str) and value in {"L0", "L1", "L2", "L3", "L4"}
            elif key.value == "timeout_seconds":
                valid = type(value) is int and 0 < value <= 86400
            else:
                valid = False
            if valid:
                result[key.value] = value
            else:
                result["parse_status"] = "UNKNOWN_NEUTRAL_VALUE_HELD"
        return result
    except (SyntaxError, UnicodeError, ValueError, TypeError, RecursionError):
        return {"parse_status": "PARSE_ERROR_HELD_NO_SOURCE_ECHO"}


def safe_path(base: Path, relative: str) -> Path:
    target = base / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts or target.is_symlink():
        raise ValueError("UNSAFE_CORPUS_PATH")
    if not target.resolve().is_relative_to(base.resolve()):
        raise ValueError("CORPUS_ESCAPE")
    return target


def inventory(output: Path) -> dict:
    assert not output.exists()
    old_seal_path = Path(
        "/cra/memory/mx_memory/evidence/v0218/20260911/t5-seal-v1/testbed-manifest.json"
    )
    old_seal = read(old_seal_path)
    old = {row["source"]: row for row in old_seal["roots"]}
    output.mkdir(parents=True, mode=0o700)
    files, accesses, repo_roots, asset_index = [], [], {}, {}
    for lane in ("clawmark", "wma-code", "supersede", "wma-data"):
        catalog_path = CORPUS / (lane + "-files.json")
        catalog = read(catalog_path)
        assert catalog["revision"] == PINS[lane]
        for row in catalog["files"]:
            base = CORPUS / ("WorldMemArena-" + PINS[lane]) if lane == "wma-data" else CORPUS / lane
            path = safe_path(base, row["path"])
            assert path.is_file() and path.stat().st_size == row["bytes"]
            observed = sha(path)
            assert observed == row["sha256"], "CORPUS_CONTENT_MISMATCH"
            relative = str(path.relative_to(CORPUS))
            files.append(
                {"lane": lane, "path": relative, "bytes": row["bytes"], "sha256": observed}
            )
            accesses.append({"path_id": digest(relative), "sha256": observed, "mode": "HASH_ONLY"})
            if lane != "wma-data":
                repo_roots[lane] = CORPUS / lane / Path(row["path"]).parts[0]
            asset_index[relative] = row
    rows, private = [], []
    claw = repo_roots["clawmark"]
    task_paths = sorted(claw.glob("tasks/*/task*/task.py"))
    assert len(task_paths) == 100
    for path in task_paths:
        source = str(path.relative_to(claw))
        family, native_id = path.parent.parent.name, path.parent.name
        root_id = "A-" + digest([PINS["clawmark"], source])[:20]
        assets = [
            f
            for f in files
            if f["lane"] == "clawmark"
            and Path(f["path"]).parent.is_relative_to(path.parent.relative_to(CORPUS))
            and f["path"] != str(path.relative_to(CORPUS))
        ]
        meta = metadata(path.read_bytes())
        accesses.append(
            {
                "path_id": digest(str(path.relative_to(CORPUS))),
                "sha256": sha(path),
                "mode": "WHITELISTED_NEUTRAL_AST_METADATA",
            }
        )
        row = {
            "root_id": root_id,
            "lane": "A",
            "revision": PINS["clawmark"],
            "family": family,
            "source_sha256": sha(path),
            "source_bytes": path.stat().st_size,
            "original_lineage_id": root_id,
            "reserve_group": "clawmark-family:" + family,
            "group_basis": "CONSERVATIVE_FAMILY_ISOLATION_NOT_CLAIM_OF_IDENTICAL_SEMANTICS",
            "semantic_template_relation": "UNKNOWN_PENDING_D_REVIEW",
            "metadata": meta,
            "asset_files": len(assets),
            "asset_extensions": dict(Counter(Path(f["path"]).suffix.lower() for f in assets)),
            "license": "CC-BY-NC-4.0",
            "profile": "ADAPTED_ACTION_WORLD_PENDING_ADMISSION",
            "known_exposure": "EVENT_OR_GOLD_OPENED" if source in old else "UNKNOWN_EXPOSURE",
            "this_inventory_access": "NEUTRAL_METADATA_ONLY",
            "static_eligibility": "HOLD_NEW_ADAPTER_CHECKER_OBSERVABILITY_NOT_VALIDATED",
            "old_D": source in old,
        }
        rows.append(row)
        private.append(
            {"root_id": root_id, "source_path": str(path), "native_id": family + "_" + native_id}
        )
    wma_root = CORPUS / ("WorldMemArena-" + PINS["wma-data"])
    wma_candidates = [
        safe_path(CORPUS, row["path"])
        for row in files
        if row["lane"] == "wma-data"
        and row["path"].endswith(".json")
        and len(Path(row["path"]).relative_to(wma_root.relative_to(CORPUS)).parts) >= 3
    ]
    assert len(wma_candidates) == 461
    for path in sorted(wma_candidates):
        source = str(path.relative_to(wma_root))
        family = "/".join(Path(source).parts[:2])
        root_id = "L-" + digest([PINS["wma-data"], source])[:20]
        rows.append(
            {
                "root_id": root_id,
                "lane": "L",
                "revision": PINS["wma-data"],
                "family": family,
                "source_sha256": sha(path),
                "source_bytes": path.stat().st_size,
                "original_lineage_id": None,
                "lineage_resolution": "CANDIDATE_FILE_NOT_YET_VALIDATED_HISTORY_ROOT",
                "reserve_group": "wma-family:" + family,
                "group_basis": "CONSERVATIVE_DIRECTORY_CLUSTER_NOT_CONFIRMED_HISTORY_INDEPENDENCE",
                "semantic_template_relation": "UNKNOWN",
                "metadata": {"parse_status": "BODY_NOT_PARSED"},
                "license": "CC-BY-NC-4.0",
                "profile": "LIFECYCLE_QA_PENDING_ADMISSION",
                "known_exposure": "EVENT_OR_GOLD_OPENED"
                if source == "lifelong/personal/personal_18.json"
                else "UNKNOWN_EXPOSURE",
                "this_inventory_access": "HASH_ONLY",
                "static_eligibility": "HOLD_HISTORY_GROUPING_MODALITY_CONTEXT_CHECKER_UNKNOWN",
                "old_D": source == "lifelong/personal/personal_18.json",
            }
        )
        private.append({"root_id": root_id, "source_path": str(path), "native_id": path.stem})
    # S contains generator/code, not a pre-generated independent timeline corpus.
    s_files = [f for f in files if f["lane"] == "supersede"]
    lanes = {
        "A": {"candidate_files": 100, "old_D": 12, "static_accepted": 0},
        "L": {
            "candidate_files": sum(r["lane"] == "L" for r in rows),
            "independent_history_roots": None,
            "static_accepted": 0,
        },
        "S": {
            "pinned_code_files": len(s_files),
            "pregenerated_timeline_roots": 0,
            "static_accepted": 0,
            "status": "GENERATOR_REVIEWED_IN_V0217_NEW_TIMELINE_CONTRACT_REQUIRED",
        },
        "MemTrap": {"status": "HOLD_MATCHING_ARTIFACT_NOT_LOCATED"},
    }
    save(output / "private/file-inventory.json", {"files": files})
    save(output / "private/source-map.json", {"rows": private})
    save(output / "access-log.json", {"accesses": accesses, "semantic_task_text_emitted": False})
    save(output / "neutral-manifest.json", {"rows": rows, "lanes": lanes})
    report = {
        "status": "F0_NEUTRAL_INVENTORY_COMPLETE_EXPOSURE_RECONSTRUCTION_REQUIRED",
        "lanes": lanes,
        "verified_files": len(files),
        "verified_bytes": sum(f["bytes"] for f in files),
        "new_model_requests": 0,
        "judge_requests": 0,
        "foreign_code_executed": False,
        "new_task_semantics_opened": 0,
        "C_static_accepted": 0,
        "input_metadata_sha256": {
            str(CORPUS / (lane + "-files.json")): sha(CORPUS / (lane + "-files.json"))
            for lane in PINS
        },
        "old_testbed_manifest_sha256": sha(old_seal_path),
        "implementation_sha256": sha(Path(__file__)),
        "neutral_manifest_sha256": sha(output / "neutral-manifest.json"),
        "access_log_sha256": sha(output / "access-log.json"),
        "private_file_inventory_sha256": sha(output / "private/file-inventory.json"),
        "private_source_map_sha256": sha(output / "private/source-map.json"),
        "exposure_limit": (
            "Known positives retained; absence of prior semantic access not yet proved. "
            "Unknown roots excluded from confirmation eligibility."
        ),
    }
    save(output / "result.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    result = inventory(parser.parse_args().output)
    print(json.dumps(result))
