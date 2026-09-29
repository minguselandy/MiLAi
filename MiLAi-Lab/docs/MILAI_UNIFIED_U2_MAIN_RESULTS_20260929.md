# Unified V8/V9 U2：首张原生质量—成本结果表

状态：**FIRST_TABLE_COMPLETE；Continue/Pivot；总体 Goal 仍 ACTIVE**。独立 development 切片不支持当前 ordinary/MiLAi 或 Mem0 相对强简单方法的稳定净收益。ordinary 的范围控制明显退化，MERIT 还有真实输出循环和额外业务动作；先保留这些负面证据，再按具体首断点选择下一步。研究目标 **NOT_ACHIEVED**，Product **NO_GO**。

本报告只关闭 U2 第一张五方法主表，不关闭完整 U0—U6 Goal。第二外部系统、适用的 U3—U5 门槛和 U6 总体收口仍待完成。原生结果与附加诊断分开，所有失败、未知和费用保留。

## 身份、样本和执行边界

- 方法源码 A：`795725a297fb1ef5f9d7bb712b3500d5b72546c0`；输入/执行提交 B：`e6df2f5d914c3ea2f08ce34f0887749e6f0c30dc`。报告提交不是实际运行提交。
- 依[事前协议](MILAI_UNIFIED_U2_PROTOCOL_20260929.md)、[开发执行合同](../data/diagnostics/unified-v8-v9-u2/development-contract.json)及[评分合同](../data/diagnostics/unified-v8-v9-u2/scoring-contract.json)执行，过程中没有改 prompt、参数、工具、scorer、样本、写入节奏或源码。
- MemSyco：60题、54个来源连通组、60份不同历史，三任务各20题；MERIT：18条完整预选 arc、90 episodes、36 dependent、111个原公开消息。新 seeds11—28仍来自同一官方生成器，不是独立任务家族。
- 五方法各自隔离 namespace、Store、checkpoint、Mem0数据库和业务 world。300次归档形成＋300次查询＋90次 arc，共690个执行单元全部尝试一次。686完成、4异常退出；不重试、不换题、不拼接轨迹。
- 全部 Host 工作结束后才冻结300个 MemSyco 回答/状态；299次单次 Judge 均成功解析，1个 Host 不完整项不调用 Judge。没有重评或按分数修复答案。
- 执行 freeze SHA256：`efe0c74b22b93da6342a9bfb125f383bb1632ad83e3efafd3347f2265cb5beb5`，绑定496份不可变文件；顺序 SHA：`9d8bbb6b46cdbd757d1ee0fe1d3b8a58a8255719465164bd2f0679a24ffaac97`；回答批 SHA：`2dac73f372411062e649e8ef5b9516fa6199dcc3b54a2e3f54cd5b1bbb239ab7`。

服务仍为独立7862上的 Qwen3.6-35B-A3B-FP8，native Agent、temperature0、thinking=false、65536容量；Host/reader4096、摘要2048、Judge1024输出。Embedding为7861/bge-m3/1024维。真实模型HTTP并发1，MERIT每公开消息总生成上限12，包含维护/摘要。全部2228次实际生成的本地 prompt 计数与服务 usage 相等；新 unknown usage=0。原7860及其他既有服务未改，未下载或部署新模型。

方法合同与环境差异保持明确：完整原文、BM25+dense/RRF原文检索、真实滚动摘要、ordinary Agent/MCP严格记忆操作、原生 pinned Mem0。MemSyco使用共同原生 reader；其程序取材不冒充 Host 自主搜索。MERIT保留原始 world/tools/checker，允许各自真实动作轨迹不同。Mem0 `f8082a7…` 是 ADD-only pin，不证明同ID修订能力。

## MemSyco 原生结果

每格分母均为预定20题。通过来自原生 rubric 的固定本地同族 Judge。

| 方法 | 范围控制 | 新旧偏好选择 | 个性化使用 |
| --- | ---: | ---: | ---: |
| RawDialogue | 17/20 | 13成功、1未知/20 | 17/20 |
| StrongRawRAG | 19/20 | 15/20 | 18/20 |
| Rolling summary | 17/20 | 15/20 | 19/20 |
| Ordinary/MiLAi | 6/20 | 13/20 | 16/20 |
| Mem0 native | 16/20 | 12/20 | 16/20 |

RawDialogue 的 `v11_000342` 实际HTTP200，但生成重复并达到4096输出上限，保留 `HOST_INCOMPLETE`。新旧选择的计划成功率界为65%—70%；原生已评分口径为13/19，两者不能混用。没有把该样本换掉或补问。

ordinary 范围控制相对原文差−55个百分点，事前配对来源组bootstrap的95%区间为[−80,−30]个百分点。StrongRawRAG相对原文为+10个百分点，[0,+25]；其个性化差+5个百分点，[−15,+25]。摘要个性化差+10个百分点，[−10,+30]。这些是当前切片、固定Judge下的描述性区间，不是多重比较校正发现或跨任务家族保证。所有新旧选择的配对CI因原文一项未评分而不输出；不删除该题凑完整配对。

[机器结果](../data/manifests/unified-v8-v9-u2-main-results-20260929.json)保留原生所有指标、逐题分数、分组/长度层、来源组及配对区间。长度分层为完整历史UTF-8字节≤4096、4097—8192、>8192；不是按结果挑长度。不得把三个任务合成未定义的“记忆总准确率”。

实际普通记忆形成201条、Mem0形成291条；60次查询各自全部交付，省略0，查询前后快照不变。摘要60次真实形成均完成，24份档案的未闭合回合保留原文，最近两回合也保留。这些只证明形成/交付发生，不证明内容质量。例 `mso_hard_000147` 的组员需求与个人偏好同时到达reader，仍被Judge判个人偏好过度主导；`v11_000580` 的当前偏好已明确在记录中，回答仍偏向旧模式。不能把这类退化直接解释为检索丢记录。

同族Judge和题目边界仍限制归因。例如 `rec_gen_0003` 的合法问题没有具体选项列表；ordinary请求补充选项，其他方法给电影名，原生Judge结果不同。保留这些分数及诊断，不以Root解释重写评分。形成压缩、信息强调、reader消费与Judge解释尚未由固定bank实验隔离。

## MERIT 原生结果

| 方法 | episode成功/90 | dependent成功/36 | 完整arc成功/18 | 未评分episodes |
| --- | ---: | ---: | ---: | ---: |
| FullHistory | 89 | 36 | 17 | 0 |
| StrongRawRAG | 90 | 36 | 18 | 0 |
| Rolling summary | 89 | 36 | 17 | 0 |
| Ordinary/MiLAi | 75 | 32 | 10 | 7 |
| Mem0 native | 86 | 35 | 14 | 0 |

ordinary 有83个已评分episodes，其中8失败；另3个中断episode和4个后续未启动episode仍占原分母。episode成功率界83.3%—91.1%，dependent88.9%—100%，整arc55.6%—72.2%；这不是把中断动作视作安全或成功。3条arc原生结果未定，已观察到的额外动作另记失败诊断。其所有配对CI均因未知项不输出。

StrongRawRAG相对FullHistory的episode差+1.1个百分点，95% arc-cluster区间[0,+3.3]；Mem0为−3.3个百分点，[−6.7,0]。摘要与FullHistory在本切片逐episode相同，bootstrap退化为[0,0]，不等于已经证明总体等效。原生 `pre_satisfied`、域、难度及每arc输入字节/消息数均在机器结果中。

摘要实际更新57次、全部committed。Mem0实际维护111次、全部完成，18个隔离arc最终共186条原生记录。ordinary的83个完成episode快照均为0条普通记录；实际MCP有7次Host搜索、7次历史读取，没有CRUD。FullHistory/ordinary有完整合法历史，因此不能由答对推导持久维护能力。额外历史读取回执：FullHistory0、RAG9、摘要2、ordinary7、Mem00；这些是各自自然轨迹的一部分。

## 首个断点与反思

[完整失败表](../data/manifests/unified-v8-v9-u2-main-failure-map-20260929.json)保留92个原生未通过/未评分条目及15份Root观测的身份和哈希。未能隔离的语义根因明确为UNKNOWN，不能用终端Judge失败倒推出Store故障。

1. **实际动作循环与输出循环。** ordinary `d2-arc18-000` 已成功设置配置，随后七次新生成的 `deploy(latest)`实际执行，最终455个WORKING HYPOTHESIS标记导致length中断。最早断点是额外动作选择；不是最后的截断，也不是同一调用被传输层重放。`d2-arc20-000`、`d2-arc22-000`分别在第五、第四episode发生标记重复截断，前面原生结果保留。
2. **排除已检查路径的checkpoint污染。** [Sol离线回执](../data/manifests/unified-v8-v9-u2-label-replay-diagnosis-20260929.json)重建41/41个实际请求，38个已接受AI正文逐字匹配服务回执，重复渲染不累加且原graph/wire不变；三个截断末答未提交为AIMessage。程序仅在请求副本添加一个标签，更多标签来自模型输出。支持“标签模仿经真实历史回流”，仍不能排除一般解码/终止不稳定，也不能断言取消标签会修复额外部署。
3. **精确业务key。** FullHistory、摘要、ordinary、Mem0均在 `d3-arc24-000` 写入 `coffee_preference`，原 `coffee` 未变；RAG通过。实际旧历史未给过明确canonical-key目录。竞争解释是自然措辞引导合成key，或自由字符串工具缺少对象发现/选择。不能用gold造ref或静默改key；原生工具保持不变。
4. **原生格式敏感。** ordinary四个退款确认因千位逗号、三个邮件因首字母大写失败；Mem0另有一个千位逗号失败。实际语义内容与精确字节合同分开报告，原生分数不改。不能称为七次记忆丢失。
5. **政策与checker条件。** Mem0 `arc15-000`实际读到11500 cents订单及10000 cents免批准阈值，因要求批准而未退款；生成器/checker要求全额退款，原工具本身未实施该政策阈值。保留原生失败和政策冲突，不强迫退款补分。
6. **形成阶段增加日期。** Mem0 `d3-arc26-000`第一次ADD就把源对话的Friday扩为Friday, September25,2026，实际记录随后被检索并用于create_event.day，造成一个dependent失败。地点和时间正确。该pin提示要求依据Observation Date落定相对时间；实际Observation/Current Date为2026-09-28。首断点在形成内容，不只是检索或末端格式；另一日期重跑可能产生不同内容。

Observed：强简单方法质量相当或更好，当前复杂路径费用增加，ordinary存在范围退化与Agent循环。Expected：公平完整比较与可追溯失败，不要求候选胜出。竞争解释至少包含形成/呈现改变信息权重、Host自然行动差异、固定Judge/原生checker边界；它们不能被本系统主表唯一隔离。

通用候选仅限后续独立身份：去除程序附加的逐assistant正文标签而保留原角色/回执/实际正文；或固定同一bank检验记忆呈现。对象发现、维护和恢复分别判断门槛，不叠加仲裁平台或自动选择器。最小下一步是完成第二外部系统接入选择，并从已有证据中冻结一个有反向控制的局部诊断。**Continue完整计划，Pivot当前优势假设；不宣称SER、State或Attention因果收益。**

## 完整成本

下表不含离线Judge；包含冷建、更新、任务、失败及真实embedding。generation tokens是输入＋输出，不含开发代理消耗。

| benchmark / 方法 | generation calls | generation tokens | embedding tokens |
| --- | ---: | ---: | ---: |
| MemSyco RawDialogue | 60 | 101,913 | 0 |
| MemSyco StrongRawRAG | 60 | 188,568 | 104,735 |
| MemSyco summary | 120 | 172,716 | 0 |
| MemSyco ordinary | 181 | 385,925 | 13,944 |
| MemSyco Mem0 | 120 | 656,736 | 121,298 |
| MERIT FullHistory | 236 | 361,588 | 0 |
| MERIT StrongRawRAG | 253 | 667,915 | 47,316 |
| MERIT summary | 294 | 362,960 | 0 |
| MERIT ordinary | 245 | 754,617 | 51 |
| MERIT Mem0 | 360 | 1,684,029 | 89,479 |

MemSyco形成/查询generation tokens分别为：原文0/101913，RAG0/188568，摘要73109/99607，ordinary329867/56058，Mem0600633/56103。RAG冷建另有103080 embedding tokens。全部60历史不同，实际无跨题构建摊销；查询是在各自已建快照上的一次增量，不称反复命中warm-cache实测。ordinary查询更短不抵消冷建成本：总generation为原文约3.79倍，Mem0约6.44倍。

MERIT摘要任务317241＋更新45719＝362960，略高于FullHistory361588，不能把仅任务阶段下降写成生命周期节省。Mem0任务637592＋维护1046437＝1684029，为FullHistory约4.66倍。自然轨迹和工具权限/呈现不同，因此不是纯压缩消融。

Host/形成/维护合计1929次generation，输入5011479、输出325488、总5336967；1428次embedding请求、376823 tokens。Judge另299次，输入442527、输出24230、总466757。**本主表总计2228次generation / 5803724 generation tokens / 376823 embedding tokens**。全部费用含失败且账本历史不变。

连续账本从3713/5060988/37969增至 **5941/10864712/414792**（generation calls / generation tokens / embedding tokens）。本Goal自起点累计新增2640次generation、6659509 generation tokens、391222 embedding tokens，包含U0失败、U1和pilot。物理I/O、净Store CPU、GPU小时及货币费用未计量；HTTP、进程、MCP和后端inclusive时延重叠，机器结果分列且不得相加。

## 复现、修正及后续边界

依[复现说明](MILAI_UNIFIED_U2_MAIN_REPRODUCTION_20260929.md)使用A/B版本与原冻结配置。此前26项工程窄检查、10份prepare和必要构建不为报告重复运行；执行B的Fast CI36474251594 success、Full36474251748 skipped。没有source修复混进主表。

Root离线汇总先误把摘要single-attempt标志与公开消息计数相加，后按源码语义区分57个标志；另把ordinary的ordinary_records字段误当backend_records，已分别呈报。Sol离线重放首次helper漏复现原runner去掉memory_block占位符，按实际链修正后通过。初次失败和原制品全部保留；这些只修离线解释/汇总，不改变模型、评分或冻结统计。

SimpleMem固定源码已在本地，但第二系统依赖/模型兼容仍待实现；Luna只读盘点未安装或下载。U3-P/O/W/R、U4各机制、U5独立/长程/另一模型及U6必须按统一计划明确处理；这里不把未运行分支视作能力通过。当前无未结束的本主表Host/Judge任务，后续工作仍在原授权完整Goal范围内；没有自动merge、main改写或Product迁移。
