# Host 工作区闭环原型

`workspace-control-v0.1` / `CONTROL_0` 是 opt-in `RESEARCH_PROTOTYPE`，不是产品 State 或已证明有效的新机制。它复用现有 HiAgent/EvidenceHost 轨迹与终端桥接，不改 Runtime、公开产品 Schema 或默认方法。旧 H_ONCE、INCREMENTAL、EVIDENCE_0/1 入口保留。

## 实际循环

首次进入或收到尚未维护的反馈时，现有维护调用产生 `record / question / intent / focus_segments / focus_refs / branches`。程序按已发布 ID 装配材料；Actor 接受或修订建议，选择真实动作；结果进入下一次维护和 Actor 输入。维护与 Actor 均使用现有 Provider、相同模型、同一个总调用预算。

`record/question/intent` 和分支说明均为可错的自由文本。程序不识别“暂停”“恢复”“已完成”等词，不根据缺口关键词强制测试，也不认证记录中的结论。分支引用已有 segment ID，不建立新的语义图或状态枚举。当前目标始终由可信调用方单列提供。

工作集默认保留当前 segment 的完整交互、Actor 尚未看过的反馈、被选中的历史段和已发布 receipt 的有界正文。其他历史正文退出输入，但 ID、子目标和分支入口仍可见；Actor 的 `retrieve` 可重新展开历史段，`read` 可分页回读不可变 receipt。这些动作不重放原业务操作。新反馈不会因旧焦点而被过滤。维护只处理未维护批次，不在纯重装或 retrieve 后重复生成。

容量沿用真实 Provider 窗口与输出上界，不新增 512-token 门槛或隐藏裁剪。选择仍可能使输入超出实际窗口，此时现有 Provider 明确停止，不偷偷删除新证据。

## 交付

`final` 首次成为交付提议，不立即派发、不写伪造的成功回执。下一次现有维护调用看到提议与当前展开证据，提出建议；Actor 再决定继续、缩小声明或提交。相同反馈边界不会无限复核；默认每条轨迹最多两次交付复核，可配置为零。普通维护、复核和 Actor 全部计入共同预算。预算耗尽、未知用量或执行异常不会触发免费最终回答或重放。

解析合法性不是业务正确性。已结算但无效的控制 JSON 保留前一记录、向 Actor 披露拒绝原因，并继续直接呈现新反馈；没有隐藏修复调用。HTTP/未知执行异常仍停止该 Host。

## 使用现有入口

原生入口仍是 `tools/run_workspace_native.py`，增加 `--order CONTROL_0`。需要单次显式交接时可指定 `--control-handoff-after N`，在第 N 个真实工具 receipt 后保存并创建新 Host，使用同一个仍保留的任务容器。未达到该位置则不声称发生交接。

本地调用可继续构造 `HiAgentTerminalSession(..., method="CONTROL_0")`，不需要 Harbor 来测试方法。配置：

```python
session = HiAgentTerminalSession(
    instruction=current_user_goal,
    binding=task_id,
    root=host_artifacts,
    terminal=existing_isolated_terminal,
    generate=existing_model_callback,
    method="CONTROL_0",
    max_calls=64,  # 整个生命周期，不因交接重置
    control_options={"manage_workset": True, "max_delivery_reviews": 2},
)
session.host.step()
```

`control_options={"manage_workset": False, "max_delivery_reviews": 0}` 可以关闭旧正文退场和交付复核；选择 H_ONCE 或 INCREMENTAL 则关闭整个新控制方法。维护政策与 Actor 政策在 `configs/policies/control/`；实验变体须另存版本，不能覆盖旧运行副本。配置能力不是认知效果消融成绩。

## 检查点与恢复边界

在 `step()` 完成、没有未知调用或动作的静止位置：

```python
session.save_checkpoint(checkpoint_path, environment_id=retained_environment_id)
# 调用方停止使用旧 Host；保留当前真实环境。
resumed = HiAgentTerminalSession(...)  # 同一方法、策略、预算、task binding
resumed.restore_checkpoint(checkpoint_path, environment_id=retained_environment_id)
resumed.host.observe(new_legitimate_observation)  # 有新反馈时；不能传 evaluator 答案
resumed.host.step()
```

检查点使用本地 JSON 与原子替换，保存工作区、历史、完整 receipt、已维护/已呈现位置、交付提议和已用调用数。恢复不执行模型、不派发业务动作。保存后但尚未被维护的工具结果仍会进入恢复后的正常循环；当前构造方提供的新用户目标不会被旧检查点覆盖。恢复后所有 receipt 继续通过同一个公开研究 Host 的 `read`/选材入口使用。

这是**可信本地单写者的显式交接**：调用方须停用旧 Host，只将检查点交给一个继续者，不能在世界进一步执行后重用旧副本。它不提供多写者租约、任意崩溃的 exactly-once 恢复、数据库持久 Memory 认证、容器重建或世界回滚。已知失败/未知 in-flight Host 不能生成可恢复检查点；仍须另外对账或核查世界。原生开发交接是同一进程中的新 Host；新进程恢复另有本地测试，二者不混称。

## 如何解释运行结果

日志保留真实输入、维护 JSON、拒绝、选中材料、动作、回执、交接及用量。模型写了分支不等于发生过分支返回；产生 `intent` 不证明 Actor 因此改变动作；回读旧材料不证明条件性再激活；原生成功也不单独证明新增机制有净收益。

本轮单条原生轨迹用于开发反馈，不要求自然出现所有能力，不补跑填矩阵。脚本化模型回调与真实文件/新进程测试属于运行检查，不算模型行为效果。EVIDENCE_1 的既有无增量结果继续保留。完整方法的比较与跨任务迁移需要后续独立授权，不由本实现自动启动。
