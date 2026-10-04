"""Opt-in review allowance in the existing Store, never a semantic equivalence test."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from milai_lab.memory.functional_state import (
    FunctionalIntegrityError,
    FunctionalMaintenanceRejection,
    FunctionalRejection,
    FunctionalReviewRejection,
    digest,
    namespace,
)
from milai_lab.memory.service import MemoryService


def bounded_support_review(
    service: MemoryService, binding: dict[str, Any], evidence: dict[str, Any],
    operation_id: str, requested: dict[str, Any], review: Callable[[], None],
) -> dict[str, Any] | None:
    """One initial proposal plus one revision per public request / actual record.

    New creations cannot be reliably split into independent semantic matters from
    arbitrary model wording; conservatively share a request's creation allowance.
    Rejected exact inputs replay their original refusal, without another review.
    An approval is usable only by its original durable operation identity.
    The caller has already checked current source visibility and target identity.
    """
    matter = {"owner": service.owner, "bank": list(service.namespace),
              "session": binding["session"], "request_source": binding["source_ref"],
              "target": evidence.get("record_id") or "request_new_memory",
              "policy": "maintenance_two_proposals_v1"}
    if evidence.get('record_id'):
        creation = {**matter, 'target': 'request_new_memory'}
        with service._locked():
            created = service.store.get(namespace(service), 'maintenance-' + digest(creation))
            prior_creations = copy.deepcopy(created.value['proposals']) if created else []
        for attempt in prior_creations:
            receipt = service.replay_requested(
                binding['session'], attempt['operation_id'], attempt['requested'])
            if receipt is not None and receipt.get('ok') and receipt['id'] == evidence['record_id']:
                matter = creation  # Same actual record, even after its first successful create.
                break
    key = "maintenance-" + digest(matter)
    proposal_sha = digest(evidence)
    previous_operation: str | None = None
    with service._locked():
        stored = service.store.get(namespace(service), key)
        checked_state = copy.deepcopy(stored.value) if stored else None
    for attempt in (checked_state or {}).get('proposals', []):
        if attempt['proposal_sha256'] == proposal_sha or attempt['status'] == 'rejected':
            continue
        receipt = service.replay_requested(
            binding['session'], attempt['operation_id'], attempt['requested'])
        if receipt is None:
            assert checked_state is not None
            raise FunctionalMaintenanceRejection(
                'FUNCTIONAL_MAINTENANCE_PRIOR_OUTCOME_UNCONFIRMED: A different proposal cannot '
                'bypass an unfinished attempt. Recover the original operation identity first.',
                {'matter_id': key, 'proposal_limit': 2,
                 'proposals_used': len(checked_state['proposals']),
                 'prior_attempt_status': attempt['status'], 'prior_semantic_effect': 'unconfirmed',
                 'formation_status': 'pending', 'target': matter['target']})
    with service._locked():
        stored = service.store.get(namespace(service), key)
        if (stored.value if stored else None) != checked_state:
            raise FunctionalIntegrityError('FUNCTIONAL_MAINTENANCE_CHANGED_DURING_PREFLIGHT')
        state: dict[str, Any] = copy.deepcopy(stored.value) if stored is not None else {
            "matter": matter, "proposals": []}
        if state.get("matter") != matter or not isinstance(state.get("proposals"), list):
            raise FunctionalIntegrityError("FUNCTIONAL_MAINTENANCE_BINDING_CHANGED")
        proposals: list[dict[str, Any]] = state["proposals"]
        if len(proposals) > 2 or any(not isinstance(p, dict)
                or not {"proposal_sha256", "operation_id", "status", "read_revision",
                        "requested"} <= p.keys()
                or p['status'] not in {'attempted', 'rejected', 'review_allowed'}
                or (p['status'] == 'rejected' and not isinstance(p.get('rejection'), dict))
                for p in proposals):
            raise FunctionalIntegrityError("FUNCTIONAL_MAINTENANCE_PROPOSALS_INVALID")
        details = {"matter_id": key, "proposal_limit": 2, "proposals_used": len(proposals),
                   "target": matter["target"], "formation_status": "pending",
                   "scope": "actual_record" if evidence.get("record_id")
                   else "conservative_request_creation"}
        prior = next((p for p in proposals if p["proposal_sha256"] == proposal_sha), None)
        if prior is not None:
            if prior["status"] == "rejected":
                error = prior["rejection"]
                if "review_status" in error:
                    raise FunctionalReviewRejection(error["reason"], error["review_status"],
                        error["evidence_sha256"], error.get("failure_type"))
                raise FunctionalRejection(error["reason"])
            if prior["operation_id"] != operation_id:
                previous_operation = prior['operation_id']
                details.update(prior_attempt_status=prior['status'],
                               prior_semantic_effect='consult_original_operation_receipt')
            elif prior["status"] == "review_allowed":
                return None  # Exact evidence, original operation; visibility rechecked.
        else:
            if len(proposals) >= 2:
                raise FunctionalMaintenanceRejection(
                    "FUNCTIONAL_MAINTENANCE_PROPOSAL_LIMIT: Initial proposal and one revision "
                    "already attempted. Preserve original qualifications and leave this matter "
                    "pending. A new explicit user request may start another checked attempt.",
                    details)
            prior = {"proposal_sha256": proposal_sha, "operation_id": operation_id,
                     "read_revision": evidence.get("read_revision"), "status": "attempted",
                     "requested": copy.deepcopy(requested)}
            proposals.append(prior)
            service.store.put(namespace(service), key, state, index=False)
    if previous_operation is not None:
        # Service methods own their lock. Return a real prior receipt only while
        # that exact committed version is still visible/current; no new write.
        receipt = service.replay_requested(binding['session'], previous_operation, requested)
        if receipt is not None and receipt.get('ok'):
            current = service.read(receipt['id'])
            if current.get('ok') and current['value']['revision'] == receipt['revision']:
                return {**receipt, 'existing_record': True}
        raise FunctionalMaintenanceRejection(
            "FUNCTIONAL_MAINTENANCE_PRIOR_ATTEMPT_REQUIRES_ORIGINAL_OPERATION_ID: "
            "An earlier approval or unfinished attempt is not new write authority.", details)
    try:
        review()
    except FunctionalRejection as error:
        outcome: dict[str, Any] = {"status": "rejected", "rejection": {"reason": str(error)}}
        if isinstance(error, FunctionalReviewRejection):
            outcome["rejection"].update(review_status=error.review_status,
                evidence_sha256=error.evidence_sha256, failure_type=error.failure_type)
        _finish(service, key, matter, proposal_sha, operation_id, outcome)
        raise
    else:
        _finish(service, key, matter, proposal_sha, operation_id, {"status": "review_allowed"})
    return None


def _finish(service: MemoryService, key: str, matter: dict[str, Any], proposal_sha: str,
            operation_id: str, outcome: dict[str, Any]) -> None:
    with service._locked():
        stored = service.store.get(namespace(service), key)
        if stored is None or stored.value.get("matter") != matter:
            raise FunctionalIntegrityError("FUNCTIONAL_MAINTENANCE_STATE_LOST")
        state = copy.deepcopy(stored.value)
        prior = next((p for p in state["proposals"]
                      if p["proposal_sha256"] == proposal_sha
                      and p["operation_id"] == operation_id), None)
        if prior is None:
            raise FunctionalIntegrityError("FUNCTIONAL_MAINTENANCE_ATTEMPT_LOST")
        prior.update(outcome)
        service.store.put(namespace(service), key, state, index=False)
