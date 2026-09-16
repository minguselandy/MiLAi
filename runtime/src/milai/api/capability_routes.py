from __future__ import annotations

from typing import cast

from flask import Blueprint, current_app, g, jsonify

from milai import IMPLEMENTATION_STATUS, SCHEMA_FREEZE_STATUS, SCHEMA_STATUS, __version__
from milai.api.auth import AuthenticatedPrincipal, authenticated_context
from milai.config import RuntimeSettings

capability_blueprint = Blueprint("capability", __name__, url_prefix="/v1")


@capability_blueprint.before_request
def require_authentication() -> None:
    authenticated_context(current_app)


@capability_blueprint.get("/capabilities")
def capabilities():  # type: ignore[no-untyped-def]
    principal = cast(AuthenticatedPrincipal, g.milai_principal)
    settings = cast(RuntimeSettings, current_app.extensions["milai.settings"])
    profiles = ["legacy-local"]
    for name, token in (
        ("reader", settings.agent_reader_token),
        ("submitter", settings.agent_submitter_token),
        ("operator", settings.agent_operator_token),
        ("reviewer", settings.agent_reviewer_token),
    ):
        if token is not None:
            profiles.append(name)
    return jsonify(
        {
            "api_version": "1",
            "contract_version": "agent.v1",
            "runtime_version": __version__,
            "profile": principal.profile,
            "capabilities": sorted(principal.capabilities),
            "agent_profiles": profiles,
            "transports": {"rest": "loopback-only", "mcp": "stdio-only"},
            "routes": ["L0", "L1"],
            "consistency_modes": ["EVENTUAL", "READ_YOUR_WRITES", "CANONICAL_REQUIRED"],
            "retrieval_routes": {"L0": True, "L1": True, "L2": False},
            "feature_profile": settings.feature_profile,
            "semantic_dense": {
                "status": (
                    "AVAILABLE"
                    if settings.embedding_provider != "deterministic_hash"
                    else "UNAVAILABLE_FOR_SEMANTIC_DENSE"
                ),
                "provider": settings.embedding_provider,
                "model_id": settings.embedding_model_id,
                "projection_dimensions": settings.embedding_projection_dimensions,
            },
            "features": {
                "context_capsule": True,
                "context_receipt_online_revalidation": True,
                "context_receipt_same_call_fallback": True,
                "memory_exact_get": True,
                "memory_resolve_query_first": True,
                "memory_state_view": True,
                "memory_state_view_bitemporal": True,
                "query_aware_bounded_search": True,
                "possible_low_cost_probe": True,
                "hard_partitioned_candidate_search": True,
                "conditional_vector_reranker": True,
                "governed_mcp_review": True,
                "reviewer_actor_separation": True,
                "incremental_projection_outbox": True,
                "projection_rebuild": True,
                "optional_task_context_narrowing": True,
                "task_free_retrieval": True,
                "proposal_review": True,
                "auto_commit": False,
                "real_embedding": settings.embedding_provider != "deterministic_hash",
                "encrypted_blob": settings.blob_encryption == "AES_256_GCM",
                "remote_access": False,
                "multi_agent_governance": False,
            },
            "limits": {
                "query_chars": 2_000,
                "max_results": 50,
                "max_evidence_bytes": settings.max_evidence_bytes,
            },
            "data_mode": settings.data_mode,
            "blob_encryption": settings.blob_encryption,
            "schema_status": SCHEMA_STATUS,
            "implementation_status": IMPLEMENTATION_STATUS,
            "schema_freeze": SCHEMA_FREEZE_STATUS,
            "request_id": g.request_id,
        }
    )
