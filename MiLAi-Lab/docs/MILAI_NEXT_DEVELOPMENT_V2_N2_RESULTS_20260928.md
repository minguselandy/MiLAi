# v2 N2 / X3：固定 bank 完整读取结果

状态：**10 条路径全部完成；本切片 Pivot 独立 A/查询增强，继续独立 N3 与 N5。总 Goal 仍 ACTIVE。**
方法提交 `575360295946a77847702a527271f66102375365`，见 [PR63](https://github.com/minguselandy/MiLAi/pull/63)。
执行依据[预先固定的协议](MILAI_NEXT_DEVELOPMENT_V2_N2_FIXED_READ_20260928.md)、
[rubric](../data/diagnostics/next-development-v2-n2-fixed-read-r1/rubric.json)，
逐路径结果、实际 HTTP 身份、费用和冻结见[机器清单](../data/manifests/next-development-v2-n2-results-20260928.json)。

## 主要结果

五种条件的最终答案均为 2/2 正确，完整历史条件用最少生成 tokens。
显式 A 和查询增强在本切片没有增加任务收益；应停止把它们当下一阶段默认必需调用。
这些是一个已暴露 arc、两个相关前缀的条件对照，不能据此宣布统计等价、所有规模无效或稳定 unseen 收益。

| 条件 | 最终答案正确 | 生成调用 / tokens | embedding 调用 / tokens | 成功 State READ / 失败 READ |
| --- | ---: | ---: | ---: | ---: |
| all 全读 | 2/2 | 3 / 3,447 | 0 / 0 | 1 / 0 |
| query 普通检索 | 2/2 | 3 / 3,189 | 2 / 387 | 1 / 0 |
| query_enhanced 同目录增强 | 2/2 | 5 / 3,889 | 2 / 433 | 1 / 0 |
| a_selector 显式 A | 2/2 | 6 / 5,540 | 0 / 0 | 2 / 1 |
| full_history 完整历史参照 | 2/2 | 2 / 1,836 | 0 / 0 | 0 / 0 |

这里的调用包含选择、实际 Host 续接及全部额外读取；不能只比较首响应或忽略 selector 费用。
A 比普通 query 多 2,351 生成 tokens；增强比普通 query 多 700 生成及 46 embedding tokens。
token 类型分别报告，没有用任意汇率相加为美元或总算力。

## 方法、共同能力与实际链路

各条件复制同一当前 bank，background 为三条 State，combined 为五条；不分别重新形成记忆。
维护与版本反馈关闭，ordinary memory 统一为空，各组提供同样的完整合法历史、State 目录和
`search_memory`/`read_record` 权限。Host 可以直接答复，也可以多轮真实读取后回答。
H 没有预交付 State 正文，但仍有共同目录及 State READ 能力；本轮它实际上没有调用工具。

background 保留五条实际历史消息；combined 拼接合法的此前两 session，再替换当前问题为只读构造诊断，共九条。
两张原 bank 中的“预约失败”卡是业务执行前模型生成的声称，保留而不认证为真实回执。
新问题、历史内联和空 ordinary memory 均已在运行前声明，不能把本轮称为未改原生 benchmark。

Root 先冻结源码、三份输入/配置/rubric、真实工具合同、各组顺序及独立 scope/Store/checkpoint。
正式 prepare 身份为 `6ff5dc46c355753f725afcef46f920c5a22395614d037245bc173bf597a99e77`，
执行冻结 SHA256 为 `b52a42a51df76c6e11d6c6f5fd90289800ffb703322bc2ee0819e5390fb61740`。
Root 串行运行，保留全部十个结果、真实 provider 请求/响应、工具返回和费用，没有重试或替换样本。
153 项源码/入口/包装身份已与上述 Git 提交逐项核对，后续 N3 修改不能代替本轮源码复现。

实际核对全部首 Host 请求中的合法历史与各自冻结输入相同，工作视图确实进入每次 Host HTTP 请求；
六个 READ 返回均真实交付后续请求。十条路径的 State ID、revision、正文、needs 和空 ordinary memory 均保持。
真实工具调用共五次成功 State 读取、一次错误 memory 读取；所有任务均完成最终回答。
进程终态、存储不变、读取成功和答案正确分别记录，没有相互替代。

## 选择覆盖不等于答案收益

combined 的普通 query 与增强 query 均选择 handout 和 welcome，没有预选 field 正文；
两者仍直接正确回答两项计划。这说明本切片共有历史已经提供所需材料，不能仅因所选 ID 缺 field 就判任务失败。
A 选择两项正确计划并真实读取两条 State，答案仍与简单条件相同，但付出了额外控制和续接费用。
H 两例均无预交付正文、无实际工具读取，答案正确；保留它作为强表示参照。

以上只证明实际材料、读取和答案之间的可见关系，不能证明模型内部因果采用了哪一段证据。
当前 bank 小、历史充分，是原先冻结条件；不在看见结果后扩充干扰记录以制造 A 优势。

## 保留的一次读取失败

**Observed：** background A 条件的 Host 用 State ID 调用了 `read_record(target_kind="memory")`，
实际返回 `not_found`；随后利用已有上下文给出了正确 handout 总结。
**Expected：** 若决定读取目录中的 State，应使用 `target_kind="state"`。
首断点是 Host 工具参数，工具按约定查了错误对象类型并如实报告未找到，没有伪造成功记录。

实际因果链为：A 选 handout/field → 正文进入 Host → Host 选择错误 target_kind → 空 ordinary memory 中未找到 →
错误回执进入后续实际请求 → 最终答案正确。任务评分按预冻结规则仍通过，但读取失败及其费用单列保留。

竞争解释：一是 Host 对两类对象的选择混淆或生成路径波动；二是候选呈现与普通 query 不同、State 正文未送达。
实际比较发现 background A 与普通 query 的**整个首 Host 请求对象相同**，后者却选对 `state`，
因此第二种解释不符合这两条请求证据；temperature=0 不能据此当作逐次响应严格确定的保证。
这也不能把单次错误归因为 A 算法，或进一步断言服务波动的具体底层原因。

短 `not_found` 回执使 A 这条续接的输入比成功 State 读取少 56 tokens。
这部分差额来自失败轨迹，不是压缩或选择效率；报告保留而不修成成功轨迹。
最小下一步是继续 N3 的独立固定前态比较及 N5 的连续任务验证，不为这个可恢复的单例追加提示变体或重跑。
若未来需评估对象类型合同修复，应单独冻结共同合同与同等机会；本轮没有程序替模型改 target_kind。

## 费用、局限及后续决定

本轮新增 **19 次生成 / 17,901 generation tokens / 4 次 embedding / 820 embedding tokens**。
连续账本由 2,799 / 3,486,504 / 19,273 更新为 **2,818 / 3,504,405 / 20,093**，
终点 SHA256 为 `9488b804f5b3c6eecdbcc79b833220f2cab13ac7b39c9bac7e75a35b6e16064f`。
当前层未知 generation/embedding usage 均 0，原 sealed 历史和失败未清除。

19 个生成 provider ID 均唯一；embedding 响应没有 provider ID，按真实 trace 路径/响应行识别四次 HTTP，
不虚构 ID。两类费用分别与连续账本增量完全对齐。State 初始化禁用索引，没有 seed embedding；
40 次直接 State seed put 与各路径 seed CPU/wall、bank 逻辑调用/字节、HTTP wall 在清单中分别记录。
bank 计数包含观测和读取，不能重复叠加 seed 子指标；ordinary 读取 CPU、物理 I/O、完整进程端到端 wall 未独立测量，保持 unknown。
这里没有新形成或跨回合维护，不能验收 WP7 全生命周期节省或用本轮差额推算长期摊销。

Continue：完成 N3 必要更新、保持、CREATE 与 pending 的独立诊断，再按完整计划评估 N5。
Pivot：本小 bank/充分历史切片取消独立 A 和查询增强作为必需机制，保留普通 query/all 与完整历史的强对照。
Stop：不扩充无任务依据的干扰、不针对已暴露前缀改写措辞、不重跑直至更好、不认领通用 State–Attention 优势。
N4 没有版本变化触发证据；N6 仍须信号与资源条件，Product 仍为 NO-GO。

## 复现与交付边界

按方法提交 5753602 的入口 `tools/run_fixed_state_read.py prepare` / `run-job` 和协议中的十条固定顺序复现，
使用新的 runtime_root/run ID/namespace，原连续账本单独保存，不覆盖本轮制品。
源码提交包含公开合成输入/rubric，评分仍由 Root 事后执行，不进入 runtime；原始 HTTP、数据库和私密 DSN 留在 ignored artifacts。
检查与必要构建已在源码发布前完成；本次结果发布仅核对 JSON、链接、哈希和差异，不重复模型调用、测试或 build。
公开精简清单不等于提供全部本地原始轨迹，后续源码不要求同时满足所有历史锁。
