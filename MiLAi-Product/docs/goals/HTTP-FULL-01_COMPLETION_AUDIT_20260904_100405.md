# HTTP-FULL-01 completion audit

> Timestamp: `2026-09-04T10:04:05+08:00`  
> Disposition: `PASS_LOCAL_CANDIDATE`  
> Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Outcome

The local Codex route now exposes one authenticated Streamable HTTP endpoint at
`127.0.0.1:7337/mcp` with the exact eleven-tool `codex-full` lifecycle catalog. One inbound
`MILAI_CODEX_TOKEN` binds one principal and exactly one project. Server-side reader, submitter,
reviewer and operator credentials are routed by tool and are never model arguments or results.

The same Codex Host can drive Capture → Proposal → Review → exact read → Revoke → deletion status
and project cleanup. Every mutation emits a structured audit log and result summary containing
`SINGLE_HOST_FULL_CONTROL`, `independent_host_review=false`, inbound principal and scope digest.

## Governance disposition

The initial requested design suggested making Proposal creator and Reviewer the same canonical
actor. The frozen architecture and migration 0032 explicitly reject that condition at the sole
canonical procedure. The implementation satisfies the one-endpoint/one-Codex control requirement
without weakening that boundary: the inbound Host is singular, while calls use separate role-bound
Runtime actors. The audit explicitly states that this is not independent-Host review.

No Runtime schema, migration, REST contract, Claim procedure, Evidence lifecycle or revocation
semantics changed.

## Acceptance evidence

```text
MCP package tests                         74 PASS
real child-process MCP transport          PASS
synthetic HTTP Runtime role routing       PASS
unauthenticated /mcp                      401 PASS
exact eleven-tool catalog                 PASS
resolve / exact get                       PASS
capture / proposal / review               PASS
revoke then no Host-visible Evidence      PASS
deletion status / cleanup status          PASS
cleanup project argument absent           PASS
cross-scope cleanup Runtime requests      0
same operation + same payload             replay PASS
same operation + changed payload          conflict PASS
Ruff src + tests                          PASS
strict mypy                               7 source files PASS
wheel + sdist                             PASS
clean-wheel install/entrypoint/import     PASS
Runtime capability/CLI tests              14 PASS
git diff --check                          PASS
```

Final clean installation used an isolated uv environment at
`/tmp/milai-codex-full-release.lqrycS`. The first two clean-install attempts failed before package
installation because the host has no `python` command and system `python3` lacks `ensurepip`; using
the repository-standard `uv` environment resolved the infrastructure issue.

The real local Runtime was not started because its `.env` lacks required configuration fields. No
user data, namespace cleanup or destructive live operation was executed. The child-process MCP test
used a synthetic HTTP Runtime; existing Runtime capability tests passed independently.

## Source identities

```text
server.py                    5ed36daba80782449b86aeea24a74504a93228fab677e7fb6f2b4c1c267fe6e1
http_transport.py            e0a093afe9005e45b2e193ffadaa449c45f87ee0799083460e31c95f839fd99f
codex_full.py                541583de3deb3b173ccac625203b40038c9652048ee8a191898b3b9614db3869
profile test                 bf894365c2626ca0e3db3f62719b1c5bd769b66d84d68e5b7c6cb4212e88696d
HTTP lifecycle test          ba7a2b771e8e4e52f73978af17bf5d3ee31bf55b56dea2436786966d607cf3c6
ADR-033                      b68b23dee569b309bf710190023d55b116bce7d058084595694954fd53723d6d
acceptance contract          794dd55a209e02afc9a5aa60fa56a92dc4cf24ed9a7737edeae45288324a0a46
runbook                      fa2bd217819353b9a7422436f5fdbdfaf332032faff3b5552c5073b13407dada
```

## Product-11 boundary

HTTP-FULL-01 is an independent integration capability. Product-11 X0 remains blocked on two real
human submissions; persisted-frontier continuation, explicit acquisition treatment and Formal 500
remain unentered. `agent-memory` retains its two-argument read schema for Product-11 experiments.
