"""Collect frozen same-source derived-index measurements without runtime imports."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)

    def percentile(p: float) -> float:
        position = (len(ordered) - 1) * p
        lo, hi = math.floor(position), math.ceil(position)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)

    return {"p50": percentile(0.5), "p95": percentile(0.95),
            "min": min(values), "max": max(values)}


def audit(lab: Path, *, allow_partial: bool = False) -> dict[str, Any]:
    freeze_path = lab / "data/manifests/v13-2-derived-index-scale-freeze.json"
    freeze = json.loads(freeze_path.read_text())
    root = Path(freeze["run_root"])
    execution_lab = Path(freeze["execution_worktree"]) / "MiLAi-Lab"
    assert all(sha(execution_lab / name) == digest
               for name, digest in freeze["runtime_sources"].items())
    driver_root = Path(freeze["parent_driver_path"]).parent
    assert all(sha(driver_root / name) == digest
               for name, digest in freeze["drivers_sha256"].items())
    assert sha(Path(freeze["tokenizer_capacity_only_config"])) == freeze["config_sha256"]
    assert sha(Path(freeze["ledger_path"])) == freeze["ledger_sha256_before"]
    assert sha(root / "ledger-before.json") == freeze["ledger_sha256_before"]
    process_bytes = (root / "process-results.json").read_bytes()
    process_hash = hashlib.sha256(process_bytes).hexdigest()
    snapshot = root / ("process-results-audit-" + process_hash + ".json")
    if not snapshot.exists():
        snapshot.write_bytes(process_bytes)
    assert sha(snapshot) == process_hash
    processes = json.loads(process_bytes)["results"]
    attempted = {row["name"]: row for row in processes}
    for row in processes:
        assert (
            row["source_sha256_before"] == row["source_sha256_after"] == freeze["runtime_sources"]
        )
        assert row["source_unchanged"]
        assert row["ledger_sha256_after"] == freeze["ledger_sha256_before"]
        assert sha(Path(row["stdout_path"])) == row["stdout_sha256"]
        assert sha(Path(row["stderr_path"])) == row["stderr_sha256"]
    profiles = []
    pending = []
    phases = freeze["phases"]
    for profile in freeze["profiles"]:
        folder = root / profile["id"]
        result_path, samples_path = folder / "result.json", folder / "samples.jsonl"
        terminal = attempted.get(profile["id"])
        if not result_path.exists() or terminal is None:
            status = ("FAILED" if terminal and terminal["returncode"] else
                      "TERMINAL_MISSING_RESULT" if terminal else
                      "RESULT_AWAITING_TERMINAL_RECEIPT" if result_path.exists() else
                      "INCOMPLETE_ATTEMPT" if folder.exists() else "NOT_STARTED")
            pending.append({**profile, "status": status,
                            "observed_samples": len(samples_path.read_text().splitlines())
                            if samples_path.exists() else 0})
            continue
        assert attempted[profile["id"]]["returncode"] == 0
        result = json.loads(result_path.read_text())
        samples = [json.loads(line) for line in samples_path.read_text().splitlines()]
        assert samples == result["samples"]
        expected = [(phase, i) for phase in phases[:2] for i in range(20)]
        expected += [(phase, i) for i in range(20) for phase in phases[2:4]]
        expected += [(phase, i) for phase in phases[4:] for i in range(20)]
        assert [(r["phase"], r["index"]) for r in samples] == expected
        assert result["storage"] == profile["storage"]
        assert result["source_map_sha256"] == freeze["runtime_source_map_sha256"]
        assert result["driver_sha256"] == freeze["drivers_sha256"]["measure_derived_index.py"]
        assert result["config_sha256"] == freeze["config_sha256"]
        assert result["source_commit"] == freeze["implementation_commit"]
        assert result["source_test_commit"] == freeze["test_commit"]
        assert result["ledger_sha256_before"] == freeze["ledger_sha256_before"]
        assert result["ledger_sha256_after"] == freeze["ledger_sha256_before"]
        assert result["generation_requests"] == result["embedding_http_requests"] == 0
        assert result["controlled_events_at_start"] == profile["size"]
        assert result["controlled_events_at_end"] == profile["size"] + 20
        assert result["semantic_cards"] == 10
        seed = root / ("seed-n" + str(profile["size"]))
        assert result["seed_sqlite_sha256"] == sha(seed / "memory.sqlite")
        assert result["seed_metadata_sha256"] == sha(seed / "seed.json")
        metrics = []
        for phase in phases:
            rows = [r for r in samples if r["phase"] == phase]
            assert len(rows) == 20
            if phase.startswith("ordinary_"):
                assert all(0 <= r["material_tokens"] <= 2048 for r in rows)
            if phase in {"ordinary_cached_reuse", "ordinary_dirty_refresh"}:
                assert all(r["retrieval_calls"] == 0 for r in rows)
                assert all(not r["offline_embedding"].get("query_calls", 0) for r in rows)
            if phase == "ordinary_cached_reuse":
                assert all(r["reused"] for r in rows)
                assert all(not r["offline_embedding"].get("documents_encoded", 0) for r in rows)
            if phase == "ordinary_dirty_refresh":
                assert all(r["selected_identity_hash"] == samples[19]["selected_identity_hash"]
                           for r in rows)
            series: dict[str, list[float]] = {
                "wall_ms": [r["wall_ns"] / 1e6 for r in rows],
                "cpu_ms": [r["cpu_ns"] / 1e6 for r in rows],
                "sdk_search_returned_rows": [r["sdk"].get("search_returned_rows", 0) for r in rows],
                "sdk_get_calls": [r["sdk"].get("get_calls", 0) for r in rows],
                "os_inblock_delta": [r["os_inblock_delta"] for r in rows],
                "os_outblock_delta": [r["os_outblock_delta"] for r in rows],
                "peak_process_rss_kib": [r["peak_process_rss_kib"] for r in rows],
            }
            calculated = {name: describe(values) for name, values in series.items()}
            original = next(r for r in result["summaries"] if r["phase"] == phase)
            assert all(calculated[name] == value for name, value in original["metrics"].items())
            sdk: Counter[str] = Counter()
            vectors: Counter[str] = Counter()
            for row in rows:
                sdk.update(row["sdk"])
                vectors.update(row["offline_embedding"])
            metrics.append({"phase": phase, "samples": 20, "metrics": calculated,
                            "sdk_totals": dict(sdk), "offline_embedding_totals": dict(vectors)})
        profiles.append({**profile, "status": "COMPLETE", "phases": metrics,
                         "seed_sqlite_sha256": result["seed_sqlite_sha256"],
                         "seed_metadata_sha256": result["seed_metadata_sha256"],
                         "ordinary_first_selected_hashes":
                         [r["selected_identity_hash"] for r in samples[:20]],
                         "initial_raw_index_bytes": result["initial_raw_index_bytes"],
                         "initial_sqlite_resource_bytes": result["initial_sqlite_resource_bytes"],
                         "final_sqlite_resource_bytes": result["final_sqlite_resource_bytes"],
                         "result_sha256": sha(result_path), "samples_sha256": sha(samples_path)})
    pairs = []
    for size in freeze["sizes"]:
        matching = [p for p in profiles if p["size"] == size]
        if len(matching) == 2:
            a, b = matching
            assert a["seed_sqlite_sha256"] == b["seed_sqlite_sha256"]
            assert a["ordinary_first_selected_hashes"] == b["ordinary_first_selected_hashes"]
            pairs.append({"size": size, "exact_seed_bytes_match": True,
                          "all_twenty_first_query_selected_identities_match": True})
    if not allow_partial:
        assert not pending, "Full planned six-profile measurements are incomplete"
        assert (root / "ledger-after.json").exists()
        assert sha(root / "ledger-after.json") == freeze["ledger_sha256_before"]
    return {"kind": "V13_2_SAME_SOURCE_DERIVED_INDEX_SCALE_AUDIT",
            "status": "PARTIAL_RUNNING" if pending else "SCOPED_COMPLETE_D5_PARTIAL",
            "freeze_sha256": sha(freeze_path), "audit_tool_sha256": sha(Path(__file__)),
            "source_map_sha256": freeze["runtime_source_map_sha256"],
            "planned_profiles": len(freeze["profiles"]), "completed_profiles": len(profiles),
            "planned_samples": freeze["planned_samples"],
            "complete_profile_samples": sum(p["samples"] for p in profiles),
            "profiles": profiles, "pending": pending, "pair_identity_checks": pairs,
            "process_results_sha256": process_hash,
            "process_results_snapshot_path": str(snapshot),
            "terminal_command_receipts_verified": len(processes),
            "new_generation_requests": 0, "new_embedding_http_requests": 0,
            "qualifications": freeze["qualifications"], "product": "NO_GO"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    result = audit(args.lab.resolve(), allow_partial=args.allow_partial)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in
                      ["status", "completed_profiles", "complete_profile_samples"]}))


if __name__ == "__main__":
    main()
