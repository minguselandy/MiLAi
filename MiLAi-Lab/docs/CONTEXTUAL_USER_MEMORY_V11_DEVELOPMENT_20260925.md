# v11 开发与受限验证记录

用户已授权执行 [v11 Goal](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v11.0_20260925.md) 和[详细设计](MILA_CONTEXTUAL_USER_MEMORY_V11_SPARSE_BASIS_DESIGN_20260925.md)，原起草时的仅文档说明不再限制实施。A 离线诊断已完成，B–D 由同一 Sol xhigh 集成人开发；根控制器只在开发冻结后串行调用模型。v10 已关闭，旧结果、代码身份和费用保持独立。

## A：旧证据与预先选择规则

基线为 `6722c5ea3363d33e366bfadad6ae4fcd941a6588`；其 47 个已提交源码／配置与 R2 冻结映射一致，R2 两臂的 result、trace、accounting 六份文件 SHA 与已发布清单一致。核对的是基线提交，不把正在修改的工作区误称为旧冻结源码。

[离线诊断清单](../data/manifests/contextual-memory-v11-baseline-diagnosis.json)保留每次截断的输入／输出、上限、当时 Basis 占用、前后可解析工具及连续失败位置。Basis 45 次生成有 18 次截断，均耗尽 4096 completion tokens 且无可执行 JSON；不能从推理文本猜测其拟执行动作。完整 set 提案有 24 个，23 个被接受。8 对相邻字面相同提案包含未提交提案；按实际采用的准确引用／范围及语义字段比较，7 次接受声明与此前相同，其中 2 次带有新交付观察，另 5 次无待确认变化。前者是重核确认机会，后者是 no-op 优化依据，均不是收益证明。

Basis 请求前占用为 40/45，Notes 为 0/26；Basis 投影消息 87–1022 字符，中位数 678。字符数不冒充 token 归因。episode 3 的工作判断是“退款需要审批”，真实执行没有审批提交或退款回执；最终“已提交审批”是无执行依据的声明，不能进一步断言错误由 State 导致。

[选择规则](../data/manifests/contextual-memory-v11-selection-policy.json)在生成新题之前记录：历史 19 份 selection／manifest 元数据均为 base_seed=0；完成开发冻结与旧 arc 一次 A2 接线回归后，按最小未暴露正 base_seed 选择两个原生完整实例，分别采用 A0→A1→A2 与 A2→A1→A0 的顺序。各 arm×arc 独立初态；不因结果换题或改变原生边界。这仍是同一生成器模板上的未暴露实例，不是新任务类型。此时尚未生成、阅读或运行两个新实例。

A 阶段新增模型调用为 0。v11 后续新账本将引用封存 v10 的 122 次生成／1216124 generation tokens／8148 embedding tokens，旧 v9 费用另列；所有失败继续计账。

## B–E：实现冻结与旧 arc 接线回归

B–D 已完成：稀疏 Basis 合同、实际查询与缓存接线、三臂模板，以及从冻结 selection 准备原生 arc 的入口。方法、Basis、JSON-action、配置身份分别为 `contextual-user-memory-v16`、`decision-basis-v2`、`contextual-json-action-v3`、`contextual-task-v11`；写入、材料视图和操作协议未无差别升级。48 个运行源码／配置文件的冻结映射 SHA 为 `3cefb731f5379b2ea7ab1d5ce1725ca1a226c74228ab3f8709190a5257d913e9`，完整文件映射与准备身份见[开发清单](../data/manifests/contextual-memory-v11-development.json)。

受影响六个测试文件共 94 项通过，Ruff 和 mypy 的窄检查通过；部署 vLLM 0.27.1／xgrammar 0.2.3 的 15 个 decoder 探针及三份固定材料投影比较均已完成，后两者没有模型调用。投影比较仅是固定合同的本地 token 估算，不能充当原生收益。旧已暴露 arc 的 A2 接线回归已启动、仍在运行，尚无终结评分；两个未见 arc 的三臂比较尚未开始。此时 Goal 保持 `IMPLEMENTED_PENDING_SMALL_VALIDATION`，不预述效果或重置费用。
