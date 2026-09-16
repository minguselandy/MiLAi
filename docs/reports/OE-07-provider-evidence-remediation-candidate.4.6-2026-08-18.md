# OE-07 provider evidence protocol remediation — candidate.4.6

Status: `READY FOR INDEPENDENT RE-REVIEW — NOT PROVIDER EVIDENCE`  
Date: `2026-08-18` (Asia/Shanghai)  
Boundary: local synthetic fixtures only; no provider credential, external model request or billing
object was used. Runtime remains `0.1.x CANDIDATE`; Schema remains
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.

## Outcome

Candidate.4.5 independently closed the host-byte enumeration part of `OE-C43-F01`: the reviewer
separately reproduced the exact 113-file closure, 79 file-backed import objects, 27 recursive ELF
dependencies and canonical root. It nevertheless retained the P0 because the persistent
`slirp4netns` helper remained alive during every final host hash, while the code already set
`post_execution_revalidated=true` and closed retained FDs before terminating that helper.

Candidate.4.6 changes only that execution-lifecycle boundary and the evidence around it. It does not
change the provider workload, adapter JSONL wire protocol, approval identity, host closure, Runtime,
Schema, frozen Logical Architecture or accepted candidate.2 optimization behavior. The local author
claim is that the original `OE-C43-F01` acceptance conditions are now satisfied; only independent
re-review may close it.

## Lifecycle correction

`AdapterProcess.__exit__` now uses this strict order:

1. request adapter shutdown; if needed, terminate/kill and wait for the complete PID namespace;
2. close the parent selector and pipes, then require the adapter process to have a terminal status;
3. TERM the persistent network helper, wait 0.5 seconds, then KILL and wait one additional second if
   necessary; require a terminal status;
4. only after both execution bodies are stopped, hash every retained execution FD and all 113 host
   closure FDs and original paths, including device/inode/size checks;
5. set `post_execution_revalidated=true` only when every final check succeeds;
6. close execution and host FDs, then propagate any shutdown or revalidation failure.

If the adapter or helper cannot be confirmed stopped, final post assertion is skipped, the flag
remains false, FDs are cleaned up, and `ProviderEvidenceError` becomes a privacy-bounded
`FAIL_PARTIAL` record. No reconciliation can accept that record. This removes the candidate.4.5
interval in which a privileged helper could continue executing after the last hash.

The allowlist setup readiness bound increased from three to eight seconds to avoid false setup
failures on a contended local host. This does not change adapter request deadlines, approved IPs,
network policy, firewall order, provider budget or any egress permission.

## Order-sensitive acceptance tests

The existing real local allowlist fixture now instruments the actual process object plus final FD
and path hash calls. It requires the real `slirp4netns` process to have a terminal `poll()` result at
every final hash observation, then completes all 1,000 synthetic logical calls and retains a true
post flag. Candidate.4.5 would fail this assertion because its helper was alive for all observations.

A second deterministic negative overrides only the bounded helper-stop result. The adapter is
started in the normal namespace path, but finalization reports that the helper cannot be confirmed
stopped. The context exit must raise `provider network helper did not stop before final byte
revalidation`, and `post_execution_revalidated` must remain false. This proves a liveness/termination
failure cannot yield accepted capture evidence.

The candidate.4.5 missing/extra closure tests remain unchanged: an incomplete or additional entry
still fails despite a freshly recomputed lock, manifest and approval. Thus candidate.4.6 preserves
both exact byte-set binding and lifecycle-complete post evidence.

## Reproduced local gates

| Gate | Result |
| --- | --- |
| Provider + benchmark + release-safety union | **45/45 PASS in 133.56 s**, with pytest cache and repository bytecode disabled |
| Real helper shutdown order | local allowlist capture PASS; helper terminal at every final FD/path hash observation; 1,000 calls complete |
| Failed helper shutdown | deterministic substitute raises before post assertion; post flag false |
| Deadline regression | partial-line fixture remains below the unchanged two-second assertion |
| Non-repository cwd | full 1,000-call isolated capture from `/tmp`: **1 PASS in 10.69 s** |
| Provider static | Ruff format/check PASS; strict mypy PASS for runner and launcher |
| Shipped Python client | Ruff format/check PASS; mypy 9 source files PASS; **76/76 tests PASS** |
| Frozen Logical Architecture | Ruff/validate/release external-anchor lock PASS; 19 tests PASS with one expected Git-scope skip |
| Archive-aware secret scan | PASS over 364 files / 296 expanded members / 17 exact local secret values; zero match/forbidden/unsafe |
| JSON/CI/Markdown structure | all provider examples and CI YAML parse; 110 Markdown files have final newline and no NUL |

These author gates do not substitute for independent reproduction or the final byte-drift check.

## Candidate identity before inventory generation

| Artifact | SHA-256 |
| --- | --- |
| `evals/agent_efficiency/provider_ab.py` | `694555f1bc3f6143cfce6f66e57639069e578fcb3456deb2520cbd4071898184` |
| `evals/agent_efficiency/provider_sandbox_exec.py` | `f3d48c0652500f46ca40f9fedcb4c9dced4a63d70e2a46bf31e150d2c4ea73c4` |
| `evals/agent_efficiency/test_provider_ab.py` | `581bfd366581feb95fd06be8d8d5e8c4510e2db8df3057ddcd8963c670a134e9` |
| `evals/agent_efficiency/PROVIDER_ADAPTER_CONTRACT.md` | `63552b57f0025b2553d256c77c7ed8f90ab9494912dc9080560d704f972a632c` |
| `.github/workflows/ci.yml` | `be5cef4a6a7283e3c5aba00c38f7099533e99654da0a4f269728c3ad14838e97` |
| candidate.4.5 independent review | `9a4ddc90b2ebce0c7bdd003df257777afc44f67b2bc46ee3925b313dd8329c45` |

Frozen/package anchors remain unchanged:

- Logical Architecture manifest:
  `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e`;
- integration package release manifest:
  `d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f`.

The inventory generated after this report is the authoritative candidate.4.6 full-byte identity.

## Remaining external gate

`OE-F06` remains OPEN. Candidate.4.6 contains no independently approved real provider/model, real
adapter execution, native receipt verification, provider billing export/invoice, same-model external
quality decision or independently attested real execution host. Local closure and shutdown evidence
cannot replace those external objects. Beta remains NO-GO until the separately authorized 1,000-call
real run and independent provider-evidence acceptance exist.
