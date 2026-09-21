"""Codex-full and legacy governance mutation tool construction."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Annotated, Any, Literal

from milai_client import AgentRecallPolicy, MilaiClient, ProposalDraft
from pydantic import AwareDatetime, Field

from milai_mcp.input_contracts import (
    EvidenceContent,
    EvidenceSourceContextInput,
    RevocationReasonCode,
    SourceRef,
    SourceType,
    SubjectId,
)
from milai_mcp.server_contracts import CodexFullProposalInput, Profile
from milai_mcp.server_wire import _bounded, _wire_sha256


def extend_codex_governance_tools(
    *,
    registered_tools: list[Callable[..., Any]],
    profile: Profile,
    ordinary_catalog: bool,
    api: MilaiClient,
    submitter_api: MilaiClient,
    reviewer_api: MilaiClient,
    operator_api: MilaiClient,
    policy: AgentRecallPolicy,
    codex_full_data_classification: Literal["SYNTHETIC", "DEIDENTIFIED", "PERSONAL"],
    codex_project_id: str | None,
    _request_scope: Callable[[], dict[str, Any]],
    _request_project: Callable[[], str],
    _codex_request_identity: Callable[..., Any],
    _codex_record_is_in_bound_project: Callable[..., Any],
    _codex_claim: Callable[..., Any],
    _codex_proposal: Callable[..., Any],
    _codex_evidence_metadata: Callable[..., Any],
    _codex_full_mutation: Callable[..., Any],
    _codex_confirmation_summary: Callable[..., Any],
    with_guidance: Callable[..., dict[str, Any]],
) -> list[Callable[..., Any]]:
    if profile == "submitter":

        def milai_evidence_capture(
            operation_id: str,
            source_type: str,
            source_ref: str,
            subject_id: str,
            observed_at: str,
            content: str,
            permission_snapshot: dict[str, Any],
            confirmation: Literal["CAPTURE"],
            speaker: Literal["user", "assistant", "system", "tool"] | None = None,
            source_context: dict[str, Any] | None = None,
            retention_state: str = "READABLE",
            data_classification: Literal["SYNTHETIC", "DEIDENTIFIED", "PERSONAL"] = "SYNTHETIC",
        ) -> dict[str, Any]:
            """[WRITE/IDEMPOTENT] Store an explicitly supplied user/tool observation as immutable
            Evidence.

            Provide source, observed time, exact content, permissions, operation_id and
            confirmation=CAPTURE. This records an observation, not verified truth or an approved
            Claim; it does not ingest the surrounding conversation. Preserve the original
            operation_id only for an identical request, and reconcile unknown outcomes before
            resubmission.
            """
            if confirmation != "CAPTURE":
                raise PermissionError("literal CAPTURE confirmation is required")
            payload = {
                "source_type": source_type,
                "source_ref": source_ref,
                "subject_id": subject_id,
                "speaker": speaker,
                "source_context": source_context,
                "observed_at": observed_at,
                "content": content,
                "data_classification": data_classification,
                "permission_snapshot": permission_snapshot,
                "retention_state": retention_state,
            }
            receipt = api.capture_evidence(payload, operation_id=operation_id).raw
            return _bounded(
                {
                    **receipt,
                    "confirmation_summary": {
                        "source_type": source_type,
                        "source_ref": source_ref,
                        "subject_id": subject_id,
                        "speaker": speaker or "unknown",
                        "structured_source_context": source_context is not None,
                        "scope": permission_snapshot,
                        "retention_state": retention_state,
                        "data_classification": data_classification,
                        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                        "content_chars": len(content),
                    },
                }
            )

        def milai_proposal_create(
            operation_id: str,
            proposal: ProposalDraft,
            confirmation: Literal["SUBMIT"],
        ) -> dict[str, Any]:
            """[WRITE/IDEMPOTENT] Stage an Evidence-backed Proposal for review without approving a
            Claim.

            Provide operation_id, a ProposalDraft matching the schema, and confirmation=SUBMIT.
            For non-CREATE changes use the current target Claim/head. Review is a separate
            authorized operation; submitting does not raise authority. Reuse operation_id only
            for the identical request after checking an uncertain result.
            """
            if confirmation != "SUBMIT":
                raise PermissionError("literal SUBMIT confirmation is required")
            if proposal.target_claim_id is not None:
                proposal.validate_current_head(
                    api.get_claim(proposal.target_claim_id).claim_version_id
                )
            receipt = api.create_proposal(proposal, operation_id=operation_id).raw
            return _bounded(
                {
                    **receipt,
                    "confirmation_summary": {
                        "operation": proposal.operation,
                        "target_claim_id": proposal.target_claim_id,
                        "requested_authority": proposal.requested_authority,
                        "supporting_evidence_refs": list(proposal.supporting_evidence_refs),
                        "contradicting_evidence_refs": list(proposal.contradicting_evidence_refs),
                        "canonical_changed": False,
                    },
                }
            )

        registered_tools.extend([milai_evidence_capture, milai_proposal_create])

    if profile == "codex-full":

        def milai_evidence_capture_codex_full(
            operation_id: str,
            source_type: SourceType,
            source_ref: SourceRef,
            subject_id: SubjectId,
            observed_at: AwareDatetime,
            content: EvidenceContent,
            confirmation: Literal["CAPTURE"],
            speaker: Literal["user", "assistant", "system", "tool"] | None = None,
            source_context: EvidenceSourceContextInput | None = None,
        ) -> dict[str, Any]:
            """[WRITE/IDEMPOTENT] Store an explicitly supplied observation as immutable Evidence,
            not a Claim.

            Use when the current task authorizes preserving a source. Provide source_type,
            source_ref, subject_id, observed_at, exact content, operation_id and
            confirmation=CAPTURE. No surrounding Prompt or chat is collected automatically. The
            receipt identifies the Evidence; any Proposal/review is separate and needs its own
            authorization. Reuse operation_id only with an identical request.
            """
            if confirmation != "CAPTURE":
                raise PermissionError("literal CAPTURE confirmation is required")
            permission_snapshot = {**_request_scope(), "readable": True}
            payload = {
                "source_type": source_type,
                "source_ref": source_ref,
                "subject_id": subject_id,
                "speaker": speaker,
                "source_context": (
                    source_context.model_dump(mode="json") if source_context is not None else None
                ),
                "observed_at": observed_at.isoformat(),
                "content": content,
                "data_classification": codex_full_data_classification,
                "permission_snapshot": permission_snapshot,
                "retention_state": "READABLE",
            }
            receipt = _codex_full_mutation(
                "milai_evidence_capture",
                operation_id,
                lambda runtime_operation_id: dict(
                    submitter_api.capture_evidence(payload, operation_id=runtime_operation_id).raw
                ),
            )
            if ordinary_catalog:
                receipt["reference"] = {
                    "object_type": "EVIDENCE",
                    "evidence_id": receipt["evidence_id"],
                    "read_tool": "milai_evidence_get",
                    "read_arguments": {"evidence_id": receipt["evidence_id"]},
                }
            return _bounded(
                with_guidance(
                    {
                        **receipt,
                        "confirmation_summary": {
                            **_codex_confirmation_summary(),
                            "source_type": source_type,
                            "source_ref": source_ref,
                            "subject_id": subject_id,
                            "structured_source_context": source_context is not None,
                            "project_id": _request_project(),
                            "data_classification": codex_full_data_classification,
                            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                            "content_chars": len(content),
                            "canonical_changed": False,
                        },
                    },
                    "Evidence captured; Canonical Memory did not change. Propose a change only "
                    "when the current user or explicit Host workflow authorizes it.",
                    next_tool="milai_proposal_create",
                    when="AUTHORIZED_CANONICAL_CHANGE_WITH_SUPPORTING_EVIDENCE",
                )
            )

        milai_evidence_capture_codex_full.__name__ = "milai_evidence_capture"

        def milai_proposal_create_codex_full(
            operation_id: str,
            proposal: CodexFullProposalInput,
            confirmation: Literal["SUBMIT"],
        ) -> dict[str, Any]:
            """[WRITE/IDEMPOTENT] Stage an Evidence-backed Claim change as a Proposal; submission
            is not approval.

            Supply operation_id, confirmation=SUBMIT and a proposal object. CREATE patch
            requires subject_id, predicate, claim_type, payload (object), confidence (0..1),
            inside proposed_patch; provide supporting_evidence_refs as real Evidence UUIDs. Non-
            CREATE needs target_claim_id and expected_version_id plus the operation-specific
            schema fields. Use the declared nine-operation enum, not invented UPDATE/RETRACT.
            Review is separate; reuse operation_id only for an identical request.
            """
            if confirmation != "SUBMIT":
                raise PermissionError("literal SUBMIT confirmation is required")
            patch = dict(proposal.proposed_patch)
            if proposal.operation == "CREATE":
                patch["authority"] = policy.authority
            business_snapshot = proposal.model_dump(mode="json")
            host_principal_id, _scope_digest = _codex_request_identity()
            draft = ProposalDraft.model_validate(
                {
                    **business_snapshot,
                    "proposed_patch": patch,
                    "requested_authority": policy.authority,
                    "scope_predicate": _request_scope(),
                    "model_id": f"mcp-host:{host_principal_id}",
                    "template_version": "codex-full-proposal-v1",
                    "input_snapshot_hash": _wire_sha256(business_snapshot),
                    "derivation_policy_id": "codex-full-host-submitted-v1",
                }
            )
            for evidence_id in sorted(
                set(draft.supporting_evidence_refs) | set(draft.contradicting_evidence_refs)
            ):
                _codex_evidence_metadata(evidence_id)
            if draft.target_claim_id is not None:
                draft.validate_current_head(_codex_claim(draft.target_claim_id).claim_version_id)
            receipt = _codex_full_mutation(
                "milai_proposal_create",
                operation_id,
                lambda runtime_operation_id: dict(
                    submitter_api.create_proposal(draft, operation_id=runtime_operation_id).raw
                ),
            )
            return _bounded(
                with_guidance(
                    {
                        **receipt,
                        "confirmation_summary": {
                            **_codex_confirmation_summary(),
                            "operation": draft.operation,
                            "target_claim_id": draft.target_claim_id,
                            "host_owned_authority": policy.authority,
                            "project_id": _request_project(),
                            "supporting_evidence_refs": list(draft.supporting_evidence_refs),
                            "contradicting_evidence_refs": list(draft.contradicting_evidence_refs),
                            "canonical_changed": False,
                        },
                    },
                    "Proposal created; Canonical Memory is unchanged. Read the proposal and its "
                    "Evidence before any explicitly authorized review decision.",
                    next_tool="milai_proposal_get",
                    when="BEFORE_REVIEW",
                )
            )

        milai_proposal_create_codex_full.__name__ = "milai_proposal_create"
        registered_tools.extend(
            [milai_evidence_capture_codex_full, milai_proposal_create_codex_full]
        )

    if profile in {"reviewer", "codex-full"}:

        def milai_proposals_list(
            status: Literal["PENDING_REVIEW", "DEFERRED", "APPLIED", "REJECTED"] = (
                "PENDING_REVIEW"
            ),
            limit: int = 50,
        ) -> dict[str, Any]:
            """[READ] List up to 100 Proposals in the authorized project, optionally filtered by
            status.

            Use to locate a pending or previously reviewed proposal; expand one with
            milai_proposal_get. Proposals are proposed changes, not approved Claims. Listing
            neither reviews them nor authorizes a later decision.
            """
            if not 1 <= limit <= 100:
                raise ValueError(
                    "Problem: proposal list limit is invalid. Reason: the server accepts 1..100 "
                    "records per page. Fix: retry with limit between 1 and 100. Example: "
                    'milai_proposals_list({"status":"PENDING_REVIEW","limit":50}).'
                )
            proposals = (
                reviewer_api.list_proposals(status, limit=limit, project_id=_request_project())
                if profile == "codex-full"
                else reviewer_api.list_proposals(status, limit=limit)
            )
            if profile == "codex-full":
                proposals = [
                    proposal
                    for proposal in proposals
                    if _codex_record_is_in_bound_project(proposal, scope_field="scope_predicate")
                ][:limit]
            else:
                proposals = proposals[:limit]
            result = {"proposals": proposals}
            if profile == "codex-full":
                result = with_guidance(
                    result,
                    "These Proposals are non-authoritative. Read one full Proposal before making "
                    "an explicitly authorized review decision.",
                    next_tool="milai_proposal_get",
                    when="PROPOSAL_SELECTED_FOR_INSPECTION",
                )
            return _bounded(result)

        def milai_proposal_get(proposal_id: str) -> dict[str, Any]:
            """[READ] Read one proposed memory change by proposal_id, including its review context.

            Inspect its Evidence references, patch and target head before an authorized review.
            A Proposal is not a current approved Claim; this read does not approve it or
            authorize subsequent writes.
            """
            result = (
                _codex_proposal(proposal_id)
                if profile == "codex-full"
                else reviewer_api.get_proposal(proposal_id)
            )
            if profile == "codex-full":
                result = with_guidance(
                    result,
                    "Inspect the Proposal, supporting Evidence and current target head. Review it "
                    "only when the current user or explicit Host workflow authorizes the decision.",
                    next_tool="milai_memory_review",
                    when="EXPLICITLY_AUTHORIZED_REVIEW_DECISION",
                )
            return _bounded(result)

        def milai_memory_review(
            proposal_id: str,
            operation_id: str,
            decision: Literal["APPROVE", "REJECT"],
            policy_version: Annotated[str, Field(min_length=1, max_length=255)],
            reason_code: Annotated[str, Field(min_length=1, max_length=255)],
            confirmation: Literal["APPROVE", "REJECT"],
        ) -> dict[str, Any]:
            """[GOVERNANCE/DESTRUCTIVE/IDEMPOTENT] Record an authorized APPROVE or REJECT decision
            on a Proposal.

            Read the Proposal and supporting material first. Supply operation_id and matching
            decision/confirmation; APPROVE may create a ClaimVersion, REJECT does not approve
            the proposed change. policy_version and reason_code are audit labels, not proof of
            authorization. The same Host's review is not an independent review. Reuse
            operation_id only for an identical decision.
            """
            if confirmation != decision:
                raise PermissionError(
                    "Problem: review confirmation does not match decision. Reason: this guard "
                    "prevents accidental approval or rejection. Fix: set confirmation exactly to "
                    "APPROVE or REJECT to match decision. Example: decision=APPROVE, "
                    "confirmation=APPROVE."
                )

            def review_call(runtime_operation_id: str) -> dict[str, Any]:
                return dict(
                    reviewer_api.review_proposal(
                        proposal_id,
                        {
                            "decision": decision,
                            "policy_version": policy_version,
                            "reason_code": reason_code,
                        },
                        operation_id=runtime_operation_id,
                    ).raw
                )

            def review_codex_call(runtime_operation_id: str) -> dict[str, Any]:
                _codex_proposal(proposal_id)
                return review_call(runtime_operation_id)

            receipt = (
                _codex_full_mutation(
                    "milai_memory_review",
                    operation_id,
                    review_codex_call,
                )
                if profile == "codex-full"
                else review_call(operation_id)
            )
            result = {
                **receipt,
                "confirmation_summary": {
                    **(_codex_confirmation_summary() if profile == "codex-full" else {}),
                    "proposal_id": proposal_id,
                    "decision": decision,
                    "policy_version": policy_version,
                    "reason_code": reason_code,
                    "actor_separation": (
                        "ROLE_ROUTED_RUNTIME_CREDENTIALS_NOT_INDEPENDENT_HOST"
                        if profile == "codex-full"
                        else "NAMED_PROFILE_CAPABILITY"
                    ),
                    "canonical_mutation": "CONTROLLED_RUNTIME_PROCEDURE",
                },
            }
            if profile == "codex-full":
                result = with_guidance(
                    result,
                    "Review recorded. If approved, read the returned or target Claim exactly to "
                    "verify the new governed state before relying on it.",
                    next_tool="milai_memory_get",
                    when="DECISION_APPROVED_OR_CLAIM_VERIFICATION_NEEDED",
                )
            return _bounded(result)

        registered_tools.extend([milai_proposals_list, milai_proposal_get, milai_memory_review])

    if profile in {"operator", "codex-full"}:

        def milai_evidence_revoke(
            evidence_id: str,
            operation_id: str,
            reason_code: RevocationReasonCode,
            confirmation: Literal["REVOKE"],
        ) -> dict[str, Any]:
            """[DESTRUCTIVE/IDEMPOTENT] Revoke one exact Evidence record under current explicit
            deletion intent.

            Supply evidence_id, reason_code, operation_id and confirmation=REVOKE. Revocation
            blocks eligible reads immediately; physical purge is asynchronous and subject to
            storage/backup policy. Use milai_deletion_status_get to inspect progress. This is
            not Note deletion or namespace cleanup; a confirmation word does not grant
            authority.
            """
            if confirmation != "REVOKE":
                raise PermissionError(
                    "Problem: Evidence revocation lacks REVOKE. Reason: revocation immediately "
                    "blocks reads. Fix: verify the current user's request, then set "
                    'confirmation to REVOKE. Example: {"confirmation":"REVOKE"}.'
                )

            def revoke_call(runtime_operation_id: str) -> dict[str, Any]:
                return dict(
                    operator_api.revoke_evidence(
                        evidence_id,
                        {"reason_code": reason_code, "confirmation": confirmation},
                        operation_id=runtime_operation_id,
                    ).raw
                )

            def revoke_codex_call(runtime_operation_id: str) -> dict[str, Any]:
                _codex_evidence_metadata(evidence_id)
                return revoke_call(runtime_operation_id)

            receipt = (
                _codex_full_mutation(
                    "milai_evidence_revoke",
                    operation_id,
                    revoke_codex_call,
                )
                if profile == "codex-full"
                else revoke_call(operation_id)
            )
            result = {
                **receipt,
                "confirmation_summary": {
                    **(_codex_confirmation_summary() if profile == "codex-full" else {}),
                    "evidence_id": evidence_id,
                    "reason_code": reason_code,
                    "canonical_read": "FAIL_CLOSED_IMMEDIATELY",
                    "physical_purge": "ASYNCHRONOUS_RECONCILIATION",
                },
            }
            if profile == "codex-full":
                result = with_guidance(
                    result,
                    "Evidence is no longer readable. Physical purge is asynchronous; check status "
                    "when deletion completion matters.",
                    next_tool="milai_deletion_status_get",
                    when="PHYSICAL_DELETION_COMPLETION_MATTERS",
                )
            return _bounded(result)

        def milai_deletion_status_get(evidence_id: str) -> dict[str, Any]:
            """[READ] Check revocation and physical-deletion progress for one Evidence ID.

            Use after milai_evidence_revoke; pending physical purge does not mean the Evidence
            remains readable. Read the reported storage and backup stages before claiming
            erasure. This call neither advances deletion nor checks Note deletion.
            """
            if profile == "codex-full":
                _codex_evidence_metadata(evidence_id)
            result = operator_api.deletion_status(evidence_id)
            if profile == "codex-full":
                result = with_guidance(
                    result,
                    "Revoked Evidence remains unreadable even while purge is pending. Poll this "
                    "tool only when physical deletion completion matters.",
                    next_tool="milai_deletion_status_get",
                    when="STATUS_IS_NONTERMINAL_AND_COMPLETION_MATTERS",
                )
            return _bounded(result)

        def milai_namespace_cleanup_submit_operator(
            project_id: str,
            operation_id: str,
            reason_code: RevocationReasonCode,
            confirmation: Literal["CLEANUP_NAMESPACE"],
        ) -> dict[str, Any]:
            """[DESTRUCTIVE/IDEMPOTENT/ADMIN] Submit an explicitly authorized project namespace
            cleanup.

            Use only the separate administrator workflow with the exact project scope and
            confirmation required by the schema. Physical purge is asynchronous; submission is
            not proof of erasure. Preserve operation_id for identical replay. Never use this as
            a fallback for a refused interactive request.
            """
            if confirmation != "CLEANUP_NAMESPACE":
                raise PermissionError("literal CLEANUP_NAMESPACE confirmation is required")
            return _bounded(
                operator_api.submit_namespace_cleanup(
                    project_id=project_id,
                    reason_code=reason_code,
                    operation_id=operation_id,
                )
            )

        milai_namespace_cleanup_submit_operator.__name__ = "milai_namespace_cleanup_submit"

        def milai_namespace_cleanup_submit_codex_full(
            operation_id: str,
            reason_code: RevocationReasonCode,
            confirmation: Literal["CLEANUP_NAMESPACE"],
        ) -> dict[str, Any]:
            """[DESTRUCTIVE/IDEMPOTENT/ADMIN] Submit cleanup of the entire server-bound project
            namespace.

            Requires an explicit current-conversation namespace-cleanup request, operation_id
            and confirmation=CLEANUP_NAMESPACE. Not available in the ordinary interactive
            catalog. Physical purge continues asynchronously; query progress before claiming
            erasure. Never substitute this for deleting one Note or bypass a Host refusal.
            """
            if confirmation != "CLEANUP_NAMESPACE":
                raise PermissionError(
                    "Problem: namespace cleanup lacks the CLEANUP_NAMESPACE confirmation. Reason: "
                    "cleanup affects the entire bound project. Fix: call only for an explicit "
                    "current-user namespace deletion request and set confirmation exactly to "
                    "CLEANUP_NAMESPACE."
                )
            if codex_project_id is None:  # pragma: no cover - build-time invariant
                raise RuntimeError("codex-full project binding is unavailable")
            receipt = _codex_full_mutation(
                "milai_namespace_cleanup_submit",
                operation_id,
                lambda runtime_operation_id: dict(
                    operator_api.submit_namespace_cleanup(
                        project_id=_request_project(),
                        reason_code=reason_code,
                        operation_id=runtime_operation_id,
                    )
                ),
            )
            return _bounded(
                with_guidance(
                    {
                        **receipt,
                        "confirmation_summary": {
                            **_codex_confirmation_summary(),
                            "project_id": _request_project(),
                            "reason_code": reason_code,
                            "physical_purge": "ASYNCHRONOUS_RECONCILIATION",
                        },
                    },
                    "Namespace cleanup accepted; physical purge is asynchronous. Do not claim "
                    "completion until the status tool returns a terminal state.",
                    next_tool="milai_namespace_cleanup_status",
                    when="CLEANUP_COMPLETION_MATTERS",
                )
            )

        milai_namespace_cleanup_submit_codex_full.__name__ = "milai_namespace_cleanup_submit"

        def milai_namespace_cleanup_status(
            cleanup_job_id: str,
            offset: int = 0,
            limit: int = 100,
        ) -> dict[str, Any]:
            """[READ] Inspect paginated progress for an existing authorized namespace-cleanup job.

            Supply cleanup_job_id and continue only its returned pagination. This neither starts
            nor advances cleanup, and terminal job status must be interpreted with its reported
            deletion stages. Other projects' jobs are not accessible; no broad deletion request
            is implied.
            """
            result = operator_api.namespace_cleanup_status(
                cleanup_job_id,
                offset=offset,
                limit=limit,
            )
            if profile == "codex-full":
                if result.get("project_id") != _request_project():
                    raise PermissionError(
                        "Namespace cleanup is outside the server-bound project scope"
                    )
                result = with_guidance(
                    result,
                    "Do not claim namespace erasure before a terminal status. Poll only while the "
                    "job is nonterminal and completion matters.",
                    next_tool="milai_namespace_cleanup_status",
                    when="STATUS_IS_NONTERMINAL_AND_COMPLETION_MATTERS",
                )
            return _bounded(result)

        registered_tools.extend(
            [
                milai_evidence_revoke,
                milai_deletion_status_get,
                (
                    milai_namespace_cleanup_submit_codex_full
                    if profile == "codex-full"
                    else milai_namespace_cleanup_submit_operator
                ),
                milai_namespace_cleanup_status,
            ]
        )
    return registered_tools
