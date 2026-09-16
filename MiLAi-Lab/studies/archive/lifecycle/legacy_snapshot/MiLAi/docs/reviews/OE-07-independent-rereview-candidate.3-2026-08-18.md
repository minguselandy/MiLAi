# OE-07 candidate.3 provider evidence readiness — independent re-review

## Decision

| Boundary | Independent decision |
| --- | --- |
| Candidate.3 local provider protocol/tool | **REVISE** |
| Real provider evidence / Beta | **NO-GO — `OE-F06` remains OPEN** |
| Candidate.2 local optimization core | Previous local/synthetic disposition is not revoked by this focused review; candidate.3's provider path is not accepted |
| Runtime / Schema | Runtime remains `0.1.x CANDIDATE`; Schema remains `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE` |

Reviewer: `/root/af09_independent_review`  
Independence: did not author candidate; reviewed current bytes and reproducible behavior rather than
accepting the author readiness report or test names as evidence.  
Review window: `2026-08-18T09:53:02Z` through `2026-08-18T10:13:30Z`  
Environment: Linux `5.15.0-86-generic` x86_64; Python `3.11.13`; Ruff `0.16.3`; mypy
`1.20.2`; pytest `8.4.2`.  
Data/network boundary: temporary synthetic values and local fake adapters only. No provider request
was made, no real credential value was printed or retained, and no candidate file was modified.

Candidate.3 is not ready to execute an accepted real-provider evidence run. Three independently
reproduced P0 paths allow unreviewed or entirely fabricated inputs to produce provider-looking
capture/final states, and the adapter isolation does not establish the claimed canonical-credential
boundary. Passing the checked-in tests is not dispositive: one positive test itself uses an
`approved-mock-provider` and asserts final `PASS`.

Open finding counts:

| P0 | P1 | P2 |
| ---: | ---: | ---: |
| 3 | 3 | 1 |

No condition in this review closes `OE-F06`. Even after all local findings are fixed and independently
accepted, a real approved provider/model run, native usage, target-tokenizer measurements, actual
model-call accounting, external billing reconciliation and same-model quality/safety evidence are
still required before Beta.

## Candidate identity and inventory

Hashes were recorded before the review file existed. An independent inventory implementation (it did
not import `build_ua_inventory` or `build_oe_inventory`) reconstructed the declared include roots,
pruned only the declared cache/venv parts, rejected symlinks and unsafe paths, and recomputed each
file's byte size and SHA-256 plus the sorted canonical entries root.

| Object | Expected | Before review write | After review write |
| --- | --- | --- | --- |
| `docs/reports/OE-current-byte-inventory-2026-08-18.json` | `4256a342a68a528a3e78fcfa3a014bd4b7875e69e2f2b9396d70180c24bb2b0b` | exact | exact |
| Inventory entries | `356` | 356, every object exact | 356, every object exact |
| Entries root | `2905a7c4c3b95d6b55a8acecb1e1afc47423704cf6f45f3db70d98a59fd60637` | exact | exact |
| `integrations/package-release-manifest.json` | `d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f` | exact | exact |
| Frozen `architecture/v1.0/architecture_manifest.json` | `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e` | exact | exact |

The inventory was sorted and unique, with no missing include target, symlink, absolute/traversal path,
cache, venv or live `.env` entry. This review is under `docs/reviews`, outside the declared candidate
inventory. The nine provider artifact hashes in the readiness report were also recomputed exactly.

## Findings

### OE-C3-F01 — P0 — unauthenticated reconciliation can manufacture final `PASS`

Artifacts: `evals/agent_efficiency/provider_ab.py:1101-1205`,
`evals/agent_efficiency/test_provider_ab.py:28-87,432-490`,
`MiLAi_Agent执行效率与Token优化设计开发文档_v1.md:1117-1123`.

`reconcile_billing()` trusts any JSON object whose format and status strings look like a pending
capture. It does not validate the capture schema, the exact 1,000 records, `provider_usage_verified`,
`same_model_ab`, the required gate-name set, workload/manifest/approval/source/lock identities, or
recompute aggregates and gates from records. `all(report["gates"].values())` accepts an empty map.
The upstream artifact is not opened or hashed; only an arbitrary 64-hex string inside the normalized
file is syntax-checked. Billing tolerance is caller supplied and unbounded.

Independent `/tmp` counterexample, with no adapter or provider execution:

- a hand-written pending report had one fabricated request ID, no provider-usage field and `gates={}`;
- the normalized billing file had one record, an arbitrary syntactically valid upstream hash and an
  actual total of 999 against report expected total 0;
- a self-authored sidecar supplied tolerance 1000;
- `reconcile_billing()` returned `status=PASS`, `billing_reconciled=true`.

The checked-in positive path independently confirms the broader issue: its adapter calls itself
`approved-mock-provider` (`test_provider_ab.py:53-86`) and the test asserts final `PASS`
(`test_provider_ab.py:432-490`). The substring filter in `provider_ab.py:926-930` does not reject
`mock`, and a name blacklist cannot authenticate a provider in any case. This directly contradicts
the design rule that fixtures cannot set the real-provider gate.

Required change and acceptance evidence:

- validate a strict, closed capture schema and exact required gate set; require exactly 1,000 unique
  records and recompute all aggregates/gates from immutable capture records;
- bind reconciliation to an independently anchored capture/approval digest rather than a status
  string in caller-authored JSON;
- authenticate the approved provider-specific adapter and native receipts; do not infer authenticity
  from provider naming;
- require the actual upstream export/invoice as a separately verified external object (or a trusted
  provider-signed attestation), verify its digest, and bind normalization provenance;
- bind a small reviewed tolerance and the actual-cost ceiling to operator approval;
- add negative tests proving a hand-written report, empty/missing gates, fewer than 1,000 records,
  mock/fake adapter, absent upstream artifact and oversized tolerance cannot exit zero or return PASS.

### OE-C3-F02 — P0 — the approved/hash-bound adapter is not necessarily the executed program

Artifacts: `evals/agent_efficiency/provider_ab.py:325-444,533-542`,
`evals/agent_efficiency/PROVIDER_ADAPTER_CONTRACT.md:28-40`.

The only source-to-command check is that the resolved `adapter_source_path` string appears somewhere
in argv (`provider_ab.py:363-366`). It need not be the program interpreted or executed. The executable,
full argv and runtime dependency environment are not hash-bound; the dependency lock is hashed but
never used to create or verify that environment. The approval path and expected approval hash come
from the same caller-authored manifest, while `approved_by` and `approved_at` need only be non-empty
strings. This is circular provenance, not an independent authorization anchor.

Independent no-network counterexample:

- the manifest/approval bound a harmless decoy source and a claimed lock;
- argv executed a different unbound Python file and included the decoy only as an ignored argument;
- the manifest also included a split `--api-key VALUE` pair, which bypassed the per-argument secret
  regex;
- `_manifest()` accepted it, and the unbound fake produced
  `PROVIDER_CAPTURE_PASS_BILLING_PENDING` with `provider_usage_verified=true`.

Required change and acceptance evidence:

- bind an exact executable/argv/adapter/dependency closure to an out-of-band approval digest or
  signature supplied independently of the manifest;
- use a closed command schema (for example, one pinned interpreter plus the exact bound source), or
  hash and verify every executable/code-bearing argv member; reject interpreters/shells and inert
  source placement that escape that schema;
- construct or attest the executed environment from the reviewed lock, and prevent validation/run
  substitution or TOCTOU;
- reject both joined and split credential options and compare argv against all declared secret values
  without writing those values to diagnostics;
- reproduce with a decoy-source/alternate-program fixture and require fail-closed before process
  start.

### OE-C3-F03 — P0 — canonical-secret isolation and report privacy are not established

Artifacts: `evals/agent_efficiency/provider_ab.py:34-43,381-474,533-542,628-682,1034-1051`,
`MiLAi_Agent执行效率与Token优化设计开发文档_v1.md:1068-1076,1115-1116`,
`evals/agent_efficiency/PROVIDER_ADAPTER_CONTRACT.md:28-32,118-124`.

The narrow child environment does not isolate the filesystem. `Popen` inherits the repository cwd
and runs as the reviewing user, so an adapter can read `runtime/.env` and other same-user files even
when their variables were removed from `env`. The canonical-name filter also allows standard
PostgreSQL names such as `PGPASSWORD`. In the result path, adapter-controlled
`provider_request_id` and `finish_reason` are retained verbatim with no length, format, enum or
known-secret rejection.

The independent fake adapter did not read any real secret content; it only checked file visibility.
It observed that `runtime/.env` was reachable, received a synthetic value through an accepted
`PGPASSWORD` declaration, returned that synthetic value as part of each request ID, and the final
report retained it. It also returned a non-`stop` finish reason for every request, and every gate still
passed. This disproves the report's unconditional `secret_values_retained=false` assertion.

Required change and acceptance evidence:

- execute reviewed provider code in an OS-level sandbox/different identity with no repository, home,
  runtime data, socket or credential-file access except explicitly mounted adapter inputs; constrain
  egress to the approved provider boundary;
- close the canonical environment denylist over PostgreSQL and project aliases, and make proxy
  credential handling explicit and approval-bound;
- treat all adapter-returned strings as tainted: enforce provider-specific ID format/length, a closed
  finish-reason contract, and in-memory rejection/redaction against every supplied secret before any
  report write;
- add a fixture that attempts cwd/absolute `.env` access, `PG*` credential inheritance and secret
  reflection in every retained field; all must fail without exposing the value.

### OE-C3-F04 — P1 — input/cost authorization is post-call and pricing/billing policy is not approval-bound

Artifacts: `evals/agent_efficiency/provider_ab.py:408-440,477-516,843-901,1018-1027,1147-1205`,
`docs/reports/OE-07-provider-evidence-readiness-candidate.3-2026-08-18.md:23-31,42-44`.

Approval does not bind the pricing snapshot, workload hash, tokenizer, manifest/command or plan
digest. Pricing time/source are accepted as arbitrary non-empty strings. Provider input is checked
only after the request has executed, and cumulative cost is checked only after the charge-bearing
response; output usage is not checked against the requested output ceiling. Thus these controls can
detect an overshoot but cannot guarantee the advertised pre-execution authorization. Reconciliation
does not require actual total cost to remain below operator approval and permits caller-selected
tolerance, as the P0 counterexample demonstrated.

Required change and acceptance evidence: bind exact workload/pricing/tokenizer/manifest/command and
billing tolerance into an independent approval and require the reviewed plan digest at run time;
pre-tokenize each complete request with the approved target tokenizer and enforce the cap before
network I/O; reserve/enforce cumulative spend before each call; validate output ceiling; and reject a
final actual total above approval regardless of tolerance. Tests must observe zero adapter starts for
every preflight denial and must prove no one-call overshoot can be labelled authorized.

### OE-C3-F05 — P1 — the A/B does not measure the shipped tool schemas or verifiable provider rounds

Artifacts: `evals/agent_efficiency/provider_ab.py:225-322,628-682,718-833`,
`integrations/python-client/src/milai_client/tools.py:38-110`,
`MiLAi_Agent执行效率与Token优化设计开发文档_v1.md:1105-1108,1525,1534-1536`.

The runner constructs six same-shaped synthetic schemas: every tool incorrectly takes `query` and
optional `limit`. The shipped schemas have distinct inputs (`claim_id`, `trace_id`, `evidence_id`,
`status`, or none), different descriptions, and a richer recall schema. Independent canonical
comparison found the same six names but **zero of six** detail schemas equal; the one reader-lite
schema also differed. Canonical map hashes were:

```text
shipped detail     879b49000bcd3f7944aff0a016ec8f8d6e2f28c7cc973072d1c05388b9f504e4
provider A/B detail 95734811140229c49b5cc4c91bd509c37aeed7daa0d442c4ef1d73321ed9100f
shipped lite       0342d6eb0bb5da06f79ba0b64d884a4bf0eb6b490b852bc6bfe0026ee7fad669
provider A/B lite  046c0dd58b547d056c1a41fbf1da29720ff12e9f23c7203556c896d9f650b8b1
```

The adapter also self-asserts provider/model/usage/component counts. A hard-coded local response can
match every expected answer, and model-round counts are derived from one JSONL exchange per record,
not native provider call receipts. An adapter can make extra calls internally without those rounds
being represented. Any non-empty finish reason is accepted.

Required change and acceptance evidence: derive both catalogs from the exact shipped, inventory-bound
tool definitions; make the baseline an exact current integration representation; require reviewed
provider-specific evidence for tokenizer counts, terminal response state and every native model call
ID; reconcile all call IDs with billing; and add negative tests for canned output, hidden extra calls,
wrong schemas and non-terminal/truncated responses.

### OE-C3-F06 — P1 — checked-in CI does not gate the candidate.3 provider code

Artifact: `.github/workflows/ci.yml:79-85,118-124,141-156`.

CI runs Runtime static/tests, release safety, package tests and the deterministic offline benchmark,
but contains no Ruff/mypy/pytest invocation for `provider_ab.py` or `test_provider_ab.py`. The manual
29-test claim can regress while checked-in CI remains green, so candidate.3 does not satisfy the CI
part of DoD 13.

Required change and acceptance evidence: add a no-network CI job/step that runs the exact provider
static and protocol tests, including the new independent negative cases, with no provider secret and
with cache/bytecode output kept outside candidate scope. A recorded green CI run must be inventory-
bound and independently checked.

### OE-C3-F07 — P2 — response timeout and partial-failure audit are not bounded

Artifacts: `evals/agent_efficiency/provider_ab.py:549-582,904-1098,1253-1280`.

After `selector.select(timeout)` reports any readable byte, `readline()` can block indefinitely waiting
for a newline. A local adapter that wrote one byte, flushed, waited 0.8 seconds and then completed the
line made an exchange configured for 0.1 seconds return after 0.826 seconds; the timeout was not
enforced. If any of 1,000 calls fails, `run_provider_ab()` raises before returning a report and the CLI
writes no privacy-bounded partial cost/request receipt. That is fail-closed for PASS, but weak for
recovering and reconciling already incurred calls.

Required change and acceptance evidence: use bounded nonblocking line accumulation with a total
deadline and size cap, terminate the process group on timeout, and atomically retain a non-PASS
partial receipt containing only validated request IDs, counters, hashes and cost-to-failure. Test a
partial-line stall and a failure after a late request, including child cleanup and billing recovery.

## Positive gates independently confirmed

These results are retained as useful evidence, but none overrides the P0/P1 findings.

| Gate | Result |
| --- | --- |
| Inventory | 356 entries; exact per-file size/SHA and canonical root; sorted, unique, safe; no symlink/cache/venv/live `.env` |
| No-network plan | `strace -f -e trace=network` recorded 0 network syscalls; plan reported 1,000 requests, authorized cost bound and `network_executed=false` |
| Explicit run controls | missing execute flag, wrong data acknowledgement and 999-request cap each failed before adapter start |
| Order/prefix | 1,000 records; first variants `baseline, optimized, optimized, baseline`; first 100 turns contained 100 baseline and 100 optimized records |
| Static | Ruff format: 5 files formatted; Ruff check PASS; mypy strict PASS |
| Focused tests | 29 passed in 1.80 seconds with pytest cache disabled and bytecode disabled |
| Archive-aware secret scan | PASS; 358 files, 296 archive members, 17 local secret values, zero file/member match, forbidden member or unsafe archive |
| Frozen boundary | bundle validation PASS; release lock verification PASS against `ac16f3b...55d0e` |

The plan path is genuinely local/no-network, the literal execution/data/request-count controls work,
the 500-turn ordering/prefix arithmetic is correct, and basic non-negative/provider/model/request
checks exist. Those are necessary but not sufficient for trustworthy provider evidence.

## Commands and reproducible results

All Python probes used `PYTHONDONTWRITEBYTECODE=1`; pytest used `-p no:cacheprovider`; mypy cache was
placed under `/tmp`. No command printed credential values.

```text
independent inventory reconstruction (standalone pathlib/hashlib/json implementation)
  file SHA 4256a342...b2b0b; 356/356 exact; root 2905a7c4...60637

ruff format --check evals/agent_efficiency/*.py
ruff check evals/agent_efficiency/*.py
mypy --strict --cache-dir /tmp/<review-cache> evals/agent_efficiency/provider_ab.py
  PASS / PASS / PASS

PYTHONPATH=. runtime/.venv/bin/python -m pytest -q -p no:cacheprovider \
  evals/agent_efficiency/test_benchmark.py \
  evals/agent_efficiency/test_provider_ab.py \
  tests/test_release_safety.py
  29 passed in 1.80s

strace -qq -f -e trace=network -o /tmp/oe-c3-plan-network.strace \
  runtime/.venv/bin/python <temporary build_plan harness>
  plan: 1000 requests / authorized / network_executed=false; trace: 0 lines

PYTHONPATH=. runtime/.venv/bin/python <temporary decoy-source adapter harness>
  split secret argv accepted; PGPASSWORD accepted; bound decoy not executed;
  fake capture PROVIDER_CAPTURE_PASS_BILLING_PENDING / provider_usage_verified=true;
  repo runtime/.env visible to child; synthetic secret reflected into report;
  non-stop finish reason accepted with all gates true

PYTHONPATH=. runtime/.venv/bin/python <temporary forged reconciliation harness>
  no adapter/provider run; one request; empty gates; provider usage absent;
  expected 0 / actual 999 / tolerance 1000; arbitrary unavailable upstream hash;
  final status PASS

PYTHONPATH=. runtime/.venv/bin/python <temporary shipped-schema comparison>
  detail names equal, 0/6 schemas equal; lite names equal, 0/1 schemas equal

PYTHONPATH=. runtime/.venv/bin/python <temporary partial-line timeout harness>
  configured 0.1 s; observed 0.826 s; timeout_was_enforced=false

PYTHONPATH=scripts runtime/.venv/bin/python scripts/scan_ua_secrets.py \
  --env-file runtime/.env
  PASS; 358 files; 296 archive members; zero matches/forbidden/unsafe

architecture/v1.0/scripts/validate_bundle.py
architecture/v1.0/scripts/verify_lock.py --scope bundle --mode release \
  --expected-manifest-sha256 ac16f3b...55d0e
  PASS / PASS
```

## Gate and release disposition

| Requirement | Disposition after candidate.3 review |
| --- | --- |
| OE-01 provider token accounting | **REVISE / PARTIAL** — local protocol has false-verification paths; no real usage exists |
| OE-07 candidate.3 provider readiness | **REVISE** — open P0/P1 findings |
| OG-00 provider baseline readiness | **REVISE** — approval/provenance and deployed baseline are not bound |
| OG-01 token truth | **OPEN** — adapter claims can be fabricated and no real capture exists |
| OG-03/04 provider token budgets | **OPEN** — component counts are self-asserted; pre-call input cap is not enforced |
| OG-09 provider quality | **OPEN** — fake/canned output passes; no real same-model A/B exists |
| OG-11 provider failure safety | **REVISE** — false PASS, secret-boundary and timeout/partial-evidence failures |
| OG-12 independent review | **FAIL for candidate.3 / NO-GO Beta** |
| DoD 1 | **OPEN** — no trustworthy real-provider token truth |
| DoD 10 | **OPEN** — no actual provider token/round/wall-time evidence; internal rounds are not verifiable |
| DoD 12 | **OPEN** — no fair current-vs-optimized real-provider comparison |
| DoD 13 for candidate.3 | **FAIL** — independent decision REVISE and checked-in CI omits the new gate |

Local acceptance requires closure and independent reproduction of every P0/P1 above. `OE-F06` then
still remains open until a separately approved real provider/model capture and independently verified
billing/quality evidence complete. Therefore neither candidate.3 readiness, Beta, Production, an SLA,
nor the final §20 release narrative is authorized by this review.

## Post-write immutability statement

After adding only this review, the independent 356-entry reconstruction remained exact with root
`2905a7c4c3b95d6b55a8acecb1e1afc47423704cf6f45f3db70d98a59fd60637`;
the inventory file remained `4256a342a68a528a3e78fcfa3a014bd4b7875e69e2f2b9396d70180c24bb2b0b`,
the package manifest remained `d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f`,
and the frozen manifest remained `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e`.
The final review-file SHA-256 is reported out of band because a file cannot self-authenticate its own
digest.
