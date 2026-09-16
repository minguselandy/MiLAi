# MILA-V02-05：事务退出长尾定位与同上限混合负载诊断

状态：`TRANSACTION_EXIT_TAIL_LOCALIZED / P1_P2_P4_PARTIAL`。
本次600次读取、150次导入均完成，客户端候选门满足；历史混合负载退化失败仍保留。
这是一次诊断运行，不是计时改动的性能收益对照。新增实验模型生成及Provider tokenize均0。

## 具体失败与最小改动

历史读取长尾已排除“主要耗在取连接排队”的解释，但连接持有仍混合多个步骤。
对历史事件重新关联后，几条相隔约50ms发送的读取在不到1ms内集中完成；500ms粒度的
API/worker资源采样缺少PG等待事件与线程调度，不能由此认定SQL、WAL、磁盘或CPU根因。
源码确认`HostCognitiveStateRepository.get_current`会在读取后写访问审计，读取包含事务提交。

复用默认关闭的[公开计时合同](../../../MiLAi-Product/docs/contracts/MILA_REQUEST_TIMING_V1.md)，
增加可选的事务进入、退出耗时和次数；退出包含commit/rollback及失败，不是提交成功回执。
它们嵌在连接持有内，不能重复相加。旧日志继续有效，缺失字段不当0。
Runtime只包装驱动已有事务上下文，原异常、取消、回滚和异常抑制仍交给同一驱动处理。
关闭计时时仍直接使用原事务上下文；不删除审计、不修改持久化设置、不扩池或扩线程。

当前Product pin为`38b43df09b2bd872fe6112cb1787b5247cd28d2896ac70fb595c13002536f342`，
锁为`data/locks/v02-transaction-timing-product.lock.json`。
Lab扩展原关联器，新增`tools/summarize_v02_mixed_timing.py`读取公开日志；
原负载入口增加`--config`，历史配置和执行源码锁保留。

## 冻结诊断及实际结果

配置：`configs/v02-transaction-timing.json`。
运行：`uv run python tools/run_v02_mixed_pair.py --config configs/v02-transaction-timing.json
--root artifacts/v02-e2e-generality/p1-transaction-load-20260906a`（换行展示，实际为一条命令）。
分析：`uv run python tools/summarize_v02_mixed_timing.py --root
artifacts/v02-e2e-generality/p1-transaction-load-20260906a`。

保持上次上限：两臂独立服务、1000条State、三份512/2048/8192字节来源，相同完整产物、
引用映射后的活动State及catalog；每臂预热12次，三轮各5秒、读取20/s，mixed导入10/s。
客户端上限6读+2导入，API线程/池最大仍8，PG 2 CPU/1 GiB，零重试。实际读取仍只覆盖
TASK/SESSION/PROJECT三个活动State，不冒充1000条范围检索。两臂按baseline→mixed执行。

| 轮次 | baseline读取P95/P99 ms | mixed读取P95/P99 ms | P95比值 |
|---|---:|---:|---:|
| 1 | 13.73 / 146.33 | 16.60 / 20.75 | 1.2095 |
| 2 | 14.52 / 14.98 | 15.33 / 16.47 | 1.0558 |
| 3 | 12.65 / 14.44 | 16.23 / 17.51 | 1.2826 |

均满足本次冻结的客户端P95≤50ms及逐轮比值≤1.5，结果为
`CLIENT_MIXED_BOUNDARY_MET_NOT_GATEWAY_SLO`。没有拒绝、超时、错误、正文或版本不一致。
150个导入目标在各轮后完成既有readiness确认并公开GET核对内容hash；不是逐写索引延迟SLO。
SDK物理调用1005+1308、MCP工具630、Runtime HTTP日志1326+1629（含辅助调用），
三层数字不能相加。初始化、健康检查和Product回归另属工程成本。

600/600读取唯一关联，并都有两项事务边界计时：

- baseline最慢客户端调用173.056ms；连接持有166.204ms，其中事务进入0.214ms、
  退出164.426ms，剩余连接工作1.564ms，取连接仅0.035ms。
- 随后的两条长尾分别145.115/99.075ms，事务退出132.780/84.995ms。
- mixed最慢调用67.778ms；MCP handler外56.687ms，应用7.411ms、事务退出1.648ms。

这把本次一组长尾定位到了事务退出段，另一组仍在MCP handler外。退出墙钟包含驱动、
网络、PG提交及调度，不能直接称磁盘fsync耗时。不能删除访问审计、关闭同步提交或放宽
持久化语义来取得更好数字。下一步应针对提交等待和MCP调度/编码边界取得证据。

历史首次退化57.15%的失败不被本轮覆盖。本轮Product包含后续容量边界及新增观测，
未做旧/新实现配对；宿主机时变、顺序与观测开销未隔离，不能归因为优化生效。

## 入口核查、回归和收尾

安装的Waitress 3.0.2源码显示：Product入口只设置host/port/threads及代理头处理；
依赖默认connection_limit=100、backlog=1024、lookahead=0。调度队列在Flask及数据库
获取之前，不能用有界DB等待证明HTTP入口延迟、公平性或立即503。
这些是依赖源码事实，不是实际网关容量/多租户测试，也不据此新增公平调度平台。

Product回归产物：`artifacts/v02-e2e-generality/p1-transaction-check-20260906a/`。
12项局部控制测试覆盖开/关计时的提交、回滚、取消、异常抑制、进入失败、退出失败。
初始直接PG检查为1通过/2失败，原因为新测试缺少RuntimeSettings必需字段；修正后
3通过（1.84s）。完整Runtime为997通过/1跳过（97.93s）；该跳过因OpenWorker导入路径
漏了`src`，修正运行环境后仅补该用例，1通过（2.56s），未重跑整套或隐藏跳过。
保留初始日志；两次新测试行宽错误在Ruff中发现并修正。

Runtime Ruff/mypy/build通过；Lab272测试（2.37s）、边界/Ruff/mypy/build通过。
SDK/MCP源码未改，不冒充本轮重跑其全套单元回归；真实MCP读取/保存由本轮服务链覆盖。
三个当前工程/候选配置pin匹配。回归及负载自有服务均停止，负载API/worker/MCP进程
核实不存在，PG停止且数据保留；共享服务未触碰。

无API响应、Schema、权限、Canonical或事务语义变更，无迁移/部署。
回退只移除可选观测字段，分析器仍接受旧日志；Schema保持`NO-GO FOR SCHEMA FREEZE`。
完整网关SLO、持续负载、租户公平性及语义效果仍未验证，D4/D5未进入，Goal继续进行。
