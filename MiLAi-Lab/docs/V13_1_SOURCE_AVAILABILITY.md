# v13.1 未曝光来源容量核查

状态：NOMINAL_UNSEEN_FORMAL_POOL_INSUFFICIENT；完整目标ACTIVE，正式集尚未选择。

[机器核查](../data/manifests/v13-1-memsyco-source-availability.json)重新对当前官方三任务950行
按非空metadata.source_id或完整dialogue的canonical SHA256做传递闭包。任何已暴露/旧reserved
case、原source、完整历史hash或旧来源组关联的整组都排除。60个旧MemSyco group标签全部
通过旧registry的代表元数据解析，不依赖重造其字符串公式。

| 任务 | 官方行/来源组 | 排除后行/来源组（新pilot前） | 原规划正式100题是否可得 |
|---|---|---|---|
| contextual_scope_control | 300/300 | 270/270 | 可得，仍须pilot后冻结 |
| valid_memory_selection | 350/45 | 63/15 | 不足 |
| personalized_memory_use | 300/121 | 95/79 | 不足 |

实际git ls-remote核对官方HEAD仍是fd1f0f0270f35467aace1f9c0bf6a8bfb9b87221。
只输出ID/source/hash分组元数据，不显示问题、memory、evaluation或gold；没有将正式题送给Host。
没有删除暴露排除条件、偷换任务、把重复问题计作新来源组或悄悄缩小完整目标。
已请求额外未曝光官方来源信息；其他独立baseline/恢复/开发任务继续。P6/P7 nominal规模要求
保留未完成，待pilot与来源条件支持后按原规划冻结，不能先宣告300未见已可运行。
