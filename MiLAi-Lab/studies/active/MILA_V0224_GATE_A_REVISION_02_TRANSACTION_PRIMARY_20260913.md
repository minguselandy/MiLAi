---
revision: V0224_GATE_A_EXECUTION_R02
status: DEV_IMPLEMENTATION_NOT_ADMITTED
model_allocation: 0
http_allocation: 0
---

# Gate A 执行修订 R02：事务清理首因与单一性能候选

本修订依据 V0224 总 Goal §9.2/9.3 的通用错误恢复修复权限，由用户指定的 subagent 进行代理技术审查。原 V0223 v0.1、K0/K1 合同、源码、夹具及失败记录不修改。此次不是 Gate A PASS。

## 证据与必要差异

[动态负控审查](/cra/memory/mx_memory/evidence/v0224/20260913-a-k2-v1/dynamic-negative-boundary-review.json)复现原 `v0221_http_batch.transaction` 的缺口：body 失败后 rollback 或 close 再失败，清理异常覆盖 body 首因。44 个局部测试中 6 个明确刻画此缺口，不能算作 A2 保证通过。

新增独立 `v0223_transaction_primary_fix.py` 实现通用清理修正，原文件保持冻结。业务或 commit 异常为已知 primary 时，rollback/close 异常作为附记保留，原 primary 对象仍向外抛出；无 primary 时清理异常仍使操作失败。不能因异常整理改变 SQL 操作顺序、宣称未知 rollback 成功、抹掉实际已提交事实，或恢复停止实例的发送资格。cleanup-only 可能发生在 commit 之后，必须以独立状态回读记录事实，不许重发。

这是有意的正确性差异，不称为原/修复 first-cause 等价。原缺口反例保留，新保证需要单独回归。

## 两臂与候选边界

K2 两臂均采用同一修正事务基线：

- `k2-base`：corrected baseline，原 verify_tree。
- `k2-edit`：corrected baseline + 唯一 verify_tree 只读遍历消除整树 defensive deepcopy 候选。

两臂相同源码集合、输入/历史负担、新等长 ID 与动态初态，唯一区别是启用只读遍历候选。共享事务修正不是第二个性能候选，不借此取消其他等价检查。

候选公共 `read_json` 不变；严格完整 JSON、manifest 校验与首因顺序、全部直接依赖读取、冲突/路径检查、parsed/引用计数和首读/关闭复验保留。不暴露可变缓存对象。深层 JSON 的原 deepcopy 递归拒绝也需保留：保守快路径资格和小型递归验证仅决定是否执行原 deepcopy，绝不设置新的业务深度拒绝线；不能证明等价时不准入。额外扫描/验证成本全部计入真实配对。

## 继承的全部门与资源

V0223 v0.1 的 K0–K4、完整矩阵和零模型/零 HTTP 边界继续成立；本修订仅将上述明确首因修复列为 A1 的有意版本差异，其余接受/拒绝、账务、权限、效果及动态负控要求不变。

- 单一性能候选；一次基线 U 与一次候选 U 55-scope 前缀，各外层≤3600秒、内部原60秒Session不变，无重试/择优。
- 当前工程 terminal、全 A1/A2 负控、全16+80参考/24效果与实际16+24冷进程、父finish/gate和独立World仍必需。
- 每参考准入并集≤18秒、完整Session≤60秒；链及归属父准入≤90秒、完整链≤300秒；P3≤900/1800秒、P4≤3600/7200秒。
- K3 seal/init≤300秒、完整参考准备≤3600秒；所有准备/报告/退出计入所属生命周期；不改变历史费用未知状态。
- 新 binding/源码/输入/审查 hash；首次非预期失败停止该实例，后续 NOT_RUN，旧结果不续填。

## 影响分析与下一步

已完成的 K1 仍只证明原版本成本与测量方法；不将其记成 R02 当前性能或工程 PASS。修正事务正常路径也有新增控制成本，必须纳入两臂测量。两臂新库存/当前状态对比、局部差分与动态负控完成并独立审查后，才冻结具体 K2 pair 合同。K3 使用当前修订重新完成完整验收，工程检查按总 Goal/AGENTS 要求在候选冻结后执行。

当前没有创建 K2 fixture、启动 K2 计时或释放 B–E。主 Goal 保持进行中；Memory 有效分母0。
