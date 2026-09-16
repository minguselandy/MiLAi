from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

HostCognitiveScope = Literal["SESSION", "TASK", "PROJECT"]

HOST_COGNITIVE_SCHEMA = "codex-cognitive-state-v1"
HOST_COGNITIVE_WIRE_SCHEMA = "host-cognitive-state-v1"
HOST_COGNITIVE_AUTHORITY = "HOST_WORKING"
MAX_HOST_COGNITIVE_PAYLOAD_BYTES = 65_536
MAX_HOST_COGNITIVE_EVIDENCE_REFS = 1024


class HostCognitiveBinding(BaseModel):
    """Server-owned binding for one Host working-state namespace."""

    # Normalize namespace identifiers only. Model-wide stripping also rewrites
    # arbitrary nested JSON payload strings and keys on inherited write requests.
    model_config = ConfigDict(extra="forbid")

    principal_binding_digest: Annotated[str, StringConstraints(strip_whitespace=True)] = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    project_id: Annotated[str, StringConstraints(strip_whitespace=True)] = Field(
        min_length=1, max_length=512
    )
    scope_type: HostCognitiveScope
    scope_ref: Annotated[str, StringConstraints(strip_whitespace=True)] = Field(
        min_length=1, max_length=1024
    )


class HostCognitiveStateGetRequest(HostCognitiveBinding):
    """Internal REST request; MCP keeps every binding field Host-owned."""


class HostCognitiveStateUpdateRequest(HostCognitiveBinding):
    """Full-replacement append request guarded by exact version CAS."""

    state_id: UUID | None = None
    expected_version: int = Field(ge=0)
    payload: dict[str, JsonValue]

    @field_validator("expected_version")
    @classmethod
    def validate_create_or_update(cls, value: int, info: ValidationInfo) -> int:
        if "state_id" in info.data and (info.data["state_id"] is None) != (value == 0):
            raise ValueError("create requires no state_id and expected_version=0")
        return value

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        encoded = canonical_json(value)
        if len(encoded) > MAX_HOST_COGNITIVE_PAYLOAD_BYTES:
            raise ValueError("working-state payload exceeds 65536 bytes")
        extract_evidence_refs(value)
        return value


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("working-state payload must be canonical JSON") from exc


def extract_evidence_refs(payload: dict[str, JsonValue]) -> tuple[UUID, ...]:
    """Extract reserved exact-identity pointers without interpreting their semantics."""

    found: set[UUID] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "evidence_id":
                    found.add(_evidence_uuid(item, key))
                elif key == "evidence_refs":
                    if not isinstance(item, list):
                        raise ValueError("evidence_refs must be an array of UUID strings")
                    for raw in item:
                        found.add(_evidence_uuid(raw, key))
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    if len(found) > MAX_HOST_COGNITIVE_EVIDENCE_REFS:
        raise ValueError(
            f"working-state payload contains more than {MAX_HOST_COGNITIVE_EVIDENCE_REFS} "
            "Evidence references"
        )
    return tuple(sorted(found, key=str))


def state_digest(
    binding: HostCognitiveBinding,
    payload: dict[str, JsonValue],
) -> str:
    material: dict[str, Any] = {
        "authority": HOST_COGNITIVE_AUTHORITY,
        "schema_name": HOST_COGNITIVE_SCHEMA,
        "principal_binding_digest": binding.principal_binding_digest,
        "project_id": binding.project_id,
        "scope_type": binding.scope_type,
        "scope_ref": binding.scope_ref,
        "payload": payload,
    }
    return hashlib.sha256(canonical_json(material)).hexdigest()


def request_fingerprint(
    *,
    tenant_id: UUID,
    actor_id: UUID,
    request: HostCognitiveStateUpdateRequest,
) -> str:
    material = {
        "tenant_id": str(tenant_id),
        "actor_id": str(actor_id),
        **request.model_dump(mode="json"),
        "contract": HOST_COGNITIVE_WIRE_SCHEMA,
    }
    return hashlib.sha256(canonical_json(material)).hexdigest()


def _evidence_uuid(value: object, field: str) -> UUID:
    if not isinstance(value, str):
        raise ValueError(f"{field} entries must be UUID strings")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} entries must be UUID strings") from exc
