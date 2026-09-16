# MiLA V02 普通读取工作量审计

状态：`PRODUCT_INTERNAL_DIAGNOSTIC / NO_PRODUCT_CHANGE`。实际诊断日期为2026-09-07，
文件名沿用冻结批次日期。完整P1/P2/P4及D4/D5未完成，模型效果和通用性没有新增结论。

## 边界与证据

本轮复用公开h运行保留的1000条完整来源，仅启动自有PG。Product开发诊断通过真实
Flask公开路由、鉴权和PG执行一次预热、一次观测，原API/worker/MCP未启动；CPU affinity
仍为0–1。这是Product自身的内部诊断，使用私有函数包装记录工作量，不是Lab黑盒实验、
网关SLO或新的并发校准。没有删首尾、缩减来源、改变请求或启用模型。

源码pin仍为`d9a2fd6df5aa471c2211eaf9aabb237735b8ae92ed810d47b8778f72dacf7fcc`，
锁digest为`ba1447c74c0078eb18c121bc31bc94727bada80cd2db8eaf9aef9cd0f9d47b26`。
原始证据位于Product忽略目录`runtime/var/v02-read-work-audit/`：
`plan.json`、`audit_request.py`、`audit.json`、两份response、`run.log`、`cleanup.json`。
观测包装在finally恢复，两个数据库客户端关闭，自有PG经inspect确认停止，数据保留。

观测请求wall为153.791ms，thread CPU为115.178ms。完整MemoryContext与预热相同，
未规范化或删除任何字段；这不等于完整HTTP响应相同，也不证明并发或语义质量。
结果为EVIDENCE / PARTIAL，context receipt未持久化，无continuation。

## 实际事务与逻辑消费者

七次事务均安装请求身份并执行逐事务角色校验。下表wall包括事务包装与调度，不是纯SQL。
SQL记录只存标签、SQL/参数hash及计时，不输出参数正文或凭证。

| 顺序 / 入口 | wall ms | thread CPU ms | 用途与边界 |
| --- | ---: | ---: | --- |
| projection_state | 2.285 | 0.824 | 初始投影水位，供可用性/新鲜度判断 |
| search_evidence：global | 14.793 | 2.070 | 全局FTS原始来源获取 |
| search_evidence：slot | 14.940 | 2.126 | LOOKUP_ANSWER需求槽获取 |
| exact_candidates | 2.586 | 0.925 | Evidence不足后的Canonical精确候选，本次0行 |
| search_fts | 4.136 | 1.144 | Canonical词法候选，本次0行 |
| gate_and_hydrate | 4.372 | 1.370 | repeatable-read下门控、补全与水位确认 |
| record_trace | 4.805 | 1.010 | 持久检索审计，正常写事务 |

两次Evidence查询对应`global:fts-raw`与`slot:LOOKUP_ANSWER:fts-raw`，均为FTS_RAW、
limit 60。逻辑probe中的entities/predicate不同，但实际执行的搜索SQL hash和参数hash
完全相同。业务SQL各耗12.030/12.257ms。这确认一次请求内存在重复物理查询；并未证明
两个逻辑probe可以删除其一，也未证明跨时间复用满足撤销/披露要求。

驱动隐式BEGIN/COMMIT及pool RESET不在execute记录范围内。Canonical查询本次无结果，
不能由此删除正常回退；repeatable-read门控和审计不能作为无用事务跳过。

## CPU工作量及输出消费者

| 阶段 | 实际工作 | thread CPU ms | 输出消费者 |
| --- | --- | ---: | --- |
| project_evidence_spans | 60来源→240 span | 9.628 | 解释、绑定、来源定位、决策快照 |
| interpret | 240 span→240 STATE_OBSERVATION | 27.420 | 绑定、需求满足度、operator/决策；本次suppressed 0 |
| bind_requirements | 1需求×240解释→240绑定 | 22.940 | 180 REJECTED、60 POSSIBLE、0 MATCH；需求状态与归因 |
| decision_snapshot | 形成决策及材料摘要 | 16.401 | 来源/QueryIR/计划/候选/门控/绑定等摘要和回放一致性；本次accepted 0 |
| MemoryContext compile | 14可用窗口→8呈现窗口 | 8.012 | 有界Host输入；不等同完整记忆或完整候选集合 |

以上不嵌套的五个阶段约84.401ms CPU，占本次请求约73.3%。外层retrieve为142.450ms
wall / 103.837ms CPU，已包含其中阶段，不能再相加；事务时间也与retrieve重叠。
retrieve返回14个结果和60个context candidates，后者还供intra-source处理及按条件启用的
continuation使用。仅呈现8窗口不能推出另外的来源、绑定或候选可以提前丢弃。

静态核对还确认：recollection是协议接口，lean_recall形成计划，均非已经存在的独立低成本
读取引擎；formation路径在原始基线已计算后再获取/重放，不是自动避免基线计算的缓存。
type-directed路径仍需扫描以保留suppressed计数；直接打开它不能视为输出不变的优化。
BindingCompatibility可变，不能假定可安全共享模型对象。

## 开发选择

优先验证请求内纯文本分析的重复计算能否复用，先限定为局部候选：文本识别结果与来源绑定
分离，每个span仍独立形成ID、provenance、speaker/时间相关结果、解释和绑定。必须比较
完整解释、绑定、快照及MemoryContext，并覆盖相同文本不同来源/时间/说话人、含日期和
数量、不同文本及输入顺序。日期归一化与当前权限判断不能仅按文本缓存。

这只是下一项待验证方案，尚未实现，也没有速度收益承诺。测试数据中重复文本较多，
局部提速必须分别报告重复文本和不同文本条件，不能推为任意任务通用。先用已有材料进行
有界等价及成本检查；确认实质收益且回归通过后，才安排下一次冻结配置公开复测。

重复物理查询是次级候选：若实施，须保留两条逻辑probe的策略、排序和归因，区分物理与
逻辑调用，限定请求内同参数，证明当前披露/撤销边界及对象修改隔离，不缓存失败。
本次可避免的一次查询仅约15ms wall / 2ms CPU，单独不足以解释或修复h的c8 P95
1306.270ms相对300ms门槛的缺口。不能把这两个数字直接相减预测并发收益。

本轮未改产品代码、API/schema、事务或权限语义，不新增模块/数据库实体，不变更资源、
负载、预算或停止线。没有再次运行1038项Runtime和309项Lab回归，既有结果属于上一
源码增量；本轮验证为两请求诊断、完整Context比较、pin/文档检查及清理。模型和Provider
tokenize调用均0。Schema继续保持`NO-GO FOR SCHEMA FREEZE`。
