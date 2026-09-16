---
document_id: MILA-HOST-WORKSPACE-MANAGED-AUTH
date: "2026-09-14"
decision: APPROVED_WITHIN_USER_DELEGATED_SCOPE
reviewer: delegated_development_subagent
independent_human_approval: false
---

# Managed 比较 1 的委托批准

已阅读本次用户附件 `550b613a-550a-42a7-91da-8d75fae910fb/pasted-text-1.txt`，并核对实际 runner、Host、核心呈现规则与现有 Provider 适配。未发现下列具体运行范围的阻断；依用户延续的 subagent 委托权限批准执行，不是独立 human 审批。

从 `MiLAi-Lab` 执行：

```bash
uv run python tools/run_workspace_task_a.py run --package /cra/memory/mx_memory/evidence/workspace-host/task-a-v2 --root /cra/memory/mx_memory/evidence/workspace-host/followup-20260914/a-managed-v3 --mode MANAGED_WORKSET --recent-exchanges 1
```

使用既有 task-a-v2 原材料、v3 入口，NOTE → REVIEW → REGULATED，共同 K=1、空工作区、相同窗口与规则，每段最多 4 次、每臂 12 次、比较 1 最多 36 次生成。沿用 loopback `127.0.0.1:7860`、固定 Qwen3.6-35B-A3B-FP8、单在途、thinking false、input 8192 / output 2048、60 秒请求与 900 秒臂限额，以及原有限动作、用量未知全批停发规则。此次批准只分配比较 1；比较 2 ≤36 须有新增解释才启动，debug ≤4，合计 ≤76，不挪用旧配额。

关键核对事实：`Task.release` 将新正文直接装为带 dependencies/body_refs 的共同观察；其可见性不依赖旧 focus。核心保留最近 K 个完整交换，旧材料仍在 registry，`read` 权限相同；合法 focus 可让退出的正文重新展开，短记录进入下一次输入。Host 记录 `new_body_refs`、`assembled_body_refs` 和未呈现正文引用，后续应以实际请求证明正文退出，不能只按 managed 名称判断。K=1 下最短三步终段允许 E1 原文退出，但实际选择可能重新保留它，必须如实记录。

模型仍只可读取已发布句柄、做四则计算和提交建议/文本，没有新 Provider 服务、任意代码或路径执行能力。任务适配器继续复用 `v0213_provider` 的 HTTP client、verify、timeout 与 close，保留输出限额、tokenizer 双端一致性检查及 RESERVED/SETTLED 停发语义；本轮不启动服务或修改旧 Provider 冻结源码。

检查时任务 visible hash 与 manifest 一致，指定运行目录不存在。runner SHA-256 为 `d8b5bbb0d3c2d7c6fc7062445e8bbef4231018b0e9cd39dd102605c87f8b57d1`，Host 为 `f767276f87b9b15ff9b1098a2f4d1dd0e8ede3700225e010694805f557c6def7`，task Provider 为 `8c86da96d8f8becaf7262e431cbc79928606512bf04f956e5cbb52aa31b7058e`。执行 header 保留实际版本与副本。

59 项邻近测试通过由主执行者报告，本 subagent 未重复运行；真实 tokenizer 回放与批次 header 由主执行者并行完成后留证。未把这些尚在执行的检查当已通过，也未将此前冻结测试的 hash 恢复当测试通过。此次核查未发送模型请求、不重开 B、不重启运行中的工程检查。

## 同包络内的执行修正与唯一比较 2

v3 实际耗用 12 次生成，三臂均因末段 `stage_answer` 被 dispatcher 当作结束而未交最终。按附件允许的具体执行修复，v4 将此动作返回为 `FINAL_STILL_REQUIRED`，保留剩余机会，仍只接受模型实际提交的 `final`。三臂共同机会改为 `[2,2,4]`，每臂 ≤8、v4 ≤24，与已用 v3 12 次合计不超过比较 1 的 36 次；新目录独立运行，不拼接旧失败。主执行者报告新增邻近检查 60 项通过，冻结源码相关测试取得真实 `1 PASS / 227.83s`，不以恢复 hash 代替测试结果。

v4 已实际完成 17 次，比较 1 共耗用 29 次。离线看到 NOTE 把 B3 数值迁移到旧批次、REVIEW/REGULATED 最终未综合旧批次，同时实际旧正文与早期回答退出；这构成一个新增且有界的问题。因此批准唯一比较 2：同一 NOTE 政策，固定 COMMON_CONTEXT → MANAGED_WORKSET(K=1)，双方全新运行、同 v4 代码/原任务/字段/机会 `[2,2,4]`/Provider/资源，每条 ≤8、合计 ≤16。仅可信入口将 `ORDER=('NOTE',)`，不改核心或政策。问题是保留旧正文及完整历史是否改善上述错误；这是**整体上下文保留消融**，不是单一正文规则、短记录因果或第二来源比较。16 次属于比较 2 的 ≤36 包络，不借用调试或旧额；总上限仍 76。未发现此具体范围的执行阻断，无需新增审批层或 Judge 调用。

比较 2 首版 COMMON 在 4 次已结算生成后因组装需要 9679 tokens 超过 input 8192 而停止，尚未发送下一次生成；MANAGED 用 5 次完成。依附件的具体执行修复范围，允许将**双方共同 input 改为 16384**（实际模型 context 65536），其余 v4/NOTE/K1/`[2,2,4]` 与 Provider 不变。可信入口以 `partial(Limits,input_tokens=16384)` 配置，实际 header 留值，根名 `note-*-v4-input16k`，COMMON→MANAGED 新跑 ≤16 次，不拼旧轨迹。首版 9+修正版 ≤16=≤25，仍在比较 2 的 ≤36 内；没有扩大 76 总上限。修正版实际 8+5=13 次，本轮全部合计 51 次、debug 0。此后不再追加生成。
