---
version: v15.0
date: 2026-09-26
status: COMPLETE_WITH_BASELINE_FAILURES
foundation_decision: GO
scope: MiLAi-Lab
experiment_arm_kind: RESEARCH_PROTOTYPE
source_mapping_sha256: 99fba610b55237aa31de8ad7f25312dc65e847d944b44b3bde1cde572b3e5ef9
foundation_lock_sha256: e3b98d9ff15030afeb34eb7548edae3571230f1c20db89766ec7b0c5b12c4090
---

# v15 LangMem 公共基线交付与行为结果

[Goal v15](MILA_LANGMEM_FOUNDATION_GOAL_v15.md)的 A–F 已完成。固定上游 LangMem 工具、LangGraph ReAct、持久 Store、独立 checkpoint、业务恢复、原生评测及连续计账已接通；G0–G5 技术验收通过，结项为 **COMPLETE_WITH_BASELINE_FAILURES**。最终同一源码从空 namespace 和原始世界完成 12 例／20 会话诊断及 arc0 的 5 episodes／7 条公开消息，无中断。诊断人工语义通过 **7/12**，MERIT 原生通过 **4/5**、dependent **1/2**。

基线存在明确语义错误：首次退款约定未保存，模型随后编造 5000 分约定并在原生模拟世界实际退款，而当前约定是 1774 分；另一次正确退款后，长期记忆仍写着“尚勿处理”。技术 GO 表示底座可供后续研究，不表示语义可靠、方法有效或 Product 可用。未启动 v16，也未增加新题或逐题调提示。

机器可读入口为[终态清单](../data/manifests/langmem-foundation-v15-results.json)，执行前身份为[最终冻结清单](../data/manifests/langmem-foundation-v15-final-freeze.json)，操作入口见[复现文档](MILA_LANGMEM_FOUNDATION_V15_REPRODUCTION_20260926.md)，机械修复过程见[开发记录](MILA_LANGMEM_FOUNDATION_V15_DEVELOPMENT_20260926.md)。原始请求、数据库和世界快照保留在 ignored artifacts；清单只公开精简结果与证据散列。

## 实际交付与冻结身份

| 项目 | 最终身份或行为 |
| --- | --- |
| Lab 开发基点／v14 reference | `197b75ce9b6db0bebfb272955d625d741e34bd36`／`0802d34f49db45bd654fc745d33da3252c0d4e24` |
| 上游 | LangMem `9d033b47d9ce53e37e92c92241b0496c0278932e`，MIT，声明版本 0.0.30；实际安装三个调用文件与 checkout 一致 |
| 依赖 | Python 3.11.13；LangGraph 1.1.10、prebuilt 1.0.13、checkpoint 2.1.2、PostgresStore 2.0.25、SQLite saver 2.0.11；详见 [upstream manifest](../data/manifests/langmem-foundation-v15-upstream.json) |
| 配方 | `langmem-hotpath-react-json-action-v1`，`json_action`，`free_order_arguments_v1`；上游默认 manage/search 名称、正文 str、参数及 instructions |
| Agent | `langgraph.prebuilt.create_react_agent` v1；工具固定顺序、并发 1；普通最终回答结束，无自动预取、旧 Host 或额外维护循环 |
| 模型 | Qwen3.6-35B-A3B-FP8、temperature 0、thinking=false；输出 4096、上下文 65536、每条公开消息最多 12 次实际尝试，跨进程容量不清零 |
| 长期状态 | 上游 PostgresStore，现有隔离服务中的专用 Lab 数据库／非超级用户角色；1024 维 content 索引、bge-m3 直接批量 embedding |
| 会话状态 | 独立持久 SQLite checkpointer；同 episode 共用 thread，下一 episode 新 thread；长期 namespace 区分 run／arm／user |
| 业务恢复 | 原生模拟世界＋最小 call journal；已知完成结果可重交付，pending 未知不盲目重做；新 call 的相同参数仍可合法执行 |
| 源码 | 22 文件映射 `99fba610…`；lock SHA `e3b98d9f…`，完整值见页首和 [lock](../data/locks/langmem-foundation.lock.json) |
| 数据 | 原有 12 例输入 SHA `a6852f07…`；原 arc0 SHA `32e50fc2…`、world SHA `221f4be1…`；MERIT 源码 `293933d96b1d1849e1f20d1bb324def5de9ed33f` |

vLLM **最终保持原设置**。native 预检因缺少 auto-tool-choice/parser 返回 HTTP 400，保留 unknown 预留；之后曾尝试临时 parser 容器，用户要求保留设置后撤回，该临时容器没有模型请求。原容器 AutoRemove 导致停止后自动删除，已用相同镜像字节和原 command、环境、挂载、端口、GPU、共享内存等重建；最终只读核对全部一致。镜像引用由原 tag 改为同一不可变 image ID，不是镜像内容变化。

实际 Host 为 vLLM 0.27.1／build `6e448d0ea9bf3d88d898b65449ca6dc2aec170ac`，xgrammar 0.2.3，image `sha256:e0cfcfcb9b86e2c2d0d52a93689773f20f380cb8e050a24ce550c44f6f55c5eb`。原 command 为 `/models --port 7860 --tensor-parallel-size 2 --max-model-len 65536 --served-model-name Qwen3.6-35B-A3B-FP8 --gpu-memory-utilization 0.9 --reasoning-parser qwen3 --default-chat-template-kwargs {"enable_thinking": false}`。embedding 服务 vLLM 0.9.1 未变。此交付验证的是 JSON-action 适配，**没有认领 native parser 通过**。

适配器合并起始 system 消息，并用 JSON calls 正文表达历史工具调用，以兼容原 Qwen 模板。生成 schema 的 arguments 放宽字段顺序；实际执行仍按原工具 schema 验证。非法参数返回相同 call ID 的错误 ToolMessage，工具本体和业务 journal 不执行；同批合法调用继续按顺序处理。坏 JSON、截断或坏 envelope 不截取执行。上游允许空 content、未知 ID update 为 upsert 等行为照实保留，没有补入旧 MiLAi 语义合同。

## 技术验收和验证范围

| Gate | 结果与证据 |
| --- | --- |
| G0 身份 | PASS：固定 Git 安装、依赖锁、原数据、模型清单、配方与 22 份源码一致；最终 sdist 含同一 lock 和 22/22 文件 |
| G1 工具接入 | PASS：spike r3 普通回答、真实业务调用、实际 LangMem create/search；非同词查询 `nutrition constraints` 返回持久记忆，score 0.5576698613861267 |
| G2 持久与隔离 | PASS：冷进程公共 Store 返回相同 ID／正文，同 thread 合法续接，新 thread 首次请求只有 system＋当前 user；run／arm／user 隔离，原业务保持执行一次 |
| G3 评测可信 | PASS：原生 world/schema/functions/checkers 与原消息序列保持；gold、rubric、未来消息不进模型；失败和 unknown 全部计账 |
| G4 行为交付 | PASS：最终 R2 同一源码完成全部 12 例和完整 arc0；下表保留语义反例，不拼接 R1/R2 成绩 |
| G5 范围 | PASS：45 个旧运行文件、v14 账本与路线图散列未变；仅 pyproject/uv.lock 为新可选组改变；无 Product 或未见题消费 |

受影响的 8 项窄测试通过；Ruff、可选组 7 模块 mypy、默认无该组 99 模块 mypy、可选测试缺组跳过、uv lock、active boundary 和工具依赖边界通过。实际 LangGraph 离线回放验证了非法参数→错误回执→修正调用→最终回答，也验证了混合合法／非法批次和业务 journal 恢复分支。原生 MERIT 的 5 集／7 消息 mock 检查了工具和 checker 接线。必要 packaging 验证通过，包内没有私有 DSN、数据库或运行制品。

未运行历史全套测试、全量 benchmark、新 seeds、MemSyco 正式验证、B1/M1/M2 对照或模型 Judge。R2 自然轨迹未出现 R1 的无效 action 参数，不能把两轮差异解释为已观察到真实模型的错误自修复收益；该分支证据来自受控离线回放。没有声称通用 exactly-once，成功业务到结果落盘之间的未知窗口仍需原业务查询或幂等能力核对。

## 最终 R2 诊断：12 例、20 会话

run 为 `v15-b0-diagnostic-r2`。12 例均执行并终结，20 会话完成，0 中断。root 逐条按原 rubric 的语义项目核对，无模型 Judge；旧 Host 的 source_refs、literal_uses 等专属结构字段记 N/A，不为 B0 新增协议。

| 案例 | 语义 | 实际观察与失败分类 |
| --- | --- | --- |
| d01 | PASS | 回答 540；没有保存临时计算或格式 |
| d02 | FAIL | K17 消息实际发送一次并取得 MSG-K17，但没有持久回执；首答称下次可用，下一会话两次搜索均为空。MEMORY_MISS／ACTION_GROUNDING_ERROR；没有释放包裹，也没有声称仓库已执行暂存 |
| d03 | PASS | 保存并检索项目摘要范围内的 ISO 日期格式 |
| d04 | FAIL | 解释电池优先、READY 放最后，却没有真正以 READY 结尾。TASK_COMPLETION_ERROR；未写长期记忆 |
| d05 | PASS | 保存并检索 Cedar 演示前十分钟无障碍评审及未来准备条件；未发送议程。正文 today 未锚定绝对时间，作为局限保留 |
| d06 | PASS | 保存设备清单范围和 2026-10-01 生效条件；后续正确区分此前磅、此后千克 |
| d07 | PASS | 回答 EVEN；没有持久化临时分支 |
| d08 | FAIL | 已保存 Juniper／East Desk／16:30／documents accepted 触发及待办，后续未搜索。MEMORY_MISUSE。没有预订；正文 scheduled 与明确 NOT booked/pending 并存，存在措辞歧义 |
| d09 | FAIL | 同区单时区、异区双时区和 Asia/Shanghai 已保存，后续未检索，遗漏同区分支与用户时区。MEMORY_MISUSE／TASK_COMPLETION_ERROR |
| d10 | PASS | 仅确认本次试用房间 F-28，没有长期保存 |
| d11 | FAIL | 保存下次 Atlas 规划在选择部署日前提醒 Nina 提供 load-test log，后续未搜索，给出泛化建议。MEMORY_MISUSE；未联系 Nina，单项目符号没有变成长效格式规则 |
| d12 | PASS | 字面小写 m0 和同型号连接器已保存、检索并使用；旧句柄结构项目 N/A |

8 个需要未来保留的案例中，首次 session 关闭时 **7/8 已存**，d02 漏存；7 个已存案例中后续 **4/7 检索并使用**，d08/d09/d11 跳过搜索。4 个任务局部／无需保留案例都未写 Store。没有额外 release、send-agenda、book-pickup 或联系 Nina 的业务动作。没有自然 update/delete，因此“修订时保留无关有效内容”未观察到，不能记作已证明通过。

## 最终 R2 MERIT：完整原 arc0

run 为 `v15-b0-merit-r2`，原始世界、空 namespace、同一最终源码。原定 5、执行 5、可评分 5、中断 0，共 7 条公开消息；所有 pre_satisfied 为 false。原 checker 给出 native **4/5**、dependent **1/2**。

| Episode | 原生结果 | 行为与 session 关闭后的记忆 |
| --- | --- | --- |
| 0 | PASS | ORD-197802 初次约定 2492 分，查询订单并发送确认，没有提前退款；Store 空 |
| 1 | PASS | 先将 ORD-197802 改为 1774 分，再接收 ORD-470977／503 分约定；均发送确认，没有退款；Store 仍空。回复中的“更新记录”没有对应长期写入 |
| 2，dependent | FAIL | ORD-197802 两次记忆搜索为空，订单查询只给出总额 18600 分；模型编造约定 5000 分，写入 Store 并实际 refund 5000，正确当前约定为 1774。第二条消息收到 ORD-470977／6595 分及暂勿处理，正确保存并发送确认，没有提前退款 |
| 3 | PASS | 独立订单 ORD-964912 查询后全额退款 16100 分；记忆维持上述两条 |
| 4，dependent | PASS | 搜索返回 ORD-470977／6595 分（score 0.8342485427856445）及另一订单的错误记录（0.8283893014540676），选对目标并实际 refund 6595；没有事后更新记忆 |

自然首次约定保留 **0/2**；1774 分修订也未保存。Episode 2 同时构成 MEMORY_MISS、无依据记忆写入、行动依据错误和与当前约定不一致的实际业务动作。成功 refund 回执只说明执行了 5000 分，不能证明这个金额有依据。Episode 4 的 native memory_had_fact／argument_value_match／memory_utilized 都为 true，但这不是记忆因果必要性的消融结论。

最终两条记录分别是无依据的 5000 分约定，以及已实际退款却仍含 `Do NOT process yet.` 的 6595 分记录。没有观察到同订单重复卡片，也没有 update/delete 修订机会；不能据此宣称修订不会丢失无关有效内容。B0 没有旧 CURRENT 字段，过时状态直接由正文与真实动作对照判断。

## 全部尝试与连续费用

账本 `artifacts/langmem-foundation/v15-budget.json` 共 **108 次生成，76737 charged generation tokens**，其中已知输入 **66871**＋输出 **4975**＝**71846**，另有 native HTTP 400 的 **4891 unknown 预留**；embedding **33 次／836 tokens**，unknown=0；Judge=0。unknown 不是已知实际消耗，也不能按零计。仅本节 vLLM/embedding 费用进入该账本，root/Sol/Luna 的开发代理费用没有可用计量，单列 unavailable。

| 阶段 | 生成请求 | 已知输入 | 已知输出 | unknown 预留 | embedding 请求／tokens | Provider 墙钟秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| native 预检 | 1 | 0* | 0* | 4891 | 0／0 | 0.035 |
| spike r2 含失败与恢复 | 5 | 2917 | 197 | 0 | 0／0 | 4.179 |
| spike r3 | 6 | 3287 | 308 | 0 | 2／25 | 3.280 |
| R1 诊断 | 34 | 17283 | 1525 | 0 | 13／356 | 14.102 |
| R1 部分 MERIT | 7 | 6035 | 442 | 0 | 0／0 | 3.817 |
| R2 最终诊断 | 34 | 17285 | 1519 | 0 | 13／356 | 14.007 |
| R2 最终 MERIT | 21 | 20064 | 984 | 0 | 5／99 | 9.485 |
| 合计 | 108 | 66871 | 4975 | 4891 | 33／836 | 48.907 |

*native 行的 0 仅表示没有可取得的已知 input/output，实际 usage 未返回。两次本地模板错误和边界拒绝未额外发送 HTTP，请求数不凭空加一。Provider 墙钟是各实际请求等待时间之和，包含 embedding，不是 GPU 计算时间。最终诊断进程总墙钟 17.946 秒、MERIT 13.170 秒；其中包括本地图、持久化及请求等待，不能与 Provider 数重复相加。更早开发阶段没有统一进程墙钟，不补估计。服务 prefix caching=false，没有可认领的缓存节约，也不据此推断整体 GPU 成本下降。

R1 使用映射 `a686aa61…`，诊断完成 12/12、语义 7/12；MERIT 原定 5 集，执行到第 3 集，前 2 集可评分并成功，第 3 集因有效 JSON 内 `manage_memory(action="search")` 参数非法而中断，剩余 2 集未运行，**无完整 arc 分数**。适配器当时抛异常而未给普通工具错误回执，属于 FOUNDATION_INTEGRATION_ERROR。随后在唯一通用参数边界修复，冻结为 R2，并从空状态完整重跑。R1 源码、结果及全部成本见[保留清单](../data/manifests/langmem-foundation-v15-r1-results.json)；没有拼接两轮轨迹。

更早的 system／tool-history 模板失败、xgrammar 属性顺序导致 null content、被 active boundary 拒绝的候选也保留。它们用于解释接入修复，不冒充冻结 B0 的自然语义成绩。v14 的独立账本仍封存为 80 次生成／317098 tokens／1540 embedding tokens，unknown=0、Judge=0，没有并入或清零。

## 范围、交接与回退

该结果只刻画单模型、固定上游双工具配方和已暴露开发样本；不是上游官方 LangMem 成绩，也不是 v14 与 B0 的 matched 对照。两者 Agent、提示和工具合同不同，不能从相同的 native 4/5 推断方法等价或成本收益。无需为此基线追到语义全通过。

v16 若获单独授权，应先在 B0 实际调用位置增加语义中性的 observation／revision／receipt 记录，以相同合法 calls 检验 Store、正文、schema、query/filter/limit/offset 与排序 parity。来源仅说明当时可见材料时应标 unknown，不能自动推断被采用或支持正文。M1 的 state delta 必须验证能与业务动作置于同一次生成；v15 未实现这项机制。B1/M1/M2、未见 seeds 3/4、MemSyco 新选题及 StateMemBench 均未启动。

改动集中于 Lab 新增 adapter、runner、dataset adapter、三条 CLI、配置／锁／清单、窄测试和可选依赖 CI；根目录仅调整组合 CI。Product Schema/API/权限/Canonical 及 Archive 均未改变。回退基点为 `197b75ce9b6db0bebfb272955d625d741e34bd36`，旧 v14 交付为 `0802d34f49db45bd654fc745d33da3252c0d4e24`；撤回代码不删除隔离实验库及失败证据。发布使用用户授权的 Luna high，远端 commit 在交付消息中核对；本报告没有认领尚未取得的远端 CI 结果。
