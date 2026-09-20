# MiLAi Provider + OpenWorker MCP Agent runbook

Status: `0.1 CANDIDATE / SYNTHETIC OR DE-IDENTIFIED ONLY`  
Runtime: `0.1.x CANDIDATE`  
Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`  
Remote MCP, production, real personal data, and image redistribution: `NOT APPROVED`

This runbook implements DG-10 without changing MiLAi canonical objects, permissions, transactions,
or invariants. Model output and MCP results remain `trust=data-only`; Evidence → Proposal → Decision
→ Canonical Procedure is the only write path.

## 1. Hard stops

Do not continue if any of these is true:

- the Provider/model, total cost, 1,000-request ceiling, data boundary, egress, Host, execution window,
  evidence custodian, or independent reviewer lacks explicit out-of-band approval;
- the Provider cannot export per-request native ID, usage, terminal state/receipt, and billable cost;
- real credentials, Prompt, memory, raw output, upstream bill, normalized bill, capture, or broker token
  would be written into this repository;
- OpenWorker would need a MiLAi token/DSN, host networking, privileged mode, Docker socket, Runtime
  `.env`, host secret directory, PostgreSQL socket, or direct Runtime route;
- Worker/OpenCode source or redistribution permission is unclear and the image would be distributed;
- any byte/hash, socket inode, helper lifetime, request coverage, usage, billing, or receipt state is
  uncertain.

At a hard stop, preserve only a bounded partial receipt outside the repository, terminate charge-
bearing helpers, reconcile incurred cost, rotate the affected credential, and keep `OE-F06 OPEN`.

## 2. Reproduce the local MCP candidate

From the repository root:

```bash
cd integrations/openworker-mcp
./build_local_candidate.sh
cd ../..

PYTHONDONTWRITEBYTECODE=1 runtime/.venv/bin/python \
  scripts/run_dg10_mcp_package_gate.py
PYTHONDONTWRITEBYTECODE=1 runtime/.venv/bin/python \
  scripts/run_dg10_openworker_host_gate.py
```

The wheelhouse builder refuses to overwrite an existing candidate. Re-verification uses the checked-
in wheelhouse and both gate commands. To create a new candidate, first choose a new non-existing
suffix and pass it explicitly:

```bash
PYTHONDONTWRITEBYTECODE=1 runtime/.venv/bin/python \
  scripts/build_dg10_musl_wheelhouse.py \
  --output integrations/openworker-mcp/wheelhouse/<new-candidate-directory>
```

The image
builder accepts only the observed base image ID, `linux/amd64`, a matching local lock tag, and an exact
base-layer prefix. Build networking is disabled.

Current local evidence must say `LOCAL_CANDIDATE_REVIEW_REQUIRED`, never `PASS` or Beta.

## 3. Trusted broker preparation

The broker and MiLAi Runtime run on the same trusted host. The Runtime remains bound to loopback.
For `reader-lite`, create a root-owned, mode-`0700` capability directory outside the repository and
install the exact broker and MCP environment under a locked absolute path. Record hashes, not secret
bytes, in the release evidence.

Required policy values:

```text
profile                 reader-lite
socket                  /run/milai-broker/reader-lite/reader-lite.sock
socket mode             0600
allowed peer UID        0 (current root Worker, no user namespace)
MCP command             /opt/milai-reader/bin/milai-mcp --profile reader-lite
Runtime                 http://127.0.0.1:<port>
Scope                   {"project_ids":["milai"]}
authority               ACTION_SAFE
consistency floor       CANONICAL_REQUIRED
max limit               3
```

Render `integrations/openworker-mcp/policy/reader-lite.example.json` outside the repository. Replace
the executable digest with the exact installed console-script SHA-256. The policy has no token.

Store the reader token in a separate repository-external regular file owned by the broker effective
UID with mode `0400` or `0600`, one UTF-8 line, 32–4,096 characters. Never put the token on the command
line, in the policy, OpenCode config, Skill, image, report, or Worker environment.

Start exactly one broker for this policy:

```bash
/usr/bin/python3 /opt/milai-broker/bin/milai-mcp-broker \
  --policy /etc/milai-broker/reader-lite.json \
  --token-file /run/secrets/milai-reader-token
```

The broker rejects a pre-existing socket. Remove a stale socket only after proving the prior broker is
terminal and resolving its exact path/type/owner. Each connection starts a new exact MCP child with an
environment allowlist; child stderr and MCP bodies are not logged.

Submitter and operator require different broker processes, policy files, capability directories,
socket files, tokens, and Worker policies. Ordinary Workers mount only `reader-lite.sock`.

### 3.1 Product-03 local usability profile

For an explicitly isolated, synthetic/deidentified Product usability run, the trusted Host may select
`OPENWORKER_USABILITY_WIDE_V01`:

```text
reader-lite maximum requested limit       50
Runtime max candidates                    120
Memory Context tokens                     8192
Runtime search ceiling                    2000 ms
model context / answer output             65536 / 2048 tokens
MCP / provider timeout                    10 / 60 seconds
```

This is one Host/MCP deployment profile, not model-controlled request input. It expands work and
presentation capacity only; reader profile, scope, permission, revocation, identity, authority and
consistency remain unchanged. It is a local usability baseline, not the default production profile.

### 3.2 Product-07 parked retrieval candidate

Product-07 did not establish its R3 Evidence-coverage gate. Normal deployments must keep both
Runtime settings false:

```text
MILAI_RETRIEVAL_QUERY_PRESERVING_UNION_ENABLED=false
MILAI_RETRIEVAL_EVIDENCE_SET_SELECTION_ENABLED=false
```

`RecallWorkspace` is query-local and non-persistent, but its default-OFF presence is not a release
claim. Do not enable it through an OpenWorker profile: the frozen R3 comparison reduced complete
EvidenceSets from 10/24 to 8/24 and lost four previously complete cases. It created no database,
Canonical, permission or public MCP state, so disabling the flags and restarting Runtime is the
complete Product-07 behavior rollback.

## 4. Worker creation

The OpenCode MCP template is baked into the derived image at
`/openworker/image/config/opencode.json`. Do not run `opencode mcp add` in a container.

Bind the socket file itself, not its directory:

```text
host:      /run/milai-broker/reader-lite/reader-lite.sock
container: /run/milai-mcp/reader-lite.sock
mode:      read-only bind mount
```

Required container controls:

```text
privileged=false
cap-drop=ALL
security-opt=no-new-privileges:true
network != host
no Docker socket
no Runtime .env or secret directory
no PostgreSQL socket
no additional MiLAi socket
no MILAI_* environment variable
```

The real Worker may join only the Provider Gateway network it already needs. It must not join the
Runtime/PostgreSQL network. Because MiLAi remains loopback-only on the trusted host, bridge addresses
cannot reach it. Document and test the exact production network topology; the local candidate uses
`--network none` and therefore is not real-Provider E2E evidence.

After start, require all of the following:

```text
OpenCode /config returns 200
opencode mcp list reports milai connected
reader-lite catalog is exactly [milai_recall, milai_memory_resolve]
reader-lite milai_recall input is exactly query-only
model-supplied consistency/limit/profile/scope/authority fields fail closed before Runtime access
2026-07-28 server/discover + tools/list pass
2025-11-25 initialize + tools/list pass
rendered MCP config digest matches the approved template rendering
```

For the primary answer path, run the Host adapter in explicit `query-first` mode. Every native user
operation must bind Host instance, task session and task operation identities, then perform exactly
one fresh `milai_memory_resolve` over the same UDS broker before calling the provider. A continuation
may carry only an opaque capsule locator; it still reauthorizes and resolves online. Remove MiLAi
Memory tools from the provider payload. If the Memory result is `NO_MEMORY`, `UNCERTAIN`, transport
unavailable or otherwise insufficient for a memory-required operation, return the typed Host outcome
and prohibit provider execution.

Bind the Host adapter to one explicit loopback or private IP literal. Wildcard addresses, hostnames,
multicast addresses, and public/routable literals are rejected by the executable. For container
ingress, deployment remains responsible for proving that the exact private address belongs to the
run-owned isolated Docker bridge; do not use host networking. Plain HTTP is allowed only on that
deployment-approved local interface.

The ingress Bearer is immutable for the adapter process lifetime. To rotate or revoke it, stop the
old adapter, replace the mode-`0400`/`0600` token file, and start a new adapter. File replacement while
the old process remains live is not an online revocation operation.

For Product-05 exchange persistence, start an additional trusted-host broker with the exact
`submitter` profile and pass its socket to the Host as `--submitter-socket`, together with a
Host-selected `--memory-subject-id` and explicit `--memory-data-classification`. The submitter socket
must differ from the reader socket and must never be mounted into OpenWorker. The task-metadata
plugin supplies exact native user/assistant message identity; settlement occurs only after a
complete Provider answer and captures the original turns, not injected Context or system content.
Assistant captures retain their recalled support lineage. Omitting both settlement options restores
the read-only Host without deleting existing Evidence.

Keep `--evidence-use-mode direct`, the default and Product-05 selected Reader. The `inventory`,
`grounded`, and `ledger` choices are default-OFF experimental diagnostics that failed the
pre-registered Product-05 effect gate. Host validation of their aliases/schema/arithmetic is not a
truth, completeness, typed-operand, Requirement `COMPLETE`, or Canonical-state certification.

## 5. Credential and route adversary check

From inside the Worker, inspect environment, rendered config, `/proc/*/{cmdline,environ}`, readable
Skill/workspace files, OpenCode debug/config responses, logs, and crash outputs. The result must contain
no MiLAi token, token variable, Runtime URL, PostgreSQL DSN, Provider adapter credential, or secret
file path. Do not copy raw scan output into the report; retain only bounded counts/status and digest.

Attempt direct Runtime loopback, host bridge, and PostgreSQL routes. All must fail. Confirm container
inspection shows only the one read-only socket bind and no forbidden mount/capability/network setting.

A Prompt asking the Agent to run env, bash, `/proc`, log, config, or filesystem extraction does not
change this gate. The Worker is expected to obey arbitrary bash; security comes from the absence of
secrets/routes and the one pinned filesystem capability.

## 6. Restart, recreate, broker failure, and recovery

1. Record rendered config, OpenCode binary, relay, image, policy, catalog, and Host policy digests.
2. Restart the same container. Require a new start time, matching config digest, matching catalog, and
   MCP connected.
3. Remove and recreate it from the exact image and socket mount. Require the same results.
4. Stop the broker. New MCP discovery/calls must fail; they must not switch transport/profile.
5. Starting a new broker creates a new socket inode. Recreate the Worker to mount that new exact file;
   an existing Worker pinned to the old inode must not silently follow the replacement.
6. Require discovery and policy to recover only after this explicit remount/recreate.

The Product-03 local run observed exactly this behavior: the old Worker remained pinned to the old
socket inode and failed closed after broker replacement; the first send after explicit recreate was
a transient typed send failure, and subsequent discovery plus native operations recovered. Preserve
that first failure rather than hiding it, and require a successful explicit retry before declaring
recovery.

Socket symlink, replacement, permission widening, executable drift, profile substitution, remote base
URL, empty ACTION_SAFE Scope, weaker consistency, unexpected policy fields, token-file widening, and
broker overload must fail closed.

## 7. Real Provider authorization and capture

Complete `docs/reports/DG-10-provider-target-2026-08-20.md`, then obtain an out-of-band approval whose
SHA-256 binds every field. This document and repository do not grant network or spending authority.

Only after approval:

1. implement the chosen real adapter against `PROVIDER_ADAPTER_CONTRACT.md` v3;
2. freeze runtime/source/dependency/host locks, pricing, manifest, approval, and deterministic plan;
3. independently verify namespace/Landlock/static-IP/helper/FD/path closure;
4. reserve target-tokenizer and worst-case cost before each call;
5. alternate the frozen baseline/optimized workload for exactly 1,000 native requests;
6. stop adapter and every helper before final FD/path/hash evidence;
7. keep capture, native receipt material, upstream bill, normalized bill, and reconciliation outside
   the repository;
8. store only sidecar SHA-256/size/time/classification/location-category and redacted aggregate report;
9. reconcile exact native request-ID coverage, usage, price, and cost within approved tolerance ≤1%;
10. independently review all Provider, Agent, MCP, OpenIssue, revocation, failure, and rollback evidence.

Do not retry a charge-bearing failure automatically. A partial run cannot enter the 1,000-call sample
and cannot produce a complete/reconciled status.

## 8. Disable and rollback

Perform in this order:

1. set both Product-07 retrieval flags above to false and restart Runtime;
2. verify the Runtime settings summary reports both flags false;
3. disable `mcp.milai` in the next controlled image/config;
4. remove/recreate the Worker without the reader socket mount;
5. verify `opencode mcp list` contains no MiLAi entry;
6. stop the exact broker and verify it is terminal;
7. revoke the exact reader token and verify subsequent Runtime authentication fails;
8. roll the Worker back to the locked base/no-MiLAi image;
9. restart/recreate again and confirm MiLAi remains absent;
10. reconcile any partial Provider cost outside the repository.

Rollback removes Agent capability only. It does not mutate or roll back Evidence, ClaimVersion,
ClaimHead, OpenIssue, StewardDecision, deletion state, or retrieval traces. The fallback is a no-memory
Agent, never stale Context or a broader profile.
