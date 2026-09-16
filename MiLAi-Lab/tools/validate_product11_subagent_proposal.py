#!/usr/bin/env python3
"""Validate one Product-11 subagent proposal without reading its peer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from milai_lab.product11_subagent import (
    ANNOTATOR_ROLE,
    REVIEWER_ROLE,
    validate_subagent_proposal,
    validate_subagent_review_packet,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/fixtures/product11-opened-dev24.v0.6.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def run(
    *, proposal: Path, role: str, identity: str, source_packet: Path
) -> dict[str, Any]:
    for path in (proposal, source_packet):
        lowered = path.name.casefold()
        if "formal" in lowered or "longmemeval" in lowered:
            raise ValueError("Product-11 subagent validation refuses Formal-named inputs")
    fixture = _load_json(FIXTURE)
    fixture_sha = _sha256_file(FIXTURE)
    packet_sha = _sha256_file(source_packet)
    validate_subagent_review_packet(
        fixture,
        _load_json(source_packet),
        expected_role=role,
        expected_fixture_file_sha256=fixture_sha,
    )
    result = validate_subagent_proposal(
        fixture,
        _load_json(proposal),
        expected_role=role,
        expected_identity=identity,
        expected_packet_sha256=packet_sha,
    )
    result.pop("groups_by_case")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--role", choices=(ANNOTATOR_ROLE, REVIEWER_ROLE), required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--source-packet", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(
        json.dumps(
            run(
                proposal=args.proposal,
                role=args.role,
                identity=args.identity,
                source_packet=args.source_packet,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
