# MILA-V02-05：当前读取成本与投影存在性负控

2026-09-07（Asia/Shanghai）执行，沿用20260906标识。当前Product pin仍为
`10f713352d53d245fa3ad27e6a283b3a09410031fe7149c7e2ee18ed8afbbe86`。
本轮未修改Product或Lab运行代码；记录诊断与未采用候选，不声称性能改善。

## 当前版本诊断

Product自身使用既有h的1000完整来源、自有PG、实际认证及Flask公开路由执行3请求：
预热、阶段计时、thread CPU cProfile各1。三个完整MemoryContext均与当前版本已保存
结果相同。原API/worker没有重启，affinity仍0/1，没有新增MCP负载或模型调用。
私有诊断仅在Product忽略目录`runtime/var/v02-current-read-work/`，Lab不导入私有实现。

| 阶段 | 次数 | CPU ms | wall ms |
| --- | ---: | ---: | ---: |
| 来源probe | 2 | 8.194 | 33.532 |
| 融合 | 1 | 2.673 | 2.672 |
| 来源span投影 | 1 | 10.083 | 10.135 |
| candidate envelope | 1 | 0.481 | 0.480 |
| requirement state | 1 | 0.360 | 0.359 |
| snapshot | 1 | 3.943 | 3.943 |
| 其中raw隔离复制 | 1 | 3.208 | 3.208 |
| Context编译 | 1 | 4.253 | 4.294 |

外层46.406ms CPU/86.554ms wall包含测试客户端及写诊断产物；它不是服务SLO。
阶段有嵌套，不能相加。单独cProfile产生155057次调用、约312ms计时CPU；递归复制
对逐调用观测特别敏感，不能将其约197ms累计值当作正常请求可节省的复制成本。
该profile只定位消费者，实际取舍仍依据未递归采样的阶段数据。

## 排除“正文非空即可推断span存在”

准备延后投影的候选时发现：原`_SENTENCE`分句规则下，`?!`或`.`单独成正文不会
产生span，而带前导空格的`  ?!`会产生span。直接用`bool(content.strip())`推断
raw绑定存在性，与原投影并不等价。

使用自有真实投影捕获的合法来源元数据，替换10种正文作离线控制；发现2个非空判据
反例。另在固定DecisionEngine输入（Canonical候选、无requirement state）中验证：
真实无绑定为`PARTIAL / NATURAL_LANGUAGE_READER_ONLY`，错误的存在性判断会变成
`UNSATISFIED / REQUIREMENT_STATE_INCOMPLETE`。这是未实现候选的反例，非线上新缺陷，
不把两种判定解释为任务正确率。第一次诊断导出误把dataclass当Pydantic，失败单列保留，
随后完整导出所有DecisionResult字段；没有因此新增Runtime请求。

候选已排除。后续若延后投影对象或摘要构造，必须先保持原分句/资格/身份/时间/偏移
校验语义和输入隔离，再测机械准备与延后构造的净收益；不能以非空正文或删除材料替代。

## 证据与边界

`plan.json`、`result.json`、`thread-cpu.pstats`、`presence-control.json`及`cleanup.json`
位于上述Product忽略目录。真实请求3，离线请求0；生成和Provider tokenize均0。
自有PG确认停止，原API3601152/worker3601153均不存在，共享服务未改，数据保留。

Lab boundary、Ruff、mypy（30文件）、构建通过，pytest337通过（2.67s）；Product pin
复核不变。无Product源码改动，不重复或追认上一轮最终pin真实PG1104测试为本轮执行。
公开j的c8 P95 662.906ms失败继续有效。完整P1/P2/P4与正式D4/D5未完成，Schema仍为
`NO-GO FOR SCHEMA FREEZE`。
