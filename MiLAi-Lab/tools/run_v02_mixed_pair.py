"""Freeze both finite load arms, run independently, and retain failed stages."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import run_v02_memory_flow as base
from check_v02_e2e_live import service_calibration
from check_v02_service_concurrency import digest

CONFIG = base.LAB / "configs/v02-fixed-arrival-mixed.json"


def comparable_fixture(directory):
    receipts = base.read_json(directory / "mcp-state-receipts.json")
    sources = base.read_json(directory / "source-receipts.json")
    identities = {source["evidence_id"]: f"source-{i}" for i, source in enumerate(sources)}
    return {
        scope: {
            "version": value["version"],
            "payload": {
                **value["payload"],
                "evidence_refs": [identities[r] for r in value["payload"]["evidence_refs"]],
            },
        }
        for scope, value in receipts.items()
    }


def source_input_hashes(directory):
    rows = [
        json.loads(line) for line in (directory / "sdk-physical.jsonl").read_text().splitlines()
    ]
    return [
        r["request_body_sha256"]
        for r in rows
        if r["phase"] == "prepare" and r["path"] == "/v1/evidence"
    ]


def run(root: Path, config_path: Path = CONFIG):
    config = base.read_json(config_path)
    assert config["read_capacity"] + config["import_capacity"] <= 8
    assert config["reads_per_round"] == config["round_seconds"] * config["read_rate"]
    assert config["imports_per_round"] == config["round_seconds"] * config["import_rate"]
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    base.write_json(
        root / "plan.json",
        {
            "config": config,
            "pin": base.pin(config_path),
            "runner_sha256": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [
                    Path(__file__),
                    base.LAB / "tools/check_v02_e2e_live.py",
                    base.LAB / "tools/check_v02_service_concurrency.py",
                    base.LAB / "tools/check_v02_mixed_load.py",
                    base.LAB / "tools/v02_fixed_arrivals.py",
                    base.LAB / "tools/v02_client_gc.py",
                    base.LAB / "tools/observe_v02_mcp_cli_gc.py",
                    base.LAB / "tools/v02_cgroup_observation.py",
                ]
            },
        },
    )
    for arm in config["arms"]:
        base.write_json(root / f"{arm}-config.json", {**config, "mixed_load_arm": arm})
    result = {"status": "RUNNING", "arms": {}, "model_calls": 0, "gateway_slo": "NOT_MEASURED"}
    try:
        for arm in config["arms"]:
            directory = root / (root.name + "-" + arm)
            service_calibration(directory, root / f"{arm}-config.json")
            result["arms"][arm] = base.read_json(directory / "mixed-result.json")
            if result["arms"][arm]["status"] != "FIXED_ARRIVAL_CHECK_COMPLETED_NOT_GATEWAY_SLO":
                result["status"] = "STOPPED_AT_ARM_FAILURE"
                return
        a, b = (root / (root.name + "-" + arm) for arm in config["arms"])
        assert comparable_fixture(a) == comparable_fixture(b)
        assert len(source_input_hashes(a)) == config["source_count"]
        assert source_input_hashes(a) == source_input_hashes(b)
        assert base.read_json(a / "mcp-catalog.json") == base.read_json(b / "mcp-catalog.json")
        result["normalized_active_fixture_digest"] = digest(comparable_fixture(a))
        result["per_round_p95_ratios"] = [
            mixed["read"]["scheduled_to_complete"]["p95_ms"]
            / baseline["read"]["scheduled_to_complete"]["p95_ms"]
            for baseline, mixed in zip(
                result["arms"]["baseline"]["phases"], result["arms"]["mixed"]["phases"], strict=True
            )
        ]
        result["status"] = (
            "CLIENT_MIXED_BOUNDARY_MET_NOT_GATEWAY_SLO"
            if all(
                ratio <= config["mixed_p95_max_ratio"] for ratio in result["per_round_p95_ratios"]
            )
            else "MIXED_DEGRADATION_BOUNDARY_MISSED"
        )
    except BaseException as exc:
        result.update(status="FAILED", error_type=type(exc).__name__)
        raise
    finally:
        base.write_json(root / "pair-result.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    run(args.root.resolve(), args.config.resolve())
