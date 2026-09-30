# v13.1 等额配置的实际开发比较

已按预先选择的 8 个旧来源组完成 B2、B3、公开 Scope 候选各两套配置，共 48 个题对。形成与读取共 96 个不同进程，48 份持久资源经独立 SDK 重开核对。官方历史的原始首尾角色完整保留，writer 不读取当前问题，reader 使用相同官方任务提示、日期和原始当前问题。完整输入、来源、参数、形成节奏及选择规则见[事前协议](../data/manifests/v13-1-equal-config-development-protocol.json)。

以下是本地 Qwen 同族 Judge 诊断，使用原任务的评分 payload、schema 与解析合同，每个答案只调用一次。它不是官方 DeepSeek、独立 Judge、盲审人工或 leaderboard 结果。scope/valid/personalized 的计划分母分别为 4/2/2；不把它们合成研究总分。

| 配置 | scope | valid | personalized | 开发配置选择用三任务平均率 |
|---|---:|---:|---:|---:|
| B2-a | 3/4 | 1/2 | 2/2 | 0.75 |
| B2-b | 4/4 | 0/2 | 2/2 | 0.667 |
| B3-a | 3/4 | 1/2 | 2/2 | 0.75 |
| B3-b | 4/4 | 0/2 | 2/2 | 0.667 |
| Ours_scope-a | 4/4 | 2/2 | 2/2 | 1.00 |
| Ours_scope-b | 4/4 | 2/2 | 2/2 | 1.00 |

按事前规则选 B2-a、B3-a、Ours_scope-a。Scope 两配置诊断相同，由完整运行 token 成本择较低的 a。选择冻结原配置字节与 sha，不再把仅声明两套配置当作已实际公平试跑。

| 配置 | 全形成＋读取生成 calls/tokens | embedding calls/tokens | 实际滚动摘要次数 |
|---|---:|---:|---:|
| B2-a | 8 / 29,230 | 48 / 14,484 | 0 |
| B2-b | 8 / 29,850 | 48 / 14,244 | 0 |
| B3-a | 30 / 31,641 | 0 / 0 | 22 |
| B3-b | 30 / 31,153 | 0 / 0 | 22 |
| Ours_scope-a | 16 / 37,210 | 0 / 0 | 0 |
| Ours_scope-b | 16 / 41,082 | 0 / 0 | 0 |

运行新增 108 generation / 200,166 generation tokens / 28,728 embedding tokens；评分另新增 48 generation / 78,556 tokens。逐个真实 HTTP 响应与原连续账本完全相符，unknown usage 为 0。冷进程时间、CPU 与存储字节已记录，但 I/O 覆盖不完整，不推断 GPU 小时或美元。完整结果见[实际结果](../data/manifests/v13-1-equal-config-development-results.json)。

这里只完成旧开发配置选择。B2 逐过去片段建索引，B3 真实闭合回合滚动摘要，Scope 一次读取完整过去历史形成；这不是只改变表示的因果实验。Scope 的正文、basis 和范围语义仍由模型提出，来源存在不证明其正确；原生文本任务也没有本项目实际业务对象／字段绑定，不能据此声称 operational grounding、权限或恢复增益。样本量很小且已曝光，不支持统计优势、非劣或独立泛化结论。

首次准备因错误假设官方历史全部闭合而在零模型调用时失败，原 24 份准备资源、错误和旧协议仍保留；未换题、补造 assistant、改写答案或多次挑选响应。完整规划继续 ACTIVE，正式来源缺口保留，Product NO_GO。
