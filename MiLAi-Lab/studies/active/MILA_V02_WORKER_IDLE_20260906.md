# MILA-V02-05：积压轮次取消固定轮询等待

状态：`READINESS_AND_C1_CONFIRMED / C8_P95_MISSED`。

## 失败证据与最小修复

上一轮e的投影就绪在5秒停止线处失败。读取保留的worker累计阶段计时后确认：失败前两个
完整忙碌cycle各处理1024个投递；后一轮日志间隔6899.586ms，非嵌套阶段增量分别为lease
2887.735ms、skip1541.843ms、Evidence batch1132.439ms、水位reconcile306.007ms、
ping1.156ms，共5869.180ms。源码每轮后另有固定1秒轮询等待；阶段时间不能再加其中嵌套
的Evidence write时间。前后日志并非完整调度trace，未将剩余约30ms进一步归因。

`runtime/src/milai/workers/main.py::FoundationWorker.run`现在只在`run_once()`返回0时等待
原`worker_poll_interval_seconds`。有处理结果时继续下一有界cycle；每次循环先检查停止
标志。`--once`、每投影256事件上限、32批大小、evidence/purge/fts/vector顺序、租约、
失败重试时刻、最大尝试数和水位推进算法不变，没有增加线程、连接、CPU/内存额度。

这消除已确认的主动等待，未解释或消除lease/skip的全部耗时，也不是将e追认为成功。
持续积压时worker会更连续地使用既有资源，混合读写竞争仍需原P4门验证；不以新调度
能力代替公平性、网关SLO或公开延迟收益。API/schema/权限/Canonical/事务语义不变，
无迁移或新实体；Schema保持`NO-GO FOR SCHEMA FREEZE`。

新增3个确定性控制：两个忙碌cycle后只有空闲cycle等待；活跃cycle内收到停止后不再
启动下一轮；启动前已停止不处理。结合原worker、路由、批次和配置控制18通过（0.80s）。
Runtime Ruff/mypy（189文件）/build通过；Lab309通过（2.67s），边界/Ruff/mypy/build通过。
Runtime真实PG完整回归1022通过、无跳过（103.13s），包含worker租约/投影/撤权等既有
回归；使用新自有数据库，并预先提供SDK路径。MCP/SDK源码未改，未重复其上轮全量检查。

原始阶段差分和本轮Product回归记录位于
`artifacts/v02-e2e-generality/p1-worker-idle-regression-20260906a/`。
差分只读取d/e保留日志，没有启动旧环境或修改旧失败结果。

## 公开确认约定

新锁`data/locks/v02-worker-idle-product.lock.json`；源码pin
`0fe5f7cf08ee3ea2a6d5813dee56aa3726508314cc4fce3cc06fd4aa0e345027`，锁digest
`17f0724b21d666693e7cff2a7f7576c17f7ea51ff752e3ec284d8bffb148e5e1`。
当前E2E/SIM02候选同步pin，历史锁和配置保留；没有模型授权变化。

`configs/v02-scoped-recall-worker-idle.json`保持1000来源、两项目、完整512/2048/8192字节
正文、预置并发4、读取1/8、三轮各24读、300ms停止线、就绪5秒、原scope/预算和资源上限。
新运行只在修复后验证，不作为原失败的隐式重试，不改变原停止线或追加补跑。

```bash
uv run python tools/check_v02_e2e_live.py --service-calibration --config configs/v02-scoped-recall-worker-idle.json --root artifacts/v02-e2e-generality/p1-scoped-recall-20260906f
```

20批就绪检查全部通过，范围正例、外项目MISS、伪造scope拒绝成立。1000来源请求hash、
完整工具catalog与d相同；首个完整MCP响应仅规范化新Evidence ID/context_id后与d相同。
两次产品改动间e未能进入读取，所以不能用d→f差异分离日期复用和worker调度各自的服务收益。

| 阶段 | 实际读数 | P50 ms | P95 ms | P99 ms | 完成/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| c1-r0 | 24 | 230.587 | 271.038 | 284.990 | 4.194 |
| c1-r1 | 24 | 225.441 | 274.508 | 278.191 | 4.280 |
| c1-r2 | 24 | 221.817 | 252.387 | 272.018 | 4.335 |
| c8-r0 | 24 | 1430.990 | 1724.674 | 1830.192 | 5.307 |

c1三轮均满足300ms线；c8首轮超线后停止后两轮，没有升档或增加资源。共99次MCP工具调用：
97个合法但预算受限的视图、1个MISS、1个预期scope拒绝；不将预算受限标为完整语义答案。
SDK预置/就绪1021次，Runtime HTTP1125次（201×1000、200×125），层次不相加。

Runtime自身98次resolve的application P50/P95为194.455/1540.886ms，连接持有之和
P50/P95为43.749/666.207ms，池获取之和最大93.813ms，连接外剩余区间P50/P95为
147.984/901.911ms。MCP结果无Runtime request ID，仍只报各层分布，不按顺序强配或减P95。
连接持有包含事务内Python/等待，剩余区间也不等于纯CPU，不能仅据这些值断定PG或GIL根因。

## 收尾与下一步

公开API/worker/MCP已核实不存在，公开与回归自有PG均经docker inspect确认停止，数据保留。
共享服务未动，无部署或迁移。正常轮询修复成立，本轮就绪和c1通过，仍没有完整P1通过。
下一步使用已保留的逐请求计时和资源采样定位8并发Runtime放大，再按需要做有界Product
内部验证；不增加并发/连接或默认增设缓存。worker持续积压时的混合负载影响仍归P4验证。

新增模型生成、Provider tokenize均0，完整P1/P2/P4及D4/D5尚未完成。
