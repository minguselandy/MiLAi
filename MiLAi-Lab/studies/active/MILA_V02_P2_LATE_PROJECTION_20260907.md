# MILA-V02-05：晚到投影与当前读取成本

状态：`LATE_PROJECTION_MECHANISM_VERIFIED / P1_P2_P4_PARTIAL`。
本轮增加一个Product真实PG回归，运行实现与公开合同不变，未增加模型/tokenize调用。

## 晚到任务：验证有效租约下的旧版本完成

新增测试为Product `runtime/tests/integration/test_projection_worker.py`中的
`test_older_claim_projection_finishes_after_new_version_without_head_regression`。
原有失效租约测试检查旧worker不能提交；本测试让旧任务保留有效租约，覆盖另一种时序：

1. 在独立测试tenant中通过公开Evidence、Proposal、Review接口建立V1并正式SUPERSEDE为V2。
2. 分别取得FTS/vector任务租约，通过真实FoundationWorker处理器先完成新版本，保留旧版本任务。
3. 核对新版本任务DELIVERED，而连续水位仍被旧任务缺口阻挡。
4. 再完成有效租约内的旧任务，核对连续水位达到本批最大序号，当前Claim head仍为V2。
5. FTS及vector的旧、新版本记录分别存在；公开Claim GET仍返回V2和新payload值。

不是通过强制改写outbox/head/租约制造状态。规范的合成Canonical变更仅发生于自有测试环境，
不是共享Canonical修改。现有搜索投影按ClaimVersion保存，所以“旧记录仍存在”合法；
本测试证明它没有覆盖新版本身份或倒退当前head，不声称历史索引全部删除。
本轮未新增公开搜索结果排序、窗口/128维投影、任意任务晚到或断电测试，也不冒充新的
进程重启实验；原重启证据保留在P2 durable报告。

独立产物根：`artifacts/v02-e2e-generality/p2-late-projection-20260907a/`。
先运行新增目标测试1 passed（2.13s），再运行全量1157 passed（102.50s），无跳过。
全量之前同数据库仅运行了该独立随机tenant测试，没有重跑带固定身份的旧全量实例。
`target-result.json`、`full-result.json`及日志保留，命令为：

```text
uv run pytest -q tests/integration/test_projection_worker.py::test_older_claim_projection_finishes_after_new_version_without_head_regression
uv run pytest -q
uv run ruff check src tests migrations
uv run mypy
uv build
```

Ruff、mypy（191源码文件）、构建通过。mypy不等于新增集成测试已被类型检查。
Lab可执行代码未改，本轮复用上一增量337测试及boundary/Ruff/mypy/build结果，未重复运行。
测试文件SHA256：`78924b850fe75d8e27b1675f27e778a1d35fde970de255f9ce272ed1a55d09bb`。
运行源码pin仍为`46333e870b7c946a22aa5f6518ac78ace070cac15197835cfbb05a082fa610e0`，
该pin不含测试文件，故测试摘要单列。`final-observation.json`确认pin、自有API/worker不存在、
PG停止且数据保留。未修改API、权限、事务、schema或运行实现，无迁移/部署。

## 当前读取成本：排除重复优化已移出路径的工作

Product忽略目录`runtime/var/v02-post-ranking-work/`保留有限计划、3次认证实际路由/真实PG
请求（warm、阶段计时、cProfile），完整MemoryContext与上一实现结果相等。
它是Product内部诊断，不是Lab黑盒效果或公开SLO。阶段嵌套，以下CPU不能相加：

| 当前实际阶段 | 线程CPU ms | wall ms |
|---|---:|---:|
| 两次排序合计 | 2.533 | 2.533 |
| 两次probe合计，含排序 | 6.076 | 30.487 |
| 融合 | 2.762 | 2.761 |
| 来源span准备 | 5.436 | 5.501 |
| acquisition整体 | 16.059 | 40.547 |
| snapshot整体 | 2.613 | 2.614 |
| retrieve整体 | 30.598 | 68.186 |
| Context编译 | 4.315 | 4.313 |

整次诊断含结果解析、相等断言及产物写入：CPU41.302ms、wall78.897ms。
cProfile单独记录119374调用、0.105s，使用默认wall计时；不把其中递归deepcopy累计值当作
未剖析路径的实际CPU，数据库wait也不等于全部纯SQL计算。该诊断未删除复制、来源或资格检查。

对既有配额轮转循环作了离线候选：维护已选数量和每slot剩余候选迭代器，避免反复扫描。
使用保留真实排序结果及公开trace中的plan，不重新构造未来答案。初版240组model_copy
控制未校验完整plan，后续校验揭示合成dense query缺失及slot/budget条件；初版不能算
合法plan范围证据。修正控制生成后每个plan经过AcquisitionPlan校验，240组完整输出相等，
包含三类现有融合policy、多slot、不同通道/重叠/空结果/配额。
最终同输入30次交替对照CPU中位数2.624101→1.766548ms，节省约0.858ms。
此候选仍在忽略诊断目录，**没有进入运行实现，也没有新公开压测或收益承诺**。

本轮该诊断3次Runtime请求，离线对照0请求；PG测试和初始化调用另列，不合并成模型样本。
模型及Provider tokenize均0，设施/开发成本不因此记零。

## 资源边界与后续选择

当前重新读取系统拓扑：CPU0/1同属package0/core0，CPU2属于core1。冻结配置继续使用
`{0,1}`，PG 2CPU/1GiB、8线程及pool8保持。没有调整阈值、亲和性或服务进程数量。
可审阅的后续独立校准方案是：同pin、同完整来源、同进程数和预算，分别固定`{0,1}`与
`{0,2}`，仅比较CPU亲和性。它改变物理资源布局，必须独立登记运行条件与额度，不能
把新条件下结果回填旧配置的PASS；本轮未执行。单进程Python的GIL也意味着分开物理核
并不保证加速，不先把硬件解释当作已证明根因。

当前仍以已冻结资源下的正确性和剩余请求成本推进P1/P2。最新公开k属于8e345a71…历史pin，
c8 P95为574.697ms；当前46333e…的内部8并发整批427.647ms来自上一增量，不是新公开P95。
混合负载退化门、租户公平性、完整服务SLO及正式D4/D5均未完成。Schema保持
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
