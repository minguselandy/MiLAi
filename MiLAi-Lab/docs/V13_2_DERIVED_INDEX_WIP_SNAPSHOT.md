# 未验证派生索引存储WIP快照

本分支保存用户要求暂停时的两个未验证源码改动，基于主分支暂停提交`48b93b3`。仅作为可恢复开发快照，不是验收实现，也没有测得加速。

`memory_derived_index_storage=owner_bank_v1`草稿拟将派生raw_index放在owner/bank绑定的独立命名空间，使用原MemoryService的公开Store。默认仍为bank_prefix；旧inline索引不迁移或删除。此处binding、pending/complete、fallback、legacy行为及性能均尚未完成验证，具体代码可能需要修正。

精确两文件hash及原始patch hash见[暂停机器记录](../data/manifests/v13-2-pause-summary-20261001.json)。没有针对这份改动完成验收测试、实际模型调用或性能比较。主实验执行分支不包含这两个改动。

用户随后要求GitHub提交后继续实验，并要求失败时检索相关设计、反思改进，同时保留原设计方向、通用性及泛化性。提交完成前继续HOLD；恢复后的开发另留新提交与执行身份，不改写本次未验证快照。
