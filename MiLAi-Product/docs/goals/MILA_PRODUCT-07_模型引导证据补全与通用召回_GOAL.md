---
document_id: MILA-PRODUCT-07
version: "1.4"
status: COMPLETE_PARKED_NO_GENERAL_EVIDENCE_GAIN
created_at: "2026-09-03T09:23:18+08:00"
updated_at: "2026-09-03T12:22:12+08:00"
supersedes: MILA-PRODUCT-07@1.3
parent: MILA-PRODUCT-GOALS@2.3
predecessor: MILA-PRODUCT-06
further_execution_authorized: false
opened_development_v0_status: S2_B1_DEVELOPMENT_GATE_PASSED
r3_context_status: CONSUMED_H1_FAILED
r3_answer_judge_status: NOT_ENTERED_BY_GATE
formal_holdout_authorized: false
schema_change_authorized: false
public_api_change_authorized: false
database_migration_authorized: false
canonical_authority_change_authorized: false
---

# MILA-PRODUCT-07：通用证据补全与模型原生可靠消费

## 1. 目标

Product-07 不再修改 Ledger，也不再通过 TypeBinding、QueryIR 题型枚举或答案格式协议解释
召回失败。它解决 Product-06 暴露的下一个真实瓶颈：

> 在大历史、多会话和多证据问题中，先让 Reader 实际看到足够且互补的 Evidence，再让
> Qwen 以模型原生 reasoning 消费完整 Evidence；简单多通道仍不足时，才允许 Qwen 根据
> 当前 observation 提出少量新的搜索表达，并通过同一正式 MCP/Runtime 路径取回证据。

目标路径：

```text
Question
→ original-query official recall
→ Raw FTS + configured Dense + real-session locality
→ identity-deduplicated candidate and locality closure
→ same-pool lightweight EvidenceSet selection
→ if the full pool is genuinely missing support: Qwen proposes additive residual search
→ zero to three additive search queries
→ official MCP/Runtime recall under the same tenant/scope
→ provenance-preserving Context union
→ coverage-qualified model-native reasoning
→ optional Host-safe calculator
→ one OpenWorker terminal answer
```

Product-07 是可用性优先的 Recollection Goal，不改变 Memory 存储、PostgreSQL Schema、
Canonical State 或用户隔离。

### 1.1 当前真实开发状态

Product-07 已按三轮跨 case 通用修复预算收口，终态为
`PARKED_PRODUCT07_NO_GENERAL_EVIDENCE_GAIN`。当前 direct 路径保持不变；
`RecallWorkspace` 是 query-local、非持久、default-OFF 的诊断候选，不构成发布或可用性声明。

```text
formal B1 execution tree SHA-256   01ad1775...94612
final delivery tree SHA-256        17df2c8f...face3
final Product pin                  valid = true
query-preserving / B1 defaults     OFF / OFF
R3 Answer / Judge / Provider calls 0 / 0 / 0
formal 500                         untouched
```

S2-B1 先在已打开 V0 上达到开发冻结条件：

```text
complete EvidenceSets                  11/12
Reader-visible group coverage          0.9167
same-pool gain over B0                 +1 complete / +0.0278 coverage
previously complete losses             0
effective Reader-visible token budget  16,384
```

因为 B1 已恢复至少一个 V0 不完整 EvidenceSet，按预注册顺序未实现 B2。已有 residual
SHADOW 仍仅是 2 次 Qwen 调用、5 条 proposal、0 次 read；所需证据已在池内，所以这些 query
始终不具执行资格。

冻结 B1 后，权威 R3 Context-only run `mila-p07-r3-context-b1-r4` 执行了全部 24 个 case：

```text
A complete / mean group coverage       10/24 / 0.5667
B0 complete / mean group coverage       8/24 / 0.4583
B1 complete / mean group coverage       8/24 / 0.4722
B1 gain over A                          -2 / -0.0944
B1 recovered / lost complete cases      2 / 4
B1 recovered query shapes               2
any-gold-session recall A / B1          22/24 / 17/24
candidate/order/hydration/budget match  24/24
window-closure match                     22/24
tenant leak / Canonical mutation         0 / 0
```

R3 不仅未达到 `+4 / +0.10 / 3 shapes / zero loss`，方向上还低于 A；其中两个大历史 case
的 B0/B1 window closure 不同，因此也没有形成纯 same-pool selector 归因。P07-H1 明确失败，
P07-H2、D0/D1、真实 Answer/Judge/OpenWorker effect 均按门槛未进入。R3-R1/R2/R3 是回执观测
合同的基础设施重放，R4 是唯一权威语义结果；它们没有触发语义重试或事后调参。

## 2. 已有机器事实与问题归因

### 2.1 Product-05 的 Ledger 问题已经被 Product-06 消除

`EvidenceLedgerV01` 是 Qwen 的回答前草稿，不是数据库账本。Product-05 最终六个失败中：

```text
Host calculation-protocol rejection     4 / 6
model semantic miss                     2 / 6
storage / persistence / tenant failure  0 / 6
```

Product-06 的 `VllmEvidenceReaderSession` 已取消强制 support/member/calculation 表格。R2 中
Host protocol rejection、transport repeat、unsupported answer、tenant leak 和 Canonical
mutation 均为 0。Product-07 不恢复 Ledger，也不增加 Ledger 字段。

### 2.2 Reader-only treatment 没有增益，因为 Context 不完整

Product-06 R2 的修正结果：

```text
direct / model-native correct                 7 / 12, 7 / 12
additional correct / regression               0 / 0
all-required Evidence-group recall            7 / 12 = 0.5833
Reader-visible Evidence-group coverage        0.7778
direct-wrong cases                            5
direct-wrong with missing Evidence group      4 / 5
```

四个 Context 缺证据错例横跨不同问题形状：

| 问题形状 | Reader 可见情况 | 观察到的结构失配 |
| --- | --- | --- |
| 跨会话 citrus 集合 | gold sessions 全命中，但仅 2/3 answer-bearing groups | session hit 不等于答案 span 命中 |
| 两个 aquarium 的 fish 总数 | 仅 1/2 groups、1/2 gold sessions | 单 anchor 取代完整集合 |
| Hawaii 与 Tokyo 每晚价格差 | 仅 1/2 operands | 被误拆为 `TOTAL_PRICE + ITEM_COUNT` |
| 本人、父母、祖父母平均年龄 | 仅 2/3 groups | 被压缩成单一 `LOOKUP_ANSWER` |

这些 Context 已包含 22–38 条 selected Evidence、11–19 个可见窗口和约 8.7k–11.7k
tokens。首要问题不是 Context 上限不足，而是候选和装配缺少跨 query/channel/session 的边际
覆盖，预算被同主题重复证据占用。

另有一个全部 Evidence groups 均可见但仍回答错误的普通 lookup。这是独立的 Reader 语义消费
问题：模型回答了相邻事实，没有回答问题要求的精确关系。它不能再归因给检索，也不能通过
扩大 Top-k、添加 relation enum 或为该问法增加规则来修复。

### 2.3 当前刻板性的位置

当前路径仍会让启发式 QueryIR 影响：

```text
是否产生 requirement-local probes
是否进入 Dense
候选预算如何在错误 slot 间分配
何时把多证据问题退化成 LOOKUP_ANSWER
```

结果是不同表达方式会得到不同通道和不同覆盖，即使它们都只是普通的跨会话 Memory
问题。QueryIR 可以继续作为 trace/advisory hint，但不得再成为 original-query FTS、configured
Dense 或 Reader Context 可用性的硬前置条件。

### 2.4 检索首要差距是 EvidenceSet，不是 anchor

Product-06 R2 的两项指标必须共同解释：

```text
any gold session recalled                0.9167
all required Evidence groups recalled    0.5833
gap                                      0.3340
```

当前系统通常能找到一个相关 anchor，却不能稳定补齐其余 operand、成员、旧/新状态或后续修改。
平均约 18 个 Evidence units、约 11k memory tokens 仍未解决这个差距，说明同时存在：

```text
over-retrieval   同一 anchor / session / topic 的重复证据
under-coverage  回答所需的另一个语义 facet 没有进入 Context
```

因此 Product-07 的优化目标不是 `rank-1 relevance`，而是固定预算内的边际 EvidenceSet
coverage。gold group 只用于离线评分；产品 Runtime 只能使用 query、候选语义、真实 identity 和
observation，不能看到 gold session 或 expected answer。

### 2.5 消费层仍然过早收敛

Product-06 虽已从强制 Ledger 切换为 model-native Reader，但当前 profile 仍固定关闭 Qwen
reasoning，模型通常在一次结构化动作中直接回答。对长 Context、多实体和相邻事实密集的输入，
这会把“协议自由”误当成“充分阅读”：Host 不再拒绝输出，但模型仍可能只消费首个显著 anchor。

消费层真正需要的是：

```text
exact question preserved
+ exact Reader-visible Context
+ model-native semantic review/reasoning
+ optional safe calculator
→ final concise answer
```

这里的 review 是临时推理过程，不是 Memory 对象，不要求列全 members，不由 Host 判断语义
完整性，也不会进入数据库、Canonical State 或后续检索索引。

## 3. 设计原则

### 3.1 原问题永远保留

每个显式 Memory read 至少执行：

```text
original question → official Raw FTS
original question → configured Dense（若服务可用）
```

模型生成的 query 只能追加，不能替换原问题，不能缩小 tenant、scope、source role、时间边界
或访问策略。

### 3.2 先构造简单、宽而不重复的候选池

先比较当前路径与一个无模型的简单候选：

```text
original-query FTS quota
+ original-query Dense quota
+ governed same-session/local adjacency
→ Evidence identity dedup
→ per-channel / real-session quota preservation
→ candidate pool
```

不同通道的 raw score 不直接比较；第一版使用 rank-based fusion。装配优先保留新 Evidence
identity 和新真实 session，而不是让同一主题、同一 session 的多个近重复窗口占满 Context。

这一阶段只回答“证据是否进入候选池”，不直接用全局 Top-k 生成最终 Context。如果简单 pool
已经覆盖必需证据，不为了使用 vLLM 而增加新的检索轮次。

### 3.3 使用轻量 RecallWorkspace 做 EvidenceSet 补全

普通 recall 不再以 `RequirementState` 或 TypeBinding 作为检索控制面。每个 query 只维护一个
query-local、非持久、无 authority 的轻量工作区：

```yaml
RecallWorkspace:
  original_query:
  anchors_found: []
  semantic_target_hints: []
  covered_target_hints: []
  uncovered_target_hints: []
  selected_evidence_ids: []
  seen_session_ids: []
  seen_region_ids: []
```

这些字段是调度提示，不是新的领域 Schema：

```text
semantic target 可以是自然语言短语，不要求固定 enum
错误或缺失 target 不得删除 original-query candidate
covered 只是本轮选择状态，不等于 Evidence Binding 或 COMPLETE
Workspace 生命周期随请求结束，不进入 PostgreSQL 或 Canonical State
```

第一版 EvidenceSet selector 在同一固定 candidate/window closure 上按边际增益贪心选择：

$$
Gain(e\mid S)=Rel(q,e)+TargetGain(e,U)+SessionNovelty(e,S)+ChannelNovelty(e,S)-Redundancy(e,S)
$$

其中 `U` 是尚未覆盖的软语义目标。为避免再写一套 benchmark-shaped entity/operand
parser，S2 只比较两个逐步增加的选择器：

```text
B1  deterministic soft selector
    original-query relevance + semantic novelty + relevant session diversity

B2  only if B1 remains incomplete
    Qwen reads the same bounded candidates and returns candidate IDs to prioritize
    + one optional natural-language uncovered-target hint
```

B2 不生成 members、typed roles 或计算表。Host 只验证 candidate ID 确实来自当前池、租户/权限不变
且不超预算，不判断模型的“选对了没有”。模型选择与 B1 backbone 取并集再去重，因此模型建议
失败时自然退化到 B1，不需要新的 fail-closed 状态机。所有 target hint 只增加候选优先级，不能成为
hard filter；无法可靠拆分时保留整个原问题作为唯一 target。

普通 recall 在 grounded Evidence 进入 Context 后即可交给 Reader。COUNT、时间范围、状态演化
等严格操作仍可在召回后做 identity/time/dedup/proof 验证，但这些后置验证不得决定普通 recall
搜什么、是否启用 Dense 或能否返回 Evidence。

### 3.4 vLLM/Qwen 只补语义表达，不填写领域表格

只有在全部已获取候选、合法局部闭包和 B1/B2 选择后，仍能证明所需证据不在当前池中时，
Qwen 才读取：

```text
原问题
初始 Reader-visible Context
已经尝试的 query
已见 Evidence/session 的权限裁剪摘要
```

模型只返回最小传输动作：

```json
{
  "action": "ANSWER | SEARCH",
  "queries": ["...", "...", "..."]
}
```

约束只有：

```text
SEARCH query 数量 1–3
每条 query 是有界自然语言字符串
不接受 SQL、代码、tool name、scope、tenant、candidate cap 或 COMPLETE
```

这不是新的 Ledger：没有 members、quantity、calculation、typed operand、proof 或完成状态。
request identity 和执行 lineage 由可信 Host 附加，不要求模型复制 digest。

当前已冻结的 5 条 SHADOW query 来自“Reader-visible 不完整”而不是“pool 缺证据”，
不得用于 residual 执行。这不否定 transport，只是修正 eligibility。

### 3.5 residual recall 必须走正式产品路径

Host 将模型 query 作为同一用户请求下的 additive recall cues，通过现有公开 MCP/Runtime
Memory read 执行。每个调用继续使用相同：

```text
tenant
principal/scope
permission/revocation snapshot
source snapshot
OpenWorker task identity
```

多个 Context 以 `(context digest, source-turn ref, Evidence identity)` 合并并重新编号 alias；
Reader 看到的文本与最终 lineage 必须一致。不得使用 Lab 自建 BM25、绕过 Gate 的向量搜索
或直接读取数据库候选。

### 3.6 一个有界 observation-conditioned cycle

第一版最多一次 residual search cycle：

```text
initial recall
→ one Qwen SEARCH/ANSWER decision
→ at most three parallel official residual reads
→ one final Reader answer
→ optional calculator round only when arithmetic is requested
```

不做自由 ReAct、多轮 `finish_search`、seed search、majority vote 或隐藏自动重试。若事实证明
第二次 observation-conditioned search 具有独立机会，再建立后续 Goal。

### 3.7 模型原生消费，不恢复中间领域协议

Evidence coverage 达标后，单独比较：

```text
D0  selected recall + current direct/model-native Reader
D1  same exact Context + Qwen native reasoning + optional safe calculator
```

D1 保留 Product-06 的最小 final transport，但不要求模型产生 support/member/calculation 表格。
若 vLLM endpoint 支持 Qwen 原生 reasoning，则 reasoning transcript 不持久化、不交给 Host 做
语义验证，只交付最终 answer/action。若 endpoint 不支持，则兼容方案是一次有界自由文本
evidence review，再将该临时文本与原 Context 一起交给最终 Reader；review 格式差异不得触发
Host rejection。

消费 Prompt 只表达三个通用目标：

```text
阅读全部可见 Evidence
回答问题要求的精确关系，而不是相邻事实
需要集合或算术时先核对所有相关 Evidence，再按需调用 calculator
```

不向模型注入 gold requirement、题型 enum、预期成员数或答案格式。最终引用仍只能解析为实际
Reader-visible alias；模型推理不能授予 Evidence authority 或 COMPLETE。

消费修复只在 `ReaderVisibleRequiredEvidenceCoverage = 1.0` 的评价 cohort 上归因。Context
不完整的 case 不能用于证明或否定 D1；这样不会再次用 Prompt 修复检索问题。

### 3.8 可用性优先预算

初始实验上限：

```text
total unique retrieval candidates       240
total hydrated Evidence units           160
effective Reader-visible Evidence tokens 16,384
provider context ceiling                65,536
Memory deadline                         10,000 ms
residual query count                    0–3
parallel residual MCP reads             up to 3
model-native reasoning                  enabled only in D1
provider calls after final Context      at most 2 normally; 3 with calculator
semantic retries / votes                0 / 0
```

这些是上限，不是每次必须消耗的配额。run-lock 同时记录 requested 和 Runtime 回执的
effective 值；当前 public contract 不允许超过 16,384，本 Goal 也不通过 schema 修改绕过。报告真实
扫描、hydration、tokens、latency 和 Provider calls；先证明可用，再根据真实分布缩减成本。

## 4. 两项主要假设

### P07-H1 — 通用 Evidence 补全

原 P07-H1 在已打开的 12-case V0 上未建立：S1-R2 达到 10/12 和 0.8889，但没有达到
0.90。不通过事后降低门槛把它改写为 PASS。

V0 现在只用于 S2 开发；固定方法后，P07-H1 在未消费的 24-case R3 Context-only 比较上判定：

```text
V0 development closure before freeze       at least 11/12 complete
V0 Reader-visible group coverage            at least 0.90
R3 all-required complete-case gain           at least +4 over A
R3 mean Reader-visible group coverage gain   at least +0.10 over A
R3 recovered query shapes                    at least 3
R3 any-gold-session recall                   no regression
R3 previously complete EvidenceSets lost    0
```

treatment 不能读取 case ID、gold answer、gold terms、gold session 或 scorer outcome。此假设只
证明 Reader 前证据补全，不声称 QA 已提高。B0/B1/B2 必须共享相同 candidate pool、hydration 和
token ceiling，以隔离 EvidenceSet selection；C 的额外 official reads 单独报告，不能把扩大扫描
伪装为 selector 增益。

### P07-H2 — 完整 Evidence 的可靠消费与真实 OpenWorker 可用性

通过 P07-H1 后，在 Product-06 预冻结且未消费的 24-case R3 上，经真实 PostgreSQL → MCP →
Runtime → OpenWorker → vLLM/Qwen 路径，相对当前 direct 产品路径：

```text
coverage-qualified consumption cohort      at least 8 cases / 3 query shapes
coverage-qualified additional correct      at least 2
coverage-qualified baseline-correct loss   0
additional correct                         at least 4
net correct gain                           at least 3
gain families / query shapes               at least 3
baseline-correct ordinary lookup losses    0
all baseline-correct losses                at most 1
unsupported answer                         0
Host protocol rejection                    0
transport repeat / semantic retry          0 / 0
tenant leak / Canonical mutation            0 / 0
```

coverage-qualified cohort 只按 Reader-visible required Evidence coverage 构造，不按 direct
答案对错选择。若 D1 没有独立消费增益，则保留当前 Reader；若无模型 simple union 已达到召回
效果，也不启用 residual search。每个额外组件都必须有自己的 mediator gain。

## 5. 五个连续阶段

### S0 — 已完成：只读归因与执行身份

完成：

```text
冻结 Product-06 terminal 与 R2 source identities
逐例区分 discovery / fusion / admission / Reader first loss
记录 original-query FTS、Dense 和 Reader-visible lineage
探测 vLLM minimal action transport
冻结 A/B0/B1/B2/C retrieval arms、D0/D1 consumption arms、预算、模型和 R3 selection
```

S0 已完成 Product pin 和 V0 来源固定；Answer/Judge 调用为 0。后续只需修正 requested/effective
budget 记录，不再新建一套身份层。

### S1 — 已完成 PARTIAL：Query-preserving simple recall

S1-R1 恢复 3 个不完整 Context，但丢失 2 个旧完整例。S1-R2 的通用修复消除回归，得到
10/12 完整 Context 和 0.8889 group coverage。由于 Dense 未调用，S1 改名为 simple recall，
不宣称 multi-channel effect。剩余两例的所有 required source refs 已在 acquired results 中，
正式首损为 `EVIDENCESET_SELECTION_GAP`。

### S2 — 已完成但未建立增益：Same-pool EvidenceSet selection

先在与 S1-R2 完全相同的 candidate/window closure 上实现 B1：

```text
B1  B0 candidate pool
    → RecallWorkspace
    → marginal target/session/channel coverage selection
    → compact Reader Context
```

若 B1 仍无法从现有池中恢复至少一个剩余不完整 EvidenceSet，再使用同池 B2 模型选择：

```text
B2  same candidates + one Qwen candidate-ID prioritization + B1 fallback union
```

target hints 和 covered/uncovered 状态不能 hard-drop original-query candidates。先在两个剩余单点比较
S1-R2/B1，再运行 12-case matched coverage。通过条件是至少 11/12 完整、coverage 至少
0.90、旧完整例零丢失。

已有 S2 residual SHADOW 保留为 transport 证据，但不执行其 query。只有新 selector 后的 full-pool trace
证明 `POOL_DISCOVERY_GAP` 时，才恢复 C：

```text
C  selected B + one Qwen SEARCH/ANSWER decision + additive official residual reads
```

模型输出只承担同池选择或 query 表达；Host 继续拥有权限、预算、调用和 Context 合并。

实际结果：B1 在 V0 达到 11/12、0.9167 且零旧损失，因此跳过 B2；冻结后的 R3 却相对 A
完整 EvidenceSet -2、平均 group coverage -0.0944，并丢失四个原本完整案例。B1 不被选择。

### S3 — 完整 Evidence 上的消费修复

`NOT_ENTERED_BY_H1_GATE`。以下内容保留为未执行的预注册设计：

执行顺序：

```text
selected B/C produces fixed Context
→ construct coverage-qualified cohort without reading answer outcomes
→ D0 current Reader
→ D1 same Context with Qwen native reasoning
→ optional calculator only when requested
→ deterministic answer scoring / local judge for open text
```

先在已打开 R2 的完全覆盖错例验证机制，再在至少 8 个、横跨至少 3 种 query shape 的
coverage-qualified cohort 上决定。不得修改 Context、检索结果、gold label 或评分器来帮助 D1。
若 D1 不提高消费正确性，则保持当前 Reader，并将错例保留为模型能力边界。

### S4 — 真实 OpenWorker 验证、选择与交付

`CONTEXT_ONLY_COMPLETE / ANSWER_EFFECT_NOT_ENTERED_BY_H1_GATE`。R3 仅执行 PostgreSQL →
MCP/Runtime Context 路径；以下 Answer/Judge 路径未执行：

在 Product-06 未消费的 24-case R3 上执行 selected retrieval × selected Reader：

```text
historical sessions → PostgreSQL → MCP/Runtime
→ native OpenWorker → vLLM/Qwen
→ deterministic scorer / local Qwen judge
```

每个 case 只有一个有效终态。基础设施错误不计作 semantic abstention，修复基础设施后重放
同一 case；语义失败不自动 retry。

选择顺序：

```text
B0 与 B1 等效 → 选择 B0
B1 建立固定池 coverage gain → 选择 B1
B2 无同池独立增益 → 删除 B2 wiring，保留 B1
C 只有成本增加、无独立增益 → 保留 B0/B1，删除 C 的产品 wiring
D1 无消费增益 → 保留当前 Reader
D1 建立 coverage-qualified gain → D1 保持 feature-gated candidate
C/D1 共同建立 P07-H2 → 各自仅保留有独立 mediator gain 的组件
任何候选安全失败 → 保持当前 direct
```

更新 OpenWorker runbook、Product status、Lab result 和回滚说明。Formal 500 仍不运行。

## 6. 失败后的反思与继续规则

单个失败不终止 Goal。每个失败先在单 case 重放并定位首损：

| 首损 | 优先修复 | 明确禁止 |
| --- | --- | --- |
| 所有正式 channel 都未发现 Evidence | 检查 representation；使用 observation-conditioned residual query | 加 gold synonym、case 分支 |
| acquired pool 有 Evidence，但 admission 丢失 | same-pool B1/B2 边际 EvidenceSet 选择 | residual search、只扩大 global Top-k |
| 已命中 anchor、其他 group 缺失 | RecallWorkspace 的 uncovered target 与跨 session 边际选择 | 新增 TypeBinding slot |
| soft target 识别错误 | 保留 whole-query target 与原始候选回退 | 用 target 做 hard filter |
| 同一主题重复挤占 Context | relevance floor 后的 redundancy penalty / session novelty | 无条件每 session 保留一条 |
| admitted pool 有 Evidence，但 Reader Context 丢失 | whole-unit admission、identity dedup、alias merge | 把 session hit 冒充 span coverage |
| 全部 Evidence 可见但只消费一个 anchor | native reasoning / 非持久 soft review | 恢复 Ledger 或 member schema |
| 全部 Evidence 可见但关系答偏 | 精确问题保留、通用 relation fidelity 指令 | relation enum、问法 regex、答案规则 |
| Evidence 已正确识别但算术错误 | Host-safe calculator | member-expression 对齐协议 |
| 模型重复旧 query/region | 提供 attempted queries 与 compact seen summaries | 新增 typed failure taxonomy |
| minimal action 输出不稳定 | 修 vLLM adapter/decoding transport | 恢复 EvidenceLedgerV01 |
| run-lock 预算与实际 profile 不符 | 记录 requested/effective 两个值 | 用计划值冒充实际执行 |
| timeout/lease/serialization | 修基础设施后重放 exact case | 计作 abstention 或语义 miss |

最多进行三轮跨 case 的通用 repair iteration。每轮必须：

```text
证明至少影响两个 case 或一个可独立描述的机制族
先跑失败单点
再跑 12-case matched slice
保留简短 failure note
继续后续阶段
```

只有 tenant/scope 泄漏、Canonical mutation、破坏性不确定性或缺少外部授权才立即停止。

参考项目只作为失败后的机制提示：

```text
ReFind       observation 改变下一次 query，而非堆叠同义词
Hindsight    保留 observation 与可修正语义组织的分层
Mem0         优先短路径和简单可用接口
Graphiti     身份、episode 和时间关联不能被向量相似度替代
OpenViking   先缩小资源区域，再消费高成本内容
```

不得把任何参考项目整体搬入 Product-07。

## 7. 减少防御性编程和审计

只在四个真实边界验证：

```text
tenant/scope/revocation
external model/MCP payload
Reader-visible alias/provenance
Canonical mutation absence
```

内部已验证对象不重复包装，不新增第二套 digest graph、RequirementState、Ledger、proof schema
或 completion owner。模型原生 reasoning 与 soft review 都是一次请求内的临时计算，不创建
新的审计对象；只记录 profile、调用数、token、最终答案和错误类别。

每次正式运行只保留：

```text
run-lock.json
cases.jsonl
summary.json
failure-notes.jsonl
terminal.json
```

开发中先跑单点测试；最终才跑受影响 package、静态检查、构建和真实 PostgreSQL/OpenWorker
闭环。允许在机器容量内最多四 case 并行，不复制四套审计层。

## 8. 禁止项

```text
不新增 case ID、答案值、gold term 或 benchmark quote
不新增 synonym 表或 query-type regex 来过 case
不恢复 TypeBinding、typed operand 或模型 COMPLETE
不让普通 recall 的 RequirementState/TypeBinding 控制 probe、channel 或 candidate admission
不把 RecallWorkspace 持久化为第二套 Memory State
不扩展 EvidenceLedgerV01
不要求 evidence review 符合 support/member/calculation schema
不让 Host 根据模型草稿的“完整性”拒绝最终答案
不让模型选择 tenant、scope、权限、candidate cap 或任意工具
不让 residual query 替换原问题
不使用 Lab-owned simplified retrieval 形成产品结论
不因单例失败换 seed、投票或自动 retry
不消费 formal 500-case holdout
不修改 public MCP/API、数据库 Schema 或 Canonical writer
```

## 9. 终态

实际终态：`PARKED_PRODUCT07_NO_GENERAL_EVIDENCE_GAIN`。

```text
PASS_PRODUCT07_SIMPLE_EVIDENCE_RECALL_USABLE
  P07-H1/H2 由无模型 B0/B1 建立；选择最简单路径。

PASS_PRODUCT07_MODEL_GUIDED_RECOLLECTION_USABLE
  C 和/或 D1 建立独立 mediator 与任务净增益；只保留有效组件。

PARTIAL_PRODUCT07_EVIDENCE_COVERAGE_IMPROVED_QA_UNRESOLVED
  Evidence coverage 明显改善，但消费或答案效果未达 H2；保留最简单安全改进。

PARKED_PRODUCT07_NO_GENERAL_EVIDENCE_GAIN
  三轮通用修复后仍无跨 case Evidence coverage 增益；不发布 treatment。

FAIL_PRODUCT07_MEMORY_AUTHORITY_OR_TENANT_SAFETY
  tenant/scope/revocation、Canonical authority 或可恢复性边界失败。
```

## 10. 当前授权

本 Goal 已收口，不再授权新的 Product-07 执行：

```text
S1-R1 / S1-R2 Context replay       COMPLETED, H1 NOT ESTABLISHED
S2 residual proposal SHADOW        COMPLETED, EXECUTION INELIGIBLE
same-pool B1 implementation        COMPLETED, DEFAULT OFF / NOT SELECTED
same-pool B2 implementation        SKIPPED BY V0 GATE
residual official reads            NOT AUTHORIZED
R3 24-case Context                 CONSUMED, P07-H1 FAILED
R3 Answer/Judge/OpenWorker effect  NOT ENTERED BY H1 GATE
formal 500                         NOT AUTHORIZED / UNCONSUMED
```

终态选择 `PARKED_PRODUCT07_NO_GENERAL_EVIDENCE_GAIN`。任何后续方向必须建立新的 Goal、
新的冻结数据与显式授权；不得复用已打开的 R3 作为未见验证集。
