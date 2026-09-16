from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[^\w\s]", re.UNICODE)


def token_count(value: object) -> int:
    """Use one frozen, dependency-free tokenizer for every method.

    This is an evaluation tokenizer, not a claim about a provider tokenizer.
    JSON keys, structural punctuation and method metadata are all charged.
    """

    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    return len(TOKEN_PATTERN.findall(rendered))


@dataclass(frozen=True)
class OpenIssueLabel:
    issue_id: str
    issue_type: str
    target_claim_id: str
    status: str
    support_refs: tuple[str, ...]
    contradict_refs: tuple[str, ...]
    discharge_rule: str
    dependencies: tuple[str, ...]
    authority: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> OpenIssueLabel:
        return cls(
            issue_id=value["issue_id"],
            issue_type=value["issue_type"],
            target_claim_id=value["target_claim_id"],
            status=value["status"],
            support_refs=tuple(value["support_refs"]),
            contradict_refs=tuple(value["contradict_refs"]),
            discharge_rule=value["discharge_rule"],
            dependencies=tuple(value["dependencies"]),
            authority=value["authority"],
        )


@dataclass(frozen=True)
class ResolutionLabel:
    evidence_id: str
    target_claim_id: str
    satisfies_rule: bool
    scope_matches: bool
    authority_matches: bool
    expected_status: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ResolutionLabel:
        return cls(**value)

    @property
    def admissible(self) -> bool:
        return self.satisfies_rule and self.scope_matches and self.authority_matches


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    domain: str
    goal: str
    budget_tokens: int
    history: tuple[str, ...]
    stable_state: tuple[str, ...]
    constraints: tuple[str, ...]
    issue: OpenIssueLabel
    resolution: ResolutionLabel
    annotation_version: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Fixture:
        return cls(
            fixture_id=value["fixture_id"],
            domain=value["domain"],
            goal=value["goal"],
            budget_tokens=value["budget_tokens"],
            history=tuple(value["history"]),
            stable_state=tuple(value["stable_state"]),
            constraints=tuple(value["constraints"]),
            issue=OpenIssueLabel.from_dict(value["issue"]),
            resolution=ResolutionLabel.from_dict(value["resolution"]),
            annotation_version=value["annotation_version"],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompressionResult:
    method: str
    method_code: str
    fixture_id: str
    budget_tokens: int
    b_min_tokens: int
    payload: dict[str, Any]
    charged_tokens: int
    infeasible: bool = False
    failure_code: str | None = None
    selection_steps: int = 0
    validator_checks: int = 0
    fallback_count: int = 0
    recovery_calls: int = 0
    recovered_tokens: int = 0
    model_calls: int = 0
    wall_time_ns: int = 0
    cpu_time_ns: int = 0
    gpu_time_ns: int = 0

    @property
    def budget_compliant(self) -> bool:
        return self.charged_tokens <= self.budget_tokens


def method_metadata(method_code: str, recovery_calls: int = 0) -> dict[str, Any]:
    # Every method uses a three-character code, so metadata token cost is equal.
    return {
        "method_code": method_code,
        "recovery_calls": recovery_calls,
        "schema": "ospc.eval.output.v1",
    }


def charged_token_count(
    payload: dict[str, Any],
    method_code: str,
    recovery_calls: int = 0,
    recovered_tokens: int = 0,
) -> int:
    return (
        token_count(payload)
        + token_count(method_metadata(method_code, recovery_calls))
        + recovered_tokens
    )


def protected_issue(issue: OpenIssueLabel) -> dict[str, Any]:
    return {
        "authority": issue.authority,
        "contradict_refs": list(issue.contradict_refs),
        "dependencies": list(issue.dependencies),
        "discharge_rule": issue.discharge_rule,
        "issue_id": issue.issue_id,
        "issue_type": issue.issue_type,
        "status": issue.status,
        "support_refs": list(issue.support_refs),
        "target_claim_id": issue.target_claim_id,
    }


def protected_payload(fixture: Fixture) -> dict[str, Any]:
    refs = sorted(set(fixture.issue.support_refs) | set(fixture.issue.contradict_refs))
    return {
        "compression_trace": {},
        "constraints": list(fixture.constraints),
        "evidence_pointers": refs,
        "evicted_recoverable": [],
        "goal": fixture.goal,
        "open_issues": [protected_issue(fixture.issue)],
        "stable_state": [],
        "status": "OK",
    }


def empty_payload(fixture: Fixture, *, status: str = "OK") -> dict[str, Any]:
    return {
        "compression_trace": {},
        "constraints": list(fixture.constraints),
        "evidence_pointers": [],
        "evicted_recoverable": [],
        "goal": fixture.goal,
        "open_issues": [],
        "stable_state": [],
        "status": status,
    }


def load_fixtures(path: Path) -> list[Fixture]:
    fixtures: list[Fixture] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        try:
            fixtures.append(Fixture.from_dict(value))
        except (KeyError, TypeError) as exc:
            raise ValueError(f"invalid fixture at line {line_number}") from exc
    return fixtures
