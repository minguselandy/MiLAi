# OpenWorker HTTP ingress exposure revalidation

Current decision: `FIXED`

## Diagnosis

The authentication layer is present and behaves fail-closed. An explicit
loopback listener accepts only the exact startup bearer; missing, wrong, or
duplicate `Authorization` values return `401` before malformed task metadata
or JSON is parsed.

The network exposure contract is not enforced by the executable. The CLI
accepts `--listen-host 0.0.0.0`, passes it directly to
`ThreadingHTTPServer`, and the resulting plain-HTTP listener serves a
correctly authenticated request through a non-loopback interface. This is a
reproducible gap against the U1 owner decision that confines ingress to the
run-owned Docker bridge gateway and accepts no request from another network.

The diagnosis does not treat missing TLS as the defect. Plain HTTP remains a
valid candidate transport for an isolated local bridge. The required repair
boundary is narrower: the adapter must reject wildcard and ambiguous bind
targets, while deployment remains responsible for proving that an allowed
explicit address belongs to the run-owned bridge.

## Capability lifecycle observation

The ingress capability is loaded once at startup. Replacing the token file
while the adapter is running leaves the old bearer valid and does not make the
replacement bearer valid. This is execution evidence, not yet a defect
decision. The owner contract must choose one of these semantics explicitly:

- capability lifetime equals adapter-process lifetime, with restart required
  for rotation or revocation; or
- file replacement/deletion is an online revocation event, which would
  require a new reload mechanism.

The diagnosis does not recommend a file watcher or hot-reload implementation
before that contract is fixed.

## Evidence boundary

The immutable diagnosis is recorded in [`receipt.json`](receipt.json):

```text
execution: FAIL
decision: OPEN
Product source commit: fa16bb7c1b28b16b15c1800df86999804e729d3b
Product tree: a93268d94a73e5aee53150ca4be9bbc5f37f76d0173c5be72633cc54cf2ea382
OpenWorker package: 181 passed; Ruff PASS; mypy PASS
```

The receipt contributes a `SCOPED FAIL` for G8. It makes no I-11 claim and
does not promote the frozen architecture item to `DEVIATION`; G8 remains
`UNVERIFIED` until a separate architecture review or complete receipt says
otherwise.

Production source, token schema, network topology, and TLS behavior were not
changed by this diagnosis.

## Remediation

The Host now validates `--listen-host` before adapter initialization. Only
explicit loopback, RFC1918, and IPv6 ULA literals are accepted; wildcard,
hostname, multicast, and public/routable targets fail closed. IPv4 and IPv6
listeners use their matching address family. Deployment still owns proof that
an accepted private address is the run-owned isolated bridge.

The ingress Bearer contract is now explicit: the token is immutable for one
adapter process. Rotation or revocation is stop, replace, restart. Execution
proves that file replacement does not mutate the live capability and that a
restarted adapter rejects the old token and accepts the replacement.

[`remediation.receipt.json`](remediation.receipt.json) records the current-tree
PASS and contributes a G8 `SCOPED PASS`. It does not claim complete G8 or I-11
coverage.
