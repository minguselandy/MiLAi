# WP2：可选严格记忆 CRUD 合同

状态：本地工程合同验收通过，待独立发布后的实际CI；行为修复，独立于C1结构整理。未进行真实模型调用。
执行依据为[新计划](MILAI_NEXT_IMPROVEMENT_PLAN_20260927_v1.0.md)与
[当前执行记录](MILAI_NEXT_IMPROVEMENT_EXECUTION_GOAL.md)。C0/G0已通过；
本切片基于C1最终提交`0d04ca68d0e575919773c24b764c3c0b1832de7e`，
独立分支`fix/lab-strict-memory-contract-20260927`。源码与必要检查由Sol唯一负责，
Root负责本文、配置实例、冻结与验收，Luna负责Git发布。

## 已有证据与两个解释

锁定LangMem `9d033b4…`的同步/异步manage工具在UPDATE提供合法UUID后直接put/aput，
不先确认当前namespace存在对象。原有
`test_upstream_manage_search_preserves_public_null_and_id_behavior`真实保留并验证该原生行为。
现有MiLAi `build_agent`检查UPDATE/DELETE缺ID及CREATE不应带ID，但未知合法UUID仍能经过。
历史E2曾把来源消息UUID当作memory ID，获得updated回执并新增一条记录。

H1：模型混淆源事件与记忆身份，是错误提案的来源；H2：集成层将upsert当作严格UPDATE，
令错误提案变成实际新记录。两者可以同时成立。首次修复只处理H2，不宣称模型已会选对ID，
也不把旧原生结果重新评分为新合同结果。必须在实际build_agent路径先重现，再验证新路径。

## 最小实现合同

使用公开LangGraph Store与LangMem工具schema，不改第三方安装包或共享服务。
`memory_contract=native|strict`可显式选择，缺省native保留历史行为；用于后续机制归因的
各臂统一strict。自定义memory_tools与strict同时指定视为明确配置冲突，不覆盖外部系统语义。

| 操作 | strict要求 | 验收边界 |
| --- | --- | --- |
| CREATE | 程序产生新UUID，成功回执对应实际新增 | 不接收用户指定ID冒充创建 |
| UPDATE | 当前namespace存在对象；有变化才put，相同内容NO_CHANGE | 未知UUID、其他scope对象或只存在的消息UUID不得insert |
| DELETE | 区分实际删除与不存在，没有目标不执行delete | 不因空正文或拒绝中的提案触发清理 |
| READ/SEARCH | 继续返回上游真实key、namespace与content | 句柄不是已读取的正文，标题不是业务主键 |
| 无操作 | 不改变Store，不强迫额外Host推理 | Store内部存在性get须计入操作开销 |

sync/async走各自真实Store API并共享同一结果语义；Store异常向上抛，不转换为已保存。
拒绝回执不得将提案正文包装成确认事实。协议拒绝、工具运输成功和真实状态变化分别记录。
单写者先读后写不是多进程CAS；不新增事务、分布式锁或跨进程exactly-once保证。

LSA三个执行分支通过run_phase将合同传至实际Host build_agent，配置与有效合同进入冻结身份。
operator可信初态写入继续使用原生LangMem工具，单列`operator_memory_contract=native`；
各机制臂共享同初态。该边界不允许将Host侧strict泛称为所有写入已统一，也不在本切片
重写operator alias协议、State bank或写入责任安排。

## 验证与验收边界

实际集成的native未知合法UUID upsert与strict零写拒绝；已有UPDATE、同内容NO_CHANGE、
缺失/错误namespace/message UUID、空删除/真实删除、CREATE程序ID、Store读写异常、
同步/异步一致、自定义工具冲突及三个LSA分支的合同传递。原有native行为测试保留。
受影响foundation/application/LSA检查、目标Ruff/Mypy、矩阵归属与边界；不重跑C0全core。
实际结果见下文；C2的CRUD工程合同通过，后续真实模型、任务动作与复用仍须单独验收，
不把mock通过改写成完整G1在线语义成功。

真实generation/embedding新增均为0。连续账本仍为2768次生成、3420333 generation tokens、
18746 embedding tokens；模拟HTTP与开发代理开销不混入该口径。
失败、首次提案、拒绝后修复、额外Store读取与原生差异均保留；回滚只恢复代码，不能回滚
已经发生的业务副作用。下一步暂定Continue：先验证合同，再冻结更小的语义诊断。

实现后的实际证据：native build_agent重现未知合法UUID实际insert；
同一工具入口的strict跨owner/不存在目标返回error/not_found，Store未改变，后续合法CREATE
返回success/created。InjectedToolCallId经实际ToolNode正确注入，模型可见参数与native一致；
strict工具说明和回执形状为明确的新合同。同步/异步窄检查保留了no_change、真实删除、
缺失删除及Store读/写/删除故障向上抛的结果。统计、准确source身份和检查命令见[机器记录](../data/manifests/next-improvement-wp2-strict-crud-20260927.json)。

工具层每次UPDATE/DELETE增加一次存在性get/aget；不要求额外Host READ调用。
该调用数不是物理磁盘I/O，观测器额外读取也不能被省略；当前不据此宣称净成本下降。


最终检查：实际native集成重现1 passed；strict/条件ID/Store故障相关子集11 passed/10 deselected；
三份受影响测试文件合计102 passed。随后只增加SEARCH内容、ID及跨owner读取断言，
对应sync/async两项再检为2 passed，不把这些重叠集合相加。目标Ruff、四份源码Mypy、
146个活动源码归属（foundation显式38）、两个边界及diff/新增文件EOF空白检查均通过。
原测试使用MockTransport、InMemoryStore与真实本地SQLite checkpoint/合成业务库；
没有共享PostgreSQL或真实模型服务调用。首次新增application测试桩遗漏
`observer.assert_healthy`而失败，修正测试桩后通过；失败记录保留，不冒充生产故障修复。

没有改包声明、CLI包装或依赖锁，不额外本地构建或重跑C0全core；后续实际CI构建单列。
保留原生NULL content行为，空值不会被程序当作DELETE。strict回执只含实际状态与目标ID，
拒绝时不回显提案为已存事实。历史原生工具测试及operator别名路径保持，未改State维护逻辑。

Observed：未知对象更新可在native路径产生新记录；strict路径拒绝并允许后续合法CREATE。
Expected：严格UPDATE只影响当前scope已存在目标，不因此阻止合法新建和后续工作。
实际因果链是Host工具参数→原schema/条件校验→当前Store目标检查→实际变更或错误回执→
后续Host请求。首个被修复的合同断点是缺失目标时仍put，而非模型提案的语义来源。
H1身份混淆仍待模型级诊断，H2合同缺口在局部集成证据中已修复。
混杂为工具说明及回执形状变化、内部get成本、原生operator仍在；都按新行为身份披露。
最小下一步是固定前态/输入的小型语义诊断。决定Continue；不声称unseen收益或Product可用。
代码可退回C1提交，实际世界副作用仍不可借代码回退消除。完整任务结束后才执行用户的
暂停Goal、总体报告和GitHub发布安排。
