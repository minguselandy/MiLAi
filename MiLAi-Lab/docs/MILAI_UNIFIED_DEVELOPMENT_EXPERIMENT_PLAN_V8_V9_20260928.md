---
title: MiLAi 统一开发与实验规划（v8 + v9 合并版）
merge_revision: "1.0"
date: 2026-09-28
status: MERGED_PLAN_NOT_EXECUTED
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
baseline_report_commit: 77dfc2f43f2307bb649cdbee9d62a97e5863fac0
baseline_runtime_commit: 2f30c14c5e7ea82db2b0a962d3636e14de5f2391
baseline_pr: 71
baseline_recipe: JSON-action / B0 / strict / retained / current_request / compact_v6
research_goal: NOT_ACHIEVED
product_status: NO_GO
source_basis: ATTACHED_V8_AND_V9
external_reverification_this_merge: false
runtime_experiments_this_merge: 0
github_writes_this_merge: 0
execution_authorization: NOT_GRANTED_BY_DOCUMENT_GENERATION
source_documents:
  - file: MILAI_DEVELOPMENT_EXPERIMENT_PLAN_20260928_v8.0.md
    sha256: f5d5dcdbfbb25ee3f16ba4ebe3c8bf1aad61b1d047e6aa22b86b8c26eda34f32
    lines: 1185
  - file: MILAI_BENCHMARK_FUNCTIONAL_COMPARISON_PLAN_20260928_v9.0.md
    sha256: dbaf2a2835af161af627beb5b0e0f183da71b11553ee427f6cddaf867930dbfa
    lines: 609
---

# MiLAi 统一开发与实验规划（v8 + v9 合并版）

> **执行主线：功能可用 → 原生 benchmark 小切片接通 → 强简单 baseline 与外部系统 → 按真实首断点修复 → 固定状态的机制对照 → 独立与长程确认。**
>
> 保留 v8 的动作可靠性、对象引用、同步维护、partial／unknown 恢复和 State–Attention 研究目标；采用 v9 的 benchmark 驱动执行顺序。native 环境阻断不再阻断可用 JSON 路径上的原生任务。生成本文件不代表开发、部署、合并或实验已经获得启动授权。

## 阅读导航

- [0. 来源、合并规则与分歧处理](#s0)
- [1. 历史基线与待解决问题](#s1)
- [2. 统一目标架构与职责](#s2)
- [3. 总体阶段与依赖关系](#s3)
- [4. Benchmark 选型与证据覆盖](#s4)
- [5. 原生切片、曝光与抽样](#s5)
- [6. Baseline 矩阵与实现风险](#s6)
- [7. U0：资源、身份与环境冻结](#s7)
- [8. U1：功能接通与薄适配](#s8)
- [9. U2：第一轮公平对照](#s9)
- [10. U3：真实首断点驱动的条件开发](#s10)
- [11. U4：呈现、Attention、更新 U 与同计算消融](#s11)
- [12. U5：独立确认、自然长程与第二模型](#s12)
- [13. 评价、信息权限与统计](#s13)
- [14. 成本、缓存与连续账本](#s14)
- [15. 代码、配置、Git 与复现组织](#s15)
- [16. 分层门槛及 Go／Pivot／Stop](#s16)
- [17. 推荐执行批次与交付检查表](#s17)
- [18. U6：总体收口、论文与 Product 边界](#s18)
- [附录 A. 原计划逐节映射](#appendix-a)
- [附录 B. 最小清单与结果模板](#appendix-b)
- [附录 C. 尚待实际核对的事项](#appendix-c)
- [附录 D. v9 保留的来源入口](#appendix-d)

<a id="s0"></a>
## 0. 来源、合并规则与分歧处理

### 0.1 本文是什么

这是两份已提供 Markdown 的**统一执行稿**，不是一次新的文献检索、仓库审计或实验报告。

- **V8**：`MILAI_DEVELOPMENT_EXPERIMENT_PLAN_20260928_v8.0.md`，动作可靠性、生命周期与长程研究工作。
- **V9**：`MILAI_BENCHMARK_FUNCTIONAL_COMPARISON_PLAN_20260928_v9.0.md`，benchmark 选型、功能适配、强对照与公平评价。
- 下文的 `[V8 §n]`、`[V9 §n]` 指原文相应章节；`[S01]`—`[S22]` 沿用 V9 的来源编号，见附录 D。
- 原文中的 GitHub 状态、数据规模、实现说明和服务配置均按其记载保留，**不表示本次重新核实了远端最新状态**。正式执行前由 U0 复核。
- U0—U6 是合并后的工作包编号，**不是新算法、实验臂或新增模型**。原 D／E／B／Stage 编号全部映射到附录 A，不覆盖旧记录。

原始文件的字节身份：

| 来源 | 行数 | UTF-8 字节 | SHA-256 |
|---|---:|---:|---|
| V8 | 1,185 | 20,889 | `f5d5dcdbfbb25ee3f16ba4ebe3c8bf1aad61b1d047e6aa22b86b8c26eda34f32` |
| V9 | 609 | 37,523 | `dbaf2a2835af161af627beb5b0e0f183da71b11553ee427f6cddaf867930dbfa` |

### 0.2 合并时明确采用的处理规则

两份计划不是完全相同的顺序表。下表记录统一执行所需的取舍；它们属于**本合并稿的编排决定**，不回写原文，也不将尚未验证的安排写成实验事实。

| 差异 | V8 的原安排 | V9 的原安排 | 合并后的执行规则 |
|---|---|---|---|
| 第一批顺序 | D0 → native 环境 → 协议比较 | 现有 JSON → 原生 smoke → baseline | **采用 V9 主线**。协议校准保留为条件分支，不阻断合法 JSON benchmark。[V8 §24；V9 §1.2、13] |
| 功能门槛 | 动作、维护与恢复稳定后进入自然长程 | 工程可信即可开始公开小样本，不要求模型全对 | 区分工程门槛、语义质量、长程副作用门槛。QA／安全工具任务可先比较；有风险的恢复与长程动作仍须专项验收。[V8 §13；V9 §1.3、8] |
| 自建脚本与公开任务 | 多种新诊断及自然积累 workload | 原生实例作为主要效果证据 | 公开任务优先；自建内容只用于旧失败复现、缺失能力及 partial／unknown 工程诊断，单列结果。[V8 §7—14；V9 §2.2、13] |
| named／required tool choice | 列为环境诊断可能方式；同时规定强制调用不能作主成绩 | 不要求 native 作为前置 | named／required 仅是**受约束能力诊断**，不得替代自动动作选择的 native 主对照。[V8 §6.2、7.4] |
| 对象引用适配 | free-text 对 typed ref 比较 | 原生工具 schema 不改 | 原生主表保留原工具；typed-ref 用明确标识的扩展比较，后续 memory 对照共同获得相同接口。[V8 §8—9；V9 §7 B2] |
| 同步 writer | direct 持续漏存才研究 | 部分 benchmark 原生要求 episode-end write | 原生 boundary 摄入不等于自主维护创新。direct／subtask 比较单列，不能把写入节奏差当纯 retrieval 差。[V8 §10—11；V9 §4.3] |
| Attention 触发 | all／query 不足后运行 | 除容量外，原生 scope／更新任务也可出现真实缺口 | 容量、实际取材遗漏或范围冲突均可构成研究依据；不强制 selector、不人为造无意义噪声。[V8 §15—17；V9 §8 Stage C] |
| 第二模型时机 | 协议、writer 或 Attention 有正信号后可提前确认 | 早期诊断或独立确认均可 | 允许单独授权的小型诊断，不把“所有任务先满分”设为前置；默认不下载或部署新模型。[V8 §18；V9 §8 Stage D] |
| 失败后的覆盖 | 停止不成立的复杂化与长程扩展 | 正常答错不取消其余预定安全任务 | **停止修改／晋升，不等于停止采集所有独立证据**。泄漏、越权、身份污染和系统性评估错误才阻断受影响执行。[V8 §22；V9 §11.4] |

### 0.3 来源不足的事项如何处理

原文没有提供实际 subset IDs、所有外部依赖的锁定版本、可用 native 服务和新实验的总预算。本文不补造这些信息。相关字段保持“执行前核对”，见附录 C。

本稿保留原文建议规模，但它们不是统计功效保证、已冻结命令或必须一次执行完的任务量。新服务、下载、收费接口、真实外部副作用和 Git 合并仍须明确授权。

<a id="s1"></a>
## 1. 历史基线与待解决问题

**依据：[V8 §0—2、5；V9 §1]。**

### 1.1 两份计划共同引用的 v7 基线

| 项目 | 原文记载 |
|---|---|
| 总体报告提交 | `77dfc2f43f2307bb649cdbee9d62a97e5863fac0` |
| 实际 E1 源码／输入提交 | `2f30c14c5e7ea82db2b0a962d3636e14de5f2391` |
| runtime/source A | `37d48577bdff582f74faf2f5e663b359885350ec` |
| PR | #71 为草稿、未合并；依赖 #70 |
| 可用研究配方 | JSON-action / B0 / strict / retained / current_request / compact_v6 / host_direct |
| Host | Qwen3.6-35B-A3B-FP8；temperature=0；thinking=false；max output=4096；capacity=65536 |
| Embedding | bge-m3，1024 维 |
| native | 环境未开启自动工具解析；`BLOCKED_ENVIRONMENT`，协议优劣 `INCONCLUSIVE` |
| 已运行切片 | 六种合成结构、两个预定重复，共12条轨迹、92/92任务义务 |
| 实际操作 | 8 CREATE、2同ID UPDATE、2 reserve-and-label、2 live lookup |
| 研究／Product | `NOT_ACHIEVED`／`NO_GO` |

12条轨迹不是12个独立任务结构，92条义务不是92个独立样本。当前配方可用，不等于 compact 已被证明优于 full，或 State–Attention 已产生收益。不得将本次合并视为晋升默认配置。

### 1.2 必须继续保留的失败链

| 失败链 | 首要待查问题 | 禁止的替代解释 |
|---|---|---|
| 明确保存 → 无 CREATE → 声称已保存 | 意图识别／动作选择 | 未进入 Store 时不能归因于数据库丢写 |
| 完整业务 key → 被改词形 → 错误执行 | 参数构造与对象引用 | 不能自动补正 key 后宣称模型成功 |
| 问当前预约 → 只查 memory → 未 live lookup | 工具选择、上游形成和世界状态分工 | 空 memory 不证明外部世界不存在结果 |
| 上游漏存 → partial 操作未发生 | 完整链依赖与专项恢复 | 未激活不等于通过，也不等于恢复能力已被否定 |
| 当前记录与旧 transcript 同时出现 → 取错版本 | 当前／历史消费 | 不以“最新永远优先”修复历史问题 |
| full/compact 首响应差异不稳定 | 呈现与 Host 波动的竞争解释 | 提案成功不等于真实持久化成功 |

旧失败、旧停止决定和旧评分不因新 smoke 通过而注销。诊断必须定位首个有证据的断点，再判断是否需要修代码。

### 1.3 统一研究问题

| 问题 | 优先证据 | 可触发开发 |
|---|---|---|
| 形成、更新和记忆是否改善真实行动？ | MERIT；随后 MemoryArena | 写入责任、任务接口、实际执行 |
| 当前／历史、scope、正确个性化如何选择？ | MemSyco；必要时 STALE | 呈现或 State 驱动的取材 |
| JSON／native／thinking 是否影响操作？ | 同内容同权限的协议诊断 | 模型适配，不重写 MemoryService |
| exact-key／对象身份能否可靠传递？ | 原生工具错误＋扩展对象实验 | 薄对象引用适配 |
| partial／unknown 后能否安全续接？ | 现有应用环境专项诊断 | 实际结果、操作日志与恢复 |
| 增量维护、大历史下何时需要选择？ | MemoryAgentBench；原生长期任务 | all/query 及有条件的 A/U |
| State–Attention 是否有独立净价值？ | 同bank／前态／writer／budget对照 | 有证据才保留复杂选择器 |

<a id="s2"></a>
## 2. 统一目标架构与职责

**依据：[V8 §3、8、10、16、26；V9 §4、12]。**

### 2.1 保留成熟底座，只增加必要的薄适配

继续复用 LangGraph ReAct、LangMem ordinary memory、strict CRUD、exact read、现有 Store／checkpoint／application world、RequestContext／Renderer／Router、operation audit、离线 evaluator 和连续计账。

```text
原生 benchmark 的合法输入 / 环境反馈
                    │
                    ▼
       薄 adapter：来源、角色、时间、接口转换
                    │
      ┌─────────────┴─────────────┐
      ▼                           ▼
一个逻辑 MemoryService       当前 Working State
来源 / 当前理解 / CRUD       目标、scope、依据、待办
      └─────────────┬─────────────┘
                    ▼
        现有 RequestContext / Renderer
           all → 普通检索 → 必要时选择
                    ▼
              同一 ReAct Host
                    ▼
       原生工具 / 现有执行器 / 实际回执
                    │
                    └──→ 当前任务与合法记忆变化

离线侧：原生 scorer + 补充诊断 + 成本与证据清单
         不向 runtime 提供 rubric、gold 或未来事件
```

这是一组职责，不要求新建同名平台、数据库或服务。不同 benchmark 的业务工具和评分由其原生实现负责。

### 2.2 一个 MemoryService，不是一个大摘要

direct Host、原生 boundary writer、可选同步子任务使用相同逻辑存储入口、namespace、目标身份、CRUD、search/read 和审计。不同实验臂拥有独立的实际存储实例，不能共享可变语义状态。

多个事项可以分别维护；禁止多个 writer 无明确所有权地独立改写同一持久认识。可选子任务是同一 MemoryService 的一种调用策略，不是第二份长期真相。

### 2.3 Working State 保留有依据的局部工作内容

允许包含：

```text
TaskState
  goal / scope / current constraints
  active matters
  working values with provenance
  open questions
  pending actions
  recent actual receipts
```

每个工作值说明来源、适用范围、临时性及刷新条件。允许多个局部 State 对应任务、子任务、业务对象或 open issue；不要复制整份用户画像，也不要独立维护第二套长期业务数据库。

### 2.4 持久记忆与当前世界分工

Memory 可保留偏好、计划、已发生事件、历史工具观察及最后已知状态。当前世界由适用的实际查询或足够新鲜的真实回执确认；不可查询时保留“最后已知／未知”，不自动把旧文本升级成实时真相。

用户计划、模型提案、已执行动作、工具回执和最终答复分开记录。一个 CREATE 回执证明写入发生，不证明其全部语义正确；一项业务完成也不证明所有相关记忆已维护。

### 2.5 完整 CRUD 与退出层次

CREATE 用于新事项；UPDATE 用于同一事项变化；READ 用于当前任务取材；DELETE／撤回依照目标和原有权限执行；无变化时允许 NO_CHANGE。

“当前不相关”不等于删除，“本次临时覆盖”不等于修改全局偏好，“删除当前记录”不自动意味着历史事件已擦除。涉及遗忘范围与安全删除的测试遵守原合同，不以问答成功代替清理验收。

<a id="s3"></a>
## 3. 总体阶段与依赖关系

**依据：[V8 §4、13、24；V9 执行摘要、§7—8、13]；阶段编排按第0节合并规则执行。**

| 合并阶段 | 工作 | 进入条件 | 主要产物 |
|---|---|---|---|
| **U0** | 来源、版本、曝光、环境与失败冻结 | 规划进入实际执行授权 | source/exposure manifest，基线与服务能力记录 |
| **U1** | 最小功能和原生 adapter；smoke | U0完成，资源可合法使用 | MemSyco＋MERIT原生可评分链与费用 |
| **U2** | 小样本强简单／外部对照 | 工程可信，不要求模型全对 | 第一张质量—成本主表与首断点 |
| **U3** | 协议、对象、writer、恢复的必要修复 | 存在对应实际问题或能力缺口 | 单变量实现、对照、回滚记录 |
| **U4** | 呈现、A/U、同计算机制分析 | 正信号或真实取材／更新瓶颈 | 固定bank/前态结果、边界与消融 |
| **U5** | 独立任务、第二模型、自然长程 | 相应路径可安全运行，方法已冻结 | 新来源组结果、跨任务/模型与长程证据 |
| **U6** | 全范围收口 | 每一已授权分支有结果或明确未运行原因 | 总报告、失败、费用、复现及论文决定 |

```text
U0 复核冻结
  │
  ▼
U1 原生小切片接通（JSON可先行）
  │
  ▼
U2 强简单基线 + 外部系统的小样本比较
  ├── 工程／语义首断点 ──→ U3 对应的最小修复 ──→ 冻结后复核
  ├── 正信号／选择瓶颈 ──→ U4 固定状态机制对照
  └── 方法可确认 ──────→ U5 独立任务／模型／长程
                                │
所有完成、否定、阻断、未触发项 ───┴──→ U6 统一收口

native环境比较、对象扩展、同步writer、partial/unknown
均为独立分支，不是所有原生benchmark的串行硬前置。
```

第二模型可以提前用于某个协议／模型问题的有限诊断。缺少 native 或 partial 场景，不阻断不依赖它们的纯 QA 比较；同时不能用 QA 通过宣称这些能力已验证。

<a id="s4"></a>
## 4. Benchmark 选型与证据覆盖

**依据：[V9 §2；S02—S18]。下列资源说明继承 V9 的检索记录，本次未重新联网核验。**

### 4.1 首批与后续优先级

| Benchmark | 原文记录的资源/规模 | 核心证据 | 安排与限制 |
|---|---|---|---|
| **MERIT** | 三业务域、SQLite worlds、原生tools/checkers、arc生成及cost；[S02—S04] | 历史记忆如何改变真实行动；更新事实 | 第一批。换seed不等于新任务族；保留完整arc和实际世界 |
| **MemSyco-Bench** | 五任务、1,550样本、统一runner和baseline；[S05—S07] | scope、新旧偏好、正确个性化、证据冲突 | 第一批取三个互补任务；主要是回答/决策，不证明副作用恢复 |
| **MemoryAgentBench** | 增量摄入、一context多问题，发布6k/32k等配置；[S08—S10] | conflict resolution、维护、跨段取材 | 第二批先FactConsolidation sh/mh；题目数与context数分开 |
| **MemoryArena** | preview代码；travel 270完整groups，本地CSV工具；[S11—S13] | 相互依赖的多session规划与工具使用 | 独立Agent确认。航班数据另取，不缩减环境冒充原生 |
| **LongMemEval** | cleaned数据、每版本500问、QA/retrieval evaluator；[S14] | 更新、时间、跨session推理、拒答 | 按claim补充；S历史通常约115k，oracle只作诊断 |
| **STALE** | 400场景、1,200 probes、两类隐式冲突及CUPMem；[S15—S16] | 隐式失效、错误前提抵抗、行为适应 | 特定问题出现再接；同场景三问关联，读取隔离 |
| **LongMemEval-V2** | 451问、两领域、多模态轨迹、Insert/Query与固定reader；[S17—S18] | 动态状态、流程、gotchas、前提、读取延迟 | 后期。原文记载最高115M token规模，不是首批任务；不删图片冒充完整结果 |

LoCoMo 作为文献常用补充保留，但本阶段不加入强制实现，避免不断增加同质 QA 榜单。

### 4.2 首批 MemSyco 的三类任务

| 原生任务 | V9记录的样本数 | 用途 |
|---|---:|---|
| Contextual Scope Control | 300 | 局部要求是否被错误推广 |
| Valid Memory Selection | 350 | 是否选择当前适用偏好，避免旧状态污染 |
| Personalized Memory Use | 300 | 是否真正使用有效记忆，防止靠少用记忆降低误用 |

沿用 `evaluation/run_task.py`、原task prompt及judge rubric。gold memory、reference evaluation 和任务标签只在原生允许的范围使用，不得作为辅助答案进入memory build或reader。[S05—S07]

### 4.3 MemoryAgentBench 的起始配置

先用官方 `Factconsolidation_sh_6k`、`Factconsolidation_mh_6k`，再到32k对应配置。完整context摄入后按原生查询组织答题；`max_test_samples=1` 代表一个长context，不代表一题。保留原chunk语义及如 `substring_exact_match` 的原指标，不添加有利答案清洗。[S08—S10]

上游6k/32k/64k是配置名称，不等于本项目tokenizer的精确输入计数；最终请求还须计入目录、模板和输出空间。

### 4.4 原生行动与专项恢复的边界

MERIT、MemoryArena用于原生行动结果；显式遗忘、部分副作用、未知结果与崩溃恢复未必被这些发布任务直接覆盖。保留 U3-R 的小型工程诊断，但其数据、故障注入和分数单列，不能混入官方benchmark成绩。[V9 §2.2；V8 §12]

<a id="s5"></a>
## 5. 原生切片、曝光与抽样

**依据：[V9 §3、13；V8 §7、9、14、18]。所有数量为建议规模，不是已冻结ID或统计保证。**

### 5.1 按阶段选择完整实例

| 数据 | 功能 smoke | 首次比较 | 独立确认建议 |
|---|---|---|---|
| MemSyco三任务 | 每类2题，共6题 | 每类20题，共60题 | 另取每类30题，共90题 |
| MERIT | 3域 × easy/hard × 1 arc＝6 arcs | 3域 × easy/hard × 3 arcs＝18 arcs | 3域 × 3难度 × 4 arcs＝36 arcs |
| MemoryAgentBench | sh/mh 6k各1完整context，各最多10原问题 | sh/mh 32k完整context，各最多25原问题 | 依据官方不同context/长度扩展，注明同源重叠 |
| MemoryArena travel | 2完整groups | 6完整groups | 另取12完整groups |
| STALE（条件） | Type I/II各1场景，各三问 | Type I/II各6场景，共36 probes | 按成本与claim必要性扩大 |

MERIT每arc的episode数来自冻结上游配置；原生五episode arc必须完整保留。MemoryArena保留组内全部人物及依赖顺序。数据不足则减少数量并说明，不补造条目。

### 5.2 来源组隔离

优先遵守官方split；没有官方split时称内部smoke/dev/confirmation，不自称官方测试集。先整理项目全部历史曝光：相同历史、人物、arc、context、group及模板衍生项尽可能组级隔离。

类别内采用事前固定规则，例如：

```text
SHA256(dataset_revision || source_group_id || selection_seed)
```

按该值排序选择。可用类别、来源、模态、历史长度等非结果元数据；不可用MiLAi得分、gold evidence或答案选择有利样本。

### 5.3 少取实例，不剪掉原始任务

完整历史昂贵时先减少实例数，不只保留答案附近片段。smoke可预先选择短历史条件，但应称长度受限功能子集；正式结果按发布长度分层，不以短子集代表整个benchmark。

原文、角色、时间、顺序、工具schema和原生评分不变。不为触发State添加“务必保存／建立State”，不把原问题改写成更容易维护的命令。

### 5.4 自建诊断的限定用途

V8所列协议8–10新诊断、对象引用反例、形成/no-write、partial/unknown和自然积累全部保留其**问题覆盖**。合并后优先利用原生任务暴露的对应失败；仅在原生资源缺少该能力时新增最小自建诊断。

自建脚本、旧曝光回归、原生dev和独立confirmation四类结果分别记录。新金额或新UUID不自动意味着新结构；同一前缀重复调用不是独立样本。

<a id="s6"></a>
## 6. Baseline 矩阵与实现风险

**依据：[V9 §5—6；V8 §7、9、11、17]。**

### 6.1 强简单基线

| 方法 | 定义与要求 | 排除的解释 |
|---|---|---|
| NoMemory／NoRetrieval | 无跨session语义记忆，保留合法当前观察和共有安全执行底座 | 验证真实历史依赖，而非假设无记忆一定为零 |
| FullHistory／RawDialogue | 全部合法历史；无法容纳须报告或另列窗口 | 复杂结构并无必要 |
| SlidingWindow＋真实LLM摘要 | 明确窗口、摘要模型、更新节奏 | 只是上下文长度或压缩的收益 |
| StrongRawRAG | 真BM25＋同一dense embedding，可加固定可用reranker | 更好原文检索已经足够 |
| OrdinaryMemory | 相同Host、strict CRUD与底座，不开研究性State–Attention | 效果来自基本工具和运行器 |
| MiLAi candidate | 明确启用与实际触发模块 | 不将代码存在当作机制运行 |

无真实reranker就称hybrid retrieval，不贴重排标签。若OrdinaryMemory与当前MiLAi配方没有实际差异，合并同一臂，不为保留候选列强制加selector。

第一张有信息量的主表以“完整历史／强原文RAG／真实摘要／ordinary／候选／一个外部系统”为上限组织；并非每个benchmark必须机械拥有全部六列。

### 6.2 外部系统与近邻

| Baseline | 接入顺序 | 核心边界 |
|---|---|---|
| Mem0／benchmark内MemZero | 第一项 | vendored MemZero与最新OSS分开；锁定真实write/update路径，托管结果另列。[S06,S19] |
| A-MEM | 第二项候选 | 保留笔记、链接、演化的实际能力，不能只移植弱reader仍称原生。[S06,S20] |
| SimpleMem text | 与A-MEM二选一先做 | 锁定text路径、规划/反思；不在确认集运行EvolveMem自演化。[S21] |
| CUPMem | 使用STALE时补 | 作为当前状态裁决、更新传播的近邻；不任意拆弱writer/reader。[S15] |
| HiMem | 机制确认阶段 | Episode/Note与重整；不提前扩全部基础设施。[S22] |
| AgentRunbook-R/C | 进入LongMemEval-V2时 | 优先R；C有额外coding agent依赖，单独资源授权和身份。[S17—S18] |
| MemZero+DynPartition／SelfReCheck | A出现信号后 | 固定MemZero bank的读取控制对照，不冒称MiLAi同bank消融。[S06] |

MemSyco可从RawDialogue、NaiveRAG、MemZero和MiLAi起步，再补StrongRawRAG。MERIT保留真实LLMSummary、EmbeddingRAG及StructuredFacts作为原生参照；结构化正则提取的领域优势需披露。

### 6.3 必须保留的源码风险提示

原文核查记载：MERIT starter `KeywordRAG` 是关键词集合交集，`RollingSummary` 只是 `transcript[:800]`，`FullReplay` 超过字符预算保留尾部，`StructuredFacts` 使用领域正则。正式强对照不能把这些占位行为当完整BM25、真实摘要或无限full history。[S04]

`memory_llm.py` 提供EmbeddingRAG、LLMSummary、LLMFacts及计量；但LLMSummary是否真正联合旧摘要重写，要审查完整调用链。需要改进简单摘要时另命名，不静默修改原生实现后保留原名。[S03]

MemSyco的MemZero、A-MEM、NaiveRAG有vendor身份；SimpleMem仓库包含text、多模态和演化入口。以执行时实际类、配置、源码和日志定义baseline，不以项目名称替代方法合同。

### 6.4 系统比较与组件比较分开

后端对照用同一reader；外部系统自己规划、写入和回答时，另标端到端系统比较。特殊encoder、训练checkpoint、原生reader等必要能力保留并列为差异，不强行拆成与MiLAi相同后仍声称原生复现。

官方能力尚未安装或服务费用不能计量时标 `NOT_RUN`／系统参考，不用README分数替代本地实验。

<a id="s7"></a>
## 7. U0：资源、身份与环境冻结

**映射：[V8 D0；V9 B0]。模型调用：0。**

### 7.1 工作内容

在新执行授权下，只读核对项目实际HEAD、PR依赖、已有adapter、原始计划及旧失败；以真实文件和资产为依据，不因旧报告写“已支持MERIT”就假定当前分支兼容。

冻结以下身份：

| 类别 | 必须记录 |
|---|---|
| 项目 | source commit、配置、实际默认/候选开关、源码与锁文件hash |
| 上游 | repo commit、dataset revision、LICENSE、scorer及必要环境资产hash |
| 模型 | 实际服务、模型资产可验证范围、tokenizer、chat template、tool parser、thinking和容量 |
| 执行 | 目录、owner/namespace、Store/checkpoint/world、顺序、预算起点、缓存身份 |
| 评估 | 原生split、subset IDs、来源组、曝光清单、附加诊断与原生主分数边界 |

模型名称不是完整权重校验。无法独立取得的revision或成本字段记unknown，不伪装成核实。

### 7.2 产物与验收

最小交付为source manifest、exposure registry、失败链表、环境说明和冻结执行顺序。复用现有清单格式，不创建新平台。

验收：新旧结果可以准确归属；原文与gold分离；所有计划实例知道来源与依赖；本阶段未发生模型或业务调用。资料不足则标对应分支阻断，不推断它的算法结果。

<a id="s8"></a>
## 8. U1：功能接通与薄适配

**映射：[V9 §4、B1—B4、Stage A；V8 §3、C1中相关工程边界]。**

### 8.1 先完成的功能，不要求先取得满分

| 功能 | 最小可用合同 |
|---|---|
| 历史摄入 | 完整合法输入、顺序、角色、时间及来源ID；目标问题/gold不提前参与建库 |
| CRUD | 正确owner、真实目标存在性、实际新增/更新/删除；NO_CHANGE合法 |
| 后续使用 | 续接只取得原协议允许的记录与历史；审计日志不能成为隐蔽档案 |
| 有界读取 | all/query可执行；按实际tokenizer计完整目录、模板、输入与输出预留 |
| 工具行动 | 原生工具与world实际运行；不将assistant文本当副作用，不自动补key |
| 输出与评分 | 原生scorer能够读取；task fail、parse/capacity/environment/scorer fail分开 |
| 计账 | writer、Host、selector、embedding、judge、失败、缓存与复用可追溯 |

先跑原生dry-run、可控fake或零模型prepare；这些只验证harness。随后运行冻结原题smoke，至少一条合适原生参考路径与MiLAi路径。

### 8.2 MemSyco adapter

复用官方 `evaluation/run_task.py`、各任务prompt、judge rubric和baseline context入口。[S06—S07]

- 原历史交给memory build，不把未来问答提前写入。
- 返回该方法真正形成/检索到的材料，不注入gold memory或reference evaluation。
- 建库按合法历史身份复用，owner隔离；相同文本不同owner不能串库。
- `--limit` 用于初始接线；正式切片使用冻结ID，不能长期只取前N行。
- 首批三个任务各2题，分别检查应采用、不适用和新旧选择，不将全部正确率当唯一功能门槛。

### 8.3 MERIT adapter

先检查现有项目适配与固定上游版本差异，复用原SQLite world、tools、arc生成、checker、指标和成本接口。[S02—S04]

- 一条arc内的episode及依赖保持，未来arc内容不提前交Host。
- 业务参数、前提、副作用和失败分支原样执行；首轮不引入typed-ref扩展。
- 记录NoMemory leak check；不可只因设计上应依赖历史，就假定无记忆必为零。
- `pre_satisfied`、world当前状态、任务完成和实际记忆形成分开。
- 写入使用episode-end hook、turn-end或主动CRUD必须写入方法身份。
- 原生接口可直接适配：

```python
write(episode_id: str, transcript: str) -> None
read(current_context: str, budget_chars: int) -> str
```

这只是已知接口示意，不是本次新增的可执行代码。

### 8.4 MemoryAgentBench adapter

优先CR sh/mh 6k，再32k。完整context一次摄入、多个问题复用，遵守原chunk与查询流程。[S08—S10]

若原生不允许测试问答持续学习，所有问题从相同建库快照独立开始，不能把前题生成答案作为后题记忆。沿用原生分数；最大问题数限制仅用于预先声明的子集，不能覆盖原context或伪称全量成绩。

### 8.5 后续接口

MemoryArena保留agent/env/memory职责和完整group。航班等必需CSV缺失时标环境阻断，不能用手写小表代替。[S11—S13]

LongMemEval-V2采用原生 `insert(trajectory)`／`query(query, query_image=None)`，返回规定context items给固定reader；删除图像或改reader需另列扩展，不称原生完整结果。[S17—S18]

### 8.6 后端与自主Agent能力不可互相替代

| 模式 | 记忆形成责任 | 可主张什么 |
|---|---|---|
| 后端评测 | harness按原生时机提交完整历史或episode | 后端形成、更新、检索与共同reader使用能力 |
| 自主Agent评测 | Host从用户输入与真实反馈中选择动作 | 意图识别、工具执行与持续维护的端到端能力 |
| 固定轨迹离线组件对照 | 各方法消费同一已记录合法轨迹 | 排除writer输入分叉，定位memory机制 |

自动 `write` 不证明Agent自主识别了“请记住”。对话历史也不能作为新的实时用户指令逐条重演，造成原本不允许的业务调用。

### 8.7 U1完成与回退

完成条件是无gold泄漏、无伪造工具、无错误scope、无静默截断且结果/费用可核验。正常模型答错保留并继续剩余安全任务。

adapter缺陷先修薄映射；行为改变独立提交。回退到上一可执行配方，不覆盖旧run；环境缺失只阻断依赖它的benchmark。

<a id="s9"></a>
## 9. U2：第一轮公平对照

**映射：[V9 Stage B、B5、§13批次B；V8的共同信息/执行原则]。**

### 9.1 第一张主表

功能接通后，先运行MemSyco 60题与MERIT 18完整arcs。按各benchmark适配实际组织：

- 完整历史／RawDialogue参考；
- 真BM25+dense的原文检索；
- 真实LLM摘要；
- ordinary记忆与有真实区别的MiLAi候选；
- 第一项外部系统Mem0／MemZero。

不用一次安装所有项目。A-MEM／SimpleMem text先择一作为第二项外部系统，待首表可运行后再加入。

### 9.2 运行冻结

执行中不调整prompt、参数、工具、数据、阈值、写入节奏或scorer。每个方法从相同合法初始条件开始，之后允许自己的真实动作和记忆内容不同。

若发现会污染结论的bug，标明受影响范围、新方法/执行身份和重跑范围；不能只重跑候选失败题、不重跑受相同缺陷影响的baseline。

### 9.3 应交付的结果

每个benchmark单独给出原生分数、分类/长度/依赖层结果、实际分母、完整arc/group成功、成本、未运行和失败首断点。不得合并成没有明确定义的“Agent Memory总准确率”。

需要排查时使用固定bank/轨迹组件诊断，但不要把它代替在线方法成绩。

### 9.4 本轮不预设候选必须胜出

若简单方法持平或更好，先查收益来源与失效范围，停止相应复杂模块的优越性主张；不为挽救原假设更换任务或加噪声。若新问题属于动作、对象或写入，进入U3对应分支，而不是统一归因于Memory Store。

<a id="s10"></a>
## 10. U3：真实首断点驱动的条件开发

**映射：[V8 D1/E1、D2/E2、D3/E3、E4；V9 B4和Stage E]。**

U3不是必须一次开发完的功能清单。各分支有独立问题、权限、源码身份和验收。原生benchmark可以继续使用已验证JSON路径；新增能力不得悄悄改变原生任务。

### 10.1 U3-P：协议与推理模式

**启动依据：**需要解释漏工具、协议接线差异，或正式完成未定的native对照。现成JSON可运行时，不将其作为整个研究的硬前置。

**先做零模型核对：**实际服务flags、模型资产可验证范围、tokenizer/template、parser、请求编码、容量、共同投影、同步执行与delivery。V7已完成的共同接线不重复从零开发。

**环境策略：**若获授权，可使用相同权重、dtype、template、context、输出限制等资产的隔离服务，只改变native解析所需配置；不直接改共享服务后混用前后结果。无法建立则保持 `BLOCKED_ENVIRONMENT`。

**实验条件：**

| 条件 | 用途 |
|---|---|
| J0：JSON-action、thinking=false | 当前可用基线 |
| N0：native自动工具选择、thinking=false | 主要协议对照 |
| J1/N1：对应协议、thinking=true | 另行冻结的推理模式变量，不与第一次协议切换混合 |
| named/required tool choice | 只诊断已被要求调用时的参数构造，不计普通自主Agent主成绩 |

目录表达、协议标记、call ID和token可以不同；合法材料、权限、业务工具语义、执行器、输出评价和资源上限对齐。不能用强制tool_choice替native自动选择结论。

**诊断覆盖：**保存但不执行业务、保存加当前回答、更新保持、实时lookup、exact-key、当前/历史、只读、引文、临时要求、一回合两项操作、业务后维护。优先旧失败与原生实例；V8建议的8–10新诊断只在缺覆盖时补，单列。

**验收：**完整执行，不只看首响应。分开动作选择、参数、执行、Store、回答、后续使用和总成本。native只在所需动作改善且no-write/参数不明显退化时进入后续候选；没有差异就停止该分支，不加保存措辞挑赢家。

### 10.2 U3-O：精确对象与业务参数

**启动依据：**真实key漂移、对象混淆或不得不反复抄写已取得身份。

建议的轻量对象结构：

```text
BusinessObjectRef
  ref
  kind
  display_name
  exact_external_key
  source_receipt
```

它是已取得对象的映射，不是新数据库。模型选择ref，执行边界解析准确外部key；没有真实对象时不得生成gold ref，多候选需查询/消歧，禁止模糊自动修正。

**两类比较不混淆：**

1. 自由文本T0 vs typed-ref T1，是明确的**业务接口扩展实验**；共同世界和语义能力，接口本身就是变量。
2. 后续MiLAi vs其他memory方法若采用T1，所有臂共同获得T1，不能只为候选补对参数。

原生benchmark主分数保留原工具。修改接口后的成绩另名标注，不覆盖官方设置。

**反例覆盖：**复数key、标点敏感key、数字代码、相似对象、更新后的对象、缺ref需lookup、历史ref失效、不同owner同名。记录target selection、argument exactness、wrong-object side effect、澄清、lookup数、任务和成本。

只有准确性改善且不增加选错对象时保留。无收益回退原接口，不对失败样本建词形修正规则。

### 10.3 U3-W：有限同步记忆子任务

**启动依据：**在可用协议和清楚输入下，direct仍出现真实漏存/漏维护；仅为backend实现官方episode-end hook不视为该算法实验。

沿用同一MemoryService、Store、strict CRUD与ID。一次有界子任务取得当前真实新观察、相关旧记录、实际回执、owner/scope，提出CREATE/UPDATE/DELETE/NO_CHANGE。不增加另一套持续事实库，不给gold、未来任务或额外档案。

**触发必须可解释：**可由可信应用save-command或Host提出的维护请求触发；不从scorer注入must-save，也不按关键词强制写入。若Host连长期意图都未识别，就应把“未触发”如实记为能力缺口，不能声称子任务自动解决了它。

| 对照 | 定义 |
|---|---|
| D | Host direct memory tools |
| M | 同一服务上的bounded maintenance subtask |

如M拥有可信应用意图标签，D也须在同一应用条件下获得该信息；另报告没有显式标签的开放对话，不混用。

**正例：**明确保存/更新/删除、实际结果改变长期计划、两个独立事项。**负例：**引用命令、临时格式、只读、未采纳建议、无未来价值的一次性工具结果。

评分包括必要写入、误存、目标、保持、重复事项、后续使用和全部额外调用。direct足够则不增加子任务；M只增加成本或误存则回退，不叠加新的correction层。

### 10.4 U3-R：partial／unknown／恢复

**启动依据：**需要验证真实行动生命周期，或原生任务已经出现部分/未知结果。它不是无副作用QA的前置条件，也不能被QA成功代替。

场景必须实际执行：例如预约创建成功而标签失败；或请求可能抵达外部系统但本地结果未知。优先现有ApplicationWorld和操作日志；缺少unknown表达时只补最小deterministic fixture，并明确是可控诊断，不声称外部网络exactly-once保证。

```text
记录本次操作意图
→ 执行真实工具
→ 记录成功 / partial / unknown
→ 更新本次任务的未完成部分
→ 关闭并重新打开进程
→ 查询实际世界
→ 只继续未完成步骤
```

验收至少包括：真实side effect与ID保留、partial不报全成功、未知不盲目重复执行、不重做已成功业务、owner隔离、需要长期保留的状态获得真实维护、恢复后任务正确。

若上游形成失败导致partial未发生，完整链记失败，partial记 `NOT_ACTIVATED`。可以从单独合法前态做组件恢复诊断，但不将其成功补进原端到端链。

删除当前记录、撤回错误理解、历史可读性与授权全范围遗忘分别按原合同测试；不能用delete工具返回成功证明全部历史已清除。

### 10.5 U3的退出方式

每次只选择与证据对应的最小修复，冻结后做旧失败及反例回归，再用未用于该修复的实例验证。无新证据不继续添加prompt变体。

结束该分支可以是“修复通过”“局部有效”“无净收益”“环境阻断”或“问题未定”；不要求所有分支最终都被开发或证明有益。

<a id="s11"></a>
## 11. U4：呈现、Attention、更新 U 与同计算消融

**映射：[V8 E5、D5/E6；V9 Stage C、§10、批次C]。**

### 11.1 进入依据

满足以下至少一项：候选相对强简单方法出现有解释价值的质量/成本信号；原生长历史或scope任务暴露实际取材遗漏；更新候选过大或选择错误；在给定正常资源条件下all/query不再适用。

不因所有历史能放下就断言State无用，也不为了触发模块故意降低窗口、添加无意义噪声或强制调用。纯粹“代码已实现”不构成研究入口。

### 11.2 四个最关键对照

| 对照 | 固定条件 | 实际检验 |
|---|---|---|
| 呈现 | 同memory、候选、内容、writer和任务 | system/current_request的组合呈现；位置和carrier role若耦合，不能称纯位置因果 |
| 读取A | 同bank、writer、候选检索、reader、合法State信息和预算 | ordinary query、同State查询增强、显式State–Attention选择 |
| 更新U | 同前态、新观察、实际来源、CREATE权限及维护接口 | 全合法候选、普通检索候选、显式U；不将当前读焦点等同所有可更新对象 |
| 同计算替代 | 相同额外资源预算与合法信息 | 简单方法真正回看、rerank或多取候选能否获得同样收益 |

### 11.3 读取A的三个条件

```text
Q = ordinary query
W = query + deterministic working-state augmentation
A = query + State–Attention selection
```

显式State信息不能只给A；Q/W/A的bank与writer形成历史一致。候选生成固定后，选择与组装是被检验变量；另列端到端writer自然分叉后的结果。

A只能从合法候选选择材料，不产生新的事实。当前不适用的旧记录仍可能是核对历史范围的证据，不按“旧”机械删除。State值和其来源一起保留，避免自我确认式检索。

如果W已达到相同质量而更省，不保留额外A调用。若A有效，报告required coverage、current/history/scope、实际行动以及总成本，不能只报选中ID。

### 11.4 更新U的独立语义

更新候选来自新观察及相关旧事项，CREATE始终允许；空U不应禁止真正新事项创建。当前任务没读取的另一长期约定收到变更时，仍应维护。

全候选、普通检索U、显式U使用相同来源访问权和操作合同；必要时oracle U只用于定位目标选择上限，不能作为可部署低成本赢家。

原文V8默认不额外恢复U selector、V9允许条件性固定前态实验，合并执行为：**先测试普通检索候选；确有更新选择问题才运行独立U诊断**。

### 11.5 结果判断

- 独立质量改善且成本可解释：保留机制并进入确认。
- 质量不下降且生命周期成本明显更好：以预先定义的质量容忍范围审查，不把“不显著”当相同。
- Q/W足够或A/U只有额外成本：停用该复杂模块，保留可用系统及负面结果。
- 实际机制没有触发：报告未激活，不计算该机制收益，也不强制创造使用。
- 一个bank多问题、同一轨迹多episode均为关联观测，不当作独立概率相乘。

<a id="s12"></a>
## 12. U5：独立确认、自然长程与第二模型

**映射：[V8 D4、E5、M1；V9 Stage D、§3、批次D]。**

### 12.1 独立确认优先使用原生来源组

开发完成后冻结方法、prompt、writer、embedding/reranker、read budget、judge和顺序。使用之前未参与开发的history／arc／group／context；确认结果不能继续被拿来调参数后仍称未见。

优先MemoryArena完整group和另一个来源组的MERIT／MemSyco。LongMemEval、STALE、LongMemEval-V2依最终claim选，不以“更新的名字”取代已接通任务。

原生资源不够覆盖某个工程功能时，允许单列补充诊断；不得在主表里混用自造任务和原生分数。

### 12.2 自然长程负载

V8 §14建议保留为有条件的长程补充：2–3 owners，每owner 20–40 sessions、15–30个逐渐形成的独立事项。V8 §1也给出10–30事项的粗略范围；本合并稿采用其详细工作包的15–30建议，**不是已测规模或强制固定基数**。

内容自然包含稳定/限定偏好、计划、项目约定、notes、业务对象、历史变化、完成/失败动作、临时例外和第三方信息。发生真实CREATE/UPDATE/DELETE/NO_CHANGE及范围切换，不随机插入无任务意义文本来制造Attention优势。

优先使用原生多session任务承载；人工工作负载另列。缺少partial能力只限制依赖该副作用恢复的长程路径，不阻断其他可安全进行的原生QA研究。

### 12.3 all与普通query先成为强参照

all仍能容纳时保留为比较对象；触发阈值、完整请求容量和原生长度配置在执行前固定。all超容量则如实报告，不静默删正文。

先比较all与ordinary query的质量、required record coverage、scope、新旧使用、任务/行动和成本。query可解决时，停止额外选择器开发；但若all可容纳却存在真实scope冲突，也允许U4独立诊断，而不是机械以大小判断。

### 12.4 第二模型

V8给出的规模为6–10个代表脚本；在benchmark路径中按相应原生实例/组选择等价的小切片，实际单位与数量另冻。必须是不同模型家族，不把同权重另一量化当跨家族确认。

可在协议、writer或Attention出现清楚信号时提前触发，也可用于定位模型限制；不必等所有任务满分。新下载、部署、外部服务与费用先获授权。

保持任务、memory、CRUD、权限和评分一致。必要的模型/模板兼容修改登记为方法配置差异，不能第二模型单独调好prompt后声称零调整泛化。若第二模型缺资源，记NOT_RUN，不用第一模型重复次数补证。

<a id="s13"></a>
## 13. 评价、信息权限与统计

**依据：[V9 §4.3、8—10；V8 §7、12、19]。**

### 13.1 原生主分数与附加诊断分开

公开benchmark沿用原scorer和rubric，不能为了修复“隐藏要求”自行改官方任务分数。若发现评分/guide与实际world分支冲突，保存原口径、证据和明确修正说明，另行报告；不得悄悄重新定义成功。

自建回归继续采用已明确的义务层：current explicit、persistent、later use、diagnostic completeness；business与recovery按实际能力补充分层。diagnostic不是task-failing要求，runtime不读取任何rubric。

只在存在来源标注时报告retrieval recall/precision；没有gold evidence时记未知或人工诊断，不伪造精确指标。

### 13.2 七层操作链

| 层 | 需要检查 |
|---|---|
| 意图／动作选择 | 该行动是否提出，不该行动是否发生 |
| 参数 | 工具、准确目标、key、数量、scope和record ID |
| 执行 | 实际工具/Store/world发生了什么，是否partial/unknown |
| 持久结果 | 内容、同ID更新、保持、删除和owner |
| 当前回答 | 是否履行当前要求，是否虚称保存/执行 |
| 后续任务 | 实际持久内容被交付并用于新session，当前/历史范围正确 |
| 资源 | 全生命周期调用、tokens、缓存、观察、恢复和失败成本 |

用于定位的条件链：

```text
合法来源存在 → 实际接收 → 可复用内容形成 → 候选召回
→ 材料实际交付 → 正确采用 → 工具/回答 → 后续恢复与使用
```

这些比例相关，不能机械相乘估算任务成功概率。零记忆也可能靠完整历史答对；有记录或调用工具也不代表语义正确。

### 13.3 信息权限

**Archive-access**：所有方法可访问相同合法原始历史，RawRAG也能查同一档案；MiLAi不能独享audit日志。

**Retained-memory**：后续只使用各方法真正保存的内容。原文方法可以保留原文并计成本，不能禁止其保存而允许候选source store旁路。

原生benchmark的信息权限优先，改变条件另列扩展协议。在线不同方法的动作带来各自反馈，不强制共享候选才取得的观察；固定轨迹比较另标离线组件实验。

### 13.4 控制变量

固定或显式报告Host/reader、模型资产身份、tool protocol、thinking、temperature、seed支持、template、输出预算、embedding、chunk、候选数、最终材料token预算、外部工具、write cadence、缓存、并行度、judge和timeout。

算法专用encoder/reader可保留差异，但必须披露。共同预算不要求所有方法实际调用次数恰好一样；既报预算下质量，又报全部实际消耗，同计算消融另做。

### 13.5 FullContext和Oracle

V9记录LongMemEval-S通常约115k、STALE可达150k，部分MAB也超当前65536容量。[S08,S14,S16] 不把前/后64k或人工证据裁剪称FullContext。

可分别报告完整可容纳子集、明确SlidingWindow、原生oracle诊断和完整历史分批摄入的memory方法。长度过滤只支持该子集结论；oracle只给接线/reader上限，不算正式检索表现。

### 13.6 Reader与Judge

后端评测共享reader；外部系统自己回答时单列系统比较。MemSyco、STALE、LongMemEval的LLM judge按原生规则接入；初期本地judge要标本地评审，不与官方榜单直接排序。正式确认优先官方配置或另报盲人工一致性及局限。[S05,S07,S14—S16]

MERIT与MAB CR优先程序评分，judge资源不成为所有任务的阻断。Judge调用计费单列，缺失/错误不静默算通过。

### 13.7 统计单位

| 数据 | 聚类／独立性单位 |
|---|---|
| MERIT | arc，不是全部episode彼此独立 |
| MemSyco | 原样本及共享历史组 |
| MemoryAgentBench | context，不是同context全部问答独立 |
| MemoryArena | group，不拆人物依赖 |
| STALE | scenario，不把三问作独立场景 |
| 重复诊断 | 同一前缀重复，只反映该条件稳定性 |

小smoke只判可执行。比较报告效应大小、真实分母、类别/长度分组和适用的组级置信区间；原文没有给出统计功效保证，不能用建议样本量声称显著。

<a id="s14"></a>
## 14. 成本、缓存与连续账本

**依据：[V8 §2.2、20；V9 §5.2、11]。**

### 14.1 源文件记载的最后账本

| 口径 | Generation calls | Generation tokens | Embedding tokens |
|---|---:|---:|---:|
| V7新增 | 38 | 49,456 | 294 |
| V7末连续账本 | 3,301 | 4,205,203 | 23,570 |

新增已包含在末账本中，不能再次相加。执行前读取实际权威账本及hash，不依据本文重建、清零或替换。开发代理与实验runtime分开；本次合并没有新增项目Host/embedding实验。

### 14.2 互斥计量

```text
任务成本 = 初始形成 + 持续更新 + 读取/回答 + 工具续接
          + selector/反思 + 重试/失败 + 恢复

Embedding、Judge、Store逻辑操作、HTTP/进程耗时分别列出。
```

同一provider request只计一次；一个请求可以承担多个语义功能，不能按每个模块重复加tokens。CPU/耗时有嵌套时标inclusive，不机械相加。

无价目、GPU小时、物理I/O或独立write CPU测量就保留unknown。未运行的native或第二模型不以零调用宣称便宜。

### 14.3 缓存与摊销

MERIT等实现的cache命中可能使本次调用tokens为零。[S03] 同时报实际本轮请求、首次建库、缓存命中与cold/warm设置；不能候选热启动对baseline冷启动。

一份历史在同方法下多问，原生允许时只建库一次；总额与按合法查询机会摊销值同时报告。失败查询仍按预冻分母保留，不把按机会摊销称每个成功任务成本。

缓存身份至少区分方法/代码、模型、配置、owner和数据来源。各臂不能共享可变memory；同文本不同事件也不按文本hash消除真实独立变化。

### 14.4 预算顺序

先由smoke取得每方法形成、读取与完整arc成本，再冻结比较批次预算。优先减少方法矩阵与完整实例数，不剪掉实际历史或只算查询阶段。

候选多用计算可以允许，但必须实报并与简单方法得到相同资源时比较。保留现有运行容量与已授权累计策略，不从本文静默引入新的共享服务限制。

<a id="s15"></a>
## 15. 代码、配置、Git 与复现组织

**依据：[V8 §21；V9 §7、12]。**

### 15.1 文件级职责

| 位置／职责 | 处理原则 |
|---|---|
| `providers/langmem_chat.py` | 保留JSON/native共享投影、容量、delivery和执行；协议差异仅在encoding/parser及显式兼容边界。V7已完成部分只复核不重写 |
| 现有benchmark adapters/runners | 优先复用MERIT、MemSyco及已有资产；只补输入、接口和输出映射 |
| `RequestContext/Renderer/Router` | 不复制另一套装配平台，不把benchmark标签混入runtime |
| strict CRUD / ordinary memory | 一个逻辑写入入口；语义事项判断由模型，程序负责真实target/scope/execution |
| 对象引用 | 先复用实际业务ID；确有必要才加薄映射，原生与扩展结果分开 |
| 同步维护 | 作为明确maintenance_policy接入现有runner，不另建Store |
| `analysis/obligation_trace.py`及scorers | offline-only；官方scorer保留，附加诊断单列 |
| 计账与来源 | 复用现有request ID、hash和scope，不为每个benchmark新建账本体系 |

原文给出的文件名和目录是建议职责。实际仓库路径在U0查清后使用，不预先创建所有文件。

### 15.2 最小交付目录示意

```text
现有 benchmarks / adapters
  官方接口薄映射：memsyco / merit / memoryagentbench
现有 baselines
  ordinary / raw-hybrid / llm-summary / 外部系统入口
configs / benchmark-study
  smoke / first-comparison / conditional-diagnostics / confirmation
data / manifests
  sources / exposure / subset / methods / order / costs
reports
  functional-acceptance / comparison / failure-analysis / overall
```

第三方方法隔离环境或进程，不覆盖foundation锁。代码和数据许可分别核对；不因数据公开就假定模型、代码及trace均可再分发。

### 15.3 冻结与提交

```text
确定问题与协议、任务/评分
→ 单一行为变量实现并提交
→ 在已发布源码上zero-model prepare
→ 固定输入/配置/服务/权限/顺序/缓存/账本
→ 完整执行授权批次
→ 独立结果提交与发布
```

结果提交不替代实际运行提交。不同协议、对象接口、writer和Attention不混成一个无法归因的行为PR。纯结构改动优先请求/容量/审计等价测试，不用历史成功自动证明新源码实效。

源文涉及PR #70/#71状态仅为历史记载；本稿不授权merge、改main或关闭旧PR。Fast CI与Full composition分别记录，skip不算pass。

### 15.4 复现、隐私与资产

每个新运行使用独立namespace、Store、checkpoint和world，不能覆盖attempted目录；脚本内合法续接保留。密钥、DSN、私密trace、数据库、模型权重、环境与构建产物不提交。

公开源码/配置/原生subset IDs/hash/精简结果及获取说明；大型数据按LICENSE处理。公开hash不是原始trace内容，不能保证只靠hash重建未发布证据。

<a id="s16"></a>
## 16. 分层门槛及 Go／Pivot／Stop

**依据：[V8 C1、§22—25；V9 §1.3、Stage A—E、§11.4]。**

### 16.1 门槛分层

| 门槛 | 要求 | 不要求 |
|---|---|---|
| **G0：输入/环境合法** | 真实版本、合法数据、无gold泄漏、实际权限和可执行服务 | native一定可用、所有外部系统已安装 |
| **G1：功能可信** | 原题、真实执行、可评分、无静默丢失、完整计账 | MiLAi满分或击败baseline |
| **G2：比较可解释** | 强简单对照、冻结变量、独立身份、失败与成本完整 | 每个方法相同实际调用数 |
| **G3：复杂机制值得** | 有真实问题/正信号；同状态和同计算替代支持独立增益 | 为维持论文模块强制获胜 |
| **G4：长程副作用可控** | 相关动作/对象/owner、partial/unknown和续接边界验收 | 无副作用QA必须先完成所有恢复功能 |
| **G5：研究确认** | 独立来源组、必要模型/任务泛化、准确结论边界 | 小smoke代表生产可靠性 |

V8 C1关于形成、no-write、对象、live-world、partial和有限成本的要求，保留于G4及整体方法稳定审查。V9“模型答错仍可比较”用于G1/G2，两者不再冲突。

### 16.2 正常失败与事故

正常模型低分、漏答或缺乏收益：记录首断点，继续其余独立且安全的冻结任务；不修改当批prompt，也不反复抽样直到通过。

隐私泄漏、越权副作用、跨owner污染、系统性scorer错误、身份失配、无法正确计量或未知外部动作需处置时：停止**受影响路径**，核对范围与恢复；不把不安全继续解释成完整实验纪律。

### 16.3 Go／Pivot／Stop的含义

| 结果 | 处理 |
|---|---|
| 工程接通、任务有对错 | Go到公平比较，不先追求暴露集满分 |
| 协议无可解释差异 | 停止协议扩张，保留较简单/可用方式 |
| 对象ref不改善或制造新选择错 | 回退扩展，不更换原benchmark工具 |
| writer提高必要保存但误存/成本扩大 | 报告trade-off；无净价值则不默认化 |
| query或State查询增强已经足够 | 停止独立selector开发，保留State工程能力 |
| 候选只有某长度/scope有效 | 明确适用边界，做对应确认，不要求所有任务通吃 |
| 所有改进依赖隐藏标签、强制工具或样本特例 | Stop相应方法主张，保存负面证据 |
| 长程费用远高于简单方法且无质量收益 | 停止扩大复杂化，不以局部节约掩盖总成本 |
| 新模型/环境缺失 | 记BLOCKED或NOT_RUN，不填失败准确率或效率优势 |

“Stop”针对当前变体、扩张或无证据主张，不代表销毁已有代码、换题或抹除旧问题。新的修复仍需具体首断点和单独授权。

<a id="s17"></a>
## 17. 推荐执行批次与交付检查表

**本节按V9主线重新组织V8最小批次；所有条件实验保留，不作为自动启动清单。**

### 批次A：先功能与原生评分

**范围：U0＋U1。**保留现有JSON；MemSyco三个任务各2题，MERIT三域easy/hard各1完整arc。先合适原生参考路径，再MiLAi；原生数据或环境阻断时只延期该项。

验收交付：

- [ ] source、exposure与subset manifest均含真实版本和ID；
- [ ] 写入节奏、history权限、owner隔离和实际工具合同明确；
- [ ] 原生scorer与本地judge差异注明；
- [ ] 输入、Store、实际delivery、答案/工具/world和成本可串联；
- [ ] 低分与adapter错误分开，未以“必须全对”为结束条件；
- [ ] 本批总报告保留失败、阻断及未运行分支。

### 批次B：第一个强对照结果表

**范围：U2。**MemSyco60题、MERIT18arcs；强原文RAG、真实摘要、完整历史、ordinary/实际候选及第一项Mem0/MemZero。重复实现合并，不强凑方法列数。

交付逐项原生分数、分类/来源组结果、冷/热缓存、完整成本和首断点。正常错误不取消剩余安全样本；当批不改方法。

### 批次C：必要的功能修复

**范围：U3-P/O/W/R中实际需要的部分。**协议、对象、writer、恢复各自独立开题、冻结、执行和收口；native环境不满足则可先处理其他问题。需要新诊断才创建，不能把补充数据混入原生主表。

交付最小实现、旧反例与反向控制、真实续接结果、回滚方式及未解决原因。

### 批次D：直接机制证据

**范围：U4。**MAB CR 6k接通、32k完整context比较；固定bank/前态做呈现、Q/W/A、U及必要同计算替代。不必须四项全跑，只运行与证据相关的项。

交付机制是否触发、同信息输入、相关分母和实际费用；不以选择集合变小等同总成本下降。

### 批次E：独立与长程确认

**范围：U5。**优先MemoryArena完整group、新来源组与不同模型家族小切片；有需要才增加V8自然长程和LongMemEval/STALE/V2。真实partial/unknown任务先满足相应安全门槛。

交付确认集锁定、原生组级结果、模型/模板差异、适用范围和失败。方法变化后重新登记曝光，不重复利用已知确认答案调参。

### 每批都执行的结案要求

- [ ] 授权范围内各项均有实际结果或明确 `NOT_RUN / NOT_TRIGGERED / BLOCKED_ENVIRONMENT / NOT_ACTIVATED`；
- [ ] 真实模型执行、mock、prepare、提案与持久成功没有混计；
- [ ] 旧结果、失败、输入、rubric、锁及账本原样保留；
- [ ] 新源码/结果/报告身份区分，未将报告commit替实际run commit；
- [ ] 总结支持与反驳了什么，下一问题是什么，不自动生成新复杂模块；
- [ ] 实验停止、服务未擅改、Git未擅合并，后续范围等待明确授权。

<a id="s18"></a>
## 18. U6：总体收口、论文与 Product 边界

**映射：[V8 §23、25—27；V9 §14、Stage E]。**

### 18.1 本阶段最小可交付

1. MERIT与MemSyco的可复用原生适配、可靠评分及计账。
2. 一组功能slice、一组独立比较slice，以及完整曝光和来源登记。
3. 至少三个有区分力的简单对照及一个实际外部系统；真实重复臂合并。
4. task fail与adapter fail、形成与消费、proposal与执行、业务与记忆完成明确分开。
5. 能解释收益/退化来自形成、取材、呈现、动作或额外计算，并确定下一项需要修改的具体层。
6. 所有已授权条件分支有清楚结果；未触发并不构成虚假的完成能力。

### 18.2 三种完成不能合并

**执行Goal完成**：按冻结范围执行并处理条件门槛，证据、费用、报告与停止状态完整。

**研究成功**：在强简单方法、外部系统、机制对照和独立确认下，对限定claim给出可信收益或新的边界结论。若要主张State–Attention优势，必须有其实际激活和独立净价值，不能靠普通CRUD通过代替。

**Product准入**：另需稳定形成/更新/删除、低误存、业务副作用与恢复、owner隔离、live-world边界、长程可用、成本、独立确认及删除/权限边界。当前NO_GO不因smoke或CI通过而改变。

### 18.3 允许的正面与负面收口

正面证据链：基础形成与行动可用 → 生命周期有依据 → 强ordinary query对照 → 必要机制有净质量/成本价值 → 独立任务/模型确认。

负面证据链同样完整：简单ordinary memory＋良好工具接口＋普通query已经足够，或复杂模块无法回收成本，则保留系统和负面结果、缩小方法主张；不为了论文目标强迫Attention获胜。

### 18.4 统一开发原则

> **用原生benchmark的小切片检验功能，用强基线检验必要性，用真实失败决定改哪一层，用独立确认决定能主张多大范围。保留v8的完整生命周期目标，但不让未启用的协议或未证明必要的模块阻断v9的可执行主线。**

<a id="appendix-a"></a>
## 附录 A. 原计划逐节映射

映射记录每一原章节在合并稿中的归属。重复原则已经合并；改变执行优先级的项目明确列出，不表示原计划相应任务已经运行。

### A.1 V8 全部章节

| 原章节 | 合并归属 | 保留／调整说明 |
|---|---|---|
| V8 §0 文档目的 | §1、§18 | 保留形成—行动—恢复—长程目标；公开benchmark成为主要证据线 |
| V8 §1 七个问题 | §1.3、§10—12 | 协议、动作、对象、writer、恢复、规模、Attention全部保留 |
| V8 §2 基线 | §1.1、§14.1 | 同一历史SHA和账本；不冒充本次远端状态 |
| V8 §3 架构原则 | §2 | 一个服务、有依据工作事实、程序与模型职责 |
| V8 §4 阶段图 | §0.2、§3 | 线性顺序调整为benchmark主线＋条件分支 |
| V8 §5 D0 | §7 U0 | 与V9资源/曝光清单合并；零模型 |
| V8 §6 D1 | §10.1 U3-P | native不再全局前置；named/required只作诊断 |
| V8 §7 E1 | §10.1 U3-P | J0/N0、thinking独立、正负例、真实执行与成本 |
| V8 §8 D2 | §10.2 U3-O | 对象ref结构与真实来源，原生/扩展边界 |
| V8 §9 E2 | §10.2 U3-O | free-text/ref，精确身份与反例全保留 |
| V8 §10 D3 | §10.3 U3-W | 漏存时同步子任务，单一提交责任 |
| V8 §11 E3 | §10.3 U3-W | direct/subtask、正负例与完整成本 |
| V8 §12 E4 | §10.4 U3-R | partial、unknown、reopen、真实ID与无重复副作用 |
| V8 §13 C1 | §16.1 G4、§18 | 不再阻断无副作用benchmark；保留长程动作与整体稳定门槛 |
| V8 §14 D4 | §12.2 | 2–3 owners、20–40 sessions、15–30事项，原生优先 |
| V8 §15 E5 | §11、§12.3 | all/query强参照，不制造容量瓶颈 |
| V8 §16 D5 | §2.3、§11 | 局部有依据State，不复制另一份长期事实 |
| V8 §17 E6 | §11.2—11.5 | Q/W/A、同bank/预算与净价值 |
| V8 §18 M1 | §12.4 | 不同家族6–10代表实例；可提前有限诊断 |
| V8 §19 Failure Taxonomy | 附录B.3、§13 | 原始首断点类型保留，另标非语义阻断 |
| V8 §20 成本 | §14 | 全部generation/embedding/工具/观察，unknown分开 |
| V8 §21 Git/PR | §15 | 单行为变量、发布后冻结、结果身份分离 |
| V8 §22 Go/Pivot/Stop | §16 | 停止扩张与继续安全覆盖分开 |
| V8 §23 Product | §18.2 | 全部十项准入要求保留，不与CI或研究成功合并 |
| V8 §24 最小批次 | §17 | 首批改为原生smoke，协议/对象/writer/恢复为条件批次 |
| V8 §25 完成判据 | §18 | 正面/负面均可完成执行收口，研究主张据证据 |
| V8 §26 最终架构 | §2、§18.4 | 一个MemoryService与同一Host，必要时子任务 |
| V8 §27 开发策略 | 执行摘要、§18.4 | 任务、记忆、检索与Attention逐层验证 |

### A.2 V9 全部章节

| 原章节 | 合并归属 | 保留／调整说明 |
|---|---|---|
| V9 执行摘要 | 执行摘要、§0.2、§3 | 成为统一主线，不串行等待native |
| V9 §1 事实与调整 | §0—1、§16 | 工程/任务/研究三个“通过”保留 |
| V9 §2 选型 | §4 | 七项benchmark、LoCoMo补充及缺失能力边界 |
| V9 §3 样本 | §5、附录B.1 | 原生完整实例、来源组、hash抽样与建议规模 |
| V9 §4 功能 | §2、§8 | 公开接口薄接入，后端/自主Agent区分 |
| V9 §5 源码风险 | §6.3、§14.3 | starter、截断full、缓存、vendor与演化风险 |
| V9 §6 baselines | §6 | 简单方法、外部系统与能力身份 |
| V9 §7 B0—B5 | §7—9、§15 | B0→U0，B1—B3→U1，B4→U1/U3，B5→U2 |
| V9 §8 Stage A—E | §3、§8—12、§16、§18 | A→U1，B→U2，C→U4，D→U5，E→U6 |
| V9 §9 公平性 | §13 | 权限、full context、reader/judge、统计单位 |
| V9 §10 指标 | §13、附录B.3 | 原生任务、条件链、首断点与未知标注 |
| V9 §11 成本与纪律 | §14、§16 | 缓存、摊销、失败不中断独立安全覆盖 |
| V9 §12 目录 | §15 | 只保留职责示意，不新建通用平台 |
| V9 §13 批次 | §17 | A/B优先，机制和独立确认按证据推进 |
| V9 §14 阶段成果 | §18.1 | 两benchmark、强对照、可归因结论，不追求名单数量 |
| V9 §15 来源 | 附录D | 22项来源和检索局限完整保留，未新查证 |

<a id="appendix-b"></a>
## 附录 B. 最小清单与结果模板

下列模板只是将两份原文的字段与交付要求合并成便于执行的示意。它们**不是已选样本、已冻结配置、新runtime schema或新增在线评审机制**；优先填入现有manifest格式。

### B.1 Source / subset manifest

```json
{
  "benchmark": "official_name",
  "upstream_code_commit": "resolve_before_run",
  "dataset_revision": "resolve_before_run",
  "scorer_hash": "resolve_before_run",
  "license_review": "pending",
  "subset_purpose": "smoke|development|confirmation|diagnostic",
  "selection_rule": "group_stratified_hash_order",
  "selection_seed": 20260928,
  "cases": [
    {
      "native_id": "actual_id_from_release",
      "source_group_id": "actual_history_or_arc_or_group_or_context",
      "raw_input_hash": "actual_hash",
      "full_history_preserved": true,
      "exposure_status": "checked_before_run"
    }
  ]
}
```

类别/长度字段仅用于离线分层。runtime只接收原生允许的输入，不因manifest存在就取得题型、gold或评估侧标记。

### B.2 Method / execution manifest

```json
{
  "method_id": "actual_frozen_recipe",
  "source_commit": "actual_execution_commit",
  "upstream_baseline_commit": "actual_commit_or_not_applicable",
  "history_mode": "native|archive|retained",
  "write_cadence": "native_episode_end|turn_end|host_direct|bounded_subtask",
  "protocol": "actual_json_or_native_mode",
  "model_identity": "actual_service_and_verified_asset_scope",
  "embedding_identity": "actual_identity",
  "reader_judge_identity": "actual_identity_or_not_applicable",
  "cache_mode": "cold|warm",
  "tool_interface": "native|explicitly_named_extension",
  "scope_isolation": "actual_run_owner_store_checkpoint_world",
  "budget_start": "actual_ledger_identity",
  "order_manifest": "actual_frozen_order"
}
```

同名arm不等于同一方法。protocol、writer、对象接口、reader或布局改变均应体现在身份中；报告commit不能替实际source commit。

### B.3 失败与条件状态

保留V8的语义首断点类型：

```text
INTENT_RECOGNITION
ACTION_SELECTION
MEMORY_TARGET
MEMORY_CONTENT
TOOL_SELECTION
TOOL_ARGUMENT
EXECUTION
WORLD_STATE
MEMORY_MAINTENANCE
DELIVERY
CONSUMPTION
ANSWER
RECOVERY
EVALUATION
```

另以独立状态字段记录V9要求的parse、capacity、environment、scorer、identity或费用问题；这些不是全部都能当作模型能力失败。

每条失败至少填写：

| 字段 | 内容 |
|---|---|
| 原生ID／来源组 | 固定实际身份 |
| Expected | 原生任务或明确诊断要求 |
| Observed | 实际输出、工具/Store/world状态 |
| Earliest breakpoint | 最早有证据的断点，找不到则unknown |
| Evidence | 实际请求、回执、记录、文件与hash位置 |
| Competing explanations | 可被区分的解释，不直接确定唯一因果 |
| Downstream effects | 上游失败带来的后果，不当独立根因 |
| Next action | 不改、工程修复、单变量诊断、停止或阻断 |
| Cost | 该失败及重试/续接已经发生的实际消耗 |

结果可标 `COMPLETED_WITH_RESULTS`、`TASK_FAILED`、`BLOCKED_ENVIRONMENT`、`NOT_RUN`、`NOT_TRIGGERED`、`NOT_ACTIVATED`、`INVALIDATED_BY_INFRASTRUCTURE` 等，但须在执行协议中固定定义。prepare、终止状态、工具提案均不能单独标任务成功。

### B.4 每个工作包的交付模板

```text
目标问题：
原文来源 / 本合并包编号：
前置与授权范围：
实际源码、数据、工具和模型身份：
最小修改：
保持不变的合同：
原生结果与附加诊断：
真实调用与全部成本：
通过、失败、阻断、未触发：
首断点及竞争解释：
回滚边界：
当前结论和下一步是否获授权：
```

<a id="appendix-c"></a>
## 附录 C. 尚待实际核对的事项

两份原文不足以确定以下细节，本文不补写成既成事实：

1. 当前main、PR #70/#71与执行工作树的实时SHA、CI和合并状态。
2. 所有上游benchmark的当前commit、数据revision、许可证与必需本地资产。
3. 历史曝光清单和实际选定的smoke/dev/confirmation原生ID。
4. 当前adapter是否与固定上游接口兼容，以及具体需要修改哪些现有文件。
5. native自动工具解析的合法隔离服务是否获授权并实际可用；named/required能力不替代该条件。
6. reranker、外部baseline、第二模型与固定judge的实际可用版本和费用。
7. 真实模型质量差异的方差、统计功效、绝对资金预算和可接受效应幅度。
8. benchmark是否真实覆盖partial/unknown／全范围遗忘，以及专项诊断需要的最小world支持。
9. 哪项State–Attention或writer机制真正有独立收益；原文没有给出已成立结论。

对这些事项，先核对再冻结。未支持的内容保持未知，不凭项目名、README结果或旧版本通过推导当前实现能力。

<a id="appendix-d"></a>
## 附录 D. v9 保留的来源入口

以下内容保留V9 §15中的22项来源、读取blob身份及检索限制。**其中“已核实”“读取”“本次”均指V9编制时的记录，不表示本合并阶段进行了新的外部检索。**执行时仍须锁定commit并确认资源可用。

检索日期：2026-09-28。GitHub路径若为main，是本次读取的公开版本，不保证后续不变；执行时必须锁定commit。以下资源已核实存在及相关说明/选定源码，未声称已复现其论文分数。

[S01] MiLAi v7总体报告，固定项目提交：
https://github.com/minguselandy/MiLAi/blob/77dfc2f43f2307bb649cdbee9d62a97e5863fac0/MiLAi-Lab/docs/MILAI_DEVELOPMENT_EXPERIMENT_V7_OVERALL_REPORT_20260928.md

[S02] MERIT官方README，代码MIT；任务、checker与基线说明：
https://github.com/smshweta/merit-bench

[S03] MERIT真实模型memory实现，读取blob SHA：3dec54a9ff12db034148989861a6859591f98e90：
https://github.com/smshweta/merit-bench/blob/main/merit/memory_llm.py

[S04] MERIT MemoryBase与starter，读取blob SHA：9eb3e8250df0496aca2a31cf80f73c4988e3ab5a：
https://github.com/smshweta/merit-bench/blob/main/merit/memory.py

[S05] MemSyco-Bench官方数据、任务与数量：
https://github.com/XMUDeepLIT/MemSyco-Bench
https://arxiv.org/abs/2607.01071

[S06] MemSyco基线集成与额外控制，读取blob SHA：d495d33b06f8ddf005f37a008f6689d5e637af20：
https://github.com/XMUDeepLIT/MemSyco-Bench/blob/main/baselines/README.md

[S07] MemSyco评估入口，读取blob SHA：ffeefc0346dd8d25f358fc1b887ae7194bbda2f6：
https://github.com/XMUDeepLIT/MemSyco-Bench/blob/main/evaluation/README.md

[S08] MemoryAgentBench官方代码、增量协议与评分对应：
https://github.com/HUST-AI-HYZ/MemoryAgentBench

[S09] MemoryAgentBench官方HF数据：
https://huggingface.co/datasets/ai-hyz/MemoryAgentBench

[S10] MemoryAgentBench公开配置：
https://github.com/HUST-AI-HYZ/MemoryAgentBench/tree/main/configs/data_conf/Conflict_Resolution
https://github.com/HUST-AI-HYZ/MemoryAgentBench/blob/main/configs/data_conf/Conflict_Resolution/Factconsolidation_mh_6k.yaml

[S11] MemoryArena官方项目页，数据CC BY 4.0说明：
https://memoryarena.github.io/

[S12] MemoryArena官方代码，README标preview；代码再分发需另核代码LICENSE，不把数据许可自动套给代码：
https://github.com/ZexueHe/MemoryArena

[S13] MemoryArena travel设置，读取blob SHA：b0f0c9f5742f13fefe49e22c85ee634bb9e45a6e：
https://github.com/ZexueHe/MemoryArena/blob/main/setup_travel.md
https://huggingface.co/datasets/ZexueHe/memoryarena

[S14] LongMemEval官方代码、cleaned数据入口与oracle说明：
https://github.com/xiaowu0162/LongMemEval
https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned

[S15] STALE/CUPMem官方代码：
https://github.com/icedreamc/STALE

[S16] STALE论文与官方数据入口：
https://arxiv.org/abs/2605.06527
https://huggingface.co/datasets/STALEproj/STALE

[S17] LongMemEval-V2官方项目页，任务与LAFS定义：
https://xiaowu0162.github.io/longmemeval-v2/

[S18] LongMemEval-V2官方代码、Insert/Query与baseline：
https://github.com/xiaowu0162/LongMemEval-V2

[S19] Mem0官方项目；接入时核对实际版本与默认add/update路径：
https://github.com/mem0ai/mem0

[S20] A-MEM官方项目：
https://github.com/agiresearch/A-mem

[S21] SimpleMem官方项目；明确text/Omni/EvolveMem区别：
https://github.com/aiming-lab/SimpleMem

[S22] HiMem官方项目：
https://github.com/jojopdq/HiMem

补充核查限制：MERIT arXiv页面本次获取失败，因此本文只用作者GitHub代码和README作为其任务与实现依据，不引用二手文章的性能/费用；没有运行任何外部baseline，不能承诺其当前依赖可直接兼容项目锁定环境。
