# MILA-V02-05 P1：逐请求等待点诊断

状态：`CORRELATION_COMPLETE / P1_PARTIAL / MCP_P95_TARGET_NOT_MET_AT_8`。
新增模型调用、生成 token、tokenize 请求均为 0。D4/D5 未进入。

## 改动与可观察边界

复用 Runtime 的 OperationTimer、ContextVar 和脱敏 JSON 日志，增加默认关闭的
`MILAI_REQUEST_TIMING_ENABLED`。记录 Flask 应用处理、连接池获取和连接持有时间；
MCP Working State 成功读写记录 handler 与 SDK 调用耗时。两侧用响应 request ID 的
SHA-256 前 16 位关联，不输出正文、身份、来源引用或凭据，不增加模型输入。
公开观测定义见 Product `docs/contracts/MILA_REQUEST_TIMING_V1.md`。

没有新增工具、返回字段、数据库实体或迁移，权限、CAS、审计和 Canonical 权威不变。
回退可关闭该开关；本轮未发布公网。Schema 仍为 `NO-GO FOR SCHEMA FREEZE`。
源码 pin 为 `f476001abeb201dc7bfe79b9a209a7851147379a7df659ec04a594fded4d2142`，
锁为 `data/locks/v02-request-timing-product.lock.json`，包括公开计时合同的独立摘要。
先前基线锁和原始结果保留，当前工程配置及仍关闭的 SIM02 候选改指此锁。

## 本轮数据与结论

配置为 `configs/v02-service-request-timing.json`；产物目录为
`artifacts/v02-e2e-generality/p1-timing-20260906a/`。
沿用 1,000 条合成 State、1/8 并发、两核进程 affinity、8 API 线程及既定 PG 限额。
SDK 基线后，两种 MCP 传输在同一服务读相同的三条 State 及其版本，正文为
512/2,048/8,192 字节。各模式一个复用客户端、三个预热读取，1/8 并发各三轮 96 次读取。
总 MCP 调用 1,161 次，其中 1,152 次计量读取全部唯一关联到两端记录。
没有缺失、歧义或格式损坏；保留逐请求结果，不用分位数相减计算等待时间。

以下均值单位为 ms；每格来自同组 288 次读取，P95 单独列示。

| 模式/并发 | 客户端均值 | 客户端 P95 | MCP handler | Runtime SDK 调用 | Flask 应用 | 池获取 | 连接持有 |
|---|---:|---:|---:|---:|---:|---:|---:|
| sync / 1 | 9.38 | 10.34 | 5.78 | 5.66 | 3.36 | 0.015 | 3.05 |
| sync / 8 | 58.06 | 71.15 | 51.81 | 51.70 | 3.82 | 0.019 | 3.44 |
| async / 1 | 9.16 | 9.84 | 5.56 | 5.45 | 3.38 | 0.015 | 3.08 |
| async / 8 | 49.39 | 82.45 | 30.40 | 30.26 | 5.76 | 0.020 | 5.35 |

此负载下没有连接池等待占主导的证据，不据此扩大池。async / 8 的逐请求平均差值为：
客户端在 handler 外约 18.99ms；SDK 调用在 Flask 应用外约 24.50ms；handler 的其他
处理约 0.15ms。差值混有调度、编码、传输、应用前排队和计时区间外日志写入，不能直接
命名为网络或队列瓶颈。连接持有也不是纯 SQL 时间。

两种模式的 P95 都未达到候选 50ms 目标，继续保持最大 8 并发。
固定 sync→async 顺序、暖缓存且未反向确认，观测本身的开销未隔离，不能与上一轮
未开启计时的数值组成严格因果对照。网关队列未测；引用密集 State、范围检索、混合负载、
持续过载和租户公平性尚未验收。本轮不授予服务 SLO 或记忆语义效果 PASS。

## 回归、失败记录与清理

Runtime 完整真实 PG 回归首跑为 **972 passed / 1 failed / 1 skipped**。失败是新增测试
依赖 pytest caplog，而 Alembic 初始化重配日志后未被捕获；真实 INFO 计时已输出。
原日志 `runtime-regression.log` 和原测试 `failed-test-request-timing.py` 保留。
修正为测试自己的局部日志 handler 后，仅重启本轮 PG 补跑：

- `pytest -q tests/integration/test_request_timing.py`：1 passed。真实池等待、获取超时、
  同线程后续请求无计时上下文泄漏、脱敏和默认关闭路径均通过。
- `pytest -q tests/integration/test_context_chat_api.py::test_composite_capsule_compiles_through_shipped_task_controller`：
  加入已发布 SDK/OpenWorker 包的 PYTHONPATH 后 1 passed，覆盖原可选包缺失跳过项。

修正仅改测试捕获，不改运行源码；没有重跑完整 Runtime 套件，不能写成一次完整绿灯。
池耗尽沿用现有通用 500 返回，本轮只确认计时，不将它当作明确背压/过载验收通过。

MCP 完整套件 169 passed / 1 默认 PG skip；本轮直接 PG 生命周期另跑 1 passed，
涵盖并发绑定、CAS、回放、SESSION 来源资格和撤权。Lab `uv run pytest -q` 为 264 passed。
Runtime `uv run ruff check src tests migrations`、`uv run mypy`、`uv build`，
MCP 对应 Ruff/mypy/build，Lab boundary、Ruff、mypy/build 均通过。
Lab 六项新回归保证缺失、重复、嵌套获取、错误和负时间差不被伪装为可分解成功记录。

原服务和补跑的 PG 都已停止，数据保留；`cleanup.json`、`timing-followup.json` 确认
本轮无存活服务/容器。公共 MCP、共享 vLLM 未触碰。详细关联在 `timing-summary.json` 和
`timing-correlated-rows.json`，检查与命令记录在 `final-checks.json` 和补跑日志。

下一步仅针对已定位的应用外耗时核查调度与传输，或推进既定 P2 保存/加工隔离；
不预先扩池、升并发或新增监控平台。P1/D3 整体仍未完成。
