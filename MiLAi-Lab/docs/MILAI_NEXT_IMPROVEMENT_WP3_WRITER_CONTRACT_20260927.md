# WP3：共同记忆操作与写入责任

状态：C3a共同能力本地工程验收通过；C3b角色配方、输入和真实实验未冻结、未运行。
本切片基于C2 `93cb3e9cb405c97d52bc807b54f532b2a5b489f3`，分支
`feat/lab-memory-writer-probe-20260927`。执行范围见[当前记录](MILAI_NEXT_IMPROVEMENT_EXECUTION_GOAL.md)。
Root负责协议、合成材料与裁判；Sol唯一负责源码；Astra仅解决下述具体跨层设计冲突，
没有设置常驻审计或第二执行/裁判模型。

## 断点与竞争方案

Host写普通LangMem，原controller只输出State edits；直接关闭一路会丢失存储能力。
State bank的apply还同时承担D0标记与pending确认，不能把它无条件套到新工具循环。
H1：减少独立语义写入者即可改善重复解释；H2：首断点仍在身份/材料消费或生成，即使单写也会错。
当前证据未隔离这两者，不能预告单写模式胜出。

方案A保留两库，复用共同executor与薄边界提案入口；方案B把原controller的LR/LRU、focus、
候选与维护协议整体扩成两库。Astra建议A：B会同时改变太多读取/候选路径，首轮难归因。
暂选A，不迁移存储表示、不添加跨库索引、全库支持图或新的持久journal。

## C3a共同能力合同

- 保留C2 strict manage_memory的参数和实际回执，不复制一套普通记忆CRUD。
- 增加manage_state的CREATE/UPDATE/DELETE及精确read_record；字段仍为原State表示，
  scope由运行配置决定，程序给CREATE分配ID。发现复用memory search、State列表和合法视图。
- 删除State只删除受管记录并处理相关focus/epoch缓存，不调用forget_source或删除原始观察。
  再次删除说明实际不存在；移出工作视图也不意味着旧文本已从transcript消失。
- 共同执行器按原顺序处理调用并返回实际回执；空列表是NO_CHANGE。没有自动镜像、
  语义实体匹配、错误ID修补或将被拒提案包装成存储事实。
- 薄propose_writes入口复用现有调用计数、角色、client与错误记录；一次边界生成覆盖两库。
  不先运行旧State维护再追加一次“翻译成memory”的生成，不自动启用任何新writer policy。

必须保留旧D0合同：旧controller的准确事件集合与编辑位置标记不改变；新路径不能对每个
工具都apply([edit])而把slot重置为0。新路径保留原调用slot与实际生成batch身份，区分
同批重放和不同批生成；可用现有marker的小型可选扩展，不新建持久状态层。
完整提案完成后才确认该批pending；部分失败保留已发生写入和未完成事件。
State已有marker可用于机械重放，普通memory没有语义事件幂等；两库无事务，DELETE也不
借已删除行承诺跨崩溃exactly-once。源码恢复不能回退业务世界。

共同能力先以实际ToolNode/执行器的两库CRUD、READ、空提案、scope、失败、同批多CREATE、
部分失败重放及不同batch同eventset检查验收；旧D0与受影响窄回归保留。通过后独立冻结，
再实现/冻结C3b角色与编排，不以接口存在称写入责任研究完成。

## 后续最小比较的边界

Host主导允许Host写两库并关闭自动语义维护；边界主导允许边界写两库，Host保留读取和
显式触发同一维护入口的途径，立即需求返回实际提交结果；重叠适配版保留Host写memory、
边界写State。普通新来源仍可触发维护/CREATE，不必等Host先提出改写。

先固定一个真实第二次增量前缀和一个无变化反例，两库初态、源材料、工具能力及预算相同，
在隔离副本中执行提案，暂不执行业务。完整overlap包含两个写阶段，**不能用单次输出冒充**；
两前缀×三个系统模式可对应八次生成，而不是预先把“六个输出”当完整三模式比较。
实际次数/分组仍待配方冻结；不设人为六次总硬上限，不把嵌套前缀当独立样本。
语义正确、拒绝、持久变化和成本分别评分，靠不写避免错误不能算完成合法更新。

只有筛查出现值得继续的信号，才选一个候选与重叠适配版运行短CRUD生命周期、真实动作及
部分失败恢复。角色提示、工具呈现、调用编排、读取材料新增及维护时点都是显式系统策略
差异；单一writer policy仍不等于单一持久真值或语义一次消费。
State引用化、局部patch、A/U选择与材料呈现各自另立身份，不揉成一项胜出解释。

C3a检查本身没有真实generation/embedding调用；独立WP6首响应已新增6次/7605 tokens，
截至该切片结束连续账本2774/3427938/18746。全任务结束后按用户要求暂停Goal、
生成总体报告并发布；本共同能力切片不能作为任务提前结束或恢复v27部署的依据。

## C3a实现与验收

[检查机器记录](../data/manifests/next-improvement-wp3-common-writer-20260927.json)
冻结6份源码/测试字节。实际ToolNode通过显式writer_tools启用两库工具；缺省C2路径不启用。
薄factory只把缺ID及CREATE带ID两个已知合同拒绝改成ToolMessage error，Host原wrapper
保持原回执；Store ValueError仍抛出，未捕获为已保存或通用拒绝。没有ID时不输出字符串None。

execute_writes复用工具对象并保留原slot；新增ack_events=False可让成功READ或写入后继续
保留pending，最终由已有ack入口确认。失败总保留pending，部分成功写入不回滚。
旧bank.apply默认marker仍为v1，新batch可选v2；不同真实生成批次与同批重放分开。
State删除只清当前受管记录及相关focus/epoch引用，原来源继续保留。

此前受影响三文件108 passed；其后nonce/重放/invalid-evidence及最后deferred-ack变更由
对应窄检查覆盖：中间D0/Writer 9 passed/69 deselected，最终Writer 7 passed/72 deselected。
这些检查集重叠，不相加。目标Ruff/Mypy、matrix 147活动源码/39 foundation显式、两边界
和新文件EOF检查通过。新文件初始import排序、类型检查错误及一次python命令不存在均
已记录，修复后对应检查通过。无包装/入口/依赖改动，不额外本地构建。
检查使用MockTransport、InMemoryStore及真实本地SQLite checkpoint/合成业务世界，
没有共享PostgreSQL或真实模型调用。真实网络语义与C3b完整角色循环仍未验收。

明确限制：propose_writes只是当前State/事件的一次提案，不交付普通memory正文，
也不续接READ/SEARCH后的下一提案。Host逐工具路径尚无边界batch/ack上下文；
不能宣称该路径具有共同executor的重放保证。C3b必须显式交付同样合法的两库前态、
读取结果和角色编排，再比较责任。两库仍非单一持久真值，memory/DELETE无跨崩溃exactly-once。

Observed：统一工具能力可经实际集成执行，但完整角色编排仍缺失。Expected：三策略都有
合理CRUD/续接途径。首断点是接口能力和编排覆盖，而不是已证明的模型语义改进。
H1责任分散与H2消费生成两解释仍待固定前态比较；通用候选是薄编排，不建新协调模型。
决定Continue，先独立提交共同能力，再完成最小角色与动作续接接线。
