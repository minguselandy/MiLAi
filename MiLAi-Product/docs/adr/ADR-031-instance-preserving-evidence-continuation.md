# ADR-031：Instance-preserving Evidence 与持久 Continuation Frontier

状态：`ACCEPTED / X1 IMPLEMENTED / X2 REJECTED DEFAULT-OFF / X3 NOT ENTERED`
日期：`2026-09-03`
适用范围：Product-10；Runtime/Testkit/PostgreSQL procedure/MCP evidence-context
Schema：`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## 背景

Product-10 要求不同 `evidence_id` 不因语义或 session/source 相似而硬合并，并要求
`previous_context_id` 能在同 principal、scope 与 snapshot 下继续未展示 Evidence frontier。

当前实现只部分满足：

- final acquisition/retrieval dedup 以 `evidence_id` 为键，但
  `application/evidence_acquisition.py::_exclude_seen_candidates` 还会按 `source_ref` 硬排除；
- default-off budget-stable Context 路径可能以 normalized semantics 硬省略不同 Evidence；
- `MemoryResolveService` 对 `previous_context_id` 只做完整 receipt reuse，miss 后重新检索；
- `EvidenceContextReceipt.persisted` 固定为 `false`；
- migration 0031 的 `create_task_free_context_capsule` 只接受五个固定 section，要求非空
  Canonical ClaimVersion items，并通过 Canonical Gate 重验；Evidence-only frontier 无法满足；
- `memory-evidence-context-v1` 已有 nullable `continuation`，MCP 只转发 Runtime assertion。

因此不能把 frontier 塞进旧 receipt、修改 0031，或仅凭 Context 截断推断 continuation。

## 拟议决定

本 ADR 冻结实现方向。用户已授权代码、effect run 与 migration，但实现仍受 X0/X1 evidence gate
约束。

### 1. Evidence identity

硬 identity 只有稳定 `evidence_id`：

```text
exact same evidence_id                hard dedup / hard seen exclusion
different evidence_id                 always remains independently eligible
source_ref / session / turn / time    soft ranking only
semantic similarity                   soft ranking only
Lab InstanceEquivalenceGroup          evaluation only; never Product input
```

B1 只有在 X1 证明 `DISCOVERED_NOT_ADMITTED` 或 `INSTANCE_DESTROYING_COLLAPSE` 是首损时才实现。
原 candidate order 必须保留为 fallback；任何 feature 失败都退回原顺序，而不是删除 candidate。

### 2. X1 trace publication

现有 `ProductRetrievalAuditObserver`、`ProductRetrievalTraceV01` 和
`OfficialRetrievalAuditProbeExecutor` 是首选基础。获授权后通过独立、默认关闭的
`PRODUCT_TESTKIT` entrypoint 发布，不挂到普通 Runtime/MCP 请求：

```text
official repository occurrence
→ channel order / cutoff
→ cross-channel union
→ exact Evidence-ID dedup
→ hydration / governance
→ Context admission trace
→ MCP rendered Evidence IDs / turn refs
```

Runtime trace 不读取 Lab label。Lab 在 trace 完成后，以 Evidence ID/turn ref 映射 sealed
InstanceEquivalenceGroups。Product trace 必须继续拒绝 expected answer、equivalence group 和
correctness fields。

### 3. Frontier 是第一次读取时的候选快照

continuation 不重新运行全局 discovery 来伪装“同 snapshot”。第一次读取必须在同一官方执行中
形成一个有序、去重、已通过当时治理检查的 candidate snapshot：

```text
shown = Host-visible exact Evidence IDs
remaining = post-governance / pre-Context-admission ordered Evidence IDs - shown
frontier_digest = SHA256(canonical candidate identities + content hashes + snapshot identity)
```

第二次调用只在这份 persisted remaining frontier 内软重排；它继承第一次读取的
`source_snapshot_as_of` 与 projection identity。当前 live revocation、permission、retention 和
scope 仍须在线重验，因此 snapshot 不能冻结访问权。

当前 `RetrievalTrace.accepted_candidates` 只覆盖最终 selected result，不能单独证明 unseen
frontier。实现必须从同一次 Product execution 的 pre-admission candidate/lifecycle snapshot 构造
frontier，并把其 canonical digest 写入 capsule；不得用第二次 search 补写，也不得读取 Lab label。

### 4. 复用表，不复用旧 receipt contract

若 X0/X1 证明至少 6 个真实 opportunity，且另行授权 migration，则新增一个只追加的
`create_evidence_continuation_capsule` SECURITY DEFINER procedure。它复用现有
`context_capsule`、`context_pointer` 与 `retrieval_trace` 表，不新增表或列；不得修改 0001--0049
中的任何 migration。

新 capsule subtype 使用独立、精确的 protected-section contract：

```yaml
EVIDENCE CONTINUATION STATE:
  schema_version: evidence-continuation-state-v0.1
  principal_scope_digest:
  source_snapshot_as_of:
  projection_identity: {}
  query_history:
    - query_digest:
  shown_evidence_ids: []
  shown_source_turn_refs: []
  remaining_frontier_identity:
    digest:
    ordered_candidates:
      - evidence_id:
        source_turn_ref:
        content_hash:
        original_rank:
  budget_used:
    official_memory_calls:
    candidates:
    context_tokens:
  continuation_request_digest:
  predecessor_context_id:
RETRIEVED EVIDENCE: []
FRONTIER POINTERS: []
TRACE POINTERS: {}
RECEIPT METADATA: {}
```

`principal_scope_digest` 使用 canonical JSON 的 tenant、actor、project/requested scope、authority、
consistency、valid/known time 与 historical policy 计算；不包含 credential 或 prompt。
procedure 必须验证 session context、trace owner、Evidence tenant/scope/readability、content hash、
`0 < TTL <= 1 day`、byte budget、section exactness 与 digest。shown 和 remaining Evidence 均由 ContextPointer
绑定并在 continuation 时在线复验。

### 5. 不可变 successor chain

ContextCapsule 不原地更新。一次合法 continuation 创建 successor capsule：

```text
previous capsule
  -- exact predecessor + residual-query/budget digest --> successor capsule
```

successor 累加 query digests 与 shown IDs，并从 remaining 移除本轮 exact Evidence。相同
predecessor/request digest 在事务 advisory lock 内返回同一 successor，实现 retry idempotency；
不同 request 可形成显式分支，但每个 successor 都绑定同一 root snapshot。Product-10 实验预算
最多两次 official memory calls，达到上限时不再声称可继续。

### 6. `previous_context_id` 分派与 fail-closed

Runtime 先识别 capsule subtype：

- legacy `context-receipt-v0.1`：保留现有 exact reuse/fallback 行为；
- `evidence-continuation-state-v0.1`：只执行 persisted frontier continuation，不在同一调用偷偷改为
  新 snapshot 的全局 search；
- unknown/not-owned/expired/invalid：不泄漏存在性，不返回旧 Evidence；可在当前 scope 做独立
  fresh read，但必须标明 continuation 未发生且 `continuation: null`；
- snapshot/projection identity 无法验证、存储不可用或在线治理失败：fail closed，不生成 available
  assertion；
- revoked/unreadable frontier candidate：删除其本轮资格并记录 typed reason，不回显内容。

### 7. Runtime 与 MCP assertion

现有 MCP schema 不变。Runtime 只有在 capsule 持久成功且至少一个在线可读 remaining candidate
存在时返回：

```json
{"continuation": {"available": true, "reason": "UNSEEN_EVIDENCE_FRONTIER"}}
```

只有对完整 persisted frontier 在线重验后为空，才可返回：

```json
{"continuation": {"available": false, "reason": "FRONTIER_EXHAUSTED"}}
```

达到 Product-10 调用预算使用 `CALL_BUDGET_EXHAUSTED`，不可冒充 frontier exhausted。无法证明时
保持 `continuation: null`。MCP renderer 不推断、不改变 reason。

## 安全与不变量

- same tenant/actor/project/scope/authority/consistency/as-of 不匹配时不得继续；
- exact shown `evidence_id` 不得再次进入 successor 的新 Evidence；
- 同 session 的不同 `evidence_id` 始终可选；
- live revocation 和权限收紧优先于旧 snapshot；
- Evidence 与 capsule 都不能触发 ClaimVersion、Canonical commit 或 OpenIssue settlement；
- query history 只保存 digest；Product 不保存 Lab instance/count/set labels；
- trace 与 response 不含 score、expected answer、credential 或 Evidence 正文副本；
- database unavailable 时不得降级为内存中伪持久 frontier。

## 兼容与回滚

实现必须由新的 default-off flag 隔离，例如：

```text
MILAI_INSTANCE_PRESERVING_ADMISSION_V0_1_ENABLED=false
MILAI_EVIDENCE_CONTINUATION_V0_1_ENABLED=false
```

关闭 flag 后恢复 Product-09 A0：legacy receipt reuse/fallback 和 `continuation: null`。公共 MCP
request/response schema、Host prompt、Reader、Canonical procedure 均不改变。已创建的非 canonical
capsule 只等待 TTL 到期；不做破坏性 downgrade。

## 验证门

获授权后的直接测试至少覆盖：

1. semantic-identical 但不同 Evidence ID 均保留；same-source/same-session unseen turn 可选；
2. exact Evidence ID dedup 和 shown exclusion；原 A0 fallback identity set 不丢失；
3. trace observer 行为中性、label-free、snapshot-bound，Context 与 MCP identity 可联结；
4. other actor/tenant/project/scope、expired、tampered digest、snapshot drift 全部 fail closed；
5. revoked/permission-changed/content-hash-changed frontier 不可返回；
6. successor chain、query history、budget、same-request idempotency；
7. legacy receipt 行为不变，unknown ID 不泄漏；
8. MCP 只转发 proven available/exhausted/null；
9. fresh PostgreSQL procedure/RLS/pointer/TTL/cleanup；
10. recall-side Canonical mutation、Reader/vLLM、automatic retry 均为零。

H1/H2 effect gate、最多 8 个 real Codex case 与 formal holdout 仍由 Product-10 Goal/Lab Plan 所有。

## Product-10 执行处置

X0/X1 已完成。X1 证明 admission 是首损，随后两个通用 B1 机制在 matched candidate pool 上均未
通过 H1：第二轮虽新覆盖 3 个 group，但丢失 3 个已覆盖 group，其中 2 个原完整 case 退化；
mean gain `+0.0416667` 小于 `+0.05`。因此 B1 代码只保留为默认关闭的研究/审计候选。

sealed slice 的 continuation opportunity 只有 A0/B1 `1/2` 个，未达到 6 个的实施门。故本 ADR
中的 capsule/procedure/successor 设计没有实现，没有 migration 或伪 frontier，公开
`memory-evidence-context-v1` 继续只转发 Runtime 可证明的 continuation，否则为 `null`。

Product-10 终态为 `PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED`；未来若重新开启，必须作为
新的 representation/acquisition Goal，不能在本 Goal 内增加第三轮规则。

派生 scorer v3 `065812c5…b5659` 已把 H1 threshold 从 group-level zero-loss 对齐到冻结的
previously-full-case zero-loss；group loss 3 保留为诊断，full-case loss 2 才是判门字段。

## 原授权门（执行结果）

本 ADR 已接受、尚未实现。以下事实必须先成立：

```text
X0 effect authorization granted                    yes
sealed A0 provenance bundle complete                 yes
X1 proves B1 need or B1 = NOT_NEEDED                 yes / B1 required
at least 6 sealed continuation opportunities         no / observed 1 A0, 2 B1
separate Product code + migration authorization granted  yes
```

机会门未满足，因此保持 `continuation: null`（除非既有 Runtime 自身提供证明）；未创建
continuation migration 或 procedure。
