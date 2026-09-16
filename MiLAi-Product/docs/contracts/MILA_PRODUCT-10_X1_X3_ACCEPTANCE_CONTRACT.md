# Product-10 X1/X3 Trace 与 Continuation 验收合同

状态：`EXECUTED X1-X2 / X3 INSUFFICIENT OPPORTUNITY / TERMINAL PARKED`
版本：`v0.1`
日期：`2026-09-03`
依据：`MILA-PRODUCT-10@1.1`、`ADR-031 PROPOSED`

## 1. 合同用途

本合同把首批实现与验收条件变成可直接测试的事实。用户已授权读取 opened-development case、
修改 Product、执行 migration、运行 Codex 与最终 formal holdout；阶段门和 anti-leakage 约束不变。

## 2. 前置封存

任何 A0/B1/B2 run 必须引用一个 immutable run bundle：

```yaml
run_identity:
arm: A0 | B1 | A0_TWO_CALL | B2
product_tree_sha256:
product_lock_digest:
lab_runner_sha256:
command_sha256:
dataset_sha256:
selection_sha256:
instance_label_sha256:
label_provenance:
label_adjudication_status:
codex_provider:
codex_model:
codex_cli_version:
codex_config_digest:
source_snapshot_as_of:
projection_identity: {}
profile: MCP_INTERACTIVE_WIDE_V01
formal_files_accessed:
formal_cases_scored: 0
redacted_trace_sha256:
cleanup_receipt_sha256:
```

任一 identity 缺失时，run 可用于调试但不可进入 H1/H2 denominator。

## 3. X1 trace bundle

Lab 组合的 `product10-x1-trace-bundle-v0.1` 必须包含：

| 边界 | Product evidence | 必需 identity |
| --- | --- | --- |
| raw discovery | `ProductRetrievalTraceV01.occurrences` | occurrence/evidence/source/snapshot |
| Evidence-ID dedup | `dedup_decisions` + S21 lifecycle | exact winner/loser IDs；不得按 semantic/source 合并 |
| locality/order/cutoff | S14/S15/S20/S22/S23 lifecycle | before/after rank、reason |
| hydration/governance | S30/S31/S32 lifecycle | Evidence ID、typed decision |
| Context admission | MemoryContext selected/omitted unit trace | Evidence IDs、turn refs、reason |
| MCP render | actual `memory-evidence-context-v1` response | rendered Evidence IDs、turn refs、response digest |

Product trace 不含 expected answer、acceptable Evidence、equivalence group、case correctness 或 count。
Lab 在 bundle 完成后才加载 sealed labels 并生成评分视图。

### 行为中性门

```text
same official repository calls and arguments
same ordered repository return identities
same Product response semantic digest
same source snapshot / projection identity
canonical mutation = 0
Reader/generative calls = 0
```

任一不相等时 trace 为 `TRACING_BEHAVIOR_CHANGED`，整次 X1 run 无效。

## 4. 唯一 first-loss 算法

对每个未覆盖 required group，按以下顺序只给一个结果：

1. acceptable Evidence/turn 都未出现在 raw occurrences：`NOT_DISCOVERED`；
2. raw 中存在，但不同 `evidence_id` 因 semantic/source/session equivalence 被硬合并或 seen-excluded：
   `INSTANCE_DESTROYING_COLLAPSE`；
3. raw 中存在、未发生上述 collapse，但没有进入 Context admitted identities：
   `DISCOVERED_NOT_ADMITTED`；
4. 已进入 Context admitted identities，但没有出现在 MCP rendered identities：
   `ADMITTED_NOT_RENDERED`；
5. 已由 MCP 渲染且 Host 在 X4 仍未使用：`VISIBLE_BUT_HOST_MISSED`。

已覆盖 group 没有 first-loss。X1 Context-only run 只能产生前四类；第五类必须来自预冻结 X4。
分类器同时记录第一条 decisive Product lifecycle step 和 reason code，不允许人工覆盖。

## 5. B1 component contract

B1 只有 X1 命中第 2/3 类时进入：

```text
hard dedup key                    exact evidence_id
hard shown exclusion              exact evidence_id
semantic/source/session/time      soft feature only
same-session unseen evidence      eligible
candidate universe                exactly A0 frozen pool
fallback                          original A0 order and identity set
Lab labels read by Product        0
```

最小反例矩阵：不同 ID/相同正文、不同 ID/相同 `source_ref`、不同 ID/同 session、同 ID/多 channel、
seen ID/同 session unseen ID、soft rank failure。前五类不得丢失 unseen stable identity。

## 6. B2 persistent state contract

`context_id` 必须定位 `evidence-continuation-state-v0.1` capsule。required fields：

```text
principal_scope_digest
source_snapshot_as_of
projection_identity
query_history digests
shown_evidence_ids
shown_source_turn_refs
ordered remaining frontier + digest
budget_used
expires_at
predecessor_context_id / continuation_request_digest
```

第二次调用：

```text
candidate universe = persisted remaining frontier only
new IDs ∩ prior shown IDs = empty
same-session unseen ID remains eligible
principal/scope/snapshot identity = exact match
live permission/retention/revocation = revalidated
first + second official memory calls = 2
automatic retry / vote = 0
```

successor capsule 不可原地改写 predecessor。相同 predecessor/request digest 必须 idempotently 返回
同一 successor；达到调用预算不等于 frontier exhausted。

## 7. Continuation assertion truth table

| Runtime proof | `continuation` |
| --- | --- |
| persisted、在线可读 remaining frontier 非空 | `{available:true, reason:UNSEEN_EVIDENCE_FRONTIER}` |
| 完整 frontier 在线重验后为空 | `{available:false, reason:FRONTIER_EXHAUSTED}` |
| Product-10 两调用预算已满但 frontier 可能非空 | `{available:false, reason:CALL_BUDGET_EXHAUSTED}` |
| persistence/identity/snapshot proof 不可用 | `null` + typed warning |
| legacy ContextReceipt | 现有 reuse/fallback；不得改写为 frontier assertion |
| not-owned/unknown/expired context | 不泄漏存在性；不得返回旧 Evidence；continuation 为 `null` |

MCP 只转发该映射，不因 truncation、PARTIAL 或 Host query 推断 continuation。

## 8. Fresh PostgreSQL 与权限矩阵

必须在 fresh PostgreSQL 直接验证：

| case | expected |
| --- | --- |
| same tenant/actor/project/scope | continuation eligible |
| different actor in same tenant | not found/not owned，无泄漏 |
| different tenant | RLS 隔离 |
| narrowed/broadened project scope | digest mismatch，不继续 |
| expired capsule | unavailable/null |
| revoked/unreadable Evidence | 不返回；typed frontier removal |
| content hash changed/tampered section | fail closed |
| DB unavailable | 不创建内存 frontier；null |
| recall execution | Claim/Canonical/OpenIssue mutation 全为 0 |

## 9. 回归与效果出口

实现回归至少包括：Runtime unit、fresh-PostgreSQL procedure/RLS、MCP schema/renderer、legacy receipt
reuse、Product-09 default-off behavior 与 Product lock verifier。

通过组件合同不等于 H1/H2 通过。H1/H2、24-case Context-only matched effect、最多 8 个 real Codex
HTTP case 与所有 terminal 仍按 Goal/Plan 判定；formal holdout 需要独立授权。

## 10. 当前状态

```yaml
execution_authorized: true
x0: COMPLETE_24_CASES_36_GROUPS_PROXY_LABELS
x1_testkit_publication: COMPLETE_BEHAVIOR_NEUTRAL
b1: TWO_GENERAL_ROUNDS_H1_FAILED_DEFAULT_OFF
b2_persistence: NOT_ENTERED_INSUFFICIENT_OPPORTUNITY_1_A0_2_B1_LT_6
public_mcp_schema_change: NOT_NEEDED
current_continuation: null_unless_existing_runtime_proof
formal_cases_scored: 0
terminal: PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED
```

第二轮权威 run 为 `p10-x2-matched-20260904b`：matched pool exact，A0/B1 均为 `29/36` micro；
B1 mean gain `+0.0416667`、new groups 3、corrected lost groups 3、previously full-coverage cases
lost 2、hard collapse 0。fresh PostgreSQL、
scope/snapshot、Canonical=0、zero retry、trace-before-label 和 cleanup 均通过。由于第 13 节终态
优先级 2 先于 continuation opportunity 不足，X3/X4/formal effect 停止。
原 sealed scorer 的 per-group coverage/first-loss 不一致少列一个 loss；派生 correction receipt
`167ee995…18a9d` 绑定同一 immutable trace/labels，未改写原 artifact，且不改变 H1/终态。
v3 receipt `065812c5…b5659` 又将 runner 的 H1 threshold 从 group loss 对齐到本合同冻结的
previously-full-case loss；本 run 为 2，仍为失败。
