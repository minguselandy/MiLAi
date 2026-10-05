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
    stored_thread_id: str | None = None

    def config(self, *, thread_id: str | None = None) -> dict[str, Any]:
        parts = [self.run_id, self.arm_id, self.user_id, self.episode_id]
        if not all(parts):
            raise ValueError("FOUNDATION_SCOPE_EMPTY_PART")
        if thread_id is None:
            thread_id = self.stored_thread_id
        if thread_id is None:
            # Retained only for archived callers whose checkpoint keys already
            # use this shape. Current functional entry supplies a persisted ID.
            thread_id = hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()
        elif type(thread_id) is not str or not thread_id:
            raise ValueError("FOUNDATION_THREAD_ID_INVALID")
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
