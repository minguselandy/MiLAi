---
title: MiLAi Benchmark 选型、功能接通与分阶段对照实验规划 v9.0
date: 2026-09-28
status: RESEARCHED_PLAN_NOT_EXECUTED
scope: MiLAi-Lab
project_evidence_ref: 77dfc2f43f2307bb649cdbee9d62a97e5863fac0
previous_plan: MILAI_DEVELOPMENT_EXPERIMENT_PLAN_20260928_v8.0.md
research_goal: NOT_ACHIEVED
product_status: NO_GO
runtime_experiments_this_turn: 0
github_writes_this_turn: 0
---

# MiLAi Benchmark 选型、功能接通与分阶段对照实验规划 v9.0

## 执行摘要

下一阶段采用一条清楚的路线：

**现有功能可用 → 原生 benchmark 小切片接通 → 强简单 baseline → 外部记忆系统 → 固定状态的机制对照 → 独立确认。**

不再以继续新增自建脚本、不断修到所有脚本满分，作为进入公开任务的唯一前提。自建测试保留作工程回归与故障定位；公开 benchmark 提供实际效果证据。也不将 native 服务未开启自动工具解析，作为全部 benchmark 工作的前置阻断。

建议首批优先使用 **MERIT + MemSyco-Bench**，其次使用 **MemoryAgentBench 的 FactConsolidation 6k/32k 官方配置**检验增量维护和有限上下文下的取材；功能接通后增加 **MemoryArena 的完整任务组**作为独立 Agent 任务证据。LongMemEval、STALE、LongMemEval-V2 分别用于通用长期回忆、隐式失效和轨迹经验取材，不在第一批同时全量运行。

第一轮功能验证只要求一个合适的原生参考路径与 MiLAi 能执行、能评分、能正确计账，不要求 MiLAi 先赢。第一轮效果比较再加入强原文检索和真实 LLM 摘要；外部系统优先 Mem0 与 A-MEM/SimpleMem 中的一项。State–Attention 的开关只在同一 bank、同一 writer、相同合法候选下比较。

本文中的样本数量是建议，不是已生成的样本清单。实际 ID、来源组、排除清单、数据版本、预算和配置必须在运行前冻结。本次核查了公开资源和选定接口，没有运行模型、下载完整评测数据、修改仓库或启动先前暂停的 Goal。

---

## 1. 当前项目事实与本次规划的调整

### 1.1 可以复用的基础

项目 v7 报告确认：JSON 路径在六种合成结构、两个预定重复中完成 12 条轨迹和 92 项任务义务；native 对照被部署环境阻断，协议比较仍为 INCONCLUSIVE。已有合法材料投影、容量检查、同一执行器、strict CRUD、实际回执和计账可作为接入基础。[S01]

这里的 12 条轨迹不是 12 个独立任务结构，92 条义务也不是 92 个独立样本。报告不支持广泛泛化或 State–Attention 效果。旧 v6 失败不因 v7 小切片成功而注销。

当前实验参数以冻结报告为依据：Qwen3.6-35B-A3B-FP8、JSON-action、temperature=0、thinking=false、输出上限 4096、总容量 65536、bge-m3/1024 维。执行前复核实际资产与服务；不凭模型名称认定完整权重身份。

### 1.2 不再重复开发

保留 RequestContext/Renderer、scope 隔离、Store、checkpoint、实际业务回执、失败保留和账本。不要为了接入 benchmark 新建另一套记忆服务、另一个业务执行器或通用 benchmark 平台。

旧 v8 中 native 环境、对象接口、同步维护子任务、长程积累仍是可选研究工作，但不必串成所有 benchmark 的硬前置链。能在现有 JSON 路径合法运行的任务先运行。涉及新服务、模型下载、部署或外部收费服务的步骤单独授权。

### 1.3 区分三种“通过”

| 层次 | 判断 | 不代表什么 |
|---|---|---|
| 工程可执行 | 数据合法进入、工具合同正确、无泄漏、真实结果可评分、成本可追溯 | 不保证模型答对 |
| 任务表现 | 原生准确率、环境成功率、更新与范围指标 | 不自动证明机制新颖 |
| 研究贡献 | 与强对照、消融和独立数据相比有可解释增益或边界 | 不自动达到 Product 准入 |

不能要求“所有公开任务全对”后才允许开展 baseline 比较。低分本身是有效结果；adapter 漏历史、rubric 泄漏、工具假执行、计账错误才是需要先阻断的工程问题。

---

## 2. Benchmark 选型与证据覆盖

### 2.1 优先级总表

| Benchmark | 官方资源与可用性 | 主要验证内容 | 首批选择 | 限制与定位 |
|---|---|---|---|---|
| MERIT，2026 | 官方仓库有 SQLite worlds、任务生成、原生 checkers、memory 接口和完整实验 traces。[S02–S04] | 历史事实是否改变真实工具行动；更新事实；成本 | 第一批：三个业务域的 easy/hard 完整 arc | 生成式模板任务，换 seed 不等于独立任务家族 |
| MemSyco-Bench，2026 | 1550 样本、五任务、公开 JSONL、统一 runner、baselines。[S05–S07] | 适用范围、新旧偏好、正确个性化、证据冲突 | 第一批：scope、valid selection、personalized use | 主要是回答/决策，不证明在线副作用或恢复 |
| MemoryAgentBench，ICLR 2026 | 官方代码与 HF 数据；增量输入、一次摄入多次查询；FactConsolidation 有 6k/32k 等配置。[S08–S10] | 冲突处理、持续维护、跨段取材 | 第二批：single-hop/multi-hop 的 6k，随后 32k | 一个 context 对应多题，不能按题数充当独立历史数量 |
| MemoryArena，2026 | 官方代码仍标 preview；数据公开；travel 有 270 个完整 group，本地 CSV 工具。[S11–S13] | 相互依赖的多 session 规划与实际工具使用 | 独立确认：先 2 个完整 travel group | 航班数据库另取；先验证环境和评分，再扩大 |
| LongMemEval，ICLR 2025 | 官方 cleaned 数据，每版本 500 问；QA 与 retrieval evaluator 公开。[S14] | 知识更新、时间、跨会话推理、拒答 | 按未暴露 question/history 小样本接入 | S 版通常约115k tokens，超当前64k；oracle 仅诊断 |
| STALE，2026 | 官方数据和 CUPMem；400 场景、1200 个 probes、两种隐式冲突。[S15–S16] | 已检索新信息却仍沿旧状态；错误前提抵抗 | 特定失效问题出现时：2场景接通，随后12场景 | 完整历史可很长；三问属于同一场景，逐题隔离读取副本 |
| LongMemEval-V2，2026 | 451 问、两领域、multimodal trajectories；Insert/Query API 和 AgentRunbook 基线公开。[S17–S18] | 从历史环境经验恢复动态状态、流程、gotchas 与前提 | 后期 small tier 的合法小子集 | 上限115M tokens不是首批规模；需要多模态及固定reader适配；不是在线重演任务 |

LoCoMo 可以作为文献常用补充，但本阶段不再增加它的强制实现；当前最缺的是持续行动和选择性使用证据，而不是再增加一个相似的对话 QA 总分。

### 2.2 与当前研究问题的对应关系

- **形成/更新/真实行动**：MERIT 优先；补 MemoryArena。
- **何时应该或不应该采用记忆**：MemSyco 的三个互补任务；必要时加入 memory–evidence conflict。
- **新旧状态及依赖变化**：MemoryAgentBench Conflict Resolution；隐式问题再用 STALE。
- **真实读取选择压力**：MemoryAgentBench 的发布长度配置、LongMemEval 全历史，后期 LongMemEval-V2。
- **显式授权删除、部分/未知副作用恢复**：上述 benchmark 不一定直接覆盖，仍保留小型工程诊断，不能用 QA 成绩替代。

### 2.3 为什么不直接全量 LongMemEval-V2

官方设置包括截图、轨迹数据、固定 reader 和 query latency/LAFS 评估。当前项目虽有文本记忆和工具链，尚未在本轮证明这套多模态接口可用。删除图片、只保留文字然后报告官方成绩，会改变任务。仅 text 子集也须有官方可识别的模态条件，明确称派生子集，不冒充完整 small tier。

### 2.4 为什么 MemoryArena 不是第一天全量部署

官方代码有独立 agent/env/memory 接口，但 README 标明 preview。Travel 依赖本地航班、餐厅、住宿等数据库，其中航班文件另行下载。[S11–S13] 这比真实联网浏览可控，但仍需验证数据资产和原生 checker。不能用空表、少量手写数据或关闭约束冒充原环境。

---

## 3. 首批样本：少取完整实例，不截断关键历史

### 3.1 三阶段建议规模

| 数据 | 功能 smoke | 初次比较 | 独立确认建议 |
|---|---|---|---|
| MemSyco 三任务 | 每任务2题，共6题 | 每任务20题，共60题 | 另取每任务30题，共90题；有充分证据再扩未暴露剩余集 |
| MERIT | 3域 × easy/hard × 1 arc = 6 arcs | 3域 × easy/hard × 3 arcs = 18 arcs | 3域 × 3难度 × 4 arcs = 36 arcs，增加模板/任务族隔离分析 |
| MemoryAgentBench | sh_6k、mh_6k 各1完整context；每context最多10个原问题 | sh_32k、mh_32k 完整context；每context最多25个原问题 | 按官方不同context/长度配置扩展；不把同源不同长度当完全独立样本 |
| MemoryArena travel | 2个完整group，所有组内人物任务顺序保留 | 6个完整group | 另取12个完整group；实际人数、步骤和成本从数据确认 |
| STALE（条件性） | Type I/II 各1完整场景、各三问 | Type I/II 各6场景、共36 probes | 根据稳定成本和诊断必要性扩展 |

上述数目不是统计显著性的保证。数据实际不足或存在来源重叠时，减少数量并报告真实分母，不补造条目。MERIT 的 episode 数依据冻结上游生成配置；若使用原生五 episode arc，则保留全部五个，不只抽最后的难题。

### 3.2 选择规则

1. 使用原生 train/dev/test 划分时优先遵守；没有正式划分则称内部 smoke/dev/confirmation，不能称官方 test split。
2. 从项目全部历史原生实验中导出 exposure registry。相同源历史、人物或模板衍生项尽可能按组隔离。
3. 在类别内按 `SHA256(dataset_revision || source_group_id || selection_seed)` 排序选取；真实ID和原文hash写入 manifest。
4. 采样只使用原生类别、来源组、模态、历史长度等非结果元数据，不根据答案、MiLAi得分、失败类型或gold evidence挑有利条目。
5. smoke 可以选择事前声明的短历史条件，但必须称“长度受限功能子集”，不能当代表性全量结果。正式比较覆盖发布长度范围并按长度分层。
6. 失败后不换题、不继续抽到全对；修代码后产生新方法版本，并明确哪些比较臂需要重跑。
7. 实例原文、角色、时间、顺序、工具schema和评分规则不变。不能为触发State加入“务必建立State”，也不能将旧benchmark问题重写成更容易保存的指令。

### 3.3 最小样本清单字段

```json
{
  "benchmark": "official_name",
  "upstream_code_commit": "resolved_before_run",
  "dataset_revision": "resolved_before_run",
  "scorer_hash": "resolved_before_run",
  "subset_purpose": "smoke|development|confirmation",
  "selection_rule": "group_stratified_hash_order",
  "selection_seed": 20260928,
  "cases": [
    {
      "native_id": "actual_id_from_release",
      "source_group_id": "actual_history_or_arc_id",
      "raw_input_hash": "actual_hash",
      "full_history_preserved": true,
      "exposure_status": "checked_before_run"
    }
  ]
}
```

这是字段示意，不是已冻结配置。文档生成阶段不填写虚构ID。

---

## 4. 先完成功能性：需要什么，不需要什么

### 4.1 本阶段必须可用的能力

| 能力 | 最小验收 |
|---|---|
| 历史摄入 | 全部合法内容按原顺序取得，角色和时间保留；有真实来源ID；无未来问题/gold混入 |
| 增删改查 | 相同事项准确更新；实际目标存在性和owner边界检查；明确不写入合法；删除保留其原合同 |
| 跨session续用 | 内存与checkpoint生命周期明确，重开后只取得允许的持久内容，不能偷读完整审计日志 |
| 有界读取 | all/query可用，最终完整请求使用真实tokenizer计数，预留输出/工具目录空间 |
| 真实工具 | 复用原生world与工具；不把assistant文本当执行；不改参数大小写/单复数自动补对 |
| 结果记录 | task fail、parse fail、capacity fail、environment blocked、scorer fail分别记录；prepared不算delivered |
| 评分 | 原生scorer可复现；离线评价接口不向runtime暴露题型、正确答案和证据定位 |
| 计账 | writer、reader、工具前后模型、重试、embedding、judge分别计入；cache状态和历史摊销透明 |

### 4.2 最小接口，不新造平台

优先直接实现上游已有记忆接口。例如MERIT明确采用：

```python
write(episode_id: str, transcript: str) -> None
read(current_context: str, budget_chars: int) -> str
```

LongMemEval-V2采用：

```python
insert(trajectory) -> None
query(query, query_image=None) -> list[context_item]
```

不要为了统一名字强行改上游调用节奏。MiLAi内部可以有薄包装，将真实事件交给现有写入器、将读取请求交给现有all/query，再返回原生要求的材料。[S04,S18]

跨benchmark只共享必要的隔离、计账、source mapping和缓存身份。用户行为、工具环境和评分仍由各benchmark负责。

### 4.3 区分记忆后端评测与自主Agent评测

**后端评测**：MemSyco、MemoryAgentBench、LongMemEval等由harness将历史交给memory，再用同一个reader回答。它证明形成/检索/使用能力，不证明Agent自主判断何时写入。不能把离线注入原对话改成向Host发出一串新的实时用户命令。

**端到端评测**：MERIT、MemoryArena中，Agent选择工具动作，真实环境给出反馈，后续任务使用自己的实际历史。不同方法动作不同，后续观察自然可以不同；不能强迫baseline看到只有MiLAi执行动作才得到的结果。

**写入节奏必须标注**：自动episode-end `write`、turn-end处理、Host主动CRUD是不同策略。不能称它们只差一个retriever。如果为了组件归因固定摄入日志，应另标为“固定轨迹离线记忆比较”。

### 4.4 不作为前置的事项

native自动工具解析、第二模型、图数据库、同步writer、独立A/U选择器、全局反思与完整Product迁移，都不是首批原生benchmark的必需前提。它们只有对实际首断点有必要时才进入独立工作包。

---

## 5. 源码核查发现：避免把弱占位实现当强基线

### 5.1 MERIT 同时提供 starter 和真实模型版本

官方 `merit/memory.py` 中：

- `KeywordRAG` 是关键词集合交集，不是完整BM25。
- `RollingSummary.summarize()` 的starter只是 `transcript[:800]`。
- `StructuredFacts` 有领域正则提取规则。
- `FullReplay` 在超过 `budget_chars` 时保留尾部，不能无条件称完整历史。

官方 `merit/memory_llm.py` 另有 `EmbeddingRAG`、`LLMSummary`、`LLMFacts` 和模型调用计量。[S03–S04]

因此，正式比较必须写清类与配置。不要让MiLAi只击败文本截取摘要或关键词重叠，然后认领超越RAG/摘要。

同时，`LLMSummary` 是否真正把旧摘要和新信息联合重写，要读完整调用链；名字不能替代行为。保留原生类作为原生参考，需要更强的滚动重写摘要时另列改进简单基线，不静默改上游后沿用原名。

### 5.2 缓存不能隐去形成成本

MERIT模型实现有磁盘cache；缓存命中时返回的本次token计数可为零。[S03] 主表必须同时记录：本轮实际付费/服务调用、首次建库成本、cache命中、各方法冷启动或热启动设置。不能用候选热缓存对比baseline冷启动。

### 5.3 MemSyco 的 MemZero 不自动等于最新 Mem0 OSS

MemSyco使用vendored `MemZero/A-MEM/NaiveRAG` 与统一配置，还有额外检索后控制选项。[S06] 应保留原标签、记录vendor身份。若再接最新Mem0，另命名为实际锁定的Mem0 OSS，不能混合分数。

### 5.4 SimpleMem 当前仓库不是单一原论文版本

当前仓库包括text、multimodal和EvolveMem入口。[S21] 主对照锁定text模式和明确检索/反思配置，不在确认集调用自动调参或自演化。原生benchmark脚本提供的适配便利，不代表其默认模型/embedding与MiLAi公平相同。

---

## 6. Baseline 分组与接入顺序

### 6.1 必不可少的简单基线

| 名称 | 做法 | 作用 |
|---|---|---|
| NoMemory / NoRetrieval | 无跨session语义记忆，保留任务所需当前观察和共享安全执行底座 | 测历史依赖，不作为主要胜出对象 |
| FullHistory / RawDialogue | 提供该任务允许的完整历史；容量不够就标不可运行或另列窗口条件 | 排除复杂结构没有必要 |
| SlidingWindow + LLM summary | 明确窗口、真实摘要模型和写入节奏 | 排除只是压缩长度 |
| StrongRawRAG | 真BM25 + 同一dense embedding；可加固定reranker，返回原始片段/来源 | 排除更好的检索即可解决 |
| OrdinaryMemory | 当前strict CRUD与相同Host，关闭研究性State–Attention | 排除效果来自基础工具/运行器 |
| MiLAi candidate | 明确启用哪些经过验证的模块 | 不把代码存在自动算成该方法运行 |

真reranker不可用时先报告BM25+dense hybrid，不贴“reranked”标签。不能用测试答案做query expansion。

### 6.2 外部记忆系统

| Baseline | 官方资源 | 建议优先级 | 比较理由与约束 |
|---|---|---|---|
| Mem0 / benchmark内MemZero | Mem0官方源码；MemSyco vendored入口。[S06,S19] | 第一项外部baseline | 代表形成和更新系统；锁定版本与实际write路径；开源与托管成绩分开 |
| A-MEM | 官方仓库与MemSyco入口。[S06,S20] | 第二项外部baseline候选 | 结构化笔记、关联与演化；不能只移植弱检索后仍称原生系统 |
| SimpleMem text | 官方仓库。[S21] | 与A-MEM二选一先做 | 代表压缩/检索规划；禁用测试集自演化；保持原实现能力并记录改动 |
| CUPMem | STALE官方仓库。[S15] | 做隐式失效时必须补 | 与状态裁决、更新传播最接近；其回答器与写入器不可被随意拆弱 |
| HiMem | 官方仓库。[S22] | 方法确认阶段 | 原始episode与note、重整；本阶段不全量接入基础设施 |
| AgentRunbook-R/C | LongMemEval-V2官方实现。[S17–S18] | 进入V2时选R，C视资源授权 | 原生任务近邻；C依赖额外coding agent，不能假定与当前Host等价 |
| MemZero+DynPartition / SelfReCheck | MemSyco官方附加控制。[S06] | A确有信号后 | 使用固定MemZero bank做读取控制对照；不是MiLAi同bank的自动替代 |

### 6.3 第一轮不要一次跑十几个系统

首个有信息量的主表建议：

**完整历史 / 强原文RAG / 真实LLM摘要 / OrdinaryMemory / MiLAi / Mem0。**

如果MiLAi当前recipe与OrdinaryMemory没有实际可运行的差异，合并为同一臂，先作为可用系统测试；不能为占一个候选列而强制启用无意义selector。

MemSyco可从RawDialogue、NaiveRAG、MemZero与MiLAi起步，再替换或补上StrongRawRAG；MERIT保留其真实LLMSummary、EmbeddingRAG、StructuredFacts作为原生参照，另加入MiLAi。不同benchmark不必机械拥有完全相同的全部baseline名单。

---

## 7. 功能开发工作包

### B0：资源与版本台账（零模型）

核对现有MiLAi适配器与暴露样本，不因旧报告说“支持MERIT/MemSyco”就假定当前分支已兼容。固定官方repo commit、数据revision、许可证、依赖、scorer和必要资产hash。外部源码隔离安装，不覆盖现有foundation锁。

产物：一份source manifest、一份exposure registry、一份最小可运行环境说明。不是新的大平台。

### B1：MEMSYCO adapter

复用官方 `evaluation/run_task.py`、任务prompt和judge rubric。[S07]

- 历史来源通过memory build入口摄入，目标问答不提前进入建库。
- 只返回当前方法实际构建/检索出的材料；gold memory、reference evaluation不进入runtime。
- 建库按历史身份缓存，同内容不同owner不可串库。
- 新方法接入官方baseline context接口；不修改问题和scorer。
- `--limit` 只用于初始接线，正式小切片使用冻结的原生ID清单，不能长期只选文件前N行。

### B2：MERIT adapter

复用原生world、tools、arc生成、checker和成本读取。保留默认的episode依赖与工具前提，不把整段未来arc交给Host。[S02–S04]

- 先确认已有MiLAi原生适配与当前官方代码差异，再补薄映射。
- 使用原生的业务参数、执行副作用和失败分支；不把对象ref改造混入baseline初试。
- 记录无记忆任务的leak check；依赖任务可重推导时需说明，不能假定NoMemory应为零。
- `pre_satisfied`、实际world状态与任务完成分开；空库但full历史能答对不算已形成记忆。
- 原生memory hook如果是episode后写入，MiLAi接入必须说明使用相同boundary还是主动CRUD策略。

### B3：MemoryAgentBench adapter

复用官方chunk与question组织，优先CR 6k和32k发布配置。[S08–S10]

- 一次完整context摄入，按原生查询语义处理多个问题。
- 若原生测试不允许用测试问答持续训练memory，读取测试从同一建库快照独立开始；不让前一问题答案进入下一题。
- 沿用 `substring_exact_match` 等原生指标，不为了提高分数新增答案清洗。
- `max_test_samples=1` 指一个长context，不等于一个QA；报告context数和question数。
- 数据中的32k/64k是上游命名，实际用当前tokenizer计量；64k历史加目录/输出可能超当前65536容量。

### B4：真实工具功能补齐

只有原生smoke实际发现缺失时，修复必要的跨session、历史范围、工具参数或查询路径。保存失败如果是Host未调用，就保留为模型结果，不在adapter自动补写。真实副作用不明时停止不安全操作、查询或报告unknown，不为了完成benchmark重试执行。

### B5：外部baseline适配

每个baseline独立环境或进程，提供同样合法材料与服务访问。能共享的模型服务、embedding服务、read budget、工具和world保持一致；存在算法专用encoder、训练checkpoint或reader时保留原依赖并另列不同设置。

保留外部方法原生输入/输出及调用日志。云服务无计账或不能固定版本时，列为不可比较或系统参考，不声称同模型公平比较。

---

## 8. 分阶段实验与门槛

### Stage A：工程接通

先使用原生dry-run或可控fake验证加载、工具、scorer、隔离和费用记录。然后执行最小原题smoke，至少保留一个原生参考路径和MiLAi路径。

工程门槛：没有gold泄漏、伪造工具、错误scope、静默截断、未标明的结果缺失或费用缺口；每个已执行项可归为真实task result或清楚失败原因。严重泄漏/副作用风险阻断相应臂。

不是门槛：MiLAi必须全对，或者必须比原生方法好。正常语义失败继续收集其余预定安全任务，不能每次失败都取消后续所有覆盖。

### Stage B：小样本对照

按第3节冻结新dev slice，运行强简单对照和候选。同一benchmark内共享任务清单、参数和评分；不同方法的实际记忆形成内容和在线轨迹允许不同。

输出：逐任务结果、主指标、分类结果、真实费用、失败首断点。每个失败提出可区分的解释，而不是直接更换方法。

### Stage C：机制确认

只有候选相对强简单方法出现有意义信号，或明确暴露一个选择瓶颈，才运行以下4项中的必要项：

1. **呈现机制**：相同memory与候选，system/current_request的组合呈现比较；明确position与carrier role耦合。
2. **Attention**：固定bank/writer/candidate retrieval，共享当前State信息，比较普通query、相同State查询增强、显式选择。计入控制调用。
3. **更新选择U**：固定前态和新事件，比较全合法更新候选、普通检索候选、显式U；CREATE始终允许。不能因当前读焦点不同而漏存别的长期约定。
4. **同计算替代**：将相同额外预算给简单方法真实回看、rerank或增加候选，排除只是多推理。

既不能因全部历史放得下就宣布State无用，也不能为触发selector私自减少窗口或添加无意义噪声。上游长历史与scope任务本身已有合法压力。

### Stage D：独立确认

冻结开发结果后使用未触碰来源组；优先一项独立agent benchmark（MemoryArena完整group）及第二模型小样本。第二模型也可以在早期作为模型/协议诊断单独授权，不必等所有任务满分。

确认集不参与prompt、阈值、reranker、memory_size或Judge调参。改变方法后重新标记已曝光，不把新版本在旧确认集上的成功冒充unseen。

### Stage E：结论

- 工程可用但质量一般：据实际首断点小修，不扩平台。
- 与强简单方法持平：保留可用系统，停止相应复杂模块的优越性主张。
- 有收益但成本过高：报告真实trade-off，不以只算查询费用掩盖建库。
- 某benchmark读写有效但行动无改善：明确后端与端到端差异。
- 只有特定长度/scope有效：报告适用边界，不要求所有任务通吃。

---

## 9. 公平性合同

### 9.1 两种信息权限

**Archive-access**：所有方法可访问相同合法原始历史。RawRAG必须有相同档案，MiLAi不能独享审计日志。

**Retained-memory**：后续仅使用各方法真正保存的内容。原文方法允许保留原文并计其成本；不能禁止它保存而允许候选访问source store。

每个benchmark的原生信息条件优先。改变条件另列扩展协议，不覆盖原生结果。

### 9.2 必须固定或显式报告

Host/reader模型、模型资产标识、tool protocol、thinking、temperature、seed支持、chat template、输出预算、embedding、分块、候选数、最终材料token上限、外部工具、write cadence、缓存、并行度、judge以及超时。

算法所必需的配置差异可以存在，但需列出。性能比较不等于要求所有算法恰好相同调用数：比较共同预算下的质量，也报告完整实际消耗；同计算消融另外做。

### 9.3 Full context 的边界

LongMemEval-S约115k、STALE可达150k、MAB某些配置超过现有65536容量。[S08,S14,S16] 不得将前64k、后64k或人工选证据称为FullContext。

可选报告：完整历史可容纳子集的结果、明确标记的SlidingWindow、原生Oracle诊断，以及记忆方法在完整历史上分批摄入的结果。不能用长度过滤得到的简单子集代表全benchmark。

### 9.4 Reader与Judge

后端比较采用同一个reader和相同答案合同。外部系统若自己回答，则另列端到端系统比较。

MemSyco、STALE和LongMemEval的原生评分依赖LLM judge。初始本地Qwen judge可用于低成本开发，但标记“本地评审版本”，不能宣称复现官方榜单。正式比较优先原官方judge配置，或报告与盲人工抽查的一致性以及模型更换后的限制。不能根据候选结果调Judge，Judge错误/缺失不静默算通过。

MERIT和MemoryAgentBench CR可先使用程序化评分，避免把Judge接入成本作为所有工作阻断。

### 9.5 统计单位

MemSyco按原样本/共享历史组，MERIT按arc，MemoryArena按group，MAB按context，STALE按scenario。相关题目不是独立样本。主表同时报真实分母、按组结果和置信区间；小smoke只判可执行，不谈显著性。

---

## 10. 指标与失败定位

| 层 | 应报告 |
|---|---|
| 原生任务 | 原始评分、宏平均/类别结果、arc/group完全成功、依赖与独立任务分开 |
| 形成/更新 | 明确应写却未写、更新目标错误、无关信息丢失、旧值复现、临时误存、重复记录 |
| 检索/使用 | 有gold依据时的recall、实际delivery覆盖、当前/历史/范围采用；没有标注则报未知而非伪造precision |
| 执行 | 必要动作、参数准确、实际副作用、业务查询、partial/unknown处理、未完成 |
| 成本 | 写入、维护、取材、回答、反思、重试、embedding、judge、冷/热缓存、storage增长、实际latency |

条件化诊断应展示：

```text
合法来源存在
→ 实际接收
→ 可复用内容形成
→ 候选召回
→ 材料交付
→ 正确采用
→ 业务执行/回答
```

这些通过率不是独立概率，不能机械相乘。判错归到最早有证据的断点；后续影响保留，但不将同一上游漏存拆成多个独立失败原因。

Memory为空可能是策略结果；如果旧历史全在上下文则任务成功不证明Memory贡献。反之，memory非空和tool_called也不证明语义正确。

---

## 11. 成本与执行纪律

### 11.1 不从README宣称金额推算本项目费用

先由smoke实际计量每种方法的建库、每查询与每arc成本，再预算正式批次。没有价目、GPU时间或物理I/O时报告unknown，不填零。

```text
总实验成本 = 各方法真实建库 + 更新 + 查询/回答 + 工具续接
            + 重试/失败 + embedding + 单列judge
```

若一份历史在同一方法下被多问复用，只建库一次；成本同时报告总额与按合法查询机会摊销值。缓存不得跨owner或跨方法语义状态串用。代码与模型不同的缓存必须隔离。

### 11.2 先控制实验矩阵，而不是改小真实历史

第一批只做两类benchmark和少量臂。不要因长历史昂贵，把原文切成只剩答案附近；减少完整实例数量优先于缩短实例内部证据。

给State–Attention或其他候选的额外计算，需要明确计入；允许其使用，但必须与简单方法得到同预算时的表现比较。

### 11.3 与连续账本衔接

最后一个已提供v7账本为3301 generation calls、4,205,203 generation tokens、23,570 embedding tokens。[S01] 实际执行前读取最新权威账本，不凭本文重建或清零。本次检索与生成文档没有进行项目Host/embedding实验；开发侧费用不混入实验累计。

### 11.4 失败不中断证据，事故需要停止

正常低分或模型漏答不触发不断改prompt再重跑，不取消无依赖的剩余冻结条目。真实隐私泄漏、未授权外部副作用、身份污染或系统性scorer错误必须停止受影响路径。恢复后使用新执行身份和清楚的无效结果范围。

---

## 12. 推荐目录与交付

先在现有目录内复用adapter、runner和评估入口。下面是职责示意，不是要求创建全部新文件：

```text
benchmarks/
  registry                 # 官方代码/数据/scorer身份
  exposure_registry        # 历史已暴露来源
  adapters/                # 仅输入/接口/输出转换
    memsyco
    merit
    memoryagentbench
baselines/
  ordinary_memory
  raw_hybrid_retrieval
  llm_summary
  external_mem0
configs/benchmark-study/
  functional_smoke
  first_comparison
  confirmation
data/manifests/
  benchmark_sources
  subset_manifest
  execution_order
  method_manifest
reports/
  functional_acceptance
  comparison_results
  failure_analysis
```

先检索项目实际已有路径，避免复制一份功能相同的framework。全量第三方baseline用隔离环境，不污染现有锁文件。原数据是否可纳入Git按许可证决定；通常只提交版本、下载说明、subset IDs与hash，不上传大型数据库、模型资产或私密trace。

---

## 13. 第一批的具体执行建议

### 批次 A：功能与评分接通

- 固定MiLAi基底与资源权限，保留当前可用JSON路径。
- MemSyco三类各2个原题；MERIT三域easy/hard各1完整arc。
- 每项先跑对应原生参考路径，再跑MiLAi。
- 验证输入、形成、后续独立使用、原生评分与计账。冻结错误与实际能力，不要求全对。
- 只修adapter或真实执行合同的缺陷；算法失败先分类，不立即加writer/selector。

### 批次 B：第一个公平结果表

- MemSyco60题、MERIT18完整arcs。
- MiLAi、强原文RAG、真实LLM摘要，加合适的FullHistory参考。
- 加入第一项外部基线Mem0/MemZero，报告其准确版本。
- 批次运行途中不调整方法、数据、评价或参数。
- 输出质量与全成本，而不是只给一个总accuracy。

### 批次 C：State–Attention直接证据

- MAB CR 6k接通，32k完整context比较，必要时官方更长配置。
- 同bank、同writer、同reader比较query / query+State / selector。
- 需要动作泛化时接MemoryArena完整group，不制造临时新工具任务冒充原生benchmark。
- State未激活则报告当前方法配置与实际运行差异，不靠强制调用制造机制效果。

### 批次 D：独立确认

- 固定方法后使用新来源组，保留之前所有原题曝光记录。
- 第二模型小样本与MemoryArena独立任务优先；LongMemEval/STALE按claim选择。
- 长程或多模态claim出现时再进入LongMemEval-V2，不以名字更新为由替换已经可用的benchmark。

---

## 14. 本阶段应形成的结论

最小可交付成果不是“支持了七个benchmark”，而是：

1. 两个原生benchmark的可复用适配、正确评分与费用记录；
2. 一组事前冻结的功能切片和一组独立比较切片；
3. 至少三个有杀伤力的简单对照和一个真实外部系统；
4. 任务失败与适配失败清楚分开；
5. 一个明确判断：当前收益来自形成、取材、呈现、动作使用还是额外计算；
6. 能说清下一项需要修的代码，而不是再创造一个新方法名。

原先“先功能可用，再实验对比”的目标保留，但功能可用不再被等同于“在高度暴露脚本上达到完美分数”。用原生benchmark的小切片完成真正接通，才开始可信的比较。

---

## 15. 原始来源与检索边界

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
