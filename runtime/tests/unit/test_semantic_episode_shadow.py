from __future__ import annotations

import ast
import copy
from pathlib import Path

from milai.application.semantic_episode_boundary_v02 import (
    MemoryFormationBundleServiceV02,
)
from milai.application.semantic_episode_shadow import SemanticEpisodeShadowHook


def test_shadow_is_default_off_and_current_observation_is_deterministic() -> None:
    sources = _sources()
    bundle = MemoryFormationBundleServiceV02().build(sources).bundle
    behavior = {"official_order": ["one", "two"], "sufficiency": "COMPLETE"}

    assert (
        SemanticEpisodeShadowHook().observe(
            request_identity="request-1",
            baseline_behavior=behavior,
            current_sources=sources,
            official_anchor_evidence_ids=["two"],
            bundle=bundle,
        )
        is None
    )
    hook = SemanticEpisodeShadowHook(enabled=True)
    first = hook.observe(
        request_identity="request-1",
        baseline_behavior=behavior,
        current_sources=sources,
        official_anchor_evidence_ids=["two"],
        bundle=bundle,
    )
    second = hook.observe(
        request_identity="request-1",
        baseline_behavior=behavior,
        current_sources=sources,
        official_anchor_evidence_ids=["two"],
        bundle=bundle,
    )

    assert first is not None and second is not None
    assert first.model_dump_json() == second.model_dump_json()
    assert first.freshness_status == "CURRENT"
    assert first.disposition == "OBSERVED"
    assert first.shadow_context_evidence_ids == ["one", "two"]
    assert first.additional_official_acquisition_calls == 0
    assert first.database_writes == 0
    assert first.canonical_mutations == 0
    assert behavior == {"official_order": ["one", "two"], "sufficiency": "COMPLETE"}


def test_shadow_rejects_stale_and_ineligible_bundles_with_raw_fallback() -> None:
    sources = _sources()
    bundle = MemoryFormationBundleServiceV02().build(sources).bundle
    hook = SemanticEpisodeShadowHook(enabled=True)

    appended = copy.deepcopy(sources)
    appended.append(_source("three", "user", "A new fact arrived.", 2))
    stale = hook.observe(
        request_identity="stale",
        baseline_behavior={"result": "unchanged"},
        current_sources=appended,
        official_anchor_evidence_ids=["one"],
        bundle=bundle,
    )
    revoked_sources = copy.deepcopy(sources)
    revoked_sources[0]["revoked_at"] = "2026-08-30T10:00:00+08:00"
    revoked = hook.observe(
        request_identity="revoked",
        baseline_behavior={"result": "unchanged"},
        current_sources=revoked_sources,
        official_anchor_evidence_ids=["one"],
        bundle=bundle,
    )
    permission_sources = copy.deepcopy(sources)
    permission_sources[0]["permission_snapshot"] = {"readable": False}
    permission = hook.observe(
        request_identity="permission",
        baseline_behavior={"result": "unchanged"},
        current_sources=permission_sources,
        official_anchor_evidence_ids=["one"],
        bundle=bundle,
    )
    unavailable = hook.observe(
        request_identity="failure",
        baseline_behavior={"result": "unchanged"},
        current_sources=sources,
        official_anchor_evidence_ids=["one"],
        bundle=None,
        formation_failed=True,
    )

    assert stale is not None and stale.disposition == "STALE_REJECTED"
    assert stale.freshness_status == "STALE" and stale.raw_fallback_used
    assert revoked is not None and revoked.disposition == "PERMISSION_REJECTED"
    assert revoked.shadow_context_evidence_ids == [] and revoked.raw_fallback_used
    assert permission is not None and permission.disposition == "PERMISSION_REJECTED"
    assert permission.shadow_context_evidence_ids == [] and permission.raw_fallback_used
    assert unavailable is not None and unavailable.disposition == "RAW_FALLBACK"
    assert unavailable.shadow_context_evidence_ids == [] and unavailable.raw_fallback_used


def test_shadow_runtime_has_no_official_read_or_persistence_dependency() -> None:
    source_path = (
        Path(__file__).resolve().parents[2] / "src/milai/application/semantic_episode_shadow.py"
    )
    imported_modules = {
        node.module
        for node in ast.walk(ast.parse(source_path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert imported_modules.isdisjoint(
        {
            "milai.persistence",
            "milai.application.acquisition",
            "milai.application.evidence_acquisition",
            "milai.application.memory_context",
            "milai.adapters",
        }
    )


def _sources() -> list[dict[str, object]]:
    return [
        _source("one", "user", "My bicycle returned from service.", 0),
        _source("two", "assistant", "Does the rear brake still squeal?", 1),
    ]


def _source(evidence_id: str, speaker: str, content: str, minute: int) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "source_ref": f"memory://md02/shadow/{evidence_id}",
        "session_id": "session-1",
        "subject_id": "subject-md02",
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "observed_at": f"2026-08-30T09:{minute:02d}:00+08:00",
        "content": content,
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
    }
