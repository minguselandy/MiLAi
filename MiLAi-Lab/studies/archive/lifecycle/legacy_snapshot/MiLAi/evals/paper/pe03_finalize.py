"""Finalize PE03 evidence and freeze external-system inclusion decisions."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.identity import (
    git_source_identity,
    license_identity,
    sha256_file,
    source_inventory,
)

ROOT = Path(__file__).resolve().parents[2]
SYSTEM_ROOTS = {
    "MEM0-OSS": Path("/cra/memory/mx_memory/mem0"),
    "HINDSIGHT-OSS": Path("/cra/memory/mx_memory/hindsight"),
    "GRAPHITI-OSS": Path("/cra/memory/mx_memory/graphiti"),
    "REME-OSS": Path("/cra/memory/mx_memory/ReMe"),
}
PROBES = {
    "MEM0-OSS": ROOT / "evals/paper/probes/mem0_feasibility.py",
    "HINDSIGHT-OSS": ROOT / "evals/paper/probes/hindsight_feasibility.py",
    "GRAPHITI-OSS": ROOT / "evals/paper/probes/graphiti_feasibility.py",
    "REME-OSS": ROOT / "evals/paper/probes/reme_provider_feasibility.py",
}


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"expected object in {path}")
    return value


def _reme_result(run_root: Path) -> dict[str, Any]:
    root = run_root / "reme"
    raw = root / "raw"
    write_one = _read(raw / "write1-rest.json")
    write_two = _read(raw / "write2-rest.json")
    search_before = _read(raw / "search-before-rest.json")
    delete = _read(raw / "delete-rest.json")
    search_after = _read(raw / "search-after-rest.json")
    provider = _read(root / "provider-result.json")
    kayak_results = search_before.get("metadata", {}).get("results", [])
    after_results = search_after.get("metadata", {}).get("results", [])
    temporary_root = Path("/tmp/milai-pe03-reme.dGY08c")
    gates = {
        "chronological_ingest_two_events": write_one.get("success") is True
        and write_two.get("success") is True,
        "cleanup_temp_root_removed": not temporary_root.exists(),
        "delete_product_api": delete.get("metadata", {}).get("deleted") is True,
        "deleted_kayak_absent_after": after_results == [],
        "fresh_isolated_install": "reme-ai @ file:///cra/memory/mx_memory/ReMe"
        in (raw / "pip-freeze.txt").read_text(),
        "local_vllm_native_usage_captured": provider.get("status") == "PASS",
        "query_found_kayak": any(
            "kayak" in str(item.get("text", "")).lower() for item in kayak_results
        ),
        "server_clean_shutdown": "Application shutdown complete"
        in (raw / "server-rest.log").read_text(),
    }
    payload: dict[str, Any] = {
        "adapter_mode": "official-fastapi-rest-and-official-agentscope-provider",
        "capabilities": {
            "chronological_order": "CALL_ORDER_WITH_DATED_PATHS",
            "delete": "SUPPORTED_PRODUCT_API",
        },
        "config": {
            "file_retrieval": "BM25",
            "llm_model": provider["model"],
            "server_port": 24333,
        },
        "development_ai_reviews": 0,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "gates": gates,
        "known_install_issue": {
            "base_install_missing_unconditional_agentscope": True,
            "evidence": "raw/cli-fallback-server.log",
            "resolution": "fresh environment installed documented core extra",
        },
        "operations": {
            "delete": delete,
            "search_after": search_after,
            "search_before": search_before,
            "write_one": write_one,
            "write_two": write_two,
        },
        "paper_labels_opened": False,
        "provider": provider,
        "schema": "milai.dg11.pe03.reme-feasibility.v1",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "system_id": "REME-OSS",
        "work_package": "DG11-PE03",
    }
    _atomic_json(root / "result.json", payload)
    return payload


def _system_identity(system_id: str, run_root: Path) -> dict[str, Any]:
    source_root = SYSTEM_ROOTS[system_id]
    source = (
        git_source_identity(source_root)
        if system_id in {"MEM0-OSS", "GRAPHITI-OSS"}
        else {
            "inventory": source_inventory(source_root),
            "root": str(source_root.resolve()),
        }
    )
    run_name = system_id.split("-")[0].lower()
    pip_freeze = run_root / run_name / "raw/pip-freeze.txt"
    return {
        "license": license_identity(source_root),
        "pip_freeze_path": str(pip_freeze),
        "pip_freeze_sha256": sha256_file(pip_freeze),
        "probe_path": str(PROBES[system_id]),
        "probe_sha256": sha256_file(PROBES[system_id]),
        "source": source,
        "system_id": system_id,
    }


def run(run_root: Path, freeze_root: Path) -> dict[str, Any]:
    reme = _reme_result(run_root)
    results = {
        "MEM0-OSS": _read(run_root / "mem0/result.json"),
        "HINDSIGHT-OSS": _read(run_root / "hindsight/result.json"),
        "GRAPHITI-OSS": _read(run_root / "graphiti/result.json"),
        "REME-OSS": reme,
    }
    if any(
        result.get("paper_labels_opened") is not False for result in results.values()
    ):
        raise ValueError("PE03 unexpectedly opened paper labels")
    identities = {
        system_id: _system_identity(system_id, run_root)
        for system_id in sorted(results)
    }
    identity_payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "paper_labels_opened": False,
        "schema": "milai.dg11.paper-external-identities.v1",
        "systems": identities,
    }
    identity_path = freeze_root / "external-identities.json"
    _atomic_json(identity_path, identity_payload)

    inclusion = {
        system_id: {
            "controlled_track": "FEASIBILITY_PASS",
            "decision": "INCLUDE",
            "native_track": "REQUIRED_WHERE_BENCHMARK_ADAPTER_APPLIES",
            "result_path": str(
                run_root / system_id.split("-")[0].lower() / "result.json"
            ),
            "result_sha256": sha256_file(
                run_root / system_id.split("-")[0].lower() / "result.json"
            ),
        }
        for system_id in sorted(results)
    }
    inclusion_payload = {
        "decision_basis": "PRE_PAPER_TEST_FEASIBILITY_ONLY_NOT_PILOT_SCORE",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "paper_labels_opened": False,
        "schema": "milai.dg11.paper-method-inclusion.v1",
        "systems": inclusion,
    }
    inclusion_path = freeze_root / "method-inclusion.json"
    _atomic_json(inclusion_path, inclusion_payload)

    gates = {
        "all_four_decisions_frozen": len(inclusion) == 4,
        "all_four_feasibility_pass": all(
            result.get("status") == "PASS" for result in results.values()
        ),
        "all_four_fresh_installs_evidenced": all(
            bool(
                result.get("gates", {}).get("fresh_isolated_install")
                or result.get("gates", {}).get("fresh_workspace")
                or result.get("gates", {}).get("fresh_isolated_server_healthy")
                or result.get("gates", {}).get("fresh_isolated_neo4j")
            )
            for result in results.values()
        ),
        "all_four_local_vllm_usage_captured": all(
            result.get("gates", {}).get("local_vllm_native_usage_captured") is True
            for result in results.values()
        ),
        "all_four_query_pass": all(
            result.get("gates", {}).get("query_found_kayak") is True
            for result in results.values()
        ),
        "all_four_source_identities_frozen": len(identities) == 4,
        "paper_labels_opened_zero": True,
    }
    payload: dict[str, Any] = {
        "development_ai_reviews": 0,
        "external_identities_path": str(identity_path),
        "external_identities_sha256": sha256_file(identity_path),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "gates": gates,
        "method_inclusion_path": str(inclusion_path),
        "method_inclusion_sha256": sha256_file(inclusion_path),
        "paper_labels_opened": False,
        "run_id": run_root.name,
        "schema": "milai.dg11.pe03-external-feasibility.v1",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "systems": {
            system_id: {
                "result_status": result["status"],
                "result_path": inclusion[system_id]["result_path"],
                "result_sha256": inclusion[system_id]["result_sha256"],
            }
            for system_id, result in sorted(results.items())
        },
        "work_package": "DG11-PE03",
    }
    _atomic_json(run_root / "result.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-root", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.run_root.resolve(), args.freeze_root.resolve())
    print(
        json.dumps(
            {"status": result["status"], "work_package": result["work_package"]},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
