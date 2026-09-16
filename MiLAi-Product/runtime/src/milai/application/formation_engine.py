"""Single application contract for product and evaluation Memory Formation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from milai.application.formation_generalization import GeneralizedFormationBundle
from milai.application.formation_generalization import (
    build_generalized_formation as _build_generalized_formation,
)
from milai.application.semantic_episode_boundary_v02 import (
    MemoryFormationBuildResultV02,
    build_memory_formation_bundle_v02,
)

FORMATION_ENGINE_IDENTITY = "milai-unified-formation-engine-v0.1"


@dataclass(frozen=True, slots=True)
class FormationEngineResult:
    generalized: GeneralizedFormationBundle
    episode: MemoryFormationBuildResultV02
    builder_identity: str = FORMATION_ENGINE_IDENTITY
    canonical_mutation: bool = False


class FormationEngine:
    """Build SemanticEpisode and recollection artifacts from one Raw snapshot."""

    builder_identity = FORMATION_ENGINE_IDENTITY

    def build(
        self, source_records: Sequence[Mapping[str, Any]]
    ) -> FormationEngineResult:
        normalized = tuple(
            _normalize_source(item, index) for index, item in enumerate(source_records)
            if _admitted_for_formation(item)
        )
        return FormationEngineResult(
            generalized=_build_generalized_formation(normalized),
            episode=build_memory_formation_bundle_v02(normalized),
        )


def _normalize_source(source: Mapping[str, Any], ordinal: int) -> dict[str, Any]:
    value = dict(source)
    if not isinstance(value.get("session_id"), str) or not value["session_id"]:
        context = value.get("source_context")
        if isinstance(context, Mapping) and isinstance(context.get("session_id"), str):
            value["session_id"] = context["session_id"]
        else:
            value["session_id"] = f"derived-session:{ordinal}"
    return value


def _admitted_for_formation(source: Mapping[str, Any]) -> bool:
    permission = source.get("permission_snapshot")
    return (
        isinstance(permission, Mapping)
        and permission.get("readable") is True
        and source.get("retention_state") == "READABLE"
        and source.get("revoked_at") is None
        and source.get("access_decision", "ALLOWED") == "ALLOWED"
    )


DEFAULT_FORMATION_ENGINE = FormationEngine()

__all__ = [
    "DEFAULT_FORMATION_ENGINE",
    "FORMATION_ENGINE_IDENTITY",
    "FormationEngine",
    "FormationEngineResult",
]
