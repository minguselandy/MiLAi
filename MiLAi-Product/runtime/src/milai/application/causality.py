from __future__ import annotations

from uuid import UUID

from milai.domain import CausalTokenCodec
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import RetrievalRepository


class CausalityService:
    def __init__(self, repository: RetrievalRepository, codec: CausalTokenCodec) -> None:
        self._repository = repository
        self._codec = codec

    def issue(self, context: SessionContext, outbox_ids: list[UUID]) -> dict[str, object]:
        sequence = self._repository.outbox_position(context, outbox_ids)
        return {
            "causal_token": self._codec.issue(context.tenant_id, sequence),
            "minimum_outbox_sequence": sequence,
        }
