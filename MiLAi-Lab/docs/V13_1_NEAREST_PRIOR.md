# v13.1 最近邻核查：主张边界

日期：2026-09-30；PRIMARY_SOURCE_READ_ONLY，未安装/运行最近邻，不计行为复现完成。

Hindsight原论文区分世界事实、Agent经历、实体总结与演变信念，并定义retain/recall/reflect。
因此“区分证据和推断”“可追踪反思”本身不能作为本项目独立新颖性。
[原论文](https://arxiv.org/abs/2512.12818)。

官方当前接口实际分别提供retain、recall、reflect；只用前两者与共同reader，应标记后端对照。
其当前observations还有支持证据的持续整合，后台维护和reflect生成必须完整计费。
这些官方功能说明不是本项目验证的准确率或隔离保证。
[官方仓库](https://github.com/vectorize-io/hindsight)。

HiMem官方提供all/note/episode构建与可选knowledge alignment；比较双类型记忆时应忠实保留这些
配置维度，而不是删掉再整合后以弱化版本代表整套方法。
[官方仓库](https://github.com/jojopdq/HiMem)。原论文方法按层级组织长期记忆并讨论修订整合；
双层命名不构成本项目独有贡献。
[原论文HTML](https://arxiv.org/html/2601.06377v1)。

本项目当前可检验的较窄假设是：受限业务字段与真实执行回执绑定，在普通使用和恢复轨迹中
减少无依据字段传播，同时保留有效信息。这是研发推断，不是已证实结论。Prompt-only、
Ref-only与共同保护的Receipt-RAG是直接替代解释；P3/P5/P7必须做公平验证。

P1/P2首批保持有限原型，不接入更多框架。若最终主张只涉及两个操作字段，不扩大成通用
自然语言验证、反思架构或双类型优势。若后续要提出双类型增益，HiMem针对性比较仍是义务；
若主张证据/推断与可追踪性，则Hindsight最近邻微切片或明确复现缺口仍须交付。
