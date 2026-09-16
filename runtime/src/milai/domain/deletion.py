from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RevocationReason = Literal[
    "USER_REQUEST",
    "SOURCE_REMOVED",
    "PERMISSION_REVOKED",
    "RETENTION_EXPIRED",
    "CORRECTION",
]


class EvidenceRevocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: UUID | None = None
    reason_code: RevocationReason
    confirmation: Literal["REVOKE"]


class NamespaceCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: str = Field(min_length=1, max_length=255)
    reason_code: RevocationReason
    confirmation: Literal["CLEANUP_NAMESPACE"]
