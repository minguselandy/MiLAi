# Host 快照 R2：正确性反例未通过

状态：`COMPLETE_DIAGNOSTIC_CANDIDATE_NOT_ADMITTED`。按
[冻结协议](../data/manifests/local-state-attention-host-snapshot-r2-protocol.json)
完成三断点 × 两视图的六次首响应；[精简结果](../data/manifests/local-state-attention-host-snapshot-r2-results.json)
保留全部分类、费用与证据哈希。执行提交为 `346adc052e1a47e8572369861cd1ad1aeb99eb2f`，
实现仍为 `83b707edee01435db454493ee792ca73f9de531f`。没有控制器、embedding、工具执行或 Store 访问。

| 冻结断点 | 无说明 | 原 R1 时点/身份说明 | 验收 |
| --- | --- | --- | --- |
| 旧 State3，真实 initial2 与两次独立 +1 均可见 | 提出 memory update3 | 提出 memory update3 | 应有计划4未恢复 |
| 实际 State4，历史中已发生错误 memory write5 | 直接称计划已改为5 | 直接称计划已改为5 | 未区分正确计划与实际错误写入 |
| 旧计划4，但实际业务回执已预约/标记5 | 报告5与真实预约ID | 报告5与真实预约ID | 数量/ID保真；两者将回执目的地 S-2 写成 storage S-2，严格完整事实仍不通过 |

最后一组没有虚构“已执行4”，也没有再次预约，这是有界的正面观察；不把它升级为完全
准确的业务报告或错误动作已修复。六个输出均保留，不续跑中间 memory 提案来寻找较好结果。
旧 State 替换和第一组额外提供的真实 initial 来源都是离线诊断；不计在线方法分数。

Observed：说明在 R1 的正确 post-event State4 断点有利，在本批旧/漏改 State 和实际错误
memory 历史中没有纠错。Expected：结合来源区分未应用变化、计划值与已经发生的写入/副作用。
实际因果链是冻结原请求 → 仅替换 work-view → 实际 HTTP → 首个 answer/calls；没有调用执行。
首个断点仍是 Host 对已送达材料的解释，不是本批维护器漏写或 Store 故障。

竞争解释 H1：Host 对呈现出来的 State 或最近 memory 写入作锚定，时点说明不足以驱动来源
重建。H2：两次同文本事件、显示副本与当前请求的关系仍未被正确合并；R1 的改善依赖已正确
维护的值。工具回合还混有模型自身历史，不能据六次单响应分离这些因素或估计稳定性。

按运行前门槛，**不部署时点候选，不再修改该说明措辞**。原 Host live view 保持不变。
更一般的候选是来源访问/重建强基线，或独立比较维护前后视图的完整架构；后者不是本轮
获准继续的提示试错。最小下一步是 LR：全候选维护后独立选择读取，补齐现有 L/LRU 的合同
差异，随后推进强历史基线。决策是停止本候选、继续完整 LSA 计划，不把诊断失败当总 Goal 完成。

本批新增 **6 次生成 / 11,093 generation tokens / 0 embedding tokens**，全部 Host，
unknown=0，实际 HTTP 合计 4.420s。累计 **2,424 次生成 / 3,030,361 generation tokens /
18,183 embedding tokens**；历史费用链不变。

核对了冻结提交中的143个源码文件、config/input/rubric/source-trace 哈希、全部实际 HTTP
与 job 请求、配对非视图消息/参数/schema、R1 说明字节及费用差额。tool-loop 无说明请求
与原 trace65 完全相等。沿用既有24项源码检查和构建，没有因文档再运行测试或模型。
复现使用执行提交、固定 ignored 输入及原 read-probe prepare/run-job，另建运行目录；
runtime 不读 rubric，返回 calls 不执行。原生 memory 参数 guard 不被 probe 验证。
Product 仍 NO-GO；公开任务、完整消融、规模/模型及应用证据尚未完成。
