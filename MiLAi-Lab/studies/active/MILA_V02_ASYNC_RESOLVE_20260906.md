# MILA-V02-05：范围resolve异步接入与单并发负结果

状态：`ASYNC_OVERLAP_AND_BINDING_CONFIRMED / SINGLE_CLIENT_P95_MISSED`。
Codex-full范围resolve已不再经过同步SDK执行锁；受控重叠、逐请求身份及真实PG生命周期
得到验证。同条件性能确认并发1首轮P95为324.034ms，触发300ms停止线，并发8未进入。
不能宣布并发性能改善或完整P1通过。

## 实现与职责边界

`integrations/mcp/src/milai_mcp/server.py`复用既有lifespan，使用`AsyncExitStack`管理独立的
Working State和reader异步客户端。Codex-full CLI为resolve提供reader凭证客户端；每次调用
在当前认证Context中推导Host binding，作为本次SDK请求的参数传入，不放到共享客户端属性。
作用域、预算、previous_context_id、解释及呈现仍走原有代码。没有新Reader、Hint、State实体
或额外语义处理。

resolve的公共轻量/可配置函数改为async，共用原错误和呈现路径。嵌入式`build_server`若
未提供`resolve_client_factory`，通过线程池调用原同步role client；该兼容路径仍受同步锁约束。
本轮优化默认覆盖Codex-full公开CLI，不宣称其它所有适配器均获得异步性能。
`--working-state-transport`继续只控制State，不改变resolve选择。

Async客户端在服务循环中创建、使用并关闭；正常错误映射保留，取消释放当前异步请求且不
取消同客户端中的另一个查询。取消不能证明远端没有完成读取或审计，也不会隐式重试。
没有改变API/schema、认证规则、权限、撤销、Canonical、CAS、事务或自动重试规则。

## 机制检查与真实PG

新增5项控制，结合原State异步控制共13项通过：

- 两个HTTP认证凭证经原Bearer校验与Request Context进入同一ASGI服务，在受控Runtime
  传输屏障中必须同时到达才返回；分别验证Host digest、项目scope、查询及续查参数。
- 公共resolve仍只有query/previous_context_id；注入ctx或scope被拒绝。
- 403、503和续查409保持原公开结果，检查实际请求次数为1。
- 取消一个阻塞查询时另一个继续；两次新事件循环中的客户端分别创建/关闭，未复用已关闭池。

这是受控机械验证，不把mock耗时算作性能。初版测试出现无端口Host不符合现有安全规则、
复用的简单stub缺少SDK必需intent/requirement字段，以及预期digest误用了紧凑JSON的问题。
修正测试夹具后通过，未修改运行时安全/摘要/响应校验来适应错误夹具。中间失败不算产品通过。

MCP完整175通过、默认跳过的真实PG生命周期另跑1通过（10.34s）；该Product测试创建新的
隔离数据库，覆盖真实HTTP角色路由、两用户/两项目、保存/恢复及撤销。仅复用已停止的自有
PG容器，不复用测试数据库，不属于Lab黑盒效果。记录在
`artifacts/v02-e2e-generality/p1-async-resolve-check-20260906a/`。

MCP Ruff/mypy（12文件）/build通过；Lab309通过（2.54s），边界/Ruff/mypy/build通过。
Runtime与SDK源码未改，未把上轮回归计作本轮新执行。

## 同条件公开接口运行

新锁`data/locks/v02-async-resolve-product.lock.json`；当前源码pin
`f8e378c86b31416ae5bc0fa7b82208b35fdea4d065052665799f8719a3a2517a`，锁digest
`d0ec713dfff9ca44371bb0cfd79432cbccf05fc5afff4d888f145b26e779dfc1`。
当前E2E/SIM02候选跟随新锁，历史配置和结果保留原pin。

```bash
uv run python tools/check_v02_e2e_live.py --service-calibration --config configs/v02-scoped-recall-async-resolve.json --root artifacts/v02-e2e-generality/p1-scoped-recall-20260906d
```

保留1000个来源、两项目各500、512/2048/8192字节完整正文、原上下文预算及范围控制；
PG 2 CPU/1 GiB、2核affinity、API/池最大8，预置并发4，计划读取档位1/8不变。
全部1000个来源请求hash与c相同，完整工具catalog相同；首个公开结果只规范化新Evidence ID
和context_id后完全相同。没有删首尾、改变表示或移除权限检查。

范围控制全部成立；并发1首轮24读全部返回合法但预算受限的视图，P50/P95/P99分别为
265.424/324.034/342.265ms，完成吞吐3.645/s。触发冻结停止线，未运行后两轮或并发8，
没有为取得并发结果放宽单并发门。

本轮27次MCP调用：25预算受限视图、1外项目MISS、1伪造scope预期拒绝。SDK预置/就绪等
1021次物理请求；Runtime共1053次HTTP（1000个201、53个200，包含辅助及异步客户端初始化
请求）。层次不相加。新增模型生成、Provider tokenize和模型分配均0。

Runtime26次resolve的application P50/P95为218.706/278.391ms；连接持有之和P50/P95为
44.247/49.846ms，池获取之和最大0.181ms；连接外剩余区间P50/P95为171.616/233.999ms。
这些仍为Runtime自身分布，没有与不含Runtime请求ID的MCP结果强配，也不能将剩余区间
全部视为CPU耗时。

## 收尾与下一步

自有API/worker/MCP进程已核实不存在；性能PG及补跑用PG均停止，数据保留，共享服务未改。
Schema保持`NO-GO FOR SCHEMA FREEZE`，没有迁移或部署。

本轮证明可重叠的异步读取及身份保真，没有证明服务SLO改善。单请求开销仍接近门槛，下一步
在Product自身固定输入或既有公开回放入口剖析完整resolve路径，先确认实际工作分布；不能
将上轮50窗口局部编译耗时直接当作真实请求全部开销。暂不扩大负载或追加计时平台。
完整P1/P2/P4和D4/D5仍未完成，Goal保持进行中。
