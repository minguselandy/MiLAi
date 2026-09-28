# v4 F8 B R1：持久能力保留，当前格式门槛未过

结论：**5/6 完整脚本，A/B 晋级门槛未过；F8 C 未创建，F8 D 未触发。**
方法提交 `e070456b57ce0b941813948464b2c1bf870c99f6`，沿用六个已暴露 v3 输入原字节及原语义 rubric。
Root 串行执行 6 个隔离进程、15 条公开消息；每条新 session，Retained，无历史旁路。
[冻结协议](MILAI_NEXT_DEVELOPMENT_V4_B_REGRESSION_20260928.md)、
[精简结果与证据身份](../data/manifests/next-development-v4-b-r1-results-20260928.json)保留全部结果，不能以之后的修复覆盖。

## 评分和实际链

| 项 | R1 | 证据与限制 |
| --- | --- | --- |
| 新事项形成 | 5/5 | 五次真实 CREATE，后续独立 session 请求含实际当前记录 |
| 修订＋无关内容保持 | 1/1 | 同一 ID UPDATE source-link 位置，heading/date 保留 |
| 后续使用 | 7/7 | 四个持久脚本、引用/临时边界和两次只读使用按原分母 |
| 持久正例完整链 | 4/4 | field_plan、editorial_revision、independent_note、read_only |
| 引用/临时/只读范围 | 3/3 | 引用无 adopted preference，临时无写，明确只读无写 |
| 当前 BRIEF | 0/1 | 实际 answer 缺少首词；解释内容仍为一句 |
| 下一 session 无临时泄漏 | 1/1 | 无 BRIEF，也无持久临时规则 |
| 完整脚本 / 逐消息任务 | 5/6；14/15 | 唯一失败为 temporary 第一条 |

程序审计未用最终 saved 文本认证执行；实际为 5 CREATE、1 UPDATE，无额外/重复记忆写入和假 saved。
唯一普通 search 在 quotation 后续查询；无业务动作、控制/selector、correction、重试、容量拒绝或 HTTP 错误。
22 个 generation ID 唯一，链审计逐请求匹配原当前输入、角色、实际记录材料、工具正文/ID、接收时间、Working State 引用及后续回答。
原 checkpoint 不变由 F8 A 机械检查覆盖；B 的实际工具内容、当前前缀和配对回执进一步核查。

此批没有动态世界变化或旧助手冲突，不能据此声明 F4 或冲突消费稳定。
field_plan 仍存有无时间限定的 “Nothing has been booked”；在本批世界没有变化，因此不是已经观测到 stale action，
也不能当作历史观察表示已经完善。所有路由为 all，尚无 Attention 研究准入证据。

## 首个断点及下一步边界

**Observed / Expected。** temporary 第一请求完整包含本次以 BRIEF 开头及不成为长期规则的要求，
但实际 JSON `answer` 从 “A title …” 开始。Expected 是该字段的用户可见文本以 BRIEF 开始；下一 session 不延续。

**实际因果链。** 原用户字节 → 实际 system＋CURRENT TASK user 请求、空 memory → 一次 Host 生成合法 JSON、漏前缀 → 零工具/零 Store 写入。
输入没有截断，首请求没有中间工具或旧助手消息，容量充足。首断点是 **Host 对可见当前回答约束的消费**，不是 Store、检索或回执解析。
该次为 1046 prompt＋34 completion tokens，provider ID `chatcmpl-bbd0b7ddb383c4cc`。

至少两种解释并存：

1. JSON-action 要求完整响应是 JSON，但没有明确区分 transport envelope 与 `answer` 内用户可见文本；模型可能遗漏本可兼容的格式要求。
2. 当前 Host 在这一工具合同下的约束遵循本就不稳定；再次改写说明可能只是对暴露题的措辞过拟合。

最小通用候选是明确回答字段与当前用户约束的关系，仅改变 v4 当前任务/输出合同，不出现样本前缀或答案，
不改变 schema、parser、thinking、温度、服务或调用容量，不加 extractor、correction 或机械证明调用。
重复当前 Human 到尾部目前缺乏依据：这次首请求本来只有 system＋user，不能归因于长 ReAct 尾部遗忘。

混杂因素：单个已暴露格式例、没有 transport 因子对照，F1–F7 组合上线，ID/接收时间和自然回答变化也影响 tokens。
Root 复用现有 Astra 做一次具体局部判断；它只分析、不评分实验或执行调用，之后由原 Sol 收敛必要源码。
最小下一实验已单列为 [R2 条件回归](MILAI_NEXT_DEVELOPMENT_V4_B_R2_PROTOCOL_20260928.md)：一次通用候选、原 temporary 两消息先行，
通过才继续其余五例；失败即拒绝，不再换措辞。R1 结果冻结时没有追加调用，后续状态按 R2 独立记录。

决定为 **Pivot 到当前任务/回答接口；Continue 已通过的简单 B0 持久路径；不扩展控制机制或修改 Store 来修格式**。
若只靠暴露题专用规则或无止境措辞变化才改善，应 Stop 此修补路线，不能偷偷越过 C 门槛。

## 全成本

| 生命周期成本段 | Generation calls | Input / output tokens | Total tokens | Embedding calls / tokens |
| --- | ---: | ---: | ---: | ---: |
| 形成 | 8 | 10,306 / 351 | 10,657 | 4 / 179 |
| 维护（含独立新 note） | 4 | 5,386 / 202 | 5,588 | 2 / 76 |
| 使用/负例 | 10 | 11,050 / 318 | 11,368 | 1 / 7 |
| 合计 | 22 | 26,742 / 871 | 27,613 | 7 / 262 |

独立新 note 的质量计入形成事件，费用只归 maintenance 一次。失败当前格式及下一消息均计入费用。
相同六例旧 v3 B0 为 22 calls／19,752 tokens、5/6；R1 calls 不增加，tokens 增加 **39.8%**，没有完整质量增益。
这是组合系统在暴露切片上的比较，不是单一机制的因果消融，也不是 unseen 或压缩收益。

HTTP wall 合计 10.944 秒；六进程 wall 35.248 秒，user/system CPU 34.395/2.484 秒。
43 次普通记录观察：6,640 logical bytes；18 次 namespace guard：72 bytes；15 次 checkpoint 读取：21,717 bytes；
15 次程序 audit：18,173 bytes、额外 checkpoint 读取 0。完整路由核算 wall 0.780 秒／CPU 0.812 秒，为 inclusive 时间，不与内部费用重复相加。
物理 Store I/O、普通写入 CPU、GPU 时间、货币费用未测，保持 unknown。

连续账本从 **2950／3,729,307／20,729** 到 **2972／3,756,920／20,991**
（generation calls／generation tokens／embedding tokens）。结束 SHA
`207f2e6909724e687400d45d194674d33ef2d852f95290647e78b71fed8db2da`。
没有清零，也不把开发代理或 Mock tokens 混入实验费用。

## 复现与 Reflection

使用上述方法提交、原 [config](../data/diagnostics/next-development-v4-b-regression-r1/config.json)和
[order](../data/diagnostics/next-development-v4-b-regression-r1/execution-order.json)；正式 freeze SHA
`1f887cbded2ebbeaae07a5c1cd8deaeab10fbe20a803a09b0e376dc2907c9c17`。
冻结绑定 158 项源码、原输入/rubric、新门槛、工具/模型、scorer、各组 namespace/Store/checkpoint/world、Root 编排/审计及连续账本起点。
既有 runner 入口为 `tools/run_persistent_memory.py prepare` 和 `run-phase`；以全新 run 身份重现，不复用或重跑原 attempted 目录。
私密 DSN 仅环境注入，原始 trace/数据库/制品继续 ignored；公开 manifest 给出各原 trace/result/manifest 哈希和逐回合精简证据。

| 总规划 §32 问题 | R1 判断 |
| --- | --- |
| 1 支持什么 | 简单 B0 在此暴露切片保留形成、局部更新、保持及跨 session 使用 |
| 2 反驳什么 | 只增加来源标签/当前引用即可修复当前格式，未获支持 |
| 3 首断点 | 完整可见要求到 Host answer 之间，非存储/检索/回执 |
| 4 更简单解释 | JSON 回答字段职责歧义或 Host 约束遵循失败，均比缺一个维护器更直接 |
| 5 更简单方法 | 保留原 CRUD 与 all；最多单一通用回答接口修正，不恢复 C |
| 6 复杂度 | 同调用数增加 39.8% tokens；程序审计成本也记录，不能宣称更省 |
| 7 过拟合风险 | 六例全部已暴露，BRIEF 曾反复出现；禁止样本路由/输出自动补词 |
| 8 反例 | 用户原文已在最后一条 user 消息，当前格式仍遗漏，下一 session 却不泄漏 |
| 9 决定 | Pivot 当前任务/回答边界；C 不创建，D 不触发 |
| 10 理由 | 未过事前门槛；先收敛单一可证伪通用修复，不能扩新样本掩盖失败 |

总体 Goal 仍 active，方法稳定未建立，Product NO-GO。此报告记录 R1，后续实验另列，绝不拼接最佳轨迹。
