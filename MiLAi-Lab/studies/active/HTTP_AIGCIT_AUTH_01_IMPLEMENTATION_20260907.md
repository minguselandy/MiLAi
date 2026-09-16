# HTTP-AIGCIT-AUTH-01 implementation checkpoint

Status: **IMPLEMENTED_CANDIDATE / P4–P6 NOT COMPLETED**. The active Goal remains the
complete AIGCIT authentication pilot. The earlier MILA-V02 memory/model experiments
remain paused. This increment used zero model requests and made no Auth registration,
user login, credential issuance/revocation, DNS or shared-service deployment changes.

## Implementation

Product ADR-048 records the new identity/permission boundary. New `aigcit_auth.py`
implements ES256 `at+jwt` verification, trusted discovery/JWKS, bounded asynchronous
refresh and safe dependency errors. `auth_policy.py` implements one admitted owner,
derived stable principal, root-owned current policy and explicit mappings for all
13 existing tools. Effective capabilities intersect JWT scopes, current owner policy,
enabled deployment scopes and existing Runtime authorization. Only the five ordinary
memory/state/capture tools can be enabled; initial configuration advertises reads.

`HttpResourceBinding` has no static secret/default user. Explicit modes reject mixed
AIGCIT/legacy/local-OAuth configuration. Server wiring retains the SDK and old modes,
filters tool lists per request, rejects direct unauthorized calls before handlers,
rechecks policy and preserves ContextVar isolation. Public Host/Origin protection is
independent of the local AS. AIGCIT installs no local login/register/token routes.
External preflight checks the independent AS, JWKS and active exact resource/scopes.
Safe authorization audit includes a generated request ID and hashed Runtime operation
ID; the existing mutation audit also hashes external-mode operation IDs.

No Runtime/Canonical schema or migration changed. Legacy principal rebinding is
explicitly unsupported by the initial admission format; old memory is untouched.
Schema remains **0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE**.

## Authoritative evidence

Root: `artifacts/http-aigcit-auth-01/` (untracked execution artifacts).

| Evidence | Result and limits |
|---|---|
| `p0-20260907/` | Source hashes and fetched public Auth docs/discovery/status. Baseline tree `cb3edf1226376d5fcb17074f6322fa9b5ed4df3e10e1c10184f7b3abc03c167a`; candidate resource remained unknown/inactive |
| `mcp-regression-final-tls.log` | `uv run --frozen pytest -q`: **258 passed, 3 skipped, 18.21s**. The skipped cases are opt-in PG (2) and calibration (1), executed separately below |
| Local package gates | `uv lock --check`; `uv run --frozen ruff check src tests`; `uv run --frozen mypy` (14 source files); `uv build` all passed |
| `p3-pg-20260907d/` | Explicit `MILAI_MCP_BASELINE_E2E=1`: external-auth lifecycle and existing legacy lifecycle **2 passed, 17.19s**, real isolated PG/API, all owned services terminal |
| PG external lifecycle | Real capture and qualified source refs, save/replay, three separate processes (save/resume/foreign), same owner across new client/key/token, correct cold State, one CAS winner, local disable ->403, cross-project State ID/Evidence refs rejected despite forged JWT tenant/project/role |
| PG response-loss case | The test discarded a successful public Runtime response and injected unavailability at the client boundary. MCP reported UNKNOWN with exactly one attempt. A later legal write made head V2; a new process's explicit idempotent replay confirmed original operation V1. Current head and operation confirmation are separate. This is fault injection after a real commit, not a real WAN packet-loss measurement |
| `package-check.json`, `current-package-pin.json` | Locked dependency install; root-owned wheels. Final MCP wheel `847059d5d44c169c9f99ea775d668379003020d6c4c7e4b8e9cb46d8ac519842`, all 14 packaged Python sources match current source. Current code pin `c8871ce36d24f515dfe20e6647a256f8cc873a13ce4f8bcc772d4665e0f8a354` |
| `installed-service-check.json` | Two actual MCP process starts as UID 65534 from installed wheel, no `/root` interpreter/package dependency. Health/metadata200, unauthenticated401, unavailable Runtime503; both PIDs terminal. Role-credential canaries absent from logs. This check intentionally had no live Runtime success or real user token |
| Non-root policy check | UID65534 can read root:65534 policy0640 in dedicated0750 directory but cannot write file/directory/package. No global directory permissions changed |
| `auth-calibration.log` | 260 local signed-fixture verifications, no warm Auth requests/timeouts. Single P50/P95/P99 **0.343/0.458/0.604ms**; 8-concurrent **1.840/3.026/3.416ms**. Calibration only, not capacity/SLO/user-login proof |
| `cold-jwks.json` | Real HTTPS Auth discovery+JWKS, **203.6ms**, 2 non-mutating requests. Does not validate a real user's token |
| TLS negative test | A real local HTTPS listener with an untrusted test certificate was rejected before any HTTP GET reached it; no verification bypass |
| `template-check/` | System Nginx lacks `http_limit_req_module`; failure preserved. Staged proxy syntax passed using existing image `sha256:a2919d0de38b585fe0ac16cf3dd9a4cf6b1c0c00b170328fb1bbd2c9020fba1c`. Temporary self-signed fixture was syntax-only; no listener or public TLS claim |
| Lab gates | Boundary passed; **417 tests passed, 3.90s**; Ruff, mypy (30 files) and build passed. No active Lab source changes |

The code pin is an implementation/install pin, not a new model-effect experiment
lock. Historical pins and memory experiment outcomes remain unchanged.

## Corrections retained

- Modern SDK HTTP fixtures initially used legacy handshake assumptions, then omitted
  the current request envelope/method header; corrected according to installed SDK.
  Both supported paths now have direct session/admission tests.
- The first added PG source-read fixture incorrectly supplied `evidence_id` to the
  canonical `milai_memory_get` tool. Product correctly rejected the argument. The
  test now verifies actual public capture and Working State source-reference
  qualification, including cross-project rejection; no new tool or case routing.
  The failed `p3-pg-20260907b` result remains separate from successful a/c/d runs.
- System Python3.10 cannot install this Python>=3.11 package. The installed-process
  check uses a dedicated standalone3.11 prefix; no `/root` permissions were relaxed.
- System Nginx's missing module was not bypassed by deleting rate limiting. The first
  isolated container syntax attempt also lacked CHOWN for its temporary cache setup;
  a corrected syntax-only invocation passed, with both results preserved.

## Completion audit and remaining gates

| Goal items | Evidence boundary / remaining work |
|---|---|
| A01–A04 | Local signed-token/HTTP negatives cover authentication/header/claims. Real AIGCIT token type/sample belongs to P5 |
| A05–A07 | Local admission/scope/directory/direct-call/CLI tests; a real unadmitted Auth test subject still belongs to P5 |
| A08–A09 | Concurrent task/thread/error/cancel ContextVars and both SDK HTTP admission/session paths verified locally; real long-lived user connection remains pilot evidence |
| A10–A13 | Real PG cold identity/replay/CAS, wrong-owner mapping rejection, cross-project refs and injected unknown outcome verified; no old-owner migration was authorized or performed |
| A14–A17 | Disable/narrow/corrupt/missing policy, key rotation/deletion/flood/deadline/cancel, untrusted TLS/redirect/oversize and exact Host/Origin covered locally |
| A18 | External preflight implementation verified; public candidate has no cert and is not registered, so actual external preflight NOT PASSED |
| A19 | Non-root installed process/restart and synthetic credential log checks passed locally; selected production installation, real credential rotation, backup and incident setup still P4/P6 |
| A20–A22 | NOT RUN: real user's DCR/browser consent, real refresh/replay/revocation, distinct test-vs-real cleanup and actual rollout/rollback/user acceptance |

P1–P3 have local engineering evidence sufficient for an implementation candidate.
P4–P6 remain the original required end state. Public rollout must select a reviewed
proxy with rate limiting, obtain a trusted domain certificate plus renewal control,
confirm independent-client reachability and Auth's ability to fetch port7960, then
register exact URI/scopes. The owner's verified sub/project is not known. The user
has been asked for those inputs; no response has been assumed. Real browser consent
cannot be supplied by the agent. Do not resume old Certbot challenges or old memory
experiments to fill these gaps.
