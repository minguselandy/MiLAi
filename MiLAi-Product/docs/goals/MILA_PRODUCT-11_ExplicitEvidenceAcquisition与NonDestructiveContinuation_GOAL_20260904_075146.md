---
document_id: MILA-PRODUCT-11
version: "0.2"
status: PLANNED_NOT_AUTHORIZED
created_at: "2026-09-04T07:40:04+08:00"
amended_at: "2026-09-04T07:51:46+08:00"
product_version: 0.1.0-candidate
schema_status: 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
predecessor: MILA-PRODUCT-10@1.3
frozen_baseline_tree: 0b170d3fdeaf962c26492578293d29a7fcc1c9036555f8adb01b121f41cba7b5
frozen_baseline_lock_digest: 4bf9ee438c92a5c4545bbcd05e940136d6f0e477f89a10cf5366663640b6d68b
execution_authorized: false
product_code_authorized: false
database_migration_authorized: false
opened_development_effect_authorized: false
real_codex_authorized: false
formal_holdout_authorized: false
---

# Product-11：Explicit Evidence Acquisition 与 Non-Destructive Continuation

## 1. Goal

在保持 Product-09/10 Host 与 MiLAi 边界、不引入生成式 Reader、不扩大 MCP 模型参数面的
前提下，分别解决 Product-10 暴露的两个机制问题：

```text
adjacent hydration 暗中承担召回
  → anchor 改变后，原本“碰巧可见”的 required turn 变成 NOT_DISCOVERED

新增 Evidence 与旧 Evidence 竞争同一个 16,384-token first-call Context
  → 新覆盖通过 budget / adjacency displacement 挤掉旧覆盖
```

目标架构是：

```text
Query
  → coarse source/session acquisition
  → explicit intra-source turn/span acquisition
  → governed Evidence anchors
  → first-call Context
  → persistent retrieval frontier
  → previous_context_id-bound novel Evidence continuation

Optional adjacent hydration
  = renderer enhancement only
  ≠ discovery
  ≠ frontier construction
```

MiLAi 只负责找到、治理、组织和增量暴露 Evidence；Host 继续负责判断是否足够、提出 residual
query、决定是否继续以及形成最终回答。

## 2. Product-10 冻结事实与继承边界

Product-10 已终止为：

```text
PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED
```

权威第二轮 opened-development 结果：

```text
A0 / B1 micro coverage                     29/36 / 29/36
mean DistinctInstanceCoverage gain         +0.0416667
newly covered groups                       3
lost groups                                3
previously full-coverage cases lost        2
hard identity collapse                     0
scope / snapshot / Canonical violation     0
```

两个 C50 budget loss 的 activation threshold 为 `17,332 / 16,971`，超过固定 `16,384`
Context budget；另一个 loss 来自 anchor 改变后 adjacent hydration 不再覆盖 required turn。
因此根因是 `budget + adjacency displacement`，不是 Evidence identity collapse。

Product-11 不追溯改写 Product-10，也不得作为 Product-10 的第三轮 B1。继承以下冻结边界：

```text
Product baseline tree
  0b170d3fdeaf962c26492578293d29a7fcc1c9036555f8adb01b121f41cba7b5

Product baseline lock digest
  4bf9ee438c92a5c4545bbcd05e940136d6f0e477f89a10cf5366663640b6d68b

MILAI_READER_INSTANCE_PRESERVING_ADMISSION_V0_1_ENABLED=false
public MCP tool schema = query + optional previous_context_id
internal Reader calls = 0
vLLM calls = 0
automatic semantic retries = 0
recall-side Canonical mutation = 0
```

Product-10 的 model-assisted proxy labels 不能直接成为 Product-11 gold。Product-11 必须重新
封存人工确认的 opened-development slice；formal 500 不用于选例、标注、调参或 effect run。

## 3. Claim map

| Claim | 为什么重要 | 最小可信证据 | Block |
| --- | --- | --- | --- |
| P11-C1：stateful continuation 在不改变 first-call Evidence 的前提下，仅恢复 persisted frontier 并增加 novel cumulative Evidence | 从结构上消除固定 16K first-call displacement，并排除 repeated retrieval 混淆 | first-call semantic digest 100% 匹配 A0；Call 2 global reacquisition/pool extension=0；novel candidate origin 100% 为 `PERSISTED_FRONTIER`；seen exact identity repeat=0；continuation opportunity 上 cumulative coverage 显著增加 | X1、X3 |
| P11-C2：explicit intra-source turn acquisition 能直接找回 required turn，而不是依赖 adjacent hydration | 消除 anchor 变化导致的 accidental recall | 相同 coarse source pool 内，`NOT_DISCOVERED → DIRECTLY_ACQUIRED`；hydration-only visibility 不计 discovery；已直接覆盖实例不回归 | X2、X3 |

必须排除的 anti-claim：

```text
收益只是 first-call Top-k 或 token budget 增大
收益只是重新排序后挤掉旧 Evidence
收益来自 adjacent neighbor 碰巧包含 gold turn
收益来自 Lab label、答案、case ID 或 LLM-generated instance_key 泄漏
收益来自第二次从头 top-k，而非真实 retrieval state
```

P11-C1 与 P11-C2 是独立 effect claim。实现顺序先 X1 后 X2，但 X1 effect 失败不得被解释为
X2 失败，X2 effect 失败也不得被 continuation 的收益掩盖。只有两者和集成门均通过，才可给出
完整 Product-11 可用性结论。

## 4. 不做什么

本 Goal 不优化或修改：

```text
Host prompt
MCP public input schema
Canonical State / Claim model
Reader / EvidenceLedger
vLLM / model-generated COMPLETE
LLM-generated count / set_members / event_type / instance_key
formal holdout
```

不允许：

- 第三轮 Product-10 admission 调参；
- case ID、gold quote、reference answer、人工 group label 进入 Product；
- 通过增大 first-call `max_context_tokens`、`max_results` 或 `max_candidates` 获得效果；
- 把 session/source/span 相似性当作硬去重或语义完备证明；
- 让 continuation 重放第一次 Context 后冒充 novel Evidence；
- 修改已应用 migration、旧 ContextReceipt 或 migration 0031 的 task-free capsule 语义；
- 因 COUNT 答案错误恢复隐藏 Reader。

## 5. 规范读链：Anchor first，Hydration last

### 5.1 Coarse acquisition

现有 official retrieval 先确定治理范围内的 source/session 候选。它继续负责 tenant、project、
scope、authority、retention、revocation、snapshot 和 canonical currentness，不因 P11 降级。

```text
Query
  → official coarse acquisition
  → governed source/session candidates
```

### 5.2 Explicit intra-source acquisition

对已选 source/session，在相同 scope 和 snapshot 内显式检索 turn/span：

```text
lexical turn retrieval
  + frozen Dense turn retrieval
  + existing typed entity/time filters when available
  → directly acquired turn/span candidates
```

每个直接候选必须携带 Product-owned identity/provenance：

```yaml
source_id:
session_id:
turn_id_or_span_id:
evidence_id:
content_hash:
observed_at:
acquisition_channels: []
channel_ranks: {}
scope_digest:
snapshot_as_of:
decision_digest:
```

Product 不读取 `InstanceEquivalenceGroup`，不判断两个 turn 是否代表同一个现实实例。Lexical、
Dense、entity、time 只用于 acquisition/rank；唯一允许的 identity hard dedup 是稳定 exact
Evidence/turn/span identity。

### 5.3 Discovery 与 hydration 分离

trace 必须区分：

```text
DIRECT_ANCHOR
HYDRATION_ONLY
```

强制规则：

```text
DirectAcquisitionCoverage 只计算 DIRECT_ANCHOR。
HYDRATION_ONLY turn 即使被 Host 看见，也不能把 NOT_DISCOVERED 改写为 DIRECTLY_ACQUIRED。
hydration 不得创建 frontier candidate，不得提升 authority，不得成为 hard identity owner。
已渲染 hydration turn 仍进入 seen_rendered_turn_ids，避免 continuation 重复展示相同内容。
```

### 5.4 Two-pass renderer

只有 X2 证明 explicit acquisition 有效后，才允许进入 two-pass renderer：

```text
Pass 1 — Evidence coverage
  emit governed direct anchors in stable order

Pass 2 — Presentation richness
  use remaining budget for optional adjacent hydration
```

不能按 candidate 逐个执行“anchor + 全部 neighbors”，否则前几个 candidate 的 hydration 会再次
抢占后续 anchor。第一阶段必须先对所有入选 anchor 完成预算分配；第二阶段不能驱逐第一阶段已
接受的 anchor。

## 6. `RetrievalContinuationState` 合同

内部持久对象命名为 `RetrievalContinuationState`，不命名为 `ContextContinuationState`。该命名
强制表明它保存 retrieval frontier，而不是一个更大的 rendered Context，也不复用 Canonical、
ContextReceipt 或 task-free capsule 的语义。

建议最小状态：

```yaml
state_id: opaque random identifier
root_state_id:
predecessor_state_id:
generation:
payload_semantics_version:
operation_fingerprint:

tenant_id:
principal_binding_digest:
scope_digest:
authority_floor:
consistency_floor:

snapshot_as_of:
canonical_position:
original_query_hash:
residual_query_hashes: []
route_plan_digest:
frontier_digest:

seen_anchor_evidence_ids: []
seen_rendered_turn_ids: []
seen_source_span_refs: []

frontier_candidate_refs: []
route_cursors: {}
exhausted_routes: []
budget_history: []

created_at:
expires_at:
state_digest:
```

持久化约束：

- 状态是 non-canonical、append-only successor；已消费 generation 不原地改写；
- 只持久化 identity、cursor、digest 和 budget metadata，不复制 raw Evidence text；
- RLS 同时绑定 tenant、principal 与 scope；unknown/not-owned/expired ID 不泄漏存在性；
- TTL、subject deletion、tenant cleanup 和 Evidence revocation 必须有真实 PostgreSQL 测试；
- 每次 continuation 都在线重验 permission、scope、revocation、retention 和 content identity；
- 所有 successor 固定 root `snapshot_as_of` / canonical position，不漂移到当前时间；
- 幂等性由数据库 operation fingerprint 保证，不依赖 MCP/HTTP request ID；
- state digest、predecessor、generation、root snapshot 任一不匹配都 fail closed；
- 状态不能声称 semantic completeness，也不能作为 Canonical truth 或 authority source。

规范操作指纹为：

```text
ContinuationOperationFingerprint =
  hash(canonical_encode(
    predecessor_state_id,
    generation,
    query_hash,
    principal_binding_digest,
    scope_digest,
    root_snapshot_as_of,
    payload_semantics_version
  ))

generation = predecessor.generation + 1
```

其中 `query_hash` 是本次 continuation payload 的规范化 query hash：A1 primary 必须等于
`original_query_hash`；A1R residual branch 使用该预封存 residual query 的 hash。

数据库必须对 `operation_fingerprint` 建立 `UNIQUE` 约束，并以原子 insert-or-read 实现：

```text
same predecessor + same query + same principal/scope/snapshot/semantics
  → same successor

same predecessor + different residual query
  → explicit branch with a different operation fingerprint
```

`request_id` 可以进入 trace 用于传输诊断，但不得进入 correctness key，也不得成为 successor
幂等性的必要条件。

### 6.1 Profile-owned state resource limits

以下限制由 Runtime profile 所有，不是模型参数，也不扩张 MCP public schema：

```yaml
max_frontier_refs_per_state: 120
max_generation: 4
max_successors_per_state: 8
max_states_per_root: 16
max_state_bytes: 262144
```

触限必须 fail closed，并返回可区分的 typed operational reason：

```text
FRONTIER_STATE_LIMIT_REACHED
GENERATION_LIMIT_REACHED
SUCCESSOR_LIMIT_REACHED
ROOT_STATE_LIMIT_REACHED
STATE_SIZE_LIMIT_REACHED
```

不得静默截断 frontier，不得丢弃分支后继续声称可恢复，也不得把任何资源触限报告为
`FRONTIER_EXHAUSTED`。

旧 `context_id` 仍是 MCP 暴露的 opaque locator。Runtime 可在内部将合格的 context_id 绑定到
retrieval state，但公共 MCP 参数保持：

```text
milai_memory_resolve(query, previous_context_id?)
```

不得增加 model-controlled tenant、scope、snapshot、budget、route、seen IDs 或 frontier IDs。

## 7. Continuation 算法

第二次 resolve 的共同前置步骤：

```text
1. 解析 opaque previous_context_id，不泄漏 unknown/not-owned 差异
2. 验证 same principal / tenant / project / scope / authority / consistency
3. 固定 root snapshot_as_of 与 canonical position
4. 校验 predecessor digest、generation、payload semantics 和 operation fingerprint
```

X1 primary 的 `A1-STATEFUL` 只能执行：

```text
5. 恢复 Call 1 已持久化并封存 digest 的 frontier refs / route cursors
6. 沿已持久化 route cursor 继续同一 snapshot、同一 query plan；不得重新规划或开启全局 source acquisition
7. 在线重验 frontier candidate 的 permission/revocation/content identity
8. 硬排除 exact seen Evidence/turn/span identity
9. 对 new source / turn / time / provenance 只做 soft novelty ranking
10. 只选择 candidate_origin=PERSISTED_FRONTIER 的 novel candidate
11. 在本次独立 16,384-token envelope 内渲染 novel Evidence
12. 以 operation fingerprint 原子生成或读取同一个 append-only successor
```

X1 primary 明确禁止：

```text
global reacquisition                    DISABLED
candidate-pool extension                DISABLED
query replanning                        DISABLED
RESIDUAL_ACQUISITION candidate output   DISABLED
```

从 Call 1 已持久化 route cursor 读取下一页属于 `PERSISTED_FRONTIER`，前提是 route、query plan、
snapshot 和 cursor predecessor 已在 Call 1 state 中封存；重新执行全局 search 或新增 route 不属于
cursor advancement。

只有 `A1R-RESIDUAL` 可以在共同前置步骤后执行 residual query acquisition，并在同一 root snapshot
下把新候选作为显式分支并入 frontier。trace 对每个候选强制记录：

```yaml
candidate_origin: PERSISTED_FRONTIER | RESIDUAL_ACQUISITION
origin_state_id:
origin_frontier_digest:
origin_route:
origin_cursor_before:
origin_cursor_after:
```

X1 primary 的 coverage/gain 分子只能来自 `PERSISTED_FRONTIER`。任何
`RESIDUAL_ACQUISITION` 输出只属于 A1R secondary diagnostic，不得进入 P11-C1 主指标或判门。

`source_id`、`session_id` 或粗粒度 `source_span` 不能单独成为 hard exclusion，因为同一来源内可能
仍有另一个未见实例。只有当 official route 能证明该 span 内所有 eligible exact turn identity 已
枚举并消费时，才可记录 route/span exhausted；“语义上已经覆盖”不构成证明。

公共 continuation assertion 只允许：

```text
available=true
  当前 RetrievalContinuationState 已成功持久化且可恢复；完成在线
  permission/revocation/content-identity 重验后，至少存在一个可继续消费的 eligible frontier item

available=false + FRONTIER_EXHAUSTED
  当前 query lineage 的 sealed retrieval plan 中，已经执行的所有 official routes
  在同一 snapshot 上均有可验证 exhaustion receipt

continuation=null
  无法证明 available 或 exhausted
```

`CALL_BUDGET_EXHAUSTED`、state expired、permission changed 和 transport unavailable 使用各自 typed
reason，不得冒充 frontier exhausted。

`FRONTIER_EXHAUSTED` 的 claim ceiling 固定为：

```text
current query lineage 下已执行 official retrieval routes 的 frontier exhausted
  ≠ semantic completeness
  ≠ corpus exhaustion
  ≠ memory 中没有更多相关内容
  ≠ no useful residual query exists
```

Host 后续仍可提交新的 residual query，在同一 root snapshot 下打开新的 retrieval region。

## 8. X0 — Human-sealed development slice 与合同冻结

**Claim tested**：不测试效果；建立无 leakage 的共同分母。  
**Priority**：MUST-RUN，未通过不得写 Product behavior。

### 8.1 Slice

在 opened-development 数据中，先于 treatment outcome 封存至少 24 个 case：

```text
continuation opportunity cases            >= 8
explicit intra-source opportunity cases   >= 8
control / already-complete cases           >= 8
```

三类可以重叠，但每个主 claim 必须有至少 8 个独立 opportunity。能力覆盖至少包括：

```text
Enumeration
Counting
Same class / different instances
Repeated mention / same instance
Cross-session aggregation
Update + aggregation
Continuation-required query
```

每种 capability shape 至少 3 个 case。选例依据只能是 treatment 前可见的 source structure、A0
trace 和人工 label，不能依据 P11 treatment 成败。

### 8.2 Human adjudication

每个 required group 在运行效果实验前完成一名 annotator 标注和一名独立 reviewer 确认；分歧在
seal 前解决。模型可协助提名，不能作最终裁决。sealed row 至少包含：

```yaml
case_id:
capability_shapes: []
instance_groups:
  - group_id:
    acceptable_evidence_ids: []
    acceptable_turn_refs: []
    source_ids: []
    session_ids: []
    required_for_answer: true
continuation_opportunity: true|false
intra_source_opportunity: true|false
human_adjudication_status: COMPLETE
```

封存 case order、membership、labels、source snapshot、budget、Dense model identity、scorer code 和
Product lock。Product 和 MCP 运行时不得读取 labels。formal 500 保持 `P11 scored cases = 0`。

### 8.3 Metric mathematics

所有主 gain 均采用 opportunity case 的 **macro mean**；group-level micro 汇总只能作为 secondary
diagnostic，不得替代主判门。设 case `i` 的人工 required groups 为 `R_i`：

```text
DIC_i(S)
  = |{g ∈ R_i : g has >=1 human-acceptable Host-visible exact Evidence/turn unit in S}|
    / |R_i|

ContinuationInstanceGain
  = mean_{i ∈ continuation_opportunities}
      (DIC_i(Call1 ∪ Call2) - DIC_i(Call1))

DAC_i(A)
  = |{g ∈ R_i : g has >=1 human-acceptable DIRECT_ANCHOR in arm A}|
    / |R_i|

DirectAcquisitionCoverageGain(Bx)
  = mean_{i ∈ intra_source_opportunities}
      (DAC_i(Bx) - DAC_i(B0))
```

case-level recovery rate 与 group-level count 分开冻结。令：

```text
ContinuationOpportunityRecoveryRate
  = |{i ∈ continuation_opportunities : DIC_i(Call1 ∪ Call2) > DIC_i(Call1)}|
    / |continuation_opportunities|

NewDirect_i(Bx)
  = {g ∈ R_i : g has no DIRECT_ANCHOR in B0
                 AND g has >=1 DIRECT_ANCHOR in Bx}

IntraSourceOpportunityRecoveryRate(Bx)
  = |{i ∈ intra_source_opportunities : |NewDirect_i(Bx)| >= 1}|
    / |intra_source_opportunities|

NewDirectRequiredGroups(Bx)
  = sum_{i ∈ intra_source_opportunities} |NewDirect_i(Bx)|

LostDirectRequiredGroups(Bx)
  = sum_i |{g ∈ R_i : g has >=1 DIRECT_ANCHOR in B0
                      AND g has no DIRECT_ANCHOR in Bx}|
```

因此 `>=50% opportunity recovered` 始终是 case-level rate，`new groups >=4` 始终是跨 opportunity
case 的 group-level count；两者不得互换。所有 `previously full ... cases lost` guard 也只计算
baseline full case 是否在 treatment 变为非 full，不得以 `lost_groups=0` 代替。

`Call1 ∪ Call2` 按 exact Evidence/turn/span identity 去重。continuation opportunity 与 intra-source
opportunity membership 在 treatment 前由 A0 trace、source structure 和人工 label 封存，不能按
treatment outcome 重选。

机会定义同时冻结为：

```text
continuation_opportunity_i =
  DIC_i(Call1) < 1
  AND Call 1 sealed frontier/ref-or-cursor path contains >=1 eligible unseen acceptable unit

intra_source_opportunity_i =
  selected coarse source/session pool contains >=1 acceptable required turn/span
  that is not DIRECT_ANCHOR under B0
```

“contains”由 scorer 对 sealed trace 与 human label 做离线 join 判定；不得把 label 写回 frontier，
不得为了满足 opportunity 数量改变 Product acquisition。

重复率按 case 定义。令 `n_{i,g}(A)` 为 arm `A` 的 cumulative Host-visible Context 中，由人工
label 映射到 required group `g` 的 exact Evidence/turn units 数量：

```text
DIR_i(A)
  = sum_{g ∈ R_i} max(0, n_{i,g}(A) - 1)
    / sum_{g ∈ R_i} n_{i,g}(A)

DuplicateInstanceRate(A)
  = mean DIR_i(A) over eligible opportunity cases with a non-zero denominator
```

分母为 0 的 case 报 `NA`，不得按 0 注入平均值。所有 acceptable mapping、group membership 和上述
计算只存在于 trace 完成后加载的 scorer；Product Runtime 永远不知道 human group。

### 8.4 X0 gate

```text
case count                                               >= 24
human adjudication COMPLETE                              100%
continuation opportunities                               >= 8
intra-source opportunities                               >= 8
capability shape minimum                                 >= 3 each
acceptable_evidence_id overlap across distinct groups    0
acceptable_turn_ref overlap across distinct groups       0
source_id overlap across distinct groups                 allowed
session_id overlap across distinct groups                allowed
Product label access                                     0
formal cases scored                                      0
```

机会不足时终止为 `PARKED_PRODUCT11_INSUFFICIENT_HUMAN_SEALED_OPPORTUNITY`，不能从少量 case 榨取
参数，也不能消费 formal holdout 补数。

## 9. X1 — P11-A Non-Destructive Continuation

**Claim tested**：P11-C1。  
**Why**：证明跨调用 cumulative acquisition 能解决 budget displacement，而不改 first-call A0。  
**Priority**：MUST-RUN。

### 9.1 Arms

```text
A0-FRESH2
  Call 1 = frozen Product-10 A0 first read
  Call 2 = same query, fresh resolve, no previous_context_id

A1-STATEFUL
  Call 1 = semantically identical frozen A0 first read
  Call 2 = same query + previous_context_id
  query_hash = original_query_hash
  global reacquisition = DISABLED
  candidate-pool extension = DISABLED
  output candidate_origin = PERSISTED_FRONTIER only

A1R-RESIDUAL (secondary diagnostic)
  Call 2 = presealed Host-style residual query + previous_context_id
  residual acquisition and frontier merge = allowed
  new candidate_origin = RESIDUAL_ACQUISITION
```

Primary comparison使用同一个 query，避免把更好的 query rewrite 误认为 continuation state
收益。A1R residual query 只能基于原始问题和 A0 public Context 预先生成，不得读取 hidden label、
reference answer 或 treatment output，也不进入主判门。

Call 1 必须在 Call 2 前封存 `Call1FrontierDigest`、route plan digest 和 route cursor predecessor。
A1 Call 2 的每个输出候选必须能证明属于该持久 frontier，或来自该 state 中已持久化 cursor 的合法
推进。第二次同 query 的 fresh acquisition 即使返回 novel candidate，也不能计为 stateful
continuation 成功。

### 9.2 First-call freeze

因 context_id、trace ID、latency 和 proven continuation assertion 可能不同，不要求 response bytes
相同；要求 `FirstCallEvidenceProjectionDigest` 相同。该 digest 固定包含：

```text
ordered rendered Evidence IDs
ordered source turn refs
ordered text content hashes
snapshot / canonical position
retrieval status and public warnings
resolved budget profile
```

排除 opaque context/request/trace ID、wall-clock latency 和 continuation assertion。

### 9.3 Metrics and gate

```text
paired cases                                      >= 24
continuation opportunity cases                    >= 8
FirstCallEvidenceProjectionDigest match           = 100%
FirstCallDistinctInstanceCoverage delta            = 0
previously full first-call cases lost              = 0

mean ContinuationInstanceGain on opportunities     >= +0.15
ContinuationOpportunityRecoveryRate                >= 50%
primary novel candidates from PERSISTED_FRONTIER    = 100%
global reacquisition calls in A1 Call 2              = 0
candidate-pool extensions in A1 Call 2               = 0
exact seen Evidence repeats                        = 0
exact seen rendered-turn repeats                   = 0
DuplicateInstanceRate                              <= A0-FRESH2

principal/scope/snapshot drift                     = 0
revoked/unreadable frontier returned               = 0
Canonical mutation                                 = 0
Reader/vLLM/automatic semantic retry               = 0/0/0
```

`CumulativeDistinctInstanceCoverage` 对 Call 1 与 Call 2 的 exact visible identity 做 union 后计算，
不重复计数。另报 MiLA cumulative coverage 与 Host 实际保留/传入模型的 coverage，避免 Host
conversation trimming 被错误归因给 MiLA continuation。

本节所有 primary gain 和 duplicate comparison 使用 §8.3 的 macro 定义，并只接受
`candidate_origin=PERSISTED_FRONTIER` 的 A1 Call 2 candidate。A1R 结果单列，不与 A1 合并。

如果 A1 没有 novel gain，但 X0 已证明旧 frontier 存在，归因到 state/cursor/selection；不得扩大
first-call budget。若旧 official frontier 本身没有 required turn，归入 X2 acquisition，不在 X1
调 continuation rank。

## 10. X2 — P11-B Explicit Intra-Source Acquisition

**Claim tested**：P11-C2。  
**Why**：把 accidental adjacency recall 替换为可审计的 direct acquisition。  
**Priority**：MUST-RUN；先 SHADOW，不改变 public Context。

### 10.1 Arms

```text
B0-OFFICIAL
  current coarse acquisition + current direct anchors
  adjacent turns 标记 HYDRATION_ONLY

B1-LEXICAL-SHADOW
  same coarse source/session pool
  explicit lexical turn/span acquisition
  no public rendering change

B2-LEXICAL-DENSE-SHADOW
  B1 + frozen real Dense turn/span acquisition
  no public rendering change
```

若 B1 已满足全部 gate，优先选择 B1，Dense 不作为装饰性复杂度加入。若只有 B2 通过，必须报告
Dense model/version/index identity 与 incremental gain，且禁止使用 vLLM 或生成式 reranker。

### 10.2 Fixed work envelope

X0 在 outcome 前固定：

```text
coarse max results                    50
coarse max candidates                 120
fine lexical hits per source          <= 8
fine Dense hits per source            <= 8
fine unique turn/span candidates      <= 120 total
Context budget                        unchanged / not used by SHADOW score
semantic retries                      0
```

相同 case 的 B0/B1/B2 必须共享 exact coarse source/session pool、scope 和 snapshot。fine retrieval
只能在这个 pool 内展开，不能悄悄增加新的全局 source search。

### 10.3 Metrics and gate

```text
paired cases                                           >= 24
intra-source opportunity cases                         >= 8
coarse source/session pool exact match                  = 100%
mean DirectAcquisitionCoverage gain                     >= +0.10
IntraSourceOpportunityRecoveryRate                       >= 50%
NewDirectRequiredGroups                                  >= 4
gain capability shapes                                  >= 2
LostDirectRequiredGroups                                 = 0
cross-source hard identity collapse                     = 0
hydration-only turn counted as direct discovery          = 0
scope/snapshot/permission violation                     = 0
```

X2 scorer 同时报告 `HostVisibleCoverage`，但它不能替代 `DirectAcquisitionCoverage`。一个 group
只有 neighbor 可见而无 direct anchor 时，Host-visible 可以为 true，directly acquired 必须为 false。
主 gain 使用 §8.3 的 `DirectAcquisitionCoverageGain(Bx)` macro 定义；micro covered-groups 汇总仅作
secondary diagnostic。

## 11. X3 — Frontier integration 与 Anchor-first renderer

**Claims tested**：P11-C1 + P11-C2 的产品集成。  
**Why**：证明 fine acquisition 能安全进入 frontier/rendering，而不是制造新的 first-call regression。  
**Priority**：MUST-RUN for full Product pass。

X3 eligibility 冻结为：

```text
X1-C1 == PASS
AND X2-C2 == PASS
AND one selected X2 minimal variant is sealed

otherwise: X3 = NOT_ENTERED
```

满足 eligibility 后按以下顺序执行：

```text
X3-0 FRONTIER_ONLY
  explicit fine candidates 只进入 persistent frontier
  first-call Evidence projection 保持 A0

X3-1 ANCHOR_FIRST
  direct anchors first
  remaining budget hydrates neighbors second
```

X3-1 只有 X3-0 通过后执行。固定 16,384-token first-call budget，不增 Top-k。判门：

```text
baseline direct anchors retained                     = 100%
previously full first-call cases lost                = 0
hydration counted as direct discovery                = 0
previously DIRECT_ANCHOR required group demoted
to HYDRATION_ONLY                                    = 0
anchor evicted by hydration                          = 0
first-call max context tokens                        = 16,384 unchanged
continuation exact seen identity repeat              = 0
cumulative coverage                                  >= selected X1 variant
scope/snapshot/revocation/Canonical violation        = 0
```

`HydrationOnlyRequiredGroups` 必须继续按 case/group 报告为 diagnostic，但它不是 X3 的零值判门。
Product-11 的 C2 是证明 explicit acquisition 带来 direct coverage gain，不在 X3 临时升级为“消灭所有
hydration-only required groups”。

如果 X3-0 通过而 X3-1 回归，保留 FRONTIER_ONLY，anchor-first 保持 default OFF，并将终态明确为
renderer unresolved；不得修改 fine acquisition 或 continuation 结果来掩盖 renderer 回归。

## 12. X4 — Memory/Host attribution

**Claim tested**：只做边界归因，不决定 retrieval mechanism 是否通过。  
**Priority**：MUST-RUN only when eligible；最多 8 个 presealed real Codex HTTP case。

只有某 case 的 cumulative required-group coverage 已完整，才能进入 Host aggregation 检查。
membership 在读取 Codex outcome 前按 case order/capability shape 封存；不修改 P08 Host instruction，
不投票，不做语义重试。记录：

```text
MiLA cumulative required Evidence coverage
Host actually retained/visible Evidence coverage
Codex exact answer and normalized F1
tool calls and previous_context_id binding
system / tool-invocation / memory / Host-reasoning failure separately
```

如果所有 required Evidence 都进入 Host 实际可见 cumulative Context，但 Codex 仍输出错误 COUNT
或集合答案，必须分类：

```text
Memory PASS
Host aggregation FAIL
```

不得因此恢复 Reader、EvidenceLedger、generated COMPLETE 或 answer-oriented prompt treatment。

## 13. Run order、修复预算与停止规则

```text
X0 human seal + contract + Product/Lab/code/input locks
  → X1 continuation effect
  → X2 fine acquisition SHADOW effect
  → X3-0 frontier integration
  → if safe: X3-1 anchor-first renderer
  → if memory-complete membership exists: X4 Host attribution
  → terminal classification
```

X1 与 X2 是独立实验结论；执行上按顺序减少同时变量。每项主机制最多允许：

```text
initial general implementation
+ one preregistered general repair
```

失败先用一个 failure case、一个不同 capability sibling 和一个正确回归验证。第二个通用版本仍未
改变首损时停止；不得添加 case-specific rank、gold token、同义词、额外 seed、额外 retry 或第三轮
规则。所有失败和 replacement 关系追加到 Lab failure ledger。

除 authority/scope/snapshot/Canonical 或 label-leakage 硬失败外，X1 effect 失败不阻止 X2，X2
effect 失败也不追溯改变 X1。X3 仅在 `X1-C1 == PASS`、`X2-C2 == PASS` 且一个 X2 最小 variant
已封存时进入；否则固定记录 `X3 = NOT_ENTERED`。

任何 effect run 必须：

- 使用全新不可覆盖 run ID；
- 在 treatment 前写 preseal 和 Product/Lab/input hashes；
- 使用每个 treatment 自己的 Product tree/lock，不复用旧 baseline pin；
- trace 完成后才加载 human labels；
- 保留 invalid run，不删除、不改写；
- fresh PostgreSQL 起始 evidence/projection/canonical 均为 0；
- 完成后验证 run-owned database volume cleanup。

## 14. 固定资源与并发预算

```yaml
transport: streamable-http
profile: MCP_INTERACTIVE_WIDE_V01
max_results_per_call: 50
max_candidates_per_call: 120
max_context_tokens_per_call: 16384
max_latency_ms_per_call: 5000
primary_total_memory_calls: 2
max_frontier_refs_per_state: 120
max_generation: 4
max_successors_per_state: 8
max_states_per_root: 16
max_state_bytes: 262144
semantic_retries: 0
votes: 0
internal_reader_calls: 0
vllm_calls: 0
formal_cases_scored: 0
```

```text
capture/projection workers         <= 8
Context effect case concurrency    1 until ephemeral-port ownership is made race-free
real Codex processes               <= 4
one isolated tenant/project        per case
```

Dense channel 必须绑定真实 model/revision/index/config digest；缺少该身份时只能报告 lexical-only，
不能声称 FTS+Dense。GPU 不是本 Goal 的必需条件；不为使用 frontier model 而强行增加模型组件。

## 15. Failure routing

| 观测 | 首要归因 | 合法动作 |
| --- | --- | --- |
| A1 first-call Evidence digest 与 A0 不同 | destructive continuation integration | 停止 effect，修 first-call isolation |
| Call 2 重复 exact seen Evidence/turn | state/exclusion bug | 修 exact identity set 或 successor CAS |
| frontier 有 required turn 但 continuation 无 novel output | cursor/selection/persistence | 修 state continuation，不增 first-call budget |
| official frontier 根本没有 required turn | acquisition | 进入/归因 X2，不调 continuation rank |
| coarse source 命中、fine retrieval 未找到 required turn | intra-source channel/cue | 在一次通用修复预算内改 channel，不用 case token |
| direct turn 已找到但 public Context 不见 | renderer/admission | 只在 X3 修 anchor-first integration |
| group 仅由 neighbor 可见 | hydration dependency | Host-visible 与 direct acquisition 分开报告 |
| cumulative memory 完整但答案错误 | Host aggregation | `Memory PASS / Host FAIL`，不恢复 Reader |
| scope/snapshot/revocation 漂移或 Canonical mutation | safety | 立即 `FAIL`，不得继续后续 Block |

## 16. Terminal states

按以下优先级选择唯一终态：

```text
FAIL_PRODUCT11_AUTHORITY_SCOPE_SNAPSHOT_OR_CANONICAL
  任一跨 tenant/project/scope、撤销泄漏、snapshot 漂移或 recall-side Canonical mutation

FAIL_PRODUCT11_FIRST_CALL_DESTRUCTIVE_REGRESSION
  stateful continuation 使 first-call Evidence projection 或原完整 case 回归

PARKED_PRODUCT11_INSUFFICIENT_HUMAN_SEALED_OPPORTUNITY
  任一主 claim 的人工确认 opportunity 少于 8

PARKED_PRODUCT11_BOTH_MECHANISMS_UNRESOLVED
  X1 与 X2 在各自两个通用版本后均未满足 C1/C2

PARKED_PRODUCT11_CONTINUATION_UNRESOLVED
  X2 已通过，但 X1 两个通用版本后仍未满足 C1

PARKED_PRODUCT11_EXPLICIT_ACQUISITION_UNRESOLVED
  X1 已通过，但 X2 两个通用版本后仍未满足 C2

PARTIAL_PRODUCT11_CONTINUATION_AND_ACQUISITION_READY_RENDERER_UNRESOLVED
  X1/X2 通过，但 X3 anchor/frontier integration 回归

PARTIAL_PRODUCT11_MEMORY_COMPLETE_HOST_AGGREGATION_LIMIT
  X1/X2/X3 memory contract 通过，完整 Evidence 已进入 Host，X4 Host reasoning 仍失败

PASS_PRODUCT11_EXPLICIT_ACQUISITION_NONDESTRUCTIVE_CONTINUATION_USABLE
  X1/X2/X3 全部通过；所有安全门通过；X4 eligible cases 无未归因 memory failure
```

若 X1 通过而 X2 失败，或 X2 通过而 X1 失败，结果正文可以报告单项机制通过，但唯一 Goal 终态
仍使用对应 `PARKED_*_UNRESOLVED`，不得用局部成功冒充完整架构可用。

## 17. Verification hierarchy

```text
开发
  failure case + different-shape sibling + correct regression

组件
  RetrievalContinuationState domain/repository/CAS/TTL
  explicit turn acquisition and DIRECT_ANCHOR/HYDRATION_ONLY trace
  exact seen exclusion and two-pass renderer

数据库
  fresh PostgreSQL migration/RLS/tenant/principal/scope
  successor idempotency/branching/expiry/revocation/deletion/cleanup

协议
  existing MCP query/previous_context_id schema unchanged
  continuation available/exhausted/null assertion truth table
  authenticated Streamable HTTP smoke

效果
  24+ human-sealed opened-development paired Context-only runs

产品
  <=8 presealed real Codex HTTP attribution cases when eligible

质量
  affected packages: Ruff, strict mypy, tests, build
  final Product manifest + separate effect/final locks
```

Schema 继续是 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。代码存在、单测通过或 migration
成功都不等于 effect gate 通过。

## 18. 预期产出

只有执行时实际产生的文件才进入 manifest；本次不预建空 tracker、receipt、migration 或 run
目录。计划产出包括：

```text
MiLAi-Product/docs/adr/ADR-032-explicit-acquisition-nondestructive-continuation.md
MiLAi-Product/docs/contracts/MILA_PRODUCT-11_ACCEPTANCE_CONTRACT.md
MiLAi-Product/docs/goals/MILA_PRODUCT-11_TRACKER.md
MiLAi-Product/runtime/.../retrieval_continuation_state.py
MiLAi-Product/runtime/.../intra_source_turn_acquisition.py
MiLAi-Product/runtime/migrations/<next>_retrieval_continuation_state.sql

MiLAi-Lab/refine-logs/EXPERIMENT_PLAN.md
MiLAi-Lab/refine-logs/EXPERIMENT_TRACKER.md
MiLAi-Lab/data/labels/product11-human-instance-groups.jsonl
MiLAi-Lab/data/locks/product11-*.lock.json
MiLAi-Lab/tools/run_product11_*.py
MiLAi-Lab/var/product11/failure-ledger.jsonl
MiLAi-Lab/artifacts/product11/<sealed-run-id>/
```

## 19. 当前授权边界

用户本次仅授权创建 Product-11 Goal 文档：

```text
Goal document creation                 authorized
Product / Lab read-only design audit   not yet authorized
human label production                 not yet authorized
Product code changes                   not yet authorized
database migration                     not yet authorized
opened-development effect runs         not yet authorized
real Codex runs                        not yet authorized
formal holdout                         not authorized
```

后续收到明确执行授权后，必须先完成 X0、ADR-032 和 acceptance contract，再写行为代码。不得把
本 Goal 文档的创建视为实验授权或效果证据。

## 20. v0.2 contract correction

本修订只收紧实验与运行时合同，不授予任何新的执行权限：

```text
X1 primary                  persisted frontier only; no global reacquisition or pool extension
successor idempotency       DB UNIQUE operation fingerprint; request_id is trace-only
continuation.available      current state is resumable after online eligibility checks
FRONTIER_EXHAUSTED          query-lineage route exhaustion only; no semantic/corpus claim
X3 hydration gate           no false discovery credit or direct-anchor demotion; diagnostic retained
X3 eligibility              X1 PASS AND X2 PASS AND sealed minimal X2 variant
metric aggregation          preregistered macro formulas; micro is secondary only
state-tree resources        profile-owned bounded limits with typed non-exhaustion reasons
label overlap               exact Evidence/turn overlap forbidden; source/session overlap allowed
```

状态继续为 `PLANNED_NOT_AUTHORIZED`。下一次授权仍应从 X0、ADR-032 与 acceptance contract 开始，
而不是直接编写 Product behavior code。
