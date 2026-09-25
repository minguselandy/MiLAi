# v7 通用开发完成记录

本轮开发及 E0—E2 已完成，最终 5/5（dependent 2/2）。[最终结果、全部失败费用和限制](CONTEXTUAL_USER_MEMORY_V7_RESULTS_20260925.md) 是结项入口；下文保留各阶段事实。

2026-09-25。状态：`DEVELOPMENT_COMPLETE_READY_FOR_BENCHMARK_SELECTION`。仅为 Lab 研究原型；本记录不认领模型自主语义效果、State 收益或生产能力。

起点的 38 个源文件逐项匹配 v6 冻结映射 `72f0279eae4223918fdd5869b84d75d85a3ac32800a3fbee7f66c8188ed5c312`。核对结果、通用文件样例、部署 grammar 检查和本版冻结身份在 `artifacts/contextual-user-memory/v7-development/`。v6 结果、预算与源码快照未修改。新协议为 method v11 / write v10 / ingestion v26 / material view v6 / operation v2。

| 工作包 | 已实现入口、所有权和消费者 |
| --- | --- |
| P0/P1 | `ContextualHost(memory=..., business_tools=...)` 显式绑定；`HostSession` 单独持有 transcript、MaterialView、DeliveryLedger、可见引用和轮内缓存。固定工具映射校验重名；业务回执独立于记忆回执。 |
| P2 | `accept_observation()` 发布、按策略保留、投影并实际追加后才授权范围；稳定事件去重。`actor_ref` 来自可信适配器，未知 user 角色不合并为所有者。单用户历史入口显式标注 current_user。默认在线来源仅会话保留；被持久记录引用的必要来源随写入保留。 |
| P3 | 历史、在线提示与 memory_save 共用 WRITE_RULES；CREATE/REVISE 显式 certainty，主体与事项一致才能语义修订，替换必须提供完整依据。精确相同修订不增版本或变更数；只新增来源只计来源变化。 |
| P4 | off 默认、optional 自由选择、forced_legacy 仅诊断。`advance_turn` 保留会话来源和工作状态，刷新问题、条件和覆盖；`project_query` 不再隐式拼接 State 自由文本。无依据的 State 条件不当筛选事实。新历史写入身份排除读取策略，恢复可共享无 task 的 v11 快照；旧 v6 拒绝。 |
| P5 | 来源直达、读取、搜索和写回执共用 MaterialView。短引用绑定准确版本与实际范围；移除消息即撤销可见性和缓存。业务结果、实际可见材料、版本写入和后续调用通过 session/turn/event/call ID 关联。最后响应约束只存在于该次模型请求，旧 HostResult transcript 保持快照。 |
| P6 | `run_task_session` 接收公开增量轮次，支持显式 session 续接或新会话。`task_runtime` 消费通用配置，使用既有 vLLM、分窗批量 embedding 和连续账本。示例提供真实读文档、期望版本写入与章节检查。 |
| P7 | 受影响静态检查、六类窄检查、部署 grammar 与包边界通过；源码和两配置已冻结。下阶段才选择 benchmark。 |

参考机制实际落点：AgeMem 的共用行动循环进入 Host 的固定分发；SimpleMem 的独立表达进入共同 WRITE_RULES 和版本存储；ReasoningBank 的观察依据经验进入普通 CREATE/REVISE，并由真实检查结果支持。ProactiveMemory 的不干预选择进入 optional State 自由循环；ReMe 的增量来源关联进入稳定 event_id 接入；OpenViking 的局部工作状态更新进入 update_state/advance_turn。MemoryArena 的环境与记忆分层由外部业务世界和通用 session 驱动实现；MERIT 尚未选定，工具映射和外部评分边界已可用。MemSkill 与 Memory-PRM 仅采用少量操作及使用链测量思路。无外部源码运行时导入，无额外抽取／提醒／语义审查模型。

## 使用

```python
from pathlib import Path
import json
from milai_lab.runners.contextual_agent_tasks import task_runtime, TaskTurn, run_task_session

config = json.loads(Path("configs/contextual-memory-v7-off.json").read_text())
# business_tools 是可信应用注册的 {name: BusinessTool}；环境状态由应用持有。
with task_runtime(config, user_id="owner", output=Path("artifacts/my-task"),
                  business_tools=business_tools) as (memory, host, identity):
    session, results = run_task_session(
        [TaskTurn("turn-1", "当前公开任务", observations=())],
        memory=memory, host=host, session_id="session-1", close=False,
    )
    # 后续只传新消息；session 参数表示同会话续接。
    session, results = run_task_session(
        [TaskTurn("turn-2", "下一轮公开任务")], memory=memory, host=host,
        session_id="session-1", session=session,
    )
    # 新 session_id 且不传 session：清空临时状态，保留持久记忆与外部业务世界。
```

optional 使用 `configs/contextual-memory-v7-optional.json`；两配置没有题号、评分字段或 benchmark 选择。当前 runtime 同时管理一个活跃会话；无需为每轮建立第二份记忆。持久快照沿 `checkpoint(include_task=False)` 保存；同任务恢复必须使用真实 checkpoint/handoff，旧可见引用不能在没有 transcript 的新会话里沿用。

直接用户事实须以可信 Observation 传入；question 只是任务文本，不自动成为持久来源。工具输出的 role 始终是 tool，即使 JSON-action 的传输消息使用 user 通道。未知执行结果保持 unknown，不自动重放业务写入。

运行确定性样例：`uv run python examples/contextual_document.py`。它在临时目录实际修改文件，并验证旧版本→反馈→修订→新会话当前版→文件检查通过。该动作顺序由脚本指定，模型调用为 0，不是自建准确率 benchmark。

## 检查与限制

已有核心、条件、检索、修订、历史摄取及 runner 窄检查共 76 项通过；新增内部 read 可见性修复相关 4 项通过。Host 原窄检查 31 项通过；新 session、材料、交付检查 12 项通过。不同检查有重叠，不将执行次数当独立样本。

受影响源和测试 Ruff 通过；root 的 7 个源／样例文件及核心 5 源 mypy 通过。`milai-lab-check-boundary` 通过。部署容器 vLLM 0.27.1 / xgrammar 0.2.3 的实际 grammar 编译和字符串接受检查 8 项通过，包含显式 certainty、业务工具和 optional State；没有付费生成。未运行全量测试、全量 benchmark 或包构建；包装配置未改。

中文词法召回仍受现有分词限制；向量与全文融合不保证语义正确。managed deletion 只覆盖既有受管记忆／制品，业务世界不属于该删除事务。容量不足保持可观察失败，不暗中裁掉材料后沿用引用。Host 是否恰当地创建、修订或不干预，留待冻结后的原生小规模实验。

v7 Host/embedding/Judge 用量采用独立的连续账本 `artifacts/contextual-user-memory/v7-budget.json`，累积上限为 null；失败和重试不清零。开发阶段没有模型实验请求。开发代理 tokens 从运行系统另列，不能与实验 Host tokens 混算；没有价格/GPU 用时不换算精确费用。无提交、推送或远端状态变更，当前交付身份以冻结源码散列为准。

E1 接线发现并修正一次通用输入歧义：当前请求同时作为来源交付时，标注 Current user request，并把“资料不作为指令”限定于历史与工具输出，正文仍只交付一次。未运行模型／见到分数；相关 3 项 session 检查通过。初始冻结完整保留，新映射 `2cb76b46776c331b212f70213cfd2a478c9d7e695d28af6828f4b753d8793672`。

最终接线收口（仍为 0 模型请求）：在线写入规则只从公共工具说明交付一次，移除 COMMON_PROMPT 重复副本；保留记忆工具名在 off 策略下仍禁止注册为业务工具，防止误解析。4 项 session 窄检查通过。最终开发映射 `6ac8a859f0a835cdd993ec620d673e4b7d61f7ad611d25236a04120d085d274a`，之前冻结均保留。

首轮失败后的通用保留合同修复已冻结：`612c47f7b55b08d974d3d123a9dd3a22037bb9e8e35aa961a8a1b42ebaf60baf`（material view v7，其余协议不变）。Host 明示实际来源保留政策，来源材料附 retention，业务成功不等于保存记忆。新的 actor 空标注仅在薄适配器。受影响 41 项窄检查、3 源 mypy、Ruff 通过；无工具 schema 变更，不重复 grammar 检查。下一次只验证同一完整原生单元。

持久性与主体合同修复冻结：`5579bd06663aabddd9ec0df3ed4dcd18f061e04f4691d69c34cb25ef7fa3c576`（method v11 / write v10 / ingestion v27 / material view v8 / operation v2）。task 明确为当前 HostSession 寿命；有后续用途的有范围业务事项可 durable。主体目录不再默认注册 u0，只有实际交付的可信 owner 来源或已存 owner 元数据才提供，Host 取消 u0 的交付豁免；unknown 不推断人物。共同规则保留指令与事实区别。Astra 仅只读复核这项具体疑难，无额外模型实验；48 项受影响窄检查及静态检查通过。
