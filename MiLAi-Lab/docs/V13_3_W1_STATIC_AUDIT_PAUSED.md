# v13.3 W1 当前静态审计（暂停／HOLD）

用户要求暂停并总结后，停止后续审计。此目录只保存部分 W1 源码阅读与原始命令；未完成 W1 接口冻结，不是实现或工程验收。

树：/cra/memory/mx_memory/MiLAi-worktrees/v13-3-edm-cep-method-implementation
分支：feat/lab-edm-cep-method-implementation-v13-3-20261002
固定基线：22addcbc378a75d7f854ddc4127eb80f45ca52fb。
bootstrap 核对 tracked clean；每条已记静态命令的 src/tests 前后字节身份均相等。初始 inventory 为 216 runtime / 398 engineering test Python 文件；未读取配置正文。

## 已完成的静态观察

|接口／原语|已核对的实际路径与入口|已知能力与最小缺口|
|---|---|---|
|直接字段支持|memory/service.py:624 _field_lineage；service_tools.py:38 FieldSupport|四字段模型显式支持、外层 Source 子集、同候选整字段严格 _json 等值继承已有。旧 map 缺失仅 legacy_whole_version_set；不证明语义蕴含。|
|读时绑定／CAS|service.py:389 _issue_candidate、406 candidate、1152 commit|owner/bank/record/revision/version hash、Source role/hash 与当前 revision 重查已有；Store get/check/put 依赖合作 flock，不是后端原子 CAS。|
|patch／no-op|service.py:565 revise、1267 no_change|content 整体替换、scope named-key merge；无显式 remove。空 patch／同值 patch 在 revise 操作下仍进入 revision+1；显式 no_change 与精确提案 replay 才无新事实 revision。|
|原请求／拒绝保留|service.py:1120 replay_requested、1359 _save_attempt、1367 _reject|原 requested/raw、成功 receipt、拒绝与 proposal_id 冲突已保存；EDM 编译继承说明尚无独立合同。|
|实际事件与处理状态|service.py:889 event_id、894/906 capture_user/tool、971 source、995 sources；application/journal.py:54 __call__|真实角色／内容 hash／幂等 capture、业务 pending/complete/unknown journal 已有。formation_status=formed 仅“曾被历史版本引用”，不能当完整逐事件消费台账。|
|闭合维护|grounded_memory.py:1364 maintain；runners/v13_1_d0.py:297 _maintain_final；v13_1_p5_compare.py:596 _closed_formation|一闭合边界 pending/replay、writer1/repair0 接口已有。实际事件当前含 assistant final；EDM 应另绑定未消费真实 user/tool，final 仅闭合见证，旧状态只读。|
|普通缓存／恢复|v13_1_p5_compare.py:460 _common_recall、548 resume_context|真实 public-turn binding、普通缓存复用与 resume 缺缓存拒绝已有；不需另造检索／重读。|
|selected_snapshot 游标|grounded_memory.py:577 _selection_snapshot、594 _persist_selection、1086 _resolve_selected_snapshot；contracts/read_protocol.py:150 snapshot_key|opaque digest exact get、完整 binding/hash/collision 拒绝、owner/turn/config/Source／历史成员约束已有；不是 EDM 短 alias 的现成公开映射合同。|
|observation 幂等／诚实回执|service.py:690 observe、816 projection_receipt、822 observations、851 selected_observation_member|pending witness→逐 fact 写入→完整 marker／读回；partial 不冒称完成，完整 replay no_change，真实 conflict成员可 exact get。|
|CEP 当前分配|grounded_memory.py:726 _fit、807 _fit_compact；contracts/common_boundary.py:81 bounded_view|现 full/compact/common 路径会截断正文或冲突候选；compact 又按真实成本升级正文。CEP 完整单元、原顺序、超额遗漏后继续是独立新行为，不能视作现有 allocator。|
|native 生命周期|integrations/memory/mem0.py:111 ctor、174 close、244 snapshot、255 add_archive；p5_compare.py:560 native_read、961 _native_readback；P5:578 evidence_before_close|实际 owner-filter snapshot→get/history、infer=True、evidence-before-close 与既有公开构造／新进程 reopen 工程测试入口存在；get_all 默认截断、get 无 owner filter，native 不拥有 M revision/CAS。未执行该测试，不保证部分 SDK 初始化的全部资源闭合。|
|共享 admission|providers/generation_admission.py:60 ctor、147 reserve；chat_bridge.py:165 begin_public_message；P5:973；Mem0 _ChatCompletions:61|真实 public-message owner/bank/session/request/config identity、start/resume fail-closed、durable reserve-before-dispatch、Unknown 不退位已存在。当前 key 是每 public message，并非轨迹累计上限；新设计不能把每条消息上限冒称每轨迹额度。|

还查看了 contextual_memory/write_contract.py 的精确 fragment patch／source-delta 与 local_state_attention 的 pending/acknowledge 概念。这些是不同方法族；不迁入其独立存储或多读循环，只能复用适用的纯原语。

## 待授权后的最小控制建议（本轮未运行）

1. EDM：空 changes、同 UTF8 content set、类型精确 scope、missing/null 与显式 remove；事实版本不增但原提案／编译继承／消费 decision 原件保留。changed 字段仍走现有 Source/role/hash/CAS 守卫。
2. Alias：实际快照 owner/ID/revision/version hash 全绑定；错 owner／跨 snapshot／stale／hash改动／碰撞及 reopen 拒绝；alias 不替模型选择来源。
3. Delta Writer：已消费与未消费 user/tool、Host final／retrieved 排除、缺源／多源／Unknown／partial，当前 trigger 与历史支持分开；不新增 generation/read/retry。
4. CEP：冻结候选/rank/版本/Source ranges，完整 current/history/Source/冲突组按原顺序 exact-token 装入；首大单元遗漏后后续小单元仍可送；metadata 超额显式失败。2048/max6、完整请求成本和服务器完整 audit 对象另验。
5. 复用已存在工程测试：direct_support、read_protocol、observation、generation_admission、common_boundary 与公开 Mem0 constructor/close/process-reopen。新 W1 没有重复执行它们。

## 原件与限制

实际命令／原 stdout/stderr/rc：commands.json 与 *.stdout.log/*.stderr.log。
原 src/tests 完整 byte map：bootstrap.json、actual-source-test-maps.json。
准确读取区间／源码 SHA：read-snapshots.json；原文件：snapshots/。
全部当前已有文件逐 SHA：paused-originals-index.json；状态：paused-status.json。

两次 rg 路径探测 rc2 已原样保留：primitive-inventory 的错误 admission 测试路径；historical-primitives-discovery 的两个不存在模块路径。没有补造运行验证。
公共 Mem0 checkout HEAD 静态核对 f8082a7345dadd9e042ebbc40b57b1498c8f6d63；Lab pin 同值。仅查方法位置，未读取或核对安装 metadata/module byte 身份、未运行 SDK。

0 方法修改，0 pytest/SDK/package 执行，0 generation/embedding HTTP，0 实验，0 新检索，0 commit/push。未读 Root 场景／配置／冻结／rubric／评分／实际 artifacts／账本／PR／新 benchmark/gold。所有旧树／旧封存结果不变。
