---
status: S2_ENGINEERING_ACCEPTED_S3A_PASS_S3B_REQUIRED_NOT_RUN
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
s1_source: 4ffd17664ce9d8a6497e57b199b3a6d764adae86
source_pr: 70
product: NO_GO
---

# v6 S2 离线投影计量与 S3a 真实 smoke

S1 源码已独立发布，PR70 的 Fast36403127754 success。
在该源码、尚未精简的 full Model View 上，四个已暴露脚本全部通过，共 **54/54 task obligations**。
另对全部131个 v5 冻结请求完成 S2 离线计量；已实现的唯一精简组合可减少固定请求输入 **3.80%**，
所定义记忆上下文组件减少 **9.54%**。这未达到10%–20%目标下界，不为凑数字继续删除信息。
精简后的真实语义行为仍待 S3b 全部12-script回归证明。

## S2：先计量，再区分 Model/Audit

[离线结果](../data/manifests/next-development-v6-s2-offline-profile-20260928.json)
使用S1已验收的同131个请求、锁定Qwen tokenizer/template；原本地计数全部等于实际provider usage。
没有生成、embedding、数据库修改或真实参数扫描。

| 组件 | 131请求独立计数 tokens | compact投影后 |
| --- | ---: | ---: |
| system base | 4,978 | 4,978 |
| action JSON规则 | 9,301 | 9,301 |
| tool schemas | 75,718 | 75,718 |
| boundary protocol | 27,379 | 27,379 |
| durable memory正文及包装 | 8,784 | 8,267 |
| durable边界 | 1,703 | 1,703 |
| working state | 18,922 | 17,661 |
| working header | 1,703 | 1,703 |
| source-role labels | 3,057 | 3,057 |
| tool观察元数据 | 10,492 | 5,400 |
| 实际ToolMessage正文 | 4,386 | 4,386 |
| 保留历史正文 | 4,834 | 4,834 |
| 当前user正文 | 5,720 | 5,720 |
| 分隔符 | 196 | 196 |
| template/BPE边界残差 | 3,494 | 3,494 |
| **完整请求输入** | **180,667** | **173,797** |

组件按独立字符串计数，不当作可相加的边际因果成本；表中明确列出完整template重算后的残差。
记忆上下文overhead口径为boundary protocol、durable正文/边界、working/header、role labels和tool元数据，
共72,040→65,170，减少6,870（9.54%）；分母不包含tool schemas、原用户/历史/业务正文。
完整请求减少同6,870（3.80%）；其中65条current_request为89,241→85,879，减少3,362。
这些是固定旧轨迹的离线输入差，不是新会话实际总成本或质量收益。

两个有明确理由的字段提案先分解计量，再采用唯一组合，不做多套真实候选扫分：

- 记录形状与空容器：140次严格`{id,value:{content}}`改为`{id,content}`，
  保留完整ID、content字节/值及顺序；省略131次空open_questions和95次空active_refs，减少1,778 tokens。
  若记录还有任何额外字段，整条保持原形状；若refs/questions非空则保持。完整原对象仍在Store/trace。
- 78次模型工具观察前缀省略content_sha256，减少5,092 tokens。
  hash由程序核对和引用，现有业务/记忆工具不接受它作为Host操作参数；完整值保留于实际观察trace、
  operation audit和原checkpoint。工具调用ID、工具名、receipt观察时间及真实ToolMessage正文均保留。

不删原BOUNDARY_PROTOCOL文字、不推断当前任务意图来隐藏写工具、不去掉当前user ref或非空active ref。
receipt time继续保留，避免把潜在有用的时间信息也当成无意义噪声。
不新增安全Agent、classifier、sanitizer、reviewer或长期事实副本。

竞争解释一：上述包装和程序hash属于可从审计恢复的模型冗余，移出可降低输入而不损害任务。
竞争解释二：即使不是工具合法参数，它们仍可能影响模型的注意或历史/当前消费。
离线计数只能证明成本变化和保留字段一致，不能反驳第二解释；完整S3b是进入S4前的必要门槛。

实现约束为`memory_boundaries.model_view=full|compact_v6`，默认full，v6配置显式compact_v6。
结构化Context在renderer前持有完整记录、working state和tool元数据；不重新用字符串查找删hash。
hook原checkpoint投影、Audit View及selector输入保持full；router、容量和delivery计量使用实际Model View。

## S2 实现与离线验收

[源码与检查回执](../data/manifests/next-development-v6-s2-implementation-checks-20260928.json)
固定五个源码/测试/config文件和全部运行源码hash。Sol已停笔；Root复核五个改动文件、18份证据hash，
并直接比较完整131条full观测、86审计和131条compact有序message hash/token/capacity输入。
full与S1保持完整等价；compact逐条等于独立Root profile，180,667→173,797，非messages请求字段不变。
真实checkpoint对象经实际hook/provider送入MockTransport；原socket未捕获，比较的是锁定HTTPX编码。
原响应仅回放，不把旧usage当成compact新生成费用。

17项core与13项foundation窄测全部通过，无skip；Ruff、Mypy、boundary、tools-boundary、matrix均通过。
覆盖额外record字段、非空refs/questions、两种placement、实际graph query/attention续接、selector保留full记录、
缓存ID读取更新后的正文以及UPDATE/DELETE。131真实旧请求自身都走all，不能据此声称真实query压力验证。
首次Mypy因循环变量复用产生int/optional类型冲突，改名后通过；一次只读入口查找不存在路径的exit2保留。
没有重复广泛测试或构建，没有真实模型/embedding/共享数据库调用，连续账本保持S3a结束值。

新config仅改变recipe_id并显式设置compact_v6；其他参数/工具/current_request不变。
公开库默认仍是system/full。S3b完整12-script语义回归尚未运行，工程验收不代表compact质量通过。

## S3a：四个已暴露脚本的完整真实链路

[预先协议](MILAI_NEXT_DEVELOPMENT_V6_S3A_SMOKE_PROTOCOL_20260928.md)
与本地freeze `23396f4b3d3fea2897e515f7e8e02a651408b791fc001bd3bed3aad51dcc94fc`
绑定S1源码、旧inputs/config、原义务子集、服务和隔离；各脚本只运行一次，Root串行调用。
详见[结果与连续成本](../data/manifests/next-development-v6-s3a-smoke-results-20260928.json)。

| 脚本 | 公开消息 | task义务 | 实际观察 |
| --- | ---: | ---: | --- |
| revised_location | 4 | 13/13 | 真正CREATE/同ID UPDATE；当前cupboard D-9与原历史L-2分别正确 |
| dynamic_world | 4 | 23/23 | 预约及label一次，实际get_reservation；存储旧规划仍为not booked |
| explicit_delete | 3 | 13/13 | 独立TX/CR；真正DELETE TX、CR identity/body不变，后续当前缺失正确 |
| one_reply_format | 2 | 5/5 | LOCAL:单句解释只用于当次；下一session普通句式，Store始终空 |
| **合计** | **13** | **54/54** | **current26/26、later8/8、persistent20/20** |

历史问答答为`L-2`，在明确retained上下文中唯一指向原locker；未新增“必须重复locker一词”的隐藏要求。
当前LOCATION答复严格为指定两行。所有保存/更新/删除声明由实际工具回执和后续Store读取支持。
20次实际HTTP都有输入、最终模型材料、路由/交付及审计关联；raw ToolMessage后续确实交付给Host。
四个namespace、checkpoint与world独立；没有controller、semantic retry或基础设施retry。

新增费用：20 generation calls，input26,629/output855，合计27,484 generation tokens；
5 embedding calls/115 tokens。业务工具reserve_and_label1、get_reservation1；
记忆工具CREATE4、UPDATE1、DELETE1。13次操作审计与checkpoint观察的逻辑bytes/CPU/wall也保留在结果。
全部20次走all，本轮最多2个records，没有query/attention触发。
进程wall27.50秒、子进程user CPU22.94秒/system CPU1.71秒；HTTP wall合计10.36秒。
物理Store I/O、单独write CPU、GPU时间、货币费用及未计时离线分析仍为unknown，不填零。

连续账本：**3,145 generation calls /3,998,838 generation tokens /22,336 embedding tokens**。
after SHA `db0b1e4ea95b2c68155e742627cfbbc9fb4c4f9c68d56d5f01aca4f5ea64aa6b`；
与20次唯一provider IDs、5次embedding的差额完全核平，history与limits未变。
新UUID、历史措辞和独立运行的实际总成本不能解释为压缩；本轮实际Model View尚未精简。

## Reflection 与推进条件

1. 支持：显式S1装配可在真实工具/Store/后续会话链路上保持这些已暴露能力。
2. 反驳：没有发现“仅mock等价但实际接线失败”的现象；小样本不排除其他失败。
3. 首断点：本轮未出现语义断点；S2观察到hash/空容器/包装实际重复输入成本。
4. 简单解释：S3a保留原prompt，成功主要是已暴露能力复现，不是新泛化证据。
5. 简单方法：只分Model/Audit的少量字段，无需删工具、重写规则或新增模型。
6. 复杂度：保留full默认，用一个明确compact_v6研究配置验证变化。
7. 过拟合：字段规则通用且不读取case ID/答案；所有效果确认仍是exposed，不能称unseen。
8. 反例：额外record字段、非空refs、真实工具续接及query/attention容量必须在S2窄测保留；
   S3b完整12脚本之后才测试S4独立任务和引用角色。
9. Continue：唯一S2候选已实现并通过工程验收；源码发布并冻结后运行全部12 scripts/156 task obligations。
10. 理由：工程与smoke已通过，少量可恢复字段有真实成本收益；模型质量尚须回归，不能提前宣布成功。

S3b任何退化先停止并定位删去的信息，不通过额外prompt修分。S4–S9及第二家族/长程的条件门槛仍未完成；
总体研究NOT_ACHIEVED，Product NO_GO。
