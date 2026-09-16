# DG-00 MiLAi Logical Architecture 1.0.0 Release Report

> Status: `FROZEN RELEASE PROMOTION`  
> Architecture: `1.0.0 FROZEN`  
> Date: `2026-08-17`（Asia/Shanghai）  
> Schema: `0.1.x EXPERIMENTAL`  
> Runtime implementation: `CANDIDATE`  
> Schema freeze: `NO-GO`

## Outcome

MiLAi Logical Architecture `1.0.0` is promoted from the exact independently accepted candidate.5.
The promotion changes release metadata, gate status, crosswalk paths and the immutable trust chain;
it does not change any G1–G9 goal, I-01–I-12 invariant, object identity, role, transaction, migration,
runtime behavior or residual-risk boundary.

## Accepted candidate identity

```text
candidate manifest  ece90366e5e3e3647af729351d8ae80310c8f6c30db1cf85b5a74ccb4168ed64
candidate archive   aa56033be8380eee9289baec11c7839cbaa9bde4d66f69c6757fd9fb651ff668
candidate receipt   2f8189339b6ee5b45107cee93c67005c1051171810913014631b1bd8c9aed680
independent review  8ddf9e8a302b46404319ef2b27d99403f73b4d71127b4483c3b333d27230d1f3
decision            ACCEPT
findings            AF09-F01 through AF09-F12 CLOSED
```

The independent reviewer verified 175 candidate archive members against live bytes and recorded the
same candidate manifest before and after review. The release source-lock set includes all four
objects above. Candidate.1–4 remain immutable `REVISE` history.

## Independent engineering evidence

```text
architecture candidate validate / external lock / tests        PASS (19)
fresh base -> 0026 exact-role PostgreSQL suite                  PASS (121)
migration foundation                                            PASS (33)
independent F12 three-generation replay                         PASS (12 invalid + 1 control)
exact F11 missing-request and F01 real-consumer replay          PASS
backup/security/catalog/RLS                                     PASS (6; 32 / 31 tables)
runtime Ruff / strict mypy                                      PASS (105 / 57 files)
research isolation                                               PASS (7 source / 9 / 40 fixtures)
double package build / locked install                           PASS (63 / 120 entries)
CI YAML / Compose / documentation                               PASS
```

The reviewer found no open P0, P1 or P2. Synthetic-only, plaintext Blob, local-root, remote/public,
real-personal-data, target-device SLO and Schema 0.1 boundaries remain explicit. Logical architecture
freeze does not approve those separate gates.

## Promotion controls

The release:

1. lives in a new `architecture/v1.0/` directory and does not edit candidate.5;
2. requires `status=FROZEN`, `freeze_status=LOGICAL_ARCHITECTURE_FROZEN` and exact AF-09
   acceptance metadata;
3. converts AF-00–AF-08 to `PASS_FROZEN` and AF-09 to
   `ACCEPTED_INDEPENDENT_REVIEW`;
4. retains the Schema experimental/no-go and runtime candidate banners;
5. rejects missing/forged acceptance, source/Git drift, unsafe paths, omitted locks and coordinated
   bundle+manifest substitution;
6. requires an external release-manifest digest in release verification mode;
7. is packaged twice with fixed metadata and compared byte-for-byte; its final manifest/archive
   identities are recorded only in a bundle-external release receipt.

## Change control

After the external release receipt is issued, `architecture/v1.0/`, its manifest, locked source
snapshot and deterministic archive are immutable. A normative change requires a new architecture
version, explicit compatibility/migration policy, new candidate evidence and independent review.
Status-only project tracking and external audit records must not rewrite this release.
