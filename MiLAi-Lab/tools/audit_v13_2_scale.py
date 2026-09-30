"""Audit the frozen, offline v13.2 Source scale measurements."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

PHASES = (
    "ordinary_first_per_turn",
    "ordinary_cached_reuse",
    "new_source_capture",
    "ordinary_dirty_refresh",
    "source_idempotent_replay",
    "backlinks_validated_lookup",
    "backlinks_delete_and_rebuild",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)

    def percentile(p: float) -> float:
        position = (len(ordered) - 1) * p
        lo, hi = math.floor(position), math.ceil(position)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)

    return {
        "p50": percentile(0.5),
        "p95": percentile(0.95),
        "min": min(values),
        "max": max(values),
    }


def audit(lab: Path) -> dict[str, Any]:
    freeze_path = lab / "data/manifests/v13-2-source-scale-baseline-freeze.json"
    freeze = json.loads(freeze_path.read_text())
    root = lab / "artifacts/v13-2-scale-fd1"
    profiles = []
    for size in freeze["sizes"]:
        run = root / f"n{size}"
        result_path, samples_path = run / "result.json", run / "samples.jsonl"
        result = json.loads(result_path.read_text())
        samples = [json.loads(line) for line in samples_path.read_text().splitlines()]
        assert samples == result["samples"], f"sample/result mismatch: {size}"
        expected_order = [
            (phase, index) for phase in PHASES[:2] for index in range(20)
        ] + [
            (phase, index) for index in range(20) for phase in PHASES[2:4]
        ] + [(phase, index) for phase in PHASES[4:] for index in range(20)]
        assert [(row["phase"], row["index"]) for row in samples] == expected_order, (
            f"incomplete/reordered phases: {size}"
        )
        for key in ("source_commit", "source_map_sha256", "driver_sha256"):
            assert result[key] == freeze[key], f"identity mismatch: {size}/{key}"
        assert result["ledger_sha256_before"] == freeze["ledger_before_sha256"]
        assert result["ledger_sha256_after"] == freeze["ledger_before_sha256"]
        assert result["generation_requests"] == result["embedding_http_requests"] == 0
        assert result["controlled_events_at_start"] == size
        assert result["controlled_events_at_end"] == size + 20
        assert result["semantic_cards"] == 10
        phase_results = []
        for phase in PHASES:
            rows = [row for row in samples if row["phase"] == phase]
            if phase.startswith("ordinary_"):
                assert all(0 <= row["material_tokens"] <= 2048 for row in rows)
            if phase in ("ordinary_cached_reuse", "ordinary_dirty_refresh"):
                assert all(row["retrieval_calls"] == 0 for row in rows)
                assert all(not row["offline_embedding"].get("query_calls", 0) for row in rows)
            if phase == "ordinary_cached_reuse":
                assert all(row["reused"] is True for row in rows)
                assert all(not row["offline_embedding"].get("documents_encoded", 0) for row in rows)
            if phase == "ordinary_dirty_refresh":
                selected = samples[19]["selected_identity_hash"]
                assert all(row["selected_identity_hash"] == selected for row in rows)
            metric_values: dict[str, list[float]] = {
                "wall_ms": [row["wall_ns"] / 1e6 for row in rows],
                "cpu_ms": [row["cpu_ns"] / 1e6 for row in rows],
                "sdk_search_returned_rows": [
                    row["sdk"].get("search_returned_rows", 0) for row in rows
                ],
                "sdk_get_calls": [row["sdk"].get("get_calls", 0) for row in rows],
                "os_inblock_delta": [row["os_inblock_delta"] for row in rows],
                "os_outblock_delta": [row["os_outblock_delta"] for row in rows],
                "peak_process_rss_kib": [row["peak_process_rss_kib"] for row in rows],
            }
            sdk_totals: Counter[str] = Counter()
            embedding_totals: Counter[str] = Counter()
            for row in rows:
                sdk_totals.update(row["sdk"])
                embedding_totals.update(row["offline_embedding"])
            metrics = {key: describe(values) for key, values in metric_values.items()}
            original = next(row for row in result["summaries"] if row["phase"] == phase)
            assert original["samples"] == 20
            for key, expected in original["metrics"].items():
                assert metrics[key] == expected, f"percentile mismatch: {size}/{phase}/{key}"
            phase_results.append({
                "phase": phase, "samples": 20, "metrics": metrics,
                "sdk_call_and_row_totals": dict(sdk_totals),
                "offline_embedding_totals": dict(embedding_totals),
            })
        profiles.append({
            "events_at_start": size, "events_at_end": size + 20,
            "semantic_cards": 10, "samples": len(samples),
            "setup_wall_ms": result["setup_wall_ns"] / 1e6,
            "initial_raw_index_bytes": result["initial_raw_index_bytes"],
            "initial_sqlite_resource_bytes": result["initial_sqlite_resource_bytes"],
            "final_sqlite_resource_bytes": result["final_sqlite_resource_bytes"],
            "phases": phase_results,
            "private_evidence": {
                "result": str(result_path.relative_to(lab)), "result_sha256": sha(result_path),
                "samples": str(samples_path.relative_to(lab)), "samples_sha256": sha(samples_path),
            },
        })
    host_path = root / "host-context.json"
    return {
        "kind": "V13_2_SOURCE_SCALE_BASELINE_ACCEPTANCE",
        "status": "SCOPED_MEASUREMENT_COMPLETE_D5_PARTIAL",
        "freeze": str(freeze_path.relative_to(lab)), "freeze_sha256": sha(freeze_path),
        "source_commit": freeze["source_commit"],
        "source_map_sha256": freeze["source_map_sha256"],
        "driver_sha256": freeze["driver_sha256"],
        "audit_tool_sha256": sha(Path(__file__)),
        "profiles": profiles, "total_samples": sum(row["samples"] for row in profiles),
        "generation_requests": 0, "embedding_http_requests": 0,
        "ledger_sha256_before_and_after_each_run": freeze["ledger_before_sha256"],
        "host_context": json.loads(host_path.read_text()), "host_context_sha256": sha(host_path),
        "qualifications": [
            "Actual public SQLite Store SDK, MemoryService, GroundedMemoryRecipe and frozen Qwen "
            "tokenizer; no private SQL connection or PRAGMA tuning.",
            "Controlled Source assertions and ten semantic cards; no business-object "
            "projection/operation stream or natural long-range semantic task.",
            "Offline deterministic 1024-dimensional one-hot vectors through the provider "
            "interface; no bge-m3 semantic/HTTP throughput claim. Integer vector serialization "
            "is smaller than typical real float-vector payloads.",
            "Twenty descriptive samples per phase; first-per-turn combines one cold initial "
            "index and nineteen incremental-index queries. Same-turn reuse and dirty refresh "
            "preserve the original selected identities.",
            "Logical SDK returned rows include prefix subnamespaces; these counts are not "
            "physical disk reads. Process OS block counters include filesystem effects and "
            "do not prove physical device bytes or causal attribution.",
            "One serial measurement process per size on a shared host, with no machine-idle "
            "guarantee, CPU affinity, frequency lock or cache reset. Root read-only work and "
            "isolated Source engineering checks overlapped the 10000-event run; wall timing "
            "is descriptive.",
            "Backlink reconstruction deletes only six derived indexes via public SDK, "
            "retaining primary events/cards. Source and authoritative continuous model "
            "ledger were checked unchanged by each frozen driver run.",
            "All three planned sizes and all phases retained. No measured method speedup, "
            "semantic advantage, cost saving, independent review or D5 full completion "
            "follows from this scoped baseline.",
        ],
        "product": "NO_GO",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.lab.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "samples": result["total_samples"]}))


if __name__ == "__main__":
    main()
