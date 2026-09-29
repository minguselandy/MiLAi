# v12 S6：writer-policy 编排归属

状态：本地工程检查完成，尚未提交/发布或通过最终远端 CI。源码基线为
`96a6ce17b331c350f44d44d71e2e0205f33aeab3`。语义实验仍暂停。

## 实际断点与选择

`WriterPolicy`、`WRITER_POLICY_INSTRUCTIONS`、`run_writer_policy_turn` 当前位于
应用阶段 runner，而已有 `runners/writer_policy.py` 为使用它们反向导入应用 runner。
竞争解释是 writer-policy 属于业务核心，或它属于独立实验编排。函数实际选择 writer 时机、
工具和 Host 路径，没有定义业务世界，因此将它归于 writer-policy runner，业务核心不重做。

直接搬移会暴露另一条依赖环：writer-policy 从 local-state runner 借用 `_accounting`，
后者又导入应用 runner 的 `run_phase`。该函数只读取 trace 和预算、汇总结果，可按原实现
归于分析层。它与 S4 的 benchmark `trace_costs` 有不同分类和输出合同，不能互相替代。
不用延迟导入隐藏环，也不把所有 runner 之间的合法组装都禁止。

应用 runner 继续负责 phase、公开消息、session progression、资源重开与结果交接。
旧 writer-policy 符号需导出 canonical 对象本身；提示、策略、调用次序和费用公式保持。

## 迁移前冻结

基于上述提交，使用冻结的 `src` 和 `tests` 运行 13 个已有 writer-policy 案例及 14 个
计账合成案例。Root 独立核对 67 个已加载模块和复用的 probe 均来自冻结目录，逐项 SHA
与迁移前清单一致。四策略、自动/显式触发、交错时机、部分提交、容量失败及计账的未知
usage、缺失/损坏 JSON、额外统计键等保留实际结果和错误。仅使用合成 MockHTTP。

公开 fixture：[writer/accounting golden](../data/diagnostics/code-architecture-v12/writer-accounting-golden.json)，
2,100,789 bytes，SHA-256：
`ea42163cad81e391fd1b3bd0d33fc4d91f17181ace48920333abf6ffdbc99a81`。
公开副本与 before 完全相同；这只能证明冻结完成，迁移后等价尚待核对。

## 首轮差异与处理

首轮迁移后的 13 个 writer、14 个 accounting 案例断言通过，但完整记录比较出现 69 处
scalar 差异。定位包括既有 `set[str]` 遍历造成的确认写入顺序，以及被 recorder 捕获的
LangGraph 内部 checkpoint/task ID 与时间。不能把断言通过称为完整字节等价。

保留原 before、after 和失败日志；补充对照固定进程 hash seed、测试时钟与 SDK 所用随机源，
每个案例重置，分别运行冻结旧代码与当前代码。不得改 runtime、排序写入或清洗已捕获字段。
固定 fixture 后，冻结 before、迁移后 after 与公开补充 fixture 全部 **2,101,064 bytes 完全一致**：
[deterministic golden](../data/diagnostics/code-architecture-v12/writer-accounting-deterministic-golden.json)，
SHA-256 `55971b7e1ada6166b5ade302c65dabc99a841ef004b1d8258f9273e57fabbee2`。
Root 独立核对补充 before 的 67 个模块及 helper 来自冻结源，并比较上述三个文件的全部字节。
原 69 处差异最终分类为 42 处确认写入顺序、27 处 SDK 内部 ID/时间；原件均保留。
这证明固定合成输入下的搬移等价，不是新增语义实验结果。

公开精简工程证据见 [S6 evidence](../data/diagnostics/code-architecture-v12/s6-engineering-evidence.json)。

## 结构与行为核对

- `run_writer_policy_turn`、两项策略定义和原 `_accounting` 的 AST 保持；应用 runner 剩余
  `_collect_turn_tail`、`_operator_memory_event`、`run_phase` 的 AST 不变。
- 原 writer/LSA 其余函数不变；另八个源码消费者和已有 writer 测试只更换 import，原断言保留。
- 对业务 world、journal、工具的现成复用改为直接导入 `application` 的 canonical owner。
- [剩余 runner 依赖审查](../data/diagnostics/code-architecture-v12/s6-runner-ownership-review.json)
  保留 53 条 import statement 和归属理由：阶段/资源组装、合法冻结前缀准备、特定 study seed、
  原生 arc 执行仍属实验编排。没有宣称 runner 之间已无依赖。
- writer 与应用/LSA 的三种先导入顺序均检查；旧入口导出相同对象，公共计账 Core 导入只需标准库。

新增架构/身份检查 27 passed；受影响 writer、phase、CLI、消费者检查 41 passed。
13 个改动运行模块的严格类型检查、最终全 Ruff、现有两项边界与验证矩阵检查通过。
五次失败检查记录保留：首次完整对照、三次 Ruff/helper/import 收敛、以及首次差异分类
未包含 SDK 随机字段的证据脚本。修正的是测试固定条件、脚本及格式，没有改运行时行为。

## 打包与安装

离线构建 sdist，再由该 sdist 构建 wheel；13 个改动运行模块的字节与工作树均一致。
Core 安装导入不加载可选 SDK，14 个 accounting 案例通过；Foundation 的 13 个 writer 案例
及全合同回放通过，旧、新入口同一对象。所有已加载 `milai_lab` 模块均来自新安装目录，
仅借用现有缓存的 Foundation 依赖，未下载。

导入检查使用 `-I`；确定性回放使用 `-P -s` 并清理其它 `PYTHON*` 环境，显式保留
`PYTHONHASHSEED=0`。后者不能称为 `-I`；它另行断言实际项目模块的安装来源。
包核对覆盖上述运行文件及 fixture/helper，不宣称随后编辑的结果文档已包含在此构建中。

- sdist SHA-256：`811c04e1964c0d6ac9850b7a5f3e5d277bbf6503dc515bdc6a3de6079fd57553`
- wheel SHA-256：`1ebd83ddc3189a05510cf3b32948490d7baa82fe617eef775ddc38e3e83d72a9`

暂存检查另发现新文件 `trace_accounting.py` 末尾多一空行。仅删除一个 LF，AST 不变；
原 receipt、hash 和构建证据保留。随后仅重建 sdist→wheel 并核对 13 个运行文件字节，
不为格式修改重复行为检查或安装回放。最终构建 SHA：

- sdist：`29a56f91ffb9163175bae91e1c67aa352f31151532c77fac0673522015c1408f`
- wheel：`1ec870094ffa1563b96c81ef65e3ee6620053c7bad8d5d1f88928e698d173125`

上述安装回放属于前一版 wheel；最终版仅复用该行为证据，不声称已重新安装/回放。
S7 的正式 DAG、类型归属、逐项最终验收及远端 CI 仍未完成。
没有真实 Host、embedding、Judge 调用，没有恢复实验或改变费用账本。
