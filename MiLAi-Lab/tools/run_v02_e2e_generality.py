"""Closed local G/A/B coordinator using the controlled Host and public snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import run_v02_local_vllm as host
import run_v02_memory_flow as base
from v02_file_sources import file_material
from v02_g_source_fork import complete_g_sources
from v02_local_provider import LocalGateError, accounting, read_events, write_json
from v02_memory_variants import compare_variant
from v02_post_g_sources import prepare_post_g_sources, source_delta
from v02_public_snapshot import prepare_snapshot
from v02_variant_plan import VARIANT_ARMS, branches

CONFIG = base.LAB / "configs/v02-local-sim02-candidate.json"


def evaluation_contract(config: dict, source_bytes: bytes, contract_bytes: bytes) -> dict:
    """Verify frozen source/rubric identities, not the rubric's semantic conclusions."""
    if config.get("task_evaluation") != "SOURCE_ASSERTIONS_FROZEN":
        raise LocalGateError("TASK_EVALUATION_CONTRACT_NOT_READY")
    reference = config.get("evaluation_contract", {})
    expected = reference.get("sha256") if isinstance(reference, dict) else None
    if hashlib.sha256(contract_bytes).hexdigest() != expected:
        raise LocalGateError("EVALUATION_CONTRACT_IDENTITY_CHANGED")
    if hashlib.sha256(source_bytes).hexdigest() != config.get("source_sha256"):
        raise LocalGateError("SOURCE_IDENTITY_CHANGED")
    try:
        source = json.loads(source_bytes)
        contract = json.loads(contract_bytes)
        is_files = source.get("schema_version") == "v02-file-source-only-v1"
        if is_files:
            file_material(source, "evaluation-preflight")
            continuation_task(contract)
        if (
            contract["schema_version"] != (
                "v02-file-evaluation-v1" if is_files else "v02-source-evaluation-v1")
            or contract["source_sha256"] != config["source_sha256"]
            or (not is_files and (contract["question"] != source["question"]
                                 or contract["question_date"] != source["question_date"]))
            or not contract["first_use_boundary"].strip()
            or not contract["necessary_conditions"]
            or not contract["source_assertions"]
        ):
            raise ValueError("rubric/source mismatch")
        for assertion in contract["source_assertions"]:
            if not assertion["statement"].strip() or not assertion["spans"]:
                raise ValueError("source assertion lacks basis")
            for ref in assertion["spans"]:
                if is_files:
                    matched = [f for f in source["files"] if f["path"] == ref["path"]
                               and f["source_uri"] == ref["source_uri"]]
                    if len(matched) != 1:
                        raise ValueError("source file identity mismatch")
                    content = matched[0]["content"]
                else:
                    sessions = [s for s in source["sessions"]
                                if s["session_ordinal"] == ref["session_ordinal"]]
                    if len(sessions) != 1:
                        raise ValueError("source session is not uniquely located")
                    turns = [t for t in sessions[0]["turns"]
                             if t["turn_ordinal"] == ref["turn_ordinal"]]
                    if len(turns) != 1 or turns[0]["role"] != ref["role"]:
                        raise ValueError("source turn/role mismatch")
                    content = turns[0]["content"]
                start, end = ref["start"], ref["end"]
                if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(
                    content
                ):
                    raise ValueError("source span is invalid")
                if hashlib.sha256(content[start:end].encode()).hexdigest() != ref["sha256"]:
                    raise ValueError("source span identity changed")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise LocalGateError("EVALUATION_SOURCE_ASSERTIONS_INVALID") from exc
    return contract


def continuation_task(source: dict) -> str:
    question, date = source.get("question"), source.get("question_date")
    if not isinstance(question, str) or not question.strip() or not isinstance(date, str) \
            or not date.strip():
        raise LocalGateError("CONTINUATION_QUESTION_AND_DATE_REQUIRED")
    return question + "\n\nQuestion date: " + date


def phase_contract(config: dict, initial: bytes, rubric: bytes,
                   continuation: bytes | None = None) -> dict:
    """Evaluate against continuation sources without ever staging them into G."""
    if "post_g_source" not in config:
        if continuation is not None:
            raise LocalGateError("UNDECLARED_CONTINUATION_SOURCE")
        return evaluation_contract(config, initial, rubric)
    reference = config["post_g_source"]
    if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
            or not isinstance(reference["path"], str) or not reference["path"]
            or continuation is None):
        raise LocalGateError("POST_G_SOURCE_NOT_DECLARED")
    if hashlib.sha256(initial).hexdigest() != config.get("source_sha256"):
        raise LocalGateError("SOURCE_IDENTITY_CHANGED")
    source_delta(json.loads(initial), json.loads(continuation))
    return evaluation_contract({**config, "source_sha256": reference["sha256"]},
                               continuation, rubric)


def prepare(root: Path, config_path: Path, *, compose_override: Path | None = None) -> None:
    config = base.read_json(config_path)
    branches(config)
    if config.get("source_mode") != "PUBLIC_SOURCE_SNAPSHOT":
        raise LocalGateError("PUBLIC_SOURCE_MODE_REQUIRED")
    source_path = base.LAB / config["source_path"]
    source_bytes = source_path.read_bytes()
    reference = config.get("evaluation_contract")
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
        raise LocalGateError("TASK_EVALUATION_CONTRACT_NOT_READY")
    contract_bytes = (base.LAB / reference["path"]).read_bytes()
    continuation_bytes = ((base.LAB / config["post_g_source"]["path"]).read_bytes()
                          if "post_g_source" in config else None)
    contract = phase_contract(config, source_bytes, contract_bytes, continuation_bytes)
    source = json.loads(source_bytes)
    continuation_task(contract if source.get("schema_version") == "v02-file-source-only-v1"
                      else source)
    pin = base.pin(config_path)
    compose = compose_override or base.LAB / "tools/containers/v02-local-bridge.compose.yaml"
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    write_json(root / "config.json", config)
    # Both files remain outside every Host workspace and are rechecked before run.
    (root / "input-source.json").write_bytes(source_bytes)
    if continuation_bytes is not None:
        (root / "continuation-source.json").write_bytes(continuation_bytes)
    (root / "evaluation-contract.json").write_bytes(contract_bytes)
    write_json(
        root / "preflight.json",
        {"pin": pin, "source_sha256": config["source_sha256"],
         "evaluation_contract_sha256": reference["sha256"], "new_generation_requests": 0,
         "cpu_affinity": sorted(os.sched_getaffinity(0)),
         "compose_override": str(compose),
         "compose_override_sha256": hashlib.sha256(compose.read_bytes()).hexdigest()},
    )
    base.prepare(
        root / (root.name + "-product"),
        config_path=config_path,
        compose_override=compose,
        runtime_overrides={
            "MILAI_DATA_MODE": config["data_mode"],
            "MILAI_EMBEDDING_PROVIDER": "deterministic_hash",
            "MILAI_EMBEDDING_MODEL_ID": "deterministic-hash-v1",
            "MILAI_EMBEDDING_SOURCE_DIMENSIONS": "16",
            "MILAI_EMBEDDING_PROJECTION_DIMENSIONS": "16",
            "MILAI_RETRIEVAL_RERANKER_PROVIDER": "none",
        },
    )
    prepare_snapshot(root, source)


def run(root: Path) -> dict:
    config = base.read_json(root / "config.json")
    host.require_new_authorization(config)
    if config.get("task_evaluation") != "SOURCE_ASSERTIONS_FROZEN":
        raise LocalGateError("TASK_EVALUATION_CONTRACT_NOT_READY")
    phase_contract(config, (root / "input-source.json").read_bytes(),
                   (root / "evaluation-contract.json").read_bytes(),
                   (root / "continuation-source.json").read_bytes()
                   if "post_g_source" in config else None)
    base.pin(root / "config.json")
    return run_chain(root)


def run_chain(root: Path, launch=host.launch) -> dict:
    """The same orchestration is exercised with scripted mock workers before model authorization."""
    config = base.read_json(root / "config.json")
    report = {
        "status": "RUNNING",
        "arm_kind": "SIMULATION",
        "sessions": {},
        "semantic_task_effect": "NOT_EVALUATED",
        "formal_D4_D5": "NOT_ENTERED",
    }
    try:
        source = base.read_json(root / "input-source.json")
        task = continuation_task(base.read_json(root / "evaluation-contract.json")
                                 if source.get("schema_version") == "v02-file-source-only-v1"
                                 else source)
        report["continuation_task_sha256"] = hashlib.sha256(task.encode()).hexdigest()
        generator = launch(
            root,
            "G",
            config["generator_task"],
            base.read_json(root / "initial-source-files.json"),
            None,
        )
        report["sessions"]["G"] = generator
        if generator["status"] != "COMPLETED":
            raise LocalGateError("G_FAILED_NO_RETRY")
        saved = base.read_json(root / "checkpoint-result.json")
        report["checkpoint"] = {k: v for k, v in saved.items() if k != "payload"}
        if saved["status"] not in {"SAVED_CONFIRMED", "NO_CHANGE"}:
            report["status"] = (
                "CHECKPOINT_UNCONFIRMED"
                if saved["operation"]["attempted"]
                else "NO_COMPARISON_OPPORTUNITY"
            )
            return report
        write_json(root / "frozen-g-files.json", host.manifest(root / "G/workspace"))
        if config.get("source_mode") == "PUBLIC_SOURCE_SNAPSHOT":
            report["g_source_fork"] = complete_g_sources(root)
        if "post_g_source" in config:
            report["post_g_sources"] = prepare_post_g_sources(root)
        for arm in branches(config)[1:]:
            state = accounting(read_events(root / "provider-ledger.jsonl"))
            if state["pending"] or state["violations"]:
                raise LocalGateError("BATCH_HAS_UNRESOLVED_REQUEST")
            report["sessions"][arm] = launch(root, arm, task, None, saved["payload"])
            if arm in VARIANT_ARMS and report["sessions"][arm]["status"] == "COMPLETED":
                try:
                    comparison = compare_variant(root, arm)
                except (FileNotFoundError, KeyError) as exc:
                    comparison = {"status": "NOT_EVALUABLE", "missing": type(exc).__name__}
                report.setdefault("variant_observations", {})[arm] = comparison
        report["status"] = (
            "LOCAL_CHAIN_COMPLETED_EFFECT_UNEVALUATED"
            if all(s["status"] == "COMPLETED" for s in report["sessions"].values())
            else "LOCAL_CHAIN_COMPLETED_WITH_FAILURES"
        )
    except Exception as exc:
        report.update(status="STOPPED_WITH_FAILURE", error_type=type(exc).__name__, error=str(exc))
    finally:
        report["accounting"] = accounting(read_events(root / "provider-ledger.jsonl"))
        write_json(root / "chain-result.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--compose-override", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.root.resolve(), args.config.resolve(), compose_override=args.compose_override)
    else:
        print(json.dumps(run(args.root.resolve())))
