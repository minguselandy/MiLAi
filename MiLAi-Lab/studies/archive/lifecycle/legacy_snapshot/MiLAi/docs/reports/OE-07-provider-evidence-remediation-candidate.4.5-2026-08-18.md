# OE-07 provider evidence protocol remediation — candidate.4.5

Status: `READY FOR INDEPENDENT RE-REVIEW — NOT PROVIDER EVIDENCE`  
Date: `2026-08-18` (Asia/Shanghai)  
Boundary: local synthetic fixtures only; no provider credential, external model request or billing
object was used. Runtime remains `0.1.x CANDIDATE`; Schema remains
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.

## Outcome

Candidate.4.4 independently proved the adapter-side Landlock read/execute closure, but the review
kept `OE-C43-F01` open at P0 because the privileged sandbox Python, `unshare`, network helpers and
their 22 observed transitive dynamic dependencies were not part of the approval-bound closure or
post-run evidence. Candidate.4.5 addresses that same finding; it does not claim closure until an
independent reviewer reproduces the evidence.

The v3 manifest adds one external host-execution lock path and digest. The v3 approval binds that
digest plus its canonical entries root, exact file count and enumeration policy. The deterministic
plan and retained capture report carry the same identity. No tool-produced status is `PASS`; a
complete capture and matched billing remain `*_REVIEW_REQUIRED`, and external `OE-F06` remains open.

## Host execution closure

`provider_ab.py host-lock` performs a no-network, no-provider enumeration of the actual local
privileged userspace execution base:

1. exact sandbox launcher and sandbox Python runtime;
2. every file-backed module and cache object loaded by an isolated `-I -S -B` launcher import probe;
3. `unshare` and every installed `slirp4netns`/`nsenter`/`nft`/`ip` helper;
4. the recursively resolved ELF closure of every executable, extension and library above;
5. the exact Linux release/machine and Python cache tag used by the enumeration.

The launcher is statically inspectable: imports nested below module scope and dynamic
`__import__`/`import_module` calls are rejected, so a future launcher cannot silently add a runtime
import outside the trace contract. Entries have a closed path/size/SHA-256/sorted-role schema and a
canonical root. On this review host, independent generation produced 113 unique files: 79
file-backed Python import objects, 27 dynamic dependencies, the launcher/runtime and five helper
roles. That includes the helper dependencies absent from candidate.4.4.

The runner does not trust a hand-written list. Every plan/run/reconciliation independently rebuilds
the expected closure and requires byte-for-byte equality with the externally hashed lock. A negative
fixture deletes one real dynamic dependency, recomputes the lock root, rewrites the manifest and
issues a fresh internally consistent approval. Plan creation still fails before adapter or provider
execution because the independently enumerated closure differs. This is the requested proof that
fresh signatures over an incomplete helper set cannot create accepted evidence.

## Validation/run and post-run binding

Immediately before namespace creation the runner opens every host-closure path with
`O_NOFOLLOW|O_CLOEXEC`, requires a regular file and hashes the opened descriptor. It retains those
descriptors in the parent for the complete capture. After the PID namespace and network helper are
stopped, it verifies for every entry:

- the retained descriptor's device, inode, size and SHA-256;
- the original path's regular-file state, device, inode, size and SHA-256;
- equality to the out-of-band approval/plan root and count.

A missing, unreadable, in-place modified, path-replaced, additional or omitted file fails closed.
The capture's closed `execution.host_execution` object records the policy, count, root and both
`pre_execution_verified=true` and `post_execution_revalidated=true`; reconciliation recomputes and
requires those exact values. Adapter dependencies remain separately copied from verified FDs,
bind-mounted and Landlock restricted as in candidate.4.4.

The kernel remains an explicit operator host-TCB boundary. Candidate.4.5 binds the observed kernel
release/machine and closes the local userspace helper/runtime byte set; it does not turn local
synthetic evidence into immutable-host or real-provider attestation. A real run still requires an
operator-approved execution host and a separate independent provider decision.

## Acceptance evidence

| Gate | Result |
| --- | --- |
| Provider protocol + deterministic benchmark + release safety | **44/44 PASS in 131.98 s**, with pytest cache and repository bytecode disabled |
| New closure positives | exact independent host lock equality; canonical count/root; required launcher/runtime/import/unshare/dynamic roles; host-only dependency delta versus adapter lock; plan binding PASS |
| New closure negative | remove a real dynamic entry, recompute root/manifest/fresh approval: plan fails on independent closure mismatch before adapter/provider execution |
| Full isolated capture | 1,000-call deny-all capture retains exact host root/count and pre/post verification booleans; existing privacy/identity/gate assertions PASS |
| Non-repository cwd | full isolated capture from `/tmp`: 1 PASS in 10.83 s |
| Deadline regression | partial-line fixture remains below the unchanged two-second assertion; process-group teardown was shortened without relaxing the deadline |
| Provider static | Ruff format/check PASS; strict mypy PASS for runner and launcher |
| Shipped Python client | Ruff format/check PASS; mypy 9 source files PASS; 76/76 tests PASS |
| Frozen Logical Architecture | validate PASS; release external-anchor bundle lock PASS; 19 tests PASS with one expected Git-scope skip |
| Archive-aware secret scan before this report | PASS over 362 files / 296 expanded members / 17 exact local secret values; zero matching path/member, forbidden member or unsafe archive |
| JSON/CI syntax | all provider example JSON parsed; checked-in CI YAML parsed; existing provider union step covers the changed suite |

## Candidate identity before inventory generation

| Artifact | SHA-256 |
| --- | --- |
| `evals/agent_efficiency/provider_ab.py` | `7110547864a4707070b1f0552902f0fdbb2bc922d4ea4f9ccf939950cb007874` |
| `evals/agent_efficiency/provider_sandbox_exec.py` | `f3d48c0652500f46ca40f9fedcb4c9dced4a63d70e2a46bf31e150d2c4ea73c4` |
| `evals/agent_efficiency/test_provider_ab.py` | `92cb45e88a8bc08c27c1e595170893bede7b8584445c88bda10f14a7903ecc74` |
| `evals/agent_efficiency/PROVIDER_ADAPTER_CONTRACT.md` | `fd01f081a5bc6dd10b041b6a865d598a5fb4aa0739fd6ad6d061616042149a42` |
| manifest example | `08e286d26801fd141a257954c8194a70ac577b6c460a16c6ca6a269ee7c129e8` |
| approval example | `ff4a41e065b7d73e336508d72c9cb444c3b01c418a90415c2bcfc3977e6b31a6` |
| host-execution-lock example | `65036e23a5b45d711a285c0319ad4770098b7a200b6a50075ae17f7884ff44d0` |
| `.github/workflows/ci.yml` | `be5cef4a6a7283e3c5aba00c38f7099533e99654da0a4f269728c3ad14838e97` |

Frozen/package anchors remained unchanged:

- Logical Architecture manifest:
  `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e`;
- integration package release manifest:
  `d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f`.

The inventory generated after this report is the authoritative candidate.4.5 full-byte identity.

## Remaining external gate

`OE-F06` remains OPEN. There is still no independently approved real provider/model, reviewed
adapter, real native receipt, target-provider billing export, same-model external quality result or
independent provider acceptance. These facts are absent, not zero. Candidate.4.5 can close only the
local `OE-C43-F01` userspace execution-closure condition; Beta remains NO-GO until the separately
authorized 1,000-call real run and external review exist.
