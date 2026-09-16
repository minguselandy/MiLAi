# V0222：显式读取作用域准入 V2 离线接线设计

日期：2026-09-12。状态：`OFFLINE_DESIGN / IMPLEMENTATION_PENDING / NO_NEW_MODEL_AUTHORIZATION`。
依据[已停止完整门](../studies/active/MILA_V0222_PRESENTATION_FULL_GATE_20260912.md)和
[读取组件](V0222_ADMISSION_READ_SCOPE_OFFLINE_20260912.md)。本设计不是新批授权，也不是旧批续跑入口。

## 改动目标与不变量

唯一工程变量是：同一次准入中，多处引用同一固定文件时共享已核验 bytes 和解析结果，
退出该准入前再重新读取并核验内容。模型、B1 呈现、D11、全部来源、原16＋条件24矩阵、
原 Session/Adapter/完整 Schema/CAS/intent/effect 验收以及1800/7200/300/60秒限制不变。
不跨 HTTP、事件、worker 或父进程准入保存成功结论；不把首次失败后的补验收写成原 PASS。

旧 presentation 源码、测试、正式实例及其冻结依赖均不编辑。组件现有46项测试在全仓
pytest session6214期间保持稳定；下述新版本实现另作版本与回归记录，不借用旧基线通过数。

## 为什么不能只覆盖一个 reader

现有 authorize/manifest/tree/artifact/history 使用模块级绑定的 read/sha/read_events，
不接受调用方 reader。继承 Batch 无法让这些函数自动共享一个 scope。
旧 admit 与 RESERVED record 分别调用 authorize/check_journal，也没有显式上下文参数。
因此禁止全局 monkeypatch、ContextVar、隐藏 self.current_scope 或临时替换旧模块常量；
新增小型读取适配与准入编排，复用纯状态机及事务原语。

作者侧只读架构核查：`/root/batch_guard`；独立安全架构审查另由`/root/p0_audit`进行。
代码入口：[旧准入](../tools/v0222_presentation_batch.py)、
[旧事务/事件状态机接线](../tools/v0221_http_batch.py)、
[原证据校验](../tools/v0220_evidence.py)、[原 artifact/tree](../tools/v0222_boundary_batch.py)。

## 最小接口与责任

第一层拟新增 `tools/v0222_scoped_evidence.py`，所有读取显式接收 scope：

| 接口 | 必须保留的验证 |
| --- | --- |
| verify_manifest(scope, root, sha) | manifest本体、源码、executed-source副本、完整inputs、Python与包版本 |
| verify_tree(scope, path, sha, seen) | 原明确files/dependencies/inputs/hash引用以及references/entries；不追踪任意模型字符串 |
| read_artifact(scope, row) | 当前SQL行的path/hash、行内依赖和文件内files的完整并集；冲突hash拒绝 |
| read_pinned_events(scope, path, sha) | 从同一已核验bytes解析固定历史JSONL，原状态机和计费语义不变 |
| historical_usage_from_pinned(scope, lineage) | 旧两份legacy账和后续v2账分别校验；只承接唯一原未知 |

SQL依赖与文件内files不必拥有相同key集合：旧实现检查两者，本版也检查并集，
不能为了“去重”仅选其中一份，也不能无依据将相同key集合增设为旧合同等价条件。
树遍历的seen只在当前scope有效；同路径冲突hash不能因seen直接跳过。
seen只用于终止同一引用树中的环，不代替不同用途的语义校验：路径此前read_bytes通过，
不能让后续manifest执行副本/环境检查或history FSM因“已读过”被跳过。
业务值对象不能影响后续返回值，原helper的同bytes解析、deepcopy和失败污染均保留。

第二层拟新增 `tools/v0222_presentation_batch_v2.py`：

- 内部 `_authorize(stage, scope)`、`_check_journal(db, scope, inflight=...)`、
  `_ready(db, stage, scope)`明确传递scope；授权构造接收已核验history而不再次隐式读取。
- 对外 authorize/admit/http_admit、RESERVED record、claim/launch、artifact/gate/finish 等
  明确拥有各自生命周期；返回成功之前必须完成scope.close。
- `transaction/events/stop`可复用原事务原语；usage_state/accounting/fingerprint可复用纯函数。
- 原独立审计器第一版保留其完整工作，不以去重为由省略父审计、gate重算或公开效果检查。

旧 Transport 也直接调用44账历史函数，旧入口硬编码ROOT及Batch类；后续需要显式的新
prepare/preflight/Transport/Provider/worker/runner接线。不能只加新Batch就宣布端到端完成。

## 每次准入的时序与动态状态

在新鲜事务内读取当前SQL状态，创建本次scope并完成固定文件核验，然后close；
close之后、返回或提交之前再次核查期限与必要动态条件。不得让第二次hash耗尽窗口后仍返回准入。
scope不跨真实HTTP保持打开；不得在持有SQLite事务锁期间发送HTTP。
顺序必须是保存attempt/request→新鲜准入与scope.close→最后动态检查及事务提交/解锁→bounded HTTP；
不能准入后再执行大量证据写入却仍凭旧期限结论发送。HTTP timeout仍取阶段/episode剩余期限。

动态SQL的stop/binding、episode顺序/状态、owner/PID、launch、cap、阶段/episode期限、
唯一自身inflight预约、中央/地方事件镜像、usage FSM、P3→P4 gate均每次重新读取核对。
动态episode JSONL没有外部冻结hash，不能现场算hash再传scope假装已被固定证据约束。
它们须在本次事务中读取，与当前中央事件/FSM比较；不能缓存到下一事件或HTTP。
USAGE_KNOWN等已发送回执结算仍需保留迟到记账能力，不得因时间过期丢弃实际成本。
scope.close失败时先退出/回滚原事务，再按精确root＋binding停批；不在已持写锁的事务中嵌套stop。
首个失败原因保持，后续收口/停批异常附记，不覆盖原因或抹掉原始回执。

两次内容观察不等于持续不可变或文件锁。上述锁仅保护合作方的SQLite事务，
不赋予外部文件连续不变性；文件变化检测能力必须如实描述，不能宣称无限并发篡改保证。

## 历史与旧终态

旧正式P3停止永久保留：12正式PASS、第13FAIL、3P3和24P4未运行。
新历史合同必须纳入这次13份新增独立ledger及其终审，共57份ledger，不再沿用44账版本当完整历史。
预期累计是58请求、1081429已知raw、唯一旧未知预约28284；总实际仍未知。
需要核对实际路径、精确hash、事件状态机及各旧中央只读终态，不能只硬编码总数。
中央镜像不重复计费，第13个失败episode的已知usage不可漏掉；原12PASS不能抵扣任何未来新矩阵位置。
后续新版本/root/阶段额度/到期和范围审查仍须另行冻结；本设计不签发这些权限。

## 可证伪的验收次序

1. 读取适配局部测试：原校验接受/拒绝对照，源码与副本漂移、包/Python漂移、漏依赖、
   hash冲突、树环、严格JSON/JSONL、原未知承接和新增未知拒绝。
2. 新Batch动态负控：两次HTTP间改文件/停批/账本/owner/期限必须失败；
   收口耗尽期限拒绝；失败scope不能返回成功；scope不跨边界，不能空scope代表全量校验。
   当前动态账不得因被塞进artifact依赖映射而进入固定文件缓存；测试先byte验证后语义检查仍必达，
   收口抛错后停批不嵌套写锁，迟到结算仍保存而不恢复发送资格，以及保存→准入→解锁→HTTP顺序。
3. 完整Mock16P3→24P4、新事件与失败分层、冷进程边界、原审计/World/readback，
   不以synthetic PID测试代替真实冷子进程成本证明。
4. 实际规模的零HTTP回放：匹配固定依赖数量/bytes/JSON和重叠结构，记录完整worker、
   父finish/gate、每准入初次/收口读取/hash/parse/bytes及墙钟/进程CPU；不得缩矩阵或延长限制。
5. 独立审查、全仓工程检查、具体新冻结范围审查之后，才讨论真实HTTP发送。

## 当前实际规模观察，不是执行性能通过

外部观测：`evidence/v0222-admission-offline/20260912-read-scope-r1/scale-observation.json`，
SHA256 `1bd83199f3ca7b2301632c9058ade3d8c0627726e3962527967441a2987db47a`。
四映射60/4486/5457/5784共15787引用、898311847引用bytes；并集5784文件、331047898bytes。
另读3控制JSON后scope实际5785首次＋5785收口hash，每遍332178630bytes，重复引用10005次。
一次观测总墙钟3.22838秒、进程CPU3.22783秒；只解析3控制JSON，其余JSON只验bytes/hash。
并行全仓测试未暂停、未清理系统缓存，没有独占资源或稳定速度保证。
此结果不含动态SQL、完整history/tree语义、HTTP、冷worker或父审计；不能据此宣称P3能在1800秒内完成。

独立复算随后通过：5266绑定JSON＋终审控制，共5267份严格解析无误且收口hash通过，
该扩展工作量总墙钟7.65397秒，不与上述仅3解析的时长作等工作量比较。
独立制品`independent-scale-review.json` SHA256
`32575c9bfce7519723450299033035bee8c92a4aa15b272b387d15567d719ce9`，
状态`OFFLINE_SCALE_AND_JSON_COMPATIBILITY_REVIEW_PASS`；仍非完整接线/阶段时限/真实发送证明。

另对检查过的旧Batch只读构造器做cProfile（未调用transaction/admit/initialize/launch/record/finish）：
总墙钟3.84110秒，authorize累计3.827秒，其中lineage3.007秒；sha函数13130次累计2.018秒，
manifest validate8次累计1.631秒，read3234次累计1.238秒。累计行相互包含，不能相加。
这进一步定位旧代码中的重复工作，但与上述scope工作量不同，不能据此给出加速比。
构造器本身不检查当前批停止锁，返回对象也不构成任何准入；旧批仍永久停止。
profile制品`old-constructor-profile.json` SHA256
`848f3a5eb8ad3fe5fbb2ef459b4bb66e685e15197f3b53ae52411da5b779cf0c`。
