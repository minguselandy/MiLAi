---
document_id: MILA-HOST-WORKSPACE-PROTOTYPE
version: "0.1"
date: "2026-09-13"
status: PROTOTYPE_NEIGHBOR_PASS_FULL_REGRESSION_INCOMPLETE
arm_kind: RESEARCH_PROTOTYPE
persistence: IN_PROCESS_ONLY
model_requests: 0
provider_http_requests: 0
product_requests: 0
---

# 工作区策略原型：本轮开发记录

## 1. 实际完成了什么

按最新审阅对[主设计修订 4](MILA_HOST_WORKSPACE_POLICY_DESIGN_v0.1_20260913.md)和[任务附件](MILA_HOST_WORKSPACE_FIRST_TASKS_20260913.md)作局部修改，没有再立总 Goal。移除必须覆盖全部机制、必须重新采用、每次必须跑满六轨迹等约束；补充未验证线索、正向诊断进展、阶段答复和机械检查不能预测模型步数的边界。

实现限于 Lab，Product、Client 默认行为和旧实验原型未改动：

| 文件 | 已实现内容 |
| --- | --- |
| [workspace_policy.py](../../src/milai_lab/methods/workspace_policy.py) | 工作区、材料句柄、完整消息组；调用前组装及调用后更新接收；机械容量/来源边界 |
| [三份政策](../../configs/policies/workspace/) | NOTE、同调用 REVIEW、REGULATED；同工作区和选材能力，均可不更新 |
| [workspace_policy_host.py](../../tools/workspace_policy_host.py) | 显式 opt-in、单写者、一次 step 一次生成回调；原动作验证/派发回调；逐轮记录 |
| [核心测试](../../tests/unit/test_workspace_policy.py)、[Host 循环测试](../../tests/unit/test_workspace_policy_host.py) | 可控响应、真实本地测试 dispatcher、输入变更与失败边界 |

这是一条借用现有 Lab `action + arguments` 形式的轻量 Host 接缝，不是已经把插件安装进所有旧 Host。没有引入新框架、持久化层、语义 controller、Reviewer 或 Provider。真实模型尚未接入，也未签发 HTTP 输出兼容结论。

在 Lab 源码 checkout 的任务入口中构造 `WorkspaceHost(enabled=True, policy=load_policy("NOTE"), ...)`，注入该任务现有的 tokenizer、当前材料 registry 和动作验证；每次正常决策调用 `host.step(new=..., generate=..., dispatch=...)`。`generate` 返回 `Generation`，`dispatch` 返回真实 `Exchange`。具体可运行用法见 Host 循环测试；这里的省略号代表任务依赖，不是另一个待开发框架。默认 `enabled=False`，禁用时不插入政策、工作区或材料目录。

## 2. 可观察的循环

CPU 循环覆盖三种政策 × 两种上下文模式。测试响应第一步留下记录并选择 E1；下一步收到这份记录、E1 和实际 dispatcher 回执；再选择 E2 后，managed 输入不再展开 E1 正文，但原材料与目录入口仍在。普通历史保留动作与真实返回，不重复旧 `work_update`；逐轮档案保留完整原响应。

这些响应是测试代码给出的，**没有模型自行形成认知记录**。测试证明记录和引用确实影响输入、动作派发与真实测试回执可以续接；不证明模型会按政策判断，也不形成六条任务开发轨迹或认知收益分数。

`COMMON_CONTEXT` 提供同一材料规则，focus 不裁剪正文；`MANAGED_WORKSET` 保留新观察、未结操作、最近完整交互，只额外展开选中旧正文。两者同钩子、同能力；common 无需胜出才能使用 managed。

## 3. 机械边界与已知限制

- 不读取 State 关键词来判定暂停、恢复、成功或任务结束。实际任务分段由调用者决定，`step` 返回不是整个任务完成。
- 完整 JSON 可解析、动作独立合格但记录不合格：拒绝记录，正常派发该动作一次，下一正常步骤反馈；不修复调用、不重放业务动作。
- 完整消息不可解析、Provider 结果未知或 dispatcher 异常：保留该次记录、停止该 Host 实例，不隐式重试。未知用量为 `None`，不填零。
- 来源句柄由调用者发布；不接受模型给出的文件路径或越任务引用。披露依赖与“当前正文已经展开”分开；移除 focus 不会抹掉旧记录的披露依赖。旧权限/版本失效时不靠历史或关闭插件回退泄露正文。
- 这里的 revision 标识可披露的材料快照，不是“这条事实目前还正确”。新的世界观察应另发句柄，合法的旧快照仍可供复核；不能把语义反证等同权限撤销来自动隐藏旧判断。
- 原任务、授权及真实结果独立于工作记录。记录中的“已完成”不是真实回执，记录只是机械上合格，不等于事实正确。
- 当前只支持 Lab 文本 JSON 动作和完整文本交互组；没有宣称兼容原生 function/tool-call 消息。实际 Host 负责提供完整组、当前资格、业务验证、动态权限/CAS、原来源读取能力。
- 只处理已发布的小材料目录，开发默认最多 32 项；这不是面向全量语料的新检索器。超出时显式报错，未来复用原 Host 分页入口，不在插件中扫描证据树或做语义排序。
- token 计数由调用者注入。当前测试使用明确标注的字符计数替身，不是模型 tokenizer 校准；真实运行需用现有模型 tokenizer／聊天模板计数。512 tokens、4 refs、K=2 都是配置。
- 输出预算单列动作、工作记录、外壳余量，并提示动作先输出、空间不足用 null。这是预算配置和后验接收，不是 decoder 对每字段的硬分配保证；截断 JSON 仍不得猜动作。
- `rows.request` 是传入 generation 回调的 Host 输入；最终 HTTP body、发送确认和模型用量仍由实际 Provider 记录。MOCK_INPUT_ONLY 不冒充真实呈现回执。
- 实际 Provider 的预算、未知用量停发和核账规则仍需保留；此接缝只接收用量记录，没有替代原 Provider 的账务门。`Generation` 数据对象不是新请求授权。
- 逐轮记录目前在内存，可交现有 logger 写到 Git 外的运行目录；未实现冷恢复、公开 Note 或 Working State 写入。权利不因进程内存而扩大。

## 4. 检查与范围

邻近测试：47 PASS。覆盖三臂共享能力、两种模式、空更新/完整替换、真实旧正文移出、回执保留、超限、引用撤销、参数越界、坏 JSON、未知发送和禁止重试。

Lab 收尾检查：

| 检查 | 实际终态 |
| --- | --- |
| `uv run pytest -q tests/unit/test_workspace_policy.py tests/unit/test_workspace_policy_host.py` | 47 PASS |
| `uv run milai-lab-check-boundary` | PASS |
| `uv run ruff check src tests tools` | PASS |
| `uv run mypy src/milai_lab` | PASS，40 个源码文件 |
| `uv build` | sdist / wheel 均成功 |
| `uv run pytest -q` | **未完成**：2250 PASS / 1 SKIP 后人工中断，exit 2，974.58 秒 |

全回归执行一次。观察到长时间仍未完成后，声明采用 15 分钟收尾预算；下一次状态检查时已超过该预算，实际中断耗时为 **16 分 14 秒**，不是严格 900 秒 deadline 的测量。只向本轮启动且核对了 PID 的 pytest 发送 SIGINT，未终止共享服务。停止位置为旧 `tools/v0220_evidence.py:20`，未做进一步性能归因或优化。已完成部分未报告测试失败；未运行部分不能据此算通过。

这不是新的实验准入门。原型依靠相关邻近检查交付，但明确保留全回归未完成的限制；不签发全仓 PASS，不自动重跑剩余旧测试。

本轮原型模型请求 0、Provider HTTP 0、Product 请求 0。没有启动或修改实验/共享服务，没有 GPU 操作、新 benchmark 下载或确认样本消费，没有重跑旧 WMA 评分或修改其历史未知账务。A0 默认、Schema NO-GO 不变。

## 5. 下一小步

优先把 A 的已有原始材料打成小回放包并接这条循环，不等 B 全部准备完；保持真实数值、来源关系、分阶段外生释放、正向诊断审阅。原型已可用受控响应调试；在实际 Provider 接线和这一次任务的共同步骤/资源范围明确之后，才开展相应的模型调试和公平三臂比较。

若任务或接口暴露具体问题，就改那一处并保留版本。工作记录、更新政策、输入组织、材料展开和任务难度可独立或组合调整；不由本次 CPU PASS 推导创新，也不再把 A—E 全链当每次探索的入口。
