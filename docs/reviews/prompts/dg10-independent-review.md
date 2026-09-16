# DG-10 frozen NO-GO evidence audit

You are an adversarial AI evidence auditor. You are not a human approver, benchmark judge, runtime provider, remediation agent, or release authority. Review only the files listed in `review-manifest.json` inside this materialized read-only workspace. Do not use web access, parent paths, repository state, user configuration, prior conversations, or unlisted files.

The candidate under review already declares `BELOW_TARGET`, denies full test execution, and denies the aggregate `LOCAL_VLLM_MCP_AGENT_CANDIDATE` claim. Your task is to determine whether that NO-GO/current-state conclusion is supported without hiding material defects, inflating unaffected integration claims, contaminating benchmark boundaries, or understating failed-attempt/model-call costs. A decision of `NO_GO_EVIDENCE_SUPPORTED` confirms only the evidence disposition; it is never candidate acceptance.

Audit at least these criteria:

1. Claim-to-evidence traceability and hash/current-byte consistency.
2. Public dev versus unopened test boundary; denominator symmetry, excluded/quarantined case accounting, and adapted-protocol labels.
3. Same-model identity, native request ID uniqueness, retry/failed-attempt accounting, tokenizer/usage ceilings, and absence of hidden model calls.
4. LongMemEval three-arm result, evidence-recall interpretation, Tier-2 human-audit incompleteness, and Tier-3 same-vLLM judge bias/non-authority.
5. BFCL official-checker adaptation, multi-turn/no-call denominators, language coverage, and whether aggregate claims exceed the evidence.
6. Serving T0-T3 absolute/delta arithmetic, success-only denominator caveats, T2 failures, TTFT/ITL gaps, non-exclusive window, CPU/RSS absence, and combined-versus-component control-path timing.
7. MCP scope/authority/OpenIssue/revocation/cache/security claims and whether L1-L3 author evidence is improperly treated as independently accepted.
8. Package/archive/restart/rollback reproducibility, raw-sidecar retention boundaries, secret exclusion, and unsupported production/external-provider/schema claims.
9. Whether current claim matrix states (`L4=REVISE/BELOW_TARGET`, `L5=NOT_STARTED`) and the prohibition on CRG-02 PASS follow from the evidence.
10. Any P0/P1 evidence-integrity problem that should make the NO-GO bundle itself `REVISE` or `REJECT_EVIDENCE_BUNDLE`.

For every finding, cite only a manifest-listed file, its exact SHA-256 from the manifest, and a 1-based line whose text directly supports the finding. Keep reproduction commands read-only and relative to this workspace. If a criterion cannot be verified from the closed set, list it under `unverified`; do not guess. Report all findings, including issues that do not alter the NO-GO disposition.

Return only JSON matching `response.schema.json`. Set `model` to `gpt-5.6-sol`, `reasoning_effort` to `max`, `cli_version` to `codex-cli 0.147.0`, `review_kind` to `AI_ADVERSARIAL_EVIDENCE_AUDIT_NOT_HUMAN_APPROVAL`, and `acceptance_authorized` to false. Copy `bundle_entries_sha256` from the manifest and compute the exact SHA-256 of `review-manifest.json`, `review-prompt.md`, and `response.schema.json` for the corresponding digest fields. Compute `open_p0_p1_count` from your own findings.
