# Retrieval trace 比较口径

`milai-retrieval-trace-testkit` 通过 stdin 接收公开 request-v0.1；仅用于隔离环境的信息性读取，
无生成模型调用，不改变检索策略或 Canonical。一次调用执行 normal/baseline/traced 三次读取。
正常 resolve 可能保存非 Canonical continuation 根记录，不能把该观测称为数据库零写入。

默认 `comparison_semantics_version="v0.1"` 保留历史响应摘要算法。显式选择 `"v0.2"` 时，
返回 report-v0.2，并保留 `legacy_response_semantic_digests`。旧 Product-10/X1 摘要和结果
不得按 v0.2 重新解释。

v0.2 对独立首轮读取的 context/root ID 作有限规范化，前提是：同次 receipt 对应；持久化
记录由当前 tenant/actor 拥有；root、predecessor、generation 正确；query/request（含 scope、
reference time、预算等）与来源 snapshot 一致；selected Evidence 及 continuation assertion
与记录一致。新增验证只有只读 repository GET，不进入原取证通路，也不替代 observer/repository 门。

Evidence/turn 身份、顺序、正文摘要、frontier 能力、数量、失效、重放和降级继续比较；v0.2
额外比较 receipt 非局部字段。错误绑定直接拒绝，不删除 continuation 整块。
`local_identity_bindings` 提供受控身份摘要与绑定验证，原根记录保留在隔离实例中。

拒绝 `TRACING_BEHAVIOR_CHANGED` 时，`response_field_diff` 最多各 32 个路径，只包含
值类型、基数和摘要及截断标志。它不输出正文。来源/READY 在三次读取期间变化仍会拒绝。

2026-09-06 验证：D1 OFF 控制、D1 ON 计数/普通/更新锚点、空来源，以及真实 PG 的
错误 query/scope/predecessor 和实际新增 READY 来源负控。工程可观测性通过不代表问答效果提升。
实验记录在 Lab 的 MILA-V02-03；公网未部署本次变更。

Schema 保持 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。回退比较口径用显式 v0.1，
不回退共享数据库或 State head。

## Opt-in Runtime owner export v1

The later [Claim/cache owner extension](trace-cache-owner.md) adds separately typed
Claim-record and actual receipt-validation facts to the Python/HTTP observer.
The subsequent [v2 cross-layer contract](trace-ownership-v2.md) and
[scoped receipt](../revalidation/trace-ownership/REVALIDATION.md) cover actual serial cache origins.
The CLI restrictions below remain unchanged; the original execution receipt is
historical Evidence-only proof, not retroactive Claim or cache coverage.

`milai-retrieval-trace-testkit --owner-trace` adds `runtime_owner_trace` to the existing
report. The Python entry point accepts `include_owner_trace=True`. Both are off by default;
the stdin request schema, normal Runtime/MCP endpoints and retrieval policy are unchanged.
The added object has schema `milai-runtime-owner-trace-v1` and is built from the actual
traced observer after all existing normal/baseline/traced neutrality checks pass. There are
still exactly three reads, no extra query/embedding/model call or automatic retry.

- `retrieval_trace_ref` hashes the actual recorded Runtime trace ID. The exporter rejects
  a response whose trace ID differs from the recorded repository return.
- `decision_snapshot_digest`, `gate_digest`, and `binding_digest` come from the captured
  immutable DecisionSnapshot. `canonical_position` comes from its recorded trace command.
- `evidence_set_digest` preserves the existing hash of ordered `accepted_evidence_ids`.
  This is the semantic decision's accepted set, not a hash of Host exposure or all Context
  selections; soft governance-admitted Context and semantic binding are distinct.
- `materialized_evidence_versions` contains exact versions from the governed result rows.
  `memory_ref=evidence:<digest>` and `version_id=evidence-record:<digest>` name an immutable
  EvidenceRecord, not a Lab bank's revision lineage. `content_sha256` is the owner-provided
  content hash; the exporter never substitutes a hash of an ID or reconstructed text.
- `selected_evidence_refs` retains the Context's selection order. `selected_versions`
  contains only selections whose exact version was observed. Raw search pointers are not
  materialized versions; this is not a complete candidate/opportunity denominator.
- Missing Context selection, missing content hashes, selected-unobserved versions and
  unsupported memory kinds produce explicit `trace_gaps` and `status=PARTIAL`, not fake
  empty known lists. This first exporter covers informational Evidence records; canonical
  Claim versions, continuation/cache-origin provenance and model use are not established.

ID references use `<kind>:SHA256(canonical_JSON(original_ID))`, compatible with the
[Host owner testkit](host-trace-testkit.md); canonical JSON is UTF-8, sorted keys,
unescaped Unicode and compact separators. The owner object emits no raw body, source locator,
native tenant/actor identity, query or label. Digests are not encryption. The surrounding
legacy report retains its existing disclosure contract and must not be relabeled as this
narrow allowlisted object. Source artifacts and identity bindings remain outside Git.

### 2026-09-22 producer validation

Product-owned [unit tests](../../runtime/tests/unit/test_runtime_owner_trace.py) exercise the
real retrieval service/observer with a synthetic repository; PostgreSQL
[integration tests](../../runtime/tests/integration/test_runtime_owner_trace_pg.py) execute
empty, visible-Evidence and wrong-scope cases through the live public testkit. They compare
exported trace/position with the database row and the selected hash with captured content.
All three neutrality comparisons remain true; wrong-scope data is not exported.

Targeted run: 40 passed, 0 skipped, 2.79 s (new unit/PG tests plus existing retrieval testkit
and audit tests). Changed-module Ruff/mypy PASS. An initial new unit-test import used an
inapplicable `tests.unit` package path; it was corrected to the existing pytest module layout.
The isolated PostgreSQL 16.14 container `milai-3a1-worker-once-20260922` was reused with
fresh synthetic tenants, deterministic-hash embedding and zero model calls, then stopped.
Its data was retained; the temporary endpoint was `127.0.0.1:32790`, database `milai_worker_once`,
migration head `0056_host_notes`.

From `runtime/`, with the isolated `MILAI_MIGRATION_DATABASE_URL` and
`MILAI_TEST_{API,STEWARD,WORKER}_DATABASE_URL` roles configured:

```bash
.venv/bin/pytest -q tests/unit/test_runtime_owner_trace.py \
  tests/unit/test_product10_retrieval_trace_testkit.py tests/test_retrieval_audit.py \
  tests/integration/test_runtime_owner_trace_pg.py --tb=short --maxfail=1 \
  --junitxml=/cra/memory/mx_memory/evidence/post-cleanup-3b1-runtime-owner-20260922/runtime-owner.xml
```

Ruff checked those new tests and the three changed `src/milai/testkit/` modules;
mypy checked `runtime_owner_trace.py`, `retrieval_trace.py` and `retrieval_trace_cli.py`.
Affected Runtime package checks/build are left to classified fast CI; they are not duplicated
locally. Normal resolve can write audit/continuation records as documented above; no claim of
zero database writes is made.

External JUnit: `/cra/memory/mx_memory/evidence/post-cleanup-3b1-runtime-owner-20260922/runtime-owner.xml`;
SHA-256 `9216dfbaeddfdb4dfedfa46765a638a6b25fcb8a30fc219026d346bcfc753de9`.

This proves the Runtime producer slice, not an end-to-end Host/MCP/Provider/Lab join. 3B-1
and trace ownership debt remain open for verification. No Product behavior receipt is
rebound and no full composition or unrelated database suite is repeated for this addition.
