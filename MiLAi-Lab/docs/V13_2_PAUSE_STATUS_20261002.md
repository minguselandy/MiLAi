# v13.2 实验总结与暂停快照（2026-10-02）

用户要求“暂停当前实验，生成总结报告，提交到github上”。**Goal 已 paused，实验未完成；暂停后仅整理已有证据、报告、归档和发布，不启动新实验或模型请求。** 当前 Source 已 READY/HOLD，无运行中的模型进程。

本次检查点保存已验证 R9 结果、共同边界的限定工程实现、资料索引和暂停状态。[机器快照](../data/manifests/v13-2-pause-summary-20261002.json)记录精确来源、费用和封存身份；[执行记录](V13_2_EXECUTION.md)保留各历史轮次。

## 已得到什么结论

现有证据支持来源/角色/owner/hash、原 ID 与版本冲突、真实回执、同一连续账本和有界材料的限定工程行为。自由生成的语言、范围、历史回答和来源语义支持仍有失败。当前不能认定方法质量、泛化或正式比较已通过。

原计划 SHA `84c89a3e8dbb1f23ad4478e8a809f264c76c430b537b0ea1501671230681a79a`、589行原样保留；48项状态仍为 **4 PASSED_SCOPED / 27 PARTIAL / 1 NOT_PASSED / 16 NOT_VERIFIED**。**E0 NOT_PASSED / D4 NOT_ADMITTED / Product NO_GO**。

## R9：15条开发轨迹、45条消息的全部首次尝试

三种更新接口沿用五个已曝光事项，实际执行前已发布并核对冻结。45条消息均完成，未中断或重跑；每条真实答复、Tool回执、Source、HTTP、费用和 Root 显式复核保留。[完整逐项报告](V13_2_E2_R9_RESULTS.md)和[机器结果](../data/manifests/v13-2-e2-r9-results.json)已在提交 `fd6bf53bbe3c2553863635af4c4f2445caf1d1bc` 发布。

| 检查项 | 实际结果及限制 |
|---|---|
| 核心修订 | 15/15命中原ID、核心偏好改对并引用真实更正来源；不证明结构范围全部保持或首次提议正确 |
| 查询 Reader | Root开发诊断13 scoped正确、1语言范围表达partial、1历史回答错误；不是独立Judge |
| 查询后形成 | 8不必要提交、1错误提议被拒pending、6 no_change；8提交仅绑定问题Source，问题本身不支持偏好事实 |
| 重复与历史 | 6额外修订、2新增重复/冗余卡；旧真实来源仍在历史中，不代表新版本有语义支持 |
| 语言和范围 | 两条实际英语卡未满足中文保存；完整update清空部分结构scope，另有频率/否定遗漏及形成后范围丢失 |
| 首次错误提议 | 6条Host提议被真实守卫拒绝，含编造/过期Source及无支持业务字段；原提议和费用保留 |

历史回答失败的旧版本仍在SDK数据库中，但其正文没有进入实际HTTP，Host也未显式读旧版本。另一接口真实送达了当前与旧正文并正确回答。存在历史、选中索引、真实送达、正确消费分别判断；尚不据此证明Attention因果或可外推收益。正确Reader也不能遮盖其后Writer的来源或范围失败。

原件封存为1069文件、0 symlink；index SHA `374f06ef4b422409ea9d189e24438487e92c65e97f4c709f666d71f384f7091f`。机械审计检查全部148实际生成packet与形成前Host final位置；15终态库通过实际安装SQLite SDK只读重开，共347 items、20当前卡、41历史版本，数据库与账本保持。机械通过不等于任务通过。

## 先前证据与费用

E0 最近已完成的 R7 正常24开发检查为21 PASS、3 FAIL，未达22/24阈值；两个旧更新问题的完整直接修复及来源支持门禁仍未收口。旧中断、NOT_RUN与各配置差异均保留，不拼接最佳答案。

R8 已完成固定观察流与自由Host的32条首次消息。固定Field有3 commit/1 pending/4 no_change，派生侧16字面观察且无语义生成；自由侧有4真实语义卡，也保留不可用最终回答、未恢复的失败历史与限定保存声明。完成数不替代质量结论。[R8固定结果](V13_2_E1_R8_CONTROLLED_RESULTS.md)、[自由结果](V13_2_E1_R8_FREE_RESULTS.md)另列。

| R9接口 | 生成请求 / known tokens | embedding请求 / tokens |
|---|---:|---:|
| 旧 target query | 51 / 291730 | 20 / 8072 |
| Source回链 | 48 / 288516 | 21 / 7983 |
| 回链＋读取句柄patch | 49 / 319137 | 22 / 8260 |
| 合计 | 148 / 899383 | 63 / 24315 |

合计已包含15次查询后形成/60678 tokens。失败、no_change、额外读取、材料与schema均计费；R9新增Unknown0，历史Unknown1及30387保守费用保持。R0–R9开发累计 **1452生成/6696226 known、590 embedding/247457**，历史条件不同，不能视作统一因果比较。

当前原连续账本为9398次generation、27006877 known / 27037264 charged生成tokens、964645 embedding known/charged tokens；SHA `991a568c47d3cdb2ad23b658565729331b876cc1c33e837e1f7f89e0405c136a`。后续工程验收与暂停整理均无真实模型HTTP，账本未增加。美元/GPU小时未测。

## 暂停前完成的共同边界工程

Source本地提交 `1c9c7334394d8f3411d2da2f58ad1151aad54251` 的7个限定路径已精确转入实验树，含4 runtime与3 tests。新增能力默认legacy，只在比较入口显式启用：实际Human一次有界读取并缓存本turn；真实Host final闭合后一次形成；共享durable生成额度跨进程持续；Host读取目录与后台合法维护分别执行。

B2保留原文索引；B6保留原文/字面投影与可选一次付费摘要；Mem0保持observed_events_v1和原生infer=True；M沿用既有writer1/repair0、排名/选择/allocator/CAS。非M任一common开关启用时移除CRUD占位；M的只读Host由common_host_profile控制。原生get/history只使用真实owned/选中ID，不伪造M版本或CAS。开关联动与新metadata/prefix分配是共同因素。

Root独立执行 **39新控制＋24相关旧控制** 全通过；Primary主SDK另36重复控制通过，不重复算作新增独立样本。实际公共Mem0构造、snapshot-before-close、close、独立进程同路径重开和第四能力P5入口为SDK/Mock机械证据。8组父/当前默认实际wire与工具目录逐字一致；6个Qwen本地tokenizer压力包复现长正文截断，M送3/省9 unit，无压缩或质量收益结论。4文件mypy、7文件ruff、两个包边界及离线wheel/sdist构建通过，未升级运行SDK。

Source145命令＋3终态锚点、27个原非零均保留。Root17个有限检查/收集回执包含2个初始非零：审计错误假设脚本命令也有stdin原件；主环境缺hatchling构建后端。原失败保存，分别按真实回执形态修正审计、使用既有本地缓存离线构建恢复；不补造缺失证据。Source6077索引原件及18终态文件核对，53个pytest目录symlink元数据由Root另记录，不冒称原Source索引已覆盖它们。

上述仅为工程检查点，没有启动新的实际四臂队列，也没有修复R9语义问题或晋升E0/D4。[共同工程证据](../data/manifests/v13-2-common-boundary-engineering-acceptance.json)保留实现hash、回执、范围和原失败。

## 文献和项目均已保存

[中文资料总结与公开出处](V13_2_DESIGN_LITERATURE.md)及[版本/hash目录](../data/manifests/v13-2-design-literature-catalog.json)随GitHub检查点保存。用户本地入口为 `artifacts/v13-2-design-literature/index.html`：19论文、21项目参考组，最新核验895文件/193入口链接、0问题；计数包含资料和归档证明，不是895篇论文。

保留完整已下载PDF/HTML、实际阅读的项目源码/固定commit、URL、UTC、SHA和中文说明。四次R9方法复查涉及EAL/Hindsight/Mem0的证据与形成边界、JSON结构与语言意图、opaque引用的真实身份、历史保留—送达—消费；新共同边界补充保留实际固定Mem0四模块、原git输出和SDK限制。原unversioned资源不改称固定版本；一次首次浏览DTO本地缺失与一次归档器语法失败均明确限定。

反思保持原方向：从真实公共事件和回执绑定来源与身份，记录版本/范围/遗漏，统一有界交付并计费显式追加读，由模型选择no_change。没有按案例、语言或题型路由，没有自动再读、修补、重试、退款或改写最终答案。改进候选与已验证收益分开记录。

## 恢复时仍需完成

1. 原E0正常24和两旧更新的完整直接修复；现有失败保留，不因有限控制通过跳过门禁。
2. 新共同能力条件先固定环境/配置/Source组并发布核对，再做四主臂六已曝光故事24轨迹；质量24次生成与共同12次条件分开。
3. 新pilot、正式两工作流、公开任务和条件消融按原证据门槛推进；Source组修订前不读新盲池内容。
4. 独立Judge、第二模型家族、正式统计、长程、迁移/恢复/删除及完整复现仍未验证；Root复核不能替代独立评审。

完整工作表仍为[48项原要求](../data/manifests/v13-2-requirements.json)。恢复必须有新的用户指令，沿用原计划、冻结与同一连续账本。当前仅保存到分支 `feat/lab-evidence-incremental-v13-2-20261001` 和[草稿PR79](https://github.com/minguselandy/MiLAi/pull/79)，不合并main。回滚基线 `95bf708bfd8aac9f7855485166e3bf739928b949`；Product API/Schema/权限/Canonical未改。

论文原文、运行HTTP/log、数据库、模型和归档目录保持本地ignored；GitHub提交代码、总结、来源与hash索引。实际提交SHA和远端核对原件在独立 `artifacts/v13-2-pause-summary-publication-20261002/` 保存，不写回已封存实验目录。
