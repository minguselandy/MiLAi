# MILA-V02-05：Context视图复用与截取计量

2026-09-07（Asia/Shanghai）执行，沿用20260906文件标识。候选Product pin为
`10f713352d53d245fa3ad27e6a283b3a09410031fe7149c7e2ee18ed8afbbe86`，锁为
`data/locks/v02-context-work-product.lock.json`。保留前一130f锁与历史失败，不增模型额度。

## 证据与实现

前一pin的warm加一次真实请求诊断保持完整Context。带包装的外层计时显示，Context
编译约8.667ms CPU，其中两次来源视图构造合计3.874ms；83次渲染、97次token估算，
7次窗口拟合合计2.804ms。它们有嵌套和观测开销，不能相加为独立总成本。

据此只修改Product `memory_context.py`中的两个纯计算位置：

- 没有扩展或替换、items与baseline逐项为同一对象且顺序相同时，复用已建视图，
  另建列表保留各自容器。复制出的等值字典或新增来源仍走原基线构造路径。
- 拟合一个窗口时，只有最后一个窗口的正文变化。先计算其余渲染内容的固定UTF-8
  字节数，再按原二分顺序、相同截取和相同估算规则判断候选；不再逐次渲染已选全文。
  固定部分已经用尽预算时直接返回无法容纳，外层仍记录每个候选的完整激活阈值。

来源原文、首尾、字段、排名、窗口顺序、必需来源、回执和权限边界保持。没有更改token
估算合同、公开API、schema、Canonical或数据库事务，无migration。

## 回放中的失败与修复

最初采样保留了输入引用。MemoryResolve随后整理公开响应时pop内部边界字段，导致
离线原实现回放的`reader_evidence_boundary`不同；回执ID与时间也自然不同。该失败保留于
`replay-failure.json`，不算候选成功证据，也不是Product丢失记忆内容的结论。

另外执行1个已单列计划的真实请求，在采样入口深复制输入，保留完整采样输出。离线双方
固定相同回执UUID和时间，比较所有字段，没有删除首尾、边界或回执字段。
最初回放又将已扩展列表作为独立副本返回，未覆盖同对象复用条件；保留其结果，最终
复用实际无扩展逻辑，读取替身一旦被调用就报错。实际记录的NO_STRUCTURED_EVIDENCE_ANCHOR
分支与回放相同，没有新增来源获取。

有效离线对照完整ContextCompilation（含回执）相等，视图构造2→1次；320个拟合控制
覆盖中英文/emoji/组合字符、已有窗口、Canonical JSON、OpenIssue、derived文本及预算。
交替10轮Context CPU中位7.796→3.797ms。此为捕获输入上的纯计算对照，未重复来源资格
检查或数据库获取，不能当作完整服务SLO或语义泛化效果。

原始记录与脚本位于Product忽略目录`runtime/var/v02-context-work/`。Lab未导入Product
私有模块；所有上述私有实现诊断由Product自身执行，不冒充Lab黑盒实验。

## 真实候选与限制

候选通过原Flask公开路由、实际认证、自有PG执行10请求（warm、single、8并发）。原h
完整1000来源、scope、预算和affinity0–1保持，未扩大连接池或负载。完整Context均与h
相等，各请求计时后恢复完整Execution DTO和snapshot/摘要也相同，raw语义仍按需派生。

| 观测 | 数值 |
| --- | ---: |
| 单请求wall / thread CPU | 89.052 / 46.537ms |
| c8各请求wall范围 | 366.516–504.116ms |
| c8整批wall | 515.590ms |
| c8请求thread CPU合计 | 476.951ms |
| c8整批process CPU | 575.666ms |

warm为133.402ms wall，c8有90.489ms thread CPU较高样本，均保留。不同CPU观察边界
不相加。0/1仍是同核SMT逻辑CPU，没有换核；未进行公开MCP SLO重测，原h的c8失败
继续有效。内部515.590ms仍未达目标，不宣布P1通过。

本增量真实诊断请求总数13＝原诊断2＋采样所有权修复1＋候选10；离线无Runtime请求，
模型与Provider tokenize均0。服务初始化和pytest调用单列，不把13当作全量HTTP计数。
诊断自有PG已停止，原API/worker没有重启，共享服务未改变，数据保留。

## 验证与下一步

新增23项回归测试，局部56通过、单元926通过（11.13s），Ruff、mypy（190文件）及
构建通过。最终pin独立PostgreSQL全量1104通过、无跳过（96.31s），记录位于
`artifacts/v02-e2e-generality/p1-context-work-regression-20260906a/`。
Lab324测试通过（2.63s），boundary、Ruff、mypy（30文件）及构建通过。
重新核对最终pin和汇总结果；自有回归API/worker均为ABSENT，PG已停止，数据保留。

仍需从剩余完整请求成本缩小并发差距。当前观察中来源投影约9.675ms CPU、两次probe
约8.850ms CPU及34.945ms wall，不能把已省去的解释/绑定或Context重复计算再次计为
可省成本。若探索进一步推迟投影，应先保留有效span存在性的判断、完整源定位及冻结
输入所有权；若处理重复获取，仍须维护每次当前资格检查。没有据此新增模块或放宽门槛。
完整P1/P2/P4、正式D4/D5和端到端通用性仍未完成；Schema保持
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
