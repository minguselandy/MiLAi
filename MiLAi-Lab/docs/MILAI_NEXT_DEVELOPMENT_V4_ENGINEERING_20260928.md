# v4 工程验收与语义验证边界

状态（工程验收时点）：**F8_A_ACCEPTED; REAL_SEMANTICS_NOT_RUN**。
后续真实B两轮均5/6、停止本轮修订；当前完整结论见[F9总体报告](MILAI_NEXT_DEVELOPMENT_V4_OVERALL_EXPERIMENT_REPORT_20260928.md)。
本记录对应 [F1–F7 合同](MILAI_NEXT_DEVELOPMENT_V4_IMPLEMENTATION_CONTRACT_20260928.md)，
不替代 [完整执行记录](MILAI_NEXT_DEVELOPMENT_EXECUTION_GOAL_V4_20260928.md)中的 F8 B/C 与 F9。
Sol 已停笔，Root 已核对 11 项工程文件的实际字节与哈希及检查回执；真实 generation/embedding 调用均为零。
公开 [检查清单](../data/manifests/next-development-v4-f8a-checks-20260928.json)绑定工程源码、检查范围和原始回执身份。

## 工程结果

- 相关 core/foundation 检查去重 **44 个 nodeids 通过**；新行为、原 C、默认路径和历史权限边界分别覆盖，未跑全套测试。
- Ruff、Mypy、依赖检查矩阵和两项源码边界检查通过。矩阵覆盖 156 个 active source，新增纯模块归 core，相关入口保留 foundation 归属。
- 六个原输入使用正式 B config 零模型 prepare 成功：15 条公开消息、158 项源码身份，零外部 HTTP/共享 Postgres，子进程不注入 DSN。
- 从真实 MockHTTP 接线捕获的四份请求经现有 Qwen 模板渲染，原内容均可见；prompt tokens 为 866/1244/1519/1631，均满足冻结容量。
- 一次成功离线构建产出 wheel/sdist，检查包内受影响源码与现场字节一致、私密资产排除。构建产物留 ignored，不提交。

失败过程保留：早期 schema/账本字段/测试数据库路径断言、两个独立 Mock RunBudget 对象导致的费用断言、
Ruff/Mypy 格式与类型问题均有修正记录。首次 no-isolation 构建因 foundation 缺 hatchling 失败；
随后使用现有离线 uv 缓存构建成功。包核查曾误将 uv 创建的 `.gitignore` 当压缩包，修正文件过滤后核验，未重建包。
Root 的离线脚本首次调用不存在的 `python` 未执行，改 `python3` 后仅语法核对通过；Git 只读状态查询缺 `gh` 后用既有 connector 完成。
这些都是工程/工具过程，不计为真实模型实验，不抹去失败，也不因此增加效果样本。

## 最小改动及可检查的职责

| 层 | 实现职责 | 验收不代表什么 |
| --- | --- | --- |
| F1/F6 程序操作审计 | 用真实 owner/turn 配对的调用和 ToolMessage 记录操作、ID、结果与前置事件引用；无调用不认证 saved | 不证明记忆内容正确或用户意图已满足 |
| F2 最终请求副本 | JSON-action 历史序列化后标六类来源；原 checkpoint/ID/参数/结果正文保留 | 不由程序选择哪段内容是真相 |
| F3 临时工作视图 | 当前 Human 引用、逐续接可见原文、当前已访问记录 ID；更新/删除后重新解析 | 不抽取所有自然语言约束，不形成第二份长期事实库 |
| F4 业务观察 | 实际 ToolNode 回执的接收时间按 scope/call ID/hash 绑定；部分副作用和未知结果保留 | 接收时间不是业务发生时间，也不证明世界当前状态 |
| F5 普通 CRUD | 原 strict 工具和 exact READ 保留；短通用合同要求独立事项、保持无关内容、临时/只读/删除分工 | 不通过关键词分类或自动改写记录来保证语义 |
| F7 预算选择 | all→普通 query→显式且确有容量瓶颈才可一次 Attention；候选正文完整，完整请求复核容量 | Mock 路由通过不证明真实检索瓶颈或选择收益 |
| 中断与费用 | v4 opt-in 捕获实际中断回执；原错误继续传播；记录检索、审计、路由和连续模型费用 | 不自动重试未知业务动作，不把退出成功当验收 |

所有新增行为由 `memory_boundaries.enabled=true` 显式启用，仍为 B0。旧 v3 配置和 C 保持按旧合同运行。
v4 不允许 C correction；无默认 controller、U 或第二 memory schema。原 `memory_result.py` 和 strict 工具不变。
可选 Attention 只保留本 turn 的 ID，不缓存事实正文；任意进程崩溃后的选择缓存恢复尚未验证。

## 七项工程解释

| 原计划 §20 问题 | 实际合同和退出条件 |
| --- | --- |
| 信息来自哪里 | 当前/历史用户、工具回执、普通持久记录、历史助手、当前提案分别标识；审计引用真实消息/工具 ID 和正文 hash |
| 属于哪类对象 | 原消息为事件；普通 Store 为 Durable Memory；Working State 是当前 task/ref；业务数据库与工具为 World |
| 谁可修改 | Host 经已有工具修改自己 scope 的普通记录/授权业务；程序只生成请求副本、临时引用与操作审计；不自动补语义事实 |
| 何时退出 | 临时 task/ref 随 turn/session 重建；持久记录按实际 DELETE/UPDATE；删除记录不删除审计历史；世界按真实工具改变 |
| Host 看到了什么 | prepared view/route 与有实际 generation ID 的 delivery 分开，最终完整 HTTP 及选中记录可核对 |
| 工具结果谁验证 | 程序按实际配对结果记执行状态；partial/unknown 不被最终回答覆盖；保存语义另由离线评分判断 |
| 是否要求模型重复证明 | B0 final 仅 answer；不要求 receipt ref、committed 声明或多一次证明调用；历史 C 只作独立复现 |

## 必须区分的证据

F8 A 使用局部 Store、真实 LangGraph/ToolNode 与 Mock HTTP、实际 tokenizer/template 和零模型 prepare。
这些能验证接线、隔离、ID、模板和费用记录，不能验证实际 Host 是否按边界执行。
所有 Mock 使用与开发代理费用均不进入实验 ledger。必要入口构建只做一次，不为 Git 发布重复已通过检查。

F8 B 使用六个已暴露脚本；[协议](MILAI_NEXT_DEVELOPMENT_V4_B_REGRESSION_20260928.md)要求四条持久正例完整链不退化，
当前 BRIEF、引用、临时和只读边界分列。只有 A/B 通过，才创建并冻结 8–12 个新的 F8 C 脚本。
小 bank 没有真实瓶颈时不启动 F8 D；测试了可选 selector 不能当作其研究准入。

## Reflection：F1–F7 的当前工程判断

| 总规划 §32 问题 | 工程阶段判断 |
| --- | --- |
| 1 支持什么 | 执行审计、来源标记、临时引用和预算路由可以复用现有 runner/工具，而无新增事实层 |
| 2 反驳什么 | 模型写出 saved/receipt ID 才能知道是否执行，不是必要条件；程序已有实际工具结果 |
| 3 首断点 | 最终 wire 重序列化会覆盖过早标签；非容量异常曾跳过回执捕获；续接不能只限制 selector 次数却不保留 ID |
| 4 更简单解释 | 格式遗漏仍可能是 Host 当前约束消费失败，来源竞争也不一定由记忆维护失败造成 |
| 5 更简单方法 | 普通 B0、原 strict CRUD、当前任务原文和 all/query；不增加常驻维护器或审核模型 |
| 6 复杂度 | 新临时 view 和程序 audit 有额外 token/CPU/I/O；真实总费用待 B/C，不能预称节省 |
| 7 过拟合风险 | 工程使用机械构造，B 全部已暴露；不把已知答案写进运行时，C 必须在 A/B 通过后另建 |
| 8 反例 | 无调用假 saved、partial/unknown 业务结果、更新后旧缓存正文、去候选仍超限，均应保持可观察 |
| 9 决定 | 工程验收通过；Continue 到发布后冻结的六脚本 B 回归，不提前创建 C |
| 10 理由 | 先证明实现实际进入模型请求和执行链；方法稳定必须再由真实完整任务证据判断 |

当前研究目标未达成，Product NO-GO。失败的工程检查及修正和最终通过回执一并保留，不替换为只有成功的记录。
