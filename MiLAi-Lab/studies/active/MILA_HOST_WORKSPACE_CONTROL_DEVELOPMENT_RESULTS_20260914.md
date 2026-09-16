# Host 工作区闭环：实现与单条原生开发运行

日期：2026-09-14。类型：`RESEARCH_PROTOTYPE`。状态：**`INTEGRATED_LOOP_IMPLEMENTED / SINGLE_NATIVE_TASK_PASS / REGRESSION_COMPLETE / BENEFIT_NOT_ESTABLISHED`**。

本轮按用户要求直接集成架构，没有重写总 Goal、建立新的准入体系或续用旧额度。代码与获批的单条模型运行已完成；后续已取得全仓回归终态：4520 通过、1 可选依赖跳过。研究判断不因局部打平自动收口为 KEEP_SIMPLE，也不因本次单题通过升级为创新成立。

后续修复见 [独立修复 Goal](MILA_HOST_MEMORY_CONTROL_REPAIR_GOAL_v1.0_20260914.md) 与
[修复结果](MILA_HOST_MEMORY_CONTROL_REPAIR_RESULTS_20260914.md)。它们不替换本报告的旧方法和费用。

## 实现交付

方法 `workspace-control-v0.1`，政策 `CONTROL_0`，终端适配器 `hiagent-method-adapter-v0.3.0`。复用 HiAgent/EvidenceHost、现有 TerminalTools、Provider 与 Harbor 入口，旧 H_ONCE、INCREMENTAL、EVIDENCE_0/1 保持可选。代码没有增加产品 Runtime 语义职责或新的 canonical State。

| 能力 | 实现 | 本轮实际覆盖 |
| --- | --- | --- |
| 维护与行动衔接 | 独立维护产生记录、当前问题、建议意图，Actor 结合原始反馈决定下一步 | 13 次维护尝试，12 次有效替换，控制实际进入 Actor |
| 工作集 | 按公开 segment/receipt ID 展开材料；当前段与尚未呈现反馈受保护；其余正文可退出 | 13 次 Actor 输入中，12 次含选中 receipt，11 次存在已归档旧段 |
| 暂挂与回读 | 自由文本分支入口、段 retrieve、receipt 分页 read；不重放旧业务动作 | 两次输入含分支记录；2 次实际 receipt read；自然 segment retrieve/分支返回均未发生 |
| 交付 | final 先提议；现有维护作有界建议，再由 Actor 继续或提交 | 1 次提议、1 次复核，之后提交；没有伪造提前提交回执 |
| 检查点 | 静止边界原子保存 Host、receipt、反馈位置、调用账；恢复同一循环 | 第 2 个工具结果后真实保存并创建新 Host/来源注册表，继续处理未维护结果；预算未重置 |

原生交接是**同一进程内的新 Host**、同一保留容器，不是 OS 进程重启。另有本地新进程测试：实际文件只写一次，恢复后通过 receipt 回读并继续；该测试使用脚本模型回调，不算模型认知或产品持久 Memory 证据。检查点仅支持可信单写者显式交接，不提供多写者租约、任意崩溃自动重放、容器恢复或世界回滚。

程序仅检查格式、已发布引用和恢复合同，不根据“未验证”“暂停”“已完成”等词裁决语义。记录可为空、可被更正。普通方法、共同材料模式和关闭交付复核均保留配置入口。使用说明见 [HOST_WORKSPACE_CONTROL](../../docs/HOST_WORKSPACE_CONTROL.md)。

## 原生运行与结果

用户在本轮明确授权 **1 条原生轨迹，最多 64 次生成（包含维护、复核、失败）**。见 [独立开发分配](../../data/manifests/workspace-control-development-20260914.json)。实际只运行 CONTROL_0，没有新增 baseline、补跑或第二来源。

- 任务：已暴露开发 root `cancel-async-tasks`，Terminal-Bench 固定提交 `2fd12b88aafdd04a52c298e3940bcb189f9766d6`。
- 环境：复用上一轮记录的 uv 0.9.5 verifier bootstrap 补充；任务说明、测试和 checker 未修改。仅调用现有 vLLM HTTP，不操作 GPU 或共享模型服务。
- 模型：`Qwen3.6-35B-A3B-FP8`，实际 65,536 窗口，输出上界 4,096；temperature=0、top_p=1、seed=213、thinking=false。维护为独立 JSON 调用，普通 HiAgent 摘要仍是原有文本调用。
- 原生结果：**reward=1；6 passed / 0 failed**，没有 trial exception。六项包括文件、并发执行、并发上限以及三种数量下的取消检查。这是一个任务，不是六个独立样本。
- Harbor 总墙钟 89.46 秒；Agent 执行 47.45 秒，其中工具累计 2.04 秒。包含关系不重复相加。

原始证据保存在仓库外：[native results](/cra/memory/mx_memory/evidence/workspace-control-development-20260914-S0i9Wr/native/results.json)、[verifier stdout](/cra/memory/mx_memory/evidence/workspace-control-development-20260914-S0i9Wr/native/trials/cancel-async-tasks-0-control_0/verifier/test-stdout.txt)、[原生产物](/cra/memory/mx_memory/evidence/workspace-control-development-20260914-S0i9Wr/native/trials/cancel-async-tasks-0-control_0/artifacts/app/run.py)。

## 轨迹带来的开发反馈

1. **初始控制有一次引用错误。** 当时尚无 segment，模型提出了 segment=1 的分支。程序拒绝整个更新、保留先前空记录，向 Actor 披露；没有额外修复生成，任务继续。这是可用性缺陷，不能将该次维护记为有效形成。
2. **维护实际伴随行动变化。** 首次实现后，维护提出检查取消处理，Actor 随后修改实现。交接恢复后，旧 receipt 被读取；自测暴露空列表错误后，维护将下一意图改为修复该边界，Actor 修改文件。这里只描述发生顺序，没有证明控制记录是动作变化的唯一原因。
3. **仍存在明显重复。** 中途连续四次执行相同的 `cat /app/run.py`；多份维护记录重复宣称实现满足要求。不能因为最终通过，就把这些步骤解释为有效探索。
4. **模型自测不等于完整覆盖。** 它生成的名为 cleanup 的自测只取消了直接创建的示例 task，没有调用 `run_tasks`；因此该自测通过不能独立支持被测函数的取消保证。最终原生 checker 的六项通过另外报告，不将二者混同，也不据此扩张成所有取消场景都正确。
5. **完整架构不等于全部认知行为实跑。** 分支记录曾形成，但没有自然分支返回或条件性再激活；交付复核本次选择提交，没有证明它减少错误完成声明。两项能力的实现与脚本测试不冒充自然效果。

本轮支持“维护—选材—行动—反馈—交接的集成循环可以完成这个原生任务”。没有同期 H_ONCE/INCREMENTAL 对照，没有重复或迁移；不能将旧轮 reward=0 与本轮 reward=1 直接报告为配对收益，更不能归因于某一条规则。EVIDENCE_1 上一轮的无额外收益结论保持不变。

## 用量与收口

| 调用职责 | 次数 | 输入 tokens | 输出 tokens | 合计 |
| --- | ---: | ---: | ---: | ---: |
| Actor | 13 | 41,506 | 2,012 | 43,518 |
| 维护/控制（含初始拒绝和交付复核） | 13 | 24,735 | 3,455 | 28,190 |
| 总计 | **26** | **66,241** | **5,467** | **71,708** |

全部结算，无 pending/violations；53 次 Provider HTTP 均有返回（1 次 models、26 次 tokenize、26 次 generation）。38 次未用生成额度关闭，不继承或扩展。原生进程已经退出，自有 trial 容器已自动删除并核对不存在；没有停止或修改共享服务。代码副本及运行前哈希保存在 native/implementation，核对与当前运行代码一致。开发代理计算与上述模型用量分账，不填造最终代理 tokens 或货币价格。

## 工程检查与剩余事项

- 邻近五模块 **75 项通过**，含真实 Provider 代码的 MockTransport 账务测试、交付提议、选材/回读、新观察直达、未知请求停发、检查点约束与新进程续接。
- boundary、全仓 ruff、mypy（43 源文件）和构建通过；`git diff --check` 通过。没有独立 review Agent 或新增审计层。
- 全仓 pytest **4520 passed、1 skipped，4014.29 秒，exit 0**。
  [regression.log](/cra/memory/mx_memory/evidence/workspace-control-development-20260914-S0i9Wr/regression.log) 与
  [regression.xml](/cra/memory/mx_memory/evidence/workspace-control-development-20260914-S0i9Wr/regression.xml)
  为本方法旧版本的真实终态；不代替后续修复的验证。

本轮工程验收及模型额度均已关闭。保留可运行原型和具体问题：初始无历史时的新线索如何表达、控制为何连续建议结束但 Actor 重复读文件、自然分支返回是否有用。后续用户已要求修复，执行情况在上述独立 Goal 和结果中记录。
