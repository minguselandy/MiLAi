# MILA-V02-05 P1：调用等待点与首轮 State 基线

状态：`STATE_CALIBRATION_COMPLETED_NOT_FULL_P1`。新增生成请求/token 为 0。
Product 运行源码未改，pin 仍为 `baf29ec03b264d22fcee0fde238d970ac52a3c106b3ad507159ad991af3a0754`。
本次增加三项 Product 机制回归，以及 Lab 负载配置和公开 SDK 负载器。
暂停时留下的来源分叉接入已有 8 项单元检查通过，完整 G/A/B 编排仍未验证。

## 已定位的等待点

| 入口/层 | 直接证据 | 结论与边界 |
|---|---|---|
| MCP 调度→同步 handler | 两次工具读取必须在同一 Barrier 会合；TASK/SESSION 分别匹配，额外 project 参数被拒绝 | 锁定 MCP 2.0.0 的调度允许独立 handler 重叠 |
| 共享 `MilaiClient`→`_run` | 首次 mock HTTP 阻塞，第二线程已调用但不能发送；释放后正确返回 | 实例 `RLock` 覆盖完整 `run_until_complete`，同一 submitter 的 GET/UPDATE 排队；不能直接删锁 |
| `AsyncMilaiClient`→复用 `HttpxAsyncTransport` | 两请求在任何一次释放前都进入传输；取消第一项后第二项按原绑定完成 | 现有异步 SDK 可重叠；mock 不证明服务延迟 |
| Runtime Waitress→PG pool | 初始化锁只覆盖 open；事务内绑定 tenant/actor、归还连接 reset | 当前公开 State 回执不暴露 pool wait/网关计时，内部等待保持未知 |

实现入口为 Product `integrations/mcp/src/milai_mcp/server.py`、
`integrations/python-client/src/milai_client/client.py`、`runtime/src/milai/persistence/database.py`。
新增回归为 `test_working_state_concurrency.py` 两项、`test_codex_full_profile.py` 一项。
本次没有修改生产 MCP 异步路径。下一增量须处理客户端事件循环归属和关闭生命周期，
复测相同负载，不能先宣称优化收益。真实基线仅一个 Runtime actor/tenant，不代表跨租户验证。

## 冻结配置与实测

配置：[`v02-service-calibration.json`](../../configs/v02-service-calibration.json)。
配置、源码摘要、逐请求事件、HTTP 尝试、回执、资源采样及清理位于
`artifacts/v02-e2e-generality/p1-cal-20260906a/`，不进入 Git。

独占 API/worker/PG；API 8 线程，API/worker 各最大 8 条 DB 连接。
API/worker/加载器继承两核 affinity；PG 限额 2 CPU/1 GiB，镜像身份在 `deployment.json`。
复用已有 bridge，端口只绑定 loopback，旧容器/卷及共享服务未改变。
SDK `milai-client 0.1.0` / `httpx 0.28.1`；MCP `2.0.0` / `milai-mcp 0.1.4`。

容量材料是 1,000 条 **Working State**，不是 Evidence。两个 Host binding、两个 project，
正文轮换 512/2,048/8,192 字节，无来源引用，不代表高引用密度或检索容量。
四并发初始化保存；读取复用异步客户端，数据库已暖，每档三轮，每轮 96 次。
两档读取相同的首 288 个 State；热点竞争后为 v2，其余 v1，返回正文和版本逐项核对。
计时从实际调用开始，是闭环负载，不是固定到达率测试。

| 路径 | 数量 | 客户端 P95 | 完成吞吐 |
|---|---:|---:|---:|
| 保存，4 并发 | 1,000 | 25.16ms | 未单列保存阶段吞吐 |
| GET，1 并发 | 3 × 96 | 各轮 6.38 / 5.77 / 5.54ms | 184.7 / 201.8 / 203.9 次/s |
| GET，8 并发 | 3 × 96 | 各轮 37.05 / 34.80 / 32.02ms | 362.4 / 351.9 / 360.5 次/s |

SDK 共 1,583 次物理 HTTP 尝试：能力协商 1、保存 1,000、负载读取 576，以及
身份负控/热点初读/两次竞争/直读/回放共 6 次。重试为 0；唯一 HTTP 错误是预期 CAS 409。
SDK 阶段约 6.34 秒，不包含初始化及后续 MCP 检查。没有网关接收时间、连接等待观测或
足够长的稳态负载，**不授予服务 SLO 或完整 P1 PASS**。

同 State/expected_version、不同 operation ID 同步起跑，恰好一个 v2 提交、一个
`STALE_WORKING_STATE`；直读版本与获胜回执一致，同 ID 回放不新增版本。
不同 principal binding 用相同 task 字符串读取返回 ABSENT。State 搜索索引记 N/A，
不能把此闭环当 Evidence 投影就绪证明。

真实 HTTP MCP 保存 TASK/SESSION 两条 512 字节正文，再以两并发读取各三次，共 8 次
工具调用，正文/版本匹配。六次读取 50.06–66.96ms；每次新建 legacy MCP 客户端，包含
握手。后续核查固定入口 `codex_full.py` 确认重试为 **0**；初版报告及原始
`mcp-result.json` 中的 2 是记录错误，原件保留，修正见后续异步报告。
此检查未提供逐物理尝试账本，不能与 SDK 延迟相减归因。
14 次采样中 API/worker RSS 峰值 82.82/64.65 MiB；不是 PG/整机峰值。CPU/IO 原始样本
保留，PG 运行时采样和卷容量未覆盖。零模型请求不表示零工程成本。

## 未完成出口与验证

P1 仍缺引用密度、范围检索、真实多主体凭证隔离、复用 MCP 连接的等价基线和读+受限导入。
P2 的 outbox/水位、重启、旧投影晚到未由本次覆盖；32/128 并发、过载和公平性未运行。
下一项先测复用 MCP 连接的调用链并接通最小异步读取路径，再在相同条件下比较。
完整 LME、SIM01 账本及表示变体记录保留，不删首尾字段或来源以争取性能。

SDK `pytest -q` 177 通过；MCP 162 通过、1 项 PG 生命周期默认跳过。本次独占公开 PG 链
不冒充该跳过项补跑。两包 Ruff/mypy/build 通过。Lab 258 项通过，边界/Ruff/mypy src/build
通过。Runtime 实现未改，未重跑完整 Runtime 测试。没有 API/schema/权限/Canonical 语义
改变，无迁移、部署或提交。清理确认 API/worker 无存活进程、PG 停止、临时 MCP 退出。
数据保留；Schema 仍为 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
