# V0224 K2 最小候选代理审查

审查者：Codex subagent `/root/gate_review`，依用户授权代行设计审查，非真人。此次只读固定源码，不改任何封存源码/fixture，不实现或计时。以下推荐以 K1 独立验收成立为进入条件，不提前签 K2/A1/A2 PASS。

**推荐的唯一候选：对 `verify_tree` 固定用途提取不可变依赖元数据，消除其不需要的完整 JSON defensive deepcopy；公共 `read_json` 的返回隔离不变。** 暂不同时优化路径标准化，不缓存准入成功，不删首读/收口重新观察。

## 证据能支持什么

K1 提供的55-scope分解约为 JSON_parse_copy exclusive 353 秒、inventory exclusive 242 秒、首/关闭读取169秒；两次运行时准入28.87秒。当前 `read_json` 首次严格解析并缓存，然后每次返回 `copy.deepcopy(entry.parsed)`。`verify_tree` 对绝大多数 JSON 只遍历固定的 `files/dependencies/inputs/hashes/references/entries` 字段提取引用，不修改或向调用者返回整棵 JSON。因此这里的整树克隆具有可说明的纯计算冗余。

但 **353秒不是已测出的 deepcopy 时间**：该观察类别还包含首次 JSON 解析、结构构造以及 `read_json` 内未被其他子 span 分走的工作。5-scope中额外重复read_json只有625/27024，不支持“反复解析同一文件是主要问题”的说法。多数工作是首遇 JSON 的解析加克隆；现有缓存已避免其重复解析。

28.87秒降到18秒至少需要约10.87秒，即约37.65%的实际准入降低。尚不知道上述候选能否达到这个幅度。不能把全部353秒作为预期节省，更不能用55-scope总比例外推单Session或宣称Gate A已可过。

## 候选的精确定义

1. 保留首次完整严格 JSON 解析，包括无依赖字段的业务正文。重复键、NaN/Infinity、非法 UTF-8、嵌套结构错误必须仍被发现；不能只扫描依赖字段而跳过正文的严格解析。
2. 只在同一个活跃 scope、同一份已验证 bytes、原 `verify_tree` 固定用途内访问内部解析对象。由固定私有提取逻辑产生不可变的引用序列及 manifest 识别所需标志；返回值只含不可变 path/hash/标志，不返回缓存中的 dict/list。
3. 不增加可供外部调用者提交任意 callback 的“借阅 JSON”接口，不增加绕过 `read_json` defensive copy 的通用选项。不能指望名字带下划线或一条“不要修改”约定就获得隔离保证。内部可变对象必须局限在固定可信提取路径内。
4. 复用原 `edges` 的字段校验、递归顺序和错误类别，输出引用序列的顺序不变；保留先验证所有直接引用再递归的次序。第一版只消除完整对象克隆，不同时缓存扫描结果或改变调用图。
5. 每次 `visit` 原有 `read_bytes`/冲突 hash 检查仍先发生；保留路径身份、`..`/symlink拒绝、原 `resolve` 行为、第一次和最终新鲜观察。跨scope不共享解析或派生结果。
6. `manifest.json` 即使已在 completed 中，仍按原流程重新执行 `verify_manifest` 的环境、源码/副本/输入验证。元数据中一个“是manifest”标志不是语义PASS。公共artifact返回、SQL/file依赖并集、history FSM、auth/owner/stop/CAS/receipt/期限和父审计全部原样保留。

精确拒绝顺序必须保持：`read_bytes → JSON解析/manifest必备键形状识别 → verify_manifest(源码/副本/输入/环境) → completed判断 → edges字段校验及提取 → 全部直接引用read_bytes → stack判断 → 递归`。不能在manifest验证前提前提取边：例如环境已漂移且edges字段也坏时，提前提取会改变首因。对此增加“manifest环境/依赖失败与非法edges同时出现”的差分反例。

一个可保持单一改动的实现位置是新候选模块的 `verify_tree` 替代函数：专用解析读取器限于该函数词法内部，复用原scope `_entry`、严格JSON hooks、parsed_ready计数和poison规则；缓存中的dict/list仅供这个固定私有遍历逻辑只读使用，不通过导出方法或callback交给外部调用者。先做形状阶段，原manifest验证完成且未completed后才做边提取阶段；对外仅有不可变引用元数据和原 `None` 终态。不新增公共borrow API、不另造第五层adapter。保持原 `_entry`、json_parses和直接引用读的次数/顺序；若新模块通过固定别名接线，只能替换这一verify_tree实现，全部调用点须列明并有未覆盖入口反例。

这是现有依赖闭包遍历的私有返回值优化，不是新的控制框架或行为语义投影。若实现必须改变静态安全模型、引入不可变快照架构、跨准入借用PASS或改动态事务责任，拒绝该实现并返回设计。

## 与路径标准化去重的比较

大量 repeat references 表明路径/引用处理值得解释，但当前 inventory exclusive 242秒包含闭包遍历、边提取、路径处理及其他未单列工作；没有证据证明 `Path/abspath/resolve` 是其中主因。路径缓存还易扩大身份观测生命周期，误吞 `..`、symlink替换或同路径新hash。

所以本轮选择更容易界定冗余、可证明不需要其返回整树的 deepcopy 用途优化。路径标准化候选先保留为未执行备选，不和它捆绑。若本候选不够快，不能因此在同一候选中追加第二种优化再合并最好成绩。

## 必须增加的负控与差分

除已冻结八类负控外，本候选至少增加以下具有区分力的检查：

- 对同一批真实冻结 JSON，用原 `read_json→edges` 与候选比较完整有序引用序列、manifest分支、每种用途与首个失败，不只比较最终PASS或文件数。
- 大型非依赖正文中放入非法JSON/重复键/非有限数，依赖字段本身合法；候选必须仍拒绝整文，证明没有偷换为“只解析少数字段”。测试仅用新合成输入。
- 试图修改候选返回元数据、公共 `read_json` 的嵌套返回对象与artifact返回；任何一种都不能污染后续引用、内部缓存或关闭验证。
- 同scope同bytes由普通tree、manifest与artifact等不同用途依次访问，manifest重复到达后改变环境；所有对应语义校验仍到达且保持原拒绝。
- 重复/菱形/循环引用中后到的hash冲突、缺失子文件、不同字段引用同对象，以及必需边遗漏；保持访问顺序、第一原因和全部close失败附记。
- 每个受影响边界首读后/收口前换文件，跨scope同size/mtime改内容，路径替换；禁止候选复用上一次结果。
- 原body错误后提取/close/rollback/stop失败；固定提取内部异常不许恢复scope可用性，原第一原因保留。完整动态账务/身份/CAS/receipt/父gate不因本次“只改静态”而免验。

## 执行决定与失败路由

代理批准将这一精确候选作为 **K2唯一开发候选**，条件是独立K1报告先成立、候选差异/输入/hash与上述反例先冻结。候选可先做局部语义开发，之后按原合同原/候选各一次U真实前缀、各3600秒外层、原Session60秒，不挑最快一次；不能把新测量移到窗口外或扣除探针成本。

如果局部差分或动态负控失败，候选不准进入完整门，保留失败后做有界新版本决定。如果原/候选比较表明剩余准入仍超18秒余量，诚实报告本轮不足；不以去掉必要read/hash或在同一实例加时过门。允许依V0224提出有新可区分证据的新子合同，但本轮不自动附送第二个候选或新的live配额。

当前结论：`K2_SINGLE_PURPOSE_CLONE_REMOVAL_RECOMMENDED / IMPLEMENTATION_NOT_REVIEWED / PERFORMANCE_UNPROVEN`。最终Gate A仍需完整16+80参考、24效果链、40真实冷进程、A1–A4和当前工程terminal证据。
