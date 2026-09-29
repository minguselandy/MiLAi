# 历史代码与复现入口

代码保留不代表研究路线恢复。v12 只整理职责、依赖和工程检查，语义实验继续暂停。
历史结果使用报告中的 method/execution commit、锁和原始输入复现；当前 main 的兼容导入
不承诺恢复所有旧构造参数或序列化 Python 对象。

| 保留内容 | 查阅入口与使用边界 |
|---|---|
| 旧 M1、ODR、freshness projection | `methods/milai_m1`、`on_demand_reconstruction`、`freshness_projection`；保留方法实现和原锁，不因迁移 Provider 自动启用 |
| A3/A4/A5 与长期检验 | [v21](MILAI_SER_V21_FINAL_RESULTS_20260927.md)、[v23](MILAI_SER_V23_RESULTS_20260927.md)；按各自证据解释收益 |
| formation/reconciliation | [v24 R2](MILAI_LIFECYCLE_V24_RECONCILIATION_R2_RESULTS_20260927.md)；停止的提示路线不因文件存在而恢复 |
| 应用持久化与恢复 | [v25](MILAI_APPLICATION_V25_RESULTS_20260927.md)；保留错误动作和未完成状态 |
| 外部记忆系统比较 | [v26](MILAI_EXTERNAL_MEMORY_V26_RESULTS_20260927.md)；原 SDK 和失败不能被新适配变体覆盖 |
| 当前最近实验报告 | [v10 总体报告](MILAI_REPAIR_V10_OVERALL_EXPERIMENT_REPORT_20260929.md)、[R2 暂停详报](MILAI_REPAIR_V10_R2_PAUSE_RESULTS_20260929.md)；错误正文真实持久化的失败保持 |
| 前次结构整理及仓库合并 | [架构记录](ARCHITECTURE_REFACTOR_20260929.md)、[合并记录](GITHUB_MERGE_AND_STRUCTURE_20260929.md) |
| 旧操作指令 | [AGENTS 原字节快照](agent-history/AGENTS_PRE_V12_20260929.md)；相对链接按原 Lab 根目录解释 |

全部历史结果导航见[结果索引](RESULTS_INDEX.md)。Root 原 checkout、旧工作树、未跟踪草稿、
元数据、私密运行记录和连续账本均保留；未冻结草稿不作为执行协议发布。
当前迁移位置和已验证范围见[v12 执行记录](CODE_ARCHITECTURE_V12_EXECUTION.md)。
