# U2 第二外部系统：SimpleMem text

状态：**ENGINEERING_READY；REAL_RUN_NOT_STARTED**。这是[统一计划](MILAI_UNIFIED_DEVELOPMENT_EXPERIMENT_PLAN_V8_V9_20260928.md) §6.2／9.1 的第二外部系统，
接续已发布的[五方法主表](MILAI_UNIFIED_U2_MAIN_RESULTS_20260929.md)（报告提交 `81f2cf469f0a64f53256838c7884592c8d88ab7e`）。
主表运行源码 A `795725a2`／执行 B `e6df2f5d`、输入、分数、失败和账本全部保留。实现及窄检查已完成；本文件不是实际执行冻结或效果证据。
Root 负责本协议、选择、实际串行 HTTP、评分和成本；Sol xhigh 负责薄适配及必要检查，Luna high 负责独立依赖环境和 Git 发布。

## 选择及第一处接入缺口

选择本地官方 SimpleMem `db80b6a7c591e0ea730a058e9f5fc4eb06572299` 的 `simplemem.core` 文本组件，
实际方法名为 `simplemem_text`：**SimpleMem 文本记忆后端＋共同 benchmark reader／业务 Host**。
保留 MemoryBuilder、默认 LanceDB／Tantivy VectorStore 和 HybridRetriever 的真实代码；不用 Omni、EvolveMem、优化器或另一套 server retriever。

两种竞争解释：顶层文本构造器无 embedding 对象注入，因而需要缺失的本地 encoder 资产；或所有真实文本路径都必须新增模型。
源码证实第一项，却不支持第二项：VectorStore 的公共 `embedding_model` 参数、MemoryBuilder／HybridRetriever 的 `llm_client` 参数可组合真实核心组件。
因此只在公开组件边界接入已计账的 Qwen 与 bge-m3，不下载 encoder、不伪造 import、不改上游算法。原生 `ask()` 的最终 AnswerGenerator
由已有共同 reader／Agent 替代；不得称未经修改的完整端到端 SimpleMem Q&A 复现。

原生 core 已将 planning、semantic／lexical／symbolic 查询以及最多两轮 reflection 放在 `retrieve()` 内，必须完整保留。
Qwen 替代默认 gpt-4.1-mini、bge-m3 替代 Qwen3-Embedding，是明确的模型配置差异。
文本路径不初始化 SentenceTransformer；实际需要 LanceDB、PyArrow、dateparser、Tantivy、pylance 及已有 numpy／pydantic／openai。
Luna 在新 ignored 环境安装必要 CPU 依赖并记录精确解析版本；不修改历史环境或现有服务。
初次纯导入未覆盖 FTS 构造，真实 SDK 检查随后发现缺少 pylance。资源检索曾遗漏上游 requirements 的 `pylance==0.39.0`，
先按 LanceDB extra 的最低版本范围装了0.25.1；在真正索引测试之前完整复核并更正为上游精确 pin。
初始7 pass／2 fail、R1／R2环境回执及更正全部保留；导入成功不能替代真实索引检查。
上游 LICENSE 实文 MIT、setup classifier 却写 Apache 的元数据差异保留；本项目不复制再分发整份上游源码。

## 固定方法边界

| 项目 | 本次合同 |
| --- | --- |
| 原生 writer | window40、overlap2，保留实际 prompt、parser、UUID、字段和原生有限重试 |
| 原生 retrieval | semantic25／keyword5／structured5，planning=true、reflection=true、max rounds2 |
| 并行 | builder 与 retrieval 均关闭原生 parallel，全部真实 HTTP 串行1 |
| LLM | 现有 Qwen@7862；核心阶段保留上游调用所给温度，Host／共同 reader 温度0；max4096、thinking=false、nonstreaming |
| Embedding | 现有 bge-m3@7861，1024维；保留 document／query 区别，有限向量校验和与原生相同的 L2 normalization；无 encoder fallback |
| MemSyco writer cadence | 完整有序、无 question／gold 的 archive，经原生 add_dialogues，再一次 process_remaining |
| MERIT writer cadence | 每个实际已关闭 public turn，完整过去消息经同一原生摄入及 process_remaining；不是新实时业务授权 |
| 查询材料 | 原生取回顺序；完整 restatement 及非空原生 time/location/person/entity/topic，完整字段和实际 ID 留在 trace；按共同16000字符预算整条纳入／省略 |
| 隔离 | 每 run／arm／owner／exact-history 独立目录和数据库；owner 不进入模型可任意选择的路径参数 |

短 turn flush 是上游公开 `finalize()` 所调用的 `process_remaining()`，但与离线完整40行窗口不是同一摄入节奏。
该 pin 的短 flush 清空 buffer、不会像完整窗口那样更新 `previous_entries`，因而没有跨 flush overlap／前窗口上下文。
保留并披露这项原生行为，不修补它来提高比较成绩。关闭并行也会影响前窗口上下文与结果完成顺序，不能称纯计算加速差异。
原生 dateparser 使用实际运行时钟且偏向过去日期；记录运行日期，不能将共同 reader 的固定日期偷偷注入其解析。
拒绝意外 ambient config.py／环境变量改变已冻结方法；不在运行中调整 prompt、temperature、窗口、top-k 或反思轮数。

## 输入、实际调用与原生结果

继续使用已有 gold-free ArchiveInput／TaskInput，不修改问题、完整历史、工具、world 或 checker。
每个原消息按原序转成原生 Dialogue，保留 role、实际时间、来源映射和完整工具参数／回执作为过去数据；没有时间就不虚构日期。
原生存储实际未保留的字段须单独说明；审计映射不成为模型额外可见事实。统计 source group 不等于可共享数据库的 owner／exact history。

MemSyco 形成不见问题，查询不回写答案；仍是原官方 reader prompt、日期2025-06-01、空 extra instruction、相同格式和固定 Judge。
MERIT 仅用当时已出现的当前 Human 查询，每个 public turn 一次自动检索，ReAct 续接复用材料。
Host 获得真实 SimpleMem 只读 search 工具及原有实际 MCP read_history，业务工具、world、checker 与共同 LangGraph 不变。
search 工具只向 Host 返回实际原生记录、query 和必要状态；内部 planner 解析、计账与重试观察保留在审计中，不回流为额外模型上下文。
SimpleMem SDK 调用不冒充 Host→MiLAi MCP；两条能力及费用各自记录。原先 MiLAi strict CRUD/MCP 路径不改。

所有真实请求复用现有 VLLMClient、同一个 RunBudget 和串行锁，不开第二个 SDK HTTP 通道或账本。
原生有限 HTTP／parse 重试可执行，每个真实请求单独计费；外层不重跑 invocation，不自动重放业务副作用。

- MemSyco 每个完整 archive build 共12次 generation，不能按窗口重置。
- MemSyco 每次 query 的 planning／reflection／重试及共同 reader 共12次 generation。
- MERIT 每个公开消息的内部检索、Host 续接及结束后的 writer 共12次 generation。
- 全部 embedding、未知 usage、空提取、失败、原生重试及观察开销保留；未发出的拒绝不伪造 token。

上游可能捕获异常后返回空列表／fallback。适配层必须保留拒绝和实际部分状态：admission／本地请求容量拒绝不得变成成功空提取，
应报 retrieval／maintenance incomplete。原生某次失败后成功恢复的重试与最终未恢复的 fallback 分开；不能仅凭曾有错误就否定已恢复结果。
合法空 JSON 提取、解析重试耗尽后空结果、默认检索 fallback 是不同 outcome。
原生 degraded 行为保留实际 bank 供共同 reader，单列形成／检索退化；不靠外层修复补答。若业务已完成而维护不完整，
保留实际回答、world、ID、checkpoint、费用，分别报告业务与维护，不能以重放业务补齐 writer。
仅此新臂允许后续独立 query 读取形成终态 DEGRADED／INCOMPLETE 留下且 owner／身份／snapshot 可核验的真实部分 bank；
查询有自己的已声明公开消息额度，但不重置旧形成费用或补做形成。形成完成率与实际 native 回答分分别报告。
缺失身份、损坏库或无法证明存在的失败产物不能伪装成空库继续。该处理不改变旧五臂状态合同。
Store 异常不能吞成健康索引；原生搜索吞错也须显示相应渠道退化。不得声称任意 in-flight builder 恢复或外部 exactly-once。

## 工程检查、曝光 pilot 与比较

先完成实现和真依赖窄检查：实际 upstream import／LanceDB／Tantivy，多视图 retrieval 与 reflection，完整40行窗口及尾部 flush，
共同 reader 边界、真实图的当前 Human／工具续接／closed-turn hook、owner 与重开快照隔离、共享12及被原生吞掉的拒绝。
以 MockHTTP 验证计账和真实 SDK，不调用共享模型或 Postgres；旧五臂只检查直接受改动影响的邻接合同。
依赖／入口涉及包装时完成必要构建，发布不重复已通过检查。CI 必须有实际依赖和源码归属，不能以 skip 冒充 SDK 检查通过。

实际工程回执见[机器清单](../data/manifests/unified-v8-v9-u2-simplemem-engineering-20260929.json)：14个去重目标最终通过、0skip，含12个新SDK目标及2个旧邻接目标。
静态类型、边界、检查矩阵及必要构建通过；首次依赖／harness／loader／静态问题均保留。显式search工具经实际StateGraph／ToolNode只交付query/status/results，完整内部审计留在私有制品。
两份零模型prepare属于最后工具过滤之前的源码，保留为接口证据；Root将在正式发布提交重新生成真实运行身份。初次与最终构建分别保留，不为发布重跑通过检查。

源码发布后，Root 在新运行身份冻结既有 U2 pilot 的首题 MemSyco 和完整 `arc5-000`：一次 build、一次 query、一次完整 arc。
这些输入已经曝光；不发额外 MemSyco Judge 来把语义得分用作工程门槛。若出现真实工程 bug，保留失败、竞争解释和全部成本，
最小修复后重新冻结受影响范围；正常低分不触发参数调优。

工程可运行后，本外部臂接入**相同已曝光 U2 development**：60题／54来源组／60 distinct histories，以及18完整 MERIT arcs／90 episodes／36 dependent。
不重跑旧五臂、不替换题目、不从分数选择子集。这不是新增 unseen 确认，也不是与 ordinary 的同 bank 消融。
顺序为60 archive builds、60 queries、18完整 arcs；每项外层只尝试一次，隔离 namespace／store／checkpoint／world。
具体源码提交、全部输入字节、配置、依赖、scorer、实际命令／顺序和当时账本须在真实运行前另存 execution freeze。
发布后的实际源码 SHA 将进入各阶段 execution freeze；本协议不预填未知提交或虚构运行结果。

所有计划回答终止后先冻结 answer batch，再按旧主表固定原生 scorer／Judge 配置各评分一次；失败／unknown 留在计划分母。
按三条 MemSyco track 和 MERIT episode／dependent／whole arc 分别报告，沿用事前 cluster bootstrap 与不可评分端点规则。
与旧 Raw／FullHistory 的配对比较披露本臂较晚运行、已见 development 结果、库／模型／温度／调用策略不同等混杂。
不构造总 memory 准确率，不用单次系统比较宣称稳定独立收益或原生默认模型复现。

## 成本与后续门槛

开始本工作时连续账本为 **5941 generation requests／10,864,712 generation tokens／414,792 embedding tokens**；
权威文件仍为原树 `artifacts/ser-v20/budget.json`。每个新阶段以实际账本前后差额及请求 trace 核对，不能重置旧账或把开发代理 token 混入。
冷建、query、retrieval planning／reflection、closed-turn maintenance、Host、Judge 和观察费用分别列出；MCP／backend inclusive 时延不相加。
物理 I/O、GPU小时、货币和净 Store CPU 若未测，继续 unknown。

Continue 仅表示完成第二外部系统的公平可运行对照，不预设效果。报告之后分别处理 U3／U4／U5 条件门槛并完成 U6。
本工作不顺带实现 label 呈现修复、typed-ref、writer 子任务、State／Attention 平台或第二模型部署。
当前完整 Goal 仍 ACTIVE，研究 NOT_ACHIEVED，Product NO_GO；PR72 保持 draft/open，旧 main／PR70／PR71 不改。
