# v12 代码架构基线

基线：`cca2fd9d1cb4614c44a40ddc0458325d959e6740`，2026-09-29。
用户已授权完整执行 v12.0，代码组织 Goal 为 active；语义实验保持暂停，Product NO_GO。
工作树为 `MiLAi-worktrees/code-architecture-v12-20260929`，原 checkout 和全部草稿保留。

## 权威输入与保留

- [原计划](MILAI_CODE_ORGANIZATION_BOUNDARY_PLAN_20260929_v12.0.md)按原字节复制，SHA256：`bf9e748685fcdd7e449a57b50e83d226bce70da5caecff69854642e4c2301db4`。
- [原 AGENTS 快照](agent-history/AGENTS_PRE_V12_20260929.md)按原字节保存，SHA256：`2f1c8a37785d2f686b3a68413a8df8342d5f4a320c7a95191bec00ca88df6609`；其中相对链接按原 Lab 根目录解释。
- 当前 [AGENTS](../AGENTS.md)只承载本轮约束和历史入口，原授权证据未删除。
- 连续账本 SHA256：`7f0e54548dcbebe1325ebbac4a0fc4441f20efc949cd16be4084c3f9b8aeda43`；不改变任何历史实验结果。

## 静态盘点

[机器可读 import map](../data/manifests/code-architecture-v12-import-map.json)包含全部170个可导入包源文件的
SHA、包归属、候选 canonical owner、兼容入口候选、import/reverse graph、动态导入位置、mypy exclude 和验证矩阵。
共1,606条静态导入记录，其中495条为内部导入；包含函数内和 TYPE_CHECKING 导入，不冒充运行时调用图。

| 关系 | AST 记录数 | 初步判断 |
|---|---:|---|
| baseline → runner | 4 | 共享 benchmark 直接使用外部 SDK runtime；应归 integrations |
| provider → method | 7 | chat bridge 直接拥有具体研究方法协议/类型分支；需要通用注入接口 |
| runner → runner | 70 | 包含合法组合及应提取公共生命周期；逐边判断，不一刀切 |
| application → baseline | 2 | recovery 的类型关联，需核查下层公开接口归属 |
| 动态导入调用点 | 7 | 单列核查；不通过动态导入隐藏边界 |

首个结构断点不是文件行数，而是消费者为复用低层能力被迫依赖高层模块。
竞争解释A：这些依赖反映真正的实验编排，迁移只会制造包装层；解释B：实现已是通用服务，
只是 owner 错位。以实际输入/输出、状态归属和调用者决定；保留编排，提取通用服务。
Provider 阶段另以冻结 wire/容量/回执对照阻止研究策略顺序或默认行为漂移。

## 验收基线与未完成项

当前已有 #74 的31项局部检查及 `97efe0c` Fast CI，只证明旧架构基线。
它们不能替代 v12 新边界、Memory core、外部集成、Provider 和 source identity 的验收。
本轮必须在受影响实现迁移前冻结第38节各项 golden，然后逐阶段完成相关检查和打包导入。

阶段/逐项证据见[执行记录](CODE_ARCHITECTURE_V12_EXECUTION.md)与
[验收矩阵](../data/manifests/code-architecture-v12-acceptance.json)。未证实的项保持 pending。
