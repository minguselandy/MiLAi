---
version: v19.0
date: 2026-09-26
status: STOPPED_STRUCTURED_RECONSTRUCTION_NOT_JUSTIFIED
engineering_delivery: COMPLETE
experiment_arm_kind: RESEARCH_PROTOTYPE
---

# v19 结果：协议可运行，重建机制未成立

v19 的全部工程实现、必要离线验证、五分支 decoder probe 和三个预冻结实例已完成。原 vLLM 设置始终未改。正式运行完成 9/9 条公开消息，但 15 次响应全部输出 `reconstruction=null`；changed 在明确看到版本过期提醒后仍实际记录旧值 4°C。完整 ODR 链为 0/3，不能声称方法有效。

终态为 `STOPPED_STRUCTURED_RECONSTRUCTION_NOT_JUSTIFIED`。按[原计划 §38、§44](MILA_ON_DEMAND_RECONSTRUCTION_V19_DEVELOPMENT_PLAN_20260926.md)，停止继续扩展 structured ODR。Freshness-only 已实现，但 V5 条件未满足，效果仍未知；V6 原 12/20、V7 arc0 均为 `NOT_RUN_GATE_NOT_MET`。没有运行新 seed、holdout、M2、Attention 或额外语义补救轮。

## 实现与验证

新方法位于 `methods/on_demand_reconstruction`，通过既有 JSON-action adapter 和 LangGraph ReAct loop 接入。三个显式臂为 `b1_control`、`freshness_only`、`odr`。

- Freshness 只检查当前实际 request 中的准确 memory material。历史版本可为 CURRENT、SUPERSEDED、DELETED、UNKNOWN；只有实际 stale/deleted 材料产生动态提示，不注入新正文或要求搜索。
- ODR 在同一生成中附加可为 null 的临时重建。非 null 使用当前实际交付的 Observation、精确 MemoryRevision 或业务 receipt；stale supports_value 被拒绝，同响应工具不执行。null 业务照常允许并单列统计。
- 分析 JSONL 不作为下一请求输入，不保存 Decision State，不在 AIMessage metadata/checkpoint 中恢复重建。正常对话和工具历史保留；每次请求重新计算机械 freshness。
- F-only 无 ODR schema、协议或 evidence-handle 目录；无 stale 时实际 wire 与 B1 相同。

V0 五条集中测试通过，覆盖上述 freshness/currentness、真实 imported-search UNKNOWN、精确交付、restart/日志独立、completed replay、null 业务和非法零业务副作用。ruff、15 文件 mypy、两项边界检查及一次 wheel/sdist build 与内容检查通过。受影响旧测试为 17 通过、1 个既存 M1 断言不匹配：旧测试期待 `DecisionDeltaError`，HEAD 的旧 schema 已先排除该 task_ended+calls 组合，旧 adapter 会先抛 `IncompleteChatResponse`。该问题完整记录于[验证清单](../data/manifests/milai-odr-v19-verification.json)，未修改封存 M1 方法，也不将该组报告为全绿。

五个真实 decoder 分支全部通过：null+answer、null+calls、reconstruction+answer/search/business；探针不执行工具、不提交重建。它们证明指定非 null 结构能够生成，不能证明模型在普通任务中会自行启用重建。

## 三个实例的独立结论

| 实例 | 初始真实取证 | 更新后的行为 | 获批实际动作 | 结论 |
| --- | --- | --- | --- | --- |
| changed | 通过 search 取得 X@1=4 | X@2=8 真实写入；3 个 request 收到 stale 提示；未读取 X@2 | 4°C，错误 | FAIL：旧证据继续支撑实际动作 |
| retained | 取得 X@1=8、note A | X@2=8、note B 真实写入；未读取 X@2，pending 答复仍复述 note A | 8°C，数值正确 | FAIL：不能以同值动作代替当前版本验证 |
| irrelevant | search 同时返回 X=8 与 Y@1=09:00 | Y 更新为 09:30；3 次提示只指 Y，X 保持 current；没有追加搜索 | 8°C，正确 | 非干扰行为 PASS；预冻结的结构重建条件未观察到 |

三个实例都只在第三条公开消息获批后调用一次业务工具，无提前执行。每例 5 次普通生成、1 次 Host search、1 次 search 后续生成、1 次业务后续生成。外部更新通过真实上游 manage-memory 工具完成，没有伪造搜索或预置模型判断。

Changed 的第 2 条公开消息和第 3 条消息的业务请求都实际携带 `X@1 is superseded by X@2` 及“当前正文不在请求中”的提示。模型随后记录 4°C。第 3 个带提示 request 是业务后的确认，因此不能表述成执行前已看过三次提醒。

Irrelevant 中 Y 的旧正文确实由初次 search 进入了历史，所以提示 Y 合法；这不是“无关内容不在 request 却被注入”。X 未被标 stale，也没有无必要查 Y。其非干扰结果值得保留，但 all-null 无法证明温度 reconstruction 的选择性或稳定性。预先冻结 rubric 对最终重建的要求没有事后删除，因此完整结构链仍记 0/3；即使仅把 V4 行为控制记为通过，V2、V3 的失败也足以关闭后续 gate。

## 指标及解释

| 指标 | 结果 | 解释 |
| --- | --- | --- |
| 非 null 重建 / 正式请求 | 0/15 | emitted=accepted=0，rejected=0；未发生自主重建 |
| 动态 freshness / 正式请求 | 9/15 | 全部针对实际旧 material；其余 6 个请求动态 freshness 为零 |
| current exact evidence 使用率 | 0/0，未定义 | 没有 action-sensitive reconstruction 可评分 |
| supports_value 声明覆盖与正文支持 | 0/0，未定义 | 不可写成 100% grounding |
| stale supports_value 尝试 / 拒绝 / 接受 | 0 / 0 / 0 | 全 null，不能说明业务已摆脱旧证据 |
| 实际 stale 业务动作 | 1 | changed 真实记录 4°C |
| ACTION_WITHOUT_RECONSTRUCTION | 3 | 合同允许；不是协议漏洞或强制重建 gate |
| reconstruction 质量抽样 | 0 条 | 无标签式对象，也没有可评估命题；质量未知 |
| unresolved discipline | 未成立 | 当前正文缺失时没有 gap，仍沿用旧值 |
| protocol rejection / truncation | 0 / 0 | 工程运输有效，语义行为未达标 |
| 独立重建 / reviewer / Judge 调用 | 0 / 0 / 0 | search 的普通后续生成另行计入成本 |

普通非干预题 d01/d04/d07/d10 属条件 V6，本轮未运行，不能以 all-null 代替它们的评分。所有实际 request 与 B1 sidecar 的交付记录已核对，逐请求证据见[机制结果](../data/manifests/milai-odr-v19-mechanism-results.json)。

## 成本

| 阶段 | 生成次数 | input tokens | output tokens | 总 tokens | embedding 次数 / tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| 五分支 probe | 5 | 3,169 | 369 | 3,538 | 0 / 0 |
| changed | 5 | 5,054 | 188 | 5,242 | 3 / 86 |
| retained | 5 | 5,180 | 220 | 5,400 | 3 / 105 |
| irrelevant | 5 | 5,992 | 188 | 6,180 | 4 / 83 |
| **合计** | **20** | **19,395** | **965** | **20,360** | **10 / 274** |

正式三例共 16,822 tokens，1,869.11 tokens/公开消息、1.667 generations/公开消息。独立额外生成 0，但 3 次 search 后续生成和 3 次业务后续生成均已计费。unknown usage=0，Judge=0，截断=0。连续账本引用完整 v18 和更早历史，未清零或丢弃成本；开发代理的平台费用与本地实验 Provider 用量分开，未假定为零。

精确片段用原本地 tokenizer 计数：固定 ODR_PROTOCOL 每请求 111 tokens，正式总计 1,665；动态 freshness 840；evidence-handle 目录 1,225；输出 reconstruction 字段 75（全部 null，含字段名）。目录计数排除了 freshness 和原 B1 system prompt。这些片段已经包含在总账中，BPE 边界使它们不能直接相加当作严格 matched 增量费用。

正式本地存储为 Provider trace 627,720 bytes、分析 reconstruction JSONL 8,527、B1 factual sidecar 270,336、普通 checkpoint 237,568。持久 semantic State 为 **0 bytes**；分析日志和对话 checkpoint 并未被冒充为零存储。共享 PostgreSQL factual Store 未包含在这些本地文件总量中。

与 maintained M1 的比较仅为描述性历史：

| 正式运行范围 | generations / 已尝试公开消息 | tokens / 已尝试公开消息 | 拒绝 / 截断 | Decision DB 文件 bytes |
| --- | ---: | ---: | ---: | ---: |
| v17 R2 changed（3/3 完成） | 5/3 = 1.667 | 6,185/3 = 2,061.67 | 0 / 0 | 36,864 |
| v18 R2 三例（各 1/3 完成，共尝试 6 条） | 6/6 = 1.000 | 9,896/6 = 1,649.33 | 2 / 1 | 135,168 |
| v19 三例（9/9 完成） | 15/9 = 1.667 | 16,822/9 = 1,869.11 | 0 / 0 | 0 |

旧版本的覆盖范围、表达合同和中断位置不同，v18 少跑后续动作不能算成本收益；v19 all-null 也不能被描述为以较低代价完成了有效重建。旧 v16 7/12、v17 5/12 不是本轮 matched 因果对照。详细账本见[费用清单](../data/manifests/milai-odr-v19-cost-summary.json)。

## 反思与决策

此次已区分三个层次：decoder 能输出结构；adapter 能准确投影 stale 事实并保持无跨轮重建；Host 是否据此重新取证和判断。前两层成立，第三层在 changed/retained 没有成立。初始取证已经改善到三例都实际 search，但更新后的重新取证为零。

失败没有证据指向 vLLM 参数或版本标识错误，也没有协议错误需要重试。重建可为 null 是预定合同，不能在看到结果后强制非 null、插入自动 search 或拦截旧温度来宣称 ODR 成功。§44.3 的**行为级旧证据支持动作**已经出现；形式上的 stale supports_value 声明为零，两个事实必须同时保留。

本轮停止 structured ODR，不声称 Freshness-only 已足够，也不声称已证明必须自动 retrieval。后续研究若重开，可分别考察 freshness 的表达/位置与 retrieval control 的贡献；它们需要新的明确假设与冻结对照，不能回填本轮结果。

## 身份与交付

参考 commit：`90ac0b35e95b0371106cb05fb66b1f933af7f432`。最终 52 文件 source mapping：`1f22b6b7b032a647e360c140c61467763f7ce71b0a1fdd481d1c00ede88fbfaa`；[v19 lock](../data/locks/milai-odr-v19.lock.json) SHA `b595101190d36f25f4b3a49456392eda547e650d7b0bf0f7bf1e456af9f2c77e`；[最终冻结](../data/manifests/milai-odr-v19-final-freeze.json) SHA `aaf62b59475c8e8170a72cfa4af5c8c89a1cbeb7a8d6e5029ff2b06ae9ba4d63`。

原计划字节、封存 M1 方法、16 项旧锁/结果/失败/账本均保持。前后原 vLLM container/image/command/environment/HostConfig 一致，Host temperature=0、thinking=false、65536 上下文、4096 输出和每公开消息 12 次尝试设置未改。全部真实调用由 Root 串行执行，原始 trace/DB/凭据继续 ignored。完整范围状态见[Goal](MILA_ON_DEMAND_RECONSTRUCTION_GOAL_v19.md)、[最终结果清单](../data/manifests/milai-odr-v19-results.json)和[复现入口](MILA_ON_DEMAND_RECONSTRUCTION_V19_REPRODUCTION_20260926.md)。
