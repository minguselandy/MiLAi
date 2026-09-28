# v3 P1：普通记忆结果闭环实现与准入检查

P1 实现和必要局部检查已完成；P2 真实运行仍为 `NOT_RUN`。这是工程准入证据，不是记忆形成效果。
[检查清单](../data/manifests/next-development-v3-p1-checks-20260928.json)绑定实际代码、命令、日志和构建哈希。
用户确认的 [v3计划](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v3.0.md)及
[P0/P1协议](MILAI_NEXT_DEVELOPMENT_V3_P0_PROTOCOL_20260928.md)保持适用。

## 最终实现

新增纯 `methods/memory_result.py` 放置冻结责任文本、结果 schema 和机械回执核对。
`langmem_chat.py` 仅在显式 v3 配方中增加回执请求副本；C 允许终答携带 memory_result。
原方法默认 schema、工具和回答路径保留，普通 strict CRUD 未改。
B0/B1/C 都使用 `build_agent` 的同一个公开 v1 ReAct graph、普通 CREATE/UPDATE/DELETE/search/精确 READ，
以及既有应用业务工具；没有独立 State/A/U 或自动语义写入。

当前 owner/公开回合的原 AI 调用与真实 ToolMessage 配对，只有实际 successful created/updated/deleted
支持 committed；no_change、失败、未知和部分成功分列。程序不认证语义正确、全部保存或自由回答真实性。
错误 no_change 若无实际写入矛盾，可以机械接受但仍不满足用户持久要求，由冻结离线评分判定。

C 在 invalid/unresolved 后，至多通过公开 `update_state(..., as_node="tools")`/`invoke(None)` 进入一次纠正。
原终答使用同一 AI ID 附加内部标记，原回答和工具结果保留；反馈加入首 system 的请求副本。
不添加 HumanMessage、不重置公开消息 12 次容量；工具目录和执行包装均限制纠正只能读/维护记忆。
不可安全解析的工具提案沿原错误路径结束，不伪造最终答复或工具回执。

新 `persistent_memory.py`/CLI 复用现有 `run_phase`、Store/checkpoint、SQLite 业务世界和副作用日志。
Archive 模式共享实际 visited owner 历史；Retained 模式不创建历史入口，只交付当前会话和实际 ordinary memory。
后续 phase 可重新打开进程资源；相同已尝试的 phase 不可冒充新运行重试。历史/原生 runner 的旧 validator 未放宽。
实际 checkpoint 观察读、C 标记写、普通记录读取、工具执行和 provider 费用分别保留，不用进程正常退出代表语义验收。

## 已通过的必要检查

新增 15 个独立工程情境通过，其中 5 个纯合同情境也在干净 core 环境通过；相邻 foundation/application/shared-use
39 项通过，均 0 skip。这些数字是工程检查，不是模型样本，重复环境验证不重复计为新增情境。

| P1 边界 | 实际检查 |
| --- | --- |
| 无提交/外 owner 回执却 committed | 纯核对拒绝；同 graph 从空引用进入一次真实工具续接 |
| 已有等价记录 | 实际 InMemoryStore 精确 READ 后 no_change，无额外 CREATE，无其他 owner 正文 |
| 业务已发生、维护失败 | SQLite 真实 reservation 部分成功；同批 strict UPDATE 不存在目标实际拒绝；纠正中的重复业务提案不执行 |
| 多操作部分成功 | 实际 CREATE 和失败 UPDATE 都保留，只认证被支持操作，semantic_completion 始终 unknown |
| no_change | 无写入时不自动纠正或判语义成功；有实际写入时记录矛盾 |
| 未知业务副作用 | 真实本地动作后模拟超时，保留未知，无伪造回执/自动重放 |
| 非法终答和容量 | 一次纠正后仍无效如实保留；容量不足不加调用；当前 Human 数不变 |
| 信息权限/入口 | Archive/Retained 实际 HTTP 副本差异、owner 隔离；prepare→phase→新会话重新打开及重复 phase 拒绝 |

锁定 Qwen tokenizer 对三份实际 MockHTTP 请求执行 `apply_chat_template`：真实 receipt_ref/name 出现在工具内容，
原 ToolMessage JSON 不变；只有一个当前 Human，system 在首位，责任正文与 P0 fenced 文本相同。
这是实际模板的本地序列化检查，没有调用推理服务。

受影响 Ruff/Mypy、core/foundation 检查矩阵、包/工具边界及空白检查通过。
B0/B1/C 各一份代表性 CLI prepare，另对全部六个正式输入做结构校验：每臂 15 条消息，目录一致，
B1/C 责任正文一致，只有 C 的结果 schema 不同。P1 装配目录与正式 P2 运行目录隔离。
新入口只进行一次 offline wheel＋sdist 构建，包中变更源码字节与工作树一致，私密资产未打包。
文档/结果发布不再重复测试或构建。

保留检查期间的测试 import 位置错误、JSON 转义断言修正及自建 StrictUndefined 模板 harness 不兼容记录；
最后使用实际 tokenizer API 验证。中间 Ruff/Mypy 的格式/类型修正日志也保留，不能把首次尝试全部称为通过。
这些是开发检查，不增加真实实验 generation/embedding 费用。

## 真实运行准入与局限

工程检查未证明 Host 会形成正确记录、正确判断 no_change、更新全部必要内容或正确消费记录。
下一步先由 Luna 发布实现，Root 按 [P2协议](MILAI_NEXT_DEVELOPMENT_V3_P2_FORMATION_20260928.md)
创建并冻结 18 个正式身份，核对已发布的 157 个 runtime 源码/入口身份及账本，再串行执行。
本阶段真实 generation/embedding/Postgres 调用为 0，权威账本 SHA 仍
`e3f5bf8ad50f7825ad010692164238c9dc14e10c113a39d2f0de383b7e3dce83`。
任意崩溃下的跨库原子性、exactly-once、物理遗忘和产品可用性均未由这些检查建立。
