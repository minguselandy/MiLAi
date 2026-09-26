# v19 修复结果

状态：`COMPLETE_WITH_FRESHNESS_LIMITATIONS`。已完成用户[修复文档](v19修复.md)的顺序开发与三个原实例验证，vLLM设置未改。请求副本中的过期记忆正文已正确隔离，精确刷新也真实交付了当前版本；**changed的错误动作仍未解决**。没有方法通过全部三个实例，因此不选出“已验证有效”的主方法，也不恢复ODR、M1或追加Attention。

## 三个阶段

| 阶段 | changed：4→8 | retained：8/note A→8/note B | irrelevant：X current，Y更新 | 通过 |
| --- | --- | --- | --- | ---: |
| A1原Notice | 有提示，旧正文仍在；记录4 | 记录8，未取得X@2 | 记录8，无额外search | 1/3 |
| A2 Quarantine | 旧记忆正文确已隔离；仍记录4 | 记录8，未取得X@2 | 逐项隔离Y，X原样；记录8 | 1/3 |
| A3 Exact Refresh | X@2真实交付；仍记录4 | X@2真实交付，记录8 | 精确刷新Y，X原样；记录8 | 2/3 |

每阶段只跑相同的三个fixture，各一次，不修改公开消息、工具或评分。每例3条公开消息、5次生成、1次初始普通search、批准后1次业务动作；全部27条公开消息完成。全部9例更新后Host search均为0，Host manage_memory写入均为0。seed/update通过原public工具真实执行，与Host自主写入分开记账。A0仅保留B1参考身份，没有新增A0运行。

A1先于源码修改，使用提交 `d0367aab36c15b39bdd4e2c1fd7a92a542f66fcf` 的现成freshness_only。失败才触发A2开发；A2失败后才开发A3。A2源码在提交 `b753347c79edfbad06083a443b6de7f3d0fc8f1c` 留下独立复现点，再改共享文件。

## changed为什么仍失败

A3 changed的三次更新后请求都进行了绑定成功的同对象精确读取，当前8°C全文进入实际Provider ToolMessage。sidecar的 `PROJECTED_REFRESHED` 与真实请求body hash一致，旧4°C记忆正文已移除。但业务请求仍包含原助手的4°C结论，以及第二条公开消息后再次生成的4°C结论。模型最终真实调用 `record_holding_instruction(crate="Lumen-42", temperature_celsius=4)`。

因此，这次错误不能再归因于“当前正文没有送到模型”。现象与历史助手结论持续影响动作一致，但未隔离该因素，不能声称已证明唯一原因。固定24-token source-authority原则未能纠正这个实例；未事后强化提示、删除助手历史、改业务参数、禁止动作或重跑取最好结果。

retained通过的是预先声明的“X@2实际进入请求，随后动作8”标准，排除了只看数字8的判定错误，但不能从单例证明模型内部推理采用了新标签。这些是三个exposed development controls，不构成泛化、产品效果或稳定成功率。

## 适配器与证据不变量

新方法位于 `methods/freshness_projection/`，在 `VLLMChatModel._generate()` 得到wire messages后、调用Provider前工作。只改本次请求副本，不改原ToolMessage、checkpoint、Store或助手历史。A2/A3共用逐项状态/渲染逻辑和结构化plan，包含ref、status、current_ref、current_body_delivered、source_tool_call、item_index与namespace；没有Decision、ack、completion或语义State。

- CURRENT及UNKNOWN项原样保留，顺序及metadata不变；UNKNOWN不伪造为current。SUPERSEDED/DELETED正文逐项隔离，不丢弃整个搜索数组。
- A2零自动读取、零自动search。它是“隔离＋通用authority原则”的组合干预，不能归因成纯renderer效果。
- A3沿用相同原则与B1 answer/calls schema，只新增同对象public `Store.get(namespace, memory_id, refresh_ttl=False)`。返回Item必须与sidecar当前revision的post_item精确匹配，才交付新正文及版本来源。
- 每request按(namespace,id,revision)去重；当前正文已实际在请求中则不读。deleted/unknown不读；缺失、异常、版本失配继续隔离并记UNKNOWN。新版本不复制旧相似度score，未变current项的score保持原样。
- 读取一完成即记录 `freshness_exact_read`，Provider成功后另记 `freshness_projection`。读取事实不等于已交付，失败请求也不能漏算已经发生的读取。
- A2/A3合计18个投影请求均核对实际wire、source search、逐项位置、body ref和原checkpoint。没有将隔离前全文继续误记为FULL。

旧freshness.py/ODR方法保留冻结历史身份；新A2/A3共用projection plan，未复制三套活动实现。所有本轮实际响应schema均无reconstruction字段。新schema与A1实际wire一致，没有重复decoder probe。

## 读取与费用

| 阶段 | 生成 | 输入/输出tokens | 总tokens | embedding请求/tokens | 新精确get |
| --- | ---: | ---: | ---: | ---: | ---: |
| A1 | 15 | 13209 / 395 | 13604 | 10 / 270 | 0 |
| A2 | 15 | 13532 / 422 | 13954 | 10 / 268 | 0 |
| A3 | 15 | 13490 / 409 | 13899 | 10 / 270 | 9 |
| 本次合计 | 45 | 40231 / 1226 | 41457 | 30 / 808 | 9 |

普通search后续生成9次、业务工具后续生成9次，已计入45次；独立State/refresh生成和Judge为0。Provider错误、协议拒绝、截断、unknown usage均为0。Provider回执wall合计16.120秒，不含全部本地运行开销，不能据此宣称性能提升。

A3每例3次get：changed读X，合计3.995090ms；retained读X，4.168146ms；irrelevant读Y，3.698550ms。总计9次、11.861786ms。跨request重新解析，未做持久缓存，因此批准后的普通业务followup仍刷新该历史项。**irrelevant有3次Y精确读取，不能称为零干预**；没有重读current X、额外search、refresh embedding或改变温度。

B1原有写入前后观测读取每阶段14次，与A3新增9次get单列。30个embedding请求来自原seed/update/Host初始search路径，exact refresh自身为0。独立run的检索文本、随机ID和元数据可能影响tokens，不把账单差异解释为因果节省。

旧v19的20次/20360tokens/274embeddingtokens继续由账本history引用，未清零或覆盖；与本次合计65次/61817tokens/1082embeddingtokens。更早v18/v17/v16/v15历史、旧失败和unknown reservation继续保留。

固定tokenizer对重复实际交付的文本片段离线计数如下：

| 片段 | A1 | A2 | A3 |
| --- | ---: | ---: | ---: |
| freshness notice | 846 | 0 | 0 |
| 固定authority原则 | 0 | 360 | 360 |
| quarantine marker | 0 | 936 | 0 |
| exact当前正文 | 0 | 0 | 264 |
| exact版本metadata | 0 | 0 | 855 |

这是独立片段tokens，包含重复交付，不是额外账单，也不能相加重构Provider计费；版本metadata不含外层JSON键/分隔符及Item时间戳。

## 存储、检查和保留项

| 实际本地字节 | A1三例 | A2三例 | A3三例 |
| --- | ---: | ---: | ---: |
| 原始trace | 581497 | 599416 | 617078 |
| 其中projection/read事件 | 4778 | 19767 | 36824 |
| B1 sidecar SQLite | 270336 | 270336 | 270336 |
| checkpoint SQLite | 233472 | 237568 | 233472 |
| 业务journal | 2418 | 2418 | 2418 |
| 持久语义State | 0 | 0 | 0 |

事件字节是trace子集，不能重复相加。sidecar文件页数相对创建时没有增长，不意味着事实记录零存储；表和正文占用这些文件。共享PostgreSQL物理空间未按run归因。原始trace、数据库、私密配置与环境回执留在ignored artifacts；Git保存紧凑结果及hash。

最终受影响窄测试27通过；ruff、mypy、两个边界及diff检查通过。A3 lock后仅一次 `uv build`，wheel/sdist内容检查通过。无full suite、12/20、MERIT或新holdout。旧M1异常漂移只改测试，独立提交 `a0ab47a09a2079e6dbe41e0981978777fb32cd26`，见[单独记录](MILA_M1_HISTORICAL_TEST_EXPECTATION_DRIFT_20260926.md)；M1语义和旧17通过/1失败的历史报告不改。

最终核对59个runtime、6个validation文件；18个旧artifact、14个旧M1/ODR方法文件和747行用户文档字节不变。Host容器/image/command/env/HostConfig、vLLM0.27.1及embedding0.9.1核对未变；max_tokens4096、max_model_len65536、thinking=false和原parser保持原值。

证据：[A1](../data/manifests/freshness-v19-repair-a1-results.json)、[A2](../data/manifests/freshness-v19-repair-a2-results.json)、[A3](../data/manifests/freshness-v19-repair-a3-results.json)、[总账与存储](../data/manifests/freshness-v19-repair-final-accounting.json)、[最终检查](../data/manifests/freshness-v19-repair-final-verification.json)、[复现](MILA_FRESHNESS_PROJECTION_V19_REPAIR_REPRODUCTION_20260926.md)。实现与小规模判定已完成，模型继续使用历史助手值的行为问题保留为失败。
