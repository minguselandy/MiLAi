# MILA-V02-05：事务身份设置合并

状态：`CONTEXT_ISOLATION_AND_C1_CONFIRMED / C8_P95_MISSED`。

## 定位与决策

本轮读取g保留的98次Runtime resolve计时，先对每个请求计算
`held_body = connection_hold - transaction_enter - transaction_exit`，再求分位数。
不使用P95直接相减，也不将Runtime记录与无request ID的MCP结果按顺序强配。

| Runtime区间 | P50 ms | P95 ms |
| --- | ---: | ---: |
| application | 156.512 | 1172.972 |
| connection hold之和 | 45.139 | 669.168 |
| transaction enter之和 | 1.625 | 95.914 |
| transaction exit之和 | 2.725 | 90.485 |
| 逐请求扣除enter/exit后的持有区间 | 40.881 | 507.743 |
| pool acquire之和 | 0.117 | 60.676 |
| application扣除hold/acquire后 | 107.822 | 591.959 |

各行分布不可相加。持有区间还包括角色校验、GUC设置、业务SQL、Python处理及调度等待，
不是纯PG执行或fsync耗时。原始差分保存在本轮回归目录的
`preserved-transaction-decomposition.json`。

源码在每个有context的事务中分别执行tenant和actor两条`SELECT set_config`。本轮合成
一条参数化SELECT，两个`is_local`仍为true；整条语句成功后才yield连接。两个表达式
互不依赖，不依赖SQL求值顺序。逐事务角色校验仍先执行，没有缓存/跳过角色校验；
read-only/isolation仍在角色校验前，statement timeout仍单独设置。

决策见Product [ADR-045](../../../MiLAi-Product/docs/adr/ADR-045-transaction-local-context-installation.md)。
每个带context的事务减少一个身份设置往返，不合并应用事务、不改变RLS/CAS/提交/重试
语义，不增加连接或资源上限。七次事务不能直接推成节省七次往返，仍应按实际调用确认。
SQL设置成本只是剩余开销的一部分，不把这项修改当成完整根因修复。

## 真实PG控制

新增4项真实PG控制，连同事务计时语义控制16通过（1.32s）：

- 成功、body异常、KeyboardInterrupt取消三种路径下，read-only/repeatable-read事务内
  两项身份均正确；同一PG backend复用前无旧local值，再绑定另一tenant/actor后两值均更新。
  实际SQL spy确认每个有context事务只有一条身份设置语句，参数顺序正确。
- 打开合法API连接后让期望角色不匹配，真实角色SQL校验拒绝，尚未设置任何身份或yield
  业务连接；验证的是逐事务重新校验，不是仅构造时拒绝错误DSN。

测试使用新的自有PG数据库，数据目录
`artifacts/v02-e2e-generality/p1-context-bind-regression-20260906a/`；是Product自己的
工程回归，不是Lab黑盒效果。Runtime完整真实PG1038通过、无跳过（98.92s），Ruff/mypy
（189文件）/build通过；Lab309通过（2.47s），边界/Ruff/mypy/build通过。MCP/SDK源码
未改，未重复其旧全量检查。ADR-045的身份设置不变式由这些直接控制和既有RLS回归支持。

## 公开确认约定

新锁`data/locks/v02-context-bind-product.lock.json`，源码pin
`d9a2fd6df5aa471c2211eaf9aabb237735b8ae92ed810d47b8778f72dacf7fcc`，锁digest
`ba1447c74c0078eb18c121bc31bc94727bada80cd2db8eaf9aef9cd0f9d47b26`。
当前E2E/SIM02候选同步pin，历史配置与失败记录保留。配置
`configs/v02-scoped-recall-context-bind.json`保留1000来源、两项目、完整三种长度、原scope/
预算、1/8并发、三轮各24读、5秒就绪和300ms停止线，以及相同预置并发与资源上限。

```bash
uv run python tools/check_v02_e2e_live.py --service-calibration --config configs/v02-scoped-recall-context-bind.json --root artifacts/v02-e2e-generality/p1-scoped-recall-20260906h
```

公开h的20批就绪及范围控制通过；1000来源请求hash和完整工具catalog与g相同，首个完整
MCP响应只规范化新Evidence ID/context_id后相同。没有缩减文件、来源或呈现内容。

| 阶段 | 读数 | P50 ms | P95 ms | P99 ms | 完成/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| c1-r0 | 24 | 196.698 | 231.571 | 248.086 | 4.925 |
| c1-r1 | 24 | 193.999 | 230.058 | 241.480 | 4.950 |
| c1-r2 | 24 | 193.421 | 227.628 | 230.773 | 4.993 |
| c8-r0 | 24 | 1178.833 | 1306.270 | 1380.639 | 6.452 |

c1均满足300ms线，c8超线后停止后两轮。单并发与g同一量级，c8有所下降但仍远超门槛；
一次同配置批次不能证明所有变化由SQL合并独占导致。MCP99次（97预算受限视图、1MISS、
1预期scope拒绝），SDK1021次，Runtime HTTP1125（201×1000、200×125），各层不相加。

Runtime98次resolve的application P50/P95为158.664/1153.681ms，hold之和为42.729/
618.232ms，enter之和1.564/144.812ms，exit之和2.697/70.198ms。逐请求扣除enter/exit
后持有区间P50/P95为38.580/421.830ms；pool acquire之和最大114.175ms，连接外剩余
109.801/580.923ms。仍只有各层分布，没有新建逐条MCP对应关系。

## 收尾与下一步

自有API/worker/MCP不存在，公开与回归自有PG均经inspect确认停止，数据保留，共享服务
未动。SQL合并和身份隔离成立，完整P1仍未通过。现有局部优化没有改变并发性能量级，
下一步先形成整条普通读取路径的必要工作/事务/输出消费者清单，寻找能显著减少每次
读取总工作量的方案；不继续每做一项小调整就盲目重跑，也不扩大资源或放宽停止线。

本轮没有API/schema/权限语义变化，无迁移或部署；源码回退即可恢复两语句，不需数据转换。
Schema保持`NO-GO FOR SCHEMA FREEZE`。新增模型/Provider tokenize均0，完整P1/P2/P4
及D4/D5未完成。
