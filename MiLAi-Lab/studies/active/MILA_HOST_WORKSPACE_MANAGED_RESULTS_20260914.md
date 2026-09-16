---
document_id: MILA-HOST-WORKSPACE-MANAGED-FOLLOWUP
version: "1.0"
date: "2026-09-14"
status: DEVELOPMENT_COMPLETE_NO_STABLE_POLICY_SIGNAL
experiment_kind: RESEARCH_PROTOTYPE
model_generations: 51
known_raw_tokens: 234134
unknown_usage_requests: 0
independent_lineages: 1
---

# Managed 真实接线、两次比较与工程收口

本轮落实用户附件的 managed 后续执行要求：新观察直接呈现，旧正文确实可退出，所有臂保留同一合法读取入口；完成修正后的 managed 三臂，以及唯一一次同 NOTE 的上下文保留消融。**当前保留可选 managed 入口及简单 NOTE 参照，暂停 REGULATED 的必要性/优胜主张，不再追加模型试验。** 普通阶段回答有时能完成信息续接，有时会传递误读或遗漏；本轮没有模型写出工作记录，不支持短记录或特殊政策的稳定收益。

本轮开发交付与研究取舍已完成：完整清单4424项经分片覆盖核对，4423通过、1项可选依赖跳过、零失败/错误；工程异常及全部实验失败保留。这不等于证明机制创新、跨来源或持久记忆收益。原 Goal、上轮报告及失败证据均保持原样。

## 1. 实现及遇到问题后的修改

[任务入口](../../tools/run_workspace_task_a.py)现在支持 `--mode COMMON_CONTEXT|MANAGED_WORKSET`、`--recent-exchanges`、`--phase-opportunities`。沿用[两个 Host 钩子](../../tools/workspace_policy_host.py)、[核心](../../src/milai_lab/methods/workspace_policy.py)和[现有 Provider 适配器](../../tools/workspace_task_provider.py)，未增加 Provider、缓存、审批层、语义控制器或任意代码执行能力。

`Task.release` 把本批材料正文作为带来源依赖及 `body_refs` 的新消息组直接送入输入，所有政策相同。旧正文随近期完整交互退出，但 registry/中性句柄不删除，仍能 `read` 或在下一步选回。Host 逐行记录新正文、实际组装正文、未呈现正文；这些与披露依赖分开，不用 `included_dependency_refs` 冒充已呈现全文。

三臂先知道同一续接规则，本轮统一 K=1。上轮常见三步轨迹在 K=2 时会保留全部旧材料；K=1 使短轨迹也有实际退出机会。新观察不受旧焦点过滤，工作记录可为空，仍可保留条件、线索或重新读源。

实验开发中实际发生两项问题，并完成针对性修正；工程回归异常另列于第5节：

| 版本/观察 | 修改与资源安排 | 核对结果 |
| --- | --- | --- |
| v3：三臂末段都用 stage_answer，入口提前结束，虽有剩余机会却不能提交 final | v4 中末段 stage_answer 只返回 `FINAL_STILL_REQUIRED`，不结束任务；final 仍须由模型自主提交，不把阶段文字改标 final。更新共同任务语义及末段提示 | v3 12 次全部保留为无最终交付；v4 三臂均提交 final。新增测试验证末段阶段答复后仍能读源/最终交付 |
| 比较 2 首版 COMMON 在第五次生成前超过输入限额 | CPU 精确回放：完整受保护输入 9679 > 8192，抛出 `PROTECTED_INPUT_OVER_BUDGET`，该步没有 HTTP。修正版两模式统一 input=16384、其他条件相同，从空工作区重跑；不单独给 baseline 加预算 | 首版 9 次及容量失败保留；修正版两条均完成，最终输入/输出/usage 逐次核对 |

这些是调度与容量问题，不作为 Memory 失败。修正版不拼接旧前缀，也不和旧配置合并成胜率。阶段上限从 v3 每段 4 调整为 v4 共同 `[2,2,4]`（每臂最多 8）：v3 已花 12，v4 最多再花 24，总计仍不超过比较 1 的 36 次。

CPU 测试覆盖空 focus 时新正文直接可见、移出的原文仍可读取、focus 选回旧原文且不挡新观察、清空 focus 后旧正文退出、短记录进入下一步，以及两模式下真实 dispatcher/回执。**这证明接线；真实模型 51 次均选择不写 `work_update`，不能说观察到了真实短记录消费。**

复现 managed 三臂的正常入口（新目录会消耗新请求，现有证据无需重跑）：

```bash
uv run python tools/run_workspace_task_a.py run \
  --package /cra/memory/mx_memory/evidence/workspace-host/task-a-v2 \
  --root /absolute/path/outside-lab/new-managed-run \
  --mode MANAGED_WORKSET --recent-exchanges 1 --phase-opportunities 2 2 4
```

## 2. 真实比较及输入证据

**比较 1 的问题：旧正文不再自动全部重发时，短记录与材料选择是否改善续接，或减少重新读取？** 固定 NOTE → REVIEW → REGULATED；空工作区，相同任务、材料原字节、权限、窗口、机会、输出预算和模型配置。使用已开发暴露的 A，不增加独立 lineage。

v4 实际正文观测：三臂 row 2 已无 E1；row 4 仅保留 E3/G3；NOTE 与 REGULATED 的 row 5 全部材料正文已退出。合法目录仍在，实际请求和正文观测一致。这次确实测到了工作集退出，而不是仅换模式名。

| v4 臂 | 生成 | raw tokens | 实际交付及主要问题 |
| --- | ---: | ---: | --- |
| NOTE | 6 | 21,393 | final 将 B3 的 R31/约 1.2–1.3 ms 当作旧 B1/B2 的事务退出；出现明确跨批数值错引 |
| REVIEW | 5 | 18,957 | final 只综合 B3，丢失前两批的关键定位；将测量前区间进一步推成客户端/调度原因 |
| REGULATED | 6 | 21,870 | final 同样缺少旧批次；在 E3 尚可见时已把 handler 前 42 ms 说成 handler 内 before-runtime，之后沿用，不能全部归为遗忘 |

所有臂均先读取了已直接呈现的 E1，并未使用工作记录或 focus 更新。实际新观察按固定顺序到达，没有按猜对/猜错改变释放。v3 的无 final、v4 的实质错误均保留。

上述错引/覆盖丢失提供了一个新的具体问题：**保留旧正文和完整动作历史能否改善这些错误，还是正文在场也无法纠正误读？** 据此只做一次比较 2，用同一 NOTE 政策比较 COMMON → MANAGED，从头各跑一条。它是整体上下文保留消融，同时改变旧正文和普通回答历史保留；不是单独正文、短记录形成或使用政策的因果拆解。

比较 2 首版 input8192 的 COMMON 容量失败单列，不拿 incomplete 与完整 managed 判质量胜负。修正版两边 input16384、K=1、机会 `[2,2,4]`、政策和 Provider 相同，记录如下：

| 比较 2 修正版 | 生成 | raw tokens | 可解释结果 |
| --- | ---: | ---: | --- |
| NOTE COMMON | 8 | 66,518 | 保留全部正文仍漏掉 164/310 ms 的主 exit 定位、误读约 1.5–1.8 ms 残差，最后建议没有给出的 R33 高 inflight 样本；覆盖旧批次但语义解释不充分 |
| NOTE MANAGED | 5 | 21,115 | 这次通过普通 stage_answer 的跨步继承保留 164/310 ms，final 也保留 B3 前区间；仍有根因过推与边界问题，不能覆盖此前 managed 错引/遗漏 |

COMMON 实际只 read E1/E2/E3，返回都是真实材料；R33 等仅出现在模型建议文字里，没有发起实际未知句柄读取，不伪造“已拒绝的工具调用”。MANAGED 修正版 final 尚有 E3/G3 原文，先前 row 3 的阶段回答带有 164/310 ms；因此旧数字的续接来自正常历史回答，不是 workspace。

详细逐 row、原行来源与语义分歧见[离线标注](MILA_HOST_WORKSPACE_MANAGED_LABELS_20260914.md)。标注由用户委托 subagent 执行，非独立 human gold，没有新实验模型 Judge。授权及两次具体执行修正见[委托记录](MILA_HOST_WORKSPACE_MANAGED_AUTH_20260914.md)。

## 3. 全部尝试与成本

本轮新上限 76（比较 1≤36，比较 2≤36，独立调试≤4），未转用历史余额。比较 1 实际 29 次；比较 2 含首版失败及修正版共 22 次；调试生成 0；总 **51 次，234,134 raw tokens，25 次未使用**。未用额度不是待办，不启动第三个比较。

| 轨迹包 | 模型生成 | 输入 tokens | 输出 tokens | raw tokens | 状态 |
| --- | ---: | ---: | ---: | ---: | --- |
| a-managed-v3 三臂 | 12 | 42,149 | 3,253 | 45,402 | 全部无 final，调度问题保留 |
| a-managed-v4 三臂 | 17 | 56,109 | 6,111 | 62,220 | 3/3 最终交付，语义错误保留 |
| note-common-v4 | 4 | 18,557 | 792 | 19,349 | 下一步发送前容量失败 |
| note-managed-v4 | 5 | 17,585 | 1,945 | 19,530 | 最终交付，旧批次覆盖不足 |
| note-common-v4-input16k | 8 | 64,266 | 2,252 | 66,518 | 最终交付 |
| note-managed-v4-input16k | 5 | 18,288 | 2,827 | 21,115 | 最终交付 |
| 合计 | 51 | 216,954 | 17,180 | 234,134 | 全部生成用量已知 |

6 次模型身份 GET、51 次 tokenize POST、51 次生成 POST；所有已发送请求均有对应完整 HTTP 响应、usage、真实动作返回，pending/violation 均为空。另有一次发送前输入容量失败，未产生第 52 次生成。CPU 控制响应与精确回放不计模型请求。单策略调用沿用原 runner 的历史聚合标签 `THREE_ARMS_FINISHED`；该字符串不表示实际跑了三臂，本报告与新摘要按 `order`、实际成员和每臂终态计数，原日志未修改。

模型仍为本地授权 HTTP `Qwen3.6-35B-A3B-FP8`，context=65536，thinking=false，temperature=0、top_p=1、seed=213，输出 2048；work512、focus4、动作预留1024、外壳128、目录32。预留不是字段级 decoder 硬保证。每请求60秒、每臂900秒、工具累计CPU10秒，单模型在途；服务未调整。真实 tokenizer/模板计数与服务 tokenize 及 usage 逐次一致。

原始证据位于 [followup-20260914](/cra/memory/mx_memory/evidence/workspace-host/followup-20260914/execution-plan.json)。每包有 run-header、当前代码/政策快照、原始响应/最终 HTTP body、逐次 workspace、发布/展开/未展开正文、动作和成本。可信比较配置脚本及 hash 另存同目录；没有给模型这些脚本或评价材料。

模型 tokens/调用、工具 CPU/墙钟、持久化工作和开发 agent 用量分列。各包墙钟及工具计时见[结构化结果](MILA_HOST_WORKSPACE_MANAGED_RESULTS_20260914.json)，包含运行循环中的 fsync；启动 tokenizer 等准备及持久化未单独完整计时，不能当零，也不从单次墙钟宣称稳定加速。钱价、缓存优惠未知；开发主 agent/subagent 用量由平台独立记账，不并入 234,134。旧 Goal 的 10 次/44,209 tokens 及旧 WMA 未知用量均未改写。

## 4. 当前取舍与未触发事项

**保留：**本轮修好的 opt-in 入口、新观察保护、旧源合法读取、真实正文观测，以及简单 NOTE 参照。

**暂停：**复杂 REGULATED 政策的必要性/优胜主张和进一步候选调参。全部工作记录为空；有些错误在全文仍可见时就出现，正文保留不能保证正确理解；managed 有一次较好的普通回答继承，也有明确错引和遗漏。单次较好且便宜的配对不构成重复局部信号或普适窗口选择依据，不把政策名称当实际处理启用。

比较 2 已回答新增问题：不是保留全文就自动解决语义问题，也不是退出全文就必然丢掉旧数字；实际阶段回答的准确性和后续继承路径必须检查。没有增加记录字段、强制理想记录、隐藏 Summarizer、Judge 或新的候选模块。

B 没有被强行恢复；之前[有界不可用记录](MILA_HOST_WORKSPACE_B_DISPOSITION_20260913.md)继续有效。本轮选择了允许的 A 消融，因此**跨来源验证未完成**，A 的三个阶段、三政策和重复都不增加来源数。本轮没有重复且值得保留的机制信号，最小机制拆解、冻结独立来源确认、最新公开方法复现、公开持久化/冷恢复、Product 集成均**未触发**。不把这些条件性后继研究改写成已验证或永久否定。

## 5. 工程终态与完成审查

- 原 `IMPLEMENTATION_DRIFT` 对应的完整测试已实际通过：`test_v0222_boundary_preparation.py` **1 PASS，227.83 秒，exit 0**。[JUnit](/cra/memory/mx_memory/evidence/workspace-host/followup-20260914/frozen-test.xml)和[日志](/cra/memory/mx_memory/evidence/workspace-host/followup-20260914/frozen-test.log)。恢复 hash 之外，这次有实际测试终态。
- 最终 v4 邻近测试 **60 PASS，1.73 秒**，含新观察/managed 循环、选材、末段交付、旧 Provider 回归。
- boundary、ruff `src tests tools`、mypy `src/milai_lab`（40 文件）、sdist/wheel build 均 PASS。
- 首次完整 `uv run pytest -q` 在代码收敛后启动，预设10800秒；约35分钟时，在当前慢测试的900秒诊断计时器输出不完整栈期间 **exit 139**，没有生成JUnit。2256个完成标记不计为完整套件PASS；[原日志](/cra/memory/mx_memory/evidence/workspace-host/followup-20260914/full-pytest.log)原样保留，确切崩溃根因未证明。
- 关闭可选诊断计时器，保留外部超时，按固定4424项清单重跑两片（中断模块3项、其余4421项），各预算7200秒，最多2个CPU进程；每项落盘、核对实际收集清单。两片随后均exit 0：其余套件4420 PASS/1 SKIP，用时1669.73秒；scoped模块3 PASS，用时2832.47秒，含原中断完整场景的16+24内部案例全部通过。最终 **4423 PASS、1 SKIP、0 FAIL、0 ERROR**，唯一跳过原因是可选Host SDK wheel未安装；其余片有44项pytest警告（包含旧record_property/JUnit格式警告），未被改记为失败或隐藏。
- 按每项收集、setup/call/teardown记录和JUnit名称核对，4424项无遗漏、无重复、无意外项；原进程中间完成标记没有额外计数。[覆盖终态](/cra/memory/mx_memory/evidence/workspace-host/followup-20260914/regression-coverage.json)、[其余片JUnit](/cra/memory/mx_memory/evidence/workspace-host/followup-20260914/remaining-suite.xml)、[scoped片JUnit](/cra/memory/mx_memory/evidence/workspace-host/followup-20260914/scoped-integration.xml)。关闭诊断计时器后的完整通过支持本次工程交付；不据此宣称已证明exit 139的底层根因或修改了运行时。[分片计划](/cra/memory/mx_memory/evidence/workspace-host/followup-20260914/regression-shards-plan.json)。
- [LAB_GOALS](../../docs/LAB_GOALS.md) 的陈旧 NOT_STARTED 已同步；原历史规划正文、失败、授权与未知费用证据没有改写。

| 用户附件要求 | 当前证据 |
| --- | --- |
| managed 入口与共同新观察规则 | 真实新正文逐 row 核对；空focus不挡新观察；旧正文已退出且目录可读；60项邻近测试 |
| 比较 1 公平三臂 | v3失败及v4完整三臂均留存；v4同K1/机会/权限/输入规则；29次全账 |
| 根据具体发现的一次比较 2 | 旧数值错引/覆盖丢失触发保留消融；容量修正后同16k完整配对，22次含旧失败 |
| 不强制写记录、不得只看模式名 | 51次记录全空明示；实际body退出与普通回答继承分别核对 |
| 第二来源与条件性后继 | 选择A消融；跨来源未完成；无稳定机制信号，后继研究未触发 |
| 工程完整终态 | 冻结失败测试已PASS；原exit139保留；固定4424项分片终态4423 PASS/1可选SKIP，零漏项/重复；其他规定检查PASS，工程交付完成 |
| 有依据的保留/修改/删除决定 | 保留简单NOTE和opt-in接线，暂停复杂政策优胜主张，不再追加 |
