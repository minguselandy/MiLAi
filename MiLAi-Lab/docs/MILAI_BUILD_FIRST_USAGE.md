# Build-first 开发候选

执行范围见[完整计划](MILAI_BUILD_FIRST_DEVELOPMENT_AND_EXPERIMENT_PLAN.md)。当前包A–D的候选代码已接通，首次启动发生调用前配置失败，修复后五条真实冒烟待继续，Product仍为NO_GO。

## 实现

`methods/edit_maintenance.py`提供一个来源批次的共同编排：当前原文→可选一次提取→普通dense K10定位→一次既有编辑器→实际提交。普通Host和benchmark调用同一实现，配对CLI仍仅用于原配对复现。`maintenance_recipe`可选`single_pass`或`extract_then_edit`；没有配置此字段的历史入口保持原流程。

普通Host继续先捕获用户来源，再按当前请求权限调用维护；实际工具来源分别处理。启用recipe后不再向Host提供另一套save/update工具。编辑提交仍走`FunctionalEditMemory.apply_writer_proposal`、现有版本和事务。结果单列在`maintenance`及`operation_status.semantic_memory`，空提案不表示事实已保存。普通Host现可复用现有`SemanticRetriever`、BGE-m3和编码计账。

编排进度放在同一个Store的执行namespace中，不进入检索事实。已保存提案使用原操作ID恢复提交；未知模型请求保留pending，重开不自动重发。当前权限和来源可见性仍先于恢复。模型传输由调用者提供，方法层不创建客户端。

旧语境使用现有可见近期来源，与当前证据分开交付，不成为本次新事实。只读呈现展开实际`modifies/overrides`关系及其原有条件与断言元数据；未保存的一般规则明确缺失。撤销后的当前状态与历史读取沿用原版本机制，不由程序推导子组频次。

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
python tools/run_edit_suite.py \
  configs/milai-build-first-prefix8-v1.json artifacts/build-first/prefix8-v1 \
  --benchmark halumem --phase predict
python tools/run_edit_suite.py \
  configs/milai-build-first-prefix8-v1.json artifacts/build-first/prefix8-v1 \
  --benchmark halumem --phase score
```

正式首轮在五条冒烟后启动。`predict`保存维护结果、完整答案、逐会话实际状态和作者更新评分所需的原标准检索诊断，诊断在Writer／Reader之后运行并继续计账，不作为维护输入。`score`只复用这些产物执行原作者评分，不重跑Writer、Reader或检索；`all`保留一次运行入口。LongMemEval同样支持预测／评分分开；原无效标签与总机会分母不变。新候选使用新的产物目录，不接写旧冻结运行。B0/B1/B2/M及Append-only主比较、65/277、16保留用户、外部子集和普通Host完整回归均仍在完整任务范围内。

五条冒烟使用一个已公开的功能配置和一个顺序fixture，复用两条既有保存／更正故事、原部分业务故事及实际服务恢复控制，加上一般规则／例外和遗忘消息。每条消息由原CLI重开进程，不用理想卡初始化：

```bash
python tools/run_functional.py prepare \
  --root artifacts/build-first/functional-v2-five-flows \
  --config configs/milai-build-first-functional-v1.json \
  --fixture data/fixtures/milai-build-first-smoke-v1.json \
  --controls data/diagnostics/milai-build-first-smoke-v1-controls.json
python tools/run_functional.py run --root artifacts/build-first/functional-v2-five-flows
```

## 本次验证与边界

受影响工程检查覆盖普通Host两个recipe实际SQLite提交和重开、只读权限、提交后中断恢复、未知抽取请求不自动重发，以及既有四组schema/来源/版本/遗忘路径。传输使用脚本响应，只能证明工程连接，不能证明真实模型效果。新增只读范围／历史、旧语境和两套基准延后评分检查使用脚本响应与实际SQLite，仍不算真实样本。开发配置离线prepare已成功；截至本候选提交准备时，新增真实生成／编码均为0。

父提交`43f5ff7`的Fast在全包mypy发现旧入口的`parse_object`隐式重导出错误，本候选改成显式重导出并通过受影响类型检查。不能借用父提交CI或把脚本响应检查说成效果通过。本候选受影响的三份测试文件通过，另一个LongMemEval延后评分检查通过；改动文件Ruff、受影响源码mypy及包／工具依赖边界通过。

修改仅在Lab；没有修改Product API、Schema、权限、Canonical、Archive或workflow。原始来源、数据库、运行配置与日志保持ignored。本次代码回滚基线为`43f5ff7`，共同编排之前的基线为`c44713e`。

原冻结072队列独立保留：本次核对PID3476759不存在、串行资源锁可取得；B0维护/评估32/32，B1为27/26，B1及suite没有终态，B2/M未启动。原因尚未确认，不能记作完成或将未运行组记零分。没有重启或覆盖旧队列，账本原unknown=4保留。

当前未完事项集中在[问题表](MILAI_BUILD_FIRST_ISSUES.md)。

首次启动记录：`functional-v1-five-flows`使用45596d8，在计账作用域创建前缺失编码客户端的可选配置默认字段，五个首消息均未进入模型；后续消息未运行。生成／编码新增均0，原unknown=4不变。修复域声明并按VLLMConfig展开默认值，使用同一公开配置文件的v2版本及新目录继续，不覆盖失败产物。
