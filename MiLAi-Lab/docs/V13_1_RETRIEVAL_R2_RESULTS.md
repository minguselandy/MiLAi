# v13.1 检索断点 R2

日期：2026-09-30。固定 bank 的单变量开发诊断通过；完整规划仍 ACTIVE。

## 输入与可区分解释

R1 已正确保存“用户通勤时更喜欢选择火车”，但 query“通勤方式偏好”返回空。
最早断点是字面检索未交付；不需要改 bank、额外 writer 或 Attention。
[预先冻结协议](../data/manifests/v13-1-retrieval-r2-protocol.json)与
[公共输入](../data/fixtures/v13-1-retrieval-r2-fixed-bank.json)在候选结果前写入。
原始 SQLite bank 复制到两组，初始 bytes 的 SHA256 均为
`a8ed9e6fc56b011abf96175647dedabcfc50e144aba9060aca143027b17bb7d9`。
新会话 s3 在新进程问相同问题，保持 owner/namespace，不复用旧终态或重写偏好。

唯一源码变量为 opt-in MemoryService 的通用 Unicode 字面分词：普通文字词元和
Han/kana/Hangul 双字符片段，匹配时 NFC/casefold。没有词典、案例 ID、同义词或 dense 新调用。
正文与 query 原文保持；owner、scope、提案、guard、CRUD、排序规则、限额和旧默认保持。
两组完整 runtime freeze 除 service.py 的源码 SHA 外完全一致，包括 prompt/tool catalog。
原代码使用独立 worktree，固定在本地提交 `54e8a96`。

否定条件预先声明：同一 query 仍不交付正确卡，否定分词修复；交付后仍答错，定位 reader 后续断点。
费用限定原 D0 每消息12调用/4096输出/HTTP并发1，全部计入连续账本。

## 结果

[完整身份与结果](../data/manifests/v13-1-retrieval-r2-results.json)。

| 检查 | 原代码 | 通用分词 |
|---|---|---|
| 零模型固定 query | 0卡/0原始事件 | 正确卡1/原始事件2 |
| 零模型无关 query | 无结果 | 无结果 |
| 实际 Host search | 相同 query，无结果 | 相同 query，交付原始正确卡 |
| 最终回答 | 声称没有找到偏好，FAIL | 回答原始偏好是火车，PASS |
| 新记忆提案 | 0 | 0 |

首次实际 HTTP 请求 bytes 语义对象完全相同。temp0 仍产生不同可选 limit：原代码显式5，
候选缺省10；本例结果数低于二者，没有截断。严格相同 limit 的零模型反控与实际传播一致，
但不能将实际轨迹声称完全相同。当前 source capture 的真实时钟也不同，初始 bank bytes 一致。
Root 阅读完整答案、原始源与持久卡进行离线判断，没有用关键词命中代替语义验收。

受影响检查12通过、11 deselected，Ruff/mypy通过；新增检查的首次9失败/1通过和Ruff4项
问题均保留。Root 零模型脚本有一次执行前 SyntaxError，未改 bank、无 HTTP，修正后单独留痕。
没有重跑已通过的全套 architecture/legacy，也没有扩展实验矩阵。

两组新增4次 generation /4908 generation tokens，embedding0、Judge0、unknown0，逐响应
usage 与原账本增量一致。连续累计6177次/11447126 generation tokens/416930 embedding tokens。
I/O 仍为部分测量；未宣称美元或 GPU 小时节省。

## 决策与边界

保留此工程修复。这个单例支持 R1 召回断点的解释，不证明一般召回质量、可用性22/24、
Field-grounded收益或研究优势。原 R1 的3/6、失败提案和成本保持；R2不替换正常24例分母。
下一实验单独处理 update 的 create 提案，随后对正确 scope bank 做 reader 消费诊断。
不把词法修复说成更新/作用域语义修复。完整P0–P8继续，Product NO_GO。
