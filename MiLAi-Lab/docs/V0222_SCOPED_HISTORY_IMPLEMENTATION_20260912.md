# V0222：同 bytes 历史账适配实施

日期：2026-09-12。状态：`LOCAL_INDEPENDENT_REVIEW_AND_FULL_REGRESSION_PASS / BATCH_INTEGRATION_IN_PROGRESS`。
这是[V2显式接线设计](V0222_SCOPED_ADMISSION_V2_DESIGN_OFFLINE_20260912.md)的历史账实现，
不是新实例授权，也不恢复任何旧停止批。主代理实现，`/root/v222_review`独立审查。

## 已实现

[scoped_history](../tools/v0222_scoped_history.py)新增两个显式scope入口：

- `historical_usage_from_pinned(scope, sources)`：有序绝对路径/hash，前两账legacy，后续v2；
  同一核验bytes解析JSONL，复用原accounting/usage_state，额外核验真实用量与预约边界及全局请求唯一。
  legacy未知完整保留，任何后续v2未知/未完成/违规拒绝；不把中央镜像重复计费。
- `presentation_history(scope)`：源码固定已独审57账inventory路径/hash，不接受调用者替换未知白名单；
  重新读取全部账、计算总数并严格比较完整旧未知对象，区分bool/int/float。

原FSM并不自动发现缺少BOUND_VIOLATION标记的超额，本版显式要求prompt与预约相等，
completion不超过output_cap，total不超过raw_upper_bound。原legacy/FSM/旧Batch代码不变。
generic全结算分支的actual_total包含v2费用，不能沿用仅legacy的旧中间值；它的
new_generation_allowed也仅是费用状态，永远不是发送授权。

语义异常会poison调用方scope，即使异常被捕获，close仍失败；返回对象不能污染下一次结果。
JSONL每次重新解析，helper的json_parses只统计JSON文档，不统计JSONL。调用者必须等待close成功，
本次两个内容观察不是连续不可变快照，不允许跨HTTP保存PASS。

最终module SHA256 `8fa5b47fe55d4a8a8b1999cf1f26f27f045aa53da2280a8edf8ecf7b9a039942`；
[测试](../tests/unit/test_v0222_scoped_history.py)SHA256
`98933c8b13c96a5adb97790dde0380fc06166f199ebe6057f49bc660c1bb5ab4`。

## 验证与实际历史

76项history局部测试，独立与64项adapter、46项scope组合共186PASS（1.62秒）。
初次70项通过后，审查建议补4种usage.total_tokens错误及2种legacy提前/重复SETTLED；
新增测试首次引入一处E501，已仅格式换行修复并同版复跑通过。Ruff、boundary、Mypy39源、build通过。

实际只读复算57账：58请求、1081429已知raw，唯一旧未知预约28284完整保留；
actual_total_raw_tokens=null、reservation_is_actual_usage=false、new_generation_allowed=false。
第13个正式FAIL请求的26739raw包含在新增13请求449759raw中，没有漏账或将FAIL升级为PASS。
共inventory＋57账58文件，首次和收口各178499bytes／58hash；只解析1个inventoryJSON，另解析全部JSONL。
单次组件观测从import后开始，总0.02134秒，不是完整冷worker或阶段耗时证明。

外部工程目录`/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/`：

| 制品 | SHA256 |
| --- | --- |
| scoped-history-r1-observation.json | `83f4b820737f9e809f5642f5450f96f8d546c03d72e1bc43a491c66d25679a17` |
| independent-scoped-history-review.json | `d709fc39f971ee3074b3eecfa996bc2f8ace60c9ab2c1ba57f456a849a17a967` |
| scoped-evidence-r2-engineering-checks.json | `3df4a8128e3cfdcf50da262a432c3b10692286fa778c7ccce849725ff3fc6983` |

主代理重核上述4／9／4项依赖hash一致（a38911）。前一R2全仓回归89818已2498PASS／1skip，
1209.05秒，但不覆盖随后新增history；该旧进程已terminal，不再重启或等待。
新全仓pytest **session50243**现已terminal0（501e90），2574PASS／1optional SDK skip，1217.35秒。
六个组件源码/测试保持稳定（8ba2bc）。该回归不覆盖其后新增的lineage和Batch核心模块与测试。
工程制品`scoped-history-engineering-checks.json`保存此独立基线。
其他当前工程检查5bab83中boundary/Ruff/Mypy通过；build session43258 terminal1222df通过。

## 下一步Batch接线，不以组件替代完整实验

本模块自身没有验证inventory完整依赖树、四个旧中央SQL当前停止锁/终态/镜像，也不读取当前动态episode账。
后续[lineage与Batch核心](V0222_SCOPED_BATCH_IMPLEMENTATION_20260912.md)已开始实现这些责任，
不能给动态账现场计算hash后假装是冻结历史。
新增模块未创建正式root、未发送HTTP、未执行GPU/设备/容器操作或读取凭据。
复用的纯FSM模块会传递导入tokenizer/configuration工具，但不初始化模型或执行本地推理。

`/root/batch_guard`只读调用链审查确认：旧成功P3冷worker有15次authorize、14次check_journal、
4次record，对应4次真实HTTP；父进程finish/gate另有重复工作。新版须显式合并同一操作内的重复入口，
但两次identity、tokenize、generation各HTTP边界独立scope，不跨边界复用成功结论。
必须实测完整worker、父finish/gate及16＋条件24矩阵，不能拿单history或单tree速度作阶段通过证据。

另一个接线要求：原基类record即使是用量结算也要求episode RUNNING，外部stop后可能拒绝迟到真实usage。
新版须提供受限settle_event：核对精确binding/request/owner/FSM及可信usage，保留停批状态，
禁止新预约、发送和动作放行；不能为记账复活episode或将未知自动变成可信已知。
HTTP必须在attempt/request保存、新鲜准入、scope.close、最终期限检查、事务解锁之后发送；
失败先回滚释放SQL锁再停批，不在持有写锁时嵌套stop。

新Batch部分动态负控已新增，完整实现、真实规模零HTTP冷进程时间证明及具体新冻结范围审查仍未完成。
旧P3为12PASS/第13FAIL，3P3及24P4未运行；P4/E1/E2/M0/M1仍受原前置门约束，整体Goal保持执行中。
