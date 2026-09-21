"""Fail-closed HTTP ingress and startup policy contracts."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from milai_client import CanonicalStateKey
from milai_client.models import Authority, Consistency

from milai_openworker_mcp.broker import BrokerError, Policy
from milai_openworker_mcp.host.request_contract import OpenWorkerAdapterError
from milai_openworker_mcp.task_binding import NativeTaskMetadata, TaskBindingError

_FIXTURE_SHA256 = "47175b17cdc8444955d28cf3ec2f6d96964faf2099decf34bd317cf7729bb555"
_IDENTIFIER_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_HEADER_NAMES = (
    "X-MiLAi-Host-Instance",
    "X-MiLAi-Task-Session",
    "X-MiLAi-Task-Operation",
)
_SETTLEMENT_HEADER_NAMES = (
    "X-MiLAi-Assistant-Message",
    "X-MiLAi-User-Observed-At",
    "X-MiLAi-Assistant-Observed-At",
)


@dataclass(frozen=True, slots=True)
class StartupTaskPolicy:
    profile: str
    scope: dict[str, Any]
    required_authority: Authority
    consistency_floor: Consistency
    max_limit: int
    state_keys: tuple[CanonicalStateKey, ...]
    broker_policy_sha256: str
    task_fixture_sha256: str


def _authenticate_ingress(values: Sequence[str], expected_token: str) -> None:
    if len(values) != 1:
        raise OpenWorkerAdapterError("AUTHENTICATION_REQUIRED")
    supplied = values[0]
    prefix = "Bearer "
    if not supplied.startswith(prefix) or not hmac.compare_digest(
        supplied[len(prefix) :].encode(), expected_token.encode()
    ):
        raise OpenWorkerAdapterError("AUTHENTICATION_REQUIRED")


def _task_metadata_from_values(
    values: Mapping[str, Sequence[str]],
    *,
    require_settlement: bool = False,
) -> NativeTaskMetadata:
    try:
        selected = {name: tuple(values.get(name, ())) for name in _HEADER_NAMES}
        if any(len(items) != 1 for items in selected.values()):
            raise TaskBindingError("metadata header cardinality is invalid")
        settlement = {
            name: tuple(values.get(name, ())) for name in _SETTLEMENT_HEADER_NAMES
        }
        expected = 1 if require_settlement or any(settlement.values()) else 0
        if any(len(items) != expected for items in settlement.values()):
            raise TaskBindingError("settlement metadata header cardinality is invalid")
        return NativeTaskMetadata(
            host_instance=selected["X-MiLAi-Host-Instance"][0],
            task_session=selected["X-MiLAi-Task-Session"][0],
            task_operation=selected["X-MiLAi-Task-Operation"][0],
            assistant_message=(
                settlement["X-MiLAi-Assistant-Message"][0] if expected else None
            ),
            user_observed_at=(
                settlement["X-MiLAi-User-Observed-At"][0] if expected else None
            ),
            assistant_observed_at=(
                settlement["X-MiLAi-Assistant-Observed-At"][0] if expected else None
            ),
        )
    except (TaskBindingError, IndexError, TypeError) as exc:
        raise OpenWorkerAdapterError("TASK_METADATA_INVALID") from exc


def _load_ingress_token(path: Path) -> str:
    if not path.is_absolute():
        raise OpenWorkerAdapterError("INGRESS_TOKEN_INVALID")
    try:
        current = path.lstat()
        raw = path.read_bytes()
    except OSError as exc:
        raise OpenWorkerAdapterError("INGRESS_TOKEN_INVALID") from exc
    if (
        not stat.S_ISREG(current.st_mode)
        or stat.S_ISLNK(current.st_mode)
        or stat.S_IMODE(current.st_mode) not in {0o400, 0o600}
        or current.st_uid not in {0, os.geteuid()}
    ):
        raise OpenWorkerAdapterError("INGRESS_TOKEN_INVALID")
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise OpenWorkerAdapterError("INGRESS_TOKEN_INVALID") from exc
    if not 16 <= len(token) <= 256 or _IDENTIFIER_SAFE.fullmatch(token) is None:
        raise OpenWorkerAdapterError("INGRESS_TOKEN_INVALID")
    return token


_PRIVATE_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_PRIVATE_IPV6_NETWORK = ipaddress.ip_network("fc00::/7")


def _validate_listen_host(value: str) -> str:
    """Accept only an explicit loopback or private IP literal."""
    if value != value.strip():
        raise OpenWorkerAdapterError("LISTEN_HOST_INVALID")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise OpenWorkerAdapterError("LISTEN_HOST_INVALID") from exc
    if address.is_unspecified or address.is_multicast:
        raise OpenWorkerAdapterError("LISTEN_HOST_INVALID")
    if isinstance(address, ipaddress.IPv4Address):
        allowed = address.is_loopback or any(
            address in network for network in _PRIVATE_IPV4_NETWORKS
        )
    else:
        allowed = address.is_loopback or address in _PRIVATE_IPV6_NETWORK
    if not allowed:
        raise OpenWorkerAdapterError("LISTEN_HOST_INVALID")
    return address.compressed


def _load_startup_task_policy(
    broker_policy_path: Path,
    task_fixture_path: Path,
) -> StartupTaskPolicy:
    try:
        policy = Policy.load(broker_policy_path)
        fixture_raw = task_fixture_path.read_bytes()
        fixture = json.loads(fixture_raw)
    except (BrokerError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID") from exc
    if policy.profile != "reader-lite":
        raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID")
    fixture_sha256 = hashlib.sha256(fixture_raw).hexdigest()
    if fixture_sha256 != _FIXTURE_SHA256 or not isinstance(fixture, Mapping):
        raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID")
    if set(fixture) != {
        "schema",
        "status",
        "data_boundary",
        "formal_evaluation_input",
        "families",
    } or (
        fixture.get("schema") != "milai.dg13u.u1-candidate-fixture.v1"
        or fixture.get("data_boundary") != "SYNTHETIC_OR_INDEPENDENTLY_DEIDENTIFIED"
        or fixture.get("formal_evaluation_input") is not False
    ):
        raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID")
    families = fixture.get("families")
    if not isinstance(families, list) or len(families) != 3:
        raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID")
    try:
        scope = json.loads(policy.scope_json)
        project_ids = scope.get("project_ids") if isinstance(scope, Mapping) else None
        if (
            not isinstance(project_ids, list)
            or not project_ids
            or any(not isinstance(project, str) or not project for project in project_ids)
        ):
            raise ValueError("scope project_ids are invalid")
        state_keys: list[CanonicalStateKey] = []
        fixture_projects: set[str] = set()
        for family in families:
            if not isinstance(family, Mapping) or set(family) != {
                "project",
                "state_key",
                "claim_type",
                "aliases",
            }:
                raise ValueError("fixture family is invalid")
            aliases = family.get("aliases")
            if (
                not isinstance(aliases, list)
                or not aliases
                or any(not isinstance(alias, str) or not alias.strip() for alias in aliases)
            ):
                raise ValueError("fixture aliases are invalid")
            project = family.get("project")
            if not isinstance(project, str):
                raise ValueError("fixture project is invalid")
            fixture_projects.add(project)
            state_keys.append(
                CanonicalStateKey(
                    subject=project,
                    predicate=str(family["state_key"]),
                    claim_type=str(family["claim_type"]),
                )
            )
        if (
            scope != {"project_ids": sorted(fixture_projects)}
            or policy.required_authority != "INFORMATIONAL"
            or policy.consistency_floor != "CANONICAL_REQUIRED"
            or len(set(state_keys)) != 3
        ):
            raise ValueError("fixture scope or state keys are invalid")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID") from exc
    return StartupTaskPolicy(
        profile=policy.profile,
        scope=dict(scope),
        required_authority=cast(Authority, policy.required_authority),
        consistency_floor=cast(Consistency, policy.consistency_floor),
        max_limit=policy.max_limit,
        state_keys=tuple(state_keys),
        broker_policy_sha256=policy.digest,
        task_fixture_sha256=fixture_sha256,
    )
