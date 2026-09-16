---
document_id: MILA-HOST-WORKSPACE-A-LABELS
date: "2026-09-13"
status: OFFLINE_DEVELOPMENT_ANNOTATION_COMPLETE
run: a-common-v2-20260913
task_version: workspace-task-a-v2
reviewer: user_delegated_development_subagent
independent_human_gold: false
new_experimental_model_requests: 0
---

# A 真实三臂：离线语义标注

本次直接阅读三臂全部 `rows.json`、`terminal.json`，任务 visible 材料及 offline source-map，并按映射回读三个长尾请求的 runtime/MCP 原行。由用户委托的开发 subagent 标注，不是独立 human gold；没有另设 LLM Judge 或调用实验模型。下述 row 索引从 0 开始，不用关键词计分或平均准确率替代语义判断。

运行根为 `/cra/memory/mx_memory/evidence/workspace-host/a-common-v2-20260913`，任务根为 `/cra/memory/mx_memory/evidence/workspace-host/task-a-v2`。NOTE、REVIEW、REGULATED 分别完成 3、3、4 次决策和最终交付；`COMPLETE` 只是交付状态，三臂均有语义问题。

## 核对依据

| 请求与原始定位 | 可支持的判断 |
| --- | --- |
| R12：`offline/source-map-1.json[1]`；原 `api.log:1122`、`mixed-mcp.log:344`、MCP events `/109`；关联材料 `/94` | client 173.055795 ms，application 166.601 ms，transaction exit 164.426 ms，acquire 0.035 ms。大部分可定位于事务上下文退出的已计时区间；不是已经知道 fsync、网络、锁或某段内部代码耗时。GC **未观测** |
| R22：`offline/source-map-2.json[1]`；原 `api.log:1104`、`mixed-mcp.log:290`、MCP events `/91`；关联材料 `/76` | client 319.974640 ms，application 312.494 ms，transaction exit 309.995 ms，acquire 0.017 ms。客户端已覆盖 GC overlap 为 0.300919 ms，无法解释此客户端窗口的全部长尾；不等于其他进程 GC 被排除，更不能补成 R12 的观测 |
| R32：`offline/source-map-3.json[1]`；原 `api.log:1053`、`mixed-mcp.log:137`、MCP events `/40`；关联材料 `/25` | client 51.367854 ms，handler 7.012 ms，application 4.574 ms，transaction exit 1.319 ms。共享时钟已核验，MCP client start 到 handler start 为 **42.393870 ms**，handler 后为 1.962101 ms；这是 handler 外的前区间，不是 handler 内的 preprocessing，也不能直接命名网络或 scheduler 根因 |

原文件完整路径保存在相应 source-map。`summarize_v02_request_timing.py:handler_edges` 的计算起点是 `mcp_event.start_s`，并非 `arrival.dispatch_s`。`connection_outside_transaction_edges_ms = hold − enter − exit` 只是扣除上下文进入/退出计时后的剩余，可能包含事务体；不能把它叫“事务之外”或“exit 到 release”的专属计时。

## 逐臂判断

| 臂 / 轨迹 | 正向进展 | 范围错误与未决项 | 下一检查价值 |
| --- | --- | --- | --- |
| NOTE，rows 0–2，final=row 2 | 前两段正确抓住 R12/R22 164.4/310 ms 的事务退出主区间；最终区分前两批与 R32 的不同长尾位置，未用新批次覆盖旧定位。`>98% application` 的比例方向成立 | final 把 B1/B2 合称 `not GC (overlap negligible)`，抹去 B1 未观测。把 R32 定位为 `handler_preprocessing/postprocessing`、handler 的 before phase，越过实际 handler 起点；`ruling out MCP layer overhead` 也比两个内部计时相近支持的范围更宽。DB/网络/锁的 `suggests` 表述作为候选假设，不单独记已确认事实，但“two distinct mechanisms”应降为两个观测位置 | 提议对齐同请求 DB commit latency/lock waits，对前两批有具体价值；低锁等待加高 commit 时间不能唯一证明网络，还可能有其他服务端/驱动耗时。MCP queue depth 可检验一个候选，但不能覆盖完整 client-start→handler-start 链。最终优先 DB 的选择有绝对尾时依据 |
| REVIEW，rows 0–2，final=row 2 | 识别 R12/R22 高 hold 与小 acquire；最终正确读出 R32 约 42.4 ms 的 handler 前差值，并承认 DB hold 可能另有原因 | rows 0/1 把仅 1.56/1.79 ms 残差作为主解释并误称事务外，遗漏已给出的巨大 exit 计时；反复要求查已给出且很低的 acquire。final 虽把小残差改称 minor，却把全部长尾归因于 MCP scheduler，并猜旧两批被同原因遮蔽；这是新批次覆盖旧定位的实质错误。B1/B2 无 handler 起止和时钟绑定，不能把 R11/R21 的 `<5ms` handler 外总差值称已测的 before gap。最终没有把 B1 GC 填零，但也未明确保留该覆盖缺口 | 增加带时钟绑定的 handler-start 与 client/dispatch 时标，有定位价值；“起点差值方差高就说明 scheduler”因果辨识不足。尚需客户端发送、服务端接收/入队/出队区间才可区分排队、传输、调度等候选 |
| REGULATED，rows 0–3，final=row 3 | row 1 明确保留 GC NOT_OBSERVED 和时钟缺口；row 2 以后抓住事务退出主区间，final 保留两类定位且明确 R32 时钟绑定。候选原因多数用 `could`/`unknown`，不作为已采信根因计错 | row 1 起首把残差误称 exit 到 release，后又正确指出 exit 巨大，形成内部不一致；后续没有明确解释撤回。row 2 将 R12/R22 一并称 unexplained by GC，final 更合并为 `GC negligible (0–0.3ms)`，丢失先前正确的 B1 缺口。final 用 `confirming ... internal to commit/rollback logic` 超过上下文退出计时本身所能证明的粒度，虽紧接着又承认根因未知 | 对高尾请求做 driver commit/rollback 边界 trace 是可推进的小检查；但长 RPC 同时可能含网络和服务端等待，不能据“返回慢”唯一判网络；若调用返回快而外层 exit 长，则应查调用边界外的清理/调度，不能直接归为 DB server contention。MCP queue trace 是合理备选假设检验 |

三臂都没有宣称已经执行所建议的新检查，也没有提议牺牲审计、持久化或负载约束。没有把 transaction exit 直接命名为 fsync。上述保留项不抵消各自的范围错误。

## 工作记录、重复与解释限制

全部 10 个 row 的 raw response 都未带 `work_update`；`work_update_status=UNCHANGED`，workspace 始终为空、revision 0。这是模型自主未写记录，不是容量拒绝或日志缺失。三臂都通过共同材料与正常动作历史续接；当前差异来自整段政策提示及自由动作历史，不能归因于已形成/消费的短工作记录，更不支持持久 Memory 的收益或失败。

REGULATED row 0 在 E1 已随共同上下文展开时又执行 `read E1`。返回是真实相同材料，该次没有新材料或修改条件，是一项**可疑重复**，多用一次正常请求；不能单凭它断言整个复读无认知价值。NOTE/REVIEW 各 3 次、REGULATED 4 次。按各 row 的 settled usage，原始输入加输出 tokens 分别为 13,532、13,588、17,089；完整 HTTP 预检、工具和开发成本仍以主执行者总账为准。

本标注没有第二裁定者，因而没有已裁决的一致性分数。NOTE/REGULATED 的“机制/内部逻辑”可被宽松读作初步假设，与其附近明确 unknown 语句有张力；这里记录为措辞与粒度问题，不把所有合理假设算事实错误。两者合并 B1 GC、REVIEW 跨批覆盖，以及残差定义误读有直接证据，不依赖这种宽严选择。不得据此单个 root 宣称稳定臂排名。

## 当前决定建议

**保留简单 NOTE 作为当前 opt-in 开发入口，暂停把 REGULATED 当必要机制或默认优胜方案。** 本组 NOTE 与 REGULATED 都保留两类大体正确的定位，REGULATED 仍丢失已知覆盖缺口并多一次已呈现材料复读，未展示工作记录形成/消费的净增量；REVIEW 此次更差也不等于普通复核普遍无效。先保持当前代码与失败轨迹可回放，不增加记录模块或自动 Judge。

若主执行者依据 Goal 继续一次小迭代，可检验“持续正文与现有历史已满足续接，导致工作记录未启用”这一具体解释，使用三臂共同的受控上下文变化并另存版本；不能强制写理想记录后仍称自主形成，不能把本次直接算作该解释已证实。
