from __future__ import annotations

from uuid import UUID

import pytest

from milai.domain import CausalTokenCodec, CausalTokenError

TENANT = UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT = UUID("22222222-2222-4222-8222-222222222222")
SECRET = "test-causal-secret-with-at-least-32-characters"


def test_causal_token_round_trip_is_tenant_bound_and_opaque() -> None:
    codec = CausalTokenCodec(SECRET)
    token = codec.issue(TENANT, 42)
    position = codec.decode(token, TENANT)
    assert position.tenant_id == TENANT
    assert position.minimum_outbox_sequence == 42
    assert "11111111" not in token

    with pytest.raises(CausalTokenError, match="tenant mismatch"):
        codec.decode(token, OTHER_TENANT)


def test_causal_token_rejects_tamper_wrong_key_and_malformed_values() -> None:
    codec = CausalTokenCodec(SECRET)
    token = codec.issue(TENANT, 42)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    wrong_key = CausalTokenCodec("an-independent-secret-that-is-at-least-32-characters")

    for supplied in (tampered, wrong_key.issue(TENANT, 42), "not-a-token", ".."):
        with pytest.raises(CausalTokenError, match="invalid causal token"):
            codec.decode(supplied, TENANT)

    with pytest.raises(ValueError, match="positive"):
        codec.issue(TENANT, 0)
    with pytest.raises(ValueError, match="32 characters"):
        CausalTokenCodec("short")
