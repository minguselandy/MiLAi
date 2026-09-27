# MiLAi 总体实验总结：后续改进计划与暂停交接

日期：2026-09-28（Asia/Shanghai）。范围：MiLAi-Lab / RESEARCH_PROTOTYPE。
**当前实验和实际Goal已暂停；总开发目标未完成，Product仍为NO-GO。**

用户最新要求“暂停当前实验，总结提交到github上，生成实验总结文档”。实际Goal于
2026-09-27 17:41:51 UTC（北京时间2026-09-28 01:41:51）设为`paused`，覆盖此前“任务全部结束后再暂停”的安排。
Root和Sol停止实验/开发，Astra没有活动研究任务；仅整理报告和由Luna high发布Git。
收尾只读核对未发现本任务实验Python进程，共享推理服务未停止或调整，没有新增模型部署/下载。
再次开展开发、实验、下载或部署须有用户新的明确继续指令；历史ACTIVE文案不能恢复授权。

本报告汇总[后续改进计划](MILAI_NEXT_IMPROVEMENT_PLAN_20260927_v1.0.md)已执行部分，承接
[此前总体复盘](MILAI_LSA_REVIEW_OVERALL_EXPERIMENT_REPORT_20260927.md)。
[机器清单](../data/manifests/next-improvement-overall-results-20260928.json)记录费用、证据文件哈希、最新CI和未提交WIP身份。
不同源码、任务和评分分母分别保留，不计算跨批次“总体准确率”。

## 当前能够支持的结论

检查归属、薄runner、严格CRUD、共用写入工具和局部更新接口已经实现并通过对应工程检查。
真实诊断进一步表明：正确State正文和合法工具合同仍不足以保证正确行动；更换标题没有修复主要错误；
一条维护路径可以修好State而留下损坏的ordinary memory。开发接线与语义有效性必须分别验收。

Host负责两种记录与Host/边界重叠维护在当前两个前缀均通过，边界双写在增量前缀失败。
这支持保留较简单的Host双写作为待验证候选，但不足以确定长期写入职责最优方案。
同粒度patch配方在本轮没有质量或总token优势，保留可选接口，停止追加本轮变体。
**尚无稳定unseen收益、独立A/U选择收益、完整生命周期节省或第二模型家族验证。**

## 历史证据及适用范围

| 阶段 | 已有结果 | 不能据此声称 |
| --- | --- | --- |
| SER开发控制 | 13/13 | 未见样本稳定收益 |
| v23原始MERIT两个arc | B1 6/10，A3/A4 7/10 | 没有自然refresh/rebase，不能归因为SER因果收益 |
| v24 formation / reconciliation | 三种形成提示各0/2；修订strict2/3、所需维护0/1 | 不继续措辞微调；CRUD能力不等于正确维护 |
| v25应用 | 8次冻结运行 | 过期动作、容量循环、错误key、虚构ID仍是失败；fresh-session成本差不是压缩效果 |
| v26原生Mem0/B1 | 4/4 vs2/4；生成tokens53852 vs5324，约10.1倍 | 4个已暴露样本、不同系统契约；ADD-only不证明同ID修订 |
| 历史LSA 16轮 | G/L匹配比较各60/78，LRU59/78；完整历史基线相近或更好 | 消息嵌套于情景，不是78个独立样本；旧源码不代表当前实现 |
| 前轮E2条件诊断 | post-event10/12、turn-start11/12 | 固定前缀首响应不等于在线效果 |
| 前轮E2在线比较 | 两组均7/11，完整轨迹均0/2；pre_model54453 vs turn_end33039 tokens | 形成内容、时点、普通memory和错误路径同时变化，不是纯时点或压缩消融 |

历史逐轮数值与锁见[原16轮报告](MILAI_LOCAL_STATE_ATTENTION_OVERALL_EXPERIMENT_REPORT_20260927.md)、
[前轮复盘](MILAI_LSA_REVIEW_OVERALL_EXPERIMENT_REPORT_20260927.md)和
[长期证据地图](MILAI_LONG_HORIZON_EVIDENCE_MAP_20260927.md)。这些费用已在连续账本中，不能再次累计。
旧M1、持久Decision State、结构化ODR和v27第二模型草稿均未因本轮自动重新启用。

## 工程交付与源码身份

所有提交仍在独立stacked draft PR；发布不等于合并main。源码身份如下，旧失败提交和历史锁保留。

| 切片 | 已交付内容 | 已发布源码 / PR |
| --- | --- | --- |
| C0 / WP0 | 相同隔离环境复现main/PR51的14错误/7文件；按真实依赖分配core/foundation/external检查，显式隔离历史资产测试 | `ebf7878fc34bef6f72723ce22e445e5bf712d4f3` / [52](https://github.com/minguselandy/MiLAi/pull/52) |
| C1 / WP1 | 入口转为薄CLI、实现归包内；活动AGENTS与历史快照分开；三组mock请求/顺序差分 | `0d04ca68d0e575919773c24b764c3c0b1832de7e` / [53](https://github.com/minguselandy/MiLAi/pull/53) |
| C2 / WP2 | 可关strict CRUD：CREATE程序生成ID、UPDATE已有目标、删除/NO_CHANGE/scoped读取；native默认保留 | `93cb3e9cb405c97d52bc807b54f532b2a5b489f3` / [54](https://github.com/minguselandy/MiLAi/pull/54) |
| C3a / WP3 | Host和边界共用ordinary memory/State工具；真实错误回执、部分成功、精确事件集合重试 | `2c7b7ddcca952f8d24ec31fe90709f1706ddeb35` / [55](https://github.com/minguselandy/MiLAi/pull/55) |
| WP6续接 | 从六条已保存的真实首响应恢复图，实际ToolNode/SQLite及Host续接，不重生首响应 | `ec34c89d96ecbf6030777b8b23c5dc9773d27ac4` / [56](https://github.com/minguselandy/MiLAi/pull/56) |
| C3b / WP3 | 三种写入职责的完整回合装配、共同正确前态、真实回执交付和费用 | `07aaa3cfc0bec3f914df00a614812aafec967b41` / [57](https://github.com/minguselandy/MiLAi/pull/57) |
| C4 / WP5 | 同State整体替换或唯一字面片段patch；显式版本、证据链接变更、零写拒绝和原D0重试 | `5874ca4ffbf7c08cfb8c4bf8f3108c9b9700696c` / [58](https://github.com/minguselandy/MiLAi/pull/58) |
| strict正文修复 | CREATE/UPDATE缺失或null正文返回错误且零写；DELETE/default/schema保持原边界 | `cf1588ab3f1d1fe8105f3f239cb56f1151e8f5bc` / [59](https://github.com/minguselandy/MiLAi/pull/59) |

工程细节见[WP0](MILAI_NEXT_IMPROVEMENT_WP0_VERIFICATION_20260927.md)、[WP1](MILAI_NEXT_IMPROVEMENT_WP1_REVIEW_20260927.md)、
[WP2](MILAI_NEXT_IMPROVEMENT_WP2_STRICT_CRUD_20260927.md)和[共同writer合同](MILAI_NEXT_IMPROVEMENT_WP3_WRITER_CONTRACT_20260927.md)。
Strict UPDATE没有新增跨记录事务/CAS或语义exactly-once保证；合法ID和成功提交不能认证内容真实。
D0精确事件集合/槽位重试不保证old+new事件混合后的语义纠错，也不保证ordinary memory跨存储原子性。

## WP6：表示方式、实际行动和续接

两个已暴露arc，每个三种条件：原标题、来源精确标题、原来源且无派生State。
六条首响应全部选择业务工具，仅1/6提案正确；实际续接后严格任务仍为**1/6**。
六条工具提案均真实落入隔离SQLite，五个错误提案忠实执行，不能因进程正常退出或回执正确而计任务成功。
三条部分成功均保留真实reservation ID并在标签失败后停止；实际ID/数量/标签回报为6/6，
保守完整回答忠实性为5/6，其中一条把实际目的地S-2说成storage S-2。此指标不能替代严格任务分数。

partial原始/来源标题分别产生错误单数key或加括号key，无State条件的四字段正确；
distinct三条件都未得到要求的4，原始标题还将目的地简写为S-2。
首断点在实际Host行动提案，后续执行没有纠正它。竞争解释包括标题锚定，以及旧助手/普通memory/增量消费干扰。
来源标题没有修复错误，不能继续只调整措辞；保留职责分离和真实前态诊断方向。

raw_sources同时改变State存在与材料标题/角色，并非纯State消融；partial合法旧历史本来已含计划事实。
协议中的早期文字误述已明确更正，原冻结inputs、rubric和顺序未改。每条件只有一个暴露前缀，不作统计推断。
详见[首响应结果](MILAI_NEXT_IMPROVEMENT_WP6_PRESENTATION_20260927.md)与[实际续接结果](MILAI_NEXT_IMPROVEMENT_WP6_CONTINUATION_20260928.md)。
合计12次生成、16451 tokens、327 embedding tokens；续接只计新增调用，首响应费用没有重复计入。

## C3b：写入职责比较

一个已暴露Cobalt arc的保持/二次增量两个前缀，三种策略共六条完整回合。
共同实际前态ordinary memory与State均为3；同合法历史、当前正文、ID目录和来源权限，增量应沿原ID得到4。
各组角色、工具呈现和维护时点仍有差异，因此是写入策略比较。

| 策略 | strict | Host调用 / tokens | 控制调用 / tokens | 全生成tokens | embedding tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Host双写 | 2/2 | 4 /11629 | 0 /0 | 11629 | 75 |
| 边界双写 | 1/2 | 3 /8179 | 3 /9349 | 17528 | 50 |
| Host普通memory＋turn_end State | 2/2 | 3 /7185 | 2 /6236 | 13421 | 75 |

失败链：真实模型响应同时提出memory/State UPDATE却省略content；ordinary memory旧合同写入null，
State合同拒绝。实际错误和null记录交付Host，Host再次请求维护；后续控制只修好State，ordinary memory仍为null。
Host宣告更新完成，未满足两种记录和有用回答的冻结判据。原始HTTP证明缺字段不是parser丢失。
第一断点是提案缺正文，集成层允许null写放大损坏；部分成功后模型只关注State也是竞争解释，不能据单例确证。

随后独立strict正文修复用零模型旧工具复现与同步/异步、ToolNode和共享executor验证，缺失/null CREATE或UPDATE现在返回错误并零写。
native参数schema相同，仅共同工具说明增加正文要求；有效操作、DELETE和native默认保持。
该修复未重跑或替换C3b失败，也没有新增语义效果样本。

决定：保留Host双写与overlap，停止把边界双写视为已可靠；先修确定合同缺口。
Host双写这两例总tokens比overlap少约13.4%，但增量单例9045高于8200，不能宣称生命周期20%收益或稳定节省。
长期形成、临时约束、双owner、复用和真实动作仍待X5。详见[写入策略结果](MILAI_NEXT_IMPROVEMENT_WP3_WRITER_POLICY_20260928.md)。

## C4：同粒度整体替换与普通patch

一个已暴露Summit arc构造两个固定前缀：只变更access时间；吸收WP6已经实际产生的部分业务结果。
两臂各一次提案：整体替换，或允许整体回退的普通patch。没有独立第三算法。
各臂同一前缀的实际材料payload相同，schema差异是处理的一部分。

| 合同 | 维护正确 | 生成调用 | prompt / completion tokens | 总tokens |
| --- | ---: | ---: | ---: | ---: |
| replace | 2/2 | 2 | 2863 /604 | 3467 |
| patch_or_replace | 1/2 | 2 | 3097 /578 | 3675 |

简单时间更新两臂均正确保留其余正文；patch少62输出tokens，却多117输入tokens，合计多55。
部分结果失败臂选择整体替换回退，拟写正文合理，但要求移除一个source catalog可见、当前State并未绑定的证据链接。
严格合同返回explicit_update_invalid，State/revision零写、pending保留。不是literal patch匹配失败。
Expected是实际预订/标签失败入State、解除旧待办且保留无关计划；“拒绝而保持旧值”不算完成必要维护。

竞争解释为模型混淆“可见来源”与“当前链接”，或严格拒绝已不存在的链接增加了接口摩擦。
不在看到结果后放宽合同；若未来有实际需求，可另冻同等错误续接机会，不能改写这次单提案失败。
本轮patch配方多208 tokens（约6%），没有优势信号，决定Pivot默认收益主张、保留可选接口、停止变体。
这些是四条真实Store维护诊断，没有新增Host回答或业务动作，不是完整任务3/4。
详见[WP5结果](MILAI_NEXT_IMPROVEMENT_WP5_LOCAL_UPDATE_20260927.md)。

## 连续费用与测量边界

| 口径 | generation calls | generation tokens | embedding tokens |
| --- | ---: | ---: | ---: |
| 本计划起点 | 2768 | 3420333 | 18746 |
| WP6首响应 | 6 | 7605 | 0 |
| WP6实际续接 | 6 | 8846 | 327 |
| C3b完整写入职责 | 15 | 42578 | 200 |
| C4固定前态更新 | 4 | 7142 | 0 |
| C5准备、strict guard验证、报告收尾 | 0 | 0 | 0 |
| **本计划新增** | **31** | **66171** | **527** |
| **暂停时连续账本** | **2799** | **3486504** | **19273** |

起点SHA256：`a9d4c681e2bee395c170a4672b4895a442522df47951c9a043e9f6b3a32e3580`。
终点SHA256：`bfc2768c4cd6d92ce650bc65e2018b8d23a404de0c9a61e07e88ccbd1c43d0c6`。
权威账本仍为原checkout的`MiLAi-Lab/artifacts/ser-v20/budget.json`，sealed历史未变，未清零；generation/embedding unknown usage均0。
Root串行执行全部真实调用，失败、修正、空维护及准备embedding均保留；Judge调用0。
527 embedding tokens分为WP6恢复327、C3b seed150和真实更新50；C4 State-only seed禁用索引，确实没有embedding。
开发代理、CI/依赖开销不混入实验token，不虚构货币或GPU总成本。

既有Host为Qwen3.6-35B-A3B-FP8，temperature0、Host max_tokens4096、thinking=false、容量65536，
每公开消息Host最多12次，实际模型HTTP并发1；冻结控制调用另有2048输出/13次上限。
Embedding为bge-m3/1024维。现有7860/7861服务配置未更改，没有为了分数调整parser、上下文或温度。

C3b生成HTTP wall为16.282秒、embedding0.491秒；C4生成8.523秒。
Store调用、序列化逻辑字节、CPU/wall及observer分别保留在逐例清单；seed和观测读取的重叠不能相加。
没有单独测量的ordinary memory写CPU、自动边界观测缺口维持未知，不填0。
上述网络时间不等于端到端生命周期延迟，逻辑字节不等于物理I/O或磁盘压缩。
本轮没有形成—维护—复用摊销全周期测量，因此不能验收WP7或20%生命周期成本目标。

## 已完成检查与保留失败

C0修复Fast与Full实际通过，Full共21个job成功；C1、C2、C3a修复、WP6续接、C3b实际Fast均通过。
C0首次发布因未声明历史MERIT资产失败、C3a首次因顶层可选依赖阻断core收集失败，均保留原失败后独立修复。
成功的foundation/external不能覆盖当时失败的core。C1请求等价只限记录的三组mock和允许的规范化，并非全面形式证明。

收尾只读核实的最新远端结果如下，没有启动或重跑工作流：

| 发布源码 | 实际Fast / 最终gate | core结果 | foundation结果 | 实际CI组合提交 |
| --- | --- | --- | --- | --- |
| C4 5874ca4 | [36336941840](https://github.com/minguselandy/MiLAi/actions/runs/36336941840) /108671892705，success | 5114 passed /142 skipped /14 deselected | 196 passed /1 deselected | `8462a6daccf9d3b604e63b834abcbe1dbaabe79d` |
| strict正文 cf1588a | [36337502319](https://github.com/minguselandy/MiLAi/actions/runs/36337502319) /108672382540，success | 5114 passed /142 skipped /14 deselected | 198 passed /1 deselected | `3594eef1f06f5c2ef41bae5335ee868f0b73070b` |

两个run的external、边界、conformance和必要wheel/sdist构建均成功；声明的Product/Archive/tree-identity job skipped不算通过。
foundation计数是各命令已通过项之和，不能与core或局部重复检查相加为独立研究样本。
严格正文followup本地是7项窄测、最后断言改动重跑其中2项，不能称9项独立测试；无入口/包装变化未重复本地build。
本次报告仅检查链接、JSON、证据哈希和diff，不运行pytest、构建或真实模型。
新报告分支的自动CI若产生，是另一提交的工程检查，不替代上表源码身份，也不恢复实验。

## 未完成项与保留现场

| 工作 | 暂停状态 |
| --- | --- |
| WP4/C5/X3读取、X4更新选择、G2 | NOT_DONE / NOT_RUN；输入准备和部分源码WIP，尚无完整执行冻结 |
| 有限交付版本反馈 | 有界设计而已；实际HTTP交付、版本失效、恢复/超限检查及效果均未实现验收 |
| WP3长期写入职责 | 两前缀六回合已完成；长期形成、owner/临时要求和后续动作不完整 |
| WP7生命周期费用与复用摊销 | NOT_DONE |
| X5/G3/C6连续在线强基线比较 | NOT_RUN；11消息候选草案未冻结、未实现，不是执行授权 |
| G4模板未见、强外部对照、参数/密度鲁棒性 | NOT_TRIGGERED |
| 第二独立模型家族、稳定unseen收益 | NOT_RUN / 未证明 |
| Product迁移 | NO-GO |

原开发树`MiLAi-worktrees/next-improvement`，分支`feat/lab-state-selection-20260928`，HEAD为cf1588a。
保留未提交的`src/milai_lab/methods/local_state_attention/{controller,protocol}.py`两处修改：
仅抽取共同selector提示/载荷函数并接线，未经任何C5检查，不声称语义或字节等价已验证。
另有read-selection和update-selection两目录的inputs/config/rubric，共六个未跟踪文件。
输入字节登记不等于源码、schema、scorer/执行identity已整体冻结；六份文件和两处源码都不进入本次发布。
[WP4状态](MILAI_NEXT_IMPROVEMENT_WP4_SELECTION_20260928.md)与机器清单保留位置/哈希。
ignored X5草案、元数据、日志和原main的旧v27草稿原地保留，不删除，不自动纳入正式方案。

## 复现和发布交接

报告使用干净独立工作树`MiLAi-worktrees/next-improvement-closeout`，从已发布cf1588a建立
`docs/lab-next-improvement-pause-20260928`分支。原开发树保留WIP，main仍为
`9515017a5dfaba6b6e306fa778fd20f4383b6e35`；旧PR51及stacked PR不关闭、不自动合并。
Root写报告和状态文档，Luna high按明确白名单commit/push并核对远端SHA与工作树。
本次不改变Schema/API/权限/Canonical行为，也不修改运行源码；报告自身Git身份以发布提交为准，避免自引用哈希。

每批结果按上表实际方法commit及对应freeze复现；现有源码无须同时匹配全部旧锁。
公开输入、rubric、精简结果和校验身份随各结果文档提供，运行时不读取评分rubric。
WP6续接依赖原六份真实首响应制品；缺少这些本地ignored制品时不能声称仅凭公共文件完成字节一致复现。
业务世界是合成任务的真实隔离SQLite副作用，不能称外部物流实际履约或Product验收。
私密轨迹、DSN、数据库、环境、模型权重、缓存和构建制品继续排除Git。
未来若明确恢复，先核实Goal/工作树/服务和成本，再完成最小实现及检查、冻结新协议；不续跑过时草稿，不清零账本。
