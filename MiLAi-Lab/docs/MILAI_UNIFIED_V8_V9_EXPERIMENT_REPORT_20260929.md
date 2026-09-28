# MiLAi 统一 V8/V9 实验报告：用户暂停时点

**状态：PAUSED_BY_USER。** 2026-09-29（Asia/Shanghai），用户明确要求“暂停当前实验，生成实验报告”。实际 Goal 已为 `paused`；现场无未结束的实验执行或模型资产下载任务。已有推理及数据库服务保留，未因整理报告修改配置。

当前已经完成原生功能切片、五方法开发比较，以及第二外部系统 SimpleMem 的工程接入和小规模试跑。**现有结果不支持当前 ordinary/MiLAi 相对强简单方法的稳定净收益。** SimpleMem 尚无开发比较结果，其试跑发生真实调用容量中断。完整统一开发 Goal 未完成，研究目标 **NOT_ACHIEVED**，Product **NO_GO**。

本报告是暂停交接，不是完整 U6 验收通过。历史文档的 ACTIVE、Continue，以及保留的候选方案和执行合同均不能覆盖本次暂停。后续实验、源码开发、下载或部署须有新的明确恢复指令；本次只整理证据和发布报告。

## 1. 范围、身份与证据

本报告汇总[统一 V8/V9 计划](MILAI_UNIFIED_DEVELOPMENT_EXPERIMENT_PLAN_V8_V9_20260928.md)的实际进展。v26 及 v2—v7 等历史结果仍按各自提交复现，不混入本轮样本或清零成本。当前工作树为 `MiLAi-worktrees/unified-v8-v9/MiLAi-Lab`，分支为 `feat/lab-unified-benchmarks-v8-v9-20260928`。

| 阶段 | 实际身份 | 状态 |
| --- | --- | --- |
| U0 真实 Agent→MCP→Store→续答 | R1 失败保留；R2 完成 2 脚本／3 消息／9 任务义务 | 功能链已验证 |
| U1 原生 smoke | 执行 `94d3b18ef6b8c1dfd6019703df8e84163628c360` | 36 Host jobs、18 单次 Judge 完成 |
| U2 五方法主表 | 方法 A `795725a297fb1ef5f9d7bb712b3500d5b72546c0`；执行 B `e6df2f5d914c3ea2f08ce34f0887749e6f0c30dc` | 完成，含失败和未知 |
| U2 主表发布 | 报告 C `81f2cf469f0a64f53256838c7884592c8d88ab7e` | 已发布，报告提交不替代运行身份 |
| SimpleMem 工程及 pilot | `9200de0146da03ac09c78dab820feb1c9d09a708` | 工程通过；pilot 2 单元完成、1 中断 |
| SimpleMem 开发比较 | 计划 138 单元、最多 60 次 Judge | **NOT_RUN**，未正式 prepare／冻结／执行 |

原生来源、合法历史、scorer、输入字节和隔离方式均保留在原阶段冻结中。U2 第一张主表 freeze 为 `efe0c74b22b93da6342a9bfb125f383bb1632ad83e3efafd3347f2265cb5beb5`；SimpleMem pilot freeze 为 `493a1f835e7e806eafa716b787e0222d31e1c984d9953dbe52d4ad2554672084`。

主要证据：[U1 报告](MILAI_UNIFIED_U1_NATIVE_RESULTS_20260929.md)、[U2 首张主表](MILAI_UNIFIED_U2_MAIN_RESULTS_20260929.md)、[主表复现说明](MILAI_UNIFIED_U2_MAIN_REPRODUCTION_20260929.md)、[SimpleMem 试跑报告](MILAI_UNIFIED_U2_SIMPLEMEM_PILOT_RESULTS_20260929.md)与[本次暂停机器汇总](../data/manifests/unified-v8-v9-pause-summary-20260929.json)。原始私有轨迹、数据库、DSN、环境和模型资产继续排除在 Git 之外。

## 2. 已完成的功能与工程

Host 是使用公共 LangGraph 的 Agent，经真实 MCP 访问 MiLAi；vLLM 只是推理服务。U0 的初始失败和修复保留，真实提案、MCP 传输、Store 操作、回执及后续回答已串联验证，不能用直接调用或 mock 替代这项证据。

U1 MERIT 每方法 30 episodes：NoMemory 16/30、FullReplay 28/30、ordinary/MiLAi 26/30；dependent 分别 0/12、12/12、10/12。ordinary 没有 CRUD，且能访问完整合法历史，答对不等于持久维护通过。MemSyco 的只读 Agent 扩展另有四次未搜索便要求背景的失败；详见原报告，不把共同 reader 的程序检索解释为 Host 自主工具选择。

U2 接通三种强简单参照：完整原文、BM25＋dense 原文检索、真实滚动摘要；ordinary/current 的相同实现合并为一臂，并接入真正的 pinned Mem0。原生 world、业务工具和 checker 保持不变；各臂的 namespace、Store、checkpoint、业务状态和外部数据库隔离。

SimpleMem 使用官方 `db80b6a7c591e0ea730a058e9f5fc4eb06572299` 的 MemoryBuilder、LanceDB/Tantivy VectorStore 和 HybridRetriever，通过公共构造器注入既有 Qwen/bge-m3，连接共同 reader／Agent。保留原生规划、反思、解析和有限重试；这是 **core text 后端系统比较，不是完整 native ask() 复现**。

SimpleMem 14 个去重局部目标最终通过、0 skip，静态、边界、矩阵及必要构建通过。初始缺 pylance 导致的真实 FTS 失败、错误依赖版本调查及后续精确 pin `0.39.0` 更正、harness 与 loader 修复全部保留。工程检查使用真实临时数据库和 MockHTTP，不计作模型效果样本。完整记录见[工程回执](../data/manifests/unified-v8-v9-u2-simplemem-engineering-20260929.json)。

## 3. U2 首张五方法主表

开发切片为 MemSyco 60 题／54 来源组／60 份不同历史，以及 MERIT 18 完整 arcs／90 episodes／36 dependent／111 公开消息。690 个单元全部只尝试一次：686 完成、4 异常退出。随后冻结回答，299 次单次 Judge 成功解析，1 个 Host 不完整项保留未知；没有重试、换题、重评或调参。

### MemSyco：各任务分别报告

每列计划分母为 20。“未知”保留在分母，不视为通过，也不悄悄删除。

| 方法 | 范围控制 | 新旧偏好选择 | 个性化使用 |
| --- | ---: | ---: | ---: |
| RawDialogue | 17/20 | 13 成功＋1 未知/20 | 17/20 |
| StrongRawRAG | 19/20 | 15/20 | 18/20 |
| Rolling summary | 17/20 | 15/20 | 19/20 |
| Ordinary/MiLAi | 6/20 | 13/20 | 16/20 |
| Mem0 native | 16/20 | 12/20 | 16/20 |

ordinary 范围控制相对原文为 −55 个百分点；事前来源组配对 bootstrap 95% 区间为 [−80,−30] 个百分点。这是当前开发切片和固定同族本地 Judge 下的描述性结果，不是跨模型或总体保证。所有新旧选择的配对区间因原文一项未评分而不输出；不做完整样本删除。

ordinary 的 201 条形成记录、Mem0 的 291 条记录在对应查询中均全部交付，省略 0、查询快照不变。负面答案不能直接归为检索丢失；形成内容、信息强调、reader 消费与 Judge 边界尚未被固定 bank 实验隔离。三个任务不能合成未定义的“记忆总准确率”。

### MERIT：任务、依赖及完整 arc

| 方法 | episode 成功/90 | dependent 成功/36 | 完整 arc 成功/18 | 未评分 episodes |
| --- | ---: | ---: | ---: | ---: |
| FullHistory | 89 | 36 | 17 | 0 |
| StrongRawRAG | 90 | 36 | 18 | 0 |
| Rolling summary | 89 | 36 | 17 | 0 |
| Ordinary/MiLAi | 75 | 32 | 10 | 7 |
| Mem0 native | 86 | 35 | 14 | 0 |

ordinary 的 7 个未知包括 3 个中断 episode 和 4 个后续未启动 episode；83 个已评分中有 8 个失败。其 episode 计划成功率界为 83.3%—91.1%，完整 arc 为 55.6%—72.2%，相关配对区间不输出。未知不免除已观察到的额外动作问题。

ordinary 实际 7 次 MCP 搜索、7 次历史读取、0 CRUD，完成快照均为空。摘要有 57 次真实更新，Mem0 有 111 次维护、18 个隔离 arc 最终共 186 条记录；这些证明维护发生，不证明语义正确或同 ID 修订。该 Mem0 pin 为 ADD-only。

## 4. SimpleMem 最新试跑：功能链成立，完整任务未完成

同一已曝光 MemSyco 首题与完整 `arc5-000`，共 3 个执行单元；试跑没有计划或发起 MemSyco Judge，不以语义高分作工程门槛。

- MemSyco 摄入 10 条原历史消息，形成 33 条原生记录；查询取回并交付 29 条，省略 0。实际重新打开的持久快照匹配，查询前后不变，材料确实进入最终 reader HTTP，生成了回答；**尚无该回答的原生质量分数**。
- MERIT 前 3 个 episode 通过；第 4 个中断，第 5 个未运行。计划 5 个中的 3 成功、2 未知；dependent 1 成功、1 未知/2。完整 arc 未能完成。
- 已关闭的 4 个公开 turn 都完成原生维护，最终保留 11 条记录。5 个已启动公开消息各自动检索一次；结果依次来自当时真实 bank，ReAct 续接复用同一材料，没有循环重复自动检索。
- 中断消息实际用了 7 次原生规划／反思生成，再由 Agent 5 次生成查询订单和政策；达到共同每消息 12 次上限后，下一次 Host 续接在 HTTP 前被拒绝。45 次 MERIT 生成全部对应真实请求和账本，无重复扣记。

这次结果支持“原生检索开销与实际工具查询共同耗尽容量”，不支持已检查路径中“适配器重复检索或虚扣容量”的解释。错误泛化政策 key 查询随后得到可用 key 列表；政策阈值又可能影响后续退款选择，但因没有最终回答，不能推断加额度就会成功。

没有追加额度、减少反思、重跑 arc、续接业务或补写答案。暂停前的继续比较提议现已被用户停止指令覆盖；计划 138 单元没有启动。该单例不能用于与旧主表排名，也不能声称独立未见收益。

## 5. 主要首断点、竞争解释和结论

| 观察 | 已有证据与竞争解释 | 当前结论 |
| --- | --- | --- |
| ordinary 范围控制 6/20 | 所有记录实际交付；形成压缩／呈现权重、reader 消费、Judge 解释均可能影响结果 | 明确负面信号；原因未唯一隔离，不支持直接增加 selector |
| 三条 ordinary arc 标记输出循环 | 41 请求精确重放、38 接受正文匹配真实服务响应；渲染副本未累加污染 | 模型输出标签回流受到支持，一般解码不稳仍可能；取消标签未实施、无因果证明 |
| 七次额外 deploy(latest) | 先完成请求动作，后由新生成、不同 call ID 产生额外真实动作 | 首断点是动作选择，不是传输重放；取消标签不能被承诺为修复 |
| coffee key 漂移 | 写入 coffee_preference，原 coffee 未变；此前未取得明确 canonical-key 回执 | 对象发现／自然措辞与自由参数均可能；不能用 gold 造 ref 或悄悄改原生工具 |
| 格式与政策冲突 | 千位逗号、大小写造成原生失败；政策拒绝与 checker 目标不同 | 原生分数保留，不能全部归为记忆错误或人工补分 |
| Mem0 Friday 被展开成错误绝对日期 | 第一次形成即新增日期，随后持久化、取回并用于实际动作 | 首断点在形成内容；运行日期和原生提示是混杂因素 |
| SimpleMem pilot 容量中断 | 当前消息 7 次原生检索＋5 次 Host 真实请求，缓存和账本核平 | 系统合同下真实失败；不是适配器重复执行的证据 |

完整 Observed、Expected、因果链、首断点、两种以上解释、通用候选和混杂因素见[主表失败清单](../data/manifests/unified-v8-v9-u2-main-failure-map-20260929.json)及[SimpleMem 机器记录](../data/manifests/unified-v8-v9-u2-simplemem-pilot-results-20260929.json)。

本次反思：工具或数据库成功不等于语义通过；更短的查询不等于更低的生命周期费用；形成失败、消费失败、动作失控和资源耗尽不能合并成一种 Store 故障。当前优势假设应收缩，强简单方法继续作为参照。未隔离的问题明确保留；不以更多措辞、平台模块或样本特例挽救分数。

**当前决策为用户要求的 Pause。** 历史 Continue/Pivot 只记录当时研究判断，不构成后续执行许可。最小潜在后续事项及原计划顺序保留，尚未开发的候选、恢复链和确认集均不在本次报告工作中执行。

## 6. 完整实验成本

generation tokens 为实际输入＋输出 token；与开发代理 token 分开。下表包括失败、试跑、维护、原生重试及 Judge，不清零历史账本。

| 本轮阶段 | generation calls | generation tokens | embedding tokens |
| --- | ---: | ---: | ---: |
| U0，包括失败 R1 | 5 | 7,613 | 62 |
| U1，包括 Judge | 321 | 613,029 | 1,330 |
| U2 五方法 pilot | 86 | 235,143 | 13,007 |
| U2 五方法主表，包括 Judge | 2,228 | 5,803,724 | 376,823 |
| SimpleMem pilot，包括中断 | 51 | 56,629 | 2,010 |
| **统一 Goal 新增** | **2,691** | **6,716,138** | **393,232** |
| **连续账本累计** | **5,992** | **10,921,341** | **416,802** |

起点为 3,301／4,205,203／23,570。权威账本仍在原树 `artifacts/ser-v20/budget.json`，暂停时 SHA256 为 `2ef3e45b0150cb6c5cc2c47dc0f0493497157e84dae0a9e991d71b1181113e3c`。报告整理不产生新的实验 Host／embedding／Judge 调用。

U2 主表逐系统成本另列，均不含 299 次 Judge 的 466,757 generation tokens：

| 方法 | MemSyco generation tokens | MERIT generation tokens |
| --- | ---: | ---: |
| RawDialogue／FullHistory | 101,913 | 361,588 |
| StrongRawRAG | 188,568 | 667,915 |
| Rolling summary | 172,716 | 362,960 |
| Ordinary/MiLAi | 385,925 | 754,617 |
| Mem0 native | 656,736 | 1,684,029 |

MemSyco 60 份历史均不同，未发生跨题构建摊销。ordinary 总生成费用约为原文 3.79 倍，Mem0 约 6.44 倍；MERIT Mem0 约为 FullHistory 4.66 倍。摘要计入更新后略高于 FullHistory，不能只取任务阶段节约解释为生命周期压缩收益。不同系统有不同轨迹和工具合同，不是纯 SER 消融。

SimpleMem pilot 的 MemSyco 为 6 次／10,164 generation tokens／1,094 embedding tokens；MERIT 为 45 次／46,465／916。全部 51 次生成 prompt 本地计数与实际 usage 相等，原始费用及中断完整保留。物理 I/O、净 Store CPU、GPU 小时和货币费用未测；inclusive 进程／HTTP／MCP／后端时延不能相加。

## 7. 未完成项和恢复边界

| 工作项 | 暂停时状态 |
| --- | --- |
| 第二外部系统开发表 | SimpleMem 接入和 exposed pilot 完成；60 形成＋60 查询＋18 arcs **NOT_RUN** |
| U3-P | native 功能链已验证；J/N 因果比较与 thinking 变量 **NOT_RUN** |
| U3-O | 真实 key 漂移仍在；typed-ref 接口扩展 **NOT_RUN** |
| U3-W | bounded writer **NOT_RUN**；不能由零 CRUD 自动推断必须加 writer |
| U3-R | partial／unknown／重开恢复链 **NOT_RUN**，真实额外动作和未知结果未解决 |
| U4 呈现 | 仅完成离线故障定位；标签候选未实现、未冻结、未实验 |
| U4 A/U／同计算 | 无已证实的检索遗漏或候选压力入口；未触发实验，未证明机制效果 |
| MAB／MemoryArena／自然长程 | **NOT_RUN**，未因模块存在自动启动 |
| U5 独立确认 | **NOT_RUN**；SimpleMem 后续计划使用的 development 已曝光 |
| 第二独立模型家族 | **NOT_RUN**；没有新增模型资产或部署 |
| 完整 U6／研究成功／Product | 暂停报告不等于全计划完成；**NOT_ACHIEVED／NO_GO** |

恢复时先核对用户新指令、实际 Goal、工作树、服务和连续账本，再选择最小下一步。保留原始未跟踪 v27 草稿、所有旧 worktree、输入/结果/锁、失败、原始日志和数据库；不删除、不把旧 ACTIVE 当授权、不重做已通过检查。

## 8. 发布与复现

报告通过既有 Luna high Git 发布职责进入 [draft PR #72](https://github.com/minguselandy/MiLAi/pull/72)，保持 open/draft/unmerged；main 及 PR70/71 不改。精确提交和远端 SHA 由发布回执记录，不能将本报告提交当作历史实验源码。

复现旧主表使用 A/B；复现 SimpleMem pilot 使用 `9200de0`、固定 SDK、独立依赖锁、原输入、原服务/工具参数和原顺序。各阶段必须使用新隔离运行身份，不能续接当前中断业务以补齐原结果；复现本身也须等待恢复授权。

此次仅文档/结果/状态变更，执行链接、JSON、哈希、成本及 Git 范围核对；不启动模型、整套测试、构建或新开发。GitHub 自动检查的实际状态与本地已通过检查分别记录，未完成检查不写作成功。

源码 `9200de0` 的 [Fast CI 36497006083](https://github.com/minguselandy/MiLAi/actions/runs/36497006083) 已完成 success；Full 36497006081 为 skipped，未将其算作通过。报告发布提交的自动检查另按实际状态记录，不重跑模型或旧实验。
