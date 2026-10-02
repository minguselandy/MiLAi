# v13.4 N0 来源资格与近邻可用性审计

状态：`METADATA_AUDIT_COMPLETE_T0_COHORT_NOT_ADMITTED`。本次已核对来源登记、官方论文入口、仓库元信息、固定版本许可和包元信息；**尚未准入任何新的 T0 历史，32 个独立开发历史的目标仍完整保留**。这不表示合格来源不存在，也不构成 T0、G1 或 v13.4 完成证据。Product 仍为 `NO_GO`。

机器记录、输入 SHA256、预登记规则和资源目录见 [v13-4-source-eligibility.json](../data/manifests/v13-4-source-eligibility.json)。原规划及旧曝光登记均未改写。本次无 generation/embedding HTTP、无新服务、无远端写入。

## 来源分组先于内容读取

本次只读取现有来源／曝光 manifest 的元数据，没有打开其指向的 benchmark、gold、holdout、问题、答案或案例正文；没有下载数据集。外部搜索预览和论文摘要偶然含有汇总成绩，其中 STALE 搜索预览含结果表。没有打开结果文件，也没有把这些数字用于来源选择、方法调参或 MiLAi 效果结论。该接触范围如实记录，不能把本次审计扩展声称为“从未接触任何公开成绩”。

已预登记 `v13.4-source-eligibility-policy-001`。它是读取前的通用分组规则，**不是具体 cohort 的冻结或读取授权**。Root 必须先冻结准确的原始来源身份、用途和允许视图，再读取该批内容。

联合组取以下关系的传递闭包：同一原始来源／完整历史 hash、同一原始文档或讨论串及其派生、同模板／生成器族、翻译、改写、截断和反事实变体。不同 UUID、seed、文件名或题目不能单独证明独立。未知模板关系保持未知，不因 source_id 不同而提升为独立样本。

读取前需记录原始 URL／身份、固定版本或 revision 边界、来源类别、许可证据、既有曝光与预留交集、模板和派生关系、开发／迁移／正式用途、与 Ours 胜负无关的选取规则和 UTC 读取记录。获取原文后补原始 hash、完整历史 canonical hash 与关系合并，再进入 evaluator 标注；WriterView 的时间截止和 SelectorView 的未选正文隔离仍须独立验证。

## 现有来源能证明什么

| 元数据证据 | 已核对数量／状态 | v13.4 资格结论 |
| --- | --- | --- |
| MemSyco v13.2 来源组图 | 431 个组件：304 未预留、80 旧排除、47 pilot 预留 | 仅证明 source_id／完整历史 hash 连通组件；未证明模板族独立或自然原始来源 |
| 未预留任务分组 | contextual 250、valid-memory 2、personalized 53 | 任务之间有共享组件，305 不可相加充当独立总数；去重为 304 |
| v13.1 pilot 预留 | 117 行继续排除 | 未运行不等于可回收；沿用旧曝光规则 |
| MERIT | seed 0–82 继续排除 | 新 seed 同样不证明新模板或独立来源 |
| R9 和其他已曝光开发样本 | 保留回归资格 | 不能计为新 T0 来源或正式泛化样本 |

这些观察来自已存在的 [source-group amendment](../data/manifests/v13-2-source-group-amendment.json)、[source exposure](../data/manifests/v13-1-source-exposure.json) 和 [pilot reservation](../data/manifests/v13-1-source-exposure-pilot-reservation.json)，不是本次重新读取底层数据的结果。旧“组件独立”命名不自动满足 v13.4 更严格的来源／模板联合分组要求。

T0 当前准入数为自然历史 0、构造诊断 0、总计 0。仍待选择 32 个历史及每历史四类查询；建议四种历史层各 8 的配额保留。没有因来源不足将目标改成 32 个题目、seed 或模板变体。

## 可采用的来源类别

1. **原始公开自然历史优先。** 可考虑有明确内容许可的官方文档修订与 errata、技术决策讨论或公开 wiki revision 历史。先核验实际原文许可与派生关系；公开可读本身不等于许可已通过。技术文档历史只能称为该工作流中的自然历史，不能改称自然个人对话。本文没有选择或读取这些候选原文。
2. **明确标记的构造诊断可以补充。** 应先登记独立场景与模板出处。互换正文、删日期、重复来源及互补证据集合属于诊断；同模板变体同组，不用于估计自然发生率，也不能用 32 个变体冒充 32 个独立历史。
3. **旧开发案例保留回归用途。** 不回收为新来源。既有未预留 benchmark 元数据组件只能作为待审候选，不能绕过模板与原始出处核验。
4. **LongMemEval／STALE 保留公开迁移候选身份。** 在 N5 另做适配、曝光和数据许可审计；如要改作 T0 开发，先修订用途并将整个来源／模板组永久标为开发，不能之后再作为独立迁移测试。

T0／T1 属于开发；T2 必须使用未参与 T0／T1 的历史，T3 和公开迁移按原始历史／模板冻结。没有方法胜负依赖的样本筛选。历史全部放得进预算时保留短历史控制，不人为添加噪声。四类查询的可解性和最小充分证据集合仍需 evaluator 标注，不从来源类型猜答案。

## 必要近邻的可用性

| 近邻 | 固定证据 | 本次结论与尚缺工作 |
| --- | --- | --- |
| BeliefMem | 论文 `2605.05583v2`；候选仓库 `623602e3b52a1ca9c5d106799c73ec80d053ac2a` | 仓库只有两行、35 bytes 的 README，无方法源码或许可证；作者主页 Code 链接为空。官方关联尚未通过本次入口核实，不能称为原生复现可用 |
| Graphiti | `3c427640abf909f12f71f963fce15eb514a3c493`，包 `0.30.2`，Apache-2.0 | 源码与包元信息可获得；仍未核验具体方法、prompts、后台调用、当前兼容后端或原生小切片 |

[BeliefMem 论文入口](https://arxiv.org/abs/2605.05583v2)、[候选仓库的固定 README](https://github.com/junfeng1212/BeliefMem-main/blob/623602e3b52a1ca9c5d106799c73ec80d053ac2a/README.md) 与 [共同作者主页](https://qizhouwang.github.io/homepage/) 支持上述有限的可用性结论。不能把“只找到占位仓库”提升为“世界上不存在实现”，也不能以自建近似方法冒称原生 BeliefMem。

[Graphiti 固定包定义](https://github.com/getzep/graphiti/blob/3c427640abf909f12f71f963fce15eb514a3c493/pyproject.toml) 声明 Python `>=3.10,<4`，核心依赖包含 Neo4j、OpenAI、Pydantic 和 PostHog；[固定许可证](https://github.com/getzep/graphiti/blob/3c427640abf909f12f71f963fce15eb514a3c493/LICENSE) 声明 Apache-2.0。本次没有安装或启动任何服务。后续需在现有允许的设施内核对原生方法与全部调用，再由 Root 统一计费运行小切片；自建时态方案继续命名 `Temporal-RAG`。

## 公开迁移来源的可用性

- **LongMemEval：** [固定论文](https://arxiv.org/abs/2410.10813v2) 对应 v1 系列；仓库固定为 `9e0b455f4ef0e2ab8f2e582289761153549043fc`，其 [许可证](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/LICENSE) 为 MIT。官方账号的 [已清理数据集元信息](https://huggingface.co/api/datasets/xiaowu0162/longmemeval-cleaned/revision/98d7416c24c778c2fee6e6f3006e7a073259d48f) 在 revision `98d7416c24c778c2fee6e6f3006e7a073259d48f` 声明 MIT，包含 oracle／s_cleaned／m_cleaned 文件名。只读取目录与许可元信息，没有读取这些文件。未选择切片；不静默替换成另一个 LongMemEval-V2 benchmark。
- **STALE：** [固定论文](https://arxiv.org/abs/2605.06527v1) 对应仓库 `icedreamc/STALE`，核对 commit `ea7d391103a151927cd29d2f01d87597a782bdcb`。[仓库许可证](https://github.com/icedreamc/STALE/blob/ea7d391103a151927cd29d2f01d87597a782bdcb/LICENSE) 为 MIT，版权人 Hanxiang Chao。该软件许可不能独立证明所有内含／借用数据的许可；数据级许可与原始历史交叉派生关系尚未完成，切片准入保持未验证。

两者是否含本研究需要的关系歧义、是否有足够独立来源，都未通过元数据审计证明。正式使用时，官方 scorer 与新增消歧标签必须分表；跨 benchmark 的共享历史须联合分组。

## 保存与剩余工作

实际使用的一手 landing、许可、包定义及 API 元信息保存在 ignored 的 `artifacts/v13-4/literature/source-eligibility/`。`catalog.json` 逐件记录 URL、UTC 获取时间、版本、HTTP 状态和本地 bytes 的 SHA256；tracked manifest 镜像该目录的摘要，保留失败记录。5 次重复 GitHub API 保存请求遇到 rate-limit 403，此前成功观察过的元信息没有伪造为已保存原始响应；固定版本许可证已成功保存。没有保存数据集、案例或结果文件。

下一个必要步骤是先冻结具体自然来源的元数据身份和用途，再获取与标注原文，补齐 32 历史的独立性与许可证据。其次补齐 BeliefMem 原生实现缺口、Graphiti 运行条件和 STALE 数据许可；这些缺口不妨碍继续已授权的 N1 机械工作，但不能被机械测试替代。两位独立标注者尚未提供复核，当前来源审计也不构成独立语义评审。

## 后续具体来源预登记

[T0 origin shortlist](../data/manifests/v13-4-t0-origin-shortlist.json) 已从官方 RFC errata Summary Table 和 RFC index 元数据选出 **39 个真实技术更正来源：32 主候选、7 顺序备用**。筛选限定 TLP5 生效后的 IETF 工作组文档；先对全目录的 updates／obsoletes 关系及相同工作组做保守传递合并，再按固定 SHA256 排序每组取一项。原始 RFC、erratum ID、原文 URL、后继版本、元数据快照 hash 和开发预留用途均已登记，未获取这些候选的正文。最初官网搜索预览偶然出现的 8 个 RFC 及其合并组件已排除，不能声称它们仍未曝光。

这是自然公开技术规范工作流，尚不是 32 个已准入的 T0 历史。RFC 的 [官方再利用说明](https://www.rfc-editor.org/series/rfc-use/) 和 [TLP5](https://trustee.ietf.org/documents/trust-legal-provisions/tlp-5/) 支持保留未改写原文及必要署名；个别 notice 和 erratum 的许可适用范围待核查。Root 冻结获取清单后，仍需核验真实语义派生关系、可解性和四类配额。当前 Verified 状态不能倒填为历史报告当天已通过；报告日期也不是规则有效期。若简单完整链已足够，应保留该结果，不能用备用来源替换“基线太容易”的历史。
