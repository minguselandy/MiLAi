# MiLAi provider A/B adapter contract v3

This is an evaluation boundary, not a Runtime dependency or a provider attestation. It permits an
approved adapter to receive only the frozen synthetic/de-identified workload. Neither capture nor
billing reconciliation can emit `PASS`; both remain `REVIEW_REQUIRED` until an independent reviewer
checks the real provider objects. A fixture can exercise the complete protocol but cannot close
`OE-F06`.

## Trust anchors and closed execution

The v3 manifest has a closed schema. It binds one exact runtime, one exact source, a structured
adapter dependency lock, an independently reproducible host-execution lock,
provider/model/tokenizer/origin, secret environment names, a distinct non-root
uid/gid, and one of two egress policies:

- `deny-all` with an empty IP list, used by local fixtures;
- `https-origin-ip-allowlist` with a sorted, unique address list, used only after operator review.

All executable, source, lock, approval and dependency files must be absolute regular files outside
the MiLAi workspace and `/root`. There is no caller-supplied command or argv. The runner constructs
the only permitted command, opens and hashes runtime/source bytes before execution, executes those
file descriptors, copies each verified dependency to an immutable per-run file, bind-mounts those
bytes over the approved dependency target in a private mount namespace, and rehashes the open
descriptors after shutdown. The adapter dependency lock must enumerate the adapter runtime's libraries,
imported code/data and every child executable (plus its transitive code dependencies). This closes
decoy-argv and validation/run substitution paths.

The host-execution lock is generated with the runner's `host-lock` command and then reviewed outside
the run. Its closed, canonical file array includes the exact sandbox launcher and Python runtime,
every file-backed module loaded by the launcher's isolated static-import probe, `unshare`, every
installed namespace/network helper, and the recursive resolved ELF dependency closure. Nested or
dynamic launcher imports are rejected. The runner independently rebuilds this closure instead of
trusting a caller-authored list. It opens and hashes every entry before namespace creation and retains
those descriptors through the run. It first stops and bounded-waits the adapter PID namespace and
every persistent network helper, then verifies both the opened inode and the original path by
device/inode/size/SHA-256, and only then sets the post-execution flag and closes descriptors. A helper
that cannot be confirmed stopped, or any missing, additional, replaced, unreadable or changed byte,
fails closed.

The approval is `milai-provider-approval-v3`. Its SHA-256 is supplied out of band with
`--expected-approval-sha256`; the manifest does not declare the expected digest. The approval binds:

- manifest, workload, pricing, runtime, source, adapter-dependency-lock and host-execution-lock
  digests, plus the host closure root, count and enumeration policy;
- sandbox launcher/runtime, `unshare`, and every allowlist-network executable digest;
- exact shipped `reader` and `reader-lite` tool-schema digests;
- provider origin/IP policy, secret names, sandbox identity and the exact
  `landlock-read-execute-allowlist-v1` policy with minimum ABI 1;
- exactly 1,000 requests, input/output ceilings, total cost and billing tolerance;
- approver identity and time.

`plan` returns a deterministic `plan_sha256` over all authorization-relevant fields. `run` requires
that digest through `--expected-plan-sha256`; it does not accept a changed budget, pricing object,
workload, tool catalog, executable or policy.

## Isolation

The adapter runs in private mount, PID and network namespaces as the approved non-root identity with
`no_new_privs`. The whole shared workspace and `/root` are covered by read-only empty mounts. HOME,
temporary and XDG paths are fresh. `/etc/hosts` is replaced by an approval-derived static provider
mapping and `/etc/resolv.conf` disables DNS. Proxy variables and all undeclared environment values
are omitted. Provider credentials must use the closed alias namespace
`MILAI_PROVIDER_CREDENTIAL_*`; the adapter reads that alias and passes the value explicitly to its
SDK. Native SDK/loader/interpreter control names such as `OPENAI_API_KEY`, `PYTHONPATH`, `LD_PRELOAD`,
`BASH_ENV`, proxy variables, and canonical/PostgreSQL credential names cannot be declared. The
privileged sandbox Python runs with `-I -S`, so environment and site startup hooks are disabled.

Immediately before privilege drop, the launcher installs a Landlock rule set that handles
`READ_FILE` and `EXECUTE`. It permits reads only from the copied source, verified dependency targets,
runtime and minimal hosts/resolver/random-device inputs; execution is limited to the verified runtime
and declared dependency targets. Any missing Landlock support, undeclared executable, imported code
file or code-bearing data read fails closed. Files opened by the privileged launcher are close-on-exec
and are not inherited by the adapter. The local fixture positively enumerates Bash, `sed` and their
dynamic dependencies and negatively verifies an undeclared host executable.

The kernel remains part of the operator-approved host TCB. The host lock binds its release/machine
identity and, unlike v2, binds and revalidates the complete local userspace byte closure for the
privileged namespace/network helpers. Real-provider acceptance must still independently review the
actual execution host and provider evidence; local closure does not by itself close `OE-F06`.

`deny-all` has no external interface. The HTTPS allowlist mode attaches a private slirp interface and
installs a default-drop nftables output chain allowing only TCP/443 to the approved IP set (plus
loopback and established replies). These helper binaries and the address set are approval-bound.

Every adapter response is tainted. Before validation or retention, the runner recursively rejects
any string containing any supplied provider-secret value. Native request IDs have a closed format
and length; terminal state and finish reason are closed enums. Reports never retain prompt, memory,
raw output, stderr, or secret values.

## JSON Lines protocol v2

The process reads one JSON object per line and writes exactly one JSON object per line. It must not
write logs to stdout. The handshake binds protocol, provider origin, model and tokenizer and declares
`native_provider_response` usage.

Before every charge-bearing operation the runner sends the entire request with
`op=count_request`. The adapter must use the approved target-model tokenizer and return exact full
input, memory-context and tool-schema counts. The runner checks the per-call cap and reserves the
maximum input/output price before it sends `op=model_call`. Thus a count or reservation denial causes
zero model calls.

Each `model_result` contains the raw model text in transit, aggregate native usage, and a non-empty
`native_calls` array. Each native call has a unique provider request ID, exact model, native usage,
terminal=true, an approved finish reason (`stop` or `completed`) and a native receipt digest. The
aggregate usage must equal the sum of every native call, provider input usage must equal the pre-call
target count, and output must not exceed the request ceiling. All native IDs are globally unique.
The runner parses/scores text in memory and retains only a normalized five-field response (or null),
its hash, counters and scores.

Native fields remain adapter claims until an independent reviewer verifies provider-native receipts
and billing. Accordingly `provider_usage_verified` is always false in tool-produced output.

## Capture and reconciliation

A successful complete capture has status
`PROVIDER_CAPTURE_COMPLETE_REVIEW_REQUIRED`. A late error produces an atomically written
`FAIL_PARTIAL` receipt with only already-validated records, native IDs, hashes, cost-to-failure and a
hashed reason. Input and output use nonblocking transfer under one total deadline, with a two-megabyte response limit;
timeout terminates the complete PID namespace/process group.

Reconciliation requires all of the following out-of-band arguments: report SHA-256, approval
SHA-256 and plan SHA-256, plus the original manifest and pricing snapshot. It independently enforces
a closed report schema, exactly 1,000 ordered records, deterministic logical IDs, exact shipped tool
hashes, all native IDs/receipts, usage/cost/output/quality fields, aggregate values and the complete
required gate set. Empty gates, shortened reports and recomputed attacker digests fail.

The v2 billing sidecar points to two distinct external objects: the normalized export and the actual
upstream provider export/invoice. Both are opened and hashed outside the repository. The normalized
file must bind the upstream digest and cover every native request ID exactly once. Billing tolerance
comes only from approval and is capped at one percent of approved spend; actual total must remain
within the approved cost ceiling regardless of tolerance.

Successful matching yields `PROVIDER_EVIDENCE_RECONCILED_REVIEW_REQUIRED`, never `PASS`. Independent
provider review and a separately retained decision are required to close `OE-F06` and promote beyond
Optimization Candidate. The CLI writes the complete review-required artifact atomically and exits
with code `3`; only the no-network `plan` can exit `0`. Validation errors use `2` and failed/partial
captures use `1`, so a fixture or unattended shell cannot mistake capture/reconciliation for final
acceptance.
