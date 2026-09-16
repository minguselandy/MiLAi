---
document_id: MILA-MF02
version: "0.1"
status: DESIGN_COMPLETE_EXECUTION_NOT_AUTHORIZED
execution_order_authority: MILA-ML-MASTER@1.4
architecture_baseline: MILA-ML-ARCH@1.0
execution_authority: NONE
predecessor_terminal: var/md01/md01-memory-formation-bundle-20260830-001/terminal.json
---

# MiLAi MF-02：Semantic Episode 四臂表示比较与独立泛化 Goal

> 日期：2026-08-30（Asia/Shanghai）  
> Program：Memory Formation  
> 性质：DESIGN-ONLY Goal  
> Formal holdout：不使用  
> Experimental feature flags：OFF

> **权限边界**：本文只完成下一阶段 Goal 与实验合同设计，不授权创建新标签、修改代码、运行 scorer、调用模型、访问数据库、启动 effect、修改产品配置或使用 formal holdout。

## 1. 基线与剩余问题

MD-01 已封存：

```text
PASS_MD01_MEMORY_FORMATION_CORE
10 conversations / 35 turns / 16 episodes
Raw coverage = 1.0
Episode boundary P/R = 1.0 / 1.0
Episode pairwise F1 = 1.0
Provider/Reader/Retrieval/DB calls = 0
Canonical mutation = 0
```

该结果证明统一 `MemoryFormationBundleV01` 可以在第一组封存 non-holdout 数据上正确工作，但尚未回答：

1. semantic episode 是否真正优于 turn、固定窗口和 session；
2. 结果是否能迁移到与当前规则具有反例关系的独立数据；
3. episode 表示是否改善简单读取，而不仅是复现人工边界标签。

MF-02 的方法命题是：

> **在保留相同 Raw Evidence、相同 anchor ranking 和相同原子 turn 成本的条件下，semantic episode 应比简单切片更准确地组织相关上下文，并提高 support closure，而不增加检索通道或模型调用。**

## 2. Research Hypotheses

| Hypothesis | 预注册最小证据 |
| --- | --- |
| `MF02-H1` — Semantic episode 具有独立表示增益 | 独立 validation 上 `EpisodePairwiseF1 ≥ 0.85`，且相对最强简单基线的 paired macro delta `≥ 0.05`；Raw coverage、source order 和 role isolation 不回归 |
| `MF02-H2` — 表示增益能转化为简单读取效用 | 固定 Raw FTS anchors 下，`SupportClosureAUC[1..8]` 相对最强简单基线 delta `≥ 0.05`，且 `DistractorTurnRate` 不劣于 `+0.02` |

Anti-claims：

```text
不声称产品检索 recall 提升
不声称 formal-holdout 泛化
不声称 semantic episode 应成为 durable Canonical object
不把增益归因于 Dense、reranker、Reader、模型 planner 或更大 Top-k
```

## 3. 四个冻结表示 Arm

所有 Arm 使用完全相同的 Raw turns、source identity、权限和时间顺序，只改变 turn 的组织方式。

| Arm | 定义 | 目的 |
| --- | --- | --- |
| `A_TURN` | 每个完整 Raw turn 是一个独立 unit | 最小无聚合基线 |
| `B_FIXED_WINDOW_2` | 每个 session 内按时间顺序构造不重叠的 2-turn window；尾部允许单 turn | 固定局部上下文基线 |
| `C_SESSION` | 一个 session 内全部 turns 构成一个 unit | 最大粗粒度基线 |
| `D_SEMANTIC_EPISODE` | 复用 MD-01 冻结的 `SemanticEpisodeCandidateV01` builder | treatment |

统一约束：

```text
每个 Raw turn 在每个 Arm 中恰好出现一次
不改写、不摘要、不扩写 Raw text
session boundary 永不被 fixed window 跨越
不允许 Arm 读取 query、gold episode 或 required support labels
不允许为 effect case 添加 case-ID、词表或正则特判
```

`B_FIXED_WINDOW_2` 是唯一 MUST-RUN window。`window=4` 只允许作为 NICE-TO-HAVE sensitivity，不参与主假设判定。

## 4. 独立 validation 设计

### 4.1 数据分层

后续若获得执行授权，建立：

```text
repair-dev:
  8 conversations
  标签可用于修复通用实现问题

sealed-validation:
  至少 24 conversations
  至少 96 turns
  scorer-only labels
  只允许一次 protocol-valid 主 effect

formal holdout:
  untouched
```

MD-01 的 10 conversations 只用于 scorer sanity 和历史重放，不计入 MF-02 主效果分母。

每个 sealed conversation 必须同时包含至少一个 gold same-episode turn pair 和一个 gold cross-episode turn pair，避免 pairwise 指标出现无信息分母。

### 4.2 必须覆盖的反例族

sealed validation 至少覆盖：

1. 长时间间隔但仍是同一 topic；
2. 很短时间内发生真实 topic shift；
3. lexical terms 不相交但属于同一事件延续；
4. lexical terms 重叠但已经切换 topic；
5. 无显式 correction cue 的更正；
6. pronoun 开头但实际指向新 topic；
7. assistant anecdote 与用户事实竞争；
8. 一个 session 内多个独立个人记忆。

每个族在 sealed validation 中至少有 3 个 conversation，不使用当前实现的触发词反向生成全部样本。

### 4.3 标签

每个 conversation 只封存必要标签：

```yaml
expected_episode_membership: []
expected_boundary_reason: []
memory_probes:
  - query_text:
    required_support_evidence_ids: []
    distractor_evidence_ids: []
```

Builder 和 Raw FTS acquisition 不得读取这些字段。

## 5. 核心实验 Block

### B1 — Label and scorer sanity（MUST）

- 检查 turn 全覆盖、标签分区、support identity 和 scorer 的手算小例。
- 用 MD-01 旧预测验证新 scorer 能重放既有结果。
- 此阶段不修改 semantic builder。

### B2 — Four-arm representation comparison（MUST）

- 对四个 Arm 计算同一组 direct representation metrics。
- 主指标为 conversation-macro `EpisodePairwiseF1`。
- boundary precision/recall、self-containedness 和 cross-boundary dependency 作为解释指标。
- 四臂输出必须保留完整 Raw span identity。

### B3 — Anchor-fixed simple read（MUST）

```text
one official Raw FTS call per probe
→ freeze identical ranked anchor turns
→ map anchors into each representation Arm
→ hydrate under raw-turn ceilings 1..8
→ score support closure and distractors
```

限制：

```text
不调用 Dense / Enriched / reranker / Reader / Provider
不增加 acquisition round
同一 probe 的四个 Arm 共用一份 anchor ranking
预算以最终 hydrated Raw turns 计，不以 unit 数计
每个 representation unit 保持原子性，不允许截断 unit 取得预算优势
累计唯一 Raw turns 超过 ceiling 的下一个 unit 不进入 context
```

该 Block 只测“相同发现结果如何被不同 Memory 表示组织”，不宣称 acquisition recall 改善。

### B4 — Generalization decision and compact terminal（MUST）

- 只按预注册 H1/H2 判定。
- 输出失败分布：over-split、over-merge、assistant contamination、time-gap error、topic-shift error。
- protocol/implementation bug 允许通用修复；任何 semantic rule 变化只能使用 repair-dev，不能根据 sealed-validation label 回调。
- 终态只保留四件套，不生成逐阶段 receipts 或多轮审查。

## 6. 指标定义

### 6.1 Direct representation

```text
EpisodePairwisePrecision / Recall / F1
BoundaryPrecision / Recall / F1
RawSpanCoverage
SourceOrderPreservation
UserSemanticSourcePrecision
CrossBoundaryDependencyRate
```

### 6.2 Simple read

对每个 probe 和 raw-turn ceiling `b ∈ {1,...,8}`：

```text
SupportClosed(b) = 1
  iff required_support_evidence_ids 全部进入 hydrated context
```

主指标：

```text
SupportClosureAUC[1..8]
= mean_b SupportClosureRate(b)
```

H2 主判定使用全部 sealed probes；另报告 anchor pool 至少命中一条 required support 的预声明诊断层，但该子层不替代主分母。

次指标：

```text
RequiredEvidenceCoverage@b
UsefulTurnRate@b
DistractorTurnRate@b
MinimumTurnsToClosure
CrossEpisodeContaminationRate
```

统计单位为 conversation/probe，不把 turn pair 当作独立样本。报告 paired delta 和 conversation-level bootstrap 95% CI；CI 用于表达不确定性，不替代预注册 effect threshold。

## 7. 安全与范围门

以下必须全部成立：

```text
RawSpanCoverage = 1.0
SourceOrderPreservation = 1.0
UserSemanticSourcePrecision = 1.0
ArtifactLineageClosure = 1.0
Canonical mutations = 0
database writes = 0
Provider calls = 0
Reader calls = 0
model calls = 0
formal holdout used = false
product feature flags = OFF
```

合法 retention/revocation 造成的 Evidence 不可读必须按当前 Runtime fail closed，不得为比较覆盖率绕过。

## 8. Terminal 决策

```text
H1 PASS and H2 PASS
→ PASS_MF02_SEMANTIC_EPISODE_GENERALIZATION

H1 PASS and H2 MISS
→ PASS_MF02_REPRESENTATION_ONLY_NO_READ_GAIN
→ 保持 sidecar，禁止产品接入

H1 MISS and strongest simple baseline >= semantic episode
→ PARKED_MF02_SIMPLE_SEGMENTATION_SUFFICIENT

H1 MISS but all arms weak
→ PARKED_MF02_DATA_OR_REPRESENTATION_UNRESOLVED

Raw/role/lineage/authority boundary violated
→ FAIL_MF02_RAW_OR_AUTHORITY_BOUNDARY
```

一次 fail-closed protocol/implementation failure 是 `REPAIR_ITERATION`，不是 Goal terminal。只有实际 Raw loss、scope/authority escape、Canonical mutation 或数据损坏立即停止当次运行。

## 9. 建议执行顺序（未授权）

```text
S0 explicit execution authorization
→ S1 repair-dev + sealed-validation label seal
→ S2 scorer and four-arm sanity
→ S3 one protocol-valid direct + simple-read effect
→ S4 compact terminal and successor route
```

资源预算：

```text
GPU hours: 0
model / Provider / Reader calls: 0
official Raw FTS calls: one per probe, shared by all arms
effect attempts: one protocol-valid sealed-validation run
```

## 10. 后续路由

只有 `MF02-H1/H2` 同时通过，才可以另行设计：

```text
semantic episode product-shadow integration
expanded MF-06 Formed+Simple comparison
larger non-holdout identity/time/state-change replay
```

即使 PASS，也不自动授权：

```text
formal holdout
background worker
PostgreSQL/public MCP schema
durable Episode replacement
default feature flag
adaptive retrieval / DG-29
```
