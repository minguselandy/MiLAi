# MiLAi Lean V1：产品底座与研究核心

> **2026-08-16 架构更新：** Logical Architecture 改为由 MiLAi 项目自行设计和实现；当前
> candidate 见 `MiLAi_Logical_Architecture_v1_设计文档.md`。下方旧“对齐 frozen baseline”
> 元数据不再表示存在外部冻结原件。

> 文档状态：即时实施剖面，非新的逻辑架构版本  
> 对齐基线：MiLAi Logical Architecture `1.0.0 FROZEN`  
> 产品目标：可运行的个人记忆系统  
> 研究目标：一个可证伪的算法问题  
> Research Core：Open-State-Preserving Compression，`RQ pending`  
> 日期：2026-08-11

本文件收缩 MiLAi 的近期实施范围。它不删除冻结对象，也不重定义 invariant；它只决定哪些能力进入 Lean V1 的在线关键路径，哪些退回实验、评测或未来版本。

原有 `MiLAi技术升级需求说明_v2.md` 继续作为长期架构和能力地图，`MiLAi开发实施与使用流程_v1.md` 继续保存完整工程任务。近期开发、实验和论文工作以本文件的范围为优先。

---

# 1. 决策结论

MiLAi 不再同时追求完整 memory infrastructure 和多个研究创新。项目拆成两部分：

```text
A. Lean Engineering Substrate
   一个正确、可追溯、足够小的个人记忆系统

B. One Research Core
   Open-State-Preserving Compression
```

近期停止横向扩展：

```text
不接多个 Shadow Memory
不默认启用 Temporal Graph
不做自动 Scope Evolution
不做自动 Pattern Promotion
不做 Multi-Agent Memory Governance
不把 Memory Intention 作为产品前置依赖
不把系统工程模式包装成算法 novelty
```

工程底座的价值是保证实验不会因状态覆盖、证据丢失或检索污染而失真。论文贡献必须来自 Research Core，而不是 PostgreSQL、CAS、Outbox、FTS、pgvector 或治理流程的组合。

---

# 2. Lean V1 的边界

## 2.1 必须在线运行

```text
EvidenceRecord
Claim / ClaimVersion / ClaimHead
OpenIssue
OperationProposal internal contract
Minimal ContextCapsule
PostgreSQL exact + FTS + pgvector
Basic deletion/revocation
Operational trace
```

## 2.2 只在离线评测运行

```text
AuditRecord
compression experiments
baseline comparison
paper metrics
policy release decision
```

## 2.3 默认关闭

```text
MemoryIntention scheduling
Hindsight production route
Graphiti/Zep production route
ReMe/OpenViking production dependency
automatic profile promotion
automatic scope induction
multi-agent maintenance agenda
LoRA personalization
multimodal/family sharing
```

冻结架构中的对象仍然有效。默认关闭表示 Lean V1 不依赖该能力，不表示对象语义被删除。

---

# 3. 控制层收缩

原完整链路：

```text
Evidence
→ State Deriver
→ Diagnosis
→ OperationProposal
→ Invariant Validator
→ Memory Steward
→ Governance
→ Canonical Commit
```

Lean V1 将其组合成三个运行组件：

```text
Evidence
→ DeriveAndDiagnose
→ ValidatedProposal
→ CommitPolicy
→ Versioned Claim
```

## 3.1 `DeriveAndDiagnose`

一个应用模块同时完成：

```text
提取候选 Claim
查找现有 current Claim
分类 CREATE / UPDATE / CONFLICT / NO_CHANGE
生成或更新 OpenIssue candidate
给出 Evidence、Scope 和 confidence
```

Diagnosis 不再是独立部署服务，只是 Deriver 的结构化输出。

## 3.2 `ValidatedProposal`

`OperationProposal` 仍然存在，但只作为内部 typed contract。确定性 validator 在 proposal 创建时执行：

```text
Evidence 是否存在且未撤销
expected version 是否正确
Scope 是否合法
是否越权提升 authority
是否非法关闭 OpenIssue
是否携带足够 replay metadata
```

Validator 是 library，不是独立服务或第二次智能判断。

## 3.3 `CommitPolicy`

Steward 与 Governance 合并成一个提交策略：

```text
AUTO_COMMIT
USER_REVIEW
REJECT
NO_CHANGE
```

建议 V1 策略：

| 情况 | 处理 |
| --- | --- |
| 明确、低风险、INFORMATIONAL、无冲突 | 可自动提交 |
| 用户明确确认或纠正自己的信息 | 提交并保留 USER_CONFIRMATION Evidence |
| 与现有 Claim 冲突 | 建立 OpenIssue，默认不自动覆盖 |
| 请求 ACTION_SAFE 或全局 Profile | 用户审核 |
| Evidence 不足或 Scope 不明 | NO_CHANGE 或保留 OpenIssue |
| 删除、权限和敏感数据 | 用户确认并走专用流程 |

数据库仍通过受控 procedure 执行版本创建和 CAS。合并应用层组件不等于允许直接 DML。

---

# 4. 写路径

```text
Observation
→ EvidenceRecord
→ DeriveAndDiagnose
→ ValidatedProposal
→ CommitPolicy
→ CREATE / UPDATE / CONFLICT / NO_CHANGE
→ ClaimVersion + ClaimHead
```

## 4.1 V1 操作集合

对产品和开发者只暴露四个概念：

```text
CREATE      创建第一版 Claim
UPDATE      创建新版本并移动 ClaimHead
CONFLICT    保留正反 Evidence 和 OpenIssue
NO_CHANGE   记录判断，不改变当前状态
```

底层仍可以映射到现有 `TX-01` 至 `TX-06`，但 UI、API 和心智模型不要求普通用户理解完整 operation matrix。

## 4.2 冲突优先保留

```text
Old Claim + New Supporting Evidence
→ UPDATE candidate

Old Claim + New Contradicting Evidence
→ CONFLICT
→ OpenIssue
→ 等待用户确认或新 Evidence
```

V1 不自动做复杂 SPLIT、跨 Claim 重构或自动 Scope Promotion。

---

# 5. 读路径收缩

原完整链路中的 Query Interpreter、Router、Candidate Fusion、Canonical Resolution、Evidence Bundle 和 Context Manager 保留为代码责任，但合并进一个 `RetrievalService`，不拆成多个服务。

```text
Query
→ Route
→ Retrieve
→ Canonical Filter
→ Context Build
→ LLM
```

## 5.1 三条路线

```text
EXACT
→ SQL subject/predicate/current ClaimHead

HYBRID
→ PostgreSQL FTS + pgvector

RECONSTRUCTIVE
→ iterative retrieval over Evidence/versions
```

`RECONSTRUCTIVE` 只用于复杂时间、来源和冲突问题。Lean V1 不依赖 Graphiti。

## 5.2 检索硬门

每个候选在进入 Context 前检查：

```text
tenant/subject
permission
deletion/revocation
current or requested historical version
Scope
valid time
OpenIssue/conflict state
required authority
Evidence reference
```

FTS 和 vector score 只排序候选，不能提升 authority 或覆盖冲突。

## 5.3 最小 Context

```text
Goal
Current State
Open Issues
Relevant Evidence
Pointers
```

不在 V1 引入复杂 ContextBackend 编排。自研结构化 ContextCapsule 是产品基线；ReMe 和 OpenViking只作为压缩实验对照。

---

# 6. 最小数据与进程

## 6.1 在线数据

```text
content_blob
evidence_record
claim
claim_version
claim_head
version_transition
claim_evidence_edge
open_issue
operation_proposal
commit_decision
search_document
search_embedding
operational_event
```

ContextCapsule 可以先作为带 TTL 的持久对象或缓存，不单独建设 Context service。

Outbox 只承担 embedding/search projection 和删除清理，不提前建设通用 Projection Registry。

## 6.2 运行进程

```text
Flask API
PostgreSQL
One background worker
LLM/embedding client
```

不拆微服务，不引入 Kafka，不运行多个 memory database。

## 6.3 单用户部署

Lean V1 只支持本地单用户、单 tenant。Schema 仍保留 `tenant_id`，但不开放远程多租户服务。家庭共享、复杂 RLS 和跨设备授权在后续版本处理。

删除仍需做到：

```text
Evidence revoke
→ current Claim 重新判断或阻断
→ search/vector purge
→ Context pointer removal
```

---

# 7. 外部项目重新定位

| 项目 | Lean V1 位置 | 是否上线依赖 |
| --- | --- | --- |
| PostgreSQL | Canonical state、FTS | 是 |
| pgvector | 语义候选召回 | 是 |
| ReMe | Context compression baseline | 否 |
| OpenViking | hierarchical context baseline | 否 |
| Hindsight | shadow recall baseline | 否 |
| Mem0 | conventional memory baseline | 否 |
| Graphiti | temporal graph baseline | 否 |
| Zep | Graphiti 托管替代 | 否 |
| MemOS/EverMemOS | 系统级对照 | 否 |

任何外部项目必须读取相同的 Episode/Evidence snapshot，并在相同 token 和计算预算下比较。没有独立增益就不进入产品默认路线。

---

# 8. 唯一 Research Core

## Open-State-Preserving Compression

研究问题暂定为：

> 在相同 token budget 下，显式保留未解决问题身份、正反 Evidence lineage 和合法 discharge 条件，能否减少 compression-induced false epistemic closure，并改善后续任务决策？

状态保持为：

```text
RQ pending
Novelty unvalidated
Method candidate only
```

当前不得将它描述为新的已验证算法贡献。

---

# 9. 问题定义

给定 Episode trace：

```text
T = (Claims, Evidence, OpenIssues, Dependencies, Events)
```

在 token budget `B` 下生成 compressed context `C`：

```text
C = Compress(T, B)
```

普通压缩主要优化：

```text
TaskUtility(C) - λ TokenCost(C)
```

本研究增加 epistemic preservation：

```text
maximize
  TaskUtility(C)
  - λ TokenCost(C)
  - μ StateDistortion(C)

subject to
  FalseClosure(C) = 0
  OpenIssueIdentityRecall(C) = 1
  AuthorityEscalation(C) = 0
  LineageCoverage(C) >= τ
```

其中：

```text
FalseClosure
  raw 中 unresolved，compressed 中却成为 resolved conclusion

OpenIssueIdentityRecall
  每个仍开放 issue 的 ID、类型和 target 是否保留

AuthorityEscalation
  compressed state 是否获得 raw 中不存在的 authority

LineageCoverage
  support/contradict branch 是否仍能回到 Evidence pointer
```

---

# 10. 最小算法候选

算法暂称 `OSPC`，只作为工作名。

## 10.1 输入

```text
Canonical Episode snapshot
Current Goal
Token Budget
OpenIssue set
Evidence/dependency graph
```

## 10.2 四阶段处理

### A. Epistemic graph extraction

使用 Canonical Core 已有结构构造：

```text
Claim node
Evidence node
OpenIssue node
support/contradict/depends-on edge
authority and valid-time label
```

这一步不要求 LLM 从纯文本重新猜测已经存在的结构。

### B. Protected closure

对每个仍开放的 OpenIssue 计算保护闭包：

```text
OpenIssue identity
+ target Claim
+ at least one pointer for every live support branch
+ at least one pointer for every live contradiction branch
+ resolution/discharge condition
+ validity-critical dependency
```

Protected closure 不能被普通 summarizer 删除或改写为单值结论。

### C. Budgeted compression

剩余内容按预算处理：

```text
stable state        → structured representation
repeated evidence   → deduplicate + pointer set
large raw content   → pointer + bounded excerpt
finished operations → evict from active context
low-value narrative → summarize or remove
```

优先压缩 protected closure 之外的区域。

### D. Preservation validator

生成结果后执行确定性检查：

```text
所有 open issue ID 是否存在
support/contradict 分支是否仍可区分
Evidence pointer 是否可恢复
是否生成 raw 中不存在的 resolution
authority 是否提升
dependency 是否断裂
```

失败时：

```text
retry with stricter template
→ increase protected budget
→ fallback to extractive protected state
```

---

# 11. 为什么它可能独立于普通 Summary

普通 Summary 输出一段较短文本。OSPC 候选输出的是：

```json
{
  "stable_state": [],
  "open_issues": [
    {
      "issue_id": "O17",
      "target_claim_id": "M81",
      "status": "WAITING_EVIDENCE",
      "support_refs": ["E202"],
      "contradict_refs": ["E115"],
      "discharge_rule": "production runtime evidence"
    }
  ],
  "evidence_pointers": [],
  "evicted_recoverable": [],
  "compression_trace": {}
}
```

潜在机制差异不在“使用结构化 JSON”，而在：

```text
issue identity is protected
conflict branches cannot collapse
resolution requires new admissible evidence
compression is rejected when those conditions fail
```

这些差异仍需经过 prior-art/absorber 审计，不能从设计直觉直接推导 novelty。

---

# 12. Baseline 与吸收风险

至少比较：

```text
Full raw context
Naive recursive summary
Extractive top-K
Hierarchical summary
Structured context eviction
Typed state summary with OpenIssue field
ReMe/OpenViking baseline where runnable
OSPC full method
```

必须包含以下消融：

```text
OSPC without protected closure
OSPC without discharge rule
OSPC without conflict-branch preservation
OSPC without validator/fallback
Static keep-all-open-issues baseline
Equal-token oracle selection
```

最大吸收风险是：强 structured eviction 或 typed context baseline 已经完整保留 issue/dependency，OSPC 最终只等价于“给 OpenIssue 一个不可删除字段”。如果最强 baseline 在相同预算下达到相同结果，应放弃算法 novelty claim。

---

# 13. 数据与任务设计

## 13.1 样本必须包含真正未解决状态

```text
支持和反驳 Evidence 同时存在
Scope 尚未确定
Authority 尚未确认
Dependency 改变但尚未重验
计划存在未完成前置条件
用户偏好可能随任务类型变化
```

## 13.2 Episode 序列

```text
Episode 1：产生冲突
Episode 2：压缩后继续任务，但没有新解决证据
Episode 3：出现真正 admissible resolving evidence
Episode 4：要求解释历史和最终 resolution
```

这样才能区分：

```text
保存了文本
保存了 unresolvedness
错误提前关闭
收到新证据后合法关闭
```

## 13.3 双域验证

优先选择两个域：

```text
Software Project Memory
Personalized Multi-Session Assistant
```

前者便于构造机器可判定的配置、测试和运行时冲突；后者验证 task-conditioned preference 和开放画像问题。

---

# 14. 指标

## 14.1 主要指标

```text
False Epistemic Closure Rate
OpenIssue Identity Recall
Conflict Branch Recall
Legal Discharge Accuracy
Authority Escalation Rate
Later-Episode Task Success
```

## 14.2 成本指标

```text
token count
compression latency
recovery calls
Evidence pointer count
fallback rate
```

## 14.3 普通质量指标

```text
factual consistency
answer correctness
unsupported claim rate
context relevance
```

ROUGE 或自然语言相似度只能作为辅助指标，不能证明 epistemic state 得到保留。

---

# 15. Hard Falsifier

出现任意情况，主动停止主张该算法方向成立：

1. 强 structured eviction/typed-state baseline 在相同 token budget 下达到相同 false-closure 和 task-success；
2. 简单“始终保留 OpenIssue 字段”与完整 OSPC 等价；
3. 性能增益来自更多 token、额外 oracle label 或更强模型；
4. OpenIssue identity preservation 不改善后续任务或合法 resolution；
5. 方法只能在人工构造文本上工作，真实项目 Episode 不出现可测差异；
6. validator/fallback 成本抵消 token 与决策收益；
7. prior art 已完整包含相同 protected closure、discharge constraint 和 false-closure evaluation。

这一步以前保持 `RQ pending`，不冻结论文标题、贡献或 benchmark。

---

# 16. Lean 开发路线

## Phase A：Artifact Gate

```text
冻结现有 architecture tests
构造 30–50 个最小 conflict/open-state fixtures
实现 naive summary、extractive 和 typed-state baseline
确认 false-closure 可以稳定测量
```

退出条件：如果 baseline 之间没有可重复差异，不进入算法开发。

## Phase B：Lean Product Core

```text
Evidence ingest
Versioned Claim
OpenIssue
Exact + FTS + pgvector
Minimal Context
Basic deletion
```

退出条件：Python 版本冲突等纵向用例可完整回放和查询。

## Phase C：OSPC Prototype

```text
Epistemic graph
Protected closure
Budget allocator
Preservation validator
Fallback
```

退出条件：所有受保护 invariant 在单元和性质测试中成立。

## Phase D：Equal-Budget Evaluation

```text
同模型
同 token budget
同输入 Episode
同 retrieval access
不同 compression method
```

退出条件：报告效果、成本、失败分布和消融，不只报告平均分。

## Phase E：Novelty Gate

```text
mechanism-first prior-art search
strongest absorber implementation
noun-erasure test
separation witness
hard-falsifier review
```

退出条件：只有不被最强 baseline 吸收时，才形成 paper candidate。

## Phase F：Optional Product Integration

算法和产品指标同时通过后，再决定是否把 OSPC 用作 MiLAi 默认 Context compressor。研究失败不影响 Lean Product Core 的运行。

---

# 17. 近期任务清单

```text
LEAN-001  冻结 Lean V1 范围和非目标
LEAN-002  合并 Deriver/Diagnoser/Validator/Steward 应用组件
LEAN-003  建立最小 PostgreSQL Schema
LEAN-004  完成 Evidence → Versioned Claim 纵向闭环
LEAN-005  完成 Exact + FTS + pgvector 读路径
LEAN-006  完成 OpenIssue 冲突保留
LEAN-007  完成 Minimal ContextCapsule
LEAN-008  建立 open-state fixture schema
LEAN-009  实现 naive/extractive/typed-state baselines
LEAN-010  定义 False Epistemic Closure scorer
LEAN-011  实现 protected closure
LEAN-012  实现 budgeted compression
LEAN-013  实现 preservation validator/fallback
LEAN-014  运行 equal-budget ablation
LEAN-015  执行 prior-art/absorber audit
LEAN-016  做 go/hold/abandon 决策
```

暂停原计划中的：

```text
ReMe production integration
Hindsight production integration
Graphiti production integration
Scope Evolution
Memory Intention scheduler
Multi-Agent governance
Profile automatic promotion
```

这些任务只有在 Lean Core 或研究实验明确需要时才重新开启。

---

# 18. 最终项目叙事

## 产品叙事

```text
MiLAi 是一个 evidence-first、versioned、conflict-aware 的个人记忆系统。
```

产品不需要声称数据库和检索组合具有算法 novelty。

## 论文叙事候选

```text
Long-context compression can create false epistemic closure.
We study whether identity-preserving, discharge-constrained compression
can preserve unresolved state under equal token budgets.
```

这只是候选叙事。只有完成 artifact、baseline、absorber 和 falsifier gate 后，才能升级为研究贡献。

---

# 19. 最终判断

Lean V1 的目标不是实现最多的 Memory 功能，而是提供两个清晰结果：

```text
一个不依赖外部 memory engine 也能工作的个人记忆产品底座

一个与工程底座分离、能够被强 baseline 直接证伪的研究问题
```

如果 Open-State-Preserving Compression 被 prior art 或简单 baseline 吸收，产品底座仍然保留；研究方向则直接放弃或重新选择，不再通过扩建架构掩盖算法缺口。
