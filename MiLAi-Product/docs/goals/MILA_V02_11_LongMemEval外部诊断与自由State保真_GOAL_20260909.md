---
document_id: MILA-V02-11
version: "0.2"
date: "2026-09-09"
status: STOPPED_RESOURCE_OR_PROTOCOL_LIMIT
execution_scope: X0_ADMISSION_STOP_A0_DIAGNOSTIC_NOT_COMPLETE
execution_revision: 3
execution_stop_reason: NO_ELIGIBLE_FIRST_WAVE_NO_SUBSTITUTION
predecessor: MILA-V02-10-v0.5
predecessor_status: COMPLETED_BOUNDED_STATE_CONTROL_PILOT
predecessor_candidate_decision: KEEP_0.1.15_A0
priority: EXTERNAL_FAILURE_DIAGNOSIS_BEFORE_STATE_STRUCTURE
research_question: CONTEXTUAL_STATE_FIDELITY
baseline_mcp_version: "0.1.15"
baseline_runtime_version: "0.1.4"
baseline_client_version: "0.1.3"
baseline_catalog: compact-memory-v1
baseline_registered_tools: 8
baseline_policy: A0_NO_NEW_REGULATION
initial_v1_oracle_target_questions: 24
initial_v2_small_target_questions: 45
initial_total_target_questions: 69
evaluation_contract_required_before_generation: true
v2_backend_fit_required: true
sequential_branch_plan_required: true
new_state_schema_authorized: false
structured_binding_enabled: false
h4_schema_status: DEFERRED_NO_GENERAL_FAILURE_EVIDENCE
new_mechanism_enabled: false
intervention_stage_authorized: false
context_projection_enabled: false
model_transport_enabled: false
new_local_model_requests_authorized: 0
new_paid_model_requests_authorized: 0
new_judge_model_requests_authorized: 0
new_raw_tokens_authorized: 0
actual_model_requests: 0
actual_raw_tokens: 0
public_deployment_authorized_by_this_document: false
public_business_mutations_authorized_by_this_document: false
automatic_maintenance_enabled: false
research_baseline: A0
schema_status: 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE
---

# MiLAi V02-11：LongMemEval 外部诊断与自由 State 保真 Goal

## 1. 目标与授权

**先在外部、异质、未参与 MiLAi 调参的任务上观察 A0 的实际失败；
仅当关系、适用条件或控制信息的使用错误跨独立任务重复出现，
才研究保留关系上下文的自由 State，不从单个受控案例直接设计强绑定 Schema。**

研究工作名为 **Contextual State Fidelity**：需要保留多少关系上下文，
Host 才能在不同任务与新观察下正确重新理解 State，而无需刚性的领域字段？

本文原为文档规划；用户现已明确要求执行本 Goal、开发优先、权限直接通过、人工审查用
subagent review。已据此启动 X0 和资格门内的序贯 A0 诊断，具体范围见 Lab
`configs/v0211-external-diagnostic.json`。当前实际生成仍为 0；付费、额外 benchmark Judge、
S1/S2、Product 改动与旧受保护分区解封不在此执行范围内，旧 Goal 余额不继承。
首轮 metadata 审查发现 V1 500 题均已暴露或受保护，V2 旧 422 分区也不能作为新样本。
在其余 29 道图片题中按 metadata 哈希冻结 10 个 gotcha 候选，原 69 位置保留 59 个不足位。
subagent 来源审查判 4 近重复、5 UNKNOWN、1 限定范围可区分；首波固定题恰为近重复。
按 §6.1 资格优先且不替题，本次执行停在资格门，后续不启动；完整 A0 外部诊断尚未完成。
已完成 200 轨迹 / 5,095 状态 / 5,095 原图的完整导出和保真核验。独立零生成 X0 补充检查
用新建独占 PostgreSQL/API 和 18 次公开 MCP 调用验证两个合成 Notes/State 作用域及跨域拒读，
并通过源文件分页、字面搜索和原图数据块保真检查；自有服务已停止。逐题在线 backend fit 仍为
FIT_UNVERIFIED，模型实际图片呈现与答题未运行，不能据此声称模型理解图片或使用来源。详见
[准入停止报告](../../../MiLAi-Lab/studies/active/MILA_V0211_ADMISSION_20260909.md)。
不启用 H4、target_id / trigger / closure_basis 绑定机制、自动维护、Hint、图结构或 Reviewer。
保留 MiLAi 自有代码、0.1.15 / A0 / 8 工具和既有治理边界。

本 Goal 首先回答“值得改什么”，不是以完成某套新机制为验收目标。
若失败主要在来源或检索层，就停止本条 State 扩张，单独提出该层最小修复；
若找不到重复失败，就保留基线，不为了证明创新构造更刻意的案例。

v0.2 保留 v0.1 的架构、样本池和预算，收紧四项执行合同：生成前冻结评分、
V2 先过 backend-fit 门、机制候选与核心信号分级、首波后按预注册分支推进。
写入分账和条件性 S2/确认要求只补归因边界，不新增机制或执行授权。

## 2. 当前证据与历史保留

[v0.5 执行合同](MILA_V02_10_可纠正记忆调控与跨会话恢复_GOAL_v0.5_20260908.md)
及[执行报告](../../../MiLAi-Lab/studies/active/MILA_V0210_V05_RESULTS_20260909.md)
保持原文与原始评分，不追溯修改。

| 已有事实 | 当前接受的含义 | 不能推导 |
| --- | --- | --- |
| v0.5 E2 A/B：8 次 / 7,428 raw，两臂均正确 | 该 controlled trajectory 未见通用探索提示的净收益 | 普通 Agent 在外部任务不会出现动态使用失败 |
| E3a：强 Git notes 与真实 MCP/PG 的核心机械检查通过 | 已有基本保存、版本、可信恢复能力 | 两类存储等价或任意故障/延迟验收均完成 |
| E3b：4 次 / 2,918 raw，完整充分性 0/4 | 对象、返回条件与关闭依据的关系使用在受控案例中失败 | 已证明自然错误率、总体 efficacy 或必须使用结构化绑定 |
| 合计 12 次 / 10,346 raw，付费 0 | v0.5 候选已关闭，保留 A0；自建服务停止，数据保留 | 本 Goal 获准续跑、v0.5 静态 E1 已运行 |

v0.5 的 R0 七调用静态计划只做零生成预检，E1 未重跑。
更早 v0.4 的 10 次 / 43,656 raw、旧 projection 原型和失败也继续保留，不混入本次分母。

产品基线依据 [V02-09 最终验收](../releases/MCP_0.1.15_FINAL_ACCEPTANCE_20260908.md)：
MCP 0.1.15 / SDK 0.1.3 / Runtime 0.1.4，compact 8 工具；
原 383 passed / 7 条件跳过和 v0.5 的 598 项 Lab 测试是历史工程结果，本轮不重跑。
OAuth、公网和两条保留 Note 不动；V02-06 继续暂停；Schema 继续 NO-GO。

## 3. 外部测试床及其结论边界

### 3.1 官方资料核对

资料访问日期为 2026-09-09，正式执行须锁定仓库 commit、数据 revision、文件 hash 和许可证。

- **LongMemEval V1**：官方提供各含 500 个实例的 S、M 和 Oracle 文件。
  S 约 115k tokens，M 约 500 sessions；Oracle 只含证据 sessions。
  类型标签、拒答 ID 标记、answer_session_ids 和 has_answer 可用于离线评价。
  官方检索评测跳过无真实答案位置的拒答题，不能将这种跳过扩展到 QA 评价。
  见[官方 README](https://github.com/xiaowu0162/LongMemEval/blob/main/README.md)。
- **LongMemEval-V2**：451 道人工整理的问题，覆盖 web / enterprise 的多模态轨迹经验；
  测 static、dynamic、workflow、gotchas、premise，最大历史达到约 500 trajectories / 115M tokens。
  问题是从历史取得有界证据后进行 QA，不是直接执行一个新环境任务。
  见[官方项目页](https://xiaowu0162.github.io/longmemeval-v2/)。
- V2 接口为 insert trajectory、query 文本/可选图片并返回上下文，随后 Reader 回答；
  问题 ID、类型、gold 和 evaluator 配置不应进入 backend。
  见[接口 README](https://github.com/xiaowu0162/LongMemEval-V2)。
- V2 的 LAFS Gain 使用指定 tier 的参考准确率–查询延迟前沿与域合并规则。
  本 Goal 使用小样本、本地模型和诊断政策，不与榜单条件等价，**不计算或申报正式 LAFS/榜单成绩**。
  见[官方计分合同](https://github.com/xiaowu0162/LongMemEval-V2/blob/main/leaderboard/README.md)。

类别映射、数据字段与具体长度以冻结版本为准，不能把文档中的概略大小当成本预算。

### 3.2 三层职责

| 层 | 数据 / 路径 | 回答什么 | 本 Goal 的优先级 |
| --- | --- | --- | --- |
| A | V1 Oracle，证据 sessions 已给定 | 材料已送达时，普通 Host 是否仍误用？ | 低成本输入/评分校准与 use 诊断 |
| B | V1 S，完整合法历史＋正常检索 | retrieval 与 use 同时存在时出错在哪里？ | 仅保留后续位置，首批不跑；M 不进入 |
| C | V2 Small，经验轨迹＋正常检索 | 状态、工作流、陷阱、前提是否被正确用于回答？ | 外部效度主测试床，先做可行性检查 |

V2 是研究优先级，V1 Oracle 可以先做少量校准，不需要等 V1 全部通过才进入 V2。
两套数据分表报告，不合并成一个“记忆准确率”。
外部 A0 运行自然产生的错误，只描述该公开任务与冻结配置；不等于真实用户部署中的自然错误率。

V1 Oracle 是 gold 引导的来源条件，不是自然检索成功或当前 MCP 检索能力。
V2 workflow / premise QA 仍不是实际工具行动、observation→State 更新、PARK/RESUME 或真实冷恢复。
它们可以提供动态/持久研究的失败线索，但不自动完成 v0.5 的 E2/E3 行为证明。

### 3.3 多模态与规模不能静默降级

V2 Small 不是“小段文本”：轨迹含图片，少量问题可能仍共享较大的历史包。
“45 道问题”不能等价换算成“45 次短输入”或“45 条轨迹”。

X0 必须核验 Reader/Host 的图片支持、MCP 或合法源读取能否真实呈现图片、
图片传输与 token 计量、下载体积、解压空间和全量摄取耗时。
不能把图片仅以路径占位就标成 presented，也不能用额外 caption/OCR 模型偷偷补齐能力。

优先保留原生 Small 定义及该题官方 haystack。
若当前链路不能处理必要图片，则标 MODALITY_UNSUPPORTED 并暂停对应题；
如改做事先定义的 text-supported 子集，必须另标
V2_TEXT_SUPPORTED_DIAGNOSTIC，报告选择规则、覆盖损失，不声称完整 V2。
不得看 gold 后挑选“文字碰巧足够”的题，或去掉必要图片后把错误算作 State-use failure。
超大历史不能只留答案轨迹后仍叫原生 Small；缩减历史必须单列 DERIVED_REDUCED_HAYSTACK。

## 4. 样本与污染控制：外部不等于未见过

### 4.1 拟定样本目标

| V1 Oracle 分层 | 问题数 | V2 Small 分层 | 问题数 |
| --- | ---: | --- | ---: |
| knowledge update | 6 | dynamic state tracking | 10 |
| temporal reasoning | 6 | workflow knowledge | 10 |
| multi-session reasoning | 6 | environment gotchas | 10 |
| abstention | 6 | premise awareness | 10 |
| — | — | static recall 负控 | 5 |
| 合计 | 24 | 合计 | 45 |

总目标为 **69 个唯一问题 ID**，不是 69 个统计独立 task family，也不是必须一次执行完。
拒答标记与 question_type 可能交叉；V1 先划入 abstention 层，其余三层只取非拒答题，避免重复。
V2 如同题多标签，也先冻结唯一主分层及 secondary labels，不重复计问题数。

问题跨 web / enterprise 和不同环境、来源任务、能力分布；
共享答案轨迹、同一底层任务或模板变体应记录 cluster，必要时按 cluster 汇总。
不因共享无关 filler 就把全部题合成一个 cluster，也不把同一关系换名称当独立复现。
分层数不足时如实报告，不看当前答案或运行结果后调整配额填满。

### 4.2 在看结果前冻结抽样

1. 先只读 inventory 元数据与既往暴露索引，锁定 split/tier、category、domain、modality、
   来源 family/cluster、数据版本及候选集合；评估标签只在离线管理端使用。
2. 排除参与过 MiLAi 提示、代码、评分规则调试的题及近重复来源；
   按冻结规则随机/哈希抽样并记录 seed，不能按问题语义选“像 publication”的案例。
3. 发布 exposure manifest：NEW_TO_MILAI_TUNING、PREVIOUSLY_OPENED、UNKNOWN。
   只有经索引核对的项可称未参与 MiLAi 调参；不据公开发布时间保证模型训练未见过。
4. 冻结各能力/测试床的候选队列、首波前缀与 §6.1 分流规则；后续只取所选队列的预定前缀。
   结果只能选择预注册分支，不能选择题目、重抽失败/超限/难题或转移配额补满。
   基础设施不适用与行为失败分别记入总分母；未进入的分支保留 NOT_RUN 及原因。
5. 如策略、解析、检索或输入模板因首批结果发生语义变化，应建立新版本；
   已打开案例只作开发诊断，重新冻结未打开确认集合，不能将变更前后拼成一次 A0 测量。

本地已经使用过 V1 的历史记录见
[LME 增量结果](../../../MiLAi-Lab/studies/active/MILA_V02_LME_INCREMENTAL.md)。
该记录还披露过 source session ID 携带 answer_ 标记、修复重导出及 Formal 数据访问边界。
不能因为换成官方 Oracle 文件，就将重合题改称新样本。
受保护的 Formal-500/历史留出集不因本规划自动解封；候选只从后续明确允许的分区选。
新生成 history 也不天然无污染：旧问题/答案不变只换 filler 仍非新任务，应另行构造和标记。

### 4.3 标签隔离与轨迹安全

在线 Host/Reader 不接收 answer、has_answer、answer_session_ids、question_type、
question_id 中的 _abs 后缀、评语或失败类别。用随机运行 ID，中性来源 ID 与离线映射保留可追溯性。
V1 Oracle 离线装配器可以依据官方证据 sessions 建包，但输出只保留普通对话、合法日期、
角色与中性引用；不泄漏“这里含答案”的标记。完整官方 Oracle 正文不能再按 gold 剪句子。
去标签只作用于官方评价字段和标识；正文中的真实对象、编号、否定词和关系不能因同名而改写。
拒答题保留官方允许的起点，不伪造证据 session 或把没有答案定位判为检索失败。

V2 离线题目、轨迹和评估元数据分开；query 只得到合法问题文本及适用图片，
摄取不提前见未来问题、答案或针对它生成 State。
轨迹中的指令、URL、账户描述和工具结果均是历史数据，不触发真实登录、下单或网页动作。
不把公开数据或合成域自动视为可外发给付费 API 的授权。

## 5. A0 必须定义为可复现配置，不只是版本号

MCP 0.1.15 是工具制品，不自动定义 Host 提示、模型、摄取表示、工具可见性和读取预算。
首个批次前冻结 A0 manifest：Product wheel/hash、Host 来源/version、模型与 tokenizer、
system/tool 提示、采样、目录、正常回查政策、来源映射、分块/排序/返回上限及预算。
首阶段不加入 Control State、自生成总结、关系提示、旧失败专用词表或额外语义模型。
允许既有普通读写能力，不以禁止普通笔记制造弱基线；出现自发保存时保留并计成本。

| 运行 profile | 路径 | 能声称什么 |
| --- | --- | --- |
| A0_ORACLE_USE | 完整 V1 Oracle 资料→同一 Host 单次首次回答 | Reader/Host 的给定材料使用诊断；不称 Product 检索结果 |
| A0_MCP_BOUNDED | 正常问题→既有 compact 工具/正常合法源读取→同一 Host 回答 | 固定产品边界与有界 Host 下的获取及使用诊断 |
| NATIVE_V2_PROTOCOL | 完整匹配官方插入/查询/Reader/模态等合同 | 只有实际做到后才如此标记；首批不默认具备 |

A0_MCP_BOUNDED 建议每题最多 3 次 Host 生成、6 次 read/search/list，
最后一次为首次交付；工具依赖与重读正文全部计量。
这是新冻结的有界外部诊断 profile，不冒充旧付费大预算 A0 的同条件复现。
若需要改用固定机械检索＋Reader，单独标 FIXED_RETRIEVAL_DIAGNOSTIC，
不与模型自主选择工具的 A0 合并；不得在看到失败后偷偷切换路由救活。

### 5.1 无架构改动的摄取接线

所有接线只在 Lab，Product 按固定制品公开接口作为黑盒；不改 Runtime、检索算法、
权限、索引策略或 8 工具，不直接写产品数据库，不借用第三方 Memory Store 替换 MiLAi。

按[compact 合同](../../contracts/mcp/compact-memory-v1.md)，统一 search 是 Note 与治理分支的有界发现，
不是全量 Raw Evidence 文本检索，且不搜索 Working State。
X0 须先明确哪种原始来源表示能被当前合法查询路径发现：
可采用现有内容优先 Note 的无语义改写映射，或已经可用的原始来源读取；
不能导入 Evidence 后假定 search 会全搜到，更不能自动批准 Claim 让测试通过。

冻结原始 session/trajectory→Note/Evidence/源文件的类型、内容版本和引用映射，
只做机械去标签、分块和格式封装，不额外提取经验、修复关系或生成摘要。
若必须分块，应按普通源边界/大小预先固定，保留完整原文可恢复和全部分块；
不得按答案位置分块、把对象字段结构化为新业务 Schema。
原文可追溯和准备成本都计入；这个摄取表示是待诊断 A0 的一部分，不称任意表示等价。

只在获准的本地独占合成域进行 ingest，按 haystack 身份复用不可变源索引以降低成本；
不能混入不属于本题 Small 的其他历史，不能在问题之间累积答案/查询产物。
模型会话、Working State、Note 写回与控制缓存按题隔离；正常共享源缓存须标明冷/热条件。
保留现有公开连接复用能力，但不运行旧付费脚本或旧 13 工具配置。

### 5.2 Harness 摄取与 Agent 写入分账

以下是 **Lab 账本分类**，不是新增 Product operation 类型或 MCP 工具：

| 操作来源 | 分类 | 边界与成本 |
| --- | --- | --- |
| Harness 建立题目环境 | HARNESS_INGEST | 完整 session/trajectory 的机械映射、分块和索引；不见未来 query/gold，准备成本单列 |
| Host 回答过程中自主维护 | AGENT_MEMORY_MUTATION | 既有授权内的普通 save/update/delete；保留调用、回执、版本、失败与在线成本 |

分别记录 actor、操作分类、run/haystack/题内 scope、中性来源映射和持久 operation_id；
重试复用原 ID，同一 ID 不混用于 ingest 和自主保存。自发写入也受冻结的工具/时间预算约束，
不得绕过既有确认、CAS、身份与治理要求；A0 不因测试需要获得自动批准 Claim 的权限。

源索引只允许按相同 haystack/version 复用不可变内容；Host 写入置于每题独立可写域，
不得修改共享源底座，下一题不得读到上一题的答案、Note 写回、Working State 或控制缓存。
X0 必须验证这条隔离；现有接口无法实现时标 BACKEND_INCOMPATIBLE，不在 Product 偷加新存储能力。
teardown 首先关闭本题可见性与写入继承；实际清理仅限获准、可精确定位的本题合成资源，
可保留隔离快照供审计，不因结束一题就执行全命名空间清理或删除共享源索引。
分别报告逻辑隔离/删除与物理保留状态，公网、用户数据、旧实验及两条保留 Note 不动。

## 6. 第一阶段：只跑 A0 的外部诊断

### X0：零生成、先核验成本与可测性

以下要求适用于正式执行；本次已完成 metadata/来源保真/离线评分与资格分流，
实际 MCP 写入隔离及文件/图片传输已补充机械验证；在线 A0/模型模态验证未进入，
X0 仍为 PARTIAL_NOT_X0_READY：

- 锁定官方代码/数据、许可证与 artifact hash；检查可用存储、选定题目的完整 haystack、
  图片依赖、摄取数量/字节和索引资源，不默认下载最大包。
- 查 exposure manifest 与受保护分区，冻结 24/45 的候选清单、cluster、主分层和预定批次；
  本次按 metadata 冻结后仅打开 10 个旧保护分区外候选作离线资格/评分合同审查，未生成回答。
- **在首个生成请求前冻结 §7.1 的 evaluation_contract**：问题级参考、判定模式、
  完整正确性/拒答/争议规则、评价责任与成本；没有评分路径的题不得先生成再想评分办法。
  同时冻结 §6.1 的分流合同、队列顺序与停止原因，69 题不是自动待执行队列。
- 固定 A0 profile 和非 gold 的来源表示，构造 source-only 包与离线评价包，
  对 answer_ / has_answer 等泄漏进行机械测试。
- 验证工具覆盖、范围隔离、摄取/自主写入分账、实际输入采集、图片支持与 tokenizer 预算；
  固定 X2a 的 backend-fit 检查及合格判据。
  固定替身只能证明接线，不证明真实 Reader 能用图片或理解材料。
- 估算 source ingest 与 query 分开的成本，冻结磁盘/下载/索引/模型/墙钟上限。
  超过建议模型额度或资源不可承受时先缩小问题批次，不缩减题内材料后冒称同一条件。
- 关闭官方默认付费 Judge、付费 Codex/controller、自动 embedding/summary 和隐藏 retry。
  若任何依赖必须生成才能诊断，单独登记调用，不放进“零生成预检”。
- 只读确认已存在本地 vLLM 的配置与能力，不重启共享服务、不下载权重、不更换模型；
  历史模型名称不是当前在线和多模态兼容的证明。

### X1：V1 Oracle 小波次

建议首波 4 题，每个分层 1 题；符合材料、标签、评分与成本合同才可发送。
扩至 24 是 §6.1 分流允许的上限，不是首波接线通过后的默认动作。
一个失败不会自动增加追问或更换提示。

完整 Oracle 包实际进入模型，问题日期、角色与普通来源时间保留，
不利用 oracle 证据排序之外的隐含 gold 信号。
超过共同输入上限的题记 BUDGET_INFEASIBLE，保留在流程统计，
不得静默截断、换题或填“答案错误”；需要放大上限时另行登记适用人群和预算。

Oracle QA 错误提供 use 诊断，不称“MiLAi 没找到来源”。
abstention 独立报告正确拒答、无依据作答与错误拒答；不以鼓励 State 使用降低拒答门槛。

### X2：V2 Small 外部经验诊断

建议首波 5 题，每个能力 1 题，域分配预定；最多扩至 45，遵循 §6.1。
每题依次出具以下两个结论，**X2a/X2b 不增加题数或生成分配**：

**X2a — Backend Fit：当前来源表示与工具路径能否承载任务？**

- 基于完整官方 trajectory/haystack、模态及 §5 的冻结映射检查，不使用 gold 指定分块或检索路线。
  核对原件/分块的完整性与版本、原始 state/时间/对象关系是否机械保留、图片入口是否可读。
- 验证实际覆盖：该表示可经当前合法 search/list/read 或冻结的源读取路径访问，
  不是“导入成功所以一定可搜”。准确列出 Note、Evidence、Working State 各自可见范围。
- 输入装配、图片传输和题间隔离检查须有记录；路径占位、未验证能力、缺失原文不能算合格。
  接线和 source-only 契约尽量零生成核验；必须通过真实生成观察的部分仍计入已授权 X2 额度，
  不新增兼容探针。必要前置能力尚未核实时不发行为请求。

记录 FIT / BACKEND_INCOMPATIBLE / MODALITY_UNSUPPORTED / FIT_UNVERIFIED 及具体原因。
**FIT 不以命中 gold 或回答正确为条件，也不保证本次检索成功**；兼容链路仍可出现普通检索失败。
题目的官方 tier、history membership 与必要模态不因选择问题子集而变化。

**X2b — Behavioral Diagnosis：合法材料取得并呈现后，经验是否仍被误用？**

使用 A0_MCP_BOUNDED 的普通检索与来源访问，保留原有合法能力，
不注入 focus、关联条件或 v0.5 受控案例的 object/trigger/closure 模板。
同一 Host 获得工具输出并首次交付，不藏入一个答案修复 Reader。
正常查询不同材料是结果；不能在观察到回答错误后补 gold 片段重新称首次成功。
workflow 的步骤描述与环境经验 QA 单独评分，不当作已执行真实动作。

只有 X2a FIT 的题进入行为诊断；只有其中必要支持已实际 presented、答案经冻结规则判错的题，
才可归因关系/适用性/control-use failure。没有足够支持则优先记录 retrieval/presented 层。
所有不兼容、未核验、超限、未发请求和失败题仍在总流程分母中；输出 backend fit 表与行为表，
不得删除这些题来提高成功率，也不得把它们当成 State-use failure。

### 6.1 首波后的预注册分流：最多 69 题，不默认跑满

首波为 4 个 V1＋5 个 V2 预定位置；无法运行的位置也有终态，不补题。
在首波已运行项完成冻结评分与归因后作一次分流，后续每小批重复同一规则。
下表的“use failure”只指已裁定、support presented 的错误；disputed/UNKNOWN 不作为正信号。

| 预注册观察条件 | 下一步 | 不能推导 |
| --- | --- | --- |
| V1 Oracle 至少出现一个可核验 use failure | 优先推进 V1 固定队列，下一批至多 4 题，寻找跨 cluster 复现 | 单例已经支持 State 机制 |
| V2 FIT 且 support presented，workflow/premise/gotcha 或 dynamic 的使用出错 | 推进命中能力的预定候选前缀，下一批合计至多 5 题；仍受各层原配额约束 | 为像某个失败的题重新抽样 |
| 无合格 use failure，但 V2 有 SOURCE_NOT_ACQUIRED、来源映射或覆盖缺口 | 不扩 State 批次；转来源/检索问题报告，先定位该层 | 原模型已经正确使用了未呈现材料 |
| 必要图片/模态路径不合格 | 停止受影响 native V2 分支；text-supported 只能按 §3.3 另立冻结条件 | 文字降级是原生 V2 结果 |
| 无合格 use failure，也无明确 acquisition 缺口 | 提前 KEEP_BASELINE；若因评分/预算/协议无法判断则标限制终止 | 少量正确或未执行证明总体有效 |

优先级在 X0 固定：泄漏/权限/未知成本等先停受影响批次；backend/modal 缺口先阻断对应分支，
不以额外生成救活；无此阻断才扩已确认 use failure 的队列。V1/V2 同时有信号时默认按
V1 一小批→V2 一小批交替；V2 多能力并列时按 §4.1 表序轮取，静态负控保留在预定覆盖位置。
这些是资源调度顺序，不是效果门槛；不在看结果后改成更有利的 tie-break。

不能以一次首次失败无限续跑：后续每波记录是否新增独立 cluster 的同类失败。
连续两波扩展没有新增复现则关闭该扩展分支；达到 §8.1 候选门后先收尾并提出条件性方案，
不自动耗尽发现集。批次、调用、token、墙钟或评价能力上限任一先到也停止。
如需不同序贯规则，应在首个结果前于 X0 冻结版本，不能追溯替换已运行批次的停止理由。

分流日志保存依据的题目/失败层/分母、所选预定队列及未运行原因。
这是 sequential diagnostic 的自适应继续策略，须披露停止规则；后续分布不冒充原始均衡随机样本，
不同分支/能力分别报告。证据不足的早停只表示本次不值得继续消费，不排除将来独立新证据。

## 7. 全链路归因：先确定材料是否真的到达

每题保存实际可见请求、工具结果、完整成本与来源版本，离线检查必要支持。
检索标签只是线索：存在多个合法证据组合时，不因未命中唯一标注 ID 就判错。
日志没有覆盖到的环节标 UNKNOWN，不猜测模型私有理解或内部注意力。

| 层 / 代码 | 可观察判据 | 不可混淆的解释 |
| --- | --- | --- |
| AVAILABILITY / INPUT_UNAVAILABLE | 允许历史是否完整，文件/图片是否可读，题目所需资格是否成立 | 输入缺失、撤权或权限失败不是检索算法失败 |
| RETRIEVAL / SOURCE_NOT_ACQUIRED | 所需来源在合法集合中，但本预算内未取回充分证据 | 本次没查到不等于没有历史 |
| PRESENTED / ASSEMBLY_LOSS | 已取得关键正文/图片，但实际请求未呈现或被截断 | 不能归成 Host 已看见仍忽略 |
| INTERPRETATION / EVIDENCE_USE_FAILURE | 必要支持已呈现，公开回答仍与它矛盾或漏掉关键关系 | 不能仅从输出反推内部推理过程 |
| APPLICABILITY / TEMPORAL_RELATIONAL_USE_FAILURE | 对象、时间、环境或条件被错误套用，有明确反例支持 | A0 未生成 State 时，不叫持久 State 损坏 |
| CONTROL_USE / WRONG_NEXT_STEP_OR_PREMISE | 已有工作流/gotcha/前提支持，公开建议仍错误 | QA 下一步建议不是实际工具行动，也不等于缺少检索 |
| FINAL / ANSWER_OR_FORMAT_FAILURE | 最终响应是否满足问题与可核验依据 | 正确 JSON、正确引用或提及关键词不能代替答案正确 |
| EVAL / ANNOTATION_DISPUTE | 参考与来源有歧义、冲突或多个可接受答案 | 保留官方答案和争议，不改 gold 帮候选通过 |

每题同时记最早可证实失败层与后续可观察症状，不把一题重复当多个独立失败样本。
“State-use failure”在首阶段只作为待检验的机制线索：
A0 可以没有任何新 State，此时观察到的是关系/适用性使用失败，不能认定 State 保存有损。

主要报告每能力 QA、可评价覆盖率、拒答风险、来源取得率、
关键内容实际呈现率及其条件下的 use failure；没有必要证据的拒答题不进入检索召回分母。
需要 oracle 注入来区分检索与使用时，标独立 ORACLE_INJECTION_DIAGNOSTIC，
与原 A0 结果并列，生成另计；不视为主结果补救，也不藏在免费评价中。

### 7.1 评分、依赖与完整分母

V1 官方示例调用模型 evaluator，见[官方 QA 评价流程](https://github.com/xiaowu0162/LongMemEval/blob/main/README.md#-testing-your-system)。
本合同 **new judge requests = 0**，因此采用 NONSTANDARD_LOCAL_DIAGNOSTIC，
结果名称固定为 **MiLAi local diagnostic correctness on frozen subset**，不是官方 LongMemEval accuracy。
更换 Reader、人工评价或本地规则不能冒充官方评分；正式横向比较须另行冻结官方 evaluator 条件与成本。

X0 在任何实验生成前，为候选清单建立仅离线 evaluator 可读的 `evaluation_contract`，
锁定版本、hash、责任人/角色、评分顺序及复核路径；题型模板不能替代每道题的具体判据：

| 必填内容 | 冻结要求 |
| --- | --- |
| official answer / evidence | 官方答案、来源版本与证据引用；无官方定位时记 NOT_PROVIDED，补充离线定位另标来源，不伪装成官方标签 |
| evaluation mode | DETERMINISTIC / HUMAN_SEMANTIC / HYBRID；明确是否可确定性判定、哪些部分必须人工语义裁决 |
| correctness rule | 必要结论、关系、时间/范围、步骤依赖、可接受等价表达，以及会使整题不正确的矛盾或无依据补充 |
| deterministic check | 仅对可封闭判定的答案冻结规范化、比较规则及测试；关键词命中不替代关系、前提或 workflow 判断 |
| abstention rule | 无答案题须明确信息不足且不编造；有答案题的无依据拒答判错；安全拒绝与不确定性按题目要求单列，不把所有拒答都当正确 |
| dispute rule | 参考与来源冲突、多种合理解释、评分者不一致如何标记、复核与保留未决；不允许看模型答案后改 gold |
| evaluator availability / cost | 谁负责语义判定、何时完成、劳动/复核预算与是否需新模型；未就绪题为 EVALUATION_NOT_READY，不先运行再补评价 |

答案/evidence/题型/判据全部留在离线侧，不进入 Host、source ingest、在线工具提示或 S2 instruction。
官方答案可能有歧义，判据可表达多种合法答案；但事后发现需要改规则时，保留原合同与原裁决，
新增版本并标事后重评，不能只改候选获益的题后称预注册结果。未来未打开确认集不参与提示开发。

评分顺序为首次输出完整正确性→证据支持核对→失败归因；能盲化条件标签时盲化。
CORRECT 必须满足冻结的完整要求；有明确可证实错误记 INCORRECT；证据/标注/裁决不确定记 DISPUTED。
等待人工裁决记 UNSCORED，不由未获授权的本地/付费模型自动填分；disputed 不进入机制正信号。
确定性检查不能覆盖的关系题，须由已冻结的人工路径裁决；当前开发代理不充当独立人类 gold。

保留全部 planned，以及 backend_fit、attempted、valid first answer、scored 的逐级计数；
另列 CORRECT/INCORRECT/DISPUTED/UNSCORED 和未运行/超时/超限/协议无效原因。
报告 attempted/planned、fit/planned（V2）、valid/attempted、评分覆盖率，以及 C/(C+I) 的明确分母；
争议/未裁决占比必须同时给出，不只发布一个正确率。分母为零记 N/A。
未执行或传输失败不冒充语义错误；主动拒答、已交付答案的格式错误不因不利而从评分中消失。

所有评价劳动和工具成本单列；新模型 Judge/代理复核即使本地免费，也须单独授权并计入调用账本。
离线查看已保存轨迹不是给 A0 追加答案修复机会。本次没有打开样本评分、创建逐题合同或增加 Judge。

## 8. 进入下一机制的门：重复失败，不是凑样本量

### 8.1 Mechanism candidate gate：只允许提出小型机制 pilot

先完成 A0 诊断和证据审阅。以下是探索性进入门，不是统计显著性或核心创新证明：

1. 至少 3 个不同底层任务/支持来源 cluster，跨至少 2 类能力，
   重复出现可说明的关系/适用性使用失败；共同 haystack 的模板变体不够。
2. 关键支持确已 presented；不是输入/模态、单纯检索、参考歧义或数据泄漏解释得更直接。
3. 失败可由一个领域无关的语义要求概括，不依赖 publication、B6 或其他 case 专用字段。
4. 若声称 Agent 环境经验的共性，须有 V2 对应证据；只有 V1 时只能提出对话 QA 的有限假设。
5. 冻结发现集合、机制假设和未打开确认集合；小 pilot 的门只表示值得研究，不证明普遍发生率。

### 8.2 Core research signal：不能从 3 clusters × 2 abilities 自动升级

Contextual State Fidelity 要成为主研究方向，还需在未打开、未参与调参的确认集重复，
且在 support-presented-but-wrong 的失败中不是偶发边缘现象；同时与 retrieval、模态和普通推理缺口比较。
这不是首阶段的完成条件，也不意味着立即运行确认或实施 S1/S2。

X0 冻结完整 taxonomy、归因规则和分母，不在看到结果后只公开关系失败：

`relation/applicability use failures / (support presented AND adjudicated answer wrong)`

分子取经证实的关系/适用性错误的并集，一题只计一次；disputed、缺支持和适配失败不进入该条件分母，
但继续保留在总流程表。分别按题和独立 cluster 报告 n/N，并按能力、域、profile 与发现/确认集分表。
同时公布所有失败层分布、覆盖损失与序贯选择过程，不能把自适应扩大的失败层频率当总体发生率。

“稳定、非边缘”不是事后指定一个有利百分比：需可复核的确认重复与完整分布支持，
不预设 20%/30% 阈值，也不将本合同当自动晋升规则。若仍受小样本、共享来源或评分争议限制，
结论继续为 CANDIDATE_ONLY；如果大部分缺口是 acquisition，就不能宣称关系保真是主要瓶颈。
未来核心主张及其确认标准须在确认集打开前另行冻结；正信号也不等于自由 State 干预已经有效。

若 §8.1 满足者不足，结果为 INSUFFICIENT_GENERAL_FAILURE_SIGNAL，保留 A0，不构造 H4。
仅满足 §8.1 而缺少 §8.2 确认时，只能提出机制 pilot，不升级为核心问题结论。
若主要为检索失败，提交该层问题报告，任何修复单独立项，不在当前 A0 批次内边改边测。
若已有不同失败类型，各自选择最小工作，不用单一 State schema 包办。

目标数量 24/45 用于观察覆盖和成本；不强迫在诊断已经充分或预算耗尽时跑满。
提前停止必须按事前规定原因并保留分母，不能因为首几题正确就宣布全面有效。

## 9. 条件性第二阶段：same evidence, different regulation

**NOT_AUTHORIZED / NOT_IMPLEMENTED。** 只有 §8.1 成立后，才具体设计/冻结并另行申请该阶段；
以下是设计边界，不是本 Goal 已要求实现的机制或已分配的实验组。

### 9.1 Contextual State Fidelity，不先做强绑定

S1 允许 Host 用自然语言、Markdown 或 JSON 形成自由处理记录：
当前问题、变化、未决项和下一步都是语义用途，不要求键名。
S2 在相同长度上限内，额外要求保留“判断针对什么、依据来自哪里、何种变化需要重新核验”
的关系上下文；**不要求 target_id、trigger、closure_basis、固定领域类型或 Runtime 校验器**。
当前关系不确定时应如实保留，不为填完整字段编造来源或关闭条件。

S2 指令须在该阶段生成前通过领域无关/语义脱敏审查并冻结 hash。例如：
“记录判断时保留适用对象或范围、可用的支持来源及可能需要重新核验的条件；不确定则明确说明。”
去掉具体任务名、实体名、关系名后，指令仍须完整成立；不得暗藏某题正确对象、答案、触发条件，
或加入“publication 与 receipt identity 不同”等发现集专用修补。允许概括失败模式，不允许把 gold 写进提示。

可纠正性由后续行为验证，不由字段齐全判定。
元数据映射、离线评分标签和预算 schema 是实验机械边界，不是给业务 State 新建 Schema。

### 9.2 必须控制额外推理机会

| 条件 | 生成上限 | 内容与用途 |
| --- | ---: | --- |
| A0-single | 1 | 完整相同证据，普通首次回答，产品/成本参考 |
| A0-review | 2 | 普通工作记录＋首次交付，等两轮强简单对照 |
| S1 自由 Control State | 2 | 自产自由处理记录＋首次交付 |
| S2 关系上下文 State | 2 | 自产保留关系上下文的记录＋首次交付 |

S1−A0-review、S2−S1 比较等两轮政策；S1/S2 对 A0-single 只作为不同总成本的产品比较。
A0 的第一次诊断结果不能因本轮更换证据包或输入格式就直接充当配对对照。
各组完整输入证据内容、顺序/位置、工具能力和输出上限一致，
无 projection、人工正确关系卡、隐藏 Reader、额外修复机会或自动关系绑定。
准备和交付、状态文本长度及全部重发证据都实计，不把 S2 更长输入当免费优势。

同时记录 **Natural Relation Preservation Rate**：离线检查 A0-review / S1 的普通工作记录，
按预冻结的适用机会分别统计 referent、source basis、applicability、reconsideration condition
是否已自然且正确地保留。没有来源支持或无需重核条件时记 N/A/明确未知，不奖励编造完整关系。
记录不可观测则记 UNKNOWN，不从最终正确猜测中间已保留，也不因没有指定键名判为缺失。
这个过程指标不替代答案/行为及成本；若强简单对照本就自然保留，S2 只是改名或格式化，不形成独立贡献。

### 9.3 选择性条件与确认

首批只来自“支持已呈现但原 A0 错误”的发现集合，所以只能证明条件化诊断价值。
保留 A0 的等机会重跑对照，避免把错误样本的随机恢复当成 State 效果。
同时加入已正确/拒答等负迁移控制，不只看 S2 能救几个错误。
所有冻结条件保留失败，不循环调提示到全过；未打开任务用于独立确认，
不能将发现、调试和确认分母混在一起。

只有自由关系上下文在多个独立任务有合格质量/成本信号，
且剩余失败确实指向表示问题而非检索或模型能力，才允许单独提出
“最小结构 vs 自由文本”的后续研究。即便提出也不自动改 Product。
外部 QA 比较本身仍不证明真实动态/冷恢复控制关系，应后续另立有新观察和实际行为的任务。

### 9.4 内部机制信号之后的外部强对照要求

首阶段只跑 A0，不新增后端；正式机制确认不能永远只做 A0/S1/S2。
V2 官方包含 rag_query_to_slice、rag_query_to_slice_notes、agentrunbook_r、codex、agentrunbook_c，
见[官方基线目录](https://github.com/xiaowu0162/LongMemEval-V2#repository-layout)。
若内部出现合格信号，后续至少选择一个最直接相关、可复现的强基线（如 AgentRunbook 或对应 RAG），
冻结完整 haystack、模态、Reader、能力/预算、评价规则和硬件条件；必要差异及全生命周期成本分账。
未做此比较时只报告内部诊断，不宣称超过直接近邻或形成论文级净优势。
此要求位于 **confirmation after internal mechanism signal**，不进入首阶段预算或依赖，
不现在安装、接入或调用外部模型，也不以第三方实现替换 MiLAi 的产品架构。

## 10. 成本与分批安排

**当前实际生成、raw、付费和 benchmark Judge 调用均为 0；资格停止后没有可发送分配。**
用户执行授权已覆盖资格门内预定首阶段，不需重复批准同范围；
69 题是候选覆盖上限，不是一次性模型调用承诺；首波后按 §6.1 分流，生成上限也不是目标消耗。
后续一次明确授权可以覆盖多个预定波次及其累计上限；每波仍检查成本/有效性门，
无需为同一已授权范围重复请求许可。超出范围或需新付费依赖时另行明确，本次文档请求不授予执行。

| 未来分配 | 问题数上限 | 生成上限 | raw token 上限 | 说明 |
| --- | ---: | ---: | ---: | --- |
| X0 | 0 | 0 | 0 | 元数据、接线、评分/分流合同和资源准备；非模型成本单列 |
| V1 首波 | 4 | 4 | 40,000 | 四层各一题，完整 Oracle，单轮 |
| V1 后续 | 20 | 20 | 200,000 | 每批至多 4 题，仅按冻结分流进入，不自动排满 |
| V2 首波 | 5 | 15 | 100,000 | 五能力各一题，先 X2a，再 X2b；每题合计至多 3 次 |
| V2 后续 | 40 | 120 | 800,000 | 每批至多 5 题/15 次，不因某能力停止而给其他能力加配额 |
| 首阶段合计上限 | 69 | 159 | 1,140,000 | 仅在明确授权范围内且符合分流门时；不是本次授权 |

默认每次输入建议 ≤8,192 token，输出预约 ≤1,024（包括服务计量 reasoning）。
V1 每题累计 ≤10,000 raw；V2 每题累计 ≤20,000 raw，整批与单题双重门禁。
三次单次最坏预约可能超过 V2 单题累计额度，必须按剩余量预留交付，
不只看请求数。完整 Oracle 超限时不能截断；V2 检索返回预算属于 A0 冻结配置，
不能根据失败扩大 top-k、缩短共同材料或强行多调用一次。

首波建议 V1 批次墙钟 ≤10 分钟、V2 ≤15 分钟，单生成 ≤60 秒、MCP ≤40 秒且不超过剩余量。
正式阈值在 X0 按硬件和完整输入冻结；每次发送前预约完整实际输入/输出；
usage 未知保留预约并停止，次数/token/时间任一先到即停，不 retry 或换模型。
单批模型最多一个在途仅约束实验成本，不限制产品多用户并发。
当前实际 GPU、vLLM 模态与资源状态未重新探测，不能用历史配置保证可执行。

### 10.1 摄取与评价不能藏在 QA 预算之外

全流程分别记录下载/解压字节、HARNESS_INGEST/索引/存储、AGENT_MEMORY_MUTATION、
查询与 tool 等待、全部控制/回答/评价生成、延迟、缓存条件及人工劳动。
准备写入和在线自主写入不可合成一个“memory writes”指标；共享摄取摊销与每题成本同时报告。
摄取默认不调用模型提取、自动摘要或 embedding；若固定 A0 必需有此依赖，
必须显式计量和授权，不把它算作“没有主 Agent 调用”。
V2 历史很大，X0 应单独冻结下载/磁盘/摄取时间上限；未冻结则不能开始批量准备。
同一合法源索引可摊销但报告摊销分母，不能把重复处理当免费或用跨题答案缓存取巧。
查询延迟与回答/总任务延迟分账；不将本地小样本点与官方 LAFS 前沿直接比较。

### 10.2 第二阶段不藏在首阶段余额

S1/S2 与公平对照每案例最多 7 次生成，若进入可先建议 2 案例 / 14 次 / 112,000 raw
作为单独的接线与条件性诊断上限，不属于上表 159 次，也不是当前授权。
两个案例不足以支持稳定结论，负控、扩大独立确认、新 G、动态任务和模型复核须另定分配。
不为了使字段方案“通过”自动用完或追加额度。

## 11. 执行产物、验收与终态

### 11.1 后续开发与归属

Product 本轮和首阶段不新增 API、Schema、权限、Canonical、检索算法或默认行为，不需迁移。
Lab 才可增加薄数据适配、固定分配、实际请求追踪、评分和成本汇总；
`src/milai_lab` 不导入 Product 内部实现，产品访问限固定公开接口。
原始语料、图片、Provider 轨迹和运行记录放 Git 外，Git 只存小 manifest、代码及紧凑结果。
旧 LME 导出/连接复用工具只作参考，须审查旧 paid 配置、旧目录、标记泄漏与暴露分区，
不能原样运行或升级到新分母。

预期产物：

- dataset/version/license 与 exposure manifest，69 题候选/分层/cluster/波次及未执行原因；
- 生成前冻结的 evaluation_contract 与评分责任/可用性、分流合同/队列/hash；
- A0 profile、来源映射、X2a backend-fit 表、输入/模态/标签隔离检查、独占资源及 Product pin；
- 每题 actual input、取得与呈现的版本/span/图片、首次输出、ingest 与自主写入分开的完整账本；
- X2b 行为表、逐层归因、参考争议、所有分母、各能力/cluster 的错误分布与成本；
- 每波分流依据与停止记录；机制候选门和核心信号分别判断，交付保留 A0/返回 acquisition/提出干预的决定。

S2 脱敏审查、Natural Relation Preservation Rate、独立确认和外部强对照仅在该阶段后续获准时产出；
不为补齐这些条目在 X0 或首阶段暗中运行新机制。本次已交付十题离线合同与 69 位置账本，
没有回答评分或行为效果结果；其余未进入产物按资格停止说明，不伪造就绪。

### 11.2 验收不是“State 有效”

| 阶段 | 合格交付 |
| --- | --- |
| X0_READY | 生成前评分/分流合同已冻结且评价可执行，来源/模态/标签/隔离/预算可核验；仅合格题可进入，不要求消除所有 benchmark 不兼容项 |
| X2_BACKEND_FIT_RECORDED | 每题 X2a 结论与理由完整；不合格/未核验不进入行为归因，但保留在总流程分母 |
| A0_DIAGNOSTIC_COMPLETE | 获准问题全部有终态，归因可回查，失效与未执行没有隐藏 |
| EXTERNAL_FAILURE_PATTERN_FOUND | 仅达到 §8.1 候选门，明确适用范围与未打开确认计划；不等于 §8.2 核心研究信号 |
| NO_GENERAL_STATE_USE_SIGNAL | 未见跨任务重复或主要是其他层错误；不实施 State 新机制 |
| INTERVENTION_PROPOSAL_READY | 有失败依据的自由文本最小干预及公平对照，仅代表可另行立项 |

允许的整体终态：

- `COMPLETED_EXTERNAL_DIAGNOSTIC_KEEP_BASELINE`：获准诊断收尾，证据不足以扩张或无需新机制。
- `COMPLETED_EXTERNAL_DIAGNOSTIC_PROPOSE_CONTEXTUAL_STATE`：存在重复失败，交付条件性方案；
  不代表 State 方案已实现、已验证或 Product 已改。
- `COMPLETED_EXTERNAL_DIAGNOSTIC_ROUTE_TO_ACQUISITION`：主要缺口在来源、模态或检索，
  交付准确问题范围；修复不在本批次内自动执行。
- `STOPPED_RESOURCE_OR_PROTOCOL_LIMIT`：预算、资格、污染或协议不允许继续；
  保留已运行、未运行、占用与失败，不伪造完成或缩小分母。

越权、跨题泄漏、标签泄漏、未知成本或未经授权依赖立即停止受影响批次。
只收尾明确获准且属于本任务的资源，共享 vLLM、公网、旧数据和保留 Note 不动。
任何产品化、实际 Agent 行为验收、持久化策略或结构化 Schema 均须后续独立决定。

**本次执行为 STOPPED_RESOURCE_OR_PROTOCOL_LIMIT，A0 外部诊断未完成，不称 69 题已测。**
继续需要新的合格题池与前瞻冻结的分配/序列，明确旧留出保护和调参暴露边界；不得将后续题
换进已失败的首波。当前不建立 State-use 结论或 S1/S2，保留 0.1.15/A0。
Lab 601 项适用测试、边界/Ruff/mypy/build 通过；没有自建服务待清理，来源与审查证据保留。
