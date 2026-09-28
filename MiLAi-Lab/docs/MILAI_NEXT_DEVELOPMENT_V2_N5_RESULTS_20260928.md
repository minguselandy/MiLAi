# v2 N5 / WP7：连续任务结果与方法收缩

**冻结的六条命令全部完成；G3 生命周期验收未通过，当前 State 优越性主张停止。**
两个原生完整单元均为5/5，但两臂全程State为空，正确业务来自合法完整历史。
构造补充的业务部分失败、闭合回合后恢复和本例owner隔离正确；明确长期保存、提醒形成和退出未完成。
不把正常退出、正确回答或pending清空当作持久维护成功；不把两条自然轨迹的成本差解释成State效果。

## 身份与运行范围

- 方法：`1d7460bd73cbff99122e4014df6bfdd15ababec7`，[PR65](https://github.com/minguselandy/MiLAi/pull/65)。
- [冻结协议](MILAI_NEXT_DEVELOPMENT_V2_N5_SHARED_USE_20260928.md)、[工程检查](../data/manifests/next-development-v2-n5-checks-20260928.json)、[结果机器清单](../data/manifests/next-development-v2-n5-results-20260928.json)。
- 执行freeze SHA256：`dac0d2779d3dd604ad4dc00b19d1a2b8a9742ea9928c47e7c10bec317959c0cd`；四份正式prepare各绑定155个与Git字节一致的源码身份。
- Root串行、每条命令新进程：native H→all；application H phase0→all phase0→H phase1→all phase1。无重试、替换样本、模型Judge、容量/HTTP错误。
- 共30个公开消息回合：原生7×2，构造8×2。每臂一个已暴露arc、一个构造owner组；相关回合不是独立样本。

H_shared与all_shared都拥有strict普通memory＋State完整CRUD、相同业务工具、完整已访问owner历史和read_history。
唯一设计变量是额外预交付State正文none/all；本次51个实际请求均未有State正文可交付，**处理变量没有被实际激活**。
H仍能主动读写State；两臂都不是原生B1，也不是有无State工具消融。
Host仍为Qwen3.6-35B-A3B-FP8，temperature0、4096输出、thinking=false、每消息12次、容量65536；embedding仍bge-m3/1024维。

## 原生任务：完成业务，但未验证记录形成

原MERIT arc3-000的五episode／七条消息、world、业务工具、checker全部保持。

| 条件 | 原生strict | dependent复用 | Host公开回合 | 普通memory / State |
| --- | --- | --- | --- | --- |
| H_shared | 5/5 | 2/2 | 7/7完成 | 全程0 / 0 |
| all_shared | 5/5 | 2/2 | 7/7完成 | 全程0 / 0 |

实际世界包含地址更新、四次确认消息和两笔7256／1882 cents退款；无提前退款。
原checker对两个note episode只检查第一客户，Root另核查第二客户确认金额2713→1882正确，辅助核查不改原生分母。
后续实际HTTP保留修订后的原始用户消息及先前真实回执，模型据此生成正确退款参数，SQLite和最终回答一致。
原`memory_had_fact`仍为false，不能把history成功改记为search_memory或State命中。

零可选记录不自动判本原生任务失败；它说明此短Archive-access任务没有产生State预交付对照，不能证明形成、同ID修订或State成本收益。
两组天然UUID、provider/tool call ID和答复措辞不同，累计tokens相差477；未做或声称完整请求字节相同，不归因于压缩或服务非确定性的具体原因。

## 构造补充：功能结果与持久维护分列

| 冻结消息 | H_shared | all_shared |
| --- | --- | --- |
| 1 Riley长期计划 | 正确确认；两库均空，形成失败 | 同左 |
| 2 Noel长期计划 | 正确确认；两库均空，形成失败 | 同左 |
| 3 本次TEMP＋复用 | 正确2/S-2/fiber；本次TEMP正确 | 同左 |
| 4 独立提醒＋原计划总结 | 原计划正确；未保存提醒 | 未保存提醒，并错误沿用TEMP |
| 5 删除saved reminder | search返回空；没有真实可删记录；却说plan“remains saved” | search返回空；创建普通handling-plan记录，仍无真实提醒删除 |
| 6 一次预约＋标签失败 | 正确实际预约、not_created、真实ID，无重试 | 业务同样正确；普通记录仍写“Nothing is reserved” |
| 7 重启后读回 | get_reservation返回同一实际ID与字段；无重复动作 | 读回和回答正确；过期普通记录仍保留并交付 |
| 8 Noel隔离复用 | 正确5/M-4/foam、自己无预约，无业务调用 | 同左；Riley记录未进入Noel视图 |

两臂初始显式长期计划形成均0/2，提醒形成均0/1；严格完整生命周期均0/1。
State可选且全程不存在，单列NA；普通memory缺失不能掩盖显式保存要求未满足。
all在第5条才创建一条正确的Riley计划；第6条真实预约后其未注明历史时点的“Nothing is reserved”成为过期断言，直到新进程第7条仍未维护。

两组实际SQLite均只有Riley一条预约和一次reserve_and_label尝试，quantity2、storage S-2、fiber cases、label_status=not_created。
phase1 world与本组phase0 world完全相同，读回ID与原真实回执相符。业务工具的ToolMessage status=success不等于标签成功，正文`ok:false`/部分失败被如实使用。
此处恢复是闭合回合/checkpoint之后的进程重开；不是任意崩溃、未提交ToolMessage恢复或通用CREATE exactly-once。
记录删除未被实际执行，因为提醒从未形成；不能把“无可删”记为退出成功。原历史按约保留，无物理遗忘或source清除结论。

## 首断点、竞争解释与决定

| 失败 | Observed / Expected及实际链路 | 首断点与竞争解释 | 通用候选、最小后续与决定 |
| --- | --- | --- | --- |
| 长期形成缺失 | 明确keep/remember进入实际HTTP；返回确认/总结；无CRUD提案；真实Store为空。预期至少一种持久记录可用 | 首断点是Host工具提案。H1：完整历史让模型把确认当成保存；H2：“无业务动作”的简短请求及多工具接口使模型未区分记忆职责。工具/schema和来源缺交付不符合实际证据 | 若另立研究，比较一个明确可验收的写入责任边界与最简单普通memory方法，先用新冻结任务检查形成及后续采用。不能程序自动抄用户正文、强制双写或只改本题措辞重试。当前host_both配方Pivot |
| 临时前缀延续 | all第3条仅本次TEMP约束和第4条当前任务均在真实HTTP；第4条仍TEMP。没有持久TEMP记录 | 首断点是后续答案生成。H1：复制近期助手格式；H2：未正确消费用户“仅此一次”范围。原始约束已交付，排除该轨迹缺历史解释 | 保留反例；以后用独立作用域覆盖任务检验通用消费规则。本轮不添加永久状态/过滤历史来修分；不是State造成的因果证据 |
| 普通记录过期 | 第5条CREATE成功；第6条真实预约部分成功回执进入下一请求；未UPDATE；第7条仍交付“Nothing is reserved”，实际回答依工具正确 | 首断点是业务后语义维护提案。H1：Host以完成业务答复为终点；H2：把记录当静态计划，没有识别同一事项当前状态。真实回执及持久记录均可见 | 可研究单次、范围明确的后续维护责任；必须保持原业务ID/副作用，不通过重做业务制造干净成功。N4只管State版本，不能解决此普通memory漏维护。当前不扩张平台 |
| 删除未验证及保存声称 | search真实返回空；未形成提醒，无DELETE。H仍宣称plan saved；all创建plan后声称无须删提醒 | 删除首断点继承上游形成缺失，H另有无写入依据的保存声称。H1：将历史保留视为saved note；H2：把当前确认当持久提交 | 未来独立冻结需真实形成后再请求精确退出；不得操作员事后补种此批记录来改分。当前退出覆盖不足，非成功 |

混杂因素包括两臂共同完整历史、没有State形成、天然身份字节及措辞分叉、极小且暴露/构造的任务组。
没有证据要求源码修复；本批实际工具、Store、world、checkpoint及交付链符合已冻结机械合同，失败落在提案/语义消费。
不追加控制调用或换样本补一个成功；所有失败费用保留。

## WP7：全部实际成本与复用摊销

| 条件 | 生成calls | 输入tokens | 输出tokens | 生成合计 | embedding calls / tokens | HTTP wall秒 | 进程wall秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| native H | 14 | 42,524 | 645 | 43,169 | 0 / 0 | 10.104 | 16.081 |
| native all | 14 | 42,943 | 703 | 43,646 | 0 / 0 | 10.077 | 16.250 |
| application H | 11 | 23,077 | 505 | 23,582 | 1 / 14 | 6.641 | 15.100 |
| application all | 12 | 27,155 | 557 | 27,712 | 2 / 49 | 7.260 | 15.943 |

全部51个generation provider ID唯一；3个embedding事件按实际trace位置计数，生成和embedding不相混。
均为task_host，无独立A/U/自动维护/Judge。HTTP wall包含本臂生成与embedding；完整进程包含准备、服务接入及实际运行，不是GPU时间。
application两phase费用以唯一请求累计，未把phase1累计会计再次叠加phase0。

| 互斥阶段，生成tokens | native H | native all | application H | application all |
| --- | ---: | ---: | ---: | ---: |
| 前期任务／形成 | 12,769 | 12,824 | 2,737 | 2,735 |
| 维护任务 | 13,595 | 13,781 | 5,961 | 8,697 |
| 使用／复用 | 16,805 | 17,041 | 8,430 | 9,144 |
| 恢复 | — | — | 6,454 | 7,136 |

这些按公开请求阶段归属，不能说全部前期成本只用于记忆形成；未执行的语义维护并未凭空产生一笔维护模型费用。
application维护embedding另为14／49 tokens；3/4/6/7/8是五个计划复用机会，其中第4条费用只归维护一次。

| 计划复用R时累计生成tokens | H | all |
| --- | ---: | ---: |
| native R=1 | 34,355 | 34,715 |
| native R=2 | 43,169 | 43,646 |
| application R=1 | 4,307 | 4,314 |
| application R=2 | 6,081 | 6,098 |
| application R=3 | 15,603 | 19,059 |
| application R=4 | 22,057 | 26,195 |
| application R=5 | 23,582 | 27,712 |

native总生成/R=2为21,584.5／21,823；每五个原生episode为8,633.8／8,729.2。
application总生成/R=5为4,716.4／5,542.4，embedding/R为2.8／9.8。
这些是保留失败的计划机会摊销，不是每个成功生命周期成本，更不是20%等质节省。
all构造生成费用高4,130（17.5%），主要伴随一次额外普通记录创建及后续轨迹；State为空，不归因于预交付正文。

Bank仪表get/search/put分别为native H与all各155/98/28、application H 86/87/22、all 99/92/24。
这些put主要是观察事件/ack元数据，**不能把Bank put数量当成State语义写入数量**。
机器清单另列真实逻辑请求/结果字节、局部CPU/wall、普通记录观测、history/checkpoint观测，未重复相加每回合累计快照。
进程user/system CPU秒依次为6.430/0.572、6.342/0.533、11.702/0.926、11.641/0.878；这是runner子进程，不含远端推理GPU。
物理DB I/O、未测普通写入CPU、GPU小时及金额保持unknown。

N5新增51生成／138,109生成tokens／63 embeddingtokens；连续账本由2830／3,512,213／20,093到
**2881／3,650,322／20,156**，SHA256 `e3f5bf8ad50f7825ad010692164238c9dc14e10c113a39d2f0de383b7e3dce83`。
当前known=charged、unknown usage0；sealed历史逐字未改，没有清零或丢弃过去未知使用。

## 验收与复现

Root逐项核对51个实际HTTP的原始owner消息前缀、截止点、完整合法历史、writer view和工具回执后续交付；
核对原生checker/world和构造真实两phase副作用、ID、记录、临时范围及owner隔离。结论来自实际链路，不来自进程exit0。
源码38项相关窄测及静态/边界/一次build是独立工程证据，未重跑整个套件来替代语义验收。

复现使用方法提交、锁文件和公开`data/diagnostics/next-development-v2-n5-shared-use-r1`字节；
原MERIT源码/arc/world身份由selection固定，必要本地资产和原DSN按协议提供；私密轨迹/数据库不发布。
对native/application各H/all先运行`tools/run_shared_record_use.py prepare`，新run_id及隔离root；Root冻结新的执行身份后按公开execution-order调用`run-merit`或`run-phase --phase 0/1`。
每次实际重跑有新成本和自然ID，不能覆盖本批制品、重用旧namespace或声称精确轨迹复现。评分仍在runtime之外。
本批ignored完整制品根为`artifacts/next-development-v2/n5-shared-use-r1`，机器清单保存对应trace/manifest/journal哈希及正式prepare身份。

N4未触发：未有已交付State版本变更；普通记录漏维护不扩成State反馈功能。
N6未触发：没有可解释State质量或全生命周期节省信号；不启动新任务族、第二模型、权重下载、部署或广泛扫描。
按计划G2/G3裁剪独立A/U和当前State优越性主张，保留通用工具工程与失败证据。**研究总目标尚未实现，Product继续NO-GO。**

## Reflection：总规划§32十项

| 问题 | 本阶段回答 |
| --- | --- |
| 1 支持什么假设 | 短合法完整历史足以支持本原生业务；回执与持久业务ID可跨闭合回合进程重开继续使用。 |
| 2 反驳什么假设 | 反驳“共同Host完整CRUD＋成功回答即可满足显式持久生命周期”；本轮不能支持State预交付收益。 |
| 3 首断点 | 显式形成时未提出写入；临时范围在答案生成时未采用；实际预约之后缺普通记录维护提案。 |
| 4 更简单解释 | 完整历史替代记录即可解释业务成功；无State使所谓prefill差异没有激活，天然轨迹即可解释观测差异。 |
| 5 更简单方法 | 以完整历史或普通memory为强参照，先把单一持久写入/维护职责做可验收，再讨论State选择。 |
| 6 当前复杂度 | 薄装配/隔离/回执仍有工程价值；双库工具未获语义成本收益支持，增加selector、索引、反馈不合理。 |
| 7 修复过拟合风险 | 用Cobalt/TEMP词语、精确ID或动作后固定模板修分风险高；本批未做此类修复。 |
| 8 应加的反例 | 未来独立任务中，保存要求与“无业务动作”并存、临时格式撤销、部分成功后的同事项持久状态、真实形成后再删除。不能事后补种本批。 |
| 9 下一步决定 | 本批收口；Pivot Host-only双库配方，Stop当前State优越性主张；N4/N6均未触发。 |
| 10 理由 | 两臂G3失败且State处理未激活；增加规模或第二模型不能替代当前缺失的形成/维护因果证据。 |

发布前读回方法提交1d7460b的[Fast CI run 36366280183](https://github.com/minguselandy/MiLAi/actions/runs/36366280183)：completed/success。该CI只证明相应源码树工程检查，不补正本轮语义失败。
