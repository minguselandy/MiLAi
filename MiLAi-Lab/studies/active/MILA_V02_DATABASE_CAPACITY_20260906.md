# MILA-V02-05：数据库等待边界与错误确认

状态：`DATABASE_ADMISSION_SUBSET_VERIFIED / P4_PARTIAL`。本轮没有扩大到达率或并发，
没有新增实验模型生成或Provider tokenize调用；上一轮混合负载退化门未通过的结果保留。

## 从已确认失败到实现

此前直接PG计时测试已确认：池获取超时在Working State接口返回通用500。检查当前实现后，
发现连接数和等待时间虽有上限，但psycopg_pool使用默认`max_waiting=0`，等待人数无上限。
本次复用池自身的队列限制，不添加全局Semaphore、数据库实体或新的Memory模块。

Product [ADR-044](../../../MiLAi-Product/docs/adr/ADR-044-bounded-database-acquisition.md)规定：

- Runtime及worker增加`MILAI_DATABASE_POOL_MAX_WAITING`，默认32，可设1–1024；0被配置
  校验拒绝。API、Steward、worker仍分别使用原有独立连接池，每个池应用自己的队列上限。
- 仅在请求获取连接时，将队列满和获取超时区分为`POOL_QUEUE_FULL`与`POOL_WAIT_TIMEOUT`。
  未由具体应用路径转换的错误返回503、`DATABASE_CAPACITY_EXCEEDED`及既有error envelope。
  已有读取路径若将DatabaseUnavailable转换成安全的abstention，继续保留原合同。
- 获取失败不能证明整个HTTP请求从未提交其他事务，也可能已写入未引用Blob。它不是
  NOT_COMMITTED回执。SDK重试配置不变；本Goal和固定Codex入口仍为0，MCP写入结果保持
  UNKNOWN，显式重放与当前head查询仍分开。

没有SQL schema、Canonical、权限、身份或事务过程变化，无迁移/公网部署。
成功响应不变；回退会取消本次队列限制和错误分类，不能保留更强的背压承诺。
Schema仍为`NO-GO FOR SCHEMA FREEZE`。

当前源码pin：`14521655c92bc00d5a0867d76b85ef5fc0b9958875fc484d467c5177a413e4d6`，
独立锁为`data/locks/v02-database-capacity-product.lock.json`。当前工程配置及尚未启用的
SIM02候选改指新锁；历史混合负载配置与原始e5dc1daf…运行证据不覆盖、不追认为新实现效果。

## 直接PG证据

运行配置为`configs/v02-database-capacity.json`，产物目录
`artifacts/v02-e2e-generality/p4-capacity-20260906a/`。配置只用于工程准备和Product自身回归，
不是新的黑盒效果臂；Lab没有直接读取或写入私有SQL。
自有PG限制2 CPU/1 GiB，bridge网络，先停止准备用API/worker，再运行Product fixture。

`pytest -q tests/integration/test_database_capacity.py tests/integration/test_request_timing.py`
为 **2 passed（2.14s）**：

1. 实际池限制1连接/1等待者，持有连接并让一条读取排队；下一条State写入在等待超时前
   返回503/POOL_QUEUE_FULL。无效凭据仍先得到401，响应没有凭据、正文或作用域泄漏。
2. 同时独立Steward池可用，事务中的tenant绑定正确。释放连接后排队读取完成且State为
   ABSENT；显式使用原operation ID保存得到V1，再重放不新增版本；另一Host绑定看不到该State。
3. 池获取超时单独返回503/POOL_WAIT_TIMEOUT；记录失败的获取耗时而不伪造连接持有，
   后续同线程请求不遗留计时上下文。

这里证明的是受控池边界和恢复，不是网关压力测试。拒绝样例中此前没有其他提交，故能
直接确认无该State；不能把这个测试结论泛化为任意503都意味着整个请求未提交。

MCP通过真实Async SDK的mock HTTP503验证仍返回WORKING_STATE_OUTCOME_UNKNOWN、仅一次
请求且不泄漏私有错误细节。它是客户端控制证明，不冒充真实MCP负载下的过载实验。

## 检查与边界

Runtime完整真实PG回归 **984 passed / 0 skipped / 0 failed（89.03s）**，包含SDK/OpenWorker
可选包路径；MCP完整 **170 passed / 1默认PG skip**，该真实PG生命周期另跑 **1 passed（10.74s）**。
Runtime/MCP Ruff、mypy、build通过，SDK源码未变，不重复计作新SDK效果。细节在`results.json`
及`product-checks.json`。Lab最终 **268 passed**，边界检查、Ruff、mypy及构建通过；
`final-checks.json`确认三个当前配置的源码锁均匹配，API/worker进程已不存在，自有PG已停止，
数据保留。未启动或修改共享服务。

此改动没有增加连接池大小，不支持吞吐或尾延迟改善结论。Waitress/HTTP入口排队、跨租户
公平份额、高成本加工容量和多实例合计资源仍需单独证据；不得用一个有界DB队列宣布
P4或完整服务SLO通过。D4/D5未进入，整体Goal继续进行。
