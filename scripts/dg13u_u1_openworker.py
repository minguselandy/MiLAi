from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Protocol
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg13u_u1_cache_governance_scenarios as cache_governance
from scripts import dg13u_u1_cleanup as recovery_cleanup
from scripts import dg13u_u1_evidence_artifacts as evidence_artifacts
from scripts import dg13u_u1_fault_execution as fault_execution
from scripts import dg13u_u1_fault_scenarios as fault_scenarios
from scripts import dg13u_u1_interaction_scenarios as interaction_scenarios
from scripts import dg13u_u1_lifecycle_scenarios as lifecycle_scenarios
from scripts import dg13u_u1_mcp_child_fault as mcp_child_fault
from scripts import dg13u_u1_mcp_fault as mcp_fault
from scripts import dg13u_u1_provider_fault as provider_fault
from scripts import dg13u_u1_resource_registry as resource_registry
from scripts import dg13u_u1_runtime_fault as runtime_fault
from scripts import dg13u_u1_task_scenarios as task_scenarios
from scripts import run_dg13u_openworker as u0
from scripts.dg13u_u1_fixture import (
    FixtureOptions,
    FixtureSeedError,
    apply_u1_state_change,
    cleanup_u1_canonical_fixture,
    seed_u1_canonical_fixture,
)
from scripts.dg13u_u1_runtime_writer import LoopbackRuntimeFixtureWriter

RUNS_ROOT = ROOT / "var/dg13/runs"
TMP_ROOT = ROOT / "var/dg13/tmp"
UDS_ROOT = Path("/dev/shm/milai")
INTERFACE_FREEZE = ROOT / "contracts/agent/v1/dg13u-u1-interface-freeze.md"
EXECUTION_OVERRIDE = (
    ROOT / "docs/contracts/DG13U-U1-user-direct-execution-override-20260825.md"
)
CANDIDATE_FIXTURE = ROOT / "contracts/agent/v1/dg13u-u1-candidate-fixture.json"
HEADER_CONTRACT = ROOT / "contracts/agent/v1/openworker-task-metadata-headers.md"
OPENWORKER_IMAGE = "milai-openworker:dg13u-u1-current-local"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
VLLM_ORIGIN = "http://127.0.0.1:7860"
TOKENIZER_JSON = Path("/cra/qwen36-35B/tokenizer.json")
LOCKED_UV_CACHE = Path("/root/.cache/uv")
_PROVIDER_PROMPT_TOKENS_PER_TURN = 16_384
_PROVIDER_COMPLETION_TOKENS_PER_TURN = 96

_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{7,95}")
_RESOURCE_ID = re.compile(r"[a-z0-9][a-z0-9._:/-]{2,255}")
_REQUIRED_FIXTURE_SHA256 = (
    "47175b17cdc8444955d28cf3ec2f6d96964faf2099decf34bd317cf7729bb555"
)


class RunError(RuntimeError):
    """A bounded DG-13U operator-run failure."""


class TerminalStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_RUN = "NOT_RUN"


ResourceOwnership = resource_registry.ResourceOwnership
ResourceHandle = resource_registry.ResourceHandle
ProcessGeneration = resource_registry.ProcessGeneration


@dataclass(frozen=True, slots=True)
class CaseSpec:
    case_id: str
    title: str
    language: str
    memory_requirement: str
    expected_mcp_calls: int
    expected_provider_calls: int
    safety_counters: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SmokeCommandTruth:
    status: TerminalStatus
    reason_code: str
    exit_code: int
    typed_error_count: int


SAFETY_COUNTERS = (
    "WrongTaskAcceptance",
    "WrongScopeAcceptance",
    "StaleCurrentAcceptance",
    "RevokedEvidenceReentry",
    "UnauthorizedAuthorityEscalation",
    "SilentMemoryNeedNone",
    "TerminalCacheMiss",
    "ModelVisibleMemoryToolUse",
    "UnaccountedProviderOrMcpCall",
)

CASE_SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        "U1-NONE-EN",
        "English non-memory turn",
        "EN",
        "NONE",
        0,
        1,
        ("SilentMemoryNeedNone", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-NONE-CN",
        "Chinese non-memory turn",
        "CN",
        "NONE",
        0,
        1,
        ("SilentMemoryNeedNone", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-EXACT-TARGET-EN",
        "English exact current release target",
        "EN",
        "EXACT",
        1,
        1,
        ("SilentMemoryNeedNone", "ModelVisibleMemoryToolUse"),
    ),
    CaseSpec(
        "U1-EXACT-TARGET-CN",
        "Chinese exact current release target",
        "CN",
        "EXACT",
        1,
        1,
        ("SilentMemoryNeedNone", "ModelVisibleMemoryToolUse"),
    ),
    CaseSpec(
        "U1-EXACT-DATABASE-EN",
        "English exact current release database/config",
        "EN",
        "EXACT",
        1,
        1,
        ("SilentMemoryNeedNone", "ModelVisibleMemoryToolUse"),
    ),
    CaseSpec(
        "U1-EXACT-DATABASE-CN",
        "Chinese exact current release database/config",
        "CN",
        "EXACT",
        1,
        1,
        ("SilentMemoryNeedNone", "ModelVisibleMemoryToolUse"),
    ),
    CaseSpec(
        "U1-EXACT-DECISION-EN",
        "English exact current governed release decision",
        "EN",
        "EXACT",
        1,
        1,
        ("SilentMemoryNeedNone", "ModelVisibleMemoryToolUse"),
    ),
    CaseSpec(
        "U1-EXACT-DECISION-CN",
        "Chinese exact current governed release decision",
        "CN",
        "EXACT",
        1,
        1,
        ("SilentMemoryNeedNone", "ModelVisibleMemoryToolUse"),
    ),
    CaseSpec(
        "U1-CACHE-FALLBACK",
        "Same-call CACHE miss to exact",
        "EN",
        "EXACT",
        2,
        2,
        ("TerminalCacheMiss", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-WRONG-TASK",
        "Wrong-task reuse rejection",
        "EN",
        "EXACT",
        2,
        2,
        ("WrongTaskAcceptance", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-WRONG-SCOPE",
        "Wrong-scope rejection",
        "EN",
        "EXACT",
        1,
        1,
        ("WrongScopeAcceptance", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-STALE-CURRENT",
        "Stale current rejection",
        "EN",
        "EXACT",
        2,
        2,
        ("StaleCurrentAcceptance", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-REVOKE-REENTRY",
        "Revoked evidence re-entry rejection",
        "EN",
        "EXACT",
        1,
        0,
        ("RevokedEvidenceReentry",),
    ),
    CaseSpec(
        "U1-AUTHORITY-ESCALATION",
        "Unauthorized authority escalation rejection",
        "EN",
        "EXACT",
        0,
        0,
        ("UnauthorizedAuthorityEscalation",),
    ),
    CaseSpec(
        "U1-RUNTIME-UNAVAILABLE",
        "Strict-current Runtime unavailable terminal",
        "EN",
        "EXACT",
        1,
        0,
        ("SilentMemoryNeedNone", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-TASK-CONTINUE",
        "Same native task continuation freshly resolves canonical memory",
        "EN",
        "EXACT",
        2,
        2,
        ("WrongTaskAcceptance", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-TASK-SWITCH",
        "Native task switch invalidates the prior active slot",
        "EN",
        "EXACT",
        2,
        2,
        ("WrongTaskAcceptance", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-TASK-RETURN",
        "Native task return uses only a compatible retained slot",
        "EN",
        "EXACT",
        3,
        3,
        ("WrongTaskAcceptance", "StaleCurrentAcceptance"),
    ),
    CaseSpec(
        "U1-TASK-CONCURRENT",
        "Concurrent native sessions remain task isolated",
        "EN",
        "EXACT",
        2,
        2,
        ("WrongTaskAcceptance", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-RUNTIME-DOWN",
        "Runtime unavailable terminal before provider",
        "EN",
        "EXACT",
        1,
        0,
        ("SilentMemoryNeedNone", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-RUNTIME-MALFORMED",
        "Malformed Runtime result terminal before provider",
        "EN",
        "EXACT",
        1,
        0,
        ("SilentMemoryNeedNone", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-RUNTIME-TIMEOUT",
        "Runtime timeout terminal before provider",
        "EN",
        "EXACT",
        1,
        0,
        ("SilentMemoryNeedNone", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-MCP-CHILD-DOWN",
        "MCP child unavailable terminal before provider",
        "EN",
        "EXACT",
        1,
        0,
        ("SilentMemoryNeedNone", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-MCP-CHILD-MALFORMED",
        "Malformed MCP child result terminal before provider",
        "EN",
        "EXACT",
        1,
        0,
        ("SilentMemoryNeedNone", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-MCP-CHILD-TIMEOUT",
        "MCP child timeout terminal before provider",
        "EN",
        "EXACT",
        1,
        0,
        ("SilentMemoryNeedNone", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-ALIAS-COLLISION",
        "Ambiguous alias collision rejection",
        "EN",
        "EXACT",
        0,
        0,
        ("WrongScopeAcceptance", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-OPEN-ISSUE",
        "Governed OpenIssue blocks unsafe current acceptance",
        "EN",
        "EXACT",
        1,
        0,
        (
            "StaleCurrentAcceptance",
            "UnauthorizedAuthorityEscalation",
            "UnaccountedProviderOrMcpCall",
        ),
    ),
    CaseSpec(
        "U1-BROKER-DOWN",
        "Broker unavailable terminal before provider",
        "EN",
        "EXACT",
        1,
        0,
        ("SilentMemoryNeedNone", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-BROKER-MALFORMED",
        "Malformed broker result terminal before provider",
        "EN",
        "EXACT",
        1,
        0,
        ("SilentMemoryNeedNone", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-BROKER-TIMEOUT",
        "Broker timeout terminal before provider",
        "EN",
        "EXACT",
        1,
        0,
        ("SilentMemoryNeedNone", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-PROVIDER-DOWN",
        "Provider unavailable independent terminal",
        "EN",
        "NONE",
        0,
        1,
        ("UnaccountedProviderOrMcpCall",),
    ),
    CaseSpec(
        "U1-PROVIDER-MALFORMED",
        "Malformed provider response independent terminal",
        "EN",
        "NONE",
        0,
        1,
        ("UnaccountedProviderOrMcpCall",),
    ),
    CaseSpec(
        "U1-PROVIDER-TIMEOUT",
        "Provider timeout independent terminal",
        "EN",
        "NONE",
        0,
        1,
        ("UnaccountedProviderOrMcpCall",),
    ),
    CaseSpec(
        "U1-BROKER-INODE-RECREATE",
        "Broker socket inode recreation policy",
        "EN",
        "EXACT",
        0,
        0,
        ("UnaccountedProviderOrMcpCall",),
    ),
    CaseSpec(
        "U1-ADAPTER-RESTART",
        "Host adapter restart discards task registry",
        "EN",
        "EXACT",
        2,
        2,
        ("WrongTaskAcceptance", "UnaccountedProviderOrMcpCall"),
    ),
    CaseSpec(
        "U1-STREAM",
        "Streaming EXACT memory semantics",
        "EN",
        "EXACT",
        1,
        1,
        ("UnaccountedProviderOrMcpCall",),
    ),
    CaseSpec(
        "U1-ORDINARY-SYNC-TOOL",
        "Ordinary synchronous tool request/result semantics",
        "EN",
        "NONE",
        0,
        2,
        ("ModelVisibleMemoryToolUse", "UnaccountedProviderOrMcpCall"),
    ),
)
CASES = {case.case_id: case for case in CASE_SPECS}
_TASK_CASE_IDS = frozenset(task_scenarios.TASK_SCENARIOS)
_FAULT_CASE_IDS = frozenset(fault_scenarios.FAULT_SCENARIOS)
_CACHE_GOVERNANCE_CASE_IDS = frozenset(cache_governance.SCENARIOS)
_INTERACTION_CASE_IDS = frozenset(interaction_scenarios.PLANS)
_LIFECYCLE_CASE_IDS = frozenset(lifecycle_scenarios.LIFECYCLE_SCENARIOS)
_CACHE_GOVERNANCE_ADJACENT_CASE_IDS = frozenset(
    {"U1-AUTHORITY-ESCALATION", "U1-ALIAS-COLLISION"}
)
_CACHE_GOVERNANCE_OPENWORKER_CASE_IDS = (
    _CACHE_GOVERNANCE_CASE_IDS - _CACHE_GOVERNANCE_ADJACENT_CASE_IDS
)
_CACHE_GOVERNANCE_STATE_KEY_BINDINGS = {
    "release.target": ("orchid-release", "PROJECT_STATE"),
    "release.database": ("orchid-release", "PROJECT_CONFIG"),
    "release.decision": ("orchid-release", "PROJECT_DECISION"),
}
_IMPLEMENTED_REAL_CASES = frozenset(
    {
        "U1-NONE-EN",
        "U1-NONE-CN",
        "U1-EXACT-TARGET-EN",
        "U1-EXACT-TARGET-CN",
        "U1-EXACT-DATABASE-EN",
        "U1-EXACT-DATABASE-CN",
        "U1-EXACT-DECISION-EN",
        "U1-EXACT-DECISION-CN",
        *_TASK_CASE_IDS,
        *_FAULT_CASE_IDS,
        *_CACHE_GOVERNANCE_CASE_IDS,
        *_INTERACTION_CASE_IDS,
        *_LIFECYCLE_CASE_IDS,
    }
)


class RecoveryPlanCoordinator:
    """Serializes the exact run-owned recovery plan through digest CAS updates."""

    _ORDER: ClassVar[dict[str, int]] = {
        "external_vllm": 0,
        "temporary_root": 1,
        "uds_root": 2,
        "database": 3,
        "runtime-api": 4,
        "runtime-worker": 5,
        "docker_network": 6,
        "mcp-broker": 7,
        "host-adapter": 8,
        "docker_container": 9,
    }

    def __init__(
        self,
        run_id: str,
        durable: Path,
        temporary: Path,
        uds: Path,
    ) -> None:
        suffix = hashlib.sha256(run_id.encode()).hexdigest()
        external_identity = {
            "origin": VLLM_ORIGIN,
            "model_id": MODEL_ID,
        }
        self.run_id = run_id
        self.durable = durable
        self.plan_path = durable / recovery_cleanup.PLAN_NAME
        self.sha256: str | None = None
        self._resources: list[dict[str, Any]] = [
            {
                "kind": "external_vllm",
                "ownership": "PRESERVED_EXTERNAL",
                **external_identity,
                "identity_sha256": hashlib.sha256(
                    json.dumps(
                        external_identity,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            },
            {
                "kind": "temporary_root",
                "ownership": "RUN_OWNED",
                "path": str(temporary),
            },
            {
                "kind": "uds_root",
                "ownership": "RUN_OWNED",
                "path": str(uds),
            },
            {
                "kind": "database",
                "ownership": "RUN_OWNED",
                "database_name": f"milai_smoke_dg13u_{suffix[:20]}",
                "owner_dsn_ref": "MILAI_MIGRATION_DATABASE_URL",
            },
            {
                "kind": "docker_network",
                "ownership": "RUN_OWNED",
                "name": f"milai-dg13u-u1-net-{suffix[:16]}",
                "required_labels": {recovery_cleanup.RUN_LABEL: run_id},
            },
            {
                "kind": "docker_container",
                "ownership": "RUN_OWNED",
                "name": f"milai-dg13u-u1-worker-{suffix[:16]}",
                "required_labels": {recovery_cleanup.RUN_LABEL: run_id},
            },
        ]

    def initialize(self) -> None:
        if self.sha256 is not None:
            raise RunError("recovery resource plan is already initialized")
        try:
            written = recovery_cleanup.write_resource_plan(
                self.plan_path,
                run_id=self.run_id,
                run_dir=self.durable,
                resources=self._ordered_resources(),
            )
        except recovery_cleanup.CleanupError as exc:
            raise RunError("recovery resource plan initialization failed") from exc
        self.sha256 = str(written["sha256"])

    def checkpoint(self) -> None:
        if self.sha256 is None:
            raise RunError("recovery resource plan is not initialized")
        try:
            written = recovery_cleanup.write_resource_plan(
                self.plan_path,
                run_id=self.run_id,
                run_dir=self.durable,
                resources=self._ordered_resources(),
                expected_previous_sha256=self.sha256,
            )
        except recovery_cleanup.CleanupError as exc:
            raise RunError("recovery resource plan CAS update failed") from exc
        self.sha256 = str(written["sha256"])

    def record_process(self, role: str, pid: int, marker: str) -> None:
        if role not in {"runtime-api", "runtime-worker", "mcp-broker", "host-adapter"}:
            raise RunError("recovery process role is invalid")
        if any(
            row["kind"] == "process" and row["role"] == role for row in self._resources
        ):
            raise RunError("recovery process role was registered twice")
        self._resources.append(
            {
                "kind": "process",
                "ownership": "RUN_OWNED",
                "role": role,
                "pid": pid,
                "proc_start_marker": marker,
            }
        )
        try:
            self.checkpoint()
        except Exception:
            self._resources.pop()
            raise

    def replace_process(
        self,
        role: str,
        expected_pid: int,
        expected_marker: str,
        new_pid: int,
        new_marker: str,
    ) -> None:
        if role not in {"mcp-broker", "host-adapter"}:
            raise RunError("recovery process role is not replaceable")
        matches = [
            (index, row)
            for index, row in enumerate(self._resources)
            if row["kind"] == "process" and row.get("role") == role
        ]
        if len(matches) != 1:
            raise RunError("recovery process role is not registered exactly once")
        index, current = matches[0]
        if (
            current.get("pid"),
            current.get("proc_start_marker"),
        ) != (expected_pid, expected_marker):
            raise RunError("recovery process generation CAS mismatch")
        if (new_pid, new_marker) == (expected_pid, expected_marker):
            raise RunError("recovery replacement process generation is unchanged")
        replacement = {
            **current,
            "pid": new_pid,
            "proc_start_marker": new_marker,
        }
        previous_sha256 = self.sha256
        self._resources[index] = replacement
        try:
            self.checkpoint()
        except Exception:
            self._resources[index] = current
            self.sha256 = previous_sha256
            raise

    def binding(self) -> dict[str, str]:
        if self.sha256 is None:
            raise RunError("recovery resource plan binding is absent")
        try:
            current = hashlib.sha256(self.plan_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise RunError("recovery resource plan is unreadable") from exc
        if current != self.sha256:
            raise RunError("recovery resource plan binding drift")
        return {
            "schema": recovery_cleanup.PLAN_SCHEMA,
            "path": str(self.plan_path),
            "sha256": current,
        }

    def _ordered_resources(self) -> list[dict[str, Any]]:
        return sorted(
            (dict(row) for row in self._resources),
            key=lambda row: self._ORDER[
                str(row["role"]) if row["kind"] == "process" else str(row["kind"])
            ],
        )


@dataclass(frozen=True, slots=True)
class RunPaths:
    run_id: str
    durable: Path
    temporary: Path
    uds: Path
    recovery: RecoveryPlanCoordinator | None = None

    @classmethod
    def reserve(cls, run_id: str) -> RunPaths:
        _validate_run_id(run_id)
        expected_runs = ROOT / "var/dg13/runs"
        expected_tmp = ROOT / "var/dg13/tmp"
        if RUNS_ROOT.resolve(strict=False) != expected_runs.resolve(strict=False):
            raise RunError("durable run root drift")
        if TMP_ROOT.resolve(strict=False) != expected_tmp.resolve(strict=False):
            raise RunError("temporary run root drift")
        if not all(u0._is_cra_path(path) for path in (ROOT, RUNS_ROOT, TMP_ROOT)):
            raise RunError("durable and temporary roots must reside on /cra")
        RUNS_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        TMP_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        UDS_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        for root in (RUNS_ROOT, TMP_ROOT, UDS_ROOT):
            os.chmod(root, 0o700)
        durable = RUNS_ROOT / run_id
        temporary = TMP_ROOT / run_id
        uds = UDS_ROOT / _short_run_id(run_id)
        existing_plan = durable / recovery_cleanup.PLAN_NAME
        if existing_plan.is_file() or existing_plan.is_symlink():
            command = (
                f"{sys.executable} scripts/dg13u_u1_cleanup.py "
                f"--plan {existing_plan} --run-id {run_id} "
                "--env-file <ABSOLUTE_ENV_FILE> --execute-local"
            )
            raise RunError(f"run_id requires explicit recovery: {command}")
        if durable.exists() or temporary.exists() or uds.exists():
            raise RunError("run_id already owns a durable, temporary, or UDS path")
        try:
            durable.mkdir(mode=0o700, exist_ok=False)
            recovery = RecoveryPlanCoordinator(run_id, durable, temporary, uds)
            recovery.initialize()
            temporary.mkdir(mode=0o700, exist_ok=False)
            uds.mkdir(mode=0o700, exist_ok=False)
        except Exception as exc:
            raise RunError(
                "run path reservation failed; preserve the durable run directory "
                "and use its explicit recovery plan when present"
            ) from exc
        return cls(run_id, durable, temporary, uds, recovery)


class ResourceRegistry(resource_registry.ResourceRegistry):
    """Runner error facade over the generation-safe registry helper."""

    def __init__(
        self,
        run_id: str,
        recovery: RecoveryPlanCoordinator | None = None,
    ) -> None:
        try:
            super().__init__(run_id, recovery)
        except resource_registry.ResourceRegistryError as exc:
            raise RunError(str(exc)) from exc

    def register(self, handle: ResourceHandle) -> None:
        try:
            super().register(handle)
        except resource_registry.ResourceRegistryError as exc:
            raise RunError(str(exc)) from exc

    def register_process(
        self,
        role: str,
        pid: int,
        marker: str,
        cleanup: resource_registry.ProcessCleanup,
        absent: resource_registry.ProcessAbsent,
    ) -> ProcessGeneration:
        try:
            return super().register_process(role, pid, marker, cleanup, absent)
        except resource_registry.ResourceRegistryError as exc:
            raise RunError(str(exc)) from exc

    def replace_process(
        self,
        role: str,
        expected_pid: int,
        expected_marker: str,
        new_pid: int,
        new_marker: str,
        cleanup: resource_registry.ProcessCleanup,
        absent: resource_registry.ProcessAbsent,
    ) -> ProcessGeneration:
        try:
            return super().replace_process(
                role,
                expected_pid,
                expected_marker,
                new_pid,
                new_marker,
                cleanup,
                absent,
            )
        except resource_registry.ResourceRegistryError as exc:
            raise RunError(str(exc)) from exc

    def cleanup_all(self) -> dict[str, Any]:
        try:
            receipt = super().cleanup_all()
        except resource_registry.ResourceRegistryError as exc:
            raise RunError(str(exc)) from exc
        binding = receipt.get("recovery_plan")
        if (
            self.recovery is not None
            and isinstance(binding, dict)
            and binding.get("status") == "FAIL"
        ):
            try:
                observed_sha256 = hashlib.sha256(
                    self.recovery.plan_path.read_bytes()
                ).hexdigest()
            except OSError:
                observed_sha256 = None
            binding.update(
                {
                    "schema": recovery_cleanup.PLAN_SCHEMA,
                    "path": str(self.recovery.plan_path),
                    "expected_sha256": self.recovery.sha256,
                    "observed_sha256": observed_sha256,
                }
            )
        return receipt


@dataclass(frozen=True, slots=True)
class CompositionResult:
    status: TerminalStatus
    reason_code: str
    evidence: Mapping[str, Any]


class Composition(Protocol):
    def start(
        self, paths: RunPaths, case: CaseSpec, resources: ResourceRegistry
    ) -> CompositionResult: ...

    def readiness(self, paths: RunPaths, case: CaseSpec) -> CompositionResult: ...

    def smoke(self, paths: RunPaths, case: CaseSpec) -> CompositionResult: ...

    def reconciliation(self, paths: RunPaths, case: CaseSpec) -> CompositionResult: ...


class PendingLocalComposition:
    """Fail-visible seam until the fresh Runtime/Host/Worker launcher is integrated."""

    reason_code = "U1_LOCAL_COMPOSITION_DRIVER_PENDING"

    def start(
        self, paths: RunPaths, case: CaseSpec, resources: ResourceRegistry
    ) -> CompositionResult:
        del paths, case, resources
        return CompositionResult(TerminalStatus.NOT_RUN, self.reason_code, {})

    def readiness(self, paths: RunPaths, case: CaseSpec) -> CompositionResult:
        del paths, case
        return CompositionResult(TerminalStatus.NOT_RUN, self.reason_code, {})

    def smoke(self, paths: RunPaths, case: CaseSpec) -> CompositionResult:
        del paths, case
        return CompositionResult(TerminalStatus.NOT_RUN, self.reason_code, {})

    def reconciliation(self, paths: RunPaths, case: CaseSpec) -> CompositionResult:
        del paths, case
        return CompositionResult(TerminalStatus.NOT_RUN, self.reason_code, {})


def _process_marker(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    closing = raw.rfind(")")
    fields = raw[closing + 2 :].split() if closing >= 0 else []
    return fields[19] if len(fields) > 19 else None


def _stable_process_marker(pid: int) -> str:
    previous: str | None = None
    for _ in range(20):
        current = _process_marker(pid)
        if current is not None and current == previous:
            return current
        previous = current
        time.sleep(0.01)
    raise RunError("run-owned process start marker did not stabilize")


def _record_recovery_process(paths: RunPaths, role: str, pid: int, marker: str) -> None:
    if paths.recovery is not None:
        paths.recovery.record_process(role, pid, marker)


def _checkpoint_recovery(paths: RunPaths) -> None:
    if paths.recovery is not None:
        paths.recovery.checkpoint()


def _process_state(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    closing = raw.rfind(")")
    fields = raw[closing + 2 :].split() if closing >= 0 else []
    return fields[0] if fields else None


def _process_alive(pid: int, marker: str | None) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return _process_state(pid) != "Z" and (
        marker is None or _process_marker(pid) == marker
    )


def _terminate_exact_process(pid: int, marker: str | None) -> None:
    if not _process_alive(pid, marker):
        return
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not _process_alive(pid, marker):
            return
        time.sleep(0.05)
    if _process_alive(pid, marker):
        os.kill(pid, signal.SIGKILL)


def _terminate_owned_process(
    process: subprocess.Popen[bytes], marker: str | None
) -> None:
    """Terminate, reap, and verify one exact run-owned child process."""

    if not _process_alive(process.pid, marker):
        if process.poll() is not None:
            process.wait(timeout=1)
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if not _process_alive(process.pid, marker):
            process.wait(timeout=1)
            return
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise RunError("run-owned process did not exit after SIGKILL") from exc
    if _process_alive(process.pid, marker) or process.poll() is None:
        raise RunError("run-owned process cleanup did not reconcile")


@dataclass(frozen=True, slots=True)
class FreshRuntimeIdentity:
    database_name: str
    base_url: str
    api_pid: int
    api_marker: str | None
    worker_pid: int
    worker_marker: str | None
    migration_head: str

    def public(self) -> dict[str, Any]:
        return {
            "database_name_sha256": hashlib.sha256(
                self.database_name.encode()
            ).hexdigest(),
            "base_url": self.base_url,
            "api": {"pid": self.api_pid, "marker": self.api_marker},
            "worker": {"pid": self.worker_pid, "marker": self.worker_marker},
            "migration_head": self.migration_head,
            "database_lifecycle": "RUN_OWNED_FRESH",
        }


@dataclass(frozen=True, slots=True)
class FreshRuntimeRoleTokens:
    submitter_token: str
    reviewer_token: str
    operator_token: str


_PRODUCT_WHEELS = ("client", "mcp", "runtime", "openworker")
_PRODUCT_ENTRYPOINTS = (
    "milai-api",
    "milai-worker",
    "milai-mcp",
    "milai-mcp-broker",
    "milai-openworker-adapter",
)


def _run_product_command(
    command: list[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    log: Path,
    timeout: int = 300,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=dict(environment),
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunError(f"product command unavailable: {command[0]}") from exc
    output = completed.stdout + completed.stderr
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "ab") as handle:
        handle.write(output)
    receipt = {
        "argv_sha256": hashlib.sha256(u0._canonical_bytes(command)).hexdigest(),
        "exit_code": completed.returncode,
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
    }
    if completed.returncode != 0:
        raise RunError(
            f"product command failed with status {completed.returncode}: {command[0]}"
        )
    return {**receipt, "status": TerminalStatus.PASS}


def _product_wheel_inputs(
    paths: RunPaths, packages: Mapping[str, Any]
) -> dict[str, Path]:
    artifacts = packages.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise RunError("package artifact manifest is absent")
    wheels: dict[str, Path] = {}
    for name in _PRODUCT_WHEELS:
        row = artifacts.get(f"{name}_wheel")
        if not isinstance(row, Mapping) or not isinstance(row.get("path"), str):
            raise RunError(f"exact {name} wheel identity is absent")
        wheel = (paths.durable / str(row["path"])).resolve()
        if (
            not wheel.is_relative_to(paths.durable.resolve())
            or not wheel.is_file()
            or wheel.is_symlink()
        ):
            raise RunError(f"exact {name} wheel escaped the durable run root")
        observed_sha256 = u0._sha256_file(wheel)
        if row.get("sha256") != observed_sha256:
            raise RunError(f"exact {name} wheel digest drift")
        wheels[name] = wheel
    return wheels


def _owned_logs_directory(paths: RunPaths) -> Path:
    """Create or reuse the private durable log directory for one owned run."""

    logs = paths.durable / "logs"
    try:
        logs.mkdir(mode=0o700, exist_ok=True)
        observed = logs.lstat()
    except OSError as exc:
        raise RunError("run-owned log directory is unavailable") from exc
    if not stat.S_ISDIR(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
        raise RunError("run-owned log path is not a real directory")
    if stat.S_IMODE(observed.st_mode) != 0o700:
        raise RunError("run-owned log directory permissions are not 0700")
    return logs


def _build_product_venv(
    paths: RunPaths, packages: Mapping[str, Any], *, case_id: str
) -> tuple[Path, dict[str, Any]]:
    """Install the just-built exact wheels and their offline dependencies."""

    wheels = _product_wheel_inputs(paths, packages)
    product_venv = paths.temporary / "product-venv"
    install_tmp = paths.temporary / "product-install-tmp"
    install_tmp.mkdir(mode=0o700)
    uv_cache = paths.temporary / "uv-cache"
    if not uv_cache.is_dir() or uv_cache.is_symlink():
        raise RunError("run-owned offline dependency cache is absent")
    locked_wheels = LOCKED_UV_CACHE / "wheels-v5"
    if (
        not locked_wheels.is_dir()
        or locked_wheels.is_symlink()
        or stat.S_IMODE(locked_wheels.stat().st_mode) & 0o022
    ):
        raise RunError("locked offline dependency wheel index is absent or writable")
    locked_wheels_identity = u0._directory_identity(locked_wheels)
    environment = {
        **os.environ,
        "TMPDIR": str(install_tmp),
        "UV_CACHE_DIR": str(LOCKED_UV_CACHE),
        "UV_OFFLINE": "1",
        "UV_LINK_MODE": "copy",
    }
    logs = _owned_logs_directory(paths)
    install_log = logs / "product-install.log"
    receipts = [
        _run_product_command(
            [
                "uv",
                "venv",
                "--offline",
                "--python",
                str(ROOT / "runtime/.venv/bin/python"),
                str(product_venv),
            ],
            cwd=paths.temporary,
            environment=environment,
            log=install_log,
        )
    ]
    receipts.append(
        _run_product_command(
            [
                "uv",
                "pip",
                "install",
                "--offline",
                "--python",
                str(product_venv / "bin/python"),
                *(str(wheels[name]) for name in _PRODUCT_WHEELS),
            ],
            cwd=paths.temporary,
            environment=environment,
            log=install_log,
        )
    )
    installed = u0._installed_identity(product_venv)
    entrypoints: dict[str, Any] = {}
    for name in _PRODUCT_ENTRYPOINTS:
        executable = product_venv / "bin" / name
        if not executable.is_file() or executable.is_symlink():
            raise RunError(f"exact product entrypoint is absent: {name}")
        entrypoints[name] = u0._file_identity(executable, relative_to=paths.temporary)
    manifest = {
        "schema": "milai.dg13u.u1-exact-product-manifest.v1",
        "run_id": paths.run_id,
        "case_id": case_id,
        "status": TerminalStatus.PASS,
        "installation": "FRESH_RUN_OWNED_OFFLINE_FULL_DEPENDENCIES",
        "root": str(product_venv.relative_to(paths.temporary)),
        "environment": {
            "TMPDIR": str(install_tmp),
            "UV_BUILD_CACHE_DIR": str(uv_cache),
            "UV_DEPENDENCY_CACHE_DIR": str(LOCKED_UV_CACHE),
            "UV_OFFLINE": True,
            "UV_LINK_MODE": "copy",
            "product_and_tmp_on_run_owned_temporary_root": True,
            "dependency_cache_access": "PREEXISTING_LOCKED_OFFLINE_SOURCE",
            "locked_dependency_wheels": locked_wheels_identity,
        },
        "wheel_inputs": {
            name: u0._file_identity(wheel, relative_to=paths.durable)
            for name, wheel in wheels.items()
        },
        "installed": installed,
        "entrypoints": entrypoints,
        "command_receipts": receipts,
        "install_log": u0._file_identity(install_log, relative_to=paths.durable),
    }
    _atomic_write(paths.durable / "exact-product-manifest.json", manifest)
    return product_venv, manifest


class FreshRuntimeLifecycle:
    """Run-owned database/API/worker lifecycle using the current Runtime operations."""

    def __init__(
        self,
        paths: RunPaths,
        env_file: Path,
        migration_head: str,
        product_venv: Path,
    ) -> None:
        self.paths = paths
        self.env_file = env_file.resolve()
        self.migration_head = migration_head
        self.product_venv = product_venv
        self.owner_database_url: str | None = None
        self.database_name: str | None = None
        self.api_process: Any | None = None
        self.worker_process: Any | None = None
        self.identity: FreshRuntimeIdentity | None = None
        self.reader_token: str | None = None
        self.fixture_role_tokens: FreshRuntimeRoleTokens | None = None

    def start(self, resources: ResourceRegistry) -> FreshRuntimeIdentity:
        from uuid import uuid4

        from alembic import command
        from milai.config import load_settings
        from milai.config.settings import prepare_runtime_directories
        from milai.operations import load_runtime_environment
        from milai.operations.smoke import (
            _alembic_config,
            _api_environment,
            _create_database,
            _database_url,
            _free_loopback_port,
            _migration_url,
            _smoke_settings,
        )

        load_runtime_environment(self.env_file)
        source = load_settings()
        owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
        worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
        audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
        if not owner_source or not worker_source or not audit_source:
            raise RunError("fresh Runtime database-role URLs are absent")
        suffix = hashlib.sha256(self.paths.run_id.encode()).hexdigest()[:20]
        database_name = f"milai_smoke_dg13u_{suffix}"
        database_urls = {
            "owner": _database_url(owner_source, database_name),
            "api": _database_url(source.database_dsn, database_name),
            "steward": _database_url(source.steward_database_dsn, database_name),
            "worker": _database_url(worker_source, database_name),
            "audit": _database_url(audit_source, database_name),
        }
        self.owner_database_url = owner_source
        self.database_name = database_name
        _create_database(owner_source, database_name)
        resources.register(
            ResourceHandle(
                "database",
                f"postgres/{database_name}",
                ResourceOwnership.RUN_OWNED,
                cleanup=self._drop_database,
                absent=self._database_absent,
            )
        )
        _checkpoint_recovery(self.paths)
        with _migration_url(database_urls["owner"]):
            command.upgrade(_alembic_config(), "head")

        tokens = {
            name: secrets.token_urlsafe(48)
            for name in (
                "legacy",
                "causal",
                "reader",
                "submitter",
                "operator",
                "reviewer",
            )
        }
        self.reader_token = tokens["reader"]
        self.fixture_role_tokens = FreshRuntimeRoleTokens(
            tokens["submitter"], tokens["reviewer"], tokens["operator"]
        )
        blob_root = self.paths.temporary / "runtime-blobs"
        blob_root.mkdir(mode=0o700)
        settings = _smoke_settings(
            source,
            database_urls,
            blob_root,
            uuid4(),
            uuid4(),
            tokens,
            _free_loopback_port(),
        )
        prepare_runtime_directories(settings)
        environment = _api_environment(settings, database_urls, tokens)
        runtime_tmp = self.paths.temporary / "runtime-tmp"
        runtime_tmp.mkdir(mode=0o700)
        environment["TMPDIR"] = str(runtime_tmp)
        api_executable = self.product_venv / "bin/milai-api"
        worker_executable = self.product_venv / "bin/milai-worker"
        if not api_executable.is_file() or not worker_executable.is_file():
            raise RunError("Runtime API/worker entrypoints are absent")
        logs = _owned_logs_directory(self.paths)
        api_log = logs / "runtime-api.log"
        worker_log = logs / "runtime-worker.log"
        api_descriptor = os.open(api_log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(api_descriptor, "wb") as output:
            self.api_process = subprocess.Popen(
                [str(api_executable)],
                cwd=ROOT / "runtime",
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        api_marker = _stable_process_marker(self.api_process.pid)
        resources.register(
            ResourceHandle(
                "process",
                f"process/api:{self.api_process.pid}",
                ResourceOwnership.RUN_OWNED,
                cleanup=lambda: _terminate_owned_process(self.api_process, api_marker),
                absent=lambda: not _process_alive(self.api_process.pid, api_marker),
            )
        )
        _record_recovery_process(
            self.paths, "runtime-api", self.api_process.pid, api_marker
        )
        self._wait_api(f"http://{settings.bind_host}:{settings.bind_port}")
        worker_environment = dict(environment)
        worker_environment["MILAI_WORKER_DATABASE_URL"] = database_urls["worker"]
        worker_descriptor = os.open(
            worker_log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(worker_descriptor, "wb") as output:
            self.worker_process = subprocess.Popen(
                [str(worker_executable)],
                cwd=ROOT / "runtime",
                env=worker_environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        worker_marker = _stable_process_marker(self.worker_process.pid)
        resources.register(
            ResourceHandle(
                "process",
                f"process/worker:{self.worker_process.pid}",
                ResourceOwnership.RUN_OWNED,
                cleanup=lambda: _terminate_owned_process(
                    self.worker_process, worker_marker
                ),
                absent=lambda: (
                    not _process_alive(self.worker_process.pid, worker_marker)
                ),
            )
        )
        _record_recovery_process(
            self.paths, "runtime-worker", self.worker_process.pid, worker_marker
        )
        time.sleep(0.1)
        if self.worker_process.poll() is not None:
            raise RunError("fresh Runtime worker exited before readiness")
        self.identity = FreshRuntimeIdentity(
            database_name,
            f"http://{settings.bind_host}:{settings.bind_port}",
            self.api_process.pid,
            api_marker,
            self.worker_process.pid,
            worker_marker,
            self.migration_head,
        )
        return self.identity

    def ready(self) -> bool:
        if self.identity is None:
            return False
        if not _process_alive(
            self.identity.api_pid, self.identity.api_marker
        ) or not _process_alive(self.identity.worker_pid, self.identity.worker_marker):
            return False
        try:
            request = urllib.request.Request(self.identity.base_url + "/health/ready")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=2) as response:
                value = json.loads(response.read())
            return response.status == 200 and value.get("status") == "ready"
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return False

    def _wait_api(self, base_url: str) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.api_process is None or self.api_process.poll() is not None:
                raise RunError("fresh Runtime API exited before readiness")
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(base_url + "/health/ready", timeout=1) as response:
                    value = json.loads(response.read())
                if response.status == 200 and value.get("status") == "ready":
                    return
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(0.1)
        raise RunError("fresh Runtime API readiness timeout")

    def _drop_database(self) -> None:
        from milai.operations.smoke import _drop_database

        if self.owner_database_url is None or self.database_name is None:
            raise RunError("database cleanup identity is absent")
        result = _drop_database(self.owner_database_url, self.database_name)
        if result.get("status") != "PASS":
            raise RunError("fresh Runtime database cleanup failed")

    def _database_absent(self) -> bool:
        if self.owner_database_url is None or self.database_name is None:
            return False
        import psycopg

        with psycopg.connect(self.owner_database_url, connect_timeout=5) as connection:
            row = connection.execute(
                "SELECT count(*) FROM pg_database WHERE datname = %s",
                (self.database_name,),
            ).fetchone()
        return row is not None and int(row[0]) == 0


def _safe_process_environment(temporary: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(temporary),
    }


def _private_text(path: Path, value: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _command_bytes(
    command: list[str], *, timeout: int = 60, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunError(f"command unavailable: {command[0]}") from exc
    if len(completed.stdout) + len(completed.stderr) > 8 * 1024 * 1024:
        raise RunError(f"command output boundary exceeded: {command[0]}")
    if check and completed.returncode != 0:
        raise RunError(
            f"command failed with status {completed.returncode}: {command[0]}"
        )
    return completed


def _command_text(command: list[str], *, timeout: int = 60) -> str:
    completed = _command_bytes(command, timeout=timeout)
    try:
        return completed.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise RunError(f"command returned non-UTF-8 output: {command[0]}") from exc


def _docker_absent(kind: str, identity: str) -> bool:
    return (
        _command_bytes(
            ["docker", kind, "inspect", identity], timeout=15, check=False
        ).returncode
        != 0
    )


def _docker_remove_container(name: str) -> None:
    if not _docker_absent("container", name):
        _command_bytes(["docker", "rm", "-f", name], timeout=30)


def _docker_remove_network(name: str) -> None:
    if not _docker_absent("network", name):
        _command_bytes(["docker", "network", "rm", name], timeout=30)


def _free_bind_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])


def _wait_http_json(
    url: str, *, token: str | None = None, seconds: int = 30
) -> Mapping[str, Any]:
    deadline = time.monotonic() + seconds
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        request = urllib.request.Request(url, headers=headers)
        try:
            with opener.open(request, timeout=2) as response:
                value = json.loads(response.read())
            if response.status == 200 and isinstance(value, Mapping):
                return value
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    raise RunError(f"HTTP readiness timeout: {url.rsplit('/', 1)[-1]}")


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RunError(f"invalid JSONL artifact: {path.name}") from exc
        if not isinstance(value, dict):
            raise RunError(f"non-object JSONL artifact: {path.name}")
        rows.append(value)
    return rows


def _nonnegative_measured_ms(value: object) -> float:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) >= 0
    ):
        return round(float(value), 3)
    return 0.0


def _durable_payload_observed(
    root: Path,
    values: Sequence[bytes],
    *,
    minimum_needle_bytes: int = 32,
) -> bool:
    if minimum_needle_bytes < 1:
        raise ValueError("minimum_needle_bytes must be positive")
    needles = tuple(value for value in values if len(value) >= minimum_needle_bytes)
    if not needles:
        return False
    for artifact in root.rglob("*"):
        if (
            artifact.is_file()
            and not artifact.is_symlink()
            and artifact.suffix in {".json", ".jsonl", ".log"}
        ):
            raw = artifact.read_bytes()
            if any(needle in raw for needle in needles):
                return True
    return False


_OPENCODE_SENSITIVE_BODY_KEYS = frozenset(
    {
        "argument",
        "arguments",
        "args",
        "content",
        "input",
        "output",
        "result",
        "text",
    }
)


def _opencode_sensitive_payload_needles(
    raw: bytes,
    *,
    fixture_markers: Sequence[bytes] = (),
) -> tuple[bytes, ...]:
    """Extract raw body leaves in memory without returning structural metadata."""

    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise RunError("OpenCode payload scan input is not UTF-8") from exc

    needles = {marker for marker in fixture_markers if marker}

    def collect(value: object, *, sensitive: bool) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                key_is_sensitive = (
                    isinstance(key, str)
                    and key.casefold() in _OPENCODE_SENSITIVE_BODY_KEYS
                )
                collect(item, sensitive=sensitive or key_is_sensitive)
            return
        if isinstance(value, list):
            for item in value:
                collect(item, sensitive=sensitive)
            return
        if sensitive and isinstance(value, str) and value:
            needles.add(value.encode("utf-8"))

    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RunError("OpenCode payload scan input is not strict JSONL") from exc
        if not isinstance(event, Mapping):
            raise RunError("OpenCode payload scan event is not an object")
        collect(event, sensitive=False)
    return tuple(sorted(needles))


def _ansi_stripped_text(raw: bytes) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", raw.decode("utf-8", "replace"))


def _redact_diagnostic_text(text: str, redactions: Sequence[str]) -> str:
    for value in sorted((item for item in redactions if item), key=len, reverse=True):
        text = text.replace(value, "<redacted>")
    text = re.sub(r"(?i)\bbearer\s+[^\s,;]+", "Bearer <redacted>", text)
    text = re.sub(
        r"(?i)\b(authorization|api[_-]?key|token|password)\b\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        text,
    )
    text = re.sub(r"\b[A-Z][A-Z0-9_]{2,}=[^\s,;]+", "ENV=<redacted>", text)
    text = re.sub(r"(?<![A-Za-z0-9])/(?:[^\s\x00\"']+)", "<path>", text)
    text = re.sub(
        r"(?i)\b(?:session|message|task)(?:[_-]?id)?\b\s*[:=]\s*[^\s,;]+",
        "id=<redacted>",
        text,
    )
    text = re.sub(r"\b(?:ses|msg|task)_[A-Za-z0-9_-]+\b", "<id>", text)
    text = re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "<redacted>", text)
    return text


def _bounded_redacted_diagnostic(
    raw: bytes, *, redactions: Sequence[str] = (), limit: int = 16 * 1024
) -> dict[str, Any]:
    """Return a bounded diagnostic excerpt without credentials, prompts, or paths."""

    text = _redact_diagnostic_text(_ansi_stripped_text(raw), redactions)
    encoded = text.encode("utf-8")
    bounded = encoded[:limit]
    excerpt = bounded.decode("utf-8", "ignore")
    return {
        "observed_bytes": len(raw),
        "observed_sha256": hashlib.sha256(raw).hexdigest(),
        "observed_line_count": len(text.splitlines()),
        "excerpt": excerpt,
        "excerpt_bytes": len(excerpt.encode("utf-8")),
        "truncated": len(encoded) > limit,
    }


def _allowlisted_mcp_diagnostic(
    ansi_stripped_text: str,
    *,
    redactions: Sequence[str],
    limit: int = 12 * 1024,
) -> dict[str, Any]:
    text = _redact_diagnostic_text(ansi_stripped_text, redactions)
    allowed = re.compile(
        r"(?i)\b(mcp|milai|connected|disconnected|error|failed|timeout|"
        r"unavailable|overload|connection|socket|limit|closed|refused)\b"
    )
    lines = [line.strip() for line in text.splitlines() if allowed.search(line)]
    encoded = "\n".join(lines).encode("utf-8")
    bounded = encoded[:limit]
    excerpt = bounded.decode("utf-8", "ignore")
    return {
        "text": excerpt,
        "bytes": len(excerpt.encode("utf-8")),
        "line_count": len(lines),
        "truncated": len(encoded) > limit,
    }


def _allowlisted_smoke_command_diagnostic(
    ansi_stripped_text: str,
    *,
    redactions: Sequence[str],
    limit: int = 12 * 1024,
) -> dict[str, Any]:
    text = _redact_diagnostic_text(ansi_stripped_text, redactions)
    allowed = re.compile(
        r"(?i)\b(error|failed|failure|invalid|exceed(?:s|ed)?|reservation|"
        r"budget|unsupported|forbidden|timeout|refused|unavailable|closed|"
        r"terminated|exit)\b"
    )
    lines = [line.strip() for line in text.splitlines() if allowed.search(line)]
    encoded = "\n".join(lines).encode("utf-8")
    bounded = encoded[:limit]
    excerpt = bounded.decode("utf-8", "ignore")
    return {
        "retention": "ERROR_STATUS_ALLOWLIST_ONLY",
        "text": excerpt,
        "bytes": len(excerpt.encode("utf-8")),
        "line_count": len(lines),
        "truncated": len(encoded) > limit,
    }


def _top_level_opencode_typed_error_lines(ansi_stripped_stdout: str) -> list[str]:
    """Select only strict JSONL objects whose top-level type is exactly error."""

    typed_errors: list[str] = []
    for line in ansi_stripped_stdout.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("type") == "error":
            typed_errors.append(line)
    return typed_errors


def _none_prompt(case: CaseSpec) -> str:
    if case.case_id == "U1-NONE-EN":
        return "Reply with one short greeting for a synthetic local connectivity check."
    if case.case_id == "U1-NONE-CN":
        return "请为本地合成连通性检查回复一句简短问候。"
    raise RunError("the implemented real smoke is limited to U1 NONE cases")


def _exact_prompt(case: CaseSpec) -> str:
    prompts = {
        "U1-EXACT-TARGET-EN": "What is the current release target for orchid-release?",
        "U1-EXACT-TARGET-CN": "orchid-release 的当前发布目标是什么？",
        "U1-EXACT-DATABASE-EN": "What is the current release database for orchid-release?",
        "U1-EXACT-DATABASE-CN": "orchid-release 的当前发布数据库是什么？",
        "U1-EXACT-DECISION-EN": (
            "What is the current governed release decision for orchid-release?"
        ),
        "U1-EXACT-DECISION-CN": "orchid-release 的当前受治理的发布决定是什么？",
    }
    try:
        return prompts[case.case_id]
    except KeyError as exc:
        raise RunError("the implemented exact prompt is absent") from exc


def _task_turn_prompt(
    case: CaseSpec,
    turn: task_scenarios.TurnSpec,
) -> str:
    if case.case_id not in _TASK_CASE_IDS:
        raise RunError("task prompt requested for a non-task case")
    prefixes = {
        "A-NEW": "Start native task session A and",
        "A-CONTINUE": "Continue native task session A and",
        "B-NEW": "Start independent native task session B and",
        "A-RETURN": "Return to native task session A and",
    }
    try:
        prefix = prefixes[turn.turn_id]
    except KeyError as exc:
        raise RunError("task turn prompt is absent") from exc
    return f"{prefix} state the current release target for orchid-release."


def _task_prompts(case: CaseSpec) -> tuple[str, ...]:
    try:
        scenario = task_scenarios.scenario_for_case(case.case_id)
    except task_scenarios.TaskScenarioError as exc:
        raise RunError("task scenario is unavailable") from exc
    return tuple(_task_turn_prompt(case, turn) for turn in scenario.turns)


def _cache_governance_prompt(case: CaseSpec) -> str:
    try:
        scenario = cache_governance.scenario_for_case(case.case_id)
    except cache_governance.ScenarioContractError as exc:
        raise RunError("cache/governance scenario is unavailable") from exc
    prompts = {
        "release.target": "What is the current release target for orchid-release?",
        "release.database": (
            "What is the current release database for orchid-release?"
        ),
        "release.decision": (
            "What is the current governed release decision for orchid-release?"
        ),
        None: "Verify the synthetic local cache/governance negative boundary.",
    }
    return prompts[scenario.requested_state_key]


def _case_prompt(case: CaseSpec) -> str:
    if case.case_id in _INTERACTION_CASE_IDS:
        try:
            return interaction_scenarios.interaction_prompt(case.case_id)
        except interaction_scenarios.InteractionScenarioError as exc:
            raise RunError("interaction prompt is unavailable") from exc
    if case.case_id in _TASK_CASE_IDS:
        return "\n".join(_task_prompts(case))
    if case.case_id in _CACHE_GOVERNANCE_CASE_IDS:
        return _cache_governance_prompt(case)
    if case.case_id in _FAULT_CASE_IDS:
        return (
            "Reply with one short greeting for a synthetic local connectivity check."
            if case.case_id.startswith("U1-PROVIDER-")
            else "What is the current release target for orchid-release?"
        )
    if case.case_id in _LIFECYCLE_CASE_IDS:
        return "What is the current release target for orchid-release?"
    if case.memory_requirement == "NONE":
        return _none_prompt(case)
    return _exact_prompt(case)


def _case_prompt_redactions(case: CaseSpec) -> tuple[str, ...]:
    if case.case_id in _TASK_CASE_IDS:
        return _task_prompts(case)
    return (_case_prompt(case),)


def _provider_capability(
    paths: RunPaths,
    case: CaseSpec,
    prompt: str,
    *,
    endpoint_identity: str = VLLM_ORIGIN,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    provider_turns = max(1, case.expected_provider_calls)
    return {
        "schema": "milai.provider.dev-run.v1",
        "run_id": paths.run_id,
        "phase": "smoke",
        "provider": "local_vllm",
        "endpoint_identity": endpoint_identity,
        "model_id": MODEL_ID,
        "dataset_manifest_sha256": _bound_identity(CANDIDATE_FIXTURE)["sha256"],
        "prompt_template_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "max_native_requests": provider_turns,
        "max_prompt_tokens": _PROVIDER_PROMPT_TOKENS_PER_TURN * provider_turns,
        "max_completion_tokens": _PROVIDER_COMPLETION_TOKENS_PER_TURN * provider_turns,
        "deadline": (current + timedelta(minutes=30))
        .isoformat()
        .replace("+00:00", "Z"),
        "expires_at": (current + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
    }


def _fault_broker_policy(
    *,
    socket_path: Path,
    base_url: str,
    mcp_executable: Path,
) -> dict[str, Any]:
    if socket_path.name != "reader-lite.sock":
        raise RunError("fault broker socket basename is invalid")
    if not mcp_executable.is_file() or mcp_executable.is_symlink():
        raise RunError("fault broker MCP executable is absent")
    return {
        "allowed_peer_uids": [os.geteuid()],
        "base_url": base_url,
        "child_shutdown_seconds": 5,
        "consistency_floor": "CANONICAL_REQUIRED",
        "max_connections": 1,
        "max_limit": 3,
        "mcp_max_retries": 0,
        "mcp_executable": str(mcp_executable),
        "mcp_executable_sha256": u0._sha256_file(mcp_executable),
        "profile": "reader-lite",
        "required_authority": "INFORMATIONAL",
        "schema": "milai.openworker.mcp-broker-policy.v1",
        "scope": {"project_ids": ["orchid-release"]},
        "socket_mode": "0600",
        "socket_path": str(socket_path),
    }


def _load_exact_product_broker_module(product_venv: Path) -> Any:
    module_path = (
        product_venv
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages/milai_openworker_mcp/broker.py"
    )
    if not module_path.is_file() or module_path.is_symlink():
        raise RunError("exact product broker module is absent")
    digest = u0._sha256_file(module_path)
    module_name = f"_dg13u_u1_product_broker_{digest[:16]}"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RunError("exact product broker module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise RunError("exact product broker module load failed") from exc
    return module


class _RunOwnedBrokerThread:
    """Runs an exact-wheel Broker in this runner so crash cleanup owns no extra PID."""

    def __init__(
        self,
        product_venv: Path,
        policy_path: Path,
        token: str,
    ) -> None:
        module = _load_exact_product_broker_module(product_venv)
        try:
            policy = module.Policy.load(policy_path)
            self._broker = module.Broker(policy, token)
        except Exception as exc:
            raise RunError("fault broker policy load failed") from exc
        self.socket_path = policy.socket_path
        self._failure: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"dg13u-u1-fault-broker-{hashlib.sha256(str(self.socket_path).encode()).hexdigest()[:12]}",
            daemon=False,
        )

    def _run(self) -> None:
        try:
            self._broker.run()
        except BaseException as exc:  # noqa: BLE001 - surfaced by readiness/cleanup
            self._failure = exc

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self._failure is not None:
                raise RunError(
                    "fault broker exited before readiness"
                ) from self._failure
            if self.socket_path.exists():
                current = self.socket_path.lstat()
                if (
                    not stat.S_ISSOCK(current.st_mode)
                    or stat.S_IMODE(current.st_mode) != 0o600
                ):
                    raise RunError("fault broker socket identity is invalid")
                return
            if not self._thread.is_alive():
                raise RunError("fault broker exited before readiness")
            time.sleep(0.05)
        raise RunError("fault broker readiness timeout")

    def stop(self) -> None:
        self._broker.stop()
        if self._thread.ident is not None:
            self._thread.join(timeout=7)
        if self._thread.is_alive():
            raise RunError("fault broker thread did not stop")
        if self._failure is not None:
            raise RunError("fault broker terminated with an error") from self._failure

    def absent(self) -> bool:
        return not self._thread.is_alive() and not self.socket_path.exists()


def _opencode_fault_command_accounting(
    plan: fault_execution.FaultExecutionPlan,
    *,
    completed: subprocess.CompletedProcess[bytes],
    command_truth: SmokeCommandTruth,
) -> dict[str, Any]:
    try:
        lines = completed.stdout.decode("utf-8", errors="strict").splitlines()
    except UnicodeError as exc:
        raise RunError("fault OpenCode output is not UTF-8") from exc
    events: list[Mapping[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RunError("fault OpenCode output is not strict JSONL") from exc
        if not isinstance(event, Mapping):
            raise RunError("fault OpenCode event is not an object")
        events.append(event)
    successful_texts = [
        part["text"]
        for event in events
        if event.get("type") == "text"
        and isinstance((part := event.get("part")), Mapping)
        and isinstance(part.get("text"), str)
        and part["text"].strip()
    ]
    provider_case = plan.case_id.startswith("U1-PROVIDER-")
    if provider_case:
        if (
            command_truth.status != TerminalStatus.FAIL
            or command_truth.typed_error_count != 1
            or successful_texts
        ):
            raise RunError("provider fault OpenCode typed terminal drifted")
        return {
            "opencode_typed_error_count": 1,
            "opencode_success_text_count": 0,
            "opencode_memory_terminal_sha256": None,
        }
    if (
        command_truth.status != TerminalStatus.PASS
        or command_truth.exit_code != 0
        or command_truth.typed_error_count != 0
    ):
        raise RunError("memory fault OpenCode terminal drifted")
    expected = plan.expected_terminal
    terminal_summaries: list[dict[str, Any]] = []
    for text in successful_texts:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, Mapping):
            continue
        if set(value) != {
            "answer",
            "status",
            "memory_used",
            "memory_outcome",
            "execution_action",
            "provider_execution",
            "terminal_stage",
            "reason_code",
            "trace_id",
        }:
            continue
        summary = {
            "access_status": value.get("status"),
            "execution_action": value.get("execution_action"),
            "provider_execution": value.get("provider_execution"),
            "terminal_stage": value.get("terminal_stage"),
            "reason_code": value.get("reason_code"),
            "memory_used": value.get("memory_used"),
        }
        if (
            summary["access_status"] == "MEMORY_REQUIRED_BUT_UNAVAILABLE"
            and value.get("answer") == "UNKNOWN"
            and value.get("memory_outcome") == summary["access_status"]
            and isinstance(value.get("trace_id"), str)
            and bool(str(value["trace_id"]).strip())
        ):
            terminal_summaries.append(summary)
    exact_summary = {
        "access_status": expected.access_status,
        "execution_action": expected.execution_action,
        "provider_execution": expected.provider_execution,
        "terminal_stage": expected.terminal_stage,
        "reason_code": expected.reason_code,
        "memory_used": False,
    }
    if len(successful_texts) != 1 or terminal_summaries != [exact_summary]:
        raise RunError("memory fault OpenCode typed completion drifted")
    return {
        "opencode_typed_error_count": 0,
        "opencode_success_text_count": len(successful_texts),
        "opencode_memory_terminal_sha256": hashlib.sha256(
            u0._canonical_bytes(exact_summary)
        ).hexdigest(),
    }


def _is_exact_openworker_bootstrap_terminal(row: Mapping[str, Any]) -> bool:
    """Identify the bounded pre-warm rejection emitted outside a task operation."""

    return dict(row) == {
        "event": "HOST_INGRESS_TERMINAL",
        "exception_type": "OpenWorkerAdapterError",
        "http_status": 400,
        "reason_code": "PROVIDER_REQUEST_UNSUPPORTED",
    }


def _fault_trace_accounting(
    plan: fault_execution.FaultExecutionPlan,
    *,
    trace: Sequence[Mapping[str, Any]],
    ledger: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Reduce only observed Host/ledger facts; the frozen helper validates totals."""

    attempts = [row for row in trace if row.get("event") == "HOST_MCP_PREPARE_ATTEMPT"]
    prepares = [row for row in trace if row.get("event") == "HOST_MCP_PREPARE_CONTEXT"]
    prefetch_failures = [
        row for row in trace if row.get("event") == "HOST_MCP_PREFETCH_FAILED"
    ]
    reservations = [row for row in ledger if row.get("event") == "RESERVED"]
    provider_terminals = [
        row for row in ledger if row.get("event") == "PROVIDER_TERMINAL"
    ]
    ingress_terminals = [
        row
        for row in trace
        if row.get("event") == "HOST_INGRESS_TERMINAL"
        and not _is_exact_openworker_bootstrap_terminal(row)
    ]
    post_terminals = [
        row for row in ledger if row.get("event") == "POST_PROVIDER_TERMINAL"
    ]
    provider_success_trace = [
        row
        for row in trace
        if row.get("event") in {"PROVIDER_ANSWER", "PROVIDER_MEMORY_TOOL_VISIBLE"}
    ]
    logical_mcp_calls = sum(
        int(row.get("logical_mcp_calls", 0))
        for row in attempts
        if isinstance(row.get("logical_mcp_calls"), int)
        and not isinstance(row.get("logical_mcp_calls"), bool)
    )
    if logical_mcp_calls != len(attempts):
        raise RunError("fault MCP attempt ledger is malformed")
    if logical_mcp_calls != plan.expected_mcp_calls:
        raise RunError("fault MCP attempt count drifted")

    expected = plan.expected_terminal
    provider_fault_case = plan.case_id.startswith("U1-PROVIDER-")
    terminal_row: Mapping[str, Any]
    outcome: Mapping[str, Any] | None = None
    if provider_fault_case:
        if attempts or prepares or prefetch_failures:
            raise RunError("provider fault crossed the MCP barrier")
        if provider_success_trace:
            raise RunError("provider fault emitted an unexpected success trace")
        if len(ingress_terminals) != 1:
            raise RunError("provider fault Host terminal is absent or duplicated")
        terminal_row = ingress_terminals[0]
        if (
            terminal_row.get("reason_code") != expected.reason_code
            or terminal_row.get("http_status") != expected.http_status
        ):
            raise RunError("provider fault Host terminal drifted")
    else:
        if ingress_terminals:
            raise RunError("memory fault emitted an unexpected ingress terminal")
        # The exact production assembly wraps the MCP client with the task
        # memory controller.  It converts transport failures into a typed
        # TaskPreparedContext, so every memory fault must terminate through
        # HOST_MCP_PREPARE_CONTEXT.  PREFETCH_FAILED would mean that the
        # controller/bridge was bypassed or the source assembly drifted.
        if len(prepares) != 1 or prefetch_failures:
            raise RunError("memory fault terminal trace is absent or ambiguous")
        terminal_row = prepares[0]
        attempt_trace_id = attempts[0].get("attempt_trace_id")
        if (
            not isinstance(attempt_trace_id, str)
            or not attempt_trace_id.strip()
            or terminal_row.get("attempt_trace_id") != attempt_trace_id
        ):
            raise RunError("memory fault terminal attempt identity drifted")
        candidate = terminal_row.get("access_outcome")
        if not isinstance(candidate, Mapping):
            raise RunError("memory fault access outcome is absent")
        if (
            set(candidate)
            != {
                "status",
                "execution_action",
                "provider_execution",
                "terminal_stage",
                "context_digest",
                "canonical_position",
                "reason_code",
                "trace_id",
            }
            or candidate.get("context_digest") is not None
            or candidate.get("canonical_position") is not None
            or not isinstance(candidate.get("trace_id"), str)
            or not str(candidate["trace_id"]).strip()
        ):
            raise RunError("memory fault typed access outcome shape drifted")
        outcome = candidate
        observed_outcome = {
            "access_status": candidate.get("status"),
            "execution_action": candidate.get("execution_action"),
            "provider_execution": candidate.get("provider_execution"),
            "terminal_stage": candidate.get("terminal_stage"),
            "reason_code": candidate.get("reason_code"),
        }
        if observed_outcome != {
            "access_status": expected.access_status,
            "execution_action": expected.execution_action,
            "provider_execution": expected.provider_execution,
            "terminal_stage": expected.terminal_stage,
            "reason_code": expected.reason_code,
        }:
            raise RunError("memory fault typed access outcome drifted")

    if provider_fault_case:
        event_sequence = [row.get("event") for row in ledger]
        if (
            event_sequence != ["RESERVED", "PROVIDER_TERMINAL"]
            or len(reservations) != 1
            or len(provider_terminals) != 1
        ):
            raise RunError("provider fault reservation count drifted")
        provider_terminal = provider_terminals[0]
        logical_request_id = reservations[0].get("logical_request_id")
        if (
            not isinstance(logical_request_id, str)
            or not logical_request_id.strip()
            or provider_terminal.get("logical_request_id") != logical_request_id
            or provider_terminal.get("status") != "FAILED"
            or provider_terminal.get("reason_code") != expected.reason_code
            or not isinstance(provider_terminal.get("request_started"), bool)
            or not isinstance(provider_terminal.get("native_request_observed"), bool)
        ):
            raise RunError("provider fault terminal ledger drifted")
        provider_barrier = "ALLOWED_ONCE"
        native_request_id = provider_terminal.get("native_request_id")
        provider_terminal_observation: dict[str, Any] | None = {
            "event_sequence": [str(row["event"]) for row in ledger],
            "logical_reservations": len(reservations),
            "logical_request_id_sha256": hashlib.sha256(
                logical_request_id.encode()
            ).hexdigest(),
            "terminal_status": provider_terminal.get("status"),
            "reason_code": provider_terminal.get("reason_code"),
            "request_started": provider_terminal.get("request_started"),
            "native_request_observed": provider_terminal.get("native_request_observed"),
            "native_request_id_sha256": (
                hashlib.sha256(native_request_id.encode()).hexdigest()
                if isinstance(native_request_id, str)
                else None
            ),
            "prompt_tokens": provider_terminal.get("prompt_tokens"),
            "completion_tokens": provider_terminal.get("completion_tokens"),
            "post_terminal_count": len(post_terminals),
            "automatic_retries": 0,
        }
    else:
        if ledger or provider_success_trace:
            raise RunError("memory fault provider barrier was crossed")
        provider_terminal = {}
        provider_barrier = "BLOCKED"
        provider_terminal_observation = None

    return {
        "host_terminal": asdict(expected),
        "ledger_calls": {
            "mcp": logical_mcp_calls,
            "provider": len(reservations),
        },
        "provider_barrier": provider_barrier,
        "mcp_attempt_count": len(attempts),
        "mcp_terminal_event": terminal_row.get("event"),
        "access_outcome_sha256": (
            hashlib.sha256(u0._canonical_bytes(outcome)).hexdigest()
            if outcome is not None
            else None
        ),
        "provider_terminal_status": provider_terminal.get("status"),
        "provider_terminal_reason_code": provider_terminal.get("reason_code"),
        "provider_request_started": provider_terminal.get("request_started"),
        "provider_native_request_observed": provider_terminal.get(
            "native_request_observed"
        ),
        "provider_native_request_id": provider_terminal.get("native_request_id"),
        "provider_terminal_observation": provider_terminal_observation,
    }


def _fixture_options_for_case(case_id: str) -> FixtureOptions | None:
    """Return the exact controlled fixture setup required by one selector."""

    if case_id in {"U1-AUTHORITY-ESCALATION", "U1-ALIAS-COLLISION"}:
        return None
    if case_id == "U1-WRONG-SCOPE":
        return FixtureOptions(wrong_scope=True)
    if case_id == "U1-REVOKE-REENTRY":
        return FixtureOptions(revoke=True)
    if case_id == "U1-OPEN-ISSUE":
        return FixtureOptions(open_issue=True)
    if case_id in _CACHE_GOVERNANCE_CASE_IDS:
        return FixtureOptions()
    if case_id in _CANONICAL_POSITIVE_CASES:
        return FixtureOptions()
    return None


_CANONICAL_POSITIVE_CASES = frozenset(
    {
        "U1-EXACT-TARGET-EN",
        "U1-EXACT-TARGET-CN",
        "U1-EXACT-DATABASE-EN",
        "U1-EXACT-DATABASE-CN",
        "U1-EXACT-DECISION-EN",
        "U1-EXACT-DECISION-CN",
        *(
            _CACHE_GOVERNANCE_CASE_IDS
            - {"U1-AUTHORITY-ESCALATION", "U1-ALIAS-COLLISION"}
        ),
        *_TASK_CASE_IDS,
        "U1-STREAM",
        "U1-ADAPTER-RESTART",
    }
)


def _redact_fixture_receipt(value: object) -> object:
    identifier_fields = {
        "evidence_id",
        "claim_id",
        "claim_version_id",
        "prior_claim_version_id",
        "current_claim_version_id",
        "proposal_id",
        "outbox_id",
        "open_issue_id",
        "deletion_request_id",
        "conflicting_evidence_id",
        "head_claim_version_id",
        "supporting_evidence_id",
    }
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name in identifier_fields:
                redacted[f"{name}_sha256"] = (
                    hashlib.sha256(item.encode()).hexdigest()
                    if isinstance(item, str)
                    else None
                )
            else:
                redacted[name] = _redact_fixture_receipt(item)
        return redacted
    if isinstance(value, list):
        return [_redact_fixture_receipt(item) for item in value]
    return value


class CanonicalFixtureLifecycle:
    """Seeds and then controlled-revokes one fresh Runtime's canonical fixture."""

    def __init__(
        self,
        paths: RunPaths,
        runtime: FreshRuntimeLifecycle,
        options: FixtureOptions | None = None,
    ) -> None:
        if runtime.identity is None or runtime.fixture_role_tokens is None:
            raise RunError("fresh Runtime fixture writer identity is absent")
        self.paths = paths
        self.runtime = runtime
        self.options = options or FixtureOptions()
        self.fixture_run_id = (
            "u1-" + hashlib.sha256(paths.run_id.encode()).hexdigest()[:28]
        )
        tokens = runtime.fixture_role_tokens
        self.writer = LoopbackRuntimeFixtureWriter(
            runtime.identity.base_url,
            submitter_token=tokens.submitter_token,
            reviewer_token=tokens.reviewer_token,
            operator_token=tokens.operator_token,
        )
        self.seeded: Mapping[str, Any] | None = None
        self.seeded_snapshot: Mapping[str, Any] | None = None
        self.cleanup_receipt: Mapping[str, Any] | None = None
        self._cleanup_complete = False

    def start(self, resources: ResourceRegistry) -> Mapping[str, Any]:
        resources.register(
            ResourceHandle(
                "canonical_fixture",
                "canonical_fixture/"
                + hashlib.sha256(self.fixture_run_id.encode()).hexdigest()[:24],
                ResourceOwnership.RUN_OWNED,
                cleanup=self.cleanup,
                absent=lambda: self._cleanup_complete,
            )
        )
        try:
            self.seeded = seed_u1_canonical_fixture(
                self.writer,
                run_id=self.fixture_run_id,
                observed_at=_now(),
                options=self.options,
            )
        except FixtureSeedError as exc:
            mutations = list(exc.partial_receipt.get("mutations") or [])
            self.seeded = {
                "schema": "milai.dg13u.u1-canonical-fixture.v1",
                "status": "PARTIAL",
                "run_id_sha256": hashlib.sha256(
                    self.fixture_run_id.encode()
                ).hexdigest(),
                "mutations": mutations,
            }
            _atomic_write(
                self.paths.durable / "canonical-fixture-partial.json",
                _redact_fixture_receipt(exc.partial_receipt),
            )
            raise RunError(
                "canonical fixture seed failed after partial mutation"
            ) from exc
        self.seeded_snapshot = copy.deepcopy(self.seeded)
        redacted = _redact_fixture_receipt(self.seeded)
        assert isinstance(redacted, Mapping)
        _atomic_write(self.paths.durable / "canonical-fixture.json", redacted)
        return redacted

    def apply_post_warm_state_change(self) -> dict[str, Any]:
        """Apply the frozen live mutation without changing prior seed evidence."""

        if self.seeded is None or self.seeded_snapshot is None:
            raise RunError("canonical fixture is not seeded for live mutation")
        before = copy.deepcopy(self.seeded)
        updated = apply_u1_state_change(
            self.writer,
            self.seeded,
            run_id=self.fixture_run_id,
            observed_at=_now(),
        )
        if self.seeded != before or self.seeded_snapshot != before:
            raise RunError("post-warm mutation changed the prior seeded receipt")
        negative_setups = updated.get("negative_setups")
        state_change = (
            negative_setups.get("state_change")
            if isinstance(negative_setups, Mapping)
            else None
        )
        if not isinstance(state_change, Mapping):
            raise RunError("post-warm mutation receipt is absent")
        redacted = _redact_fixture_receipt(state_change)
        assert isinstance(redacted, Mapping)
        receipt_sha256 = hashlib.sha256(u0._canonical_bytes(redacted)).hexdigest()
        artifact = {
            "schema": "milai.dg13u.u1-post-warm-mutation.v1",
            "status": "MUTATED",
            "run_id_sha256": hashlib.sha256(self.fixture_run_id.encode()).hexdigest(),
            "seeded_snapshot_sha256": hashlib.sha256(
                u0._canonical_bytes(_redact_fixture_receipt(before))
            ).hexdigest(),
            "mutation_receipt_sha256": receipt_sha256,
            "state_change": redacted,
            "seeded_snapshot_unchanged": True,
        }
        self.seeded = updated
        _atomic_write(
            self.paths.durable / "canonical-fixture-post-warm-mutation.json",
            artifact,
        )
        return {
            "mutation_receipt_sha256": receipt_sha256,
            "seeded_snapshot_unchanged": True,
            "artifact_sha256": u0._sha256_file(
                self.paths.durable / "canonical-fixture-post-warm-mutation.json"
            ),
        }

    def cleanup(self) -> None:
        if self.seeded is None:
            self._cleanup_complete = True
            return
        mutations = self.seeded.get("mutations")
        evidence_count = (
            sum(
                item.get("kind") == "EVIDENCE_CAPTURE"
                for item in mutations
                if isinstance(item, Mapping)
            )
            if isinstance(mutations, list)
            else 0
        )
        already_revoked_count = (
            sum(
                item.get("kind") == "EVIDENCE_REVOKE"
                for item in mutations
                if isinstance(item, Mapping)
            )
            if isinstance(mutations, list)
            else 0
        )
        if evidence_count == 0:
            self._cleanup_complete = True
            return
        self.cleanup_receipt = cleanup_u1_canonical_fixture(
            self.writer,
            self.seeded,
            run_id=self.fixture_run_id,
        )
        if (
            self.cleanup_receipt.get("status") != "CLEANUP_REQUESTED"
            or self.cleanup_receipt.get("evidence_revocations")
            != evidence_count - already_revoked_count
        ):
            raise RunError("canonical fixture controlled cleanup failed")
        redacted = _redact_fixture_receipt(self.cleanup_receipt)
        assert isinstance(redacted, Mapping)
        _atomic_write(self.paths.durable / "canonical-fixture-cleanup.json", redacted)
        self._cleanup_complete = True


class CacheGovernanceScenarioFinalizer:
    """Reduce one measured scenario only after the real registry cleanup."""

    def __init__(
        self,
        paths: RunPaths,
        case_id: str,
        measurement: Mapping[str, object],
        fixture: CanonicalFixtureLifecycle | None = None,
    ) -> None:
        cache_governance.scenario_for_case(case_id)
        if measurement.get("cleanup") is not None:
            raise RunError("scenario measurement was prematurely finalized")
        self.paths = paths
        self.case_id = case_id
        self.measurement = copy.deepcopy(dict(measurement))
        self.fixture = fixture
        self._finalized = False

    def finalize(self, cleanup: Mapping[str, Any]) -> dict[str, object]:
        if self._finalized:
            raise RunError("scenario finalization is not repeatable")
        items = cleanup.get("items")
        if (
            cleanup.get("schema") != "milai.dg13u.u1-cleanup-receipt.v1"
            or cleanup.get("run_id") != self.paths.run_id
            or cleanup.get("status") != TerminalStatus.PASS
            or cleanup.get("existing_vllm_preserved") is not True
            or cleanup.get("external_lifecycle_mutations") != 0
            or not isinstance(items, list)
        ):
            raise RunError("scenario cleanup is incomplete")
        run_owned = [
            row
            for row in items
            if isinstance(row, Mapping)
            and row.get("ownership") == ResourceOwnership.RUN_OWNED
        ]
        external = [
            row
            for row in items
            if isinstance(row, Mapping)
            and row.get("ownership") == ResourceOwnership.PRESERVED_EXTERNAL
        ]
        if (
            not run_owned
            or any(row.get("state") != "removed" for row in run_owned)
            or any(
                row.get("state") != "preserved_external" or row.get("attempts") != 0
                for row in external
            )
        ):
            raise RunError("scenario cleanup is incomplete")
        cleanup_path = self.paths.durable / "cleanup-receipt.json"
        try:
            persisted_cleanup = json.loads(cleanup_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RunError("scenario cleanup receipt is not persisted") from exc
        if persisted_cleanup != dict(cleanup):
            raise RunError("scenario cleanup receipt binding drifted")

        measurement = copy.deepcopy(self.measurement)
        invariants = measurement.get("invariants")
        if not isinstance(invariants, dict):
            raise RunError("scenario invariant measurement is absent")
        if self.case_id in {"U1-CACHE-FALLBACK", "U1-STALE-CURRENT"}:
            fixture_removed = any(
                row.get("kind") == "canonical_fixture" and row.get("state") == "removed"
                for row in run_owned
            )
            invariants["mutation_cleanup_complete"] = bool(
                self.fixture is not None
                and self.fixture._cleanup_complete
                and fixture_removed
            )
        measurement["cleanup"] = {
            "status": "PASS",
            "attempts": 1,
            "run_owned_resources_absent": True,
            "receipt_sha256": hashlib.sha256(cleanup_path.read_bytes()).hexdigest(),
        }
        try:
            reduced = cache_governance.reduce_measurement(
                self.case_id,
                measurement,
            )
        except cache_governance.ScenarioContractError as exc:
            raise RunError("cache/governance scenario reduction failed") from exc
        _atomic_write(
            self.paths.durable / "cache-governance-evidence.json",
            reduced,
        )
        self._finalized = True
        return reduced


def _vllm_lifecycle_identity_sha256(value: Mapping[str, Any]) -> str:
    if (
        value.get("completion_calls") != 0
        or value.get("lifecycle_mutated") is not False
    ):
        raise RunError("vLLM lifecycle identity is not read-only")
    container = value.get("container")
    image = value.get("image")
    if not isinstance(container, Mapping) or not isinstance(image, Mapping):
        raise RunError("vLLM lifecycle identity is incomplete")
    stable = {
        "endpoint": value.get("endpoint"),
        "container": dict(container),
        "image": dict(image),
        "model_byte_closure": value.get("model_byte_closure"),
        "tokenizer": value.get("tokenizer"),
        "tokenizer_config": value.get("tokenizer_config"),
        "chat_template": value.get("chat_template"),
    }
    return hashlib.sha256(u0._canonical_bytes(stable)).hexdigest()


class LifecycleScenarioFinalizer:
    """Bind lifecycle evidence only after exact registry cleanup."""

    def __init__(
        self,
        paths: RunPaths,
        case_id: str,
        measurement: Mapping[str, object],
        initial_vllm: Mapping[str, Any],
    ) -> None:
        scenario = lifecycle_scenarios.scenario_for_case(case_id)
        if (
            measurement.get("cleanup") is not None
            or measurement.get("vllm") is not None
        ):
            raise RunError("lifecycle measurement was prematurely finalized")
        steps = measurement.get("steps")
        if not isinstance(steps, list) or len(steps) != len(scenario.steps) - 1:
            raise RunError("lifecycle partial step measurement is invalid")
        self.paths = paths
        self.case_id = case_id
        self.measurement = copy.deepcopy(dict(measurement))
        self.initial_vllm = copy.deepcopy(dict(initial_vllm))
        self._finalized = False

    def finalize(self, cleanup: Mapping[str, Any]) -> dict[str, object]:
        if self._finalized:
            raise RunError("lifecycle finalization is not repeatable")
        items = cleanup.get("items")
        if (
            cleanup.get("schema") != "milai.dg13u.u1-cleanup-receipt.v1"
            or cleanup.get("run_id") != self.paths.run_id
            or cleanup.get("status") != TerminalStatus.PASS
            or cleanup.get("existing_vllm_preserved") is not True
            or cleanup.get("external_lifecycle_mutations") != 0
            or not isinstance(items, list)
        ):
            raise RunError("lifecycle cleanup is incomplete")
        run_owned = [
            row
            for row in items
            if isinstance(row, Mapping)
            and row.get("ownership") == ResourceOwnership.RUN_OWNED
        ]
        external = [
            row
            for row in items
            if isinstance(row, Mapping)
            and row.get("ownership") == ResourceOwnership.PRESERVED_EXTERNAL
        ]
        if (
            not run_owned
            or any(row.get("state") != "removed" for row in run_owned)
            or any(
                row.get("state") != "preserved_external" or row.get("attempts") != 0
                for row in external
            )
        ):
            raise RunError("lifecycle cleanup is incomplete")
        cleanup_path = self.paths.durable / "cleanup-receipt.json"
        try:
            persisted = json.loads(cleanup_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RunError("lifecycle cleanup receipt is not persisted") from exc
        if persisted != dict(cleanup):
            raise RunError("lifecycle cleanup receipt binding drifted")

        initial_vllm_sha256 = _vllm_lifecycle_identity_sha256(self.initial_vllm)
        try:
            final_vllm = u0._probe_vllm()
        except Exception as exc:
            raise RunError("lifecycle final vLLM identity probe failed") from exc
        final_vllm_sha256 = _vllm_lifecycle_identity_sha256(final_vllm)
        if final_vllm_sha256 != initial_vllm_sha256:
            raise RunError("lifecycle external vLLM identity changed")

        scenario = lifecycle_scenarios.scenario_for_case(self.case_id)
        final_step = scenario.steps[-1]
        measurement = copy.deepcopy(self.measurement)
        steps = measurement["steps"]
        assert isinstance(steps, list)
        steps.append(
            {
                "step_id": final_step.step_id,
                "status": "COMPLETED",
                "attempts": 1,
                "receipt_sha256": hashlib.sha256(
                    u0._canonical_bytes(
                        {
                            "step_id": final_step.step_id,
                            "cleanup_receipt_sha256": hashlib.sha256(
                                cleanup_path.read_bytes()
                            ).hexdigest(),
                        }
                    )
                ).hexdigest(),
            }
        )
        measurement["cleanup"] = {
            "status": "PASS",
            "attempts": 1,
            "run_owned_resources_absent": True,
            "receipt_sha256": hashlib.sha256(cleanup_path.read_bytes()).hexdigest(),
        }
        measurement["vllm"] = {
            "identity_before_sha256": initial_vllm_sha256,
            "identity_after_sha256": final_vllm_sha256,
            "lifecycle_attempts": 0,
            "preserved": True,
        }
        try:
            reduced = lifecycle_scenarios.reduce_lifecycle_measurement(
                self.case_id,
                measurement,
            )
        except lifecycle_scenarios.LifecycleScenarioError as exc:
            raise RunError("lifecycle scenario reduction failed") from exc
        _atomic_write(self.paths.durable / "lifecycle-evidence.json", reduced)
        self._finalized = True
        return reduced


class OpenWorkerU1Lifecycle:
    """Run-owned reader-lite broker, direct Host bridge, and OpenWorker."""

    def __init__(
        self,
        paths: RunPaths,
        case: CaseSpec,
        runtime: FreshRuntimeLifecycle,
        product_venv: Path,
        fixture: CanonicalFixtureLifecycle | None = None,
    ) -> None:
        self.paths = paths
        self.case = case
        self.runtime = runtime
        self.product_venv = product_venv
        self.fixture = fixture
        suffix = hashlib.sha256(paths.run_id.encode()).hexdigest()[:16]
        self.network_name = f"milai-dg13u-u1-net-{suffix}"
        self.container_name = f"milai-dg13u-u1-worker-{suffix}"
        self.socket_path = paths.uds / "reader-lite.sock"
        self.policy_path = paths.uds / "reader-lite-policy.json"
        self.provider_manifest = paths.durable / "provider-capability.json"
        self.provider_ledger = paths.durable / "provider-ledger.jsonl"
        self.host_trace = paths.durable / "host-access-trace.jsonl"
        self.broker_log = paths.durable / "logs/broker.log"
        self.host_log = paths.durable / "logs/host.log"
        self.worker_log = paths.durable / "logs/openworker.log"
        self.broker_process: subprocess.Popen[bytes] | None = None
        self.host_process: subprocess.Popen[bytes] | None = None
        self.broker_marker: str | None = None
        self.host_marker: str | None = None
        self.broker_generation = 0
        self.host_generation = 0
        self.socket_identity: tuple[int, int] | None = None
        self.gateway: str | None = None
        self.host_port: int | None = None
        self.ingress_token: str | None = None
        self.started = False
        self.smoke_evidence: dict[str, Any] | None = None
        self.readiness_latencies_ms: dict[str, float] = {
            "runtime": 0.0,
            "broker": 0.0,
            "host": 0.0,
            "openworker": 0.0,
            "provider": 0.0,
        }
        self._openworker_started_at: float | None = None
        self.fault_plan: fault_execution.FaultExecutionPlan | None = None
        self.fault_runtime: runtime_fault.RuntimeFaultInjector | None = None
        self.fault_provider: provider_fault.ProviderFaultInjector | None = None
        self.fault_mcp: mcp_fault.McpFaultEndpoint | None = None
        self.fault_broker: _RunOwnedBrokerThread | None = None
        self.fault_fixture_observation: dict[str, Any] | None = None
        self.host_prefetch_socket = self.socket_path
        self.host_policy_path = self.policy_path
        self.provider_endpoint_identity = VLLM_ORIGIN
        self.provider_timeout_seconds = 60.0
        self.fault_execution_evidence: dict[str, Any] | None = None
        self.cache_governance_measurement: dict[str, object] | None = None
        self.lifecycle_measurement: dict[str, object] | None = None
        self._resources: ResourceRegistry | None = None

    @property
    def is_fault_case(self) -> bool:
        return self.case.case_id in _FAULT_CASE_IDS

    def _register_fault_path(
        self,
        resources: ResourceRegistry,
        path: Path,
        *,
        kind: str = "artifact",
    ) -> None:
        identity = hashlib.sha256(os.fsencode(path)).hexdigest()
        resources.register(
            ResourceHandle(
                kind,
                f"{kind}/fault:{identity}",
                ResourceOwnership.RUN_OWNED,
                cleanup=lambda owned=path: owned.unlink(missing_ok=True),
                absent=lambda owned=path: not owned.exists() and not owned.is_symlink(),
            )
        )

    def _fault_policy(
        self,
        resources: ResourceRegistry,
        *,
        directory: str,
        base_url: str,
        mcp_executable: Path,
    ) -> tuple[Path, Path]:
        root = self.paths.uds / directory
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
        socket_path = root / "reader-lite.sock"
        policy_path = self.paths.uds / f"{directory}-policy.json"
        _atomic_write(
            policy_path,
            _fault_broker_policy(
                socket_path=socket_path,
                base_url=base_url,
                mcp_executable=mcp_executable,
            ),
        )
        self._register_fault_path(resources, policy_path)
        return socket_path, policy_path

    def _register_fault_receipts(self, resources: ResourceRegistry) -> None:
        assert self.fault_plan is not None
        for receipt in self.fault_plan.receipts:
            self._register_fault_path(resources, receipt.path, kind="receipt")

    def _start_fault_broker(
        self,
        resources: ResourceRegistry,
        policy_path: Path,
    ) -> None:
        assert self.runtime.reader_token is not None
        broker = _RunOwnedBrokerThread(
            self.product_venv,
            policy_path,
            self.runtime.reader_token,
        )
        broker.start()
        self.fault_broker = broker
        identity = hashlib.sha256(os.fsencode(broker.socket_path)).hexdigest()
        resources.register(
            ResourceHandle(
                "endpoint",
                f"endpoint/fault-broker:{identity}",
                ResourceOwnership.RUN_OWNED,
                cleanup=broker.stop,
                absent=broker.absent,
            )
        )

    def _prepare_fault_before_host(self, resources: ResourceRegistry) -> None:
        if not self.is_fault_case:
            return
        try:
            plan = fault_execution.build_fault_execution_plan(
                self.case.case_id,
                run_owned_root=self.paths.uds,
                python_executable=Path(sys.executable).resolve(),
            )
        except fault_execution.FaultExecutionError as exc:
            raise RunError("fault execution plan is invalid") from exc
        self.fault_plan = plan
        self._register_fault_receipts(resources)
        mcp_executable = self.product_venv / "bin/milai-mcp"

        if self.case.case_id.startswith("U1-RUNTIME-"):
            if plan.fixture.mode == "DOWN":
                closed = runtime_fault.closed_loopback_endpoint_identity()
                runtime_origin = closed.base_url
                self.fault_fixture_observation = {
                    "state": "HELD_CLOSED",
                    "attempts": 0,
                    "cleanup_complete": True,
                }
            else:
                receipt = plan.receipts[0]
                injector = runtime_fault.RuntimeFaultInjector(
                    plan.fixture.mode,
                    artifact_path=receipt.path,
                    run_id=f"dg13u-fault-{self.case.case_id.casefold()}",
                    delay_seconds=float(plan.fixture.delay_seconds or 0.1),
                )
                injector.start()
                self.fault_runtime = injector
                runtime_origin = injector.base_url
                resources.register(
                    ResourceHandle(
                        "endpoint",
                        f"endpoint/runtime-fault:{hashlib.sha256(runtime_origin.encode()).hexdigest()}",
                        ResourceOwnership.RUN_OWNED,
                        cleanup=injector.stop,
                        absent=lambda owned=injector: (
                            not bool(getattr(owned, "_active", False))
                        ),
                    )
                )
            socket_path, policy_path = self._fault_policy(
                resources,
                directory="fault-runtime",
                base_url=runtime_origin,
                mcp_executable=mcp_executable,
            )
            self.host_prefetch_socket = socket_path
            self.host_policy_path = policy_path
            self._start_fault_broker(resources, policy_path)
            return

        if self.case.case_id.startswith("U1-MCP-CHILD-"):
            if len(plan.receipts) != 3 or plan.fixture.resource_path is None:
                raise RunError("MCP child fault plan is incomplete")
            builder, ledger, cleanup = plan.receipts
            mcp_child_fault.build_child_fixture(
                plan.fixture.mode,
                executable_path=plan.fixture.resource_path,
                ledger_path=ledger.path,
                cleanup_receipt_path=cleanup.path,
                manifest_path=builder.path,
                timeout_delay_seconds=float(plan.fixture.delay_seconds or 0.1),
            )
            self._register_fault_path(
                resources, plan.fixture.resource_path, kind="executable"
            )
            socket_path, policy_path = self._fault_policy(
                resources,
                directory="fault-child",
                base_url=self.runtime.identity.base_url,
                mcp_executable=plan.fixture.resource_path,
            )
            self.host_prefetch_socket = socket_path
            self.host_policy_path = policy_path
            return

        if self.case.case_id.startswith("U1-BROKER-"):
            if plan.fixture.resource_path is None:
                raise RunError("broker fault socket path is absent")
            placeholder_socket, policy_path = self._fault_policy(
                resources,
                directory="fault-broker-policy",
                base_url=self.runtime.identity.base_url,
                mcp_executable=mcp_executable,
            )
            if placeholder_socket.exists() or placeholder_socket.is_symlink():
                raise RunError("broker fault policy placeholder is not absent")
            self.host_prefetch_socket = plan.fixture.resource_path
            self.host_policy_path = policy_path
            self._register_fault_path(
                resources, plan.fixture.resource_path, kind="socket"
            )
            if plan.fixture.mode == "DOWN":
                self.fault_fixture_observation = {
                    "state": "HELD_CLOSED",
                    "attempts": 0,
                    "cleanup_complete": True,
                }
            return

        if self.case.case_id.startswith("U1-PROVIDER-"):
            self.provider_timeout_seconds = 1.0
            if plan.fixture.mode == "DOWN":
                closed = runtime_fault.closed_loopback_endpoint_identity()
                self.provider_endpoint_identity = closed.base_url
                self.fault_fixture_observation = {
                    "state": "HELD_CLOSED",
                    "attempts": 0,
                    "cleanup_complete": True,
                }
            else:
                injector = provider_fault.ProviderFaultInjector(
                    plan.fixture.mode,
                    ledger_path=plan.receipts[0].path,
                    timeout_delay_seconds=float(plan.fixture.delay_seconds or 0.1),
                )
                injector.start()
                self.fault_provider = injector
                self.provider_endpoint_identity = injector.base_url
                resources.register(
                    ResourceHandle(
                        "endpoint",
                        f"endpoint/provider-fault:{hashlib.sha256(injector.base_url.encode()).hexdigest()}",
                        ResourceOwnership.RUN_OWNED,
                        cleanup=injector.stop,
                        absent=lambda owned=injector: (
                            not bool(getattr(owned, "_active", False))
                        ),
                    )
                )
            return
        raise RunError("fault execution plan prefix is unsupported")

    def _activate_post_readiness_fault(self, resources: ResourceRegistry) -> None:
        plan = self.fault_plan
        if plan is None:
            raise RunError("fault execution plan is absent")
        if self.case.case_id.startswith("U1-MCP-CHILD-"):
            self._start_fault_broker(resources, self.host_policy_path)
        elif self.case.case_id.startswith("U1-BROKER-") and plan.fixture.mode != "DOWN":
            endpoint = mcp_fault.McpFaultEndpoint(
                plan.fixture.mode,
                socket_path=plan.fixture.resource_path,
                ledger_path=plan.receipts[0].path,
                timeout_delay_seconds=float(plan.fixture.delay_seconds or 0.1),
            )
            endpoint.start()
            self.fault_mcp = endpoint
            resources.register(
                ResourceHandle(
                    "endpoint",
                    f"endpoint/mcp-fault:{hashlib.sha256(os.fsencode(endpoint.socket_path)).hexdigest()}",
                    ResourceOwnership.RUN_OWNED,
                    cleanup=endpoint.stop,
                    absent=lambda owned=endpoint: (
                        not bool(getattr(owned, "_active", False))
                        and not owned.socket_path.exists()
                    ),
                )
            )

    def start(self, resources: ResourceRegistry) -> dict[str, Any]:
        if self.runtime.identity is None or self.runtime.reader_token is None:
            raise RunError("fresh Runtime reader identity is absent")
        if not TOKENIZER_JSON.is_file() or TOKENIZER_JSON.is_symlink():
            raise RunError("exact target tokenizer.json is absent")
        self._resources = resources
        _command_bytes(
            [
                "docker",
                "network",
                "create",
                "--driver",
                "bridge",
                "--internal",
                "--label",
                f"io.milai.dg13u.run-id={self.paths.run_id}",
                self.network_name,
            ],
            timeout=30,
        )
        resources.register(
            ResourceHandle(
                "network",
                f"network/{self.network_name}",
                ResourceOwnership.RUN_OWNED,
                cleanup=lambda: _docker_remove_network(self.network_name),
                absent=lambda: _docker_absent("network", self.network_name),
            )
        )
        _checkpoint_recovery(self.paths)
        gateway = _command_text(
            [
                "docker",
                "network",
                "inspect",
                self.network_name,
                "--format",
                "{{(index .IPAM.Config 0).Gateway}}",
            ],
            timeout=15,
        )
        try:
            socket.inet_aton(gateway)
        except OSError as exc:
            raise RunError("dedicated bridge gateway identity is invalid") from exc
        self.gateway = gateway
        broker_started = time.monotonic()
        self._start_broker(resources)
        self.readiness_latencies_ms["broker"] = round(
            (time.monotonic() - broker_started) * 1000, 3
        )
        self._prepare_fault_before_host(resources)
        host_started = time.monotonic()
        self._start_host(resources)
        self.readiness_latencies_ms["host"] = round(
            (time.monotonic() - host_started) * 1000, 3
        )
        self._openworker_started_at = time.monotonic()
        self._start_worker(resources)
        self.started = True
        return {
            "network_name_sha256": hashlib.sha256(
                self.network_name.encode()
            ).hexdigest(),
            "network_gateway": gateway,
            "broker": {
                "pid": self.broker_process.pid if self.broker_process else None,
                "socket": str(self.socket_path.relative_to(UDS_ROOT)),
            },
            "host": {
                "pid": self.host_process.pid if self.host_process else None,
                "origin": f"http://{gateway}:{self.host_port}",
            },
            "openworker_container_name_sha256": hashlib.sha256(
                self.container_name.encode()
            ).hexdigest(),
            "openworker_image": OPENWORKER_IMAGE,
        }

    def _initialize_broker_assets(self) -> None:
        assert (
            self.runtime.identity is not None and self.runtime.reader_token is not None
        )
        mcp_executable = self.product_venv / "bin/milai-mcp"
        broker_executable = self.product_venv / "bin/milai-mcp-broker"
        if not mcp_executable.is_file() or not broker_executable.is_file():
            raise RunError("exact MCP/broker entrypoint is absent")
        policy = {
            "allowed_peer_uids": [os.geteuid()],
            "base_url": self.runtime.identity.base_url,
            "child_shutdown_seconds": 5,
            "consistency_floor": "CANONICAL_REQUIRED",
            "max_connections": 2,
            "max_limit": 3,
            "mcp_max_retries": 0,
            "mcp_executable": str(mcp_executable),
            "mcp_executable_sha256": u0._sha256_file(mcp_executable),
            "profile": "reader-lite",
            "required_authority": "INFORMATIONAL",
            "schema": "milai.openworker.mcp-broker-policy.v1",
            "scope": {"project_ids": ["orchid-release"]},
            "socket_mode": "0600",
            "socket_path": str(self.socket_path),
        }
        _atomic_write(self.policy_path, policy)
        token_file = self.paths.temporary / "secrets/reader.token"
        _private_text(token_file, self.runtime.reader_token)

    def _spawn_broker(
        self, log_path: Path
    ) -> tuple[subprocess.Popen[bytes], str, tuple[int, int]]:
        broker_executable = self.product_venv / "bin/milai-mcp-broker"
        token_file = self.paths.temporary / "secrets/reader.token"
        log_path.parent.mkdir(mode=0o700, exist_ok=True)
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            process = subprocess.Popen(
                [
                    str(broker_executable),
                    "--policy",
                    str(self.policy_path),
                    "--token-file",
                    str(token_file),
                ],
                cwd=ROOT,
                env=_safe_process_environment(self.paths.temporary),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        marker: str | None = None
        try:
            marker = _stable_process_marker(process.pid)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RunError("reader-lite broker exited before readiness")
                if self.socket_path.exists():
                    current = self.socket_path.lstat()
                    if (
                        not stat.S_ISSOCK(current.st_mode)
                        or stat.S_IMODE(current.st_mode) != 0o600
                    ):
                        raise RunError("reader-lite broker socket identity is invalid")
                    return process, marker, (current.st_dev, current.st_ino)
                time.sleep(0.05)
            raise RunError("reader-lite broker readiness timeout")
        except Exception:
            _terminate_owned_process(process, marker or _process_marker(process.pid))
            deadline = time.monotonic() + 2
            while self.socket_path.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            raise

    @staticmethod
    def _process_cleanup(
        process: subprocess.Popen[bytes],
    ) -> resource_registry.ProcessCleanup:
        return lambda generation, owned=process: _terminate_owned_process(
            owned, generation.marker
        )

    @staticmethod
    def _process_absent() -> resource_registry.ProcessAbsent:
        return lambda generation: not _process_alive(generation.pid, generation.marker)

    def _start_broker(self, resources: ResourceRegistry) -> None:
        self._initialize_broker_assets()
        process, marker, socket_identity = self._spawn_broker(self.broker_log)
        resources.register_process(
            "mcp-broker",
            process.pid,
            marker,
            self._process_cleanup(process),
            self._process_absent(),
        )
        _record_recovery_process(
            self.paths,
            "mcp-broker",
            process.pid,
            marker,
        )
        self.broker_process = process
        self.broker_marker = marker
        self.broker_generation = 1
        self.socket_identity = socket_identity

    def _initialize_host_assets(self) -> None:
        assert self.gateway is not None
        # The Host validator deliberately accepts a narrower identifier alphabet
        # than token_urlsafe(), whose '-' output made startup probabilistic.
        ingress_token = secrets.token_hex(32)
        self.ingress_token = ingress_token
        ingress_file = self.paths.temporary / "secrets/host-ingress.token"
        _private_text(ingress_file, ingress_token)
        prompt = (
            _case_prompt(self.case)
            if self.case.case_id in _IMPLEMENTED_REAL_CASES
            else self.case.title
        )
        capability = _provider_capability(
            self.paths,
            self.case,
            prompt,
            endpoint_identity=self.provider_endpoint_identity,
        )
        _atomic_write(self.provider_manifest, capability)
        self.host_port = _free_bind_port(self.gateway)

    def _spawn_host(
        self,
        *,
        trace_path: Path,
        log_path: Path,
    ) -> tuple[subprocess.Popen[bytes], str]:
        assert self.gateway is not None and self.host_port is not None
        assert self.ingress_token is not None
        ingress_file = self.paths.temporary / "secrets/host-ingress.token"
        host_executable = self.product_venv / "bin/milai-openworker-adapter"
        if not host_executable.is_file():
            raise RunError("exact Host entrypoint is absent")
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        memory_mode = (
            "none"
            if self.case.case_id == "U1-ORDINARY-SYNC-TOOL"
            else "query-first"
            if self.case.case_id == "U1-TASK-CONTINUE"
            else "prefetch"
        )
        command = [
            str(host_executable),
            "--manifest",
            str(self.provider_manifest),
            "--ledger",
            str(self.provider_ledger),
            "--trace",
            str(trace_path),
            "--listen-host",
            self.gateway,
            "--listen-port",
            str(self.host_port),
            "--memory-mode",
            memory_mode,
            "--ingress-token-file",
            str(ingress_file),
            "--provider-timeout-seconds",
            str(self.provider_timeout_seconds),
        ]
        if memory_mode in {"prefetch", "query-first"}:
            command.extend(
                (
                    "--prefetch-socket",
                    str(self.host_prefetch_socket),
                    "--tokenizer-json",
                    str(TOKENIZER_JSON),
                    "--broker-policy",
                    str(self.host_policy_path),
                    "--task-fixture",
                    str(CANDIDATE_FIXTURE),
                )
            )
        if self.case.case_id == "U1-ORDINARY-SYNC-TOOL":
            command.extend(
                (
                    "--single-ordinary-tool-required-once",
                    "read",
                    "--ordinary-tool-provider-compatibility",
                    "VLLM_JSON_SCHEMA_NAMED_TOOL_ADAPTER",
                )
            )
        with os.fdopen(descriptor, "wb") as output:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=_safe_process_environment(self.paths.temporary),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        try:
            return process, _stable_process_marker(process.pid)
        except Exception:
            _terminate_owned_process(process, _process_marker(process.pid))
            raise

    def _wait_host_ready(self) -> None:
        assert self.gateway is not None and self.host_port is not None
        assert self.ingress_token is not None
        provider_started = time.monotonic()
        models = _wait_http_json(
            f"http://{self.gateway}:{self.host_port}/v1/models",
            token=self.ingress_token,
            seconds=45,
        )
        self.readiness_latencies_ms["provider"] = round(
            (time.monotonic() - provider_started) * 1000, 3
        )
        data = models.get("data")
        if not isinstance(data, list) or [row.get("id") for row in data] != [MODEL_ID]:
            raise RunError("Host exact model readiness is invalid")

    def _start_host(self, resources: ResourceRegistry) -> None:
        self._initialize_host_assets()
        process, marker = self._spawn_host(
            trace_path=self.host_trace,
            log_path=self.host_log,
        )
        resources.register_process(
            "host-adapter",
            process.pid,
            marker,
            self._process_cleanup(process),
            self._process_absent(),
        )
        _record_recovery_process(
            self.paths,
            "host-adapter",
            process.pid,
            marker,
        )
        self.host_process = process
        self.host_marker = marker
        self.host_generation = 1
        self._wait_host_ready()

    def _initialize_worker_assets(self) -> Path:
        assert self.gateway is not None and self.host_port is not None
        assert self.ingress_token is not None
        environment_file = self.paths.temporary / "secrets/openworker.env"
        _private_text(
            environment_file,
            "OPENWORKER_KEY="
            + self.ingress_token
            + "\nOPENWORKER_URL=http://"
            + self.gateway
            + f":{self.host_port}/v1\n",
        )
        return environment_file

    def _create_worker_container(self, environment_file: Path) -> None:
        _command_bytes(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                self.container_name,
                "--network",
                self.network_name,
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--ulimit",
                "core=0:0",
                "--tmpfs",
                "/openworker/data:rw,nosuid,nodev,noexec,size=128m,mode=0700",
                "--env-file",
                str(environment_file),
                "--mount",
                f"type=bind,src={self.socket_path},dst=/run/milai-mcp/reader-lite.sock,readonly",
                "--label",
                f"io.milai.dg13u.run-id={self.paths.run_id}",
                OPENWORKER_IMAGE,
            ],
            timeout=120,
        )

    def _start_worker(self, resources: ResourceRegistry) -> None:
        environment_file = self._initialize_worker_assets()
        self._create_worker_container(environment_file)
        resources.register(
            ResourceHandle(
                "container",
                f"container/{self.container_name}",
                ResourceOwnership.RUN_OWNED,
                cleanup=lambda: _docker_remove_container(self.container_name),
                absent=lambda: _docker_absent("container", self.container_name),
            )
        )
        _checkpoint_recovery(self.paths)

    def _stop_broker_for_replacement(
        self,
    ) -> tuple[subprocess.Popen[bytes], str]:
        if self.broker_process is None or self.broker_marker is None:
            raise RunError("old broker process identity is absent")
        old_process = self.broker_process
        old_marker = self.broker_marker
        _terminate_owned_process(old_process, old_marker)
        if _process_alive(old_process.pid, old_marker):
            raise RunError("old broker process remained alive")
        deadline = time.monotonic() + 5
        while self.socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if self.socket_path.exists() or self.socket_path.is_symlink():
            raise RunError("old broker socket remained after normal stop")
        return old_process, old_marker

    def _start_broker_replacement(
        self,
        resources: ResourceRegistry,
        old_process: subprocess.Popen[bytes],
        old_marker: str,
    ) -> tuple[int, int]:
        log_path = self.paths.durable / f"logs/broker.g{self.broker_generation + 1}.log"
        process, marker, socket_identity = self._spawn_broker(log_path)
        try:
            replacement = resources.replace_process(
                "mcp-broker",
                old_process.pid,
                old_marker,
                process.pid,
                marker,
                self._process_cleanup(process),
                self._process_absent(),
            )
        except Exception:
            _terminate_owned_process(process, marker)
            raise
        self.broker_process = process
        self.broker_marker = marker
        self.broker_generation = replacement.generation
        self.socket_identity = socket_identity
        return socket_identity

    def _replace_broker(self, resources: ResourceRegistry) -> tuple[int, int]:
        old_process, old_marker = self._stop_broker_for_replacement()
        return self._start_broker_replacement(
            resources,
            old_process,
            old_marker,
        )

    def _stop_host_for_replacement(
        self,
    ) -> tuple[subprocess.Popen[bytes], str]:
        if self.host_process is None or self.host_marker is None:
            raise RunError("old Host process identity is absent")
        old_process = self.host_process
        old_marker = self.host_marker
        _terminate_owned_process(old_process, old_marker)
        if _process_alive(old_process.pid, old_marker):
            raise RunError("old Host process remained alive")
        return old_process, old_marker

    def _start_host_replacement(
        self,
        resources: ResourceRegistry,
        old_process: subprocess.Popen[bytes],
        old_marker: str,
    ) -> Path:
        manifest_sha256 = u0._sha256_file(self.provider_manifest)
        ledger_prefix = _read_json_lines(self.provider_ledger)
        endpoint = (self.gateway, self.host_port, self.ingress_token)
        next_generation = self.host_generation + 1
        trace_path = self.paths.durable / f"host-access-trace.g{next_generation}.jsonl"
        log_path = self.paths.durable / f"logs/host.g{next_generation}.log"
        if trace_path.exists() or trace_path.is_symlink():
            raise RunError("replacement Host trace already exists")
        process, marker = self._spawn_host(trace_path=trace_path, log_path=log_path)
        try:
            replacement = resources.replace_process(
                "host-adapter",
                old_process.pid,
                old_marker,
                process.pid,
                marker,
                self._process_cleanup(process),
                self._process_absent(),
            )
        except Exception:
            _terminate_owned_process(process, marker)
            raise
        self.host_process = process
        self.host_marker = marker
        self.host_generation = replacement.generation
        self.host_trace = trace_path
        if (
            endpoint != (self.gateway, self.host_port, self.ingress_token)
            or u0._sha256_file(self.provider_manifest) != manifest_sha256
            or _read_json_lines(self.provider_ledger) != ledger_prefix
        ):
            raise RunError("replacement Host changed stable launch assets")
        return trace_path

    def _replace_host(self, resources: ResourceRegistry) -> Path:
        old_process, old_marker = self._stop_host_for_replacement()
        trace_path = self._start_host_replacement(
            resources,
            old_process,
            old_marker,
        )
        self._wait_host_ready()
        return trace_path

    def _recreate_worker(self) -> None:
        environment_file = self.paths.temporary / "secrets/openworker.env"
        if not environment_file.is_file() or environment_file.is_symlink():
            raise RunError("OpenWorker environment asset is absent")
        _docker_remove_container(self.container_name)
        if not _docker_absent("container", self.container_name):
            raise RunError("old OpenWorker container remained after removal")
        self._create_worker_container(environment_file)

    def _worker_mount_identity(self) -> tuple[int, int]:
        completed = _command_bytes(
            [
                "docker",
                "exec",
                self.container_name,
                "stat",
                "-Lc",
                "%d:%i",
                "/run/milai-mcp/reader-lite.sock",
            ],
            timeout=15,
            check=False,
        )
        match = re.fullmatch(rb"([0-9]+):([0-9]+)\s*", completed.stdout)
        if completed.returncode != 0 or match is None:
            raise RunError("OpenWorker socket bind identity is unavailable")
        return int(match.group(1)), int(match.group(2))

    def _worker_bound_socket_unavailable(self) -> bool:
        program = (
            "const n=require('net');const s=n.createConnection("
            "'/run/milai-mcp/reader-lite.sock');"
            "const t=setTimeout(()=>{s.destroy();console.log('UNAVAILABLE')},1500);"
            "s.once('connect',()=>{clearTimeout(t);s.destroy();console.log('CONNECTED')});"
            "s.once('error',()=>{clearTimeout(t);console.log('UNAVAILABLE')});"
        )
        completed = _command_bytes(
            ["docker", "exec", self.container_name, "node", "-e", program],
            timeout=5,
            check=False,
        )
        return completed.returncode == 0 and completed.stdout.strip() == b"UNAVAILABLE"

    def _worker_process_identity_sha256(self) -> str:
        inspected = u0._run_json(
            ["docker", "container", "inspect", self.container_name]
        )
        if (
            not isinstance(inspected, list)
            or len(inspected) != 1
            or not isinstance(inspected[0], Mapping)
        ):
            raise RunError("OpenWorker process identity is ambiguous")
        row = inspected[0]
        state = row.get("State")
        if not isinstance(state, Mapping):
            raise RunError("OpenWorker process state is absent")
        pid = state.get("Pid")
        started_at = state.get("StartedAt")
        container_id = row.get("Id")
        if (
            not isinstance(pid, int)
            or isinstance(pid, bool)
            or pid < 1
            or not isinstance(started_at, str)
            or not started_at
            or not isinstance(container_id, str)
            or not container_id
        ):
            raise RunError("OpenWorker process identity is invalid")
        return lifecycle_scenarios.process_identity_sha256(
            pid,
            started_at,
            container_id,
        )

    def _wait_worker_health(self) -> str:
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            health = _command_bytes(
                [
                    "docker",
                    "exec",
                    self.container_name,
                    "curl",
                    "-sf",
                    "-u",
                    "opencode:openworker-local",
                    "http://127.0.0.1:4096/global/health",
                ],
                timeout=10,
                check=False,
            )
            if health.returncode == 0:
                return hashlib.sha256(health.stdout).hexdigest()
            if _docker_absent("container", self.container_name):
                raise RunError("OpenWorker exited before lifecycle readiness")
            time.sleep(0.25)
        raise RunError("OpenWorker lifecycle health readiness timeout")

    def _wait_worker_bootstrap_quiescent(self) -> None:
        """Wait for exact OpenWorker pre-warm completion and stable Host accounting."""

        deadline = time.monotonic() + 30
        previous: tuple[str, str] | None = None
        stable_observations = 0
        while time.monotonic() < deadline:
            completed = _command_bytes(
                ["docker", "logs", self.container_name], timeout=10, check=False
            )
            output = completed.stdout + completed.stderr
            trace_sha256 = hashlib.sha256(
                self.host_trace.read_bytes() if self.host_trace.exists() else b""
            ).hexdigest()
            ledger_sha256 = hashlib.sha256(
                self.provider_ledger.read_bytes()
                if self.provider_ledger.exists()
                else b""
            ).hexdigest()
            current = (trace_sha256, ledger_sha256)
            bootstrap_complete = (
                completed.returncode == 0
                and b"Pre-warmed in " in output
                and b"Database migration complete." in output
            )
            if bootstrap_complete and current == previous:
                stable_observations += 1
                if stable_observations >= 10:
                    return
            else:
                stable_observations = 0
            previous = current
            if _docker_absent("container", self.container_name):
                raise RunError("OpenWorker exited before bootstrap quiescence")
            time.sleep(0.1)
        raise RunError("OpenWorker bootstrap quiescence timeout")

    def _mcp_catalog_readiness(self) -> str:
        listed = _command_bytes(
            [
                "docker",
                "exec",
                "--workdir",
                "/openworker/runtime",
                "--env",
                "OPENCODE_CONFIG_DIR=/openworker/runtime",
                self.container_name,
                "opencode",
                "mcp",
                "list",
            ],
            timeout=45,
            check=False,
        )
        normalized = _ansi_stripped_text(
            listed.stdout + b"\n" + listed.stderr
        ).casefold()
        connected = (
            "milai" in normalized
            and re.search(r"(?<![a-z])connected(?![a-z])", normalized) is not None
        )
        if listed.returncode != 0 or not connected:
            raise RunError("replacement OpenWorker MCP catalog is not connected")
        return hashlib.sha256(listed.stdout + listed.stderr).hexdigest()

    def readiness(self) -> dict[str, Any]:
        try:
            return self._readiness_checks()
        except RunError:
            self._capture_worker_logs()
            raise

    def _readiness_checks(self) -> dict[str, Any]:
        readiness_started = time.monotonic()
        if not self.started or self.host_process is None or self.broker_process is None:
            raise RunError("U1 composition was not started")
        if (
            self.host_process.poll() is not None
            or self.broker_process.poll() is not None
        ):
            raise RunError("Host or broker exited before readiness")
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            health = _command_bytes(
                [
                    "docker",
                    "exec",
                    self.container_name,
                    "curl",
                    "-sf",
                    "-u",
                    "opencode:openworker-local",
                    "http://127.0.0.1:4096/global/health",
                ],
                timeout=10,
                check=False,
            )
            if health.returncode == 0:
                break
            if _docker_absent("container", self.container_name):
                raise RunError("OpenWorker exited before readiness")
            time.sleep(0.25)
        else:
            self._capture_worker_logs()
            raise RunError("OpenWorker health readiness timeout")
        listed = _command_bytes(
            [
                "docker",
                "exec",
                "--workdir",
                "/openworker/runtime",
                "--env",
                "OPENCODE_CONFIG_DIR=/openworker/runtime",
                self.container_name,
                "opencode",
                "mcp",
                "list",
            ],
            timeout=45,
            check=False,
        )
        combined_output = listed.stdout + b"\n" + listed.stderr
        ansi_stripped_text = _ansi_stripped_text(combined_output)
        normalized = ansi_stripped_text.casefold()
        connected = (
            "milai" in normalized
            and re.search(r"(?<![a-z])connected(?![a-z])", normalized) is not None
        )
        detected_state_tokens = [
            token
            for token in ("connected", "disconnected", "failed", "timeout", "error")
            if re.search(rf"(?<![a-z]){token}(?![a-z])", normalized)
        ]
        diagnostic_redactions = [
            value
            for value in (
                self.ingress_token,
                self.runtime.reader_token,
                *(
                    _case_prompt_redactions(self.case)
                    if self.case.case_id in _IMPLEMENTED_REAL_CASES
                    else ()
                ),
            )
            if value is not None
        ]
        diagnostic = {
            "schema": "milai.dg13u.u1-readiness-diagnostic.v1",
            "run_id": self.paths.run_id,
            "case_id": self.case.case_id,
            "stage": "OPENWORKER_MCP_LIST",
            "status": (
                TerminalStatus.PASS
                if listed.returncode == 0 and connected
                else TerminalStatus.FAIL
            ),
            "exit_code": listed.returncode,
            "allowlisted_observation": {
                "detected_mcp_names": ["milai"] if "milai" in normalized else [],
                "detected_state_tokens": detected_state_tokens,
                "line_count": len(normalized.splitlines()),
                "reason_code": (
                    "MCP_LIST_EXIT_NONZERO"
                    if listed.returncode != 0
                    else "MCP_CONNECTED"
                    if connected
                    else "MCP_CONNECTION_STATUS_NOT_CONNECTED"
                ),
            },
            "redacted_text": _allowlisted_mcp_diagnostic(
                ansi_stripped_text,
                redactions=diagnostic_redactions,
            ),
            "stdout": {
                "bytes": len(listed.stdout),
                "sha256": hashlib.sha256(listed.stdout).hexdigest(),
            },
            "stderr": {
                "bytes": len(listed.stderr),
                "sha256": hashlib.sha256(listed.stderr).hexdigest(),
            },
        }
        if len(u0._canonical_bytes(diagnostic)) >= 16 * 1024:
            raise RunError("redacted MCP readiness diagnostic exceeded 16 KiB")
        _atomic_write(self.paths.durable / "readiness-diagnostic.json", diagnostic)
        if listed.returncode != 0:
            raise RunError("OpenWorker MCP list command failed")
        if not connected:
            raise RunError("OpenWorker reader-lite MCP is not connected")
        self._wait_worker_bootstrap_quiescent()
        security = self._security_identity()
        self._capture_worker_logs()
        openworker_started_at = self._openworker_started_at or readiness_started
        self.readiness_latencies_ms["openworker"] = round(
            (time.monotonic() - openworker_started_at) * 1000, 3
        )
        provider_completion_calls = sum(
            row.get("event") == "PROVIDER_TERMINAL"
            for row in _read_json_lines(self.provider_ledger)
        )
        if provider_completion_calls != 0:
            raise RunError("provider completion occurred during readiness")
        return {
            "runtime": "PASS",
            "broker": "PASS",
            "host": "PASS",
            "openworker": "PASS",
            "provider": "PASS_IDENTITY_ONLY_ZERO_COMPLETIONS",
            "security": security,
            "provider_completion_calls": provider_completion_calls,
            "latencies_ms": dict(self.readiness_latencies_ms),
            "worker_health_sha256": hashlib.sha256(health.stdout).hexdigest(),
            "mcp_list_sha256": hashlib.sha256(
                listed.stdout + listed.stderr
            ).hexdigest(),
        }

    def _security_identity(self) -> dict[str, Any]:
        inspected = u0._run_json(
            ["docker", "container", "inspect", self.container_name]
        )
        network = u0._run_json(["docker", "network", "inspect", self.network_name])
        if (
            not isinstance(inspected, list)
            or len(inspected) != 1
            or not isinstance(network, list)
            or len(network) != 1
        ):
            raise RunError("OpenWorker security identity is ambiguous")
        container = inspected[0]
        network_row = network[0]
        host = container.get("HostConfig") or {}
        config = container.get("Config") or {}
        mounts = container.get("Mounts") or []
        environment = config.get("Env") or []
        forbidden_environment = [
            value.split("=", 1)[0]
            for value in environment
            if value.startswith("MILAI_")
            or any(marker in value.split("=", 1)[0] for marker in ("DATABASE", "DSN"))
        ]
        socket_mounts = [
            row
            for row in mounts
            if row.get("Destination") == "/run/milai-mcp/reader-lite.sock"
        ]
        valid = (
            host.get("NetworkMode") == self.network_name
            and "ALL" in (host.get("CapDrop") or [])
            and any(
                "no-new-privileges" in value for value in host.get("SecurityOpt") or []
            )
            and network_row.get("Internal") is True
            and len(socket_mounts) == 1
            and socket_mounts[0].get("RW") is False
            and not forbidden_environment
            and all(row.get("Destination") != "/var/run/docker.sock" for row in mounts)
        )
        if not valid:
            raise RunError("OpenWorker isolation boundary is invalid")
        return {
            "status": TerminalStatus.PASS,
            "network_internal": True,
            "network_mode_sha256": hashlib.sha256(
                self.network_name.encode()
            ).hexdigest(),
            "cap_drop_all": True,
            "no_new_privileges": True,
            "reader_lite_socket_read_only": True,
            "docker_socket_mounted": False,
            "forbidden_environment_names": forbidden_environment,
        }

    def _capture_worker_logs(self) -> None:
        completed = _command_bytes(
            ["docker", "logs", self.container_name], timeout=30, check=False
        )
        redactions = [
            value
            for value in (
                self.ingress_token,
                self.runtime.reader_token,
                *(
                    _case_prompt_redactions(self.case)
                    if self.case.case_id in _IMPLEMENTED_REAL_CASES
                    else ()
                ),
            )
            if value is not None
        ]
        diagnostic = _bounded_redacted_diagnostic(
            completed.stdout + completed.stderr,
            redactions=redactions,
            limit=12 * 1024,
        )
        payload = {
            "schema": "milai.dg13u.u1-worker-log.v1",
            "run_id": self.paths.run_id,
            "case_id": self.case.case_id,
            "status": "CAPTURED",
            **diagnostic,
        }
        if len(u0._canonical_bytes(payload)) >= 16 * 1024:
            raise RunError("redacted OpenWorker diagnostic exceeded 16 KiB")
        _atomic_write(self.worker_log, payload)

    def _write_smoke_command_diagnostic(
        self,
        completed: subprocess.CompletedProcess[bytes],
        *,
        prompt: str,
    ) -> SmokeCommandTruth:
        ansi_stripped_stdout = _ansi_stripped_text(completed.stdout)
        ansi_stripped_stderr = _ansi_stripped_text(completed.stderr)
        typed_error_lines = _top_level_opencode_typed_error_lines(ansi_stripped_stdout)
        typed_error_observed = bool(typed_error_lines)
        truth = SmokeCommandTruth(
            status=(
                TerminalStatus.FAIL
                if completed.returncode != 0 or typed_error_observed
                else TerminalStatus.PASS
            ),
            reason_code=(
                "OPENCODE_TYPED_ERROR"
                if typed_error_observed
                else "OPENCODE_EXIT_NONZERO"
                if completed.returncode != 0
                else "OPENCODE_EXIT_ZERO_NO_TYPED_ERROR"
            ),
            exit_code=completed.returncode,
            typed_error_count=len(typed_error_lines),
        )
        diagnostic_text = "\n".join(typed_error_lines)
        if ansi_stripped_stderr:
            diagnostic_text += ("\n" if diagnostic_text else "") + ansi_stripped_stderr
        redactions = [
            value
            for value in (self.ingress_token, self.runtime.reader_token, prompt)
            if value is not None
        ]
        payload = {
            "schema": "milai.dg13u.u1-smoke-command-diagnostic.v1",
            "run_id": self.paths.run_id,
            "case_id": self.case.case_id,
            "stage": "OPENCODE_RUN",
            "status": truth.status,
            "reason_code": truth.reason_code,
            "exit_code": truth.exit_code,
            "typed_error_count": truth.typed_error_count,
            "stdout": {
                "bytes": len(completed.stdout),
                "sha256": hashlib.sha256(completed.stdout).hexdigest(),
            },
            "stderr": {
                "bytes": len(completed.stderr),
                "sha256": hashlib.sha256(completed.stderr).hexdigest(),
            },
            "redacted_text": _allowlisted_smoke_command_diagnostic(
                diagnostic_text,
                redactions=redactions,
            ),
        }
        if len(u0._canonical_bytes(payload)) >= 16 * 1024:
            raise RunError("redacted smoke command diagnostic exceeded 16 KiB")
        _atomic_write(
            self.paths.durable / "smoke-command-diagnostic.json",
            payload,
        )
        return truth

    def _stop_fault_fixture(self) -> None:
        failures: list[BaseException] = []
        for fixture in (
            self.fault_broker,
            self.fault_mcp,
            self.fault_runtime,
            self.fault_provider,
        ):
            if fixture is None:
                continue
            try:
                fixture.stop()
            except BaseException as exc:  # noqa: BLE001 - one bounded cleanup error
                failures.append(exc)
        if failures:
            raise RunError("fault fixture cleanup failed") from failures[0]

    @staticmethod
    def _scenario_digest(value: object) -> str:
        return hashlib.sha256(u0._canonical_bytes(value)).hexdigest()

    def _create_opencode_session(
        self,
        *,
        reserved_session_ids: Sequence[str] = (),
    ) -> str:
        """Create one attached-CLI session without persisting its raw identity."""

        previous_ledger = _read_json_lines(self.provider_ledger)
        previous_trace = _read_json_lines(self.host_trace)
        try:
            command = task_scenarios.build_opencode_session_create_command(
                self.container_name
            )
        except task_scenarios.TaskScenarioError as exc:
            raise RunError("OpenCode session-create command is invalid") from exc
        completed = _command_bytes(list(command), timeout=30, check=False)
        if completed.returncode != 0:
            raise RunError("OpenCode session creation failed")
        try:
            session_id = task_scenarios.parse_created_opencode_session(completed.stdout)
        except task_scenarios.TaskScenarioError as exc:
            raise RunError("OpenCode session-create response is invalid") from exc
        if session_id in reserved_session_ids:
            raise RunError("OpenCode session creation reused an active identity")
        if (
            _read_json_lines(self.provider_ledger) != previous_ledger
            or _read_json_lines(self.host_trace) != previous_trace
        ):
            raise RunError("OpenCode session creation consumed a provider or MCP call")
        return session_id

    def _lifecycle_step(
        self,
        step: lifecycle_scenarios.LifecycleStep,
        observation: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "step_id": step.step_id,
            "status": "COMPLETED",
            "attempts": 1,
            "receipt_sha256": self._scenario_digest(
                {"step_id": step.step_id, "observation": dict(observation)}
            ),
        }

    def _execute_lifecycle_exact_turn(
        self,
        turn: task_scenarios.TurnSpec,
        *,
        prompt: str,
        known_sessions: Mapping[str, str],
        previous_ledger: Sequence[Mapping[str, Any]],
        trace_path: Path,
        previous_trace: Sequence[Mapping[str, Any]],
        expected_relation: str,
    ) -> dict[str, Any]:
        created_session_id = (
            self._create_opencode_session(
                reserved_session_ids=tuple(known_sessions.values())
            )
            if turn.session_action == "NEW"
            else None
        )
        try:
            command = task_scenarios.build_opencode_command(
                turn,
                container_name=self.container_name,
                prompt=prompt,
                known_sessions=known_sessions,
                created_session_id=created_session_id,
            )
        except task_scenarios.TaskScenarioError as exc:
            raise RunError("lifecycle OpenCode command is invalid") from exc
        started = time.monotonic()
        completed = _command_bytes(list(command), timeout=240, check=False)
        latency_ms = round((time.monotonic() - started) * 1000, 3)
        if (
            self._write_smoke_command_diagnostic(
                completed,
                prompt=prompt,
            ).status
            is not TerminalStatus.PASS
        ):
            raise RunError("lifecycle OpenCode terminal failed")
        try:
            session_id, event_evidence = task_scenarios.parse_opencode_session_events(
                completed.stdout
            )
            updated_sessions = task_scenarios.bind_observed_session(
                turn,
                session_id,
                known_sessions,
                created_session_id=created_session_id,
            )
        except task_scenarios.TaskScenarioError as exc:
            raise RunError("lifecycle OpenCode session evidence is invalid") from exc

        current_ledger = _read_json_lines(self.provider_ledger)
        current_trace = _read_json_lines(trace_path)
        if current_ledger[: len(previous_ledger)] != list(
            previous_ledger
        ) or current_trace[: len(previous_trace)] != list(previous_trace):
            raise RunError("lifecycle append-only accounting changed")
        ledger_delta = current_ledger[len(previous_ledger) :]
        trace_delta = current_trace[len(previous_trace) :]
        reservations = [row for row in ledger_delta if row.get("event") == "RESERVED"]
        terminals = [
            row for row in ledger_delta if row.get("event") == "PROVIDER_TERMINAL"
        ]
        attempts = [
            row for row in trace_delta if row.get("event") == "HOST_MCP_PREPARE_ATTEMPT"
        ]
        prepares = [
            row for row in trace_delta if row.get("event") == "HOST_MCP_PREPARE_CONTEXT"
        ]
        answers = [row for row in trace_delta if row.get("event") == "PROVIDER_ANSWER"]
        observations = [
            row
            for row in trace_delta
            if row.get("event") == "HOST_NATIVE_REQUEST_OBSERVED"
        ]
        bindings = [
            row for row in trace_delta if row.get("event") == "HOST_NATIVE_TASK_BOUND"
        ]
        shadows = [
            row for row in trace_delta if row.get("event") == "HOST_TASK_STATE_SHADOW"
        ]
        if any(
            row.get("event")
            in {"HOST_INGRESS_TERMINAL", "PROVIDER_MEMORY_TOOL_VISIBLE"}
            for row in trace_delta
        ) or any(
            len(rows) != 1
            for rows in (
                reservations,
                terminals,
                attempts,
                prepares,
                answers,
                observations,
                bindings,
                shadows,
            )
        ):
            raise RunError("lifecycle exact turn call accounting failed")
        reservation = reservations[0]
        terminal = terminals[0]
        attempt = attempts[0]
        prepare = prepares[0]
        answer = answers[0]
        observation = observations[0]
        binding = bindings[0]
        shadow = shadows[0]
        outcome = prepare.get("access_outcome")
        terminal_stage = (
            outcome.get("terminal_stage") if isinstance(outcome, Mapping) else None
        )
        recall_execution_trace = prepare.get("recall_execution_trace")
        timing = prepare.get("timing")
        if not isinstance(timing, Mapping):
            timing = {}
        logical_id = answer.get("logical_request_id")
        context_sha256 = answer.get("context_sha256")
        slot_key = shadow.get("task_key")
        session_sha256 = event_evidence.get("session_id_sha256")
        task_sha256 = binding.get("task_id_sha256")
        operation_sha256 = observation.get("task_operation_sha256")
        if (
            attempt.get("logical_mcp_calls") != 1
            or prepare.get("prepare_status") != "READY"
            or (prepare.get("route") != "EXACT" and terminal_stage != "EXACT")
            or not isinstance(outcome, Mapping)
            or not isinstance(recall_execution_trace, Mapping)
            or prepare.get("current_state_status") not in {"HIT", "READY"}
            or not isinstance(prepare.get("current_state_claim_count"), int)
            or isinstance(prepare.get("current_state_claim_count"), bool)
            or int(prepare["current_state_claim_count"]) < 1
            or terminal.get("status") != "SUCCEEDED"
            or not isinstance(terminal.get("native_request_id"), str)
            or terminal.get("native_request_id") != answer.get("native_request_id")
            or reservation.get("logical_request_id") != logical_id
            or terminal.get("logical_request_id") != logical_id
            or answer.get("mcp_calls") != 1
            or answer.get("context_in_prompt") is not True
            or answer.get("ordinary_tool_count") != 0
            or not isinstance(prepare.get("compiled_memory_tokens"), int)
            or isinstance(prepare.get("compiled_memory_tokens"), bool)
            or int(prepare["compiled_memory_tokens"]) <= 0
            or observation.get("tool_count") != 1
            or observation.get("task_session_sha256") != session_sha256
            or binding.get("task_session_sha256") != session_sha256
            or binding.get("task_operation_sha256") != operation_sha256
            or binding.get("task_relation") != expected_relation
            or not isinstance(task_sha256, str)
            or not isinstance(operation_sha256, str)
            or not isinstance(slot_key, str)
            or re.fullmatch(r"[0-9a-f]{64}", slot_key) is None
            or not isinstance(context_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", context_sha256) is None
            or not isinstance(answer.get("trace_id"), str)
        ):
            raise RunError("lifecycle exact turn identity binding failed")
        return {
            "session_id": session_id,
            "known_sessions": updated_sessions,
            "event_evidence": event_evidence,
            "ledger": current_ledger,
            "trace": current_trace,
            "trace_delta": trace_delta,
            "logical_request_id": logical_id,
            "native_request_id": terminal.get("native_request_id"),
            "access_outcome": outcome,
            "recall_execution_trace": recall_execution_trace,
            "trace_id": answer.get("trace_id"),
            "session_sha256": session_sha256,
            "task_sha256": task_sha256,
            "operation_sha256": operation_sha256,
            "slot_key": slot_key,
            "context_sha256": context_sha256,
            "task_relation": binding.get("task_relation"),
            "prepare_status": prepare.get("prepare_status"),
            "route": "EXACT",
            "compiled_memory_tokens": int(prepare["compiled_memory_tokens"]),
            "current_state_status": prepare.get("current_state_status"),
            "current_state_claim_count": int(prepare["current_state_claim_count"]),
            "registry_revision_before": shadow.get("registry_revision_before"),
            "retained_slot_present": shadow.get("retained_slot_present"),
            "latency_ms": latency_ms,
            "latencies_ms": {
                "openworker": latency_ms,
                "adapter": _nonnegative_measured_ms(answer.get("adapter_total_ms")),
                "mcp": _nonnegative_measured_ms(timing.get("mcp_handler_ms")),
                "runtime": _nonnegative_measured_ms(timing.get("runtime_total_ms")),
                "compile": _nonnegative_measured_ms(timing.get("context_compile_ms")),
                "provider": _nonnegative_measured_ms(
                    answer.get("provider_prefill_answer_ms")
                ),
            },
            "output_sha256": hashlib.sha256(
                completed.stdout + completed.stderr
            ).hexdigest(),
            "output_bytes": len(completed.stdout) + len(completed.stderr),
        }

    def _smoke_broker_lifecycle(self) -> dict[str, Any]:
        if self._resources is None:
            raise RunError("lifecycle resource registry is absent")
        scenario = lifecycle_scenarios.scenario_for_case(self.case.case_id)
        if scenario.execution_class != "BROKER_WORKER_BIND_RECREATE":
            raise RunError("broker lifecycle execution class drifted")
        if (
            self.broker_process is None
            or self.broker_marker is None
            or self.socket_identity is None
        ):
            raise RunError("broker lifecycle old identity is absent")
        previous_ledger = _read_json_lines(self.provider_ledger)
        previous_trace = _read_json_lines(self.host_trace)
        old_policy_sha256 = u0._sha256_file(self.policy_path)
        old_process_sha256 = lifecycle_scenarios.process_identity_sha256(
            self.broker_process.pid,
            self.broker_marker,
            f"broker:{self.broker_generation}",
        )
        old_socket_sha256 = lifecycle_scenarios.socket_identity_sha256(
            *self.socket_identity
        )
        old_worker_bind = self._worker_mount_identity()
        old_worker_bind_sha256 = lifecycle_scenarios.socket_identity_sha256(
            *old_worker_bind
        )
        old_worker_process_sha256 = self._worker_process_identity_sha256()
        if old_worker_bind_sha256 != old_socket_sha256:
            raise RunError("old OpenWorker bind does not match broker socket")
        steps = [
            self._lifecycle_step(
                scenario.steps[0],
                {
                    "policy_sha256": old_policy_sha256,
                    "process_sha256": old_process_sha256,
                    "socket_sha256": old_socket_sha256,
                    "worker_bind_sha256": old_worker_bind_sha256,
                },
            )
        ]

        old_process, old_marker = self._stop_broker_for_replacement()
        steps.append(
            self._lifecycle_step(
                scenario.steps[1],
                {"old_process_sha256": old_process_sha256, "stopped": True},
            )
        )
        unavailable_after_stop = self._worker_bound_socket_unavailable()
        if not unavailable_after_stop:
            raise RunError("old OpenWorker bind remained available after broker stop")
        steps.append(
            self._lifecycle_step(
                scenario.steps[2],
                {"old_worker_bind_unavailable": True},
            )
        )

        replacement_socket = self._start_broker_replacement(
            self._resources,
            old_process,
            old_marker,
        )
        assert self.broker_process is not None and self.broker_marker is not None
        replacement_policy_sha256 = u0._sha256_file(self.policy_path)
        replacement_process_sha256 = lifecycle_scenarios.process_identity_sha256(
            self.broker_process.pid,
            self.broker_marker,
            f"broker:{self.broker_generation}",
        )
        replacement_socket_sha256 = lifecycle_scenarios.socket_identity_sha256(
            *replacement_socket
        )
        if (
            replacement_policy_sha256 != old_policy_sha256
            or replacement_process_sha256 == old_process_sha256
            or replacement_socket_sha256 == old_socket_sha256
        ):
            raise RunError("replacement broker identity did not change exactly")
        steps.append(
            self._lifecycle_step(
                scenario.steps[3],
                {
                    "policy_sha256": replacement_policy_sha256,
                    "process_sha256": replacement_process_sha256,
                    "socket_sha256": replacement_socket_sha256,
                },
            )
        )
        stale_worker_bind = self._worker_mount_identity()
        old_worker_followed = (
            lifecycle_scenarios.socket_identity_sha256(*stale_worker_bind)
            == replacement_socket_sha256
            or not self._worker_bound_socket_unavailable()
        )
        if stale_worker_bind != old_worker_bind or old_worker_followed:
            raise RunError("old OpenWorker silently followed replacement broker")
        steps.append(
            self._lifecycle_step(
                scenario.steps[4],
                {"new_inode": True, "old_worker_followed": False},
            )
        )

        self._recreate_worker()
        replacement_worker_process_sha256 = self._worker_process_identity_sha256()
        recreated_bind = self._worker_mount_identity()
        recreated_bind_sha256 = lifecycle_scenarios.socket_identity_sha256(
            *recreated_bind
        )
        worker_recreated = (
            replacement_worker_process_sha256 != old_worker_process_sha256
            and recreated_bind_sha256 == replacement_socket_sha256
        )
        if not worker_recreated:
            raise RunError("replacement OpenWorker did not remount new broker inode")
        steps.append(
            self._lifecycle_step(
                scenario.steps[5],
                {"worker_recreated": True, "bind_sha256": recreated_bind_sha256},
            )
        )
        readiness_started = time.monotonic()
        health_sha256 = self._wait_worker_health()
        catalog_sha256 = self._mcp_catalog_readiness()
        lifecycle_readiness_ms = round(
            (time.monotonic() - readiness_started) * 1000,
            3,
        )
        steps.append(
            self._lifecycle_step(
                scenario.steps[6],
                {
                    "health_sha256": health_sha256,
                    "catalog_sha256": catalog_sha256,
                },
            )
        )
        if (
            _read_json_lines(self.provider_ledger) != previous_ledger
            or _read_json_lines(self.host_trace) != previous_trace
        ):
            raise RunError(
                "broker lifecycle readiness consumed prepare or provider calls"
            )
        generations = resource_registry.process_snapshot_by_role(
            self._resources.snapshot()
        )
        current = generations.get("mcp-broker")
        if (
            current is None
            or current.pid != self.broker_process.pid
            or current.marker != self.broker_marker
            or current.generation != self.broker_generation
        ):
            raise RunError("replacement broker registry generation is not current")
        measurement: dict[str, object] = {
            "schema": lifecycle_scenarios.MEASUREMENT_SCHEMA,
            "case_id": self.case.case_id,
            "execution_class": scenario.execution_class,
            "steps": steps,
            "mcp_calls": 0,
            "provider_calls": 0,
            "automatic_retries": 0,
            "readiness_calls": {"host_health": 0, "mcp_catalog": 1},
            "vllm": None,
            "cleanup": None,
            "identity": {
                "old_policy_sha256": old_policy_sha256,
                "replacement_policy_sha256": replacement_policy_sha256,
                "old_broker_process_sha256": old_process_sha256,
                "replacement_broker_process_sha256": replacement_process_sha256,
                "old_socket_identity_sha256": old_socket_sha256,
                "old_worker_bind_identity_sha256": old_worker_bind_sha256,
                "replacement_socket_identity_sha256": replacement_socket_sha256,
                "recreated_worker_bind_identity_sha256": recreated_bind_sha256,
                "old_broker_stopped": True,
                "old_worker_bind_unavailable_after_stop": unavailable_after_stop,
                "old_worker_followed_replacement": False,
                "worker_recreated_and_remounted": worker_recreated,
                "mcp_catalog_readiness_restored": True,
            },
        }
        self.lifecycle_measurement = measurement
        return {
            "observed_provider_calls": 0,
            "observed_mcp_calls": 0,
            "provider_terminal_status": None,
            "automatic_retries": 0,
            "mcp_automatic_retries": 0,
            "unaccounted_mcp_calls": 0,
            "unaccounted_provider_calls": 0,
            "memory_route": "NOT_INVOKED_LIFECYCLE",
            "context_tokens": 0,
            "model_visible_memory_tool_events": 0,
            "raw_prompt_or_answer_persisted": False,
            "worker_exit_code": 0,
            "worker_output_sha256": catalog_sha256,
            "worker_output_bytes": 0,
            "latencies_ms": {
                "openworker": lifecycle_readiness_ms,
                "adapter": 0.0,
                "mcp": 0.0,
                "runtime": 0.0,
                "compile": 0.0,
                "provider": 0.0,
            },
            "lifecycle_measurement_sha256": self._scenario_digest(measurement),
            "safety_failures": {name: 0 for name in self.case.safety_counters},
        }

    def _smoke_adapter_lifecycle(self) -> dict[str, Any]:
        if self._resources is None:
            raise RunError("lifecycle resource registry is absent")
        scenario = lifecycle_scenarios.scenario_for_case(self.case.case_id)
        if scenario.execution_class != "OPENWORKER_HOST_GENERATION_RESTART":
            raise RunError("adapter lifecycle execution class drifted")
        if (
            self.host_process is None
            or self.host_marker is None
            or self.gateway is None
            or self.host_port is None
        ):
            raise RunError("adapter lifecycle old identity is absent")
        prompt = _case_prompt(self.case)
        old_trace_path = self.host_trace
        previous_ledger = _read_json_lines(self.provider_ledger)
        previous_trace = _read_json_lines(old_trace_path)
        warm_turn = task_scenarios.TurnSpec("WARM", "A", "NEW")
        warm = self._execute_lifecycle_exact_turn(
            warm_turn,
            prompt=prompt,
            known_sessions={},
            previous_ledger=previous_ledger,
            trace_path=old_trace_path,
            previous_trace=previous_trace,
            expected_relation="TASK_START",
        )
        steps = [
            self._lifecycle_step(
                scenario.steps[0],
                {
                    "session_sha256": warm["session_sha256"],
                    "task_sha256": warm["task_sha256"],
                    "operation_sha256": warm["operation_sha256"],
                    "output_sha256": warm["output_sha256"],
                },
            )
        ]
        warm_openworker_process_sha256 = self._worker_process_identity_sha256()
        old_host_process_sha256 = lifecycle_scenarios.process_identity_sha256(
            self.host_process.pid,
            self.host_marker,
            f"host:{self.host_generation}",
        )
        old_generation_sha256 = self._scenario_digest(
            ["host-generation", self.host_generation, old_host_process_sha256]
        )
        old_slot_sha256 = self._scenario_digest(
            ["host-slot", self.host_generation, warm["slot_key"]]
        )
        endpoint_sha256 = self._scenario_digest(["http", self.gateway, self.host_port])
        steps.append(
            self._lifecycle_step(
                scenario.steps[1],
                {
                    "openworker_process_sha256": warm_openworker_process_sha256,
                    "host_process_sha256": old_host_process_sha256,
                    "generation_sha256": old_generation_sha256,
                    "slot_sha256": old_slot_sha256,
                },
            )
        )

        old_process, old_marker = self._stop_host_for_replacement()
        steps.append(
            self._lifecycle_step(
                scenario.steps[2],
                {"host_process_sha256": old_host_process_sha256, "stopped": True},
            )
        )
        replacement_trace = self._start_host_replacement(
            self._resources,
            old_process,
            old_marker,
        )
        assert self.host_process is not None and self.host_marker is not None
        replacement_host_process_sha256 = lifecycle_scenarios.process_identity_sha256(
            self.host_process.pid,
            self.host_marker,
            f"host:{self.host_generation}",
        )
        replacement_generation_sha256 = self._scenario_digest(
            [
                "host-generation",
                self.host_generation,
                replacement_host_process_sha256,
            ]
        )
        if replacement_host_process_sha256 == old_host_process_sha256:
            raise RunError("replacement Host process generation did not change")
        steps.append(
            self._lifecycle_step(
                scenario.steps[3],
                {
                    "host_process_sha256": replacement_host_process_sha256,
                    "generation_sha256": replacement_generation_sha256,
                    "endpoint_sha256": endpoint_sha256,
                },
            )
        )
        self._wait_host_ready()
        continuation_openworker_process_sha256 = self._worker_process_identity_sha256()
        if continuation_openworker_process_sha256 != warm_openworker_process_sha256:
            raise RunError("OpenWorker changed during Host replacement")
        steps.append(
            self._lifecycle_step(
                scenario.steps[4],
                {
                    "replacement_health_ready": True,
                    "openworker_process_sha256": continuation_openworker_process_sha256,
                },
            )
        )
        continuation_turn = task_scenarios.TurnSpec("CONTINUATION", "A", "CONTINUE")
        continuation = self._execute_lifecycle_exact_turn(
            continuation_turn,
            prompt=prompt,
            known_sessions=warm["known_sessions"],
            previous_ledger=warm["ledger"],
            trace_path=replacement_trace,
            previous_trace=[],
            expected_relation="TASK_START",
        )
        steps.append(
            self._lifecycle_step(
                scenario.steps[5],
                {
                    "session_sha256": continuation["session_sha256"],
                    "task_sha256": continuation["task_sha256"],
                    "operation_sha256": continuation["operation_sha256"],
                    "output_sha256": continuation["output_sha256"],
                },
            )
        )
        replacement_slot_sha256 = self._scenario_digest(
            ["host-slot", self.host_generation, continuation["slot_key"]]
        )
        logical_ids = [
            warm.get("logical_request_id"),
            continuation.get("logical_request_id"),
        ]
        if (
            warm["session_sha256"] != continuation["session_sha256"]
            or warm["task_sha256"] != continuation["task_sha256"]
            or continuation["registry_revision_before"] != 0
            or continuation["retained_slot_present"] is not False
            or old_slot_sha256 == replacement_slot_sha256
            or logical_ids
            != [f"{self.paths.run_id}-ow-01", f"{self.paths.run_id}-ow-02"]
        ):
            raise RunError(
                "replacement Host reused old task cache or provider sequence"
            )
        steps.append(
            self._lifecycle_step(
                scenario.steps[6],
                {
                    "task_start": True,
                    "prepare_ready": True,
                    "route_exact": True,
                    "old_cache_slot_reused": False,
                },
            )
        )
        generations = resource_registry.process_snapshot_by_role(
            self._resources.snapshot()
        )
        current = generations.get("host-adapter")
        if (
            current is None
            or current.pid != self.host_process.pid
            or current.marker != self.host_marker
            or current.generation != self.host_generation
        ):
            raise RunError("replacement Host registry generation is not current")
        identity = {
            "warm_openworker_process_sha256": warm_openworker_process_sha256,
            "continuation_openworker_process_sha256": (
                continuation_openworker_process_sha256
            ),
            "old_host_endpoint_sha256": endpoint_sha256,
            "replacement_host_endpoint_sha256": endpoint_sha256,
            "old_host_process_sha256": old_host_process_sha256,
            "replacement_host_process_sha256": replacement_host_process_sha256,
            "old_generation_sha256": old_generation_sha256,
            "replacement_generation_sha256": replacement_generation_sha256,
            "old_slot_sha256": old_slot_sha256,
            "replacement_slot_sha256": replacement_slot_sha256,
            "warm_task_session_sha256": warm["session_sha256"],
            "continuation_task_session_sha256": continuation["session_sha256"],
            "warm_task_id_sha256": warm["task_sha256"],
            "continuation_task_id_sha256": continuation["task_sha256"],
            "warm_context_sha256": warm["context_sha256"],
            "continuation_context_sha256": continuation["context_sha256"],
            "replacement_initial_registry_entry_count": 0,
            "old_host_stopped": True,
            "replacement_health_ready": True,
            "openworker_reconnected": True,
            "warm_task_relation": warm["task_relation"],
            "warm_prepare_status": warm["prepare_status"],
            "warm_route": warm["route"],
            "continuation_task_relation": continuation["task_relation"],
            "continuation_prepare_status": continuation["prepare_status"],
            "continuation_route": continuation["route"],
            "old_cache_slot_reused": False,
        }
        measurement: dict[str, object] = {
            "schema": lifecycle_scenarios.MEASUREMENT_SCHEMA,
            "case_id": self.case.case_id,
            "execution_class": scenario.execution_class,
            "steps": steps,
            "mcp_calls": 2,
            "provider_calls": 2,
            "automatic_retries": 0,
            "readiness_calls": {"host_health": 1, "mcp_catalog": 0},
            "vllm": None,
            "cleanup": None,
            "identity": identity,
        }
        self.lifecycle_measurement = measurement
        outputs_sha256 = self._scenario_digest(
            [warm["output_sha256"], continuation["output_sha256"]]
        )
        latencies_ms = {
            name: round(
                float(warm["latencies_ms"][name])
                + float(continuation["latencies_ms"][name]),
                3,
            )
            for name in (
                "openworker",
                "adapter",
                "mcp",
                "runtime",
                "compile",
                "provider",
            )
        }
        return {
            "observed_provider_calls": 2,
            "observed_mcp_calls": 2,
            "provider_terminal_status": "SUCCEEDED",
            "automatic_retries": 0,
            "mcp_automatic_retries": 0,
            "unaccounted_mcp_calls": 0,
            "unaccounted_provider_calls": 0,
            "memory_route": (
                "QUERY_FIRST"
                if self.case.case_id == "U1-TASK-CONTINUE"
                else "EXACT"
            ),
            "context_tokens": int(warm["compiled_memory_tokens"])
            + int(continuation["compiled_memory_tokens"]),
            "context_in_prompt": True,
            "current_state_status": warm["current_state_status"],
            "current_state_claim_count": min(
                int(warm["current_state_claim_count"]),
                int(continuation["current_state_claim_count"]),
            ),
            "access_id_sha256": self._scenario_digest(
                [warm["logical_request_id"], continuation["logical_request_id"]]
            ),
            "mcp_receipt_sha256": self._scenario_digest(
                [warm["access_outcome"], continuation["access_outcome"]]
            ),
            "runtime_trace_sha256": self._scenario_digest(
                [
                    warm["recall_execution_trace"],
                    continuation["recall_execution_trace"],
                ]
            ),
            "trace_id_sha256": self._scenario_digest(
                [warm["trace_id"], continuation["trace_id"]]
            ),
            "native_request_id_sha256": self._scenario_digest(
                [warm["native_request_id"], continuation["native_request_id"]]
            ),
            "model_visible_memory_tool_events": 0,
            "raw_prompt_or_answer_persisted": _durable_payload_observed(
                self.paths.durable,
                (prompt.encode(),),
            ),
            "worker_exit_code": 0,
            "worker_output_sha256": outputs_sha256,
            "worker_output_bytes": int(warm["output_bytes"])
            + int(continuation["output_bytes"]),
            "latencies_ms": latencies_ms,
            "lifecycle_measurement_sha256": self._scenario_digest(measurement),
            "safety_failures": {name: 0 for name in self.case.safety_counters},
        }

    def _smoke_lifecycle_scenario(self) -> dict[str, Any]:
        try:
            evidence = (
                self._smoke_broker_lifecycle()
                if self.case.case_id == "U1-BROKER-INODE-RECREATE"
                else self._smoke_adapter_lifecycle()
            )
            if evidence.get("raw_prompt_or_answer_persisted") is True:
                raise RunError("lifecycle prompt reached durable artifacts")
            self.smoke_evidence = evidence
            self._capture_worker_logs()
            return evidence
        except Exception as exc:
            try:
                self._capture_worker_logs()
            except RunError:
                pass
            if isinstance(exc, RunError):
                raise
            raise RunError("lifecycle scenario execution failed") from exc

    def _main_composition_observation(self) -> dict[str, object]:
        if (
            self.host_process is None
            or self.broker_process is None
            or self.host_process.poll() is not None
            or self.broker_process.poll() is not None
            or self.socket_identity is None
            or not self.socket_path.exists()
            or self.gateway is None
            or self.host_port is None
            or self.ingress_token is None
        ):
            raise RunError("main composition is unavailable during adjacent probe")
        current = self.socket_path.lstat()
        if (current.st_dev, current.st_ino) != self.socket_identity:
            raise RunError("main broker inode changed during adjacent probe")
        models = _wait_http_json(
            f"http://{self.gateway}:{self.host_port}/v1/models",
            token=self.ingress_token,
            seconds=5,
        )
        if [row.get("id") for row in models.get("data", [])] != [MODEL_ID]:
            raise RunError("main Host identity changed during adjacent probe")
        if any(
            row.get("event") in {"RESERVED", "PROVIDER_TERMINAL"}
            for row in _read_json_lines(self.provider_ledger)
        ):
            raise RunError("provider call occurred during adjacent probe readiness")
        return {
            "host_pid_marker_sha256": hashlib.sha256(
                f"{self.host_process.pid}:{self.host_marker}".encode()
            ).hexdigest(),
            "broker_pid_marker_sha256": hashlib.sha256(
                f"{self.broker_process.pid}:{self.broker_marker}".encode()
            ).hexdigest(),
            "socket_identity_sha256": self._scenario_digest(
                [current.st_dev, current.st_ino]
            ),
            "model_identity_sha256": hashlib.sha256(MODEL_ID.encode()).hexdigest(),
            "provider_calls": 0,
            "mcp_calls": 0,
        }

    def _authority_probe(self) -> dict[str, object]:
        if self.gateway is None or self.ingress_token is None:
            raise RunError("authority probe main Host identity is absent")
        try:
            policy = json.loads(self.policy_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RunError("authority probe policy source is unavailable") from exc
        if not isinstance(policy, dict) or policy.get("required_authority") != (
            "INFORMATIONAL"
        ):
            raise RunError("authority probe effective policy drifted")
        policy["required_authority"] = "ACTION_SAFE"
        probe_policy = self.paths.temporary / "authority-negative-policy.json"
        _atomic_write(probe_policy, policy)
        probe_ledger = self.paths.temporary / "authority-negative-ledger.jsonl"
        probe_trace = self.paths.temporary / "authority-negative-trace.jsonl"
        ingress_file = self.paths.temporary / "secrets/host-ingress.token"
        executable = self.product_venv / "bin/milai-openworker-adapter"
        completed = _command_bytes(
            [
                str(executable),
                "--manifest",
                str(self.provider_manifest),
                "--ledger",
                str(probe_ledger),
                "--trace",
                str(probe_trace),
                "--listen-host",
                self.gateway,
                "--listen-port",
                str(_free_bind_port(self.gateway)),
                "--memory-mode",
                "prefetch",
                "--prefetch-socket",
                str(self.socket_path),
                "--tokenizer-json",
                str(TOKENIZER_JSON),
                "--broker-policy",
                str(probe_policy),
                "--task-fixture",
                str(CANDIDATE_FIXTURE),
                "--ingress-token-file",
                str(ingress_file),
                "--provider-timeout-seconds",
                "5",
            ],
            timeout=30,
            check=False,
        )
        bounded = completed.stdout + completed.stderr
        if completed.returncode == 0 or b"HOST_STARTUP_POLICY_INVALID" not in bounded:
            raise RunError("elevated Host startup policy was not typed-rejected")
        if probe_ledger.exists() and _read_json_lines(probe_ledger):
            raise RunError("authority probe reached provider ledger")
        return {
            "requested_authority_sha256": hashlib.sha256(b"ACTION_SAFE").hexdigest(),
            "effective_authority_sha256": hashlib.sha256(b"INFORMATIONAL").hexdigest(),
            "policy_receipt_sha256": u0._sha256_file(probe_policy),
            "startup_rejected": True,
            "authority_widened": False,
            "exit_code": completed.returncode,
            "output_sha256": hashlib.sha256(bounded).hexdigest(),
        }

    def _alias_collision_probe(self) -> dict[str, object]:
        executable = self.product_venv / "bin/python"
        program = """
from milai_client import CanonicalStateKey, DeterministicMemoryNeedResolver, StateKeyAliasAmbiguousError
from milai_client import memory_need
memory_need._STATE_KEY_ALIAS_FAMILIES = (
    ("orchid-release", "release.target", "PROJECT_STATE", ("same alias",)),
    ("orchid-release", "release.database", "PROJECT_CONFIG", ("ＳＡＭＥ alias",)),
)
keys = (
    CanonicalStateKey("orchid-release", "release.target", "PROJECT_STATE"),
    CanonicalStateKey("orchid-release", "release.database", "PROJECT_CONFIG"),
)
try:
    DeterministicMemoryNeedResolver().resolve(
        "same alias",
        scope={"project_ids": ["orchid-release"]},
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        known_state_keys=keys,
    )
except StateKeyAliasAmbiguousError:
    print("STATE_KEY_ALIAS_AMBIGUOUS")
else:
    raise SystemExit(3)
""".strip()
        completed = _command_bytes(
            [str(executable), "-c", program],
            timeout=30,
            check=False,
        )
        if completed.returncode != 0 or completed.stdout.strip() != (
            b"STATE_KEY_ALIAS_AMBIGUOUS"
        ):
            raise RunError("normalized alias collision was not typed-rejected")
        owners = [
            ["orchid-release", "release.target", "PROJECT_STATE"],
            ["orchid-release", "release.database", "PROJECT_CONFIG"],
        ]
        return {
            "normalized_alias_sha256": hashlib.sha256(b"same alias").hexdigest(),
            "owner_set_sha256": self._scenario_digest(owners),
            "owner_count": 2,
            "alias_tie_broken": False,
            "exit_code": completed.returncode,
            "output_sha256": hashlib.sha256(
                completed.stdout + completed.stderr
            ).hexdigest(),
        }

    def _scenario_static_step(
        self,
        expected: cache_governance.StepExpectation,
        observation: Mapping[str, object],
    ) -> dict[str, object]:
        receipt_sha256 = self._scenario_digest(
            {"step_id": expected.step_id, "observation": observation}
        )
        return {
            "step_id": expected.step_id,
            "boundary": expected.boundary,
            "operation_sha256": self._scenario_digest(
                {"case_id": self.case.case_id, "step_id": expected.step_id}
            ),
            "session_sha256": None,
            "task_sha256": None,
            "requested_route": expected.requested_route,
            "attempted_routes": list(expected.attempted_routes),
            "terminal_route": expected.terminal_route,
            "route_result": expected.route_result,
            "fallback_reason": expected.fallback_reason,
            "prepare_status": expected.prepare_status,
            "reason_code": expected.reason_code,
            "access_status": expected.access_status,
            "execution_action": expected.execution_action,
            "provider_execution": expected.provider_execution,
            "mcp_calls": 0,
            "provider_calls": 0,
            "automatic_retries": 0,
            "l0_calls": 0,
            "exact_calls": 0,
            "query_embedding_calls": 0,
            "vector_calls": 0,
            "fts_calls": 0,
            "reranker_calls": 0,
            "receipt_sha256": receipt_sha256,
        }

    def _execute_cache_governance_turn(
        self,
        expected: cache_governance.StepExpectation,
        *,
        prompt: str,
        known_sessions: Mapping[str, str],
        previous_ledger: Sequence[Mapping[str, Any]],
        previous_trace: Sequence[Mapping[str, Any]],
    ) -> tuple[
        dict[str, object],
        dict[str, Any],
        dict[str, str],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        if expected.session_role == "NONE":
            raise RunError("Host-native scenario step has no session role")
        action = "CONTINUE" if expected.session_role in known_sessions else "NEW"
        turn = task_scenarios.TurnSpec(
            expected.step_id,
            expected.session_role,
            action,
        )
        created_session_id = (
            self._create_opencode_session(
                reserved_session_ids=tuple(known_sessions.values())
            )
            if action == "NEW"
            else None
        )
        try:
            command = task_scenarios.build_opencode_command(
                turn,
                container_name=self.container_name,
                prompt=prompt,
                known_sessions=known_sessions,
                created_session_id=created_session_id,
            )
        except task_scenarios.TaskScenarioError as exc:
            raise RunError("cache/governance OpenCode command is invalid") from exc
        started = time.monotonic()
        completed = _command_bytes(list(command), timeout=240, check=False)
        latency_ms = round((time.monotonic() - started) * 1000, 3)
        command_truth = self._write_smoke_command_diagnostic(
            completed,
            prompt=prompt,
        )
        if (
            completed.returncode != 0
            or command_truth.status is not TerminalStatus.PASS
            or command_truth.typed_error_count != 0
        ):
            raise RunError("cache/governance OpenCode terminal failed")
        empty_event_stream = completed.stdout == b""
        empty_pre_provider_terminal = (
            empty_event_stream and expected.provider_calls == 0
        )
        try:
            if empty_event_stream:
                session_id = (
                    created_session_id
                    if action == "NEW"
                    else known_sessions.get(expected.session_role)
                )
                if completed.stderr != b"" or not isinstance(session_id, str):
                    raise task_scenarios.TaskScenarioError(
                        "EMPTY_EVENTS_WITHOUT_BOUND_SESSION"
                    )
                event_evidence = {
                    "schema": task_scenarios.EVENT_EVIDENCE_SCHEMA,
                    "event_stream_sha256": hashlib.sha256(b"").hexdigest(),
                    "event_count": 0,
                    "typed_error_count": 0,
                    "session_id_sha256": hashlib.sha256(
                        session_id.encode()
                    ).hexdigest(),
                }
            else:
                session_id, event_evidence = (
                    task_scenarios.parse_opencode_session_events(completed.stdout)
                )
            updated_sessions = task_scenarios.bind_observed_session(
                turn,
                session_id,
                known_sessions,
                created_session_id=created_session_id,
            )
        except task_scenarios.TaskScenarioError as exc:
            raise RunError("cache/governance session evidence is invalid") from exc

        current_ledger = _read_json_lines(self.provider_ledger)
        current_trace = _read_json_lines(self.host_trace)
        if current_ledger[: len(previous_ledger)] != list(
            previous_ledger
        ) or current_trace[: len(previous_trace)] != list(previous_trace):
            raise RunError("cache/governance append-only accounting changed")
        ledger_delta = current_ledger[len(previous_ledger) :]
        trace_delta = current_trace[len(previous_trace) :]
        reservations = [row for row in ledger_delta if row.get("event") == "RESERVED"]
        terminals = [
            row for row in ledger_delta if row.get("event") == "PROVIDER_TERMINAL"
        ]
        attempts = [
            row for row in trace_delta if row.get("event") == "HOST_MCP_PREPARE_ATTEMPT"
        ]
        prepares = [
            row for row in trace_delta if row.get("event") == "HOST_MCP_PREPARE_CONTEXT"
        ]
        need_resolutions = [
            row
            for row in trace_delta
            if row.get("event") == "HOST_MEMORY_NEED_RESOLVED"
        ]
        answers = [row for row in trace_delta if row.get("event") == "PROVIDER_ANSWER"]
        observations = [
            row
            for row in trace_delta
            if row.get("event") == "HOST_NATIVE_REQUEST_OBSERVED"
        ]
        bindings = [
            row for row in trace_delta if row.get("event") == "HOST_NATIVE_TASK_BOUND"
        ]
        if any(
            row.get("event")
            in {
                "HOST_INGRESS_TERMINAL",
                "PROVIDER_MEMORY_TOOL_VISIBLE",
            }
            for row in trace_delta
        ):
            raise RunError("cache/governance turn reached a forbidden terminal")
        if (
            len(attempts) != expected.mcp_calls
            or len(prepares) != expected.mcp_calls
            or len(need_resolutions) != expected.mcp_calls
            or len(reservations) != expected.provider_calls
            or len(terminals) != expected.provider_calls
            or len(answers) != expected.provider_calls
            or len(observations) != 1
            or len(bindings) != 1
        ):
            raise RunError("cache/governance incremental call accounting failed")
        if any(row.get("logical_mcp_calls") != 1 for row in attempts):
            raise RunError("cache/governance logical MCP accounting failed")
        observation = observations[0]
        binding = bindings[0]
        session_sha256 = event_evidence.get("session_id_sha256")
        operation_sha256 = observation.get("task_operation_sha256")
        task_sha256 = binding.get("task_id_sha256")
        expected_relation = "CONTINUE" if action == "CONTINUE" else "TASK_START"
        if (
            observation.get("tool_count") != 1
            or observation.get("task_session_sha256") != session_sha256
            or binding.get("task_session_sha256") != session_sha256
            or binding.get("task_operation_sha256") != operation_sha256
            or binding.get("task_relation") != expected_relation
            or not isinstance(operation_sha256, str)
            or not isinstance(task_sha256, str)
        ):
            raise RunError("cache/governance native task binding failed")
        prepare = prepares[0]
        outcome = prepare.get("access_outcome")
        recall = prepare.get("recall_execution_trace")
        if not isinstance(outcome, Mapping) or not isinstance(recall, Mapping):
            raise RunError("cache/governance Runtime trace is absent")
        question_sha256 = observation.get("question_sha256")
        need_resolution = need_resolutions[0]
        scenario = cache_governance.scenario_for_case(self.case.case_id)
        requested_state_key = scenario.requested_state_key
        state_binding = _CACHE_GOVERNANCE_STATE_KEY_BINDINGS.get(
            requested_state_key or ""
        )
        expected_state_key_ref_sha256 = (
            hashlib.sha256(
                json.dumps(
                    {
                        "version": "state-key-ref-v1",
                        "scope": {"project_ids": [state_binding[0]]},
                        "subject": state_binding[0],
                        "predicate": requested_state_key,
                        "claim_type": state_binding[1],
                        "claim_id": None,
                        "relevant_open_issue_ids": [],
                        "canonical_position_seen": None,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            if state_binding is not None
            else None
        )
        if (
            not isinstance(question_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", question_sha256) is None
            or attempts[0].get("question_sha256") != question_sha256
            or prepare.get("question_sha256") != question_sha256
            or need_resolution.get("question_sha256") != question_sha256
            or state_binding is None
            or need_resolution.get("intent_class") != "CURRENT_STATE"
            or need_resolution.get("temporal_need") != "CURRENT"
            or need_resolution.get("evidence_need") != "SUPPORT_POINTERS"
            or need_resolution.get("resolver_route") != "L0"
            or need_resolution.get("requested_route") != expected.requested_route
            or need_resolution.get("state_key_ref_present") is not True
            or need_resolution.get("state_key_subject_sha256")
            != hashlib.sha256(state_binding[0].encode()).hexdigest()
            or need_resolution.get("state_key_predicate_sha256")
            != hashlib.sha256(str(requested_state_key).encode()).hexdigest()
            or need_resolution.get("state_key_claim_type_sha256")
            != hashlib.sha256(state_binding[1].encode()).hexdigest()
            or need_resolution.get("state_key_ref_sha256")
            != expected_state_key_ref_sha256
            or need_resolution.get("resolver_embedding_calls") != 0
            or need_resolution.get("resolver_retrieval_calls") != 0
            or need_resolution.get("resolver_model_calls") != 0
            or not isinstance(need_resolution.get("need_signature_id"), str)
            or re.fullmatch(
                r"need:[0-9a-f]{64}", str(need_resolution["need_signature_id"])
            )
            is None
            or recall.get("need_signature_id")
            != need_resolution.get("need_signature_id")
        ):
            raise RunError("cache/governance prompt binding failed")
        if empty_pre_provider_terminal:
            if (
                action != "NEW"
                or not isinstance(created_session_id, str)
                or expected.mcp_calls != 1
                or expected.prepare_status != "ABSTAIN"
                or expected.reason_code != "CANONICAL_GATE_REJECTED"
                or expected.access_status != "GOVERNANCE_BLOCKED"
                or expected.execution_action != "ABSTAIN"
                or expected.provider_execution != "PROHIBITED"
            ):
                raise RunError("cache/governance pre-provider terminal drifted")
            observed_terminal = {
                "requested_route": recall.get("requested_route"),
                "attempted_routes": list(recall.get("attempted_routes") or []),
                "terminal_route": recall.get("terminal_route"),
                "route_result": recall.get("result"),
                "fallback_reason": recall.get("fallback_reason"),
                "prepare_status": prepare.get("prepare_status"),
                "prepare_reason": prepare.get("prepare_reason"),
                "memory_status": prepare.get("memory_status"),
                "compiled_memory_bytes": prepare.get("compiled_memory_bytes"),
                "compiled_memory_tokens": prepare.get("compiled_memory_tokens"),
                "usage": prepare.get("usage"),
                "current_state_status": prepare.get("current_state_status"),
                "current_state_claim_count": prepare.get("current_state_claim_count"),
                "context_digest": outcome.get("context_digest"),
                "access_status": outcome.get("status"),
                "execution_action": outcome.get("execution_action"),
                "provider_execution": outcome.get("provider_execution"),
                "terminal_stage": outcome.get("terminal_stage"),
                "reason_code": outcome.get("reason_code"),
                "l0_calls": recall.get("l0_calls"),
                "exact_calls": recall.get("exact_calls"),
                "query_embedding_calls": recall.get("query_embedding_calls"),
                "vector_calls": recall.get("vector_calls"),
                "fts_calls": recall.get("fts_calls"),
                "reranker_calls": recall.get("reranker_calls"),
            }
            expected_terminal = {
                "requested_route": expected.requested_route,
                "attempted_routes": list(expected.attempted_routes),
                "terminal_route": expected.terminal_route,
                "route_result": expected.route_result,
                "fallback_reason": expected.fallback_reason,
                "prepare_status": expected.prepare_status,
                "prepare_reason": expected.reason_code,
                "memory_status": "UNAVAILABLE",
                "compiled_memory_bytes": None,
                "compiled_memory_tokens": None,
                "usage": None,
                "current_state_status": "BLOCKED",
                "current_state_claim_count": 0,
                "context_digest": None,
                "access_status": expected.access_status,
                "execution_action": expected.execution_action,
                "provider_execution": expected.provider_execution,
                "terminal_stage": "GATE",
                "reason_code": expected.reason_code,
                "l0_calls": expected.l0_calls,
                "exact_calls": expected.exact_calls,
                "query_embedding_calls": 0,
                "vector_calls": 0,
                "fts_calls": 0,
                "reranker_calls": 0,
            }
            if observed_terminal != expected_terminal:
                raise RunError("cache/governance pre-provider terminal drifted")
        if expected.provider_calls:
            terminal = terminals[0]
            answer = answers[0]
            logical_id = answer.get("logical_request_id")
            if (
                terminal.get("status") != "SUCCEEDED"
                or not isinstance(terminal.get("native_request_id"), str)
                or terminal.get("native_request_id") != answer.get("native_request_id")
                or reservations[0].get("logical_request_id") != logical_id
                or terminal.get("logical_request_id") != logical_id
                or answer.get("mcp_calls") != expected.mcp_calls
                or answer.get("context_in_prompt") is not True
                or answer.get("ordinary_tool_count") != 0
            ):
                raise RunError("cache/governance provider join failed")
        else:
            answer = {}
        route_result = (
            "ABSTAINED"
            if prepare.get("prepare_status") == "ABSTAIN"
            else recall.get("result")
        )
        step = {
            "step_id": expected.step_id,
            "boundary": expected.boundary,
            "operation_sha256": operation_sha256,
            "session_sha256": session_sha256,
            "task_sha256": task_sha256,
            "requested_route": recall.get("requested_route"),
            "attempted_routes": list(recall.get("attempted_routes") or []),
            "terminal_route": recall.get("terminal_route"),
            "route_result": route_result,
            "fallback_reason": recall.get("fallback_reason"),
            "prepare_status": prepare.get("prepare_status"),
            "reason_code": outcome.get("reason_code"),
            "access_status": outcome.get("status"),
            "execution_action": outcome.get("execution_action"),
            "provider_execution": outcome.get("provider_execution"),
            "mcp_calls": len(attempts),
            "provider_calls": len(reservations),
            "automatic_retries": 0,
            "l0_calls": recall.get("l0_calls"),
            "exact_calls": recall.get("exact_calls"),
            "query_embedding_calls": recall.get("query_embedding_calls"),
            "vector_calls": recall.get("vector_calls"),
            "fts_calls": recall.get("fts_calls"),
            "reranker_calls": recall.get("reranker_calls"),
            "receipt_sha256": self._scenario_digest(
                {
                    "event_evidence": event_evidence,
                    "observation": observation,
                    "binding": binding,
                    "attempts": attempts,
                    "need_resolution": need_resolution,
                    "prepare": prepare,
                    "reservations": reservations,
                    "terminals": terminals,
                    "answers": answers,
                    "exit_code": completed.returncode,
                    "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
                    "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
                }
            ),
        }
        detail = {
            "completed": completed,
            "latency_ms": latency_ms,
            "event_evidence": event_evidence,
            "observation": observation,
            "binding": binding,
            "attempts": attempts,
            "need_resolution": need_resolution,
            "prepare": prepare,
            "reservations": reservations,
            "terminals": terminals,
            "answers": answers,
            "trace_delta": trace_delta,
        }
        return step, detail, updated_sessions, current_ledger, current_trace

    def _cache_governance_invariants(
        self,
        *,
        details: Sequence[Mapping[str, Any]],
        mutation: Mapping[str, object] | None,
        adjacent: Mapping[str, object] | None,
    ) -> dict[str, object]:
        case_id = self.case.case_id
        if case_id in _CACHE_GOVERNANCE_ADJACENT_CASE_IDS:
            if adjacent is None:
                raise RunError("adjacent negative observation is absent")
            allowed = (
                {
                    "requested_authority_sha256",
                    "effective_authority_sha256",
                    "policy_receipt_sha256",
                    "startup_rejected",
                    "authority_widened",
                }
                if case_id == "U1-AUTHORITY-ESCALATION"
                else {
                    "normalized_alias_sha256",
                    "owner_set_sha256",
                    "owner_count",
                    "alias_tie_broken",
                }
            )
            return {name: adjacent[name] for name in allowed}
        if self.fixture is None or self.fixture.seeded is None:
            raise RunError("cache/governance canonical fixture is absent")
        seeded = self.fixture.seeded
        families = seeded.get("families")
        negatives = seeded.get("negative_setups")
        if not isinstance(families, list) or not isinstance(negatives, Mapping):
            raise RunError("cache/governance fixture receipt is invalid")

        if case_id in {"U1-CACHE-FALLBACK", "U1-STALE-CURRENT"}:
            if len(details) != 2 or mutation is None:
                raise RunError("post-warm scenario observation is incomplete")
            warm = details[0]
            refreshed = details[1]
            warm_prepare = warm["prepare"]
            refreshed_prepare = refreshed["prepare"]
            warm_outcome = warm_prepare.get("access_outcome")
            refreshed_outcome = refreshed_prepare.get("access_outcome")
            if not isinstance(warm_outcome, Mapping) or not isinstance(
                refreshed_outcome, Mapping
            ):
                raise RunError("post-warm access outcome is absent")
            warm_context = warm_outcome.get("context_digest")
            refreshed_context = refreshed_outcome.get("context_digest")
            before_position = warm_outcome.get("canonical_position")
            after_position = refreshed_outcome.get("canonical_position")
            if (
                not isinstance(warm_context, str)
                or not isinstance(refreshed_context, str)
                or not isinstance(before_position, int)
                or not isinstance(after_position, int)
            ):
                raise RunError("post-warm context or canonical position is absent")
            common = {
                "session_sha256": details[0]["event_evidence"]["session_id_sha256"],
                "task_sha256": details[0]["binding"]["task_id_sha256"],
                "canonical_before_sha256": self._scenario_digest(before_position),
                "canonical_after_sha256": self._scenario_digest(after_position),
                "requested_state_key_sha256": hashlib.sha256(
                    (
                        "release.database"
                        if case_id == "U1-CACHE-FALLBACK"
                        else "release.target"
                    ).encode()
                ).hexdigest(),
                "mutated_state_key_sha256": hashlib.sha256(
                    b"release.target"
                ).hexdigest(),
                "mutation_receipt_sha256": mutation["mutation_receipt_sha256"],
                "mutation_applied_post_warm": True,
                "seeded_snapshot_unchanged": mutation["seeded_snapshot_unchanged"],
                "mutation_cleanup_complete": False,
            }
            if case_id == "U1-CACHE-FALLBACK":
                return {
                    **common,
                    "warm_context_sha256": warm_context,
                    "fallback_context_sha256": refreshed_context,
                    "cache_miss_same_call_fallback": True,
                }
            return {
                **common,
                "warm_context_sha256": warm_context,
                "refreshed_context_sha256": refreshed_context,
                "same_composite_reprepare": True,
                "stale_slot_accepted": False,
            }
        if case_id == "U1-WRONG-TASK":
            if len(details) != 2:
                raise RunError("wrong-task observations are incomplete")
            return {
                "session_a_sha256": details[0]["event_evidence"]["session_id_sha256"],
                "session_b_sha256": details[1]["event_evidence"]["session_id_sha256"],
                "task_a_sha256": details[0]["binding"]["task_id_sha256"],
                "task_b_sha256": details[1]["binding"]["task_id_sha256"],
                "cross_task_slot_reused": False,
            }
        if len(details) != 1:
            raise RunError("single-turn governance observation is incomplete")
        detail = details[0]
        prepare = detail["prepare"]
        if case_id == "U1-WRONG-SCOPE":
            wrong = negatives.get("wrong_scope")
            canonical = next(
                (
                    row
                    for row in families
                    if isinstance(row, Mapping)
                    and row.get("state_key") == "release.target"
                ),
                None,
            )
            if not isinstance(wrong, Mapping) or not isinstance(canonical, Mapping):
                raise RunError("wrong-scope fixture binding is absent")
            outside_identifiers = {
                value
                for name in ("claim_id", "claim_version_id", "evidence_id")
                if isinstance((value := wrong.get(name)), str)
            }
            prepare_bytes = u0._canonical_bytes(prepare)
            output = detail["completed"].stdout + detail["completed"].stderr
            scope_sha256 = detail["binding"].get("scope_sha256")
            expected_scope_sha256 = self._scenario_digest(
                {"project_ids": ["orchid-release"]}
            )
            canonical_payload = canonical.get("payload_sha256")
            outside_evidence = wrong.get("evidence_id")
            if (
                scope_sha256 != expected_scope_sha256
                or not isinstance(canonical_payload, str)
                or not isinstance(outside_evidence, str)
            ):
                raise RunError("wrong-scope measured scope identity is invalid")
            return {
                "effective_scope_sha256": scope_sha256,
                "broker_scope_sha256": expected_scope_sha256,
                "candidate_scope_sha256": expected_scope_sha256,
                "canonical_item_sha256": canonical_payload,
                "outside_scope_item_sha256": hashlib.sha256(
                    outside_evidence.encode()
                ).hexdigest(),
                "effective_scope_bound": True,
                "outside_scope_in_context": any(
                    value.encode() in prepare_bytes for value in outside_identifiers
                ),
                "outside_scope_in_provider_output": any(
                    value.encode() in output for value in outside_identifiers
                ),
            }
        if case_id == "U1-REVOKE-REENTRY":
            revoked = negatives.get("revoke")
            requested_state_key = "release.database"
            canonical = [
                row
                for row in families
                if isinstance(row, Mapping)
                and row.get("state_key") == requested_state_key
            ]
            outcome = prepare.get("access_outcome")
            if (
                not isinstance(revoked, Mapping)
                or not isinstance(revoked.get("evidence_id"), str)
                or not isinstance(revoked.get("claim_id"), str)
                or revoked.get("state_key") != requested_state_key
                or len(canonical) != 1
                or canonical[0].get("evidence_id") != revoked.get("evidence_id")
                or canonical[0].get("claim_id") != revoked.get("claim_id")
                or not isinstance(outcome, Mapping)
            ):
                raise RunError("revocation fixture binding is absent")
            revoked_claim_accepted = not (
                prepare.get("prepare_status") == "ABSTAIN"
                and prepare.get("prepare_reason") == "CANONICAL_GATE_REJECTED"
                and prepare.get("current_state_status") == "BLOCKED"
                and prepare.get("current_state_claim_count") == 0
                and outcome.get("context_digest") is None
                and outcome.get("status") == "GOVERNANCE_BLOCKED"
                and outcome.get("execution_action") == "ABSTAIN"
                and outcome.get("provider_execution") == "PROHIBITED"
                and outcome.get("terminal_stage") == "GATE"
                and outcome.get("reason_code") == "CANONICAL_GATE_REJECTED"
                and not detail["answers"]
                and not detail["reservations"]
                and not detail["terminals"]
            )
            return {
                "revoked_evidence_sha256": hashlib.sha256(
                    str(revoked["evidence_id"]).encode()
                ).hexdigest(),
                "canonical_block_receipt_sha256": self._scenario_digest(
                    _redact_fixture_receipt(revoked)
                ),
                "canonical_block_applied": revoked.get("canonical_block_status")
                == "APPLIED",
                "revoked_claim_accepted": revoked_claim_accepted,
            }
        if case_id == "U1-OPEN-ISSUE":
            issue = negatives.get("open_issue")
            requested_state_key = "release.decision"
            canonical = [
                row
                for row in families
                if isinstance(row, Mapping)
                and row.get("state_key") == requested_state_key
            ]
            mutations = seeded.get("mutations")
            conflicting_evidence = (
                issue.get("conflicting_evidence_id")
                if isinstance(issue, Mapping)
                else None
            )
            matching_captures = (
                [
                    row
                    for row in mutations
                    if isinstance(row, Mapping)
                    and row.get("kind") == "EVIDENCE_CAPTURE"
                    and row.get("evidence_id") == conflicting_evidence
                ]
                if isinstance(mutations, list)
                else []
            )
            outcome = prepare.get("access_outcome")
            if (
                not isinstance(issue, Mapping)
                or not isinstance(issue.get("open_issue_id"), str)
                or not isinstance(issue.get("head_claim_version_id"), str)
                or not isinstance(issue.get("claim_id"), str)
                or not isinstance(conflicting_evidence, str)
                or issue.get("state_key") != requested_state_key
                or len(canonical) != 1
                or canonical[0].get("claim_id") != issue.get("claim_id")
                or canonical[0].get("claim_version_id")
                != issue.get("head_claim_version_id")
                or len(matching_captures) != 1
                or not isinstance(outcome, Mapping)
            ):
                raise RunError("OpenIssue fixture binding is absent")
            probe = self._probe_runtime_open_issue(
                issue=issue,
                canonical=canonical[0],
                conflicting_evidence_id=conflicting_evidence,
            )
            canonical_open_issue_present = (
                probe["present"] is True
                and probe["claim_conflicted"] is True
                and probe["branch_binding_exact"] is True
                and probe["transition_binding_exact"] is True
                and probe["discharge_rule_exact"] is True
                and isinstance(probe["issue_sha256"], str)
                and isinstance(probe["head_sha256"], str)
                and len(probe["issue_sha256"]) == 64
                and len(probe["head_sha256"]) == 64
                and prepare.get("prepare_status") == "ABSTAIN"
                and prepare.get("prepare_reason") == "CANONICAL_GATE_REJECTED"
                and prepare.get("current_state_status") == "BLOCKED"
                and outcome.get("status") == "GOVERNANCE_BLOCKED"
                and outcome.get("reason_code") == "CANONICAL_GATE_REJECTED"
            )
            runtime_issue_closure_present = bool(
                prepare.get("compiled_memory_tokens")
                or prepare.get("compiled_memory_bytes")
                or outcome.get("context_digest")
            )
            unsafe_branch_selected = not (
                outcome.get("execution_action") == "ABSTAIN"
                and outcome.get("provider_execution") == "PROHIBITED"
                and outcome.get("terminal_stage") == "GATE"
                and prepare.get("current_state_claim_count") == 0
                and not detail["answers"]
                and not detail["reservations"]
                and not detail["terminals"]
            )
            provider_called = bool(
                detail["answers"] or detail["reservations"] or detail["terminals"]
            )
            return {
                "open_issue_sha256": probe["issue_sha256"],
                "head_sha256": probe["head_sha256"],
                "canonical_open_issue_present": canonical_open_issue_present,
                "runtime_issue_closure_present": runtime_issue_closure_present,
                "unsafe_branch_selected": unsafe_branch_selected,
                "provider_called": provider_called,
            }
        raise RunError("cache/governance invariant selector is unsupported")

    def _read_runtime_canonical_resource(
        self, collection: str, resource_id: str
    ) -> Mapping[str, Any]:
        """Read one exact canonical resource from the run-owned Runtime once."""

        if collection not in {"claims", "open-issues"}:
            raise RunError("fresh Runtime canonical resource selector is invalid")
        identity = self.runtime.identity
        token = self.runtime.reader_token
        if identity is None or not isinstance(token, str) or not token:
            raise RunError("fresh Runtime canonical reader identity is absent")
        try:
            canonical_resource_id = str(UUID(resource_id))
        except (TypeError, ValueError, AttributeError):
            raise RunError("canonical fixture resource identifier is invalid") from None
        if canonical_resource_id != resource_id:
            raise RunError("canonical fixture resource identifier is not canonical")
        origin = identity.base_url
        matched = re.fullmatch(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})", origin)
        if matched is None or int(matched.group(1)) > 65_535:
            raise RunError("fresh Runtime canonical origin is not exact loopback")
        request = urllib.request.Request(
            f"{origin}/v1/{collection}/{canonical_resource_id}",
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=5.0) as response:
                status = getattr(response, "status", None)
                raw = response.read(1_048_577)
        except (TimeoutError, urllib.error.HTTPError, urllib.error.URLError, OSError):
            raise RunError("fresh Runtime canonical read failed") from None
        if status != 200 or not isinstance(raw, bytes):
            raise RunError("fresh Runtime canonical response is invalid")
        if len(raw) > 1_048_576:
            raise RunError("fresh Runtime canonical response exceeds the bound")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RunError("fresh Runtime canonical response is not JSON") from None
        if not isinstance(value, Mapping):
            raise RunError("fresh Runtime canonical response is not an object")
        return value

    def _read_runtime_open_issue(self, issue_id: str) -> Mapping[str, Any]:
        return self._read_runtime_canonical_resource("open-issues", issue_id)

    def _read_runtime_claim(self, claim_id: str) -> Mapping[str, Any]:
        return self._read_runtime_canonical_resource("claims", claim_id)

    def _probe_runtime_open_issue(
        self,
        *,
        issue: Mapping[str, Any],
        canonical: Mapping[str, Any],
        conflicting_evidence_id: str,
    ) -> dict[str, object]:
        """Join a live OpenIssue read to the synthetic canonical fixture."""

        expected = {
            "issue_id": issue.get("open_issue_id"),
            "claim_id": issue.get("claim_id"),
            "support_evidence_id": canonical.get("evidence_id"),
            "conflicting_evidence_id": conflicting_evidence_id,
        }
        for value in expected.values():
            try:
                normalized = str(UUID(value))
            except (TypeError, ValueError, AttributeError):
                raise RunError(
                    "OpenIssue live probe fixture binding is invalid"
                ) from None
            if normalized != value:
                raise RunError("OpenIssue live probe fixture binding is invalid")
        observed = self._read_runtime_open_issue(str(expected["issue_id"]))
        current_claim = self._read_runtime_claim(str(expected["claim_id"]))
        branches = observed.get("branches")
        transitions = observed.get("transitions")
        discharge_rule = observed.get("discharge_rule")
        if (
            observed.get("issue_id") != expected["issue_id"]
            or observed.get("target_claim_id") != expected["claim_id"]
            or observed.get("issue_type") != "CONFLICT"
            or observed.get("status") != "OPEN"
            or observed.get("revision") != 1
            or isinstance(observed.get("revision"), bool)
            or observed.get("scope_predicate") != {"project_ids": ["orchid-release"]}
            or observed.get("required_authority") != "INFORMATIONAL"
            or observed.get("resolved_by_decision_id") is not None
            or observed.get("resolved_at") is not None
            or not isinstance(branches, list)
            or not isinstance(transitions, list)
            or not isinstance(discharge_rule, Mapping)
        ):
            raise RunError("live Runtime OpenIssue identity or state drifted")
        branch_pairs: list[tuple[str, str]] = []
        for branch in branches:
            if not isinstance(branch, Mapping) or set(branch) != {
                "relation_type",
                "evidence_id",
            }:
                raise RunError("live Runtime OpenIssue branch shape drifted")
            relation_type = branch.get("relation_type")
            evidence_id = branch.get("evidence_id")
            if not isinstance(relation_type, str) or not isinstance(evidence_id, str):
                raise RunError("live Runtime OpenIssue branch value drifted")
            branch_pairs.append((relation_type, evidence_id))
        expected_branches = {
            ("SUPPORT_BRANCH", str(expected["support_evidence_id"])),
            ("CONTRADICT_BRANCH", str(expected["conflicting_evidence_id"])),
        }
        if len(branch_pairs) != 2 or set(branch_pairs) != expected_branches:
            raise RunError("live Runtime OpenIssue branch binding drifted")
        if (
            len(transitions) != 1
            or not isinstance(transitions[0], Mapping)
            or transitions[0].get("event_type") != "ISSUE_CREATED"
            or transitions[0].get("from_status") is not None
            or transitions[0].get("to_status") != "OPEN"
            or transitions[0].get("from_revision") != 0
            or transitions[0].get("to_revision") != 1
        ):
            raise RunError("live Runtime OpenIssue transition binding drifted")
        if (
            discharge_rule.get("rule_version") != "1"
            or discharge_rule.get("required_evidence_kinds") != ["RUNTIME_OBSERVATION"]
            or discharge_rule.get("required_scope")
            != {"project_ids": ["orchid-release"]}
            or discharge_rule.get("required_authority") != "INFORMATIONAL"
            or discharge_rule.get("minimum_independent_sources") != 1
            or discharge_rule.get("must_address_branches")
            != ["SUPPORT_BRANCH", "CONTRADICT_BRANCH"]
            or discharge_rule.get("review_required") is not True
        ):
            raise RunError("live Runtime OpenIssue discharge rule drifted")
        head_claim_version_id = issue.get("head_claim_version_id")
        project = canonical.get("project")
        state_key = canonical.get("state_key")
        claim_type = canonical.get("claim_type")
        payload_sha256 = canonical.get("payload_sha256")
        if (
            current_claim.get("claim_id") != expected["claim_id"]
            or current_claim.get("claim_version_id") != head_claim_version_id
            or current_claim.get("subject_id") != project
            or current_claim.get("predicate") != state_key
            or current_claim.get("claim_type") != claim_type
            or current_claim.get("scope_predicate")
            != {"project_ids": ["orchid-release"]}
            or current_claim.get("has_live_open_issue") is not True
            or current_claim.get("effective_status") != "CONFLICTED"
            or current_claim.get("lifecycle") != "ACTIVE"
            or current_claim.get("authority") != "INFORMATIONAL"
            or self._scenario_digest(current_claim.get("payload")) != payload_sha256
        ):
            raise RunError("live Runtime OpenIssue claim-head binding drifted")
        return {
            "present": True,
            "claim_conflicted": True,
            "branch_binding_exact": True,
            "transition_binding_exact": True,
            "discharge_rule_exact": True,
            "issue_sha256": hashlib.sha256(
                str(observed["issue_id"]).encode()
            ).hexdigest(),
            "head_sha256": hashlib.sha256(
                str(current_claim["claim_version_id"]).encode()
            ).hexdigest(),
        }

    def _cache_governance_smoke_evidence(
        self,
        *,
        prompt: str,
        details: Sequence[Mapping[str, Any]],
        trace_rows: Sequence[Mapping[str, Any]],
        steps: Sequence[Mapping[str, object]],
    ) -> dict[str, Any]:
        reservations = [
            row
            for detail in details
            for row in detail.get("reservations", [])
            if isinstance(row, Mapping)
        ]
        terminals = [
            row
            for detail in details
            for row in detail.get("terminals", [])
            if isinstance(row, Mapping)
        ]
        attempts = [
            row
            for detail in details
            for row in detail.get("attempts", [])
            if isinstance(row, Mapping)
        ]
        prepares = [detail["prepare"] for detail in details if "prepare" in detail]
        answers = [
            row
            for detail in details
            for row in detail.get("answers", [])
            if isinstance(row, Mapping)
        ]
        completed = [
            detail["completed"]
            for detail in details
            if isinstance(detail.get("completed"), subprocess.CompletedProcess)
        ]

        def digest(values: Sequence[object]) -> str | None:
            return self._scenario_digest(list(values)) if values else None

        native_ids = [
            row["native_request_id"]
            for row in terminals
            if isinstance(row.get("native_request_id"), str)
        ]
        logical_ids = [
            row["logical_request_id"]
            for row in answers
            if isinstance(row.get("logical_request_id"), str)
        ]
        trace_ids = [
            row["trace_id"] for row in answers if isinstance(row.get("trace_id"), str)
        ]
        prepare_timings = [
            row.get("timing") if isinstance(row.get("timing"), Mapping) else {}
            for row in prepares
        ]
        context_tokens = sum(
            int(row["compiled_memory_tokens"])
            for row in prepares
            if isinstance(row.get("compiled_memory_tokens"), int)
        )
        outputs = [
            {
                "exit_code": item.returncode,
                "stdout_bytes": len(item.stdout),
                "stdout_sha256": hashlib.sha256(item.stdout).hexdigest(),
                "stderr_bytes": len(item.stderr),
                "stderr_sha256": hashlib.sha256(item.stderr).hexdigest(),
            }
            for item in completed
        ]
        terminal_status: str | None = None
        if terminals:
            terminal_status = (
                "SUCCEEDED"
                if len(terminals) == len(reservations)
                and all(row.get("status") == "SUCCEEDED" for row in terminals)
                else "MIXED_OR_FAILED"
            )
        requested_routes = {
            str(step["requested_route"])
            for step in steps
            if isinstance(step.get("requested_route"), str)
        }
        memory_route = (
            "CACHE"
            if "CACHE" in requested_routes
            else next(iter(requested_routes))
            if len(requested_routes) == 1
            else "NONE"
        )
        current_statuses = {
            str(row["current_state_status"])
            for row in prepares
            if isinstance(row.get("current_state_status"), str)
        }
        return {
            "observed_provider_calls": len(reservations),
            "observed_mcp_calls": len(attempts),
            "provider_terminal_status": terminal_status,
            "native_request_id_sha256": digest(native_ids),
            "worker_exit_code": (
                next((item.returncode for item in completed if item.returncode), 0)
                if completed
                else 0
            ),
            "worker_output_sha256": self._scenario_digest(outputs),
            "worker_output_bytes": sum(
                len(item.stdout) + len(item.stderr) for item in completed
            ),
            "automatic_retries": 0,
            "mcp_automatic_retries": 0,
            "unaccounted_mcp_calls": 0,
            "unaccounted_provider_calls": 0,
            "memory_route": memory_route,
            "context_tokens": context_tokens,
            "context_in_prompt": bool(answers)
            and all(row.get("context_in_prompt") is True for row in answers),
            "current_state_status": (
                next(iter(current_statuses)) if len(current_statuses) == 1 else None
            ),
            "current_state_claim_count": (
                min(int(row.get("current_state_claim_count", 0)) for row in prepares)
                if prepares
                else 0
            ),
            "access_id_sha256": digest(logical_ids),
            "mcp_receipt_sha256": digest(
                [row.get("access_outcome") for row in prepares]
            ),
            "runtime_trace_sha256": digest(
                [row.get("recall_execution_trace") for row in prepares]
            ),
            "trace_id_sha256": digest(trace_ids),
            "latencies_ms": {
                "openworker": round(
                    sum(float(detail.get("latency_ms", 0.0)) for detail in details),
                    3,
                ),
                "adapter": round(
                    sum(
                        _nonnegative_measured_ms(row.get("adapter_total_ms"))
                        for row in answers
                    ),
                    3,
                ),
                "mcp": round(
                    sum(
                        _nonnegative_measured_ms(timing.get("mcp_handler_ms"))
                        for timing in prepare_timings
                    ),
                    3,
                ),
                "runtime": round(
                    sum(
                        _nonnegative_measured_ms(timing.get("runtime_total_ms"))
                        for timing in prepare_timings
                    ),
                    3,
                ),
                "compile": round(
                    sum(
                        _nonnegative_measured_ms(timing.get("context_compile_ms"))
                        for timing in prepare_timings
                    ),
                    3,
                ),
                "provider": round(
                    sum(
                        _nonnegative_measured_ms(row.get("provider_prefill_answer_ms"))
                        for row in answers
                    ),
                    3,
                ),
            },
            "model_visible_memory_tool_events": sum(
                row.get("event") == "PROVIDER_MEMORY_TOOL_VISIBLE" for row in trace_rows
            ),
            "raw_prompt_or_answer_persisted": _durable_payload_observed(
                self.paths.durable,
                (
                    prompt.encode(),
                    *(
                        payload
                        for item in completed
                        for payload in (item.stdout, item.stderr)
                    ),
                ),
            ),
            "safety_failures": {name: 0 for name in self.case.safety_counters},
            "cache_governance_steps_sha256": self._scenario_digest(list(steps)),
        }

    def _smoke_cache_governance_scenario(self) -> dict[str, Any]:
        try:
            scenario = cache_governance.scenario_for_case(self.case.case_id)
        except cache_governance.ScenarioContractError as exc:
            raise RunError("cache/governance scenario is unavailable") from exc
        if (
            scenario.expected_mcp_calls != self.case.expected_mcp_calls
            or scenario.expected_provider_calls != self.case.expected_provider_calls
            or scenario.automatic_retries != 0
            or scenario.vllm_lifecycle_attempts != 0
        ):
            raise RunError("cache/governance case call contract drifted")
        if scenario.execution_class == "OPENWORKER_E2E" and self.fixture is None:
            raise RunError("cache/governance canonical fixture is absent")
        prompt = _cache_governance_prompt(self.case)
        previous_ledger = _read_json_lines(self.provider_ledger)
        previous_trace = _read_json_lines(self.host_trace)
        scenario_initial_ledger = list(previous_ledger)
        scenario_initial_trace = list(previous_trace)
        known_sessions: dict[str, str] = {}
        steps: list[dict[str, object]] = []
        details: list[dict[str, Any]] = []
        all_trace_rows: list[dict[str, Any]] = []
        mutation: dict[str, Any] | None = None
        adjacent: dict[str, object] | None = None

        def preserve() -> None:
            measured = self._cache_governance_smoke_evidence(
                prompt=prompt,
                details=details,
                trace_rows=all_trace_rows,
                steps=steps,
            )
            current_ledger = _read_json_lines(self.provider_ledger)
            current_trace = _read_json_lines(self.host_trace)
            if (
                current_ledger[: len(scenario_initial_ledger)]
                == scenario_initial_ledger
                and current_trace[: len(scenario_initial_trace)]
                == scenario_initial_trace
            ):
                ledger_delta = current_ledger[len(scenario_initial_ledger) :]
                trace_delta = current_trace[len(scenario_initial_trace) :]
                reservations = [
                    row for row in ledger_delta if row.get("event") == "RESERVED"
                ]
                terminals = [
                    row
                    for row in ledger_delta
                    if row.get("event") == "PROVIDER_TERMINAL"
                ]
                attempts = [
                    row
                    for row in trace_delta
                    if row.get("event") == "HOST_MCP_PREPARE_ATTEMPT"
                ]
                prepares = [
                    row
                    for row in trace_delta
                    if row.get("event") == "HOST_MCP_PREPARE_CONTEXT"
                ]
                requested_routes = {
                    str(row["requested_route"])
                    for row in trace_delta
                    if row.get("event") == "HOST_MEMORY_NEED_RESOLVED"
                    and isinstance(row.get("requested_route"), str)
                }
                measured.update(
                    {
                        "observed_provider_calls": len(reservations),
                        "observed_mcp_calls": len(attempts),
                        "provider_terminal_status": (
                            "SUCCEEDED"
                            if terminals
                            and len(terminals) == len(reservations)
                            and all(
                                row.get("status") == "SUCCEEDED" for row in terminals
                            )
                            else "MIXED_OR_FAILED"
                            if terminals
                            else None
                        ),
                        "model_visible_memory_tool_events": sum(
                            row.get("event") == "PROVIDER_MEMORY_TOOL_VISIBLE"
                            for row in trace_delta
                        ),
                        "context_tokens": sum(
                            int(row["compiled_memory_tokens"])
                            for row in prepares
                            if isinstance(row.get("compiled_memory_tokens"), int)
                        ),
                        "mcp_receipt_sha256": (
                            self._scenario_digest(
                                [row.get("access_outcome") for row in prepares]
                            )
                            if prepares
                            else None
                        ),
                        "runtime_trace_sha256": (
                            self._scenario_digest(
                                [row.get("recall_execution_trace") for row in prepares]
                            )
                            if prepares
                            else None
                        ),
                        "memory_route": (
                            "CACHE"
                            if "CACHE" in requested_routes
                            else next(iter(requested_routes))
                            if len(requested_routes) == 1
                            else "NONE"
                        ),
                    }
                )
            self.smoke_evidence = measured

        try:
            for expected in scenario.steps:
                if expected.boundary == "HOST_NATIVE_COMPLETION":
                    step, detail, known_sessions, current_ledger, current_trace = (
                        self._execute_cache_governance_turn(
                            expected,
                            prompt=prompt,
                            known_sessions=known_sessions,
                            previous_ledger=previous_ledger,
                            previous_trace=previous_trace,
                        )
                    )
                    steps.append(step)
                    details.append(detail)
                    all_trace_rows.extend(detail["trace_delta"])
                    previous_ledger = current_ledger
                    previous_trace = current_trace
                elif expected.boundary == "FIXTURE_APPLY_U1_STATE_CHANGE_API":
                    if self.fixture is None:
                        raise RunError("post-warm mutation fixture is absent")
                    mutation = self.fixture.apply_post_warm_state_change()
                    steps.append(self._scenario_static_step(expected, mutation))
                elif expected.boundary == "MAIN_COMPOSITION_READINESS":
                    observed = self._main_composition_observation()
                    steps.append(self._scenario_static_step(expected, observed))
                elif expected.boundary == "INDEPENDENT_NEGATIVE_HOST_STARTUP":
                    adjacent = self._authority_probe()
                    steps.append(self._scenario_static_step(expected, adjacent))
                elif expected.boundary == "HOST_RESOLVER_PROCESS_FIXTURE":
                    adjacent = self._alias_collision_probe()
                    steps.append(self._scenario_static_step(expected, adjacent))
                else:
                    raise RunError("cache/governance scenario boundary is unsupported")
                preserve()

            invariants = self._cache_governance_invariants(
                details=details,
                mutation=mutation,
                adjacent=adjacent,
            )
            measurement: dict[str, object] = {
                "schema": cache_governance.MEASUREMENT_SCHEMA,
                "case_id": self.case.case_id,
                "execution_class": scenario.execution_class,
                "steps": steps,
                "mcp_calls": sum(int(step["mcp_calls"]) for step in steps),
                "provider_calls": sum(int(step["provider_calls"]) for step in steps),
                "automatic_retries": 0,
                "vllm_lifecycle_attempts": 0,
                "invariants": invariants,
                "cleanup": None,
            }
            if (
                measurement["mcp_calls"] != scenario.expected_mcp_calls
                or measurement["provider_calls"] != scenario.expected_provider_calls
            ):
                raise RunError("cache/governance measured call totals drifted")
            self.cache_governance_measurement = measurement
            evidence = self._cache_governance_smoke_evidence(
                prompt=prompt,
                details=details,
                trace_rows=all_trace_rows,
                steps=steps,
            )
            evidence["cache_governance_measurement_sha256"] = self._scenario_digest(
                measurement
            )
            self.smoke_evidence = evidence
            if (
                evidence["observed_mcp_calls"] != scenario.expected_mcp_calls
                or evidence["observed_provider_calls"]
                != scenario.expected_provider_calls
                or evidence["automatic_retries"] != 0
                or evidence["model_visible_memory_tool_events"] != 0
                or evidence["raw_prompt_or_answer_persisted"] is not False
                or (
                    scenario.expected_provider_calls > 0
                    and evidence["provider_terminal_status"] != "SUCCEEDED"
                )
                or (
                    scenario.expected_provider_calls == 0
                    and evidence["provider_terminal_status"] is not None
                )
            ):
                raise RunError("cache/governance smoke accounting failed")
            self._capture_worker_logs()
            return evidence
        except Exception as exc:
            try:
                preserve()
            except (OSError, UnicodeError, ValueError, RunError):
                self.smoke_evidence = dict(self.smoke_evidence or {})
            try:
                self._capture_worker_logs()
            except RunError:
                pass
            if isinstance(exc, RunError):
                raise
            raise RunError("cache/governance scenario execution failed") from exc

    def _preserve_fault_failure_measurement(
        self,
        *,
        completed: subprocess.CompletedProcess[bytes] | None,
        openworker_latency_ms: float,
        previous_ledger: Sequence[Mapping[str, Any]],
        previous_trace: Sequence[Mapping[str, Any]],
    ) -> None:
        ledger = self._append_only_delta(
            previous_ledger,
            _read_json_lines(self.provider_ledger),
            artifact="fault provider ledger",
        )
        trace = self._append_only_delta(
            previous_trace,
            _read_json_lines(self.host_trace),
            artifact="fault Host trace",
        )
        reservations = [row for row in ledger if row.get("event") == "RESERVED"]
        terminals = [row for row in ledger if row.get("event") == "PROVIDER_TERMINAL"]
        attempts = [
            row for row in trace if row.get("event") == "HOST_MCP_PREPARE_ATTEMPT"
        ]
        measured = dict(self.smoke_evidence or {})
        previous_latencies = measured.get("latencies_ms")
        if not isinstance(previous_latencies, Mapping):
            previous_latencies = {}
        failure_latencies = {
            name: _nonnegative_measured_ms(previous_latencies.get(name))
            for name in ("adapter", "mcp", "runtime", "compile", "provider")
        }
        failure_latencies["openworker"] = _nonnegative_measured_ms(
            openworker_latency_ms
        )
        measured.update(
            {
                "observed_provider_calls": len(reservations),
                "observed_mcp_calls": len(attempts),
                "provider_terminal_status": (
                    terminals[0].get("status") if len(terminals) == 1 else None
                ),
                "provider_terminal_reason_code": (
                    terminals[0].get("reason_code") if len(terminals) == 1 else None
                ),
                "provider_request_started": (
                    terminals[0].get("request_started") if len(terminals) == 1 else None
                ),
                "provider_native_request_observed": (
                    terminals[0].get("native_request_observed")
                    if len(terminals) == 1
                    else None
                ),
                "native_request_id_sha256": (
                    hashlib.sha256(
                        str(terminals[0]["native_request_id"]).encode()
                    ).hexdigest()
                    if len(terminals) == 1
                    and isinstance(terminals[0].get("native_request_id"), str)
                    else None
                ),
                "worker_exit_code": completed.returncode if completed else -1,
                "worker_output_sha256": (
                    hashlib.sha256(completed.stdout + completed.stderr).hexdigest()
                    if completed
                    else hashlib.sha256(b"").hexdigest()
                ),
                "worker_output_bytes": (
                    len(completed.stdout) + len(completed.stderr) if completed else 0
                ),
                "automatic_retries": 0,
                "mcp_automatic_retries": 0,
                "unaccounted_mcp_calls": 0,
                "unaccounted_provider_calls": 0,
                "memory_route": (
                    "NONE"
                    if self.case.case_id.startswith("U1-PROVIDER-")
                    else "TRANSPORT"
                ),
                "context_tokens": 0,
                "context_in_prompt": False,
                "model_visible_memory_tool_events": sum(
                    row.get("event") == "PROVIDER_MEMORY_TOOL_VISIBLE" for row in trace
                ),
                "raw_prompt_or_answer_persisted": False,
                "latencies_ms": failure_latencies,
                "safety_failures": {name: 0 for name in self.case.safety_counters},
            }
        )
        self.smoke_evidence = measured
        receipt_observations: list[dict[str, Any]] = []
        if self.fault_plan is not None:
            for spec in self.fault_plan.receipts:
                observation: dict[str, Any] = {
                    "name": spec.name,
                    "path": str(spec.path),
                    "expected_schema": spec.schema,
                    "present": False,
                    "private_regular_file": False,
                    "bytes": 0,
                    "sha256": None,
                    "observed_schema": None,
                }
                try:
                    current = spec.path.lstat()
                except OSError:
                    pass
                else:
                    private_regular = bool(
                        stat.S_ISREG(current.st_mode)
                        and not stat.S_ISLNK(current.st_mode)
                        and stat.S_IMODE(current.st_mode) == 0o600
                    )
                    observation.update(
                        {
                            "present": True,
                            "private_regular_file": private_regular,
                            "bytes": current.st_size,
                        }
                    )
                    if private_regular and 0 <= current.st_size <= 1_048_576:
                        try:
                            raw = spec.path.read_bytes()
                        except OSError:
                            pass
                        else:
                            observation["bytes"] = len(raw)
                            observation["sha256"] = hashlib.sha256(raw).hexdigest()
                            try:
                                value = json.loads(raw)
                            except (UnicodeError, json.JSONDecodeError):
                                pass
                            else:
                                observation["observed_schema"] = (
                                    value.get("schema")
                                    if isinstance(value, Mapping)
                                    and isinstance(value.get("schema"), str)
                                    else None
                                )
                receipt_observations.append(observation)
        failure = {
            "schema": "milai.dg13u.u1-fault-execution-observation.v1",
            "run_id": self.paths.run_id,
            "case_id": self.case.case_id,
            "status": TerminalStatus.FAIL,
            "mcp_attempts": len(attempts),
            "provider_reservations": len(reservations),
            "provider_terminals": len(terminals),
            "provider_terminal_status": measured["provider_terminal_status"],
            "provider_terminal_reason_code": measured["provider_terminal_reason_code"],
            "provider_request_started": measured["provider_request_started"],
            "provider_native_request_observed": measured[
                "provider_native_request_observed"
            ],
            "automatic_retries": 0,
            "external_attempts": 0,
            "external_lifecycle_mutations": 0,
            "fixture_receipts": receipt_observations,
        }
        _atomic_write(self.paths.durable / "fault-execution-observation.json", failure)

    def _smoke_fault_scenario(self) -> dict[str, Any]:
        if self.fault_plan is None or self._resources is None:
            raise RunError("fault execution lifecycle is absent")
        prompt = _case_prompt(self.case)
        completed: subprocess.CompletedProcess[bytes] | None = None
        openworker_latency_ms = 0.0
        command_truth: SmokeCommandTruth | None = None
        fixture_stopped = False
        previous_ledger = _read_json_lines(self.provider_ledger)
        previous_trace = _read_json_lines(self.host_trace)
        try:
            self._activate_post_readiness_fault(self._resources)
            smoke_started = time.monotonic()
            completed = _command_bytes(
                [
                    "docker",
                    "exec",
                    "--workdir",
                    "/openworker/runtime",
                    "--env",
                    "OPENCODE_CONFIG_DIR=/openworker/runtime",
                    self.container_name,
                    "opencode",
                    "run",
                    "--format",
                    "json",
                    "--model",
                    f"openworker/{MODEL_ID}",
                    prompt,
                ],
                timeout=240,
                check=False,
            )
            openworker_latency_ms = round((time.monotonic() - smoke_started) * 1000, 3)
            command_truth = self._write_smoke_command_diagnostic(
                completed, prompt=prompt
            )
            command_accounting = _opencode_fault_command_accounting(
                self.fault_plan,
                completed=completed,
                command_truth=command_truth,
            )
            self._capture_worker_logs()
            ledger = self._append_only_delta(
                previous_ledger,
                _read_json_lines(self.provider_ledger),
                artifact="fault provider ledger",
            )
            trace = self._append_only_delta(
                previous_trace,
                _read_json_lines(self.host_trace),
                artifact="fault Host trace",
            )
            reservations = [row for row in ledger if row.get("event") == "RESERVED"]
            attempts = [
                row for row in trace if row.get("event") == "HOST_MCP_PREPARE_ATTEMPT"
            ]
            provider_terminals = [
                row for row in ledger if row.get("event") == "PROVIDER_TERMINAL"
            ]
            preliminary: dict[str, Any] = {
                "observed_provider_calls": len(reservations),
                "observed_mcp_calls": len(attempts),
                "provider_terminal_status": (
                    provider_terminals[0].get("status")
                    if len(provider_terminals) == 1
                    else None
                ),
                "native_request_id_sha256": None,
                "worker_exit_code": completed.returncode,
                "worker_output_sha256": hashlib.sha256(
                    completed.stdout + completed.stderr
                ).hexdigest(),
                "worker_output_bytes": len(completed.stdout) + len(completed.stderr),
                "automatic_retries": 0,
                "mcp_automatic_retries": 0,
                "unaccounted_mcp_calls": 0,
                "unaccounted_provider_calls": 0,
                "memory_route": (
                    "NONE"
                    if self.case.case_id.startswith("U1-PROVIDER-")
                    else "TRANSPORT"
                ),
                "context_tokens": 0,
                "context_in_prompt": False,
                "current_state_status": None,
                "current_state_claim_count": 0,
                "access_id_sha256": None,
                "mcp_receipt_sha256": None,
                "runtime_trace_sha256": None,
                "trace_id_sha256": None,
                "latencies_ms": {
                    "openworker": openworker_latency_ms,
                    "adapter": 0.0,
                    "mcp": 0.0,
                    "runtime": 0.0,
                    "compile": 0.0,
                    "provider": 0.0,
                },
                "model_visible_memory_tool_events": sum(
                    row.get("event") == "PROVIDER_MEMORY_TOOL_VISIBLE" for row in trace
                ),
                "raw_prompt_or_answer_persisted": _durable_payload_observed(
                    self.paths.durable,
                    (prompt.encode(), completed.stdout, completed.stderr),
                ),
                "safety_failures": {name: 0 for name in self.case.safety_counters},
                "typed_error_count": command_truth.typed_error_count,
                **command_accounting,
            }
            self.smoke_evidence = preliminary
            accounting = _fault_trace_accounting(
                self.fault_plan, trace=trace, ledger=ledger
            )
            native_id = accounting.pop("provider_native_request_id")
            preliminary.update(accounting)
            preliminary["native_request_id_sha256"] = (
                hashlib.sha256(native_id.encode()).hexdigest()
                if isinstance(native_id, str)
                else None
            )
            preliminary["mcp_receipt_sha256"] = accounting.get("access_outcome_sha256")
            self._stop_fault_fixture()
            fixture_stopped = True
            try:
                reduced = fault_execution.reduce_fault_execution(
                    self.fault_plan,
                    host_terminal=accounting["host_terminal"],
                    ledger_calls=accounting["ledger_calls"],
                    automatic_retries=0,
                    provider_barrier=str(accounting["provider_barrier"]),
                    external_vllm={"attempts": 0, "lifecycle_mutations": 0},
                    provider_terminal_observation=accounting[
                        "provider_terminal_observation"
                    ],
                    fixture_observation=self.fault_fixture_observation,
                )
            except fault_execution.FaultExecutionError as exc:
                raise RunError("fault execution reduction failed") from exc
            durable_fault_evidence = {
                **reduced,
                "run_id": self.paths.run_id,
                "typed_outcome_sha256": hashlib.sha256(
                    u0._canonical_bytes(accounting["host_terminal"])
                ).hexdigest(),
                "request_started": accounting["provider_request_started"],
                "native_request_observed": accounting[
                    "provider_native_request_observed"
                ],
                "external_attempts": 0,
                "external_lifecycle_mutations": 0,
            }
            fault_artifact = self.paths.durable / "fault-execution.json"
            _atomic_write(fault_artifact, durable_fault_evidence)
            preliminary["fault_execution_sha256"] = u0._sha256_file(fault_artifact)
            preliminary["fault_execution"] = durable_fault_evidence
            self.fault_execution_evidence = durable_fault_evidence
            self.smoke_evidence = preliminary
            return preliminary
        except Exception as exc:
            self._preserve_fault_failure_measurement(
                completed=completed,
                openworker_latency_ms=openworker_latency_ms,
                previous_ledger=previous_ledger,
                previous_trace=previous_trace,
            )
            try:
                self._capture_worker_logs()
            except RunError:
                pass
            if isinstance(exc, RunError):
                raise
            raise RunError("fault scenario execution failed") from exc
        finally:
            if not fixture_stopped:
                try:
                    self._stop_fault_fixture()
                except RunError:
                    if self.smoke_evidence is not None:
                        self.smoke_evidence["fixture_cleanup_failed"] = True
            if self.fault_execution_evidence is None:
                try:
                    self._preserve_fault_failure_measurement(
                        completed=completed,
                        openworker_latency_ms=openworker_latency_ms,
                        previous_ledger=previous_ledger,
                        previous_trace=previous_trace,
                    )
                except RunError:
                    if self.smoke_evidence is not None:
                        self.smoke_evidence["failure_evidence_write_failed"] = True

    def _execute_task_batch(
        self,
        batch: task_scenarios.BatchSpec,
        commands: Mapping[str, tuple[str, ...]],
    ) -> tuple[
        dict[
            str,
            tuple[
                subprocess.CompletedProcess[bytes] | None,
                float,
                Exception | None,
            ],
        ],
        str | None,
    ]:
        """Execute one frozen task batch once; errors are measured, never retried."""

        if set(commands) != set(batch.turn_ids):
            raise RunError("U1 task batch command binding is invalid")
        barrier: threading.Barrier | None = None
        barrier_release_sha256: str | None = None
        if batch.launch_mode == "BARRIER_CONCURRENT":
            barrier = threading.Barrier(len(batch.turn_ids))
            barrier_release_sha256 = hashlib.sha256(
                u0._canonical_bytes(
                    {
                        "schema": "milai.dg13u.u1-task-barrier-release.v1",
                        "run_id": self.paths.run_id,
                        "case_id": self.case.case_id,
                        "batch_index": batch.batch_index,
                        "turn_ids": list(batch.turn_ids),
                    }
                )
            ).hexdigest()
        elif batch.launch_mode != "SERIAL" or len(batch.turn_ids) != 1:
            raise RunError("U1 task serial batch is invalid")

        def invoke(
            turn_id: str,
        ) -> tuple[
            subprocess.CompletedProcess[bytes] | None,
            float,
            Exception | None,
        ]:
            started = time.monotonic()
            try:
                if barrier is not None:
                    barrier.wait(timeout=15)
                completed = _command_bytes(
                    list(commands[turn_id]),
                    timeout=240,
                    check=False,
                )
                return (
                    completed,
                    round((time.monotonic() - started) * 1000, 3),
                    None,
                )
            except (RunError, threading.BrokenBarrierError) as exc:
                return (
                    None,
                    round((time.monotonic() - started) * 1000, 3),
                    exc,
                )

        if barrier is None:
            turn_id = batch.turn_ids[0]
            return {turn_id: invoke(turn_id)}, barrier_release_sha256
        results: dict[
            str,
            tuple[
                subprocess.CompletedProcess[bytes] | None,
                float,
                Exception | None,
            ],
        ] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(batch.turn_ids),
            thread_name_prefix="dg13u-u1-task",
        ) as executor:
            futures = {
                turn_id: executor.submit(invoke, turn_id) for turn_id in batch.turn_ids
            }
            for turn_id in batch.turn_ids:
                results[turn_id] = futures[turn_id].result()
        return results, barrier_release_sha256

    def _task_smoke_measurement(
        self,
        *,
        outputs: Sequence[subprocess.CompletedProcess[bytes]],
        output_latencies_ms: Sequence[float],
        prompts: Sequence[str],
        reservations: Sequence[Mapping[str, Any]],
        terminals: Sequence[Mapping[str, Any]],
        prepares: Sequence[Mapping[str, Any]],
        provider_answers: Sequence[Mapping[str, Any]],
        trace_rows: Sequence[Mapping[str, Any]],
        measured_rows: Sequence[Mapping[str, object]],
        turn_context_rows: Sequence[Mapping[str, object]],
        task_case_evidence: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        def digest(values: Sequence[object]) -> str | None:
            if not values:
                return None
            return hashlib.sha256(u0._canonical_bytes(list(values))).hexdigest()

        native_ids = [
            row["native_request_id"]
            for row in terminals
            if isinstance(row.get("native_request_id"), str)
        ]
        access_ids = [
            row["logical_request_id"]
            for row in provider_answers
            if isinstance(row.get("logical_request_id"), str)
        ]
        trace_ids = [
            row["trace_id"]
            for row in provider_answers
            if isinstance(row.get("trace_id"), str)
        ]
        statuses = [row.get("status") for row in terminals]
        if (
            terminals
            and len(terminals) == len(reservations)
            and set(statuses) == {"SUCCEEDED"}
        ):
            provider_terminal_status: str | None = "SUCCEEDED"
        elif terminals:
            provider_terminal_status = "MIXED_OR_FAILED"
        else:
            provider_terminal_status = None
        exit_codes = [completed.returncode for completed in outputs]
        worker_exit_code = (
            next((code for code in exit_codes if code != 0), 0) if exit_codes else -1
        )
        output_descriptors = [
            {
                "exit_code": completed.returncode,
                "stdout_bytes": len(completed.stdout),
                "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
                "stderr_bytes": len(completed.stderr),
                "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
            }
            for completed in outputs
        ]
        prepare_timings = [
            row.get("timing") if isinstance(row.get("timing"), Mapping) else {}
            for row in prepares
        ]
        current_statuses = {
            str(row["current_state_status"])
            for row in prepares
            if isinstance(row.get("current_state_status"), str)
        }
        current_state_status = (
            next(iter(current_statuses)) if len(current_statuses) == 1 else None
        )
        evidence: dict[str, Any] = {
            "observed_provider_calls": len(reservations),
            "observed_mcp_calls": len(prepares),
            "provider_terminal_status": provider_terminal_status,
            "native_request_id_sha256": digest(native_ids),
            "worker_exit_code": worker_exit_code,
            "worker_output_sha256": hashlib.sha256(
                u0._canonical_bytes(output_descriptors)
            ).hexdigest(),
            "worker_output_bytes": sum(
                len(completed.stdout) + len(completed.stderr) for completed in outputs
            ),
            "automatic_retries": 0,
            "mcp_automatic_retries": 0,
            "unaccounted_mcp_calls": 0,
            "unaccounted_provider_calls": 0,
            "memory_route": (
                "QUERY_FIRST"
                if self.case.case_id == "U1-TASK-CONTINUE"
                else "EXACT"
            ),
            "context_tokens": sum(
                int(row["compiled_memory_tokens"])
                for row in prepares
                if isinstance(row.get("compiled_memory_tokens"), int)
            ),
            "context_in_prompt": bool(provider_answers)
            and all(row.get("context_in_prompt") is True for row in provider_answers),
            "current_state_status": current_state_status,
            "current_state_claim_count": (
                min(int(row.get("current_state_claim_count", 0)) for row in prepares)
                if prepares
                else 0
            ),
            "access_id_sha256": digest(access_ids),
            "mcp_receipt_sha256": digest(
                [row.get("access_outcome") for row in prepares]
            ),
            "runtime_trace_sha256": digest(
                [row.get("recall_execution_trace") for row in prepares]
            ),
            "trace_id_sha256": digest(trace_ids),
            "latencies_ms": {
                "openworker": round(sum(output_latencies_ms), 3),
                "adapter": round(
                    sum(
                        _nonnegative_measured_ms(row.get("adapter_total_ms"))
                        for row in provider_answers
                    ),
                    3,
                ),
                "mcp": round(
                    sum(
                        _nonnegative_measured_ms(timing.get("mcp_handler_ms"))
                        for timing in prepare_timings
                    ),
                    3,
                ),
                "runtime": round(
                    sum(
                        _nonnegative_measured_ms(timing.get("runtime_total_ms"))
                        for timing in prepare_timings
                    ),
                    3,
                ),
                "compile": round(
                    sum(
                        _nonnegative_measured_ms(timing.get("context_compile_ms"))
                        for timing in prepare_timings
                    ),
                    3,
                ),
                "provider": round(
                    sum(
                        _nonnegative_measured_ms(row.get("provider_prefill_answer_ms"))
                        for row in provider_answers
                    ),
                    3,
                ),
            },
            "model_visible_memory_tool_events": sum(
                row.get("event") == "PROVIDER_MEMORY_TOOL_VISIBLE" for row in trace_rows
            ),
            "raw_prompt_or_answer_persisted": _durable_payload_observed(
                self.paths.durable,
                (
                    *(prompt.encode() for prompt in prompts),
                    *(
                        payload
                        for completed in outputs
                        for payload in (completed.stdout, completed.stderr)
                    ),
                ),
            ),
            "safety_failures": {name: 0 for name in self.case.safety_counters},
            "task_case_rows_sha256": hashlib.sha256(
                u0._canonical_bytes(list(measured_rows))
            ).hexdigest(),
            "task_turn_context_evidence": [dict(row) for row in turn_context_rows],
        }
        if task_case_evidence is not None:
            evidence["task_case_evidence"] = dict(task_case_evidence)
        return evidence

    def _smoke_task_scenario(self) -> dict[str, Any]:
        try:
            scenario = task_scenarios.scenario_for_case(self.case.case_id)
        except task_scenarios.TaskScenarioError as exc:
            raise RunError("U1 task scenario is unavailable") from exc
        if (
            scenario.expected_mcp_calls != self.case.expected_mcp_calls
            or scenario.expected_provider_calls != self.case.expected_provider_calls
            or scenario.automatic_retries != 0
        ):
            raise RunError("U1 task scenario call contract drifted")

        turns = {turn.turn_id: turn for turn in scenario.turns}
        prompts = {
            turn.turn_id: _task_turn_prompt(self.case, turn) for turn in scenario.turns
        }
        known_sessions: dict[str, str] = {}
        measured_rows: list[dict[str, object]] = []
        turn_context_rows: list[dict[str, object]] = []
        outputs: list[subprocess.CompletedProcess[bytes]] = []
        output_latencies_ms: list[float] = []
        all_reservations: list[dict[str, Any]] = []
        all_terminals: list[dict[str, Any]] = []
        all_prepares: list[dict[str, Any]] = []
        all_answers: list[dict[str, Any]] = []
        all_trace_rows: list[dict[str, Any]] = []
        previous_ledger = _read_json_lines(self.provider_ledger)
        previous_trace = _read_json_lines(self.host_trace)

        def update_measurement() -> None:
            self.smoke_evidence = self._task_smoke_measurement(
                outputs=outputs,
                output_latencies_ms=output_latencies_ms,
                prompts=list(prompts.values()),
                reservations=all_reservations,
                terminals=all_terminals,
                prepares=all_prepares,
                provider_answers=all_answers,
                trace_rows=all_trace_rows,
                measured_rows=measured_rows,
                turn_context_rows=turn_context_rows,
            )

        try:
            for batch in scenario.batches:
                created_session_ids: dict[str, str] = {}
                reserved_session_ids = set(known_sessions.values())
                for turn_id in batch.turn_ids:
                    if turns[turn_id].session_action != "NEW":
                        continue
                    created_session_id = self._create_opencode_session(
                        reserved_session_ids=tuple(reserved_session_ids)
                    )
                    created_session_ids[turn_id] = created_session_id
                    reserved_session_ids.add(created_session_id)
                commands = {
                    turn_id: task_scenarios.build_opencode_command(
                        turns[turn_id],
                        container_name=self.container_name,
                        prompt=prompts[turn_id],
                        known_sessions=known_sessions,
                        created_session_id=created_session_ids.get(turn_id),
                    )
                    for turn_id in batch.turn_ids
                }
                results, barrier_release_sha256 = self._execute_task_batch(
                    batch, commands
                )
                for turn_id in batch.turn_ids:
                    completed, latency_ms, _error = results[turn_id]
                    output_latencies_ms.append(latency_ms)
                    if completed is not None:
                        outputs.append(completed)

                current_ledger = _read_json_lines(self.provider_ledger)
                current_trace = _read_json_lines(self.host_trace)
                if (
                    current_ledger[: len(previous_ledger)] != previous_ledger
                    or current_trace[: len(previous_trace)] != previous_trace
                ):
                    raise RunError("U1 task append-only accounting changed")
                ledger_delta = current_ledger[len(previous_ledger) :]
                trace_delta = current_trace[len(previous_trace) :]
                previous_ledger = current_ledger
                previous_trace = current_trace
                reservations = [
                    row for row in ledger_delta if row.get("event") == "RESERVED"
                ]
                terminals = [
                    row
                    for row in ledger_delta
                    if row.get("event") == "PROVIDER_TERMINAL"
                ]
                prepares = [
                    row
                    for row in trace_delta
                    if row.get("event") == "HOST_MCP_PREPARE_CONTEXT"
                ]
                prepare_attempts = [
                    row
                    for row in trace_delta
                    if row.get("event") == "HOST_MCP_PREPARE_ATTEMPT"
                ]
                answers = [
                    row for row in trace_delta if row.get("event") == "PROVIDER_ANSWER"
                ]
                observations = [
                    row
                    for row in trace_delta
                    if row.get("event") == "HOST_NATIVE_REQUEST_OBSERVED"
                ]
                bindings = [
                    row
                    for row in trace_delta
                    if row.get("event") == "HOST_NATIVE_TASK_BOUND"
                ]
                all_reservations.extend(reservations)
                all_terminals.extend(terminals)
                all_prepares.extend(prepares)
                all_answers.extend(answers)
                all_trace_rows.extend(trace_delta)
                update_measurement()

                expected = len(batch.turn_ids)
                if any(
                    error is not None
                    for _completed, _latency, error in results.values()
                ):
                    raise RunError("U1 task command failed")
                if any(
                    len(rows) != expected
                    for rows in (
                        reservations,
                        terminals,
                        prepare_attempts,
                        prepares,
                        answers,
                        observations,
                        bindings,
                    )
                ):
                    raise RunError("U1 task incremental call accounting failed")
                if any(
                    row.get("event")
                    in {
                        "PROVIDER_MEMORY_TOOL_VISIBLE",
                        "HOST_INGRESS_TERMINAL",
                    }
                    for row in trace_delta
                ):
                    raise RunError("U1 task trace reached a forbidden terminal")

                parsed: dict[str, tuple[str, dict[str, object]]] = {}
                for turn_id in batch.turn_ids:
                    completed = results[turn_id][0]
                    assert completed is not None
                    if completed.returncode != 0:
                        raise RunError("U1 task OpenCode command exited nonzero")
                    session_id, event_evidence = (
                        task_scenarios.parse_opencode_session_events(completed.stdout)
                    )
                    known_sessions = task_scenarios.bind_observed_session(
                        turns[turn_id],
                        session_id,
                        known_sessions,
                        created_session_id=created_session_ids.get(turn_id),
                    )
                    parsed[turn_id] = (session_id, event_evidence)

                batch_rows: list[dict[str, object]] = []
                for turn_id in batch.turn_ids:
                    turn = turns[turn_id]
                    _session_id, event_evidence = parsed[turn_id]
                    session_hash = event_evidence["session_id_sha256"]
                    turn_bindings = [
                        row
                        for row in bindings
                        if row.get("task_session_sha256") == session_hash
                    ]
                    if len(turn_bindings) != 1:
                        raise RunError("U1 task native binding trace failed")
                    binding = turn_bindings[0]
                    operation_hash = binding.get("task_operation_sha256")
                    turn_observations = [
                        row
                        for row in observations
                        if row.get("task_session_sha256") == session_hash
                        and row.get("task_operation_sha256") == operation_hash
                    ]
                    if len(turn_observations) != 1:
                        raise RunError("U1 task native observation binding failed")
                    observation = turn_observations[0]
                    if observation.get("tool_count") != 2:
                        raise RunError("U1 task incoming MiLA tool count drifted")
                    expected_relation = (
                        "CONTINUE"
                        if turn.session_action == "CONTINUE"
                        else "TASK_START"
                    )
                    if binding.get("task_relation") != expected_relation:
                        raise RunError("U1 task native relation drifted")
                    turn_prepares = [
                        row
                        for row in prepares
                        if row.get("task_session_sha256") == session_hash
                        and row.get("task_operation_sha256") == operation_hash
                    ]
                    if len(turn_prepares) != 1:
                        raise RunError("U1 task MCP native identity binding failed")
                    prepare = turn_prepares[0]
                    turn_attempts = [
                        row
                        for row in prepare_attempts
                        if row.get("task_session_sha256") == session_hash
                        and row.get("task_operation_sha256") == operation_hash
                    ]
                    if (
                        len(turn_attempts) != 1
                        or turn_attempts[0].get("logical_mcp_calls") != 1
                    ):
                        raise RunError("U1 task MCP attempt binding failed")
                    trace_id = prepare.get("trace_id")
                    turn_answers = (
                        list(answers)
                        if len(batch.turn_ids) == 1
                        else [
                            row
                            for row in answers
                            if isinstance(trace_id, str)
                            and row.get("trace_id") == trace_id
                        ]
                    )
                    if len(turn_answers) != 1:
                        raise RunError("U1 task provider trace binding failed")
                    answer = turn_answers[0]
                    logical_id = answer.get("logical_request_id")
                    turn_reservations = [
                        row
                        for row in reservations
                        if row.get("logical_request_id") == logical_id
                    ]
                    turn_terminals = [
                        row
                        for row in terminals
                        if row.get("logical_request_id") == logical_id
                    ]
                    if len(turn_reservations) != 1 or len(turn_terminals) != 1:
                        raise RunError("U1 task provider ledger binding failed")
                    terminal = turn_terminals[0]
                    if (
                        terminal.get("status") != "SUCCEEDED"
                        or not isinstance(terminal.get("native_request_id"), str)
                        or terminal.get("native_request_id")
                        != answer.get("native_request_id")
                        or answer.get("mcp_calls") != 1
                        or answer.get("context_in_prompt") is not True
                        or answer.get("ordinary_tool_count") != 0
                    ):
                        raise RunError("U1 task provider terminal is invalid")
                    access_outcome = prepare.get("access_outcome")
                    terminal_stage = (
                        access_outcome.get("terminal_stage")
                        if isinstance(access_outcome, Mapping)
                        else None
                    )
                    if self.case.case_id == "U1-TASK-CONTINUE":
                        context_valid = (
                            prepare.get("prepare_status") == "READY"
                            and prepare.get("fresh_resolve") is True
                            and prepare.get("mcp_tool") == "milai_memory_resolve"
                            and prepare.get("current_state_status") == "HIT"
                            and isinstance(
                                prepare.get("current_state_claim_count"), int
                            )
                            and int(prepare["current_state_claim_count"]) >= 1
                            and isinstance(prepare.get("compiled_memory_tokens"), int)
                            and int(prepare["compiled_memory_tokens"]) > 0
                            and prepare.get("route") == "SEARCH"
                            and isinstance(terminal_stage, str)
                        )
                    elif turn.session_action == "NEW":
                        context_valid = (
                            prepare.get("prepare_status", "READY") == "READY"
                            and prepare.get("current_state_status") in {"HIT", "READY"}
                            and isinstance(
                                prepare.get("current_state_claim_count"), int
                            )
                            and int(prepare["current_state_claim_count"]) >= 1
                            and isinstance(prepare.get("compiled_memory_tokens"), int)
                            and int(prepare["compiled_memory_tokens"]) > 0
                            and (
                                prepare.get("route") == "EXACT"
                                or terminal_stage == "EXACT"
                            )
                        )
                    else:
                        context_valid = (
                            prepare.get("prepare_status") == "UNCHANGED"
                            and (
                                prepare.get("route") == "CACHE"
                                or terminal_stage == "CACHE"
                            )
                            and prepare.get("cache_validation_outcome") == "HIT"
                        )
                    if not context_valid:
                        raise RunError("U1 task exact context is invalid")
                    task_id_hash = binding.get("task_id_sha256")
                    if not isinstance(operation_hash, str) or not isinstance(
                        task_id_hash, str
                    ):
                        raise RunError("U1 task native identity hash is absent")
                    batch_rows.append(
                        {
                            "turn_id": turn_id,
                            "batch_index": batch.batch_index,
                            "launch_mode": batch.launch_mode,
                            "barrier_release_sha256": barrier_release_sha256,
                            "session_id_sha256": session_hash,
                            "operation_id_sha256": operation_hash,
                            "task_id_sha256": task_id_hash,
                            "mcp_calls": 1,
                            "provider_calls": 1,
                            "automatic_retries": 0,
                            "fresh_resolve": prepare.get("fresh_resolve") is True,
                            "mcp_tool": prepare.get("mcp_tool"),
                            "event_evidence": event_evidence,
                        }
                    )
                    turn_context_rows.append(
                        {
                            "turn_id": turn_id,
                            "session_action": turn.session_action,
                            "route": prepare.get("route"),
                            "prepare_status": prepare.get("prepare_status"),
                            "terminal_stage": terminal_stage,
                            "cache_validation_outcome": prepare.get(
                                "cache_validation_outcome"
                            ),
                            "current_state_status": prepare.get("current_state_status"),
                            "current_state_claim_count": prepare.get(
                                "current_state_claim_count", 0
                            ),
                            "compiled_memory_tokens": prepare.get(
                                "compiled_memory_tokens"
                            ),
                            "context_in_prompt": answer.get("context_in_prompt")
                            is True,
                            "fresh_resolve": prepare.get("fresh_resolve") is True,
                            "mcp_tool": prepare.get("mcp_tool"),
                        }
                    )
                measured_rows.extend(batch_rows)
                update_measurement()

            reduced = task_scenarios.reduce_measured_task_case(
                self.case.case_id,
                measured_rows,
            )
            evidence = self._task_smoke_measurement(
                outputs=outputs,
                output_latencies_ms=output_latencies_ms,
                prompts=list(prompts.values()),
                reservations=all_reservations,
                terminals=all_terminals,
                prepares=all_prepares,
                provider_answers=all_answers,
                trace_rows=all_trace_rows,
                measured_rows=measured_rows,
                turn_context_rows=turn_context_rows,
                task_case_evidence=reduced,
            )
            self.smoke_evidence = evidence
            if (
                evidence["observed_mcp_calls"] != scenario.expected_mcp_calls
                or evidence["observed_provider_calls"]
                != scenario.expected_provider_calls
                or evidence["provider_terminal_status"] != "SUCCEEDED"
                or evidence["model_visible_memory_tool_events"] != 0
                or evidence["raw_prompt_or_answer_persisted"] is not False
            ):
                raise RunError("U1 task final accounting failed")
            self._capture_worker_logs()
            return evidence
        except (RunError, task_scenarios.TaskScenarioError) as exc:
            update_measurement()
            try:
                self._capture_worker_logs()
            except RunError:
                pass
            raise RunError("U1 task smoke accounting failed") from exc

    @staticmethod
    def _append_only_delta(
        previous: Sequence[Mapping[str, Any]],
        current: Sequence[Mapping[str, Any]],
        *,
        artifact: str,
    ) -> list[dict[str, Any]]:
        if len(current) < len(previous) or list(current[: len(previous)]) != list(
            previous
        ):
            raise RunError(f"{artifact} append-only accounting changed")
        return [dict(row) for row in current[len(previous) :]]

    def _interaction_provider_observation(
        self,
        ledger_delta: Sequence[Mapping[str, Any]],
        answers: Sequence[Mapping[str, Any]],
        *,
        expected_rounds: int,
    ) -> dict[str, object]:
        expected_events = [
            event
            for _ in range(expected_rounds)
            for event in (
                "RESERVED",
                "PROVIDER_TERMINAL",
                "POST_PROVIDER_TERMINAL",
            )
        ]
        if [row.get("event") for row in ledger_delta] != expected_events:
            raise RunError("interaction provider ledger sequence is invalid")
        if len(answers) != expected_rounds:
            raise RunError("interaction provider trace count is invalid")

        logical_ids: list[str] = []
        native_ids: list[str] = []
        terminals: list[dict[str, Any]] = []
        for index in range(expected_rounds):
            reservation, terminal, post = ledger_delta[index * 3 : index * 3 + 3]
            answer = answers[index]
            logical_id = reservation.get("logical_request_id")
            native_id = terminal.get("native_request_id")
            if (
                not isinstance(logical_id, str)
                or not logical_id
                or logical_id in logical_ids
                or terminal.get("logical_request_id") != logical_id
                or post.get("logical_request_id") != logical_id
                or answer.get("logical_request_id") != logical_id
                or reservation.get("transport") != "stream"
                or terminal.get("transport") != "stream"
                or answer.get("provider_transport") != "stream"
                or terminal.get("status") != "SUCCEEDED"
                or terminal.get("reason_code") is not None
                or terminal.get("request_started") is not True
                or terminal.get("native_request_observed") is not True
                or not isinstance(native_id, str)
                or not native_id
                or native_id in native_ids
                or answer.get("native_request_id") != native_id
                or post.get("status") != "SUCCEEDED"
                or post.get("reason_code") is not None
                or answer.get("provider_call") is not True
            ):
                raise RunError("interaction provider ledger/trace join is invalid")
            for usage_field in ("prompt_tokens", "completion_tokens"):
                usage = terminal.get(usage_field)
                if (
                    not isinstance(usage, int)
                    or isinstance(usage, bool)
                    or usage < 0
                    or answer.get(usage_field) != usage
                ):
                    raise RunError("interaction provider usage observation is invalid")
            logical_ids.append(logical_id)
            native_ids.append(native_id)
            terminals.append(dict(terminal))
        return {
            "logical_ids": logical_ids,
            "native_ids": native_ids,
            "terminals": terminals,
            "native_request_id_sha256": self._scenario_digest(native_ids),
            "logical_request_id_sha256": self._scenario_digest(logical_ids),
        }

    @staticmethod
    def _interaction_answer_policy(
        answer: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        policy = answer.get("ordinary_tool_policy")
        if policy is None:
            return None
        if not isinstance(policy, Mapping):
            raise RunError("interaction ordinary-tool policy trace is invalid")
        required = {
            "policy",
            "round",
            "requested_tool_choice",
            "effective_tool_choice",
            "ordinary_tool_count",
            "ordinary_tool_name_sha256",
            "assistant_tool_call_count",
            "tool_result_count",
            "matching_tool_result_count",
            "tool_call_id_sha256",
        }
        if set(policy) != required:
            raise RunError("interaction ordinary-tool policy trace is invalid")
        return policy

    def _interaction_observation(
        self,
        *,
        parsed: Mapping[str, object],
        completed: subprocess.CompletedProcess[bytes],
        ledger_delta: Sequence[Mapping[str, Any]],
        trace_delta: Sequence[Mapping[str, Any]],
        prompt: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        plan = interaction_scenarios.interaction_plan(self.case.case_id)
        expected_rounds = plan.provider_rounds
        native_requests = [
            row
            for row in trace_delta
            if row.get("event") == "HOST_NATIVE_REQUEST_OBSERVED"
        ]
        attempts = [
            row for row in trace_delta if row.get("event") == "HOST_MCP_PREPARE_ATTEMPT"
        ]
        prepares = [
            row for row in trace_delta if row.get("event") == "HOST_MCP_PREPARE_CONTEXT"
        ]
        answers = [row for row in trace_delta if row.get("event") == "PROVIDER_ANSWER"]
        visible_memory_tools = [
            row
            for row in trace_delta
            if row.get("event") == "PROVIDER_MEMORY_TOOL_VISIBLE"
        ]
        forbidden_terminals = [
            row for row in trace_delta if row.get("event") == "HOST_INGRESS_TERMINAL"
        ]
        provider_call_rows = [row for row in trace_delta if row.get("provider_call")]
        if (
            len(native_requests) != expected_rounds
            or len(answers) != expected_rounds
            or provider_call_rows != answers
            or visible_memory_tools
            or forbidden_terminals
        ):
            raise RunError("interaction Host trace accounting is invalid")
        if any(
            row.get("stream") is not True or row.get("stream_include_usage") is not True
            for row in native_requests
        ):
            raise RunError("interaction native stream request contract is invalid")

        provider = self._interaction_provider_observation(
            ledger_delta,
            answers,
            expected_rounds=expected_rounds,
        )
        terminals = provider["terminals"]
        assert isinstance(terminals, list)
        if any(
            not isinstance(answer.get("excluded_memory_tools"), list)
            or answer.get("excluded_memory_tools") != ["milai_milai_recall"]
            for answer in answers
        ):
            raise RunError("interaction MiLA tool filtering trace is invalid")

        sensitive_needles = _opencode_sensitive_payload_needles(
            completed.stdout,
            fixture_markers=(prompt.encode(),),
        )
        raw_persisted = _durable_payload_observed(
            self.paths.durable,
            sensitive_needles,
            minimum_needle_bytes=1,
        )
        if self.case.case_id == "U1-STREAM":
            if (
                len(attempts) != 1
                or len(prepares) != 1
                or any(answer.get("ordinary_tool_count") != 0 for answer in answers)
                or terminals[0].get("finish_reason") != "stop"
                or answers[0].get("finish_reason") != "stop"
                or parsed.get("terminal_success_event_count") not in {0, 1}
                or parsed.get("completed_ordinary_tool_event_count") != 0
            ):
                raise RunError("stream interaction call accounting is invalid")
            prepare = prepares[0]
            access_outcome = prepare.get("access_outcome")
            if (
                attempts[0].get("logical_mcp_calls") != 1
                or prepare.get("prepare_status", "READY") != "READY"
                or prepare.get("current_state_status") not in {"HIT", "READY"}
                or not isinstance(prepare.get("current_state_claim_count"), int)
                or int(prepare["current_state_claim_count"]) < 1
                or not isinstance(prepare.get("compiled_memory_tokens"), int)
                or int(prepare["compiled_memory_tokens"]) <= 0
                or (
                    prepare.get("route") != "EXACT"
                    and (
                        access_outcome.get("terminal_stage")
                        if isinstance(access_outcome, Mapping)
                        else None
                    )
                    != "EXACT"
                )
                or answers[0].get("mcp_calls") != 1
                or answers[0].get("context_in_prompt") is not True
                or self._interaction_answer_policy(answers[0]) is not None
            ):
                raise RunError("stream EXACT memory trace is invalid")
            observation: dict[str, object] = {
                "request": {
                    "stream": True,
                    "include_usage": True,
                    "provider_memory_tool_count": 0,
                    "excluded_memory_tool_count": 1,
                },
                "gateway": {
                    "terminal_event_count": 1,
                    "done_observed": True,
                    "usage_observed": True,
                    "native_id_count": 1,
                    "native_request_id_sha256": hashlib.sha256(
                        str(provider["native_ids"][0]).encode()
                    ).hexdigest(),
                    "finish_reason": "stop",
                    "terminal_status": "SUCCEEDED",
                },
                "opencode": {
                    "exit_code": completed.returncode,
                    "json_event_count": parsed.get("json_event_count"),
                    "terminal_success_event_count": parsed.get(
                        "terminal_success_event_count"
                    ),
                    "json_parse_error_count": parsed.get("json_parse_error_count"),
                    "typed_error_count": parsed.get("typed_error_count"),
                },
                "provider": {
                    "attempts": 1,
                    "automatic_retries": 0,
                    "ledger_events": [
                        "RESERVED",
                        "PROVIDER_TERMINAL",
                        "POST_PROVIDER_TERMINAL",
                    ],
                },
                "mcp": {"calls": 1, "automatic_retries": 0},
                "host": {"terminal_status": "SUCCEEDED"},
                "persistence": {
                    "raw_sse_frames": raw_persisted,
                    "opencode_event_body": raw_persisted,
                    "prompt": raw_persisted,
                    "credentials": False,
                    "response_content": raw_persisted,
                },
            }
            details = {
                "context_tokens": int(prepare["compiled_memory_tokens"]),
                "current_state_status": prepare.get("current_state_status"),
                "current_state_claim_count": prepare.get(
                    "current_state_claim_count", 0
                ),
                "mcp_receipt_sha256": self._scenario_digest(access_outcome),
                "runtime_trace_sha256": self._scenario_digest(
                    prepare.get("recall_execution_trace")
                ),
                "trace_id_sha256": (
                    hashlib.sha256(str(answers[0]["trace_id"]).encode()).hexdigest()
                    if isinstance(answers[0].get("trace_id"), str)
                    else None
                ),
            }
            return observation, details

        cli_terminal_count = parsed.get("terminal_success_event_count")
        cli_tool_count = parsed.get("completed_ordinary_tool_event_count")
        cli_tool_name_sha256 = parsed.get("completed_ordinary_tool_name_sha256")
        if (
            attempts
            or prepares
            or any(answer.get("mcp_calls") != 0 for answer in answers)
            or any(answer.get("context_in_prompt") is not False for answer in answers)
            or [answer.get("ordinary_tool_count") for answer in answers] != [0, 1]
            or [answer.get("ordinary_tool_delivery") for answer in answers]
            != ["VLLM_JSON_SCHEMA_NAMED_TOOL_ADAPTER", "NATIVE_NONE"]
            or [terminal.get("finish_reason") for terminal in terminals]
            != ["stop", "stop"]
            or [answer.get("finish_reason") for answer in answers] != ["stop", "stop"]
            or not isinstance(cli_terminal_count, int)
            or isinstance(cli_terminal_count, bool)
            or cli_terminal_count not in {0, 1, 2}
            or not isinstance(cli_tool_count, int)
            or isinstance(cli_tool_count, bool)
            or cli_tool_count not in {0, 1}
            or (
                cli_tool_count == 1
                and cli_tool_name_sha256 != hashlib.sha256(b"read").hexdigest()
            )
            or (cli_tool_count == 0 and cli_tool_name_sha256 is not None)
        ):
            raise RunError("ordinary interaction call accounting is invalid")
        policies = [self._interaction_answer_policy(answer) for answer in answers]
        if any(policy is None for policy in policies):
            raise RunError("ordinary interaction policy trace is absent")
        first_policy, second_policy = policies
        assert first_policy is not None and second_policy is not None
        delivery = answers[0].get("ordinary_tool_delivery_evidence")
        if not isinstance(delivery, Mapping):
            raise RunError("ordinary interaction delivery trace is absent")
        call_id_sha256 = second_policy.get("tool_call_id_sha256")
        if not isinstance(call_id_sha256, str):
            raise RunError("ordinary interaction paired tool id is absent")
        read_sha256 = hashlib.sha256(b"read").hexdigest()

        rounds: list[dict[str, object]] = []
        for index, policy in enumerate((first_policy, second_policy)):
            rounds.append(
                {
                    "round": policy.get("round"),
                    "requested_tool_choice": policy.get("requested_tool_choice"),
                    "effective_tool_choice": policy.get("effective_tool_choice"),
                    "ordinary_tool_count": policy.get("ordinary_tool_count"),
                    "ordinary_tool_name_sha256": policy.get(
                        "ordinary_tool_name_sha256"
                    ),
                    "provider_memory_tool_count": 0,
                    "excluded_memory_tool_count": 1,
                    "assistant_tool_call_count": policy.get(
                        "assistant_tool_call_count"
                    ),
                    "tool_result_count": policy.get("tool_result_count"),
                    "matching_tool_result_count": policy.get(
                        "matching_tool_result_count"
                    ),
                    "tool_call_id_sha256": policy.get("tool_call_id_sha256"),
                    "provider_finish_reason": terminals[index].get("finish_reason"),
                    "provider_payload_ordinary_tool_count": answers[index].get(
                        "ordinary_tool_count"
                    ),
                    "tool_call_delivery": answers[index].get("ordinary_tool_delivery"),
                    "delivered_tool_call_count": 1 if index == 0 else 0,
                    "delivered_tool_name_sha256": read_sha256 if index == 0 else None,
                    "delivered_tool_call_id_sha256": (
                        call_id_sha256 if index == 0 else None
                    ),
                }
            )
        observation = {
            "rounds": rounds,
            "provider": {
                "attempts": 2,
                "automatic_retries": 0,
                "terminal_count": 2,
                "post_terminal_count": 2,
                "logical_request_ids_unique": True,
                "third_round_observed": False,
            },
            "mcp": {"calls": 0, "automatic_retries": 0},
            "host": {
                # The second Host-observed request carries the matching tool
                # result even when this OpenCode version drops CLI JSONL events.
                "tool_execution_count": second_policy.get("matching_tool_result_count"),
                "tool_name_sha256": read_sha256,
                "tool_call_id_sha256": call_id_sha256,
                "tool_result_call_id_sha256": call_id_sha256,
                "third_round_observed": False,
            },
            "delivery": dict(delivery),
            "persistence": {
                "tool_arguments": raw_persisted,
                "tool_result": raw_persisted,
                "prompt": raw_persisted,
                "credentials": False,
            },
        }
        return observation, {
            "context_tokens": 0,
            "current_state_status": None,
            "current_state_claim_count": 0,
            "mcp_receipt_sha256": None,
            "runtime_trace_sha256": None,
            "trace_id_sha256": None,
        }

    def _smoke_interaction_scenario(self) -> dict[str, Any]:
        try:
            plan = interaction_scenarios.interaction_plan(self.case.case_id)
            if (
                plan.memory_need != self.case.memory_requirement
                or plan.provider_rounds != self.case.expected_provider_calls
                or plan.mcp_calls != self.case.expected_mcp_calls
                or plan.automatic_retries != 0
                or plan.request_stream is not True
                or plan.stream_include_usage is not True
            ):
                raise RunError("interaction CaseSpec contract drifted")
            prompt = interaction_scenarios.interaction_prompt(self.case.case_id)
            previous_ledger = _read_json_lines(self.provider_ledger)
            previous_trace = _read_json_lines(self.host_trace)
            session_id = self._create_opencode_session()
            command = interaction_scenarios.build_opencode_interaction_command(
                self.case.case_id,
                container_name=self.container_name,
                prompt=prompt,
                model=f"openworker/{MODEL_ID}",
                session_id=session_id,
            )
            started = time.monotonic()
            completed = _command_bytes(list(command), timeout=240, check=False)
            openworker_latency_ms = round((time.monotonic() - started) * 1000, 3)
            command_truth = self._write_smoke_command_diagnostic(
                completed,
                prompt=prompt,
            )
            parsed = interaction_scenarios.parse_opencode_interaction_events(
                completed.stdout
            )
            if (
                command_truth.status is not TerminalStatus.PASS
                or parsed.get("json_parse_error_count") != 0
                or parsed.get("typed_error_count") != 0
                or parsed.get("session_id_sha256")
                != hashlib.sha256(session_id.encode()).hexdigest()
            ):
                raise RunError("interaction OpenCode terminal failed")
            current_ledger = _read_json_lines(self.provider_ledger)
            current_trace = _read_json_lines(self.host_trace)
            ledger_delta = self._append_only_delta(
                previous_ledger,
                current_ledger,
                artifact="provider ledger",
            )
            trace_delta = self._append_only_delta(
                previous_trace,
                current_trace,
                artifact="Host trace",
            )
            observation, details = self._interaction_observation(
                parsed=parsed,
                completed=completed,
                ledger_delta=ledger_delta,
                trace_delta=trace_delta,
                prompt=prompt,
            )
            reduced = interaction_scenarios.reduce_interaction(
                self.case.case_id,
                observation,
            )
            case_artifact = {
                "schema": "milai.dg13u.u1-interaction-evidence.v1",
                "run_id": self.paths.run_id,
                "case_id": self.case.case_id,
                "opencode_events": dict(parsed),
                "interaction": reduced,
            }
            artifact_path = self.paths.durable / "interaction-evidence.json"
            _atomic_write(artifact_path, case_artifact)
            interaction_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            answers = [
                row for row in trace_delta if row.get("event") == "PROVIDER_ANSWER"
            ]
            provider = self._interaction_provider_observation(
                ledger_delta,
                answers,
                expected_rounds=plan.provider_rounds,
            )
            answer_timings = [
                _nonnegative_measured_ms(row.get("adapter_total_ms")) for row in answers
            ]
            provider_timings = [
                _nonnegative_measured_ms(row.get("provider_prefill_answer_ms"))
                for row in answers
            ]
            prepares = [
                row
                for row in trace_delta
                if row.get("event") == "HOST_MCP_PREPARE_CONTEXT"
            ]
            prepare_timing = (
                prepares[0].get("timing")
                if prepares and isinstance(prepares[0].get("timing"), Mapping)
                else {}
            )
            evidence = {
                "observed_provider_calls": plan.provider_rounds,
                "observed_mcp_calls": plan.mcp_calls,
                "provider_terminal_status": "SUCCEEDED",
                "native_request_id_sha256": provider["native_request_id_sha256"],
                "worker_exit_code": completed.returncode,
                "worker_output_sha256": hashlib.sha256(
                    completed.stdout + completed.stderr
                ).hexdigest(),
                "worker_output_bytes": len(completed.stdout) + len(completed.stderr),
                "automatic_retries": 0,
                "mcp_automatic_retries": 0,
                "unaccounted_mcp_calls": 0,
                "unaccounted_provider_calls": 0,
                "memory_route": plan.memory_need,
                "context_tokens": details["context_tokens"],
                "context_in_prompt": self.case.case_id == "U1-STREAM",
                "current_state_status": details["current_state_status"],
                "current_state_claim_count": details["current_state_claim_count"],
                "access_id_sha256": provider["logical_request_id_sha256"],
                "mcp_receipt_sha256": details["mcp_receipt_sha256"],
                "runtime_trace_sha256": (
                    details["runtime_trace_sha256"] or interaction_sha256
                ),
                "trace_id_sha256": details["trace_id_sha256"],
                "latencies_ms": {
                    "openworker": openworker_latency_ms,
                    "adapter": round(sum(answer_timings), 3),
                    "mcp": _nonnegative_measured_ms(
                        prepare_timing.get("mcp_handler_ms")
                    ),
                    "runtime": _nonnegative_measured_ms(
                        prepare_timing.get("runtime_total_ms")
                    ),
                    "compile": _nonnegative_measured_ms(
                        prepare_timing.get("context_compile_ms")
                    ),
                    "provider": round(sum(provider_timings), 3),
                },
                "model_visible_memory_tool_events": 0,
                "raw_prompt_or_answer_persisted": any(
                    bool(value) for value in observation["persistence"].values()
                ),
                "safety_failures": {name: 0 for name in self.case.safety_counters},
                "interaction_evidence": reduced,
                "interaction_evidence_sha256": interaction_sha256,
                "opencode_interaction_events": dict(parsed),
            }
            self.smoke_evidence = evidence
            self._capture_worker_logs()
            return evidence
        except (
            RunError,
            interaction_scenarios.InteractionScenarioError,
        ) as exc:
            try:
                self._capture_worker_logs()
            except RunError:
                pass
            raise RunError("U1 interaction smoke accounting failed") from exc

    def smoke(self) -> dict[str, Any]:
        if self.case.case_id not in _IMPLEMENTED_REAL_CASES:
            raise RunError("real smoke for this U1 case is not implemented")
        if self.case.case_id in _LIFECYCLE_CASE_IDS:
            return self._smoke_lifecycle_scenario()
        if self.case.case_id in _CACHE_GOVERNANCE_CASE_IDS:
            return self._smoke_cache_governance_scenario()
        if self.case.case_id in _TASK_CASE_IDS:
            return self._smoke_task_scenario()
        if self.case.case_id in _FAULT_CASE_IDS:
            return self._smoke_fault_scenario()
        if self.case.case_id in _INTERACTION_CASE_IDS:
            return self._smoke_interaction_scenario()
        prompt = _case_prompt(self.case)
        smoke_started = time.monotonic()
        completed = _command_bytes(
            [
                "docker",
                "exec",
                "--workdir",
                "/openworker/runtime",
                "--env",
                "OPENCODE_CONFIG_DIR=/openworker/runtime",
                self.container_name,
                "opencode",
                "run",
                "--format",
                "json",
                "--model",
                f"openworker/{MODEL_ID}",
                prompt,
            ],
            timeout=240,
            check=False,
        )
        openworker_latency_ms = round((time.monotonic() - smoke_started) * 1000, 3)
        command_truth = self._write_smoke_command_diagnostic(completed, prompt=prompt)
        self._capture_worker_logs()
        ledger = _read_json_lines(self.provider_ledger)
        trace = _read_json_lines(self.host_trace)
        reservations = [row for row in ledger if row.get("event") == "RESERVED"]
        terminals = [row for row in ledger if row.get("event") == "PROVIDER_TERMINAL"]
        route_none = [
            row for row in trace if row.get("event") == "HOST_MEMORY_ROUTE_NONE"
        ]
        prepares = [
            row for row in trace if row.get("event") == "HOST_MCP_PREPARE_CONTEXT"
        ]
        provider_answers = [
            row for row in trace if row.get("event") == "PROVIDER_ANSWER"
        ]
        observed_mcp = len(prepares)
        context_tokens = sum(
            int(row["compiled_memory_tokens"])
            for row in prepares
            if isinstance(row.get("compiled_memory_tokens"), int)
        )
        common_success = (
            command_truth.status == TerminalStatus.PASS
            and bool(completed.stdout.strip())
            and len(reservations) == 1
            and len(terminals) == 1
            and terminals[0].get("status") == "SUCCEEDED"
            and len(provider_answers) == 1
        )
        if self.case.memory_requirement == "NONE":
            success = (
                common_success
                and len(route_none) == 1
                and not prepares
                and observed_mcp == 0
                and provider_answers[0].get("context_in_prompt") is False
            )
            memory_route = "NONE"
        else:
            success = (
                common_success
                and not route_none
                and len(prepares) == 1
                and observed_mcp == 1
                and (
                    prepares[0].get("route") == "EXACT"
                    or (prepares[0].get("access_outcome") or {}).get("terminal_stage")
                    == "EXACT"
                )
                and prepares[0].get("prepare_status", "READY") == "READY"
                and prepares[0].get("current_state_status") in {"HIT", "READY"}
                and int(prepares[0].get("current_state_claim_count", 0)) >= 1
                and context_tokens > 0
                and provider_answers[0].get("context_in_prompt") is True
            )
            memory_route = "EXACT"
        native_id = terminals[0].get("native_request_id") if terminals else None
        provider_answer = provider_answers[0] if provider_answers else {}
        prepare = prepares[0] if prepares else {}
        prepare_timing = prepare.get("timing")
        if not isinstance(prepare_timing, Mapping):
            prepare_timing = {}
        logical_request_id = provider_answer.get("logical_request_id")
        trace_id = provider_answer.get("trace_id")
        evidence = {
            "observed_provider_calls": len(reservations),
            "observed_mcp_calls": observed_mcp,
            "provider_terminal_status": (
                terminals[0].get("status") if terminals else None
            ),
            "native_request_id_sha256": (
                hashlib.sha256(native_id.encode()).hexdigest()
                if isinstance(native_id, str)
                else None
            ),
            "worker_exit_code": completed.returncode,
            "worker_output_sha256": hashlib.sha256(
                completed.stdout + completed.stderr
            ).hexdigest(),
            "worker_output_bytes": len(completed.stdout) + len(completed.stderr),
            "automatic_retries": 0,
            "mcp_automatic_retries": 0,
            "unaccounted_mcp_calls": 0,
            "unaccounted_provider_calls": 0,
            "memory_route": memory_route,
            "context_tokens": context_tokens,
            "context_in_prompt": provider_answer.get("context_in_prompt") is True,
            "current_state_status": prepare.get("current_state_status"),
            "current_state_claim_count": prepare.get("current_state_claim_count", 0),
            "access_id_sha256": (
                hashlib.sha256(logical_request_id.encode()).hexdigest()
                if isinstance(logical_request_id, str)
                else None
            ),
            "mcp_receipt_sha256": (
                hashlib.sha256(
                    u0._canonical_bytes(prepare.get("access_outcome"))
                ).hexdigest()
                if prepare.get("access_outcome") is not None
                else None
            ),
            "runtime_trace_sha256": (
                hashlib.sha256(
                    u0._canonical_bytes(prepare.get("recall_execution_trace"))
                ).hexdigest()
                if prepare.get("recall_execution_trace") is not None
                else None
            ),
            "trace_id_sha256": (
                hashlib.sha256(trace_id.encode()).hexdigest()
                if isinstance(trace_id, str)
                else None
            ),
            "latencies_ms": {
                "openworker": openworker_latency_ms,
                "adapter": _nonnegative_measured_ms(
                    provider_answer.get("adapter_total_ms")
                ),
                "mcp": _nonnegative_measured_ms(prepare_timing.get("mcp_handler_ms")),
                "runtime": _nonnegative_measured_ms(
                    prepare_timing.get("runtime_total_ms")
                ),
                "compile": _nonnegative_measured_ms(
                    prepare_timing.get("context_compile_ms")
                ),
                "provider": _nonnegative_measured_ms(
                    provider_answer.get("provider_prefill_answer_ms")
                ),
            },
            "model_visible_memory_tool_events": sum(
                row.get("event") == "PROVIDER_MEMORY_TOOL_VISIBLE" for row in trace
            ),
            "raw_prompt_or_answer_persisted": _durable_payload_observed(
                self.paths.durable,
                (prompt.encode(), completed.stdout, completed.stderr),
            ),
            "safety_failures": {name: 0 for name in self.case.safety_counters},
        }
        self.smoke_evidence = evidence
        if not success:
            raise RunError("U1 OpenWorker smoke accounting failed")
        return evidence

    def reconciliation(self) -> dict[str, Any]:
        if self.smoke_evidence is None:
            raise RunError("U1 smoke evidence is absent")
        if self.socket_identity is None or not self.socket_path.exists():
            raise RunError("reader-lite socket identity was lost")
        current = self.socket_path.lstat()
        if (current.st_dev, current.st_ino) != self.socket_identity:
            raise RunError("reader-lite socket inode changed during the case")
        if self.broker_process is None or self.host_process is None:
            raise RunError("U1 process identity is absent")
        if (
            self.broker_process.poll() is not None
            or self.host_process.poll() is not None
        ):
            raise RunError("U1 process exited before reconciliation")
        if self.case.case_id in _LIFECYCLE_CASE_IDS:
            if self._resources is None or self.lifecycle_measurement is None:
                raise RunError("lifecycle generation measurement is absent")
            generations = resource_registry.process_snapshot_by_role(
                self._resources.snapshot()
            )
            broker = generations.get("mcp-broker")
            host = generations.get("host-adapter")
            if (
                broker is None
                or host is None
                or broker.pid != self.broker_process.pid
                or broker.marker != self.broker_marker
                or host.pid != self.host_process.pid
                or host.marker != self.host_marker
                or broker.generation != self.broker_generation
                or host.generation != self.host_generation
            ):
                raise RunError("lifecycle current registry generation drifted")
        secrets_to_find = tuple(
            value
            for value in (self.ingress_token, self.runtime.reader_token)
            if value is not None
        )
        for artifact in self.paths.durable.rglob("*"):
            if artifact.is_file() and any(
                secret.encode() in artifact.read_bytes() for secret in secrets_to_find
            ):
                raise RunError("credential material reached a durable artifact")
        evidence = {
            **self.smoke_evidence,
            "broker_socket_inode_preserved": (
                self.case.case_id != "U1-BROKER-INODE-RECREATE"
            ),
            "host_process_preserved": self.case.case_id != "U1-ADAPTER-RESTART",
            "broker_process_preserved": (
                self.case.case_id != "U1-BROKER-INODE-RECREATE"
            ),
            "durable_credentials_found": 0,
            "unaccounted_calls": 0,
            "external_lifecycle_mutations": 0,
            "existing_vllm_preserved": True,
        }
        return evidence


def _evidence_calls(case: CaseSpec, measured: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mcp": {
            "expected": case.expected_mcp_calls,
            "observed": int(measured.get("observed_mcp_calls", 0)),
            "unaccounted": int(measured.get("unaccounted_mcp_calls", 0)),
            "automatic_retries": int(measured.get("mcp_automatic_retries", 0)),
        },
        "provider": {
            "expected": case.expected_provider_calls,
            "observed": int(measured.get("observed_provider_calls", 0)),
            "unaccounted": int(measured.get("unaccounted_provider_calls", 0)),
            "automatic_retries": int(measured.get("automatic_retries", 0)),
            "maximum_per_model_round": 1,
            "model_rounds": case.expected_provider_calls,
            "calls_per_task_operation": case.expected_provider_calls,
            "case_maximum": case.expected_provider_calls,
        },
    }


def _evidence_joins(measured: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "access_id_sha256": measured.get("access_id_sha256"),
        "mcp_receipt_sha256": measured.get("mcp_receipt_sha256"),
        "runtime_trace_sha256": measured.get("runtime_trace_sha256"),
        "provider_native_request_id_sha256": measured.get("native_request_id_sha256"),
    }


def _smoke_artifact_measurement(
    paths: RunPaths,
    case: CaseSpec,
    status: TerminalStatus,
    measured: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "run_id": paths.run_id,
        "case_id": case.case_id,
        "status": status,
        "calls": _evidence_calls(case, measured),
        "joined_identities": _evidence_joins(measured),
        "latencies_ms": dict(measured.get("latencies_ms") or {}),
        "context_tokens": int(measured.get("context_tokens", 0)),
        "model_visible_memory_tool_events": int(
            measured.get("model_visible_memory_tool_events", 0)
        ),
        "raw_prompt_or_answer_persisted": bool(
            measured.get("raw_prompt_or_answer_persisted", False)
        ),
        "provider_terminal_status": measured.get("provider_terminal_status"),
        "worker_exit_code": int(measured.get("worker_exit_code", -1)),
        "worker_output_sha256": measured.get("worker_output_sha256"),
        "worker_output_bytes": int(measured.get("worker_output_bytes", 0)),
        "memory_route": measured.get("memory_route", case.memory_requirement),
    }


class LocalComposition:
    """Incremental exact-current launcher; later stages remain explicitly NOT_RUN."""

    def __init__(self, env_file: Path) -> None:
        self.env_file = env_file
        self.runtime: FreshRuntimeLifecycle | None = None
        self.fixture: CanonicalFixtureLifecycle | None = None
        self.u1: OpenWorkerU1Lifecycle | None = None
        self.identity: dict[str, Any] | None = None
        self.readiness_evidence: dict[str, Any] | None = None
        self.smoke_evidence: dict[str, Any] | None = None
        self.reconciliation_evidence: dict[str, Any] | None = None
        self.cache_governance_finalizer: CacheGovernanceScenarioFinalizer | None = None
        self.lifecycle_finalizer: LifecycleScenarioFinalizer | None = None

    def start(
        self, paths: RunPaths, case: CaseSpec, resources: ResourceRegistry
    ) -> CompositionResult:
        source = u0._collect_source_identity()
        packages = u0._build_and_probe_packages(paths.durable, paths.temporary)
        image = u0._run_json(["docker", "image", "inspect", OPENWORKER_IMAGE])
        if (
            not isinstance(image, list)
            or len(image) != 1
            or not isinstance(image[0], dict)
        ):
            raise RunError("U1 OpenWorker image identity is absent or ambiguous")
        vllm = u0._probe_vllm()
        if (
            vllm.get("completion_calls") != 0
            or vllm.get("lifecycle_mutated") is not False
        ):
            raise RunError("vLLM identity probe changed provider state")
        product_venv, product_manifest = _build_product_venv(
            paths, packages, case_id=case.case_id
        )
        self.runtime = FreshRuntimeLifecycle(
            paths, self.env_file, packages["migration_head"], product_venv
        )
        runtime_started = time.monotonic()
        runtime = self.runtime.start(resources)
        runtime_readiness_ms = round((time.monotonic() - runtime_started) * 1000, 3)
        canonical_fixture: Mapping[str, Any] | None = None
        if case.case_id in _CANONICAL_POSITIVE_CASES:
            options = _fixture_options_for_case(case.case_id)
            if options is None:
                raise RunError("canonical fixture options are absent")
            self.fixture = CanonicalFixtureLifecycle(paths, self.runtime, options)
            canonical_fixture = self.fixture.start(resources)
        self.u1 = OpenWorkerU1Lifecycle(paths, case, self.runtime, product_venv)
        self.u1.fixture = self.fixture
        self.u1.readiness_latencies_ms["runtime"] = runtime_readiness_ms
        u1_topology = self.u1.start(resources)
        self.identity = {
            "schema": "milai.dg13u.u1-identity-preflight.v1",
            "run_id": paths.run_id,
            "case_id": case.case_id,
            "status": TerminalStatus.PASS,
            "source": source,
            "u1_runner": u0._file_identity(Path(__file__), relative_to=ROOT),
            "packages": packages,
            "exact_product": product_manifest,
            "openworker_image": {
                "reference": OPENWORKER_IMAGE,
                "id": image[0].get("Id"),
                "created": image[0].get("Created"),
                "architecture": image[0].get("Architecture"),
                "os": image[0].get("Os"),
            },
            "vllm": vllm,
            "fresh_runtime": runtime.public(),
            "canonical_fixture": canonical_fixture,
            "u1_topology": u1_topology,
        }
        manifest_path = paths.durable / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("run_id") != paths.run_id:
            raise RunError("run manifest identity drift")
        manifest["resolved_composition"] = {
            "exact_product": product_manifest,
            "exact_product_manifest": u0._file_identity(
                paths.durable / "exact-product-manifest.json",
                relative_to=paths.durable,
            ),
        }
        _atomic_write(manifest_path, manifest)
        _atomic_write(paths.durable / "identity-preflight.json", self.identity)
        return CompositionResult(
            TerminalStatus.PASS,
            "EXACT_FRESH_U1_COMPOSITION_STARTED",
            {
                "source_sha256": source["sha256"],
                "openworker_image_id": image[0].get("Id"),
                "vllm_container_id": (vllm.get("container") or {}).get("id"),
                "product_entrypoints": product_manifest["entrypoints"],
                "runtime": runtime.public(),
                "u1_topology": u1_topology,
            },
        )

    def readiness(self, paths: RunPaths, case: CaseSpec) -> CompositionResult:
        if (
            self.runtime is None
            or self.u1 is None
            or self.identity is None
            or not self.runtime.ready()
        ):
            return CompositionResult(TerminalStatus.FAIL, "FRESH_RUNTIME_NOT_READY", {})
        try:
            readiness = self.u1.readiness()
        except RunError as exc:
            reason_code = {
                "OpenWorker MCP list command failed": (
                    "OPENWORKER_MCP_LIST_COMMAND_FAILED"
                ),
                "OpenWorker reader-lite MCP is not connected": (
                    "OPENWORKER_MCP_NOT_CONNECTED"
                ),
                "OpenWorker health readiness timeout": (
                    "OPENWORKER_HEALTH_READINESS_TIMEOUT"
                ),
                "OpenWorker exited before readiness": (
                    "OPENWORKER_EXITED_BEFORE_READINESS"
                ),
                "Host or broker exited before readiness": (
                    "HOST_OR_BROKER_EXITED_BEFORE_READINESS"
                ),
            }.get(str(exc), "U1_READINESS_ERROR")
            failure = {
                "schema": "milai.dg13u.u1-readiness-failure.v1",
                "run_id": paths.run_id,
                "case_id": case.case_id,
                "status": TerminalStatus.FAIL,
                "reason_code": reason_code,
                "exception_class": type(exc).__name__,
                "message_sha256": hashlib.sha256(str(exc).encode()).hexdigest(),
            }
            _atomic_write(paths.durable / "readiness-failure.json", failure)
            return CompositionResult(
                TerminalStatus.FAIL,
                reason_code,
                {
                    "error_type": type(exc).__name__,
                    "message_sha256": failure["message_sha256"],
                },
            )
        self.readiness_evidence = readiness
        return CompositionResult(
            TerminalStatus.PASS,
            "FRESH_RUNTIME_BROKER_HOST_OPENWORKER_READY",
            readiness,
        )

    def smoke(self, paths: RunPaths, case: CaseSpec) -> CompositionResult:
        if self.u1 is None:
            return CompositionResult(TerminalStatus.FAIL, "U1_COMPOSITION_ABSENT", {})
        if case.case_id not in _IMPLEMENTED_REAL_CASES:
            return CompositionResult(
                TerminalStatus.NOT_RUN,
                "U1_EXACT_CASE_SMOKE_PENDING",
                {"provider_calls": 0, "mcp_calls": 0},
            )
        try:
            evidence = self.u1.smoke()
        except RunError as exc:
            measured = dict(self.u1.smoke_evidence or {})
            self.smoke_evidence = measured
            artifact_error: evidence_artifacts.EvidenceArtifactError | None = None
            if measured:
                try:
                    evidence_artifacts.write_smoke_evidence_artifact(
                        paths.durable,
                        _smoke_artifact_measurement(
                            paths,
                            case,
                            TerminalStatus.FAIL,
                            measured,
                        ),
                    )
                except evidence_artifacts.EvidenceArtifactError as evidence_exc:
                    artifact_error = evidence_exc
            return CompositionResult(
                TerminalStatus.FAIL,
                (
                    "U1_NONE_REAL_OPENWORKER_SMOKE_FAILED"
                    if case.memory_requirement == "NONE"
                    else "U1_EXACT_REAL_OPENWORKER_SMOKE_FAILED"
                ),
                {
                    **measured,
                    "error_type": type(exc).__name__,
                    "error_message_sha256": hashlib.sha256(
                        str(exc).encode()
                    ).hexdigest(),
                    "failure_evidence_error_type": (
                        type(artifact_error).__name__
                        if artifact_error is not None
                        else None
                    ),
                },
            )
        self.smoke_evidence = dict(evidence)
        cache_measurement = getattr(self.u1, "cache_governance_measurement", None)
        if cache_measurement is not None:
            self.cache_governance_finalizer = CacheGovernanceScenarioFinalizer(
                paths,
                case.case_id,
                cache_measurement,
                self.fixture,
            )
        lifecycle_measurement = getattr(self.u1, "lifecycle_measurement", None)
        if lifecycle_measurement is not None:
            if self.identity is None or not isinstance(
                self.identity.get("vllm"), Mapping
            ):
                raise RunError("lifecycle initial vLLM identity is absent")
            self.lifecycle_finalizer = LifecycleScenarioFinalizer(
                paths,
                case.case_id,
                lifecycle_measurement,
                self.identity["vllm"],
            )
        return CompositionResult(
            TerminalStatus.PASS,
            (
                "U1_NONE_REAL_OPENWORKER_SMOKE_PASSED"
                if case.memory_requirement == "NONE"
                else "U1_EXACT_REAL_OPENWORKER_SMOKE_PASSED"
            ),
            evidence,
        )

    def finalize_after_cleanup(
        self,
        paths: RunPaths,
        case: CaseSpec,
        cleanup: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        del paths
        if case.case_id not in (_CACHE_GOVERNANCE_CASE_IDS | _LIFECYCLE_CASE_IDS):
            return None
        if case.case_id in _LIFECYCLE_CASE_IDS:
            if self.lifecycle_finalizer is None:
                raise RunError("lifecycle scenario finalizer is absent")
            reduced = self.lifecycle_finalizer.finalize(cleanup)
            evidence_name = "lifecycle_evidence"
            evidence_path = (
                self.lifecycle_finalizer.paths.durable / "lifecycle-evidence.json"
            )
        else:
            if self.cache_governance_finalizer is None:
                raise RunError("cache/governance scenario finalizer is absent")
            reduced = self.cache_governance_finalizer.finalize(cleanup)
            evidence_name = "cache_governance_evidence"
            evidence_path = (
                self.cache_governance_finalizer.paths.durable
                / "cache-governance-evidence.json"
            )
        merged = {
            **(self.smoke_evidence or {}),
            evidence_name: reduced,
            f"{evidence_name}_sha256": u0._sha256_file(evidence_path),
        }
        self.smoke_evidence = merged
        self.reconciliation_evidence = {
            **(self.reconciliation_evidence or merged),
            evidence_name: reduced,
            f"{evidence_name}_sha256": merged[f"{evidence_name}_sha256"],
        }
        if self.u1 is not None:
            self.u1.smoke_evidence = dict(merged)
        return merged

    def reconciliation(self, paths: RunPaths, case: CaseSpec) -> CompositionResult:
        if self.u1 is None:
            return CompositionResult(TerminalStatus.FAIL, "U1_COMPOSITION_ABSENT", {})
        try:
            evidence = self.u1.reconciliation()
        except RunError as exc:
            return CompositionResult(
                TerminalStatus.FAIL,
                "U1_RECONCILIATION_FAILED",
                {"error_type": type(exc).__name__},
            )
        self.reconciliation_evidence = dict(evidence)
        return CompositionResult(
            TerminalStatus.PASS, "U1_CALL_AND_IDENTITY_RECONCILED", evidence
        )

    def write_final_evidence_artifacts(
        self,
        paths: RunPaths,
        case: CaseSpec,
        status: TerminalStatus,
        stage_rows: Sequence[Mapping[str, Any]],
        cleanup: Mapping[str, Any],
    ) -> None:
        if self.readiness_evidence is None or self.smoke_evidence is None:
            return
        readiness = self.readiness_evidence
        evidence_artifacts.write_readiness_artifact(
            paths.durable,
            {
                "run_id": paths.run_id,
                "case_id": case.case_id,
                "status": status,
                "components": {
                    name: readiness[name]
                    for name in ("runtime", "broker", "host", "openworker", "provider")
                },
                "provider_completion_calls": int(
                    readiness["provider_completion_calls"]
                ),
                "security": readiness["security"],
                "latencies_ms": readiness["latencies_ms"],
                "worker_health_sha256": readiness["worker_health_sha256"],
                "mcp_list_sha256": readiness["mcp_list_sha256"],
            },
        )
        smoke_path = paths.durable / "smoke-evidence.json"
        if smoke_path.exists():
            existing = json.loads(smoke_path.read_text(encoding="utf-8"))
            if existing.get("status") != status:
                raise RunError("smoke evidence final status binding changed")
        else:
            evidence_artifacts.write_smoke_evidence_artifact(
                paths.durable,
                _smoke_artifact_measurement(
                    paths,
                    case,
                    status,
                    self.smoke_evidence,
                ),
            )
        reconciled = self.reconciliation_evidence or self.smoke_evidence
        reconciliation_duration = next(
            (
                row.get("duration_ms", 0.0)
                for row in stage_rows
                if row.get("stage") == "reconciliation"
            ),
            0.0,
        )
        latencies = dict(reconciled.get("latencies_ms") or {})
        latencies["reconciliation"] = _nonnegative_measured_ms(reconciliation_duration)
        unaccounted = int(reconciled.get("unaccounted_mcp_calls", 0)) + int(
            reconciled.get("unaccounted_provider_calls", 0)
        )
        evidence_artifacts.write_reconciliation_artifact(
            paths.durable,
            {
                "run_id": paths.run_id,
                "case_id": case.case_id,
                "status": status,
                "calls": _evidence_calls(case, reconciled),
                "joined_identities": _evidence_joins(reconciled),
                "latencies_ms": latencies,
                "unaccounted_calls": unaccounted,
                "durable_credentials_found": int(
                    reconciled.get("durable_credentials_found", 0)
                ),
                "broker_socket_inode_preserved": bool(
                    reconciled.get("broker_socket_inode_preserved", False)
                ),
                "host_process_preserved": bool(
                    reconciled.get("host_process_preserved", False)
                ),
                "broker_process_preserved": bool(
                    reconciled.get("broker_process_preserved", False)
                ),
                "existing_vllm_preserved": bool(
                    cleanup.get("existing_vllm_preserved", False)
                ),
                "external_lifecycle_mutations": int(
                    cleanup.get("external_lifecycle_mutations", 0)
                ),
            },
        )


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _short_run_id(run_id: str) -> str:
    return "u1-" + hashlib.sha256(run_id.encode()).hexdigest()[:16]


def _validate_run_id(run_id: str) -> None:
    if _RUN_ID.fullmatch(run_id) is None:
        raise RunError("run_id must contain 8-96 lowercase URL-safe characters")
    u0._validate_python_version(sys.version_info[:2])


def _case(case_id: str) -> CaseSpec:
    try:
        return CASES[case_id]
    except KeyError as exc:
        raise RunError(f"unsupported case_id: {case_id}") from exc


def _atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(u0._canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _bound_identity(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise RunError(f"bound contract is absent: {path.relative_to(ROOT)}")
    return u0._file_identity(path, relative_to=ROOT)


def _read_run_document(path: Path, *, label: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_size > 1_048_576
        ):
            raise RunError(f"{label} is not a bounded regular file")
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise RunError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise RunError(f"{label} is not an object")
    return value


def _verify_final_product_binding(
    paths: RunPaths, expected_identity: Mapping[str, Any]
) -> None:
    manifest = _read_run_document(
        paths.durable / "manifest.json", label="final run manifest"
    )
    exact_path = paths.durable / "exact-product-manifest.json"
    exact_product = _read_run_document(exact_path, label="exact product manifest")
    identity = _read_run_document(
        paths.durable / "identity-preflight.json", label="identity preflight"
    )
    resolved = manifest.get("resolved_composition")
    if not isinstance(resolved, Mapping):
        raise RunError("final exact product binding is absent")
    current_file_identity = u0._file_identity(exact_path, relative_to=paths.durable)
    if (
        resolved.get("exact_product") != exact_product
        or resolved.get("exact_product_manifest") != current_file_identity
        or expected_identity.get("exact_product") != exact_product
        or identity != dict(expected_identity)
    ):
        raise RunError("final exact product binding drifted")


def _secondary_error(stage: str, exc: BaseException) -> dict[str, str]:
    return {
        "stage": stage,
        "type": type(exc).__name__,
        "message_sha256": hashlib.sha256(str(exc).encode()).hexdigest(),
    }


def _execution_manifest(paths: RunPaths, case: CaseSpec) -> dict[str, Any]:
    fixture = _bound_identity(CANDIDATE_FIXTURE)
    if fixture["sha256"] != _REQUIRED_FIXTURE_SHA256:
        raise RunError("candidate fixture identity drift")
    return {
        "schema": "milai.dg13u.u1-run-manifest.v1",
        "run_id": paths.run_id,
        "case_id": case.case_id,
        "created_at": _now(),
        "status": TerminalStatus.NOT_RUN,
        "release_label": "LOCAL_OPENWORKER_MCP_CURRENT_STATE_USABLE",
        "release_label_earned": False,
        "scope": {
            "deployment": "LOCAL",
            "profile": "reader-lite",
            "consistency": "STRICT_CURRENT",
            "task_continuity": "SAME_ADAPTER_PROCESS_ONLY",
            "data": "SYNTHETIC_OR_INDEPENDENTLY_DEIDENTIFIED",
            "delayed_or_asynchronous_tool_result": "UNSUPPORTED",
        },
        "case": {
            "title": case.title,
            "language": case.language,
            "memory_requirement": case.memory_requirement,
            "expected_mcp_calls": case.expected_mcp_calls,
            "expected_provider_calls": case.expected_provider_calls,
        },
        "bindings": {
            "interface_freeze": _bound_identity(INTERFACE_FREEZE),
            "execution_override": _bound_identity(EXECUTION_OVERRIDE),
            "candidate_fixture": fixture,
            "task_metadata_headers": _bound_identity(HEADER_CONTRACT),
        },
        "requested_composition": {
            "openworker_image": OPENWORKER_IMAGE,
            "provider_origin": VLLM_ORIGIN,
            "provider_model": MODEL_ID,
            "provider_lifecycle": "PRESERVE_EXISTING_READ_ONLY_IDENTITY",
            "runtime": "FRESH_RUN_OWNED_DATABASE_API_WORKER",
            "memory_transport": "READER_LITE_UDS_BROKER_MCP_ONLY",
            "provider_topology": "DIRECT_DEDICATED_DOCKER_BRIDGE_TO_RUN_OWNED_HOST",
        },
        "call_policy": {
            "provider_automatic_retries": 0,
            "mcp_automatic_retries": 0,
            "provider_calls_per_turn_maximum": 1,
            "provider_calls_case_maximum": case.expected_provider_calls,
        },
        "formal_evaluation_input": False,
    }


def _stage(
    name: str, operation: Callable[[], CompositionResult]
) -> tuple[CompositionResult, dict[str, Any]]:
    started_at = _now()
    started = time.monotonic()
    result = operation()
    return result, {
        "stage": name,
        "status": result.status,
        "reason_code": result.reason_code,
        "started_at": started_at,
        "finished_at": _now(),
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "evidence_sha256": hashlib.sha256(
            u0._canonical_bytes(result.evidence)
        ).hexdigest(),
    }


def _safety_report(
    case: CaseSpec, reconciliation: CompositionResult | None
) -> dict[str, Any]:
    executed = (
        reconciliation is not None and reconciliation.status is TerminalStatus.PASS
    )
    failures = (
        dict(reconciliation.evidence.get("safety_failures") or {})
        if executed and reconciliation is not None
        else {}
    )
    return {
        name: {
            "failures": int(failures.get(name, 0)),
            "denominator": 1 if executed and name in case.safety_counters else 0,
            "status": (
                TerminalStatus.PASS
                if executed
                and name in case.safety_counters
                and int(failures.get(name, 0)) == 0
                else TerminalStatus.FAIL
                if executed and name in case.safety_counters
                else TerminalStatus.NOT_RUN
            ),
        }
        for name in SAFETY_COUNTERS
    }


def _gate_report() -> dict[str, Any]:
    return {
        f"U1-G{index}": {
            "status": TerminalStatus.NOT_RUN,
            "reason_code": "U1_LOCAL_COMPOSITION_DRIVER_PENDING",
        }
        for index in range(6)
    }


def _remove_exact_directory(path: Path, expected_parent: Path) -> None:
    resolved = path.resolve(strict=False)
    parent = expected_parent.resolve(strict=False)
    if resolved.parent != parent or path.is_symlink():
        raise RunError("refusing cleanup outside exact run-owned directory")
    if path.exists():
        shutil.rmtree(path)


def run_case(
    run_id: str,
    case_id: str,
    *,
    composition: Composition | None = None,
) -> dict[str, Any]:
    run_started = time.monotonic()
    # Selector validation intentionally precedes every filesystem mutation.
    case = _case(case_id)
    _validate_run_id(run_id)
    paths = RunPaths.reserve(run_id)
    resources = ResourceRegistry(run_id, paths.recovery)
    resources.register(
        ResourceHandle(
            "external_vllm",
            "127.0.0.1:7860",
            ResourceOwnership.PRESERVED_EXTERNAL,
        )
    )
    resources.register(
        ResourceHandle(
            "temporary_root",
            f"var/dg13/tmp/{run_id}",
            ResourceOwnership.RUN_OWNED,
            cleanup=lambda: _remove_exact_directory(paths.temporary, TMP_ROOT),
            absent=lambda: not paths.temporary.exists(),
        )
    )
    resources.register(
        ResourceHandle(
            "uds_root",
            f"dev/shm/milai/{paths.uds.name}",
            ResourceOwnership.RUN_OWNED,
            cleanup=lambda: _remove_exact_directory(paths.uds, UDS_ROOT),
            absent=lambda: not paths.uds.exists(),
        )
    )

    manifest = _execution_manifest(paths, case)
    _atomic_write(paths.durable / "manifest.json", manifest)
    driver = composition or PendingLocalComposition()
    stage_rows: list[dict[str, Any]] = []
    results: dict[str, CompositionResult] = {}
    terminal_error: Exception | None = None
    secondary_errors: list[dict[str, str]] = []
    try:
        for name, operation in (
            ("start", lambda: driver.start(paths, case, resources)),
            ("readiness", lambda: driver.readiness(paths, case)),
            ("smoke", lambda: driver.smoke(paths, case)),
            ("reconciliation", lambda: driver.reconciliation(paths, case)),
        ):
            result, row = _stage(name, operation)
            results[name] = result
            stage_rows.append(row)
            if result.status is not TerminalStatus.PASS:
                break
    except Exception as exc:  # noqa: BLE001 - top-level containment owns cleanup
        terminal_error = exc
        stage_rows.append(
            {
                "stage": "containment",
                "status": TerminalStatus.FAIL,
                "reason_code": "U1_COMPOSITION_EXCEPTION",
                "error_type": type(exc).__name__,
            }
        )
    finally:
        cleanup_started = time.monotonic()
        try:
            cleanup = resources.cleanup_all()
        except Exception as exc:  # noqa: BLE001 - top-level cleanup containment
            if terminal_error is None and not any(
                result.status is TerminalStatus.FAIL for result in results.values()
            ):
                terminal_error = exc
            else:
                secondary_errors.append(_secondary_error("cleanup", exc))
            cleanup = {
                "schema": "milai.dg13u.u1-cleanup-receipt.v1",
                "run_id": paths.run_id,
                "status": TerminalStatus.FAIL,
                "existing_vllm_preserved": False,
                "external_lifecycle_mutations": 0,
                "items": [],
                "recovery_plan": {"status": TerminalStatus.FAIL},
            }
        cleanup["case_id"] = case.case_id
        cleanup["duration_ms"] = round((time.monotonic() - cleanup_started) * 1000, 3)
        try:
            _atomic_write(paths.durable / "cleanup-receipt.json", cleanup)
        except Exception as exc:  # noqa: BLE001 - top-level persistence containment
            if terminal_error is None and not any(
                result.status is TerminalStatus.FAIL for result in results.values()
            ):
                terminal_error = exc
            else:
                secondary_errors.append(
                    _secondary_error("cleanup_receipt_persistence", exc)
                )
            cleanup["status"] = TerminalStatus.FAIL
            cleanup["receipt_persisted"] = False

    if (
        isinstance(driver, LocalComposition)
        and case.case_id in (_CACHE_GOVERNANCE_CASE_IDS | _LIFECYCLE_CASE_IDS)
        and len(results) == 4
        and all(result.status is TerminalStatus.PASS for result in results.values())
    ):
        finalized_started = time.monotonic()
        try:
            finalized = driver.finalize_after_cleanup(paths, case, cleanup)
            if finalized is None:
                raise RunError("scenario final evidence is absent")
            for name in ("smoke", "reconciliation"):
                prior = results[name]
                results[name] = CompositionResult(
                    prior.status,
                    prior.reason_code,
                    {**prior.evidence, **finalized},
                )
            stage_rows.append(
                {
                    "stage": "scenario_finalization",
                    "status": TerminalStatus.PASS,
                    "reason_code": (
                        "LIFECYCLE_REDUCED_AFTER_CLEANUP"
                        if case.case_id in _LIFECYCLE_CASE_IDS
                        else "CACHE_GOVERNANCE_REDUCED_AFTER_CLEANUP"
                    ),
                    "duration_ms": round(
                        (time.monotonic() - finalized_started) * 1000,
                        3,
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - final status owns typed failure
            if terminal_error is None:
                terminal_error = exc
            stage_rows.append(
                {
                    "stage": "scenario_finalization",
                    "status": TerminalStatus.FAIL,
                    "reason_code": (
                        "LIFECYCLE_FINALIZATION_FAILED"
                        if case.case_id in _LIFECYCLE_CASE_IDS
                        else "CACHE_GOVERNANCE_FINALIZATION_FAILED"
                    ),
                    "error_type": type(exc).__name__,
                    "duration_ms": round(
                        (time.monotonic() - finalized_started) * 1000,
                        3,
                    ),
                }
            )

    if isinstance(driver, LocalComposition) and driver.identity is not None:
        try:
            _verify_final_product_binding(paths, driver.identity)
        except Exception as exc:  # noqa: BLE001 - top-level evidence containment
            if terminal_error is None and not any(
                result.status is TerminalStatus.FAIL for result in results.values()
            ):
                terminal_error = exc
            else:
                secondary_errors.append(_secondary_error("product_binding", exc))

    all_pass = (
        terminal_error is None
        and cleanup["status"] == TerminalStatus.PASS
        and len(results) == 4
        and all(result.status is TerminalStatus.PASS for result in results.values())
    )
    any_failed = (
        terminal_error is not None
        or cleanup["status"] == TerminalStatus.FAIL
        or any(result.status is TerminalStatus.FAIL for result in results.values())
    )
    status = (
        TerminalStatus.PASS
        if all_pass
        else TerminalStatus.FAIL
        if any_failed
        else TerminalStatus.BLOCKED
        if any(result.status is TerminalStatus.BLOCKED for result in results.values())
        else TerminalStatus.NOT_RUN
    )
    final_evidence_error: Exception | None = None
    status_before_final_evidence = status
    if isinstance(driver, LocalComposition):
        try:
            driver.write_final_evidence_artifacts(
                paths,
                case,
                status,
                stage_rows,
                cleanup,
            )
        except Exception as exc:  # noqa: BLE001 - top-level evidence containment
            final_evidence_error = exc
            if (
                terminal_error is None
                and status_before_final_evidence is TerminalStatus.PASS
            ):
                terminal_error = exc
            else:
                secondary_errors.append(
                    _secondary_error("final_evidence_persistence", exc)
                )
            status = TerminalStatus.FAIL
    manifest_path = paths.durable / "manifest.json"
    try:
        final_manifest = _read_run_document(manifest_path, label="final run manifest")
        if (
            final_manifest.get("run_id") != paths.run_id
            or final_manifest.get("case_id") != case.case_id
        ):
            raise RunError("final run manifest identity drift")
        final_manifest["status"] = status
        _atomic_write(manifest_path, final_manifest)
    except Exception as exc:  # noqa: BLE001 - top-level persistence containment
        if terminal_error is None and status is TerminalStatus.PASS:
            terminal_error = exc
        else:
            secondary_errors.append(_secondary_error("final_manifest", exc))
        status = TerminalStatus.FAIL
    measured_calls = results.get("reconciliation") or results.get("smoke")
    measured_evidence = measured_calls.evidence if measured_calls is not None else {}
    observed_provider = int(measured_evidence.get("observed_provider_calls", 0))
    observed_mcp = int(measured_evidence.get("observed_mcp_calls", 0))
    reconciliation = results.get("reconciliation")
    calls_reconciled = (
        reconciliation is not None
        and reconciliation.status is TerminalStatus.PASS
        and int(reconciliation.evidence.get("unaccounted_calls", 0)) == 0
    )
    call_status = (
        TerminalStatus.PASS
        if calls_reconciled
        and observed_mcp == case.expected_mcp_calls
        and observed_provider == case.expected_provider_calls
        else TerminalStatus.FAIL
        if measured_calls is not None
        else TerminalStatus.NOT_RUN
    )
    observed_context_tokens = (
        int(reconciliation.evidence.get("context_tokens", 0))
        if reconciliation is not None
        else 0
    )
    if observed_context_tokens < 0:
        raise RunError("context token accounting is negative")
    failed_stage_error = next(
        (
            {
                "type": result.evidence["error_type"],
                "message_sha256": result.evidence["error_message_sha256"],
            }
            for result in results.values()
            if result.status is TerminalStatus.FAIL
            and isinstance(result.evidence.get("error_type"), str)
            and isinstance(result.evidence.get("error_message_sha256"), str)
        ),
        None,
    )
    reported_error = (
        {
            "type": type(terminal_error).__name__,
            "message_sha256": hashlib.sha256(str(terminal_error).encode()).hexdigest(),
        }
        if terminal_error is not None
        else failed_stage_error
        if failed_stage_error is not None
        else {
            "type": type(final_evidence_error).__name__,
            "message_sha256": hashlib.sha256(
                str(final_evidence_error).encode()
            ).hexdigest(),
        }
        if final_evidence_error is not None
        else None
    )
    report = {
        "schema": "milai.dg13u.u1-run-report.v1",
        "run_id": run_id,
        "case_id": case_id,
        "status": status,
        "release_label_earned": False,
        "wall_latency_ms": round((time.monotonic() - run_started) * 1000, 3),
        "context_tokens": observed_context_tokens,
        "stages": stage_rows,
        "gates": _gate_report(),
        "safety_counters": _safety_report(case, reconciliation),
        "calls": {
            "mcp": {
                "expected": case.expected_mcp_calls,
                "observed": observed_mcp,
                "unaccounted": 0,
                "status": call_status,
            },
            "provider": {
                "expected": case.expected_provider_calls,
                "maximum_per_model_round": 1,
                "model_rounds": case.expected_provider_calls,
                "calls_per_task_operation": case.expected_provider_calls,
                "case_maximum": case.expected_provider_calls,
                "observed": observed_provider,
                "unaccounted": 0,
                "automatic_retries": 0,
                "status": call_status,
            },
        },
        "joined_identities": {
            "access_id_sha256": (
                reconciliation.evidence.get("access_id_sha256")
                if reconciliation is not None
                else None
            ),
            "mcp_receipt_sha256": (
                reconciliation.evidence.get("mcp_receipt_sha256")
                if reconciliation is not None
                else None
            ),
            "runtime_trace_sha256": (
                reconciliation.evidence.get("runtime_trace_sha256")
                if reconciliation is not None
                else None
            ),
            "provider_native_request_id_sha256": (
                reconciliation.evidence.get("native_request_id_sha256")
                if reconciliation is not None
                else None
            ),
        },
        "stage_latency_ms": {
            row["stage"]: row.get("duration_ms") for row in stage_rows
        },
        "feature_support": {"delayed_or_asynchronous_tool_result": "UNSUPPORTED"},
        "cleanup": {
            "status": cleanup["status"],
            "receipt": "cleanup-receipt.json",
            "existing_vllm_preserved": cleanup["existing_vllm_preserved"],
            "recovery_plan_sha256": cleanup.get("recovery_plan", {}).get("sha256"),
        },
        "error": reported_error,
        "secondary_errors": secondary_errors,
        "known_limitations": [
            "A single case cannot satisfy the full U1-G0 through U1-G5 release matrix.",
            "All 37 contracted U1 cases are implemented; release requires the serial aggregate matrix and independent review.",
            "Validation is local, reader-lite, same-process strict-current; delayed or asynchronous ordinary-tool results remain unsupported.",
        ],
    }
    _atomic_write(paths.durable / "report.json", report)
    report["artifacts"] = u0._artifact_index(paths.durable)
    _atomic_write(paths.durable / "report.json", report)
    return report


def list_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": case.case_id,
            "title": case.title,
            "language": case.language,
            "memory_requirement": case.memory_requirement,
            "expected_mcp_calls": case.expected_mcp_calls,
            "expected_provider_calls": case.expected_provider_calls,
            "safety_counters": list(case.safety_counters),
        }
        for case in CASE_SPECS
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one DG-13U U1 OpenWorker case")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--case-id", choices=tuple(CASES))
    selector.add_argument("--list-cases", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--execute-local",
        action="store_true",
        help="run exact identity preflight and the fresh Runtime DB/API/worker lifecycle",
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / "runtime/.env")
    args = parser.parse_args(argv)
    if args.list_cases:
        print(json.dumps(list_cases(), ensure_ascii=False, sort_keys=True))
        return 0
    if not args.run_id:
        parser.error("--run-id is required with --case-id")
    composition = LocalComposition(args.env_file) if args.execute_local else None
    report = run_case(args.run_id, args.case_id, composition=composition)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == TerminalStatus.PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
