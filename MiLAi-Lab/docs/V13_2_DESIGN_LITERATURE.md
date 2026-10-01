# v13.2 设计资料索引与失败反思

2026-10-01。按用户要求，检索并实际采用的论文、项目和官方SDK资料均留存，后续新增资料继续追加本索引与[机器目录](../data/manifests/v13-2-design-literature-catalog.json)。现保存5篇论文PDF/HTML/摘要，3个上游项目的固定commit方法源码、README与LICENSE，以及LangGraph SDK和Arrow表示格式两份官方参考。

完整本地资料位于`artifacts/v13-2-design-literature/`；打开其中`index.html`可查看总结并点击PDF、网页原文和项目README。二进制论文和第三方源码快照保持ignored，GitHub发布索引、原文链接、固定commit和SHA256，便于在其他机器重新下载核对。下载/保存不等于完整复现；原benchmark问题、gold、正式holdout未读入或用于修复。

## 论文与可借鉴内容

| 资料 | 方法要点 | 对当前设计的用途与边界 |
| --- | --- | --- |
| [Lost in the Middle](https://arxiv.org/abs/2307.03172) | 研究相关证据在长上下文不同位置时的消费差异。 | 材料进入上下文不保证答案消费。R3首先要解决旧正文未交付，再分别测交付和使用，不能把增加上下文长度当作修复。 |
| [Mem0](https://arxiv.org/abs/2504.19413) | 把新候选事实抽取与对旧记忆的操作选择分成两个阶段，包含NOOP。 | 借鉴“先判断有没有新事实，再决定维护”的职责。保留现有一次writer边界与来源/CAS，不增加后台服务；这只是修复假设，不移植论文收益。 |
| [Hindsight](https://arxiv.org/abs/2512.12818) | 保留时间/实体信息，区分事实、经历与意见；通过多路检索关联有关记忆。 | 参考实际历史关联和主张性质的表达。沿用原词法+dense与source回链，只压缩重复metadata并交付真实相关版本，不默认接新reranker、推断日期或重建大型图。 |
| [HiMem](https://arxiv.org/abs/2601.06377) | Episode与Note关联，冲突感知再整合帮助动态维护。 | 作为类型/关联机制近邻，保留可选kind及现有身份修订。当前先验证单条实际关联/更新，不据此强制双Store或宣称双类型更好。 |
| [EAL-Bench论文](https://arxiv.org/abs/2609.01836) | 分析错误权威在记忆形成和下游行动中的传播，比较来源约束与有界事件溯源。 | 提示存在来源ID仍不等于概括被支持，推断/提问不能升级成用户事实或业务授权。gold引用源gate属于诊断条件，不引入运行时隐藏授权或gold。 |

上表是对原始论文相关方法部分的概括；应用到当前系统的取舍是Root推断，尚未通过新实验。论文自报性能不作为MiLAi性能结论。HiMem和EAL的代码未作忠实复现；项目版本也不自动等于论文评测版本。

## 已保存项目版本

| 官方项目 | 保存身份 | 本地内容 |
| --- | --- | --- |
| [nelson-liu/lost-in-the-middle](https://github.com/nelson-liu/lost-in-the-middle) | `29b8a6d042ce29abccee3db1a73171a107d7e6af` | `projects/lost-in-the-middle`；12份文件，源码/README/LICENSE或SDK版本参考，完整文件hash见目录 |
| [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) | `f2c33cc405023dcaa8aa8ef4c0120e1f262f05ad` | `projects/hindsight`；353份文件，源码/README/LICENSE或SDK版本参考，完整文件hash见目录 |
| [mem0ai/mem0](https://github.com/mem0ai/mem0) | `94c3fe9f238f3dbf29c9ce98643bd71eb13077cd` | `projects/mem0`；171份文件，源码/README/LICENSE或SDK版本参考，完整文件hash见目录 |
| [langchain-ai/langgraph Store reference](https://github.com/langchain-ai/langgraph) | `11ee185999b86bfea2d8c0e69cef9a5e37acf686` | `projects/langgraph-store-reference`；10份文件，源码/README/LICENSE或SDK版本参考，完整文件hash见目录 |
| [Apache Arrow dictionary encoding reference](https://github.com/apache/arrow) | `3ad0370a04ccdae638755b94c3c31c8760a11193`，20.0.0 | `projects/apache-arrow-dictionary-reference`；8份官方版本文档、格式源码、README/LICENSE和tag元数据；选定参考片段，不是全仓复现 |

LangGraph另保留本次实际安装`langgraph-checkpoint-sqlite==2.0.11`的源码与包METADATA；官方新版本的分段匹配和实际安装版本的LIKE行为分开记录，没有升级SDK。Hindsight目录重组使首次旧路径未取到源码，随后按tree metadata找到实际路径并核对353份文件；这个归档问题不算实验失败或成功。

## R3失败给出的改进假设

实际证据见[R3全24结果](../data/manifests/v13-2-e0-r3-results.json)。四个更新查询的普通包都只送达当前正文；历史revision/source匹配菜单占据大量预算，另五个已选单元被省略。饮品/距离的Host显式读旧版后能回答历史；语言/会议未读取所需旧版或只重复读当前，最终漏旧值。这支持优先检查“元数据与正文如何分配同一预算”，不能把revision菜单存在当作历史消费成功，也不能按“以前”等语言关键词选答案。

通用读入修复候选是在固定选中record/source范围内压缩重复metadata，把真实相关旧版本和叶子片段按同一2048/6限制呈现，保留读时CAS、来源角色/hash和省略页。不改变检索排名或强行选更新目标；构造、实际HTTP送达和最终消费分别验收。

维护方面，R3在无新偏好陈述的查询边界仍发生额外修订，七条轨迹只以问题引用旧事实；团队午餐例还新增错误长期个人素食卡。抽取新主张与选择修改应先在同一writer推理中明确区分：仅查询既有信息时允许直接decline/no_change，当前事件是触发而非旧事实的全部支持；保留实际旧支持与未改字段。这个语义判断仍由模型完成，不能用固定问号/中文词或benchmark ID替代，也不声称引文匹配能验证蕴含。

下一次候选必须另列修改范围、冻结配置/源码/rubric和费用身份；共同解释规则同样提供给基线。保留R0–R3全量否定结果，不挑最好回答。此阶段仍是曝光开发诊断，完整独立来源pilot、独立评分和泛化验证未完成。

## R4复检后的取舍

[R4完整结果](../data/manifests/v13-2-e0-r4-results.json)20通过/4失败，没有达到门槛。重新查阅[Mem0原论文](https://arxiv.org/abs/2504.19413)、[Hindsight原论文](https://arxiv.org/abs/2512.12818)及[固定Mem0抽取/更新源码](https://github.com/mem0ai/mem0/blob/94c3fe9f238f3dbf29c9ce98643bd71eb13077cd/mem0/configs/prompts.py)，来源正文和固定代码均已保存。抽取允许空候选、维护允许不变只是设计职责，不保证模型能正确区分问题前提与用户事实；不会整段照搬上游prompt、时钟推断或示例。

R4维护14次no_change说明同一writer能够选择不改，但团队素食误写、临时演示范围扩大和语言查询单问题引用仍然存在。实际引用成员验证不等于支持主张，更不等于范围正确。这些是Root结合本地证据的推断，论文收益没有迁移为MiLAi结论。

表示候选只压缩已有选中单元的重复metadata，留出真实历史/叶子正文预算；不按题目语种或关键词改变检索/更新选择。先验收工程交付，再冻结新的全量开发cohort；相同公开说明提供各基线。默认旧行为保留，索引存储性能改动独立测量，不合并为单因素收益。

SDK检查另保存官方固定Store接口与实际安装`langgraph-checkpoint==2.1.2`接口/METADATA。公开put禁止namespace分量包含句点；无效测试样例失败与修正依据保留。官方最新分段行为与实际Sqlite2.0.11前缀LIKE继续分开，没有升级SDK。新增资源和失败反思在本地SDK参考的`namespace-validation/`可查看。

## 材料压缩工程失败与表示参考

共享来源绑定后，两记录、多语种的实际Qwen tokenizer工程夹具仍只交付一份选中旧正文；失败回执保留。为减少重复字段，查阅并保存[Arrow 20.0字典编码格式](https://arrow.apache.org/docs/20.0/format/Columnar.html#dictionary-encoded-layout)与[格式说明](https://arrow.apache.org/docs/20.0/format/Intro.html)。字典保存完整值，重复处使用明确索引；字典与索引需要一起传递。

当前候选借鉴这个通用表示原则，压缩实际record ID、完全相等的scope及重复读入口，保留完整来源role/hash、版本hash/CAS、当前/历史区分和真实省略状态。表、解码说明及正文仍共同计入原2048预算。此应用是工程假设；不引入Arrow依赖，不改排名或选取范围，模型能否正确消费及完整语义收益尚未验证。小包可能因表开销变大，同样需要记录。

20.0.0发布tag实际指向第二层tag；首次只解引用一层的归档检查失败，原元数据保留，递归解析后固定到上述实际commit。归档错误与材料交付失败分开，不算模型样本。
