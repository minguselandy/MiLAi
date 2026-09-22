"""Finite Lab recorder for public owner exports, with pre-outcome persisted snapshots.

This is accounting instrumentation, not a selector or an outcome scorer. Provider
fixture success never establishes task success or model use.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.analysis.opportunity_ledger import (
    SCHEMA_VERSION,
    build_opportunity_ledger,
    freeze_opportunity,
)
from milai_lab.analysis.owner_exports import export_owner_attempts


def _write(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    path.chmod(0o600)


class OpportunityCapture:
    """Serial fixture-only capture; existing output artifacts are never overwritten."""

    def __init__(self, output: Path, method_sha256: str) -> None:
        self.output = output
        self.method_sha256 = method_sha256
        self.attempts: list[dict[str, Any]] = []
        self.origins: dict[str, list[dict[str, Any]]] = {}
        self.current: dict[str, Any] | None = None

    def begin(self, query: str, *, empty_pool_control: bool = False) -> None:
        if self.current is not None:
            raise ValueError("OPPORTUNITY_CAPTURE_ALREADY_ACTIVE")
        index = len(self.attempts) + 1
        self.current = {
            "index": index, "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
            "started": time.monotonic(), "snapshot": None,
        }
        # These controls run before any fixture Evidence/Claim is inserted. The
        # declared empty observation is still checked against actual owner facts.
        if empty_pool_control:
            self._freeze([])

    def _freeze(self, pool: list[dict[str, Any]]) -> None:
        assert self.current is not None
        if self.current["snapshot"] is not None:
            raise ValueError("OPPORTUNITY_CAPTURE_ALREADY_FROZEN")
        snapshot = freeze_opportunity({
            "sequence": self.current["index"] * 10,
            "task_input_sha256": self.current["query_sha256"],
            "available_versions": pool,
            # Descriptive alternatives are exact singleton bundles; they do not
            # claim utility discrimination or change Product's actual selection.
            "meaningful_alternatives": [[version] for version in pool],
            "baseline_attempt_id": None,
        })
        path = self.output / f"opportunity-{self.current['index']:02d}.json"
        _write(path, snapshot)
        self.current.update(snapshot=snapshot, snapshot_path=path,
                            file_sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def before_transport(self, runtime_rows: list[dict[str, Any]]) -> None:
        """Called inside the fixture before any response or intentional failure."""
        if self.current is None:
            raise ValueError("OPPORTUNITY_CAPTURE_NOT_ACTIVE")
        pool: list[dict[str, Any]] = []
        for row in runtime_rows:
            if row["receipt_reused"]:
                if row["context_capsule_ref"] not in self.origins:
                    raise ValueError("OPPORTUNITY_CACHE_ORIGIN_NOT_CAPTURED")
                pool.extend(self.origins[row["context_capsule_ref"]])
            else:
                owner = row["owner_trace"]
                if (not isinstance(owner, dict) or owner["status"] != "COMPLETE"
                        or owner["trace_gaps"] or row["observation_gap"] is not None):
                    raise ValueError("OPPORTUNITY_RUNTIME_EXPORT_INCOMPLETE")
                pool.extend(owner.get("materialized_claim_versions", []))
                pool.extend(owner["materialized_evidence_versions"])
        # Multiple reads of one exact version are one observed candidate.
        unique = {tuple(version.items()): version for version in pool}
        pool = list(unique.values())
        if self.current["snapshot"] is None:
            self._freeze(pool)
        elif self.current["snapshot"]["available_versions"] != pool:
            raise ValueError("OPPORTUNITY_PREDECLARED_EMPTY_POOL_CHANGED")

    def end(self, case: dict[str, Any]) -> None:
        if self.current is None or self.current["snapshot"] is None:
            raise ValueError("OPPORTUNITY_SNAPSHOT_MISSING_BEFORE_OUTCOME")
        current = self.current
        if hashlib.sha256(current["snapshot_path"].read_bytes()).hexdigest() != current[
            "file_sha256"
        ]:
            raise ValueError("OPPORTUNITY_PERSISTED_SNAPSHOT_CHANGED")
        index = current["index"]
        result = {
            "schema_version": "milai-fixture-outcome-v1",
            "host_attempt_trace_id": case["host"]["host_attempt_trace_id"],
            "sequence": index * 10 + 5,
            "opportunity_file_sha256": current["file_sha256"],
            "host_route": case["route"], "error_type": case["error_type"],
            "task_outcome": "UNKNOWN", "usage_kind": "CONTROLLED_FIXTURE",
            "reason": "NO_TASK_SCORER_OR_MODEL",
        }
        result_path = self.output / f"fixture-outcome-{index:02d}.json"
        _write(result_path, result)
        result_ref = "fixture-result:" + hashlib.sha256(result_path.read_bytes()).hexdigest()
        self.attempts.append({
            "host_attempt_trace_id": case["host"]["host_attempt_trace_id"],
            "arm_id": "trace-fixture", "task_id": "task:" + current["query_sha256"],
            "policy_version": "unchanged-product-query-first-v1",
            "opportunity": current["snapshot"],
            "outcome": {"sequence": result["sequence"], "task_outcome": "UNKNOWN",
                        "result_ref": result_ref},
            "explicit_adoption": [], "explicit_rejection": [],
            "revision_opportunity": False, "revision_opportunity_ref": None,
            "costs": {
                "retrieval_calls": sum(not row["receipt_reused"] for row in case["runtime"]),
                "embedding_calls": None, "model_generations": 0,
                "maintenance_input_tokens": 0, "maintenance_output_tokens": 0,
                "latency_ms": (time.monotonic() - current["started"]) * 1000,
                "unknown_reasons": ["EMBEDDING_COUNTER_NOT_EXPORTED"],
            },
        })
        for row in case["runtime"]:
            if not row["receipt_reused"] and row["context_capsule_ref"] is not None:
                owner = row["owner_trace"]
                self.origins[row["context_capsule_ref"]] = copy.deepcopy([
                    *owner.get("selected_claim_versions", []), *owner["selected_versions"],
                ])
        self.current = None

    def finish(
        self, cases: list[dict[str, Any]], *, run_id: str,
        product_lock_digest: str, owner_schema: str,
    ) -> dict[str, Any]:
        if self.current is not None:
            raise ValueError("OPPORTUNITY_CAPTURE_INCOMPLETE")
        facts = export_owner_attempts(
            cases, run_id=run_id, product_lock_digest=product_lock_digest,
            result_refs=[row["outcome"]["result_ref"] for row in self.attempts],
            schema_version=owner_schema,
        )
        observations = {
            "schema_version": SCHEMA_VERSION, "method_version": "real-trace-fixture-ledger-v1",
            "method_sha256": self.method_sha256, "arm_kind": "PRODUCT_TESTKIT",
            "usage_kind": "CONTROLLED_FIXTURE", "attempts": self.attempts, "revisions": [],
        }
        _write(self.output / "ledger-owner-facts.json", facts)
        _write(self.output / "ledger-observations.json", observations)
        ledger = build_opportunity_ledger(facts, observations)
        _write(self.output / "opportunity-ledger.json", ledger)
        return ledger
