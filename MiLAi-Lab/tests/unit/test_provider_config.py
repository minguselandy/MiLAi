from __future__ import annotations

import pytest

from milai_lab.providers.config import ProviderEndpoint


def test_provider_config_has_no_implicit_retry() -> None:
    endpoint = ProviderEndpoint("qwen", "http://127.0.0.1:7860", "pinned-model")

    assert endpoint.retry_count == 0
    assert endpoint.max_concurrency == 1


def test_provider_config_rejects_non_http_endpoint() -> None:
    with pytest.raises(ValueError, match="HTTP"):
        ProviderEndpoint("bad", "unix:///tmp/provider.sock", "model")

