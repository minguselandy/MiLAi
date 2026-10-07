# Build-first 开发候选

执行范围见[完整计划](MILAI_BUILD_FIRST_DEVELOPMENT_AND_EXPERIMENT_PLAN.md)。当前已接通包A的代码路径，尚未完成真实模型验收及包B–D，Product仍为NO_GO。

## 实现

`methods/edit_maintenance.py`提供一个来源批次的共同编排：当前原文→可选一次提取→普通dense K10定位→一次既有编辑器→实际提交。普通Host和benchmark调用同一实现，配对CLI仍仅用于原配对复现。`maintenance_recipe`可选`single_pass`或`extract_then_edit`；没有配置此字段的历史入口保持原流程。

普通Host继续先捕获用户来源，再按当前请求权限调用维护；实际工具来源分别处理。启用recipe后不再向Host提供另一套save/update工具。编辑提交仍走`FunctionalEditMemory.apply_writer_proposal`、现有版本和事务。结果单列在`maintenance`及`operation_status.semantic_memory`，空提案不表示事实已保存。普通Host现可复用现有`SemanticRetriever`、BGE-m3和编码计账。

编排进度放在同一个Store的执行namespace中，不进入检索事实。已保存提案使用原操作ID恢复提交；未知模型请求保留pending，重开不自动重发。当前权限和来源可见性仍先于恢复。模型传输由调用者提供，方法层不创建客户端。

## 使用现有入口

在Lab目录使用已有包含LangGraph依赖的Python环境，设置`PYTHONPATH=src`。以下命令会使用配置中的现有本地服务；`message`与benchmark运行会产生真实调用，需保持串行。配置中的本机服务、tokenizer及账本路径按当前环境填写，不创建新服务或预算。

```bash
python tools/run_functional.py prepare \
  --root artifacts/build-first/functional-v1-smoke \
  --config configs/milai-build-first-functional-v1.json
python tools/run_functional.py message \
  --root artifacts/build-first/functional-v1-smoke \
  --owner development --session daily --message-id save-1 \
  --text '请记住：我的提醒用静音模式。'
python tools/run_functional.py message \
  --root artifacts/build-first/functional-v1-smoke \
  --owner development --session daily --message-id query-1 \
  --text '我现在的提醒偏好是什么？这次只查询，不保存。'
```

同一公开消息显式恢复时使用相同owner/session/message-id/text并加`--resume`。新的用户消息使用新的message-id。真实五条冒烟尚未运行，上述是可运行入口说明，不是成功结果。

实验配置使用同一方法实现，首轮只选M作为工程候选，不是最终方法选择：

```bash
python tools/run_edit_benchmarks.py \
  --config configs/milai-build-first-prefix8-v1.json \
  --output artifacts/build-first/prefix8-v1 \
  --benchmark halumem
```

正式首轮应在包B–D与五条冒烟之后启动；当前作者评分仍为原同步路径，预测与事后评分解耦尚未接完。B0/B1/B2/M及Append-only主比较、65/277、16保留用户、外部子集和普通Host完整回归均仍在完整任务范围内。

## 本次验证与边界

受影响工程检查覆盖普通Host两个recipe实际SQLite提交和重开、只读权限、提交后中断恢复、未知抽取请求不自动重发，以及既有四组schema/来源/版本/遗忘路径。传输使用脚本响应，只能证明工程连接，不能证明真实模型效果。Ruff、受影响源码mypy、包依赖与工具依赖边界通过。开发配置离线prepare已成功，新增真实生成/编码均为0。

修改仅在Lab；没有修改Product API、Schema、权限、Canonical、Archive或workflow。原始来源、数据库、运行配置与日志保持ignored。回滚基线为`c44713e`。

原冻结072队列独立保留：本次核对PID3476759不存在、串行资源锁可取得；B0维护/评估32/32，B1为27/26，B1及suite没有终态，B2/M未启动。原因尚未确认，不能记作完成或将未运行组记零分。没有重启或覆盖旧队列，账本原unknown=4保留。

当前未完事项集中在[问题表](MILAI_BUILD_FIRST_ISSUES.md)。
