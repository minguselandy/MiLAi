# SIM09：原生思考模式未消除规划续做错误

状态：`MECHANICAL_CHAIN_VERIFIED / TASK_CONDITIONS_NOT_PASSED`。
这是SIM08失败后的开放开发检查，不是正式D4/D5、留出样本或独立效果确认。

## 最小改动与冻结边界

发现本地Provider原先固定发送`enable_thinking=false`，而已部署vLLM进程启用了`qwen3`
reasoning parser。新增严格布尔配置`enable_thinking`，旧配置缺省仍为false。
tokenize和实际生成使用同一设置；输出上界、预约、单在途、deadline及未知usage规则不变。
只把最终content交给Host动作解析，原生reasoning不作为来源证据或工具动作，也不转发到
下一轮任务上下文。保留原始Provider回执，不索取或评价模型内部推理。

[vLLM官方文档](https://docs.vllm.ai/en/stable/features/reasoning_outputs/)描述该解析模式及
结构化输出支持；本次是否实际启用以本机回执为准。A/B均返回独立reasoning字段，
completion_tokens全部计入成本；Provider没有返回reasoning token细分，不用字符数估算。

本次只为A/B各分配一个新本地续做会话。逐字节复用SIM08真实G的所有文件，不再次生成G，
不根据续做答案补记忆。来源、评价、Host提示、工具、CURRENT_TASK_ONCE及输出4096上限
保持；两组仅记忆预载方式不同，均启用原生思考。每会话100万raw/600秒/64请求，
新批200万raw仅作异常护栏。公共source ID重新绑定，业务payload与数组保持原值。
Product pin仍为`97eaac6de36a96e903af0b41412a44e8c7715539ca12359b7be41f790a5754bc`。

## 准备失败与显式恢复

第一步在0模型分配、0生成时发现payload比较不相等。核对确认唯一差异是适配器自己维护的
Evidence引用集合在新ID绑定后重新排序；普通字段和业务数组没有变化。保留原失败，
仅对这个已声明的资格引用集合记录顺序无语义，不对任意数组做排序或删除。

原公开保存其实已CONFIRMED。恢复时重新启动已确认停止的自有服务，公开GET确认原提交版本，
直接复用该回执和payload，修复过程新增State写入0。第一次恢复命令因旧Docker Compose
不支持`start --wait`在生成前失败；改用该环境已经验证的`up --detach --wait`继续。
这两次基础设施失败均保留，没有覆盖原结果或释放未知请求，也没有模型请求重试。

## 实际结果

| 续做 | 请求 | input | output（含reasoning） | raw总计 | 在线秒 |
|---|---:|---:|---:|---:|---:|
| A 详细预载 | 1 | 7,757 | 2,831 | 10,588 | 27.078 |
| B State优先 | 1 | 6,252 | 2,840 | 9,092 | 32.832 |
| 合计 | 2 | 14,009 | 5,671 | 19,680 | 分会话报告 |

成功恢复执行含准备/清理69.696秒；此前两次准备失败分别20.382和0.220秒，
各次执行墙钟合计90.298秒，人工诊断间隔另计。历史G的34,480 raw不重复加入新增总账；
若描述共享G加本次A/B链路，须另列总54,160 raw，且G仍是原非思考条件。
当前两臂输出均未触及4096上限，没有预算、UNKNOWN或超时失败。

两组仍第一次请求就交付，主动来源查阅均为0。Host回查完整呈现条件1–4的冻结片段；
ADR-047未进入回查、计时文档仅部分返回，原文件和检索入口仍存在。
因此不能把所有错误解释为检索未提供来源，也不能把思考模式生效解释为理解正确。

按原固定来源条件直接审阅最终交付，不增加Judge：

| 必要条件 | A | B |
|---|---|---|
| 1 操作与head区分 | 保持UNKNOWN并明确两种观察独立；较SIM08表达更清楚 | FAIL：把题目未指明原因的请求超时写成已知PoolTimeout/连接获取失败 |
| 2 不盲覆盖或凭head确认旧操作 | 明确禁止盲覆盖，使用显式操作重放 | 明确禁止盲覆盖，但其下一步仍笼统称确认最终一致性，未说明关联操作约束；未完整满足 |
| 3 目录同步失败阻止Evidence/outbox提交 | 未完整满足：解释未引用Blob，未明确本情形提交被阻止 | 未完整满足：解释发布边界未闭合，未明确无Evidence/outbox提交 |
| 4 保留来源、同步及既有重放合同 | 未完整满足：建议重放/再提交，没有明确来源保留与幂等条件 | 未完整满足：提出有效证据或清理的处置，未明确原文保留和原操作条件；没有实际执行 |
| 5 可选tenant上限的每池/进程范围 | FAIL：把可选tenant设置归于ADR-044，未说明其具体边界 | FAIL：仅以ADR-044普通池背压解释，没有取得ADR-047约束 |
| 6 缺失计时与嵌套口径 | 未覆盖，不默认PASS | 未覆盖，不默认PASS |

“未完整满足”记录必要内容缺失，不一律解释成错误事实断言。整体写作质量与不可观察推理
保持NOT_EVALUATED。两组存在可直接核验的关键错误，故不能进入留出验证或声称有效降本。
跨批没有独立重复，不将局部表述变化写成原生思考的普遍质量提升。

下一步保持failure-driven：同时审查Host对来源依据的交付要求与评测条件是否对应实际任务，
只修一般机制。当前判据和失败不回写；新任务契约若需更清楚，应建立独立版本并明确非留出。
不通过提高输出额度、反复重跑原G、增加隐藏reviewer或按题目注入答案来制造成功。

## 检查、总账与清理

定向33通过；完整Lab `uv run pytest -q` 422 passed（3.94秒），boundary/Ruff/mypy30/build通过。
新增测试验证缺省/显式思考设置在tokenize与生成一致、reasoning不是动作、输出子集不重复记账，
以及非布尔值在网络前拒绝。Product未改，无迁移、权限或Canonical变化。
实际请求hash、usage、两组公开恢复、原G完整文件、来源呈现、模型配置与终态审计通过。
自有两个Host、API、worker退出；PG退出0无OOM，卷保留。共享服务未变。批次新发送已关闭。

SIM01–SIM09累计63请求、1,229,525 raw tokens，16个执行完成模型会话、2个失败会话及
1个首次生成前失败分配，共19个终态分配。SIM09两次准备失败发生在分配前，分别保留而不混入
模型会话分母。付费0，pending0。Schema仍0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE。

证据：`artifacts/v02-e2e-generality/sim09-planning-thinking-20260907a/`：
`execution-result.json`、`resume-result.json`、`resume-v2-result.json`、`generator-reuse.json`、
`terminal-audit.json`、原始Provider请求/回执/ledger及A/B最终交付。
配置：`configs/v02-project-planning-thinking-20260907.json`，原运行配置保留在产物目录。
