---
status: EXECUTION_CLOSED_STOP_PIVOT_PUBLICATION_PENDING
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
method_goal: NOT_ACHIEVED
minimum_stability_standard: NOT_ACHIEVED
research_goal: NOT_ACHIEVED
product: NO_GO
---

# MiLAi v6 总体实验报告

v6完成结构化Request Assembly、Model/Audit边界和完整适用小样本验证；**方法稳定性目标未达成**。
旧暴露回归156/156，但独立结构S4仅10/12脚本、166/193任务义务通过，出现两次虚假保存。
四次首响应对照不能选出可靠的full回退。按原计划§22作 **Stop/Pivot**：停止扩大compact候选，
保留结构工程和全部失败；下一问题是Host形成/动作可靠性，没有以补充prompt、reviewer或controller继续修分。
这是一轮计划执行的否定结果与收敛决定，不是宣告§23最低消费稳定性、总体研究或Product完成。

[执行记录](MILAI_NEXT_DEVELOPMENT_EXECUTION_GOAL_V6_20260928.md)、
[总体审计清单](../data/manifests/next-development-v6-overall-audit-20260928.json)和
[S4完整报告](MILAI_NEXT_DEVELOPMENT_V6_S4_INDEPENDENT_RESULTS_20260928.md)给出证据、失败链、评分修正和复现边界。
全部适用评估与报告已完成，Luna发布及Root远端核对后才关闭本轮“执行计划”任务；不自动暂停、恢复历史实验或合并未来PR。
实际Goal的完成只指按计划允许的Stop结案，不把未达到的质量门槛改写为成功。

## 全部计划审计

| 阶段 | 实际结果 | 判定与证据 |
| --- | --- | --- |
| S0 | 保留旧v5源码/锁、28 terminal jobs、131生成与86消息审计、全部成本 | COMPLETE；[基线](../data/manifests/next-development-v6-s0-baseline-20260928.json) |
| S1 | 显式RequestContext/renderer/router，消除序列化字符串块搬运；原协议字节保留 | ENGINEERING_ACCEPTED；[报告](MILAI_NEXT_DEVELOPMENT_V6_S1_ASSEMBLY_RESULTS_20260928.md)，131请求/86审计/22条件26阶段/27窄测 |
| S2 | full默认、compact唯一投影；完整审计/graph/checkpoint不改 | ENGINEERING_ACCEPTED，compact质量不推广；[实现清单](../data/manifests/next-development-v6-s2-implementation-checks-20260928.json)，30窄测/131双view回放 |
| S3a | S1/full四暴露脚本、13消息54义务通过 | PASS；[阶段报告](MILAI_NEXT_DEVELOPMENT_V6_S2_PROFILE_S3A_RESULTS_20260928.md) |
| S3b | S2/compact十二暴露脚本、35消息156义务通过；额外3诊断缺项保留 | PASS_EXPOSED；[报告](MILAI_NEXT_DEVELOPMENT_V6_S3B_REGRESSION_RESULTS_20260928.md) |
| S4 | 十二独立脚本、40消息；166/193义务、显式102/121、持久64/72 | FAIL；两次虚假保存，world任务失败，partial失败边界未激活 |
| S4局部诊断 | 同一失败前缀compact/full/full/compact各一次；full2/2、compact1/2合法提案 | INCONCLUSIVE；无工具执行，不计持久成功；[清单](../data/manifests/next-development-v6-s4-proposal-diagnostic-20260928.json) |
| S5 | 第二模型6–8脚本 | NOT_TRIGGERED；S4硬门槛未过，没有下载/部署 |
| S6 | 自然积累20–30sessions | NOT_TRIGGERED；S4未稳定；不是把“最好S5”改成额外硬门槛 |
| S7 | 普通query真实压力基线 | NOT_TRIGGERED；所有本轮任务all，无容量/检索瓶颈 |
| S8 | lazy State–Attention条件比较 | NOT_TRIGGERED；没有query不足证据，无第二份durable facts/U |
| S9 | 全范围审计、成本、失败、Reflection、复现、Go/Pivot/Stop | REPORT_COMPLETE，发布核验是最后行政步骤 |

§23七项最低要求：1结构化组装、2锁定编码等价、3Model/Audit边界、4独立小样本完成、6完整成本、7是否进入后续阶段均有证据。
**第5项current/history/world/temporary整体消费稳定未满足**：current/history/temporary有通过例，world/formation仍失败，
partial能力没有激活，不能用合并通过率或源码测试代替。最低标准整体NOT_ACHIEVED；不把条件阶段未触发算作通过。
§24长期研究的第二家族、长程自然积累、强检索基线及真实压力下净收益仍无证据，Product NO_GO。

## 实现与实验身份

S1提交4ffd17664ce9d8a6497e57b199b3a6d764adae86；S2源码85f45b367ee1c90d1c378e4a8a5c699c03889ee9；
S4执行提交515ec7145ac1c1a66bafd080f472eb3e57c54037，仅在S2后增加文档/数据。
旧v5效果属于ec682a3等旧提交，保留原协议和失败，不转记到v6。
131次等价比较使用原有序request字典与锁定HTTPX编码，没有原socket capture，不能声称做了不存在的抓包比较。
S2只在发出请求的副本精简，保留所有真实原工具正文、历史/graph/checkpoint及审计。
库默认system/full不变；current_request/compact_v6保持显式研究recipe，S4失败后不推广。

Root负责所有真实HTTP、冻结、人工评分、报告和账本；Sol xhigh独占源码/配置和必要检查；
Astra xhigh只回答具体形成归因与world评分冲突；Luna high执行Git发布。没有LLM Judge或常驻审计代理。
Host服务、thinking/parser/context/output/temperature不改；Root HTTP并发1，单消息生成上限12。
不下载新模型、不创建第二服务、不访问Product；未恢复旧C纠错、M1/ODR/持久Decision State。

Git用户授权的S0合并已由Luna完成：PR69→main07cc364f96d484ad9ff8497adcf2a6f1b486bdb2，tree等于S0c6dcd1d7。
S1/S2及结果在[PR70](https://github.com/minguselandy/MiLAi/pull/70)，保持draft/open，不能把S0的合并授权延用于后续PR。
PR51未验收，仍不合并。原checkout保留旧HEAD和七份未跟踪计划/v27草稿；实际工作在v6独立worktree。
已有必要局部检查和Fast CI通过，纯结果提交仅检查链接/JSON/哈希/diff，不为发布重复测试或构建。

## 效果与收益的实际边界

S2固定131请求输入180,667→173,797，节省6,870tokens，完整输入3.80%；定义的记忆组件72,040→65,170，节省9.54%。
未达到10%–20%目标，不为凑数删除更多语义。真实S3b比旧v5少793总tokens，但多一次search、UUID/措辞/轨迹变化，
不能将该差解释为压缩因果效果。S4无匹配完整full臂，四次proposal-only也不提供完整质量/成本赢家。

S4的命令引文、纠正后的当前解释、历史/当前、temporary、删除、双owner和混合语言小样本可工作；
两次形成失败说明不能把“正确记忆已经存在”的前提视为通用事实。
一个业务精确key被改写，另一个明确lookup被遗漏；没有持久层异常来解释这些Host决策。
当前更简单解释是普通形成与动作执行可靠性不足，未发现需要Attention或新状态平台的断点。

原I guide的成功分支值与真实not_found冲突，修正只把三项状态回答按实际缺席分支通过。
原guide/原快照保留，193分母不变；机械套guide163/193，纠正后166/193，两种都不达标。
前序未保存/未预约仍失败，部分副作用NOT_ACTIVATED。scoped_preference技术措辞局限另列，不从格式通过推事实正确。

## 连续成本

| 阶段 | 生成calls | input | output | 生成总tokens | embedding calls / tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| S0/S1/S2离线工程 | 0 | 0 | 0 | 0 | 0 / 0 |
| S3a | 20 | 26,629 | 855 | 27,484 | 5 / 115 |
| S3b | 54 | 71,723 | 2,296 | 74,019 | 23 / 448 |
| S4原完整R1 | 60 | 75,864 | 2,519 | 78,383 | 19 / 492 |
| S4诊断 | 4 | 4,338 | 169 | 4,507 | 0 / 0 |
| v6新增 | **138** | **178,554** | **5,839** | **184,393** | **47 / 1,055** |

账本从3,125calls/3,971,354generation/22,221embedding累加至
**3,263calls/4,155,747generation/23,276embedding tokens**。
最终SHA `2df7547a9d038cb53105afbf5daa97bbd8225bb204c19af40b7c68eee264ade2`，history/limits不变；无unknown usage、真实HTTP错误或模型/基础设施重试。
失败、空搜索、诊断和观察计入，没有更换失败样本或拼接最佳轨迹；不包含开发代理tokens。
各阶段报告/清单分别给出Store逻辑calls/bytes、operation audit、业务/路由、HTTP和进程CPU/wall。
物理I/O、独立write CPU、GPU时间、货币价目和未计时离线准备保持unknown；嵌套成本不重复加总。

## 复现与最终决定

按对应源码提交复现各阶段，不要求当前源码匹配所有旧锁。
S4的输入、recipe、order、义务和guide均已公开；原freeze/trace/DB/checkpoint、逐step启动/结束/评分回执和诊断wire留在ignored artifacts。
公开清单保存证据哈希与精简结果；私密DSN仅从ignored文件注入MILAI_LANGMEM_POSTGRES_DSN，数据库/原始私密轨迹/模型资产不入Git。
重跑需新namespace/Store/checkpoint/world并继续累计原账本，不覆盖已暴露R1，也不声称逐token完全复现。

决定是 **保留工程、否决当前compact稳定性主张、停止扩大这一候选**。
条件阶段没有达到门槛，不做新模型部署、长程负载或人为容量压力。
若未来重新授权新的形成/动作可靠性方案，应提出具体通用机制和可证伪最小验证，先覆盖本轮失败及反例；本报告不自动启动它。

## 总体Reflection

1. 支持什么：显式结构组装能在固定编码下保留原行为输入，审计与模型材料可分离，边界能由实际HTTP核验。
2. 反驳什么：旧12/12回归不能保证新任务形成稳定；少量元数据删除的静态合理性也不能证明全面语义安全。
3. 首断点：Host未调用CREATE就确认保存；后续还有tool key/lookup问题，不是Store或检索损坏。
4. 简单解释：同一compact前缀动作不稳定，且多数案例可解；当前样本不支持单一投影因果结论。
5. 简单方法：保留普通LangMem和full默认；不添加语义控制器为本轮失误兜底。
6. 复杂度合理性：S1改善结构，S2为有限投影；失败后未扩大平台，审计helper错误与实验失败分别保留。
7. 过拟合风险：所有诊断前缀已暴露；不改保存措辞、不继续抽样选赢家、不调整服务参数。
8. 所需反例：形成与明确no-write/引用/temporary共存、精确业务引用、真实部分失败；本轮最后一类未激活。
9. Go/Pivot/Stop：Stop扩大compact，Pivot研究问题到形成/动作可靠性；无已选下一实现，第二模型/长程不触发。
10. 为什么：硬门槛失败、预定诊断未选出可靠修复，继续规则堆叠违背§22。真实否定结论比虚报最低完成标准更有用。
