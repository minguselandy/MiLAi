# MILA-V02-05 P1：Working State 异步传输增量

状态：`ASYNC_STATE_CORRECTNESS_VERIFIED / MCP_P95_TARGET_NOT_MET_AT_8`。
新增模型请求和生成 token 为 0；P1/D3 整体未通过，D4/D5 未进入。

## 实现与边界

`codex-full` 的 Working State GET/UPDATE 现在使用服务 lifespan 创建、关闭的单个
`AsyncMilaiClient`，连接始终在所属事件循环使用。请求从可信 MCP context 取得身份并形成
完整 binding；客户端不维护共享“当前主体/任务”。Runtime 继续负责 CAS、幂等、引用资格和
持久化。公有工具仍为 13 个，参数/正文/版本和非 Canonical 权威不变。

同步与异步 mutation 共用同一审计上下文。取消中的写入记 UNKNOWN，不能当未提交；
冲突、未知结果恢复提示和零重试保持。其他 MCP 工具仍用原角色客户端，本次没有改检索调度。
通用 `milai-mcp --working-state-transport sync` 保留串行兼容路径，默认 async；固定 Codex
入口采用 async、零重试。嵌入式 `build_server` 未传异步 factory 时继续使用调用方的同步客户端。
该传输选择不改变 L1/L2 装配，更不把 State-first 自动提升为产品默认。

改动仅 MCP 集成，无 Runtime/数据库、权限、Canonical 或迁移变化；未发布公网、未提交共享修改。
当前源码 pin：`fd93b919c24965586bf9c71f32b0802fe9349fae4ef568487a1e32fd7908bd12`，
独立 lock 为 `data/locks/v02-async-working-state-product.lock.json`。
原 `baf29…` 基线锁和历史产物保留；关闭的 SIM02 候选与当前工程配置改指新锁，模型额度仍为 0。

六项新增机制回归覆盖：读写在真实 SDK mock transport 中重叠、两次事件循环生命周期分别
创建/关闭、工具 schema 无 Context 参数泄漏、嵌入同步兼容、冲突/未知错误单次尝试，以及
取消写入不取消独立读取且留下 UNKNOWN 审计。它们不证明远端取消后的提交状态。
最初 mock 能力文档遗漏 L1，按兼容合同被拒绝；修正测试能力文档后通过，未放宽产品协商。

## 独占 PG 与相同 State 的 MCP 配对诊断

配置：[`v02-service-async-state.json`](../../configs/v02-service-async-state.json)。
产物：`artifacts/v02-e2e-generality/p1-async-20260906a/`。
沿用前轮两核 affinity、8 API 线程、API/worker 各最大 8 DB 连接、PG 2 CPU/1 GiB。
先公开 SDK 保存 1,000 条 State 并完成 SDK/CAS 基线，再在同一数据库中为 MCP 建立
TASK/SESSION/PROJECT 三条正文分别为 512/2,048/8,192 字节的 State。

两种模式使用同一个当前源码 pin、身份/项目、三个 State 的同一版本、相同 catalog、
零重试、协议 `2026-07-28`、各一个复用的 HTTP/MCP 客户端。每模式预热三个读取，再按
1/8 并发各三轮，每轮 96 次读取；正文和版本逐项相同，catalog 完全一致。
同步模式 582 次工具调用（3 保存+3 预热+576 读取），异步模式 579 次，共 1,161 次。
SDK 阶段与 MCP 阶段独立计数；服务初始化、PG 回归和模型成本不混进读取分布。

| 模式 | 并发 | 各轮客户端 P95（ms） | 各轮完成吞吐（次/s） |
|---|---:|---|---|
| sync | 1 | 10.53 / 9.49 / 10.41 | 106.3 / 113.2 / 110.5 |
| async | 1 | 10.16 / 9.41 / 9.92 | 111.8 / 116.6 / 117.1 |
| sync | 8 | 59.28 / 61.01 / 100.16 | 140.0 / 139.9 / 132.8 |
| async | 8 | 64.66 / 91.28 / 71.59 | 171.1 / 155.3 / 173.6 |

8 并发总完成数/三轮总时长为 sync 137.45、async 166.27 次/s，观察到约 21% 增长；
**P95 没有稳定改善，两模式均未达到候选 50ms 目标。** 不提高到 32/128 并发。
这不是旧部署修改前后的严格效果估计：当前代码包含两条兼容路径，固定先 sync 后 async，
仅保证都预热，未证明缓存初态逐项等价或消除时间趋势；没有反向顺序独立确认。
样本短、计时位于客户端、无网关/连接等待分解，因此仍不授予服务 SLO、完整容量或净成本收益。
MCP 负载只覆盖三条无引用 State 的已知作用域读取，不冒充千条范围检索或高引用密度验收。

## PG 失败保留与后续确认

最初 PG 生命周期回归失败于将无来源会话元数据的 Evidence 写入 SESSION State。
既有 `0050_host_cognitive_state` 合同要求该引用的 `source_session_id == scope_ref`，
故 `EVIDENCE_REFERENCE_INVALID` 是正确拒绝；不是删除引用或改为更宽 scope 来通过。
原失败留在 `postgres-regression.log`。

修正测试为先明确 SESSION binding，并保留来源会话不匹配的负控，再通过公开 capture
提供真实一致的 session/turn/round 元数据。只重启本轮已停止的 PG 做一次直接回归，
没有重复性能测量；`postgres-regression-followup.log` 为 **1 passed**。
测试覆盖同 endpoint 两套 Host 凭证并发读写不串用（仍是同一 Runtime actor/tenant），
同 State 同版本仅一方 CAS 成功、幂等不新增版本、来源不匹配拒绝、撤权后 GET 和旧回执
整段 payload 隐藏，另一主体的 State 仍正确；并复用既有重启/Canonical/检索生命周期检查。
原失败配置与 follow-up 测试摘要分别保留，不能把最终通过回填到第一次失败。

前轮报告勘误：`p1-cal-20260906a/mcp-result.json` 的 `runtime_retry_policy: 2` 是加载器
记录错误；实际 `milai-codex-full-mcp` 入口固定 `--max-retries 0`。原 JSON 未改，新增
勘误记录并修正后续加载器字段；历史请求计数和性能数字不变。

## 验证及剩余工作

MCP 全部单元/HTTP检查 168 通过、1 个 PG 生命周期默认跳过；该 PG 项上述独立补跑 1 通过。
MCP Ruff/mypy/build 通过。Lab 258 通过，边界/Ruff/mypy src/build 通过。
Runtime 和 SDK 源码未改，本次不重跑其完整包测试。
清理回执确认独占 API/worker/MCP 退出、PG 停止；follow-up 仅启动自己的 PG，结束后再次停止。
数据和失败保留，共享服务/GPU未变。

下一瓶颈仍未定位到具体服务等待：先补网关/连接等待的可用观测、带引用读取与范围检索，
再做相同固定读取流量下的受限导入；不靠去鉴权、减正文或丢历史换 P95。
P2 outbox/水位与过时任务、P4 公平性/背压尚未完成。模型额度、正式 Host/Provider 和任务
判据仍待满足；不能从本轮推导 Agent 理解、分层收益或泛化。
Schema 继续 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
