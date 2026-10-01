# v13.2 暂停与GitHub提交快照

2026-10-01，用户指令：“暂停当前实验，提交到github上”。Goal状态为 **paused**，实验未完成。
记录时间：2026-10-01T07:34:00+08:00。当前模型运行和Source开发均已停止；暂停后仅对已有文件做收集、对账、保存和发布。

## 当前结果

D0旧cohort、D1来源/CAS、D2确定性投影及D3有界交付取得限定工程证据，具体执行身份与验证范围见[执行记录](V13_2_EXECUTION.md)。这些证据不构成完整方法验收。

| E0原24开发cohort | 完整轨迹 / 实际HTTP最终回答 | Root事后诊断 |
| --- | --- | --- |
| R0 | 24 / 48 | 18 PASS、5 FAIL、1 UNKNOWN |
| R1 | 24 / 48 | 20 PASS、4 FAIL |
| R2 | 24 / 48 | 19 PASS、3 FAIL、2 UNKNOWN |
| R3 | 24 / 48 | **NOT_SCORED**，完整评分未完成 |

R3原24全部进程退出0，48回答均与实际HTTP原回包链接。[公开只读审计](../data/manifests/v13-2-e0-r3-unscored-results.json)保存每消息回执、trace及原回包hash，没有合成答案或聚合通过数。先前局部Root查看仍见旧语言/会议历史遗漏及将问题写成长期个人素食偏好的现象，仅作为未完整评分的诊断线索。完整语义/来源/回执评分、独立Judge、SDK重开和全部actual-wire预算复核尚未执行；不能把24完成计为24成功，也不拼接R0–R3最佳答案。22/24及两旧更新完整修复门禁仍未通过，Product为 **NO_GO**。

固定fd1源码的100/1k/10k Source基线完成420次测量，保留全bank缓存变慢的负结果。10k普通构建p50/p95约114.0/116.7秒；此限定离线SDK基线没有真实嵌入质量、完整对象/操作流或长程收益证据，D5-10仍PARTIAL。

## 费用与冻结身份

R3新增120次generation、462,391已知生成tokens和49次embedding、20,342 tokens；与原连续账本逐trace对上，新unknown为0。semantic_boundary分类writer25次、91,005 tokens；其余95次、371,386 tokens保留collector分类限制。

暂停时原连续累计8,611次generation、22,576,650 charged / 22,546,263 known生成tokens、840,103 embedding tokens。历史unknown generation为1、保守未知费用30,387保持；embedding unknown为0，美元/GPU小时未测。账本SHA256：`9ba23552d639ba4703253c5a1bbb6f8a2501eca3e77cf5fb21a8e4c090b53795`。

R3执行源码为`1e329a44d10fd4600ffecb737f2dde1e842249d6`，208文件紧凑map为`4fe85502d25d807d823ecbd9d6f0350ff8c21fdece0011fdd3ac91dbe4a03fca`，暂停时实际字节仍相符。原589行计划及其SHA原样保存；48项requirement逐项状态保留，顶层状态改为PAUSED。

## 未完成工作与代码保存

- R3完整评分、独立复核、SDK重开与全部实际交付核查。
- D4同能力四臂、第二工作流24轨迹及12/24分轨。
- D5新独立来源pilot、正式比较、独立Judge、第二模型家族、公开任务执行、泛化、正式统计和完整复现。
- 条件消融、恢复/生命周期、迁移/删除及其他未满足门禁；完整列表见[48项映射](../data/manifests/v13-2-requirements.json)。

主提交分支：`feat/lab-evidence-incremental-v13-2-20261001`，基于`95bf708bfd8aac9f7855485166e3bf739928b949`，包含已提交Lab实现、公开证据及暂停记录。全部新运行行为opt-in，旧默认保留；Product API/Schema/权限/Canonical未改。现有限定测试与边界证据见阶段验收；暂停后不再启动测试或实验，远端CI不预先计为通过。

未验证WIP分支：`feat/lab-v13-2-derived-index-cost-20261001`。只涉及`grounded_memory.py`与`v13_1_d0.py`中的opt-in派生raw-index存储草稿；尚无完整验收或性能比较，未进入主执行源码，不能据此声称加速。精确两文件hash及本地patch hash见[机器暂停快照](../data/manifests/v13-2-pause-summary-20261001.json)。

私密正文、原始HTTP/运行日志、SQLite数据库、模型、token和ignored运行产物保留在本地，不加入Git。本次发布为独立分支及草稿PR；不合并main。恢复实验须有新的用户指令，并沿用原冻结与连续账本，保留全部失败和未运行项。
