# Contextual user memory v4 开发与执行记录

日期：2026-09-24。范围以 [Goal v4](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v4.0_20260924.md) 为准；研究原型，不代表 Product 行为。v3 Goal、报告、六批运行和原始数据保持原样。

最终状态：`implementation=IMPLEMENTED_AND_NARROWLY_CHECKED`，`execution=DEFAULT_FULL_STALE_AND_FIXED_C_SCOPE_COMPLETE`，`mechanism_coverage=ONE_H2_FIVE_STAGE_CHAIN_CONFIRMED`，`effect=NO_ESTABLISHED_BENEFIT_H2_COST_INCREASE`。总 Goal 为 `COMPLETE_WITH_NEGATIVE_OR_INCONCLUSIVE_EFFECT`。固定 C 四题中三题完成三臂比较，一题因未提出相关更新停在摄入；`v11_001003` 走通五环节，但没有 H2 独立收益证据。最新默认 smoke 再次误把停止活动当成删除请求，原生评分未通过。完成的是本轮有限开发与诊断合同，不代表语义可靠或可用于生产。下文保留各阶段当时状态，最终结果见末节。

## 已实现的合同

- 方法 checkpoint 身份 `contextual-user-memory-v7`；首次执行协议 `contextual-ingestion-handles-v1`，明确失败修复后为 `contextual-ingestion-handles-v2`。v2 将生成 schema 的引用字段限制到已交付句柄枚举，多个来源只能放入 source_refs 数组。来源短句柄绑定真实角色、完整内容散列及实际交付范围；记录句柄绑定准确旧版本。未知句柄拒绝，不自动扩大范围或覆盖最新版本。
- 仅稳定去重声明的引用集合。提案先冻结并校验，ordinary 按操作、support 按局部组保存回执、别名及 checkpoint。来源接收、提案有效、局部提交和维护结清分别记录；部分失败不会推进为已完成。有效提案中断后继续未提交项，不重请 Host 生成。已记录冲突、截断或远端请求不明状态要求有理由的显式修复。
- 使用本地固定 Qwen tokenizer 和聊天模板计算完整请求，单列输出预留与安全余量；服务端回执记录实际 prompt/completion 和计数误差。自然会话／消息分批，超长消息用连续准确范围，覆盖校验拒绝缺口、重叠和漏项。
- `QueryContext` 在 `contextual=False` 且无 `memory_state` 时同样工作；ordinary 与 support 共用匹配、不匹配、未知的三态条件判断。问题日期与 known_at 分开；Host 的条件引用核对出处，但程序不认证推断为真。
- 共享提示允许依据历史约束提出新建议，禁止冒充过去事实。关系变化后的材料到差量交付窄检查通过，保留原有正文省略逻辑。
- 配置指定运行目录外的累计预算及固定 scope；换目录不重置消费。摄入保留后续作答／Judge 额度。冻结源码内容、配置、协议、提示、模型、tokenizer、边界及答案身份；不以未提交工作树的 HEAD 代替文件身份。
- 增补提交／复制、检索和材料组装计时以及材料 token 分项。检索含 embedding 等待；嵌套计时及独立 token 分项不可直接相加。未据此优化深拷贝或扩大结构重构。

## 验证包 A 与旧失败

离线诊断：`artifacts/contextual-user-memory/v4-offline-audit/diagnostic.json`，零模型调用。

旧 STALE trace 确认重复 source_refs、4096 输出截断、准确范围拒绝及同批多组更新同一旧版本导致的冲突。旧 EAGER／PENDING／RAW_EVIDENCE 局部组拒绝分别为 5／6／3；短句柄和集合规范化消除机械表达负担，版本冲突继续如实拒绝。旧 H5 多轮调用主要包含对同一来源的增量范围展开，不能全部归为完全重复请求。

恢复检查演示第一组提交、第二组中断后重启：保留第一组、恢复别名、只执行剩余项、无重复对象或新 Host 请求。另有同批版本冲突保留先行成功操作的检查。三态条件、原始范围覆盖、预算预留和关系新鲜度检查均使用必要的窄用例。

本轮检查分切片执行，计数存在重叠，不相加当作一次全套回归：条件／摄入／runner／capacity／delivery 集成25条通过；最终 Host18条、runner14条、预算3条、CLI身份2条通过。来源可见范围补充后的条件／delivery／摄入9条通过；闭合句柄语法的摄入3条通过。受影响 Ruff／mypy 及新增模块的依赖边界检查通过。未运行全仓 pytest、包构建或大规模 benchmark。

## 新执行范围与预算

| 配置 | 完整输入规划 | 生成累计上限 | embedding 上限 | 状态 |
| --- | --- | --- | --- | --- |
| `configs/contextual-memory-v4-default.json` | 已暴露 v11_000977，12 消息／7933 字符／1 批 | 24 请求／150000 tokens | 200000 tokens | 完整执行，原生评分未通过 |
| `configs/contextual-memory-v4-stale-ordinary-repair.json`（接续原 ordinary 配置） | 固定场景全部 594 消息／673289 字符／50 会话，50 批、独立三问 | 96 请求／1000000 tokens | 500000 tokens | 完整执行与有效联合评分，1／3 |

Host/Judge 继续使用固定本地 vLLM Qwen3.6-35B-A3B-FP8；上下文 65536，输出 4096，输入余量 512，源批目标 6000 tokens。STALE Judge 输出预留 2048。所有失败与 unknown usage 保留；部署查询成本和离线评分成本分列。无额外候选、未用确认题或 formal 恢复。

默认真实制品：`artifacts/contextual-user-memory/v4-default-smoke-1`。历史 3／3 操作提交且结清；生成共 9 请求／56577 tokens，无 unknown usage，embedding 2 请求／2073 tokens。历史生成 3188（输入2820／输出368），作答 52364（输入47659／输出4705），Judge 1025（输入950／输出75）。完整计数以该目录 summary 和运行目录外累计 budget 为准。

默认 Host 正常退出且答案可评分，但最终答案只确认记忆删除，未完成当前用户任务。原生 `uses_latest_preference=0`、`outdated_preference_contamination=0`、`valid_selection_pass=0`；不是执行异常，也不是通过。作答含一次截断输出和后续删除，受管 trace 已按既有删除合同擦除正文，只保留费用及最小删除回执，不恢复被擦除副本。材料交付累计正文1153 tokens、引用/状态5392 tokens，说明元数据和多轮展开仍有明显成本，不能宣称总体效率已经解决。

首次 STALE 在第5批拒绝 `source_ref="s0,s2,s4,s6,s8"`：把多个句柄拼入单字段，未知句柄解析拒绝，失败批零提交。前4批10项操作结清。该尝试消耗5次生成／28379 tokens、embedding13972 tokens；三问未作答，不具备联合评分条件，未请求 Judge。旧目录 `v4-stale-ordinary-1` 冻结保留。

一次有依据修复：v2 闭合句柄语法并说明单字段／数组区别；配置 `contextual-memory-v4-stale-ordinary-repair.json` 固定旧 progress 与 batches 散列，显式导入成功前缀、旧 checkpoint 和零提交失败批，保持完整自然边界，从第5批重新提案。新目录只计新请求，包总额仍用原累计账。来源重新发布使用适配器的原始消息序号，避免未保留来源在恢复后被排到会话末尾。

默认失败的只读诊断未找到原始对话中的明确删除请求，具体触发材料因受管擦除不可再确定。共享提示补充通用边界：偏好改变、认识更正、停止活动应更新版本，不自动等于擦除历史；仅明确 erase/not-retain 请求才执行 forget。未使用 case ID／关键词路由或额外分类模型。新默认在同一预算内执行一次修复后 smoke；旧失败费用和分数继续保留。

`v4-default-smoke-2` 在发送前被预算预留拒绝：已花56577＋新请求预留7601＋原作答预留90000＝154178，超过150000累计上限。该目录零新模型调用，预算请求数未变。按剩余额度把作答预留改为60000，原累计总上限、每问回合数和Judge预留不变；Provider 现在显式记录未发送的预算拒绝。

最终默认 `v4-default-smoke-3`：5／5摄入操作结清，Host3次生成完成推荐答案，没有forget或截断；原生结果仍为 `uses_latest_preference=0 / outdated_preference_contamination=1 / valid_selection_pass=0`。这是同一暴露题的修复复核，不是新确认样本，不再为追求通过追加同题调用。

| 默认最终执行阶段 | 请求 | 输入 tokens | 输出 tokens | 合计 |
| --- | ---: | ---: | ---: | ---: |
| 摄入生成 | 1 | 2993 | 482 | 3475 |
| 作答生成 | 3 | 16471 | 340 | 16811 |
| 原生Judge | 1 | 1184 | 109 | 1293 |
| embedding | 2 | 2076 | 0 | 2076 |

默认包全部尝试累计14次生成／78156 tokens、embedding4149 tokens、最终 unknown usage=0。作答tokens减少伴随不同回答与不同错误，单题观察不构成效率或质量收益证明。

最终默认与STALE修复执行冻结35个源码文件，文件散列映射按既定JSON序列化的SHA-256为 `1cb7429dd50de62544f1e6da0abcdf27a76a7160657344f0969f33008ca46bee`；共享提示SHA为 `b06bb5ccc70d5bedd0172662581cc4446cb45356de7420b3ff0944df07a0d753`。源码全文、逐文件SHA、配置、模型/tokenizer身份及答案冻结记录均在各新目录；没有创建commit或push。

## 完整 STALE 的实际结果

制品为 `artifacts/contextual-user-memory/v4-stale-ordinary-repair-1`。复用前4批10项成功提交，续跑46批80项提交；共50批／90项操作结清，完整覆盖594条消息、673289字符，无剩余协议故障或 pending maintenance。最终88条记录、299条保留来源；其余合法原文仍由受控 archive-backed 读取提供，不能称为仅依赖压缩记忆作答。

三个 probe 均从同一历史 checkpoint 的独立实例开始，均正常作答，冻结后进行一次原生联合 Judge。`dim1=0 / dim2=0 / dim3=1`，有效评分3／3；dim2 的答案沿用每周约8小时旧计划，dim3 则给出每天10–20分钟的小步计划。单场景执行通过，质量仅1／3，不是全面效果验证。Judge 与 Host 同权重，属于同模型自评。

| STALE 包累计阶段（含首次失败） | 请求 | 输入 tokens | 输出 tokens | 合计 |
| --- | ---: | ---: | ---: | ---: |
| 摄入生成 | 51 | 318642 | 18621 | 337263 |
| 作答生成 | 13 | 157997 | 1744 | 159741 |
| 原生联合Judge | 1 | 2109 | 275 | 2384 |
| 摄入embedding | 99 | 174355 | 0 | 174355 |
| 作答embedding | 28 | 178510 | 0 | 178510 |

本包累计65次生成／499388 tokens，embedding352865 tokens；最终unknown usage=0。续跑的60次生成请求，本地完整聊天模板计数与服务端 prompt tokens 误差均为0。总费用不以tokens直接换算货币或GPU时间。

新目录的材料交付总计53328 tokens，其中正文分项13734、引用/状态39163、关联材料0；分项边界不严格可加。没有完全相同只读调用的缓存复用，但存在多次展开：三个答案合计4次search、6次read，均无工具失败。这说明剩余成本主要还在材料元数据与多轮读取，不能归结为单纯网络往返或宣称已彻底解决。

续跑的embedding缓存命中1492个key，按该目录唯一输入估计的冷启动tokens为338893；原失败目录另花13972，未重复复制其trace或抹去消费。跨目录与独立启动估计分开记录。新目录测得摄入检索15.56秒（含embedding等待）、材料0.065秒、提交dispatch2.23秒；作答dispatch19.06秒，其中检索约19.00秒、材料0.004秒。嵌套计时不可求和，未测得足以推动深拷贝优化的真实支持组负载，因此未作复制优化。

条件能力的真实覆盖也有限：默认与STALE作答均没有 Host 提出的condition_evidence；这些作答回执未显式交付条件适用性字段，不能认领自然使用条件机制的效果。摄入回执有未知条件的PENDING，未把它计作USABLE；ordinary不计算支持组的UNSUPPORTED／CONFLICT，这些支持状态仅有定向机械检查，不冒充实际候选覆盖。

全部新执行累计79次生成／577544 tokens、embedding357014 tokens，含失败、评分和修复；另有一次零发送的预算拒绝。没有消耗包 B 可选候选或包 C 的模型预算。

## 机制覆盖限制

旧 trace 中 13 道允许 MemSyco 原题均单批。新固定 tokenizer 自然分批（6000 source tokens、32 tokens／消息开销）复核后仍各一批；四道 valid screen 的源 token 总量为 1866／2170／2163／1901。因此不能证明旧对象提交后再收到更正，H1/H2 机会分母为 0，后四环比例不适用。包 C 不得用同批内部变化、终态对象或刻意缩小批次制造机会；不启动无触发依据的候选分数比较。

ordinary 保持默认。A和B已完成，原 C 因无真实机会未执行；未完成真实机制比较前，总体状态保持 `PARTIAL_NOT_COMPLETE`。上述未覆盖结论属于原单批协议，不以负面结果或无机会改写为方法收益或全 Goal 完成。

## 包 C 范围修订时的方案

用户回复“允许修改包C范围，先制定具体小规模方案”后，已将具体方案写入 [Goal 第 9 节](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v4.0_20260924.md)。首先运行 `v11_000977`，RAW／ordinary／既有 H2 `ordinary_linked` 三臂；后续固定为 `v11_000569`、`v11_001003`、`v11_001002`，首题结果交付前不自动扩展。

新方案明确改变到达协议：每条原生 user 及其后续 assistant 为一个到达单位，逐步提交后再接收下一单位。四题分别 6／7／6／6 个单位，全部原文、顺序、问题与评分保留。原生用户消息中分别有影评停止、讨论方式逆转、社区服务方式收窄、法律学习方式改变；这些只支持输入有修订需求，尚不证明 Host 已形成可用的版本链。

ordinary 与 H2 每题共享一次在线摄入及准确最终快照，只切换材料模式；先验证提交链，再执行三臂作答及冻结后评分。若没有相关旧对象、真实更新或自然后续使用，就报告断点，不种入旧卡、不指定模型更新、不反复同题追分。首题上限 30 次生成／150000 tokens、embedding 80000 tokens；最多四题总上限 120 次／600000 tokens、embedding 250000 tokens，包含首题及失败，不能通过换目录重置。在线摄入增加的费用与 H2 材料费用分开记录。

交付上述方案时只修改规划与导航文档，没有改运行源码或发起模型请求；当时累计费用为 79 次生成／577544 tokens、embedding357014 tokens。下节记录持续 Goal 随后的实际实施与首题结果，避免将规划状态当成当前执行状态。

## 包 C 首题：三臂评分通过，更正使用仍未覆盖

运行目录为 `artifacts/contextual-user-memory/v4-c-online-pilot-1/`，有效配置为 [contextual-memory-v4-c-pilot.json](../configs/contextual-memory-v4-c-pilot.json)。先执行 `--phase ingest`，核对实际提交链和零调用关联读取后，同配置、同目录执行 `--phase develop`。只运行 `v11_000977`，没有扩到其余三题、追加定向提示或重试追分。

实现增加显式 `history_arrival_policy=online_turn_replay`，默认仍为 `natural_capacity`。`batches.json` 冻结到达策略、原生消息索引边界和容量分批；恢复／失败导入要求其身份一致。`ingest` 阶段只构建去重后的历史 owner，不作答、不冻结空答案批次、不评分。容量／runner 定向 18 项通过，受影响 5 文件 Ruff、2 文件 mypy 通过；未运行全套、包构建或重复默认模型 smoke。已有默认分批回归通过，B 的实际默认 smoke 留作此前源码身份的执行证据。

本次 12 消息、7933 字符完整覆盖，到达边界为 `[0,3), [3,5), [5,7), [7,9), [9,11), [11,12)`；6／6 批结清、8／8 操作提交，形成 6 张当前卡和 2 个历史版本，没有协议故障、未提交项或待维护项。ordinary 与 H2 的 `history_cache_id` 相同，均为 `53b999db5684e4b6c3a28f08660accf9953d96db9b5ab31485d0eb2f80641665`；实际只摄入一次。

| 阶段 | 生成请求 | 输入 tokens | 输出 tokens | 合计 |
| --- | ---: | ---: | ---: | ---: |
| ordinary／H2 共用摄入 | 6 | 9740 | 892 | 10632 |
| RAW 作答 | 3 | 14519 | 352 | 14871 |
| ordinary 作答 | 3 | 19213 | 421 | 19634 |
| H2 作答 | 4 | 27381 | 428 | 27809 |
| RAW Judge | 1 | 1200 | 86 | 1286 |
| ordinary Judge | 1 | 1278 | 73 | 1351 |
| H2 Judge | 1 | 1219 | 72 | 1291 |
| **首题合计** | **19** | **74550** | **2324** | **76874** |

embedding 实际 13 请求／3503 tokens：摄入 10／1573，RAW 作答 2／1828，ordinary 作答 1／102，H2 作答命中共享缓存、零新增调用。不能因此称 H2 不需要 embedding：按独立启动估计，RAW 为1828，ordinary／H2 各为3503（历史1573＋作答1930；两阶段 key 无交集）。独立启动的生成费用含摄入和 Judge 后，RAW为16157、ordinary为31617、H2为39732；这是费用口径调整，不是额外实跑。

三臂各有一份冻结答案、一次有效原生 Judge；均为 `uses_latest_preference=1`、`outdated_preference_contamination=0`、`valid_selection_pass=1`。但没有独立确认集或多次重复；题目本身也要求轻松、不分析，答案正确不能证明使用了历史更正。

### 修订链与自然使用证据

所有引用以下均在 `f6dae52827eb04a1/` 命名空间内。历史目录位于 `memsyco/screen/history/ORDINARY_MEMORY/` 下上述 cache ID。

| 环节 | 本题证据 | 结论 |
| --- | --- | --- |
| 机会存在 | 原生 user 索引3表示重启影评博客；批1已提交 `card:3@1`；批3才收到索引7停止影评及关闭博客的新消息 | 1 个合格机会 |
| 材料可见 | 历史 `trace.jsonl:38` 的实际 Host 请求同时包含停止影评的 `s0` 和旧卡 `r0`；`r0` 对应准确 `card:3@1` | 1／1 |
| 操作提出 | `chunk-00003-*` 首操作使用 `target_ref=r0` 和新 `source_ref=s0` 提出更新 | 1／1 |
| 提交成功 | 回执为 complete，`card:3@1 → card:3@2`，新正文明确停止影评、避免分析压力 | 1／1 |
| 后续材料及答案使用 | 离线旧 source／旧卡读取可关联 `card:3@2`；H2 自然作答却未交付该更正正文或新来源 | 自然更正取材 0／1；可确认使用 0／1，答案归因 unknown |

H2 答案目录为 `memsyco/screen/answers/H2_LINKED/619ef7f631553cb625d047577cc79c5325f458f003a7a52174a2e01068076b0b/`。其 `trace.jsonl:7` 搜索使用 `limit=5`，材料主要为旧 assistant 来源及 `card:1/2`；第12、17行只展开家庭观影建议和拥挤影展来源。关联材料均为普通 `source_provenance`，没有该题的 `revised_interpretation`。离线指定 ref 的成功关联只证明路径可达，不计为 Host 的自然使用。

RAW 和 ordinary 都实际展开了更正来源 `source:656ca07a5fc68f7e26f2daae`，回答分别提及停止影评、无需做笔记或写评论。ordinary 未显式指定 limit，实际搜索返回更多材料；H2 的回答只说避免 overthink／analyze，与问题本身相符，不能据此推断更正链起效。这是相同工具与上限下的实际行为差异，不是固定相同工具轨迹的因果实验。

**语义缺陷保留：**同批还将无关的 fan-trailer `card:4@1` 覆盖成停止影评正文；原生消息不支持这次泛化，因此不计为第二个合格机会。Host 为两次更新写入 `valid_until="present"`，当前没有可确定的任务日期，记录适用性为 PENDING；不能把“提交结清”写成“语义正确或适用性已确认”。窄只读复核与上述判断一致，H1 支持机制未在此运行。

### 效果、成本与当前状态

H2 比 ordinary 多 1 次作答生成，作答 tokens 增加8175（41.6%）；含共享摄入归摊及各自 Judge 的独立启动生成成本增加25.7%。三臂分数相同，H2 更正使用未覆盖，故没有 H2 收益证据，ordinary 保持默认。

实际交付材料 tokens 为 RAW5071、ordinary6848、H2 6983；H2 其中关联材料1054，均未携带这条更正。分项 tokenizer 计数不保证可加。查询／展开次数分别为1＋1、1＋1、1＋2，无工具错误。摄入检索1.0734秒、材料0.00121秒、提交 dispatch0.2313秒；RAW／ordinary／H2 作答 dispatch分别0.3005／0.0764／0.0350秒。检索含 embedding 等待，局部计时不可与嵌套项相加；共享缓存下的低延迟不证明独立部署更快。

首题实际费用低于30请求／150000生成 tokens／80000 embedding tokens上限，失败与未知用量均为0。**全 Goal 累计98次生成／654418 tokens、embedding360517 tokens**，包括原 A／B 的失败、修复与全部评分，另保留此前零发送预算拒绝。其余三题及大规模测试均未运行。执行比较已完成，但五环节最后一环缺少证据，总 Goal 仍为 `PARTIAL_NOT_COMPLETE`；不以三臂评分通过替代机制验证。

当前运行冻结35文件源码散列汇总为 `cad9cc978cd870f848a118d62e1bf065d7b97efbcdf47173670b39c285eae8ae`，配置散列 `89fa629d95d116c691c3fe3c9fd34cd1d6b72b7c886c31acbc91de30a4e5cb5f`，共用 checkpoint 散列 `776ebd690f6ce357a4a814aaf8b69de2f59965c548c717e3b2134faeb6987220`。方法仍为v7、句柄提案协议仍为v2，共享提示散列仍为 `b06bb5ccc70d5bedd0172662581cc4446cb45356de7420b3ff0944df07a0d753`；新到达策略由配置、分批计划和源码身份区分，旧 A／B 与 v3 制品未覆盖。

## 首题后的时间判断修复（零模型调用）

实际提案中的 `valid_until="present"` 暴露了共享 `scope_result` 的确定性错误：原实现直接比较字符串；为记录提供 `task_valid_at="2026-09-24"` 后，ordinary 和 support 都会把该含糊上界判成 `MATCH/USABLE`。首题本身没有任务日期，因此当时仍是 PENDING，旧评分不受这次复现改写。

修复只改 `query_context.py`：使用标准库解析 ISO 日期，不能解析的实际日期或边界保留原值并报告 `UNKNOWN/PENDING`，未解析边界列入 `unresolved_boundaries`；若另一个确定边界已能排除实际日期，仍报告 `MISMATCH/UNUSABLE`。不推断 present／now／相对日期，不改 Host 提示或 schema，也不替 Host 判定无关记录应该如何修改。带时刻的非日期文本同样待定，不声称支持任意日期表达。

conditions／revision 相关测试12项及受影响 Ruff／mypy 通过，无模型请求。相对首题35文件快照仅 `query_context.py` 改变，该文件散列为 `e5ce4f87865a699d05d476a7e29ec5b49d10a8a9e7addd50f4857a363fd46d5d`；修复后源码散列汇总为 `0783c133506306289ffeda9e562a0febd9f7ff7349abdf5fd3b405e9e812f92d`。首题来源快照和运行目录保持原样，旧分数不冒充修复后模型实跑，累计费用不变。

## 最终固定范围结果

首题结果交付后，按预先写定的 `v11_000569 → v11_001003 → v11_001002` 续行，每题先摄入核对相关更新；没有追加题目、改提示、改候选或检索参数。窄范围判断确认属于既有1＋3授权。三题与下述默认 smoke4 使用上节修复后的同一35文件源码映射；首题保留自己的旧源码身份，不把四题统计成同一源码上的准确率或确认集收益。

| 固定题／目录尾名 | 摄入覆盖、提交 | 作答及原生评分 | H2 机制结果 |
| --- | --- | --- | --- |
| `v11_000977`／`v4-c-online-pilot-1` | 12消息／7933字符；6批／8操作 | RAW、ordinary、H2 均通过 | 真实更新已提交，但自然取材没有更正，答案归因 unknown |
| `v11_000569`／`v4-c-fixed-1` | 14消息／9611字符；7批／9操作 | 停在摄入，无答案、无 Judge | 相关旧卡可见，但只新增叙述，未提出相关旧卡更新 |
| `v11_001003`／`v4-c-fixed-2` | 12消息／10421字符；6批／8操作 | 三臂均通过：latest=1、contamination=0、pass=1 | 一条真实五环节链成立，未证明独立因果收益 |
| `v11_001002`／`v4-c-fixed-3` | 11消息／8888字符；6批／13操作 | 三臂均未通过：latest=0、contamination=1、pass=0 | 更新状态实际可见、回答部分采用，仍混入旧偏好 |

四题均完整覆盖合法历史，协议与提交故障结清；这不认证语义正确。v569 的批2保存建设性讨论 `fe56f9f6d14d5445/card:2@1`，批4新消息转向尖锐辩论，实际请求含该旧卡 `r0` 和另一旧卡 `r1`。Host 却新增 `card:4/5`，其中正文还引用临时“r0 and r1”，没有相关版本关系；更早的无关 card1 更新不计入本题机会。按预定摄入检查点不执行三臂答案，保留所有费用；它不是三题答错，也不因其他题完成而冒称此断点已修复。

### v1003：一条可核对的真实五环节链

以下对象均在 `a14f919cce740239/` 命名空间；运行根目录为 `artifacts/contextual-user-memory/v4-c-fixed-2/`。ordinary 与 H2 共用一次摄入，`history_cache_id=c946bc54742b5c65bf5dfc7eb89616bf624728f1b8ae3f3e3a246348b7c88868`，随后分别从准确快照作答。

| 环节 | 实际证据 |
| --- | --- |
| 机会存在 | 批1已提交 `card:2@2`：离开官僚式法律援助、转向直接社区接触；批3才收到原生 user 索引7选择有安排的青少年法律素养项目 |
| 材料可见 | 共用历史 `trace.jsonl:40` 实际 Host 请求同时包含旧卡 `r0=card:2@2` 和新来源 `s0=source:5b1eaf250dcb0963b986f3e8` |
| 操作提出 | 批3提案针对 `r0` 更新、引用 `s0`，明确课后法律素养、定期工作坊及定制课程 |
| 提交成功 | 局部回执 complete，`card:2@2 → card:2@3`；checkpoint 散列为 `bd4a07d6d34a02fe9d2388a1ed4a4476868eae7a9d9c63417fe3c12571f4953b` |
| 后续材料与回答 | H2 自然搜索实际返回新来源、当前卡和旧解释；旧来源 `source:4531b6efc78943ecc7cf9c2b` 的 `revised_interpretation` 关联交付当前 `card:2@3`；最终答案明确采用新安排 |

H2 答案目录为 `memsyco/screen/answers/H2_LINKED/c6884be37b04f611d26c0aba9151aa9fe06f085b8a53773ef58aa262e3a88049/`。其 `trace.jsonl:7` 为自然搜索材料，`limit=5`：第0项是新来源，第1项是当前卡及 `prior_interpretation=card:2@2`，第3项是上述旧来源及关联更正。第8行最终响应明确写出 “after-school legal literacy programs”、“scheduled workshops” 和 “tailored curricula”，并表示这种安排比无结构的普遍社区接触更合适。这些细节对应实际更正材料，符合 Goal §7.1 的可见材料与回答一致标准。

这只确认机制可达。相同搜索也直接交付新来源和当前卡，无法单独归因于旧来源的关联更正包；RAW 和 ordinary 也通过，所以不能声称 H2 必不可少或带来额外正确率。

v1002 则在批3将模拟法庭取向 `card:1@2` 更新为理论与判例取向 `card:1@3`，同时更新其他相关卡；批4又补充志愿服务，形成当前 `card:1@4`。这些针对同一偏好变化的多卡更新只算一个机会。H2 作答材料看到了更新后的卡及历史解释，最终虽说应优先理论与判例，却同时建议继续法律援助实务和参加研讨会。记录“部分采用新状态、仍有旧偏好污染”，保留原生 Judge 的0／1，不用人工判断改分。

按相关变化计，固定四题有4个机会、4个实际可见；相关更新提出3／4，提出后提交3／3。三条已提交且完成作答的链中，H2 更正状态实际进入材料2／3，完整回答一致可确认1条（v1003），部分采用且污染1条（v1002），未取到而归因 unknown 1条（v977）。保守只认领 v1003 一条完整链；无关覆盖、多卡重复修订和离线指定 ref 不增加分母。

### 后续三题阶段成本与比较

所有 tokens 均为生成输入＋输出；每题共享摄入只计一次，Judge 单列。

| 题目／阶段 | 生成请求 | 生成 tokens | 实际 embedding tokens |
| --- | ---: | ---: | ---: |
| v569 仅摄入 | 7 | 12726 | 2291 |
| v1003 共用摄入 | 6 | 11286 | 1992 |
| v1003 RAW 作答／Judge | 3＋1 | 14958＋1024 | 2180 |
| v1003 ordinary 作答／Judge | 2＋1 | 8865＋1058 | 52 |
| v1003 H2 作答／Judge | 2＋1 | 11313＋1029 | 0（共享缓存） |
| v1002 共用摄入 | 6 | 11665 | 2146 |
| v1002 RAW 作答／Judge | 6＋1 | 62421＋1128 | 1896 |
| v1002 ordinary 作答／Judge | 5＋1 | 54085＋1198 | 87 |
| v1002 H2 作答／Judge | 6＋1 | 74350＋1099 | 10 |
| **后三题合计** | **49** | **268205** | **10654** |

v1003、v1002 总生成分别为16请求／49533 tokens、26请求／205946 tokens。两题 H2 相对 ordinary 作答 tokens 分别增加27.6%和37.5%，分数均无优势。加上相同摄入和各自 Judge 后，独立启动生成成本分别为 RAW15982／ordinary21209／H2 23628，以及 RAW63549／ordinary66948／H2 87114；这些是费用口径调整，不是额外运行。

缓存命中不等于 H2 不需要 embedding。按独立启动的唯一输入估计，v1003 的 RAW2180、ordinary与H2各4224（历史1992＋作答2232）；v1002 的 RAW1896、ordinary4129（2146＋1983）、H2 4139（2146＋1993）。实际账本只记录真正发送的费用，独立成本估计另列，不重复加进累计。

| 题目 | RAW 交付材料 tokens | ordinary | H2 | H2 其中关联材料 |
| --- | ---: | ---: | ---: | ---: |
| v1003 | 5263 | 5144 | 7617 | 2382 |
| v1002 | 11141 | 12310 | 18831 | 7999 |

材料分项不可保证相加。v1003 摄入检索／材料／dispatch 为0.7020／0.00133／0.2225秒，RAW／ordinary／H2 作答 dispatch 为0.3128／0.0751／0.0307秒；v1002 对应0.5520／0.00110／0.3610秒及0.2904／0.0883／0.1179秒。检索包括 embedding 等待、dispatch 内嵌其他操作；共享缓存下的单次局部时间不证明部署速度改善，也不是 GPU 计时。未据此增加复制优化或结构重构。

### 当前源码自己的默认 smoke：仍有语义失败

时间修复改变共享源码后，以实际交付的 [默认配置](../configs/contextual-memory-v4-default.json) 运行 `v4-default-smoke-4`，配置内容不变，单独新目录冻结当前身份。目的仅是补齐当前源码的实际默认执行证据，不重跑直到通过。1批、12消息／7933字符、5操作结清，随后完成答案冻结和一次有效原生评分。

Host 再次把停止活动误解为删除请求，最终只返回：“Acknowledged. The memory deletion is complete. No prior information has been reconstructed.” 原生 latest=0、contamination=0、pass=0。执行状态 complete 表示已有可评分响应，任务质量仍失败；这与先前默认 smoke 的误删风险一致，不能因协议结清而写成语义修复成功。受管 trace 已按删除流程裁减，本轮不恢复其已擦除正文。

实际费用为8次生成／40404 tokens：摄入1／3457、作答6／35931、Judge1／1016；embedding2请求／2058 tokens。此前 smoke3 与完整 STALE 保留各自旧源码身份；未把它们称为当前修复后的重跑。没有追加第五次默认 smoke。

### 最终身份、累计预算与完成核对

最终三题及默认 smoke4 的35文件源码映射散列均为 `0783c133506306289ffeda9e562a0febd9f7ff7349abdf5fd3b405e9e812f92d`，工作树对应文件已逐一核对。方法v7、协议v2，共享提示散列仍为 `b06bb5ccc70d5bedd0172662581cc4446cb45356de7420b3ff0944df07a0d753`。模型、tokenizer、原始数据及到达计划身份随每份 manifest／batches 冻结。

| 运行 | 有效配置散列 |
| --- | --- |
| `v4-c-fixed-1` | `0192766347d5c2e0ccbccd78486c0eddeee485009636d8410e41e880301c012b` |
| `v4-c-fixed-2` | `42da3b93b2dfd570a293aa53a5d4e3d985820ce264851a0685f905188e2dc3a6` |
| `v4-c-fixed-3` | `bd5b5d73680cfc0e92ebfdbf07c9d6e22b3945184874fd94943bcbe9cadc8ca4` |
| `v4-default-smoke-4` | `d69a509e63d9f661540b296b8074d7bdc043c37c4b1ecd2163b95c7c4a16b76f` |

最终核对使用运行器相同的规范 JSON digest（排序键、保留 Unicode），而非带缩进文件的字节散列：上述配置与首题配置均匹配；C 的9份冻结答案及默认 smoke4 的1份答案均与 `answer-batch.json` 匹配，v569 确无答案批次或 Judge。v1003 H2 答案散列为 `0fd8adc3e430b81e2dca148d16429d96a2be50f71c49fe8182694439dabcfe9d`，默认 smoke4 为 `ae39de6d4b3baf287d9cc8944478f9af83903b5307d3f9dea55b6706727a1661`。完整证据位于各运行目录，未覆盖旧冻结制品。

| 外置累计账本 | 生成请求 | 生成 tokens | embedding tokens |
| --- | ---: | ---: | ---: |
| B 默认 `b-default.json` | 22 | 118560 | 6207 |
| B STALE `b-stale-ordinary.json` | 65 | 499388 | 352865 |
| C 首题 `c-pilot.json` | 19 | 76874 | 3503 |
| C 固定后三题 `c-fixed-remainder.json` | 49 | 268205 | 10654 |
| **全 Goal 合计** | **155** | **963027** | **373229** |

C 全包68请求／345079生成 tokens／14157 embedding tokens。四账本均未超固定上限，charged与known一致、unknown usage为0；失败、显式修复、摄入检查点未通过、所有 Judge 都保留。另保留此前一次零发送预算拒绝。未运行 B 可选候选、额外场景、未使用确认题或大规模测试。这里是实验模型消耗，不包含开发 Agent 的上下文 tokens，也未换算货币费用。

| 工作包／Goal §11 条件 | 完成依据与限制 |
| --- | --- |
| W0 失败审计 | 离线 diagnostic、旧失败分类和断点表已保存，零新增模型调用 |
| W1／W2 协议可执行 | 准确句柄、部分提交恢复、容量及覆盖窄检查通过；真实 STALE 50批完整、三问独立、原生评分1／3；最新默认自己的执行和评分完整但质量失败 |
| W3 条件可解释 | 无主动 State 的 MATCH／MISMATCH／UNKNOWN、准确可见出处和隔离检查通过；时间边界修复相关12项通过；不认领自然 Host 使用条件机制的效果 |
| W4 材料与任务边界 | 关系或条件改变而正文不变的交付检查通过，共享提示允许新建议；实际误删、无关覆盖和旧偏好污染作为未解决的 Host 语义问题保留 |
| W5 身份和成本 | 当前默认源码／配置、已冻结答案、四累计预算核对完成；阶段身份分开，未把旧分数归于新源码 |
| W6 机制可达与可解释对照 | v1003 一条五环节链及三臂原生比较成立；失败／未评分题保留；H2 额外成本明确，独立因果收益未知 |
| W7 有限职责整理 | 仅收拢实际修改触及的窄接口，无大规模 runner 搬迁；没有测量依据，未优化深拷贝 |

参考源码 Mem0、Memobase、Graphiti、LangMem 已在本地下载并由[来源清单](../data/manifests/contextual-memory-v3-sources.json)固定；选定文件散列复核一致，本次无需再次下载。协议、条件与 runner 变更只在 Lab：不改 Product 的 Schema、API、权限或 canonical 状态；新增 Lab 到达策略、ingest 阶段及句柄协议有独立身份。受影响静态检查、窄测试和新增模块时的依赖边界检查已通过；没有重跑全套 pytest、包构建或扩大 benchmark。未创建提交／回滚 tag、未推送，未宣称核对远端 commit；交接依据为配置和逐文件源码散列。

据原定 §11，四项有限交付条件已满足，结项为 `COMPLETE_WITH_NEGATIVE_OR_INCONCLUSIVE_EFFECT`。ordinary 继续默认，候选保持冻结；本轮未证明收益，也未解决全部语义可靠性问题。后续改进应针对已记录的误删意图、无关覆盖与旧偏好污染，而不是继续扩大本轮样本或用追分重跑替代开发。
