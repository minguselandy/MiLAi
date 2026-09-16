# OE-07 Agent Execution Optimization candidate.4.4 — independent local re-review

Status: `COMPLETE — LOCAL DECISION REVISE; REAL PROVIDER/BETA NO-GO`  
Review date: `2026-08-18`  
Reviewer: `/root/af09_reviewer_retry`  
Independence: same independent reviewer who issued the candidate.4.3 finding; did not author
candidate.4.4, its remediation report, inventory, protocol, launcher, tests, templates, CI, frozen
artifacts, or package artifacts. Author conclusions were treated as claims rather than evidence.

## Decision

| Boundary | Independent decision |
| --- | --- |
| A — local synthetic protocol | **REVISE** |
| B — real provider evidence / Beta | **NO-GO — external `OE-F06` remains OPEN** |

Candidate.4.4 closes the concrete adapter-side host fallback demonstrated in candidate.4.3: the
Landlock policy is approval/plan-bound, the successful fixture explicitly locks Bash, `sed`, and their
dynamic closure, and both an undeclared executable and an undeclared host-file read fail closed.
Those controls and all requested local gates passed.

However, the original `OE-C43-F01` acceptance condition also required every code-bearing
runtime/interpreter/sandbox/helper/transitive byte, or an equivalent immutable image/filesystem
identity, to be bound. Candidate.4.4 still binds only the top-level privileged helper executables.
The successful local runs load helper/runtime dependencies that are absent from the approval-bound
dependency closure and from post-run revalidation. The contract explicitly postpones immutable
host/image and helper-transitive identity to a future real-provider review. That is a material and
honest boundary statement, but it does not close the existing local P0 under its recorded acceptance
condition. Green tests cannot override that unresolved evidence-integrity path.

No external provider, account, billing service, or credential was accessed. All execution was limited
to repository synthetic fixtures and local namespace controls. This record does not authorize a real
provider run.

## Review identity and byte inventory

- Review start: `2026-08-18T12:21:24Z` / `2026-08-18T20:21:24+0800`.
- Evidence completion / immediately-before-write check: `2026-08-18T12:30:57Z` /
  `2026-08-18T20:30:57+0800`.
- Host: Linux `5.15.0-86-generic`, `x86_64`.
- Python `3.11.13`; uv `0.8.3`; Ruff `0.16.3`; mypy `1.20.2`; pytest `8.4.2`.
- Workspace: `/cra/memory/mx_memory/MiLAi`.
- Network/account boundary: local synthetic adapters and local namespaces only; no external service,
  real account, real credential, or provider request.

The inventory digest and canonical entries root were supplied out of band. I independently rebuilt
the listed live objects without invoking the inventory writer, recomputed every size/hash, and checked
ordering, uniqueness, and symlinks.

| Identity check | Expected | Independently observed |
| --- | --- | --- |
| Inventory SHA-256 | `640effd3860cda7b38b79852d18bb74084c1df706abb65e5880e98d93d525dc1` | exact |
| Entry count | `359` | `359` |
| Canonical entries SHA-256 | `730080ba8a437ef58db100b6b6b09cd91f9052aa17ab155c04f18d7102f7f12b` | exact |
| Listed entries versus live bytes | exact | all 359 path/size/hash objects equal |
| Ordering / uniqueness / source symlinks | sorted / unique / none | PASS |
| Immediately-before-write reconstruction | same identity | PASS |
| After-review-write reconstruction | same identity | PASS at `2026-08-18T12:33:07Z` — inventory SHA, 359 entries, canonical root, and all live objects unchanged |

The new review path is outside the inventory include roots. Additional independently recomputed
anchors remained unchanged:

- frozen Logical Architecture manifest:
  `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e`;
- integration package release manifest:
  `d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f`;
- all 6 package locks and all 12 wheel/sdist artifacts matched their declared hashes, and all 12
  artifact sizes matched.

Candidate.4.4 core hashes independently matched the supplied identity:

| Artifact | SHA-256 |
| --- | --- |
| `evals/agent_efficiency/provider_ab.py` | `ca8569cb388db5a8bc652c2f531a397be82b9d00994417e5a5e596adc6a0fb6e` |
| `evals/agent_efficiency/provider_sandbox_exec.py` | `f3d48c0652500f46ca40f9fedcb4c9dced4a63d70e2a46bf31e150d2c4ea73c4` |
| `evals/agent_efficiency/test_provider_ab.py` | `1554ce63f815f54cd4d6a9b4693afbc577c8f9bbe6c86a55e589b72db1e2cbab` |
| `evals/agent_efficiency/PROVIDER_ADAPTER_CONTRACT.md` | `9602fdc3dc38a80c096461cca63e606bb33b76d5de654dc2841242cbf4d6e69a` |
| candidate.4.4 author report | `dd2e33b3cf60c4edef8854eeed13f6ce6d525c0b825f8c6bcb84afd0b3edc89b` |
| `.github/workflows/ci.yml` | `be5cef4a6a7283e3c5aba00c38f7099533e99654da0a4f269728c3ad14838e97` |

## Materials reviewed

Read before decision: `AGENTS.md`, the implementation contract, the complete optimization design,
the candidate.3 and candidate.4.3 independent records, the complete candidate.4.4 author report,
provider contract, provider runner, sandbox launcher, provider and benchmark tests, all provider
workload/manifest/approval/dependency templates, shipped Python-client tool implementation and tests,
release-safety scanner/tests, inventory and package-manifest builders, the package manifest, and the
complete relevant CI workflow. All changed candidate.4.4 files were re-read in full. Source and
executable negative behavior, rather than the remediation report, controlled the decision.

## `OE-C43-F01` closure decision

### Result: **PARTIALLY REMEDIATED — OPEN P0**

What is closed:

- `provider_ab.py:616-710,1579-1621` uses a closed approval/plan schema and binds the exact
  `landlock-read-execute-allowlist-v1` policy with minimum ABI 1.
- `provider_sandbox_exec.py:90-142,196-252` installs `READ_FILE`/`EXECUTE` Landlock rules before
  privilege drop and allows adapter execution only from the runtime/source/declared-dependency set.
- `test_provider_ab.py:44-97,161-198,432-475` makes an undeclared host-file read part of the successful
  fixture, enumerates Bash/`sed` plus their dynamic closure, and proves an undeclared executable returns
  `FAIL_PARTIAL` with zero provider requests. Both positive and negative nodes passed.
- Runtime, source, launcher, top-level helpers, and declared dependency files are opened and hashed
  before launch and rehashed after shutdown at `provider_ab.py:853-908,1155-1188`.

What remains open:

- The approval contains only top-level hashes for sandbox Python, `unshare`, `slirp4netns`, `nsenter`,
  `nft`, and `ip` (`provider_ab.py:629-635,666-710`); the plan repeats those top-level values
  (`provider_ab.py:1603-1611`). No helper-transitive lock or immutable image/filesystem identity is
  present.
- Those privileged processes execute before or outside the adapter's Landlock boundary
  (`provider_ab.py:909-1048`). Their runtime-loaded libraries and sandbox-Python imported standard
  library/code data never enter `_fds`, so the post-run check at `provider_ab.py:1155-1188` cannot
  revalidate them.
- An independent `ldd` closure comparison found 7 files in the Bash/`sed` adapter fixture closure, but
  22 unique dynamic-library files used by the sandbox runtime/network-helper set were outside it.
  The ordinary deny-all fixture already uses the sandbox runtime; the allowlist fixture also executes
  the network helpers. Thus this is not a hypothetical unused branch.
- The contract itself acknowledges that the kernel and privileged namespace/network helpers are host
  TCB and defers immutable host/container identity and their transitive dependencies to real-provider
  acceptance (`PROVIDER_ADAPTER_CONTRACT.md:62-65`). The author report makes the same deferral at
  lines 62-67.

Adversarial conclusion: Landlock now establishes a useful closed *adapter* execution root, and it
fully fixes the concrete undeclared-`sed` symptom. It does not establish the larger execution closure
that `OE-C43-F01` expressly required. A locally green report still depends on code-bearing privileged
runtime/helper bytes absent from approval, plan, the dependency lock, and post-run rehash evidence.

Required change/evidence remains:

1. Bind and independently attest the complete code-bearing sandbox-runtime/launcher/helper closure,
   including transitive runtime/import/dynamic dependencies, or bind an equivalent immutable
   host/container image plus the actual run identity.
2. Carry that identity through out-of-band approval, deterministic plan, execution, and post-run
   evidence; a documentation-only host-TCB assumption is not a substitute for the recorded closure.
3. Add a safe synthetic negative proving that a helper-transitive byte set outside the approved
   identity cannot produce accepted capture evidence, and a positive independently enumerated closure
   check. No operational bypass or external request is needed for this acceptance test.

No new candidate.4.4 finding ID is opened; this is the same `OE-C43-F01` failing its previously recorded
closure condition.

## F01–F07 independent matrix

| Finding | Local result | Independent evidence and conclusion |
| --- | --- | --- |
| `OE-C3-F01` forged reconciliation | `PASS_LOCAL` | Closed report/record/normalized schemas, 1,000 ordered records, identities, native coverage, usage/cost/quality/aggregates/gates, and external report/approval/plan/upstream digests are recomputed at `provider_ab.py:1987-2335`. Empty-gate, short-record, forged-quality, extra-field, missing-upstream, and tolerance-sidecar negatives passed. Status remains review-required, never PASS. |
| `OE-C3-F02` unbound execution | **`FAIL`** | Adapter-side fallback is fixed, but `OE-C43-F01` remains open because privileged helper/runtime transitive bytes or immutable image identity are not bound. |
| `OE-C3-F03` isolation/privacy | `PASS_LOCAL` | Distinct UID/GID, private mount/PID/network namespaces, hidden roots, minimal environment, control-name rejection, Landlock, secret reflection rejection, and deny-all/allowlist nodes passed (`provider_ab.py:561-576,839-1048`; `provider_sandbox_exec.py:162-252`). This does not attest a future real adapter. |
| `OE-C3-F04` pre-call authorization | `PASS_LOCAL` | Approval and plan bind limits; target count, per-call cap, maximum-output reservation, and cumulative authorization precede `model_call` (`provider_ab.py:1579-1662,1798-1863`). Wrong-plan and oversized-count fixtures produced zero charge-bearing calls. |
| `OE-C3-F05` shipped tools/native state | `PASS_LOCAL` | Tool catalogs are derived from shipped `create_milai_tools`; native IDs, usage sums, terminal/finish state, receipt digest, and global coverage are checked. Exact-schema and hidden-round/nonterminal negatives passed. Authenticity remains external and `provider_usage_verified=false`. |
| `OE-C3-F06` CI coverage | `PASS_LOCAL` | `.github/workflows/ci.yml:151-183` parses and contains one Python-client provider gate with namespace tools, locked Runtime setup, provider Ruff, strict mypy, and the reproduced 42-item union under a 20-minute job timeout. No hosted-run claim is made. |
| `OE-C3-F07` total timeout/partial receipt | `PASS_LOCAL` | One monotonic deadline, bounded response, process-group teardown, validated-only partial state, and atomic replacement are implemented; partial-line, non-reading input, late-call, privacy, and atomic-output nodes passed. |

Local open findings after this review: **P0/P1/P2 = 1/0/0**.

## Reproduced commands and results

All commands ran from the repository root unless noted. Bytecode/cache output was disabled or directed
outside the repository.

| Gate | Result |
| --- | --- |
| Independent inventory reconstruction | PASS — external inventory digest, 359 live entries, canonical root, ordering/uniqueness, and no source symlink all matched |
| Core and package identities | PASS — all supplied candidate.4.4 core hashes matched; package manifest matched; 6/6 locks and 12/12 artifacts plus sizes matched |
| Provider + benchmark + release-safety union | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:integrations/python-client/src runtime/.venv/bin/pytest -q -p no:cacheprovider evals/agent_efficiency/test_provider_ab.py evals/agent_efficiency/test_benchmark.py tests/test_release_safety.py` — **42 passed in 96.01 s** |
| Non-repository cwd capture | The full 1,000-call isolated-capture node rerun from `/tmp` — **1 passed in 9.36 s** |
| Provider static | Ruff format/check PASS for runner, launcher, tests; strict mypy PASS for 2 source files |
| Frozen architecture | architecture Ruff PASS; `validate_bundle.py` PASS; release-mode bundle `verify_lock.py` with external `ac16f3…d0e` PASS; 19 tests PASS with 1 expected Git-scope skip |
| Archive-aware scan | `/dev/null` credential source; PASS over 361 files / 296 expanded members / 186,154,639 source bytes; zero match, forbidden member, or unsafe archive. Synthetic archive negatives were separately included in the 42-item union. |
| CI syntax/coverage | YAML parse PASS; exactly one provider gate; 20-minute job timeout; reproduced Ruff/mypy/test inputs present |
| Shipped Python client | Ruff format/check PASS; mypy PASS for 9 files; **76 passed in 0.59 s** |
| Helper-closure audit | 7-file Bash/`sed` adapter fixture closure; 22 unique sandbox-runtime/network-helper dynamic dependencies outside that lock; no immutable host/image identity in approval or plan |

## Real-provider boundary (`OE-F06`)

`OE-F06` remains open independently of the local P0. Candidate.4.4 contains no independently approved
real provider/model and adapter closure, no real 1,000-request capture, no provider-native receipt
verification, no real upstream billing export/invoice reconciliation, no immutable execution-host
attestation, and no same-model external quality/safety decision. The protocol deliberately leaves
`provider_usage_verified=false` and emits only `*_REVIEW_REQUIRED` states.

Therefore B is **NO-GO**. A later host/helper-closure remediation cannot be represented as closing
external `OE-F06`; a separately authorized real run and independent external-evidence decision remain
mandatory.

## Final rationale and boundary

- A: **REVISE** because `OE-C43-F01`'s exact execution-closure condition is only partially satisfied;
  the unresolved path affects evidence integrity and remains P0.
- B: **NO-GO** because required real provider/native/billing/quality/host-attestation evidence does not
  exist.
- This record does not claim production readiness, real-data readiness, Beta readiness, or Schema
  freeze. Logical Architecture remains frozen; Runtime remains candidate; Schema remains experimental
  and NO-GO for freeze.

Signature/reference: `/root/af09_reviewer_retry — OE-07 candidate.4.4 independent local re-review decision`
