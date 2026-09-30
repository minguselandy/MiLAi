# v13.1 回执消费 R8

日期：2026-09-30。通用公开合同提示的单变量开发诊断通过，完整规划 ACTIVE。

R7已实际交付正确 lookup回执，最终回答仍把已创建标签说成未完成。最早断点在回执消费/
生成，不是 Store丢失、对象不存在或工具未执行。[R8协议](../data/manifests/v13-1-receipt-r8-protocol.json)
复制相同实际 world、memory和journal；公共查询相同，新进程/新会话，源码/工具/guard/模型/
预算保持。唯一增加的通用说明区分操作结果status与label_status，公开工具中created表示
标签创建已成功。没有案例词典、特定ID、标准业务计划、答案改写或额外writer。

[结果与身份](../data/manifests/v13-1-receipt-r8-results.json)：两组都实际get_reservation，
原始 lookup回执完全相同，world终态相同；真实每次调用的source/object ref ID自然不同，未
伪造为相同。首次 wire仅system内容不同。原指令再次回答created表示“已创建但尚未完成”，
候选正确报告标签工作已完成、无需重做。两组额外mutation和memory提案均0；无新错误效果。
Root按完整回执与最终答案判断，不以关键词命中代替语义验收。

改善来自通用公开合同提示，不能计为Field-grounded或额外业务guard的收益；旧fields为空/
unchecked、R7错误与成本保留。所有强baseline应得到相同公开字段含义，单例不证明一般优势。

新增4generation/5314tokens，embedding0、Judge0、unknown0，逐响应与ledger增量一致。
连续6230generation/11524397 generation tokens/416930 embedding tokens；完整I/O未齐。
R9组合候选按原24输入/rubric，先重跑六故事，通过真实链检查后才运行余18例。正常门槛
仍NOT_MET，完整P0–P8继续，Product NO_GO。
