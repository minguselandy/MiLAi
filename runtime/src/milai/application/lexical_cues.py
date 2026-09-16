"""Planner-owned, provenance-bearing lexical cue compilation."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from milai.domain.semantic_query import EvidenceRequirementV02, LexicalCueSetV01

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_LATIN = re.compile(r"[A-Za-z]")
_HAN = re.compile(r"[\u3400-\u9fff]")


def compile_lexical_cue_set(requirement: EvidenceRequirementV02) -> LexicalCueSetV01:
    """Normalize requirement surfaces without inventing semantic synonyms."""

    surface_terms = _unique_normalized(requirement.entity_constraints)
    variants = _unique(
        variant
        for term in surface_terms
        for variant in _generic_morphological_variants(term)
        if variant not in surface_terms
    )
    language_tags = _language_tags([*surface_terms, *variants])
    provenance = ["QUERY_REQUIREMENT_SURFACE", "UNICODE_NFKC_CASEFOLD_V1"]
    if variants:
        provenance.append("GENERIC_LATIN_MORPHOLOGY_V1")
    return LexicalCueSetV01(
        requirement_slot=requirement.slot_id,
        surface_terms=surface_terms,
        morphological_variants=variants,
        entity_aliases=[],
        relation_cues=[],
        language_tags=language_tags,
        provenance=provenance,
    )


def compile_lexical_cue_sets(
    requirements: Iterable[EvidenceRequirementV02],
) -> list[LexicalCueSetV01]:
    return [compile_lexical_cue_set(requirement) for requirement in requirements]


def enriched_lexical_terms(cues: LexicalCueSetV01) -> list[str]:
    return _unique(
        [
            *cues.surface_terms,
            *cues.morphological_variants,
            *cues.entity_aliases,
            *cues.relation_cues,
        ]
    )


def _generic_morphological_variants(term: str) -> list[str]:
    """Return bounded surface morphology only; never semantic paraphrases."""

    if not term.isascii() or not term.isalpha() or len(term) < 4:
        return []
    candidates: list[str] = []
    if term.endswith("ies") and len(term) > 4:
        candidates.append(f"{term[:-3]}y")
    elif term.endswith("ing") and len(term) > 5:
        base = term[:-3]
        undoubled = _undouble_final(base)
        if undoubled != base:
            candidates.append(undoubled)
    elif term.endswith("ed") and len(term) > 4:
        base = term[:-2]
        undoubled = _undouble_final(base)
        if undoubled != base:
            candidates.append(undoubled)
    elif term.endswith(("sses", "xes", "zes", "ches", "shes")) and len(term) > 4:
        candidates.append(term[:-2])
    elif term.endswith("s") and len(term) > 4:
        candidates.append(term[:-1])
    return [value for value in _unique(candidates) if len(value) >= 3 and value != term]


def _undouble_final(value: str) -> str:
    if len(value) >= 2 and value[-1] == value[-2]:
        return value[:-1]
    return value


def _unique_normalized(values: Iterable[str]) -> list[str]:
    return _unique(
        unicodedata.normalize("NFKC", token).casefold()
        for value in values
        for token in _WORD.findall(value)
    )


def _language_tags(values: Iterable[str]) -> list[str]:
    text = " ".join(values)
    result: list[str] = []
    if _HAN.search(text) is not None:
        result.append("zh-Hans")
    if _LATIN.search(text) is not None:
        result.append("und-Latn")
    return result or ["und"]


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = [
    "compile_lexical_cue_set",
    "compile_lexical_cue_sets",
    "enriched_lexical_terms",
]
