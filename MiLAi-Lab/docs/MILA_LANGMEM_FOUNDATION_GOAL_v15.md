---
version: v15.0
date: 2026-09-26
status: PLANNED_NOT_STARTED
planning_delivery: COMPLETE
implementation_authorized_this_round: false
scope: MiLAi-Lab
experiment_arm_kind: RESEARCH_PROTOTYPE
reference_commit: 0802d34f49db45bd654fc745d33da3252c0d4e24
reference_runtime_mapping_sha256: 944cda954858d7181624fc25c72ada717d3bd973e5231b29ecab85751e7f66ab
roadmap_sha256: 2b4868be60fd49f1f5ba645fa5357a445a254782417eb22b4416184b3bf00ed5
langmem_audit_commit: 9d033b47d9ce53e37e92c92241b0496c0278932e
foundation_lock_status: NOT_CREATED
foundation_execution_status: NOT_RUN
cumulative_generation_request_cap: null
cumulative_generation_token_cap: null
cumulative_embedding_token_cap: null
verification_count_cap: null
---

# v15 开发 Goal：LangMem 公共基线与独立研究底座

本 Goal 将 [vNext 路线图](MiLAi_vNext_Development_Roadmap_20260926.md)收敛为第一项可独立完成的开发工作：**在 MiLAi-Lab 中建立固定上游、固定 Agent 配方、使用现有 vLLM 的 LangGraph／LangMem 基线，接通原生业务任务、长期记忆、恢复和连续计账，再记录它在已有小样本上的真实行为。**

本轮只生成规划及导航，不安装依赖、不修改运行代码、不启动开发或实验。下列路径、命令、门槛及交付均为后续实施合同；“规划完成”不等于 v15 开发完成。

## 1. 目标、研究转向与成功定义

v14 的结构保障已交付，但首次未来约定与业务后记忆更新仍存在语义失败。继续逐例扩展 ordinary 的提示、frontier 和终结字段，难以区分基础设施改进与方法收益。v15 改用可检查的公共工具库建立对照；v14 保留为 reference，研究增量在后续 v16／v17 单独引入。

本 Goal 要解决四个实际问题：

1. 本地模型能否在公开 Agent／memory 工具接口下正常调用，而不复制旧 Host？
2. 长期 Store、单会话 checkpoint 与业务动作恢复能否分别成立？
3. 原有 benchmark 与费用记录能否接入新基线，保持输入、世界和评分不变？
4. 固定基线实际何时漏存、误改、遗漏业务后更新或作出无依据声明？

**成功是技术接入及行为记录可信，不是 B0 必须语义全通过。** v15 不以修好 v14 的每个失败、MERIT 5/5 或证明 MiLAi 创新为结项目标。基线失败可以成为结果；模型接入失败、检索失效、跨会话偷带历史、评分泄漏和费用缺失则不能当作合格基线。

## 2. 本轮核对事实与尚未证明的部分

| 项目 | 已核对事实 | 对本 Goal 的约束 |
| --- | --- | --- |
| MiLAi 源码 | 本地 HEAD 为 `0802d34`；v14 最终冻结的 47 份运行文件散列全部匹配 | 以该实现和证据为 reference，不重新运行 v14 来“确认一次” |
| v14 结果 | 最终原始世界／空记忆 arc0：native 4/5、dependent 1/2、Host／维护 7/7；首次约定 0/2 保留，最终 CURRENT 卡过时 | 保留负面结论，不把技术完成升格为 semantic readiness |
| v14 费用 | 80 次生成，输入＋输出 317,098 tokens，embedding 1,540 tokens；Judge=0 | 费用封存，v15 单独开连续账本，不混算、不清零历史 |
| LangMem 源码 | 仓库外本地 checkout 固定 `9d033b47…`、工作树干净；声明版本 0.0.30、MIT；公开 manage/search 工具已有实现 | 直接调用上游工具，不重写一份 MiLAi CRUD 冒充 LangMem |
| Lab 依赖 | 当前 `pyproject.toml`／`uv.lock` 尚无 LangMem／LangGraph | 依赖组、安装兼容性与 foundation lock 是待开发工作 |
| vLLM 客户端 | `VLLMClient.chat()` 已接受 tools、tool_choice；配置接受 native 和 json_action | 原生 tool calling 尚待真实兼容性验证，不先重写 HTTP 客户端 |
| MERIT 入口 | 现有 runner 直接依赖 `TaskTurn`、旧 Host、session、ContextualMemory 和 maintenance 结果 | 复用原生输入／工具／checker合同，建立窄适配，不能直接 import 旧运行器当新 runtime |
| RuntimeStore | 当前持久库直接依赖旧方法、Host、session、协议身份 | 可以参考动作日志原则，不把整个 RuntimeStore 导入新底座 |
| 未见任务 | v14 没有生成或读取 seeds 3/4；0/1/2 已暴露 | v15 不消费新 seeds；v17 使用前重新核对暴露登记，不保证它们永远未见 |

本轮未安装 LangGraph、未启动 vLLM 请求、未运行 pytest，也未核验部署中的 native parser／新持久后端兼容性。上述未验证项不能填成通过。[v14 结果](CONTEXTUAL_USER_MEMORY_V14_RESULTS_20260926.md)与[冻结清单](../data/manifests/contextual-memory-v14-final-freeze.json)是旧结果的证据入口。

## 3. 范围与后续 Goal 的关系

| Goal | 本阶段交付 | 启动与结束边界 |
| --- | --- | --- |
| **v15，本文件** | 路线图 P0–P2：reference freeze、依赖及协议 spike、B0 adapter、已有诊断与 arc0 characterization | 只实现公共基线；无 B1 版本层、Basis 或 Attention |
| v16，后续独立 Goal | P3–P4：B1 语义中性 instrumentation、M1 Sparse Basis | v15 foundation GO 后启动；先 parity，再机制可达性；无未见题调参 |
| v17，后续独立 Goal | P5–P6：M2 Attention；冻结后的 B1／M1／M2 小规模 matched 实验 | v16 有效接入且机制可解释后启动；允许明确负结果 |
| v18，可选 | 外部 Mem0／ReMe 对照及效率后端 | 有值得保留的机制后另行立项，Jev 不作为 LLM-only 主方法成立条件 |

这一转向取代旧活动路径的“先把 ordinary 调到语义无反例，再研究方法”的开发依赖；不改写 v14 gate 的失败结论。新的 gate 检查基线接入是否有效及对照是否公平，**不要求公开基线先变成语义完美系统**。

Product、产品 Schema／API／权限／Canonical、Archive 均不在开发范围。旧 contextual 方法、Host、maintenance-v5、H1–H6 和已封存运行源码不扩展、不删除。允许复用与旧语义策略无关的现有 provider、计账、输入类型及原生评分；避免为了“复用”重新引入旧 Host 的整条依赖。

## 4. 固定 B0：先定义配方，再运行分数

LangMem 是工具库，不是唯一预设的 benchmark agent。**B0 的正式身份是“固定上游 LangMem hot-path 工具＋固定 LangGraph ReAct 配方＋Lab 环境适配”**，不称为上游官方 MERIT 成绩，也不代表所有 LangMem 用法的上限。

首版选择已核对 [LangMem README 的双工具配方](https://github.com/langchain-ai/langmem/blob/9d033b47d9ce53e37e92c92241b0496c0278932e/README.md)：manage 与 search 由同一 Host 在正常任务中使用。上游还存在自动预取等其他公开配方；本次不根据暴露题成绩切换配方。

| 配置面 | v15 固定选择 |
| --- | --- |
| 记忆工具 | `create_manage_memory_tool`、`create_search_memory_tool`；正文类型 `str`；保留上游默认名称、参数和 manage instructions |
| CRUD | 上游 create／update／delete；仅能操作本次隔离实验 namespace，不映射到 Product、外部来源清除或用户数据治理权限 |
| Agent | 使用锁定版本可用的 LangGraph ReAct 工厂；实际入口、导入路径与版本写入 lock。弃用告警不是盲目升级理由 |
| 提示 | 简短通用任务说明与原生环境公开规则；不移植 frontier、future_use、finish_turn、永久正文拒绝或强制回写策略 |
| 检索 | 有效语义索引，使用同一 bge-m3 接入；上游 query／filter／limit／offset 及排序结果保持；不偷偷替换成旧 BM25 或全库枚举 |
| 预取 | 此配方不额外增加自动全库／固定 top-k 预取；后续更换为上游 hot-path prefetch 配方必须使用新身份并共享到 matched arms |
| 其他 LangMem 能力 | background memory manager、prompt optimizer 不启用；这是研究范围选择，不宣称这些能力不存在 |
| 工作上下文 | 同一 episode 的多消息共用 thread；下一 episode 使用新 thread，保留同一用户的长期 namespace |
| 默认记忆隔离 | namespace 至少区分 run／arm／user；不同案例、方法臂和失败重跑不共用可变 Store |
| 结束 | 普通 ReAct 最终回答结束；不附加 MiLAi 维护终结仪式或一次额外总结模型调用 |

上游工具将实际管理交给 Store；源码不提供 MiLAi 的精确来源支持、CAS 或语义完整性保证。对未知 ID、重复删除、空内容等行为，先通过上游公共接口记录实际结果，**不把旧合同悄悄补进 B0**。[工具源码](https://github.com/langchain-ai/langmem/blob/9d033b47d9ce53e37e92c92241b0496c0278932e/src/langmem/knowledge/tools.py)

## 5. 开发工作包与依赖顺序

顺序固定为 **A → B → C → D → 开发冻结 → E → F**。B 允许少量兼容性模型请求，因为接口可执行性本身是待解决问题；它们属于 spike，不算 benchmark 或方法结果。正式诊断与原生任务必须在 C／D 完成、窄检查通过后运行。

| 包 | 具体工作与源码落点 | 完成证据 | 未通过时怎样处理 |
| --- | --- | --- | --- |
| A：身份与依赖 | 固定 v14 reference；新增独立 `baseline-langmem` 依赖组；建立 foundation lock；核对公开源码与实际安装分发物 | 依赖可重建；源码／包身份一致；旧 runtime 散列未变 | 修包兼容和锁文件，不进入模型实验 |
| B：Foundation spike | LangGraph agent＋vLLM facade＋原生 LangMem 工具；有效 embedding；持久 Store／checkpointer；一次可控业务动作 | 普通回答、业务、create/search、跨 thread 及冷启动恢复均有真实回执；所有请求计账 | 按 §7 选择原生或薄适配，不能在一个 run 内静默降级 |
| C：任务与评分接入 | 新窄 MERIT 适配与 v14 输入适配；复用原生 world／schema／checker；业务结果原样交付 | 零模型回放能证明消息顺序、业务效果、checker和隔离边界一致；gold 不进入 Agent | 定位适配错误；不修改原题、工具或评分 |
| D：可复现入口 | 配置模板、prepare/run 命令、费用和失败记录、最小 CI；声明固定 B0 recipe | 干净进程可按文档准备；必需窄检查通过；开发冻结可核对 | 修入口与身份；不为发布扩大测试 |
| E：行为 characterization | 原样运行已有 12 例诊断，再运行已暴露完整 arc0 | final-source 结果、失败分母、记忆变化及全部成本；不要求语义全通过 | 机械错误可一般化修复并新冻结；语义失败进入报告，不逐题调 prompt |
| F：结项与交接 | 冻结 B0 配方、实现、环境、数据身份、结果、下一阶段必要接口 | 按 §14 选择 foundation GO／有限交付／PIVOT，并明确 v16 前提 | 不自动开 B1／M1 或换题追分 |

所有工作包使用复用现有能力优先、单一状态所有者和窄接口。不要为有限适配建立事件总线、全局依赖图、通用插件框架或重复验证层。

## 6. A：依赖、源码与环境锁

### 6.1 固定提交和实际安装物必须一致

已存在的只读参考源码：`/cra/memory/mx_memory/reference-sources/contextual-v2.3/langmem-9d033b47d9ce`。实施前复核其 HEAD／工作树；不重复下载、不 vendor、不放入 MiLAi Git。后续必要的 LangGraph 参考源码也放仓库外，并使用实际解析版本对应的提交。

首选在依赖组中使用 LangMem 的**精确 Git commit 依赖**，由 `uv.lock` 固定分发身份；LangGraph、prebuilt、checkpoint、Store 后端、LangChain 及模型适配相关传递依赖同时锁定。源码的 `version=0.0.30` 不证明 PyPI 同名版本包含同一代码。若改用发行包，必须先比较所调用关键文件、记录差异和包 hash，不能仅填写一个版本号就认领提交一致。[固定 pyproject](https://github.com/langchain-ai/langmem/blob/9d033b47d9ce53e37e92c92241b0496c0278932e/pyproject.toml)

在现有 Python 支持范围内，首先使用 CI 的 Python 3.11；不要同时升级 Lab 默认依赖。新增依赖组不能让默认 core import 自动加载整套 LangChain，也不能破坏默认安装解析。

### 6.2 foundation lock 的最小内容

拟新增 `data/locks/langmem-foundation.lock.json`，开发时再生成，不在规划阶段伪造 resolved versions。记录：

- Lab 基点与运行源码映射；上游 URL、commit、声明版本、license、关键文件 SHA、实际安装包来源／hash及 uv.lock SHA。
- Python 与已解析依赖；选用的 graph factory、Store／checkpointer类及后端参数身份。
- B0 配方和 prompt／tool schema SHA；native 或 functional-core transport 身份；embedding index 配置。
- Host／embedding／tokenizer身份、服务版本和 parser配置；可变地址／本地目录放本地配置，不把秘密写入 manifest。

模型沿用 Qwen3.6-35B-A3B-FP8 与 bge-m3 既有身份，实施时核对服务实际配置。沿用已封存的合法模型 manifest，除非文件或身份变化，不重复散列全部权重。固定提交、环境锁、运行数据身份三者缺一时，不能称为已可复现。

## 7. B：vLLM 与公开工具的兼容性 spike

### 7.1 首选 native tool calling

`VLLMClient` 已有 native 请求字段。优先用一个薄的 LangChain ChatModel facade，将 messages／tools 转成现有 `client.chat()` 请求，将原始响应转换为 AIMessage／ToolCall；沿用现有 ledger、容量检查和响应记录。若使用官方模型适配器，也必须把实际 HTTP 尝试接入同一计账点。

兼容性检查同时覆盖：tool 名称／JSON 参数／call ID、无工具最终回答、错误回执、tool_result 后继续生成。捕获 malformed、length 截断及 parser失败的原始结果；不能从坏 JSON 中截出一段就执行。顺序执行可控业务工具，真实 Provider 并发为 1；若模型一次返回多个 calls，完整保留并按固定顺序处理，不丢弃剩余动作。

SDK 自带重试若未逐次纳入账本，应关闭；不能把多次请求记成一次。服务端 parser能力以实际锁定版本验证，不因 endpoint 自称兼容就假定成功。需要服务参数变更时应使用明确的新服务身份，在实验冻结前完成，不能在对比中途修改。[vLLM 工具调用说明](https://docs.vllm.ai/en/latest/features/tool_calling/)

### 7.2 明确而有限的 fallback

若失败属于真实 native parser／tool schema 兼容问题，先记录最小复现及已尝试的通用修复，再选择 LangMem functional-core＋现有 JSON-action transport。薄适配只负责模型响应和**实际上游 StructuredTool 调用**，不重写 manage/search，不导入 contextual_host／maintenance／frontier。

fallback 使用独立 `transport_variant` 和 B0 配方身份，不能继续称“原生 LangGraph tool calling 已通过”；后续 B1／M1／M2 必须全部使用同一 transport。若连薄适配都需要复制旧 Host、session、来源合同及恢复系统的大部分逻辑，foundation 判 PIVOT，停在定位结果，不无限扩展兼容层。

### 7.3 spike 验证表

| 编号 | 最小动作 | 必须观察到的结果 |
| --- | --- | --- |
| S1 | 无工具普通回答 | 正常结束、usage 可追溯；不是强制 tool-only 输出 |
| S2 | 一次受控业务调用 | 原生参数／返回内容与 call ID 对应，真实世界状态发生预期变化 |
| S3 | LangMem create 后 query search | 实际 Store 中有记录，非同词查询通过配置的语义索引取得目标；不是在 transcript 复述答案 |
| S4 | 同 thread 第二条消息 | checkpoint 保留合法同会话上下文，没有重复提交第一条用户消息 |
| S5 | 新 thread、同用户 | 只能通过长期 memory 或合法业务查询取得历史事项；上一 thread 对话没有被整体附带 |
| S6 | 关闭进程后重开 | Store 中 ID／正文仍在；同 thread 可恢复，新 thread 可 search；原业务不因续接而自动再做 |

update／delete 的上游调用合同以确定性工具检查补齐，不为“覆盖每个动作”追加模型请求。spike 不使用 MERIT gold，不强迫模型表现跨任务记忆策略；必要的显式“请保存”仅验证工具接通，不能算自然首次保留率。

## 8. 持久化与副作用：三类状态分别验证

| 状态 | 所有者 | 恢复目标 |
| --- | --- | --- |
| thread 中的 messages／graph执行位置 | LangGraph checkpointer | 恢复同一会话；不跨 episode 泄漏全文 |
| 跨 thread 的记忆记录和语义索引 | LangGraph BaseStore 的固定后端 | 冷启动仍可按同一语义查询；保留 ID、正文及后端保证的元数据 |
| 实际业务 intent／result | 原生模拟世界及共享的最小执行记录 | 区分未执行、已执行和未知；恢复不盲目重复外部动作 |

**checkpoint 保存不证明 Store 持久化，graph 恢复也不等于业务动作恰好执行一次。** 官方文档将 thread checkpointer 与长期 Store 明确分开；`InMemoryStore`／内存 saver 不能通过跨进程验收。[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

长期 Store 首选已存在隔离环境中可使用的上游持久后端，例如公开 PostgresStore；不得接到 Product 数据库或真实业务实例。checkpointer 可选锁定的本地持久实现。先核对环境可用性和公开 API，再确定唯一后端；不为本 Goal 部署新存储平台。仅有本地 checkpoint 而缺少可用长期持久后端时，可以完成 spike 的内存部分，但只能记为部分交付，不能宣称 foundation GO。若需要自定义持久 Store 才能推进，先判 PIVOT，而不是顺势重建一个 memory runtime。

业务恢复仅需一个窄的 request／call 身份及结果记录，不移植整个 RuntimeStore。已持久记录成功结果时，可恢复交付原结果；若进程恰好在业务成功与结果落盘之间退出，标明未知，利用原生世界查询／动作幂等能力核对，不能假装具备通用 exactly-once。相同参数的新合法请求不是重复 call。该机械保障在未来全部方法臂共享，不能归因于 Basis。

## 9. C：接入 MERIT 与已有语义诊断

### 9.1 不沿旧 Host 重新造一个 B0

现有 `tools/run_contextual_merit.py` 同时处理旧方法配置、Host、记忆可见性和评分。新运行器调用**原始 MERIT 模块**，保留已有 source pin、world、schema、tool函数和 checker合同；不调用旧 `run_arc()` 或 `task_runtime()`。

新适配只传递公开用户消息、原生工具定义及实际工具返回。方法输入与评分结构分开：`checker_args`、`golds()`、dependent标签、诊断 future_use／rubric 不进入模型、Store或检索 query。模型不会获得未来 episode，也不通过调度参数推知哪道题需要保存。

业务动作先执行原生函数，原始 JSON tool output 原样交付；基础设施可以记录状态、ID和费用，但不能把错误输出改成成功。B0 的这些执行日志默认供运行器恢复与分析，不额外投影成旧 frontier／执行总结，也不注入原本不可见的历史。checker 使用原有 before／after world逻辑，保留 pre-satisfied 情形。`memory_utilized` 等匹配指标仅作使用链证据，不作为记忆不可替代或因果贡献的证明。

### 9.2 两套小样本的固定用途

| 输入 | v15 使用方式 | 解释限制 |
| --- | --- | --- |
| v14 冻结语义诊断 | 12 例、20 个会话，原输入、fixture工具和独立 rubric 原样复用 | 开发行为诊断，不计 native benchmark 分数，不复用 v14 某轮成功摘要当 B0 结果 |
| 原生 MERIT arc0 | 上游 `293933d96b1d1849e1f20d1bb324def5de9ed33f`；hard、base_seed=0、5 episodes、7 条公开消息；原始世界与空记忆启动 | 已暴露回归，不是未见验证；不删失败集、不只跑有利末轮 |

原 arc SHA 为 `32e50fc25c1ce473eccb5c0653e3867072d792c9aed80148236f9b0baff5d12f`，world SHA 为 `221f4be1976ff8bc44ddc97b121dea6e15c22d79eff15dfe551a914342569b29`。诊断执行数据的 JSON SHA 与说明 Markdown 的 SHA 不同，应从既有 freeze 指定的**实际输入文件**读取校验，不用文档摘要替代。

每个诊断实例空记忆启动、内部 session 共用长期 namespace；不同实例完全隔离。MERIT 同一个 arc 的世界与长期 memory 顺序延续，episode 间换新 thread；故障恢复只恢复原任务，不重新把 before world 当当前世界。原始业务历史不能通过恢复日志额外暴露给模型。

### 9.3 失败处理

先修影响所有任务的机械故障，再冻结新版本；保留旧失败请求、费用、世界及未完成阶段。正常结束但没有保存、未更新旧记忆、答非所问属于 B0 语义结果，不在本 Goal 根据题目改 prompt。

因运行器错误或 Provider 失败无法完成的 episode 标 `INTERRUPTED/UNSCORED`，单列原定分母、已执行、可评分、成功数；若原生协议明确将中断计失败，同时保留其原始计分和执行分类。不能把未运行视为全错，也不能仅用完成子集宣称整条 arc 成功。最终源码的完整轨迹与较早版本的局部证据分开。

## 10. 新代码组织与现有能力复用

以下是建议落点，不要求提前创建所有文件。只在实际职责需要时拆分，短类型就近放置。

| 路径／模块 | v15 职责 | 边界 |
| --- | --- | --- |
| `src/milai_lab/baselines/langmem_agent.py` | 公开工具与 Agent 装配、recipe配置、namespace绑定 | 不含未来价值分类、Basis或总结策略 |
| `src/milai_lab/providers/langmem_chat.py` | 必要的 ChatModel／JSON-action薄适配 | 复用现有 VLLMClient、capacity及账本；不复制 HTTP逻辑 |
| `src/milai_lab/datasets/merit.py` | 上游 pin、公开任务／world／tool接口与 scorer隔离 | 不导入 contextual runtime，不改变原生任务；若无公共复用需要可先在窄 runner 内实现 |
| `src/milai_lab/runners/langmem_foundation.py` | thread边界、实验生命周期、freeze核对、结果输出 | 不承担记忆语义维护；不把旧 1,600 行 runner 原样迁入 |
| 现有 `harness/contextual_artifacts.py` | digest、文件写入、连续费用与 trace基础 | 名称旧不等于不能复用；不为了命名整洁作大迁移 |
| 必要的窄动作记录组件 | 仅 request／call／result 恢复事实 | 不引入第二套记忆库、删除／权限／维护合同 |
| `configs/langmem-baseline-v1.json` | 固定 B0 recipe和本地配置模板 | 无开发机秘密；不生成 M1／M2空配置 |
| `data/locks/langmem-foundation.lock.json` | 公开 foundation及依赖身份 | 运行结果另放 manifest；不以 lock冒充运行验收 |
| `tools/prepare_langmem_foundation.py` | 校验上游／本地配置，准备 freeze和已暴露输入引用 | 不下载新 benchmark题或把 gold写入 Agent配置 |
| `tools/run_langmem_foundation.py` | spike／diagnostic／merit子命令，统一调用一个 runner | 不维护三个彼此漂移的 Agent循环 |
| `tests/unit/test_langmem_foundation*.py` | 受影响的少量适配／持久／隔离合同 | 无大规模 replay框架、无每个字段一个镜像测试 |

新 `methods/milai_vnext/` 只在 v16 开始存在真正方法代码时建立。v15 不先造 provenance/versioned_store/decision_basis/attention 的空壳。

新增依赖组的 import不能影响无该组的默认 Lab安装；必要时使用窄可选依赖边界，并给出缺失组的直接提示，不写多层隐式 fallback。任何第三方 API不匹配集中在边界解决，不能让 runner 到处兼容版本分支。

## 11. D：窄检查、CI 与复现交付

### 11.1 必需检查只覆盖新风险

| 检查 | 解决的问题 | 是否需模型 |
| --- | --- | --- |
| 依赖组安装／import；默认 core import | 可选依赖是否隔离、锁是否有效 | 否 |
| 上游 manage/search 调用与返回回放 | ID、内容、删除、query/filter/排序是否被适配器改写 | 否，真实上游工具＋小 Storefixture |
| 模型协议正反例 | native／选定 fallback能否表达正常 final、call、error、truncation | 先零模型；S1–S3作真实接线 |
| Store＋checkpoint冷启动、namespace隔离 | 进程内成功是否掩盖持久或隔离错误 | 先确定性，再 S4–S6 |
| 原生工具／checker与消息边界 | runner有没有改任务或泄漏未来消息／gold | 否 |
| 动作结果保存后的续接 | 是否重复业务、是否把未知当成功 | 否，受控世界 |
| 计账与中断 | 每次请求只记一次，失败及 unknown不归零 | 否 |

只运行这些受影响检查、静态检查。因新增 package模块／依赖，执行相应 boundary检查和一次必要 packaging验证；不因此运行历史全套、全量 benchmark或旧 v14回归。CI增加可选组的窄 foundation job，现有 active／historical jobs保留；不把所有旧测试塞进新 job。

### 11.2 交付入口必须能从模板得到真实配置

文档应提供依赖同步、填写 endpoint／模型 manifest／Store连接、准备、spike、诊断、arc0、离线汇总及续接命令。命令在对应工具实现之后验证，规划期不把未存在命令写成“已可运行”。

复现至少分为：零模型合同检查、真实 vLLM运行、既有结果查看。Store地址或本地目录变化需要新运行配置；改变模型、协议、工具配方或索引产生新方法／运行身份，不能关闭身份校验以恢复旧 checkpoint。

## 12. E：实验规模、计账与指标

### 12.1 运行顺序及规模

1. A–D开发期间仅执行必要 S1–S6兼容性 spike，记录独立 stage。
2. 代码、recipe、服务、索引、容量和数据 identity冻结。
3. 对 12 例旧诊断运行固定 B0，使用原 rubric分析；无需达到 12/12。
4. 对已暴露完整 arc0运行固定 B0，保留五集及全部失败。
5. 冷恢复与来源／成本核对优先复用以上制品，不为“再确认”追加同义运行。

这个规模是本阶段的数据范围，不是累计请求／token硬停止。因已定位机械错误进行必要复核仍连续计账；没有新问题就不重复。无新 MERIT seeds、无 MemSyco正式选题、无 B1/M1/M2真实比较。Judge仅在原生评分或少量语义复核确有需要时使用 vLLM，输入与方法隔离；能用原生 checker或人工有限复核的，不增加 Judge调用。

### 12.2 请求及费用合同

Host／embedding／Judge使用同一连续 ledger，按 stage、run、case、episode分列。所有 spike、SDK重试、截断、故障、修复复核都计入；unknown保留预留值及状态，不能当作零。一次请求在 transport计账后，LangChain callback只能补元数据，不能再次收费。

累计请求／生成tokens／embeddingtokens／验证次数上限为 null；单次上下文、输出、超时、每个workflow的调用容量仍有效。先核对既有配置的 `thinking=false`、输出4096、上下文65536、每公开消息容量12在新 graph语义下的映射，再在真实请求前冻结，不按某一题临时增大。

输入／输出分列，生成tokens明确为两者之和；embedding单列；Judge不是部署每次回答成本；代理开发费用另列。prefix caching若没有实际命中／服务指标就记 unavailable，不因少发文字或重复前缀推算GPU节约。

### 12.3 v15主结果表

| 维度 | 记录方式 |
| --- | --- |
| 执行 | 原定／已运行／可评分／中断数，真实Provider与工具错误；技术验收单列 |
| 原生任务 | MERIT原规则native、dependent分母和逐集结果；v14诊断单独列，不混成总准确率 |
| 首次保留 | 对已知未来约定在首次session关闭时实际持久结果及后续消费；明确漏存，不以模型说“记住了”代替 |
| 当前状态 | 外部动作发生后 Store里相关记录是否过时、重复／冲突；不依赖没有被上游定义的 CURRENT字段 |
| 有效内容保持 | 修订后不相关但仍有效内容是否误丢；既看漏改也看误改 |
| 行动依据 | 实际完成回执、无回执完成声明、政策／工具不一致分别列；无程序语义审查器 |
| 记忆正文 | 会话引用／历史叙述等问题作为观察，不能通过给 B0加写入拒绝规则来“修评分” |
| 成本 | 实际input/output、embedding、requests、失败成本、Provider墙钟和本地执行；完整生命周期计入 |
| 研究限制 | 单模型、旧开发集、没有 matched方法实验；维护完成不替代任务成功 |

主要失败分类延续 MEMORY_MISS、MEMORY_MISUSE、ACTION_GROUNDING_ERROR、TASK_COMPLETION_ERROR、POLICY_ACTION_MISMATCH、BUSINESS_TOOL_ERROR；新增的 FOUNDATION_INTEGRATION_ERROR／PERSISTENCE_ERROR单列。SCORING_MISMATCH需要原输入和评分规则的独立证据，不能由“我不同意Judge”直接认定。

## 13. 后续 v16／v17 的接口交接与实验纪律

### 13.1 B1：instrumentation不等于语义改造

v16只在 B0已实际调用的位置记录 observation身份、精确版本、实际写入与业务回执。`source_refs`必须区分**写入当时可见材料**与**Host明确声明采用的依据**；仅凭同一次调用／同一会话不能自动证明内容受该来源支持。基线从未提供来源关系时保留 unknown，不补一个虚假的“全历史支持”。

parity用相同合法tool calls回放比较B0/B1的Store结果、返回正文、schema、query/filter/limit/offset和排序。生成ID／时钟如需归一化，仅在比较器中用一一映射，不能把生产执行中的两次不同操作合并。若 hidden revision意外进入embedding输入、ranking或模型消息，parity失败。

未来M1需要引用句柄时，B1与所有matched臂共享同一最小材料外壳；外壳新增模型可见内容必须单独记录为设计变化，不能仍叫“完全不可见”。不要给B1增加future_use、reconciliation、frontier、强制终结或旧CAS语义。B0和B1差异没有解释清楚前不评价M1。

### 13.2 M1：只移植纯机制

一项task-local active decision、action-sensitive gap、精确adopted revision/span、程序触发recheck、状态no-op、同次ReAct生成delta。旧采用的 `@3`不能随Store更新自动重绑`@4`；新观察没有旧依赖边时，由同一Host判断是否影响已有decision。没有行动分歧时保持无Basis；不强制采用MemoryCard或制造gap。

v16开始设计时必须证明选择的native／fallback响应载体能把state delta与业务／记忆动作放在**同一次生成**，且状态更新本身不触发新的模型回合。不能用一个额外“update_state工具→再继续”伪装零额外调用。表达载体及schema是待验证设计，不因v15 native工具接通就宣称已解决。

### 13.3 M2与matched实验

M2保留explicit query优先、普通检索fallback、gap-directed查询和有限扩展／停止。上游search的query是必填字符串；后续如果引入“未给query则自动gap”入口，必须明确新增的控制入口／可选参数，不能覆盖Host已经给出的合法query，不能声称只开一个标志就完成接线。

B1→M1比较表示与重核；M1→M2比较Attention。共同使用同一Host、公共prompt部分、记忆工具、Store、索引、业务权限、历史范围、模型容量和恢复保障；每臂独立世界／namespace，从原始相同起点运行，不分享其他臂学出的memory。额外信息或循环次数需要显式纳入成本和设计，不假装预算相同。

v17先冻结方法与选择规则，再生成／读取未见MERIT小样本：从实际未暴露seed中前瞻选两条完整arc；3／4仅为当前候选。MemSyco使用锁定原生split中少量前瞻样本，具体数量、固定排序／seed及原生评分在任何读题前登记；未评分、不适用机制和失败不能事后换题。此处不创建selection，也不读取新题。

后续指标增加activation、churn、adopted validity、recheck precision／recall、gap utility与state开销。precision／recall需要独立标注的确有变化机会及全体分母；若只观察触发事件只能报告precision诊断，不能捏造recall。state-induced calls不能单凭工具次数认定因果，应结合matched轨迹或消融。StateMemBench保持NOT_RUN，不作为交付依赖。

## 14. 验收、结项与转向条件

| Gate | 达标条件 | 不足时的结论 |
| --- | --- | --- |
| G0 身份 | 上游源码、实际安装、Agent recipe、配置／模型、数据及Lab源码对应 | IDENTITY_INCOMPLETE，不进入效果比较 |
| G1 工具接入 | 普通回答、原生业务、真实LangMem manage/search、语义索引均可执行 | FOUNDATION_NOT_READY；合法语义miss不属于此类 |
| G2 持久与隔离 | 同thread／新thread／冷启动分别验证，无跨case或跨episode全文泄漏，恢复不盲目重做动作 | SCOPED_PARTIAL_DELIVERY，不宣称foundation GO |
| G3 评测可信 | 原始任务／工具／评分未改，gold隔离，所有attempt及费用保留 | EVALUATION_INVALID，先修共享机械问题 |
| G4 行为交付 | 固定B0完成已声明诊断和arc0的可解释执行；已知语义失败逐项保留 | 技术完整可记COMPLETE_WITH_BASELINE_FAILURES；机械中断未解决仍为部分交付 |
| G5 范围 | 无旧runtime新语义、无Product改动、无候选扩张／未见题消费 | 修正范围后才交接 |

全部技术gate成立时可以结项 `COMPLETE_FOUNDATION_CHARACTERIZED`；若语义反例存在则明确 `COMPLETE_WITH_BASELINE_FAILURES`。两者均不表示v16／v17自动开始或方法有效。需要复制旧平台、无法支持实际检索／持久性或持续混入MiLAi语义时，交付 `FOUNDATION_PIVOT_REQUIRED`，记录下一候选选择依据，不在同Goal里继续集成多套系统。

**v15不以“比v14更高分”作为GO条件。** v14和B0有不同Agent、提示及工具合同，历史分数仅作描述，不能形成方法因果结论。后续M1若与强B1工作笔记持平或更差，应保留负结果；不能通过继续加字段、换样本或增加调用把机制“做有效”。

## 15. 开发组织、成本与交付清单

常规由一个Sol xhigh负责adapter／graph／provider接线及其窄验证。Luna max可处理上游identity、依赖清单、离线费用核对和文档，限定不重叠文件；Astra xhigh仅在native／Store／因果对照等具体疑难问题无法收敛时介入。不设常驻reviewer或额外语义审核Agent。root唯一控制真实模型请求，concurrency=1；Luna high按已有授权负责最终提交发布。这是后续实施分工，本轮不启动这些开发任务。

按工作包交付可审查增量，不以固定工时、累计token或复核次数强制结项；每次额外调用必须对应待解释的问题。完成相关窄检查后继续交付，不反复跑已经通过的检查。开发问题由最接近故障的模块解决，避免在多个层面堆重复断言或case-specific补丁。

最终应交付以下内容；当前均未生成开发结果：

- [ ] A：reference与foundation lock、独立依赖组／uv.lock、许可与源码核对。
- [ ] B：公开工具＋vLLM薄接入、有效索引、明确持久后端及S1–S6证据。
- [ ] C：独立MERIT／诊断适配、原生业务／评分和历史边界核对。
- [ ] D：固定B0配置、prepare/run／恢复说明、窄检查与CI入口。
- [ ] E：12例旧诊断＋完整暴露arc0，原始失败及连续费用。
- [ ] F：`MILA_LANGMEM_FOUNDATION_V15_RESULTS_20260926.md`与复现文档，明确最终identity、GO/PIVOT、已运行／未运行和v16交接条件。

源码、精简manifest、配置模板和结果摘要可以提交；模型、数据库、原始transcript、第三方checkout及运行目录保持仓库外／ignored。旧制品不覆盖，失败记录不改成成功。回退以本Goal所列基点及后续每个实际提交为准，不为规划单独重建回滚框架。

## 16. 本轮规划交付记录

已完整读取319行路线图，核对当前Lab规则、v14结果、47份运行文件身份、provider／MERIT／持久库关键耦合点，以及本地固定LangMem源码与官方持久化／工具调用文档。路线图原文保持不变。

本轮仅生成本Goal、更新最新规划导航及过期的v14活动状态。尚未生成foundation lock、解析或安装新依赖、创建v15运行代码、运行测试／模型请求／新benchmark，也未消费未见样本。后续开发应从A开始，不能将本段源码阅读当作S1–S6实测。
