# OE-07 Agent Execution Optimization candidate.4.6 — independent local re-review

Status: `COMPLETE — LOCAL SYNTHETIC PROTOCOL PASS; REAL PROVIDER/BETA NO-GO`  
Review date: `2026-08-18`  
Reviewer: `/root/af09_reviewer_retry`  
Independence: same independent reviewer who originally recorded `OE-C43-F01`; did not author
candidate.4.6, its remediation report, inventory, protocol, runner, launcher, tests, examples, CI,
frozen architecture, or package artifacts. Author statements and test names were treated as claims,
not evidence.

## Decision

| Boundary | Independent decision |
| --- | --- |
| A — local synthetic protocol | **PASS** |
| B — real provider evidence / Beta | **NO-GO — external `OE-F06` remains OPEN** |

Candidate.4.6 satisfies the original `OE-C43-F01` P0 acceptance conditions. In an independently
instrumented run of the real checked-in local allowlist fixture, the adapter PID namespace was
terminal before persistent-helper shutdown, the real network helper was terminal before every final
execution/host hash, and all 113 retained host descriptors remained open until both processes had
been waited. The post-execution flag remained false throughout final hashing and became true only
after all final FD/path comparisons succeeded. Independent wait-error, bounded TERM/KILL still-alive,
and adapter-still-alive substitutes all skipped final hashing, left the flag false, produced
`FAIL_PARTIAL`, and could not pass reconciliation.

The independently rebuilt host closure remains exactly 113 files with canonical root
`98e3756fa4cc1a306ef03d898099b23bfa389d3c657ea4d19e388dce6f2ca207`.
Missing and additional closure entries still fail under freshly recomputed lock, manifest and
approval identities. No local P0/P1/P2 remains open; **`OE-C43-F01 — CLOSED P0`**. No new protocol
finding was identified.

This is not real provider evidence. No provider service, external model, real account, real billing
service, or real credential was accessed. A local PASS cannot close `OE-F06` or authorize Beta.

## Review identity and byte inventory

- Review start: `2026-08-18T13:42:12Z` / `2026-08-18T21:42:12+0800`.
- Evidence completion / immediately-before-write check: `2026-08-18T13:53:40Z` /
  `2026-08-18T21:53:40+0800`.
- Host: Linux `5.15.0-86-generic`, `x86_64`.
- Python `3.11.13`; uv `0.8.3`; Ruff `0.16.3`; mypy `1.20.2`; pytest `8.4.2`.
- Workspace: `/cra/memory/mx_memory/MiLAi`.
- Boundary: local/synthetic only; no external provider/account/credential request.

The inventory digest, count and canonical root were supplied out of band. I independently traversed
the declared include roots, applied only the declared cache/venv exclusions, rejected symlinks,
recomputed each path/size/SHA object, sorted it, and recomputed the canonical JSON entries digest.
The inventory builder was not invoked to overwrite or bless the candidate.

| Identity check | Expected | Independently observed |
| --- | --- | --- |
| Inventory SHA-256 | `defecfec508d624d4c8a7d1d5f490863c5dc9c73a880c0e8e45453c800589bf7` | exact |
| Entry count | `362` | `362` |
| Canonical entries SHA-256 | `0c1888e0f1f16f3e9729c2dbe8603259c3d6383a95073bcaff4cfad11a51de56` | exact |
| Listed objects versus live bytes | exact | all 362 path/size/hash objects equal |
| Ordering / uniqueness / source symlinks | sorted / unique / none | PASS |
| Immediately-before-write reconstruction | same identity | PASS |
| After-review-write reconstruction | same identity | PASS at `2026-08-18T13:57:04Z` / `2026-08-18T21:57:04+0800` — inventory SHA, 362 entries, canonical root and every live object unchanged |

The review path is outside the inventory include roots. Supplied and inherited anchors independently
matched:

| Artifact | SHA-256 |
| --- | --- |
| candidate.4.6 author report | `11fefe51d33c63f7642c8b24a69cc3a4c3e3a3358700e6a4339f4f71e577009b` |
| `evals/agent_efficiency/provider_ab.py` | `694555f1bc3f6143cfce6f66e57639069e578fcb3456deb2520cbd4071898184` |
| `evals/agent_efficiency/provider_sandbox_exec.py` | `f3d48c0652500f46ca40f9fedcb4c9dced4a63d70e2a46bf31e150d2c4ea73c4` |
| `evals/agent_efficiency/test_provider_ab.py` | `581bfd366581feb95fd06be8d8d5e8c4510e2db8df3057ddcd8963c670a134e9` |
| `evals/agent_efficiency/PROVIDER_ADAPTER_CONTRACT.md` | `63552b57f0025b2553d256c77c7ed8f90ab9494912dc9080560d704f972a632c` |
| `.github/workflows/ci.yml` | `be5cef4a6a7283e3c5aba00c38f7099533e99654da0a4f269728c3ad14838e97` |
| candidate.4.5 independent review | `9a4ddc90b2ebce0c7bdd003df257777afc44f67b2bc46ee3925b313dd8329c45` |
| integration package manifest | `d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f` |
| frozen Logical Architecture manifest | `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e` |

All 6 package locks and 12 wheel/sdist artifacts matched the package manifest's declared SHA-256;
all 12 artifact sizes matched.

## Materials and method

Read in full before decision: `AGENTS.md`, the implementation contract, the optimization design,
the candidate.4.5 independent record, complete candidate.4.6 author report, provider contract, runner,
sandbox launcher, provider and benchmark tests, all provider JSON examples and workload, relevant
Python-client implementation/tests, release-safety scanner/tests, inventory and package builders,
package manifest, and the provider CI step. The lifecycle decision rests on implementation order and
independently observed process/descriptor state rather than the author report.

## `OE-C43-F01` closure decision

### Result: **CLOSED P0**

Static implementation evidence:

- `provider_ab.py:1392-1415` performs bounded TERM, then KILL when needed, catches termination/wait
  errors, and returns true only when the helper has a terminal `poll()` result.
- `provider_ab.py:1427-1456` first completes adapter shutdown, closes parent communication handles,
  requires a terminal adapter state, and then synchronously stops the persistent helper.
- `provider_ab.py:1459-1498` performs execution-FD and all host FD/original-path comparisons only
  when both stop results are true. It compares device, inode, size and SHA-256 and sets the post flag
  only after the loop succeeds.
- `provider_ab.py:1499-1518` closes execution and host descriptors only after those checks, then
  propagates either nonterminal result. Changed/unreadable byte failures follow at `1519-1534`.
- `provider_ab.py:2175-2328` converts lifecycle errors into privacy-bounded `FAIL_PARTIAL` output;
  `2368-2702` requires a successful complete status and exact true host evidence, so a partial result
  cannot be accepted; reconciliation begins from that validator at `2705`.
- The contract's ordering at `PROVIDER_ADAPTER_CONTRACT.md:28-38` now agrees with code behavior.

Independent real-local lifecycle trace:

| Observation | Result |
| --- | --- |
| Synthetic allowlist boundary | Local fixture exchange completed; capture remained `PROVIDER_CAPTURE_COMPLETE_REVIEW_REQUIRED` |
| Adapter state before helper stop | terminal (`returncode=0`) |
| Actual helper state before/after stop | running before stop; terminal after bounded wait (`returncode=-15`) |
| Adapter terminal at every final hash | true |
| Helper terminal at every final hash | true |
| Retained host FDs during final hashes | exactly 113 at every observation |
| Post flag during every final hash | false |
| Final hash calls | 16 execution FD hashes; 113 host FD hashes; 113 original-path hashes |
| Final successful state | post flag true; retained host-FD collection empty only after validation |

This directly replays the candidate.4.5 counterexample with the actual local namespace/helper path.
The old defect is absent: the helper no longer executes during or after the final hash window.

Independent deterministic failure substitutes did not rely on the author test name:

| Condition | Result |
| --- | --- |
| Helper wait raises an OS-level error | `ProviderEvidenceError`; post false; zero final hashes |
| TERM times out, KILL/wait returns, but helper still reports alive | same fail-closed result |
| Adapter still reports alive after shutdown path | adapter-stop error; post false; zero final hashes |
| Full 1,000-call run with injected helper-stop false | `FAIL_PARTIAL`; 1,000 already-validated records retained; post false; reconciliation rejects status |

All failure cases also closed retained descriptors during cleanup. No error path asserted post evidence
or upgraded partial evidence to review-required complete evidence.

### 113-file closure non-regression

- `provider_ab.py:626-680` still includes the launcher, sandbox runtime, namespace/network helpers,
  isolated Python import closure and recursively resolved ELF dependencies; `684-703` requires exact
  equality to a newly rebuilt object.
- A separate AST/import/recursive-ELF enumerator found 5 module-scope import nodes, 79 file-backed
  import/cache objects, 27 dynamic dependencies and 113 unique files. Its full object and root
  `98e3756f...a207` exactly matched the runner.
- The checked-in fresh-approval missing-entry negative passed. An independent added-entry case
  recomputed the list root, lock digest, manifest digest and approval; plan construction still failed
  with the independently enumerated-closure error. Thus internally coordinated over- and under-set
  submissions cannot self-authorize.
- Independent temporary-file cases continued to reject same-size content change, same-content inode
  replacement, and original-path disappearance; the post flag remained false.
- Root/count/policy remain bound through approval, deterministic plan, capture report and
  reconciliation (`provider_ab.py:684-703, 842-979, 1949-2096, 2680-2702`).

## F01–F07 independent matrix

| Finding | Local result | Independent conclusion |
| --- | --- | --- |
| `OE-C3-F01` forged reconciliation | `PASS_LOCAL` | Closed schemas, exact identity, record/gate recomputation, upstream artifact binding, request coverage, approval/plan digests, cost and tolerance are enforced. Forged complete-report and host-root mutations fail closed; statuses never say PASS. |
| `OE-C3-F02` unbound execution | `PASS_LOCAL` | Exact runtime/source/dependency/113-host-file execution closure is externally digest-bound and independently rebuilt. Both adapter and helper are terminal before final revalidation; `OE-C43-F01` is closed. |
| `OE-C3-F03` isolation/privacy | `PASS_LOCAL` | Distinct UID/GID, mount/PID/network namespaces, hidden workspace/root, closed environment, Landlock execution/read policy, secret reflection rejection, deny-all and declared local allowlist nodes passed. This does not attest a future real adapter. |
| `OE-C3-F04` pre-call authorization | `PASS_LOCAL` | Approval and deterministic plan bind request/input/output/cost ceilings. Per-call token and conservative cost reservation checks precede every model call (`provider_ab.py:2154-2239`). Wrong-plan and over-budget controls issue no charge-bearing call. |
| `OE-C3-F05` shipped tool/native state | `PASS_LOCAL` | Tool schemas derive from shipped code; native IDs, usage sums, terminal/finish state, receipt digest and coverage are checked. Exact-schema and nonterminal/hidden-round negatives pass. Provider authenticity remains external and explicitly unverified. |
| `OE-C3-F06` CI coverage | `PASS_LOCAL` | `.github/workflows/ci.yml:158-183` parses and contains exactly one provider gate with namespace helpers, frozen Runtime setup, provider Ruff, strict mypy, exact union inputs and a 20-minute job timeout. No hosted-run claim is made. |
| `OE-C3-F07` total timeout/partial receipt | `PASS_LOCAL` | One monotonic run deadline, bounded process shutdown, validated-only partial records and atomic output remain enforced. Partial-line, non-reading input, late-call, privacy and atomic-output nodes passed; lifecycle errors remain `FAIL_PARTIAL`. |

Local open finding count: **P0/P1/P2 = 0/0/0**.

## Reproduced commands and results

All commands ran from the repository root unless noted. Bytecode and pytest cache writes were
disabled; reviewer-generated adversarial inputs and reports were outside the repository.

| Gate | Result |
| --- | --- |
| Independent inventory reconstruction | PASS — external digest, 362 live entries, canonical root, sorted/unique paths and no source symlink all matched |
| Provider + benchmark + release-safety union | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:integrations/python-client/src runtime/.venv/bin/pytest -q -p no:cacheprovider evals/agent_efficiency/test_provider_ab.py evals/agent_efficiency/test_benchmark.py tests/test_release_safety.py` — **45 passed in 133.24 s** |
| Test collection | PASS — exactly 45 union nodes collected |
| Non-repository cwd | Full isolated 1,000-call capture node from `/tmp` — **1 passed in 10.88 s** |
| Actual helper/adapter lifecycle | PASS — real checked-in local allowlist helper terminal before all final hashes; adapter terminal; 113 FDs retained; post false during hashes, true only after validation |
| Shutdown failure propagation | PASS — helper wait error, TERM/KILL still-alive and adapter still-alive substitutes all skipped final hash, kept post false and raised; full-run failure became `FAIL_PARTIAL` and reconciliation rejected it |
| Independent host closure | PASS — 5 module imports, 79 import/cache objects, 27 recursive ELF dependencies, 113 files, root `98e375…a207`, exact complete-object match |
| Closure adversarial checks | PASS — omission and independent addition both failed despite fresh coordinated internal identities |
| FD/path mutation checks | PASS — content change, inode replacement and disappearance all rejected with post false |
| Provider static | Ruff format/check PASS for runner, launcher and provider test; strict mypy PASS for both source files |
| Frozen architecture | Ruff format/check PASS; validation PASS; release-mode lock verification with external `ac16f3…d0e` PASS; exact CI bundle-scope unittest invocation: 19 PASS with one expected Git-scope skip |
| Shipped Python client | Ruff format/check PASS; mypy PASS for 9 files; **76 passed in 0.60 s** |
| Archive-aware secret scan | `/dev/null` secret source; PASS over 364 files, 296 expanded members, 2,873,815 archive-uncompressed bytes and 186,198,839 scanned bytes; zero secret match, forbidden member or unsafe archive |
| JSON / CI | 9 provider JSON objects parsed; CI YAML parsed; exactly one provider gate with 20-minute total job timeout |
| Package identity | PASS — package manifest, 6 locks, 12 artifacts and all declared sizes/hashes exact |

Informational reproducibility note: the author report's unscoped statement that 110 Markdown files all
have a final newline was not reproducible as a whole-candidate-inventory assertion. The inventory has
98 Markdown entries; one unchanged third-party model README lacks a final LF and none contains NUL.
This is not executable protocol evidence, does not affect the changed lifecycle, and is not counted as
a local finding. Provider JSON, CI YAML, frozen architecture and archive gates passed.

## Real-provider boundary (`OE-F06`)

`OE-F06` remains OPEN. Candidate.4.6 contains no independently approved real provider/model and
adapter execution, no real 1,000-request provider capture, no independently verified provider-native
receipt, no upstream provider billing export/invoice reconciliation, no independently attested real
execution host, and no same-model external quality/safety decision. These objects are absent, not
zero. The protocol correctly keeps `provider_usage_verified=false` and emits only
`*_REVIEW_REQUIRED` for successful local fixtures.

Therefore B is **NO-GO**. Closing `OE-C43-F01` is necessary local protocol evidence but cannot replace
the separately authorized external execution and review needed to close `OE-F06`.

## Final rationale and boundary

- A: **PASS** because the exact 113-file closure remains closed and the adapter plus every persistent
  helper are demonstrably terminal before the final FD/path evidence window; shutdown uncertainty is
  partial failure and cannot reconcile.
- B: **NO-GO** because required real provider/native/billing/quality/host-attestation evidence does
  not exist; `OE-F06` remains OPEN.
- This record does not claim production readiness, real-data readiness, Beta readiness, provider
  authenticity, or Schema freeze. Logical Architecture remains frozen; Runtime remains candidate;
  Schema remains experimental and NO-GO for freeze.

Signature/reference: `/root/af09_reviewer_retry — OE-07 candidate.4.6 independent local re-review decision`
