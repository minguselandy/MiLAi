# v25：持久应用短脚本四臂结果

同一冻结的五阶段、九消息、两用户脚本，B1 7/9、A3 7/9、A4 9/9、A5 8/9。A4本次正确消费最新计划并更新原记忆，但单条轨迹不足以证明稳定收益。四臂的初始请求及新session首请求完全相同，仍出现不同工具选择；不能把所有分差归因于SER。

这是已暴露合成应用的RESEARCH_PROTOTYPE结果，不是formal unseen或Product结论。标签操作在真实SQLite中产生持久副作用，不发生物理发货。F/R关闭，最终记忆维护由用户明确要求，不能记为自主生命周期收益。

## 身份与执行

源码预先发布于`44fb7ac9b6ed90cdfce1da8c17de734638d9b937`。81文件mapping为`ff874dc00936261303336963a415007ddbe93bbdf06a87cb87ae0a7409ab6e38`，[lock](../data/locks/milai-application-v25.lock.json) SHA `796b32df3dbe5d5028d799bbdd92a7ff313ac17fd73ce34a84de3cae3d4d0e25`。[输入/运行冻结](../data/manifests/milai-application-v25-short-execution-freeze.json)、[独立rubric](../data/diagnostics/milai-application-v25-rubric.json)、[完整精简结果](../data/manifests/milai-application-v25-short-results.json)保存来源、每消息判定、费用、状态和哈希。

普通上游LangMem manage/search与原Agent执行；每臂独立namespace、业务库、四条checkpoint thread。五阶段分别开启进程、重开Store/Provider/sidecar/checkpoint/world。公开操作员七次CRUD和Host一次manage分别计数，全部embedding计费；rubric不进入runtime。真实模型/embedding并发1，vLLM及12生成/消息容量不变。源码冻结前六项新窄测试、一个受影响旧检查、静态检查和一次构建通过；真实调用后无源码调整或重复构建。

## 质量与费用

| Arm | 严格任务 | Host完成 | 首次动作currentness | 新session任务 | 生成 | 输入/输出tokens | 总tokens | embedding请求/tokens | exact get | demotion |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B1 | 7/9 | 9/9 | 1/2 | 1/2 | 19 | 25834/1099 | 26933 | 12/334 | 0 | 0 |
| A3 Exact Refresh | 7/9 | 8/9 | 1/2 | 1/2 | 27 | 62370/1218 | 63588 | 23/424 | 7 | 0 |
| A4 SER | 9/9 | 9/9 | 2/2 | 2/2 | 19 | 28679/1138 | 29817 | 13/339 | 7 | 12 |
| A5 bounded SER | 8/9 | 9/9 | 2/2 | 1/2 | 19 | 29860/1105 | 30965 | 13/339 | 4 | 14 |

Alice受到revision1→2→3变化的首次动作共一处：B1/A3仍使用6/E-4/foam，A4/A5使用当前9/N-7/rigid。按实际参数匹配旧版本计，stale-consumption分别1/1、1/1、0/1、0/1；这不是逐词推理因果证明。Bob三条任务均通过，原计划与Alice独立access两项均保持，旧contact删除保持1/1。

四臂都实际保存Alice部分失败的预留，重启后完成同一ID的标签，并为Bob建立另一条scoped记录。最终两条reservation、两次reserve、一次complete_label，没有重复reserve。恢复只证明正确处理已经存在的记录；B1/A3错误数量不会因恢复成功变成正确。

未受Alice更新影响的Bob记忆保留了原始“尚未预留”文本，虽然Bob业务已完成。该脚本只要求报告Bob计划字段，未要求维护该状态。因此保持2/2不是完整世界状态同步，不能隐藏这项生命周期局限。

A4机械snapshot demotion precision/recall均12/12；A5均14/14；A3没有demotion，12个风险位置未处理。这里检测的是生成请求曾含后来过期的证据，不能推断整段assistant文本实际依赖该证据。exact读取均返回BOUND_CURRENT；完整结果另列动作生成请求中的直接读取数。语义贡献的refresh precision无独立反事实，记UNKNOWN，不用送达率冒充因果精度。

总84生成、151303生成tokens、61次embedding/1436tokens、18次方法get。短脚本结束连续账本755生成/755474tokens/7540embeddingtokens/93累计get；unknown、截断、Judge均0。A3的一次消息容量失败独立保留，不是Provider截断。

| Arm | Provider wall秒 | 进程wall秒 | 投影CPU/wall毫秒 | exact读取wall毫秒 | observer CPU/wall毫秒 | trace/sidecar/checkpoint/world字节 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| B1 | 12.350 | 31.431 | 0/0 | 0 | 87.512/1924.133 | 741516/184320/323584/36864 |
| A3 | 17.013 | 39.528 | 36.133/41.895 | 13.001 | 142.576/4072.358 | 1623151/294912/602112/36864 |
| A4 | 11.841 | 30.206 | 27.412/32.760 | 13.740 | 98.756/1668.391 | 924787/204800/327680/36864 |
| A5 | 11.753 | 30.204 | 20.928/22.404 | 5.420 | 96.135/1663.471 | 932918/208896/348160/36864 |

每臂observer另有16次Store读取，Root阶段后快照另有10次只读查询；二者不混入方法exact get，也不送入模型。Host search分别5/16/6/6。进程wall包括启动和观察开销，单次固定顺序不能支持稳定延迟优势。

以“任务质量最大、生成tokens最小”两轴，Pareto为B1/A4：A4多2884tokens、通过多两项；A3和A5被A4支配。若把get作为第三轴，A5的4次相对A4的7次是额外权衡，不能声称所有成本轴均被支配。所有失败和全部成本参与比较。

## Failure Review

**B1旧值执行与计划丢失。** Expected：按revision3行动，新会话保存实际状态同时保留计划字段。Actual：旧assistant结论及旧证据仍在历史→按revision2预留6→恢复真实6条目→新会话把真实6写回原计划ID，丢失计划9。第一断点是行动使用历史参数；第二断点是把执行事实覆盖计划。解释一为旧历史干扰，解释二为普通Host未区分意图与实际状态。A4受控干预路径支持前者，但同样首请求不同续轨迹使独立因果归因受限。通用修复候选是现有请求副本rebase及明确区分计划/结果的原合同，不加领域值判断或自动改参。下一步按预冻结长度边界保留原源，Continue。

**A3的刷新不保证使用。** revision3正文真实送达，首次动作仍为6；新session第一生成选择两次search_memory，第二生成将原plan ID写回仍称“无reservation/label”的相同正文，随后重复搜索状态直到12生成容量上限。没有调用已提供的get_reservation。第一断点是业务状态查询选错工具，之后循环放大费用；不等于Store内容缺失或投影漏送。假设一是旧assistant结论在动作时干扰，假设二是独立工具选择/搜索循环。新session首请求与其他臂逐字段相同却不同选择支持后者独立存在。不追加cue、不提高容量；保留此次失败及Bob后续完成，Kill“刷新即可保证端到端正确”的强假设。

**A5错key导致错误维护。** 第一生成同时search_memory和get_reservation(`Cobalt_collection`)，实际记录键是`Cobalt display panels`。真实工具正确返回not_found；下一生成将not_found/none写入原plan ID并保留“未创建”，最终回答也称不存在。世界中的正确9条目已创建标签。第一断点是搜索结果返回前猜测业务identity；随后将特定键查询失败泛化为对象不存在。假设一为rank刷新不足，假设二为与刷新无关的工具参数绑定错误。新session没有待投影历史且四臂首请求完全相同，排除了本次首步由不同SER请求导致的解释。工具已有通用完整key描述；不添加Cobalt别名、字符串纠正或领域门禁。本次不据此修改SER；保留为已知普通Agent失败边界。

Root与Sol独立只读复核未发现需要重冻源代码的确定性集成缺陷。原始checkpoint保持、实际请求副本与逐项projection/lineage对应、用户search namespace及业务scope均经实际产物核对。下一步只运行预先固定的medium/long B1/A4各一对，不扩大四臂全因子、不选择最好轨迹。

## 十项Reflection

1. 支持请求副本rebase可在有持久副作用的普通Agent中真实到达，并在本条轨迹帮助适应。
2. 反驳“exact正文送达就必然使用”和“新session维护天然准确”。
3. first broken link分别是旧值动作、业务工具选择、key身份绑定，不是SQLite/Store集成。
4. 普通Host轨迹差异能解释部分分差；首请求相同是直接证据。
5. B1本次成本最低；A4质量更高，不能只选最高分忽略简单基线。
6. 沿用小型机械版本投影合理；当前证据不支持新增语义状态平台。
7. 修具体物品key或继续改提示会过拟合，故不做。
8. 长度边界已提前固定；若将来修工具身份，需独立异名/错误key/真实缺失反例，不能重评分本次。
9. Continue预冻结B1/A4长度边界；F/R cue家族仍停止；Product不迁移。
10. 原因是应用接线已成立，但未见稳定收益和跨模型证据仍不足。
