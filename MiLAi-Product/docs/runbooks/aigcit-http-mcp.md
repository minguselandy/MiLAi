# AIGCIT MCP resource server

This is the deployment procedure for ADR-048 and the private-user mode in ADR-049. The public deployment and real-user
login require separate evidence; a successful package build is not a login result.
The existing local OAuth runbook remains valid only for `local-oauth` mode.

Current OAuth 7960 uses MCP 0.1.15 compact-memory-v1: **8 tools / 9 scopes**.
Use [the compact scope profile](../../contracts/mcp/compact-memory-v1.md#deployment-scope-profile).
Client request, enabled scopes, public resource metadata and Auth resource registration
must agree; an old token does not acquire missing scopes through a server restart.
The earlier 13-tool / 8-scope and ordinary 22-tool / 12-scope profiles are historical or
separate catalogs, not the current public client's requested scope set.

Historical MCP 0.1.6 implements [ADR-050](../adr/ADR-050-full-private-mcp-capabilities.md): the complete
13-tool private profile. Its legacy profile required eight scopes. Re-register the exact resource with
Auth after publishing the new scope metadata, then obtain new user consent; existing tokens
retain their original grants. The five-tool pilot restrictions below are historical rollout notes,
not the 0.1.6 capability ceiling. Current deployment evidence is in the
[0.1.6 handoff](../releases/MCP_0.1.6_HANDOFF_20260908.md).

## Prepare the candidate

Build `integrations/python-client` and `integrations/mcp` wheels with `uv build`.
Install them and the versions frozen by the MCP `uv.lock` into a root-owned environment
under `/opt/milai-aigcit/venv`. Record wheel, lock and configuration hashes. Do not run
an editable source tree as the deployed service. Keep the previous install intact.

Create the dedicated unprivileged `milai-mcp` account. `/etc/milai-aigcit` must be
root:milai-mcp 0750; its `bindings.json` must be root:milai-mcp 0640. The account may
read admission but must not change it. Do not relax unrelated files or directories.
The root-owned `mcp.env` is 0600, read by systemd before it changes user. It contains
only the four dedicated Runtime role credentials and this edge configuration, never
database passwords or a production user's OAuth token. Runtime remains loopback.

Use the separate [environment](../../examples/codex-mcp/milai-aigcit.env.example),
[unit](../../examples/codex-mcp/milai-aigcit.service.example) and
[proxy](../../examples/codex-mcp/milai-aigcit-7960.nginx.conf.example) examples. They are
not installed automatically. The private profile advertises ordinary read/write/capture
scopes after isolation gates pass; governance and destructive tools stay closed.

## Login with a private memory namespace

For the login-and-use product, set `MILAI_AIGCIT_ACCESS_MODE=authenticated_private`.
The fixed `MILAI_AGENT_SCOPE_JSON` project is a stable deployment namespace, not a
shared user project. After verification, the service derives the actual private project
and principal from namespace/issuer/sub. Keep the namespace stable across upgrades.
Login does not adopt legacy data or give clients control over project selection.

Use this root-owned policy (project must match the deployment namespace):

```json
{
  "version": 1,
  "issuer": "https://auth.aigcit.com",
  "project_id": "milai",
  "mode": "authenticated_private",
  "owners": [],
  "disabled_subjects": []
}
```

No per-user enrollment or manual sub submission is needed. To locally disable a known
subject, atomically update `disabled_subjects`; requests reread the policy. Mode changes
require matching environment and policy plus a restart. Ordinary read/write/capture
scopes may be enabled after isolation tests; governance stays closed. Use the
[private client example](../../examples/codex-mcp/milai-aigcit-client.toml.example).
Clients with earlier read-only grants need new consent granting the write scopes.

## Optional legacy explicit-owner mode

Set `MILAI_AIGCIT_ACCESS_MODE=explicit_owners` only when this older admission policy is
desired. This manual-owner section does not apply to authenticated_private deployments.

Obtain `sub` from an authenticated trusted operator channel or a verified Auth result.
Do not ask users to paste tokens into chat, decode an unverified token as identity, or
guess from username/client ID. Confirm the intended fixed project. Compute its new
principal with `milai_mcp.auth_policy.principal_for(issuer, sub, project_id)` using the
installed package, then prepare this exact JSON shape:

```json
{
  "version": 1,
  "issuer": "https://auth.aigcit.com",
  "project_id": "APPROVED_PROJECT",
  "owners": [{
    "sub": "VERIFIED_AUTH_SUB",
    "principal_id": "aigcit:COMPUTED_SHA256",
    "allowed_scopes": ["milai.memory.read", "milai.state.read"],
    "enabled": true
  }]
}
```

Validate the candidate file with `AdmissionPolicy.load()` against the same issuer,
project and enabled scopes before atomic replacement. Increment version for audit.
The current file is checked for every protected request and again before tool use.
Missing, unreadable or invalid admission yields dependency failure, with no stale
policy fallback. Disable the owner or narrow allowed scopes to deny new requests on
existing connections. Already committed transactions and already disclosed content
cannot be undone by changing this file.

Only one enabled owner is supported. Old principal IDs are rejected by this format;
this release does not implement legacy owner migration. Historical State remains
untouched. Tokens for other subjects get 403, even if Auth consent succeeded.

## Public rollout

First finish the Goal's P1–P3 and Remote Access Gate. Prepare a trusted domain
certificate and an executable renewal procedure (DNS-01 requires DNS ownership).
Do not install a proxy pointing at nonexistent certificate files. Do not reuse the
cancelled DNS challenge, stop shared listeners, or expose the candidate as anonymous
HTTP. Stage on an isolated loopback port; switch 7968 only in a controlled window.

Before registration, verify DNS and TLS from an independent client network, public
metadata and the 401 challenge. Then register the exact MiLAi resource with Auth and
retain the sanitized response and separate status result. Neither same-machine
loopback nor a status lookup proves Auth can fetch the metadata on port 7960.

Check `nginx -V` and syntax against the selected installation before rollout. The
system binary inspected on 2026-09-07 was built with `--without-http_limit_req_module`;
it cannot load this template. The template passed isolated syntax checking using an
existing Nginx container image with that module. This does not replace the system
binary or verify production TLS. Deploy a reviewed installation with the required
module; do not remove rate limiting to make a configuration test pass.

After registration the credential-free packaged check is:

```bash
milai-oauth-readiness --base-url https://milai.aigcit.com:7960 \
  --external-issuer https://auth.aigcit.com
```

It checks the independent AS endpoints/JWKS and active exact resource/scopes. It
does not register clients, issue tokens, call authenticated tools or prove login.
Only then have the real user add a separate client entry and approve Auth in their
own browser. Keep test and real connections distinct. Verify read-only use, refresh
and refresh replay after the documented grace window with a dedicated test client.
Do not revoke a real user's connection as test cleanup. Real State save/exit/resume
and final user acceptance are still required to complete the pilot.

### Codex resource parameter

An early user login attempt returned `invalid_target` because `resource` was missing;
the historical workaround was an explicit `oauth_resource`. On 2026-09-08, actual
Codex 0.153.0 authorization-URL checks against the public service showed that metadata
discovery supplies the correct resource automatically, and the explicit setting adds
the same resource a second time. Remove that setting from the current client entry.
Keep Auth audience checks unchanged.
In the user's existing server entry (use its actual name; do not duplicate a TOML table):

```toml
[mcp_servers.milai]
url = "https://milai.aigcit.com:7960/mcp"
scopes = ["milai.memory.read", "milai.state.read", "milai.state.write", "milai.evidence.capture", "milai.evidence.revoke", "milai.note.read", "milai.note.write", "milai.note.delete", "milai.evidence.read"]
```

Cancel the failed local login attempt, then run on the client machine:

```bash
codex mcp login milai --oauth-client-registration dcr \
  --scopes milai.memory.read,milai.state.read,milai.state.write,milai.evidence.capture,milai.evidence.revoke,milai.note.read,milai.note.write,milai.note.delete,milai.evidence.read
```

For a new entry, omit `--oauth-resource`; use the MCP URL and DCR registration.
The explicit resource setting is optional in the
[official OpenAI configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
The two local URL-generation checks produced two identical `resource` parameters with
the explicit setting, and one exact parameter without it. They stopped before browser
login or token exchange; they do not establish completed authentication on the user's client.
Open the newly generated URL, not the old state/PKCE request. Verify its `resource`
decodes to the exact HTTPS MCP URL (including port and `/mcp`). Changing only the
browser URL does not establish correct token-exchange or refresh behavior.
The user has reported external login working. That report does not establish refresh,
replay or revocation behavior, or a private-mode State save/resume receipt.

### Remaining real-client acceptance

Use a dedicated test connection for refresh/replay/revocation, as required by Goal
A20–A22. The normal user's working connection must not be revoked by test cleanup.
Retain only sanitized receipts: operation/version IDs, observed status, granted scope
names and timestamps. Keep tokens, codes, cookies and memory contents out of reports.

For private State continuity, read the current TASK State, preserve its existing
payload, and use the returned version for CAS when saving a non-sensitive test marker.
Record the save receipt, end the client process, then use a fresh process with the same
account to read TASK State. Compare the recovered marker and version with the receipt;
do not count a local file read as server recovery. If restoring the original payload,
first read the current version and preserve intervening user changes.

As of the latest check on 2026-09-07, Auth discovery still omits
`revocation_endpoint_auth_methods_supported`. A `none` entry on the token endpoint
does not resolve this separate endpoint contract. Keep the strict readiness result
unresolved until authoritative endpoint support and the dedicated-client test supply
the required evidence; do not weaken the checker or substitute fixture JWTs.

## Faults, audit and rollback

Warm JWKS verification has no Auth network call. The cache expires after 600 seconds;
refreshes have a shared 30-second cooldown, 3-second total deadline and 256 KiB bounds.
Expired keys with failed refresh return 503, not anonymous access. A valid warm key
may remain usable during an unrelated refresh failure until its deadline. Auth token
revocation is not advertised as instantaneous; local admission is independently checked.

The `milai_mcp.auth` logger records only tool authorization metadata and the hashed
Runtime operation ID. An `allowed` record means the request passed the entrance gate,
not that Runtime committed. Inspect public operation receipts separately. Never log
Bearer tokens, authorization codes, refresh tokens, cookies, memory bodies or raw query
strings. Limit access and retention for service logs and admission backups.

Record the exact previous unit/drop-ins/proxy/package/config hashes before switching.
Rollback disables the candidate listener and restores those files and the prior
protected service. Preserve data, operation receipts, old OAuth databases and audit;
never roll back user writes or reactivate revoked secrets. Only owner-authorized Auth
administration can disable a registered resource. No schema migration is required.

Schema remains **0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE**.
