# D0增量：四条后续验证任务资料

状态`PREPARED_NOT_EXECUTABLE`。本轮未启动服务或模型，未授予D0整体/D3/D4/D5通过。
上一轮私人HTTP负载是真实进展；本轮核对完整D0–D3后，补齐此前缺失的任务资料，
没有因混合保存长尾重复压测，也没有缩减正式验证矩阵。

索引`configs/v02-d5-task-pack.json`；资料根
`artifacts/v02-e2e-generality/d5-task-pack-20260907a`。manifest SHA256：
`7e884ae847e44acbfe7101aa7f331b0b257d1171a15100633caf8742f3748b8a`。
源码与Host未因资料改变；当前Product pin仍84ccec2a…，完整值见索引引用的锁。

| 独立任务 | 正常G产物 | 续做交付 | 预定记忆机会 |
|---|---|---|---|
| research-comparison | 两种研究路线的阅读札记 | 给负责人的研究简报及编辑核对表 | 预期L1足够，必须依据真实G再确认 |
| research-benchmark | 长程对话评估计划 | 按新评审决定续做建议及事实表 | G后新增评审原件，须取得新来源 |
| writing-event | 社区活动邀请初稿 | 已报名者确认邮件 | 预期L1足够，必须依据真实G再确认 |
| writing-maintenance | 维护公告与客服初稿 | 按批准安排完成公告和FAQ | G后新增批准原件，旧窗口不再适用 |

两个写作案例和研究项目决定明确是合成情境，不能解释为MiLAi线上维护或实际实验成绩。
研究背景使用指定版本的[原始RAG摘要页面](https://arxiv.org/abs/2005.11401v4)、
[位置敏感性研究摘要页面](https://arxiv.org/abs/2307.03172v3)、
[LoCoMo摘要页面](https://arxiv.org/abs/2402.17753v1)。各页面原始HTML完整保留并计算hash；
保留的是完整摘要页面，不是论文全文。另有标明整理性质的中文笔记，三处关键原始摘要span
单独核验；不将整理笔记冒充原始论文或本地复现。

每条包含独立`g-sources.json`、`continuation-sources.json`、`evaluation.json`和`task.json`。
G资料共11份（含3份论文页面），两个后续增量各1份；未来问题、标签、评分条件和新增原件
均不进入G包。12项必要条件都有来源路径、URI、精确字符范围和摘要；沿用已有
`file_material`与`evaluation_contract`实际验证身份、完整内容和来源span。
语义评分仍需实际交付及可靠来源核对，不因span存在就PASS；论证整体质量、营销效果和
未列事实保持未评价。首次实际交付/下游使用为观察边界，未交付草稿不自动算错。

保留每条G/A/B＋B表示＋B结构，共20个D5候选会话；D4仍另需新的开发G/A/B。
表示暂限定完整文本的Markdown/JSON包装，明确不证明分字段语义组织不变性。
四种结构扰动分别分配；操作必须适用于实际G产物，不能为了凑变体强迫业务schema、添加
合成业务字段或删除有含义的首尾。实际不适用、L1机会不符、表示被序列化消除均分别记录。
尚未生成G，所以当前不能确认四条都已有合格分层/变体机会。

开发者已查看资料和判据，标为`OPEN_REVIEWED_NOT_BLIND_NOT_USED_FOR_TUNING`，不称盲测。
这些任务尚未用于Host/模型调参；如果以后据模型失败修改实现，应按Goal转为开发材料，
不能修好后追认为独立确认。

具体开发缺口：现有`run_v02_e2e_generality`只处理G前统一来源，尚不能在G后把新原件等同
送入各续做分支。不得直接把continuation包交给旧prepare，否则未来修订会提前进入G。
下一增量实现通用的阶段来源更新：公开捕获、独立分支映射、完整文件更新、保留原G/H*，
再补独立的真实保存/冷恢复变体编排。不是新增Memory数据库或业务路由。
索引无模型授权、不是现有runner可执行配置；正式运行仍受完整D1–D3、D4及成本/额度约束。

验证：4个初始包与4个续做包通过现有文件合同，4个评价合同/12处来源span通过；3份HTTP200
原始页面的hash及摘要span已核验。Lab451通过（4.49秒），boundary/Ruff/mypy30/build通过。
没有新增代码行为，无需重跑Product套件；无迁移/权限/Canonical/公网改动。
新增实验模型/tokenize/付费0，总账仍69请求、1,304,756 raw；Schema仍NO-GO FOR SCHEMA FREEZE。
