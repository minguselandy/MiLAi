# MCP 0.1.15 / V02-09 final acceptance

Status: COMPLETED_COMPACT_MCP_USABLE (protocol/product integration scope).
This closes C0–C5, not model-selection quality, autonomous recall, long-term benefit,
OAuth-provider conformance or Schema freeze. Historical pending statements in earlier
receipts are superseded by this audit, not evidence of additional current work.

## Supplied client evidence

User supplied `docs/goals/milai-realistic-audit.zip` (15 entries), SHA-256:
`0b334156dc1b5d45c6c35d056c1890a3299d605a7db9a8dd9c809eb7895222b8`.
All 13 manifest-covered files match their declared bytes and hashes. README and manifest
are the remaining two entries. The original user archive is preserved, not modified or
committed as a Product artifact. Independent verification code/results reside in
`MiLAi-Lab/artifacts/v0209-realistic-audit-0b334156/`.

The main agent and user-authorized independent `realistic_receipt_audit` both recomputed
all 12 assertions from raw requests, responses, plans, sessions and scenario bodies.
All passed. The eight response text objects match structuredContent exactly; no MCP
call reports an error. Exported tool definitions match all eight release tools in full.

| Session | Client PID | Calls and verified result |
| --- | ---: | --- |
| A / `01a0811d-38f8-7820-9dd8-fd358acd40f6` | 14040 | Save synthetic project; COMMITTED, durable=true, ACTIVE v1 |
| B / `01a0811d-c4ae-72c2-ac30-eb73abd5ed3a` | 32012 | Question/project literal only; search reference → exact original v1 |
| C / `01a0811e-a843-7af2-8b59-308a23d5a511` | 13092 | expected_version=1 → v2; same-operation durable receipt; exact historical v1 |
| D / `01a0811f-65a2-7ba0-833d-b498603fbf3d` | 30228 | Fresh question/project literal only; search reference → exact updated v2 |

B/D inputs contain no Note ID, old content or cursor. Their read arguments equal the
preceding returned typed reference, not an externally supplied ID. Session/PID records
are client provenance, not server-issued transport session IDs or process-lifecycle
attestations. The eight calls occur in order (1+2+3+2) and agree with the plans.

Note `01196ccf-2c95-48f9-8ef2-fea028db06a5` remains ACTIVE in the final receipt.
Initial text digest: `sha256:885d20f34ee40a25f7356d8155f35c97063eb38e3d9a03af2033eb1bfb638303`.
Updated text digest: `sha256:9c9cf12eb774caadc53e4b980f5a3c84bcb5d3fcdc29a155e48830dadf547897`.
Both were recomputed from exact UTF-8 bodies. Updated progress/deadline/next action are
preserved, as is the undecided English edition. All content is synthetic, not user fact.
Both this Note and the previously retained cross-session test Note were left untouched.

## Association with the deployed endpoint

The archive contains no URL or transport/initialize metadata and is unsigned. It alone
does not authenticate a server endpoint. The association with OAuth 7960 combines the
user's prior explicit endpoint statement and matching client catalog with separately
inspected server state/logs:

- `milai-aigcit.service` is active/running, PID 3839065, NRestarts=0, using the pinned
  0.1.15 venv and `--catalog compact-memory-v1`; existing deployment metadata binds it
  to `https://milai.aigcit.com:7960/mcp` through backend 7969.
- Its journal window 2026-09-08 21:02:40–21:05:40 Asia/Shanghai contains exactly eight
  compact outer save/search/read/status authorization events, in the same order as the client
  receipts, all allowed, for the same principal and OAuth client, under PID 3839065.
  There are also ten internal delegated-tool authorizations (18 total), not eight total
  server authorization events. These are existing internal handlers, not extra public tools.
- Each client timestamp follows the corresponding server event by 1.542–1.723 seconds.
  This is a time/order/identity correlation, not a latency benchmark, exact Runtime
  request-ID match or cryptographic per-response proof. A bounded API journal search
  did not yield the response request IDs. No token or new identity was obtained.

`service-correlation.json` records only the scoped correlation, omitting principal and
client identifiers. This combined evidence supports target-connection protocol acceptance
without claiming the ZIP independently proves the transport or replaying business writes.
The independent reviewer also reread this exact journal window in UTC and reproduced all
eight correlations, including timestamps, delays and the same-principal/client check.

## Completion audit against the original Goal

The detailed [deployment matrix](MCP_0.1.15_OAUTH_DEPLOYMENT_20260908.md) retains the
engineering evidence and exact earlier commands. Current audit dispositions:

| Requirement | Authoritative evidence inspected | Disposition |
| --- | --- | --- |
| C0 / U01, catalog and metadata | ADR-054, compact contract, generated snapshot, live-protocol snapshot/scope tests, supplied full tool objects | Pass; max 8 vs ordinary 22 and legacy 13; existing scopes retained |
| C1 / U02–U04 | Compact permission/dispatch/default/finite-schema tests and same installed code | Pass; branch reauthorization, old-name denial, Note default, CAS and confirmation requirements |
| C2 / U05, U12 | Compact reference/content-fidelity and search-status tests | Pass; typed Note/Evidence/Claim read-through, no user-payload rewrite, independent source statuses and cancellation |
| C3 / U06, U11 | Final installed-package PG test/report; inspected unknown-outcome, cross-catalog replay and competing-update assertions | Pass; no hidden retry, receipt reconciliation, single CAS winner |
| C3 / U07, U08, U10 | Final PG fresh-client/restart/identity/checkpoint assertions and report | Pass; exact cold read, scope-specific recovery, foreign denial, restart persistence |
| C3 / U09, U12 | Final PG deletion/revocation/dependent-read/cursor assertions and report | Pass; fail-closed historical reads and current identity/filter gates, honest physical-deletion stages |
| C4 / U13 local | Final archive hash and all 48 installed delivery manifest checks; current source and two installs match wheel; full suite/static gates | Pass; same package and no source drift |
| C5 / U13 target | Prior authorization/deployment, full client tool export, independently recomputed 12/12 raw checks and scoped server correlation | Pass; save—cold discover—exact read—update/receipt/history—cold latest read |
| Costs and deliverables | Generated byte measurements, PG request/timing report, ADR/contract/runbook, pinned archive/rollback receipts | Delivered; bytes are not tokens; verification reads are not mandatory product overhead |

Deletion/conflict engineering checks remain required and are covered by the real-PG gate;
they are not claimed as public client tests. Successful update/receipt/history maintenance
meets the target maintenance chain without requiring deletion of retained records.

Final isolated-PG evidence reused: `MiLAi-Lab/artifacts/v0209-75212b48032e6031/`, pytest
1 passed in 10.84s; cleanup receipt confirms only owned temporary resources removed.
No new PG run or public service restart was necessary for this receipt-only audit.

Fresh closeout commands/results (working directory `integrations/mcp`):

- `uv run --locked pytest -q tests/test_compact_memory.py tests/test_compact_catalog_snapshot.py tests/test_memory_search.py`: 40 passed in 4.92s.
- `uv run --locked pytest -q`: 383 passed, 7 conditional skips in 26.71s; skips remain skips.
- `uv run --locked ruff check src tests`: passed.
- `uv run --locked mypy`: passed, 21 source files.

Offline `verify_receipts.py` reproduces 12/12, both body hashes, reference use, session
associations, 13 manifest checks and eight exact tool definitions. `correlate_service.py`
checks the journal correlation. An initial correlation command used the delivery directory
instead of the repository and failed before execution; the corrected invocation passed.

Delivery archive SHA-256 remains
`18344e991596de27c8033b8a5ebb69de235ea98bfee0f0008061900d5fd49b41`;
MCP wheel remains `ee24607e0f365468a7ace818bb66718cc397bfaba33f8d6db22dd7ef2f61ae7b`.
All 21 Python source files match the wheel, source tree, deployed venv and clean-test venv.
The delivered archive and embedded historical docs were not rebuilt or overwritten.

## Unchanged boundaries

No API, Schema, permission, canonical transaction, model budget or deployment change in
this final audit. No memory write/delete, namespace cleanup, credential read or migration.
Rollback remains the pinned 0.1.14 ordinary service switch without data restoration;
syntax was checked previously, live rollback is unrun. No paid/local model pilot ran.
Note matching here is literal and governed retrieval is MISS; autonomous recall, semantic
quality, model decisions and long-term net benefit are not certified. Prior provider
revocation-metadata limitation remains outside this adapter Goal's completion claim.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.
