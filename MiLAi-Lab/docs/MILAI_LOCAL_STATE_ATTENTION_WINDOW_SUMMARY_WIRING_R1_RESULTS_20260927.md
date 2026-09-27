# 滑动窗口＋摘要：小接线 R1

当前切片已完成，用户要求的 Goal 暂停已执行。四条轨迹、八个 phase 进程、24 条消息全部
完成；不再启动修复轮或其他实验。执行源码为 `bc5a5c8b98db8b965432759bdea367c9475869b1`，
全批保持冻结。[协议](../data/manifests/local-state-attention-window-summary-wiring-r1-protocol.json)
及[精简结果](../data/manifests/local-state-attention-window-summary-wiring-r1-results.json)保存输入、
顺序、容量、逐消息判定和实际证据哈希。

| 方法 | interleaved | partial | strict合计 | 完整轨迹 | 生成调用 | generation tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| window_summary | 4/6 | 5/6 | 9/12 | 0/2 | 20 | 19703 |
| full_history | 6/6 | 4/6 | 10/12 | 1/2 | 16 | 18501 |

这是同源码、已暴露输入、每格一次的接线比较；不能当作稳定效果或大历史压缩结论。
先前完整历史 R1 仍原样保留，不用本批更有利的片段替换旧轨迹。

## 合同与验证

`window_summary` 保留最近两个闭合的 COMPLETED 回合和当前完整 ReAct 前缀，更早的新
移出回合连同旧摘要更新一次短摘要。每公开消息最多一次持久计数的尝试；同 Host，控制
max_tokens2048、总控制容量13、摘要上限16000 chars；Host4096/12，窗口65536，HTTP并发1。
摘要正文与 covered owner ordinal 同键提交到现有 Store，原 checkpoint 不改写。

两臂共享 `read_history` 工具、普通 memory 与业务工具。摘要输入不含当前任务、未来消息、
rubric或observer档案。可选摘要超时/截断/无效输出回退原始完整历史；真实Store错误显式
抛出。owner tombstone 屏蔽旧摘要和历史访问；不完整旧回合仍以真实前缀和journal标注。
这些故障边界没有在本批自然触发，不能称为实测恢复或物理删除。

80项相关测试、目标静态检查、四个零模型prepare和一次离线build通过，哈希见协议。
实际32次Host请求的原始历史部分均与scoped checkpoint对应回合及当前前缀相等；四次
摘要HTTP仅接收新移出的完成回合，旧摘要与上次已提交输出一致。最终Store摘要/游标与
最后输出一致，实际Host system请求确实使用已提交摘要。两臂工具描述/schema相同。
没有HTTP异常、降级、容量失败或重放；两臂均未自然调用read_history。

## 失败链与评分边界

摘要 interleaved 的第三次更新（trace31）是事实保持的首个断点。第一次摘要保存了三项
安排；第二次仍含 R-3/14:30/step-free。第三次输入明确含这份旧摘要，仅新增已完成的
background-revision回合，输出却只保留field kits更新和handout安排，丢失welcome briefing。
这份缺项摘要真实写入Store并送到最终Host，后者回答Room101/09:00/main entrance。
预期简报原安排保持且无业务行动；过程没有截断或预算耗尽。

竞争解释：H1是生成器偏重新近变化，更新全局摘要时遗失不相关旧事实；H2是模型把“更新
摘要”执行成了总结新输入回合，没有正确合并旧摘要。现有证据能定位丢失点，不能区分
这两种模型内解释。接口、原历史可达性和16000字符上限没有迫使它丢弃这三个短事实。
Host在缺项时继续虚构、不调用可用历史工具，是后续独立断点。

摘要 interleaved 还将两次实际预约键改为 `workshop_handout_packs`、`workshop_field_kits`；
两条 partial 都把Mira的 `Summit archive crates` 改为单数。数量、地点、包装正确不能
代替精确key要求。两条partial均真实found原预约并用同一ID补标签，最终恰好两次reserve
和一次complete_label，没有重复副作用；这项操作恢复单列为2/2。

完整历史 partial 的恢复回答还声称 **“No physical dispatch has occurred.”** 两份实际
回执均无物理发货观察，原请求明确要求不推断physical dispatch，因此主strict判定该消息
失败。这不是数据库恢复失败。若辅助口径只看动作/要求字段并忽略此越界断言，则该臂为
11/12；主报告保留10/12，并公开这一个评分边界，不把它藏入动作正确率。

Mira门禁D-2/10:15及Noel自己事实均保持。最终摘要中的“无预约”描述的是已覆盖的早期
回合，较新的真实预约回执仍在窗口内；不能把明确标注为早期的摘要自动按最新世界状态判错。

此轮不进行提示词微调、扩大窗口、改对象键或更换失败样本。若以后明确恢复，最小诊断
可固定第三次摘要的原始输入区分保留失败与Host取证失败；该建议不是执行授权。当前决定
是按用户要求暂停，保留负面结果，而非宣布整个研究成功或被否定。

## 成本与复现

本批新增36次生成/38204 generation tokens，embedding0。其中Host32/36342，摘要4/1862；
连续账本为 **2677 /3296791 /18445**（generation calls/tokens、embedding tokens），
unknown usage0，历史成本链未改。生成HTTP墙钟合计20.4613秒，不等于进程端到端时延。

摘要臂Host prompt tokens16899，完整历史17555，少656（3.74%），但加入摘要计算后
generation总量反而多1202（6.50%）。两轨迹回答也有差异，此处不是纯压缩因果估计。
该摘要候选在这批短历史中既没有严格质量收益，也没有总token节省。

两臂各9次checkpoint读取；摘要逻辑返回14438字节，完整历史14736。摘要臂另有32次
Store search、16get、4put，完整历史16search。原始checkpoint物理数据仍保留，未实现
存储压缩或规模索引。Root另做8次空namespace查询、8次phase snapshot查询及12个原会话
checkpoint离线核对，均无模型/embedding或业务写入。详细CPU/墙钟/字节见结果。

复现采用执行提交及其锁文件，沿[共同历史复现命令](MILAI_LOCAL_STATE_ATTENTION_HISTORY_WIRING_R1_RESULTS_20260927.md#复现)，
按本协议的四行顺序设置 `window_summary/full_history`、window_completed_turns2、
summary_content_max_chars16000，其余服务参数不变。使用新run/namespace/runtime目录，
两个phase分进程执行，成本续记，原rubric完整分母不变。当前暂停期间不执行这些命令。
