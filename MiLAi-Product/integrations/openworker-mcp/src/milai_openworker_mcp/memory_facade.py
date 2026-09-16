from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from milai_openworker_mcp.settlement import (
    MemoryDataClassification,
    MemoryWriteHandoff,
    MemoryWriteIntent,
    MemoryWriteReceipt,
    SubmitterLane,
)

_LINEAGE_FRAGMENT = "milai-memory-lineage-v1="


class ReaderLane(Protocol):
    def resolve_memory(
        self, query: str, *, previous_context_id: str | None = None
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ReaderAlias:
    alias: str
    evidence_ids: tuple[str, ...]
    source_turn_refs: tuple[str, ...]
    claim_versions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OpenWorkerMemoryRecall:
    payload: dict[str, Any]
    context_id: str | None
    aliases: tuple[ReaderAlias, ...]

    @property
    def visible_aliases(self) -> tuple[str, ...]:
        return tuple(item.alias for item in self.aliases)

    def evidence_ids_for(self, aliases: Sequence[str]) -> tuple[str, ...]:
        selected = set(aliases)
        selected_rows = [item for item in self.aliases if item.alias in selected]
        source_ref_by_evidence_id: dict[str, str] = {}
        for item in self.aliases:
            if len(item.evidence_ids) == len(item.source_turn_refs):
                source_ref_by_evidence_id.update(
                    zip(item.evidence_ids, item.source_turn_refs, strict=True)
                )

        def roots(evidence_id: str, visiting: frozenset[str]) -> tuple[str, ...]:
            if evidence_id in visiting:
                return ()
            source_ref = source_ref_by_evidence_id.get(evidence_id)
            lineage = (
                decode_memory_support_lineage(source_ref)
                if source_ref is not None
                else None
            )
            if lineage is None:
                return (evidence_id,)
            next_visiting = visiting | {evidence_id}
            return tuple(
                root
                for support_id in lineage.evidence_ids
                for root in roots(support_id, next_visiting)
            )

        return tuple(
            dict.fromkeys(
                root
                for item in selected_rows
                for evidence_id in item.evidence_ids
                for root in roots(evidence_id, frozenset())
            )
        )


@dataclass(frozen=True, slots=True)
class MemorySupportLineage:
    context_sha256: str
    evidence_aliases: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExchangeSettlementReceipt:
    user: MemoryWriteReceipt
    assistant: MemoryWriteReceipt
    memory_support: MemorySupportLineage | None

    @property
    def outbox_ids(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (self.user.outbox_id, self.assistant.outbox_id)
            if value is not None
        )


class OpenWorkerMemoryFacade:
    """Host-owned reader/write facade for one tenant-bound Runtime namespace."""

    def __init__(
        self,
        reader: ReaderLane,
        *,
        submitter: SubmitterLane | None = None,
        subject_id: str | None = None,
        permission_snapshot: Mapping[str, Any] | None = None,
        data_classification: MemoryDataClassification = "SYNTHETIC",
    ) -> None:
        if submitter is not None and (subject_id is None or not subject_id.strip()):
            raise ValueError("exchange settlement requires a host-owned subject_id")
        self._reader = reader
        self._handoff = MemoryWriteHandoff(submitter) if submitter is not None else None
        self._subject_id = subject_id.strip() if subject_id is not None else None
        self._permission_snapshot = dict(permission_snapshot or {})
        self._data_classification = data_classification

    @property
    def settlement_enabled(self) -> bool:
        return self._handoff is not None

    def recall_for_operation(
        self,
        query: str,
        *,
        previous_context_id: str | None = None,
    ) -> OpenWorkerMemoryRecall:
        payload = (
            self._reader.resolve_memory(query, previous_context_id=previous_context_id)
            if previous_context_id is not None
            else self._reader.resolve_memory(query)
        )
        receipt = payload.get("context_receipt")
        context_id = (
            receipt.get("context_capsule_id") if isinstance(receipt, Mapping) else None
        )
        aliases = _reader_aliases(receipt)
        return OpenWorkerMemoryRecall(
            payload=dict(payload),
            context_id=context_id if isinstance(context_id, str) and context_id else None,
            aliases=aliases,
        )

    def settle_exchange(
        self,
        *,
        task_epoch: str,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
        user_content: str,
        assistant_content: str,
        user_observed_at: str,
        assistant_observed_at: str,
        round_ordinal: int,
        context_sha256: str | None = None,
        support_aliases: Sequence[str] = (),
        recall: OpenWorkerMemoryRecall | None = None,
    ) -> ExchangeSettlementReceipt:
        if self._handoff is None or self._subject_id is None:
            raise RuntimeError("OpenWorker exchange settlement is disabled")
        if round_ordinal < 0:
            raise ValueError("round_ordinal must be non-negative")
        aliases = tuple(dict.fromkeys(support_aliases))
        available = set(recall.visible_aliases if recall is not None else ())
        if aliases and (recall is None or not set(aliases).issubset(available)):
            raise ValueError("assistant support aliases are not Reader-visible")
        support: MemorySupportLineage | None = None
        if aliases and context_sha256 is not None:
            if recall is None:  # guarded above; keeps the lineage source explicit
                raise ValueError("assistant support recall is absent")
            support = MemorySupportLineage(
                context_sha256=context_sha256,
                evidence_aliases=aliases,
                evidence_ids=recall.evidence_ids_for(aliases),
            )
        user_source_ref = _source_ref(session_id, user_message_id)
        assistant_source_ref = _source_ref(
            session_id,
            assistant_message_id,
            support=support,
        )
        user_ordinal = round_ordinal * 2
        user = self._handoff.handoff(
            MemoryWriteIntent(
                intent_id=_intent_id(session_id, user_message_id, "user", user_content),
                task_epoch=task_epoch,
                source_type="OPENWORKER_USER_MESSAGE",
                source_ref=user_source_ref,
                subject_id=self._subject_id,
                observed_at=user_observed_at,
                content=user_content,
                speaker="user",
                source_context={
                    "session_id": session_id,
                    "turn_id": user_message_id,
                    "turn_ordinal": user_ordinal,
                    "round_id": user_message_id,
                    "round_ordinal": round_ordinal,
                    "next_turn_id": assistant_message_id,
                },
                permission_snapshot=self._permission_snapshot,
                data_classification=self._data_classification,
            ),
            confirmation="HANDOFF",
        )
        assistant = self._handoff.handoff(
            MemoryWriteIntent(
                intent_id=_intent_id(
                    session_id,
                    assistant_message_id,
                    "assistant",
                    assistant_content,
                ),
                task_epoch=task_epoch,
                source_type="OPENWORKER_ASSISTANT_MESSAGE",
                source_ref=assistant_source_ref,
                subject_id=self._subject_id,
                observed_at=assistant_observed_at,
                content=assistant_content,
                speaker="assistant",
                source_context={
                    "session_id": session_id,
                    "turn_id": assistant_message_id,
                    "turn_ordinal": user_ordinal + 1,
                    "round_id": user_message_id,
                    "round_ordinal": round_ordinal,
                    "previous_turn_id": user_message_id,
                },
                permission_snapshot=self._permission_snapshot,
                data_classification=self._data_classification,
            ),
            confirmation="HANDOFF",
        )
        return ExchangeSettlementReceipt(user=user, assistant=assistant, memory_support=support)


def decode_memory_support_lineage(source_ref: str) -> MemorySupportLineage | None:
    marker = "#" + _LINEAGE_FRAGMENT
    if marker not in source_ref:
        return None
    encoded = source_ref.split(marker, 1)[1]
    try:
        padding = "=" * (-len(encoded) % 4)
        value = json.loads(base64.urlsafe_b64decode(encoded + padding))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "context_sha256",
        "evidence_aliases",
        "evidence_ids",
    }:
        return None
    digest = value.get("context_sha256")
    aliases = value.get("evidence_aliases")
    evidence_ids = value.get("evidence_ids")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or not isinstance(aliases, list)
        or not isinstance(evidence_ids, list)
        or any(not isinstance(item, str) or not item for item in (*aliases, *evidence_ids))
    ):
        return None
    return MemorySupportLineage(digest, tuple(aliases), tuple(evidence_ids))


def _reader_aliases(receipt: object) -> tuple[ReaderAlias, ...]:
    if not isinstance(receipt, Mapping):
        return ()
    raw_mappings = receipt.get("receipt_mapping")
    if not isinstance(raw_mappings, list):
        return ()
    aliases: list[ReaderAlias] = []
    for raw in raw_mappings:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("alias"), str):
            raise ValueError("Reader receipt alias mapping is invalid")
        aliases.append(
            ReaderAlias(
                alias=raw["alias"],
                evidence_ids=_strings(raw.get("evidence_ids")),
                source_turn_refs=_strings(raw.get("source_turn_refs")),
                claim_versions=_strings(raw.get("claim_versions")),
            )
        )
    if len({item.alias for item in aliases}) != len(aliases):
        raise ValueError("Reader receipt aliases must be unique")
    return tuple(aliases)


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return ()
    return tuple(dict.fromkeys(item for item in value if item))


def _intent_id(session_id: str, message_id: str, speaker: str, content: str) -> str:
    material = json.dumps(
        {
            "session_id": session_id,
            "message_id": message_id,
            "speaker": speaker,
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "ow-" + hashlib.sha256(material.encode()).hexdigest()


def _source_ref(
    session_id: str,
    message_id: str,
    *,
    support: MemorySupportLineage | None = None,
) -> str:
    value = f"openworker://session/{session_id}/message/{message_id}"
    if support is None:
        return value
    encoded = base64.urlsafe_b64encode(
        json.dumps(
            {
                "context_sha256": support.context_sha256,
                "evidence_aliases": list(support.evidence_aliases),
                "evidence_ids": list(support.evidence_ids),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).decode().rstrip("=")
    return value + "#" + _LINEAGE_FRAGMENT + encoded
