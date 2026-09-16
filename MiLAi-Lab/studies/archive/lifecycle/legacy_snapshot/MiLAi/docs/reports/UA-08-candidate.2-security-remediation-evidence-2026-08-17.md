# UA-08 Candidate.2 Independent-Review Remediation Evidence

> Date: 2026-08-17  
> Boundary: Agent Integration `0.1 candidate.2`, synthetic/de-identified only  
> Author decision: `READY FOR INDEPENDENT RE-REVIEW`  
> First independent review: `REVISE`, UA-F01～UA-F05 open  
> Promotion: still `PENDING`; only a new independent PASS can promote the candidate

This record closes the exact findings in
`docs/reviews/MiLAi-Agent-Integration-0.1-independent-review-2026-08-17.md`. It does not alter the
frozen Logical Architecture, enable real personal data, approve remote transport or claim Schema
freeze/Production readiness.

## UA-F01 — exposed Runtime sdist (P0)

The unsafe `332,884,607`-byte Runtime sdist was deleted. It is not retained as a backup or release
artifact. Because it contained a byte-exact live `.env`, every embedded credential was treated as
exposed, even though the package was local:

- all five PostgreSQL role passwords (`milai_owner/api/steward/worker/audit`) were replaced;
- API token, causal signing secret and the four Agent capability tokens were replaced;
- the tenant Blob KEK and key reference were rotated while the Runtime was stopped;
- the replacement `.env` was atomically written with mode `0600`; no old `.env` backup remains;
- all five new database credentials connected as their exact role and every old password was
  rejected on a new connection;
- after restart, the captured old reader token returned HTTP `401` and the new reader token returned
  HTTP `200`;
- the rotation command emitted only status/role names and no secret values. A failed first SQL
  syntax probe rolled back the database transaction, `.env` and Blob key before the corrected
  parameter-safe operation was rerun.

`milai-ops rotate-local-credentials --confirm ROTATE_EXPOSED_LOCAL_CREDENTIALS` is now a tested,
reusable stop-the-world remediation command. Its failure path restores the original file and reverses
Blob re-encryption; it refuses a live Runtime, non-0600/symlink env, wrong role, non-loopback DSN,
missing field or wrong confirmation.

The replacement Runtime sdist is allowlist-built:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `runtime/dist/milai_runtime-0.1.0.tar.gz` | 252,401 | `8794145a8dc2808d69c838dce84f7f78bbdc0662daa686d4a2bf29d8be839e37` |
| `runtime/dist/milai_runtime-0.1.0-py3-none-any.whl` | 121,670 | `8c41e1b5333adf711bbf85dca81eedc43508d8d1dbf69e51ab31596129c02242` |

The sdist has 131 regular file members. `.env.example` is the only environment template; live
`.env`, `var/`, backups, logs, caches, smoke reports, Blob bytes and nested `dist/` are absent.
`scripts/scan_ua_secrets.py` now opens zip/wheel/tar/tar.gz members recursively with path/link,
member-count, member-size, total-uncompressed-size and nesting limits. The final pre-inventory run
scanned 323 current files plus 287 decompressed members and found zero exact-secret match, forbidden
member or unsafe archive. Eight adversarial release-safety tests include nested compressed secrets,
`.env`, cache, symlink and missing inventory target failures.

## UA-F02 — incomplete/cache-bearing inventory (P1)

`scripts/build_ua_inventory.py` now includes root `.gitignore`, root release tests and
`runtime/docker/`, including `runtime/docker/initdb/010_roles.sh`. It includes both
`runtime/.env.example` and `.python-version`, rejects missing named roots and any source symlink, and
excludes `.cache`, virtualenv, pytest/mypy/Ruff caches and `__pycache__` at every nesting level.
Executable negatives prove missing roots, nested cache and symlink fail closed. The final inventory
is generated only after all source, reports and rebuilt artifacts are stable.

## UA-F03 — checked-in CI did not match a clean current tree (P1)

`.github/workflows/ci.yml` now uses the intended Runtime static scope (`src tests migrations`) instead
of scanning generated model/cache directories. It runs the frozen `architecture/v1.0` bundle in
release mode with external manifest anchor
`ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e`, the 19 adversarial bundle
tests, a five-package Agent integration matrix, allowlisted Runtime builds, root release-safety tests
and the archive-aware secret scanner. Local execution of the exact package/static commands passes.

## UA-F04 — model-controlled framework recall policy (P1)

`AgentRecallPolicy` freezes a canonical JSON copy of host Scope plus authority, consistency floor and
maximum limit. The generic tool set, LangGraph recall node, AutoGen Memory adapter and MCP server all
receive this policy at construction time. LangGraph state and AutoGen kwargs that contain policy
override keys are rejected before a client call; MCP has no Scope/authority tool arguments, cannot
weaken consistency and clamps limit to the host maximum. Tests mutate both the original nested Scope
and a returned copy, inject all framework override keys, and request EVENTUAL/20 against a
CANONICAL_REQUIRED/5 host policy; the HTTP client sees only the frozen host values.

## UA-F05 — ProposalDraft validation bypass (P1)

Raw model/framework/tool proposal dictionaries now pass `ProposalDraft.model_validate()` before any
proposal POST in AgentMemory, generic tools, LangGraph, MCP and the E2E adapter. The strict schema
requires model/template identity, lowercase input snapshot SHA-256, Evidence branches, Scope,
authority, operation-specific target/expected head and canonical patch fields. A locally known
current head is read before update submission and `validate_current_head()` rejects a stale expected
version before the proposal POST; the server CAS remains the final TOCTOU authority.

Negatives cover missing/empty model or template, malformed snapshot hash, Evidence branch overlap,
authority mismatch, missing head, known stale head and arbitrary raw dicts with zero proposal client
calls. Repeating a valid typed tool request produces identical operation ID and canonical API body.
MCP exposes the same strict nested schema and validates it before invoking the proposal client.

## Regression gates after remediation

| Gate | Result | Durable evidence |
|---|---|---|
| Fresh exact-role PostgreSQL Runtime | `144 passed in 76.30s`; zero connections, test DB dropped | `UA-runtime-fresh-database-full-gate-2026-08-17.json`, SHA-256 `0d9d5732bf34f5ff1e0c0601e8b1cefd3ae435172a5d278e84e2ee8a5f3efd2f` |
| Package tests | client 30, MCP 7, LangGraph 4, AutoGen 3, hooks 2 | package-local Ruff/format/mypy/pytest |
| Three-session cross-adapter E2E | three phases PASS, no hard failure, cleanup PASS | `UA-05-three-session-agent-e2e-2026-08-17.json`, SHA-256 `4ca8bcde322569a7845912663114d61642eecde4e28865e91bfe9e6648448609` |
| Six fresh wheel installs | PASS, isolated imports, six PEP 561 markers | `UA-package-clean-install-gate-2026-08-17.json`, SHA-256 `3f2bd3cecab9440e1b6dedc4e2933619bf1cf4200150523f368a876eb141ec7e` |
| Package release manifest | six wheel+sdist pairs and independent locks | `integrations/package-release-manifest.json`, SHA-256 `84c947394f3bcfb2132a9f8cc88dc724ffe69fc0b1dc11693a9fb69d97e3a4ef` |
| Release safety | 8 adversarial tests + archive-aware exact-secret scan | PASS, zero match/forbidden/unsafe |

There is no Schema migration or canonical procedure change in this remediation. Public candidate
adapter constructors now require an explicit host recall policy; model-generated proposal paths are
stricter. Runtime remains `0.1.x CANDIDATE`, Schema remains `0.1.x EXPERIMENTAL / NO-GO`, real data
remains denied, and Local Private/Remote/multi-agent governance remain NO-GO.
