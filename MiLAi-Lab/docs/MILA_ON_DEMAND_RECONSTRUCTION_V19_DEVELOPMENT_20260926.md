---
version: v19.0
date: 2026-09-26
status: STOPPED_STRUCTURED_RECONSTRUCTION_NOT_JUSTIFIED
scope: MiLAi-Lab
---

# v19 开发记录

已完整阅读[1391行原计划](MILA_ON_DEMAND_RECONSTRUCTION_V19_DEVELOPMENT_PLAN_20260926.md)。原SHA `55caef7595bc69a2955d672706612a2320910c79807e160230ebdfca6026a355`不变；[执行Goal](MILA_ON_DEMAND_RECONSTRUCTION_GOAL_v19.md)承接全部实现与条件验收。

## A：冻结前序结果

在v19源码改动前核对HEAD `90ac0b35e95b0371106cb05fb66b1f933af7f432`及v18全部41 runtime文件、4验证文件和16项旧锁/冻结/结果/失败/账本。新[reference](../data/manifests/milai-odr-v19-reference.json) SHA `5742e05a7a182cbaadc8d0fd0d690bba035eb5dba98c36923e7bc3078a6c8bfb`，明确保留0/3机制、0Basis/adoption/trigger/business、16次／19237tokens／267embeddingtokens、1次截断及后续gate关闭。

运行中原Host容器/image/command/environment hash/HostConfig核对一致，未修改vLLM。新连续账本引用封存v18和更早history，零新请求开始，累计caps=null。环境和账本原文留在ignored `artifacts/on-demand-reconstruction-v19/`。

## 实现分工与选择

按既有规则由一名Sol xhigh负责方法/adapter/runner/config/tests/CI；Root负责文档、输入/评分、冻结及每个真实Provider请求；Luna仅负责下载及授权发布。实现单独放入on_demand_reconstruction，不继续演进旧M1。

Freshness只陈述本request中准确memory版本的状态及新正文是否交付。ODR可见短句柄指向当前实际材料；F-only不带reconstruction schema、提示或其handle目录负担。重建只写分析日志，不恢复成语义状态；普通对话/工具历史继续由原graph处理。工具副作用边界沿用原合同：null合法、非法结构零同响应效果，没有业务参数真值门禁。

本节记录实现时的选择；后续已按V0→五分支probe→最终冻结→三个预先冻结小例完成，实际结果与停止判断记录于下文。

## 模型前的数据与合同对齐

三个[fixture](../data/fixtures/milai_odr_v19_changed.json)沿用v18公开消息、工具与扰动时点，仅建立独立v19身份；changed为4→8，retained为8的备注变化，irrelevant为员工通知变化而primary保持8。三份公开freeze、独立ignored rubric及[评价协议](../data/manifests/milai-odr-v19-evaluation-protocol.json)均在0真实请求时冻结。初次临时重建可null，但必须实际取得旧X；最终ODR判断需使用真实当前X，动作同代可null并独立统计，不能强制重建来提高分数。

F-only条件消融使用完全相同三fixture和新的空namespace；原12/20与arc0的输入、评分、世界hash原样记录在[条件冻结](../data/manifests/milai-odr-v19-exposed-freeze.json)。为两臂准备的10组本地路径与namespace均以public Store query=null核对为空，没有embedding或数据库结构变更；只有gate通过才会发请求。新账本arms元数据为3，对齐b1_control/freshness_only/odr，旧history不动、累计caps仍null。

代码核对纠正两点：本地tokenizer_path需允许由模板空值落到原模型目录，其余capacity与Host字段保持；response校验必须使用发出该request时的机械freshness快照，不能把响应等待期间的新revision误作已告知事实。此快照不含重建语义，下一project重算。

重复证据按(exact ref, support_role)规范化：同ref同role折叠，不同用途保留声明，stale supports_value逐项拒绝。历史User Observation和业务receipt只在本request正文准确匹配时可用，不恢复过去重建。真实B1未版本化搜索项也需记录UNKNOWN，不以人工构造的不存在revision代替该路径；UNKNOWN不能冒充精确当前版本支持动作值。

为响应已观察到的v18开放结构退化，新schema采用通用短文本与数组界限（命题/gap512字符、scope/参数160字符、参数8项、证据12项）；没有温度/金额/样本词规则。这些是输出表达边界，不是业务真值或自动retrieval策略，实际decoder兼容性仍需五分支probe确认。

## 完成实现、最小验证和冻结

一名Sol完成schema/freshness/evidence view/controller/metrics/identity、既有adapter/runner接入、三臂CLI和只读inspection。V0合并为5条零模型测试，均通过；ruff、15文件mypy、两项边界检查通过。旧受影响测试17通过、1个HEAD原有的M1异常类型断言不匹配，证据保留于[verification](../data/manifests/milai-odr-v19-verification.json)，未为本轮改旧方法或重复全套审计。

Root独占原服务，五分支真实probe一次通过，5次／3538tokens／0embedding，无工具效果。随后冻结52文件mapping `1f22b6b7b032a647e360c140c61467763f7ce71b0a1fdd481d1c00ede88fbfaa`；源码负责人只做一次必要uv build与包内容检查，未再改冻结源码。10组zero-model prepare通过并绑定[最终freeze](../data/manifests/milai-odr-v19-final-freeze.json)，正式请求前空namespace和输入/评分均已固定。

## 三例实际执行与反思

Root串行运行changed、retained、irrelevant，每例3条公开消息、5次生成，全部流程到终点，未出现协议拒绝或截断。初次search均真实取到旧X。随后每例3个request收到准确stale提示，但更新后的普通search为0，15次reconstruction全null。

Changed在第二条消息和获批业务请求中实际看到旧X过期、当前正文缺失，仍记录4°C；后续确认再看到第三次提示。Retained记录8°C但未取新X，pending答复仍沿用旧备注。Irrelevant初次search同时返回Y，因此后续只提醒旧Y合法；X保持current，没有无必要搜索或温度变化。保留这项非干扰通过，同时不把缺席的结构重建记为通过。

该结果是Host未响应freshness并未启用重建，不是transport/schema失败。probe复制结构成功也不能替代普通任务的自主激活。本轮没有需要通过修改vLLM来修复的错误；不事后把null改为非法，也不增加自动search/业务真值gate来完成原指标。

按§38/44.3停止structured ODR；形式上的stale supports_value声明为0，而行为上的stale动作有1，两者分开。V5–V7 gate不满足，已具备执行入口但不扩跑；也未证明F-only足够或自动retrieval必需。

完整[结果](MILA_ON_DEMAND_RECONSTRUCTION_V19_RESULTS_20260926.md)与[费用](../data/manifests/milai-odr-v19-cost-summary.json)保留全部20次／20360tokens／274embeddingtokens。正式请求固定ODR片段1665、动态freshness840、handle目录1225、null字段输出75tokens；它们属于总账，不能重复相加作为费用。无持续semantic State，但分析日志/普通checkpoint/factual sidecar的实际存储另行报告。原vLLM前后identity、旧M1方法、原计划及旧16项证据核对不变。Luna按已有授权负责最终Git提交和推送，不为发布重跑模型或build。
