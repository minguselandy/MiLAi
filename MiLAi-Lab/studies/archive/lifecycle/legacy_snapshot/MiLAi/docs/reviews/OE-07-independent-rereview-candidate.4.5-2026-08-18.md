# OE-07 Agent Execution Optimization candidate.4.5 — independent local re-review

Status: `COMPLETE — LOCAL DECISION REVISE; REAL PROVIDER/BETA NO-GO`  
Review date: `2026-08-18`  
Reviewer: `/root/af09_reviewer_retry`  
Independence: same independent reviewer who recorded `OE-C43-F01`; did not author candidate.4.5,
its report, inventory, protocol, launcher, tests, examples, CI, frozen artifacts, or package artifacts.
Author statements and test names were treated as claims, not evidence.

## Decision

| Boundary | Independent decision |
| --- | --- |
| A — local synthetic protocol | **REVISE** |
| B — real provider evidence / Beta | **NO-GO — external `OE-F06` remains OPEN** |

Candidate.4.5 fixes the candidate.4.4 *enumeration* defect. An independent implementation found the
same 113-file host closure, including 79 file-backed Python import/cache objects and 27 recursively
resolved ELF dependencies. The lock is closed, externally digest-bound, independently rebuilt, and
carried through approval, plan, run report, and reconciliation. Missing and additional entries fail
even under a newly generated internally consistent approval. FD and original-path checks also reject
content change, path replacement, and disappearance.

The original P0 acceptance condition nevertheless remains unmet. During allowlist execution,
`slirp4netns` is part of the approved host-execution closure and continues to execute as the privileged
network helper. `AdapterProcess.__exit__` rehashes every host entry and sets
`post_execution_revalidated=true`, then closes all retained host descriptors, and only afterward sends
TERM/KILL and waits for that helper. A real local `slirp4netns` run confirmed it was alive for all
113/113 final host-entry rehashes. Thus the evidence can say “post-execution revalidated” before the
host-closure execution lifetime has ended, leaving an undetectable post-check execution/mutation
window. This directly contradicts the contract and author report's “after shutdown” claim.

This is the existing **`OE-C43-F01 — OPEN P0`**, not a new finding ID. Local open finding counts after
this review are **P0/P1/P2 = 1/0/0**. Green synthetic tests do not close the lifecycle gap.

No provider service, real account, billing service, external model, or real credential was accessed.
All dynamic evidence used repository synthetic fixtures, local namespaces, temporary files, and one
fixture-defined local TCP loopback boundary. This review does not authorize a real provider run.

## Review identity and byte inventory

- Review start: `2026-08-18T13:04:52Z` / `2026-08-18T21:04:52+0800`.
- Evidence completion / immediately-before-write check: `2026-08-18T13:23:50Z` /
  `2026-08-18T21:23:50+0800`.
- Host: Linux `5.15.0-86-generic`, `x86_64`.
- Python `3.11.13`; uv `0.8.3`; Ruff `0.16.3`; mypy `1.20.2`; pytest `8.4.2`.
- Workspace: `/cra/memory/mx_memory/MiLAi`.
- Boundary: synthetic/local-only; no external provider/account/credential request.

The inventory digest and canonical entries root were supplied out of band. I independently rebuilt
the include-root set without invoking either inventory writer, applied only the declared cache/venv
exclusions, rejected symlinks, and recomputed every file size/hash and the sorted canonical root.

| Identity check | Expected | Independently observed |
| --- | --- | --- |
| Inventory SHA-256 | `c84bc0b5aeba050db50894d33ad42f9a4e668e79c8790b26ee91c35e2452b12d` | exact |
| Entry count | `361` | `361` |
| Canonical entries SHA-256 | `542a65aee53b18c49cda3bbe5191ff58004fb199aeca317ad8f4f034cb150e9a` | exact |
| Listed entries versus live bytes | exact | all 361 path/size/hash objects equal |
| Ordering / uniqueness / source symlinks | sorted / unique / none | PASS |
| Immediately-before-write reconstruction | same identity | PASS |
| After-review-write reconstruction | same identity | PASS at `2026-08-18T13:26:18Z` — inventory SHA, 361 entries, canonical root, and all live objects unchanged |

The review path is outside the inventory include roots. Additional anchors independently matched:

- integration package manifest:
  `d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f`;
- frozen Logical Architecture manifest:
  `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e`;
- candidate.4.5 author report:
  `f0616f92f8b3a2165ef3b88b1da18ca8a2a88e92f32ab732cb0139171bcc1d00`.

Candidate.4.5 core hashes also matched the frozen inventory:

| Artifact | SHA-256 |
| --- | --- |
| `evals/agent_efficiency/provider_ab.py` | `7110547864a4707070b1f0552902f0fdbb2bc922d4ea4f9ccf939950cb007874` |
| `evals/agent_efficiency/provider_sandbox_exec.py` | `f3d48c0652500f46ca40f9fedcb4c9dced4a63d70e2a46bf31e150d2c4ea73c4` |
| `evals/agent_efficiency/test_provider_ab.py` | `92cb45e88a8bc08c27c1e595170893bede7b8584445c88bda10f14a7903ecc74` |
| `evals/agent_efficiency/PROVIDER_ADAPTER_CONTRACT.md` | `fd01f081a5bc6dd10b041b6a865d598a5fb4aa0739fd6ad6d061616042149a42` |
| `.github/workflows/ci.yml` | `be5cef4a6a7283e3c5aba00c38f7099533e99654da0a4f269728c3ad14838e97` |

All 6 package locks and 12 wheel/sdist artifacts matched the package manifest's declared SHA-256;
all 12 artifact sizes matched.

## Materials and method

Read in full before decision: `AGENTS.md`, the implementation contract, the optimization design,
the candidate.4.4 independent record, the complete candidate.4.5 author report, provider contract,
runner, sandbox launcher, provider/benchmark tests, all provider JSON examples and workload, relevant
Python-client implementation/tests, release-safety scanner/tests, inventory and package-manifest
builders, package manifest, and the complete provider CI step. Changed candidate.4.5 files were read
in full. The decision is based on code order and independently observed process state, not report text.

## `OE-C43-F01` closure decision

### Result: **ENUMERATION REMEDIATED; LIFECYCLE NOT REMEDIATED — OPEN P0**

What candidate.4.5 closes:

- `provider_ab.py:504-579` rejects nested/dynamic launcher imports and probes the exact sandbox Python
  under `-I -S -B`; `582-680` recursively resolves ELF dependencies and emits a canonical lock.
- My independent AST/import/ELF implementation observed 5 module-scope import nodes, 79 file-backed
  import/cache objects, 27 dynamic-dependency entries, and 113 unique files. Its canonical root
  `98e3756fa4cc1a306ef03d898099b23bfa389d3c657ea4d19e388dce6f2ca207` and complete object were exactly
  equal to `build_host_execution_lock()`.
- `provider_ab.py:684-703` rebuilds the whole object rather than trusting the submitted list.
  `test_provider_ab.py:430-525` and an independent extra-entry mutation proved both omission and
  addition fail with the error `host execution lock does not match the independently enumerated
  closure`, even after lock root, manifest digest, and fresh approval are made mutually consistent.
- Approval validation binds lock SHA/root/count/policy at `provider_ab.py:782-788,842-979`; the plan
  carries those values at `1949-2026`; the report and closed capture schema carry them at
  `2029-2089,2344-2678`; reconciliation re-derives them at `2681-2984`. A fresh-digest report mutation
  of the host root failed as `capture host execution evidence mismatch`.
- `provider_ab.py:1106-1135` opens every host entry with `O_NOFOLLOW|O_CLOEXEC`, records
  dev/inode/size, hashes the FD, and sets the pre-check. The per-entry final comparison at
  `1442-1471` checks both FD and original path dev/inode/size/SHA. Independent temporary-file cases
  rejected same-size content change, same-bytes path replacement, and path disappearance. Injected
  post-exit failure propagated to `FAIL_PARTIAL` with `PROVIDER_EVIDENCE_CAPTURE_FAILED`.

What remains open:

- The runner requires root at `provider_ab.py:1086-1089`. The allowlist helper is launched without a
  UID/GID drop at `1265-1272`, so it remains a privileged, executing member of the locked host closure.
- Main adapter shutdown occurs at `1411-1421`. Host FD/path rehash then occurs at `1430-1471`, where
  `post_execution_revalidated` is set. All execution FDs and host FDs are closed at `1472-1483`.
  Only then does the runner TERM/KILL/wait `_network_process` at `1484-1494`.
- A no-network event-trace harness observed the exact order:
  `host-fd-rehash(alive, post=false)` → `host-path-rehash(alive, post=false)` →
  `host-fd-close(alive, post=true)` → `TERM(alive, post=true)` →
  `wait(alive, post=true)`.
- More importantly, an actual checked-in allowlist fixture, instrumented without changing candidate
  files, completed its local `10.0.2.2`→host-loopback exchange and returned
  `PROVIDER_CAPTURE_COMPLETE_REVIEW_REQUIRED`; the real `slirp4netns` process had `poll() is None` at
  every one of 113 host FD rehash calls, then exited on TERM with return code `-15`.
- `PROVIDER_ADAPTER_CONTRACT.md:28-36` promises descriptors retained through the run and verification
  “after shutdown.” The author report makes the same assertion at lines `49-58`. The implementation's
  order disproves both claims. The positive test at `test_provider_ab.py:552-571` checks only that the
  final Boolean is true; it does not check that every closure-executing process had stopped first.

Adversarial conclusion: the new lock identifies the right local files, but its final assertion is
premature. A privileged approved helper can continue executing after the last observable hash and
after retained descriptors close. Changes or additional execution in that interval cannot affect the
already-set Boolean, yet the report and reconciliation accept that Boolean as post-execution evidence.
This is an execution-evidence TOCTOU and fails the original P0 acceptance condition.

Required change and acceptance evidence:

1. Stop and bounded-wait every process that can execute any host-closure byte, including
   `_network_process`, before final FD/path revalidation begins.
2. Retain all host descriptors until every such process has exited; then verify FD and original path
   dev/inode/size/SHA, set `post_execution_revalidated`, and only afterward close descriptors.
3. Treat helper termination/wait failure as `FAIL_PARTIAL`; never emit a true post flag if a helper may
   still execute.
4. Add an order-sensitive local negative using a real helper or deterministic substitute. It must
   prove no helper is alive at any final host hash and that a safe post-check mutation/liveness attempt
   cannot yield accepted capture/reconciliation evidence.

## F01–F07 independent matrix

| Finding | Local result | Independent evidence and conclusion |
| --- | --- | --- |
| `OE-C3-F01` forged reconciliation | `PASS_LOCAL` | Closed report/record schemas, exact record/gate recomputation, identities, upstream artifact, approval/plan digests, cost, and tolerance are validated at `provider_ab.py:2344-2984`. Empty-gate, short-record, forged-quality, extra-field, missing-upstream, sidecar-tolerance, and independent host-root tamper negatives failed closed. Tool status remains review-required, never PASS. |
| `OE-C3-F02` unbound execution | **`FAIL`** | Runtime/source/dependency execution and the 113-file host set are now content-bound, but `OE-C43-F01` remains open because the privileged network helper is alive after final host rehash and after FD closure. |
| `OE-C3-F03` isolation/privacy | `PASS_LOCAL` | Distinct UID/GID, mount/PID/network namespaces, hidden roots, closed environment/control names, Landlock, secret-reflection rejection, deny-all, undeclared executable, and local allowlist nodes passed (`provider_ab.py:706-979,1086-1313`; launcher `90-252`). This does not attest a future real adapter. |
| `OE-C3-F04` pre-call authorization | `PASS_LOCAL` | Approval and plan bind limits; target count, per-call cap, maximum-output reservation, and cumulative cost authorization precede `model_call` (`provider_ab.py:1949-2026,2092-2339`). Wrong-plan and oversized-count fixtures produced no charge-bearing calls. |
| `OE-C3-F05` shipped tools/native state | `PASS_LOCAL` | Tool catalogs derive from shipped `create_milai_tools`; native IDs, usage sums, terminal/finish state, receipt digest, and global coverage are checked (`provider_ab.py:1625-1827`). Exact-schema and hidden-round/nonterminal negatives passed. Authenticity remains external and `provider_usage_verified=false`. |
| `OE-C3-F06` CI coverage | `PASS_LOCAL` | `.github/workflows/ci.yml:158-183` parses and contains exactly one Python-client provider gate with namespace helpers, locked Runtime setup, provider Ruff, strict mypy, the reproduced union, and a 20-minute job timeout. No hosted-run claim is made. |
| `OE-C3-F07` total timeout/partial receipt | `PASS_LOCAL` | One monotonic deadline, bounded response, process-group teardown, validated-only partial state, and atomic replacement are implemented; partial-line, non-reading input, late-call, privacy, and atomic-output nodes passed. The separate helper-finalization P0 above remains. |

## Reproduced commands and results

All commands ran from the repository root unless noted. Bytecode and pytest cache writes were disabled;
temporary adversarial artifacts were outside the repository.

| Gate | Result |
| --- | --- |
| Independent inventory reconstruction | PASS — external inventory digest, 361 live entries, canonical root, ordering/uniqueness, and no source symlink all matched |
| Core/package identity | PASS — all supplied candidate.4.5 core hashes matched; package manifest matched; 6/6 locks and 12/12 artifacts plus sizes matched |
| Provider + benchmark + release-safety union | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:integrations/python-client/src runtime/.venv/bin/pytest -q -p no:cacheprovider evals/agent_efficiency/test_provider_ab.py evals/agent_efficiency/test_benchmark.py tests/test_release_safety.py` — **44 passed in 132.28 s** |
| Non-repository cwd capture | Full 1,000-call isolated capture node rerun from `/tmp` — **1 passed in 10.55 s** |
| Independent host closure | PASS — 5 module-scope imports; 79 import/cache objects; 27 recursive ELF dependencies; 113 files; root `98e375…a207`; exact complete-object match |
| Closure-set adversarial checks | PASS for control and missing-with-fresh-approval nodes (**2 passed**); independently added `/usr/bin/false`, recomputed root/manifest/fresh approval, and plan still failed on independent closure mismatch |
| FD/path final checks | Same-size content change and same-hash new-inode replacement rejected as changed; removed original path rejected as unreadable; all post flags false |
| Error propagation | Injected post-execution revalidation failure produced `FAIL_PARTIAL`, code `PROVIDER_EVIDENCE_CAPTURE_FAILED`; no exception was upgraded to accepted evidence |
| Approval→plan→run→reconciliation identity | Root/count/policy exact across all stages; a host-root mutation plus freshly supplied report digest failed `capture host execution evidence mismatch` |
| Actual helper lifecycle | Local allowlist fixture completed; real `slirp4netns` alive at 113/113 final host hashes; it exited only afterward with `-15` — **P0 blocker reproduced** |
| Provider static | Ruff format/check PASS for runner, launcher, tests; strict mypy PASS for 2 source files |
| Frozen architecture | Ruff and validation PASS; release-mode bundle verification with external `ac16f3…d0e` PASS; exact CI scope (`MILAI_ARCHITECTURE_LOCK_SCOPE=bundle`) yielded 19 tests PASS with 1 expected Git-scope skip |
| Frozen test invocation audit | An initial reviewer invocation omitted the required bundle-scope environment and therefore failed the current-project hash-lock node; the explicit release verifier had already passed. Rerunning the exact checked-in CI environment passed. This invocation error is disclosed, not counted as candidate evidence. |
| Archive-aware scan | `/dev/null` credential source; PASS over 363 files / 296 expanded members / 186,187,145 bytes; zero matching path/member, forbidden member, or unsafe archive |
| Shipped Python client | Ruff format/check PASS; mypy PASS for 9 files; **76 passed in 0.64 s** |
| JSON / CI / package metadata | 9 provider JSON files parsed; CI YAML parsed with one provider gate and 20-minute job timeout; package locks/artifacts independently rehashed |

## Real-provider boundary (`OE-F06`)

`OE-F06` remains open independently of the local P0. Candidate.4.5 contains no independently approved
real provider/model and adapter execution, no real 1,000-request capture, no provider-native receipt
verification, no upstream provider billing export/invoice reconciliation, no actual execution-host
attestation, and no same-model external quality/safety decision. These objects are absent, not zero.
The protocol correctly leaves `provider_usage_verified=false` and emits only `*_REVIEW_REQUIRED`.

Therefore B is **NO-GO**. Closing the local helper lifecycle cannot itself close external `OE-F06`;
a separately authorized real run and independent external-evidence decision remain mandatory.

## Final rationale and boundary

- A: **REVISE** because `OE-C43-F01` remains OPEN P0: complete bytes are identified, but the final
  evidence check happens before the privileged network helper's execution lifetime ends.
- B: **NO-GO** because the required real provider/native/billing/quality/host-attestation evidence
  does not exist.
- This record does not claim production readiness, real-data readiness, Beta readiness, or Schema
  freeze. Logical Architecture remains frozen; Runtime remains candidate; Schema remains experimental
  and NO-GO for freeze.

Signature/reference: `/root/af09_reviewer_retry — OE-07 candidate.4.5 independent local re-review decision`
