---
document_id: MILA-PRODUCT-11
version: "0.1"
status: PLANNED_NOT_AUTHORIZED
created_at: "2026-09-04T07:40:04+08:00"
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
| P11-C1：stateful continuation 在不改变 first-call Evidence 的前提下增加 novel cumulative Evidence | 从结构上消除固定 16K first-call displacement | first-call semantic digest 100% 匹配 A0；seen exact identity repeat=0；continuation opportunity 上 cumulative coverage 显著增加 | X1、X3 |
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

tenant_id:
principal_binding_digest:
scope_digest:
authority_floor:
consistency_floor:

snapshot_as_of:
canonical_position:
original_query_hash:
residual_query_hashes: []

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
- 同一 request id + 同一 payload 幂等返回同一 successor；不同 residual query 形成显式分支；
- state digest、predecessor、generation、root snapshot 任一不匹配都 fail closed；
- 状态不能声称 semantic completeness，也不能作为 Canonical truth 或 authority source。

旧 `context_id` 仍是 MCP 暴露的 opaque locator。Runtime 可在内部将合格的 context_id 绑定到
retrieval state，但公共 MCP 参数保持：

```text
milai_memory_resolve(query, previous_context_id?)
```

不得增加 model-controlled tenant、scope、snapshot、budget、route、seen IDs 或 frontier IDs。

## 7. Continuation 算法

第二次 resolve 的规范步骤：

```text
1. 解析 opaque previous_context_id，不泄漏 unknown/not-owned 差异
2. 验证 same principal / tenant / project / scope / authority / consistency
3. 固定 root snapshot_as_of 与 canonical position
4. 在线重验旧 frontier candidate 的 permission/revocation/content identity
5. 从旧 frontier 继续，而不是从头重新 top-k
6. 在同一 snapshot 下将 residual query 的新候选并入 frontier
7. 硬排除 exact seen Evidence/turn/span identity
8. 对 new source / turn / time / provenance 只做 soft novelty ranking
9. 在本次独立 16,384-token envelope 内渲染 novel Evidence
10. 生成 append-only successor state 与 typed continuation assertion
```

`source_id`、`session_id` 或粗粒度 `source_span` 不能单独成为 hard exclusion，因为同一来源内可能
仍有另一个未见实例。只有当 official route 能证明该 span 内所有 eligible exact turn identity 已
枚举并消费时，才可记录 route/span exhausted；“语义上已经覆盖”不构成证明。

公共 continuation assertion 只允许：

```text
available=true
  Runtime 已持久化 successor 所需 state，且在线可读 frontier 非空

available=false + FRONTIER_EXHAUSTED
  所有 official routes 在同一 snapshot 上均有可验证 exhaustion receipt

continuation=null
  无法证明 available 或 exhausted
```

`CALL_BUDGET_EXHAUSTED`、state expired、permission changed 和 transport unavailable 使用各自 typed
reason，不得冒充 frontier exhausted。

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
    required_for_answer: true
continuation_opportunity: true|false
intra_source_opportunity: true|false
human_adjudication_status: COMPLETE
```

封存 case order、membership、labels、source snapshot、budget、Dense model identity、scorer code 和
Product lock。Product 和 MCP 运行时不得读取 labels。formal 500 保持 `P11 scored cases = 0`。

### 8.3 X0 gate

```text
case count                              >= 24
human adjudication COMPLETE             100%
continuation opportunities              >= 8
intra-source opportunities              >= 8
capability shape minimum                >= 3 each
label overlap across required groups    0
Product label access                    0
formal cases scored                     0
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

A1R-RESIDUAL (secondary diagnostic)
  Call 2 = presealed Host-style residual query + previous_context_id
```

Primary comparison使用同一个 query，避免把更好的 query rewrite 误认为 continuation state
收益。A1R residual query 只能基于原始问题和 A0 public Context 预先生成，不得读取 hidden label、
reference answer 或 treatment output，也不进入主判门。

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
opportunity cases with >=1 novel required group    >= 50%
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
NOT_DISCOVERED groups directly acquired                 >= 50% of opportunities
new directly acquired required groups                   >= 4
gain capability shapes                                  >= 2
previously directly acquired required groups lost       = 0
cross-source hard identity collapse                     = 0
hydration-only turn counted as direct discovery          = 0
scope/snapshot/permission violation                     = 0
```

X2 scorer 同时报告 `HostVisibleCoverage`，但它不能替代 `DirectAcquisitionCoverage`。一个 group
只有 neighbor 可见而无 direct anchor 时，Host-visible 可以为 true，directly acquired 必须为 false。

## 11. X3 — Frontier integration 与 Anchor-first renderer

**Claims tested**：P11-C1 + P11-C2 的产品集成。  
**Why**：证明 fine acquisition 能安全进入 frontier/rendering，而不是制造新的 first-call regression。  
**Priority**：MUST-RUN for full Product pass。

进入条件：X1 与 X2 各自完成有效 effect 判定；X2 至少一个最小 variant 通过。顺序：

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
required-group coverage dependent only on hydration  = 0
anchor evicted by hydration                          = 0
first-call max context tokens                        = 16,384 unchanged
continuation exact seen identity repeat              = 0
cumulative coverage                                  >= selected X1 variant
scope/snapshot/revocation/Canonical violation        = 0
```

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
effect 失败也不追溯改变 X1。X3 只有两项都通过才进入。

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
