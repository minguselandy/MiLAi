# MILA-V02-05：MCP外部长尾定位到handler入口之前

状态：`PRE_HANDLER_TAIL_LOCALIZED / MIXED_STOPPED_AT_IMPORT_CAPACITY`。
400次读取、48次导入完成；mixed首轮另有2次计划导入被客户端容量拒绝，因此停止后续轮次。
读取P95满足目标不能抵消拒绝。新增实验模型生成及Provider tokenize均0，完整服务门仍未通过。

## 最小实现与时钟边界

之前只能计算客户端调用减handler总耗时，无法区分等待发生在入口前还是返回后。
本次在既有默认关闭的[公开计时合同](../../../MiLAi-Product/docs/contracts/MILA_REQUEST_TIMING_V1.md)
中增加可选的`handler_start_monotonic_s`及`handler_end_monotonic_s`，Working State GET/UPDATE
使用同一monotonic时钟计算对应时长。它们只出现在日志，不进入工具结果、Memory正文或新工具。
未知写入、鉴权、CAS及正文披露路径保持原规则。

跨进程分段不是默认可信：Lab验证本机boot身份摘要和MCP/负载客户端time namespace，
客户端开始/结束时钟身份必须一致。缺失、时钟未证实、时间顺序不一致或时长不符均保持未知，
不将负值钳成0，也不把这种验证推广到远端主机。两臂此次均验证成功。

边界含义：客户端调用开始→handler入口，包含客户端准备、传输、框架派发和参数处理；
handler结束→客户端调用完成，包含计时日志、框架编码、传输及客户端处理。
二者都不能直接叫网络延迟或服务器队列等待。

当前Product pin：`13999df2432148b9ec9cd2580164f3cae70ee2875b70a2a8dff316f5a0b3ce46`，
锁`data/locks/v02-mcp-boundary-timing-product.lock.json`。
当前工程和未启用SIM02配置指向新锁；历史配置/源码身份不覆盖。

## 冻结执行与停止

配置：`configs/v02-mcp-boundary-timing.json`。
产物：`artifacts/v02-e2e-generality/p1-mcp-boundary-20260906a/`。

```bash
uv run python tools/run_v02_mixed_pair.py --config configs/v02-mcp-boundary-timing.json --root artifacts/v02-e2e-generality/p1-mcp-boundary-20260906a
uv run python tools/summarize_v02_mixed_timing.py --root artifacts/v02-e2e-generality/p1-mcp-boundary-20260906a
```

保持此前1000条State、三份完整来源、同catalog及12次预热；三轮各5秒，读取20/s、mixed
导入10/s，客户端上限6读+2导入，PG 2 CPU/1 GiB，API线程/池最大8，零重试。
继续相同GC/cgroup观测，未扩大负载或删正文首尾。部分运行停止后仍单独核对两臂实际来源
输入hash、引用映射后的活动State和catalog相同，结果保存在`final-observation.json`。

| 已进入部分 | 读取完成 | 读取计划至完成P95 ms | 导入情况 |
|---|---:|---:|---|
| baseline第1轮 | 100 | 12.581 | 无计量导入 |
| baseline第2轮 | 100 | 12.669 | 无计量导入 |
| baseline第3轮 | 100 | 12.159 | 无计量导入 |
| mixed第1轮 | 100 | 15.490 | 50计划，48发送并完成，2客户端拒绝 |

mixed拒绝项index=34/35各已有2条导入在途；它们没有dispatch或Runtime回执，不是服务端503。
48次完成导入的P95/P99为34.082/394.453ms，拒绝另列，不混入成功时长分布。
按冻结条件停止mixed剩余两轮，未重试或自动另起一批；完整三轮两臂比较未完成，不计算
一个可授予通过的整批退化结论。48个已保存目标完成既有readiness和公开GET核对。

SDK物理调用2107、MCP工具430、Runtime HTTP日志2549（含辅助请求），三层不相加。
预置/预热包含正常保存；“48导入”仅指已进入的计量导入。Product回归和初始化成本另列。

## 本次分段证据

400/400实际读取均完成唯一Runtime/MCP关联和时钟分段一致性检查：

| 调用 | 客户端调用 ms | handler前 ms | handler内 ms | handler后 ms | 客户端GC交集 ms |
|---|---:|---:|---:|---:|---:|
| baseline最大外部等待 | 51.368 | 42.394 | 7.012 | 1.962 | 0 |
| mixed最大外部等待 | 55.927 | 46.488 | 7.126 | 2.313 | 0 |

由此把本次两条外部长尾定位到handler入口之前。baseline对应PG容器包围窗口没有I/O压力
或自身CPU限流增量；mixed窗口I/O压力约2.184ms，不能解释其46.488ms的入口前耗时。
仍不能区分客户端发送、传输、服务器框架派发、参数处理或服务端GC，不能据此改Socket、
关闭GC、增加线程或宣称具体协议故障。下一步应复用实际HTTP/框架观测继续核查入口前区间。
历史没有起止时间戳的轮次保留原归因，不追填本次分段结果。

## 回归、影响与收尾

MCP局部8通过；完整170通过/1默认PG跳过（13.49s），直接PG生命周期另跑1通过（10.02s）。
后者由Product自身夹具创建/清理独立测试数据库，Lab没有写私有表。MCP Ruff/mypy/build通过。
Lab局部计时控制15通过，完整 **293 passed（2.42s）**，边界/Ruff/mypy/build通过；
新import排序问题修正后Ruff通过。Runtime/SDK源码未改，未重复其全套并冒充新验证。

三个当前配置pin均匹配；两臂API/worker/MCP进程核实不存在，自有PG和回归服务停止，
数据保留，共享服务未触碰。无API响应或Schema/权限/Canonical/事务语义改变，无迁移/部署。
回退仅移除可选时间戳，旧日志仍支持相对时长分析；Schema保持`NO-GO FOR SCHEMA FREEZE`。
网关SLO、公平性、持续负载及端到端语义效果仍未验证，P1/P2/P4仍PARTIAL，D4/D5未进入。
