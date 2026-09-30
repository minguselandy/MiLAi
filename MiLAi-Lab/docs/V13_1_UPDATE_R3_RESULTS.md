# v13.1 更新提案 R3

日期：2026-09-30。单变量开发诊断；完整规划 ACTIVE，正常24例门槛未满足。

R1 最早断点是用户明确修改已保存偏好时 Host 仍 create。R2只修词法检索，不改变提案。
[预冻结协议](../data/manifests/v13-1-update-r3-protocol.json)保留竞争解释：检索修复可能让
原指令在最终问题上答对，即使及时修订仍失败。单独检查原始提案、原记录版本和最终答案。

先以原指令真实形成一次偏好，bank 只有原始公共消息及一张第一版卡，不包含未来更新/问题。
两组初始 SQLite bytes 相同，SHA256
`f999357049e963f19b8689cca571f855a8684a2f5378db5e4361bf0d8e3ce9e7`。
公共更新和历史查询各由新进程执行。两组源码、工具 schema/说明、检索、guard、权限、模型、
预算完全一致，只有 system_prompt 多一条通用发现与 update 指令；没有偏好答案或任务特定计划。
首次真实 wire 仅 system 内容不同。新配置入口在缺省时保持旧 prompt，冻结的 hash 与实际
传给既有 Agent 的内容一致；MockHTTP包含缺省/指定 prompt 和非法值反控。

[完整结果](../data/manifests/v13-1-update-r3-results.json)：

| 检查 | 原指令 | 通用更新指令 |
|---|---|---|
| 更新消息的原始提案 | create 新卡 | search 后 update 原 ID |
| 更新消息结束 | 两张第一版卡 | 一张原 ID 第二版卡 |
| 后续查询 | 读旧卡后补做 update | 读当前及第一版历史 |
| 最终回答 | 正确区分当前/以前 | 正确区分当前/以前 |
| 全部进程退出后 SDK 读回 | 原卡第二版及第一版可读，但重复卡仍在 | 原卡第二版及第一版可读，无重复卡 |

两组最终都正确，不能宣称答案准确率改善。此例的收益是及时修订、保留历史且避免重复卡。
候选 update 没有填写 scope，当前 scope 为空，原 scope 保存在历史版；不宣称完整适用范围
元数据保存。未添加静默继承、清卡或事后修正，原始提案与当前/历史真实状态均保留。

受影响 runner11检查、Ruff/mypy通过；首次8失败/3通过和Ruff3项问题保留。
所有实际形成和两组调用合计14generation/23053tokens，embedding0、Judge0、unknown0，
usage与原连续账本增量一致。形成占2generation/2148tokens；连续6191次/11470179 generation
tokens/416930 embedding tokens。Store完整I/O仍未测齐，不推断美元或GPU收益。

决定保留这条 opt-in 工程提示候选，没有新结构或 reader 准确率创新主张。若同一原卡不能
及时 update 或正确版本交付后仍误答，将否定充分性并记录下一断点。下一轮独立检验 scope
消费，之后再做合并候选的正常六故事/24检查；旧 R1/R2结果和分母保持。Product NO_GO。
