# Product-11 X0 subagent-sealed review runbook

This workflow is a user-authorized, opened-development, model-adjudicated alternative to the
historical HUMAN workflow. It never sets a HUMAN attestation or claims human gold. Formal inputs are
forbidden.

## Provenance boundary

```text
seal mode                  SUBAGENT_SEALED
claim ceiling              OPENED_DEVELOPMENT_MODEL_ADJUDICATED
human adjudication         NOT_PERFORMED
Formal files/cases         false / 0
```

Two subagents receive different source-only packets and must run without receiving the peer output,
the A0 trace, opportunity assignments, or treatment results. The orchestrator binds their identities,
roles, input packet hashes, invocation IDs and output hashes. Agreement proves exact model-review
agreement, not statistical independence or human truth.

## Prepare and freeze inputs before execution

```bash
uv run python tools/prepare_product11_subagent_workflow.py \
  --run-id <review-run> \
  --annotator-identity <annotator-id> \
  --reviewer-identity <reviewer-id> \
  --annotator-invocation-id <annotator-invocation> \
  --reviewer-invocation-id <reviewer-invocation> \
  --model-id <observed-model-id-or-explicit-inherited-value>
```

This creates two dedicated immutable `SUBAGENT_*` packets plus a pre-execution orchestration
manifest. The packets contain source cases only: no HUMAN attestation, A0 trace, treatment output,
opportunity assignment, peer proposal, or Evidence-ID mapping. Do not reuse the historical HUMAN
packets for this workflow.

## Validate each proposal

```bash
uv run python tools/validate_product11_subagent_proposal.py \
  --proposal var/product11/<run>/annotator-proposal.json \
  --role SUBAGENT_ANNOTATOR \
  --identity <orchestrator-assigned-annotator-id> \
  --source-packet data/labels/product11-subagent-annotator.packet.v0.1.json

uv run python tools/validate_product11_subagent_proposal.py \
  --proposal var/product11/<run>/reviewer-proposal.json \
  --role SUBAGENT_REVIEWER \
  --identity <orchestrator-assigned-reviewer-id> \
  --source-packet data/labels/product11-subagent-reviewer.packet.v0.1.json
```

Proposal files cannot contain opportunity assignments, HUMAN attestations or Formal claims.
`acceptable_evidence_ids` must be empty because the source packet exposes no deterministic
turn-ref-to-Evidence-ID mapping.

## Merge exact agreement

```bash
uv run python tools/merge_product11_subagent_reviews.py \
  --orchestration-manifest \
  var/product11/<review-run>/subagent-orchestration-manifest.json
```

Local `group_id` and notes do not participate in agreement. Exact turn/Evidence membership, required
semantics and derived source/session provenance do. Any disagreement produces only case IDs and
semantic hashes; it never produces adjudicated rows or chooses one proposal.

## Seal or stop

Only a conflict-free merge may be sealed:

```bash
uv run python tools/seal_product11_subagent_labels.py \
  --merge-summary var/product11/<review-run>/subagent-merge-summary.json \
  --run-id <seal-run>
```

The seal does not trust an adjudicated JSONL by itself. It reloads the immutable manifest, packets,
proposals and A0 trace; verifies every digest and producer envelope; then recomputes the exact merge
and requires byte-equivalent adjudicated rows. Handcrafted rows or a modified merge summary fail
closed.

The seal derives opportunity assignments after agreement from the frozen label-blind A0 trace. If
any required opportunity count is below eight, the terminal is
`PARKED_PRODUCT11_INSUFFICIENT_SUBAGENT_SEALED_OPPORTUNITY`. Do not reshape the slice, tune A0, run
X1/X2 treatment, or consume Formal 500 to repair the denominator.
