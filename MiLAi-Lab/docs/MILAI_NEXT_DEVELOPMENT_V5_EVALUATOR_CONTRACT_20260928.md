# v5 离线义务合同与链路分析接口

状态：IMPLEMENTATION_CONTRACT；Root拥有rubric与语义判断，Sol实现小型离线组合器。
遵守[v5计划](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v5.0.md) V1/V2，不增加自动语义裁判或runtime接口。

## 四层义务

每项义务有 `id`、`case_id`、`target_message_id`、`layer`、`description`、`task_failing` 和 `basis`。
layer固定为 `current_explicit_obligations`、`persistent_obligations`、`later_use_obligations`、`diagnostic_completeness`。
同一个实际要求只使用一个id；later use既计入其层，也按当前消息显式要求纳入explicit汇总时须按id去重。
保存确认不等于保存成功；持久状态和后续回答分别打分，不能混合分母。

basis是 `message_id` 与原始可见文本的 `quote` 列表；必须逐项核对引用存在且为原文连续片段。
basis不得引用target之后才出现的消息；当前/过去可见文本均可作为依据。
引用机械存在只证明可追溯，不证明自然语言蕴含，Root仍须人工交叉审查每个task-failing/持久义务。
diagnostic不得设置task_failing；没有用户可见依据的完整性要求只保留诊断。
负持久义务依据“仅此回复”“不要保存/改变”“第三方引用并未采纳”等可见范围声明，不冒充长期保存请求。
历史rubric不改，legacy_score只透传保留；新解释不生成替代legacy总分。

## 建议JSON边界

合同根字段：`schema_version: 1`、`runtime_must_not_read: true`、`cases`。
每个case含 `case_id`、`messages: [{message_id, text}]`、`obligations`。
观测根字段：`schema_version: 1`、`observations`，每行以 `case_id/obligation_id` 配对。七个链路字段在观测行顶层；输出组合为chain。
每行 `result` 为pass/fail/unknown/not_applicable；链路字段由Root检查证据后显式填写：

```text
present_in_user_request
requires_memory
memory_formed
memory_delivered
answer_contains
tool_argument_contains
world_effect_correct
```

链值为yes/no/unknown/not_applicable；答案不应包含的范围义务用description/result表达，不能把no机械等同fail。
`evidence`保存来源path、SHA及定位信息；工具只检查形状/身份和组合表，不通过子串自动打语义分。
支持 `legacy_score`、人工 `earliest_breakpoint` 和 `note` 透传；不从yes/no自作因果归因。
缺失观测保留unknown/missing，不能被零条结果伪装全通过；重复或悬空id明确拒绝。
输入不能被修改；输出是四层链表及分项计数，不修改冻结历史分数。

## 实现与检查范围

允许 `src/milai_lab/analysis/obligation_trace.py` 与直接窄测试；可经模块CLI读取两JSON并输出JSON，
不增加线上入口、LLM、网络/DB或runtime依赖。不引入通用评测平台、自动义务抽取器或隐式rubric推断。
必要检查覆盖：diagnostic不影响失败、无依据要求被拒绝、legacy保持、缺失未知、重复/错id、正负义务不按yes/no误判。
采用现有core环境、矩阵和边界检查；只在文件变动需要时改验证映射。无需完整测试或模型。

V3请求组件token分析可用独立离线函数，不改变任何实际Host请求。须区分组件独立token数与
完整chat-template总数（BPE边界并非简单可加），并以同一个现有tokenizer复核old/candidate。
不得以“删除了一段说明所以语义不变”替代明确保留字段核对；即使离线节省成立，也不宣称实测质量不变。
