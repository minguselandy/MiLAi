# DG13-U1 local OpenWorker operator runbook

Status: `DEVELOPMENT / RELEASE STATUS IS ARTIFACT-DERIVED`  
Scope: local `reader-lite`, `STRICT_CURRENT`, same-adapter-process task continuity  
Data: synthetic or independently de-identified only  
Provider: existing local vLLM at `http://127.0.0.1:7860`, model `Qwen3.6-35B-A3B-FP8`

This runbook operates the current DG13-U1 source. It does not confer a Production, Beta, remote-MCP,
portable-lease, general-retrieval, benchmark, or paper claim. Do not read formal labels or use a
formal holdout, DG12 formal capability, or real personal data during these operations.

The source currently advertises 37 selectors and contains 37 corresponding real-case execution
paths. That is source implementation parity only. Product usability is earned only by a current,
hash-bound 37-case aggregate, a sealed review bundle, and an independent model review whose terminal
verdict is `PASS`; this runbook never turns source parity or a stale artifact into a release claim.

The current runner is a one-case entrypoint. One invocation owns
`start → readiness → smoke → report → cleanup`; cleanup executes from its top-level `finally` block.
Its durable directory is `var/dg13/runs/$DG13U_RUN_ID`, its temporary root is
`var/dg13/tmp/$DG13U_RUN_ID`, and its short UDS root is under `/dev/shm/milai`. The runner retains the
durable report and cleanup receipt and removes only resources registered to that run ID.

## 1. Non-negotiable stops

Run from `/cra/memory/mx_memory/MiLAi` in one Bash shell. Stop before a stateful command if any of the
following is false:

- `runtime/.env` is the intended local development environment and contains no formal-data source.
- The image build and run use current repository source and only synthetic/de-identified fixture data.
- No other DG13-U1 stateful startup owns the intended database, port, container, network, socket, or
  provider execution window.
- The existing vLLM identity is expected and is not being administered by this run.

The vLLM is preserved external state. Never start, stop, restart, kill, remove, upgrade, reconfigure,
or retag it. Do not use Docker lifecycle commands, process signals, service-manager commands, or GPU
reconfiguration against it. The only permitted vLLM operations here are the read-only health,
model/identity, process/container identity, and ledger observations performed by the runner or shown
below. A provider request is never a readiness probe.

Provider automatic retry is prohibited. MCP automatic retry is also zero. A failed provider turn is
terminal for that run/case; first reconcile whether a request was issued, its provider native request
ID, and its ledger terminal.

## 2. Read-only preflight

These commands do not issue a completion:

```bash
set -euo pipefail
cd /cra/memory/mx_memory/MiLAi
runtime/.venv/bin/milai-ops status --json --env-file runtime/.env
curl -fsS --max-time 3 http://127.0.0.1:7860/health
curl -fsS --max-time 3 http://127.0.0.1:7860/v1/models
docker image inspect milai-openworker:dg13u-u1-current-local
docker ps --no-trunc
ps -eo pid,lstart,args | rg '[m]ilai-(api|worker|mcp-broker|mcp-relay|openworker-adapter)'
df -h / /tmp /cra /dev/shm
nvidia-smi
runtime/.venv/bin/python scripts/dg13u_u1_openworker.py --list-cases
```

Separate component readiness is not combined E2E evidence. Stop on identity drift, a non-zero vLLM
completion count during preflight, an existing run ID, or an occupied stateful execution window.

## 3. Exact source and image build

The build entrypoint pins the base image ID, platform, relay, OpenCode config, task-metadata plugin,
and Dockerfile hashes. It builds with `--pull=false --network none`, verifies the base-layer prefix and
embedded bytes, and writes only the derived tag `milai-openworker:dg13u-u1-current-local`. It does not
manage vLLM.

```bash
set -euo pipefail
cd /cra/memory/mx_memory/MiLAi
./integrations/openworker-mcp/build_dg13u_u1_image.sh
docker image inspect milai-openworker:dg13u-u1-current-local
```

During each `--execute-local` run, the runner additionally hashes the current source tree, builds and
probes the current wheels, installs them into a fresh run-owned product venv offline, records Runtime
migration identity, inspects the derived image, and performs a read-only vLLM identity probe. Do not
substitute a historical DG10 image, wheel, report, or shadow artifact.

## 4. Current single-case CLI capability

The runner exposes `--list-cases` and one `--case-id` per invocation; it has no multi-case selector.
The following is a concrete NONE smoke. It may issue exactly one provider request and must be the
only provider-consuming job in its window.

```bash
set -euo pipefail
cd /cra/memory/mx_memory/MiLAi
DG13U_RUN_ID="dg13u-u1-none-en-$(date -u +%Y%m%dt%H%M%Sz)-${BASHPID}"
test ! -e "var/dg13/runs/$DG13U_RUN_ID"
test ! -e "var/dg13/tmp/$DG13U_RUN_ID"
TMPDIR=/dev/shm \
  runtime/.venv/bin/python scripts/dg13u_u1_openworker.py \
  --case-id U1-NONE-EN \
  --run-id "$DG13U_RUN_ID" \
  --execute-local \
  --env-file runtime/.env
DG13U_REPORT="var/dg13/runs/$DG13U_RUN_ID/report.json"
test -f "$DG13U_REPORT"
```

Exit `0` means that this case report is `PASS`; exit `2` means a typed non-PASS report was retained.
An exception is contained at the top level and cleanup is still attempted. A successful single case
is not a release gate and must not be relabeled as DG13-U1 PASS.

## 5. Cleanup receipt verification

Cleanup is part of every runner invocation. Verify its receipt before leaving the execution window
or starting another case:

```bash
runtime/.venv/bin/python - "$DG13U_REPORT" <<'PY'
import json
import pathlib
import sys

report_path = pathlib.Path(sys.argv[1])
report = json.loads(report_path.read_text(encoding="utf-8"))
cleanup = report["cleanup"]
receipt_path = report_path.with_name(cleanup["receipt"])
receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
assert cleanup["status"] == "PASS"
assert cleanup["existing_vllm_preserved"] is True
assert receipt["schema"] == "milai.dg13u.u1-cleanup-receipt.v1"
assert receipt["run_id"] == report["run_id"]
assert receipt["status"] == "PASS"
assert receipt["existing_vllm_preserved"] is True
assert receipt["external_lifecycle_mutations"] == 0
assert any(
    row.get("kind") == "external_vllm"
    and row.get("ownership") == "PRESERVED_EXTERNAL"
    and row.get("state") == "preserved_external"
    for row in receipt["items"]
)
print(json.dumps({"run_id": report["run_id"], "cleanup": "PASS"}, sort_keys=True))
PY
```

If this verifier fails, preserve the bounded durable report and receipt. Do not manually delete an
unknown container, network, database, process, socket, or directory. For a process killed before its
`finally` block, use only the standalone recovery CLI with the exact run-adjacent, hash-chained
`recovery-resource-plan.json`:

```bash
set -euo pipefail
cd /cra/memory/mx_memory/MiLAi
runtime/.venv/bin/python scripts/dg13u_u1_cleanup.py \
  --plan "$(pwd)/var/dg13/runs/$DG13U_RUN_ID/recovery-resource-plan.json" \
  --run-id "$DG13U_RUN_ID" \
  --env-file "$(pwd)/runtime/.env" \
  --execute-local
```

The recovery command validates exact paths, ownership labels, database ownership, process PID/start
markers, external-vLLM identity, and compare-and-swap generations before mutating anything. A
missing, changed, or guessed identity fails closed and must never be repaired by broad deletion.

## 6. Source implementation-parity guard

The public selector and `_IMPLEMENTED_REAL_CASES` are currently at source parity: **37 advertised
cases; 37 source implementations; 0 implementation-gap selectors**. This does not prove that any
case or the matrix passes real E2E. The following zero-provider guard verifies source parity before a
full-matrix provider window and fails with a typed drift reason before starting a case:

```bash
set -euo pipefail
cd /cra/memory/mx_memory/MiLAi
runtime/.venv/bin/python - <<'PY'
from scripts import dg13u_u1_openworker as runner

if set(runner.CASES) != set(runner._IMPLEMENTED_REAL_CASES):
    missing = sorted(set(runner.CASES) - set(runner._IMPLEMENTED_REAL_CASES))
    extra = sorted(set(runner._IMPLEMENTED_REAL_CASES) - set(runner.CASES))
    print("FULL_MATRIX_IMPLEMENTATION_DRIFT")
    print("\n".join(missing))
    print("\n".join(extra))
    raise SystemExit(2)
print("FULL_MATRIX_IMPLEMENTATION_READY")
PY
```

## 7. Current full-matrix CLI capability: serial execution and aggregation

`scripts/dg13u_u1_matrix.py` is the exact full-matrix CLI. It validates runner/implementation/
aggregate parity, derives 37 deterministic unique run IDs, executes cases serially, stops at the
first non-PASS exit, verifies each cleanup receipt, and passes explicit report paths to the
aggregator. It neither discovers a directory nor retries a case.

```bash
set -euo pipefail
cd /cra/memory/mx_memory/MiLAi
DG13U_BATCH_ID="u1matrix-$(date -u +%m%dt%H%M%S)-${BASHPID}"
DG13U_AGGREGATE="$(pwd)/var/dg13/aggregates/$DG13U_BATCH_ID.json"
test ! -e "$DG13U_AGGREGATE"
TMPDIR=/dev/shm runtime/.venv/bin/python scripts/dg13u_u1_matrix.py \
  --batch-id "$DG13U_BATCH_ID" \
  --env-file "$(pwd)/runtime/.env" \
  --output "$DG13U_AGGREGATE"
```

The aggregator returns `0` only if all 37 unique cases, all nine safety denominators, call ledgers,
metrics, evidence joins, cleanup receipts, and `U1-G0` through `U1-G5` pass. Any missing, `FAIL`,
`BLOCKED`, or `NOT_RUN` input keeps the release label unearned.

For every report, the aggregator requires these exact sibling artifact/schema pairs:

- `manifest.json` — `milai.dg13u.u1-run-manifest.v1`
- `exact-product-manifest.json` — `milai.dg13u.u1-exact-product-manifest.v1`
- `identity-preflight.json` — `milai.dg13u.u1-identity-preflight.v1`
- `readiness.json` — `milai.dg13u.u1-readiness.v1`
- `smoke-evidence.json` — `milai.dg13u.u1-smoke-evidence.v1`
- `reconciliation.json` — `milai.dg13u.u1-reconciliation.v1`
- `cleanup-receipt.json` — `milai.dg13u.u1-cleanup-receipt.v1`
- `recovery-resource-plan.json` — `milai.dg13u.u1-recovery-resource-plan.v1`

For each of the 13 frozen fault cases, the aggregator additionally requires
`fault-execution.json` — `milai.dg13u.u1-fault-execution.v1`. U1-G4 validates its exact typed
Host terminal, call counts, zero retries, provider barrier, fault-case/run identity, and zero
external vLLM attempts or lifecycle mutations. A fault artifact copied from another case or reduced
with a different reason/barrier is a typed gate failure.

Do not fabricate, copy forward, or repair an absent artifact by hand. Missing, schema-drifted,
identity-mismatched, non-hash-bound, or non-PASS evidence is a typed aggregate failure.

## 8. Fixed owning-test gate and durable receipt

Freeze the source and documentation before this step. The gate rejects top-level U1 test-inventory
drift, then executes the fixed 26-file U1 inventory plus its one U0 support owning test in one
27-file command, the 10-file Python-client suite, and the 8-file OpenWorker integration suite. Each
command runs once with `-W error`, plugin autoload disabled, and a short, run-owned `/dev/shm`
temporary root that is removed before the receipt is sealed. The gate snapshots every closed-over
source input before the commands and re-reads the same inventory afterward; any missing input,
identity/read instability, byte drift, or digest drift makes the receipt fail. No raw stdout or
stderr is persisted; their complete byte counts and SHA-256 digests are recorded in `receipt.json`.

```bash
set -euo pipefail
cd /cra/memory/mx_memory/MiLAi
DG13U_TEST_GATE_ID="dg13u-u1-test-gate-$(date -u +%Y%m%dt%H%M%Sz)-${BASHPID}"
DG13U_TEST_GATE_PARENT="$(pwd)/var/dg13/test-gates"
DG13U_TEST_GATE_ROOT="$DG13U_TEST_GATE_PARENT/$DG13U_TEST_GATE_ID"
mkdir -p "$DG13U_TEST_GATE_PARENT"
chmod 0700 "$DG13U_TEST_GATE_PARENT"
test ! -e "$DG13U_TEST_GATE_ROOT"
runtime/.venv/bin/python scripts/dg13u_u1_test_gate.py \
  --run-root "$DG13U_TEST_GATE_ROOT"
test "$(runtime/.venv/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$DG13U_TEST_GATE_ROOT/receipt.json")" = PASS
```

Any source or owning-test change after this receipt invalidates it and requires a new unique gate
run. A valid receipt has `source_revalidation.status=PASS` and identical pre/post source-input
digests. The receipt is supplemental review evidence; it is not itself a matrix or release result.

## 9. Explicit read-only review bundle

Only package an aggregate that already earned all six gates. The bundle CLI never discovers run
directories and never reruns a case. Every aggregate report and every report-bound artifact must be
passed explicitly; additional `--artifact` values become supplemental evidence. The command scans
text and bounded archive members for secret-like content, verifies all SHA/byte/schema/identity
bindings, publishes atomically, and seals directories `0555` and files `0444`.

```bash
set -euo pipefail
cd /cra/memory/mx_memory/MiLAi
test -f "$DG13U_AGGREGATE"
DG13U_BUNDLE="$(pwd)/var/dg13/reviews/$DG13U_BATCH_ID-bundle"
test ! -e "$DG13U_BUNDLE"
mapfile -t DG13U_REPORTS < <(
  runtime/.venv/bin/python - "$DG13U_AGGREGATE" <<'PY'
import json, pathlib, sys
aggregate = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert aggregate["status"] == "PASS" and aggregate["release_label_earned"] is True
for row in aggregate["inputs"]:
    path = row["report_path"]
    assert "\n" not in path
    print(path)
PY
)
mapfile -t DG13U_ARTIFACTS < <(
  runtime/.venv/bin/python - "${DG13U_REPORTS[@]}" <<'PY'
import json, pathlib, sys
for value in sys.argv[1:]:
    report_path = pathlib.Path(value)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for row in report["artifacts"]:
        path = str(report_path.parent / row["path"])
        assert "\n" not in path
        print(path)
PY
)
mapfile -t DG13U_TEST_GATE_SOURCES < <(
  runtime/.venv/bin/python - "$DG13U_TEST_GATE_ROOT/receipt.json" "$(pwd)" <<'PY'
import hashlib, json, pathlib, sys

receipt = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
root = pathlib.Path(sys.argv[2]).resolve(strict=True)
assert receipt["status"] == "PASS"
assert receipt["source_revalidation"]["status"] == "PASS"
assert (
    receipt["source_revalidation"]["post_source_inputs_sha256"]
    == receipt["source_inputs_sha256"]
)
for row in receipt["source_inputs"]:
    path = (root / row["path"]).resolve(strict=True)
    assert path.is_relative_to(root)
    raw = path.read_bytes()
    assert len(raw) == row["bytes"]
    assert hashlib.sha256(raw).hexdigest() == row["sha256"]
    assert "\n" not in str(path)
    print(path)
PY
)
DG13U_ARTIFACTS+=(
  "$DG13U_TEST_GATE_ROOT/receipt.json"
  "${DG13U_TEST_GATE_SOURCES[@]}"
)
DG13U_BUNDLE_ARGS=(--aggregate "$DG13U_AGGREGATE" --output-dir "$DG13U_BUNDLE")
for path in "${DG13U_REPORTS[@]}"; do DG13U_BUNDLE_ARGS+=(--report "$path"); done
for path in "${DG13U_ARTIFACTS[@]}"; do DG13U_BUNDLE_ARGS+=(--artifact "$path"); done
runtime/.venv/bin/python scripts/dg13u_u1_bundle.py "${DG13U_BUNDLE_ARGS[@]}"
test "$(stat -c %a "$DG13U_BUNDLE")" = 555
test "$(stat -c %a "$DG13U_BUNDLE/manifest.json")" = 444
```

The bundle validates the test-gate receipt semantically and requires exactly one explicit file with
matching bytes and SHA-256 for every receipt source row. Those files are emitted under
`test-gate-sources/`; a receipt without its exact reviewed source closure fails packaging. The
manifest binds a canonical `entries_sha256`, the aggregate digest, 37 report rows, all run artifacts,
supplemental evidence, archive-scan measurements, and zero bundle-side network, resource-start, and
rerun counts.

## 10. One independent Sol/xhigh model review

The review runner performs a single shell-free Codex execution with approval policy `never`, model
`gpt-5.6-sol`, reasoning effort `xhigh`, an ephemeral session, read-only sandbox, ignored user config
and rules, and zero retry. Its attempt directory must be new, absolute, and outside the sealed bundle.
The runner validates the bundle before and after execution and emits JSON/Markdown terminals plus
input, argv, process, and output hash attestations.

```bash
set -euo pipefail
cd /cra/memory/mx_memory/MiLAi
DG13U_MANIFEST_SHA256="$(sha256sum "$DG13U_BUNDLE/manifest.json" | awk '{print $1}')"
DG13U_REVIEW_ID="dg13u-u1-review-primary-001"
DG13U_REVIEW_ROOT="$(pwd)/var/dg13/review-attempts/$DG13U_REVIEW_ID"
test ! -e "$DG13U_REVIEW_ROOT"
runtime/.venv/bin/python scripts/dg13u_u1_review.py \
  --bundle "$DG13U_BUNDLE" \
  --expected-manifest-sha256 "$DG13U_MANIFEST_SHA256" \
  --attempt-root "$DG13U_REVIEW_ROOT" \
  --attempt-id "$DG13U_REVIEW_ID"
runtime/.venv/bin/python - "$DG13U_REVIEW_ROOT" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
terminal = json.loads((root / "terminal.json").read_text(encoding="utf-8"))
process = json.loads((root / "process.json").read_text(encoding="utf-8"))
review = json.loads((root / "review.json").read_text(encoding="utf-8"))
assert terminal["status"] == "COMPLETED" and terminal["verdict"] == "PASS"
assert process["status"] == "PASS" and process["attempt_count"] == 1
assert process["automatic_retries"] == 0
assert process["model"] == "gpt-5.6-sol" and process["reasoning_effort"] == "xhigh"
assert not [item for item in review["open_findings"] if item["severity"] in {"P0", "P1"}]
assert review["missing_evidence"] == []
print("DG13U_U1_INDEPENDENT_REVIEW_PASS")
PY
```

A valid `REVISE` or `BLOCKED_BY_MISSING_EVIDENCE` response proves only that the review completed; it
does not earn product usability. Apply one evidence-backed fix, rerun every affected gate, mint new
artifact identities, and use a new review attempt ID. Never overwrite or relabel an earlier attempt.

## 11. Single failure closure

On a single failure, stop the matrix and freeze the exact run/case ID, command, fixture and source
digests, first failing stage, typed outcome, bounded log hashes, MCP/provider counts, provider native
request ID, and cleanup receipt. Do not rerun the matrix to diagnose it.

For a source-level NONE smoke failure, this is a concrete zero-provider unit loop using run-owned temp
and cache paths:

```bash
set -euo pipefail
cd /cra/memory/mx_memory/MiLAi
DG13U_TEST_ID="dg13u-u1-none-debug-$(date -u +%Y%m%dt%H%M%Sz)-${BASHPID}"
mkdir -p "/dev/shm/$DG13U_TEST_ID/t" "/dev/shm/$DG13U_TEST_ID/b" "/dev/shm/$DG13U_TEST_ID/c"
TMPDIR="/dev/shm/$DG13U_TEST_ID/t" \
  runtime/.venv/bin/python -m pytest -q -x \
  tests/test_dg13u_u1_openworker.py::test_none_smoke_executes_once_and_rejects_duplicate_provider_reservation \
  --basetemp="/dev/shm/$DG13U_TEST_ID/b" \
  -o cache_dir="/dev/shm/$DG13U_TEST_ID/c"
```

After the exact node is green, run its negative twin, then the owning module, then one real case, and
only then the full matrix. For provider failures, no automatic second request is allowed: determine
request-issued state, native ID, terminal ledger, and unaccounted count first; a later authorized
attempt uses a new run ID and remains in the denominator.

## 12. Artifact-derived release decision

The source implementation matrix is complete, but source alone never earns usability. The decision
is fail-closed and entirely artifact-derived:

1. The current-source serial matrix must retain exactly 37 unique PASS reports and an aggregate whose
   matrix, safety denominators, reconciliations, cleanup receipts, and `U1-G0` through `U1-G5` pass.
2. Every required artifact and recovery plan must be generated by its owning execution path and pass
   schema, hash/byte bound, status, run identity, case identity, call, and cleanup reconciliation.
3. The durable fixed-test receipt must be PASS and must match the reviewed frozen source inputs.
4. The sealed explicit bundle must be PASS and match the exact aggregate manifest closure.
5. The independent model review must be a schema-valid `PASS` with open P0/P1 findings equal to zero,
   no missing evidence, one attempt, zero retry, and a preserved read-only bundle closure. It must
   confirm no fabrication, no hidden retry, no unaccounted call, preserved existing vLLM, and bounded
   cleanup/recovery.
6. Only when all five conditions are true may the exact aggregate release label be reported. Any
   missing or non-PASS condition yields `PRODUCT NOT USABLE`; no locally green subset is promotable.

The runbook changes no Runtime/Schema/API/canonical behavior. Schema remains
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.
