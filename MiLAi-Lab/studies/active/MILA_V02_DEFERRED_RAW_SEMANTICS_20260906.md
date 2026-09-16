# MILA-V02-05：普通读取按需派生原始语义材料

2026-09-07（Asia/Shanghai）执行，沿用20260906文件标识。Product候选pin为
`130f0f74dd571becb33ea80b1f8e00078eb2fe8826eafba0e514df488ec539f7`，
锁为`data/locks/v02-deferred-raw-product.lock.json`；保留前一d634锁与失败记录。
本次不增加模型额度，不发布或重启共享服务。

## 改动与边界

前一独立懒序列候选因snapshot规范化立即消费而增成本。本次联通编译与snapshot消费：

- 获取、当前资格检查、完整来源投影、候选与RequirementState仍立即执行。
- 仅显式允许延迟、无operator、无range scan、无type-directed/Formation语义且为
  ORDINARY_RECALL时，保留原始解释/绑定的待计算输入。没有增加语义推理者或Memory schema。
- 判断仍看到真实的binding存在性；完整迭代、长度、索引或序列化执行原函数，保留所有
  REJECTED/POSSIBLE/MATCH材料。没有把空列表或占位结果当成完整Execution。
- 空authoritative bindings下，消费者先确认没有可用操作输入，再跳过无用映射构造；
  DecisionEngine对raw binding存在性的判断保留。
- Execution的即时facts与完整诊断表示分开；`model_dump`和正式消费恢复原完整DTO。
  snapshot冻结独立输入，完整摘要被消费时才派生语义材料；已物化诊断也完整复制。
- Runtime内部请求引用和snapshot各有本地锁。审计、匹配回放、Formation、确定性恢复、
  operator及type-directed路径沿用完整计算，正式消费者仍取得完整对象。

主要修改位于Product的`deferred_raw_semantics.py`、`evidence_acquisition.py`、
`reader_evidence_plan.py`、`retrieval.py`及两个相邻消费者。未改变公开工具/API、权限、
CAS、Canonical、数据库事务或migration；解释/绑定仍无operator authority。
完整来源与首尾内容保持。按需派生不是对所有输入语义正确性的证明。

## 同输入与真实请求证据

Product内部忽略目录`runtime/var/v02-deferred-raw/`保存脚本、计划、所有响应与样本。
Lab未导入Product私有实现；这些是Product自有诊断，不是Lab黑盒实验或服务SLO。

同一候选版本、同一捕获输入，仅切换`defer_semantics`，交替10轮比较完整编译及snapshot
facts构造，CPU中位26.939→14.861ms。包含完整来源投影，不包含数据库或Context编译；
完整DTO、snapshot与摘要在两侧计时外逐项核对相等。原计算70.987ms离群样本保留。
这个组件对照不能直接解释为HTTP/MCP整体收益。

另以原公开Flask路由、真实认证和自有PG执行10请求（warm、single、8并发），使用原h
完整数据、scope、预算及affinity0–1，不裁剪来源，不扩大连接池。全部完整Context与
保留h相同；10请求内均未物化raw语义或完整摘要。计时后分别用各请求自己的输入执行
原完整计算，完整DTO、snapshot及摘要全部相等。

| 观测 | 结果 |
| --- | ---: |
| 单请求wall / thread CPU | 89.740 / 49.675ms |
| c8各请求wall范围 | 361.677–530.348ms |
| c8整批wall | 543.862ms |
| c8请求thread CPU合计 | 512.077ms |
| c8整批process CPU | 614.969ms |

warm为207.496ms wall；c8中的94.868ms thread CPU较高样本保留。请求CPU合计与进程CPU
是不同观察边界，不能相加。0/1仍为同核SMT逻辑CPU；本次没有换核或增加资源。
本次不是公开MCP SLO重测，原公开h并发8 P95 1306.270ms失败继续有效；内部543.862ms
也未达到目标。不能从局部成本下降宣布完整P1通过。

## 回归、清理与后续

新增14项控制覆盖完整材料、存在性负控、输入变更隔离、已物化输入、并发一次派生、
普通请求未消费、审计完整性及typed fallback。开发过程Product单元903通过（11.12s），
该次在已物化列表bool处理补充前；最终pin独立PG全量1081通过、无跳过（99.79s），
包含全部单元测试。Ruff、mypy（190文件）及构建通过。
全量原始记录位于Lab忽略目录
`artifacts/v02-e2e-generality/p1-deferred-raw-regression-20260906a/`。

Lab最终324测试通过（2.81s），boundary、Ruff、mypy（30文件）及构建通过。
Product pin、关闭的SIM02候选配置、完整诊断结果及汇总JSON重新核对一致。

本增量性能诊断请求10，离线组件比较Runtime请求0，模型/Provider tokenize均0。
回归测试的服务调用单列在回归范围，不把10当作包含pytest的总HTTP请求计数。
自有诊断PG及回归PG停止；回归API/worker已确认ABSENT，数据保留，共享服务未触碰。

下一步基于当前完整请求的剩余成本继续解决并发差距，不再以独立懒序列候选或已省去的
解释/绑定计算解释剩余瓶颈。保持已冻结负载、资源和失败门槛，不扩大负载或模型样本。
完整P1/P2/P4与正式D4/D5仍未完成，端到端通用性未证明。
Schema保持`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
