# V0218 T3 首两个纵切：真实动作与冷读初步审计

状态：**建设未完成，G-TESTBED 未通过，E0–E5 未完成。**
本报告不是完整 V0218 终稿，也不是 ClawMark 原生成绩。

## 范围与完整成本

数据/冻结实现/实际请求/业务数据库均在 Git 外
`/cra/memory/mx_memory/evidence/v0218/20260910/t3-note-chain-v{1,2,3}`。
业务工具只改变本地适配 SQLite 世界；Note 通过隔离不可变 Product 公开接口提交/冷读。
当前 Product 工作树全局 pin 漂移仍保留；本批实际交付物独立 lock 与已安装 wheel 对比通过。

| 尝试 | 实际生成 | raw token | 结果 |
| --- | ---: | ---: | --- |
| v1 兼容 | 2 | 145 | 写入动作缺参，业务任务未启动 |
| v2 可见 schema 修订 | 80 | 165,019 | 5 episode 已启动，重复缺参，最终输出解析失败；业务状态均未完成 |
| v3 必需 JSON 字符串参数封装 | 72 | 125,609 | 2A + 8B 全执行，进入真实业务结果审计 |
| 全部建设尝试 | 154 | 290,773 | pending=0、bound violation=0；无 Judge/embedding/OCR |

v1/v2 不计有效比较，不从成本与流程账删除。v3 在所有臂使用共同协议修复，
未换 root/业务规则/checker/旧 Note 内容，没有额外兼容生成。
每 episode 上界 16，最后一次保留交付；原 60 秒请求/900 秒 episode/9600 秒整批边界保留，
累计 raw-token cap=null。隔离 API 和 PostgreSQL 均已停止，卷保留；没有停止共享模型/服务。

## v3 完整结果

| lineage | A 业务 / 自写 Note | Stable N0 / N1 | Superseded N0 / N1 |
| --- | --- | --- | --- |
| executive_assistant/task2，日程 | PASS / 1 次公开提交 | PASS / PASS | PASS / FAIL |
| insurance/task3，理赔 | FAIL / NO_WRITE | PASS / PASS | FAIL / FAIL |

日程 A 实际创建两条合法日程，保存的自由 Note 描述两次面试时间、房间、面试官。
本次由同一开发代理作**非盲语义复核**（不是独立人工评审）：所陈述事实均与 A 当时有效记录一致。
Note 未被开发者重写。N1 的 Stable 与 Superseded 分支分别由 harness 将这条实际 A Note 逐字
复制到新 scope，再由全新 Host 通过公开 Note ID/version/content digest 精确冷读。

Superseded 日程：N0 更新到当前线上模式/新时段，通过；N1 虽收到确定的当前事实，
仍提交“请确认是修改预订还是当前可用性有误”的待核验请求，未修改旧预订，失败。
确定事实下的多余暂停不计有效 SUSPEND；CAS 错版本被拒绝后成功重试待核验动作，
只证明机械错误可修复，不算业务/记忆恢复成功。

理赔 A 按 167 分钟、每完整小时 200 的公开规则应记 400，却真实写入 600，且 NO_WRITE。
Stable 两个 B 都将其修为 400；Superseded 两个 B 都多余暂停并保留过期的旧审批。
此 root 没有 A Note，因此 N1 没有笔记处理差异；不能把它算作第二条自写记忆链，
也不能把两臂共同错误归因于持久 Note。未按 NO_WRITE 或答错替换它。

## 实际请求链分母

`chain-audit-v1.json` 核对保存的 HTTP 请求原始 bytes/hash、已结清请求 ID、HTTP 200、
请求中初始 Note 字符串及后续 current 证据内容/hash，不仅依赖 Host 的 presented 字段。
每个 Host PID 不同，前一个退出才开下一个；各 B memory scope 事先公开列举为空。

- A attempts=2；自主写 Note 的 A=1；NO_WRITE=1。
- B attempts=8；公开精确冷读旧 Note=2；旧 Note 实际发送=2。
- 当前业务事实实际发送=8；同一请求含旧 Note 与当前事实=2。
- 有上述双呈现证据的独立 lineage=1（不是 2）。

Stable 保留合法状态与 Superseded 必须修订分别判定；两种世界并非两个独立 root。
这些是小规模开发观察，尚未跑强基线 N2、跨 lineage 复验、适用范围/Helpful/真正未决覆盖，
不声称已证明记忆负效应、候选机制收益或创新性。

## 剩余建设与实验

已建 2 lineage/2 family，目标 12/≥3 尚有缺口；checker 校准与第二条合格自写链也要继续补齐。
按先前冻结顺序继续审查下一来源，不按当前失败定制反证/选择题目，不强制生成理想 Note。
G 未过前不开发记忆候选；完整 E0–E5 与创新决策报告仍是本 Goal 必需工作。

本阶段 Lab 回归：850 passed、1 optional SDK skip；boundary、Ruff、mypy、build 通过。
随后新增下载完整性测试 4 passed，下一次全量检查应包含它们。
