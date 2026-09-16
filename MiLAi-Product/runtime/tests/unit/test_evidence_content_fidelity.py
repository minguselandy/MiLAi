from __future__ import annotations

import pytest
from pydantic import ValidationError

from milai.domain.evidence import EvidenceIngestRequest


@pytest.mark.parametrize("content", [" \tfirst\r\n中文\nlast\n ", "\t\r\n "])
def test_evidence_content_is_preserved_while_identifiers_are_normalized(content: str) -> None:
    request = EvidenceIngestRequest.model_validate(
        {
            "source_type": " RUNTIME_OBSERVATION ",
            "source_ref": " source ",
            "subject_id": " subject ",
            "observed_at": "2026-09-06T10:00:00+08:00",
            "content": content,
            "permission_snapshot": {"readable": True},
        }
    )
    assert request.content == content and request.source_ref == "source"
    assert request.model_dump(mode="json")["content"] == content
    with pytest.raises(ValidationError):
        EvidenceIngestRequest.model_validate({**request.model_dump(), "content": ""})
