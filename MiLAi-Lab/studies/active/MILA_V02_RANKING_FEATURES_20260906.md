# MILA-V02-05：请求内排序特征复用

状态：`IMPLEMENTED_ENGINEERING_VERIFIED_PUBLIC_RECHECK_NOT_RUN`。记录日期为
2026-09-07（Asia/Shanghai），运行标识沿用20260906。完整P1/P2/P4、正式D4/D5未完成。

## 改动与边界

实际认证Flask路由及真实PG请求显示，同一执行中的两次排序各处理60份来源，query与
完整正文均重合；两次排序CPU合计约4.444ms。原输入及结果保留于Product自有诊断目录。

`runtime/src/milai/application/acquisition.py::rank_evidence_turns`增加可选特征缓存，
键为完整`(query, content)`，值只含词覆盖数量及数量回答信号。来源身份、anchor、分数、
speaker、时间、权限和结果行不缓存，仍取本次检索返回值。
`evidence_acquisition.py`在每次execute内创建缓存，仅在原repository读取及来源策略过滤
之后使用；下一次execute重新创建。没有合并SQL或复用旧资格，不改变排序、完整正文与首尾。
公开API、schema、Canonical、CAS及权限语义不变；不需要迁移，未部署共享服务。
回退仅移除本增量的特征缓存及传参，不改已持久化数据。

当前Product pin：`46333e870b7c946a22aa5f6518ac78ace070cac15197835cfbb05a082fa610e0`。
锁文件：[v02-ranking-features-product.lock.json](../../data/locks/v02-ranking-features-product.lock.json)，
锁摘要`f95c9eda2116939ffb235c6285d05e9713591d7239802c429cc7b949b7f9d2ba`。
E2E及保持关闭的SIM02候选配置引用新锁，历史实验pin不覆盖。

## 验证及成本

| 证据 | 结果与限制 |
|---|---|
| 离线候选36组控制 | 6种query、3种speaker偏好、原/变更行；完整结果相等，含正文及元数据变化 |
| 新增20项Runtime测试 | 缓存与未缓存结果、完整query/text绑定、执行隔离；4次repository读取均发生，空新结果不恢复旧来源 |
| 相邻测试 | 27 passed |
| 最终真实PG全量 | `uv run pytest -q`：1156 passed，无跳过，98.96s；独立PG和角色连接 |
| Runtime静态/包 | `uv run ruff check src tests migrations`、`uv run mypy`（191文件）、`uv build`通过 |
| Lab交付检查 | boundary、Ruff `src tests tools`、mypy `src/milai_lab`（30文件）、build通过；pytest 337 passed，2.84s |
| 最终同pin离线排序对照 | 两次排序CPU中位数4.638555→2.303113ms；60个缓存项，完整结果相等；0网络请求 |
| 最终10次内部真实请求 | warm＋single＋8并发；完整Context与保留母本一致，计时后完整DTO/snapshot相等 |

最终单请求wall/CPU为74.064905/36.543409ms。8并发请求wall范围288.658218–412.951410ms，
整批wall427.646681ms、请求线程CPU合计391.205285ms、进程CPU494.420419ms。
单个80.888323ms CPU样本保留。它们是Product内部实际路由诊断，**不是公开MCP服务SLO**，
整批完成时间也不是请求P95。未在计时路径消费的完整span/raw semantics/snapshot在计时后
核对；完整消费成本不能被称为消失。

本增量没有新的公开压测。最新公开k仍属于上一个8e345a71…版本，c8 P95为574.696638ms，
300ms目标未满足。不能把当前内部427.647ms与历史公开P95相减归因。
保留原PG 2 CPU/1GiB、Runtime affinity `{0,1}`（同核SMT）、pool8/maxwaiting32及完整来源。
没有扩负载、换核或放宽阈值。

本增量诊断实际请求11次（原实现采集1＋最终实现10）；离线对照0请求，回归/初始化另列。
新增模型调用、Provider tokenize均为0。开发对话和设施成本不据此称为零。
本增量服务已停止、数据保留，共享服务未动。Schema仍为
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。

## 可定位证据与下一步

- Product忽略目录`runtime/var/v02-ranking-work/`：采集、候选、最终同pin对照、10请求结果、清理及`lab-checks/results.json`。
- Lab忽略目录`artifacts/v02-e2e-generality/p1-ranking-features-regression-20260906a/`：全量日志、退出状态及最终清理。
- [中央结果](MILA_V02_E2E_GENERALITY_RESULTS.json)保留本次独立增量，历史顶层pin不改写。

下一步以当前实现仍发生的完整请求工作量为依据继续P1/P2，已缓存或延后的工作不能再次
计算为可省成本。模型授权仍为0；这些工程证据不证明分层降本、任务质量或端到端泛化。
