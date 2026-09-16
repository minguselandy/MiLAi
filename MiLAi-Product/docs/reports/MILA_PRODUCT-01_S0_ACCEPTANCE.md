# MILA-PRODUCT-01 S0 acceptance summary

Status: `PASS`

Date: `2026-09-01`
Scope: isolated synthetic local Product only

| Gate | Result |
| --- | --- |
| Fresh migration | `0049_cleanup_terminal_counts` PASS |
| Real-role RLS/security/concurrency/worker | Runtime full gate: 731 passed, 1 declared optional skip |
| Operations lifecycle | init, doctor (17/17), start, isolated smoke, stop PASS |
| MCP stdio vertical | capture, readiness, query, revoke, post-revoke non-leak PASS |
| OpenWorker UDS vertical | submitter/reader/operator brokers, mode 0600, capture/query/revoke PASS |
| Lease behavior | slow/recoverable lease tests PASS; terminal residue 0; worker fatal exit 0 |
| Restart/replay | same isolated volume retained state; capture replay returned same Evidence ID |
| Isolation cleanup | exact `milai-p01-s0` containers, network, volume, env and blob root removed |
| Production mutation | 0; the pre-existing `milai-ua-runtime-postgres-1` endpoint was not addressed |

General repairs made while closing the gate:

- durable ContextReceipt reuse is preferred for canonical-only resolve outcomes;
- operations smoke uses a relation-specific natural query;
- capable capture adapters preserve structured speaker/source context without inferring ordinals;
- OpenWorker exposes explicit operator revocation and accepts bounded MCP envelope overhead.

No database schema, frozen architecture, remote transport, default experimental feature, or formal
holdout setting changed. Schema remains `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.
