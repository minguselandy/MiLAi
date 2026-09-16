#!/usr/bin/env python3
"""Run bounded evidence-use arms through isolated real OpenWorker stacks.

The original Product-05 path remains reproducible. Product-06 reuses the same
black-box capture/Runtime/OpenWorker harness with a disjoint selection contract and
the model-native Reader arm.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import math
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx

LAB = Path(__file__).resolve().parents[1]
PRODUCT = LAB.parent / "MiLAi-Product"
RUNTIME = PRODUCT / "runtime"
OPENWORKER = PRODUCT / "integrations" / "openworker-mcp"
MCP = PRODUCT / "integrations" / "mcp"

sys.path.insert(0, str(LAB / "src"))
sys.path.insert(0, str(LAB / "tools"))

from milai_lab.context_preflight import source_session_instance_keys  # noqa: E402
from milai_lab.longmemeval_gate import judge_messages, strict_json_judgment  # noqa: E402
from milai_lab.product_adapter.manifest import (  # noqa: E402
    load_product_lock,
    verify_product_lock,
)
from run_product03_openworker_lme import (  # noqa: E402
    _capture,
    _history_events,
    _wait_projection,
)

MODEL = "Qwen3.6-35B-A3B-FP8"
PROVIDER_ENDPOINT = "http://127.0.0.1:7860"
IMAGE = "milai-openworker:dg13u-u1-current-local"
SCOPE_PROJECT = "orchid-release"
SCOPE = {"project_ids": [SCOPE_PROJECT]}
MCP_EXE = MCP / ".venv" / "bin" / "milai-mcp"
BROKER_EXE = OPENWORKER / ".venv" / "bin" / "milai-mcp-broker"
HOST_EXE = OPENWORKER / ".venv" / "bin" / "milai-openworker-adapter"
API_EXE = RUNTIME / ".venv" / "bin" / "milai-api"
WORKER_EXE = RUNTIME / ".venv" / "bin" / "milai-worker"
OPS_EXE = RUNTIME / ".venv" / "bin" / "milai-ops"
ALEMBIC_EXE = RUNTIME / ".venv" / "bin" / "alembic"
TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
TASK_FIXTURE = PRODUCT / "contracts" / "agent" / "v1" / "dg13u-u1-candidate-fixture.json"
OPENCODE_CONFIG = OPENWORKER / "openworker" / "opencode.json"
DEFAULT_SELECTION = LAB / "data/labels/product05-openworker-lme-selection.v0.1.json"
DEFAULT_SOURCE_SELECTION = LAB / "data/labels/product03-context24-selection.v0.1.json"
DEFAULT_ANSWER_TURN_LABELS = (
    LAB / "data/labels/product02-longmemeval-answer-turns-qwen36-v4.json"
)
DEFAULT_DATASET_MANIFEST = LAB / "data/manifests/longmemeval-s-cleaned-500.json"
DEFAULT_PRODUCT_LOCK = LAB / "data/locks/product05-product.lock.json"
ARMS = ("direct", "inventory", "grounded", "ledger", "model-native")


class Product05RunError(RuntimeError):
    pass


def _expected_arm_cardinality(
    mode: str,
    reader_result: object,
) -> tuple[int, int]:
    """Return (evidence-use passes, provider requests) for an answer arm."""
    if mode == "direct":
        return 0, 1
    if mode == "ledger":
        return 2, 2
    if mode == "model-native":
        rounds = (
            reader_result.get("provider_rounds")
            if isinstance(reader_result, Mapping)
            else None
        )
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds not in {1, 2}:
            raise Product05RunError("model-native Reader round count is invalid")
        return rounds, rounds
    return 1, 1


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sampling_configuration(path: Path) -> dict[str, int]:
    config = json.loads(path.read_text(encoding="utf-8"))
    agent = config.get("agent") if isinstance(config, Mapping) else None
    build = agent.get("build") if isinstance(agent, Mapping) else None
    provider = config.get("provider") if isinstance(config, Mapping) else None
    openworker = provider.get("openworker") if isinstance(provider, Mapping) else None
    models = openworker.get("models") if isinstance(openworker, Mapping) else None
    model = models.get(MODEL) if isinstance(models, Mapping) else None
    if not isinstance(build, Mapping):
        raise Product05RunError("OpenWorker build-agent sampling configuration is absent")
    if not isinstance(model, Mapping) or model.get("temperature") is not True:
        raise Product05RunError("OpenWorker model does not declare temperature capability")
    sampling = {"temperature": build.get("temperature"), "top_p": build.get("top_p")}
    if sampling != {"temperature": 0, "top_p": 1}:
        raise Product05RunError(
            "OpenWorker answer sampling must be fixed at temperature=0, top_p=1"
        )
    return {name: int(value) for name, value in sampling.items()}


def _canonical_sha256(value: object) -> str:
    return _sha256_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )


def _retrieval_metrics(
    record: Mapping[str, Any],
    receipts: Sequence[Mapping[str, str]],
    selected_evidence_ids: Sequence[str],
    answer_turn_label: Mapping[str, Any],
) -> dict[str, Any]:
    case_id = record.get("question_id")
    session_ids = record.get("haystack_session_ids")
    sessions = record.get("haystack_sessions")
    answer_session_ids = record.get("answer_session_ids")
    if (
        not isinstance(case_id, str)
        or not isinstance(session_ids, list)
        or any(not isinstance(value, str) for value in session_ids)
        or not isinstance(sessions, list)
        or len(sessions) != len(session_ids)
        or not isinstance(answer_session_ids, list)
        or not answer_session_ids
        or any(not isinstance(value, str) for value in answer_session_ids)
    ):
        raise Product05RunError("LongMemEval answer-session identity is invalid")
    instances = source_session_instance_keys(session_ids)
    answer_id_set = set(answer_session_ids)
    expected_prefixes = {
        f"lme://{_sha256_text(case_id)[:12]}/{_sha256_text(instance)[:20]}/"
        for source_session_id, instance in zip(session_ids, instances, strict=True)
        if source_session_id in answer_id_set
    }
    if len(expected_prefixes) != len(answer_id_set):
        raise Product05RunError("LongMemEval answer session is absent from the haystack")
    source_ref_by_evidence = {
        str(receipt["evidence_id"]): str(receipt["source_ref"])
        for receipt in receipts
    }
    selected_source_refs = {
        source_ref_by_evidence[evidence_id]
        for evidence_id in selected_evidence_ids
        if evidence_id in source_ref_by_evidence
    }
    visible_gold_sessions = sum(
        any(source_ref.startswith(prefix) for source_ref in selected_source_refs)
        for prefix in expected_prefixes
    )
    session_coverage = visible_gold_sessions / len(expected_prefixes)
    negative = answer_turn_label.get("negative_without_answer_turn") is True
    selections = answer_turn_label.get("selections")
    if not isinstance(selections, list):
        raise Product05RunError("answer-turn labels are invalid")
    expected_evidence_refs: set[str] = set()
    for selection in selections:
        if not isinstance(selection, Mapping):
            raise Product05RunError("answer-turn selection is invalid")
        session_ordinal = selection.get("session_ordinal")
        turn_ordinal = selection.get("turn_ordinal")
        source_session_id = selection.get("source_session_id")
        source_text_sha256 = selection.get("source_text_sha256")
        speaker = selection.get("speaker")
        if (
            not isinstance(session_ordinal, int)
            or isinstance(session_ordinal, bool)
            or not isinstance(turn_ordinal, int)
            or isinstance(turn_ordinal, bool)
            or not isinstance(source_session_id, str)
            or not isinstance(source_text_sha256, str)
            or not isinstance(speaker, str)
            or session_ordinal < 0
            or session_ordinal >= len(session_ids)
            or session_ids[session_ordinal] != source_session_id
        ):
            raise Product05RunError("answer-turn label no longer matches the dataset")
        session = sessions[session_ordinal]
        turn = (
            session[turn_ordinal]
            if isinstance(session, list) and 0 <= turn_ordinal < len(session)
            else None
        )
        if (
            not isinstance(turn, Mapping)
            or turn.get("role") != speaker
            or not isinstance(turn.get("content"), str)
            or _sha256_text(str(turn["content"])) != source_text_sha256
        ):
            raise Product05RunError("answer-turn content identity drifted")
        expected_evidence_refs.add(
            f"lme://{_sha256_text(case_id)[:12]}/"
            f"{_sha256_text(instances[session_ordinal])[:20]}/turn/{turn_ordinal}"
        )
    if negative != (not expected_evidence_refs):
        raise Product05RunError("answer-turn negative marker is inconsistent")
    visible_evidence_groups = len(expected_evidence_refs & selected_source_refs)
    evidence_group_coverage = (
        visible_evidence_groups / len(expected_evidence_refs)
        if expected_evidence_refs
        else 1.0
    )
    return {
        "gold_session_count": len(expected_prefixes),
        "reader_visible_gold_session_count": visible_gold_sessions,
        "any_gold_session_recall": visible_gold_sessions > 0,
        "reader_visible_answer_session_coverage": session_coverage,
        "required_evidence_group_count": len(expected_evidence_refs),
        "reader_visible_evidence_group_count": visible_evidence_groups,
        "all_required_evidence_group_recall": evidence_group_coverage == 1.0,
        "reader_visible_evidence_group_coverage": evidence_group_coverage,
    }


def _private_write(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _private_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )


def _command(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(  # noqa: S603 - fixed local executable argv
        arguments,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        message = completed.stderr.decode(errors="replace")[-2000:]
        raise Product05RunError(f"command failed ({arguments[0]}): {message}")
    return completed


def _free_port() -> int:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = int(listener.getsockname()[1])
    listener.close()
    return port


def _clean_environment(values: Mapping[str, str]) -> dict[str, str]:
    result = {key: value for key, value in os.environ.items() if not key.startswith("MILAI_")}
    result.update(values)
    return result


def _load_environment(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MILAI_") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def _write_environment(path: Path, values: Mapping[str, str]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("# Product-05 private LongMemEval Runtime environment.\n")
        for key, value in sorted(values.items()):
            handle.write(f"{key}={value}\n")


def _http_json(method: str, url: str, *, timeout: float = 30) -> tuple[int, Any]:
    request = urllib.request.Request(url, method=method)  # noqa: S310 - loopback only
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read()
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def _wait_http(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise Product05RunError(f"process exited while waiting for {url}")
        try:
            status, _ = _http_json("GET", url, timeout=2)
            if status == 200:
                return
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.25)
    raise Product05RunError(f"timed out waiting for {url}")


def _wait_port(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise Product05RunError(f"process exited while waiting for port {port}")
        probe = socket.socket()
        probe.settimeout(0.25)
        try:
            probe.connect(("127.0.0.1", port))
            return
        except OSError:
            time.sleep(0.1)
        finally:
            probe.close()
    raise Product05RunError(f"timed out waiting for port {port}")


def _wait_socket(path: Path, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise Product05RunError(f"broker exited while waiting for {path}")
        try:
            mode = path.lstat().st_mode
            if stat.S_ISSOCK(mode) and stat.S_IMODE(mode) == 0o600:
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise Product05RunError(f"timed out waiting for broker socket {path}")


@dataclass(slots=True)
class ManagedProcesses:
    entries: list[tuple[subprocess.Popen[bytes], Any]] = field(default_factory=list)

    def start(
        self,
        arguments: list[str],
        log_path: Path,
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen[bytes]:
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        handle = os.fdopen(descriptor, "ab", buffering=0)
        process = subprocess.Popen(  # noqa: S603 - fixed local executable argv
            arguments,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.entries.append((process, handle))
        return process

    def stop_all(self) -> None:
        for process, _ in reversed(self.entries):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 15
        for process, handle in reversed(self.entries):
            if process.poll() is None:
                try:
                    process.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
            handle.close()
        self.entries.clear()


@dataclass(slots=True)
class HostLane:
    mode: str
    port: int
    manifest: Path
    ledger: Path
    trace: Path
    ingress_token: Path
    container: str


@dataclass(slots=True)
class CaseStack:
    ordinal: int
    case_id: str
    metadata: dict[str, Any]
    record: dict[str, Any]
    root: Path
    environment: dict[str, str]
    reader_socket: Path
    reader_policy: Path
    reader_token: Path
    lanes: dict[str, HostLane]
    processes: ManagedProcesses = field(default_factory=ManagedProcesses)
    containers: list[str] = field(default_factory=list)


def _policy(socket_path: Path, base_url: str) -> dict[str, Any]:
    return {
        "schema": "milai.openworker.mcp-broker-policy.v1",
        "profile": "reader-lite",
        "socket_path": str(socket_path),
        "socket_mode": "0600",
        "allowed_peer_uids": [os.geteuid()],
        "mcp_executable": str(MCP_EXE),
        "mcp_executable_sha256": _sha256_file(MCP_EXE),
        "base_url": base_url,
        "scope": SCOPE,
        "required_authority": "INFORMATIONAL",
        "consistency_floor": "CANONICAL_REQUIRED",
        "max_limit": 50,
        "max_connections": 16,
        "child_shutdown_seconds": 5,
        "mcp_max_retries": 0,
    }


def _provider_manifest(run_id: str, selection_sha256: str) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "schema": "milai.provider.dev-run.v1",
        "run_id": run_id,
        "phase": "dev",
        "provider": "local_vllm",
        "endpoint_identity": PROVIDER_ENDPOINT,
        "model_id": MODEL,
        "dataset_manifest_sha256": selection_sha256,
        "prompt_template_sha256": _sha256_text("product05-native-openworker-lme-v1"),
        "max_native_requests": 2,
        "max_prompt_tokens": 131_072,
        "max_completion_tokens": 8_192,
        "deadline": (now + timedelta(hours=4)).isoformat(),
        "expires_at": (now + timedelta(hours=5)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
    }


def _load_inputs(
    selection_path: Path,
    source_selection_path: Path,
    dataset_manifest_path: Path,
    tier: str,
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], dict[str, Any]]:
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    source = json.loads(source_selection_path.read_text(encoding="utf-8"))
    manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(selection, Mapping)
        or selection.get("opened_development_only") is not True
        or selection.get("formal_holdout_consumed") is not False
    ):
        raise Product05RunError("opened-development selection contract is invalid")
    schema = selection.get("schema_version")
    product06 = schema == "milai-product06-reader-selection-v0.1"
    product05 = schema == "milai-product05-openworker-lme-selection-v0.1"
    if not product05 and not product06:
        raise Product05RunError("selection schema is unsupported")
    if product05 and (
        not isinstance(source, Mapping)
        or source.get("schema_version") != "milai-product03-context24-selection-v0.1"
        or source.get("opened_development_only") is not True
        or source.get("formal_holdout_consumed") is not False
    ):
        raise Product05RunError("Product-05 source selection contract is invalid")
    tiers = selection.get("tiers")
    rows = selection.get("cases")
    source_rows = source.get("cases") if isinstance(source, Mapping) else None
    if not isinstance(tiers, Mapping) or not isinstance(rows, list):
        raise Product05RunError("selection rows are invalid")
    tier_ids = tiers.get(tier)
    if tier == "B2":
        base = tiers.get("S1")
        additions = selection.get("b2_mechanism_probe_additions")
        tier_ids = (
            [*base, *additions]
            if isinstance(base, list) and isinstance(additions, list)
            else None
        )
    if not isinstance(tier_ids, list) or any(not isinstance(value, str) for value in tier_ids):
        raise Product05RunError("selected tier is invalid")
    if product05:
        s0 = tiers.get("S0")
        s1 = tiers.get("S1")
        s2 = tiers.get("S2")
        source_ids = [
            str(row.get("case_id"))
            for row in source_rows or []
            if isinstance(row, Mapping)
        ]
        if (
            not isinstance(s0, list)
            or not isinstance(s1, list)
            or not isinstance(s2, list)
            or len(s0) != 6
            or len(s1) != 12
            or len(s2) != 24
            or not set(s0).issubset(s1)
            or not set(s1).issubset(s2)
            or set(s2) != set(source_ids)
        ):
            raise Product05RunError("S0/S1/S2 selection nesting is invalid")
    else:
        validation = tiers.get("V0")
        confirmation = tiers.get("R3")
        if (
            not isinstance(validation, list)
            or not isinstance(confirmation, list)
            or len(validation) != 12
            or len(confirmation) != 24
            or len(set(validation)) != 12
            or len(set(confirmation)) != 24
            or set(validation) & set(confirmation)
            or set(validation) | set(confirmation)
            != {
                str(row.get("case_id"))
                for row in rows
                if isinstance(row, Mapping)
            }
        ):
            raise Product05RunError("Product-06 V0/R3 selection partition is invalid")
    metadata_by_id = {
        str(row["case_id"]): dict(row)
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("case_id"), str)
    }
    if len(metadata_by_id) != len(rows) or any(
        case_id not in metadata_by_id for case_id in tier_ids
    ):
        raise Product05RunError("selection metadata is incomplete")

    root = manifest.get("external_root") if isinstance(manifest, Mapping) else None
    split_files = manifest.get("split_files") if isinstance(manifest, Mapping) else None
    hashes = manifest.get("file_sha256") if isinstance(manifest, Mapping) else None
    filename = split_files.get("population_500") if isinstance(split_files, Mapping) else None
    if (
        not isinstance(root, str)
        or not isinstance(filename, str)
        or not isinstance(hashes, Mapping)
    ):
        raise Product05RunError("dataset manifest is invalid")
    dataset = Path(root) / filename
    if not dataset.is_file() or _sha256_file(dataset) != hashes.get(filename):
        raise Product05RunError("dataset identity mismatch")
    population = json.loads(dataset.read_text(encoding="utf-8"))
    if not isinstance(population, list) or len(population) != 500:
        raise Product05RunError("dataset population shape is invalid")
    population_by_id = {
        str(row["question_id"]): dict(row)
        for row in population
        if isinstance(row, Mapping) and isinstance(row.get("question_id"), str)
    }
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for case_id in tier_ids:
        record = population_by_id.get(case_id)
        metadata = metadata_by_id[case_id]
        if record is None or record.get("question_type") != metadata.get("query_type"):
            raise Product05RunError("selected case metadata drifted from the dataset")
        selected.append((metadata, record))
    identities = {
        "experiment": "product06" if product06 else "product05",
        "dataset_sha256": _sha256_file(dataset),
        "dataset_manifest_sha256": _sha256_file(dataset_manifest_path),
        "selection_sha256": _sha256_file(selection_path),
        "source_selection_sha256": (
            None if product06 else _sha256_file(source_selection_path)
        ),
    }
    return selected, identities


def _make_stack(
    *,
    output: Path,
    socket_root: Path,
    ordinal: int,
    metadata: dict[str, Any],
    record: dict[str, Any],
    base_environment: Mapping[str, str],
    arms: Sequence[str],
    run_id: str,
    selection_sha256: str,
) -> CaseStack:
    label = f"c{ordinal:02d}"
    root = output / "private" / label
    root.mkdir(mode=0o700, parents=True)
    (root / "blobs").mkdir(mode=0o700)
    (root / "openworker-data").mkdir(mode=0o700)
    api_port = _free_port()
    environment = dict(base_environment)
    environment.update(
        {
            "MILAI_BLOB_ROOT": str(root / "blobs"),
            "MILAI_TENANT_ID": str(uuid4()),
            "MILAI_LOCAL_ACTOR_ID": str(uuid4()),
            "MILAI_API_TOKEN": secrets.token_urlsafe(48),
            "MILAI_CAUSAL_TOKEN_SECRET": secrets.token_urlsafe(48),
            "MILAI_AGENT_READER_TOKEN": secrets.token_urlsafe(48),
            "MILAI_AGENT_SUBMITTER_TOKEN": secrets.token_urlsafe(48),
            "MILAI_AGENT_OPERATOR_TOKEN": secrets.token_urlsafe(48),
            "MILAI_AGENT_REVIEWER_TOKEN": secrets.token_urlsafe(48),
            "MILAI_BLOB_KEK_B64": base64.b64encode(secrets.token_bytes(32)).decode(),
            "MILAI_BIND_PORT": str(api_port),
            "MILAI_BASE_URL": f"http://127.0.0.1:{api_port}",
            "MILAI_DATA_MODE": "DEIDENTIFIED_ALLOWED",
        }
    )
    _write_environment(root / "runtime.env", environment)
    reader_root = socket_root / label / "reader-lite"
    reader_root.mkdir(mode=0o700, parents=True)
    reader_socket = reader_root / "reader-lite.sock"
    reader_policy = root / "reader.policy.json"
    _private_write(reader_policy, _policy(reader_socket, environment["MILAI_BASE_URL"]))
    reader_token = root / "reader.token"
    descriptor = os.open(reader_token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(environment["MILAI_AGENT_READER_TOKEN"] + "\n")
    lanes: dict[str, HostLane] = {}
    for mode in arms:
        lane_root = root / mode
        lane_root.mkdir(mode=0o700)
        ingress = lane_root / "ingress.token"
        descriptor = os.open(ingress, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("t" + secrets.token_urlsafe(47) + "\n")
        manifest_path = lane_root / "provider-manifest.json"
        _private_write(
            manifest_path,
            _provider_manifest(f"{run_id}-{label}-{mode}", selection_sha256),
        )
        lanes[mode] = HostLane(
            mode=mode,
            port=_free_port(),
            manifest=manifest_path,
            ledger=lane_root / "provider-ledger.jsonl",
            trace=lane_root / "host-trace.jsonl",
            ingress_token=ingress,
            container=f"{run_id}-{label}-{mode[:3]}",
        )
    return CaseStack(
        ordinal=ordinal,
        case_id=str(record["question_id"]),
        metadata=metadata,
        record=record,
        root=root,
        environment=environment,
        reader_socket=reader_socket,
        reader_policy=reader_policy,
        reader_token=reader_token,
        lanes=lanes,
    )


def _start_case_services(stack: CaseStack) -> None:
    environment = _clean_environment(stack.environment)
    api = stack.processes.start(
        [str(API_EXE)], stack.root / "api.log", cwd=RUNTIME, env=environment
    )
    worker = stack.processes.start(
        [str(WORKER_EXE)], stack.root / "worker.log", cwd=RUNTIME, env=environment
    )
    _wait_http(f"{stack.environment['MILAI_BASE_URL']}/health/ready", api)
    if worker.poll() is not None:
        raise Product05RunError("projection worker exited during startup")
    broker = stack.processes.start(
        [
            str(BROKER_EXE),
            "--policy",
            str(stack.reader_policy),
            "--token-file",
            str(stack.reader_token),
            "--resolve-budget-profile",
            "OPENWORKER_USABILITY_WIDE_V02",
        ],
        stack.root / "reader-broker.log",
    )
    _wait_socket(stack.reader_socket, broker)


def _start_lane(stack: CaseStack, lane: HostLane, network: str, gateway: str) -> None:
    host = stack.processes.start(
        [
            str(HOST_EXE),
            "--manifest",
            str(lane.manifest),
            "--ledger",
            str(lane.ledger),
            "--trace",
            str(lane.trace),
            "--listen-host",
            "0.0.0.0",  # noqa: S104 - dedicated bridge plus bearer-authenticated ingress
            "--listen-port",
            str(lane.port),
            "--memory-mode",
            "query-first",
            "--prefetch-socket",
            str(stack.reader_socket),
            "--evidence-use-mode",
            lane.mode,
            "--tokenizer-json",
            str(TOKENIZER),
            "--broker-policy",
            str(stack.reader_policy),
            "--task-fixture",
            str(TASK_FIXTURE),
            "--ingress-token-file",
            str(lane.ingress_token),
            "--provider-timeout-seconds",
            "300",
        ],
        lane.trace.with_name("host.log"),
        cwd=OPENWORKER,
    )
    _wait_port(lane.port, host)
    token = lane.ingress_token.read_text(encoding="utf-8").strip()
    _command(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            lane.container,
            "--network",
            network,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--ulimit",
            "core=0",
            "--mount",
            f"type=bind,src={stack.root / 'openworker-data'},dst=/openworker/data",
            "--mount",
            (
                f"type=bind,src={stack.reader_socket},"
                "dst=/run/milai-mcp/reader-lite.sock,readonly"
            ),
            "--env",
            f"OPENWORKER_URL=http://{gateway}:{lane.port}/v1",
            "--env",
            f"OPENWORKER_KEY={token}",
            "--env",
            "OPENWORKER_PRINT_LOGS=1",
            IMAGE,
        ],
        timeout=60,
    )
    stack.containers.append(lane.container)
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        health = _command(
            [
                "docker",
                "exec",
                lane.container,
                "curl",
                "--fail",
                "--silent",
                "--user",
                "opencode:openworker-local",
                "http://127.0.0.1:4096/global/health",
            ],
            timeout=5,
            check=False,
        )
        if health.returncode == 0:
            return
        time.sleep(1)
    raise Product05RunError("OpenWorker did not become healthy")


def _stop_container(name: str) -> None:
    _command(["docker", "stop", "--time", "10", name], timeout=20, check=False)
    _command(["docker", "rm", name], timeout=20, check=False)


def _container_json(container: str, arguments: list[str], timeout: int = 60) -> Any:
    completed = _command(["docker", "exec", container, *arguments], timeout=timeout)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise Product05RunError("OpenWorker returned invalid JSON") from exc


def _native_answer(container: str, title: str, prompt: str) -> tuple[str, str]:
    created = _container_json(
        container,
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--user",
            "opencode:openworker-local",
            "--request",
            "POST",
            "--header",
            "Content-Type: application/json",
            "--data-binary",
            json.dumps({"title": title}, separators=(",", ":")),
            "http://127.0.0.1:4096/session?directory=%2Fopenworker%2Fruntime",
        ],
    )
    session_id = created.get("id") if isinstance(created, Mapping) else None
    if not isinstance(session_id, str):
        raise Product05RunError("native OpenWorker session identity is absent")
    _command(
        [
            "docker",
            "exec",
            "--workdir",
            "/openworker/runtime",
            "--env",
            "OPENCODE_CONFIG_DIR=/openworker/runtime",
            container,
            "opencode",
            "run",
            "--attach",
            "http://127.0.0.1:4096",
            "--password",
            "openworker-local",
            "--format",
            "json",
            "--model",
            f"openworker/{MODEL}",
            "--session",
            session_id,
            "--dir",
            "/openworker/runtime",
            prompt,
        ],
        timeout=600,
    )
    messages = _container_json(
        container,
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--user",
            "opencode:openworker-local",
            (
                f"http://127.0.0.1:4096/session/{session_id}/message?"
                "directory=%2Fopenworker%2Fruntime"
            ),
        ],
    )
    answers = [
        part["text"]
        for message in messages
        if isinstance(message, Mapping)
        and isinstance(message.get("info"), Mapping)
        and message["info"].get("role") == "assistant"
        for part in message.get("parts", [])
        if isinstance(part, Mapping)
        and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    ]
    if not answers:
        raise Product05RunError("native OpenWorker operation returned no answer")
    return session_id, str(answers[-1]).strip()


def _jsonrpc_receive(stream: Any, request_id: int) -> dict[str, Any]:
    for _ in range(32):
        line = stream.readline()
        if not line:
            raise Product05RunError("reader broker closed its JSON-RPC stream")
        response = json.loads(line)
        if response.get("id") != request_id:
            continue
        if "error" in response or not isinstance(response.get("result"), Mapping):
            raise Product05RunError("reader broker returned an MCP error")
        return dict(response["result"])
    raise Product05RunError("reader broker response limit exceeded")


def _broker_resolve(socket_path: Path, query: str) -> dict[str, Any]:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(60)
    connection.connect(str(socket_path))
    try:
        stream = connection.makefile("rwb")

        def send(value: object) -> None:
            stream.write(
                json.dumps(value, separators=(",", ":")).encode() + b"\n"
            )
            stream.flush()

        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2026-07-28",
                    "capabilities": {},
                    "clientInfo": {"name": "product05-fixed-context", "version": "0.1"},
                },
            }
        )
        _jsonrpc_receive(stream, 1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "milai_memory_resolve", "arguments": {"query": query}},
            }
        )
        result = _jsonrpc_receive(stream, 2)
        structured = result.get("structuredContent")
        if result.get("isError") is True or not isinstance(structured, Mapping):
            raise Product05RunError("reader resolve returned no structured result")
        return dict(structured)
    finally:
        connection.close()


def _trace_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _provider_trace(lane: HostLane) -> dict[str, Any]:
    rows = [row for row in _trace_rows(lane.trace) if row.get("event") == "PROVIDER_ANSWER"]
    if len(rows) != 1:
        raise Product05RunError("native arm did not produce exactly one provider trace")
    return rows[0]


def _cleanup_case(stack: CaseStack) -> None:
    for container in reversed(stack.containers):
        _stop_container(container)
    stack.containers.clear()
    stack.processes.stop_all()


async def _execute_case(
    stack: CaseStack,
    *,
    network: str,
    gateway: str,
    generation_semaphore: asyncio.Semaphore,
    capture_concurrency: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        await asyncio.to_thread(_start_case_services, stack)
        events = _history_events(stack.record, SCOPE_PROJECT)
        helper_args = SimpleNamespace(
            mcp_executable=MCP_EXE,
            scope_project=SCOPE_PROJECT,
            capture_concurrency=capture_concurrency,
        )
        receipts = await _capture(helper_args, events, stack.environment)
        await _wait_projection(helper_args, receipts, stack.environment)
        prompt = (
            f"Reference date: {stack.record['question_date']}\n"
            f"{stack.record['question']}\n"
            "Answer concisely using only the governed memory supplied for this operation."
        )
        snapshot = await asyncio.to_thread(_broker_resolve, stack.reader_socket, prompt)
        memory_context = snapshot.get("memory_context")
        if not isinstance(memory_context, Mapping) or not isinstance(
            memory_context.get("text"), str
        ):
            raise Product05RunError("fixed Reader Context is absent")
        context_text = str(memory_context["text"])
        context_sha256 = _sha256_text(context_text)
        selected_evidence = memory_context.get("selected_evidence_ids")
        captured_ids = {str(row["evidence_id"]) for row in receipts}
        if (
            not isinstance(selected_evidence, list)
            or not selected_evidence
            or not set(str(value) for value in selected_evidence).issubset(captured_ids)
        ):
            raise Product05RunError("Reader Context crossed its case Evidence namespace")
        receipt = snapshot.get("context_receipt")
        mappings = receipt.get("receipt_mapping") if isinstance(receipt, Mapping) else None
        aliases = [
            str(row["alias"])
            for row in mappings
            if isinstance(row, Mapping) and isinstance(row.get("alias"), str)
        ] if isinstance(mappings, list) else []
        if not aliases or len(aliases) != len(set(aliases)):
            raise Product05RunError("fixed Reader Context lost stable aliases")

        arms: dict[str, dict[str, Any]] = {}
        for mode, lane in stack.lanes.items():
            async with generation_semaphore:
                await asyncio.to_thread(_start_lane, stack, lane, network, gateway)
                session_id, answer = await asyncio.to_thread(
                    _native_answer,
                    lane.container,
                f"Reader experiment {stack.ordinal:02d} {mode}",
                    prompt,
                )
                await asyncio.to_thread(_stop_container, lane.container)
                stack.containers.remove(lane.container)
            trace = _provider_trace(lane)
            observations = [
                row
                for row in _trace_rows(lane.trace)
                if row.get("event") == "HOST_NATIVE_REQUEST_OBSERVED"
            ]
            expected_applied = mode != "direct"
            reader_result = trace.get("reader_session_result")
            expected_pass_count, expected_provider_request_count = (
                _expected_arm_cardinality(mode, reader_result)
            )
            if (
                len(observations) != 1
                or observations[0].get("temperature") != 0
                or observations[0].get("top_p") != 1
                or trace.get("provider_call") is not True
                or trace.get("mcp_calls") != 1
                or trace.get("memory_status") not in {"AVAILABLE", "UNCERTAIN"}
                or trace.get("context_sha256") != context_sha256
                or trace.get("evidence_use_mode") != mode
                or trace.get("evidence_use_applied") is not expected_applied
                or trace.get("evidence_use_pass_count") != expected_pass_count
                or trace.get("reader_visible_alias_count") != len(aliases)
            ):
                raise Product05RunError("Host arm violated the fixed Context contract")
            evidence_result = trace.get("evidence_use_result")
            if mode in {"grounded", "ledger"} and (
                not isinstance(evidence_result, Mapping)
                or evidence_result.get("host_validated") is not True
                or evidence_result.get("truth_or_completeness_certified") is not False
            ):
                raise Product05RunError("grounded response did not pass Host validation")
            if mode == "model-native" and (
                not isinstance(reader_result, Mapping)
                or reader_result.get("transport") != "minimal_action_v1"
                or reader_result.get("provider_rounds") not in {1, 2}
            ):
                raise Product05RunError("model-native Reader trace is incomplete")
            ledger_rows = _trace_rows(lane.ledger)
            if (
                len([row for row in ledger_rows if row.get("event") == "RESERVED"])
                != expected_provider_request_count
                or any("retry" in str(row.get("event", "")).casefold() for row in ledger_rows)
            ):
                raise Product05RunError("provider call cardinality or retry contract drifted")
            arms[mode] = {
                "answer": answer,
                "answer_sha256": _sha256_text(answer),
                "session_id": session_id,
                "trace": trace,
            }

        if len({row["trace"]["context_sha256"] for row in arms.values()}) != 1:
            raise Product05RunError("evidence-use arms did not consume identical Context bytes")
        compile_trace = memory_context.get("compile_trace")
        if (
            not isinstance(compile_trace, Mapping)
            or compile_trace.get("canonical_mutation") is not False
        ):
            raise Product05RunError("read path reported Canonical mutation")
        return {
            "status": "ANSWERED",
            "ordinal": stack.ordinal,
            "case_id": stack.case_id,
            "metadata": stack.metadata,
            "question": stack.record["question"],
            "question_date": stack.record["question_date"],
            "reference_answer": stack.record["answer"],
            "source_session_count": len(stack.record["haystack_sessions"]),
            "source_turn_count": len(events),
            "evidence_count": len(receipts),
            "context_text": context_text,
            "context_sha256": context_sha256,
            "visible_aliases": aliases,
            "selected_evidence_count": len(selected_evidence),
            "_capture_receipts": receipts,
            "_selected_evidence_ids": [str(value) for value in selected_evidence],
            "arms": arms,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    except Exception as exc:
        failure = {
            "status": "FAILED",
            "ordinal": stack.ordinal,
            "case_id": stack.case_id,
            "metadata": stack.metadata,
            "failure_class": type(exc).__name__,
            "failure_message": str(exc)[:1000],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        _private_write(stack.root / "case.failure.json", failure)
        return failure
    finally:
        await asyncio.to_thread(_cleanup_case, stack)


def _references(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _literal_answer_match(answer: str, reference: object) -> bool:
    normalized_answer = " ".join(answer.casefold().split())
    return any(
        normalized_answer == " ".join(candidate.casefold().split())
        for candidate in _references(reference)
        if candidate.strip()
    )


@dataclass(frozen=True, slots=True)
class NumericReference:
    value: float
    kind: str
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class AnswerNumber:
    value: float
    start: int
    end: int


_SCALAR_NUMERIC_REFERENCE = re.compile(
    r"^\s*(?P<currency>[$€£¥])?\s*"
    r"(?P<number>-?\d+(?:,\d{3})*(?:\.\d+)?)(?P<scale>[kKmM])?\s*"
    r"(?P<unit>%|[A-Za-z]+(?:\s+ago)?)?\s*\.?\s*$"
)
_ANSWER_NUMBER = re.compile(
    r"(?<![\w.])(?P<currency>[$€£¥])?\s*"
    r"(?P<number>-?\d+(?:,\d{3})*(?:\.\d+)?)(?P<scale>[kKmM])?\s*"
    r"(?P<unit>%|[A-Za-z]+)?",
    re.IGNORECASE,
)
_AGGREGATE_MARKER = re.compile(
    r"\b(?:total|sum|combined|altogether|in\s+all|result|equals?)\b|=",
    re.IGNORECASE,
)
_ABSTENTION_MARKER = re.compile(
    r"\b(?:cannot|can't|unable\s+to)\s+(?:determine|answer|calculate|establish)\b"
    r"|\b(?:not\s+enough|insufficient)\s+(?:information|evidence)\b"
    r"|\b(?:no|does\s+not\s+contain|doesn't\s+contain)\s+"
    r"(?:any\s+)?(?:information|records?|evidence)\b",
    re.IGNORECASE,
)


def _scaled_number(number: str, scale: str | None) -> float:
    multiplier = (
        1_000.0
        if scale and scale.casefold() == "k"
        else 1_000_000.0
        if scale
        else 1.0
    )
    return float(number.replace(",", "")) * multiplier


def _normalized_unit(value: str | None) -> str | None:
    if value is None:
        return None
    unit = value.casefold().removesuffix(" ago").strip()
    if unit.endswith("s") and unit not in {"ms"}:
        unit = unit[:-1]
    return unit


def _numeric_reference(value: object) -> NumericReference | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return NumericReference(float(value), "scalar")
    if not isinstance(value, str):
        return None
    match = _SCALAR_NUMERIC_REFERENCE.fullmatch(value)
    if match is None:
        return None
    currency = match.group("currency")
    unit = _normalized_unit(match.group("unit"))
    kind = "currency" if currency else "percent" if unit == "%" else "unit" if unit else "scalar"
    return NumericReference(
        _scaled_number(match.group("number"), match.group("scale")),
        kind,
        currency or unit,
    )


def _scorable_numeric_text(answer: str, expected: NumericReference) -> str:
    scrubbed = re.sub(r"\[E\d+\]", "", answer, flags=re.IGNORECASE)
    scrubbed = re.sub(r"(?m)^\s*\d+[.)]\s+", "", scrubbed)
    if not (expected.kind == "scalar" and 1000 <= expected.value <= 2100):
        scrubbed = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}\b", "", scrubbed)
        scrubbed = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", "", scrubbed)
    return scrubbed


def _answer_numbers(answer: str, expected: NumericReference) -> list[AnswerNumber]:
    result: list[AnswerNumber] = []
    for match in _ANSWER_NUMBER.finditer(answer):
        currency = match.group("currency")
        unit = _normalized_unit(match.group("unit"))
        if expected.kind == "currency" and currency != expected.unit:
            continue
        if expected.kind == "percent" and unit != "%":
            continue
        if expected.kind == "unit" and unit != expected.unit:
            continue
        result.append(
            AnswerNumber(
                _scaled_number(match.group("number"), match.group("scale")),
                match.start(),
                match.end(),
            )
        )
    return result


def _same_number(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def _numeric_answer_match(answer: str, expected: NumericReference) -> bool:
    scorable = _scorable_numeric_text(answer, expected)
    numbers = _answer_numbers(scorable, expected)
    if not any(_same_number(item.value, expected.value) for item in numbers):
        return False
    distinct = {item.value for item in numbers}
    if expected.kind not in {"currency", "percent", "unit"} or len(distinct) == 1:
        return True
    aggregate_results: list[AnswerNumber] = []
    for marker in _AGGREGATE_MARKER.finditer(scorable):
        following = next(
            (
                item
                for item in numbers
                if marker.end() <= item.start <= marker.end() + 80
            ),
            None,
        )
        if following is not None:
            aggregate_results.append(following)
    if aggregate_results:
        return _same_number(aggregate_results[-1].value, expected.value)
    return _same_number(numbers[0].value, expected.value)


def _abstention_answer_match(answer: str) -> bool:
    return _ABSTENTION_MARKER.search(" ".join(answer.split())) is not None


def _seed(case_id: str) -> int:
    return int(_sha256_text(f"product05\0{case_id}\0judge")[:16], 16) & ((1 << 63) - 1)


async def _judge_one(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    *,
    case_id: str,
    question: str,
    reference: object,
    prediction: str,
    abstention_expected: bool,
) -> tuple[bool, dict[str, Any]]:
    exact = _literal_answer_match(prediction, reference)
    expected_number = _numeric_reference(reference)
    if abstention_expected:
        return _abstention_answer_match(prediction), {
            "scorer": "DETERMINISTIC_ABSTENTION",
            "provider_called": False,
        }
    if exact or (
        expected_number is not None and _numeric_answer_match(prediction, expected_number)
    ):
        return True, {"scorer": "DETERMINISTIC", "provider_called": False}
    if expected_number is not None:
        return False, {"scorer": "DETERMINISTIC", "provider_called": False}
    async with semaphore:
        started = time.perf_counter()
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": MODEL,
                "messages": judge_messages(question, _references(reference), prediction),
                "temperature": 0,
                "top_p": 1,
                "seed": _seed(case_id),
                "max_tokens": 64,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "milai_product05_judgment",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {"correct": {"type": "boolean"}},
                            "required": ["correct"],
                            "additionalProperties": False,
                        },
                    },
                },
            },
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    body = response.json()
    choices = body.get("choices") if isinstance(body, Mapping) else None
    message = choices[0].get("message") if isinstance(choices, list) and len(choices) == 1 else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str):
        raise Product05RunError("judge response content is absent")
    correct = strict_json_judgment(json.loads(content))
    usage = body.get("usage") if isinstance(body.get("usage"), Mapping) else {}
    return correct, {
        "scorer": "QWEN_SAME_MODEL_JUDGE",
        "provider_called": True,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "elapsed_ms": round(elapsed_ms, 3),
        "response_sha256": _sha256_text(content),
    }


async def _score_answers(
    answered: list[dict[str, Any]], arms: Sequence[str], concurrency: int
) -> int:
    semaphore = asyncio.Semaphore(concurrency)
    client = httpx.AsyncClient(
        base_url=PROVIDER_ENDPOINT,
        timeout=httpx.Timeout(180),
        trust_env=False,
        limits=httpx.Limits(max_connections=concurrency),
    )
    jobs: list[tuple[dict[str, Any], str, asyncio.Task[tuple[bool, dict[str, Any]]]]] = []
    try:
        for case in answered:
            for mode in arms:
                task = asyncio.create_task(
                    _judge_one(
                        client,
                        semaphore,
                        case_id=str(case["case_id"]),
                        question=str(case["question"]),
                        reference=case["reference_answer"],
                        prediction=str(case["arms"][mode]["answer"]),
                        abstention_expected=case["metadata"].get("abstention") is True,
                    )
                )
                jobs.append((case, mode, task))
        judge_calls = 0
        for case, mode, task in jobs:
            correct, score = await task
            case["arms"][mode]["correct"] = correct
            case["arms"][mode]["score"] = score
            judge_calls += int(score["provider_called"])
        return judge_calls
    finally:
        await client.aclose()


def _comparison(answered: Sequence[Mapping[str, Any]], mode: str) -> dict[str, Any]:
    gains = [
        row
        for row in answered
        if not row["arms"]["direct"]["correct"] and row["arms"][mode]["correct"]
    ]
    losses = [
        row
        for row in answered
        if row["arms"]["direct"]["correct"] and not row["arms"][mode]["correct"]
    ]
    lookup_losses = [row for row in losses if row["metadata"]["ordinary_lookup"]]
    unsupported = (
        [
            row
            for row in answered
            if row["metadata"]["abstention"] and not row["arms"][mode]["correct"]
        ]
        if mode == "model-native"
        else [row for row in losses if row["metadata"]["abstention"]]
    )
    families = sorted({str(row["metadata"]["capability_family"]) for row in gains})
    result: dict[str, Any] = {
        "additional_correct": len(gains),
        "regressions": len(losses),
        "net_correct_gain": len(gains) - len(losses),
        "ordinary_lookup_correct_case_regressions": len(lookup_losses),
        "new_unsupported_answers": len(unsupported),
        "gain_family_count": len(families),
        "gain_families": families,
        "gained_case_hashes": [_sha256_text(str(row["case_id"])) for row in gains],
        "lost_case_hashes": [_sha256_text(str(row["case_id"])) for row in losses],
    }
    if mode in {"grounded", "ledger"}:
        grounded_results = [row["arms"][mode]["trace"]["evidence_use_result"] for row in answered]
        arithmetic = [
            row["arms"][mode]["trace"]["evidence_use_result"]
            for row in answered
            if row["metadata"]["arithmetic_expected"]
        ]
        result.update(
            {
                "evidence_alias_validity": sum(
                    int(value.get("host_validated") is True) for value in grounded_results
                )
                / len(grounded_results)
                if grounded_results
                else 0.0,
                "explicit_arithmetic_consistency": (
                    sum(
                        int(
                            value.get("host_validated") is True
                            and value.get("calculation_present") is True
                        )
                        for value in arithmetic
                    )
                    / len(arithmetic)
                    if arithmetic
                    else 1.0
                ),
            }
        )
    if mode == "model-native":
        reader_results = [
            row["arms"][mode]["trace"].get("reader_session_result")
            for row in answered
        ]
        typed_results = [value for value in reader_results if isinstance(value, Mapping)]
        tool_results = [
            value
            for row, value in zip(answered, reader_results, strict=True)
            if isinstance(value, Mapping) and value.get("tool_calls")
        ]
        result.update(
            {
                "reader_trace_coverage": (
                    len(typed_results) / len(answered) if answered else 0.0
                ),
                "reader_fallbacks": sum(
                    int(value.get("fallback") is True) for value in typed_results
                ),
                "invalid_visible_citations": sum(
                    int(value.get("invalid_citation_count", 0))
                    for value in typed_results
                ),
                "calculator_answer_count": len(tool_results),
                "calculator_correct_answer_count": sum(
                    int(row["arms"][mode]["correct"])
                    for row, value in zip(answered, reader_results, strict=True)
                    if isinstance(value, Mapping) and value.get("tool_calls")
                ),
                "provider_rounds": sum(
                    int(value.get("provider_rounds", 0)) for value in typed_results
                ),
            }
        )
    result["p05_h2_effect_gate"] = (
        result.get("evidence_alias_validity") == 1.0
        and result.get("explicit_arithmetic_consistency") == 1.0
        and result["ordinary_lookup_correct_case_regressions"] == 0
        and result["additional_correct"] >= 3
        and result["gain_family_count"] >= 2
        and result["new_unsupported_answers"] == 0
    )
    return result


def _database_audit(postgres_container: str) -> dict[str, Any]:
    queries = {
        "evidence": (
            "SELECT tenant_id::text || '|' || count(*) "
            "FROM milai.evidence_record GROUP BY tenant_id ORDER BY tenant_id"
        ),
        "projection": (
            "SELECT tenant_id::text || '|' || count(*) "
            "FROM milai.evidence_search_document GROUP BY tenant_id ORDER BY tenant_id"
        ),
        "canonical": (
            "SELECT (SELECT count(*) FROM milai.claim)"
            "+(SELECT count(*) FROM milai.operation_proposal)"
            "+(SELECT count(*) FROM milai.steward_decision)"
            "+(SELECT count(*) FROM milai.open_issue)"
            "+(SELECT count(*) FROM milai.claim_version)"
            "+(SELECT count(*) FROM milai.claim_head)"
            "+(SELECT count(*) FROM milai.version_transition)"
            "+(SELECT count(*) FROM milai.grounding_relation)"
            "+(SELECT count(*) FROM milai.grounding_block)"
            "+(SELECT count(*) FROM milai.open_issue_transition)"
        ),
    }
    values: dict[str, Any] = {}
    for name, query in queries.items():
        output = _command(
            [
                "docker",
                "exec",
                postgres_container,
                "psql",
                "--no-psqlrc",
                "--tuples-only",
                "--no-align",
                "--username",
                "milai_owner",
                "--dbname",
                "milai",
                "--command",
                query,
            ]
        ).stdout.decode().strip()
        if name == "canonical":
            values[name] = int(output)
        else:
            values[name] = {
                tenant: int(count)
                for line in output.splitlines()
                for tenant, count in [line.split("|", 1)]
                if line
            }
    return values


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    args.output = args.output.resolve(strict=False)
    if args.output.exists():
        raise Product05RunError("run output already exists")
    args.output.mkdir(mode=0o700, parents=True)
    arms = tuple(value.strip() for value in args.arms.split(",") if value.strip())
    if (
        not arms
        or len(set(arms)) != len(arms)
        or any(value not in ARMS for value in arms)
        or "direct" not in arms
    ):
        raise Product05RunError("arms must be unique supported modes and include direct")
    selected, identities = _load_inputs(
        args.selection,
        args.source_selection,
        args.dataset_manifest,
        args.tier,
    )
    experiment = str(identities.pop("experiment"))
    if experiment == "product06" and arms != ("direct", "model-native"):
        raise Product05RunError("Product-06 requires exact direct,model-native arms")
    lock = load_product_lock(args.product_lock)
    verification = verify_product_lock(lock, PRODUCT)
    if not verification.valid:
        raise Product05RunError("Product pin failed: " + "; ".join(verification.errors))
    for path in (
        MCP_EXE,
        BROKER_EXE,
        HOST_EXE,
        API_EXE,
        WORKER_EXE,
        OPS_EXE,
        ALEMBIC_EXE,
        TOKENIZER,
        TASK_FIXTURE,
        OPENCODE_CONFIG,
        args.answer_turn_labels,
    ):
        if not path.is_file():
            raise Product05RunError(f"required local artifact is missing: {path}")
    expected_tokenizer = "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"
    if _sha256_file(TOKENIZER) != expected_tokenizer:
        raise Product05RunError("frozen tokenizer identity changed")
    provider_status, provider_value = _http_json("GET", PROVIDER_ENDPOINT + "/v1/models")
    if provider_status != 200 or MODEL not in json.dumps(provider_value):
        raise Product05RunError("frozen local Qwen provider is unavailable")
    image_id = _command(
        ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"]
    ).stdout.decode().strip()
    sampling = _sampling_configuration(OPENCODE_CONFIG)
    config_sha256 = _sha256_file(OPENCODE_CONFIG)
    image_config_sha256 = _command(
        [
            "docker",
            "image",
            "inspect",
            IMAGE,
            "--format",
            '{{index .Config.Labels "io.milai.dg13u.source-config-sha256"}}',
        ]
    ).stdout.decode().strip()
    if image_config_sha256 != config_sha256:
        raise Product05RunError("OpenWorker image does not embed the pinned sampling configuration")

    run_id = args.run_id
    project = f"{run_id}-pg"
    network = f"{run_id}-net"
    socket_root = Path(tempfile.mkdtemp(prefix="m5l-", dir="/tmp"))
    socket_root.chmod(0o700)
    compose: list[str] = []
    postgres_started = False
    network_started = False
    stacks: list[CaseStack] = []
    run_payload = {
        "schema": f"milai.{experiment}.openworker-lme.run.v1",
        "run_id": run_id,
        "runner_sha256": _sha256_file(Path(__file__)),
        "started_at": datetime.now(UTC).isoformat(),
        "tier": args.tier,
        "arms": list(arms),
        "case_count": len(selected),
        "product_lock_digest": lock.digest,
        "product_tree_sha256": lock.tree_sha256,
        "product_pin_valid": True,
        **identities,
        "model": MODEL,
        "provider_endpoint": PROVIDER_ENDPOINT,
        "image": IMAGE,
        "image_id": image_id,
        "tokenizer_sha256": expected_tokenizer,
        "experiment_arm_kind": "PRODUCT_BLACK_BOX",
        "same_context_bytes_across_arms": True,
        "one_tenant_and_data_namespace_per_case": True,
        "capture_concurrency_per_case": args.capture_concurrency,
        "case_stack_concurrency": args.case_concurrency,
        "generation_concurrency": args.generation_concurrency,
        "judge_concurrency": args.judge_concurrency,
        **sampling,
        "openworker_config_sha256": config_sha256,
        "semantic_retries": 0,
        "votes": 0,
        "formal_holdout_consumed": False,
        "references_hidden_until_all_answers_complete": True,
        "answer_turn_labels_sha256": _sha256_file(args.answer_turn_labels),
    }
    _private_write(args.output / "run.json", run_payload)
    try:
        postgres_port = _free_port()
        base_env_path = args.output / "private" / "postgres.env"
        base_env_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _command(
            [
                str(OPS_EXE),
                "init",
                "--env-file",
                str(base_env_path),
                "--blob-root",
                str(args.output / "private" / "unused-base-blobs"),
                "--postgres-port",
                str(postgres_port),
                "--api-port",
                str(_free_port()),
            ],
            cwd=RUNTIME,
        )
        base_environment = _load_environment(base_env_path)
        compose = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(base_env_path),
            "--file",
            str(RUNTIME / "compose.yaml"),
        ]
        _command([*compose, "up", "--detach", "postgres"], cwd=RUNTIME, timeout=120)
        postgres_started = True
        deadline = time.monotonic() + 90
        while True:
            migration = _command(
                [str(ALEMBIC_EXE), "-c", "alembic.ini", "upgrade", "head"],
                cwd=RUNTIME,
                env=_clean_environment(
                    {
                        "MILAI_MIGRATION_DATABASE_URL": base_environment[
                            "MILAI_MIGRATION_DATABASE_URL"
                        ]
                    }
                ),
                timeout=120,
                check=False,
            )
            if migration.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise Product05RunError("fresh PostgreSQL migration failed")
            await asyncio.sleep(1)
        _command(["docker", "network", "create", network], timeout=30)
        network_started = True
        network_value = json.loads(
            _command(["docker", "network", "inspect", network], timeout=30).stdout
        )
        gateway = network_value[0]["IPAM"]["Config"][0]["Gateway"]
        if not isinstance(gateway, str):
            raise Product05RunError("Docker bridge gateway is absent")

        stacks = [
            _make_stack(
                output=args.output,
                socket_root=socket_root,
                ordinal=ordinal,
                metadata=metadata,
                record=record,
                base_environment=base_environment,
                arms=arms,
                run_id=run_id,
                selection_sha256=identities["selection_sha256"],
            )
            for ordinal, (metadata, record) in enumerate(selected, start=1)
        ]
        case_semaphore = asyncio.Semaphore(args.case_concurrency)
        generation_semaphore = asyncio.Semaphore(args.generation_concurrency)

        async def guarded(stack: CaseStack) -> dict[str, Any]:
            async with case_semaphore:
                row = await _execute_case(
                    stack,
                    network=network,
                    gateway=gateway,
                    generation_semaphore=generation_semaphore,
                    capture_concurrency=args.capture_concurrency,
                )
                print(
                    json.dumps(
                        {
                            "case": f"{stack.ordinal}/{len(stacks)}",
                            "case_id_sha256": _sha256_text(stack.case_id),
                            "status": row["status"],
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                return row

        rows = await asyncio.gather(*(guarded(stack) for stack in stacks))
        answered = [row for row in rows if row["status"] == "ANSWERED"]
        answers_complete_at = datetime.now(UTC).isoformat()
        answer_turn_payload = json.loads(
            args.answer_turn_labels.read_text(encoding="utf-8")
        )
        answer_turn_rows = (
            answer_turn_payload.get("cases")
            if isinstance(answer_turn_payload, Mapping)
            else None
        )
        if (
            not isinstance(answer_turn_payload, Mapping)
            or answer_turn_payload.get("schema_version")
            != "milai-product02-answer-turn-labels-v1"
            or not isinstance(answer_turn_rows, list)
        ):
            raise Product05RunError("answer-turn label artifact is invalid")
        answer_turn_by_id = {
            str(item["case_id"]): item
            for item in answer_turn_rows
            if isinstance(item, Mapping) and isinstance(item.get("case_id"), str)
        }
        if len(answer_turn_by_id) != len(answer_turn_rows) or any(
            stack.case_id not in answer_turn_by_id for stack in stacks
        ):
            raise Product05RunError("answer-turn labels are incomplete")
        for stack, row in zip(stacks, rows, strict=True):
            if row["status"] != "ANSWERED":
                continue
            row["retrieval_metrics"] = _retrieval_metrics(
                stack.record,
                row.pop("_capture_receipts"),
                row.pop("_selected_evidence_ids"),
                answer_turn_by_id[stack.case_id],
            )
        judge_calls = await _score_answers(answered, arms, args.judge_concurrency)
        postgres_container = f"{project}-postgres-1"
        database = _database_audit(postgres_container)
        expected_tenants = {stack.environment["MILAI_TENANT_ID"] for stack in stacks}
        expected_evidence = {
            stack.environment["MILAI_TENANT_ID"]: len(
                _history_events(stack.record, SCOPE_PROJECT)
            )
            for stack in stacks
        }
        database_valid = (
            database["canonical"] == 0
            and set(database["evidence"]) == expected_tenants
            and database["evidence"] == database["projection"]
            and all(
                database["evidence"].get(tenant) == count
                for tenant, count in expected_evidence.items()
            )
        )
        unexpected_tenants = (
            set(database["evidence"]) | set(database["projection"])
        ) - expected_tenants
        expected_evidence_total = sum(expected_evidence.values())
        captured_evidence_total = sum(
            min(database["evidence"].get(tenant, 0), expected_count)
            for tenant, expected_count in expected_evidence.items()
        )
        projection_ready_count = sum(
            database["evidence"].get(tenant) == expected_count
            and database["projection"].get(tenant) == expected_count
            for tenant, expected_count in expected_evidence.items()
        )
        fixed_context_count = sum(
            row["status"] == "ANSWERED"
            and len(
                {
                    row["arms"][mode]["trace"]["context_sha256"]
                    for mode in arms
                }
            )
            == 1
            for row in rows
        )
        lane_traces = [
            _trace_rows(lane.trace)
            for stack in stacks
            for lane in stack.lanes.values()
        ]
        native_openworker_operations = sum(
            any(row.get("event") == "HOST_NATIVE_REQUEST_OBSERVED" for row in trace)
            for trace in lane_traces
        )
        native_request_attempts = sum(
            row.get("event") == "HOST_NATIVE_REQUEST_OBSERVED"
            for trace in lane_traces
            for row in trace
        )
        query_first_resolve_calls = sum(
            row.get("event") == "HOST_MCP_PREPARE_ATTEMPT"
            for trace in lane_traces
            for row in trace
        )
        provider_answer_calls = sum(
            row.get("event") == "RESERVED"
            for stack in stacks
            for lane in stack.lanes.values()
            for row in _trace_rows(lane.ledger)
        )
        automatic_transport_retries = max(
            0, native_request_attempts - native_openworker_operations
        )
        comparisons = {
            mode: _comparison(answered, mode) for mode in arms if mode != "direct"
        }
        arm_metrics = {
            mode: {
                "correct": sum(int(row["arms"][mode]["correct"]) for row in answered),
                "total": len(answered),
                "accuracy": (
                    sum(int(row["arms"][mode]["correct"]) for row in answered)
                    / len(answered)
                    if answered
                    else 0.0
                ),
            }
            for mode in arms
        }
        retrieval_metrics = {
            "any_gold_session_recall_rate": (
                sum(
                    int(row["retrieval_metrics"]["any_gold_session_recall"])
                    for row in answered
                )
                / len(rows)
                if rows
                else 0.0
            ),
            "all_required_evidence_group_recall_rate": (
                sum(
                    int(
                        row["retrieval_metrics"][
                            "all_required_evidence_group_recall"
                        ]
                    )
                    for row in answered
                )
                / len(rows)
                if rows
                else 0.0
            ),
            "reader_visible_evidence_group_coverage": (
                sum(
                    float(
                        row["retrieval_metrics"][
                            "reader_visible_evidence_group_coverage"
                        ]
                    )
                    for row in answered
                )
                / len(rows)
                if rows
                else 0.0
            ),
            "reader_visible_answer_session_coverage": (
                sum(
                    float(
                        row["retrieval_metrics"][
                            "reader_visible_answer_session_coverage"
                        ]
                    )
                    for row in answered
                )
                / len(rows)
                if rows
                else 0.0
            ),
        }
        reader_comparison = comparisons.get("model-native", {})
        host_evidence_rejections = sum(
            row.get("event") == "HOST_EVIDENCE_USE_REJECTED"
            for trace in lane_traces
            for row in trace
        )
        host_reader_fallbacks = sum(
            row.get("event") == "HOST_READER_SESSION_FALLBACK"
            for trace in lane_traces
            for row in trace
        )
        p06_h1_gate = (
            experiment == "product06"
            and args.tier == "V0"
            and len(answered) == 12
            and reader_comparison.get("additional_correct", 0) >= 3
            and reader_comparison.get("gain_family_count", 0) >= 2
            and reader_comparison.get("ordinary_lookup_correct_case_regressions", 0) == 0
            and reader_comparison.get("new_unsupported_answers", 0) == 0
            and reader_comparison.get("invalid_visible_citations", 0) == 0
            and host_evidence_rejections == 0
            and host_reader_fallbacks == 0
            and automatic_transport_retries == 0
        )
        p06_h2_gate = (
            experiment == "product06"
            and args.tier == "R3"
            and len(answered) == 24
            and reader_comparison.get("additional_correct", 0) >= 4
            and reader_comparison.get("net_correct_gain", 0) >= 3
            and reader_comparison.get("gain_family_count", 0) >= 3
            and reader_comparison.get("ordinary_lookup_correct_case_regressions", 0) == 0
            and reader_comparison.get("regressions", 0) <= 1
            and reader_comparison.get("new_unsupported_answers", 0) == 0
            and reader_comparison.get("invalid_visible_citations", 0) == 0
            and host_evidence_rejections == 0
            and host_reader_fallbacks == 0
            and automatic_transport_retries == 0
            and len(unexpected_tenants) == 0
            and database["canonical"] == 0
        )
        selected_method = (
            "model-native"
            if p06_h1_gate or p06_h2_gate
            else next(
                (
                    mode
                    for mode in ("inventory", "grounded", "ledger")
                    if mode in comparisons and comparisons[mode]["p05_h2_effect_gate"]
                ),
                None,
            )
        )
        private_rows: list[dict[str, Any]] = []
        public_rows: list[dict[str, Any]] = []
        for row in rows:
            if row["status"] != "ANSWERED":
                private_rows.append(dict(row))
                public_rows.append(
                    {
                        "ordinal": row["ordinal"],
                        "case_id_sha256": _sha256_text(str(row["case_id"])),
                        "status": "FAILED",
                        "query_type": row["metadata"].get("query_type"),
                        "capability_family": row["metadata"].get("capability_family"),
                        "failure_class": row.get("failure_class"),
                        "failure_message": row.get("failure_message"),
                    }
                )
                continue
            private_rows.append(dict(row))
            public_rows.append(
                {
                    "ordinal": row["ordinal"],
                    "case_id_sha256": _sha256_text(str(row["case_id"])),
                    "status": "PASS",
                    "query_type": row["metadata"]["query_type"],
                    "capability_family": row["metadata"]["capability_family"],
                    "source_sessions": row["source_session_count"],
                    "source_turns": row["source_turn_count"],
                    "evidence_captured": row["evidence_count"],
                    "context_sha256": row["context_sha256"],
                    "visible_alias_count": len(row["visible_aliases"]),
                    "selected_evidence_count": row["selected_evidence_count"],
                    "retrieval_metrics": row["retrieval_metrics"],
                    "arms": {
                        mode: {
                            "answer_sha256": row["arms"][mode]["answer_sha256"],
                            "correct": row["arms"][mode]["correct"],
                            "scorer": row["arms"][mode]["score"]["scorer"],
                            "context_sha256": row["arms"][mode]["trace"]["context_sha256"],
                            "host_validated": (
                                row["arms"][mode]["trace"].get("evidence_use_result", {}).get(
                                    "host_validated"
                                )
                                if isinstance(
                                    row["arms"][mode]["trace"].get("evidence_use_result"),
                                    Mapping,
                                )
                                else None
                            ),
                            "reader_stop_reason": (
                                row["arms"][mode]["trace"]
                                .get("reader_session_result", {})
                                .get("stop_reason")
                                if isinstance(
                                    row["arms"][mode]["trace"].get(
                                        "reader_session_result"
                                    ),
                                    Mapping,
                                )
                                else None
                            ),
                        }
                        for mode in arms
                    },
                }
            )
        _private_jsonl(args.output / "cases.jsonl", public_rows)
        _private_jsonl(args.output / "private" / "cases.private.jsonl", private_rows)
        execution_valid = (
            len(answered) == len(rows)
            and database_valid
            and automatic_transport_retries == 0
        )
        summary = {
            "schema": f"milai.{experiment}.openworker-lme.summary.v1",
            "run_id": run_id,
            "status": (
                "PASS_P06_H1"
                if p06_h1_gate
                else "PASS_P06_H2"
                if p06_h2_gate
                else "PASS_P05_H2"
                if experiment == "product05" and selected_method is not None
                else "PASS_EXECUTION_NO_EFFECT_GATE"
            )
            if execution_valid
            else "FAIL_EXECUTION",
            "tier": args.tier,
            "case_count": len(rows),
            "answered_case_count": len(answered),
            "failed_case_count": len(rows) - len(answered),
            "arms": list(arms),
            "arm_metrics": arm_metrics,
            "retrieval_metrics": retrieval_metrics,
            "comparisons_to_direct": comparisons,
            "selected_smallest_passing_method": selected_method,
            "p06_h1_gate": p06_h1_gate,
            "p06_h2_gate": p06_h2_gate,
            "host_evidence_use_rejections": host_evidence_rejections,
            "host_reader_session_fallbacks": host_reader_fallbacks,
            "native_openworker_operations": native_openworker_operations,
            "native_request_attempts": native_request_attempts,
            "query_first_resolve_calls": query_first_resolve_calls,
            "provider_answer_calls": provider_answer_calls,
            "judge_calls": judge_calls,
            "capture_success_rate": (
                captured_evidence_total / expected_evidence_total
                if expected_evidence_total
                else 0.0
            ),
            "projection_ready_rate": projection_ready_count / len(stacks) if stacks else 0.0,
            "fixed_context_identity_rate": fixed_context_count / len(rows) if rows else 0.0,
            "independent_tenant_count": len(database["evidence"]),
            "expected_independent_tenant_count": len(rows),
            "database_namespace_complete": set(database["evidence"]) == expected_tenants,
            "database_projection_consistent": database["evidence"] == database["projection"],
            "cross_tenant_evidence_or_projection_leaks": len(unexpected_tenants),
            "unauthorized_canonical_mutations": database["canonical"],
            "automatic_semantic_retries": 0,
            "automatic_transport_retries": automatic_transport_retries,
            "votes": 0,
            "answers_complete_before_judges": True,
            "answers_complete_at": answers_complete_at,
            "same_model_self_judge": True,
            "runner_sha256": run_payload["runner_sha256"],
            "product_lock_digest": lock.digest,
            "product_tree_sha256": lock.tree_sha256,
            "dataset_sha256": identities["dataset_sha256"],
            "selection_sha256": identities["selection_sha256"],
            "answer_turn_labels_sha256": _sha256_file(args.answer_turn_labels),
            "image_id": image_id,
            **sampling,
            "openworker_config_sha256": config_sha256,
            "tokenizer_sha256": expected_tokenizer,
            "model": MODEL,
            "formal_holdout_consumed": False,
            "postgres_volume_preserved": True,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        _private_write(args.output / "summary.json", summary)
        return summary
    finally:
        for stack in stacks:
            _cleanup_case(stack)
        if network_started:
            _command(["docker", "network", "rm", network], timeout=30, check=False)
        if postgres_started:
            _command([*compose, "down"], cwd=RUNTIME, timeout=60, check=False)
        for path in sorted(socket_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_socket() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                path.rmdir()
        socket_root.rmdir()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--tier", choices=("S0", "S1", "S2", "B2", "V0", "R3"), required=True
    )
    parser.add_argument("--arms", default="direct,inventory,grounded")
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--source-selection", type=Path, default=DEFAULT_SOURCE_SELECTION)
    parser.add_argument(
        "--answer-turn-labels", type=Path, default=DEFAULT_ANSWER_TURN_LABELS
    )
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_DATASET_MANIFEST)
    parser.add_argument("--product-lock", type=Path, default=DEFAULT_PRODUCT_LOCK)
    parser.add_argument("--capture-concurrency", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--case-concurrency", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--generation-concurrency", type=int, choices=range(1, 5), default=3)
    parser.add_argument("--judge-concurrency", type=int, choices=range(1, 5), default=4)
    return parser


def main() -> None:
    args = _parser().parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    if not 8 <= len(args.run_id) <= 42 or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in args.run_id
    ):
        raise SystemExit("run-id must contain 8-42 lowercase alphanumeric/hyphen characters")
    try:
        summary = asyncio.run(_run(args))
    except Exception as exc:
        raise SystemExit(f"Product-05 OpenWorker LME failed: {type(exc).__name__}: {exc}") from exc
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
