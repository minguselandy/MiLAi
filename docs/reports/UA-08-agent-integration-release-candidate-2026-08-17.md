# UA-08 Agent Integration 0.1 Release Candidate.2

> Date: 2026-08-17  
> Candidate decision: `READY FOR INDEPENDENT RE-REVIEW`  
> Promotion decision: `PENDING`; the author does not self-certify DoD 14.

Candidate.1 received an independent `REVISE` with UA-F01～UA-F05. Candidate.2 closes those exact
findings; the remediation evidence is
`UA-08-candidate.2-security-remediation-evidence-2026-08-17.md`. The first review remains immutable,
and only a new independent record may accept this candidate.

## Exact release boundary

```text
Agent Integration: 0.1 RELEASE CANDIDATE / synthetic or de-identified
Logical Architecture: 1.0.0 FROZEN (unchanged)
Schema: 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
Implementation: CANDIDATE
Real personal data: DENIED
Remote/multi-agent governance: NOT ENABLED
Package publication: DENIED / project license undeclared
```

This candidate supplies a local Agent Integration Plane over the public HTTP contract. Adapters do
not connect to PostgreSQL, import Runtime internals, review proposals or directly mutate canonical
state. Scope, required authority and credentials are host configuration, not model tool arguments.

## Reproducible release gates

| Gate | Result | Durable evidence |
|---|---|---|
| Exact-role fresh PostgreSQL Runtime suite | PASS, `144 passed in 76.30s`; zero connections and database dropped | `UA-runtime-fresh-database-full-gate-2026-08-17.json`, SHA-256 `0d9d5732bf34f5ff1e0c0601e8b1cefd3ae435172a5d278e84e2ee8a5f3efd2f` |
| Three-session cross-adapter E2E | PASS; no hard failures; temporary database dropped | `UA-05-three-session-agent-e2e-2026-08-17.json`, SHA-256 `4ca8bcde322569a7845912663114d61642eecde4e28865e91bfe9e6648448609` |
| Six clean wheel installs | PASS in six fresh temporary virtual environments with isolated imports; all six expose PEP 561 type markers | `UA-package-clean-install-gate-2026-08-17.json`, SHA-256 `3f2bd3cecab9440e1b6dedc4e2933619bf1cf4200150523f368a876eb141ec7e` |
| Package tests | PASS: client 30, MCP 7, LangGraph 4, AutoGen 3, hooks 2 | Package-local pytest, Ruff, format and strict-mypy gates |
| Four executable examples | PASS: generic, MCP client, LangGraph, AutoGen | `examples/*/smoke.py` |
| Target-device retrieval gate | PASS: top-1 `0.5385 → 0.8462`; warm p95 `15.069 ms`; failure `0`; external cost `0` | `all-MiniLM-L6-v2-target-device-result.json`, SHA-256 `f4863156353247f05da06478b480c0656ac058ace55c6b36c204c18ad6e795c2` |
| Secret/content boundary | PASS: archive-aware scan opens 287 members with no matching/forbidden/unsafe member; replacement sdist is 252,401-byte allowlist build | `scripts/scan_ua_secrets.py`, 8 adversarial safety tests and candidate.2 remediation evidence |
| Frozen Logical Architecture | PASS; no release bundle refresh or source-lock substitution | Existing 1.0.0 independent release verification |

The package release manifest binds all six `0.1.0` wheels/sdists to their independent `uv.lock`
files and records license metadata for every locked package visible on the build platform. Its
SHA-256 is `84c947394f3bcfb2132a9f8cc88dc724ffe69fc0b1dc11693a9fb69d97e3a4ef`.
MiLAi package licenses remain explicitly `UNDECLARED`, so artifacts are local-only.

## Cross-adapter behavior

The same isolated fixture proves:

1. a pending Claim is not recalled as canonical truth; after independent approval and a causal
   token, generic SDK, MCP and LangGraph return the same V1 with independent persisted traces;
2. contradictory Evidence creates a live OpenIssue while Head stays V1; generic ContextCapsule,
   MCP, LangGraph and AutoGen preserve the uncertainty and abstain;
3. independent runtime Evidence permits governed V2, then revoking one grounding Evidence reopens
   the same issue and makes generic SDK, MCP and LangGraph reject stale FTS/vector results before
   physical purge completes.

The MCP legs use both the official high-level stdio Client (`2026-07-28`) and an independent
minimal JSON-RPC host (`2025-11-25`). The proposal inbox/UI jointly exposes pending governance,
Claims, Evidence, OpenIssues, retrieval traces, deletion layers, data mode and secret-free Agent
configuration.

## Security and data decision

Server-side Evidence classification rejects `PERSONAL` while the Runtime is `SYNTHETIC_ONLY`.
AES-256-GCM, rotation, wrong-key/tamper failure, encrypted backup/restore and import dry-run are
implemented, but classification is a trusted host/user assertion rather than automatic PII
detection. User approval and an environment-specific independently accepted recovery/deletion
drill are missing. Therefore SG-01 and `Local Private Beta` remain `NO-GO` without weakening the
synthetic/de-identified Agent Integration candidate.

## Finalization protocol

`scripts/build_ua_inventory.py` produces the canonical current-byte inventory for source,
contracts, tests, configuration, model assets, reports and all package artifacts while excluding
secrets, virtual environments and caches. An independent reviewer must recompute every entry and
the canonical root, replay proportionate gates, inspect the exact design/DoD matrix and report all
open P0/P1 in a new file under `docs/reviews/`. Only an independent PASS permits Beta promotion.

Known non-goals and operational limitations are frozen in
`docs/known-limitations-agent-integration-0.1.md`.
