# Product-11 X0 independent-human review runbook

Status: `READY_FOR_TWO_INDEPENDENT_HUMANS`

This runbook is the only remaining entry path to the Product-11 X0 seal. It does not authorize
Product behavior, migration, X1--X4, or Formal 500 access.

## Inputs

- compact source-only view: `data/labels/product11-source-review-view.v0.1.json`
- full annotator source packet: `data/labels/product11-annotator.packet.v0.7.json`
- full reviewer source packet: `data/labels/product11-reviewer.packet.v0.7.json`
- annotator template: `data/labels/product11-annotator.submission-template.v0.1.jsonl`
- reviewer template: `data/labels/product11-reviewer.submission-template.v0.1.jsonl`

The two submission templates contain no model proposal and no A0 Product output. The compact view
contains full substantive turns and hashes/previews deterministic index-only distractors. A reviewer
may consult their role-specific full packet if a compacted turn needs inspection.

## Independent review

Each human copies their role-specific template to a new submission file. They must not read the
other human's submission, `product11-instance-groups.candidate.*`, the A0 trace, or an earlier
adjudication while making the judgment.

For the manifest row, set:

```json
{
  "human_review_status": "COMPLETE",
  "human_attestation": {
    "kind": "HUMAN",
    "id": "stable-human-identity",
    "signed_at": "ISO-8601 timestamp",
    "attestation": "I independently reviewed all 24 source-only cases."
  }
}
```

For every case row, set `human_review_status` to `COMPLETE` and provide one or more groups:

```json
{
  "group_id": "human-defined-local-id",
  "acceptable_evidence_ids": [],
  "acceptable_turn_refs": ["p11://..."],
  "source_ids": [],
  "session_ids": [],
  "required_for_answer": true
}
```

Repeated mentions of the same real-world instance belong to one group. Distinct instances belong to
different groups. An exact turn ref cannot occur in two required groups. `source_ids` and
`session_ids` may remain empty: the merger deterministically derives them from exact turn refs.

Each human can validate their own file without reading the other submission:

```bash
uv run python tools/validate_product11_human_submission.py \
  --submission /absolute/path/to/my.submission.jsonl \
  --role ANNOTATOR
```

The reviewer uses `--role INDEPENDENT_REVIEWER`. Success is
`READY_FOR_INDEPENDENT_MERGE`; a PENDING or incomplete template fails closed.

## Merge and conflict handling

After both 24/24 submissions are complete:

```bash
uv run python tools/merge_product11_human_reviews.py \
  --annotator /absolute/path/to/annotator.submission.jsonl \
  --reviewer /absolute/path/to/reviewer.submission.jsonl \
  --run-id p11-x0-human-merge-YYYYMMDDa
```

The merger verifies distinct HUMAN identities, role/source/trace hashes, all case order and
capabilities, exact identity membership, and cross-group overlap. Group IDs are ignored during
comparison; group semantics must agree exactly.

- `BLOCKED_HUMAN_RECONCILIATION_REQUIRED`: only `conflicts.json` and `summary.json` are produced;
  no adjudicated labels are emitted. The humans reconcile only listed cases, independently attest
  the corrected complete files, and run a new merge ID.
- `READY_FOR_X0_SEAL`: exact agreement and the derived 8/8/8 opportunity gate pass.
- `READY_FOR_INSUFFICIENT_OPPORTUNITY_TERMINAL_SEAL`: exact human agreement exists, but the frozen
  A0-derived opportunity counts are insufficient. This is a valid PARKED path, not permission to
  reshape the fixture.

Humans never enter opportunity flags. The merger derives them only after group agreement from the
frozen label-blind A0 trace.

## X0 seal

For an agreement output:

```bash
uv run python tools/seal_product11_labels.py \
  --adjudicated var/product11/p11-x0-human-merge-YYYYMMDDa/adjudicated.jsonl \
  --a0-trace artifacts/product11/p11-x0-a0-20260904f/product-trace.redacted.jsonl \
  --run-id p11-x0-seal-YYYYMMDDa
```

Only `PASS_PRODUCT11_X0_HUMAN_SEAL` permits Product behavior implementation. A human-sealed
insufficient-opportunity result terminalizes Product-11 as PARKED. No AI, model, agent, or proxy may
fill the HUMAN identities or attestations.
