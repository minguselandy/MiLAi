"""Research-only correction eligibility over existing v0.7 version/exposure facts.

No bank mutation, Product facts, model calls, semantic judge or benefit estimator.
The caller authenticates facts and persists the review BEFORE later execution.
Declared support/complete lineage are reviewed inputs, not inferred by this code.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from milai_lab.methods.controlled_workspace import MemoryCard
from milai_lab.methods.experience_utility import VersionUtility, version_key
from milai_lab.methods.reasoning_bank import ExperienceBank

SCHEMA = "milai-research-revision-review-v1"
_TEXT = {"type": "string", "minLength": 1}
_REFS = {"type": "array", "items": _TEXT, "uniqueItems": True}
_PROPERTIES = {
    **{
        k: _TEXT
        for k in (
            "revision_id",
            "version_key",
            "source_task_id",
            "policy_version",
            "kind",
            "reason",
            "feedback_regime",
            "creation_ref",
        )
    },
    **{k: {"type": "integer", "minimum": 0} for k in ("created_sequence", "review_sequence")},
    **{k: _REFS for k in ("changed_claims", "changed_applicability", "original_evidence_refs")},
    "support": {"enum": ["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]},
    "support_ref": {"anyOf": [_TEXT, {"type": "null"}]},
    "lineage_clusters": {"anyOf": [_REFS, {"type": "null"}]},
    "provenance_ref": {"anyOf": [_TEXT, {"type": "null"}]},
    "feedback_visibility": {
        "type": "object",
        "propertyNames": _TEXT,
        "additionalProperties": {"enum": ["VISIBLE", "NATIVE_OUTCOME", "UNKNOWN"]},
    },
}
_VALIDATOR = Draft202012Validator(
    {
        "type": "object",
        "properties": _PROPERTIES,
        "required": list(_PROPERTIES),
        "additionalProperties": False,
    }
)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _utility(bank: ExperienceBank) -> VersionUtility:
    if not bank.utility_state:
        raise ValueError("REVISION_UTILITY_STATE_MISSING")
    utility = VersionUtility(copy.deepcopy(bank.utility_state))
    utility.validate(bank.cards, bank.historical_cards, bank.completed_tasks)
    return utility


def _card(bank: ExperienceBank, record: dict[str, Any]) -> MemoryCard:
    key = version_key(record["memory_ref"], record["revision"])
    if key in bank.historical_cards:
        return MemoryCard(**bank.historical_cards[key])
    return bank.cards[record["memory_ref"]]


def freeze_revision_review(bank: ExperienceBank, review: dict[str, Any]) -> dict[str, Any]:
    """Bind the existing exact lineage and scope; sealing alone proves no chronology.

    lineage_clusters must cover ALL transitive source/feedback and formation-task
    clusters, with provenance_ref locating that review. None means not established.
    kind uses the Opportunity Ledger taxonomy; only its two correction kinds enter
    the core effect denominator. Unknown/other kinds never become correction credit.
    """
    if next(_VALIDATOR.iter_errors(review), None) is not None:
        raise ValueError("INVALID_REVISION_REVIEW")
    if review["feedback_regime"] not in {"H", "R"}:
        raise ValueError("INVALID_FEEDBACK_REGIME")
    if review["created_sequence"] >= review["review_sequence"]:
        raise ValueError("REVIEW_PRECEDES_REVISION")
    utility = _utility(bank)
    new = utility.state["versions"].get(review["version_key"])
    if new is None or new["predecessor"] is None:
        raise ValueError("REVIEW_REQUIRES_EXISTING_REVISION_LINEAGE")
    old = utility.state["versions"][new["predecessor"]]
    visited: set[str] = set()
    ancestor = review["version_key"]
    while ancestor is not None:
        if ancestor in visited:
            raise ValueError("REVISION_LINEAGE_CYCLE")
        visited.add(ancestor)
        ancestor = utility.state["versions"][ancestor]["predecessor"]
    if new == old or new["card_sha256"] == old["card_sha256"]:
        raise ValueError("REVISION_HAS_NO_VERSION_CHANGE")
    source = utility.state["tasks"].get(review["source_task_id"])
    if source is None or source["scope"] != bank.scope:
        raise ValueError("REVISION_SOURCE_TASK_SCOPE_MISMATCH")
    if source["feedback_regime"] != review["feedback_regime"]:
        raise ValueError("REVISION_FEEDBACK_REGIME_MISMATCH")
    old_card = _card(bank, old)
    original = set(review["original_evidence_refs"])
    feedback = set(review["feedback_visibility"])
    if original != set(old_card.source_refs):
        raise ValueError("REVIEW_ORIGINAL_EVIDENCE_MISMATCH")
    if feedback != set(new["feedback_refs"]) or not original | feedback <= bank.sources.keys():
        raise ValueError("REVIEW_FEEDBACK_BINDING_MISMATCH")
    bound = {
        "schema": SCHEMA,
        "arm_kind": "RESEARCH_PROTOTYPE",
        "scope_sha256": _digest(bank.scope),
        "bank_contract_sha256": _digest(bank.contract),
        "evidence_sha256": {
            ref: hashlib.sha256(bank.sources[ref].encode()).hexdigest()
            for ref in sorted(original | feedback)
        },
        "feedback_release": {
            "regime": source["feedback_regime"],
            "native_result": source["native_result"],
            "result_ref": source["result_ref"],
        },
        "review": copy.deepcopy(review),
        "predecessor": copy.deepcopy(old),
        "version": copy.deepcopy(new),
        "version_retired": _card(bank, new).retired,
    }
    return {**bound, "review_sha256": _digest(bound)}


def assess_revision_reuse(
    bank: ExperienceBank,
    sealed: dict[str, Any],
    *,
    later_task_id: str,
    later_cluster: str | None,
    retrieval: dict[str, Any],
    actor_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Check one later request, not quality, cost, observed use or causal benefit.

    retrieval: {ref, task_id, scope_sha256, sequence, version_keys}; actor_receipt
    adds sequence to the NativeProvider SETTLED receipt. Both must be authentic
    runner facts; this function does not dispatch, sign or invent owner facts.
    """
    expected = freeze_revision_review(bank, sealed["review"])
    if expected != sealed:
        raise ValueError("FROZEN_REVISION_REVIEW_CHANGED")
    review = sealed["review"]
    rejected, unknown = [], []
    if review["kind"] not in {"CORRECTION", "SCOPE_NARROWING"}:
        rejected.append("NOT_CORE_CORRECTION")
    if _card(bank, sealed["predecessor"]).text == _card(bank, sealed["version"]).text:
        rejected.append("NO_CLAIM_TEXT_CHANGE")
    if review["support"] == "UNSUPPORTED":
        rejected.append("UNSUPPORTED_CORRECTION")
    elif review["support"] != "SUPPORTED" or not review["support_ref"]:
        unknown.append("SEMANTIC_SUPPORT_UNKNOWN")
    change = "changed_applicability" if review["kind"] == "SCOPE_NARROWING" else "changed_claims"
    if (
        not review[change]
        or not review["original_evidence_refs"]
        or not review["feedback_visibility"]
    ):
        unknown.append("CORRECTION_EVIDENCE_INCOMPLETE")
    visibility = set(review["feedback_visibility"].values())
    if "UNKNOWN" in visibility:
        unknown.append("FEEDBACK_VISIBILITY_UNKNOWN")
    source = bank.utility_state["tasks"][review["source_task_id"]]
    if "NATIVE_OUTCOME" in visibility:
        if review["feedback_regime"] != "R":
            rejected.append("HIDDEN_OUTCOME_NOT_ALLOWED_IN_H")
        elif source["native_result"] is None:
            unknown.append("NATIVE_OUTCOME_NOT_RELEASED")
    lineage = review["lineage_clusters"]
    if not lineage or not review["provenance_ref"] or not later_cluster:
        unknown.append("SOURCE_CLUSTER_INDEPENDENCE_UNKNOWN")
    elif later_cluster in lineage:
        rejected.append("SHARED_SOURCE_CLUSTER")
    if later_task_id == review["source_task_id"]:
        rejected.append("SAME_TASK_REUSE")
    if sealed["version_retired"]:
        rejected.append("REVISED_VERSION_RETIRED")
    versions = retrieval.get("version_keys")
    if (
        not isinstance(versions, list)
        or any(not isinstance(key, str) or not key for key in versions)
        or len(versions) != len(set(versions))
        or not isinstance(retrieval.get("ref"), str)
    ):
        raise ValueError("INVALID_LATER_RETRIEVAL")
    if (
        retrieval.get("task_id") != later_task_id
        or not retrieval.get("ref")
        or retrieval.get("scope_sha256") != sealed["scope_sha256"]
    ):
        raise ValueError("LATER_RETRIEVAL_BINDING_MISMATCH")
    retrieved_at, exposed_at = retrieval.get("sequence"), actor_receipt.get("sequence")
    if (
        type(retrieved_at) is not int
        or type(exposed_at) is not int
        or not review["review_sequence"] < retrieved_at < exposed_at
    ):
        raise ValueError("LATER_REUSE_CHRONOLOGY_MISMATCH")
    if review["version_key"] not in versions:
        rejected.append("REVISED_LINEAGE_NOT_RETRIEVED")
    if actor_receipt.get("session") != later_task_id:
        raise ValueError("LATER_ACTOR_TASK_MISMATCH")
    utility = _utility(bank)
    later = utility.state["tasks"].get(later_task_id)
    matched = None
    if later is not None:
        if later["scope"] != bank.scope:
            raise ValueError("LATER_TASK_SCOPE_MISMATCH")
        if bank.completed_tasks.index(later_task_id) <= bank.completed_tasks.index(
            review["source_task_id"]
        ):
            rejected.append("NOT_A_LATER_COMPLETED_TASK")
        matched = next(
            (e for e in later["exposures"] if e["request_id"] == actor_receipt.get("request_id")),
            None,
        )
    if matched is None:
        unknown.append("LATER_CONFIRMED_EXPOSURE_MISSING")
    else:
        # Reuse the existing confirmation contract on an ephemeral sequence.
        sequence: list[dict[str, Any]] = []
        utility.confirm(
            sequence,
            receipt=actor_receipt,
            task_id=later_task_id,
            versions=[(v["memory_ref"], v["revision"]) for v in matched["versions"]],
        )
        if sequence[0] != matched:
            raise ValueError("LATER_ACTOR_RECEIPT_MISMATCH")
        if review["version_key"] not in {
            version_key(v["memory_ref"], v["revision"]) for v in matched["versions"]
        }:
            rejected.append("REVISED_VERSION_NOT_EXPOSED")
    return {
        "schema": SCHEMA,
        "arm_kind": "RESEARCH_PROTOTYPE",
        "revision_id": review["revision_id"],
        "review_sha256": sealed["review_sha256"],
        "eligible": False if rejected else (None if unknown else True),
        "rejected_reasons": rejected,
        "unknown_reasons": unknown,
        "request_id": actor_receipt.get("request_id"),
        "observable_use": "UNKNOWN",
        "claim_ceiling": "STRUCTURAL_ELIGIBILITY_NOT_BENEFIT",
    }
