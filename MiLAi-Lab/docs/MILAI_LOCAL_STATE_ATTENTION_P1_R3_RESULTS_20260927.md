# LSA P1 R3：来源身份合同未解决读取与状态污染

源码 `70bb5c59cd86455903d0425c9e3f67ff26cb84b1`，
[冻结协议](../data/manifests/local-state-attention-p1-r3-protocol.json)，
[精简结果与证据哈希](../data/manifests/local-state-attention-p1-r3-results.json)。
三个 run、六个独立 phase 进程均已结束；所有失败及容量后跳过消息保留在分母。
原两条 development 轨迹严格 **5/12**、完整业务 **0/2**；新增用户报告控制 **1/2**、
完整轨迹 **0/1**。P1 尚未通过，不启动广泛 benchmark 或规模扫描。

## 实际链与首个断点

| 轨迹 | 严格任务 | 实际结果 |
| --- | ---: | --- |
| 三事项交错 | 3/6 | 首阶段三消息正确；新会话 focus 为空，不能恢复已存事实；组合行动陷入空 memory search，达到原有每消息 12 次 Host 上限，末消息按规则跳过；实际业务调用 0 |
| 部分失败后恢复 | 2/6 | 两个计划确认正确；Mira 预留的对象 key 被单数化，部分成功 ID 留存；恢复时以另一描述作 get key，未执行 complete_label；Noel 数量/地点/包装错误；已存 D-2/10:15 未交付 |
| 用户报告过去事件 | 1/2 | 首次正确形成用户本人交付 Juniper notes 的陈述；新会话两次 focus 为空，Host 搜索后回答无记录；未发生业务调用 |

交错轨迹创建了三张实际 State，后台 B 修订也成功写入，但维护 focus 选择 B，前台回答
仍依赖原历史。新 session 中，正确 B 已在 Store，控制器却选择空集合；这是恢复任务的
首个断点。组合行动在工具执行前被写成“已尝试、待观察”，之后真实的空 memory search
又成为业务结果描述。部分更新使用 `new:N` 指向更新编辑而非新建编辑，归一化后为空；
没有 degraded 标记不能证明选择有效。最终两张业务卡 revision 为 12/13，仍无预留。

Mira 实际创建 key 为 `Summit Archive Crate`，数量 5、标签尚未创建；真实 ID 保留。
恢复 get 却查 `mezzanine M-4 foam inserts crate`，not-found 被控制器扩大成不存在预留，
从而放弃实际可恢复对象。Noel 创建数量 1、`Archive Storage Facility` 与
`Climate-controlled crate`，与本 owner 原计划不符。各 owner namespace 隔离，不能把
失败归为跨用户串读。全部六张末态均有程序机械依赖；这不是执行过授权删除的证明。

## 竞争解释与决定

H1：联合维护/选择不能可靠区分 U 与 A，导致正确持久信息未交付。用户报告控制的
正确 State 加空 focus 是直接证据；全量读取可最小区分这一解释。

H2：维护器仍将任务要求和非业务工具结果当成行动状态；即使全部读取，污染内容仍可能
导致错动作。来源身份合同不能单独解决此问题，不能把合法 evidence_refs 当作事实支持。

H3：Host 另有对象键和参数理解问题。R2/P2 已有正确计划仍改名，以及用内部 State ID
调用另一 namespace 的 memory 工具的证据；不能将所有错误都算到 attention。

**停止该控制合同的措辞微调；继续最小读取对照。** R4 保持控制器、调用频率和脚本
不变，比较 `local_all` 与 `local_state`。前者全量交付实际 bank，仍执行同一个联合
控制器，因此不是“去掉全部 attention 计算”或“仅维护”臂。两臂共同从临时 Host
视图移除内部 State ID/revision，保留 title/content/needs/evidence_refs；控制输入、
Store、trace 和原 checkpoint 保留原值。不能把 R3→R4 的差异单独解释为读取策略收益。

最小下一实验为同三脚本×两臂×一次完整运行；原 24 消息与新增 4 消息分别计分。
固定轮转臂序，全部新 namespace/world/checkpoint，源码全批冻结。若全量也失败，
按具体第一断点决定简化表示或分开维护/读取，不继续无限增加合同文字。完整历史、
更强普通笔记与 G/L/LRU 尚未比较；当前失败不构成这些方法无效的结论。

## 成本与测量边界

| 角色 | 实际 HTTP | tokens | HTTP wall seconds |
| --- | ---: | ---: | ---: |
| state_control | 31 | 46696 | 50.466 |
| task_host | 30 | 37611 | 12.782 |
| embedding | 15 | 181 | 0.505 |

合计新增 **61 generation / 84307 generation tokens / 181 embedding tokens**；
unknown usage 为 0。Host 容量在客户端阻止下一调用，无额外服务拒绝请求。
连续账本 **983 generation calls / 1184433 generation tokens / 10575 embedding tokens**。
LSA 启动以来含全部失败共 120 generation / 141704 generation tokens / 958 embedding tokens。
旧 SER exact-version reads 107 与此处 BaseStore 操作是不同指标。

三个 run 的实际 BaseStore get 合计 512、search 310、put 127；失败均 0、delete 未执行。
这是 wrapper 调用数，不能等同 SQL roundtrips。逻辑值存储为 State 6489 字节、原始事件
11746 字节、meta 375 字节，不含 key、Postgres 行/索引/WAL、checkpoint 与原始 trace。
各操作 CPU/wall 与输入/结果逻辑字节见精简结果，不能将此前未测的 R2 记为 0。
所有 run 为 0 pending/0 degraded，实际仍大量失败；这两个计数仅描述程序状态。

## 复现与保留

ignored 原证据位于 `artifacts/local-state-attention/p1-r3/`：运行前后账本、配置、
execution-freeze、run_plan、逐 phase 结果和 Store 快照、真实 trace、world/journal、
checkpoint、offline-review。六 phase 均为独立进程，没有替换失败、盲重试或轨迹拼接。
实际运行入口及共参沿 R3 协议，prepare 绑定本页源码 SHA；每个 run 依次执行 phase 0/1。
独立复现须使用新 run/root 和原始输入字节，并加载对应历史提交，不能覆盖旧运行。

13 项源码窄测、目标静态检查、三个零模型 prepare 和一次构建在运行前通过；未为发布
重复测试。机械删除路径仅经过离线检查，真实授权删除链仍待后续独立证据。
P2–P7 与完整 Goal 仍未完成，Product 仍 NO-GO。
