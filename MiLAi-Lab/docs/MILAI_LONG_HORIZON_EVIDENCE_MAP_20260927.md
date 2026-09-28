# 长程计划证据与剩余要求

最新状态（2026-09-28）：实际 Goal 已 PAUSED，总研究目标未完成。当前汇总见
[总体实验总结与 v2 暂停交接](MILAI_OVERALL_EXPERIMENT_REPORT_V2_PAUSE_20260928.md)。
下表保留 v26 时点证据与当时账本，区分实现、开发效果和未见效果；局部测试通过不代替正式收益。
v25 应用和 v26 外部形成对照已完成，第二模型族仍未完成；历史下一步或条件判定不能恢复执行。

| 要求 | 当前证据 | 判断 |
| --- | --- | --- |
| §4–7普通assistant lineage、请求副本失效、多类型控制 | [P3](MILAI_SER_V20_P3_RESULTS_20260927.md)、[P4](MILAI_SER_V20_P4_RESULTS_20260927.md)、[P6最终](MILAI_SER_V21_FINAL_RESULTS_20260927.md)；同源十三例13/13，保留旧失败 | 最小机制成立；snapshot风险不是逐词因果 |
| §8 rank-bounded refresh | [P5 R1](MILAI_SER_V21_P5_R1_RESULTS_20260927.md)、[R2](MILAI_SER_V21_P5_R2_RESULTS_20260927.md)；低排名例get3→0但tokens5161→5213 | 可控读取成立，整体成本优势未证明 |
| §21多对象/多版本、§22当前冲突、§24checkpoint边界 | [P6最终](MILAI_SER_V21_FINAL_RESULTS_20260927.md)及其原manifest，CURRENT/SUPERSEDED/DELETED/UNKNOWN、两次revision、显式低排名权威反例 | 开发覆盖成立；不把latest当真值权威 |
| §25冻结、§26/41未见matched | [P8冻结](MILAI_SER_V22_P8_METHOD_FREEZE.md)、[P9全部六条运行](MILAI_SER_V23_RESULTS_20260927.md) | B1 6/10，A3/A4各7/10；0自然refresh/rebase，额外分数不证明SER因果收益 |
| §14 Formation | [v24 F3](MILAI_LIFECYCLE_V24_FORMATION_R3_RESULTS_20260927.md)及前两轮 | 三种cue均0/2；显式保存控制独立通过；停止cue家族 |
| §15 Reconciliation | [v24 R2](MILAI_LIFECYCLE_V24_RECONCILIATION_R2_RESULTS_20260927.md)及R1/两个能力控制 | 原正文实际送达仍必要更新0/1；停止cue家族，不默认启用 |
| §20短/中/长历史 | [v25最终](MILAI_APPLICATION_V25_RESULTS_20260927.md)、[提前固定的长度输入](../data/manifests/milai-application-v25-history-inputs.json) | B1三档7/9，A4为9/9、8/9、9/9；实际最大输入9467tokens；合成日志不等于自然长期分布 |
| §30同域四臂Pareto | [短四臂](MILAI_APPLICATION_V25_SHORT_RESULTS_20260927.md)，B1/A3/A4/A5为7/9、7/9、9/9、8/9 | 质量/tokens两轴B1/A4非支配；A5少get是第三轴权衡；long成本差受fresh-session循环混杂 |
| §43非benchmark可用性 | v25五阶段/九消息，真实SQLite副作用、partial failure、restart、CRUD、新session和两用户 | 八条实际运行及必要窄检查完成；保留普通Host取证、维护与容量失败，不宣称可靠Agent |
| §19至少两个模型族 | 当前真实研究仅本地Qwen；独立端点信息已请求 | 未完成；不能把subagent推理充作同合同模型评价 |
| P10 external baselines | 公开LangMem B1与[Mem0 native四例对照](MILAI_EXTERNAL_MEMORY_V26_RESULTS_20260927.md)已完成，严格2/4对4/4、形成0/2对2/2 | Mem0生成tokens 10.1倍；已暴露系统比较、单模型，ADD-only不冒充v25同ID修订或SER收益 |
| §18/42广泛鲁棒性 | 主未见效果尚未成立 | 不进行参数/密度/比例大扫描来寻找最好结果；保留第二模型明确缺口和独立历史边界 |
| §28–29完整质量/适应/保持/currentness/费用 | [v25完整manifest](../data/manifests/milai-application-v25-results.json)含逐消息/阶段、投影、observer、延迟/存储 | 已汇总并追加[v26成本](../data/manifests/milai-external-memory-v26-results.json)；连续863生成/1042729tokens/9617embeddingtokens/107get；语义refresh贡献UNKNOWN，不能冒充因果precision |
| §44 Product迁移 | 稳定未见收益前提不满足 | NO-GO，Product不改 |

## 条件机制判定

Current Evidence Capsule目前没有新触发证据：十三例开发控制已能消费实际送达的当前证据；P9主要是没有形成记忆和容量路径差异。v25 medium新session缺的是未读取的实际业务状态，复制当前memory不能提供真实reservation ID；不能由此推出需要增加呈现层。

Evidence-Grounded Action要求隔离、当前正文送达、derived demotion后仍反复旧参数。P9错误退款发生在原约定未持久化时，v24暴露维护遗漏；v25 A4三档行动均为当前9，而新session失败是未取证/虚构，未满足该条件。Root/Sol独立只读核对无确定性集成故障，当前不加入语义门禁或自动参数修正。

State–Attention要求“当前证据已知不足且普通ReAct反复无法取得必要当前证据”。空搜索来自未保存信息时，增加检索控制不能恢复从未存在的内容。没有新增持久Decision State或reviewer的依据。

Jev是后期效率后端；当前主要方法使用机械版本解析和有界策略，未建立需要LLM控制再压缩的稳定收益。暂不引入新后端。统一生命周期框架也缺少F/R独立正面证据，不将负结果包装为完整生命周期能力。

## 复现边界

旧已执行source lock和结果原字节保留，使用各自Git checkpoint复现；当前工作树不应被误称同时符合全部历史锁。P9旧锁描述字段erratum已在[P9报告](MILAI_SER_V23_RESULTS_20260927.md)保存，实际配置/请求仍决定运行身份。公开仓库保存合成输入、rubric、锁和精简结果；原始Provider轨迹、DSN、数据库和构建产物保持本地ignored。

用户要求的参考源码已记录在[来源manifest](../data/manifests/contextual-memory-v3-sources.json)：Mem0批量记忆/embedding、Memobase紧凑上下文、Graphiti混合召回、LangMem普通记忆工具。Mem0在v26中另行作为明确声明合同差异的实际原生系统对照；其余源码借鉴本身不等于运行依赖或公平实验基线。
