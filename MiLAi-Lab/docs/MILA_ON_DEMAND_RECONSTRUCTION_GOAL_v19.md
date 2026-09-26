---
version: v19.0
date: 2026-09-26
status: STOPPED_STRUCTURED_RECONSTRUCTION_NOT_JUSTIFIED
engineering_delivery: COMPLETE
implementation_authorized: true
scope: MiLAi-Lab
experiment_arm_kind: RESEARCH_PROTOTYPE
reference_commit: 90ac0b35e95b0371106cb05fb66b1f933af7f432
development_plan_sha256: 55caef7595bc69a2955d672706612a2320910c79807e160230ebdfca6026a355
v0_status: PASS_5_FOCUSED_TESTS
decoder_probe_status: PASS_5_OF_5
mechanism_status: ZERO_OF_THREE_COMPLETE_ODR_CHAINS
freshness_only_status: NOT_RUN_GATE_NOT_MET
exposed_diagnostic_status: NOT_RUN_GATE_NOT_MET
exposed_merit_status: NOT_RUN_GATE_NOT_MET
cumulative_generation_request_cap: null
cumulative_generation_token_cap: null
cumulative_embedding_token_cap: null
---

# v19 执行 Goal：On-Demand Evidence Reconstruction

用户要求完整执行[1391行原计划](MILA_ON_DEMAND_RECONSTRUCTION_V19_DEVELOPMENT_PLAN_20260926.md)。原文件保持字节不变，其PLANNED_NOT_STARTED是规划时状态，本Goal记录实际执行。完成标准包含实现、必要机械验证、三个受控小例、条件消融/诊断的判断、完整证据和授权发布，不能缩成schema可解析。

全部工程、必要验证和三个小例已完成，结论见[结果](MILA_ON_DEMAND_RECONSTRUCTION_V19_RESULTS_20260926.md)与[复现](MILA_ON_DEMAND_RECONSTRUCTION_V19_REPRODUCTION_20260926.md)。正式9/9公开消息完成，15次响应全null；changed实际执行旧4°C，retained未取得新版本，irrelevant行为未受干扰但无结构重建。按§38/44停止structured ODR，条件V5–V7不运行；Freshness-only效果未知。总用量20次生成／20360tokens／274embeddingtokens，unknown/Judge/截断均0。原vLLM设置未改。

## 1. 组织与边界

沿用一名Sol xhigh负责源码/config/tests/CI，Root负责文档、reference、fixture/rubric、lock/freeze、真实环境、所有LLM/embedding请求与评分（并发1）；Luna high负责用户已授权的GitHub发布。必要参考下载才交Luna。无常驻reviewer和重复授权步骤。

v18已发布commit `90ac0b35e95b0371106cb05fb66b1f933af7f432`，原41文件mapping、结果、失败、锁、16次／19237tokens／267embeddingtokens完整保留。不得修改M1方法代码来救旧机制。新方向位于`methods/on_demand_reconstruction`，只对已有B1/JSON-action/runner作必要接入，不新建第二个Agent loop，不改Product、Archive、旧contextual、ranking、candidate expansion。

原vLLM容器/image/command/environment/HostConfig、parser、thinking、65536上下文、4096输出和原每公开消息12次尝试保持；模型为Qwen3.6-35B-A3B-FP8，embedding为bge-m3。功能通过适配器实现。没有自动search/gap search、业务真值gate、独立State/reflection/reviewer调用、M2/Attention、训练、新seed/holdout。

## 2. 必须成立的运行合同

1. Freshness由本次实际Provider request中的memory material与B1准确revision元数据机械计算：CURRENT/SUPERSEDED/DELETED/UNKNOWN。相同文本的新revision仍是新版本，不靠文本猜同一对象。
2. 只有实际进入request的SUPERSEDED/DELETED材料生成动态freshness block。标明当前ref及正文是否实际交付；不注入未读新正文、判断温度真假、命令搜索或禁止业务动作。无stale时动态freshness为零。
3. ODR同generation输出`reconstruction=null`，或proposition/action_scope(subject,item,action_type,critical_parameters)/evidence_used(ref,support_role)/unresolved_gap；没有set/clear/ack/outcome/pending或持续语义状态。
4. evidence_used仅绑定本次实际交付的Observation、准确MemoryRevision或业务receipt。无continued adoption。重复ref规范化。SUPERSEDED不能supports_value，可以contextual；程序不证明自然语言支持充分性。
5. `reconstruction=null`始终合法，即使同时执行business也照常允许并记录ACTION_WITHOUT_RECONSTRUCTION。非null协议自相矛盾时同响应工具零副作用，不能把这种拒绝当业务真值gate收益。
6. 重建只进入append-only分析trace，下一请求不得读取、恢复或投影旧重建字段。正常对话/工具历史允许保留。没有Decision SQLite；freshness每request重新算。
7. process restart不需要语义状态恢复；已有checkpoint/business journal保证completed turn及业务/记忆效果不重复；日志不参与下一请求决策。
8. 同时提供b1_control、freshness_only、odr入口；F-only不输出reconstruction、不添加ODR字段/提示负担，无stale时保持B1的模型可见合同。

## 3. 里程碑与实际证据

| 包/里程碑 | 要求 | 证据 |
| --- | --- | --- |
| A/M0 | v18原样封存 | reference、旧源码/锁/结果/费用/原环境 |
| B–C/M1 | 精确freshness与稀疏投影 | actual request material、revision、稀疏文本 |
| D/M2 | ephemeral schema与currentness | 准确交付、角色规则、duplicate normalize |
| E–G/M3 | adapter、无持久化、恢复 | 同代响应、零额外调用、无跨轮字段、重放 |
| V0/M4 | 全部必要零模型合同 | 下述集中测试，无完整suite |
| V1/M5 | 原服务五种最小probe | null+answer、null+calls、重建+answer/search/business |
| V2–V4/M6–7 | changed/retained/irrelevant | 同一最终源码、预先冻结数据/rubric |
| V5/M8 | 条件F-only消融 | 三机制通过后，相同三fixture独立空状态 |
| V6/M9 | 条件原12/20 | 三机制通过；原输入/评分不改 |
| V7/M10 | 条件原arc0 5/7 | V6没有明显退化；不消费新数据 |
| M11 | 指标、判断、复现、发布 | 全失败/费用、明确边界与远端核对 |

V0需覆盖current/superseded/deleted/unknown、同文新版本、无关不在request、重复历史ToolMessage、多版本共存；null/命题/action scope、Observation/memory/receipt绑定、旧supports_value拒绝/current接受；answer/search/business/null business组合、非法零副作用、无独立模型调用；无跨轮字段（含restart/checkpoint/日志）、completed replay和准确revision。按问题合并为少量有意义测试，受影响静态/边界检查；包装声明改变才build一次。

## 4. 小规模运行与停止条件

三个fixture新建v19身份，沿用既有development family及三条公开消息，通过原LangMem工具完成真实seed/update，不预置reconstruction、伪造搜索结果或把gold放入方法。所有数据与人工rubric在真实请求前冻结。

Changed成功必须完整观察：X@1真实送达→真实外部X@2更新→后续实际freshness→Host普通工具取得X@2→最终临时重建使用X@2→获批动作8°C，且旧X@1未作supports_value、无额外独立调用/自动search/温度规则。首次重建可null，实际读取X@1不能省略。记录动作同代是否null，不强制所有业务都生成重建。

Retained要求获得当前同值X@2并仍正确8°C，不要求retained标签；irrelevant若Y不在request则不提示，若历史Y恰好在request可以提示，但不能扰乱X判断或无必要搜索Y。选择性不可用“没有取得任何证据所以没有提醒”冒充。

V5在ODR三例通过后，对相同三例运行F-only，比较changed/retained适应和irrelevant行为。若更简单F-only等价或更好，最终选择freshness并删除活动reconstruction候选的负担，保留可复现研究证据，不声称重建有增量。V6仅三例通过后，V7仅V6没有明显退化；条件不成立则明确NOT_RUN_GATE_NOT_MET。

按原§44：初始取证不稳定、明显结构负担、仍使用stale支持、需要独立调用或硬编码搜索、activation接近每轮、或F-only等价更好，停止继续结构化ODR。必要通用工程/解码修复保留失败并重新冻结；开放结构退化按§27优先简化schema/文本上限，不能改vLLM设置。不得无限调提示救语义负结果。没有明确数字阈值时报告实际分子分母与任务性质，不能事后给通过阈值。

## 5. 指标与费用

人工评价每个实际非null重建：具体命题/标签、临时gap是否对动作相关、关键参数是否有supports_value及正文是否真的支持；机械合法不等于语义充分。单列activation、freshness介入、current exact使用、旧supports_value尝试/拒绝、null业务、普通非干预、协议错误/截断及实际任务完成。

分别计固定ODR提示tokens、动态freshness tokens、证据handle目录tokens、reconstruction输出tokens、search后的普通ReAct请求、独立额外请求（应0）、trace/storage bytes和持久语义状态bytes（应0）。所有片段属于完整Provider账单，不相加冒充精确增量；截断及失败全额保留。描述性比较v17/v18按每公开消息tokens/次数/拒绝/截断/存储，不能把历史B1 7/12与M1 5/12当新matched因果比较。

新`artifacts/on-demand-reconstruction-v19/v19-budget.json`持续记账并引用旧v18和更早history；累计caps=null，不清零。开发代理成本与实验Provider用量分开，Judge=0。

## 6. 交付和结项

交付新方法/adapter/config、三fixture、CLI/inspection、reference/lock/final freeze、必要测试/CI、开发/结果/复现/Goal、费用与各运行manifest。按证据选择COMPLETE_WITH_ODR_MECHANISM_REACHABLE、COMPLETE_WITH_FRESHNESS_ONLY_PIVOT、STOPPED_STRUCTURED_RECONSTRUCTION_NOT_JUSTIFIED或PIVOT_TO_RETRIEVAL_CONTROL；不写ODR_EFFECTIVE或GENERAL_IMPROVEMENT。Luna按用户授权发布全部开发，raw trace/DB/凭据保持ignored。

- [x] 全文阅读原计划，41个v18源码、4份验证、16项旧artifact及原服务已核对封存。
- [x] B–G全部实现及无持久化/恢复合同。
- [x] V0五条通过、五分支decoder通过、最终52文件lock/freeze。
- [x] 三个小例和完整独立判定，包含all-null、真实stale动作和irrelevant非干扰证据。
- [x] 条件F-only/12例/arc0以gate未满足关闭，不宣称未运行方法有效。
- [x] 全指标、终态、开发与复现记录已交付；最终Git发布由已获授权的Luna执行，远端SHA与清洁工作区以会话发布回执为准。

最终mapping为`1f22b6b7b032a647e360c140c61467763f7ce71b0a1fdd481d1c00ede88fbfaa`。V0/静态/边界/包装通过；受影响旧测试17通过、1个既存M1断言不匹配，已明确记录，未冒称全绿。原计划、封存M1方法和16项旧证据不变。研究负结果不等于工程未实现；也不能以工程完成代替机制有效。
