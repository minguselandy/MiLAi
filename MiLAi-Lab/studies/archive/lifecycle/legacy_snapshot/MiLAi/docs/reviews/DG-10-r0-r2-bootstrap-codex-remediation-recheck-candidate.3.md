# DG-10 candidate.3 bootstrap Codex remediation recheck

```text
review_role: CODEX_ADVERSARIAL_EVIDENCE_AUDITOR_ONLY
evidence_class: AUTHOR_ADVERSARIAL_NOT_INDEPENDENT
candidate_id: candidate.3
rechecked_bundle_entries_sha256: 083a3d4b312dcc87c8a87bcfd5a41b1f5a1f83c1c52ad28670ed9be68676f0d6
review_outcome: REVISE_ONE_P1_REMAINS
accepted_stages: []
model_calls_authorized: false
```

The v2 bundle contains 86 declared entries, is materialized with file mode `0444`
and directory mode `0555`, and reports a clean scan against 17 locally configured
secret values. This recheck remains non-accepting Codex evidence.

## Finding replay

- `DG10-BOOT-CX-001` — remediated in author evidence. The v2 prompt explicitly
  separates the sanitized Codex lane from protected-archive human replay. The importer
  requires a human/independent response with authorized protected archive access,
  exact archive digest, 201-member denominator, safe-member status and member-manifest
  hash. Codex evidence is rejected.
- `DG10-BOOT-CX-002` — remediated in author evidence. The exact response contract now
  binds reviewer identity, authority receipt, review time, manifest, transcript,
  structured findings and archive replay. `import_dg10_bootstrap_review.py` was checked
  with a valid synthetic independent fixture and a negative Codex fixture; the valid
  fixture produced three stage receipts but kept candidate.3 model authorization false,
  while the Codex fixture failed closed.
- `DG10-BOOT-CX-004` — remediated in author evidence. The supplemental R2 receipt
  directly binds the 70-entry source root, fresh-install closure report, lock and freeze
  hashes, 193/193 pytest result, Ruff result and BFCL commit.
- `DG10-BOOT-CX-003` — remains open P1. No independent authority has disposed the
  R3/T2 startup cycle. Candidate.3 cannot consume a policy outcome to authorize T2,
  and it must not be modified into doing so after its threshold/authorization contract
  was frozen. A role-separated reviewer must either require a new candidate with an
  R0–R2-only T2 bootstrap rule or reject bootstrap authorization.

## Disposition

The bundle is now fit to request an external R0–R2/bootstrap-policy review, but it is
not itself acceptance evidence. R0–R2 remain unaccepted; R3–R8 and all model calls
remain blocked pending the external response and fail-closed importer result.
