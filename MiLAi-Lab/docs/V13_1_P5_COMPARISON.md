# v13.1 生命周期比较的代码与输入边界

完整规划继续 ACTIVE，Product NO_GO。现有六例是已曝光的单一预约／标签工作流开发故事；重复方法与节奏不会增加独立场景数，不能替代 12 条新 Pilot-L 或两个实质不同工作流各至少 30 个正式基础任务。

[代码核验](../data/manifests/v13-1-p5-comparison-source-acceptance.json)记录 207 文件闭包 `c0c3896ffab51634c58f47fcf35a0e9d348fa9d858c305e675cdf4db7b7b2878`。比较器为 opt-in，复用已有真实业务工具、授权保护、journal、Source 捕获、Store 和进程恢复；保持完整合法当前线程，以最新 Human 选择检索问题。代码检查通过不代表模型质量通过。目前比较模型运行 NOT_RUN。

Mem0 的手动 UPDATE 必须持久保存原提案和唯一同 owner 目标，调用真实公开 `Memory.update(text=...)`，再核对同 owner 的 snapshot/get/history。只有正文改变为原请求内容，且新增实际 UPDATE 历史的 old/new 正文匹配，才返回 committed UPDATE 并允许 W3。无改变为 no_change；无法核对为 unknown，保留第一次错误，不自动重试。该扩展不替代 pinned ADD-only 抽取算法，也不声称通用 CAS 或跨 Store 原子提交。

最初的比较器检查保留首次失败，后续受影响检查 125 项、有效 reader 检查 15 项通过。原生读回修订又通过 6 项针对性检查，使用真实已安装 Mem0 2.1.0、SQLite/Qdrant 持久资源与 MockHTTP，并验证全部内部 embedding 已计费到临时测试账本。并未进行真实模型调用或改写原连续账本；constructor、原生抽取／排序和语义效果仍需实际运行验证。

[开发配置](../data/manifests/v13-1-p5-comparison-development-candidates.json)声明四主臂 B2、B6、Mem0-TraceEqual、Field-grounded 的相同原始观察和保护。matched 与原生维护节奏分表；后者在完成回答后形成的后端不能冒称经历 W2/W3。非 field 的 matched W2 在持久 Source/PREPARED 后、形成前；W3 必须是实际持久材料 UPDATE。原文索引 revision 与语义记忆 UPDATE 的机制差异会披露。

E-L 目前只能关闭已核对有限操作字段的持久／交付视图，仍检查同一原提案并保留正文、来源、scope、历史和 revision。这不是独立通用自动操作事实投影器的消融，也不是 Ref-only。另列的 Mem0 手动更新扩展不能与原生 ADD-only 主臂混报。

每个当前公开消息最多共享 12 次生成，包括 reader、writer 和原生内部维护；恢复沿用同一持久 admission。所有真实生成、embedding、失败和附加查询写入原连续账本，模型调用总并发 1。Root 持有故障调度和离线评分；Host、writer 不接收故障标签、gold、隐藏 world 或未来问题。首次失败、未到达窗口、超限和 NOT_RUN 均保留。

另一次公开问答准备的零调用检查发现官方历史可能从 assistant 开始、以 user 结束；默认闭合回合接口不能用于伪造结尾。该准备失败已完整保留，并要求单独添加 opt-in 静态归档适配后重新冻结代码。它尚未产生模型费用，也未改变旧的实际结果。
