---
status: ACTIVE
scope: RESEARCH_PROTOTYPE
parent: MILAI_LONG_HORIZON_EXECUTION_GOAL.md
---

# v20：Selective Evidence Rebase

本阶段执行总计划P0–P4，为[长程Goal](MILAI_LONG_HORIZON_EXECUTION_GOAL.md)的第一阶段，不替代其余范围。A3当前证据交付已成立，先检验旧assistant结论是否是第一个尚未处理的污染来源。

## 实现合同

从实际生成请求R的证据快照建立response/message identity到exact(namespace,id,revision)的关系，记录的是机械request风险，不做词级语义因果推断。A3投影后实际交付X@2，新的回复必须绑定X@2，不能误记为历史search的X@1。

在下一次request副本中，仅当可绑定的ordinary assistant text对应snapshot含SUPERSEDED/DELETED时替换为通用历史回复marker；保留role、位置与已执行tool-call JSON。不按内容、金额、温度、case ID或expected值识别旧结论；相同文本的不同response也需靠真实身份区分。原checkpoint、Store及历史不改。

事件包含response_id、generating_request_id、原正文hash、投影hash、stale_refs/current_refs和reason；实际请求中的原文本与marker需可核对。无第二模型、持续语义State、强制reconstruction或业务真值gate。UNKNOWN不伪造为current，也不靠猜测删除无法绑定的文本。

## 首轮范围与判定

先用同一三个原fixture，各新独立run/namespace，冻结源码和判定后串行运行。A4沿用A3 schema、authority、Host/embedding和精确刷新策略。Changed要求X@2真实交付、旧正文与stale-derived文本处理后实际动作8；retained要求真实取得X@2且动作8；irrelevant要求primary正确、不错误扰动current内容，并单列不必要demotion与Y读取。

如果失败，按总计划§37逐项检查当前实际wire，选择一个最可区分的新对照。不是自动判停，也不事后修改rubric或注入正确值。正确性成立后再扩展非温度categorical、boolean、deleted、multi-revision和assistant-only stale；至少一组非温度通过只是v20最低要求，全部泛化类型仍属于总Goal后续范围。

## 验证与交付

必要窄验证覆盖lineage恢复、不同response同文、refresh后快照、CURRENT/UNKNOWN保留、工具调用不删、checkpoint/restart及真实Provider投影。沿用旧schema不做复制式decoder probe；包装变化完成后只做必要build。保留每次失败与费用，新的账本history引用旧repair的45次/41457tokens/808embeddingtokens。

- [x] P0封存，见[reference](../data/manifests/milai-ser-v20-reference.json)。
- [x] P1/P2最小实现与29条受影响窄检查。
- [x] P3原三例3/3通过，完成[逐请求核对和反思](MILAI_SER_V20_P3_RESULTS_20260927.md)。
- [x] P4非温度控制与反例5/5通过，见[P4结果及中间表述缺陷](MILAI_SER_V20_P4_RESULTS_20260927.md)。
- [x] P0–P4结果、连续费用、复现与阶段判定；合计41生成/36834tokens/589embeddingtokens，8个开发控制通过。
- [ ] 源码交付与累计包装检查：sdist补入diagnostics纳入P5首次修改及新锁，之后做一次必要build；保留P4真实运行身份。总Goal继续。
