from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from milai.adapters.agent_prefetch import SYSTEM_PROMPT

from evals.benchmark import lme_product_smoke as benchmark
from scripts import dg11_state
from scripts import run_dg10_f0 as package_gate

RUNS_ROOT = ROOT / "var/dg11/runs"
FREEZE_ROOT = ROOT / "var/dg11/freeze"
CANDIDATE_ROOT = FREEZE_ROOT / "candidate"
SPLIT_FREEZE = ROOT / "var/dg11/splits/v1/freeze-manifest.json"
SPLIT_BINDING = ROOT / "var/dg11/splits/v1/candidate-binding.json"
DG10_CANDIDATE = ROOT / "var/dg10/final/candidate"
TOKENIZER_JSON = Path("/cra/qwen36-35B/tokenizer.json")

DEFAULT_R04_RESULT = ROOT / "var/dg11/dev/r04-latest-result.json"
DEFAULT_FUNCTIONAL_RESULT = ROOT / "var/dg11/functional/latest-result.json"
DEFAULT_AGENTIC_RESULT = ROOT / "var/dg11/agentic/latest-result.json"
DEFAULT_EFFICIENCY_RESULT = ROOT / "var/dg11/efficiency/latest-result.json"

PACKAGE_NAMES = (
    "client_wheel",
    "mcp_wheel",
    "runtime_wheel",
    "openworker_wheel",
)
PACKAGE_PROJECTS = (
    ROOT / "integrations/python-client/src",
    ROOT / "integrations/mcp/src",
    ROOT / "runtime/src",
    ROOT / "integrations/openworker-mcp/src",
    ROOT / "evals/agent_integration/mcp_host.py",
    Path(package_gate.__file__).resolve(),
)
SOURCE_PATHS = (
    ROOT / "runtime/src",
    ROOT / "runtime/migrations",
    ROOT / "runtime/pyproject.toml",
    ROOT / "integrations/python-client/src",
    ROOT / "integrations/python-client/pyproject.toml",
    ROOT / "integrations/mcp/src",
    ROOT / "integrations/mcp/pyproject.toml",
    ROOT / "integrations/openworker-mcp/src",
    ROOT / "integrations/openworker-mcp/pyproject.toml",
)
ADAPTER_PATHS = (
    ROOT / "evals/benchmark/dg11_holdout_context_worker.py",
    ROOT / "evals/benchmark/lme_product_smoke.py",
    ROOT / "evals/benchmark/dg11_v2.py",
    ROOT / "integrations/mcp/src/milai_mcp/server.py",
    ROOT / "integrations/openworker-mcp/src/milai_openworker_mcp/adapter.py",
    ROOT / "scripts/freeze_dg11_v2.py",
    ROOT / "scripts/run_dg11_v2.py",
)


class R06FreezeError(RuntimeError):
    pass


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise R06FreezeError(f"required JSON is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise R06FreezeError(f"required JSON is not an object: {path}")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _all_true(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and bool(value)
        and all(item is True for item in value.values())
    )


def _publish_candidate(
    temporary_candidate: Path, binding: Mapping[str, Any]
) -> None:
    """Publish the candidate and split binding without leaving a normal-error half state."""
    if CANDIDATE_ROOT.exists() or SPLIT_BINDING.exists():
        raise R06FreezeError("the unique DG11 candidate is already frozen")
    staged_binding = SPLIT_BINDING.with_name(
        f".{SPLIT_BINDING.name}.{uuid.uuid4().hex}.stage"
    )
    try:
        dg11_state.atomic_json(staged_binding, dict(binding))
        os.replace(temporary_candidate, CANDIDATE_ROOT)
        try:
            os.replace(staged_binding, SPLIT_BINDING)
        except BaseException:
            try:
                os.replace(CANDIDATE_ROOT, temporary_candidate)
            except BaseException as rollback_error:
                raise R06FreezeError(
                    "candidate publication failed and rollback also failed; "
                    f"staged binding retained at {staged_binding}"
                ) from rollback_error
            raise
    finally:
        if not (CANDIDATE_ROOT.exists() and not SPLIT_BINDING.exists()):
            staged_binding.unlink(missing_ok=True)


def _validate_evidence(
    r04: Mapping[str, Any],
    functional: Mapping[str, Any],
    agentic: Mapping[str, Any],
    efficiency: Mapping[str, Any],
) -> None:
    if (
        r04.get("work_package") != "DG11-R04"
        or r04.get("status") != "PASS"
        or not _all_true(r04.get("gates"))
        or r04.get("development_ai_reviews") != 0
    ):
        raise R06FreezeError("R04 combined evidence has not passed every gate")

    functional_classification = functional.get("classification")
    functional_gates = (
        functional_classification.get("gates")
        if isinstance(functional_classification, Mapping)
        else None
    )
    if (
        functional.get("status") != "PASS"
        or not _all_true(functional_gates)
        or functional.get("provider_requests") != 30
        or functional.get("development_ai_reviews") != 0
    ):
        raise R06FreezeError("R05 functional evidence is incomplete")

    if (
        agentic.get("status") != "PASS"
        or not _all_true(agentic.get("gates"))
        or agentic.get("provider_requests") != 60
        or agentic.get("development_ai_reviews") != 0
    ):
        raise R06FreezeError("R05 Agentic evidence is incomplete")

    classification = efficiency.get("classification")
    if not isinstance(classification, Mapping):
        raise R06FreezeError("R05 efficiency classification is absent")
    for work_package in ("DG11-04", "DG11-05"):
        entry = classification.get(work_package)
        if (
            not isinstance(entry, Mapping)
            or entry.get("status") != "PASS"
            or not _all_true(entry.get("gates"))
        ):
            raise R06FreezeError(f"R05 efficiency gate failed: {work_package}")
    if (
        efficiency.get("status") != "PASS"
        or efficiency.get("development_ai_reviews") != 0
    ):
        raise R06FreezeError("R05 efficiency evidence is incomplete")


def _resolve_package_artifacts(
    functional: Mapping[str, Any],
) -> tuple[Path, dict[str, Path], dict[str, Any]]:
    functional_run_id = functional.get("run_id")
    if not isinstance(functional_run_id, str):
        raise R06FreezeError("functional run ID is absent")
    package_root = RUNS_ROOT / functional_run_id / "steps/package-step"
    package_result = _load_object(package_root / "result.json")
    package_manifest = _load_object(package_root / "manifest.json")
    expected_cases = {"F0-01": "PASS", "F0-02": "PASS"}
    if (
        package_result.get("status") != "PASS"
        or package_result.get("cases") != expected_cases
        or package_manifest.get("code_identity")
        != package_gate._tree_identity(list(PACKAGE_PROJECTS))
    ):
        raise R06FreezeError("R05 package bytes are not bound to the current source")
    raw_artifacts = package_result.get("artifacts")
    if not isinstance(raw_artifacts, Mapping):
        raise R06FreezeError("R05 package artifact manifest is absent")
    artifacts: dict[str, Path] = {}
    artifact_entries: dict[str, Any] = {}
    for name in PACKAGE_NAMES:
        entry = raw_artifacts.get(name)
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise R06FreezeError(f"R05 package artifact is absent: {name}")
        path = (package_root / str(entry["path"])).resolve()
        if (
            not path.is_relative_to(package_root.resolve())
            or not path.is_file()
            or dg11_state.sha256(path) != entry.get("sha256")
        ):
            raise R06FreezeError(f"R05 package artifact identity drifted: {name}")
        artifacts[name] = path
        artifact_entries[name] = dict(entry)
    return package_root, artifacts, artifact_entries


def _projection_identity(r04: Mapping[str, Any]) -> dict[str, Any]:
    records = r04.get("records")
    if not isinstance(records, list) or len(records) != 100:
        raise R06FreezeError("R04 record denominator is not 100")
    embeddings: dict[str, dict[str, Any]] = {}
    rerankers: dict[str, dict[str, Any]] = {}
    for raw_record in records:
        if not isinstance(raw_record, Mapping):
            raise R06FreezeError("R04 record is malformed")
        trace = raw_record.get("runtime_trace")
        if not isinstance(trace, Mapping):
            raise R06FreezeError("R04 runtime trace is absent")
        raw_embedding = trace.get("embedding")
        if isinstance(raw_embedding, Mapping):
            embedding = {
                key: raw_embedding.get(key)
                for key in (
                    "provider",
                    "model_id",
                    "source_dimensions",
                    "projection_dimensions",
                )
            }
            embeddings[_digest(embedding)] = embedding
        retrieved = trace.get("retrieved_items")
        if isinstance(retrieved, list):
            for item in retrieved:
                reranker_raw = item.get("reranker") if isinstance(item, Mapping) else None
                if not isinstance(reranker_raw, Mapping):
                    continue
                reranker = {
                    key: reranker_raw.get(key)
                    for key in (
                        "provider",
                        "model_id",
                        "model_sha256",
                        "revision",
                        "runtime",
                        "max_length",
                        "tokenizer_sha256",
                    )
                }
                rerankers[_digest(reranker)] = reranker
    if len(embeddings) != 1 or len(rerankers) != 1:
        raise R06FreezeError("R04 projection or reranker identity is not unique")
    return {
        "embedding": next(iter(embeddings.values())),
        "reranker": next(iter(rerankers.values())),
    }


def _file_identities(paths: Sequence[Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.is_file() or path.name == ".env":
            raise R06FreezeError(f"identity source is absent or unsafe: {path}")
        result[path.relative_to(ROOT).as_posix()] = {
            "sha256": dg11_state.sha256(path),
            "bytes": path.stat().st_size,
        }
    return result


def _rollback_identity() -> dict[str, Any]:
    freeze = DG10_CANDIDATE / "freeze-manifest.json"
    packages = DG10_CANDIDATE / "packages"
    if not freeze.is_file():
        raise R06FreezeError("DG10 rollback freeze manifest is absent")
    wheels = sorted(packages.glob("*.whl"))
    if len(wheels) != 4:
        raise R06FreezeError("DG10 rollback wheel denominator is not four")
    return {
        "status": "AVAILABLE",
        "freeze_manifest": str(freeze.relative_to(ROOT)),
        "freeze_manifest_sha256": dg11_state.sha256(freeze),
        "wheels": {
            wheel.name: {
                "path": str(wheel.relative_to(ROOT)),
                "sha256": dg11_state.sha256(wheel),
                "bytes": wheel.stat().st_size,
            }
            for wheel in wheels
        },
    }


def _record_state(result: Mapping[str, Any]) -> None:
    state = _load_object(dg11_state.CURRENT_STATE)
    recovery = state.setdefault("recovery_work_packages", {})
    if not isinstance(recovery, dict):
        raise R06FreezeError("recovery work-package state is malformed")
    recovery["DG11-R05"] = "PASS"
    recovery["DG11-R06"] = "PASS"
    state["recovery_phase"] = "R06_FROZEN"
    state["latest_result"] = result["run_id"]
    state["development_ai_reviews"] = 0
    dg11_state.atomic_json(dg11_state.CURRENT_STATE, state)
    dg11_state.append_ledger(
        {
            "run_id": result["run_id"],
            "work_package": "DG11-R06",
            "status": "PASS",
            "decision": "FREEZE",
            "provider_requests": 0,
            "development_ai_reviews": 0,
            "metrics": result["gates"],
        }
    )


def run(
    run_id: str,
    *,
    r04_result_path: Path = DEFAULT_R04_RESULT,
    functional_result_path: Path = DEFAULT_FUNCTIONAL_RESULT,
    agentic_result_path: Path = DEFAULT_AGENTIC_RESULT,
    efficiency_result_path: Path = DEFAULT_EFFICIENCY_RESULT,
) -> dict[str, Any]:
    if package_gate._RUN_ID.fullmatch(run_id) is None:
        raise R06FreezeError("run_id must be 8-96 lowercase URL-safe characters")
    if CANDIDATE_ROOT.exists() or SPLIT_BINDING.exists():
        raise R06FreezeError("the unique DG11 candidate is already frozen")
    for required in (SPLIT_FREEZE, TOKENIZER_JSON, ROOT / "runtime/.env"):
        if not required.is_file():
            raise R06FreezeError(f"freeze input is absent: {required}")

    r04 = _load_object(r04_result_path)
    functional = _load_object(functional_result_path)
    agentic = _load_object(agentic_result_path)
    efficiency = _load_object(efficiency_result_path)
    _validate_evidence(r04, functional, agentic, efficiency)
    package_root, artifacts, artifact_entries = _resolve_package_artifacts(functional)
    projection = _projection_identity(r04)
    adapter_identity = _file_identities(ADAPTER_PATHS)
    source_identity = package_gate._tree_identity(list(SOURCE_PATHS))
    rollback = _rollback_identity()

    run_root = RUNS_ROOT / run_id
    try:
        run_root.mkdir(parents=True, mode=0o700)
    except FileExistsError as exc:
        raise R06FreezeError(f"run_id already exists: {run_id}") from exc
    trace: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=f"milai-{run_id}-") as temporary:
        workspace = Path(temporary).resolve() / "frozen-install-probe"
        if workspace.is_relative_to(ROOT):
            raise R06FreezeError("fresh install workspace is inside the repository")
        install = package_gate._probe_install(
            kind="wheel",
            client_artifact=artifacts["client_wheel"],
            mcp_artifact=artifacts["mcp_wheel"],
            runtime_artifact=artifacts["runtime_wheel"],
            runtime_extras=("embedding",),
            openworker_artifact=artifacts["openworker_wheel"],
            workspace=workspace,
            trace=trace,
        )

    identity_payload = {
        "source_identity": source_identity,
        "config_sha256": dg11_state.sha256(ROOT / "runtime/.env"),
        "prompt_contract_sha256": benchmark.prompt_contract_sha256(),
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "tokenizer_sha256": dg11_state.sha256(TOKENIZER_JSON),
        "projection": projection,
        "adapters": adapter_identity,
        "wheels": {
            name: artifact_entries[name]["sha256"] for name in PACKAGE_NAMES
        },
    }
    candidate_id = _digest(identity_payload)
    evidence = {
        "r04": {"path": str(r04_result_path), "sha256": dg11_state.sha256(r04_result_path)},
        "functional": {
            "path": str(functional_result_path),
            "sha256": dg11_state.sha256(functional_result_path),
        },
        "agentic": {
            "path": str(agentic_result_path),
            "sha256": dg11_state.sha256(agentic_result_path),
        },
        "efficiency": {
            "path": str(efficiency_result_path),
            "sha256": dg11_state.sha256(efficiency_result_path),
        },
    }

    FREEZE_ROOT.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary_candidate = Path(
        tempfile.mkdtemp(prefix=".candidate.", dir=FREEZE_ROOT)
    )
    try:
        packages = temporary_candidate / "packages"
        packages.mkdir(mode=0o700)
        wheel_manifest: dict[str, Any] = {}
        for name, source in artifacts.items():
            destination = packages / source.name
            shutil.copy2(source, destination, follow_symlinks=False)
            wheel_manifest[name] = {
                "path": f"packages/{destination.name}",
                "sha256": dg11_state.sha256(destination),
                "bytes": destination.stat().st_size,
            }
        manifest = {
            "schema": "milai.dg11.frozen-candidate.v1",
            "status": "FROZEN",
            "run_id": run_id,
            "candidate_id": candidate_id,
            "frozen_at": datetime.now(UTC).isoformat(),
            "source_identity": source_identity,
            "package_source_root": str(package_root.relative_to(ROOT)),
            "config": {
                "path": "runtime/.env",
                "sha256": identity_payload["config_sha256"],
                "content_embedded": False,
            },
            "prompt": {
                "answer_contract_sha256": identity_payload["prompt_contract_sha256"],
                "system_prompt_sha256": identity_payload["system_prompt_sha256"],
            },
            "tokenizer": {
                "path": str(TOKENIZER_JSON),
                "sha256": identity_payload["tokenizer_sha256"],
            },
            "projection": projection,
            "adapters": adapter_identity,
            "wheels": wheel_manifest,
            "fresh_install": install,
            "evidence": evidence,
            "split_freeze": {
                "path": str(SPLIT_FREEZE.relative_to(ROOT)),
                "sha256": dg11_state.sha256(SPLIT_FREEZE),
            },
            "rollback": rollback,
            "declarations": {
                "runtime": "0.1.x CANDIDATE",
                "schema": "0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE",
                "production_ready": False,
            },
            "provider_requests": 0,
            "development_ai_reviews": 0,
        }
        candidate_manifest = temporary_candidate / "candidate-manifest.json"
        dg11_state.atomic_json(candidate_manifest, manifest)
        binding = {
            "schema": "milai.dg11.recovery-split-candidate-binding.v1",
            "status": "BOUND",
            "candidate_id": candidate_id,
            "split_freeze_sha256": dg11_state.sha256(SPLIT_FREEZE),
            "candidate_manifest_path": str(
                (CANDIDATE_ROOT / "candidate-manifest.json").relative_to(ROOT)
            ),
            "candidate_manifest_sha256": dg11_state.sha256(candidate_manifest),
            "created_at": datetime.now(UTC).isoformat(),
        }
        _publish_candidate(temporary_candidate, binding)
    except BaseException:
        shutil.rmtree(temporary_candidate, ignore_errors=True)
        raise
    gates = {
        "r04_pass": True,
        "r05_functional_pass": True,
        "r05_agentic_pass": True,
        "r05_efficiency_pass": True,
        "four_wheels_frozen": len(manifest["wheels"]) == 4,
        "fresh_isolated_install_pass": install.get("status") == "PASS",
        "non_repo_cwd": not Path(str(install["non_repo_cwd"])).is_relative_to(ROOT),
        "source_and_runtime_identity_bound": True,
        "dg10_rollback_available": rollback["status"] == "AVAILABLE",
        "development_ai_reviews_zero": True,
        "provider_requests_zero": True,
    }
    result = {
        "schema": "milai.dg11.r06-freeze-result.v1",
        "run_id": run_id,
        "work_package": "DG11-R06",
        "status": "PASS" if all(gates.values()) else "FAILED",
        "decision": "FREEZE" if all(gates.values()) else "DO_NOT_FREEZE",
        "candidate_id": candidate_id,
        "candidate_manifest": str(
            (CANDIDATE_ROOT / "candidate-manifest.json").relative_to(ROOT)
        ),
        "candidate_manifest_sha256": binding["candidate_manifest_sha256"],
        "gates": gates,
        "provider_requests": 0,
        "hidden_provider_calls": 0,
        "development_ai_reviews": 0,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.atomic_json(run_root / "trace.json", {"commands": trace})
    dg11_state.atomic_json(run_root / "result.json", result)
    if result["status"] != "PASS":
        raise R06FreezeError("R06 freeze gates failed after candidate construction")
    _record_state(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the unique DG11 candidate")
    parser.add_argument(
        "--run-id",
        default=(
            "dg11-r06-freeze-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
    parser.add_argument("--r04-result", type=Path, default=DEFAULT_R04_RESULT)
    parser.add_argument(
        "--functional-result", type=Path, default=DEFAULT_FUNCTIONAL_RESULT
    )
    parser.add_argument("--agentic-result", type=Path, default=DEFAULT_AGENTIC_RESULT)
    parser.add_argument(
        "--efficiency-result", type=Path, default=DEFAULT_EFFICIENCY_RESULT
    )
    args = parser.parse_args()
    result = run(
        args.run_id,
        r04_result_path=args.r04_result.resolve(),
        functional_result_path=args.functional_result.resolve(),
        agentic_result_path=args.agentic_result.resolve(),
        efficiency_result_path=args.efficiency_result.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
