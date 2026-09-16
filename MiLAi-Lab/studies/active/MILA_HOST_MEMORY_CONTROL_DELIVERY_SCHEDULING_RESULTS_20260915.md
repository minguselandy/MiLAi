# Host 记忆调控：交付与调度改进（2026-09-15）

阶段：**Lab 架构开发完成；v0.3 / 适配器 v0.5 已真实运行；v0.4 / 适配器 v0.6 作为当前开发基线，已完成离线验证，尚无该版本真实模型结果。实际效率与 N1–N4 收益仍未证明。**

当前实现为 `milai-rwc-v0.4` / 适配器 `v0.6`，独立 OM 保持 `om-sync-port-v0.1`。
这是 Lab `RESEARCH_PROTOTYPE`。本轮新增真实模型生成 **0**，新增真实业务执行 **0**。
之前 56/64 次生成及其剩余额度保持关闭，没有重新分配。
本轮是依据真实失败进行的运行改进，不构成新的正面或负面方法实验。

[当前架构、记忆流程与使用方法](../../docs/HOST_REVERSIBLE_WORKSPACE.md)；
[紧凑验证记录](../../data/results/memory-delivery-scheduling-20260915.json)；
[上一轮真实运行结果](MILA_HOST_MEMORY_CONTROL_USABILITY_RESULTS_20260914.md)。

## 原始尾部定位

直接读取上一轮 `native-three-arms/host/*/method-events.jsonl` 的模型输入、原始输出、草稿事件
和回执，未依赖旧摘要推断路由。两臂共享同一题与 14 次调用上限，但尾部问题不同：

| 方法 | 已有记录 | 原来的结束阻塞 |
| --- | --- | --- |
| MILAI_RWC | 第13次 Actor 返回合法 final 草稿；此后无新业务反馈、外部消息或回读；第14次 Controller 只回显 delivery_proposal，没有 dispatch。 | 草稿存在且未过期，但 Controller 缺省 ACT，后续 Actor 无额度。 |
| WORKSPACE_SIMPLE | 第13次 Actor 执行业务检查并获得真实结果；没有 final 草稿；第14次调用为关闭段摘要。 | 最后机会被历史摘要用掉，Actor 未获得当前答复机会。 |

RWC 最后一次复核输入的 delivery_reviews_remaining=0，是当前复核已扣除后的余额，
并不意味着该次 Controller 不能 DELIVER；新版另用 delivery_review_active 明确阶段。

历史三臂原生 verifier 均 reward=1、3项通过，只有 OM 提交了 Host final。产物通过与
完成交付是不同观察。OM 7次、RWC/SIMPLE 各14次的历史结果保持原样，不计算“效率翻倍”。

## 改动一：结束路径可达

共享预算中优先保留一次结束 Actor。关闭段摘要按缓存照常复用，但不能消耗保留调用；
Controller 同样不能占用最后一次生成。一次可选草稿复核至少需要两次剩余机会，
使显式要求继续时仍能形成当前答复。Controller RECALL 也保留回读后的控制和结束机会。

Actor 得到 call_budget.remaining / closing。closing=true 时应返回当前结果或明确未完成；
若仍提出工具动作，Host 不执行新动作，提交固定未完成说明。没有剩余调用且没有当前草稿时
同样诚实结束，不凭预算宣布成功。预算耗尽不会自动开启新一轮额度。

普通工作阶段的 `{}` 仍保持工作区并 ACT。草稿复核阶段的无修改且未显式指定路由，或者
已结算但无法接受的复核返回，可以结束可选复核，交付当前 Actor 原稿，标记 UNREVIEWED。
这不把空对象当成批准。明确 ACT/RECALL 会继续；有新反馈时旧草稿失效，需要新的 Actor 答复。

交付状态按机械路径记录：REVIEWED 为明确 DELIVER；UNREVIEWED 为未经明确复核的 Actor
答复；INCOMPLETE 为 Host 生成的固定未完成说明。UNREVIEWED 答复本身也可以诚实报告未完成，
Host 不通过文本分类器判断任务是否成功。状态出现在快照、DELIVERY_COMPLETED 和原生终态元数据。
max_delivery_reviews=0 可以关闭内部复核。工具合同、权限与未知副作用/未知用量停止规则保留。

## 改动二：可关闭的批量维护

`feedback_batch_size=1` 是默认值，保留逐批反馈维护。设为3可让普通连续 Actor 工作先消费
真实反馈，累计三个尚未维护的业务反馈再统一维护。初始目标、恢复、新外部反馈、显式回读、
工作段切换及可选草稿复核会提前触发。工作段边界沿用已有 subgoal，没有新增调度 Agent、
语义判断调用或“失败两次必须换路线”的程序规则。
因此 batch=3 不保证三步只维护一次；频繁切换工作段可能使批量延后很少发生。实际介入频率
与记录滞后的影响需要从正常轨迹判断，当前机制是可配置批处理与生命周期触发。

沿用两套位置：Actor 看过原文，只推进 Actor 接收位置；未触发 Controller 时维护覆盖位置
不动。下一次 Controller 仍看到完整待处理批次。pending_maintenance_events 与
CONTROL_DEFERRED 明确记录维护延迟。这里“覆盖”指已呈现给 Controller，不证明认知吸收正确。

WORKSPACE_SIMPLE 与 MILAI_RWC 使用完全相同的参数、生命周期、模型调用合同和结束规则。
RWC 的一次 Controller 仍能修订依据、选择材料并安排下一步；本轮没有修改两份特殊/普通政策正文。
H_ONCE 和 OM 不接入 RWC 调度。没有增加 Observer/Reflector/Curator 维护链。

原生入口增加 `--control-feedback-batch-size`；实际值写入 configuration.json。
检查点绑定该配置，可信旧 v0.2/v0.3 检查点按原批量1迁移；同一检查点不隐式切换调度。
没有修改公开保存恢复接口、压缩载荷、CAS 或大对象容量。

## 验证及其边界

先单独验证结束路径：45项原有及新增邻近用例通过；之后加入调度改动，最终合并检查为
**72 passed，6.11秒**。中间一次失败是原测试仍把显式回读的维护原因断言为 feedback；
新版有独立 recall 原因，修正断言后通过。该变化没有改变回读的材料或次数。

```bash
uv run pytest -q tests/unit/test_controlled_workspace.py \
  tests/unit/test_hiagent_provider.py tests/unit/test_workspace_native_wave.py
uv run milai-lab-check-boundary
uv run ruff check src tests tools
uv run mypy src/milai_lab
uv build
```

边界、全目录 lint、45个源文件类型检查及 sdist/wheel 构建均通过。测试包括：草稿复核
无变化/不可用、真实新反馈使草稿失效、末次摘要让出 Actor、回读与结束预算、未知调用停止；
两臂批量反馈连续性、外部反馈/段边界/回读提前维护，以及适配器传参、账务和交付状态。
仅检查受影响的本地恢复配置；没有重跑公开 SDK/服务恢复矩阵。

本轮遵循聚焦共享循环的范围，未再次运行约68分钟的全量回归。上一轮 **4578 passed、1 skipped**
只属于原版本，不能写成当前源码的全量结果。本轮也没有运行真实模型、原生 verifier、
新的对照矩阵或 Reflector 长历史实验。

固定历史输出回放独立使用 batch=1，因此只定位结束改动：模型回调返回已保存响应，
终端回调只读取已保存回执，历史命令从不执行。

| 回放 | 结果 | 可以得出的结论 |
| --- | --- | --- |
| RWC | 消费原第1–13次响应、4份已有业务结果，原草稿直接提交，UNREVIEWED。 | 已有草稿不再被末次可选 Controller 阻断。 |
| SIMPLE | 消费原第1–13次响应、5份已有业务结果；第14位置请求 closing=true 的 Actor，原日志此处只有 summary，回放主动停止。 | 保留了结束 Actor 机会；没有历史答案，不能推断它成功交付或任务质量。 |

回放输入已冻结模型输出，不能证明新提示下模型会保持同样轨迹。没有新 token、延迟、费用
或成功率测量，不能把回放中少消费一条历史响应写成真实效率收益。批量用例证明维护结果仍会
到达 Actor 并改变选材输入，尚未证明这种介入减少了实际求解工作。

原始证据位于：

- 历史轨迹：`/cra/memory/mx_memory/evidence/memory-usability-20260914-2vnovnhb/native-three-arms/host/`。
- 本轮回放脚本、输入散列、事件与结果：`/cra/memory/mx_memory/evidence/memory-delivery-scheduling-20260915-mq55akck/`。

之后在明确的新执行范围内，优先选择一个明确配置、一个已有可运行任务，开展 SIMPLE/RWC
同结构比较。配置共同固定批量与复核参数，不要求先完成 batch=1/3 × review=0/1 的参数矩阵。
分别记录实际交付、原生任务质量、完整成本与维护触发原因，再从现有轨迹判断工作区怎样影响
后续选材或行动。两臂共同改善先归于共享运行改进；单一批量配置不能建立批量参数的净因果收益。
出现更多 final 不等于任务成功率提高，维护/卡片/回读次数也不代替政策增量证据。
无自然使用机会时如实记录；没有可观察问题就不继续改结束路径。本轮没有新开模型实验。
