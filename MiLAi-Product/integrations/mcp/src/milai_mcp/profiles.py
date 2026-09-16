from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResolveBudgetProfile:
    name: str
    max_results: int
    max_candidates: int
    max_context_tokens: int
    max_latency_ms: int
    recommended_max_calls: int

    def runtime_budget(self) -> dict[str, int]:
        return {
            "max_results": self.max_results,
            "max_candidates": self.max_candidates,
            "max_context_tokens": self.max_context_tokens,
            "max_latency_ms": self.max_latency_ms,
        }


_CANONICAL: dict[str, ResolveBudgetProfile] = {
    "MCP_INTERACTIVE_STANDARD_V01": ResolveBudgetProfile(
        name="MCP_INTERACTIVE_STANDARD_V01",
        max_results=50,
        max_candidates=120,
        max_context_tokens=8_192,
        max_latency_ms=2_000,
        recommended_max_calls=3,
    ),
    "MCP_INTERACTIVE_WIDE_V01": ResolveBudgetProfile(
        name="MCP_INTERACTIVE_WIDE_V01",
        max_results=50,
        max_candidates=120,
        max_context_tokens=16_384,
        max_latency_ms=5_000,
        recommended_max_calls=3,
    ),
    "MCP_RESEARCH_V01": ResolveBudgetProfile(
        name="MCP_RESEARCH_V01",
        max_results=50,
        max_candidates=120,
        max_context_tokens=16_384,
        max_latency_ms=5_000,
        recommended_max_calls=5,
    ),
}

_ALIASES = {
    "OPENWORKER_USABILITY_WIDE_V01": "MCP_INTERACTIVE_STANDARD_V01",
    "OPENWORKER_USABILITY_WIDE_V02": "MCP_INTERACTIVE_WIDE_V01",
}


def accepted_resolve_budget_profile_names() -> tuple[str, ...]:
    return tuple(sorted((*_CANONICAL, *_ALIASES)))


def resolve_budget_profile(name: str) -> ResolveBudgetProfile:
    canonical_name = _ALIASES.get(name, name)
    try:
        return _CANONICAL[canonical_name]
    except KeyError as exc:
        raise ValueError("unknown resolve budget profile") from exc
