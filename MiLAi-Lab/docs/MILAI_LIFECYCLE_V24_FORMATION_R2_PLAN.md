# Formation R2：明确条件性持久化义务

R1代码、0/2形成失败及全部费用已发布并核对remote：`5c1574c8943bcc0ad0fab0933770a6e4e51d1a62`。原[Goal](MILAI_LIFECYCLE_V24_GOAL.md)、cue和四例输入的原字节由该commit保留。R2只检验“弱考虑提示没有形成明确工具义务”这一解释，不同时改变触发时机。

固定cue改为以下原文，`formation_protocol_id=prospective_retention_duty_v2`：

> When the user establishes a future use for a commitment, constraint, unfinished obligation, or reusable result, call manage_memory before the final reply to save or update the smallest accurate, scoped durable note, including relevant identifiers from completed tool results. Do not substitute an oral acknowledgement for the memory operation. If no future use is established, do not write memory.

这是更窄的显式未来用途条件。普通Host仍判断条件、要保留的内容和原工具CRUD/no-op，不由程序判断正文，不强制所有消息写入。只替换一段cue和对应身份，原schema、loop、容量、Store、vLLM及F/R隔离不变；不加receipt hook或独立模型步骤。

只新跑F的原四例/六消息，使用同一输入、业务回执和rubric，新空namespace。B1固定参考为R1的10生成/5325tokens/0/2形成/2/4case，不称本轮fresh matched B1。新source lock、protocol与execution freeze在调用前完成；旧cue结果永久保留，不覆盖其source/config/lock。F2的B1提示合同与旧参考保持相同，但真实轨迹可能波动，因此收益只按已暴露开发例解释。

成功要求同时满足两条未来信息形成/后续使用与两条临时信息no-op；若只提高写入量或误存临时内容则未通过。逐项核对实际记忆内容、工具回执和Provider送达，不把口头“已保存”当成写入。先做与cue/身份直接相关的最窄检查；CLI/config/lock包装若改变只做一次必要构建，不重复全套测试。

起点连续588生成/541964generation tokens/5115embedding tokens/75exact reads；所有新失败和输出计费。完成后给出Failure Review和十项Reflection，再独立进入R；若F2仍失败，按证据判断事件提示是否值得增加，不连续堆积提示或扩题。当前不据两条正例宣称普遍形成能力；非业务未来用途仍是边界，留后续P12小脚本验证。
