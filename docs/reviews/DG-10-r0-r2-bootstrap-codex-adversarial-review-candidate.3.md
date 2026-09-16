# DG-10 candidate.3 R0–R2 bootstrap Codex adversarial review

```text
review_role: CODEX_ADVERSARIAL_EVIDENCE_AUDITOR_ONLY
evidence_class: AUTHOR_ADVERSARIAL_NOT_INDEPENDENT
candidate_id: candidate.3
bundle_entries_sha256: ebced4dd305ea862d879f872e916f1f646083f519be0cc29a603ed40ecaa9d4d
review_outcome: REVISE
accepted_stages: []
model_calls_authorized: false
```

The review used only the repository-external read-only bundle. All 83 declared
material entries were rehashed successfully, and the recomputed canonical entry
root equals `ebced4dd305ea862d879f872e916f1f646083f519be0cc29a603ed40ecaa9d4d`.
This review has no authority to accept a stage or close a finding.

## Findings

### DG10-BOOT-CX-001 — P1 — archive replay instruction is not satisfiable

The prompt asks the reviewer to recompute the candidate.2 archive member manifest,
but the original archive bytes are intentionally absent from the closed bundle.
Only an author-produced member manifest and archive digest are present. A closed-set
reviewer can validate the manifest's internal shape but cannot independently derive
its member hashes or safe-path result.

Required action: distinguish the protected-archive human lane from the sanitized
Codex lane. The sanitized lane must say that archive bytes are excluded and must not
claim independent member-manifest recomputation. Any R0 acceptance must bind a
role-separated human replay receipt that had authorized access to the exact archive.

### DG10-BOOT-CX-002 — P1 — review response is not safely importable

`response.schema.json` lacks a reviewer identity hash, review time, authority receipt
binding, finding schema, and bundle-manifest digest. There is also no importer that
validates an external response and emits stage-qualified receipts. A self-authored
JSON object could therefore look structurally sufficient without proving reviewer
separation or being consumable by the model-run authorization gate.

Required action: add an exact response schema and fail-closed importer. Require a
distinct reviewer identity, authority receipt digest, transcript digest, exact bundle
and manifest hashes, structured findings, and zero open P0/P1 before generating any
stage receipt. The importer must never convert Codex evidence into acceptance.

### DG10-BOOT-CX-003 — P1 — current smoke runner cannot consume later acceptance

`run_dg10_remediation.py` reads the immutable pre-review stage map and supplies an
empty receipt list to its authorization evaluator. Even if a valid independent R0–R2
response were produced, the current command has no interface that could consume it.
Candidate.3 also retains the circular rule that R3 must already be ACCEPTED before
the T2 model smoke that is required to establish R3.

Required action: an independent authority must dispose the policy cycle. If it chooses
the new-candidate route, freeze a new contract where only the T2 control-path bootstrap
may run after R0–R2 acceptance, while all benchmark model runs remain gated by R0–R3.
The runner must consume hash-bound imported receipts; it must not infer acceptance from
repository state.

### DG10-BOOT-CX-004 — P2 — R2 source-to-verification binding is indirect

The 193-test fresh-install receipt binds a seven-file runner/helper closure. The broader
70-entry candidate source inventory is in a separate engineering status report. Both
are present in the bundle, but no terminal R2 receipt directly binds the inventory root
to the fresh-install receipt hash.

Required action: emit a supplemental R2 binding receipt containing the exact 70-entry
inventory root, worker-closure report digest, lock/environment identities, 193/193 test
result, Ruff result, and BFCL commit. This remains author evidence until independently
replayed.

## Disposition

R0, R1, and R2 remain `AUTHOR_CANDIDATE` / `REVIEW_REQUIRED`; none is accepted.
R3–R8 remain unopened. The bundle is useful as a transport closure, but findings
DG10-BOOT-CX-001 through DG10-BOOT-CX-003 must be addressed before requesting a
bootstrap acceptance decision.
