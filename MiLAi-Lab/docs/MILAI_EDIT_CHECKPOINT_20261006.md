# MiLAi-Edit 当前实验检查点

快照：2026-10-06 12:05:32 Asia/Shanghai。保留 I2、B0/B1/B2/M 与现有
Qwen3.6 家族。**条件绑定已有真实形成证据，M 范围、例外撤销和最终读取仍未通过；
没有最终候选、四组完整方法比较或方法优势结论，Product NO_GO。**

本次按用户要求整理并提交报告。实际运行源码固定为
`497b8d89f37ebe795e1e79f8791fe5ddd9289ed9`；此前报告/原生配置声明提交为
`22f4b84e24a7993339419f491127732df52a784b`。报告提交不改变正在运行的算法或配置。
PR #85 保持 open、draft、未合并，基础仍是 PR #84 开发分支。

## 已完成与正在运行

| 范围 | 实际进度 | 结论边界 |
| --- | --- | --- |
| `497b8d8` 条件绑定、非思考 | 两分支 80 次，162,068 known token，80 stop；Root 复核 44 事件、36 回答 | 条件确实形成、普通更正保留未重述限定；范围、共同条件更新及撤销仍失败 |
| 同源码共同原生配置 | 原分支 44 次，197,788 known token，44 stop；Root 复核 24 事件、20 回答；共同分支 0/36 | 消除了本分支截断，M 范围/撤销仍失败；B1 Writer 有保持与撤销正例，最终 Reader 仍未完整 |
| `2335ea9` 思考模式、8,192 输出 | 80 次，348,003 known token，71 stop、9 length | M 实际选择增加/撤销例外；两次初始形成截断，不能算旧限定保持成功 |
| `8ed7826` 非思考及来源控制 | 132 次，236,165 known token，全部 stop | 普通更正改善；范围、撤销及无依据助手强化的归属仍失败 |
| 旧 `4357d46` 完整历史 | B0 277/277；B1 115/277；B2/M 各 0/277 | 剩余范围延后，未取消、未补零，尚无四组完整比较 |

非思考条件绑定的 80 次包含 44 Writer、36 Reader、零 Judge；35 committed、
4 rejected、1 no_change，另四个空 envelope。操作计数不等于语义成功率。
B2/M 在两个分支都实际形成两条 condition 和两条 modifies，八次普通更正保留
未重述限定。但 M 仍以 change_value 覆盖一般规则，撤销时删除仍有效的共同限定；
共同条件事件还重复选择同一内容目标、提出错误新值而被整事务拒绝。
其他组同样出现一般频率丢失、矛盾旧限定或新开始时间漏写。
拒绝后的状态不变、目标从未形成、后来重申修复，均不抵消此前维护失败。

四组原分支无新事实查询保持实际状态、版本和支持不变；M 使用合法 no_change。
不能写成四组都返回空提案。Root 复核不是独立 Judge 或独立的完整数据库审计；
这些 R3 分支来自同一个已曝光开发来源，没有读取保留用户。

## 当前原生配置对照

四组各分支从自己的空库运行既有原 44 / 共同条件 36，统一设置
enable_thinking=true、temperature=1、max_tokens=32,768；方法、说明/schema、
Reader、评分器及其他预算保持冻结。其他采样参数保留现服务默认，不称完整厂商
最优配置。生成条件收益与 M 方法贡献分开报告。

原分支于 12:02:20 完成 44 次，24 Writer / 20 Reader；84,716 prompt + 113,072
completion = 197,788 known token，44 响应均有原生 reasoning，包含在 completion
内，只计一次。44 次全部 stop，无 length。15 committed / 2 rejected / 1 no_change，
另六个空 envelope；四组查询均为空且实际状态完全不变，另外两个是 B1/B2 重申。
这些计数不当作语义成功率。

Root 已阅读全部 24 事件的实际输入、提案、回执、前后状态和 20 回答，核对 44 对
HTTP、prompt 投影和 usage，以及连续账本。B2 实际形成两条条件/两条关系，
M 形成一条节假日条件/一条关系，开始未定作为另一 content 保存。

| 方法 | 这次实际行为 |
| --- | --- |
| B0 | 普通更正的新频率有当前证据，但把旧复合限定拆成 h-only 新 clause，被字面支持规则拒绝；范围更新又丢一般频率和限定 |
| B1 | 插入单独夜班例外，随后只删除例外单元；一般三次及两个旧限定均保留。Writer 是有限正例；撤销后及最终 Reader 仍拒绝给出完整日/夜班频率 |
| B2 | 普通更正正确保留条件；例外提案删掉一般规则并复用旧绑定，遭拒；随后 no_change 因例外从未形成，不能算成功撤销 |
| M | 夜班事件用 change_value 覆盖一般规则，撤销时 retract 节假日条件并留下夜班四次；后续重申才用 add_exception 补回节假日暂停，没有 remove_exception |

四组最终 Reader 均未完整回答班次频率。M 的晚期 add_exception 不等于先前正确
增加夜班例外；B1 保存后的规则仍存在却未被完整使用，也不能归为 Writer 丢失。
共同条件分支已声明、尚未启动，下一步仍使用同一冻结源码/配置继续；没有取消。
预声明中的 actual0 保留为调用前历史记录，不能当作当前运行计数。
当前报告没有新启动模型请求，没有修改队列、重试未知请求或修补截断 JSON。

连续账本 36,286 → 36,330 请求、139,019,217 → 139,217,005 known generation
token，差额 197,788 与 usage 一致；charged 139,268,707。历史 generation unknown=2、
embedding unknown=0 保留，无新增 unknown 或 embedding。进程已退出、账本稳定、
串行锁释放，当前没有模型队列运行。运行原终态与首次失败全部保留。

## 新发现与本地工作

普通 SDK 的 kept_support 收集只遍历旧 units/relations/edits，遗漏新 clauses 中的
条件正文和绑定支持。真实 SQLite 重开、fresh record read、五个不同旧支持范围的
fixture 已复现拒绝；源码 owner 报告最小遍历修复及该模块 77 项检查通过，尚未 Root 复核、提交或
准入后续模型实验。本次报告不包含这两个源代码/测试文件，也不混入冻结源码。

必要旧原文重发仍只有只读设计，没有实现。应沿用实际来源读取和交付，不把未发送
正文算作模型已收到，也不弱化 h-only 字面保持、来源身份、版本或权限规则。
Reader 把来源报告日期过度理解成事实自动失效的现象也需单独复核；当前队列没有
热改 Reader。继续减少无效选择，避免追加提示警告、审核平台或模型家族部署。

## 工程检查与剩余工作

冻结源码的 440 项受影响检查、Ruff、strict mypy、24 份默认关闭合同及依赖边界
已通过。2026-10-06 11:59 查询确认其自身
[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37408624077) success，
[Full](https://github.com/minguselandy/MiLAi/actions/runs/37408624028) success，
Full 21/21 job 成功。报告 `22f4b84` 自身 Fast success、Full 仍 in_progress；
本次新报告提交的 CI 需按新 head 单独查询。工程通过不替代语义通过。

本次报告的 JSON/计数/成本/账本检查、59 个本地链接、6,440 tracked paths 依赖
边界（零 findings）及 staged diff 检查通过；冻结源码与配置匹配。只提交七个
报告/状态文件，未重复运行源码测试，未提交 SDK 修复或原始实验产物。

下一步继续已声明的共同条件分支，并独立复核 SDK 最小修复。关键短历史、
来源行为和共同配置满足后，才能进入四开发用户前八会话及事前选定第一用户长历史，
随后完成同版本四组完整历史。旧延后历史、原生机制/漂移、同 M 低层/语义入口消融、
一次较紧预算、16 保留用户、LongMemEval 与现有基线、Host 功能和恢复仍在计划内。
完整 R0–R5/E0–E5 和六项交付尚未完成。

本次只提交 Lab 报告和安全聚合；Product Schema/API/权限/Canonical、运行源码与
配置原件不变。raw、gold、HTTP、reasoning、数据库、日志继续 ignored。
回滚参考 `22f4b84`，不回滚实验原件；没有合并操作。

[原生配置 44 次结果](../data/manifests/milai-edit-post-b0-native-capacity-results-20261006.json) ·
[当前机器状态](../data/manifests/milai-edit-v2-current-status-20261006.json) ·
[条件绑定 80 次结果](../data/manifests/milai-edit-post-b0-bound-clauses-results-20261006.json) ·
[原生配置预声明](../data/manifests/milai-edit-post-b0-native-capacity-development-20261006.json) ·
[完整进度](MILAI_EDIT_V2_PROGRESS_20261005.md) · [复现](MILAI_EDIT_REPRODUCTION.md)。
