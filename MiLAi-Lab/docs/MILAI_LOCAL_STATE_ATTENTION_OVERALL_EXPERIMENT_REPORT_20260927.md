# MiLAi 总体实验报告：长期记忆与 Local State–Attention

日期：2026-09-27。状态：**按用户要求暂停，研究总目标未完成，Product仍为NO-GO。**
最后执行源码为 `bc5a5c8b98db8b965432759bdea367c9475869b1`。正在进行的滑窗摘要切片已
完成实现、80项相关检查、构建与四条冻结轨迹；实际Goal已设为paused。后续仅整理报告和
GitHub发布，不自动启动开发、实验、下载或部署。旧模型敏感性v27草稿继续保留且未恢复。

本报告详细汇总本次Local State–Attention（LSA）全部16轮开发、诊断及比较，并把前序
SER、生命周期、应用和Mem0结果作为独立背景。[总体数据与成本清单](../data/manifests/local-state-attention-overall-results-20260927.json)
绑定各轮结果哈希；[原规划](MILAI_LOCAL_STATE_ATTENTION_DEVELOPMENT_EXPERIMENT_PLAN_20260927.md)
和[执行Goal](MILAI_LOCAL_STATE_ATTENTION_EXECUTION_GOAL.md)保留全部范围与过程。不同源码、
输入、分母和诊断类型分别报告，不拼接最佳轨迹或合成一个跨阶段“总准确率”。

## 1. 当前可以支持的结论

已实现并运行公开LangGraph/LangMem上的独立State维护、局部选择、真实来源展开、跨进程
恢复、公共checkpoint历史以及滑动窗口摘要。模型请求、持久化、后续交付和业务副作用
可以逐段核查；各阶段失败与成本保留。工程接线已具备继续研究的条件。

**目前没有充分证据证明局部State、读写注意力或滑窗摘要带来稳定的未见收益。**
最大一批同源比较中G/L各60/78，LRU59/78，LRU生成成本最高。后续完整历史对照表明，
在这两条短历史脚本中，完整原始上下文可以达到相近或更好的行为结果，且成本较低。
仍有局部正例：精确交付原始部分失败回执后，模型能读取真实对象并沿原ID补完标签。
这些正例限定在相应冻结轨迹，不证明总体可靠性。

主要失败分属不同层：维护重复应用或丢失无关事实、选择遗漏、Host把正确材料改写成
错误业务key、先声称行动已发生、对回执未支持的事实作断言。增加调用或更清楚的短提示
没有稳定消除它们；不能把所有失败都归因于检索或State形成。

## 2. 前序MiLAi证据背景

| 阶段 | 已有结果 | 可解释边界 |
| --- | --- | --- |
| SER开发控制 | 最终13/13 | 开发控制通过，不等于未见效果 |
| v23原生MERIT | B1 6/10，A3/A4各7/10 | 没有自然refresh/rebase；分差不能当SER因果收益 |
| v24 formation | 三种提示候选均0/2 | 已停止这些措辞路线 |
| v24 reconciliation | R1/R2 strict2/3，所需维护0/1 | CRUD存在不等于语义维护成功 |
| v25应用 | 八条冻结运行 | 包含过期行动、容量循环、错误key、虚构ID；新session差异不能称压缩收益 |
| v26原生Mem0 vs B1 | Mem0 4/4，B1 2/4；tokens53852/5324 | 四个已暴露formation样本，系统契约不同；约10.1倍开销，ADD-only不证明同ID修订 |

来源：[SER控制](MILAI_SER_V21_FINAL_RESULTS_20260927.md)、
[v23](MILAI_SER_V23_RESULTS_20260927.md)、
[v24](MILAI_LIFECYCLE_V24_RECONCILIATION_R2_RESULTS_20260927.md)、
[v25](MILAI_APPLICATION_V25_RESULTS_20260927.md)、
[v26](MILAI_EXTERNAL_MEMORY_V26_RESULTS_20260927.md)。旧M1、持久Decision State及结构化ODR
没有因本轮研究自动重新启用；历史锁与更早成本链继续封存。

## 3. LSA方法及比较口径

G为一个全局工作笔记，L为全部局部State候选维护/呈现，LR在L维护后独立选择读取集合A，
LRU先选择更新集合U再维护并独立选择A。State由真实事件在线形成，不由rubric给定事项
ID或正确分组。机械删除依赖与模型声明的evidence_refs分离；合法引用不等于语义支持。

方法通过LangGraph公开hook只改变发出请求的副本，保留原始checkpoint、用户/工具消息
及调用JSON。原始source与State按run/arm/user/workspace隔离，部分失败的真实副作用不
回滚或盲目重放。公共历史接口从实际已访checkpoint读取完整assistant/tool链，不读私有
observer档案或未来脚本。完整历史和摘要两新臂共享read_history工具，增加的工具目录
明确披露，不能称为原B1工具合同的完全不变版本。

Host始终为现有Qwen3.6-35B-A3B-FP8，temperature0、max_tokens4096、thinking=false、
context65536，每公开消息Host最多12次；控制输出2048、控制容量13，实际HTTP并发1。
embedding为bge-m3/1024维。没有更改vLLM配置，也没有部署第二模型。开发代理与实验
Host的模型、职责和成本分别处理。runtime未读取gold/rubric，不硬编码评测答案或对象ID。

## 4. 主要结果

### 同源重复比较：六模板×三臂×两次

[P3 matched R1](MILAI_LOCAL_STATE_ATTENTION_P3_MATCHED_R1_RESULTS_20260927.md)预定36条轨迹、
234条消息。35条完整，1条首消息因原生memory update缺ID中断，后五消息未运行但保留
在原分母；没有重跑该失败或替换输入。每臂12条轨迹、78条消息。

| 方法 | strict消息 | 完整轨迹 | 生成调用 | generation tokens |
| --- | ---: | ---: | ---: | ---: |
| G | 60/78 | 2/12 | 234 | 414859 |
| L | 60/78 | 3/12 | 246 | 354030 |
| LRU | 59/78 | 4/12 | 442 | 472853 |

消息分数与整轨迹分数给出不同排序，必须同时保留。LRU约提交全bank正文的69.1%，仍需
全Store扫描；不能把正文候选减少称为物理I/O节省。该实现的维护输入当时还含current_task，
重复施加用户增量的问题在后续另修；此历史批次的数值不能冒充最终源码验证。

### LR、完整历史和摘要的小接线

| 独立冻结批次 | 方法 | strict消息 | 完整轨迹 | generation tokens |
| --- | --- | ---: | ---: | ---: |
| LR wiring R1 | L / LR / LRU | 9/12 /10/12 /8/12 | 0/2 /1/2 /0/2 | 44872 /53386 /55262 |
| History wiring R1 | full / LR history | 10/12 /10/12 | 0/2 /1/2 | 18508 /56198 |
| Window summary R1 | window summary / full | 9/12 /10/12 | 0/2 /1/2 | 19703 /18501 |

来源：[LR](MILAI_LOCAL_STATE_ATTENTION_LR_WIRING_R1_RESULTS_20260927.md)、
[公共历史](MILAI_LOCAL_STATE_ATTENTION_HISTORY_WIRING_R1_RESULTS_20260927.md)、
[滑窗摘要](MILAI_LOCAL_STATE_ATTENTION_WINDOW_SUMMARY_WIRING_R1_RESULTS_20260927.md)。每格只有一次
已暴露轨迹，不能跨批次挑选较高结果。LR小接线中L/LRU初始合成一张综合卡，LR形成三卡，
在线分组分叉阻止纯A/U归因；LRU仍提交约93%的全bank正文。

公共历史批次的LR总tokens约为full的3.04倍。最后摘要批次只减少656个Host prompt tokens
（3.74%），加上四次摘要调用后总generation tokens多1202（6.50%），且摘要丢失简报事实。
短历史均远未触及窗口容量；不能推广为所有长历史场景中摘要均无价值。

最后批次full的10/12包括一个明确公开的语义评分边界：恢复操作真实成功，但回答声称
“No physical dispatch has occurred”，回执未提供该观察且原请求禁止推断physical dispatch。
若辅助口径忽略此越界断言，只看动作与要求字段，则为11/12；主strict仍为10/12。两臂
真实同ID恢复均通过。评分不会把成功数据库操作和完整回答可信度混为一项。

### 其他开发与诊断轮次

| 轮次 | 结果与决策 |
| --- | --- |
| P1 R1 | schema允许省略title而bank要求title，三次控制输出均未形成State；保留失败后修字段契约 |
| P1 R2 | 原两轨迹9/12，完整1/2；发现预先虚构行动、读取遗漏、Host参数错误及空evidence_refs |
| P2 R1 | 12个方法首响应：3直接正确、2中间memory步、7错误；另3诊断；不执行业务、不换算端到端分数 |
| P1 R3 | 原5/12，附加报告1/2，原完整0/2；保持容量失败与跳过，停止来源合同措辞微调 |
| P1 R4 | all/focus原各7/12，完整均0/2；附加报告2/2与1/2 |
| P1 R5 | 精确来源展开on4/6、off3/6，完整均0/1；on真实get found并同ID补标签，错误初始key仍失败 |
| P3 wiring R1 | G11/12、L9/12；完整1/2与0/2，仍是小接线 |
| P3 wiring R2 | G9/12、L8/12、LRU6/12；发现U阻断创建机会 |
| P3 wiring R3 | 修复共享创建机会后LRU8/12，完整0/2；不替换R2 |
| maintenance-events R1 | 去掉维护输入current_task；原高耦合G/L/LRU各6/6，新distinct事件反例LRU3/5；首断点转移到Host |
| Host snapshot R1 | 固定首响应诊断中时点/身份候选有局部正例，无工具执行；不是端到端改进 |
| Host snapshot R2 | 六个反例未通过准入：漏维护/错误memory历史/真实回执限定仍有失败；未部署候选、不再措辞微调 |

各轮结果与精简数据均由总体manifest链接。诊断只改变临时视图或固定前缀时，明确单列，
不与在线方法成功数合并。原生memory条件参数错误已改为局部ToolMessage验证错误；
后续批次没有自然触发该错误，不声称它的语义恢复收益已经实测。

## 5. 主要因果链与剩余混杂

**维护输入重复施加变化。** 旧维护请求同时含当前任务与新工具观察，模型在tool-only回合
重新应用用户增量。通用修复为events-only维护；原高耦合三臂均通过，但不同真实事件的
相同“加一”反例仍失败。真实State已从3改到4，随后Host写普通memory为5，说明后者
不能再归因于维护器没有收到新事件。

**无关事实保持失败。** 综合卡会在用户排除某项行动时遗失该项原安排；最后滚动摘要在
第三次更新时，也把先前仍完整的R-3/14:30/step-free删掉。实际输入、模型输出、Store写入
及后续Host使用均已定位，之后Host虚构Room101/09:00/main entrance。可能机制为近因
偏重或把增量更新当作仅总结新回合；不能从输出确定模型内部原因。过程无容量截断。

**正确材料未转成精确行为。** 多批中原始对象名已在实际HTTP，却被Host改成单数或下划线
键并真实写入数据库。数量、地点和包装正确不补偿key错误；沿错误key成功恢复也不追补
初始失败。现有工具已要求精确复制完整名称，重复添加这一提示不是新修复。

**成功接线与语义可靠性分离。** 真实回执来源展开能帮助部分失败恢复；当前版本、引用、
Store提交和正常退出均不证明正文正确。State曾在工具发生前声称attempted，并把部分已
提交预约概括为failed。完整历史可达也不能保证Host主动调用历史工具核查；两个历史批次
都没有自然read_history调用。删除、截断与fallback等离线边界不得表述成真实触发结果。

## 6. 全部成本

| LSA轮次 | 生成调用 | generation tokens | embedding tokens |
| --- | ---: | ---: | ---: |
| P1 R1 | 6 | 5489 | 0 |
| P1 R2 | 34 | 34388 | 9 |
| P2 R1 | 19 | 17520 | 768 |
| P1 R3 | 61 | 84307 | 181 |
| P1 R4 | 96 | 115854 | 256 |
| P1 R5 | 40 | 46862 | 88 |
| P3 wiring R1 | 72 | 93431 | 173 |
| P3 wiring R2 | 130 | 142179 | 70 |
| P3 wiring R3 | 61 | 51693 | 0 |
| P3 matched R1 | 922 | 1241742 | 6173 |
| maintenance-events R1 | 108 | 135012 | 848 |
| Host snapshot R1 | 6 | 8062 | 0 |
| Host snapshot R2 | 6 | 11093 | 0 |
| LR wiring R1 | 150 | 153520 | 154 |
| History wiring R1 | 67 | 74706 | 108 |
| Window summary R1 | 36 | 38204 | 0 |
| **本LSA Goal合计** | **1814** | **2254062** | **8828** |

连续账本 `artifacts/ser-v20/budget.json` 从863/1042729/9617增加至
**2677 generation calls /3296791 generation tokens /18445 embedding tokens**，unknown usage0。
所有失败、重试、空提取及控制/Host开销包含在内。更早的sealed history链未清零，未将其
重复加进本表；这也不是所有历史MiLAi阶段和开发代理的统一总成本。既往SER exact-version
reads107单独保留，LSA Store/checkpoint I/O另计，不混成同一种读取。

来源、State、索引、checkpoint、journal与business world都是真实资源。各轮manifest记录
Store操作、逻辑字节、CPU/HTTP墙钟等可观测量；早期缺失项不追造。候选正文减少不等于
底层扫描减少；完整历史与摘要保留原checkpoint，不能声称物理存储压缩。开发代理tokens
不在实验账本；未虚构货币价格或GPU摊销数值。

## 7. 完成状态及未完成项

| 项目 | 暂停时状态 |
| --- | --- |
| 核心bank、共享维护、G/L/LR/LRU、来源展开、公共history/summary | 已实现并有真实冻结轨迹；语义失败保留 |
| 跨进程/新session、双owner、真实部分失败同ID恢复 | 已在小规模轨迹验证；非长期可靠性保证 |
| P2固定bank/错误视图诊断与P3同源重复比较 | 已执行；未证明稳定独立收益 |
| R | 仅完成薄目录＋临时重建设计建议，未实现/运行 |
| U=A、剩余六项消融、在线A6纠错与模板留出 | 未完成；不能以已有局部诊断替代 |
| 真实归档/重新激活、共享原子更新组 | 未完成；语义关闭/重开不等于archived生命周期 |
| 全链授权删除及物理清除、真实未知结果边界恢复 | 未完成；现有tombstone屏蔽和已知部分失败不等价 |
| 新MERIT selection与独立MemoryArena评估/重复 | NOT_RUN；MERIT seeds0–4已暴露，不得称unseen |
| 少量代表N/d/a/r/H规模曲线、第二独立模型族 | NOT_RUN；无第二推理端点/模型部署 |
| 无模板模拟协作workload、完整论文证据包 | 未完成；本报告是暂停快照 |
| MiLAi-Product迁移/发布 | NO-GO |

MemoryArena固定源码/数据及环境资源已准备，但runtime/gold隔离适配与原生评分尚未完成。
资源在ignored外部目录，数据许可不自动覆盖参考实现及外部CSV。没有生成新MERIT题目来
挑选有利样本。训练selector、大范围参数扫描及条件性分支未自动展开。

## 8. 暂停交接与复现入口

最后切片源码已发布；各历史结果按各自source commit复现，不要求当前源码匹配所有旧锁。
实际方法配置、输入与rubric哈希、阶段顺序、隔离方式和原始证据哈希见每轮protocol/results。
[共同历史复现说明](MILAI_LOCAL_STATE_ATTENTION_HISTORY_WIRING_R1_RESULTS_20260927.md#复现)及
[最后摘要切片](MILAI_LOCAL_STATE_ATTENTION_WINDOW_SUMMARY_WIRING_R1_RESULTS_20260927.md)提供命令与
参数。复现须用新run/namespace，成本续记，不覆盖原结果。原始私密轨迹、DSN、数据库、
模型、环境、缓存、构建产物继续排除Git；公开发布源码、配置、合成输入、rubric、精简结果
和文档。未跟踪 `docs/MILAI_MODEL_SENSITIVITY_V27_GOAL.md` 保留，不当正式协议发布。

用户暂停指令优先于旧文档的ACTIVE及“下一步”。当前没有继续实验的授权。若以后明确
恢复，应从未完成项选择最小可验证步骤，并先核对实际Goal、工作树、服务和账本；本报告
中的候选设计与复现命令均不自动触发执行。
