# MiLAi Logical Architecture 1.0.0 Independent Release Verification

Status: `COMPLETE — PASS`

Decision: `PASS`

## Reviewer record

```text
Reviewer: /root/af09_reviewer_retry
Reviewer role/independence: same independent AF-09 reviewer who accepted candidate.5;
  did not author candidate.5, the release promotion, frozen bundle, manifest,
  archive, receipt, source locks, author report, or release-gate evidence;
  publisher summaries were navigation only and were not treated as proof
Review started: 2026-08-17T07:27:19Z / 2026-08-17T15:27:19+08:00
Review completed: 2026-08-17T07:43:06Z / 2026-08-17T15:43:06+08:00
Workspace: /cra/memory/mx_memory/MiLAi
Release: MiLAi Logical Architecture 1.0.0
Signature/reference: /root/af09_reviewer_retry release-1.0.0 independent verification
```

This is a new verification of the frozen release, not a rewrite of the candidate.5 acceptance.
The only repository object created by this review is this record. The frozen bundle, all candidates,
manifests, source/Git locks, archives, receipts, prior reviews/remediations/reports and runtime/research
source remain untouched.

The immutable receipt deliberately retains `Independent release verification: PENDING`. That is its
submission-time state, not a current contradiction, and this review did not edit it.

## External trust anchors and no-drift result

The three expected digests below came from the external review assignment and were independently
checked against the bundle-external receipt. They were not derived from the release manifest.

| Object | External expected SHA-256 | Before review | After all checks, before this record | Result |
| --- | --- | --- | --- | --- |
| `architecture/v1.0/architecture_manifest.json` | `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e` | same | same | PASS |
| `docs/releases/MiLAi-Logical-Architecture-1.0.0-ac16f3b7-release.tar.gz` | `dc43e4a5facb6037e14a98ca4f50e26a8bb599c3bd38440e8bcbd3869a3e4ff1` | same | same | PASS |
| `docs/releases/MiLAi-Logical-Architecture-1.0.0-release-receipt.md` | `15c98d883e5048719898f91cb0f4f4aaa994f422311141d6d77ac4d6a79febc4` | same | same | PASS |

The receipt is physically outside `architecture/v1.0/` and explicitly defines itself as the
release-mode external anchor (`docs/releases/MiLAi-Logical-Architecture-1.0.0-release-receipt.md:8-10,
105-121`). Its 19,138,126-byte archive, manifest identity and accepted-candidate lineage agree with
the independently supplied values. A final post-record rehash is recorded in the handoff; the three
release objects remained identical.

## Environment

```text
Host: Linux 5.15.0-86-generic x86_64
Python: 3.11.13
uv: 0.8.3
Ruff: 0.16.3
mypy: 1.20.2
pytest: 8.4.2
psql client: PostgreSQL 16.14
Docker Compose: 2.35.1
Timezone: UTC and Asia/Shanghai
```

## Deterministic archive audit

I inspected the gzip/tar with Python `tarfile` without extracting it and independently constructed
the expected member set from the live manifest. Project locks resolve under `MiLAi/`; workspace locks
resolve at the workspace-relative path used by the archive.

| Property | Independent result |
| --- | --- |
| Expected set | exactly 19 `required_files` + 161 `source_locks`; overlap 0; total 180 |
| Actual inventory | exactly 180 members; no missing or extra member |
| Order and uniqueness | lexically sorted; 180 unique names |
| Path safety | every name is a non-empty safe relative path; no absolute path or `..` traversal |
| Member type | every member is a regular file; no directory, symlink, hardlink, device or special entry |
| Ownership | every member `uid=0`, `gid=0` |
| Time | every member `mtime=1786896000`; gzip header mtime 0 |
| Archive/live identity | 180/180 byte-identical; byte differences 0 |
| Manifest identity | archived manifest bytes exactly equal the live release manifest |

Observed audit output:

```text
entries=180 expected=180 sorted=True unique=True regular_only=True
safe_paths=True uid_gid_zero=True member_mtime_ok=True gzip_mtime=0
missing=0 extra=0 archive_live_diffs=0 archived_manifest_equal=True
required=19 source_locks=161 overlap=0
```

This verifies the receipt's archive statements independently; the receipt was not used as a
substitute for member inspection.

## Frozen bundle and external-anchor gates

```text
runtime/.venv/bin/ruff format --check \
  architecture/v1.0/scripts architecture/v1.0/tests
  PASS — 4 files already formatted

runtime/.venv/bin/ruff check \
  architecture/v1.0/scripts architecture/v1.0/tests
  PASS — All checks passed

runtime/.venv/bin/python architecture/v1.0/scripts/validate_bundle.py
  PASS — MiLAi architecture bundle validation: PASS (1.0.0 frozen)

runtime/.venv/bin/python architecture/v1.0/scripts/verify_lock.py \
  --scope all --mode release \
  --expected-manifest-sha256 \
  ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e
  PASS — MiLAi architecture lock verification: PASS (1.0.0 frozen)

MILAI_ARCHITECTURE_LOCK_SCOPE=all runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0/tests -v
  PASS — 19 tests, OK (final run 1.099s)
```

The 19 tests include direct missing-artifact, missing-invariant, absent-negative-evidence,
bundle/source/Git drift, omitted-lock, path-escape, forged-acceptance and external-anchor negatives.
In particular:

- `test_release_mode_requires_external_manifest_trust_anchor` rejects release verification without
  an external digest;
- `test_release_mode_rejects_external_manifest_digest_mismatch` rejects a wrong digest;
- `test_coordinated_bundle_and_manifest_tamper_fails_external_anchor` copies the bundle, changes
  `OBJECTS.md`, updates its manifest lock to match the tampered bytes, and still rejects the forged
  manifest against the original external digest;
- `test_frozen_release_requires_independent_acceptance` and
  `test_manifest_rejects_forged_acceptance_binding` reject a downgraded or substituted ACCEPT chain.

I also invoked the release verifier directly with an all-zero external digest. It exited 1 with
`external manifest trust anchor mismatch`, while reporting the actual trusted digest
`ac16f3b7...55d0e`. Coordinated bundle/manifest substitution therefore cannot use bundle self-consistency
to replace the external trust anchor.

`refresh_manifest.py` was not run because it is a mutation utility and this frozen review forbids
rewriting the release. Its declared-path and self-lock failure behavior is covered by the adversarial
tests above.

## Accepted-candidate chain

I rehashed the four live accepted-candidate objects and compared each value both with the release
manifest's `review` object and with the actual independent review, not merely the release report.

| Object | Recomputed SHA-256 | Manifest binding | Result |
| --- | --- | --- | --- |
| candidate.5 manifest | `ece90366e5e3e3647af729351d8ae80310c8f6c30db1cf85b5a74ccb4168ed64` | exact | PASS |
| candidate.5 archive | `aa56033be8380eee9289baec11c7839cbaa9bde4d66f69c6757fd9fb651ff668` | exact | PASS |
| candidate.5 receipt | `2f8189339b6ee5b45107cee93c67005c1051171810913014631b1bd8c9aed680` | exact | PASS |
| independent ACCEPT review | `8ddf9e8a302b46404319ef2b27d99403f73b4d71127b4483c3b333d27230d1f3` | exact | PASS |

The live review itself says `COMPLETE — DECISION ACCEPT` and `Decision: ACCEPT`
(`docs/reviews/AF-09-independent-rereview-candidate.5-2026-08-17.md:3-5`), records the same manifest
before and at decision (`:17-24`), and independently closes AF09-F01 through AF09-F12 (`:333-353`).
Its finding table has no open finding (`:424-443`). The semantic and hard-reject tables are present at
`:355-423`; open P0/P1/P2 is explicitly `none`. The release `FREEZE_REVIEW.md:15-37` and manifest review
object bind that exact reviewer, decision and four-object chain.

Result: candidate.5 acceptance is an actual external decision with all F01-F12 closed and open
P0/P1/P2 = 0; it is not a publisher-authored assertion.

## Candidate.5 to release semantic-drift audit

### Frozen normative books

For the seven normative books I diffed accepted candidate.5 against release and normalized only the
explicit promotion tokens: candidate version/header to `1.0.0 FROZEN`, candidate/bundle wording to
frozen/release wording, candidate review scope to release scope, and `PASS_CANDIDATE` to
`PASS_FROZEN`. No object, permission, invariant, transaction, retrieval, deletion or threat predicate
was normalized away. All seven normalized byte streams are exactly equal:

| File | SHA-256 of both normalized streams |
| --- | --- |
| `OBJECTS.md` | `050f0831cbe94aa16a70058001ed333e1b8ff2a58d322bf8637dd19165c38b53` |
| `PERMISSIONS.md` | `6076046ccd3da2c307c7b8d690973e19d7084b7615c2f679a1db180582364674` |
| `INVARIANTS.md` | `62dc6e42e9f82b0bbe7862fb99e8221624c032efbb182b32b0c4e261906b2194` |
| `TRANSACTIONS.md` | `fc1c59e89683efb0c5e385cabe8796f28e4fb2d3cdf71646495e5042e5b28dbb` |
| `RETRIEVAL_CONTEXT.md` | `1b779e6cbacb3ab912c1ef33d80c564657d1774faf4270c2c003ed1594bb32a9` |
| `DELETION_RECOVERY.md` | `ea1abfb9fced2228ecc714804a5f5eee7728f5169c46029daf87d0fe65fed0e3` |
| `THREAT_MODEL.md` | `07990ebce7ed49c016cf6d28a8408dd8c9526c60323dda41ca5c485c80a37c30` |

Observed result: `NORMATIVE_NORMALIZED_EQUAL=7/7`.

### Crosswalk and promotion metadata

I compared machine crosswalk entries after path/status promotion normalization. Normative fields and
direct test-node mappings are equal for 9 goals, 12 invariants, 8 transactions and 5 roles. Candidate
evidence remains a subset; additions are only the accepted review/promotion evidence. All ten freeze
gate changes are status promotion, with AF-09 bound to the external acceptance.

I read/diffed `AF09_REMEDIATION.md`, `AUTHOR_PREFLIGHT.md`, `BASELINE.md`, `CROSSWALK.md`,
`FREEZE_REVIEW.md`, `README.md`, the manifest, validator/verifier/tests, the release report and the four
changed root status documents. `refresh_manifest.py` is byte-identical. Validator/verifier/test changes
enforce release identity, FROZEN state, exact ACCEPT binding and release-mode external trust; they do
not change normative semantics. Root-document diffs only replace the prior pending candidate state
with the accepted/frozen current state and preserve the implementation/schema boundaries.

### Source/Git lock delta

```text
candidate.5 source locks = 156
release source locks     = 161
common                    = 156
common unchanged          = 152
promotion-state changed   = 4
accepted-evidence added   = 5
removed                   = 0
Git locks byte-identical  = 9/9
```

The four changed source locks are exactly `AGENTS.md`, `MiLAi_Lean_V1_实施合同.md`,
`MiLAi_Lean_V1_设计开发_GOALS.md` and `MiLAi_Logical_Architecture_v1_设计文档.md`. The five additions
are exactly the candidate.5 manifest, archive, receipt, independent ACCEPT review and
`docs/reports/DG-00-architecture-1.0.0-release-2026-08-17.md`. There is no removed source lock.

Direct category comparison against candidate.5 and live bytes produced:

```text
ADR=19 CI=1 compose=1 migration=26 research-governance=2 runbook=3
runtime-other=57 drift=0
GIT_LOCK_IDENTITY count=9 byte_identical=True
```

Thus all release-governing executable/runtime/migration, ADR, runbook, CI, Compose, governed research
identity and external Git inputs are the same accepted bytes. Promotion metadata does not conceal a
normative change.

## Current project-state consistency

The current declarations agree:

- `AGENTS.md:7-11,44-49` says candidate.5 was independently accepted, `architecture/v1.0/` is the
  current frozen logical architecture, Runtime remains candidate and Schema remains experimental/no-go;
- `MiLAi_Lean_V1_实施合同.md:3-6,20-29` names the frozen architecture while expressly forbidding a
  Schema/Runtime/production-ready expansion;
- `MiLAi_Lean_V1_设计开发_GOALS.md:6-9,203-248,858-885` records DG-00 achieved, AF-09 accepted,
  frozen architecture and the continuing experimental/candidate/no-go boundary;
- `MiLAi_Logical_Architecture_v1_设计文档.md:3-9,1151-1160,1267-1299` records `1.0.0 FROZEN`,
  AF-09 independently accepted, and keeps Schema/implementation/real-data gates separate.

Candidate.2-.5 `PENDING` text remains only inside clearly dated immutable historical sections; the
current 13.5 GOALS section supersedes it. The release receipt's `PENDING` is likewise the immutable
pre-verification receipt state and must not be edited.

Current state is therefore coherent:

```text
Logical Architecture 1.0.0 FROZEN
AF-09 ACCEPTED_INDEPENDENT_REVIEW
Schema 0.1.x EXPERIMENTAL
Implementation CANDIDATE
Synthetic-only
NO-GO FOR SCHEMA FREEZE
```

## Current-source, package, CI/Compose and documentation gates

Exact source-lock comparison is the primary evidence that release promotion did not alter accepted
runtime behavior. I nevertheless reran non-database gates on the current bytes and isolated all
generated output outside the repository.

```text
runtime/.venv/bin/ruff format --check .     PASS — 105 files
runtime/.venv/bin/ruff check .              PASS
runtime/.venv/bin/mypy                      PASS — 57 source files

[fresh temporary research copy]
ruff format/check                           PASS — 11 files
mypy --strict research/ospc                 PASS — 7 source files
unittest discover research/ospc/tests       PASS — 9 tests (0.196s)
generate_fixtures + run_benchmark           PASS — 40 synthetic fixtures
fixture SHA-256                             8fd9482aacf58d8802a16dbc86a9e8043ffc28123d904f72b7b87a052eaa718a
decision                                    ABANDON; novelty_claim=false
reasons                                     HF-01_STRONG_TYPED_STATE_EQUIVALENT,
                                            HF-02_STATIC_OPEN_ISSUE_EQUIVALENT,
                                            HF-06_VALIDATOR_COST_WITHOUT_MEASURED_GAIN

uv build --offline --out-dir <temp-a>       PASS
uv build --offline --out-dir <temp-b>       PASS; byte-identical to temp-a
wheel SHA-256                               45e61f9376aa7bd7cd2b06f27cfeeb850bc4be278638285d4ae97f631bf64365
sdist SHA-256                               d17b910229004700876f845d7d885d4b34260e7ebafa7f0dfd498d12c280acbf
wheel / sdist inventory                     PASS — 63 / 120 unique safe entries
uv pip install --offline --no-deps          PASS — milai-runtime==0.1.0

Ruby YAML.safe_load .github/workflows/ci.yml
  PASS — mapping; job=runtime-and-research
[container values supplied without printing] docker compose -f runtime/compose.yaml config --quiet
  PASS

[root-bounded Markdown relative-link and fence audit before this record]
  PASS — 94 Markdown files; 1,200 headings; 22 relative links; zero errors
```

The independent package hashes reproduce the prior candidate.5 independent-review build. They are
an independent build result, not an assertion that the author-gate package hashes are universal
cross-environment package identities.

I did not rerun the 121-test PostgreSQL suite, migration foundation or backup/security database
suite. This is a deliberate evidence-based decision, not an unrun blocker: all 26 migrations and all
57 other runtime/config/test/package source-lock entries plus Compose are byte-identical to the exact
candidate.5 independently accepted by the real exact-role PostgreSQL, migration and backup/security
gates (`docs/reviews/AF-09-independent-rereview-candidate.5-2026-08-17.md:70-100,124-285`). Replaying
the same database tests cannot add promotion-identity evidence after zero executable drift. Current
Ruff/mypy, research, package, CI/Compose, documentation and release gates were rerun as independent
sanity checks. No review database was created and `/milai` was not touched.

All temporary research/package/cache directories created by this verification were removed.

## Findings

| ID | Severity | Finding | Disposition |
| --- | --- | --- | --- |
| — | — | No release-verification finding | No open P0, P1 or P2; all required checks passed |

## Decision and remaining boundary

`PASS` is warranted because the externally anchored manifest/archive/receipt identities are exact and
stable; the deterministic archive is safe and live-exact; release-mode validation and adversarial
tests reject self-consistent substitution; the accepted candidate four-object chain is genuine; all
F01-F12 are independently closed; normative candidate-to-release bytes differ only by controlled
promotion language; and executable/source/Git identities have no unreviewed drift.

This decision means only:

```text
MiLAi Logical Architecture 1.0.0 frozen release is trustworthy for its declared boundary.
```

It does **not** approve Schema freeze, production readiness, real-data readiness, remote/public access,
plaintext Blob use for personal data, target-device SLOs, or model/external-adapter enablement. The
remaining boundary is Schema `0.1.x EXPERIMENTAL`, Implementation `CANDIDATE`, synthetic-only,
real-personal-data denied, and `NO-GO FOR SCHEMA FREEZE`.

```text
Decision: PASS
Release manifest SHA-256 before/after checks:
  ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e
Release archive SHA-256 before/after checks:
  dc43e4a5facb6037e14a98ca4f50e26a8bb599c3bd38440e8bcbd3869a3e4ff1
Release receipt SHA-256 before/after checks:
  15c98d883e5048719898f91cb0f4f4aaa994f422311141d6d77ac4d6a79febc4
Open findings: none
Signature/reference: /root/af09_reviewer_retry release-1.0.0 independent verification
```
