# LSA P1 R1：控制 schema 与写入契约不一致

状态：`HALTED_EXECUTION_VALIDITY_FAILURE`。已发布源码
`031acc7ae63353ac00ef237755b7b028ef8ae989` 的首次真实接线运行，在前三条消息后
停止后续调用。不是完整轨迹通过，也不是 LSA 语义无效的证据。

## 冻结与实际范围

[原 P1 协议](../data/manifests/local-state-attention-p1-protocol.json)预先固定两条轨迹、
12 条公开消息和独立 rubric。实际入口 prepare 生成源码/config/输入/依赖清单；
配置、模型和脚本未在运行中修改。串行执行交错轨迹 phase 0，未执行其 phase 1，
部分失败轨迹全部未执行。后九条保留为 `NOT_RUN_AFTER_EXECUTION_VALIDITY_FAILURE`，
不删除分母、不替换样本；两条完整轨迹均未通过验收。

ignored 证据目录：`artifacts/local-state-attention/p1-r1/`。其中 execution-freeze、
每 run 的 run_manifest/prepared、trace、phase result、checkpoint、halt-store-snapshot、
halt-review 和前后账本保留。两个 namespace 在调用前只读核对为空。

## Observed / Expected / 首个断点

Expected：新事件进入独立控制调用，合法新建编辑实际写入 Store，后台修订能够影响持续
State；读取选择可为空，但不能用业务事实正文冒充 State ID。

Observed：三次控制 HTTP 均为 200、`finish_reason=stop`；输出 JSON 满足实际发送的
schema。三份新建编辑均包含 `id:null`、content、evidence，却没有 title。
schema 的 required 只有 id/content，而 bank 新建分支要求非空 title，因而三份编辑
均 `skipped_invalid_edit`。真实 Store 为 0 State、3 个 pending 事件；第二、三次
focus 还包含事实文本，程序过滤后为空。没有业务动作、embedding 或丢失 pending。

实际因果链：用户事件 → 控制 HTTP → schema 合法但无法新建的编辑 → bank 拒绝 →
保留 pending 并交付原观察 → Host 回答。Host 三条回答都完成了当轮要求（3/3），
但这来自原历史和 pending 的交付，不能证明持久 State 已形成。

H1（已确认）：发送 schema 与本地写入条件不一致，造成确定性接口拒绝。
H2（独立待核）：字段契约未充分进入模型可见文本，模型把当前任务当成回答任务，
生成回复式正文并把 focus 当成事实列表。H2 也可能导致修复标题后仍无法正确分事项或
选择，因此不能把 H1 修复等同语义通过。
HTTP、decoder 结构输出和 Store 连接故障不符合已取得的证据；失败不是服务参数问题。

## 最小修复与下一实验

由同一 Sol 仅对齐通用控制契约：新建标题的 schema 要求与 bank 一致；更新仍允许
省略保持字段；模型可见文本说明编辑对象、current_task 用途和 focus 的 ID/本批短引用
规则。对非标识符 focus 的约束不能编码样本事实。先用零模型回归检查已观察到的
schema/store 反例及合法新建、更新、no-op；Root 在新源码冻结后按原顺序重新执行两条
完整 development 轨迹。旧样本已暴露，不称 unseen；不拼接 R1 前缀和修复后后缀。

决策：**Continue，修复接口后再判断语义**。不继续在已知不一致的契约上消耗剩余九条，
不扩大到 P2/P3；无需新增平台、提升预算或改变 vLLM。若合法编辑仍遗漏后台事实或错误
分组，按新的首断点单独分析，不能归咎为这次 schema 故障。

## 成本、混杂与限制

| 实际角色 | HTTP 生成次数 | generation tokens | HTTP wall seconds |
| --- | ---: | ---: | ---: |
| state_control | 3 | 2037 | 4.175 |
| task_host | 3 | 3452 | 1.613 |
| 合计 | 6 | 5489 | 5.788 |

embedding 增量 0，unknown usage 0。连续账本由 863/1042729/9617 更新为
**869 generation calls / 1048218 generation tokens / 9617 embedding tokens**；
历史链完整保留。上述为实验费用，开发代理和零模型观察不计入模型 token；Store 观察
另有调用前 4 次 search、停止后 4 次 search，用于核实两组 namespace。
旧 exact-version reads 仍为 107；LSA bank 的机械 Store 读不是 SER exact refresh。

3 个 pending 的完整正文进入 Host，构成有效降级路径，也使当轮回答正确率无法用于
判断 State 收益。没有跨进程恢复、部分失败、长期保持或 U/A 解耦的有效结论。
原型发布时 staged whitespace check 曾提示 `__init__.py` 末尾空行，属于非功能问题；
不将原 tracked diff 检查说成全部 staged 文件均无警告。本次修复可一并移除此空行。
