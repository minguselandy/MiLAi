# OE-07 Agent Execution Optimization candidate.4.3 — independent local re-review

Status: `COMPLETE — LOCAL DECISION REVISE; REAL PROVIDER/BETA NO-GO`  
Review date: `2026-08-18`  
Reviewer: `/root/af09_reviewer_retry`  
Independence: separate independent reviewer; did not author candidate.4.3, its remediation report, protocol, launcher, tests, templates, CI, inventory, or package artifacts. Author conclusions were treated as claims rather than evidence.

## Decision

| Boundary | Independent decision |
| --- | --- |
| A — local synthetic protocol | **REVISE** |
| B — real provider evidence / Beta | **NO-GO — external `OE-F06` remains OPEN** |

The local suite is reproducibly green, and six of the seven candidate.3 findings are closed within the
synthetic boundary. However, the exact execution closure required to close `OE-C3-F02` is not actually
enforced. The passing 1,000-call fixture executes a host program that is absent from its approved
dependency lock. This is an execution-integrity blocker, so the local protocol cannot be accepted.

No provider service was contacted, no real account was used, and no real credential was supplied to an
adapter. All execution evidence below came from repository synthetic fixtures. This review does not
authorize a real provider run.

## Review identity and environment

- Review start: `2026-08-18T11:51:26Z` / `2026-08-18T19:51:26+0800`.
- Evidence completion and immediately-before-write check: `2026-08-18T12:04:24Z` /
  `2026-08-18T20:04:24+0800`.
- Host: Linux `5.15.0-86-generic`, `x86_64`.
- Python `3.11.13`; uv `0.8.3`; Ruff `0.16.3`; mypy `1.20.2`; pytest `8.4.2`.
- Workspace: `/cra/memory/mx_memory/MiLAi`.
- Network/account boundary: local mock adapters and local namespace boundary only; no external service,
  account, billing system, or credential was used.

### Authoritative byte inventory

The authority supplied the inventory digest and entries root out of band. I independently rebuilt the
file set without invoking the writing inventory script, sorted it by repository-relative path, rejected
symlinks, and recomputed every size and SHA-256.

| Check | Expected | Observed |
| --- | --- | --- |
| Inventory SHA-256 | `056f0f164a93189066de0f3d2c388c2246df983b60d3cf4bffd8a4415e793c02` | exact match |
| Entry count | `359` | `359` |
| Canonical entries SHA-256 | `0be317f035701ad32dc3c5c6c9d3706732b25e72bd9a7f08270efb3efab6f3a4` | exact match |
| Listed entries versus live bytes | exact | all 359 path/size/hash objects equal |
| Ordering / uniqueness / symlinks | sorted, unique, no source symlink | PASS |

The same reconstruction was repeated immediately before this file was written and after it was written.
Both checks returned the same inventory SHA-256, 359 entries, the same entries root, and exact live-entry
equality. The review file is outside the inventory include roots.

Additional independently recomputed anchors:

- frozen Logical Architecture manifest:
  `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e`;
- integration package release manifest:
  `d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f`;
- all 6 declared package locks and all 12 declared wheel/sdist artifacts matched their manifest SHA-256;
  all 12 artifact sizes also matched.

Candidate.4.3 core hashes also independently matched the authoritative inventory:

| Artifact | SHA-256 |
| --- | --- |
| `evals/agent_efficiency/provider_ab.py` | `59aec965ddc6e381b1dad28a197968e0adaf18c6319cd950f5f9bb0dbb5dc013` |
| `evals/agent_efficiency/provider_sandbox_exec.py` | `25201b23a1ff48057867d56da9cf38fae98e31c7216ad548fb895664b8d63512` |
| `evals/agent_efficiency/test_provider_ab.py` | `75968d43a94b4085d4fb206c95d19529de55c136990afa20d15b834c396fcd23` |
| `evals/agent_efficiency/PROVIDER_ADAPTER_CONTRACT.md` | `3a992f8606c17f2079a39706db66309ab531d54d54f28ab32268bcf0206af895` |
| `evals/agent_efficiency/provider_ab_workload.json` | `ab5cac3c660835ad1beda1cac56e32b893af476f77b3fb987d4f59d3b8e827e0` |
| `.github/workflows/ci.yml` | `be5cef4a6a7283e3c5aba00c38f7099533e99654da0a4f269728c3ad14838e97` |

## Materials reviewed

Read in full before decision: `AGENTS.md`, `MiLAi_Lean_V1_实施合同.md`,
`MiLAi_Agent执行效率与Token优化设计开发文档_v1.md`, the candidate.3 independent re-review,
the candidate.4.3 remediation report, provider adapter contract, provider runner, sandbox launcher,
provider and benchmark tests, all provider JSON workload/templates, shipped Python-client tool catalog,
release-safety tests, inventory builders/scanner, package release manifest, and the complete relevant CI
job. Source and tests, rather than the author report, were used for the findings below.

## Finding

### OE-C43-F01 — P0 — `OE-C3-F02` exact execution closure remains open

Affected evidence:

- `evals/agent_efficiency/PROVIDER_ADAPTER_CONTRACT.md:18-23` states that executable/source/dependency
  bytes form a closed, pinned execution path.
- `evals/agent_efficiency/provider_ab.py:385-394` deliberately retains a host executable search path.
- `evals/agent_efficiency/test_provider_ab.py:43-93` uses an external host utility during the successful
  mock protocol, while `test_provider_ab.py:155-190` builds the fixture lock only from the runtime's
  dynamic-link dependencies.
- The independent read-only reconstruction found 3 paths in that fixture lock; the external utility
  used by the fixture was not one of them.
- `evals/agent_efficiency/provider_sandbox_exec.py:121-137` pins only dependency paths that were
  declared; it does not make undeclared executable/code-bearing host paths inaccessible.
- `evals/agent_efficiency/provider_ab.py:854-951,1141-1175` correctly hashes and rehashes opened,
  declared FDs, but cannot attest bytes that never entered that FD set.

Adversarial conclusion: the 41-test run passed, including its 1,000-call capture, while an undeclared
host executable participated in that capture. Top-level runtime/source binding and post-run FD hashing
therefore do not establish the claimed transitive execution closure. The same structural gap applies to
code-bearing runtime/helper dependencies unless the execution root itself prevents fallback to
undeclared host bytes. A locally green report can consequently depend on bytes absent from approval,
plan, inventory evidence, and the post-run rehash set.

Required change/evidence:

1. Construct an enforceable closed execution root from the reviewed, digest-bound runtime/source and
   complete transitive code dependency set; do not permit host-path fallback outside that set.
2. Bind and attest all code-bearing runtime, interpreter, sandbox/helper, and transitive dependency
   bytes that may participate in the run, or bind an equivalent immutable image/filesystem identity.
3. Add a synthetic negative test proving that any undeclared executable/code dependency fails closed,
   plus a positive test whose complete closure is independently enumerated and rehashed before and
   after execution.

No operational exploit or external request was performed to establish this finding; it follows from
the passing fixture's own source, lock construction, launcher behavior, and independently resolved file
identities.

## Candidate.3 finding closure audit

| Prior finding | Local result | Independent evidence and conclusion |
| --- | --- | --- |
| `OE-C3-F01` P0 forged reconciliation | `PASS_LOCAL` | Closed schemas and fixed identities are enforced at `provider_ab.py:1979-2055`; exactly 1,000 ordered records and all record/aggregate/gate fields are recomputed at `2061-2277`; report, approval, and plan digests are supplied out of band at `2280-2325`; both normalized and upstream objects are opened and hashed at `2326-2404`. Forged/short/extra-field, absent-upstream, and tolerance-sidecar tests at `test_provider_ab.py:644-747` passed. Reconciliation remains review-required, never PASS. |
| `OE-C3-F02` P0 unbound execution | **`FAIL`** | Runtime/source/declared FDs and the start gate are materially improved, but `OE-C43-F01` proves the executed transitive byte set is not closed. This finding is not closed. |
| `OE-C3-F03` P0 isolation/privacy | `PASS_LOCAL` | Closed inert credential aliases are enforced at `provider_ab.py:561-576`; distinct UID/GID, private mount/PID/network namespaces, FD execution, and the pre-start network gate are constructed at `839-966`; private tmpfs, hidden roots, fixed host/resolver, `no_new_privs`, and privilege drop are at `provider_sandbox_exec.py:79-162`. The UID/workspace, local allowlist, control-name, and secret-reflection tests passed. This does not attest a future real adapter. |
| `OE-C3-F04` P1 post-call authorization | `PASS_LOCAL` | Approval and deterministic plan bind identity/budgets at `provider_ab.py:614-715,1565-1662`; count, per-call input ceiling, maximum-output cost reservation, and cumulative authorization occur before `model_call` at `1812-1841`; returned usage/cost ceilings are then checked at `1843-1858`. Wrong-plan and over-token fixtures produced zero charge-bearing calls. |
| `OE-C3-F05` P1 fake tools/hidden rounds | `PASS_LOCAL` | Catalogs are derived from shipped `create_milai_tools` at `provider_ab.py:285-316`; native identity/usage/terminal/receipt closure and aggregate equality are checked at `1290-1384`; global native IDs and billing coverage are recomputed. Exact shipped-schema and malformed-native-state tests passed. Native authenticity remains external and `provider_usage_verified=false`. |
| `OE-C3-F06` P1 absent CI gate | `PASS_LOCAL` | `.github/workflows/ci.yml:151-183` contains the Python-client-only provider gate with namespace tools, locked runtime setup, Ruff, strict mypy, and the same 41-test command. YAML parsed; `agent-integrations` has a 20-minute job timeout. No hosted run is claimed. |
| `OE-C3-F07` P2 timeout/partial receipt | `PASS_LOCAL` | One monotonic input/output deadline and the response cap are implemented at `provider_ab.py:1036-1097`; process-group termination is bounded at `1099-1111`; partial records/cost/ID state is emitted at `1891-1929`; atomic replacement is at `2461-2481`. Partial-line, non-reading input, late fourth-call, privacy, and atomic-receipt tests passed. |

Local open findings after this review: **P0/P1/P2 = 1/0/0**.

## Commands and results

All commands were run from the repository root unless a working directory is shown. Cache and bytecode
writes were disabled or directed outside the repository.

| Gate | Result |
| --- | --- |
| Independent inventory reconstruction | PASS — 359 exact live entries; canonical root and external inventory digest matched before testing and immediately before review write |
| Package manifest reconstruction | PASS — manifest digest matched; 6/6 locks and 12/12 artifacts matched digest; all artifact sizes matched |
| Provider + benchmark + release-safety union | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:integrations/python-client/src runtime/.venv/bin/pytest -q -p no:cacheprovider evals/agent_efficiency/test_provider_ab.py evals/agent_efficiency/test_benchmark.py tests/test_release_safety.py` — **41 passed in 103.30 s** |
| Provider Ruff | format check and lint over runner, launcher, and provider tests — PASS |
| Provider strict mypy | exact CI environment with `PYTHONPATH=integrations/python-client/src` — PASS, 2 source files |
| Mypy diagnostic correction | An earlier diagnostic invocation omitted the CI `PYTHONPATH` and reported two local-package import-resolution errors. It was not treated as a candidate failure; the exact checked-in command above passed. |
| Frozen architecture | architecture Ruff PASS; `validate_bundle.py` PASS; release-mode `verify_lock.py --scope bundle` with expected `ac16f3…d0e` PASS; 19 tests PASS with 1 expected Git-scope skip |
| Archive-aware scan | `/dev/null` used as the secret source to honor the no-real-credential boundary: PASS over 361 files / 296 expanded members / 186,146,843 source bytes; zero forbidden or unsafe members. Synthetic compressed/nested-secret, forbidden-path, and link cases were separately exercised inside the 41-test suite. |
| CI syntax/coverage | YAML parse PASS; exactly one provider evidence gate in the Python-client matrix; job timeout 20 minutes; local gate command matches the reproduced suite |
| Shipped Python client | Ruff PASS; mypy PASS for 9 files; **76 passed in 0.64 s** |

The allowlist test used only a local namespace boundary. No external provider request or billing lookup
was performed. Test-generated artifacts were confined to temporary pytest locations.

## Real-provider boundary (`OE-F06`)

`OE-F06` remains open independently of the local P0 above. Candidate.4.3 contains no independently
approved provider/model, no independently accepted real adapter closure, no real 1,000-request capture,
no provider-native receipt verification, no real upstream billing export/invoice reconciliation, and no
same-model external quality/safety result. The code explicitly leaves
`provider_usage_verified=false` and emits only `*_REVIEW_REQUIRED` statuses
(`provider_ab.py:59-60,1674-1718,2432-2457`).

Therefore Beta is **NO-GO** even after a future local remediation. Closing the local execution-closure
finding must not be represented as closing external `OE-F06`; a separately approved real run and a new
independent external-evidence decision are still mandatory.

## Final rationale and boundary

- A: **REVISE** because exact execution closure is a core evidence-integrity control and the repository's
  own passing fixture demonstrates that the current lock is not closed.
- B: **NO-GO** because the required real provider/native/billing/quality evidence does not exist.
- This record says nothing about production readiness, real-data readiness, or Schema freeze. Logical
  Architecture remains frozen; Runtime remains candidate; Schema remains experimental and NO-GO for
  freeze.

Signature/reference: `/root/af09_reviewer_retry — OE-07 candidate.4.3 independent local re-review decision`
