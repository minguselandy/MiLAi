# HTTP-AIGCIT-AUTH-01 acceptance contract

Authority: [ADR-049](../adr/ADR-049-authenticated-private-memory.md), superseding the
one-owner restriction in [ADR-048](../adr/ADR-048-aigcit-resource-server-identity.md), and the complete
[P0–P6 / A01–A22 Goal](../goals/HTTP-AIGCIT-AUTH-01_设计与实施规划_20260907.md).
This contract does not waive any Goal gate. Schema remains 0.1.x EXPERIMENTAL /
NO-GO FOR SCHEMA FREEZE. The MCP integration changes no Runtime schema or Canonical
permission. The earlier memory/model experiments remain paused.

## Local invariants and direct tests

| Surface | Required behavior | Direct evidence location |
|---|---|---|
| Explicit mode | No AIGCIT/static/local-AS mixture; no default owner or dummy secret | `tests/test_aigcit_http.py` mode and CLI tests |
| Token | ES256 `at+jwt`, exact issuer and scalar audience, integer time claims, nonempty subject/client, no scope defaults | `tests/test_aigcit_auth.py` signed fixtures |
| Network | Trusted same-origin JWKS discovery, TLS verification, no redirects, 3s total refresh deadline, 256KiB bounds | JWT I/O, deadline and cancellation tests; real public cold-discovery receipt |
| Cache | Warm key avoids network/refresh lock; TTL cannot be extended by failure; shared unknown-kid cooldown | Concurrent rotation/deletion/cancellation and opt-in calibration tests |
| Admission | Root-owned read-only file, exact project/issuer/principal, at most one active owner; reread on requests | Admission file tests and non-root installed-package check |
| Tools | Token/admission/deployment scope intersection; all 13 tools explicitly mapped; pilot exposes at most five; denied handler/Runtime calls zero | HTTP directory, direct call, audit and no-identity tests |
| Session | Legacy handshake and current SDK per-request envelope both reauthenticate; disable/corruption cannot be bypassed with session ID | HTTP session tests; ContextVar thread/error/cancellation tests |
| Persistence | Stable identity across signing key, token and client changes; exact CAS and replay; cold process recovery | Opt-in real PostgreSQL test; do not count its default skip as success |
| Project | Token self-asserted tenant/project/role ignored; foreign State/Evidence refs cannot authorize persistence | Signed-claim tests and real PostgreSQL project tests |
| Metadata | Independent issuer and exact non-default resource port; no local AS routes; registration and login reported separately | External preflight tests and proxy Host/Origin tests |

Run the focused tests first, then locked Ruff/mypy/full MCP pytest/build. Run real
PostgreSQL under its explicit opt-in with disposable roles and databases. Record
failures and corrections; do not discard a failed extension because an earlier test
passed. No model or production OAuth token is used to test local authentication.

## Public gates remain independent

Before P4, verify the selected proxy includes the required rate-limit module, keep
candidate listeners isolated, and validate a trusted certificate/renewal plan. A
temporary self-signed certificate used solely for `nginx -t` proves syntax, never
public trust. No plaintext fallback and no changes to shared services as test cleanup.

Before P5/P6, obtain the real owner's verified sub/project, independent-client TLS
and Auth metadata-fetch evidence, active exact resource/scopes, real DCR/browser
consent and token-type confirmation, refresh/replay/family-revocation evidence, then
real save/exit/resume and scoped rollback/user acceptance. Do not infer those results
from local signed fixtures, an installed wheel, a discovery GET or an API 200.

Readiness states, authorized in-flight operation boundaries and unresolved external
dependencies follow Goal sections 6, 9, 11 and 12. Full completion is the original
`COMPLETED_AUTH_PILOT`, not merely this local implementation.
