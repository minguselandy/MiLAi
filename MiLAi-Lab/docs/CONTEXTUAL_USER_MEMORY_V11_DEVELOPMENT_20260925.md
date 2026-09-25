# v11 开发与受限验证记录

用户已授权执行 [v11 Goal](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v11.0_20260925.md) 和[详细设计](MILA_CONTEXTUAL_USER_MEMORY_V11_SPARSE_BASIS_DESIGN_20260925.md)，原起草时的仅文档说明不再限制实施。A 离线诊断已完成，B–D 由同一 Sol xhigh 集成人开发；根控制器只在开发冻结后串行调用模型。v10 已关闭，旧结果、代码身份和费用保持独立。

当前交付状态：固定两个新实例的六臂比较正在运行；另已确认缓存过度失效，修复与最终分析尚未完成。以下按发生顺序保留冻结、失败和诊断记录，不以早期“已实现”描述替代最终工程验收。本次 Git 发布是现有开发与证据的检查点，Goal 保持开启。

## A：旧证据与预先选择规则

基线为 `6722c5ea3363d33e366bfadad6ae4fcd941a6588`；其 47 个已提交源码／配置与 R2 冻结映射一致，R2 两臂的 result、trace、accounting 六份文件 SHA 与已发布清单一致。核对的是基线提交，不把正在修改的工作区误称为旧冻结源码。

[离线诊断清单](../data/manifests/contextual-memory-v11-baseline-diagnosis.json)保留每次截断的输入／输出、上限、当时 Basis 占用、前后可解析工具及连续失败位置。Basis 45 次生成有 18 次截断，均耗尽 4096 completion tokens 且无可执行 JSON；不能从推理文本猜测其拟执行动作。完整 set 提案有 24 个，23 个被接受。8 对相邻字面相同提案包含未提交提案；按实际采用的准确引用／范围及语义字段比较，7 次接受声明与此前相同，其中 2 次带有新交付观察，另 5 次无待确认变化。前者是重核确认机会，后者是 no-op 优化依据，均不是收益证明。

Basis 请求前占用为 40/45，Notes 为 0/26；Basis 投影消息 87–1022 字符，中位数 678。字符数不冒充 token 归因。episode 3 的工作判断是“退款需要审批”，真实执行没有审批提交或退款回执；最终“已提交审批”是无执行依据的声明，不能进一步断言错误由 State 导致。

[选择规则](../data/manifests/contextual-memory-v11-selection-policy.json)在生成新题之前记录：历史 19 份 selection／manifest 元数据均为 base_seed=0；完成开发冻结与旧 arc 一次 A2 接线回归后，按最小未暴露正 base_seed 选择两个原生完整实例，分别采用 A0→A1→A2 与 A2→A1→A0 的顺序。各 arm×arc 独立初态；不因结果换题或改变原生边界。这仍是同一生成器模板上的未暴露实例，不是新任务类型。此时尚未生成、阅读或运行两个新实例。

A 阶段新增模型调用为 0。v11 后续新账本将引用封存 v10 的 122 次生成／1216124 generation tokens／8148 embedding tokens，旧 v9 费用另列；所有失败继续计账。

## B–E：实现冻结与旧 arc 接线回归

B–D 已完成：稀疏 Basis 合同、实际查询与缓存接线、三臂模板，以及从冻结 selection 准备原生 arc 的入口。方法、Basis、JSON-action、配置身份分别为 `contextual-user-memory-v16`、`decision-basis-v2`、`contextual-json-action-v3`、`contextual-task-v11`；写入、材料视图和操作协议未无差别升级。48 个运行源码／配置文件的冻结映射 SHA 为 `3cefb731f5379b2ea7ab1d5ce1725ca1a226c74228ab3f8709190a5257d913e9`，完整文件映射与准备身份见[开发清单](../data/manifests/contextual-memory-v11-development.json)。

受影响六个测试文件共 94 项通过，Ruff 和 mypy 的窄检查通过；部署 vLLM 0.27.1／xgrammar 0.2.3 的 15 个 decoder 探针及三份固定材料投影比较均已完成，后两者没有模型调用。投影比较仅是固定合同的本地 token 估算，不能充当原生收益。旧已暴露 arc 的 A2 接线回归已启动、仍在运行，尚无终结评分；两个未见 arc 的三臂比较尚未开始。此时 Goal 保持 `IMPLEMENTED_PENDING_SMALL_VALIDATION`，不预述效果或重置费用。

## E：首次失败与公共维护说明修复

上述首次回归随后终止于 episode 3：前 3 个 episode 原生 checker 通过，5 个公开回合完成，第 6 个回合返回 `maintenance_pending`，最后一个 episode 未运行。因此整条 arc 不评分，不能称 3/5 或完整通过。[首次尝试清单](../data/manifests/contextual-memory-v11-e-first-attempt.json)保留身份、终止点、费用和制品 hash。共 33 次生成、344195 generation tokens、1914 embedding tokens；11 次截断费用全部计入，截断请求没有部分 dispatch。Basis 请求占用 9/33、动作占用 5/22，2 次激活、1 次 gap 解决、1 次显式清除、1 次 review acknowledgement；没有实际 search 或自动版本通知。

失败点已经成功保存待回复事项，且没有未审阅的必需材料、未持久化的必需事项或未决执行。Host 将未来客户回复列入本轮记忆维护的 `remaining`。程序按它的声明返回 pending，没有保存或执行接线故障。共享提示及 finish 工具原先均用“unfinished matters”，未明确本轮记忆维护与未来业务等待的区别。修复仅澄清这两处说明，不自动推断 reason、不把 pending 改判为 processed，也不改变 schema、方法序列化或业务权限。

相关维护／Host 48 项测试及两源文件的 Ruff、mypy 通过。[新冻结清单](../data/manifests/contextual-memory-v11-final-freeze.json)记录 48 文件映射 `2a95dcd0fde0e90a4eff053b5875d0f6d07a3ec61961fd158201c312102d1cf4`；METHOD v16、ACTION v3 与配置字节保持兼容，前后源码身份分别记录。

一次[定向恢复](../data/manifests/contextual-memory-v11-e-recovery.json)复制实际持久状态及业务世界，在原回合剩余的 1 次响应内仅提供 finish_turn 的维护判定；模型仍重复原 pending。新增 1 次生成、8669 tokens，没有新业务动作，世界不变，episode 4 仍未运行。这证明恢复未重执行业务，不能证明措辞修复有效。输入以旧 assistant 的 pending 答案结尾；重复可能受此影响，不能仅凭一次续写判定原因。

下一步限定为一次干净后缀复核：使用原 episode 2 结束的实际持久记忆与世界，按原消息边界运行 episode 3，完成后再运行 episode 4。此前完整尝试与恢复失败保持原样；该后缀只提供混合源码下的接线证据，不作为单一源码五 episode 成绩。之后按预定规则进入两个新实例的三臂比较，不继续按旧题分数调整提示。

这次[干净后缀](../data/manifests/contextual-memory-v11-e-suffix.json)随后完成：episode 3 与 4 的 Host／维护均 complete，原生 checker 分别 false／true。新增 20 次生成、226865 generation tokens、36 embedding tokens，9 次截断、1 次写入拒绝均保留；恢复副本复用了 embedding cache，其费用不能当作新 arm 的冷启动费用。第一次完整尝试、一次 finish 恢复和这次后缀累计 54 次生成、579729 generation tokens、1950 embedding tokens，unknown=0、Judge=0。措辞修复后新会话可以正常终结，但单次接线证据不证明维护普遍可靠。

## F：未暴露实例正式选择

上述后缀终结后执行既有选择规则，冻结[实际选择回执](../data/manifests/contextual-memory-v11-f-selection.json)：`arc1-000`（base_seed 1、arc_seed 10000、5 episodes／6 messages）与 `arc2-000`（base_seed 2、arc_seed 20000、5 episodes／7 messages），各有 2 个 dependent episode。选择回执记录原 arc／world、选择清单及最终开发冻结的 hash；没有替换、删减或重排原题。三臂顺序分别 A0→A1→A2 与 A2→A1→A0，各 arm×arc 使用独立初始世界、空记忆及新 embedding cache。它们是同一原生生成器模板上的未暴露实例，不是新任务类型。

六个准备身份见[准备清单](../data/manifests/contextual-memory-v11-f-prepared.json)。独立于模型轨迹的[原生变化机会清单](../data/manifests/contextual-memory-v11-native-opportunities.json)记录 13 条消息中 8 次同事项变化；这些变化均跨原生 episode，不能自动算作同一个未解决 Basis 的重核机会。原题没有 Basis-needed 或版本通知必要性的标签，相应真值保持 unknown，不从 Host 自写 gap 构造 precision／recall。

## 待修复：缓存过度失效

F 运行期间的只读源码核对确认两处不必要的失效：Host search 缓存键含 `recheck_reasons`，确认已经交付的通知后，即使有效 query 和材料未变，也因 reasons 清空而失配；`apply_sidecar` 又在 gap／事项／状态字段改变时无条件清缓存，即使本次显式 query 仍相同。真实版本、来源发布及删除另有材料变化标记和失效路径。该问题违反设计中的等值确认和实际查询依赖要求，是尚未修复的工程问题；尚不能声称它在真实 F 轨迹中造成了费用增加。

为保留六臂一致身份，当前运行源码不在比较途中修改。后续定向修复应覆盖同值确认不重检索、显式 query 不变时无关状态变化不重检索，以及真实 query／材料变化仍失效；同时检查下层 expansion／latest_search 的依赖。修复另记身份，当前 F 结果不能冒充修复后版本的未见比较，不为此自动扩题。

本次提交仅涉及 Lab 源码、文档和紧凑清单；Product API、Schema、权限及 Canonical 行为未改，没有新增跨包依赖。维护说明修复的 48 项窄测、Ruff 和 mypy 已通过；此次状态文档更新不重复模型调用、全量测试或构建。原始世界、模型输出、运行日志和缓存继续留在 ignored artifacts。此前已发布检查点为 `27fddfc20535d87d76959247478f23823425c328`；本次发布的精确 Git 身份由提交记录和远端核对给出。
