"""Source-backed episode indices in the existing owner Store.

An episode groups actual public events. Its descriptions are semantic proposals,
not another copy of the original body or a new independent observation. Reads
resolve the sources again, so forgetting immediately withdraws derived access.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any

from milai_lab.contracts.memory import EpisodeDescription
from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.service import MemoryService, _lexical_tokens


class EpisodeIndex:
    """A small index owned by the same MemoryService as sources and records."""

    def __init__(self, service: MemoryService) -> None:
        self.service = service
        self.namespace = (*service.namespace, "episodes")
        self.consolidated_namespace = (*self.namespace, "consolidated")

    def register(
        self,
        episode_id: str,
        source_refs: Sequence[str],
        *,
        descriptions: Sequence[EpisodeDescription] | None = None,
    ) -> dict[str, Any]:
        """Group immutable sources; supplied descriptions can refine the index.

        Re-registering an identity cannot bind it to different events. Refining
        descriptions retains the original support identities and never captures
        a fresh source. Source roles and capture times are resolved by the reader.
        """
        refs = list(dict.fromkeys(source_refs))
        if not episode_id or not refs:
            raise FunctionalRejection("EPISODE_ID_AND_SOURCES_REQUIRED")
        sources = self._sources(refs)
        if sources is None:
            raise FunctionalRejection("EPISODE_SOURCE_UNAVAILABLE")
        checked = (
            self._descriptions(descriptions, refs, sources) if descriptions is not None else None
        )
        with self.service._locked():
            prior = self.service.store.get(self.namespace, episode_id)
            if prior is not None and prior.value["source_refs"] != refs:
                raise FunctionalRejection("EPISODE_SOURCE_BINDING_CHANGED")
            value = {
                "episode_id": episode_id,
                "owner": self.service.owner,
                "source_refs": refs,
                "descriptions": checked
                if checked is not None
                else (prior.value["descriptions"] if prior is not None else []),
            }
            self.service.store.put(self.namespace, episode_id, value, index=False)
            result = self.read(episode_id)
        if result is None:
            raise FunctionalRejection("EPISODE_SOURCE_UNAVAILABLE")
        return {**result, "replayed": prior is not None}

    @staticmethod
    def _descriptions(
        descriptions: Sequence[EpisodeDescription],
        source_refs: list[str],
        sources: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Validate the semantic-index boundary once, without judging entailment."""
        roles = {source["event_id"]: source["role"] for source in sources}
        checked = []
        for description in descriptions:
            refs = list(dict.fromkeys(description["source_refs"]))
            if (
                description["kind"] not in {"event", "participant", "context", "outcome"}
                or description["basis"] not in {"reported", "observed", "inferred", "uncertain"}
                or not isinstance(description["text"], str)
                or not description["text"].strip()
                or not refs
                or not set(refs) <= set(source_refs)
            ):
                raise FunctionalRejection("EPISODE_DESCRIPTION_INVALID")
            if description["basis"] == "observed" and any(roles[ref] != "tool" for ref in refs):
                raise FunctionalRejection("EPISODE_OBSERVED_DESCRIPTION_REQUIRES_TOOL_SOURCE")
            value: dict[str, Any] = {
                "kind": description["kind"],
                "basis": description["basis"],
                "text": description["text"],
                "source_refs": refs,
            }
            for field in ("occurred_at", "effective_from", "effective_until"):
                if field in description:
                    time = description[field]
                    if time is not None and (not isinstance(time, str) or not time.strip()):
                        raise FunctionalRejection("EPISODE_DESCRIPTION_TIME_INVALID")
                    value[field] = time
            checked.append(value)
        return copy.deepcopy(checked)

    def _sources(self, source_refs: Sequence[str]) -> list[dict[str, Any]] | None:
        sources = []
        for ref in source_refs:
            source = self.service.source(ref)
            if source is None:
                return None
            sources.append(source)
        return sources

    def read(self, episode_id: str, *, include_sources: bool = True) -> dict[str, Any] | None:
        """Return current visible material; a revoked original hides its whole episode."""
        item = self.service.store.get(self.namespace, episode_id)
        if item is None:
            return None
        sources = self._sources(item.value["source_refs"])
        if sources is None:
            return None
        metadata = [
            {
                "source_ref": source["event_id"],
                **{
                    key: source[key]
                    for key in ("role", "origin", "session", "source_revision", "observed_at")
                },
                "occurred_at": source.get("occurred_at"),
                "object_ref": copy.deepcopy(source.get("object_ref")),
            }
            for source in sources
        ]
        bindings = {row["source_ref"]: row for row in metadata}
        descriptions = [
            {
                **copy.deepcopy(description),
                "source_bindings": [bindings[ref] for ref in description["source_refs"]],
                "content_verification": "unchecked",
            }
            for description in item.value["descriptions"]
        ]
        consolidated = self.service.store.get(self.consolidated_namespace, episode_id)
        return {
            "episode_id": episode_id,
            "owner": self.service.owner,
            "source_refs": list(item.value["source_refs"]),
            "source_metadata": metadata,
            "descriptions": descriptions,
            "actual_outcomes": [row for row in metadata if row["role"] == "tool"],
            "visibility": "visible",
            "consolidated": consolidated is not None,
            "consolidation_request_id": consolidated.value["request_id"] if consolidated else None,
            **({"sources": copy.deepcopy(sources)} if include_sources else {}),
        }

    def select(
        self,
        *,
        episode_ids: Sequence[str] | None = None,
        pending_only: bool = False,
        limit: int | None = 20,
    ) -> list[dict[str, Any]]:
        """Select visible material; ``limit=None`` explicitly exports every episode."""
        if limit is not None and not 1 <= limit <= 100:
            raise FunctionalRejection("EPISODE_SELECTION_LIMIT_INVALID")
        selected = []
        if episode_ids is not None:
            ids = list(dict.fromkeys(episode_ids))
            if limit is not None and len(ids) > limit:
                raise FunctionalRejection("EPISODE_SELECTION_EXCEEDS_LIMIT")
            for episode_id in ids:
                episode = self.read(episode_id)
                if episode is not None and (not pending_only or not episode["consolidated"]):
                    selected.append(episode)
            return selected
        offset = 0
        while limit is None or len(selected) < limit:
            page = self.service.store.search(self.namespace, limit=100, offset=offset)
            for item in page:
                if item.namespace != self.namespace:
                    continue
                episode = self.read(item.key)
                if episode is not None and (not pending_only or not episode["consolidated"]):
                    selected.append(episode)
                    if len(selected) == limit:
                        return selected
            if len(page) < 100:
                break
            offset += 100
        return selected

    def source_matches(self, query: str) -> dict[str, int]:
        """Match unchecked descriptions to their currently visible original sources.

        Scores locate source bodies, never turn descriptions into factual evidence.
        Repeated descriptions or episodes do not multiply the same source's score.
        """
        tokens = _lexical_tokens(query)
        if not tokens:
            return {}
        matches: dict[str, int] = {}
        for episode in self.select(limit=None):
            for description in episode["descriptions"]:
                terms = set(_lexical_tokens(description["text"], include_cjk_unigrams=True))
                score = sum(token in terms for token in tokens)
                if score:
                    for ref in description["source_refs"]:
                        matches[ref] = max(matches.get(ref, 0), score)
        return matches

    def associated_records(self, episode_id: str) -> list[dict[str, Any]]:
        """Follow provenance to actual current records, rather than copied summaries."""
        episode = self.read(episode_id, include_sources=False)
        if episode is None:
            return []
        refs = set(episode["source_refs"])
        return [
            row
            for row in self.service.records()
            if row.get("ok") and refs.intersection(self.service._version_source_refs(row["value"]))
        ]

    def mark_consolidated(self, episode_ids: Sequence[str], request_id: str) -> None:
        """An execution marker, never an additional factual observation."""
        with self.service._locked():
            for episode_id in episode_ids:
                if self.read(episode_id, include_sources=False) is None:
                    raise FunctionalRejection("EPISODE_SOURCE_UNAVAILABLE")
                self.service.store.put(
                    self.consolidated_namespace, episode_id, {"request_id": request_id}, index=False
                )
