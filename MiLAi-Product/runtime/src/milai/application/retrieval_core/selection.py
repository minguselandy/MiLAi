"""Context budgeting and deterministic candidate selection helpers."""

from __future__ import annotations

import json
import re
from typing import Any

from milai.application.memory_access import ACQUISITION_DECISION_CONTEXT_CEILING
from milai.application.retrieval_core.candidates import _result_identity


def _apply_context_budget(
    assembled: tuple[
        list[dict[str, object]],
        list[dict[str, object]],
        list[dict[str, Any]],
        list[str],
    ],
    token_budget: int,
    progressive_l1: dict[str, Any],
    degraded: set[str],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, Any]],
    list[str],
]:
    """Bound Context by a conservative UTF-8-byte token upper bound.

    Tokenizers cannot emit more tokens than input bytes. Selecting whole governed
    items keeps canonical values immutable and makes the cap tokenizer-independent.
    """
    accepted, rejected, results, open_issue_ids = assembled
    selected: list[dict[str, Any]] = []
    used = 2  # JSON list delimiters.
    for result in results:
        encoded = json.dumps(
            _context_budget_view(result),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        item_cost = len(encoded) + (1 if selected else 0)
        if used + item_cost > token_budget:
            if result.get("kind") == "EVIDENCE_OBSERVATION":
                continue
            break
        selected.append(result)
        used += item_cost
    truncated = len(selected) != len(results)
    progressive_l1["context_token_upper_bound"] = used
    progressive_l1["context_budget_truncated"] = bool(
        progressive_l1.get("context_budget_truncated") or truncated
    )
    if not truncated:
        return assembled
    degraded.add("context_budget")
    selected_ids = {_result_identity(result) for result in selected}
    selected_ids.discard(None)
    accepted_by_id = {
        _result_identity(item): item for item in accepted if _result_identity(item) in selected_ids
    }
    bounded_accepted = [
        accepted_by_id[identity]
        for result in selected
        if (identity := _result_identity(result)) in accepted_by_id
    ]
    return bounded_accepted, rejected, selected, open_issue_ids


def _context_candidate_budget(
    assembled: tuple[
        list[dict[str, object]],
        list[dict[str, object]],
        list[dict[str, Any]],
        list[str],
    ],
    context_token_budget: int,
) -> int:
    """Return the fixed decision-input ceiling, never the presentation cap.

    ``context_token_budget`` remains in the compatibility signature so older
    internal callers do not break. It is intentionally ignored by DG-23.
    """

    del assembled, context_token_budget
    return ACQUISITION_DECISION_CONTEXT_CEILING


def _context_budget_view(result: dict[str, Any]) -> dict[str, Any]:
    """Return only fields rendered into an Evidence Context candidate.

    Permission and retention metadata participate in the live gate but are not
    duplicated into the provider-facing Context. Counting the complete internal
    candidate made a short observation exceed a 512-token budget before Context
    compilation had even started.
    """
    if result.get("kind") != "EVIDENCE_OBSERVATION":
        # Canonical hydration also carries opaque identity and provenance fields
        # that are required for gate/receipt bookkeeping but are deliberately
        # removed from the Reader semantic projection.  Charging those fields
        # here made a compact canonical value exceed the 768-token POSSIBLE-read
        # budget even though the value rendered by MemoryContextCompiler fit.
        # Reuse the compiler projection so search admission and presentation
        # account for the same material.
        from milai.application.memory_context import _reader_semantic_value

        projected = _reader_semantic_value(result)
        if not isinstance(projected, dict):
            raise TypeError("canonical Reader semantic projection must be an object")
        return projected
    return {
        key: result[key]
        for key in (
            "kind",
            "evidence_id",
            "source_ref",
            "subject_id",
            "observed_at",
            "content",
            "authority",
        )
        if key in result
    }


_MMR_TOKEN = re.compile(r"[\w.-]+", re.UNICODE)
_SET_COVER_NUMBER = re.compile(r"(?:[$£€]\s*)?\b\d+(?:[.,:]\d+)*\b")
_SET_COVER_QUANTITY = re.compile(r"\b(?:how many|how much|total|combined|all)\b", re.I)
_SET_COVER_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "did",
        "do",
        "for",
        "from",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "who",
        "with",
    }
)


def _set_cover_text(item: dict[str, Any]) -> str:
    payload = item.get("payload")
    if isinstance(payload, dict):
        memory_text = payload.get("memory_text")
        if isinstance(memory_text, str):
            return memory_text
    memory_text = item.get("memory_text")
    return memory_text if isinstance(memory_text, str) else ""


def _set_cover_tokens(text: str) -> frozenset[str]:
    return frozenset(
        token.casefold()
        for token in _MMR_TOKEN.findall(text)
        if len(token) > 1 and token.casefold() not in _SET_COVER_STOPWORDS
    )


def _weighted_set_cover_select(
    candidates: list[dict[str, Any]],
    limit: int,
    *,
    query: str,
    diversity_weight: float = 0.14,
) -> list[dict[str, Any]]:
    """Select a bounded evidence set from canonical-gated candidates without gold data."""
    if limit <= 0 or not candidates:
        return []
    if not 0.0 <= diversity_weight <= 0.3:
        raise ValueError("diversity_weight must be between 0 and 0.3")
    query_terms = _set_cover_tokens(query)
    quantity_query = _SET_COVER_QUANTITY.search(query) is not None
    maximum_score = max(float(item.get("relevance_score", 0.0)) for item in candidates) or 1.0
    indexed = list(enumerate(candidates))
    token_sets = {index: _set_cover_tokens(_set_cover_text(item)) for index, item in indexed}
    selected: list[tuple[int, dict[str, Any]]] = []
    remaining = list(indexed)
    covered_query_terms: set[str] = set()
    while remaining and len(selected) < limit:

        def utility(entry: tuple[int, dict[str, Any]]) -> tuple[float, float, int]:
            index, item = entry
            tokens = token_sets[index]
            overlap = query_terms.intersection(tokens)
            lexical = len(overlap) / max(len(query_terms), 1)
            new_query = len(overlap.difference(covered_query_terms)) / max(len(query_terms), 1)
            relevance = float(item.get("relevance_score", 0.0)) / maximum_score
            redundancy = (
                max(
                    _jaccard(tokens, token_sets[selected_index])
                    for selected_index, _selected_item in selected
                )
                if selected
                else 0.0
            )
            diversity = 1.0 - redundancy
            quantity = (
                1.0 if quantity_query and _SET_COVER_NUMBER.search(_set_cover_text(item)) else 0.0
            )
            score = (
                0.44 * relevance
                + 0.24 * lexical
                + 0.12 * new_query
                + diversity_weight * diversity
                + 0.10 * quantity
            )
            return score, relevance, -index

        chosen = max(remaining, key=utility)
        selected.append(chosen)
        covered_query_terms.update(query_terms.intersection(token_sets[chosen[0]]))
        remaining.remove(chosen)
    return [item for _index, item in selected]


def _mmr_select(
    candidates: list[dict[str, Any]],
    limit: int,
    *,
    relevance_weight: float,
) -> list[dict[str, Any]]:
    """Deterministic lexical MMR over already canonical-gated hydrated results."""
    if limit <= 0 or not candidates:
        return []
    if not 0.5 <= relevance_weight <= 1.0:
        raise ValueError("relevance_weight must be between 0.5 and 1.0")
    remaining = list(candidates)
    maximum_score = max(float(item.get("relevance_score", 0.0)) for item in remaining) or 1.0
    token_sets = {str(item["claim_version_id"]): _mmr_tokens(item) for item in remaining}
    selected: list[dict[str, Any]] = []
    while remaining and len(selected) < limit:

        def score(item: dict[str, Any]) -> tuple[float, float]:
            item_id = str(item["claim_version_id"])
            relevance = float(item.get("relevance_score", 0.0)) / maximum_score
            protected_issue = bool(item.get("open_issue_ids"))
            similarity = (
                0.0
                if protected_issue or not selected
                else max(
                    _jaccard(token_sets[item_id], token_sets[str(chosen["claim_version_id"])])
                    for chosen in selected
                )
            )
            mmr = relevance_weight * relevance - (1.0 - relevance_weight) * similarity
            return (mmr, relevance)

        chosen = min(
            remaining,
            key=lambda item: (
                -score(item)[0],
                -score(item)[1],
                str(item["claim_version_id"]),
            ),
        )
        selected.append(chosen)
        remaining.remove(chosen)
    return selected


def _mmr_tokens(item: dict[str, Any]) -> frozenset[str]:
    safe_material = {
        key: item.get(key) for key in ("predicate", "claim_type", "payload", "scope_predicate")
    }
    encoded = json.dumps(safe_material, ensure_ascii=False, sort_keys=True, default=str)
    return frozenset(_MMR_TOKEN.findall(encoded.casefold()))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / max(1, len(left | right))
