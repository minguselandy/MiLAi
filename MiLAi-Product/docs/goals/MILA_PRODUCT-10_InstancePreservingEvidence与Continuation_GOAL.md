---
document_id: MILA-PRODUCT-10
version: "1.3"
status: PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED
created_at: "2026-09-03T19:47:38+08:00"
amended_at: "2026-09-04T02:05:50+08:00"
product_version: 0.1.0-candidate
schema_status: 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
predecessor: MILA-PRODUCT-09@1.1
frozen_baseline_tree: 557ad09059b50bb52b9b2b77e3f1f3c88a7d1a317f460cc95b9d2b5ea479171f
baseline_integrity: PROVISIONAL_FAIL_AUDIT_GRADE_RERUN_REQUIRED
execution_authorized: true
formal_holdout_authorized: true
---

# Product-10：Instance-Preserving Evidence Coverage & Continuation

## 1. Goal

在不引入生成式 Reader、不修改 Host 推理提示、不改变 Canonical read semantics
的条件下，建立 instance-preserving evidence retrieval 与 continuation，使跨 session、
多证据查询能够稳定覆盖不同历史实例，并明确分离 memory coverage failure 与
Host aggregation failure。

本 Goal 不是“修复 COUNT”，也不是新的语义类型系统。它要回答的是：

```text
当用户查询需要多个历史实例时，
MiLA 能否保留不同 Evidence 的真实身份，
在有界 Context 中避免无效重复，
并让后续调用继续向尚未展示的 Evidence 推进？
```

## 2. Product-09 冻结基线

Product-09 的历史终态 `PASS_PRODUCT09_CODEX_HTTP_PERSISTENT_MEMORY_USABLE` 不在本 Goal 中
追溯改写；但它只作为 documentary historical observation，不作为 Product-10 的审计级 effect
baseline。独立同族审计判定为 `FAIL / provisional`：历史结果未绑定 Product/Lab/input hashes，
所谓 restart 实际只重启 API/worker/MCP，answer-turn labels 是未人工裁决的 Qwen proxy，且
Codex tool choice 由 prompt 强制。Product-10 必须在 treatment 前按 X0 合同重跑 sealed A0。
Product-10 不得以实验方便为由退回以下边界：

```text
Host owns semantic sufficiency.
MiLA owns memory correctness.

Codex:
  判断是否调用 memory
  理解 Evidence
  提出 residual query
  判断是否继续
  最终推理与回答

MiLA:
  持久化、scope、permission、revocation
  temporal / canonical currentness
  retrieval routing、Evidence identity、Context 装配
  可证明的 continuation 与 retrieval trace
```

正常 HTTP MCP read path 继续要求：

```text
vLLM calls                    = 0
internal Reader calls         = 0
EvidenceLedger                = absent
generated semantic COMPLETE   = absent
automatic semantic retry      = 0
recall-side Canonical mutation = 0
```

`memory-evidence-context-v1` 仍是对 Host 的唯一正常读协议。

## 3. 当前已知事实

Product-09 的一份 opened-development LongMemEval 四类历史诊断记录为 normalized EM/F1
`3/4 / 0.75`：

```text
ordinary user lookup       PASS
assistant answer lookup    PASS
state update               PASS
multi-session set COUNT    FAIL: 2 vs 3
```

COUNT case 中：

```text
required sessions Host-visible         3/3
annotated answer turns Host-visible     3/4
未展示 turn                         blazer 的重复陈述
回答需要的不同实例                可能已全部可见，待独立标注确认
Codex output                          2
reference                             3
```

因此不得将该 case 简化为“retrieval recall fail”或“Codex 不会 COUNT”。

该记录的 claim ceiling 是：四个具名 opened-development case、非官方 deterministic scorer、
answer reference 来自数据集；turn visibility 来自 Qwen model-assisted proxy。完整 500-case 数据
与 label 文件曾被 loader 读取后再取子集，所以只能说“未执行 formal 500-case scoring/effect
run”，不能说 formal 文件从未访问。历史 `3/4` 不进入 Product-10 matched effect denominator。

当前源码的窄审查还显示：

- 普通 acquisition/retrieval 的候选去重主要按 `evidence_id`；
- MCP renderer 只转发 Runtime 明确给出的 `continuation`，不自行推测完备性；
- `previous_context_id` 当前主要用于 ContextReceipt 原样复用或校验失败后回落到新检索；
- 当前尚没有将已展示 Evidence、未展开候选和 snapshot 共同绑定的
  retrieval continuation frontier。

所以 Product-10 先审计“实例是否被错误折叠”，不预设结论；实施重点默认是建立真实
continuation，而不是再写一个语义 selector。

## 4. 四种 identity 不得混用

```text
Evidence identity
  某个真实来源 EvidenceRecord / turn / span 的身份

Semantic similarity
  两段文本含义接近，只能作为排序特征

Event-instance identity
  多条 Evidence 是否指向同一个现实事件，可能尚未有产品级确定身份

Canonical equivalence
  受治理 State/Claim 是否表达同一状态，由既有 Canonical Procedure 所有
```

强制规则：

```text
不同 evidence_id 不得因语义相似被硬合并。
同一 session 不得被整体排除，因为其中可能存在另一个未见实例。
已展示的 exact evidence_id 可在 continuation 中硬排除。
source/session/time 新颖性只能是软排序特征。
模型或 Runtime 不得为了计数而生成未受验证的 instance_key。
```

## 5. 评测对象与产品对象分离

`DistinctInstanceCoverage` 是 Lab 的评测指标，不是 Product schema。

Lab 在 treatment 前封存：

```yaml
InstanceEquivalenceGroup:
  group_id:
  acceptable_evidence_ids: []
  acceptable_turn_refs: []
  required_for_answer: true
```

它只用于计算：

```text
DistinctInstanceCoverage
DuplicateInstanceRate
NovelInstanceRate
ContinuationInstanceGain
```

Product 不读取该标注，也不在 MCP 协议中暴露 `count`、`set_members`、
`event_type` 或 LLM-generated `instance_key`。

## 6. 两项假设

### P10-H1 — Instance-preserving first recall

在相同 scope、snapshot、official candidate pool、hydration 和 Context 预算下，一个仅使用
确定性 provenance 新颖性、不以语义相似做硬去重的最小 admission 修复，能够提高
Host-visible distinct-instance coverage，并且不丢失原先已完整的 case。

预注册判定：

```text
mean DistinctInstanceCoverage gain       >= +0.05
newly covered instance groups             >= 2
gain capability shapes                    >= 2
previously full-coverage cases lost        = 0
cross-Evidence hard collapse               = 0
scope / snapshot / Canonical violations    = 0
```

若 X1 证明当前 A0 已经没有 instance-destroying collapse，则 B1 可合法判为
`NOT_NEEDED`，不为了保留假设而修改 Product。

### P10-H2 — Provenance-novel continuation

对首轮 `DistinctInstanceCoverage < 1` 且 official frontier 中确实存在尚未展示实例的
opportunity cases，一次绑定 `previous_context_id` 的 continuation 能够以更低重复率增加
Host-visible distinct-instance coverage。

预注册判定：

```text
minimum opportunity cases                 >= 6
mean ContinuationInstanceGain             >= +0.15
opportunity cases with novel instance      >= 50%
exact seen-Evidence repeats                = 0
DuplicateInstanceRate                      <= A0 two-call control
principal / scope / snapshot drift         = 0
```

若开放开发集不足 6 个真实 opportunity，P10-H2 记为 `INSUFFICIENT_OPPORTUNITY`，
不给出正向或负向方法结论。

## 7. 三个 matched arms

```text
A0  PRODUCT09_CURRENT
    当前 first recall 与 ContextReceipt 行为

B1  INSTANCE_PRESERVING_ADMISSION
    与 A0 共享同一 candidate pool
    exact Evidence identity dedup
    provenance/session/time novelty 仅作为 soft admission feature
    不使用 Lab instance labels

B2  FRONTIER_CONTINUATION
    选定的 A0/B1 first read
    + 一次 previous_context_id-bound official resolve
    + exact seen-Evidence exclusion
    + same principal/scope/snapshot/as-of
    + unseen Evidence frontier continuation
```

不新增 Host-prompt arm、Reader arm 或 vLLM arm。

## 8. 五个连续阶段

### X0 — Measurement truth and sealed slice

- 从 opened-development 数据封存 24 个 case，不使用 formal 500；
- 总体覆盖 enumeration、counting、repeated mention、same-type/different-instance、
  cross-session aggregation、update+collection 和 continuation，类别可重叠；
- 在任何 treatment 前封存 InstanceEquivalenceGroup、reference turn/session 与 opportunity label；
- 检查 Product-09 source pin、Codex identity、tokenizer/profile 与评分器；
- 仅保留一份紧凑 case manifest 和一份 failure ledger。

X0 还必须在任何 A0/B1/B2 run 前封存：

```text
Product behavior tree + semantic lock digest
Lab runner hash + command + timestamp
dataset / selection / label hashes
label provenance、annotator/reviewer 与 adjudication 状态
Codex provider/model/CLI/config identity
完整 redacted tool trace hash，包括失败、未完成和额外 tool attempt
formal files accessed 与 formal cases scored 两个独立字段
```

若 label 是 model-assisted 且未完成人工裁决，必须标为 proxy；不得称为 gold。P09 历史结果缺少
这些绑定，所以 A0 必须重新运行，不能用当前 lock 对历史 JSON 做追溯绑定。
同一 case 内，一个 Evidence ID/turn ref 不得同时属于两个 required instance groups；冲突必须在
seal 前裁决，否则该 case 记为 label error。

### X1 — Current-path first-loss audit

不改行为，仅追踪：

```text
raw retrieval occurrence
→ Evidence-ID dedup
→ session/locality ordering
→ Context admission
→ MCP rendered Evidence
→ Lab InstanceEquivalenceGroup coverage
```

每个未覆盖 group 必须定位为：

```text
NOT_DISCOVERED
DISCOVERED_NOT_ADMITTED
ADMITTED_NOT_RENDERED
INSTANCE_DESTROYING_COLLAPSE
VISIBLE_BUT_HOST_MISSED
```

X1 不一边审计一边修算法。

### X2 — Minimal instance-preserving admission

只在 X1 证明 admission 或错误 collapse 是首损时进入。修改顺序：

1. 硬去重只使用稳定 Evidence identity；
2. 保留每个高排名 source/session 的原子单元；
3. 对已展示的来源只降权，不排除同 session 的未见 turn；
4. 所有排序特征为软特征，原 candidate 保留为 fallback；
5. 若 A0 已满足合同，不实现 B1。

### X3 — Retrieval continuation frontier

将 `previous_context_id` 从“可复用 Context 的身份”扩展为“同一读取轨迹的继续键”，
但不改变 Host/MiLA 权限边界。

最小 continuation state：

```yaml
context_id:
principal_scope_digest:
source_snapshot_as_of:
query_history: []
shown_evidence_ids: []
shown_source_turn_refs: []
remaining_frontier_identity:
budget_used: {}
expires_at:
```

实施优先复用现有 ContextCapsule/receipt 持久边界，不新建数据库 Schema。
如现有边界无法表达经证明 frontier，先保持 `continuation: null`，不伪造能力。
授权后的拟议受治理路径见 `docs/adr/ADR-031-instance-preserving-evidence-continuation.md`；组件与
权限验收见 `docs/contracts/MILA_PRODUCT-10_X1_X3_ACCEPTANCE_CONTRACT.md`。ADR 当前为
`PROPOSED / DESIGN-ONLY`，不构成 implementation 或 migration 授权。

连续调用必须：

```text
验证 same principal / tenant / project / scope
继承 same snapshot / as-of semantics
硬排除 exact shown evidence_id
允许同 session 中的 unseen turn
对已见 source/session 只做 soft penalty
将新 Evidence 合并到同一 context trace
不判断语义上是否已足够
```

### X4 — Context effect and real Codex HTTP confirmation

先运行 Context-only A0/B1/B2，通过 H1/H2 或证明 memory contract 已满足后，再在不改
Codex instruction 的情况下运行最多 8 个真实 HTTP MCP case。

最终回答只用于边界归因：

```text
DistinctInstanceCoverage < 1
  → MiLA acquisition / admission / continuation failure

DistinctInstanceCoverage = 1 且 Host 未在有机会时继续
  → Host tool-loop failure

DistinctInstanceCoverage = 1 且所有实例可见，但答案错
  → Host aggregation ceiling
```

第三类错误不允许恢复 MiLA Reader 或增加 Host prompt treatment。

X4 case membership 在读取 treatment outcome 前，按 X0 已封存的 capability shape、opportunity
与稳定 `case_id` 顺序确定并封存，最多 8 个；不得按 A0/B1/B2 成败挑选。每 case 只有一个
primary Codex run，不投票、不做语义重试；仅 system error 可 replacement，原失败和替换关系必须
保留。运行前必须记录 exact provider/model/CLI/config identity；无法验证 model identity 时记为
`MODEL_IDENTITY_UNVERIFIED`，不产生产品效果主张。

`AnswerTaskSuccess` 使用已固定的 `score_normalized_em_f1_v1.exact_match` case indicator；同时报告
normalized F1、原始 answer/reference，并明确 `NOT_OFFICIAL_LONGMEMEVAL_SCORE`。X4 只做边界
归因，不替代 H1/H2 mediator。

## 9. 固定预算与并发

First-read A0/B1 共享：

```yaml
profile: MCP_INTERACTIVE_WIDE_V01
max_results: 50
max_candidates: 120
max_context_tokens: 16384
max_latency_ms: 5000
official_memory_calls: 1
```

B2 和 A0 two-call control 共享：

```yaml
total_official_memory_calls: 2
same_per_call_budget: true
semantic_auto_retry: 0
votes: 0
```

计算并发策略：

```text
capture/projection workers     <= 8
Context-only cases             <= 8 concurrent
real Codex HTTP cases          <= 4 concurrent
one isolated tenant per case
```

上限是容量约束，不是必须消耗目标。报告实际 candidates、hydrated units、visible
tokens、memory calls 和 P50/P95 latency。

## 10. 失败后的高效修复循环

失败不直接终止 Product-10，也不为每个 case 创建新 Goal。

```text
失败 case
→ 定位第一个真实丢失边界
→ 查找另一个不同形状的 sibling case
→ 修复一个共享机制
→ 先跑失败 case + sibling + 一个已正确回归
→ 通过后自动继续当前阶段
```

| 失败边界 | 优先修复 | 不允许 |
| --- | --- | --- |
| frontier 也无 required reference instance | channel/query expression | 改 admission 假装召回 |
| pool 有、Context 无 | atomic admission / budget allocation | 只放大 Top-k |
| 不同 Evidence 被折叠 | identity-key repair | 增加题型/commodity rule |
| continuation 重复 | seen-Evidence/frontier state | 排除整个 session |
| 实例全可见但答案错 | 记录 Host ceiling | 恢复 Reader/Ledger/prompt 补丁 |
| state update 选旧值 | canonical/currentness lane | 用 recency keyword 特判 |

只有结果改变 Product treatment、标注合同或主指标时才新建一个 run identity。
格式、超时或环境修复不应复制整套审计制品。

## 11. 禁止项

```text
NO hidden Reader
NO EvidenceLedger
NO vLLM on normal read path
NO count/clothing/case-ID special rule
NO Host prompt treatment as the primary mechanism
NO semantic-similarity hard dedup
NO LLM-generated instance_key
NO recall-time Canonical mutation
NO semantic COMPLETE inside MiLA
NO automatic semantic retry or voting
NO formal-holdout tuning
```

## 12. 验证层级

只做与当前声称相称的验证：

```text
开发：失败 case + sibling + 正确回归
组件：Runtime receipt/continuation/dedup/Context 相关单测
协议：MCP agent-memory contract + HTTP smoke
效果：24-case opened-development Context-only matched run
产品：最多 8-case real Codex HTTP confirmation
质量：受影响包 Ruff、strict mypy、build；最后再跑必要全量门
```

数据库、RLS、revocation 或 snapshot 修改必须用 fresh PostgreSQL；纯选择函数不需要为每次
迭代重建数据库。

## 13. 终态决策

```text
PASS_PRODUCT10_INSTANCE_PRESERVING_CONTINUATION_USABLE
  H1 通过或审计证明 B1 不需要
  H2 在足够 opportunity 上通过
  scope/snapshot/Canonical 门全通过

PASS_PRODUCT10_MEMORY_CONTRACT_ALREADY_SATISFIED
  instance coverage 已完整
  不需要 continuation opportunity
  X4 没有 coverage 完整时的 Host aggregation miss
  没有不必要的 Product 算法修改

PARTIAL_PRODUCT10_MEMORY_COMPLETE_HOST_AGGREGATION_LIMIT
  memory coverage/continuation 达到合同
  真实 Codex 仍有 aggregation miss

PARKED_PRODUCT10_INSUFFICIENT_CONTINUATION_OPPORTUNITY
  first read 不完整但可审计 opportunity 不足，不强行建设 frontier

PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED
  两轮通用机制修复后仍无 coverage gain，需要重新审视 representation/acquisition

FAIL_PRODUCT10_AUTHORITY_SCOPE_OR_SNAPSHOT
  出现越权、snapshot 漂移、撤销泄漏或 recall-side Canonical 写入
```

`AnswerTaskSuccess` 是最终产品指标，但不是否定已完成 memory contract 的唯一依据。

终态按以下优先级唯一选择，前项一旦命中即停止：

1. 任一 authority/scope/revocation/snapshot/Canonical 门失败 -> `FAIL`；
2. memory coverage 在两轮通用修复后仍未达到合同 -> `PARKED ... UNRESOLVED`；
3. first read 不完整且真实 continuation opportunity 少于 6 -> `PARKED ... INSUFFICIENT`；
4. memory contract 达到、但 X4 存在 coverage 完整时的 Host aggregation miss -> `PARTIAL`；
5. A0 first read 已完整且无需 B1/B2、X4 无上述 miss -> `ALREADY_SATISFIED`；
6. H1（或 B1 `NOT_NEEDED`）与 H2 均通过、X4 无上述 miss -> `USABLE`。

## 14. 当前授权

用户于 `2026-09-03T21:41:22+08:00` 明确“授权全部内容”。以下范围现已授权：

```text
Product 代码修改                         authorized
opened-development effect run            authorized
real Codex Product-10 run                 authorized
formal 500-case holdout                   authorized, one-way final evaluation only
public MCP schema 修改                    authorized if contract evidence requires it
database migration                       authorized if X0/X1 gates require B2
```

授权不改变 X0→X1→X2/X3→X4 顺序，也不允许 formal-holdout tuning、label leakage、隐藏 Reader、
自动语义重试或跳过 fresh-PostgreSQL 权限验证。formal 500 在 treatment、X4 membership 与所有参数
冻结前保持未消费。

执行依据见 MiLAi-Lab 的当前 `EXPERIMENT_PLAN.md` 和 `EXPERIMENT_TRACKER.md`。
当前逐项完成状态见 `MILA_PRODUCT-10_COMPLETION_AUDIT.md`。

## 15. 执行终态（2026-09-04）

X0--X2 已按顺序执行，终态为：

```text
PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED
```

- X0 封存 24 个 opened-development case、36 个 required instance group；标签是
  `Qwen3.6-35B-A3B-FP8` model-assisted proxy，人工裁决仍为 `PENDING`，不得称为 gold；
- X1 observational run `p10-a0-x1-20260904c` 在 fresh PostgreSQL 和真实 HTTP MCP 路径上
  得到 A0 `28/36` micro coverage，并定位 4 个 `DISCOVERED_NOT_ADMITTED` 首损，因此 B1 必须进入；
- 第二轮 paired run 的 matched A0 为 `29/36`、mean `0.84375`，只用于与同 run 的 B1
  比较，不追溯改写 X1 observational identity；
- B1 通用机制第一轮为 `28/36`，新覆盖 0、丢失 1，H1 失败；
- 第二轮在 exact matched candidate pool 上为 `29/36`，新覆盖 3、丢失 3 个 group、原完整
  case 丢失 2、mean gain `+0.0416667`、hard collapse 0；因 mean gain `<0.05` 且
  previously full-coverage cases lost `>0`，H1 再次失败；
- 两轮通用机制修复后 memory coverage 仍未达到合同，第 13 节优先级 2 命中并停止；
- A0/B1 仅有 1/2 个 audited continuation opportunity，均 `<6`，所以 X3 保持
  `INSUFFICIENT_OPPORTUNITY`，未实现 migration/frontier，`continuation` 保持 Runtime-proven
  assertion 或 `null`；
- X4 与 formal 500 不再进入；formal 文件历史上曾访问，但本 Goal 评分 case 数为 0；
- authority/scope/snapshot/Canonical、same-pool、zero-retry、trace-before-label 与 cleanup 门全部通过。

权威第二轮制品位于
`../MiLAi-Lab/artifacts/product10/p10-x2-matched-20260904b/`：summary SHA256
`6d4b1a8a293718429d270c7d744e5c4708f4f5dcb64866d175ea22f1a6cfeeba`，Product effect tree
`db355c3c322d4bbb79a0becde321112b5b5f9d75498ff281a3346e0dea276d6c`。未通过 H1 的 B1
实现保留为默认关闭的审计候选，不作为生产默认。sealed summary 的旧 scorer 少列了一个由
adjacent hydration 形成的 A0-visible loss；不改写原 artifact，派生 correction receipt SHA256 为
`167ee99528ec291175c931596bf2a13108a3e806c1284503c1c8b177c7b18a9d`，修正只强化失败结论。
runner 还曾把 H1 zero-loss guard 误编码为 group-level；v3 correction SHA256
`065812c5702a8bffa1ac05158a0f833268a597f65cfd478425f5ea4adb9b5659` 对齐为预注册的
previously-full-case 口径，得到 2 个退化完整 case，仍不改变 H1/终态。

交付同时增加 `milai-agent-memory-mcp` 包装入口：固定 authenticated Streamable HTTP、
`agent-memory` 与 zero automatic retries，只暴露 Host-owned bind/path/budget 配置；MCP tool schema
仍为 `query` 与可选 `previous_context_id`。

最终交付 Product tree 为
`0b170d3fdeaf962c26492578293d29a7fcc1c9036555f8adb01b121f41cba7b5`，由 Lab
`data/locks/product10-final-product.lock.json` 绑定并通过反向验证；effect run 的原 lock 保持不变。
