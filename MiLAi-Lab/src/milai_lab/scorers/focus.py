"""Offline material-coverage observations, never an input to the selector.

These annotations assess source coverage, not comprehension or answer truth.
Unannotated sufficiency stays unknown; alternative sufficient bundles are valid.
"""

from __future__ import annotations

from collections.abc import Mapping


def observe_focus(
    *,
    source_bytes: Mapping[str, int],
    presented_ids: frozenset[str],
    requirements: Mapping[str, tuple[frozenset[str], ...]],
    distractor_ids: frozenset[str],
) -> dict[str, object]:
    available = frozenset(source_bytes)
    if not presented_ids <= available or not distractor_ids <= available:
        raise ValueError("unknown observed source")
    if any(type(size) is not int or size < 0 for size in source_bytes.values()):
        raise ValueError("invalid source byte count")
    if any(not alternatives for alternatives in requirements.values()):
        raise ValueError("requirement needs at least one sufficient bundle")
    for alternatives in requirements.values():
        for bundle in alternatives:
            if not bundle <= available or bundle & distractor_ids:
                raise ValueError("unknown or contradictory material annotation")

    covered = {
        key: any(bundle <= presented_ids for bundle in alternatives)
        for key, alternatives in requirements.items()
    }
    total, satisfied = len(covered), sum(covered.values())
    removed = distractor_ids - presented_ids
    distractor_bytes = sum(source_bytes[key] for key in distractor_ids)
    removed_bytes = sum(source_bytes[key] for key in removed)
    return {
        "annotated_requirements": total,
        "covered_requirements": satisfied,
        "requirement_coverage": covered,
        "focus_sufficiency": all(covered.values()) if total else None,
        "necessary_material_recall": satisfied / total if total else None,
        "focus_exclusion_error": any(not value for value in covered.values()) if total else None,
        "excluded_requirements": total - satisfied,
        "distractor_units_total": len(distractor_ids),
        "distractor_units_removed": len(removed),
        "distractor_bytes_total": distractor_bytes,
        "distractor_bytes_removed": removed_bytes,
        "distractor_reduction": removed_bytes / distractor_bytes if distractor_bytes else None,
        "unannotated_sources_are_not_distractors": True,
        "semantic_correctness_assessed": False,
    }
