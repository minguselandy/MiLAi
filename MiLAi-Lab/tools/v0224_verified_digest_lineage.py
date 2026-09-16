"""Explicit R03 lineage connection for synthetic development, not a gate PASS."""

from v0220_wire_contract import fingerprint
from v0222_presentation_lineage_v2 import (
    EVIDENCE_INDEX_PATH,
    EVIDENCE_INDEX_SHA256,
    INDEX_STATUS,
    LAUNCH_REVIEW_PATH,
    LAUNCH_REVIEW_SHA256,
    LineageError,
    _launch_review,
    _terminal,
    read_inventory,
)
from v0222_scoped_evidence import _guard
from v0222_scoped_history import INVENTORY_PATH, INVENTORY_SHA256, presentation_history
from v0224_verified_digest_scope import BundleReadScope


def verify_lineage_r03(scope: BundleReadScope) -> dict:
    """Keep original lineage checks; only static tree authority changes in R03.

    The caller must close this explicit scope successfully before consuming its
    result. All historical accounting, launch checks and fresh SQL calls remain
    original helpers in their original order. No module aliases are patched.
    """
    if not isinstance(scope, BundleReadScope):
        raise TypeError("EXPLICIT_R03_BUNDLE_SCOPE_REQUIRED")
    with _guard(scope):
        index = scope.read_json(EVIDENCE_INDEX_PATH, EVIDENCE_INDEX_SHA256)
        if (
            type(index) is not dict
            or set(index) != {"status", "description", "files"}
            or index["status"] != INDEX_STATUS
            or type(index["description"]) is not str
            or type(index["files"]) is not dict
            or fingerprint(index["files"])
            != fingerprint(
                {
                    str(INVENTORY_PATH): INVENTORY_SHA256,
                    str(LAUNCH_REVIEW_PATH): LAUNCH_REVIEW_SHA256,
                }
            )
            or not INVENTORY_PATH.is_absolute()
            or not LAUNCH_REVIEW_PATH.is_absolute()
            or INVENTORY_PATH == LAUNCH_REVIEW_PATH
        ):
            raise LineageError("EXACT_TWO_PINNED_LINEAGE_ROOTS_REQUIRED")
        scope.verify_static_tree(EVIDENCE_INDEX_PATH, EVIDENCE_INDEX_SHA256)
        inventory = read_inventory(scope)
        history = presentation_history(scope)
        review = _launch_review(scope, inventory)
        for expected, proof in zip(inventory["terminal_states"], review["roots"], strict=True):
            _terminal(scope, inventory, expected, proof)
        return history
