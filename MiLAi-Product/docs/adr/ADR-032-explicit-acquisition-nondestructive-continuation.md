# ADR-032：Explicit Acquisition 与 Non-Destructive Retrieval Continuation

状态：`ACCEPTED / ENGINEERING IMPLEMENTATION AUTHORIZED / EFFECT CLAIM GATED`  
日期：`2026-09-04`  
适用范围：Product-11；Runtime/PostgreSQL/Testkit/MCP evidence context  
Schema：`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## 背景

Product-10 的 matched audit 证明新增 first-call Evidence 会在固定 16,384-token envelope 中造成
budget/adjacency displacement；另有 required turn 只因 anchor 邻接关系而偶然可见。继续调整同一
first-call admission 无法分别归因这两个问题。

现有 `previous_context_id` 定位 task-free Context capsule，主要语义是完整 receipt reuse/fallback，
不是可恢复的 retrieval frontier。migration 0031 的 capsule 合同不能被改写。现有
adjacent hydration 也不能继续暗中决定某个 Evidence 是否被发现。

## 决定

### 1. Retrieval continuation 是独立的非 Canonical 状态

新增 append-only `RetrievalContinuationState`，不复用或修改旧 ContextReceipt 的受保护 section。
它只持久化 identity、digest、cursor、budget metadata 与过期时间，不复制 Evidence 正文，不产生
ClaimVersion、ClaimHead、OpenIssue 或任何 authority 提升。

建议持久模型：

```text
milai.retrieval_continuation_state
  tenant_id
  state_id
  root_state_id
  predecessor_state_id nullable
  generation
  payload_semantics_version
  operation_fingerprint nullable for root
  principal_binding_digest
  scope_digest
  authority_floor
  consistency_floor
  snapshot_as_of
  canonical_position
  original_query_hash
  operation_query_hash
  route_plan_digest
  frontier_digest
  frontier_candidate_refs jsonb
  route_cursors jsonb
  exhausted_routes jsonb
  seen_anchor_evidence_ids jsonb
  seen_rendered_turn_ids jsonb
  seen_source_span_refs jsonb
  budget_history jsonb
  state_digest
  state_bytes
  created_at
  expires_at
```

主键为 `(tenant_id, state_id)`；`operation_fingerprint` 对非 root successor 建立数据库唯一约束。
predecessor/root 关系只能指向同一 tenant，successor insert 后不可更新语义字段。

### 2. 幂等性属于数据库，不属于 transport

successor 指纹为：

```text
SHA256(canonical_encode(
  predecessor_state_id,
  predecessor.generation + 1,
  query_hash,
  principal_binding_digest,
  scope_digest,
  root_snapshot_as_of,
  payload_semantics_version
))
```

repository 使用单事务 insert-or-read：相同指纹返回相同 successor；不同 residual query hash 形成
显式 branch。HTTP/MCP `request_id` 只记 trace，不参与 correctness。

### 3. X1 primary 只恢复旧 frontier

第一次 resolve 在同一次 official acquisition 中封存：

```text
ordered eligible post-governance candidates
shown exact Evidence/turn identities
remaining exact candidate refs
route plan + resumable cursor predecessor
root snapshot/canonical position
frontier digest
```

同 query 的第二次 A1 调用：

```text
global reacquisition       0
candidate-pool extension   0
query replanning           0
candidate origin           PERSISTED_FRONTIER only
```

从第一次 state 已持久化的 route cursor 取下一页允许标为 `PERSISTED_FRONTIER`；新增 route、重新执行
global source search 或改变 query plan 不允许。residual acquisition 仅属于 A1R 分支，origin 必须是
`RESIDUAL_ACQUISITION`，不得进入 C1 primary score。

### 4. 在线治理优先于旧 snapshot

root snapshot、canonical position 与 query plan 固定不漂移；每次读取 frontier 仍在线重验：

```text
tenant / principal / project / scope
authority / consistency floor
permission / retention / revocation
Evidence content identity
state digest / predecessor / generation
```

unknown、not-owned、expired、tampered 与 scope mismatch 对调用方使用同一 fail-closed 外观，不泄漏
state 是否存在。被撤销或不可读 candidate 不返回正文，并进入 typed trace。

### 5. Continuation assertion 只陈述可证明的运行时事实

```text
available=true
  当前 state 已持久且可恢复；在线重验后有 eligible frontier item

available=false / FRONTIER_EXHAUSTED
  当前 query lineage 的 sealed plan 中，已执行 official routes 有可验证 exhaustion receipt

continuation=null
  persistence、identity、snapshot 或 exhaustion 无法证明
```

`FRONTIER_EXHAUSTED` 不表示 semantic completeness、corpus exhaustion、memory 中没有其他相关内容，
也不表示不存在有用 residual query。资源上限、调用预算、过期、权限变化和 transport 错误必须使用
各自 typed reason。

Phase D1 implementation ceiling：D1 仅保存 post-acquisition exact candidate frontier，尚无 official
route-exhaustion receipt。因此 D1 的候选池耗尽必须使用 `PERSISTED_FRONTIER_EXHAUSTED`，在线
permission/retention/revocation/content-identity 变化导致无可用项时使用
`FRONTIER_ELIGIBILITY_CHANGED`；二者均不得升级成 `FRONTIER_EXHAUSTED`。

D1 Call 2 是 render-only continuation：通用 Context compiler 的 adjacent hydration 必须关闭，
`selected_evidence_ids` 必须是 predecessor persisted frontier 的子集。不得以 renderer enrichment
打开新 Evidence identity 或改变 predecessor snapshot。

### 6. 状态树资源上限由 profile 所有

```yaml
max_frontier_refs_per_state: 120
max_generation: 4
max_successors_per_state: 8
max_states_per_root: 16
max_state_bytes: 262144
```

这些值不能由 MCP model input 覆盖。触限 fail closed，使用
`FRONTIER_STATE_LIMIT_REACHED`、`GENERATION_LIMIT_REACHED`、
`SUCCESSOR_LIMIT_REACHED`、`ROOT_STATE_LIMIT_REACHED` 或 `STATE_SIZE_LIMIT_REACHED`；不静默截断，
不冒充 `FRONTIER_EXHAUSTED`。

### 7. Fine acquisition 与 hydration 分层

在 official coarse source/session pool 内执行受限 turn/span retrieval：

```text
lexical channel
+ optional frozen Dense channel
+ existing typed entity/time filters
→ exact turn/span candidates
```

fine channel 不得打开新的 global source region。候选使用 stable Evidence/turn/span identity hard
dedup；source/session/time/semantic similarity 只能 soft rank。trace 必须区分：

```text
DIRECT_ANCHOR
HYDRATION_ONLY
```

X2 首先只运行 SHADOW，不改变 public Context。只有 X2 gate 通过的最小 variant 才能进入 frontier。
hydration 不能创建 frontier candidate，不能获得 direct-discovery credit。

### 8. Renderer 分两阶段且独立回滚

X3-0 只让通过的 fine candidate 进入 persistent frontier，first-call projection 保持 A0。X3-1 才可
启用：

```text
Pass 1  emit all admitted direct anchors
Pass 2  spend remaining tokens on optional adjacent hydration
```

Pass 2 不得驱逐 Pass 1 anchor。若 X3-1 回归，保留 X3-0，renderer flag 回到 OFF。

### 9. 功能开关与公共协议

实现至少由以下 Runtime-owned flags 隔离，默认全部关闭：

```text
MILAI_RETRIEVAL_CONTINUATION_V0_1_ENABLED=false
MILAI_INTRA_SOURCE_ACQUISITION_V0_1_MODE=OFF
MILAI_ANCHOR_FIRST_RENDERER_V0_1_ENABLED=false
```

长期 fine mode 只允许 `OFF | SHADOW | FRONTIER`；D2 Engineering 实现当前只接受
`OFF | SHADOW`，`FRONTIER` 必须等待 X2 effect gate。公开 MCP 输入继续严格为：

```text
query + optional previous_context_id
```

不增加 tenant、scope、snapshot、budget、route、frontier、seen IDs 或 label 参数。MCP renderer 只转发
Runtime 已证明的 assertion，不自行推断。

## 数据库与 migration 决策

Engineering Mode 使用链尾之后的 migration `0052` 新增表、RLS、约束和 SECURITY DEFINER
procedure，由 `0053` hardening principal/identity/replay/resource validation，并由 `0054` 增加
exact coarse Evidence ID 驱动的 governed lexical intra-source SHADOW read。不得改写 0001--0049。
migration 必须提供：

- upgrade、兼容说明和明确 downgrade/irreversibility 说明；
- root create、successor insert-or-read、owned-state lookup 与 cleanup procedure；
- real PostgreSQL 的 RLS、并发幂等、branch、TTL、revocation/deletion/cleanup 测试；
- migration owner/API/worker 权限分离；PUBLIC 无直接执行权。

X0 未通过时不得发布 Product-11 量化效果 claim，也不得消费 Formal 500；但在公开协议不扩张、功能
开关默认关闭且核心安全不变量通过真实 PostgreSQL 验证的前提下，不再阻塞最小 Engineering Mode
实现。任何 in-memory state 仍不得冒充 persistence。

## 不变量

- PostgreSQL Canonical Core 仍是唯一正式状态源；continuation state 非 Canonical。
- retrieval、fine acquisition、Context、MCP 与模型都不能提高 authority。
- live revocation/permission 收紧优先于历史 snapshot。
- exact shown identity 不得在 continuation 新 Evidence 中重现。
- same source/session 的不同 stable identity 仍独立 eligible。
- Product 与 MCP 不读取 case ID、答案或 human instance group。
- Reader、vLLM、model-generated COMPLETE、automatic semantic retry 保持 0。
- first-call token budget、Top-k 与 Host prompt 不因本 ADR 增大或改变。

## 验收与回滚

直接验收由 `MILA_PRODUCT-11_ACCEPTANCE_CONTRACT.md` 所有。关闭三个 flag 后恢复 Product-10 最终
A0 行为；非 Canonical state 等待 TTL 或由 run-owned cleanup 删除。不得删除或重写旧 ContextReceipt。

## 被拒绝的方案

- 第二次同 query 重新 search 后排除 seen：不能证明 persisted-state continuation。
- 把 frontier 塞进 migration 0031 task-free capsule：改变已应用合同且混淆 Context 与 retrieval state。
- 以 request ID 保证幂等：transport identity 不稳定且不能正确表达 branch。
- 让 hydration 贡献 discovery：anchor 改变会再次造成 accidental recall。
- 生成 instance key/count/set membership：恢复隐藏 Reader 并泄漏 scorer 语义。
- 扩大 first-call budget/Top-k：不能解决 displacement 的结构原因。

## 当前处置

用户后续明确把普通产品开发与研究性效果声明分离。最小 persisted-frontier continuation 可按
Engineering Mode 增量实现和真实 E2E 验证；X0 的人工 seal、opportunity count 与预注册指标只在
声明 P11-C1/P11-C2 效果时恢复为 hard gate。Formal 500 仍不得访问或计分，Schema 继续
`NO-GO FOR SCHEMA FREEZE`。
