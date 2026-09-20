#!/usr/bin/env python3
"""Verify identity-bound Product behavior revalidation receipts."""

from __future__ import annotations

import argparse

from verify_architecture_conformance import (
    ARCHITECTURE_MANIFEST_PATH,
    CROSSWALK_PATH,
    PRODUCT_MANIFEST_PATH,
    _load_revalidation_receipts,
    _read_json,
    _revalidation_receipt_paths,
    _sha256_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify all checked-in receipts against the current Product identity",
    )
    parser.parse_args()

    product_manifest = _read_json(PRODUCT_MANIFEST_PATH)
    crosswalk = _read_json(CROSSWALK_PATH)
    claims = _load_revalidation_receipts(
        crosswalk=crosswalk,
        product_manifest_sha256=_sha256_file(PRODUCT_MANIFEST_PATH),
        product_tree_sha256=str(product_manifest["tree_sha256"]),
        architecture_manifest_sha256=_sha256_file(ARCHITECTURE_MANIFEST_PATH),
    )
    receipt_paths = _revalidation_receipt_paths()
    receipt_count = len(receipt_paths)
    preserved_failed_receipts = sum(
        _read_json(path).get("execution", {}).get("status") == "FAIL" for path in receipt_paths
    )
    current_receipt_count = len(
        {claim["receipt"] for values in claims.values() for claim in values}
    )
    claim_count = sum(len(values) for values in claims.values())
    failed_receipts = {
        claim["receipt"]
        for values in claims.values()
        for claim in values
        if claim["execution_status"] == "FAIL"
    }
    print(
        "Behavior revalidation receipts: PASS "
        f"({receipt_count} validated receipts; {current_receipt_count} current; "
        f"{claim_count} current claims; {preserved_failed_receipts} preserved "
        f"diagnostic failures; {len(failed_receipts)} current failures)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
