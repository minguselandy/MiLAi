"""Stable owner/session scope for foundation and external memory adapters."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FoundationScope:
    run_id: str
    arm_id: str
    user_id: str
    episode_id: str

    def config(self) -> dict[str, Any]:
        parts = [self.run_id, self.arm_id, self.user_id, self.episode_id]
        if not all(parts):
            raise ValueError("FOUNDATION_SCOPE_EMPTY_PART")
        thread_id = hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()
        return {
            "configurable": {
                "thread_id": thread_id,
                "foundation_run_id": self.run_id,
                "arm_id": self.arm_id,
                "user_id": self.user_id,
            },
            "max_concurrency": 1,
            # The model's own counter enforces the 12-request public-message limit.
            "recursion_limit": 128,
        }
