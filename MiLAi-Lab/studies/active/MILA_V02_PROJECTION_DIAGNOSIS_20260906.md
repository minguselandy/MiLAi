# MILA-V02-05：重复获取边界与来源投影诊断

2026-09-07（Asia/Shanghai）执行，沿用20260906文件标识。Product pin保持
`d6343d4b34c1f85ab40780cd12f4ac89fb5e34b3055b4d99edd8d1fb8084f337`。
本次无Product源码、公开部署或模型授权变更。

## 重复获取不等于可以直接缓存结果

保留的真实获取计划有两个FTS_RAW probe：全局probe和LOOKUP_ANSWER槽probe。两者
lexical_terms、scope/as-of及limit相同，历史工作审计也确认SQL/参数相同，但槽probe
另有requirement_slot、predicate_family、entities；它们的逻辑归属不能删除。

当前`RetrievalRepository.search_evidence`每次独立进入只读连接，调用
`milai.search_evidence_projection`。现有0045实现除校验session identity，还联接当前
Evidence，检查revoked_at、retention、permission_snapshot和project scope。相同SQL及
参数不代表两次执行间的授权状态必然相同。直接复用第一次返回值会跳过第二次当前检查，
需要单独定义与验证一致性/权限语义；本次没有实施该改变，也没有以静态数据相等证明可缓存。

该结论是实现检查得到的约束，不是一次新执行的并发撤权实验。历史两个probe各约3.8ms
CPU/16ms wall也不能全归为可删除工作。没有合并数据库事务，没有新增跨请求缓存。

## 来源投影的实际成本

Product自身通过真实Flask公开路由、原认证与PG执行1个请求，复用h的1000完整来源，
原scope、载荷和affinity0–1不变。捕获60个实际来源、240个投影span，完整MemoryContext
与保留h相同。自有API/worker未重启，只临时启动自有PG；请求结束关闭客户端并停止PG。

外层子步骤计时如下，含包装开销及嵌套，不能相加成独立总成本：

| 位置 | 调用数 | CPU合计ms |
| --- | ---: | ---: |
| `_source_offsets` | 60 | 4.892 |
| `_identity` | 240 | 3.235 |
| EvidenceSpan构造 | 240 | 2.206 |
| 源正文逐span核对 | 240 | 0.319 |
| 完整投影 | 1 | 12.844 |

捕获材料只保存在Product忽略目录`runtime/var/v02-span-projection-work/`。
`trusted-projection-inputs.pickle`由本任务自身生成与读取，不是公开输入或Lab黑盒材料。

## 小候选与限制

离线候选仅在整行不包含ASCII `. ! ?`时，直接沿用原规则的左右空白修剪及绝对偏移，
避免句子正则扫描；含这些标点时完整保留原分句与缩写规则。没有删除首尾、正文、
source identity、provenance、验证或span摘要。

1011个控制字符串涵盖空白、CR/LF、Unicode空白/分隔符、标点、缩写、小数及固定seed随机
组合；另比较全部60个实际来源，偏移相同。交替10次完整投影结果保持全部240个typed span
对象相等，CPU中位8.954→7.344ms，约节省1.610ms；原始样本全部保留。

这只是已测输入上的候选收益，尚未进入Product。没有对每个语料家族进行泛化实验，也
没有新的HTTP/MCP SLO校准。先记录候选，避免因这一小差异重复全量公开负载；它不足以
单独消除目前的并发差距。原有服务失败与模型效果未验证结论不变。

## 计数及后续

新增真实诊断请求1，生成/Provider tokenize均0；无SQL合并、无Product改动、无migration。
现有1067真实PG回归属于上一增量，本次不追认为新执行。自有PG停止、客户端关闭、
资料保留，共享服务未触碰。

本次Lab检查：`uv run pytest -q`为309通过（2.67s），boundary、Ruff、mypy（30文件）及
构建均通过。最终重新验证Product pin未改变、自有PG已停止，汇总JSON可解析。
Product源码未变，没有为文档/诊断再次执行上一轮1067项数据库回归。

下一步应检查普通读取中仍实际被消费的解释、绑定和Context材料及其重复计算，优先寻找
能够减少整体工作量的改动；本候选保留，等组合收益与完整输出合同明确再决定是否采用。
不能用假摘要、省略来源/权限检查或更换资源来掩盖差距。完整P1/P2/P4及正式D4/D5未完成，
Schema仍为`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
