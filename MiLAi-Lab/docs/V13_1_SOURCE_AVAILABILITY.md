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
用户已确认没有额外未曝光官方来源；使用现pin继续其他独立baseline/恢复/开发任务。P6/P7 nominal规模要求
保留未完成，待pilot与来源条件支持后按原规划冻结，不能先宣告300未见已可运行。

新[pilot身份预留](../data/manifests/v13-1-pilot-prospective-selection.json)仅按ID哈希在每任务选20题，未读取问题或评分内容。
其来源组分别为20、12、18；同历史题必须聚类，不能称60个独立来源。所选组件的全部117题均预留为development。
整组件排除后，三个任务还剩250、7、54题；valid与personalized仍不能满足正式各100题。
追加[暴露预留清单](../data/manifests/v13-1-source-exposure-pilot-reservation.json)保留原暴露文件身份，之后正式选择必须取两者并集。
MERIT按三个领域、三种难度各两arc预留全局未用seed65–82；尚未生成arc或执行pilot。
