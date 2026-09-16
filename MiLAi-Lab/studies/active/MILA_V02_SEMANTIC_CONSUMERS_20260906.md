# MILA-V02-05：解释与绑定消费者诊断

2026-09-07（Asia/Shanghai）执行，沿用20260906文件标识。Product pin保持
`d6343d4b34c1f85ab40780cd12f4ac89fb5e34b3055b4d99edd8d1fb8084f337`。
本次是Product内部诊断，无运行源码、API、权限、Canonical或schema改变。

## 真实消费与不能删除的区别

通过真实Flask公开路由、原认证与自有PG执行1个请求，保留h数据、scope及完整来源。
得到60个结果、240个span、240个interpretation和240个binding，完整MemoryContext
与保留结果相同。实际响应始终使用原计算；离线反事实仅用于比较，没有进入产品响应。

记录到16次构造后访问：DecisionEngine读取binding真值3次，来源引用材料复制产生
6次迭代/长度访问，requirement state构造映射2次，accepted span构造映射2次，
snapshot规范化3次。记录不是所有可能消费者的完备证明，也不覆盖所有C层序列化访问。

现有合同将raw prose bindings与正式operator operands分开，转换函数当前返回空tuple。
因此部分消费者构造了最终未用于operator输入的映射。但DecisionEngine仍使用原始
bindings是否存在，选择判定分支；无operator authority不等于无行为影响。

本请求的FTS/FINAL反事实省略raw材料后结果相同，两处空authoritative bindings下
省略span/interpretation映射也相同。这只描述本请求，不能推出可以全局省略。

独立离线负控使用既有lookup测试材料，在未提供requirement_state时比较：

| 输入 | status | reason |
| --- | --- | --- |
| 完整原始材料 | UNSATISFIED | REQUIREMENT_STATE_INCOMPLETE |
| 清空span/interpretation/binding | PARTIAL | NATURAL_LANGUAGE_READER_ONLY |

两者都未宣布complete，但结果合同已经改变。因此拒绝直接以空列表替换诊断材料；
没有将一次真实请求相等推广为安全优化，没有省略首尾、来源或权限检查。

## 离线成本及适用范围

对本任务自身捕获的可信输入交替测量10次，保留全部样本：

| 独立操作 | thread CPU中位ms |
| --- | ---: |
| 完整compile_existing_results | 23.199879 |
| deepcopy冻结输入 | 3.115960 |
| 完整来源投影 | 9.095351 |

完整execution和全部typed spans均相等。操作分别计时，不能相加、相减后当作已实现的
端到端收益；尚未实现deferred semantics，也没有新的并发或HTTP/MCP SLO结果。
输入冻结本身有成本，后续按需计算也不能借用会被调用方修改的对象。

## 证据与下一步

原始证据位于Product忽略目录`runtime/var/v02-semantic-consumers/`：
`observe.py`、`result.json`、`response.json`、`negative_control.py`、
`negative-control.json`、`trusted-compile-inputs.pickle`、`measure.py`、
`cost-result.json`及`cleanup.json`。pickle仅由本任务自身生成和消费，不是公开输入，
也不是Lab黑盒调用。新增真实诊断请求1，离线控制无Runtime请求，模型/tokenize均0。
自有PG已停止，原API/worker未重启，共享服务未改变，数据保留。

下一步若做按需派生候选，必须保留binding存在性对判断的影响、请求内输入所有权、
完整snapshot与Audit/replay消费；严格/formation分支在未证明等价前沿用原计算。
先做有界内部候选并比较完整结果，不能先将审计字段替换为空值再补证据。
本报告不新增模块实施要求，也不将23.20ms当成收益承诺。

本次交付检查：`uv run pytest -q`为324通过（2.71s）；
`uv run milai-lab-check-boundary`、`uv run ruff check src tests tools`、
`uv run mypy src/milai_lab`（30文件）及`uv build`均通过。
重新验证当前Product pin、汇总JSON及诊断材料，并独立确认自有PG已停止。
Product运行源码未改，本次没有重跑上一增量的1067项真实PG回归；无migration或回滚步骤。

## 后续离线候选：保留存在性，但单独接入没有收益

同日继续实现Product忽略目录中的`deferred_raw_candidate.py`，未接入Product源码。
它仅对应无kind过滤、无Formation合并的普通raw语义函数：非空白span必定生成
STATE_OBSERVATION；未启用type_compatible_only的绑定对每个requirement/interpretation
生成一行，包括REJECTED。因而可以在不算兼容性的情况下回答列表是否为空，真正迭代、
长度、索引或序列化仍调用原函数并保留全部结果，不用占位绑定冒充完整材料。

`check_deferred_raw.py`验证了以下边界：

- 已捕获实际240个interpretation和240个binding完整相等。
- 两种兼容profile、无requirement、无span、空白、时态/数量/否定/中英文及固定随机
  文本共294个语义函数控制通过。它们不是新来源或端到端表示变体。
- 上一负控使用候选得到与完整材料相同的UNSATISFIED，且未触发完整语义计算。
- 调用方在捕获后清空列表或修改嵌套provenance，不改变最终结果；8个并发消费者只计算一次。
- snapshot规范化完整消费候选，得到相同binding材料，不能保持语义计算未执行。

首轮控制曾用model_copy修改正文而未调整偏移，绕过了EvidenceSpan校验；该轮不作为有效
验证。已保留`deferred-raw-initial-invalid-controls.*`，修正为重新model_validate并同步偏移，
空正文采用无span，再执行上述294个控制。最终结果为`deferred-raw-result.json`。

交替10轮测量，语义函数CPU中位：原计算12.201ms，候选冻结并仅读存在性3.618ms，
候选冻结并完整消费15.639ms。这里不包含来源投影或服务I/O，不能当成整体优化幅度。

随后`check_deferred_snapshot_consumer.py`复用已捕获snapshot输入，双方使用相同实际
binding材料和现有`build_decision_snapshot(defer_digests=True)`，比较完整snapshot及所有
摘要。10轮候选都被规范化阶段迫使计算语义，完整输出/摘要相等。语义计算加snapshot
facts构造CPU中位由15.464ms增至19.205ms；完整摘要在双方计时外生成并核对。
原始样本见`deferred-snapshot-consumer-result.json`，本比较不是一次完整服务请求。

**不采用独立的deferred raw候选。** 它保留了判断区别，却在现有消费者下增加复制成本。
后续若继续，应统一编译输入所有权与snapshot binding取材时机，并保留完整消费入口；
不能仅给列表加懒包装、删除审计字段或假定现有defer_digests已推迟语义计算。
本后续新增Runtime、模型和tokenize请求均0，没有启动服务或改变pin。
后续交付重新执行Lab324项测试（2.66s），boundary、Ruff、mypy及构建通过，
Product pin与最终候选/汇总JSON核对通过；未重跑不受影响的Product数据库回归。

完整P1/P2/P4及正式D4/D5仍未完成；现有公开c8失败继续有效。
Schema保持`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
