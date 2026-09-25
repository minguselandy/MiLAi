---
goal_id: MILAI-CONTEXTUAL-USER-MEMORY-DEV-01
version: v2.4
date: 2026-09-23
status: SUPERSEDED_BY_LAB_GOAL_V3
superseded_by: MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v3.0_20260923.md
kind: LAB_DEVELOPMENT_AND_LIGHTWEIGHT_EVALUATION
implementation_status: V3_CODE_PRESENT_EFFECT_UNVALIDATED
evaluation_scope: FIXED_DEVELOPMENT_CASES_ONLY
formal_evaluation_status: DEFERRED_BY_USER
product_scope: OUT_OF_SCOPE
dataset_policy: UPSTREAM_DATA_UNMODIFIED_LAB_ADAPTS
llm_judge_provider: VLLM_ONLY_WHEN_REQUIRED
baseline_commit: 5f233a16829b9c2db603153b0e7d28dd6edb2188
source_plan: ../../MiLAi-Product/docs/cleanup/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_PLAN_v1.2_20260923.md
source_plan_sha256: 597be86070b005f78b56c2527bc0ef45dac7fefae908c30f1c92c60462b28704
supersedes_goal_sha256: aa0de72c4e67d3b16d8e686fa5527fc935ca80cd2f7fcf3a92c2c67cd494ef7d
development_mode: LEAD_WITH_TWO_SCOPED_WORKERS
---

# MiLAi 情境化用户记忆：完整 Lab 开发与轻量效果检查 Goal

> 历史版本：当前开发以 [Goal v3.0](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v3.0_20260923.md) 为准。下文保留原设计与阶段记录；其中全量评测、完整测试套件及仅限旧四题的安排不再约束当前 Goal。新范围为完整 Lab 能力开发、多个候选的小规模原生 benchmark 比较，不包含 Product 迁移。

**目标：完整实现本 Goal 定义的 Lab 情境化用户记忆能力，再用已有公开测试集评价。测试集保持原样，由 MiLAi Lab 适配其输入、执行与评分协议；需要 LLM Judge 时统一使用 vLLM。**

执行顺序为：**完整 Lab 方法与运行时开发 → 数据适配及评分接线 → 少量工程联调 → 固定版本的正式评估 → 结果分析与 Lab 交付。** 本 Goal 不安排 Product 迁移、接口映射、数据库变更或迁移准入，不以未来产品形态约束当前 Lab 设计。

**用户于 2026-09-23 调整本轮执行范围：先轻量化跑通部分实例并查看效果，开发完全完成后再做大规模测试。当前只使用已经固定的四道开发原题及已有历史快照；本轮交付开发状态、小样本结果和实际问题，不以全量评测作为当前交付门槛，也不自动恢复大批次。** 已启动的 formal-v2 已停止，原始输出和成本保留。下文全量规格保留为后续正式评估协议，不表示本轮仍要继续执行。

本文内容更新为 v2.4，保留现有文件路径。它替代上一版的 Product 迁移阶段、8＋4 段自建场景验收和迁移收益阈值。[开发计划 v1.2](../../MiLAi-Product/docs/cleanup/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_PLAN_v1.2_20260923.md)及[历史 Goal](archive/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v1.2_20260923.md)仅提供背景；本轮范围、数据约束与完成条件以本文及上述用户范围调整为准。当前实现、模型联调、数据下载修复与未完成项见[结果说明](CONTEXTUAL_USER_MEMORY_RESULTS_20260923.md)。

**源码诊断修正了 v2.2 的完成判断；已有四题交付保留为历史结果，开发继续推进。** R0 核心修复及其确定性验证已记录。此次重新读取工作树，方法已到 `contextual-user-memory-v3`，批量摄取、普通回合 schema 约束、重复读取回执、片段混合检索、embedding 身份绑定、原文检索臂和答案冻结均已有代码，不再重复列为待建。源码存在不代表这些接线已完成真实 Host 验证，旧四题成绩也不属于 v3。

v2.4 在前轮四个项目的基础上，详细读取用户提供的本地 ReFind、ReMe、OpenViking，新增 §3.5–3.8 和 §8.3。确切版本、入口、默认路径与本地 fork 的区别集中记在结果说明的“本地 ReFind／ReMe／OpenViking 源码增补”。本次只更新设计文档，不启动模型或正式批次。

## 1. 开发原则与范围

1. **分增量实现，按完整范围交付。** 复用 Lab 的 Workspace、经验卡、Revision、Attention 和 checkpoint，逐段打通；三个演示场景或 CRUD 跑通不能代替完整开发。
2. **让 Host 表达意图。** 保存来源、记下理解、修改记录；不要求模型先判定正文属于 Evidence 还是 Note，也不增加分类 Agent。
3. **先完成开发，再正式评估。** 适配器与方法可并行开发，单元检查随实现运行；正式对照在完整功能和评测接线稳定后启动，不拿局部收益作为其余功能的开工条件。
4. **结构随实际代码收敛。** 使用有限类型、直接函数和一个装配入口；真实重复出现后再提取。不先建设通用后端、工作流、注册中心或跨对象事务框架。
5. **减少防御性编程。** 外部输入在入口解析；来源绑定和版本比较放在实际操作边界。内部依赖明确类型，不反复判空、吞异常或叠加兜底重试。
6. **减少协调和审查。** 普通实现、修复与相关验证连续完成，不设置常驻 Reviewer、逐阶段审批或多份准入报告。一份 Goal、一份运行清单、一份结果说明足够。

“完整 Lab 开发”指本次情境化用户记忆的下列全部能力，不是把仓库所有历史研究、RL 或多模态项目一并重做。以下项目均为本 Goal 的必交项，不能降格为未来待办：

| 能力 | 完整交付行为 |
| --- | --- |
| 统一记忆操作 | Host 可保存来源、记下理解、修改记录，并统一搜索和读取，无需选择 Evidence／Note |
| 来源与版本 | 原文、作者整理和实际来源身份分开；引用准确版本，修订可追溯，来源复用且不重复计为独立佐证 |
| 用户情境 | 区分当前用户与第三方、长期条件与临时例外、明确陈述与有不确定性的隐式理解；实际“不记住”要求影响持久化与后续使用 |
| Revision | 根据实际后续信息修改内容、主体或适用范围，保留原文与历史，更新当前采用的版本 |
| State ↔ Attention | 当前状态实际影响查询、选源和材料展开；新材料再改变状态，不能只生成一段静态摘要 |
| 检索与材料组织 | 来源和整理均可发现；接通语义检索、准确读取、完整语义单元、预算与去重；索引和缓存对应实际版本 |
| 持久化与续接 | Lab 本地保存、进程重启恢复、同用户任务切换／显式交接，以及用户间状态隔离 |
| 原生数据集评估 | 三类指定数据适配、真实 vLLM Host、确定性评分／vLLM Judge、可恢复批量运行与完整结果汇总 |

## 2. 以现有 Lab 能力作为起点

下面是基线代码能力与本轮新增工作，不能将前者的存在解释为新方法已经有效。

| 现有位置 | 可直接复用的能力 | 本轮补充或注意事项 |
| --- | --- | --- |
| [controlled_workspace.py](../src/milai_lab/methods/controlled_workspace.py) | MemoryCard、WorkspaceSnapshot、稀疏 patch、引用检查、局部版本与可逆修改 | 卡片已有 source_refs 和 revision，允许无来源记录；补统一操作与明确的来源／加工语义，避免另造一套卡片模型 |
| [reasoning_bank.py](../src/milai_lab/methods/reasoning_bank.py) | ExperienceBank、embedding 回调、向量选择、会话与恢复基础 | 复用检索与跨任务记录；补当前记录版本和来源发现，不覆盖旧研究配置 |
| [experience_revision.py](../src/milai_lab/methods/experience_revision.py) | 经验卡修订、已读版本检查、历史版本与当前采用记录 | 将明确用户更正和适用范围变化接入这条路径；本地版本检查不冒称 PostgreSQL 并发保证 |
| [state_attention.py](../src/milai_lab/methods/state_attention.py) | 状态引用、来源选择、覆盖缺口与有界展开 | 当前状态字段主要保存引用与 provenance；实际选源使用 memory_intentions／open_conflicts。可用的情境正文和其他字段作用仍需实现 |
| [workspace_control.py](../src/milai_lab/methods/workspace_control.py) | 工作状态维护、Actor 与实际反馈循环 | 借用已有操作机制；不强制每轮增加 Controller 或语义审查模型 |
| [dataset registry](../src/milai_lab/datasets/registry.py) | 外部数据路径、split 与 SHA-256 校验 | contextual 三类适配及清单现已存在；后续扩展顺序元数据，不创建修改后的数据副本 |
| [answers scorer](../src/milai_lab/scorers/answers.py) | 通用 EM／F1 | 仅作诊断；其标识明确说明不是官方 LongMemEval 分数 |

既有 joint runtime、Revision 研究批次和冻结配置维持原语义与结果。新 Goal 使用独立候选版本与配置；可以复用其组件，不能静默改写历史臂、续跑旧批次或借用已关闭预算。[历史状态](LAB_CURRENT_STATUS.md)继续保留。本文不要求重新走旧批次的审查链。

## 3. 完整 Lab 实现设计

### 3.1 三种角色，共用操作入口

| 角色 | 保存什么 | 允许怎样改变 |
| --- | --- | --- |
| 来源记录 | 适配器实际取得的消息、文档或工具结果及取得信息 | 保留当时内容；取得错误通过明确替代关系修正，不悄悄重写历史 |
| 可修订记忆 | Host／用户维护的理解、条件性偏好、经验或独立想法 | 根据已经读到的目标版本修改，记录前后版本和可选依据 |
| 当前 Workspace／State | 当前问题、适用情境、暂时采用的理解、下一步与相关引用 | 按当前任务局部更新和恢复；临时选择不自动改成长期用户属性 |

它们是处理职责，不要求立即新增三张表。优先扩展现有 MemoryCard／Workspace 及本地 checkpoint。一个来源可关联多份整理，一份整理可引用多个来源；独立想法允许没有来源。来源证明收到过什么，不自动证明正文为真，长期使用和检索频次不改变这一点。

Lab 提供简洁的 `memory_search`、`memory_read`、`memory_save` 工具外壳，名称与字段在 L1 用一组调用示例确定；只定义 Lab 的方法合同。

| Host 意图 | 最小输入与行为 |
| --- | --- |
| 记下理解 | 内容、可选来源引用；默认作者为实际调用 Host，创建可修订记录 |
| 保留来源 | 适配器已发布的 source_ref；准确取得并保留已有内容，不让模型重写原文或自填可信角色 |
| 修改记录 | 读取返回的 target_ref 和新内容；引用携带已观察版本，冲突返回给 Host，不偷偷换成最新版本覆盖 |
| 原文加整理 | source_ref 与整理内容；复用来源并关联记录，分步呈现实际结果，不承诺跨对象原子写入 |

使用小型分派函数连接现有方法，不加后端注册器。工具回执给出可直接复用的引用、版本、作者／加工说明和来源入口。Host 不构造数据库类型，也不猜并发版本。

### 3.2 来源、版本与检索

- 来源身份由取得内容的程序绑定。用户消息、工具回执和 Host 生成文本分开记载；正文中的“用户说”不能改变作者。数据集消息同时记录上游制品／事件身份和原始角色，不把离线历史冒充本次现场发言。只拿到转述时仍允许保存，记录为 Host 转述。
- 引用可定位材料不等于材料支持全部推论。混合原话、分析与计划的记录默认按作者整理处理；只有实际核对的摘录才声明原样引用。
- 当前记录、读过的版本与来源之间建立明确联系。来源保留和整理更新可各自成功或失败，回执不得伪报整体成功；重复请求复用已有可确认结果。
- 发现与读取复用 Lab 已有候选检索路径，统一返回后再按需展开来源。相同来源的摘要不计算为多份独立佐证；相同正文的不同观察事件不因文本相同而合并。
- 依赖发生变化时，下一次呈现重新解析当前记录及其相关版本。需要修订的整理明确标识，避免旧缓存继续冒充当前理解；失败和未覆盖的检索路线保留可见状态。

复用现有 embedding 与向量选择，实现来源／整理的统一发现、按版本读取与有界材料包。检索索引是派生物，修改后更新对应项，返回前解析真实对象版本；不将语义发现、当前版本解析或来源展开留到另一个 Goal。暂不需要通用依赖传播平台或新图数据库，直接维护当前方法实际使用的引用关系即可。

### 3.3 情境、Revision 与 Attention

State 中保留足够的情境正文和引用，使“本次客户汇报只要结论”与“技术讨论需要展开”可以同时成立。状态更新采用现有稀疏操作，不要求每轮重写完整画像或给每句文本贴标签。

隐式理解可表达为带来源、主体、情境和不确定性的记录，不能直接升格为永久人格属性。主体和“不记住”等意图从合法对话中理解，不能读取测试集的 `who`、目标 preference 或隐私标签来替 Host 作答。原始 benchmark 文件仅是评测输入；数据集保存在外部目录不等于允许方法把所有内容永久写入自己的用户记忆。

实际收到的新反馈直接进入当前交互。Host 可据此修订错误概括或缩小适用范围；来源历史保持可核对。Attention 根据当前任务选择适用记录和必要原文，Revision 修改持续维护的表达，两者不借检索排名提升权威。

恢复时重新核对声明依赖的身份和版本；暂时不用某条记录只改变当前状态。同用户交接使用可恢复快照和准确引用，新 Host 在自己的当前任务中采用；不同用户的记忆互相隔离。确定性解析、来源绑定和版本检查由代码完成，语义判断由当前 Host 表达。离线答案判分另按 §6 使用 vLLM Judge，不将 Judge 嵌入在线记忆控制链。

### 3.4 代码组织

| 位置 | 实施职责 |
| --- | --- |
| Lab `src/milai_lab/methods/contextual_user_memory.py`（已有） | 来源、记录、State、版本操作与工具分派；继续复用 Workspace／Revision／Attention |
| 同目录 `contextual_retrieval.py`、`contextual_materials.py`（按 §8.3 新增） | 将已有索引排序与新材料组装分别收敛为小型纯方法模块；前者处理候选，后者处理顺序、范围和预算，不新增服务层 |
| Lab `tools/contextual_host_adapter.py`（已有） | vLLM 协议、生成约束、实际工具回执、调用预算与无进展退出；维护当前请求上下文，I/O 留在工具层 |
| Lab `tools/contextual_ingestion.py`（已有） | 一个历史批次的一次有界 Host 提案及逐项真实操作；相关记录由核心提供，允许空提案和部分失败 |
| Lab `tools/run_contextual_user_memory.py`（已有） | 单一装配入口，发布合法历史、选择实验臂、持久化与恢复、冻结答案后评分 |
| Lab `src/milai_lab/datasets/` 与 `scorers/` | 三个数据集的字段解析、合法历史视图、结果格式与确定性评分；目标答案只进入评测侧 |
| Lab `tools/` 中的 vLLM 传输与判分适配 | 复用可用调用代码，接官方 rubric；Host／Judge 分离请求和记录，不复制旧整套 runner |
| Lab `tests/unit/` | 复用邻近用例，只补新语义的关键回归 |
| Lab 被忽略的 artifacts 目录 | 请求、回执、checkpoint、模型输出和运行用量；Git 仅保留精简配置／清单与结果说明 |

后端采用 Lab 自身工作区、经验库和本地 checkpoint，完成保存与新进程恢复。`src/milai_lab` 保持纯方法边界，不导入 Product、SDK 或历史模块。没有新框架的实际需求时，用有限类型、普通函数和一个 runner 完成装配。

### 3.5 本地项目的复用决策

下表是源码支持的设计来源，不是三个外部后端的接入清单。逐项证据及限制见[结果说明](CONTEXTUAL_USER_MEMORY_RESULTS_20260923.md)。

| 来源 | 实际值得复用的机制 | MiLAi 已有基础与新增范围 |
| --- | --- | --- |
| ReFind：`app/store.py`、`bm25.py`、`retriever.py` | 保留会话顺序；BM25 片段排名与会话排名融合；命中附近消息展开；一次检索循环内排除已返回 anchor | v3 已有字符片段及 lexical/vector RRF；新增稳定消息序号、真正的 BM25、时间约束和邻接读取。会话排名作为单独可关闭的假设，不再加一个检索 Planner LLM |
| ReMe：`steps/index/search.py`、`local_file_store.py` | 派生片段的关键词／向量召回与 RRF，带原文件范围回读 | 复用算法和范围语义；保留 MiLAi 来源与版本对象，不改成文件即唯一权威。默认配置未启用 embedding 时实际只有关键词路径 |
| ReMe 本地 fork：`search_v2.py`、`_source_format.py` | 重叠／相邻会话行区间合并、工具上下文去重 | 在 MiLAi 的准确来源版本上做范围合并，解决不同 query 返回重复材料；不能称这些是 ReMe 默认路径已启用的能力 |
| ReMe：`auto_memory.py`、`dream/extract.py`、`dream/integrate.py` | 当前会话增量整理；从变更内容查相关旧记忆，再提出创建或修订 | 在已有一次批量提案内优先复用旧记录并保留条件；独立整理至多作为显式有界实验开关，不启动后台多轮 Dream 流水线 |
| OpenViking：`retrieve/context_assembler/` | 先给多个候选提供紧凑视图，再用剩余预算展开；只读取计划所需的层次；记录实际呈现的内容 | 新增确定性的材料规划器和当前任务呈现账本；复用现有整理及原文范围，不为每条消息生成多份 LLM 摘要 |
| OpenViking：`session.py`、`semantic_sidecar.py` | 先保存原始会话再产生派生记忆；摘要带来源与生成信息 | 复用 Lab 现有来源发布、checkpoint 和版本依赖；不引入队列、虚拟文件系统或 Agent 训练链 |

ReFind 为 MIT，所读 ReMe 为 Apache-2.0，所读 OpenViking 为 **AGPL-3.0**。后续若适配前两者的具体代码，标注来源并保留相应版权／许可；OpenViking 本轮用于机制参照，按 MiLAi 现有对象实现材料规划，不复制其实现或新增运行依赖。本地 ReMe 没有 `.git`，包版本 `0.4.1.6` 不能替代提交身份；引用区分默认实现和明确标注的 local fork。

### 3.6 检索：定位会话、命中范围，再按需展开

**先让输入可准确定位。** 在现有 Observation／adapter 上补稳定的原始消息序号，构成 `user → artifact → session → ordinal → source_ref` 的定位关系；序号来自合法输入顺序，不从 event ID、文本相似度或模型推断。保留原始日期及其粒度，缺失则为未知；没有 session 的来源保持独立，不把所有未知来源拼成一个会话。此目录属于派生元数据，不改上游数据文件。

**在已有混合检索上补缺口。** v3 的 lexical 路径目前是子串计数，尚非 BM25。将其替换为有 IDF 和长度归一化的 BM25；沿用已有向量缓存与 RRF，再按原始来源聚合，避免同一长消息的多个窗口占满候选。保留一个来源内多个不同命中范围供材料规划，不只保存单个窗口。BM25 索引随当前来源／记录版本失效并按需重建，使用简单缓存，不引入新的数据库。中文／英文采用可声明的通用分词策略；不照搬 ReFind 的英文 stopword／词干表，更不按测试答案添加词表。

ReFind 的会话排名来自正分 chunk 分数求和。MiLAi 可增加一个独立的 session 排名项，但应先按原始来源去重，并限制单个长会话的贡献；具体聚合策略是本项目待验证的设计，不能写成 ReFind 已提供的保证。该项默认关闭，只有固定开发比较支持时启用。来源与其多份整理共享出处，不能因此多算若干次“支持”。

工具仅增加必要的可选参数，以下是**拟议 Lab 合同**，当前 v3 尚未提供：

```text
memory_search(query, limit, max_bytes, session_id?, date_from?, date_to?)
memory_read(ref, include_sources?, start?, length?, before?, after?, date_from?, date_to?)
```

不填筛选时，仍可发现全部合法历史。日期范围约束来源发生时间，不等同于偏好的生效区间；关联整理通过匹配的依据进入候选，并说明时间命中来自依据。显式日期范围只匹配已知日期，未知日期另记未覆盖数量，Host 可去掉筛选查找；非法日期在入口返回一次明确错误，不默默放行。`question_date` 可提供时间语境，不能自动转成“只找这一天”。

`before/after` 表示同一 session 中原始消息的数量，不是字符数；先读取 anchor，再按原始顺序补邻接。它与当前长 source 的字符范围读取并存。用户隔离、合法历史截止点和本次显式筛选同样约束 anchor 与邻接，不能通过展开读到未来或其他会话。筛选作为本次调用参数进入材料函数，不从前一个无关查询中隐式继承；不填日期时可以读取全部合法来源。邻接中超出预算的消息返回准确入口，可继续分页；不把截断文本声明为完整来源。检索／展开由同一 Host 的现有工具循环控制，不叠加 ReFind 的独立 Planner。

### 3.7 材料：预算内呈现，跨查询复用

采用一个普通函数完成 `候选 → 合并范围 → 规划视图 → 读取必要内容 → 返回材料`。输入包括候选、当前版本、已有任务呈现记录及预算；输出材料、未展开入口、各路实际状态和消耗。版本检查继续由现有记忆核心负责，材料函数不再建立第二套对象或权限系统。

| 视图 | 内容与边界 |
| --- | --- |
| 入口 | 准确 ref、来源／作者、版本、可展开范围；没有正文就不能算已读 |
| 紧凑视图 | 已有短记录的完整内容，或原文中的准确命中范围；分别标明作者整理与原文摘录。缺少摘要就用摘录，不临时调用 LLM 压缩 |
| 展开视图 | 按需要取得完整记录／来源或同会话邻接消息，保留顺序、出处与范围；超长来源允许明确分页 |

借鉴 OpenViking 的分配顺序：先保证相关候选有可用的紧凑视图，再把剩余预算用于关键项展开；为单项设限，避免一条长消息吞掉全部上下文。范围尽量按消息／段落边界返回；无法完整容纳则降级为明确的摘录或入口，不隐藏遗漏。当前精确字节预算继续有效，计入返回外壳；若接入运行环境已有的 Host tokenizer，额外计算 token 预算，缺失时不伪称精确 token 控制，也不为此另建 tokenizer 项目。

**去重按出处、版本和范围处理。** 对同一来源版本的相交／相邻区间求并集并按原始顺序呈现；不同来源事件即使正文相同也保留身份。可共享显示一份重复正文，但要列出不同出处，不能借正文 hash 抹掉事件。摘要与原文可以互相链接，不能把它们计为两份独立证据。

任务内维护小型呈现账本，键至少包含 `task_id + ref/version + range + view`。只登记实际交给 Host 的正文；先前给过一个摘录不等于整份来源已经读完，已读一个片段也不排除整个 session。换 query 时优先返回新增范围，旧材料用先前回执入口表示；新版本、此前未展示的范围和更深层读取仍可返回。当前 Host 的相同参数读缓存保留，两者分别解决相同动作重试和跨动作材料重叠。

账本是当前上下文的优化，不是长期记忆，也不复用为 CAS 的 `seen` 或 coverage 充分性判断。新任务清空；恢复／裁剪 Host 上下文时，已不在上下文中的正文必须允许重新取得。只恢复记忆 checkpoint 而未恢复完整对话时，不恢复“已经呈现”的抑制状态。

### 3.8 整理：在现有批量提案内维护当前理解

当前 `ingest_chunk()` 已把合法相邻输入和相关旧记录交给同一 vLLM Host，一次返回多项操作。借鉴 ReMe 的增量思路，下一步围绕**这次实际变化了什么**提供相关旧记录，而不是重写全部画像：能够更新已有理解时使用已读版本，内容没变化允许空提案，临时例外保留范围；历史来源不变，派生理解通过既有版本路径修订。

一轮提案中的操作顺序执行并返回各自结果，失败不伪装为整体回滚，也不让后续操作引用还没有真实回执的新对象。合并重复表达优先修订已读记录并在检索呈现时合并共同出处；**不使用 `forget_refs` 作为去重捷径**，因为遗忘可能连带删除依赖。实际“不记住”要求仍执行现有生命周期，不被整理任务忽略。

外部工具提供的原始结果可保留其真实角色；MiLAi 自己的 search/read 回执不是新发生的外部事实，不应再摄取成独立来源。ReMe 对 tool result 的过滤提供了防止自我引用的线索，但 MiLAi 不应删除所有工具消息。用户偏好与 Agent 操作经验按现有主体／情境分开表达，不新增强制分类工具，也不把测试解答或 Judge 反馈变成用户画像。

仅当一次提案仍产生实际重复或冲突时，允许显式开启一次针对本批变更及相关旧记录的有界整理提案；与摄取一起计入调用和 token 预算。默认不加夜间 Dream、逐命中压缩或反复自我反思。持久化继续用现有 runner/checkpoint，保存来源和写入派生记录的进度分别真实记录；不为此移植 OpenViking 队列或 ReMe Agent 工作流。

## 4. vLLM Host 与运行方式

vLLM 承担被研究的 Host。开发 Agent 的 Sol／Luna／Astra 分工与该 Host 模型分开配置、分开记录费用；不把 OpenAI reasoning 档位直接套到 vLLM。

薄驱动完成：输入实际对话 → 模型选择工具 → 调用 Lab 真实函数与存储 → 回传实际结果 → 模型继续任务。优先使用端点已有的原生工具调用能力；若使用显式 JSON-action，则在运行配置标明。可参考[现有 vLLM runner](../tools/run_v02_local_vllm.py)的接线，不能将其旧工具集视为新路径已打通。

每次运行记录候选版本、Host 模型／配置、原始 case ID 与历史边界、真实工具轨迹、最终回答、可取得的 usage 和耗时。调用次数、输出长度、并发和超时集中配置。支持按题续跑已固定的批次、复用未变化的历史构建与 embedding，失败不触发整批重算。端点不可用时继续独立开发，模型验证保持未完成，mock 不充当效果证据。

按[现有实验臂合同](../src/milai_lab/contracts/arms.py)使用 `RESEARCH_PROTOTYPE` 描述本 Goal 的真实 Lab 方法运行；只验证模拟机制时用 `SIMULATION`。公开数据为合成或真实采集是另一项数据属性，不因使用真实 vLLM 而改变。历史实验的状态、结果和旧预算不续用，本 Goal 单独记录自己的版本、数据覆盖与执行结果。

## 5. 选定测试集，由 Lab 适配

### 5.1 默认评估组合

本次已核查以下官方来源。选择固定文本规格控制成本，不要求把所有长窗口、多模态和新版本一并跑完。

| 测试集 | 本 Goal 使用范围 | 主要检验内容 | 主评分 |
| --- | --- | --- | --- |
| [PersonaMem-v1](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v1/blob/main/README.md) | `questions_32k.csv` 与 `shared_contexts_32k.jsonl`；正式结果覆盖所固定 32k 文件全部问题 | 当前偏好、偏好演变、更新原因与跨情境响应 | 原生多选答案匹配，无需 Judge |
| [PersonaMem-v2](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/blob/main/README.md) | `train_text` 开发、`val_text` 选版本、`benchmark_text` 正式评估；使用原生 32k 历史，benchmark 数据卡列出 5,000 个问题 | 隐式偏好、主体归属、更新和“不记住”请求 | 原生 MCQ 为主；开放回答另按固定 rubric 使用 vLLM Judge |
| [LongMemEval-S cleaned](https://github.com/xiaowu0162/LongMemEval) | 官方发布的 `longmemeval_s_cleaned.json` 全部 500 题 | 多会话回忆、时间推理、知识更新和拒答 | 官方按题型 rubric，经 vLLM Judge 评分 |

还核查了 [LoCoMo](https://github.com/snap-research/locomo) 的公开长对话与 QA 数据。它可作补充，但本 Goal 默认先完成上述三类适配与评估，不把接入更多测试集本身当作开发成果。PersonaMem 的 128k／1M、v2 多模态和其他基准不属于本轮完整覆盖承诺；v2 自由回答为可选诊断，必跑主表采用 MCQ。

活动 Lab 的 [contextual adapter](../src/milai_lab/datasets/contextual.py) 及三个 contextual manifest 已存在：[PersonaMem-v1](../data/manifests/contextual-personamem-v1.json)、[PersonaMem-v2](../data/manifests/contextual-personamem-v2.json)、[LongMemEval](../data/manifests/contextual-longmemeval-s-cleaned-500.json)。当前入口为 [contextual runner](../tools/run_contextual_user_memory.py)，原生评分接线在 [contextual scorer](../src/milai_lab/scorers/contextual.py)。后续只补所需顺序元数据，不重复建设 loader；旧 LongMemEval runner／Judge 不代表这条新路径的协议。

### 5.2 测试集保持原样

1. 从官方发布制品取得数据，固定 revision、文件名、SHA-256、split、样本数和许可来源；原文件只读保存在 Git 外。使用上游已发布的 cleaned 版本不等于自行清洗测试集。
2. 不改正文、角色、顺序、时间、问题、答案、候选选项或标签；不补写对话，不添加更正场景，不删除难例，不按候选结果筛题，也不重生成“更适合 MiLAi”的数据。
3. Lab adapter 只做格式解析、身份映射、官方历史边界选择和模型输入／评分输入分离。输出单独保存，绝不回写上游 CSV／JSON。开发小样本只用外置 ID 清单选择原题，不创建修改后的测试集。
4. 全部合法历史须向方法可用。模型窗口不足时，由 MiLAi 自己顺序摄取、检索和组织上下文；不能在适配器中预先删掉干扰会话、截成易题或偷偷改成 oracle 输入。
5. 数据不支持的字段或格式由 Lab 修复适配。疑似原始数据问题保留原题并记录，评分按固定上游规则处理，不手工“纠正”答案。
6. 单元测试可以用最小工程 fixture 验证解析和版本行为；它们不替代公开测试集，也不计入 benchmark 成绩。用户要求适用的是所有正式评估数据，不禁止必要的代码测试。

### 5.3 每个适配器遵守原生协议

**PersonaMem-v1：**按 `shared_context_id` 取得历史，只允许 `history[:end_index_in_shared_context]`，上界排他。Host 可见题目、原生选项和截止前的原始历史；`correct_answer`、证据定位和诊断标签留给评分器。保留上游问题与选项顺序。该边界来自[官方格式说明](https://github.com/bowen-upenn/PersonaMem)。

**PersonaMem-v2：**按原始 `chat_history_32k_link` 读取历史，接入 `user_query`，保留原来的 train／val／benchmark 划分；不能把问题行任意串成带正确答案反馈的用户轨迹。MCQ 的正确与错误候选按[上游 MCQ 组装协议](https://github.com/bowen-upenn/PersonaMem-v2/blob/d29d91d016add354e459dfeb0d24af08bc402e2a/inference.py)生成未标答案的选项，固定同一排列供所有臂使用；这是运行时任务格式，不修改数据。复用时固定随机状态并保存映射，避免 Python hash 或并行调度导致排列漂移。不复用其中超窗口时删会话的 fallback，也不添加候选专属提示。

v2 的目标 preference、`who`、更新／隐私标签、完整 raw persona 和正确性标记仅供评分与分组。选择题候选本身可按原生协议交给 Host；“哪项正确”的映射不得交给方法或持久化记忆。官方 MCQ 与自由生成分开运行、分开报告，不拿一次看过候选答案的执行再评自由生成。

**LongMemEval：**保留原始 session、日期和消息顺序，问题时间使用 `question_date`；方法只接收合法历史和 question。`answer`、`has_answer`、`answer_session_ids` 以及拒答／题型标签只在评分侧使用。`question_id` 用于执行与结果对齐，其 `_abs` 等线索不放入 Host 提示或可读来源句柄。输出匹配原生 `question_id`／`hypothesis`；不用 oracle 版替代全历史测试。[上游数据与输出格式](https://github.com/xiaowu0162/LongMemEval#-testing-your-system)

**共同执行规则：**先按原始历史形成记忆，再回答当前题目；同一历史可共享相同合法截止点的构建缓存，各题从独立 Workspace 副本执行。题目、选项、模型答案和 Judge 反馈不回写为其他测试题的历史。缓存绑定数据身份、用户／历史、截止点、方法及模型配置；不能先用未来消息形成摘要或索引，再只过滤原文。允许完整历史顺序摄取及分批运行，不生成新的跨题时间线。

原生 QA 分数只说明这些任务上的表现。恢复、交接、版本依赖等能力用工程检查验证，不能通过改测试集增加标签后，声称它们是官方 benchmark 已覆盖的能力。

## 6. 评分与正式评估

### 6.1 需要 LLM Judge 时仅使用 vLLM

选择题优先采用原生解析与准确答案匹配，格式错误明确计入结果，不让 Judge 猜一个更有利的选项。自由回答需要语义判分时，通过 **vLLM 服务**调用 Judge，不直接请求托管商业 Judge，也不用开发 Agent 人工代替整个评分器。

LongMemEval 保留[官方 `get_anscheck_prompt()`](https://github.com/xiaowu0162/LongMemEval/blob/main/src/evaluation/evaluate_qa.py)的题型规则与拒答分支，只适配传输到 vLLM；现有通用 EM／F1 和本地 Qwen rubric 不冒充官方指标。若运行 PersonaMem-v2 自由回答，采用固定的[上游 narrow／broad 评分定义](https://github.com/bowen-upenn/PersonaMem-v2/blob/d29d91d016add354e459dfeb0d24af08bc402e2a/inference_utils.py)，明确实际选择与调用次数，不把几种分数混成一个总分。

Judge 配置与 Host 分开声明：`base_url`、模型／权重版本、chat template、temperature、输出上限与并发。默认一套固定 Judge，不建多模型投票委员会；确定性题不消耗 Judge 调用。可以共用 vLLM 实例，但使用隔离的请求与会话。若权重也相同，结果标明同模型自评，不能声称独立模型验证。

先冻结 Host 回答，再判分。Judge 只接收评分所需的问题、参考答案／rubric、候选回答；不展示方法名和期望胜负，不允许其修改答案、数据集或记忆。评分标注和评估反馈不回流测试中的 Host。解析失败、超时与正常判错分开记录，有限重试保留原回执；仍未解决的判分不偷偷当作正确或从分母移除。

保留原生评分定义不等于复现官方排行榜分数。更换为 vLLM 上的具体 Judge 后，报告写明“官方 rubric＋指定 vLLM Judge”，同一 Judge 下比较各臂，不直接与采用另一 Judge 的官方数字作等价排名。全部 Judge 调用和 GPU／tokens 成本单独列出。

### 6.2 执行范围与成本控制

默认比较 **RAW_RETRIEVAL、BASELINE、CANDIDATE**，使用同一个 vLLM Host。当前 v3 runner 和开发配置已接入 RAW_RETRIEVAL：跳过 Host 历史整理，直接在合法原文上检索；它仍使用现有 embedding／混合检索，不能称为零模型或零 embedding 成本。BASELINE 保留正常记忆读写，CANDIDATE 增加情境 State／Attention；原文臂帮助辨认历史整理的增量价值。

各臂使用同一原题、合法历史、Host、共享检索配置及可比任务预算。整理和 State 是显式差异，历史构建的实际额外成本单列。BM25／材料组装等共同基础应在三臂接线一致，不把检索器更换的收益都归给 State。若需要归因某项新算法，只补一个预先声明的开关比较，不展开所有参数组合；纯 BM25 也须单独关闭 embedding 路径，不能仅改臂名称。

在 PersonaMem-v1 上另保留成本较低的 `QUERY_ONLY` 对照，直接量化历史利用的增量；它只改变对照臂可见历史，不改变数据。不能根据该对照答错与否事后筛题。其他数据集不再默认增加额外实验臂、多模型或全消融矩阵。

执行分为三步：

1. **开发联调：**用 PersonaMem-v2 train／val 的少量固定原题，以及其他适配器必要的少量原题验证格式、端到端调用和评分；暴露过的样本记录为开发使用。
2. **版本固定：**在开发／验证数据上完成实现和参数选择，固定方法、Host、Judge、上游文件、数据覆盖、模型调用预算及运行配置。一个清单即可，不设置批准环节。
3. **后续正式评估（本轮后置）：**开发收敛后另行启动，届时跑完 §5.1 指定规格的全部问题。允许分批、缓存历史构建和断点续跑；样本数从固定制品核对。开发 smoke 或一个好看的子集不能标为完成整套评价，运行受限时列出剩余数和未完成原因。

无官方 train／val 的数据不私自改成新发布 split。开发选题只记录在外置清单，正式全量结果中仍保留它们并披露暴露情况。原有 LongMemEval 历史使用也要标注，不能把再次评估声称为从未接触的 holdout；历史 runner 的旧批次准入流程不构成本 Goal 的额外审批。

固定测试结果用于报告。若看完后继续修方法，另记版本及数据暴露状态，不能把同一批题重新包装成未见验证，也不能把不同候选的最好逐题答案拼成一次运行。

### 6.3 输出有用结果

按数据集分别报告原生主指标、原有题型／类别分组、正确／错误／未完成数，以及相对基线的成对变化；不把 v1、v2、LongMemEval 拼成一个任意总分。多题共用一个用户历史时，说明聚合单位；若计算不确定性，使用现成按用户／历史分组的统计，不新增评测平台。

额外记录方法实际暴露的来源／版本问题、工具次数、总 tokens 和耗时。总成本包括历史摄取、记忆形成／修订、embedding、检索、答题、重试及 Judge；共享构建只记真实发生的次数。Host 与 Judge 成本分列，vLLM GPU 时间与 tokens 不伪装成商业 API 账单。

无法判分的结果报告覆盖率及未决数量，不冒称完整主分数；官方定义的格式错误等依其规则计分。缺失 usage 记未知，不为补数字另建 tokenizer。对原始错误和负面结果保留记录，不靠增加题目特例、改标签或更换有利 Judge 消除失败。

工程完成与效果结论分别给出。候选可表现为有改善、相当、退步或证据不足；完整实现加真实评估可以得出负面结论，不要求达到此前 1.2 倍／15% 的迁移阈值，也不启动任何 Product 阶段。

## 7. 多 Agent 开发与成本

### 7.1 按 Lab 模块并行

默认一名主 Agent 加两名执行 Agent；小任务用单 Agent。有额外独立数据适配切片或窄任务时才临时增加一名，本环境最多四个活跃 Agent（含主 Agent）。子 Agent 不自行扩队，不设常驻 Reviewer 或 Tester。

| 角色 | 独占写入范围 | 推进内容 |
| --- | --- | --- |
| 主 Agent | Goal 进度、最小调用合同、runner 装配、共同配置与结果说明 | 分工后继续实现集成；统一运行最终包检查和共享 vLLM 端点实验 |
| 方法 Agent | 分配的 `src/milai_lab/methods/` 模块及相邻测试 | L1 操作／来源／版本，随后 L3 情境方法、L4 检索与依赖 |
| Host Agent | `tools/contextual_host_adapter.py` 及其测试 | L2 工具循环与来源取得，随后 L4 持久化／续接接线；完成后可接续 L5 |
| 数据与评测 Agent（独立切片时启用） | 指定 `datasets/`、`scorers/` 模块及判分适配 | L5 的原始数据解析、字段隔离、原生评分与 vLLM Judge；不改语料和方法策略 |
| 窄任务 Agent（按需） | 明确指定的文件或只读范围 | 源码定位、字段映射、小型文档或机械修复，不承担开放式架构工作 |

先用一组请求／回执示例对齐两侧接口，再并行写代码；无需先完成完整设计评审。同一文件同时只有一名写入者，共享依赖、环境、Git 和装配由主 Agent 协调。重叠改动先交接所有权；仅在确有需要时建立 worktree。数据适配可独立并行，但正式效果评估须等完整方法稳定。上表是角色清单，不是同时启动人数；始终遵守四个活跃槽位上限。

### 7.2 使用用户指定的模型档位

| 工作 | 模型与推理强度 |
| --- | --- |
| 常规开发、主 Agent 集成、方法／Host／数据适配与评分实现 | **gpt-6-sol / xhigh** |
| 数据集、项目和测试集下载（用户本次明确指定） | **gpt-6-luna / high** |
| 其他范围明确的定位、映射、文档和机械修改 | **gpt-6-luna / max** |
| 已定位的疑难故障、关键设计冲突或跨层难题 | **gpt-6-astra / xhigh** |
| 实验中的 MiLAi Host | 单独配置的 vLLM 模型，固定后用于所有可比实验臂 |
| 必要的 LLM Judge | 单独配置的 vLLM Judge，按 §6 执行；不是开发 Agent |

不自行降低上述推理强度。已知难题可直接交 Astra；常规修复仍反复遇到同一推理障碍时，带最小复现和已尝试内容升级，不消耗多轮重复探索。解决后回到 Sol。Luna 遇到超出窄任务的语义工作就交接，不因单价低扩大职责。

成本优化靠减少无关上下文、重复实现、冲突和返工，不让多个模型同时解同一道题。只保留切片的实际模型／档位、可取得的用量、耗时与返工原因；不维护易过期的静态价格表或新成本平台。实际费率与服务档位以运行环境为准，包含主 Agent 协调和全部子任务用量。

主会话模型由环境决定，子 Agent 参数不能切换主模型。可配置的后续主会话按 Sol xhigh 组织；环境无法提供指定组合时明确说明，不静默换档。

### 7.3 小上下文分派与交接

任务说明只包含目标、准确允许写入路径、相关源码／合同、依赖、最小验证和交付物。使用独立模型时采用 `fork_turns="none"` 或必要的少量近期轮次；本会话的 `fork_turns="all"` 会继承父模型，不能同时覆盖模型参数。

以下为分派示例，不表示已启动代码开发；实际运行前先确认示例文件归属：

```json
{
  "task_name": "lab_memory_core",
  "model": "gpt-6-sol",
  "reasoning_effort": "xhigh",
  "fork_turns": "none",
  "message": "执行 Goal v2.4 的 R3a 检索切片。仓库 /cra/memory/mx_memory/MiLAi。先读适用 AGENTS.md、MiLAi-Lab/docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v2.0_20260923.md §3.6，以及 /cra/memory/mx_memory/ReFind/app/bm25.py 和 /cra/memory/mx_memory/ReMe/reme/steps/index/search.py。已有 v3 混合检索，不从零重写。仅写已交接的 MiLAi-Lab/src/milai_lab/methods/contextual_retrieval.py 与相邻定向测试；核心分派、adapter 和 runner 由主 Agent 接线。按已确定候选类型补 BM25 与范围候选，不改测试集、不加模型调用。返回文件、入口、实际验证和剩余接线问题。"
}
```

同职责续作复用原 Agent。交接给文件、接口、已跑命令与剩余问题，不在消息中复制整段实现。更换模型前停止原写入者；followup 不视为改变原 Agent 模型。主 Agent 等待时做不重叠集成，无独立工作就等待；协调开销变大则缩为一主一执行或单 Agent。

## 8. 开发顺序、必要检查与进度

### 8.1 按完整能力推进

| 阶段 | 交付内容 | 完成依据 | 状态 |
| --- | --- | --- | --- |
| L1：记忆核心 | 统一操作、来源快照、可修订记录、引用与版本 | 保存、读回、更正与来源关联形成真实闭环 | 已有实现；R0 修复和前轮确定性验证保留，来源顺序元数据按 R3a 扩展 |
| L2：Host 运行 | vLLM Host、真实工具分派、输入角色与回执 | 模型可连续调用 Lab 方法并完成当前任务 | v3 已有普通回合 schema、重复只读回执、无进展退出及一次批量摄取；本轮未作真实 Host 验证 |
| L3：情境方法 | 用户视图、临时例外、隐式理解、Revision、State ↔ Attention | 状态实际改变后续取材，新材料实际更新理解 | coverage／GAP 已修复；R2a 增量整理与修复后真实行为待验证 |
| L4：检索与持续使用 | 语义发现、材料包、当前版本解析、checkpoint、重启与交接 | 检索能取得当前可用内容，任务切换／新进程恢复可继续工作 | v3 已有重叠片段、lexical/vector RRF 及 embedding 身份；R3a 的会话／时间／BM25 和 R3b 的材料组装待开发 |
| L5：数据与评分适配 | 三个原始数据集 loader、不可见字段隔离、MCQ scorer、vLLM Judge、可续跑 runner | 原题可无改动执行，方法输入与评分输入分离，评分定义可核对 | 已有三类接线、RAW_RETRIEVAL 和答案批次冻结；新改动须沿用，不重建评测器 |
| L6：完整开发收敛 | 删除实际重复、补必要回归、运行包检查与少量原题联调 | §1 全部能力具备，接线可运行；不以演示代替完成 | 未完成；前轮包检查与四题记录保留，不作为本轮修改后的完整有效性证据 |
| E1：正式评估 | 后续冻结候选并跑完指定范围、三臂与必要 QUERY_ONLY | 原生评分、覆盖和实际成本完整记录，失败保留 | DEFERRED_BY_USER：formal-v2 已停止并确认 exit 143；67 个完成答案、15 份历史、0 失败记录保留，未评分 |
| D1：历史轻量交付 | 可复现轻量命令、小样本结果、开发状态、局限及实际问题 | 工程完成与小样本效果分别清楚，不冒称全量评价 | 历史交付完成：9/9 答题与评分完成；三道 PersonaMem 两臂均错、一道 LME 两臂均对。不是当前 v3 或 v2.4 规划的效果证明 |

L1 与 L2 在最小接口确定后并行，L3/L4 在现有结构上接续；L5 可由独立文件的 Agent 并行开发。E1 必须在 L1–L6 全部完成后开始。必要单元检查和少量格式联调随开发进行，不先铺大型测试平台，也不边看正式测试答案边补功能。

### 8.2 最少且必要的验证

优先扩展现有 [Workspace](../tests/unit/test_controlled_workspace.py)、[Revision](../tests/unit/test_experience_revision.py)、[Attention](../tests/unit/test_state_attention.py) 和 [dataset registry](../tests/unit/test_dataset_registry.py) 用例，不复制整套测试或为普通函数提取添加镜像测试。

| 改动 | 需要直接确认的行为 |
| --- | --- |
| 来源／版本 | 来源角色准确，整理修改不改原文，旧版本冲突可见，返回当前引用 |
| State／检索 | 情境实际影响选源，旧缓存不冒充当前版本，材料包保留条件与例外 |
| 持久化／隔离 | 新进程恢复取得已保存的记录与依赖，不同用户互不串用，交接不覆盖另一任务的局部状态 |
| 数据适配 | 原始文件摘要不变，截止点准确，Host／记忆输入没有 gold 字段，官方选项与评分映射一致 |
| Host／Judge | 工具调用与回执配对，评分使用已冻结答案，失败与正常判错区分 |
| 会话／范围 | 原始顺序稳定；日期未知不伪造，邻接不越过用户、会话和合法截止点；同来源区间合并，不丢不同观察身份 |
| 材料／整理 | 已呈现摘录不遮住未读范围和新版本；超预算显式降级；自己生成的检索回执不变成独立来源，整理不调用遗忘来去重 |

恢复和版本检查优先确定性测试；必要模型联调复用原有开发题，不另造一套用户故事 benchmark。超时、解析失败等工程问题按实际出现补最小回归，不先做全故障组合。

Lab 代码交付前集中运行一次既有检查：`uv run milai-lab-check-boundary`、`uv run pytest -q`、`uv run ruff check src tests tools`、`uv run mypy src/milai_lab`、`uv build`。平时先跑受影响用例；无新增改动、失败或未解问题时不重复全包检查。本文文档修改只做链接、内容一致性和格式检查，不触发模型批次。

### 8.3 v2.4 的实际开发切片

前轮 R0–R4 是历史诊断顺序，当前应从已存在的 v3 继续。以下必做增量用于完成原定检索、材料与修订能力；可选实验开关不变成全量矩阵或新的交付前置条件。

| 顺序 | 文件与具体交付 | 最小验证与额外成本 |
| --- | --- | --- |
| R3a：来源定位与候选 | 核心／dataset adapter 补稳定 ordinal；提取 `contextual_retrieval.py`，补 BM25、时间／会话候选约束、多范围命中与同会话邻接入口。session 排名开关默认关 | 用少量 fixture 联合覆盖顺序、缺日期、合法边界与不同命中范围；沿用当前向量缓存。新增逻辑不调用 LLM |
| R3b：材料组装 | 新增 `contextual_materials.py`，收敛当前 `_material` 与预算逻辑，实现区间合并、紧凑／展开规划；Host 接入当前任务呈现账本 | 验证重叠区间、已读局部后继续展开、新版本、预算降级和新任务重置；同一材料路径供各实验臂使用，不新增 reranker 或压缩 LLM |
| R2a：增量修订 | 在 `suggest_existing_records`／`contextual_ingestion.py` 内围绕本批新来源供给相关旧版本，保留空操作及部分失败；避免检索回执再摄取 | 验证一次提案可更正条件而不改原文，自己生成的材料不增加独立来源；默认仍一次 Host 调用，独立整理开关另计成本 |
| R4：固定版本轻量比较 | 主 Agent 整合既有 runner／配置，更新方法和 checkpoint 身份，再在原四题执行 RAW_RETRIEVAL／BASELINE／CANDIDATE；v1 保留既有 QUERY_ONLY | 先必要工程检查，后统一冻结答案与失败清单，再做原生判分／vLLM Judge。报告材料新增量、重复呈现量、错误与全部实际成本；不续写旧批次 |

并行按文件切分：主 Agent 用 Sol xhigh 负责核心、adapter、摄取与 runner；一个 Sol xhigh 负责检索模块，一个 Sol xhigh 负责材料模块。先约定小型候选／范围输入输出，再各自写独占文件。需要区间合并 fixture、链接校验等窄任务时，用 Luna max 接续空出的槽位；不让它独立决定时间或版本语义。Astra xhigh 仅用于已定位的跨层难题，不常驻评审。共享 vLLM 轻量运行只由主 Agent 统一调度。

本轮规划不运行三套外部服务。ReFind 可在确有归因需要时成为后续独立检索对照，但其只返回 evidence 的 Search 不能直接与 MiLAi 最终 QA 分数等价比较；需使用相同 Host、输入与预算。ReMe／OpenViking 的整套后端、后台精炼、目录递归和额外语料均不进入本轮必做范围。

## 9. 完成状态与下一步

- **完整开发完成：**L1–L6 全部交付，§1 的八项能力有实际实现与必要验证；数据适配和评分不能仍是占位接口。
- **评估完成：**指定数据版本及范围执行完毕，逐题输出、评分覆盖、原生指标、失败与成本可追溯；原数据摘要保持不变。仍有未执行题或未决评分时分别标明，不将局部结果标为完整评价。
- **本轮开发与轻量交付完成：**按用户最新范围，D1 给出可重复运行方式、开发状态、四道固定开发题的真实结果与实际问题。正式全量评价仍明确后置，不冒称已经完成。效果没有改善可以如实交付，不为追求正面结果改数据、换标签或堆叠审核。

完成记录只维护本表与一份结果说明。可以切回现有 Lab 基线，保留原始输入、已保存的研究记录和失败轨迹；不改写旧研究结论。需要继续优化时，明确下一项方法假设和已暴露数据，不无限扩测。

**当前状态：历史四题交付和 R0 修复已完成，v3 已有批量与混合检索接线，v2.4 新增规划尚未实现。** 接续 §8.3 的 R3a／R3b／R2a，再用固定版本做 R4；这次文档增补本身没有运行新实验。不得把源码存在或单元通过等同于记忆有效，也不为追求正面分数改数据。大规模测试后置，不自动恢复 formal-v1／formal-v2；保留中断输出与实际成本，不进入 Product。
