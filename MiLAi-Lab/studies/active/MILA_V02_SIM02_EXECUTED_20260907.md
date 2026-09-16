# SIM02：授权批次在G预算门停止

状态：`STOPPED_WITH_FAILURE / G_TOKEN_LIMIT / NO_AB_COMPARISON`。
用户在审阅[已准备批次](MILA_V02_SIM02_PREPARED_20260907.md)后明确“授权运行”。
本次只启用已准备目录的G/A/B各至多一次、每会话20,000 raw tokens/30秒、批次60,000额度；
独立本地诊断先行，不进入正式D4/D5。配置、授权原文、执行前源码摘要及Product pin均留档。

| 项目 | 实际结果 |
|---|---|
| 模型 | 本地Qwen3.6-35B-A3B-FP8，未使用付费模型 |
| 分配 | G一次；A/B未分配 |
| 已发送生成请求 | 2，均有可信usage回执 |
| raw input / output / total | 11,167 / 147 / 11,314 |
| G在线时间 | 22.827608秒，包含绑定、恢复、工具与必要保存预算边界 |
| 停止点 | 第三次tokenize之后、预约/生成发送之前，`TOKEN_LIMIT_BEFORE_DISPATCH` |
| 未结算请求 / 超额回执 | 0 / 0 |
| 保存、冷恢复、续做比较 | 未取得证据；无handoff.md/details.md/最终交付 |
| 服务恢复 / 全程含清理 | 7.136309秒 / 30.848543秒，恢复单独列账 |

累计11,314并不意味着还可以发送8,686 token的新材料：下一次请求还要重复发送历史，
并留出输出额度。第1/2次prompt分别4,050/7,117，输出74/73。第三次具体tokenize计数
没有落盘，不能补造数字；由固定代码路径与终止阶段可知3次tokenize中最后一次未进入生成。
这是一处计量可观察性限制，不追加调用来回填历史结果。

实际两次模型动作均为read_files：先读session-000至003，再读004至007。
第一批页面进入第二次真实模型请求；第二批只有工具取得记录，第三次生成未发送，不能算已呈现。
分页有MORE/next，完整44份原文件逐字核验未改；未删除首尾、补摘要或按未来题目选内容。
已发送请求不含续做题目。没有产生足够产物前就停止，不能判作“合理不保存已完成任务”，
也不能判作记忆保存接口失败或整个记忆方案无效。

结果只证明这个Host/任务/模型组合在冻结预算内未完成前序归档任务。
L1与L1+L2的收益、后续题目的首次实质判断与端到端通用性均未评价。
不重试、不追加G、不扩样、不将剩余额度转到未来批次；执行目录与通用候选配置现均关闭模型入口。

运行目录：`artifacts/v02-e2e-generality/sim02-ready-20260907a/`。
主要证据：`authorization.json`、`authorized-config.json`、`provider-ledger.jsonl`、
`G/*-request.json`、`G/tool-events.jsonl`、`chain-result.json`、`execution-result.json`。
准备时的零授权记录原样保留，不能解释为当前仍待审批。自有API/worker/G/MCP均退出，
PG停止且未OOM，完整数据保留。Product源码与既定pin未变，Schema仍为0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE。

本轮Lab检查：`uv run milai-lab-check-boundary`通过；`uv run pytest -q` 372通过（2.75秒）；
`uv run ruff check src tests tools`、`uv run mypy src/milai_lab`（30源文件）、`uv build`通过。
这些工程检查不提供模型语义或产品效果PASS。
