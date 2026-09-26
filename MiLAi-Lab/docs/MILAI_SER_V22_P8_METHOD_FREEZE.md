# P8：冻结可检验方法，尚未确认端到端收益

Decision：允许小规模正式matched评价。P7完成了规定暴露输入的开发验证与两次通用修复，保留全部负面结果；不是所有业务问题通过。依据是多类型机制证据、稳定执行合同与可统计费用，不是挑选最好轨迹。

## §25逐项判定

| 条件 | 证据与限制 |
| --- | --- |
| 多类型changed/retained/irrelevant | P6最终同源13/13；P3/P4和旧失败独立保存，不能重标R3实跑 |
| 无stale正文泄漏 | P3–P6真实wire逐项检查；R3核心投影代码不变，其回归无stale输入 |
| derived失效有真实request | P6实际34次demotion，checkpoint原文保留；是snapshot风险，不是逐词因果 |
| irrelevant干预可控 | P5低排名get3→0，P6无关任务动作正确但仍有3次snapshot风险demotion；R3空证据49/55省略authority，20首request与B1相同；不称零误干预 |
| 多对象/多版本 | P6 multi-memory、multi-revision、retained/delete/unknown等控制通过 |
| 协议/截断不主导 | R3全部27公开消息完成、0截断，MERIT一次普通tool validation错误；容量故障按R2策略单列，不隐藏 |
| 方法参数冻结 | 下表冻结算法/协议；新v23仅提供同源入口及预冻结selection加载，源锁在调用前另绑定 |
| 无benchmark特定规则 | 方法不读case/gold/业务值；authority条件只依机械projected items/rebases |
| 完整费用 | 连续415生成/373013tokens/4370embeddingtokens/75get；旧失败和unknown历史永久保留 |

这不是最终质量GO。R3诊断7/12对固定B1 8/12，d11首request完整相同仍不同回答；MERIT同4/5、1/2，0自然rebase。形成与检索失败尚存。当前证据足以检验是否有未见收益，不能证明收益；若未见baseline不劣，按总计划pivot/kill，不继续调已见prompt刷分。

## 冻结的正式三臂

| arm | 方法 |
| --- | --- |
| b1_control | 原公开LangMem ReAct，保留同一观察器，projection=None |
| a3_exact_refresh / SER-lite | item级stale quarantine + public Store.get当前版本，stage v21，无rank截断，不做derived rebase |
| a4_selective_rebase / SER-full | 同SER-lite，加普通assistant生成请求snapshot lineage与失效回答降级；仅outgoing copy |

lite/full同用原63-token source authority及R3机械触发条件、原31-token降级标记。currentness不代表语义权威；冲突由普通Host处理。A3现有观察器仍记录ordinary lineage，但不使用其rebase；照实计入成本，不为了formal临时优化。A5已有rank-bounded配置只留开发消融：总体成本优势未证明，不预设为主方法。

共同Host为现有Qwen3.6-35B-A3B-FP8、temperature0、thinking=false、max_tokens4096、每message最多12生成；embedding为现有bge-m3/1024。vLLM设置完全不变。工具、原world/scorer、空namespace初始化和R2局部容量处理相同；并发1，连续账本不清零。Store/业务/checkpoint副作用保留；服务故障仍停止。不能更改主方法、历史或gold来改善结果。

下一阶段在阅读/生成未见题前先固定选择规则与三臂；v23实现只抽取同一loader/loop并绑定selection SHA。生成真实任务、冻结arc/world字节后才调用。每个选择全跑三臂，失败不换题、不补最好轨迹，结果后不改prompt。P10鲁棒性依§42主效果成立条件决定；P11独立Formation/Reconciliation与P12真实脚本/质量成本交付继续，不因v22结束而停止。

## Reflection

1. 支持：现有机制值得一次独立三臂检验。2. 反驳：controls通过可推出原任务收益。3. 第一断点：形成/漏搜。4. 简单解释：空memory与运行波动。5. 简单方法：正式保留baseline/lite/full三个必要arm。6. 复杂度：不加新平台、状态或模型。7. 过拟合：正式输入在方法冻结后选择。8. 反例：baseline同等或更好将否定收益。9. 决定：Continue P9，生命周期另研。10. 理由：机制证据与效果证据分开，依未见结果选择继续或pivot。
