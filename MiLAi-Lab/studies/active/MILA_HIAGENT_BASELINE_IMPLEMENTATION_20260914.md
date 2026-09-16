# HiAgent 首个方法基线：实现、源码差异与交付边界

日期：2026-09-14。版本：`hiagent-terminal-v0.1`。

初版状态：`IMPLEMENTED_MECHANISM_TRANSPLANT / MOCK_VERIFIED / LIVE_UNTESTED`。

执行更新（同日）：用户要求执行本文件后，已完成独立预算内的真实任务尝试和通用接口修复，见[执行报告](MILA_HIAGENT_BASELINE_EXECUTION_20260914.md)。57 次真实生成 / 50,153 tokens；分段与摘要进入真实输入，原生任务 5/6 通过、reward 0，检索未触发。工程验收已完成：全回归 4473 PASS / 1 SKIP，新增测试与邻近回归去重后当前 4479 项全覆盖（4478 PASS / 1 SKIP）。下文第 1—7 节保留初版交付时点，其中“0 次真实运行”和“回归中断”不是当前执行状态。

本轮交付的是 **HiAgent 核心机制的独立终端移植**：模型声明子目标，Host 按段保存动作与真实返回；组装后续输入时独立调用模型整理过去段；Actor 请求检索后重新展开历史细节。不再依赖可选 `work_update`。

这不是 HiAgent 原实验复现，不是 MiLAi 创新候选，也不是已经验证可用的真实模型成绩。没有运行 AgentBoard、Terminal-Bench trial、Provider 实验 HTTP 或 GPU 操作；新增真实模型生成与实验用量均为 0。旧 `KEEP_SIMPLE` 结论及关闭的配额不变。

## 1. 本次源码学习得到什么

官方来源是 [HiAgent2024/HiAgent](https://github.com/HiAgent2024/HiAgent)，而非根据名称猜测的其他仓库。冻结提交为 `cebdd8e4eacec1a532ce2c0041db8902217b90ba`；两个核心文件的内容 SHA-256 和 Git blob ID 见[来源清单](../../data/manifests/hiagent-terminal-baseline-20260914.json)。另读了 README、启动脚本及 barman 配置；没有执行上游安装脚本。

论文的方法是：当前子目标保留详细轨迹，过去子目标用摘要表示，按需恢复历史。论文采用原 AgentBoard 任务与模型配置；本实现换成终端环境，不能继承其分数或泛化结论。[HiAgent 论文](https://arxiv.org/html/2408.09559v1)

源码补充了不能只从概念介绍推断的细节：

| 源码位置 | 实际行为 | 本次处理 |
| --- | --- | --- |
| `cme_final.py::run` | 子目标与第一动作同一次 Actor 输出；后续动作继续属于该段 | 保留，采用已有终端可承载的 JSON 表达 |
| `make_prompt / serialize_history` | 输入装配时遍历过去段，调用摘要器；当前段保留详情 | 保留这一明确维护时点 |
| 同一输入装配路径 | 没有复用已完成段摘要的缓存；后续装配再次调用摘要器 | 首版保留，成本不隐藏；不是推荐的最终效率设计 |
| `subgoal_idx` | 指定旧段恢复详情，直到新子目标清除选择 | 保留 |
| `gripper / blocksworld` 分支 | 使用末次观察替代摘要调用；默认脚本选 blocksworld | 不把任务名特判迁入通用终端方法；本移植使用摘要分支 |
| 检索递归路径 | `self.run(...)` 的返回值没有传给外层返回 | 静态代码缺陷观察，非本地原项目复现结果；移植改为显式下一步，不派发 retrieve 到环境 |

上述运行行为依据[冻结核心代码](https://github.com/HiAgent2024/HiAgent/blob/cebdd8e4eacec1a532ce2c0041db8902217b90ba/agentboard/agents/cme_final.py)。摘要器确实发起模型调用；失败回退路径使用末次观察，不能算模型生成的新摘要。[冻结摘要器](https://github.com/HiAgent2024/HiAgent/blob/cebdd8e4eacec1a532ce2c0041db8902217b90ba/agentboard/agents/summarize.py)

冻结目录树未发现覆盖根目录或核心代理代码的 LICENSE，仅发现内嵌 WebShop 的 LICENSE。本仓库不纳入上游源代码或原提示全文；独立实现算法并注明来源。没有据此宣称已完成上游许可、完整依赖和论文复现验收。

## 2. 实际代码落点

| 文件 | 职责 |
| --- | --- |
| [hiagent.py](../../src/milai_lab/methods/hiagent.py) | 纯 Host 算法：分段、维护调用、输入装配、历史展开、共享调用上限 |
| [actor.txt](../../configs/policies/hiagent/actor.txt) / [summary.txt](../../configs/policies/hiagent/summary.txt) | 分开的 Actor 与摘要政策；不是逐题提示 |
| [hiagent_terminal_session.py](../../tools/hiagent_terminal_session.py) | 将分段方法接到已有 exec/read/final 与实际回执 |
| [hiagent_harbor_agent.py](../../tools/hiagent_harbor_agent.py) | 同一 Provider 的 Actor／摘要调用、逐类账务、Harbor worker |
| [run_workspace_native.py](../../tools/run_workspace_native.py) | 增加显式 `--order HIAGENT`；原默认实验臂不变 |
| [workspace_terminal_session.py](../../tools/workspace_terminal_session.py) | 抽出无记忆政策的 `TerminalTools`，旧 Workspace 方法继续复用同一执行逻辑 |

不增加 Runtime 语义状态、数据库表、第二常驻 Agent、模型服务或新的任务环境。HiAgent 入口不实例化旧 WorkspaceHost；`context` 和可选 Note 字段不能偷偷改变这个基线的历史组织策略。

## 3. 运行过程与真实输入变化

```text
Actor：子目标 1 + 动作 → 真实观察归入段 1
Actor：子目标 2 + 动作 → 真实观察归入段 2
下一轮：摘要调用读取段 1 的真实动作/观察
        Actor 输入 = 用户任务 + 段 1 摘要 + 段 2 详细轨迹
Actor：retrieve(1)
下一轮：Actor 输入 = 用户任务 + 段 1 详细轨迹 + 段 2 详细轨迹
Actor：新子目标 + 动作 → 清除展开选择，下一次装配恢复过去段摘要路径
```

维护由 Host 输入生命周期保证发生，但子目标边界仍由模型提出。若真实模型全程只使用一个子目标，摘要次数仍可能为 0；本实现不会用固定轮数强行制造“方法启动”。此时应报告实际未分段，而不是认定维护已被充分检验。

原始动作与工具返回完整归档；输入中的 terminal observation 仍沿用已有 16,000 字符可分页视图。因此“恢复详情”是恢复当时实际可见的动作／观察对，未展开的底层回执仍可通过原 `read` 接口取得，不冒称每次输入都包含无限长命令输出。

新子目标不是完成证书，摘要也不是事实权威。动作执行前只保存请求；取得返回后才添加观察。未知副作用或传输失败会停下，不为补摘要重复执行业务动作。

## 4. 与上游不同的地方必须公开

| 项目 | 本移植的明确差异／限制 |
| --- | --- |
| 环境、模型、示例 | 终端公开边界与既有 HTTP 模型；未复现 AgentBoard/GPT-4/领域示例设置 |
| 输出表达 | JSON 子目标＋动作，不使用上游多行字符串解析器；摘要是独立纯文本响应 |
| 提示 | 独立撰写的方法提示；没有移植领域示例或完整原提示 |
| 故障与检索 | 修正递归结果丢失；检索算一次 Actor 决策，随后继续，不运行 shell |
| 完成与权限 | 由已有工具合同和 native verifier 判业务结果；程序不认证模型对完成的解释 |
| 摘要失败 | 已结算但空白的输出显式回退到末次观察；HTTP 错误／未知用量直接停发，不吞异常 |
| 窗口 | 使用 Provider 的真实 tokenizer／窗口检查；不沿用上游不断删除历史直到容纳的分支 |
| 预算 | 沿用本地单 trial 64 次总生成、每次 4096 输出容量；Actor 与维护共同计数，不额外给予免费摘要额度 |
| 持久化 | 仅研究 Host 的本次任务内存与实验轨迹归档；未实现或验证产品公开 Note 冷恢复 |

64 与 4096 是当前本地调用合同，不是 HiAgent 的论文设定或认知规律。若下一步需要更改，应明确改运行配置并纳入比较成本，不能偷偷把维护调用移出总账。

没有缓存被隐藏在首版中。将来若需要“每个闭合段只生成一次摘要”，应另列实现版本与差异；首先确认原方法在真实任务中如何工作，再决定是否值得优化。

## 5. 已完成的检查与未完成的验证

邻近检查 **81 PASS**，包括新增 HiAgent 单元和模拟传输测试，以及受抽取影响的旧 Workspace 测试。测试证明的是程序接线与故障处理，不是模型认知效果。

覆盖的关键行为：

- 过去段真实进入摘要请求；当前段不进入该摘要；摘要进入下一次 Actor 输入，旧正文不重复附带。
- 检索后恢复实际旧正文，选择持续到下一子目标；检索没有业务副作用。
- 维护不是可选 Note；摘要调用计入同一总上限并逐类关联真实 Provider ledger ID。
- 未知用量保留 reservation 并停发；已结算但无可见输出仍计入成本。
- 用完已知调用上限后正常交回 Harbor，以便 verifier 检查已有产物，不用额外生成填“最终答案”。
- 任务目标始终保留；越界引用、非法字段不能进入执行；未知动作结果不能伪装成已经完成。

模拟完整路径使用 **5 次假响应：4 Actor、1 摘要**，固定假用量 550；该数仅为核对账务而构造，**不是实验模型 tokens**。[逐调用轨迹](/cra/memory/mx_memory/evidence/hiagent-baseline-20260914-nYqZki/mock-cases/test_actor_and_maintenance_use0/host/demo/method-events.jsonl)保存了请求、摘要、展开前后输入和回执；[终态](/cra/memory/mx_memory/evidence/hiagent-baseline-20260914-nYqZki/mock-cases/test_actor_and_maintenance_use0/host/demo/terminal.json)可核对 Actor／摘要的用量归属。

| 工程项 | 本轮状态 |
| --- | --- |
| 邻近测试 | 81 PASS；[记录](/cra/memory/mx_memory/evidence/hiagent-baseline-20260914-nYqZki/targeted.log) |
| 边界检查 | PASS |
| 全仓 ruff | PASS |
| 全包 mypy | PASS，41 个源文件 |
| 构建 | wheel / sdist PASS |
| 既有 Harbor 0.23 环境 import／CLI | PASS；只导入与 `--help`，没有启动容器、HTTP 或任务 |
| 全仓 pytest | **未完成**：收集 4474 项，主动中断前 2279 PASS / 1 可选依赖 SKIP；589.50 秒，exit 2；[日志](/cra/memory/mx_memory/evidence/hiagent-baseline-20260914-nYqZki/regression.log) |

全回归在历史 V0222 校验过程中仍在运行，本轮为有界交付主动 SIGINT 停止；这不是测试 FAIL、超时故障或全仓 PASS。2194 个收集项没有取得本次完整执行终态，不用邻近检查重复计数补齐，也不继承上轮全仓成绩。对应检查进程已经退出，没有遗留后台回归任务。**因此原型的局部交付成立，全仓回归验收仍未完成。**

没有运行真实 tokenizer+HTTP+Actor+摘要+环境的完整 trial，故不能签发 `LIVE_USABLE`。模拟 Provider 使用真正的客户端与账务代码，但 `MockTransport` 完全替换了网络；Harbor 继承边界在测试中被替身隔离，真实 Harbor 本轮只做导入检查。

## 6. 近邻与 MiLAi 增量：本轮没有混入

Mastra 的同步生命周期说明支持“Host 明确发起维护，而非等待 Actor 自愿写记忆”这一实现取向；本轮只核对文档，不移植 Observer、Reflector 或其 TypeScript 代码，也不声称完整复现。此处 HiAgent 的维护时点来自其自身源码，不是叠加 Mastra 阈值。[Mastra 官方文档](https://mastra.ai/docs/memory/observational-memory)

MemR³、ACE、AgentFold 保留为用户提出的后续近邻；本轮没有重新逐项复现其运行路径，不把其他项目的主张当成本实现成果。

MiLAi 后继差异仍只是一项待验证假设：在基线已运行之后，将“总结一个闭合段的过程与结果”改为“维护当前决策依据的适用范围，并只修订被新反馈影响的部分”。该操作可能保留、缩小或撤回既有判断，不等于再增加一个 `REGULATED` 提醒。

这会改变什么、需要额外多少维护调用、能否超出已有近邻，应随后单独检验。本基线中没有植入该增量，不能把其未来信号预支为当前创新。

## 7. 下一步不是重新填写任务矩阵

保留一个短的实际使用步骤：明确授权一个已有隔离任务和调用预算后，通过 `--order HIAGENT` 运行一条真实方法轨迹，直接查看分段是否发生、摘要是否改变输入、Actor 是否能够继续有效行动，以及完整成本。任务不要求刻意经历恢复；若没有触发某条路径就如实记录。

这不是要求基线先获胜，也不是新的 A—E 准入链。真实运行能够解释之后，再提出相对该基线的一处算法改变，并放回普通 Agent／review 和已有方法的对照。当前不启动新批次、不续用旧 Goal 剩余配额、不修改产品默认。
