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
reader-lite catalog is exactly [milai_recall]
reader-lite milai_recall input is exactly query-only
model-supplied consistency/limit/profile/scope/authority fields fail closed before Runtime access
2026-07-28 server/discover + tools/list pass
2025-11-25 initialize + tools/list pass
rendered MCP config digest matches the approved template rendering
```

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

1. disable `mcp.milai` in the next controlled image/config;
2. remove/recreate the Worker without the reader socket mount;
3. verify `opencode mcp list` contains no MiLAi entry;
4. stop the exact broker and verify it is terminal;
5. revoke the exact reader token and verify subsequent Runtime authentication fails;
6. roll the Worker back to the locked base/no-MiLAi image;
7. restart/recreate again and confirm MiLAi remains absent;
8. reconcile any partial Provider cost outside the repository.

Rollback removes Agent capability only. It does not mutate or roll back Evidence, ClaimVersion,
ClaimHead, OpenIssue, StewardDecision, deletion state, or retrieval traces. The fallback is a no-memory
Agent, never stale Context or a broader profile.
