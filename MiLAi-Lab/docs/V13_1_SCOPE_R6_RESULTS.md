# v13.1 scope R6：实际消费通过，对照有边界

日期：2026-09-30。完整规划 ACTIVE。

[R6协议](../data/manifests/v13-1-scope-r6-protocol.json)复制 R5候选实际形成的合法 bank，
保持相同初始 SQLite bytes、原始问句、owner/namespace、完整源码/工具、模型/预算。
两组都有相对时间指令，唯一变量是预先声明的通用“问句不等于事实确认、保留适用范围”指令。
首次实际 wire 仅 system 内容不同。没有重新写 bank 或用事后正确答案构造观察。

[结果](../data/manifests/v13-1-scope-r6-results.json)：原指令未 search/read，回答不知道用户
长期坚持素食；候选实际 search“个人饮食偏好 素食”，获得团队/本周卡及完整原始否定源，
明确据此回答该要求仅针对团队午餐，不能默认个人晚餐素食。两组都无错误个人偏好提案，
最终“不推断”均通过；全部进程退出后的独立公开SDK重开确认原卡与源保留。

因此候选真实 source→card→delivery→answer 链通过，但原指令没有消费 bank，两组不是
相同 delivered material 的严格 reader 对照。不能宣称最终准确率提升或独立结构优势。
这是相同工具/原始档案权限下的自由 Agent 通用提示比较；后续强 Prompt-only 必须得到
同等通用指导。旧 R1错误、R4形成失败、R5反控全部保留。

新增3generation/4046tokens，embedding0、Judge0、unknown0，usage与原ledger增量一致。
连续6200generation/11480939 generation tokens/416930 embedding tokens；完整I/O仍未齐。
决定组合已观察的工程修复，按原始固定输入先跑六故事，再检查24门槛，不修改原rubric。
若组合仍失败，记录最早断点，不将单例诊断改称可用性通过。Product NO_GO。
