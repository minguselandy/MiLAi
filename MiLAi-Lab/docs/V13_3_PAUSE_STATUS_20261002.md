# v13.3 实验总结与暂停检查点（2026-10-02）

**当前实验已按用户指令暂停，Goal 为 PAUSED，完整计划尚未完成。** 暂停后只整理已有证据、报告与 GitHub 检查点。v13.3 新增方法修改、机制测试、真实生成／embedding 请求和实验样本均为 **0**；不能把计划中的预期结果当成实际收益。

[机器暂停快照](../data/manifests/v13-3-pause-summary-20261002.json)记录精确身份与费用；[原 v13.3 计划](MILAI_DEVELOPMENT_EXPERIMENT_PLAN_v13_3.md)和[v13.2 已有总结](V13_2_PAUSE_STATUS_20261002.md)分别保留规划与历史结果。

## 本轮已经完成的工作

完整读取 v13.3 计划，建立 Root 与唯一方法 Source 的隔离工作区，均基于 PR79 提交 `22addcbc378a75d7f854ddc4127eb80f45ca52fb`。原计划 487 行、SHA `9de1d62920d681beda11520408c00ea67526074d217e0afc24fefafff7d39050` 逐字保存；原文的 PROPOSED 状态属于文档历史，实际启动与暂停分别由[入口记录](../data/manifests/v13-3-entry.json)和本次快照说明。

已确认本轮方向仍为 Grounded Memory、Verified Object References、Semantic/Episodic Memory、Grounded Revision 与 Lifecycle Recovery。计划提出 EDM 证据条件下的稀疏增量维护，以及 CEP 正文优先的有界证据交付；两者目前均未接入运行时，也没有质量、费用或泛化收益证据。

Source 完成部分 W1 静态阅读并已 HOLD，未修改方法。核对了现有来源支持、读时版本、CAS、原提案／拒绝记录、事件捕获、普通缓存、快照游标、字面观察、Mem0 生命周期入口及共享生成额度。共保存 26 条静态命令、20 个源码／工程测试快照；两次不存在路径的 `rg` 错误原样保留。读取测试正文没有运行测试，不记为 PASS。[完整静态报告](V13_3_W1_STATIC_AUDIT_PAUSED.md)及[原件身份](../data/manifests/v13-3-w1-static-audit-paused.json)可查。

## 接口审计得到的具体信息

| 能力 | 已有实现与本轮发现 | 仍待验证或实现 |
|---|---|---|
| 来源与版本绑定 | owner、record、revision、version hash、Source role/hash 和严格整字段继承已有 | 不证明内容语义支持；不能重造为 v13.3 新贡献 |
| 稀疏修订 | 现 content 整体替换、scope named-key merge；显式 no_change／精确 replay 不增事实版本 | revise 的空／同值 patch 仍增版本；显式 remove、叶级支持继承与原始／编译提案合同未实现 |
| 事件处理 | 真实事件幂等捕获、来源与 pending／complete／unknown journal 已有 | 历史曾引用不等于逐事件消费；EDM 未消费 user/tool 台账与 Host final 的闭合见证边界未实现 |
| CEP 交付 | 有界读取、缓存和真实快照游标已有；旧分配仍可能截断正文 | 固定候选顺序下完整单元送达、超额明确遗漏后继续装入、全请求 exact-token 与审计映射未实现 |
| 恢复与 SDK | 公共 Mem0 close、snapshot、infer=True、同路径重开测试入口存在 | 本轮未核对安装身份、未执行 SDK；合作锁下的 Store 检查不等于后端原子 CAS 或分布式 exactly-once |
| 生成额度 | durable reserve-before-dispatch 与真实 public-message 绑定已有 | 现额度按每 public message，不得误称整轨迹累计额度 |

这些是源码静态观察，尚未完成 W1 接口冻结或验收。恢复时复用既有原语，在一个逻辑 MemoryService 和真实公共事件／回执边界内实现增量层，保持方法通用性，不按案例、题型或语言路由。

## W0–W6 的真实进度

| 工作包 | 暂停状态 | 尚未完成 |
|---|---|---|
| W0 失败与实际配置核对 | PARTIAL | 仅做入口与历史摘要核对；逐失败“实现／启用／实际效果”矩阵及原 48 行补充映射未冻结 |
| W1 公共原语与 SDK 边界 | PARTIAL_STATIC_ONLY | 部分接口阅读完成；机制复现、安装身份、恢复控制与接口冻结未完成 |
| W2 EDM | NOT_STARTED | 稀疏编译、逐事件消费、支持继承、显式保存提交及实际运行接入 |
| W3 CEP | NOT_STARTED | 完整单元装包、真实快照短引用、历史扩展与全请求预算验证 |
| W4 E0／E1／E2 | NOT_STARTED | 新接口门禁后冻结并执行实际实验，旧失败仍保留 |
| W5 四方法／两工作流 | NOT_STARTED | 条件满足后的开发与正式比较；无新四臂样本 |
| W6 泛化与公开任务 | NOT_STARTED | 未曝光来源、语言／模型／工具迁移、独立评审、正式统计与论文复现材料 |

原 v13.2 的 48 行及状态保持 **4 PASSED_SCOPED / 27 PARTIAL / 1 NOT_PASSED / 16 NOT_VERIFIED**，本轮没有晋升。**E0 NOT_PASSED / D4 NOT_ADMITTED / Product NO_GO**。计划提及的 `reference/core.py`、`experiment_plan.yaml` 等配套文件尚未在已查路径定位，其“32 个测试通过”没有在本仓库复现。

## 继承的实验结果与失败

以下为 v13.2 已发布结果，不是 v13.3 新实验。[R9 逐项结果](V13_2_E2_R9_RESULTS.md)保留 15 条已曝光开发轨迹／45 条消息的全部首次尝试。

| R9 检查项 | 历史实际结果 |
|---|---|
| 核心更正 | 15/15 原 ID、核心偏好和真实更正来源；完整范围与首次提议质量另判 |
| 查询 Reader | Root 诊断 13 scoped 正确、1 语言范围 partial、1 历史回答失败 |
| 查询后形成 | 8 次仅绑定问题来源的不必要提交、1 次被拒 pending、6 次 no_change；其中 6 次额外修订、2 次重复／冗余卡 |
| 其他失败 | 6 条 Host 提议被拒；中文保存意图未落实、scope 清空／否定频率遗漏及形成后范围丢失 |

历史回答失败时旧正文仍在 SDK 库中，但没有进入实际 HTTP，Host 也未显式读旧版本；存储、选中、送达、消费须分别判断。来源 ID／owner／hash 合法不能替代语义支持。R9 的 support/read 实际为 legacy，不能当作已启用 direct_support 的失败；完整配置矩阵仍属 W0 未完成工作。

最近已完成的 E0 R7 正常 24 检查为 21 PASS／3 FAIL，未达到 22/24。已有共同边界工程通过的有限控制是 v13.2 继承证据，不修复 R9 语义失败，也不能替代新 EDM／CEP 实验。Root 诊断不等于独立 Judge，旧曝光轨迹不等于新来源泛化。

## 费用与证据保存

R9 为 **148 次生成／899383 known tokens、63 次 embedding／24315 tokens**；其中查询后形成 15 次／60678 tokens 已包含在生成合计。R0–R9 历史开发累计 1452 次生成／6696226 known、590 次 embedding／247457，历史配置不同，不作统一因果比较。

本轮 v13.3 和暂停整理均无新增模型请求。连续账本逐字等于入口副本：9398 次 generation，27006877 known／27037264 charged 生成 tokens，964645 embedding known／charged tokens；历史 Unknown 1 与 30387 保守费用保持。账本 SHA `991a568c47d3cdb2ad23b658565729331b876cc1c33e837e1f7f89e0405c136a`。

旧 R9、共同边界和文献封存不改写。新 W1 原始输出、文件快照与失败保存在独立 ignored 目录。初始 78 行索引生成后，recorder 向命令表追加暂停整理回执，因此其中 1 行属于追加前时点；原索引与全部原命令保留，另生成终态索引，84 个被索引文件逐 hash 匹配，索引自身另记身份。新发表核对也在新目录追加，不写回封存实验。

## 论文、项目与恢复约束

本轮取得 10 项官方全文来源（9 论文、1 标准），33 个有效资源与 1 个 PPMF HTML 404 原响应；新增项目 0。原件、URL、UTC、版本、SHA 和中文说明保存于本地 `artifacts/v13-3-literature/`，入口为 `index.html`，58 条本地链接有效；[中文资料总结](V13_3_DESIGN_LITERATURE_PAUSED.md)与[来源目录](../data/manifests/v13-3-design-literature-catalog.json)随 GitHub 发布。方法深读尚未完成，适用性仅为方法启发。旧 v13.2 的 19 论文／21 项目参考组、895 文件／193 本地链接保留在原索引，不混入新实验样本或声称项目已复现。

文献阅读边界也保留：EAL 自动方法提取曾附带官方 running example，其来源不称新的盲来源；初次展示已授权旧文献目录时显示了非身份元数据。未打开 benchmark corpus／gold 或关联实验报告、材料、账本，没有把示例或实验元数据用于本轮方法修改／实验；正式来源资格仍须以后暴露审查。

用户补充授权：配套文件先自主检索，找不到就按计划实现；以后遇到问题自主研究和判断，保持设计方向、通用性与泛化性，并保存使用过的论文和项目。这一后续执行偏好已记录；最新暂停仍生效，恢复实验需要用户明确恢复指令。

恢复时先补齐 W0 原 48 行修订说明和实际配置矩阵、完成 W1 有限控制与接口冻结，再实现 W2／W3，并按门禁进入 W4–W6。每个核心假设最多两次已曝光开发修订后做 Go／Simplify／Stop 审查；不自动扩大重复开发轮次。新来源分组修订与冻结须先于新盲池访问，独立 Judge／第二模型家族缺失继续标未验证。

本次只发布 Lab 计划、总结和来源／哈希索引。运行时、测试、配置、Product API／Schema／权限／Canonical 与 Archive 相对 `22addcbc…` 无变化；原论文、运行日志、数据库及模型保持本地 ignored。分支 `feat/lab-edm-cep-v13-3-20261002` 基于 PR79；保留历史 PR79，另建草稿检查点，不合并 main。当前检查点回滚到 `22addcbc378a75d7f854ddc4127eb80f45ca52fb`；历史 main 基线为 `95bf708bfd8aac9f7855485166e3bf739928b949`。实际提交与远端核对保存在 `artifacts/v13-3-pause-publication-20261002/`。
