# v13.3 资料检索总结（暂停检查点）

已保存 **10 项官方全文来源：9 篇论文、1 项标准**，含 33 个有效资源及 1 个 PPMF HTML 404 原响应；本轮新增项目 0。PDF／HTML／TXT 原件、URL、UTC、固定版本和 SHA 均在本地保留。**完整方法核查尚未完成，资料归档不构成 EDM／CEP 实现、性能或安全验收。**

[公开版本与哈希目录](../data/manifests/v13-3-design-literature-catalog.json)记录逐资源身份；本地浏览入口：`artifacts/v13-3-literature/index.html`。Root 核对 34 个原响应 hash 全匹配；本地入口 58 条链接存在。旧 [v13.2 论文与项目总结](V13_2_DESIGN_LITERATURE.md)和[原目录](../data/manifests/v13-2-design-literature-catalog.json)保持。

3 项读了部分方法节，1 项只读有限方法导入，1 项读摘要及方法开头，另 5 项只读论文／标准摘要。以下适用性是基于 EDM 稀疏继承、CEP 正文优先概念的推论，须在恢复后的接口与实验中验证。

## [EAL](https://arxiv.org/pdf/2609.01836v1) — v1

读取范围：`METHOD_SECTIONS_READ`。

EAL 将记忆中错误权限的形成与执行器对错误权限的传播分开。其有界事件溯源让模型只抽取变更，由外部不可变日志和确定性 reducer 构造当前状态；它仍依赖正确抽取、目标绑定与已知授权主体。

方法启发适用：EDM 稀疏继承须保留撤销、范围和有效期变更的可追溯关系；CEP 正文优先须保留真实证据，不能用记忆摘要自我授权。

不能据论文证明 EDM 或 CEP 已安全：论文不覆盖实际检索、缓存失效、并发、外部执行与运行恢复。事件抽取错误也不会被 reducer 自动修正。

## [PPMF](https://arxiv.org/pdf/2607.29167v1) — v1

读取范围：`LIMITED_METHOD_INTRO_READ`。

PPMF 将持久记忆的来源维护、动作参数级支持绑定、风险与来源权限的门控连成三阶段，目标是阻止低信任观察在有损合并后变成高权限行动依据。其边界依赖平台维护的来源、确认记录与固定风险策略。

有限方法启发适用：EDM 继承的是来源约束而非可升级权限；CEP 应带可核对来源，正文措辞本身不能授予权限。

本次只读了方法导入；没有核查实现、全部绑定规则或威胁证明。论文摘要的受控结果不能作为 EDM/CEP 保证。官方 HTML 未提供，PDF 已保存。

## [Hindsight](https://arxiv.org/pdf/2512.12818v1) — v1

读取范围：`METHOD_SECTIONS_READ`。

Hindsight 区分世界事实、主体经历、观点和合成观察，提供 retain、recall、reflect。TEMPR 组织时间与实体关联，并融合语义、关键词、图和时间检索，再重排和按调用方 token 预算打包。

方法启发适用：EDM 继承应区分事实、推断和合成摘要；CEP 正文与预算选择应保持来源类别，并清楚标记推断。

多路召回和预算打包不保证权限、版本或稀疏补丁语义正确；本次未读取 CARA 例题、系统提示、judge 内容或项目源码。

## [HiMem](https://arxiv.org/pdf/2601.06377v1) — v1

读取范围：`METHOD_SECTIONS_READ`。

HiMem 以不可变 Episode 保存具体对话，以 Note 保存归一化知识；混合检索或 Note 优先、Episode 回退。Note 不足且 Episode 有充分支持时才触发 reconsolidation，以 ADD/UPDATE/DELETE 处理独立、可扩展或冲突关系。

方法启发适用：EDM 可参考保留底层事件与稀疏知识修改的分层关系；CEP 正文优先比 Note 优先回退更直接接近保留原始 Episode 的依据。

其语义判断大量依赖 LLM，单用户文字对话假设不能外推到授权、多人或事务场景；Note 优先路由不能直接作为 CEP 正文优先的证据。

## [DeltaMem](https://arxiv.org/pdf/2606.03083v1) — v1

读取范围：`ABSTRACT_AND_METHOD_OPENING_ONLY`。

DeltaMem 将经验分为任务技能与环境知识两棵残差树，以根经验和增量变化减少重复；召回后沿根到匹配节点组合完整经验，并通过巩固形成新根。

有限概念启发适用：为 EDM 的稀疏继承提供基础加差异、读取时重建的参照。

方法细节核查未完成。经验的语义残差不是确定性 JSON Patch，也未证明撤销、来源权限、版本句柄或 CEP 正文优先的正确性。

## [LongMemEval](https://arxiv.org/pdf/2410.10813v2) — v2

读取范围：`ABSTRACT_ONLY`。

LongMemEval 将长期记忆工作分成 indexing、retrieval、reading，关注信息抽取、多会话推理、时间推理、知识更新和拒答；摘要提出会话分解、事实增强索引键和时间感知查询扩展。

有限概念启发适用：EDM 的更新与 CEP 的读取可分别考察，正文已存储不等于模型已检索并消费。

方法正文核查未完成；未读取 benchmark 具体题、数据或 gold。不得将该 benchmark 的结果直接当作 EDM/CEP 的适用性证据。

## [Lost in the Middle](https://arxiv.org/pdf/2307.03172v3) — v3

读取范围：`ABSTRACT_ONLY`。

Lost in the Middle 研究相关信息在长上下文中的位置变化，发现部分模型对中间位置的相关信息利用更差。其贡献是位置敏感性诊断与评测协议。

有限概念启发适用：CEP 保留正文后仍需考虑证据位置、上下文长度和实际阅读；EDM 重建全文不能自动消除位置问题。

方法正文核查未完成；论文不提供权限维护、稀疏继承或本文两方法的当前模型效果证明。

## [JSONSchemaBench](https://arxiv.org/pdf/2501.10868v3) — v3

读取范围：`ABSTRACT_ONLY`。

JSONSchemaBench 从效率、约束类型覆盖和生成质量评估结构化输出的 constrained decoding。它提醒 schema 合规、支持的约束范围与内容质量是不同维度。

有限概念启发适用：EDM/CEP 的结构化接口不能只验 JSON 可解析；仍须校验语义、来源与继承关系。

方法正文和实现核查未完成；schema 合规不能证明记忆内容真实，也不能证明权限、版本或补丁操作安全。未读取 schema 测试样例或 benchmark 内容。

## [RFC 6902](https://www.rfc-editor.org/rfc/rfc6902) — RFC 6902; April 2013

读取范围：`STANDARD_ABSTRACT_ONLY`。

RFC 6902 定义对 JSON 文档应用一串操作的 JSON Patch 文档结构及 application/json-patch+json 媒体类型。已保存官方全文 TXT 与 HTML 片段。

有限接口参照适用：为 EDM 的显式稀疏更新提供正式补丁语法参照。

条款逐项核查未完成。该格式不提供来源授权、领域生命周期、事务或 EDM 的继承语义；不能据归档完成声称已遵守全部 RFC。

## [LLMLingua-2](https://aclanthology.org/2024.findings-acl.57.pdf) — Findings of ACL 2024; August 2024

读取范围：`ABSTRACT_ONLY`。

LLMLingua-2 用数据蒸馏和双向 Transformer 编码器，把通用提示压缩建模为 token 分类；通过抽取式压缩学习保留关键信息，目标是减少输入开销。

有限概念参照适用：可作为 CEP 中正文预算与压缩代价的背景，但需要另行检查关键约束、撤销和引用是否保存。

方法正文核查未完成。抽取式提示压缩不保证逐字正文完整、授权保真或 EDM 撤销语义；本次未下载或检查其项目/模型。

## 保存边界与尚未完成项

先前已提交的下载批次在暂停收口时结束；确认暂停后没有新增网络请求。PPMF 的 PDF 正常，HTML 404 原件保留；RFC 官方 HTML 是 `<pre>` 片段，首次校验规则过严，其已有字节重新分类为有效资源，全文 TXT 亦保留。

EAL 官方方法节自动提取曾附带 running example；未打开 benchmark corpus／gold，也没有把示例用于方法修改或实验。该来源不称新的盲来源，正式资格须经以后暴露审查。首次展示已授权 v13.2 文献目录时曾超出身份字段并显示非身份元数据；未打开关联实验报告、材料或账本，后续只投影身份／路径／SHA，未将实验元数据用于方法结论。这两项边界均在原 manifest 记录。

完整条款／方法／接口核查、项目源码检查与复现尚未完成。原文件保持本地 ignored，GitHub 发布中文总结及可追溯目录；恢复后使用到的新论文或项目继续保存原件与说明。
