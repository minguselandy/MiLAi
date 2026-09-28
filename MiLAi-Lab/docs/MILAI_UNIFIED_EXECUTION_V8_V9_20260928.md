---
status: ACTIVE_U0_U1_PREPARATION
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
plan_sha256: b496818cc94dc5a3eee83f7795f8afb7f145cc16aa628f31c52d7e33251a948c
base_commit: 77dfc2f43f2307bb649cdbee9d62a97e5863fac0
research_goal: NOT_ACHIEVED
product: NO_GO
---

# V8/V9 统一计划执行记录

实际 Goal 明确授权详细阅读并执行[统一计划](MILAI_UNIFIED_DEVELOPMENT_EXPERIMENT_PLAN_V8_V9_20260928.md)。
最新用户补充：可以设置 vLLM、更改模型配置；vLLM 模拟 Host 的推理，Host 仍以 Agent 模式通过 MCP 工具调用 MiLAi。
此明确授权优先于旧阶段禁止调整 vLLM 的限制。旧 v7 结案、旧实验失败及原计划字节保留。
Root 已完整阅读统一计划 1266 行、v9 609 行和 v8 1185 行；三份原文件 SHA 保存在 U0 来源清单，原字节不改。

本 Goal 覆盖 U0—U6 的适用工作，不能在 U0/U1 smoke 通过后缩成更小目标。
最低交付包含 MERIT、MemSyco 的原生适配和独立比较切片、至少三个强简单对照与一个真实外部系统。
正常模型低分不阻止比较；U3/U4/U5 按实际证据和依赖门槛进入，未触发必须说明，不能冒充完成能力。

## 初始现场与职责

Luna high 从 `77dfc2f` 建立隔离树 `/cra/memory/mx_memory/MiLAi-worktrees/unified-v8-v9`，
分支 `feat/lab-unified-benchmarks-v8-v9-20260928`。原本地 main 为 `9515017`，远端 main 为 `07cc364f`；
PR70/71 仍 draft/open、未合并，分别为 `c6f335fe`、`77dfc2f`。没有 pull/reset/merge 原树。
原树十二份未跟踪计划/复盘及 v27 草稿保留。刚才两次 Goal 切换只产生只读核对，无后台实验或下载任务。

Root 负责文档、原生选择/曝光清单、冻结、全部真实 Host/embedding/Judge 调用、评分、账本与验收。
复用 Sol xhigh 作为唯一源码/config/runner/CI 负责人；Luna high 负责必要公开资源和 Git 发布。
Astra xhigh 仅在具体难题存在时启用，当前未另派常驻审计。

## 新增 MCP 验收边界

目标链为原生合法输入 → Host Agent/vLLM 实际模型请求 → Agent 工具选择 → MCP 请求 →
同一 MiLAi strict CRUD/Store → MCP 实际回执 → Host 续接与后续 session 使用。
不能把函数直调、模拟 MCP 或打印工具名当成该链成立。MCP 只暴露已有逻辑入口，不增加第二套长期事实库。
Lab 原型边界保留，不借此迁移 Product 或导入 Product 私有实现。

后端历史摄入仍遵守 benchmark 原生 boundary，不把历史对话变成新实时命令。
自主 Agent、原生 episode-end writer、后端共同 reader 是不同方法合同，分别记录。
本轮要在真实 MCP 链成立后再开展正式模型比较；scorer/gold 保持离线。

## 第一个实际断点与竞争解释

现有 `langmem_merit.py` 直接使用 LangGraph/strict tools，尚未证明 Agent→MCP→MiLAi 的实际传输链。
现有 MemSyco loader/scorer 存在，但其旧 `screen/confirmation` 清单及旧 recipe 不能自动代表本轮原生接通。

解释一：已有研究路径只缺 MCP 薄传输和原生接口映射，可保留 Store/CRUD/Agent/计账。
解释二：已有 Product MCP 路径与研究 MemoryService 不是同一合同；直接替换可能引入额外能力或改变比较，
需明确服务身份与调用边界，不能因为名称相同就复用为已完成能力。
Sol 已实现最小 MCP 切片：同一 runtime 内启动 loopback HTTP MCP，复用原 Store、embedding client 和单一 RunBudget。
Agent 的 manage/search/read 以及程序发起的 records/search/exact 取材均走实际 MCP；调用来源分开记录。
后者不算 Agent 自主工具选择，服务端观测审计不回流模型。旧 direct 配方保留以复现历史。
Root 同时核对原生资源、曝光、服务和评分，不先运行大矩阵。

[MCP工程检查](../data/manifests/unified-v8-v9-mcp-engineering-checks-20260928.json)已通过20个去重窄测，
覆盖真实HTTP CRUD／拒绝／分页／owner／重开、JSON与native Graph、单一预算与真实Provenance上下文、旧默认邻接。
Ruff、3文件Mypy、验证矩阵、两项边界及diff检查通过；两份实际配置完成临时目录零模型prepare。
Root核对5个实现／测试文件及27个检查制品的SHA一致，未重复运行已通过检查。
底层Store异常按RPC失败暴露，不自动重试；UUID参数拒绝使用MCP invalid_arguments格式，合法回执内容保持原样。
HTTP和SDK超时共同取现有Host／embedding超时最大值；没有独立账本。
初期参数拒绝接线问题及测试断言／静态检查失败均已留存。检查使用MockHost/embedding、内存Store及本地SQLite，
没有真实Host、embedding、Judge或共享Postgres调用，不代表语义效果。
源码已由 Luna 发布为 `196fa0136effc442b33a346df4bd17631807542d`，Root 核对远端 SHA 一致。

## 原生资源、曝光和事前选样

[U0 来源清单](../data/manifests/unified-v8-v9-u0-sources-20260928.json)记录 Luna 的资源回执、源码／许可、
环境和历史四个首断点。MERIT 固定 `293933d96b1d1849e1f20d1bb324def5de9ed33f`，MemSyco 固定
`fd1f0f0270f35467aace1f9c0bf6a8bfb9b87221`，均与核对时官方 HEAD 一致；已有源码和数据可复用，0下载／安装。
Mem0 使用现有 v26 精确 pin 时须明确不是最新上游；SimpleMem 源码已在本地，第二系统待首表完成后选择接入。
MemSyco 顶层为 MIT，但数据卡未单独声明数据许可；本地评估使用已有官方数据，公开只提供 IDs/hash 和获取说明，
不把代码许可写成已单独核实的数据再分发许可。

[曝光清单](../data/manifests/unified-v8-v9-exposure-20260928.json)保守排除旧 MemSyco 24 个已声明 ID
所在的全部 20 个来源／历史连通组（327 行），其中 13 个 ID 有实际运行／结果关联。
以完全相同 source_id 或完整 dialogue hash 连成组，再按固定 SHA 排序，禁止组跨 smoke/dev/confirmation。
同阶段不同 task 的共享组仍按相关单位报告。实际[选择清单](../data/manifests/unified-v8-v9-memsyco-subsets-20260928.json)
为 smoke **6题/6组**、development **60题/54组**、预留 confirmation **75题/74组**。
valid-selection 的 350 行只有 45 个连通组，排除历史 8 组后，2 smoke＋20 dev 只剩 15 confirmation；
因此确认集改为 scope30＋valid15＋personalized30，不能重复来源凑90题。两次零模型准备失败及调整已记录；未按答案或分数选样。

MERIT 官方 `DOMAINS` 提供 d1/d2/d3 三个独立入口及其 tools/world/system prompt；每个原生五 episode 完整保留。
补充扫描7172份JSON/Markdown元数据（约253MB），只发现已知arc0—4，未发现 d2/d3 运行身份。
[前瞻规则](../data/manifests/unified-v8-v9-merit-selection-policy-20260928.json)固定按阶段、域、难度依次取未用 seed：
smoke6 arcs（5—10）、dev18（11—28）、confirmation36（29—64）。尚未生成新 arc；源码冻结后生成原字节并核对 hash。
新 seed 仍共用官方模板，不能称为独立任务家族。官方 leak check 与实际 NoMemory 轨迹、pre_satisfied 分别记录。

原生基线核查：MERIT starter RollingSummary 只是截取，升级版 LLMSummary 对单集作摘要后继承追加逻辑，
不能冒充联合旧摘要重写的强基线；真正 rolling summary 必须另名、计入生成费用。
MemSyco 的 gold memory/evaluation 仅供离线 scorer，原生 question 不进建库，历史不按实时命令重放。
原生 reader 使用 temperature0.2；本轮拟统一为本地 temperature0/max4096/thinking=false，
此为明确的本地模型配置差异，不称官方模型榜单复现。正式请求仍待方法／协议冻结。
Root 已离线核对三类 Judge prompt 与固定上游常量逐字一致。使用固定本地 tokenizer、原生 reader system/date 和完整对话格式，
smoke6题输入为285—1763 tokens，dev60题为291—2002 tokens；包含4096输出预留和512安全量后均可完整容纳。
没有按长度筛题、裁剪历史或降低容量制造选择压力；confirmation 内容未用于这项容量检查。

### MemSyco 原生 reader 与 Agent 接口裁决

原生 `run_one` 先 `build_baseline_context(history, question)`，再以普通 reader 回答；最新用户要求实际 Agent→MCP。
Root 将此具体接口冲突交给复用 Astra xhigh 一次分析，未设常驻审计。两种解释／可检验目标分别为：
共同 reader 可以识别后端形成／取材的差异；加入 Agent 循环则同时改变查询规划、额外计算、工具目录和呈现。
采用以下最小合同，交 Sol 收敛实现：

- 主表：harness 在原生 boundary 提交完整归档历史，MiLAi Host Agent 自主决定 CRUD，经真实 MCP 和同一 Store 执行；
  不含目标 question/gold，不把归档发言当实时命令。称“边界触发、Agent决定操作”，不宣称自主发现维护时机。
- 主表查询：adapter 通过同一 MCP 的 program search 取得材料，使用官方 reader prompt/context label/question 和 scorer。
  明确 origin=material；共同 reader 后端系统比较不证明 Host 自主选择检索。
- Agent 扩展：只复用 smoke 三任务各2题及其合法形成快照，运行实际不同的 MiLAi／ordinary 一臂，允许自然零调用；
  原问题与 scorer 保留，回答改为 Agent 工具循环，单列身份、效果和成本，不按 gold 强制 search。
- RawDialogue、摘要、RAG、外部系统不扩成第二张 Agent 大矩阵。U2 60题／18完整arcs仍须完成；
  这6题扩展及前述3消息接线诊断都不能替代全 Goal。MERIT 持续承担真实业务工具／world 的 Agent 行动比较。

正式运行前还需固定形成时机／工具权限、reader模型参数、query来源/top-k/材料预算、来源身份及合法缓存键。
问题／生成答案不得污染历史形成快照；复用只计一次实际构建，并同时报告冷启动成本与合法查询机会摊销值。
形成、检索、Agent续接、embedding、MCP、Judge、失败和缓存全部计账；主表与扩展不合并为纯记忆组件收益。

## 服务与连续成本起点

只读 GET 已核实 Host7860：vLLM0.27.1、Qwen3.6-35B-A3B-FP8、容量65536。
容器 `25f0a0dee927`（pid2160380）以同一 `/cra/qwen36-35B` 资产运行，TP2、gpu_memory_utilization0.9、
reasoning_parser=qwen3、default enable_thinking=false，无 auto-tool-choice/tool-call-parser。
Embedding7861：vLLM0.9.1、bge-m3；已有 reranker7961，是否纳入强基线待接口和费用核对。
U0 未发任何 generation/embedding/Judge 请求。配置修改先记录原/新命令、资产、parser 和回退，不混用旧运行身份。

在用户允许 vLLM 配置变更后，Root 记录[首次准备](../data/manifests/unified-v8-v9-host-service-20260928.json)，
以原镜像／权重、TP2、65536、non-thinking，在GPU2/3和loopback7862启动独立 native 服务，
启用 auto tool choice＋qwen3_coder。旧7860、embedding和reranker未改。
首次启动因 CUDA 初始化后每卡 free35.37GiB 小于0.9要求的35.54GiB而失败，未产生模型调用。
保留退出容器、完整日志、两种解释与首断点；[R2准备](../data/manifests/unified-v8-v9-host-service-r2-20260928.json)
只把新服务 gpu_memory_utilization 改为0.88，其他模型／生成参数不变。
[R2启动验收](../data/manifests/unified-v8-v9-host-service-r2-ready-20260928.json)已确认7862返回预期模型／65536、
generation和prompt计数为0；旧7860／7861／7961均可访问。此为HTTP就绪，不是原生工具语义验收。
回退是停止新容器，保留日志和原服务。权重仅复用本地资产；小配置／tokenizer文件已hash，完整权重revision仍unknown。
初始化和编译消耗了GPU资源；0实验调用不表示0运维成本，GPU小时和货币费用未独立计量。

接线验收采用[独立最小协议](../data/diagnostics/unified-v8-v9-mcp-smoke/protocol.json)：
原样复用已曝光 v7 save_plan 两消息与 read_only 一消息，以 native＋实际 MCP 运行；先发布源码、输入和协议，
随后在同一源码提交下冻结准备身份，再发送真实请求。
它验证实际保存、fresh-session材料交付和合法no-write，不计入原生benchmark或协议效果结论。Root独自执行、离线评分；
Sol 的真实loopback HTTP检查使用MockHost，不计为真实Host语义成功。

权威账本仍在原树 `artifacts/ser-v20/budget.json`，SHA
`f9efa35e1a83f4c4300f03f28394a584868f8955b320e960dc3f8bb7a4ce1592`。
起点 **3301 generation calls / 4,205,203 generation tokens / 23,570 embedding tokens**；unknown usage=0。
所有新调用继续追加，真实模型 HTTP 并发1；开发代理成本分开。私密 DSN 仅按需注入，不输出。

## 首轮实际 MCP 接线失败与最小修复

[R1 失败记录](../data/manifests/unified-v8-v9-mcp-r1-failure-20260928.json)保留冻结身份、实际调用与持久化证据。
Root 在上述源码提交下先冻结完整两脚本，再开始运行。首个 save_plan 消息的 native HTTP200 返回合法
`manage_memory` CREATE；实际 Host-origin MCP HTTP200、embedding 和 strict Store 写入成功，程序经 MCP
重新读取到了同一个真实 record ID。没有业务动作。但是第二次生成前，本地容量模板对
OpenAI `function.arguments` JSON 字符串调用 `items`，抛出 TypeError；续接 HTTP 尚未发出。
该 turn 为 INTERRUPTED_UNKNOWN，phase FAILED，没有最终回答，第二个 session 和 read_only 均未运行。
实际 CREATE 保留，不能以它替代完整任务成功，也不将 R1 与后续成功片段拼接。

两个竞争解释是：合法 OpenAI 字符串参数缺少本地 HF 模板所需的对象适配；或请求 renderer 重复编码参数。
Sol 已用实际失败 checkpoint 零模型复现第一种不匹配，并排除重复编码：一次 JSON 解码与原参数完全相等。
首请求的已记录请求对象一致，且本地1391 tokens等于实际服务usage；JSON邻接路径正常。部署中vLLM源码也明确执行这项转换。
最小通用候选只修改 tokenizer 计数副本，保留原 checkpoint、实际工具 JSON、模型参数、输入和评分。
窄测与源码发布后，按[事前 R2 协议](../data/diagnostics/unified-v8-v9-mcp-smoke/protocol-r2.json)
在全新身份／namespace 重跑同一完整两脚本；不是修改失败样本或自动重试。决策为 Continue 最小工程修复。
已曝光合成输入、单模型及工程中断均限制结论；此诊断不替代 U1/U2 原生比较。

[修复窄测回执](../data/manifests/unified-v8-v9-capacity-repair-checks-20260928.json)已确认6个独立目标通过、0 skip，
Ruff／目标Mypy／矩阵／diff检查通过。实际checkpoint离线重放的native计数为1391／1788，JSON仍为1092／1476；
原checkpoint、请求对象和audit保持不变。空串／缺省／JSON null同服务规则转换，非法JSON仍报错。
Root只核对3个源码／测试文件及全部检查制品哈希，没有重跑测试；第二请求的实际服务计数仍待R2验证。

R1 新增 **1 generation / 1,455 generation tokens / 1 embedding / 31 embedding tokens**，unknown usage=0。
连续账本为 **3302 generation / 4,206,658 generation tokens / 23,601 embedding tokens**，SHA
`f4ff524f60fd237a1624e2048dcc968c17871d836d9c3f4a7e8ee040d5086571`。
失败消耗与实际持久化全部保留；没有清零或撤销费用。

## 全范围需求与当前状态

| 要求 | 证明完成所需证据 | 当前 |
| --- | --- | --- |
| U0 身份/资源/许可/曝光 | 源码、模型、数据、scorer 哈希；历史曝光和无模型账本 | IN_PROGRESS |
| Host Agent 真实 MCP | 实际模型提案、MCP 请求/回执、同一 Store 和后续回答 | R1 ACTUAL_CREATE; CONTINUATION_CAPACITY_FAILURE |
| U1 MemSyco | 三类各2原题、原生参考及MiLAi、完整历史、原生评分和成本 | NOT_RUN |
| U1 MERIT | 三域easy/hard各1完整arc、原生tools/world/checker、两路径、leak check | NOT_RUN |
| U2 独立比较 | 60题/18arcs建议规模，正式ID另冻；强原文RAG、真实摘要、完整历史、ordinary/候选和Mem0 | NOT_RUN |
| 第二外部系统 | A-MEM/SimpleMem择一，在首表可用后接入，原生能力和成本可追溯 | NOT_RUN |
| U3-P 协议 | 需要时独立冻结J/N和thinking；自动选择而非强制调用 | CONDITION_OPEN |
| U3-O 对象 | 原生真实key失败触发；原工具主表和ref扩展分开 | CONDITION_OPEN |
| U3-W 写入 | 实际漏维护触发；同服务、可信触发、正负例与全成本 | CONDITION_OPEN |
| U3-R 恢复 | 相关行动需求触发；partial/unknown、进程重开、实际ID及无重复副作用 | CONDITION_OPEN |
| U4 机制 | 真信号/瓶颈；MAB6k/32k及必要固定bank/State/writer/预算对照 | CONDITION_OPEN |
| U5 确认 | 冻结后新来源组、MemoryArena完整group；必要模型/长程，缺资源明确登记 | CONDITION_OPEN |
| U6 总结 | 全部适用需求逐项证据、失败两解释、成本、统计、复现、发布SHA | NOT_STARTED |

数量先按计划建议组织；若实际数据/资源要求调整，必须在模型运行前说明理由、保持完整实例并冻结。
研究优势不预设；最终必须说明形成、取材、呈现、动作或额外计算的证据边界。
当前 Goal 保持 active；首轮实际接线因容量适配失败中断，完整原生适配与后续实验尚未完成。
