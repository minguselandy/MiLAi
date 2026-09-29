# v7 E1 冻结协议：同模型工具协议校准

状态：输入与评价已预定，源码检查／发布及运行 freeze 尚待完成。本文不宣称运行结果。
依据[原 v7 计划](MILAI_DEVELOPMENT_EXPERIMENT_PLAN_20260928_v7.0.md) §10.2、§15，
第一 slice 只有 P0/P1/E1。使用现有普通记忆 B0、严格工具合同、host_direct writer、原始业务接口。

## 比较与环境边界

J 使用 json_action，N 使用 native；两组均 current_request / compact_v6 / non-thinking。
原用户文字、owner、当前合法记录、历史权限、工具名称／能力／执行校验、世界初始状态相同。
JSON 最终 `answer` 的解码文本与 native 最终自然文本面对同样的用户内容／格式义务。
工具目录表示、消息编码、native 专用模板标记、调用 ID、parser、真实 tokens 可以不同，逐项记录。
不回退 full，不强制 `tool_choice=required`，不启用旧 C、M1、ODR、selector 或独立 writer。

[P0 能力清单](../data/diagnostics/development-experiment-v7-p0/protocol_capabilities.json)证明
现有 vLLM 0.27.1 缺少 auto-tool-choice 和 tool parser，native N 的 12 个 job 已在看答案前
标为 `BLOCKED_ENVIRONMENT`。保留其计划分母，不发无效生成、不改共享服务、不添加第三种客户端解析协议。
仅 J 可真实执行，故 E1 的协议效应结论必为未定；J 的失败仍是自己的真实任务结果。
P1 native 模拟响应与真实工具执行窄查属于工程证据，不冒充真实 Host native 验收。

## 固定输入、重复与评分

输入位于 [E1 目录](../data/diagnostics/development-experiment-v7-e1/)。

| 意图结构 | 每轨迹公开消息 | 关键证据 |
| --- | ---: | --- |
| save_plan | 2 | 实际持久保存＋新 session 读取，不预约 |
| update_matter | 3 | 自然形成、原事项同 ID 更新、保留独立事项、新 session 使用 |
| business_current | 2 | 一次真实预约／标签、精确完整 key、后续 live lookup；不依赖 formation |
| read_only | 1 | 正确只读答案，合法零写入 |
| quoted_rejected | 2 | 拒绝的命令式引文不成为写入／业务指令，后续普通任务 |
| temporary_override | 3 | 自然保存长期格式、一次临时覆盖、同 session 恢复长期格式 |

六种预定结构，每种两重复、两协议，共 24 条计划微轨迹／52 公开消息；
实际可运行 J 为 12 条／26 消息／22 个隔离 session，N 为 12 条／26 消息／22 session 未运行。
每重复 46 条任务义务：current_explicit 26、later_use 4、persistent 16；
另有 13 条非任务失败诊断义务。J 完整分母为 92 条任务、26 条诊断。
六种结构是主要任务单位；重复与同链义务不能当成新的独立样本。
这是新写的合成协议诊断实例，继承已暴露意图结构，不称稳定 unseen 或自然用户收益。

[execution-order.json](../data/diagnostics/development-experiment-v7-e1/execution-order.json)
预定两个重复轮次和交替 J/N 顺序。N 的阻断槽位保留；J 严格沿既定顺序运行。
每 job 一次正式尝试；不失败后换题、调提示、补写 memory、挑轨迹或增加重复。
每条轨迹使用独立 run_id/owner namespace、Store、checkpoint、业务数据库；开始全空，label_available=true。
没有 operator memory 或 world event；实际 IDs 只来自本 job 工具，不能从标准答案注入。
跨 session 的信息仅由持久记忆及实际业务数据库进入；同 session 保留真实图历史。

Root 按[义务](../data/diagnostics/development-experiment-v7-e1/obligations.json)和
[评分说明](../data/diagnostics/development-experiment-v7-e1/rubric-guide.json)离线评判。
每个任务失败项有用户原文依据；多字段项必须全部满足，失败字段单列。
记录拆分／合并本身不判错，不要求人为偏好的记录数；同事项更新必须有真实旧 ID，且不能留冲突副本。
若上游 formation 未成功，后续请求失败保留，条件化的同 ID 执行分母记未激活；不假造初始正确记忆。
业务查询按实际世界分支评分：若前序没预约，后序真实 `not_found` 可通过自己的如实回答义务，
前序预约仍失败。自然语言声称保存与程序真实提交分开；不由程序“已完成”代替语义验收。
可选额外只读调用仅进入成本／诊断，不以隐藏最少或最多工具数造失败。
无在线 rubric/Judge，无模型裁判成本，无运行时自动改写最终答案。

## 请求、执行与费用

Host Qwen3.6-35B-A3B-FP8，7860，temperature=0，max_tokens=4096，thinking=false；
容量 65536，安全余量沿现有 recipe；embedding bge-m3，7861，1024维。
部署模板/tokenizer 与计数资产已核 hash；recipe 不发 seed，temperature=0 不保证重复相同。
所有真实生成／embedding HTTP 并发为 1。每公开消息最多 12 次生成，失败和重试均不能绕开容量。
共同同步 FoundationScope 的 `max_concurrency=1` 及实际 ToolNode 调度由 P1 验证；
参数依赖上次工具结果时，必须等待实际结果，不能虚构尚未产生的 ID。异步调度不属于本配方。

连续账本沿原树 `artifacts/ser-v20/budget.json`，起点 3263 次生成／4,155,747 generation tokens／
23,276 embedding tokens，SHA `2df7547a9d038cb53105afbf5daa97bbd8225bb204c19af40b7c68eee264ade2`。
不清零，不引入累计硬上限。预计 J 26–90 次生成、约 40k–150k generation tokens，
依据 v6 S4 60 calls/40 messages 的量级及本轮保存／维护可能多次工具续接；只是投入估算。
实际可能超出估算，仍按既有每消息限制和安全停止规则执行。资源由现有共享 Host、embedding、
Postgres 和本地隔离 checkpoint/world 提供，无下载／新服务／构建产物。
逐阶段记录 formation/maintenance/business/use 的完整生成输入、输出、embedding、HTTP wall time、
Store/CPU/持久读写、失败与 unknown。未提供独立 reasoning tokens 时为 unknown，不填 0 或重复相加。
开发代理 token 与实验成本另账；无证据不估精确 GPU 小时／货币费用。

## 冻结与停止

先发布 P1 源码及窄查，再发布本协议／输入。Root 在已发布准确 SHA 上用现有 runner `prepare`；
核源码、配置、输入、依赖、工具目录、义务／评分、顺序、部署、起点账本、Root 编排 helper 哈希，
形成 ignored `artifacts/development-experiment-v7/e1/execution-freeze.json` 后才运行。
prepare 同样可核 N 的离线身份，不代表 N 获准真实调用。原始 trace、DSN、数据库仅留 ignored；
公开精简结果和复现身份不包含凭据。

普通漏写、漏答、错误参数或合法无操作保留为失败，已终止且环境安全时继续其余独立冻结 job。
跨 owner 写入、越权删除、未知副作用盲目重放、伪造执行回执立即停止并隔离该路径。
每 job 完成后 Root 核安全与实际语义再运行下一 job；语义未通过不自动删除后续独立诊断。
运行中源码、输入或环境改变则停止旧身份，不修改 freeze 冒充同一批。

完成 12 个可运行 J job 或记录具体安全／环境阻断后，P5 报告七层结果、四层义务、
条件化分母、逐例失败与两种解释、完整成本和全部未运行项。
当前 slice 到此结束；N 恢复、E2–E6、第二模型、接口／writer 分支不自动开始。
协议效果只能判 `INCONCLUSIVE/BLOCKED_ENVIRONMENT`；可另报 J 的任务可靠性，Product 仍 NO-GO。
