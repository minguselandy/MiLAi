# MiLAi 总体实验报告：NEXT_DEVELOPMENT v4 / F9

**工程边界已实现并通过必要检查，方法稳定仍未建立。本轮两次完整 B 回归均为 5/6；停止本次修订循环，不创建 C，不启动 D。**
R1 遗漏当前格式；唯一通用接口修订后的 R2 恢复了格式，却在另一例完整计划复述中遗漏物品身份。
这不是 6/6：不能把两个版本的成功轨迹拼接。研究总目标未达成，Product 仍为 NO-GO。

本报告完成 F9 的证据审查与交接，不把工程完成改称原计划的“方法稳定”。按用户“任务结束后暂停 Goal、生成总体报告并上传 GitHub”的要求收口；
实际 Goal 状态由线程工具在发布核对后设置，文档不代替该状态。没有本轮之后的自动实验授权。

## 范围、版本与要求落实

[原 v4 计划](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v4.0.md)共 862 行，Root 完整阅读，原始草案字节保留，SHA
`c9a149cf5a7ad1ff6fc833702391813afd4c1494187bdb350c8e545e8b42625e`。执行授权来自用户实际 v4 Goal。
基线为 v3 发布提交 `44f9291bb0c7f3b6d5c9c71dadf76d1924a81eb2`，当前分支为
`feat/lab-memory-boundaries-v4-20260928`，位于独立工作树。main、历史实验树、v27 草稿和旧 WIP 均保留。

| 要求 | 交付与证据 | 验收状态及局限 |
| --- | --- | --- |
| F0 | [九类失败与基线](MILAI_NEXT_DEVELOPMENT_V4_F0_BASELINE_20260928.md)，32 项来源核对 | COMPLETE；没有重跑旧实验或重评旧分数 |
| F1 | 程序核对实际 owner/turn 工具执行，B0 answer 无模型自证 | ENGINEERING_ACCEPTED；B 无虚称保存，不能代替语义完整性 |
| F2 | 六类来源进入最终 HTTP 副本，原 checkpoint 和工具 JSON 保留 | ENGINEERING_ACCEPTED；真实旧助手冲突消费 NOT_RUN |
| F3 | 临时 task/constraints/ref/open questions；更新/删除解析当前记录 | ENGINEERING_ACCEPTED；R1 当前格式失败，R2 此项通过；新场景稳定性未证 |
| F4 | 业务回执接收时间、来源、部分/未知结果与记忆分工 | ENGINEERING_ACCEPTED；真实动态世界冲突 NOT_RUN |
| F5 | 原 strict CRUD/exact READ；独立事项、局部更新、负例范围 | 工程通过；两轮新形成5/5、修订保持1/1、负例3/3；仅暴露切片 |
| F6 | 配对真实事件的 provenance 审计，不增加手填证据 schema | ENGINEERING_ACCEPTED；semantic support 仍不由程序推断 |
| F7 | all → ordinary query → 仅真正超容量时可选 Attention | 工程通过；44 次真实生成全部 all，无真实选择瓶颈 |
| F8 A | [工程报告](MILAI_NEXT_DEVELOPMENT_V4_ENGINEERING_20260928.md)与[机械清单](../data/manifests/next-development-v4-f8a-checks-20260928.json) | 44 个去重相关 nodeids、静态/模板/零模型 prepare 和必要构建通过 |
| F8 B | 六个原 v3 暴露脚本，两次完整独立版本回归 | R1/R2 均 GATE_FAILED；不是只跑 pilot 后报全通过 |
| F8 C | A/B 同时通过后才可创建8–12个新脚本 | NOT_CREATED / NOT_RUN；前置门槛失败，不能称已完成方法验证 |
| F8 D | 真实选择瓶颈后的普通检索/working-state query/Attention 比较 | NOT_TRIGGERED；不能推断 Attention 已被证明无效 |
| F9 | 本报告、逐轮失败模板与 Reflection、费用、复现、状态交接 | REPORT_COMPLETE；Stop 本轮修订，研究未达成 |

F1–F7 的代码路径和边界分别可检查，但真实 B 是组合实现，没有逐项消融，不能分配因果收益给某个组件。
新行为由 `memory_boundaries.enabled=true` 显式启用，名称仍为 B0；旧默认及历史 C 保留各自复现合同。
没有新增 D/E 方法、持久事实副本、语义事项分类器、额外 memory agent 或自动补答案。
保留失败候选源码供复现不代表将其晋升为稳定方法。

## 四层结果：两个版本分开判断

[R1 详细报告](MILAI_NEXT_DEVELOPMENT_V4_B_R1_RESULTS_20260928.md)与[R2 详细报告](MILAI_NEXT_DEVELOPMENT_V4_B_R2_RESULTS_20260928.md)
给出原答、Store、实际请求、冻结身份、失败解释和逐阶段成本；[最终清单](../data/manifests/next-development-v4-final-acceptance-20260928.json)汇总要求与哈希。
每轮6个脚本、15条公开消息，后续消息使用新 session，只获得合法当前普通记录。输入和原 rubric 字节不改，Root 离线评分，无 Judge。

| 层/指标 | 原 v3 B0参考 | v4 B R1 | v4 B R2 |
| --- | ---: | ---: | ---: |
| 任务：完整脚本 | 5/6 | 5/6 | 5/6 |
| 任务：严格逐消息完成 | 14/15 | 14/15 | 14/15 |
| 任务：当前 BRIEF 正确 | 0/1 | 0/1 | 1/1 |
| 记忆：新形成 | 5/5 | 5/5 | 5/5 |
| 记忆：修订＋无关内容保持 | 1/1 | 1/1 | 1/1 |
| 记忆：持久正例完整链 | 4/4 | 4/4 | 3/4 |
| 记忆：引用/临时/只读范围正确 | 3/3 | 3/3 | 3/3 |
| 消费：完整后续使用 | 7/7 | 7/7 | 6/7 |
| 消费：下一 session 无格式泄漏 | 1/1 | 1/1 | 1/1 |
| 成本：生成 calls / tokens | 22 / 19,752 | 22 / 27,613 | 22 / 28,571 |
| 成本：embedding calls / tokens | 7 / 230 | 7 / 262 | 7 / 246 |

两轮均5 CREATE、1 UPDATE、1普通 search，未出现误持久化、重复事项、最终假 saved、业务动作、纠正或控制调用。
没有业务动作不等于已经通过 live-world correctness；没有真实旧助手冲突不等于 authority 投影已改善冲突消费。

R1 的 temporary 首请求只有 system 与原当前 user，记忆为空、工具为零，完整当前要求确实到达 HTTP，但回答没有 BRIEF。
首断点是 Host 约束采用。竞争解释是 JSON 外壳与用户可见 answer 合同不够清楚，或 Host 本身未可靠执行当前指令。
一次局部 Astra 讨论后，Sol 只增加通用 answer 字段映射段，没有样本前缀、特殊路由、schema/parser 或服务改动。

[R2 事前协议](MILAI_NEXT_DEVELOPMENT_V4_B_R2_PROTOCOL_20260928.md)冻结唯一候选、temporary 先行与完整回归拒绝规则。
pilot 两消息通过后才完成另外五例；R2 field_plan 的后续答案是：

> Your current sample-delivery plan is for 4 units to be delivered to rack R-7, packed in sealed sleeves.

三个点名字段数量/目的地/包装均正确，但省略 Harbor sampler trays。原 rubric 明列物品且要求 all plan fields，因此完整后续使用为失败。
报告同时保留“三字段3/3”和“完整性失败”，没有把它描述成整个答案错误；也不另因省略未预约陈述扣分。
完整物品信息已正确形成、持久化并送入实际后续 HTTP，首断点在最终回答的完整性。
可能是新增 format/language/length 说明改变了简略程度，也可能是问题列举字段导致的普通回答变化；单次切片不能唯一归因。

两个首断点都在正确交付材料之后，改写 Store 或自动补字段不能说明原问题已解决。
按预冻规则拒绝 R2 晋级，停止本轮措辞/anchor 变体。不放宽原门槛、不替换失败题、不补用 R1 的 field_plan 成功。
本轮最小下一实验为无追加实验，转入报告与暂停交接。

## 七项工程解释与方法稳定审计

| 原计划 §20 工程问题 | 可复核的实现 |
| --- | --- |
| 来源 | 当前/历史用户、实际工具、普通记录、历史助手、当前提案分别标记；事件 ID/hash 可追溯 |
| 对象归属 | checkpoint 是 Event；普通 Store 是 Durable Memory；当前 task/ref 是 Working State；业务工具/数据库是 World |
| 修改权 | Host 通过原工具修改授权 scope；程序只投影视图、解析引用和记执行审计，不自动生成语义事实 |
| 退出 | task/ref 随当前 turn/session 重建；记录经真实 UPDATE/DELETE；审计历史保留；业务由工具改变 |
| 实际可见 | prepared view 与带实际 generation ID 的 delivery 分开；完整 HTTP、选择记录及 checkpoint 可对照 |
| 执行结果 | 程序从配对 ToolMessage 记录成功/失败/partial/unknown；模型答案不能覆盖回执 |
| 无重复自证 | B0 final 仅 answer，不要求 receipt refs/committed 或额外证明调用；C 保留历史复现 |

工程验证包含真实 LangGraph/ToolNode 接线和 Mock HTTP，不是语义模型通过率。R2 仅合同常量修改，2项必要 Graph 检查与 Ruff 通过；
没有为文档发布重跑全套测试或构建。可选 selector 任意崩溃后的 ID 缓存恢复仍未验证；没有把该局限藏为完成能力。

| 方法稳定条件 | 现有实证 | 尚缺 |
| --- | --- | --- |
| 持久形成可靠 | 暴露六脚本的形成5/5 | 新小样本完整验证 |
| 局部更新可靠 | 两轮同一修订1/1且无关内容保持 | 新事项/删除/长链组合 |
| 临时约束不泄漏 | 两轮均无持久污染和下一 session 泄漏 | 新约束；当前采用本身R1曾失败 |
| read-only 不写 | 同一暴露例两轮通过 | 独立新场景 |
| stale memory 不替代 live world | 仅工程边界检查 | 实际动态世界语义验证 NOT_RUN |
| 旧助手不覆盖有效材料 | 仅来源投影机械证据 | 实际冲突消费 NOT_RUN |
| 额外控制费用可接受 | 控制调用均0，生成调用与B0相同 | 输入总量增加；未证明可回收成本或质量优势 |

R2 的 field_plan 记录仍含无时间限定的 “Nothing has been booked”。本切片业务没有变化，不能算已经观察到过期动作，
也不能拿本次正确无动作证明 F4 已稳定。F8 C 的保存、更新、独立事项、临时、引用、动态世界、只读、删除、助手冲突、多记录十类新覆盖均未运行。
44次生成全部使用小 bank 的 all；没有实际 query 容量瓶颈，§19 的 State–Attention 研究重新准入条件未满足。

## 全成本和连续账本

| 轮次 | Input tokens | Output tokens | Generation calls / tokens | Embedding calls / tokens |
| --- | ---: | ---: | ---: | ---: |
| R1 | 26,742 | 871 | 22 / 27,613 | 7 / 262 |
| R2 | 27,707 | 864 | 22 / 28,571 | 7 / 246 |
| v4 总计 | **54,449** | **1,735** | **44 / 56,184** | **14 / 508** |

两轮失败和 R2 pilot 全部包含，零重试/纠正/selector/Judge。相同六例相对 v3 B0，R1/R2 generation tokens 分别增加约39.8%/44.65%，
完整脚本均5/6。没有成本回收证据。两轮顺序/提示不同且样本已暴露，这是固定切片比较，不是 SER 消融或总体统计等价证明。
embedding 因实际写入正文改变而变化，不称压缩收益。

| 账本时点 | Generation calls | Generation tokens | Embedding tokens |
| --- | ---: | ---: | ---: |
| v4 起点 | 2,950 | 3,729,307 | 20,729 |
| R1 后 | 2,972 | 3,756,920 | 20,991 |
| R2 后 | **2,994** | **3,785,491** | **21,237** |

唯一连续账本为原树 `artifacts/ser-v20/budget.json`，终点 SHA
`e47de5a370b7c6dad581d836a440411055c01c137ec4c589f95389109a4ca668`。旧账本及历史未知费用没有清零。
F0/F8 A/报告没有新增真实调用；开发代理、Mock 使用与真实实验成本分别记录。

两轮 HTTP wall 合计21.033秒；进程 wall 合计69.957秒，user/system CPU 合计68.801/5.281秒。
普通记录观察86次/12,968 bytes；namespace guard36次/144 bytes；checkpoint30次/43,341 bytes；
程序 audit30次/36,281 bytes且无额外 checkpoint 读取。路由 inclusive CPU/wall 合计1.629/1.565秒，内部读开销不再重复加计。
逐轮形成/维护/使用和观察明细在结果清单；物理 I/O、普通写入 CPU、GPU 小时及货币成本仍 unknown。

## 历史实验如何延续

| 阶段 | 已发布观察 | 结论边界 |
| --- | --- | --- |
| P0–P8 / v21 | 机制开发、集成、冻结与有限验证 | 不等于稳定 unseen 收益 |
| P9 / v23 | B1 6/10，A3/A4 7/10；无自然 refresh/rebase | 分差不能直接归因为 SER |
| P11 / v24 | formation三提示均0/2；reconciliation strict2/3、必要维护0/1 | 已停止这些提示词路线 |
| P12 / v25 | 八条应用运行，包含持久化、恢复、scope、部分副作用 | 过期动作、容量循环、错误key和虚构ID未消失 |
| P10 / v26 | B1 strict2/4，native Mem0 4/4；5,324 vs53,852生成tokens | 不同系统合同，约10.1倍；ADD-only不证明同ID修订 |
| LSA / v1–v2 | N2/N3固定bank未得A/U净收益；N5原生arc两臂5/5但State空，构造生命周期两臂0/1 | 不选最佳轨迹，不把空处理或单段节省当总收益 |
| v3 | B0/B1完整5/6、持久4/4；C完整4/6、持久2/4 | C一次格式正例保留，但未获扩大门槛 |
| v4 | R1/R2完整5/6；程序边界可检查，最终消费仍有遗漏 | 新样本稳定性未建立，停止本轮接口修订循环 |

历史对应提交、详细分母和原报告链接见[v3总体报告](MILAI_NEXT_DEVELOPMENT_V3_OVERALL_EXPERIMENT_REPORT_20260928.md)、
[v2总体报告](MILAI_NEXT_DEVELOPMENT_V2_OVERALL_EXPERIMENT_REPORT_20260928.md)和[长程证据表](MILAI_LONG_HORIZON_EVIDENCE_MAP_20260927.md)。
第二独立模型家族仍 NOT_RUN，v27 原草稿/元数据保留，新增模型权重下载为0、无新推理服务。
大范围密度/比例/参数鲁棒性前置条件未满足；旧 M1、持久 Decision State、结构化 ODR 和条件性分支不自动重启。

## 复现与发布

| 身份 | 固定值 |
| --- | --- |
| F0 发布 | `8d4ddc4a315bd97f4a7a62a84ec51f23fbaf53eb` |
| R1 方法 | `e070456b57ce0b941813948464b2c1bf870c99f6` |
| R1 执行 freeze | `1f887cbded2ebbeaae07a5c1cd8deaeab10fbe20a803a09b0e376dc2907c9c17` |
| R2 方法 | `24ef49945cd12eccbd85792fee3c256bf3fe6d2a` |
| R2 执行 freeze | `593190a15d7be29b2d4be6ee3d532b6505a63fc2832727978a27a9e1ef6a4ffd` |

分别 checkout 对应方法，使用 `data/diagnostics/next-development-v4-b-regression-r1/` 或 `r2/` 的 config/order，
及其引用的原 v3 六份 inputs；scorer/rubric 仅离线使用，不送入 runner。
正式 prepare/run 入口见[R1复现说明](MILAI_NEXT_DEVELOPMENT_V4_B_R1_RESULTS_20260928.md)，R2另遵守其先行门槛。
新复现必须使用全新run目录/namespace/Store/checkpoint/业务状态；不得覆盖原 attempted 目录或清零总账。
私密 DSN 仅经 `MILAI_LANGMEM_POSTGRES_DSN` 注入，不输出、不入Git。

Host保持 Qwen3.6-35B-A3B-FP8，温度0、max_tokens4096、thinking=false、容量65536、每公开消息12次；
embedding保持 bge-m3/1024维。实际 HTTP 并发1；未修改既有 vLLM parser、服务参数或部署。
R1 [Fast CI](https://github.com/minguselandy/MiLAi/actions/runs/36380454177)和R2 [Fast CI](https://github.com/minguselandy/MiLAi/actions/runs/36381555861)均success；Full为skipped，不计作通过。
本次报告仅查JSON/链接/哈希/diff，不为发布重复模型、检查套件或构建。

Root负责协议、合成材料、真实调用、评分、账本和报告；复用Sol xhigh为源码唯一负责人，Astra xhigh仅参与一次具体接口冲突，
Luna high负责Git提交/推送。开发代理不是实验Host，不声称创建子代理改变主会话模型。
发布到[draft PR67](https://github.com/minguselandy/MiLAi/pull/67)，base保持v3分支；不自动merge、改main或关闭历史PR。
公开源码/配置/合成inputs/rubric/精简结果/文档，原始私密轨迹、凭据、数据库、环境、权重、缓存和构建产物继续排除。

## F9 Reflection 与最终决定

| 总规划 §32 问题 | 本轮判断 |
| --- | --- |
| 1 支持什么 | 来源/执行/临时引用可用现有graph与工具表达；暴露形成与更新基本成功 |
| 2 反驳什么 | 工程可观察或单个格式通过即可推断完整方法稳定，证据不支持 |
| 3 首断点 | R1当前约束采用；R2正确完整材料到最终完整回答之间 |
| 4 更简单解释 | 普通Host指令采用/回答省略；无证据归因于Store丢失或容量截断 |
| 5 更简单方法 | 普通B0/strict CRUD/all作为参考；保留程序审计，无需模型自证或额外控制层 |
| 6 复杂度 | 零新增控制调用仍增加约40%–45%生成tokens；没有实测收益补偿 |
| 7 过拟合风险 | 六例重复暴露、方法已变；禁止拼轨迹、换失败样本或继续同义提示循环 |
| 8 反例 | 三个点名字段均正确但完整计划遗漏物品；格式成功与全任务成功可以分离 |
| 9 决定 | Stop本轮修订；保留工程与全部反例；C/D不运行，方法稳定未达成 |
| 10 理由 | 预冻质量门槛失败且唯一候选退化；扩控制、扩样本或换模型不能补当前证据 |

本轮没有触发原计划 §16 中所有可能的 STOP 条件，也没有证据宣布整个 State–Attention 方向无效。
本次停止依据是已发布 R2 协议的唯一候选拒绝规则、A/B准入失败及用户要求报告后暂停；不借用v3收口条款宣告v4方法完成。
可继续保留普通记忆和这些工程能力作为未来基底；新的实验方向须有新的明确指令和独立冻结。
本轮报告、证据与交接完成，完整方法/研究目标仍未达成。
