# MiLAi 总体实验报告：NEXT_DEVELOPMENT v5 / V9

**v5 的评价合同、开发、冻结验证和完成审查已完成。唯一 R2 候选通过全部 10 个已暴露回归脚本及 2 个新脚本：156/156 任务义务、89/89 显式回答义务、67/67 持久义务。**
接受显式启用 `memory_placement=current_request` 的研究 recipe，结论限定为本轮单模型、小规模合成验证。
原默认 `system` 布局仍存在当前值与历史值混淆；源代码默认值没有改变。
初始 R1 的 9/10、诊断与新内容对照的失败全部保留，不能把后续成功覆盖原结果。

这是原计划 §20 的小样本门槛通过，尚不证明广泛 unseen 稳定性、跨模型泛化或生产可靠性。
长期研究目标仍为 **NOT_ACHIEVED**，第二独立模型家族 **NOT_RUN**，Product **NO_GO**。
本报告与精简证据由 Luna 发布至 [PR #68](https://github.com/minguselandy/MiLAi/pull/68)；线程 Goal 仅在远端核对完成后标记本次 v5 计划完成。
本轮无后续自动实验、下载、部署或合并安排。

## 1. 范围、身份与完成审计

授权来自后来明确恢复的实际 v5 Goal，已取代旧 v4 的任务后暂停安排。
[原计划](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v5.0.md) 1,204 行已完整阅读，原 DRAFT/PAUSED/NOT_STARTED 字节保留，SHA-256：
`ff79dcd0e24458175c520913bac29b842a69b5ebbc15681545748b14b2eb52a2`。
文档中的历史状态不代替线程 Goal；原 main、旧工作树、失败、锁、账本、v27 草稿与元数据均保留。

| 要求 | 交付及实际证据 | 完成审查 |
| --- | --- | --- |
| V0 / §6 | [六脚本重新分类](../data/manifests/next-development-v5-v4-reinterpretation.json)：50 项身份、12 轨迹、30 回答、44 生成 ID | COMPLETE；v4 两轮 legacy 分数仍各 5/6 |
| V1 / §7、20.1 | [四层评价合同](MILAI_NEXT_DEVELOPMENT_V5_EVALUATOR_CONTRACT_20260928.md)，人工可见依据，离线组合器 | COMPLETE；未引入隐藏完整性要求、Judge 或 runtime rubric |
| V2 / §8 | [离线义务链](MILAI_NEXT_DEVELOPMENT_V5_OFFLINE_ANALYSIS_20260928.md)：每版本六脚本合计 55 项，两版本共 110 项 | COMPLETE；保存、交付、回答、工具/world 分开审查 |
| V3 / §9、16 | 66 个旧 HTTP 请求九类组件分析；JSON 空白候选只离线测量 | COMPLETE；约 1.2% 输入节省，未部署；不声称消除旧开销 |
| V4 / §10 | [首轮协议](MILAI_NEXT_DEVELOPMENT_V5_PROSPECTIVE_PROTOCOL_20260928.md)：10 脚本、27 消息、133 项义务，各 2–4 sessions | COMPLETE；全部类别覆盖，首次调用前冻结 |
| V5 / §11 | [首轮 R1](MILAI_NEXT_DEVELOPMENT_V5_PROSPECTIVE_R1_RESULTS_20260928.md)：未改 v4 R2 runtime；70/71 显式、59/59 持久 | COMPLETE_WITH_FAILURE；98.59% 不能替代 H 冲突的独立门槛 |
| V6 / §12 | 未启动独立提示/答案补全候选；唯一消费修复归入 V7 | NO_SEPARATE_BRANCH；V6 对接口修复要求的完整旧回归及至少两条新约束已在 R2 覆盖 |
| V7 / §13、20.2 | [单候选协议](MILAI_NEXT_DEVELOPMENT_V5_AUTHORITY_R2_PROTOCOL_20260928.md)，四次诊断通过后才执行预冻 14 jobs | COMPLETE；候选 12/12，动态 world 与保留历史分别通过 |
| V8 / §14、20.3 | 131 次生成全走 all，最多 6 条、351 candidate tokens；无实际 query miss 或容量瓶颈 | NOT_TRIGGERED；Attention 保持关闭 |
| V9 / §17–20 | 本报告、逐项人工观测、费用核账、复现与 GitHub 发布 | REPORT_COMPLETE；发布后的实际 SHA/CI/Goal 由独立回执核对 |

v5 分支为 `feat/lab-obligation-contract-v5-20260928`，基于 v4 报告 `676fe4d32005cefbfb01daa4fe24425edf5a5e21`，PR 仍叠放在 v4 分支上，未合并 main。

| 身份 | 固定值 |
| --- | --- |
| R1 实际执行提交 | `3c207f836ef7f3e35694f4b9cf242846884c3012`；runtime 语义基底 v4 R2 `24ef49945cd12eccbd85792fee3c256bf3fe6d2a` |
| R1 结果发布提交 | `18851d3934e05621ddffecebbfebf69c04c831d5` |
| R2 全部诊断/确认源码及输入提交 | `ec682a3a8b1ac58b41733b882ed0bad367347fed` |
| R1 有效 execution freeze | `1ee06b7ff36ebb40ce05e1a8a5de2505e5b0d98eb066f2b2c446963998af8aa3` |
| R2 诊断 freeze | `9b9eb1d24d1d2345de11d5a3a3dbacc8b3923bd218514226f9dbf2998993bbe9` |
| R2 确认 freeze | `afd135a7253712347362f666c837258f250747da17780761331cc5428fe9c6a0` |
| R2 runtime 文件 SHA | `7aad791facac87fe814869b4c2f684792c6a05c877844cc1cd35d0d734d4cdd3`，`src/milai_lab/methods/memory_boundaries.py` |
| R2 config SHA | `91105f1ca25cc5cdd21077141eb86bd8913ad2ed061a7693f3e46eb89db23ecd` |

Root 负责文档/语义数据、冻结、所有真实 HTTP、评分、成本与验收；Sol xhigh 是唯一源码负责人；Astra xhigh 只处理保留历史的具体困难冲突；Luna high 负责授权 Git 发布。
开发代理消耗与实验 Host 消耗分开。没有通过子代理声称更换主会话模型。

## 2. 评价合同与初始失败

v4 R1 的 BRIEF 遗漏属于明确当前义务失败；v4 R2 的 field_plan 已正确回答三个点名字段且不预约，却没有额外重述物品。
v5 将后者单列为 diagnostic completeness，保留旧 legacy fail。
竞争解释是“current plan 隐含完整复述”与“旧 rubric 加入点名字段以外要求”；未来输入明确区分完整问答和部分问答，避免以歧义继续改 runtime。

四层分别为 current explicit、persistent、later use、diagnostic completeness。
显式回答汇总等于 current 加 later use；任务汇总再加 persistent，不重复计算同一层义务。
持久义务包括所需保存/修订/删除、保持其他事项及不误持久化等范围要求，不等同写工具次数。
所有会造成任务失败的要求都有用户可见依据。Root 人工判定，离线代码校验标识/引用并组合，既不调用 LLM，也不认证语义真值。

R1 只运行一次预先冻结的现有方法；10 脚本全完成，9/10 严格通过：

| 指标 | R1 |
| --- | ---: |
| current explicit | 41/41 |
| later use | 29/30 |
| 显式回答合计 | 70/71（98.59%） |
| persistent | 59/59 |
| 全部任务义务 | 129/130 |
| 部分问答的额外完整性诊断 | 0/3；不加入任务分母 |

完整计划、部分字段、临时格式、独立事项更新、引文、只读、DELETE、动态 world、六事项 bank 均通过。
所需 11 次变更事件完成：8 次 formation 请求涉及 15 个事项，另有 2 次 update 与 1 次 delete。
不存在本轮可见的虚称保存、误持久化或重复业务动作。

**Observed：** H 在 S1 保存 6，S2 真实同 ID 更新为 9，回到 S1 问当前值时仍回答 6。
**Expected：** 回答实际已交付的当前 durable 值 9，同时保留历史 6。
真实因果链为用户更新 → manage update → Store 同 ID 当前 9 → HTTP 中完整当前记录 9 + 原 transcript 6 → 答案 6。
首个已证实断点是 **CURRENT_TASK_CONSUMPTION**；不是形成、更新目标或材料交付失败。

两个主要竞争解释：一是 system 中当前材料与近端旧 transcript 的呈现导致错误取材；二是模型对当前/历史目标的消费本身波动或不稳定。
旧 6 同时存在于 user、tool proposal、assistant，不能只归因于 assistant 文本。
重新读取已经完整交付的记录、增加持久 State 或换检索并无首断点证据；继续延长权威提示也缺少依据。
因此只做一处组合呈现修复，并用历史反向问题检验它是否变成“总选新 Memory”。

## 3. 唯一 R2 实现及工程验证

增加可选字段 `memory_boundaries.memory_placement=system|current_request`，缺省仍为 system，非法值明确拒绝。
候选仅从首 system 的请求副本取出唯一 Durable Memory 块，将完全相同的块放到最后一个真实 user 请求副本的 `[CURRENT USER REQUEST]` 前。
原 graph/checkpoint、Human 原文、历史、工具 JSON、工作引用、schema 与公开工具合同均保持；query 仍从原 Human 取得。
all/query/attention/empty 及容量计算均检查实际将发送的布局，不额外复制材料或添加 controller。

既有 chat template 不允许非首位 system，因此此改动同时改变位置和承载 role。
它是**组合呈现候选**，不是纯位置因果实验；附加的 Memory 也不因此成为用户新陈述、事实真相或当前业务权威。

[源码检查回执](../data/manifests/next-development-v5-authority-r2-checks-20260928.json)包含 10 项模块窄测、7 项实际 Graph/ToolNode/mock HTTP 跨层检查、Ruff、Mypy，以及默认 all/query/attention 的完整有序 UTF-8 请求与容量输入对照，均通过。
跨层检查使用真实本地 SQLite；不冒充真实 Host 或 PostgreSQL 效果样本。9 条依赖弃用 warning 保留。
前期离线 evaluator 的 20 个去重目标、两次实际 CLI 集成及 package boundary/验证矩阵检查也已通过。
本次未改包入口或依赖，未构建、未重跑全套测试；报告阶段仅检查数据、链接和哈希。
源码 [Fast CI 36391234190](https://github.com/minguselandy/MiLAi/actions/runs/36391234190) 已读回 success，Full composition 按工作流条件 skipped，不能称 Full pass。
没有 Schema/API/权限/Canonical 数据行为修改；新增 Lab recipe 配置项保持 opt-in。回退可选默认 system 或对应旧提交，无需改历史记录。

## 4. 真实诊断、完整回归与新内容

两阶段的输入、义务、组顺序和停止门槛均在第一次 R2 调用前发布冻结。
每个 job 独立 namespace、Store、checkpoint、SQLite 业务世界；脚本内按其 session ID 真实回访。
Root 串行执行，同一完整脚本一次正式尝试，未替换失败样本或拼接轨迹。

阶段一按 system rep1 → candidate rep1 → candidate rep2 → system rep2 完整执行 6→9 的保存/更新链，追加问最初确认值的历史问题。
这复用正式 runner，避免新增续接执行器；各自形成真实前缀与 UUID，**不是相同 HTTP 前缀的配对实验**，重复也不是独立样本。
[四 job 证据](../data/manifests/next-development-v5-authority-r2-diagnostic-results-20260928.json)及 48 项人工观测均保留。

| 阶段一布局 | 当前应为 9 | 历史应为 6 | 完整脚本 | 任务义务 |
| --- | ---: | ---: | ---: | ---: |
| system | 0/2（均答 6） | 0/2（均答 9） | 0/2 | 20/24 |
| current_request | 2/2 | 2/2 | 2/2 | 24/24 |

所有形成、同 ID 更新、持久范围与无业务动作检查均通过。阶段一共同门槛满足后才开始阶段二。
阶段二先以候选完整重跑 R1 十脚本，再按预定交错顺序执行两个新脚本的 system/candidate 对照，共 14 jobs、43 消息。
[确认结果](../data/manifests/next-development-v5-authority-r2-confirmation-results-20260928.json)及[185 项人工观测](../data/diagnostics/next-development-v5-offline/authority-r2-confirmation-observations.json)包含候选 159 项（含 3 diagnostic）与新 baseline 26 项。

| 阶段二子集 | 脚本 | current | later use | 显式合计 | persistent | 任务合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 候选：已暴露十脚本 | 10/10 | 41/41 | 30/30 | 71/71 | 59/59 | 130/130 |
| 候选：两个新脚本 | 2/2 | 14/14 | 4/4 | 18/18 | 8/8 | 26/26 |
| **候选验收集合** | **12/12** | **55/55** | **34/34** | **89/89** | **67/67** | **156/156** |
| system：两个新脚本 | 0/2 | 14/14 | 0/4 | 14/18 | 8/8 | 22/26 |

“current” 是冻结义务层名称；新脚本的当前数值与历史数值问答都依赖 later use，故 baseline 的 current 层通过不代表数值回答正确。
所有分母以冻结定义为准；部分问答额外三字段仍为 diagnostic fail，不改变候选 12/12。

两个新脚本在候选首次效果评价前撰写，含反向数量 12→4 与非数值地址 locker L-2→cupboard D-9，且分别加入新当前格式要求。
关键实际答案如下，完整原答见结果清单：

| 脚本 / 目标 | system | current_request |
| --- | --- | --- |
| reversed_count / 当前 4、COUNT: 开头 | `COUNT: 12` | `COUNT: 4` |
| reversed_count / 最初历史 12 | 回答 4 | 回答 12 |
| revised_location / 当前两行 LOCATION + 地点 | `LOCATION` 换行 `locker L-2` | `LOCATION` 换行 `cupboard D-9` |
| revised_location / 最初历史地点 | cupboard D-9 | locker L-2 |

格式判定边界明确保留：冻结 COUNT 要求为一句且以 COUNT: 开头；`COUNT: 4` 与 `COUNT: 12` 按一句省略式回答处理，两臂同一口径，未追加句号或完整系动词要求。
因此两条新当前格式记 2/2，但不声称验证了完整语法句生成。LOCATION 的实际形式严格为两行；内容值另评分。

完整链路核查确认：候选 H 的当前答案为 9，旧 6 的 transcript 仍在；历史反向问题并未被新值覆盖。
DELETE 真正删除目标且保留另一事项；更新保持同一 ID 及无关字段；临时、引文、只读没有误写。
动态 world 实际执行一次 reserve_and_label、后来真实 get_reservation 查询到已创建结果；旧 not-booked 记忆仍保留，但没有覆盖 live world，也没有重复预约。
六条独立事项真实形成并交付，不靠固定样本 ID 或标准答案分支。
28 个 job 全部 terminal 只是机械前提，结论另依据实际 HTTP、工具/Store/world、后续交付与最终回答。

## 5. 完整费用与成本收益边界

[连续费用清单](../data/manifests/next-development-v5-total-costs-20260928.json)绑定全部 28 组 trace/result SHA，131 个唯一 provider ID。
各阶段成本均含 formation、maintenance、use，全部失败与对照保留。

| 阶段/子集 | 生成调用 | 输入 | 输出 | 生成总 tokens | embedding 调用 / tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| R1 十脚本 | 42 | 58,135 | 1,904 | 60,039 | 19 / 380 |
| R2 四次诊断 | 24 | 33,254 | 705 | 33,959 | 8 / 104 |
| R2 暴露回归候选 | 41 | 55,919 | 1,895 | 57,814 | 18 / 376 |
| R2 新内容候选 | 12 | 16,654 | 344 | 16,998 | 4 / 62 |
| R2 新内容 system | 12 | 16,705 | 348 | 17,053 | 4 / 62 |
| **v5 总计** | **131** | **180,667** | **5,196** | **185,863** | **53 / 984** |

| 生命周期 | 生成调用 | 输入 / 输出 | 生成总 tokens | embedding 调用 / tokens |
| --- | ---: | ---: | ---: | ---: |
| formation | 48 | 69,047 / 2,370 | 71,417 | 38 / 786 |
| maintenance | 29 | 40,257 / 1,288 | 41,545 | 13 / 182 |
| use | 54 | 71,363 / 1,538 | 72,901 | 2 / 16 |

同十脚本 R1→候选由 60,039 降至 57,814（−2,225，约 3.71%），生成少 1 次，embedding 少 1 次。
DELETE 本轮省去一次搜索，且 UUID、形成文字与输出轨迹各自生成，因此这不是压缩因果收益或部署平均成本估计。
新内容两臂也只差 55 生成 tokens，诊断候选反而比 system 多 89 tokens，不能只挑便宜切片。

[42 个固定 R1 请求的离线移位](../data/manifests/next-development-v5-authority-r2-offline-cost.json)每条完整 template 输入差均为 0，58,135→58,135；全部原 provider prompt counts 核平。
它支持此批相同内容的呈现变更不增加直接输入开销，满足“不继续加长接口”的局部门槛，不代表任何新轨迹总费用必然相等。
V3 的 JSON 空白候选没有部署，旧 v4 相对 v3 的大额边界/元数据开销仍未解决，不能用本轮结果声称方法已比最简单 ordinary B0 更便宜。

实际 memory 工具为 38 CREATE、12 UPDATE、2 DELETE、3 search_memory，参数逻辑字节 5,640；不是物理数据库 I/O。
业务为 2 次 reserve_and_label、2 次 get_reservation，分属两个隔离 world 验证，无单 job 重复动作。
controller/selector/correction 调用均 0，单消息最多 3 次生成，低于 12 次上限。
HTTP 错误、未知 usage、本地容量拒绝均 0；131 次实际输入计数全部与本地模板一致。

| 观察开销 | 逻辑调用 | 逻辑 bytes | CPU / wall 秒 |
| --- | ---: | ---: | ---: |
| Memory read | 245 | 35,987 | 0.257511 / 0.445250 |
| namespace guard | 84 | 336 | 0.031359 / 0.101444 |
| checkpoint read | 86 | 183,715 | 0.062408 / 0.062381 |
| operation audit | 86 | 134,563 | 0.010665 / 0.011000 |

route inclusive CPU/wall 为 3.996909/3.822184 秒，含嵌套观察，不重复相加。
累计 HTTP wall 62.935225 秒；28 个成功进程 wall 182.378324 秒，user/system CPU 160.879982/12.917060 秒。
含前置失败的所有启动 wall 为 184.680161 秒，user/system CPU 165.539982/13.331364 秒。
物理 Store I/O、普通写入 CPU、GPU 时间、货币费用、prepare 与 Root 离线分析时间未完整测量，保持 unknown。
单次墙钟不是稳定性能结论，开发代理 token 不混入上述账本。

连续账本始终为原树 `artifacts/ser-v20/budget.json`，没有重置历史或上限字段：

| 账本 | 生成请求 | 生成 tokens | embedding tokens |
| --- | ---: | ---: | ---: |
| v5 起点 | 2,994 | 3,785,491 | 21,237 |
| v5 增量 | 131 | 185,863 | 984 |
| **本轮终点** | **3,125** | **3,971,354** | **22,221** |

起点 SHA `e47de5a370b7c6dad581d836a440411055c01c137ec4c589f95389109a4ca668`；
终点 SHA `98b02945ab195ad94e37061f97c5ba5eb8068ecd87ff47caef9f76f9e51fdd15`。

## 6. 失败保留、局限与反思

R1 曾在发布前 prepare，发布改变 Git SHA 后 runner 拒绝旧身份，发生在数据库/HTTP/runtime 尝试之前。
十份 identity 对照仅 git_sha 不同，原 prepare、freeze、失败启动均留在 `prospective-r1/`，其旧 freeze SHA 为
`208001c087ef185673f492d882aad4f6e795ee9c07cd8db35c3f5ce572eaddcc`。
独立 `prospective-r1-published/` 在发布提交上重新 prepare/freeze 后才正式运行，没有语义重试；失败启动 wall 2.301837 秒，账本未增。
R1 离线组合器第一次因额外顶层元数据键拒绝输入，移除该非评分键后同一人工判定通过，未改模型结果。
其他 V0–V3 离线机械修正保留在原分析记录，不计真实模型样本。

R2 确认 freeze 的 `isolation` 自由文本误沿用 H 的“每 job 保存 6→9”描述；该句不准确。
实际机器绑定的 14 个 steps、输入 SHA、prepare identity、执行命令和 trace 对应各自脚本，隔离条件均核对通过。
保留原冻结字节并在此纠正说明，不能事后改 freeze 使记录看起来从未有误。

证据局限：一个 Qwen 家族、短合成脚本、明确用户持久意图、最多六事项；两个新脚本与原冲突任务族相近，不能称独立用户 holdout。
R2 的十脚本已暴露，诊断重复不是新样本；没有第二模型、长程压力、广泛比例/密度/参数扫描。
位置和承载 role 耦合，各 job 的真实前缀、UUID、工具轨迹独立产生，无法排除模型波动，也未唯一确定旧 user/tool/assistant 哪个角色主导。
没有测得 adversarial Memory 注入等新的权限边界；本轮正确取材不证明来源可信或事实真实性。
当前 stored content、历史 transcript、live tool 仍由任务目标决定用途，不能简化成“最新永远优先”。

| 总规划反思项 | 本轮结论 |
| --- | --- |
| 1 支持什么 | 在已形成并完整交付时，单一请求呈现变化可改善本组当前/历史消费；完整链路不是只看程序退出 |
| 2 反驳什么 | pooled ≥95% 自动满足独立冲突门槛；取到当前记录就一定正确回答；只看 Store 就能判断效果 |
| 3 首断点 | v4 额外完整性是评价歧义；v5 R1 H 是 CURRENT_TASK_CONSUMPTION |
| 4 更简单解释 | 默认呈现的竞争线索与模型消费波动；无证据先归为检索/形成缺陷 |
| 5 更简单方法 | 保留普通 CRUD 与全部历史，只移动一份已交付材料；默认布局仍可作为参考 |
| 6 复杂度收益 | 一个 opt-in 字段、零额外控制调用；固定请求直接输入增量 0，实际收益局限于本组 |
| 7 过拟合风险 | 两个新内容仍共享任务结构、旧十脚本已暴露，12/12 不是广泛 unseen 保证 |
| 8 反例 | system 当前/历史两边答反；候选对历史问正确选旧值，动态 world 选真实业务查询而非陈旧记忆 |
| 9 决定 | GO：接受此冻结小范围研究 recipe；STOP：本次执行结束，不追加提示候选/Attention/重复到通过 |
| 10 理由 | 所有预定候选验收项通过、成本核平；不足部分明确留给未来另行授权的研究 |

最小后续研究建议仅作交接：若用户另行授权，可先冻结独立任务结构与第二模型家族的小样本验证，再决定是否扩大范围。
不得据此自动下载/部署第二模型、恢复 v27 草稿、启用 State–Attention 或迁移 Product。
若未来再次出现已交付但答错，先区分目标解释与取材，按实际首断点处理，不能继续堆叠权威措辞。

## 7. 复现与发布边界

使用对应执行提交恢复源码和公开输入；旧结果按旧提交复现，报告提交不能替换原 prepare 所绑定的 Git SHA。
R1 按 `3c207f83`，R2 按 `ec682a3a`。输入/配置/义务/顺序分别见：

- [R1 execution order](../data/diagnostics/next-development-v5-prospective-r1/execution-order.json)。
- [R2 diagnostic order](../data/diagnostics/next-development-v5-authority-r2/diagnostic-order.json)。
- [R2 confirmation order](../data/diagnostics/next-development-v5-authority-confirmation-r2/execution-order.json)。

锁定 foundation 环境与既有 tokenizer，Host `http://127.0.0.1:7860/v1/`、Qwen3.6-35B-A3B-FP8，temperature 0、max_tokens 4096、thinking false、context 65536；embedding 7861、bge-m3、1024 维。
不更改共享 vLLM、parser 或上下文设置。私密 DSN 仅注入 `MILAI_LANGMEM_POSTGRES_DSN`，不打印，不提交。
`config.json` 继续指向原连续账本；异机复现若必须重定向资源位置，应另记配置差异及新的执行身份，不覆盖历史。

下列是未来获授权复现时使用的现有 runner 模板；本报告没有再次运行它。
`$FOUNDATION_PY` 指既有锁定 Python；`$CASE_CONFIG`、`$CASE_INPUTS`、`$PHASE` 按上述顺序文件逐项取值；每项使用全新 `$RUN_NAME` 和 `$RUN_DIR`：

```bash
PYTHONPATH=src "$FOUNDATION_PY" tools/run_persistent_memory.py prepare \
  --config "$CASE_CONFIG" --inputs "$CASE_INPUTS" --run "$RUN_NAME" \
  --arm B0 --runtime-root "$RUN_DIR" --output "$RUN_DIR/prepared.json"

PYTHONPATH=src "$FOUNDATION_PY" tools/run_persistent_memory.py run-phase \
  --config "$CASE_CONFIG" --inputs "$CASE_INPUTS" --run "$RUN_NAME" \
  --arm B0 --runtime-root "$RUN_DIR" --prepared "$RUN_DIR/prepared.json" \
  --phase "$PHASE" --stage "$RUN_NAME"
```

先 checkout 已发布提交，再零模型 prepare；核对全部 source/input/config/工具/模型/顺序/隔离与账本起点后冻结，才逐项串行 run-phase。
R2 第二阶段仅在第一阶段冻结门槛满足后执行，不能以预期通过代替实际门槛。
runtime 命令不接受 rubric。离线人工观测按 job 提取对应合同后，可用现有组合器：

```bash
PYTHONPATH=src "$CORE_PY" -m milai_lab.analysis.obligation_trace \
  --contract "$CASE_CONTRACT" --observations "$CASE_OBSERVATIONS" \
  --output "$CASE_REVIEW_OUTPUT"
```

逐项核对实际 user 原文、provider 请求/ID、工具参数/回执、Store 同 ID 变化、后续 HTTP 的交付、最终回答与业务世界。
UUID 和非严格确定性的生成文本不作为复现 gold；不改输入、换失败样本或将新运行冒充原执行。
原始 traces、数据库、prepare/freeze 与 Root 编排/审查产物留 ignored artifacts，公共 manifest 提供 SHA 和精简合成证据；仅克隆 GitHub 不包含本地私密原始 trace。
复现可生成新的独立轨迹，不能仅凭公开哈希重建未发布原始日志。

报告发布只包含 Lab 源码/配置/窄测（已发布）、合成输入/rubric、精简结果及文档。
密钥、DSN、私密轨迹、数据库、环境、模型权重、缓存和构建产物不入 Git；历史实验锁保持。
最终仅检查新 JSON、证据 SHA、链接、diff 与远端身份，不为发布重复测试或调用模型。

## 8. 与长期证据的关系

[v21](MILAI_SER_V21_FINAL_RESULTS_20260927.md) 的机制/来源控制、[v23](MILAI_SER_V23_RESULTS_20260927.md) 的 MERIT 6/10 对 7/10、
[v24 R2](MILAI_LIFECYCLE_V24_RECONCILIATION_R2_RESULTS_20260927.md) 的维护 2/3、
[v25](MILAI_APPLICATION_V25_RESULTS_20260927.md) 的八条持久应用轨迹及
[v26](MILAI_EXTERNAL_MEMORY_V26_RESULTS_20260927.md) 的 native Mem0 4/4 对 B1 2/4 均为独立历史阶段。
v23 没有自然 refresh/rebase，v26 系统契约和费用不同且仅 ADD，均不能转换为本轮因果消融或同 ID 修订证据。
v26 53,852 对 5,324 生成 tokens 的约 10.1 倍成本取舍仍成立；本轮不重写这些分母。

[v3 总结](MILAI_NEXT_DEVELOPMENT_V3_OVERALL_EXPERIMENT_REPORT_20260928.md)与
[v4 总结](MILAI_NEXT_DEVELOPMENT_V4_OVERALL_EXPERIMENT_REPORT_20260928.md)保留其失败、停止与未触发分支。
当前 B0 是后来 ordinary-memory runner 的 arm 名称，不等同早期 native LangMem B1。
v5 证明的是显式义务分离后，一处通用呈现修复在限定验证集通过；未填补跨模型、长程自然任务和稳定 unseen 收益的证据空白。
