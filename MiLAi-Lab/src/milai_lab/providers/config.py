from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ProviderEndpoint:
    provider_id: str
    base_url: str
    model: str
    timeout_seconds: float = 120.0
    max_concurrency: int = 1
    retry_count: int = 0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if not self.provider_id or not self.model:
            raise ValueError("provider identity and model are required")
        if self.timeout_seconds <= 0 or self.max_concurrency <= 0:
            raise ValueError("timeout and concurrency must be positive")
        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")

