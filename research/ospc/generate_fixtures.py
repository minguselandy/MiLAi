from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from .compressors import b_min_tokens, full_raw_tokens
from .models import Fixture, OpenIssueLabel, ResolutionLabel

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "fixtures" / "pilot.jsonl"
MANIFEST = ROOT / "fixtures" / "manifest.json"
ANNOTATION_VERSION = "ospc.annotation.v1"

ISSUE_TYPES = (
    "CONFLICT",
    "MISSING_EVIDENCE",
    "SCOPE_UNCERTAIN",
    "AUTHORITY_UNCERTAIN",
    "DEPENDENCY_INVALIDATED",
)
DOMAINS = ("software_project_memory", "personalized_multi_session_assistant")


def build_fixture(index: int) -> Fixture:
    fixture_no = index + 1
    domain = DOMAINS[index % len(DOMAINS)]
    issue_type = ISSUE_TYPES[index % len(ISSUE_TYPES)]
    issue_id = f"OI-{fixture_no:03d}"
    claim_id = f"CL-{fixture_no:03d}"
    support_refs = (f"EV-{fixture_no:03d}-S1",) + (
        (f"EV-{fixture_no:03d}-S2",) if index % 3 == 0 else ()
    )
    contradict_refs = (f"EV-{fixture_no:03d}-C1",) + (
        (f"EV-{fixture_no:03d}-C2",) if index % 4 == 0 else ()
    )
    dependencies = (f"DEP-{fixture_no:03d}",) if index % 2 == 0 else ()
    authority = "ACTION_SAFE" if index % 4 == 1 else "INFORMATIONAL"
    issue = OpenIssueLabel(
        issue_id=issue_id,
        issue_type=issue_type,
        target_claim_id=claim_id,
        status="WAITING_EVIDENCE" if index % 3 else "WAITING_USER",
        support_refs=support_refs,
        contradict_refs=contradict_refs,
        discharge_rule=f"RULE-{(index % 4) + 1}:MATCH_TARGET_SCOPE_AUTHORITY",
        dependencies=dependencies,
        authority=authority,
    )
    admissible = index % 2 == 0
    resolution = ResolutionLabel(
        evidence_id=f"EV-{fixture_no:03d}-R1",
        target_claim_id=claim_id,
        satisfies_rule=admissible or index % 4 == 1,
        scope_matches=admissible or index % 4 == 3,
        authority_matches=admissible,
        expected_status="RESOLVED" if admissible else issue.status,
    )
    topic = (
        "runtime compatibility"
        if domain.startswith("software")
        else "task-conditioned preference"
    )
    fixture = Fixture(
        fixture_id=f"OSP-{fixture_no:03d}",
        domain=domain,
        goal=f"Decide {topic} without closing {issue_id} before admissible evidence.",
        budget_tokens=0,
        history=(
            f"Episode 1: {support_refs[0]} supports {claim_id}; retain source lineage.",
            f"Episode 1: {contradict_refs[0]} contradicts {claim_id}; {issue_id} remains open.",
            f"Episode 2: routine activity {fixture_no} completed; it does not discharge {issue_id}.",
            f"Episode 2: a fluent recap suggests a single answer for {topic}, but has no authority.",
            f"Episode 3 candidate {resolution.evidence_id} must satisfy {issue.discharge_rule}.",
        ),
        stable_state=(
            f"Workspace-{fixture_no:03d} is active.",
            f"The current goal concerns {topic}.",
        ),
        constraints=(
            "Do not close an OpenIssue without admissible resolving Evidence.",
            "Do not collapse support and contradiction branches.",
        ),
        issue=issue,
        resolution=resolution,
        annotation_version=ANNOTATION_VERSION,
    )
    minimum = b_min_tokens(fixture)
    raw_cost = full_raw_tokens(fixture)
    # Eight fixtures are below B_min; sixteen permit the full-raw reference.
    budget_class = index % 5
    if budget_class == 0:
        budget = max(1, minimum - (3 + index % 4))
    elif budget_class == 1:
        budget = minimum
    elif budget_class == 2:
        budget = minimum + 12
    elif budget_class == 3:
        budget = max(minimum + 24, raw_cost)
    else:
        budget = raw_cost + 12
    return replace(fixture, budget_tokens=budget)


def main() -> None:
    fixtures = [build_fixture(index) for index in range(40)]
    body = "".join(
        json.dumps(
            fixture.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
        for fixture in fixtures
    )
    OUTPUT.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    manifest = {
        "annotation_version": ANNOTATION_VERSION,
        "fixture_count": len(fixtures),
        "generator": "research.ospc.generate_fixtures",
        "pilot_sha256": digest,
        "schema": "ospc.pilot.v1",
        "synthetic_only": True,
    }
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
