# v3 P2：空库形成、范围与跨会话使用

状态：执行协议；真实运行 `NOT_RUN`。方法提交和执行 freeze 必须在 P1 验收及源码发布后记录。
执行依据为用户确认的 [v3计划](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v3.0.md)及
[P0/P1合同](MILAI_NEXT_DEVELOPMENT_V3_P0_PROTOCOL_20260928.md)，不能以本文件替代实际源码检查。

## 输入和顺序

[输入目录](../data/diagnostics/next-development-v3-p2-formation-r1/)包含一份共同配置、六份脚本、
Root 离线 rubric 和唯一执行顺序。运行器只读取配置及选中脚本，不能读取 rubric/执行评分。
六脚本是新构造的开发诊断；不称为原生 benchmark、独立确认或真实 unseen 用户。

| 脚本 | 回合 | 核查重点 | 后续查询 R | 臂顺序 |
| --- | ---: | --- | ---: | --- |
| field_plan | 2 | 明确长期安排及完整复用 | 1 | B0、B1、C |
| editorial_revision | 3 | 自然形成后仅改一个约束，保持其他条件 | 1 | B1、C、B0 |
| independent_note | 3 | 新独立事项与原事项共同保留 | 1 | C、B0、B1 |
| quotation | 2 | 引用话语不成为用户采纳的长期偏好 | 1 | B0、B1、C |
| temporary | 2 | 仅本次格式不泄漏到后续会话 | 1 | B1、C、B0 |
| read_only | 3 | 正确已有记录的只读复用，无强制新写 | 2 | C、B0、B1 |

共 18 个隔离 job、每臂 15 条公开消息、总计 45 条。每个 job 从空普通记忆与空业务世界开始，
同一脚本每条消息使用新的 session/checkpoint；跨会话只能用该臂实际持久的普通记忆。
运行器可保留审计轨迹，但不能把旧聊天、source bank、read_history、旁路摘要或评分输入交给 Host。
三臂共同提供当前 owner 普通记录和实际 ID，按小 bank 全读；不检验大规模检索选择效果。

Root 按 JSON 顺序串行、每 job 一个新进程执行 phase 0；run/arm/owner 命名空间、Store、checkpoint、
SQLite 业务世界相互隔离。脚本明确不要求业务动作；保留正常业务工具以检查是否出现无授权动作。
发生语义失败仍保留后续冻结消息；不补种、替换失败样本、抽取最佳重试或重跑至通过。
基础设施错误先保留实际请求和成本，核对根因；任何修复后运行必须新身份并与原尝试分列。

## 方法、服务与冻结

B0 原普通提示，B1 增加一份冻结通用责任说明，C 使用相同 B1 语义并增加有限结果核对。
没有 State/A/U、独立维护模型或自动语义写入。共同实际回执请求副本保证引用 ID 被 Host 看到；
原工具 JSON 和 checkpoint 内容保持。C 最多一次仅记忆纠正，占用当前公开消息原有的 12 次额度，
不重发用户任务、不调用业务工具、不清零计数。无效 no_change 语义判断仍交 Host/离线评分，
程序只核查结构和实际操作支持程度。

Host 沿用 Qwen3.6-35B-A3B-FP8 / 7860，temperature=0、thinking=false、max_tokens=4096、
context=65536；embedding 沿用 bge-m3 / 7861 / 1024 维。真实 HTTP 并发为 1。
配置中继承的 control 字段只为现有装配兼容，不授权 controller 调用或额外生成预算。

Root 执行前将已发布 method commit、实际全部 runtime 源码哈希、锁文件/依赖、提示/schema/工具目录、
全部 9 个输入 JSON 字节、协议、P1检查清单、scorer、顺序、隔离身份、服务只读核实及连续账本起点
绑定到 ignored `artifacts/next-development-v3/p2-formation-r1/execution-freeze.json`。
prepare 是零模型装配；formal freeze 前不得真实运行。该 freeze 及逐 job receipt 的摘要/哈希随结果发布，
原始私密 HTTP、数据库和凭据不上传。

## 五层评分与分母

每个公开消息分别核查：真实输入/HTTP/工具/持久化；当前任务；记忆正文/主体/范围/当前性；
实际成功、零写、部分成功或未完成；后续独立会话的真实回答。工具成功、目标 ID 或自报字段不能代替语义评分。

每臂明确持久要求共 6 次：5 次新事项形成、1 次 editorial 局部修订。独立 key note 作为新事项形成事件，
不要求固定卡数；同一记录正确保留两件独立事项也可满足内容要求。修订须保留另外两项仍有效条件。
负例分别报告引用、临时要求、只读复用；忠实且有明确引用范围的上下文记录不自动算采纳偏好。
无必要的写入、重复和费用另列；readonly 不要求 CREATE 才算成功。

后续使用分母每臂 7 次，原失败仍占分母。闭环按 6 个脚本聚类；明确持久正例另列 4 个脚本，
不把每个调用/消息当独立样本。形成失败后答错仍是完整链失败；形成失败后正确拒答不会补成保存成功。
保存声称以实际正文和回执双重核对，普通语言与 C 字段冲突分列；机械合法 committed 不认证全部要求已满足。

C 激活另列：结构字段实际发出、支持/不支持的引用、unresolved、纠正实际进入、纠正工具目录和每次额外调用。
零纠正不支持纠正有效性的结论；机械接受但错误 no_change 仍判持久要求未完成。超限/无效终答保留未完成及费用。

## 成本和门槛

沿用原始连续账本 `artifacts/ser-v20/budget.json` 的绝对路径，不复制新账本替代原累计。
每个实际 provider request 只计一次；initial/correction 是同一 Host 路径的细分，不能另加逻辑请求数。
形成/维护/使用互斥归属按冻结 rubric：formation→formation，revision/new_note→maintenance，
quotation/temporary/read_only/reuse→use。新独立事项的质量分母属于形成，但费用只归 maintenance 一次。
本 P2 没有恢复阶段，R 固定如表；失败调用、错误、补读、embedding、观察成本及 unknown 单列。
报告 input/output/total tokens、HTTP wall 与整进程 wall/CPU；未测物理 I/O、GPU 小时、货币成本保持 unknown。
未完成生命周期不能计算或宣传“每个成功生命周期成本”。

P3 准入要求 B1 或 C 相对 B0 在至少两个独立脚本中出现可解释的形成/修订/后续使用完整改善，
并且引用、临时、只读负例无明显破坏。B1 持平或更好时优先选择 B1；不为了保留 C 追加措辞。
C 若有额外收益且消耗额外计算，确认前须执行等复核预算 E6，不能提前归因于结果结构。
不满足门槛时 P3/P4 不扩展，P5 按原五项共同条件判断，P6 始终完成；小样本零差异不是等价证明。
