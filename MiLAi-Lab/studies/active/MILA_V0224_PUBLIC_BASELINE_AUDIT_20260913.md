---
goal_id: MILA-V02-24
document_kind: PUBLIC_BASELINE_SOURCE_AUDIT
status: SOURCE_SNAPSHOT_ONLY_NOT_EFFECT_ADMITTED
checked_date: "2026-09-13"
model_requests: 0
judge_requests: 0
provider_http_requests: 0
changes_active_execution_contract: false
---

# V0224 公开基线制品核验与机制对照

## 1. 结论与范围

AdaptiveMem 可以列为新的公开政策对照候选；CUPMem/TEPA 是必须讨论的近邻。但本次仅核验论文、README、许可证和一个 runner 片段，**没有复现它们，也没有取得任何行为收益成绩**。
相关修订见[Goal 待采纳提案](MILA_V0224_RESEARCH_REFINEMENT_PROPOSAL_20260913.md)。当前 Gate A 执行合同、历史结果与确认池不变。

尤其需要纠正同名制品的归属：

| 项目 | 可核验标识 | 本次处理 |
| --- | --- | --- |
| The Compliance Trap: Diagnosing How AI Agents Consume Conflicting Memory | [arXiv:2607.10608](https://arxiv.org/abs/2607.10608)；Chen、Bai、Yuille | 原先 E-P-R/浏览器任务研究对应的匹配制品 HOLD 不变 |
| MemTrapBench: Benchmarking Cognitive Traps in LLM Memory Use | [arXiv:2608.20202](https://arxiv.org/abs/2608.20202)；[zjunlp/MemTrapBench](https://github.com/zjunlp/MemTrapBench/tree/02fc32a2b5ffecce893e353b29fcd49242ea71cf) README 引用此论文 | 新增 AdaptiveMem 政策制品记录，不当作前一论文的替代品 |

两者不是同一论文；同名 MemTrapBench 不能用来追认 V0217 的原始制品定位、完整 P-Lane 或冷持久行为准入。

## 2. 实际冻结了什么

[机器可读清单](MILA_V0224_PUBLIC_BASELINE_SOURCE_AUDIT_20260913.json)记录固定 URL、commit、Git blob、SHA-256、字节量、许可证核验范围与本地位置。

| 来源 | 固定 revision | 读取并留存的文件 |
| --- | --- | --- |
| zjunlp/MemTrapBench | `02fc32a2b5ffecce893e353b29fcd49242ea71cf` | `AdaptiveMem/skill.txt`、README、`eval_retrieved_memory.py` |
| icedreamc/STALE | `ea7d391103a151927cd29d2f01d87597a782bdcb` | 根 README、`cup_mem/README.md`、LICENSE |
| TEPA | [论文 v2](https://arxiv.org/html/2608.07429v2) | 网页论文核对；没有冻结或验证可执行包 |

共6个原文文件、28,081字节，保留在 Git 外目录 `/cra/memory/milai-v0224-public-source-audit.S9bhWF`；不是全仓库、完整依赖、数据集或 runner 环境快照。
AdaptiveMem 原文 SHA-256：`cc279ded25d30649c55ee2a62866bf41537d2aa58d2475748ddd6da27b60b4ad`。
五份文件的本地 Git blob 与已读取 tree 一致；`cup_mem/README.md` 固定 commit 下载并记录本地字节/hash，其 blob 未经后续 tree API 复核。该后续 API 请求返回403，未绕过或以凭据重试。

这些文件仅作为不可信研究材料读取。`skill.txt` 不注册为 Codex skill、不成为当前 Agent 的系统指令，也未执行其中任何流程；runner 未 import/运行，未加载其环境变量或连接其 Provider/Judge。
本轮有公开网页/GitHub读取，但没有 vLLM HTTP、模型/Judge、GPU操作、业务写入或确认任务正文读取。

## 3. 许可与运行边界

- AdaptiveMem：本次完整 tree 元数据未出现 LICENSE/COPYING/NOTICE 文件，仓库 API `license=null`。记录为 `NOT_DECLARED_IN_CHECKED_TREE`，不擅自推定 MIT。当前仅保存本地审计副本与引用/hash；移植运行、再发布或打包前，确认拟用范围的许可。这里不对未核验的授权作法律结论。
- CUPMem：固定 commit 的[LICENSE](https://github.com/icedreamc/STALE/blob/ea7d391103a151927cd29d2f01d87597a782bdcb/LICENSE)为 MIT。此核验不自动覆盖依赖模型、第三方数据及其使用条件。
- TEPA：本轮只核验论文；没有确认官方可执行制品的来源、依赖、许可或冷恢复实现。记录 `PAPER_VERIFIED / EXECUTABLE_NOT_VERIFIED`，不是声称“制品不存在”。

## 4. 三类对照不能混为一个实验

| 比较类型 | 应固定/允许改变什么 | 能解释的收益 |
| --- | --- | --- |
| 同输入使用政策 | N1/R1/政策移植/候选同一 Note、当前证据、动作合同、机会预算；仅政策差异 | 最接近 Memory consumption；仍须计实际计算成本 |
| 完整记忆系统 | 可以改变写入、更新、检索、呈现；全部流水线和维护成本显式报告 | 系统整体差异，不能直接归因注意力或 State |
| 外部 benchmark | 遵循其任务、输入、evaluator与暴露条件，另报非原生适配差异 | 外部迁移/复现，不替代内部行为因果链 |

暂不同时集成 LangMem/Mem0/Graphiti/A-MEM/Hindsight。它们是后续可能的系统对照，不是本轮已核验或获准运行的组件。

## 5. 最相关机制对照

| 对照 | 本次直接支持的机制描述 | 对 MiLAi 的约束与验证缺口 |
| --- | --- | --- |
| Ordinary review | 本地强简单政策，在同一正常决策调用核对记录与当前任务/证据 | 必须允许它胜出；不能强制昂贵多 Agent 反思再制造成本优势 |
| AdaptiveMem | 公开提示包含任务边界变化、偏置风险与避免过度检查；retrieved runner 可把该提示加入问题模板。[原文](https://github.com/zjunlp/MemTrapBench/blob/02fc32a2b5ffecce893e353b29fcd49242ea71cf/AdaptiveMem/skill.txt)、[runner](https://github.com/zjunlp/MemTrapBench/blob/02fc32a2b5ffecce893e353b29fcd49242ea71cf/runners/eval/eval_retrieved_memory.py) | “适用性复核/避免过度触发”不能独占为新主张；本地策略移植不是原论文复现，也不建立真实持久/行动链 |
| CUPMem | 结构化当前状态、写入时裁决与相关失效传播，读出使用当前裁决状态。[STALE 论文 §5/附录](https://arxiv.org/html/2605.06527v1) | 同时改变维护和读出，不直接属于旧新材料完全相同的单一政策臂；当前只读论文及[组件 README](https://github.com/icedreamc/STALE/blob/ea7d391103a151927cd29d2f01d87597a782bdcb/cup_mem/README.md)，没有代码内部或效果复现 |
| TEPA | keyed precedent 的有效性、冲突撤销、历史保留与再提升；主要 controlled/executable/preference 流采用确定性执行器，另有模型回答设置。[论文 §4/§5/附录 A、E](https://arxiv.org/html/2608.07429v2) | “撤销/重激活”概念已有近邻；不能用确定性 executor 的成绩替代自由 Note 经真实 Host 决策、冷恢复和 World 行为成绩 |

表中的差异判断是根据上述材料作出的设计推论，不是本次性能测量。当前不能声称 MiLAi 首创这些概念，也不能据此认定其将超过相关方法。

## 6. AdaptiveMem 移植的前置合同

当前只完成原文冻结，不启动移植。若 Gate E 后出现有价值问题并获准增加该臂：

1. 明确许可/使用范围；保留固定原文、实际使用文本和逐项 diff，不能修改后仍称完全原版。
2. 保留已通过验证的 intent presentation boundary；当前任务不挪位，旧/新材料不裁掉，不偷加答案或减少干扰。
3. 原提示含“选择相关记忆”的表达。在 MiLAi 同输入政策比较中只研究 Host 如何使用完整已呈现材料，不接入语义过滤器；若必须改变可见材料，另列系统臂，不能仍称同输入比较。
4. 不照搬其 API、默认 Judge 或并发配置。使用既有合法实验服务，实际多余调用/检索/上下文成本全部计入。
5. 不要求输出内部思维链；观测仅限实际请求、公开产物、工具动作、环境变化和成本。
6. 名称使用 `ADAPTIVEM_POLICY_TRANSPLANT`，报告移植边界；官方 runner/全 benchmark 复现另需独立合同。

## 7. 后续创新判定

先问 Note 是否产生方向明确的行为问题，再问普通 review/相关政策是否已解决；两门独立。
同信息 ordinary Note/review 打平时保留简单方案。候选若仅降低实际生命周期成本，可以保留效率贡献，不能改写成准确率突破。
条件 A→B→A 的重新利用与“犯错后修复”的 recovery 分别设置分母，二者都不能仅凭持久化成功认定行为成立。
只有达到执行与呈现准入、跨独立根重复、强简单基线不足，才继续候选消融与未打开确认。

本审计没有开启任何 Gate、修改历史 HOLD/PASS、消费确认池或验证新机制；它只使下一版 Goal 的基线选择与新颖性主张更可核验。
