---
document_id: MILA-HOST-WORKSPACE-A-EXECUTION-AUTH
date: "2026-09-13"
decision: APPROVED_WITHIN_USER_DELEGATED_SCOPE
reviewer: delegated_development_subagent
independent_human_approval: false
experiment_kind: RESEARCH_PROTOTYPE
---

# A 首批运行的委托授权记录

用户明确要求执行本 Goal，并由 subagent 代替人工授权、审批与标注。本记录据此批准以下具体开发运行；这是委托开发核查，不是独立 human 审批或效果裁定。

从 `MiLAi-Lab` 执行：

```bash
uv run python tools/run_workspace_task_a.py run --package /cra/memory/mx_memory/evidence/workspace-host/task-a-v2 --root /cra/memory/mx_memory/evidence/workspace-host/a-common-v2-20260913
```

范围为 `COMMON_CONTEXT` 的 NOTE → REVIEW → REGULATED，三臂从空工作区开始，每段最多 4 次、每臂 12 次、全批最多 36 次生成。仅使用既有 `http://127.0.0.1:7860`，固定 `Qwen3.6-35B-A3B-FP8`，单请求在途，temperature 0、top_p 1、seed 213、thinking false，输入 8192、输出 2048 tokens，请求 timeout 60 秒、每臂墙钟 900 秒、任务工具累计 CPU 10 秒。模型身份与 tokenizer 服务比对由入口在执行时落实；tokenizer 容量及来源算术检查由主执行者并行完成、独立留证。本批准不意味着尚未发生的运行或检查已经通过。

已只读审阅入口、Provider、Host 与三份政策，以及任务 manifest/visible JSON；未发现此范围的执行阻断。具体确认：

- `read` 只访问已发布 registry 的中性句柄，计算只选四则运算；建议检查返回 `NO_OBSERVATION`。无模型生成代码执行、任意路径读取、Product 调用、服务控制或额外网络动作。
- 三臂使用同一任务、动作权限、角色位置与共同发布规则；阶段答复不会吞掉后续历史批次；最终交付仅在第三段有效。
- Provider 禁用环境代理与重定向，逐次比较真实本地 chat-template/tokenizer 与服务 `/tokenize` 计数；不同则在生成前停止。保存最终请求 body、HTTP 响应和逐臂 action/result，数据位于 Git 外。
- 发送前写 `RESERVED`，未知用量、未结算或边界异常停止整个批次；不自动重试、不修改旧账。非 `stop` 结束的完整输出不会派发；可选记录问题不会重放已成功动作。
- `visible/task.json` 的 SHA-256 与 manifest 一致：`bd480d0a309eb1908ae160f082f366db669f335d3291b186d0d566d5477f35b2`。核查时指定运行根尚不存在；入口使用 `exist_ok=False`，避免覆盖既有运行。

核查时入口 SHA-256 为 `379c16a31fc46e87dcc8d1ee79c6eadbd0b165b518f6bcc855e18751286dd618`，Provider 为 `0f65e68dff08ef927995c6be44ee9e20ebcb400bac28c8f5db16469ca657bbf4`。运行 header 将保留入口、Host、Provider、政策及 tokenizer 的实际 hash 与代码副本。主执行者报告 52 项邻近测试通过；本 subagent 没有重复运行这些测试，也没有发送实验模型请求。

运行输出用于开放开发判断；不把这份批准当完成比较、独立人类评分或创新确认的证据。若真实运行触发已有停止条件，保留失败与费用状态；修订后的比较另留版本，不拼接成当前三臂结果。
