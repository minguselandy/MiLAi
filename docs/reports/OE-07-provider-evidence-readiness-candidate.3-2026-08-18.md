# OE-07 provider evidence readiness — candidate.3

Decision: `LOCAL PROTOCOL PASS / READY FOR INDEPENDENT REVIEW / PROVIDER NO-GO`  
Date: `2026-08-18` (Asia/Shanghai)  
Boundary: synthetic/de-identified only; no provider request executed; no secret or billing artifact
retained

## Outcome

Candidate.2 independently passed the local synthetic Optimization Candidate gate and closed
OE-F01–F05/F07. Candidate.3 adds the missing executable path for OE-F06: a frozen same-model A/B
workload, provider-agnostic long-lived JSONL adapter protocol, native usage and exact-tokenizer
validation, privacy-bounded reports, explicit operator approval/cost guards, and billing
reconciliation from an external normalized provider export.

This is readiness evidence, not provider evidence. No approved provider/model, adapter, credential,
pricing snapshot, provider request receipt, usage record or invoice/export is present. Provider
usage, billing, model rounds, model wall time and quality remain unmeasured rather than zero. The
release status remains `Optimization Candidate`; Beta and Production remain `NO-GO`.

## Implemented evidence chain

1. `plan` validates the workload, executable adapter source, dependency lock, approval and pricing,
   then calculates a conservative upper cost bound without starting the adapter.
2. `run` requires the literal `--execute-provider`, the exact
   `synthetic-deidentified-only` acknowledgement, exactly 1,000 requests, an approved per-request
   input ceiling and an approved USD limit.
3. A SHA-bound approval anchors provider/model, adapter/lock, declared provider-secret environment
   names, data boundary, request count, token ceiling, cost ceiling, approver and time.
4. The adapter process is launched without a shell and with a narrow environment. Database,
   PostgreSQL, Steward, MiLAi token, KEK, tenant and actor credential names are rejected.
5. Baseline/optimized ordering alternates. One 500-turn pair run also yields the first 100-turn
   prefix, avoiding a second, selectively favorable run.
6. Every response must match provider/model/request identity, use `provider_response` counters,
   provide a unique provider request ID, and provide target-tokenizer memory/tool counts. Missing,
   negative, inconsistent or substituted values fail closed.
7. The runner scores strict structured output for current ACTION_SAFE state, live conflict,
   revocation, insufficient authority, Scope mismatch and four non-memory controls. Any forbidden
   stale value or malformed output fails its case.
8. Reports retain only hashes, counters, timings, request identities and scores. Prompt, Memory,
   Evidence and model-output text are processed transiently and omitted.
9. `reconcile` reads a normalized billing export outside the repository, verifies its upstream
   provider-artifact SHA, recomputes the exact provider request-ID coverage root and sums per-request
   decimal costs. It does not trust a sidecar aggregate.

## Adversarial and regression gates

The provider protocol suite passes `17/17`. Together with the pre-existing efficiency and release
safety tests, the focused gate passes `29/29`:

```text
PYTHONPATH=. runtime/.venv/bin/python -m pytest -q \
  evals/agent_efficiency/test_benchmark.py \
  evals/agent_efficiency/test_provider_ab.py \
  tests/test_release_safety.py

29 passed in 1.84s
```

Static gates:

```text
ruff format --check evals/agent_efficiency/*.py  PASS
ruff check evals/agent_efficiency/*.py           PASS
mypy --strict provider_ab.py                     PASS
```

Covered negative conditions include:

- public execution without explicit provider/data/cost/request authorization;
- provider/model/usage-source/request-ID substitution;
- secret-looking argv and MiLAi canonical credential environment names;
- source bytes not actually present in executed argv;
- source, dependency lock or approval hash mismatch;
- execution token/cost limits larger than operator approval;
- duplicate request identity, missing or inconsistent provider counters;
- component tokens exceeding provider input and non-zero counts for empty components;
- per-request memory/tool budget overflow hidden by a low aggregate average;
- prose/malformed JSON, false conflict closure, stale revoked value, authority or Scope escalation;
- incomplete/duplicate billing request coverage, wrong identity/currency/artifact hash or cost
  outside tolerance;
- retention of prompt, memory, model output or secret value in the report.

## Candidate identities

| Artifact | SHA-256 |
| --- | --- |
| `evals/agent_efficiency/provider_ab.py` | `68e8992250cb93a62e196b5d1fc4ba4a78d5eff43ae17a678f0cca5529326d04` |
| `evals/agent_efficiency/provider_ab_workload.json` | `ab5cac3c660835ad1beda1cac56e32b893af476f77b3fb987d4f59d3b8e827e0` |
| `evals/agent_efficiency/test_provider_ab.py` | `926df0689512329b9fcc313cb908f3a4e4dd3d8ddb1571531e963c36f78d1245` |
| `evals/agent_efficiency/PROVIDER_ADAPTER_CONTRACT.md` | `aefe00446c99c977b7c7000b5dc089b7b080c1e9a304eac9462572cfba742bf1` |
| `provider_adapter_manifest.example.json` | `2603e441e4adf04e225dca896f8d7a08c72935fd5f63969453a8785a72732995` |
| `provider_approval.example.json` | `d8360b095df39f09028b0ccef5836a399fb52d10aa127e35a9c6dc593ef0f200` |
| `provider_pricing_snapshot.example.json` | `5e7df78efddd89113257513958c8a500121ac95b3f55a42aa1945fb2725f8b9e` |
| `provider_billing_evidence.example.json` | `df004612d54b0e201996b6adbcd4415682f2f98b6815afc3f253a9f1d8cbbc15` |
| `normalized_provider_billing_export.example.json` | `8e3d8ab5e4d7db52454a7234dc1e92c1dd455980178a471d40f4b759e0d3a749` |

The example JSON files are non-secret schemas with explicit replacement markers. They are not valid
approval, pricing or billing evidence until an operator replaces every marker and the runner
validates the resulting external files.

## Remaining OE-F06 closure sequence

1. The user/operator selects and approves one provider, exact model version and target tokenizer.
2. A removable adapter is implemented against that provider's native API and locked dependencies;
   an independent reviewer audits its usage mapping and data egress.
3. The operator supplies the provider secret through the approved environment variable and runs the
   no-network plan.
4. If the 1,000-request conservative cost bound is accepted, the explicit provider run executes and
   must produce `PROVIDER_CAPTURE_PASS_BILLING_PENDING`.
5. The provider billing export/invoice is normalized outside the repository, hashed and reconciled;
   the final report must be `PASS`.
6. The report, workload, adapter/lock, approval, pricing and upstream billing hashes are added to the
   candidate inventory and independently re-reviewed.

Until all six steps complete, OE-F06 remains an external P1 and the full design objective is not
complete.
