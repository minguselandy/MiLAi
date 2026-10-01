# v13.2 结果快照、读取反馈和保存回执通信的限定工程验收

本次接受默认关闭的 A/B/C 通用实现及最终源码的本地工程检查。没有新模型样本；原 R7 的来源、保存主张、任务失败和费用保持。完整计划 ACTIVE，48 条要求状态仍为 4 PASSED_SCOPED / 27 PARTIAL / 1 NOT_PASSED / 16 NOT_VERIFIED，E0 NOT_PASSED、D4 NOT_ADMITTED、Product NO_GO。

Source 原提交 `5c8aecbccc406a5971ea1ea08b54dcffc74ac6ca` 基于 `7511ddf73691cdb75755e774e47a558391aa6aaf`，精确 11 路径转入 Root `61456c6ad45db93523c962f691791af7be9f56da`。8 个既有运行文件、1 个新 contract、2 个新工程测试以外无源码变更，旧测试和完整配置保持。范围和方法输入见[实现范围](V13_2_READ_PROTOCOL_IMPLEMENTATION_SCOPE.md)、[已保存文献与项目](V13_2_DESIGN_LITERATURE.md)，机器验收见 [manifest](../data/manifests/v13-2-read-protocol-implementation-acceptance.json)。Source 继续 READY/HOLD。

## 实际变化与边界

| 因素 | 默认 | opt-in | 实际变化 |
|---|---|---|---|
| A `memory_read_protocol` | `legacy` | `selected_snapshot_v1` | ordinary 和每次 explicit query 的实际选中结果分别绑定不可变快照，按真实 cursor exact get。 |
| B `tool_read_feedback` | `legacy` | `typed_read_v1` | 8 个有限原读取 guard/快照缺失撤销，以实际 typed exception 返回原 tool name/call ID/error 状态。 |
| C `tool_save_communication` | `legacy` | `completed_receipt_v1` | 共同 bridge/catalog、M ordinary policy 和单次 closed writer 说明已完成逐项回执与保存时序。 |

因素独立；A 要求原 bounded reader、event-bound、read-handle 能力。8 个合法 A/B/C 组合实际走 service/catalog/builder/hook/invoke；未知值和 model/service/freeze/start-resume 漂移在派发前拒绝。native reader 无这些能力时不补造 Source、revision 或 CAS。没有运行时语义分类器、案例/语言分支、隐式当前 Source、来源合并、自动分页、自动重试、额外付费修复或最终答复重写。

A 的完整 H 绑定实际 trusted Human/owner/bank/namespace/config/policy、query/request/budget、捕获 bank revision/source index、原选择及 omitted menu 和拟交付 shape；cursor 使用 H 前 24 位。`Store.get/put(recipe.namespace, 'selected_snapshot:'+D)` 保存完整 H/binding、发行 packet SHA 和 receipt SHA，持久化早于普通/query cache 指针发布。同 D 不同完整内容拒绝覆盖。resolver 不枚举普通/query cache、不重新检索、不用最新成员替补。合作 get/check/put 使用既有 service lock，释放后再 read；它不提供后端原子 CAS、跨非合作写事务或全局 HTTP 串行。快照没有 TTL/GC，持久存储随发行量增长。

旧实际 revision 在 dirty refresh 后仅按其历史身份返回，旧 CAS 不因历史可读而合法。观察成员按原 observation ID→实际 projection ID→complete marker→实际 tool Source exact get，保留原事实/hash/role/对象/字段绑定；新 current winner 不替换旧选中成员。缺失/修改 marker、fact 或 Source 及 owner/turn/config/integrity、SDK、未知程序错误继续传播。原 selected-unavailable 仍显示 unavailable。

B 不按 ValueError 文本分类，仅捕捉实际 `ReadProtocolRejected` 类型；有限完整 JSON ≤1024 UTF-8 bytes，保留 `ok=false/status=read_rejected/code/origin/semantic_effect=none`。权限、Source 完整性、预算、CAS、freeze、GraphBubbleUp 及未知异常继续传播。原 ToolNode handler、observer、业务 journal 字节不变；实际本地控制保留有限坏读或未知失败之前已经完成的业务动作。

C 只说明已经完成的逐项 mutation receipt。raw event/observation、业务成功、no_change/replay、语义卡 commit 的效果分别陈述；Host final 之后的 writer 无法回溯确认先前主张。native 共同说明保持实际能力，M 的 Source DTO 不扩张。普通新文本/metadata 计入 2048/max6，全请求另计；提示不能保证模型遵守或语义支持。

## 原件与独立检查

Root 逐字节核对 1764 个索引文件及 3 个避免自引用的 terminal anchors，共 1767 个原文件；128 条命令的原 stdout/stderr/rc、前后完整 maps、执行 driver/snapshot 和全部 13 次非零原件保留。110 个 pytest `current` 目录软链另核对，原绝对指向如实复制，没有冒充新的独立运行目录。262 份原静态方案和 8 份已有 primary 方法输入字节一致。

11 条 validation provenance 独立复算实际执行源码与最终源码的 AST/字节关系、旧测试定义与后续追加定义。早期通过记录保留当时 runtime/test SHA，没有改称最终字节重跑。Source 的未记录 `pwd` 原 tool/输出/rc 另存，当时前后 maps 不可得，不倒补。

Root 接入后的最终 213 运行 / 391 测试 / 316 完整配置 maps 分别为 `dfa818dc9c67ea0c3856e98ff0bb28dab333892b33e21bba07eeac084438ffbd` / `d78ff9aa8d0f096548c85337d89be4f26952bb3e2b45e80fe4bad4f2c52613f1` / `9b6fead193a50d8e0c8eeec06787cac63a743221f0c78c35a65f929a4145606f`。

最终源码安装 socket-denial 后：75 个新有限控制、91 个受影响既有控制通过（19 项明确 deselect），11 路径 ruff、9 运行路径 mypy、package/tools 双边界均通过。没有全套测试、构建、远端 CI 或实际模型质量声明。未执行的嵌套真实输入、SIGKILL 和其他 helper 分支不计通过；本次新测试中的 D0/P5 start/resume 使用隔离合成输入与实际 MockTransport。固定 Python 3.11.13 / SDK / Host7860 / embed7861 / 本地 Qwen tokenizer 保持。

8 个 absent/explicit legacy × native/json_action × bridge/recipe 的完整 catalog/request/grammar/参数/response/成功拒绝 receipt/ordinary 状态原件相等，仅 wall/cpu 时间排除。Root 另核对 8 个 baseline module 原 stdout 等于真实 Git base 的原字节。这个结论限这 8 个真实本地组合，不宣称穷尽全部 legacy 输入。

Root 首次原件审计错误排除了 pytest 合法目录软链，原 rc1/driver/log 保留，修正库存规则后首次核验通过；首次 metadata read 使用不存在的 `python` 得 rc127，改用 `python3` 读取，未重试实验。Source 的初次 collection、mock invoke、入口/生命周期/成员预期、压力记录、ruff/mypy 与编辑 driver 失败都留存，细节见原 HANDOFF/128 回执，不用最终通过掩盖历史失败。

## 原保存压力包独立复算

Root 直接用固定 local tokenizer/chat template 对 10 份保存的原普通 material、完整 wire、付费页和 snapshot SHA/存储字节复算，没有重跑旧 8 包或重建首次未落盘 packet。5 对 selected unit 身份/原 full-unit snapshot hash/顺序保持；delivered/full/prefix/omitted 单独复算。短、多语言长 Source、history/backlinks、大 scope 和双成员冲突组均为合成本地计量。

| 压力输入 | ordinary legacy→A+B+C | whole prompt legacy→A+B+C | Source delivered / selected | actual chosen body codepoints legacy→A+B+C |
|---|---|---|---|---|
| short | 1340→1517 | 3749→4829 | 1/1→1/1，均 full | [394]→[394] |
| long-multiple | 2047→2048 | 4456→5360 | 3/6→2/6，均 prefix | [178,183,210]→[672,606] |
| history-backlinks | 2047→2033 | 4456→5345 | 0/6→1/6，后者 prefix | [363]→[65,0] |
| large-scope | 2048→2035 | 4457→5347 | 0/4→3/4，后者 prefix | [228]→[186,38,51] |
| conflicting-observation | 2043→2047 | 4452→5359 | 2/6→1/6，均 prefix | [0,148,129]→[0,499] |

history/backlinks 的 current selected2，legacy 仅交付 1 个 363 字符 prefix，A+B+C current 全部 omitted；historical selected2，legacy 全 omitted，A+B+C 交付 1 个 65 字符 prefix；其额外 Source prefix 0 字符。large scope 的 current selected1 在 A+B+C 全 omitted，historical selected1 两侧均 omitted。metadata 和 C 说明与原 allocator 共同影响交付，不作压缩收益、可读性或质量改善结论，也没有据此调参。

冲突组两侧均 selected/delivered/full/prefix/omitted=1/1/0/1/0，保留 `status=conflict/current_verified=false/candidate_count=2`，两个候选正文都 omitted。追加 pair 的付费页 1528→1863 tokens，只含 Source pointers、search delta0；已交付的冲突 stub 不属于完全 omitted 的 menu，所以此页没有交付冲突候选正文。有限 exact-member/history 控制是另一证据，不能改称本包 full-body delivery。

所有 ordinary/付费 pointer 页 ≤2048，candidate identities≤6；whole wire 仍另预留 4096 output+64 safety。A 存储行 UTF-8 字节为 short3644、long7826、history11858、scope6682、conflict8899。Root 在冲突 pair 重算保存的完整 selected units SHA；旧 8 包没有独立保存全 selected units 原正文，只核对原 descriptor hashes、snapshot binding 和已交付单位，不重建缺失原文。原件保留已明确存在的 metadata/body allocation 退化。

## 后续实际实验条件

原连续实际账本 SHA `374fcef4dd8a3082d352e2e936f68601edd65ba142880655349cfc68e652b15f` 前后不变：9200 generation / 25,757,358 known / 25,787,745 charged / historical unknown1；embedding920,843 / unknown0。本轮实际 generation/embedding HTTP 均0，合成 Mock ledger 独立标识，无新零账本替换/退款/成本收益。

全局共享 HTTP owner/continuous-ledger lease 仍待独立实现与验收，snapshot service lock 和[逐轨迹审查 controller](V13_2_STAGED_COHORT_REVIEW.md)的父 job lock 不替代它。下一实际 E0 须新 runtime/config/input/route/wire/ledger freeze 和 GitHub pre-first-HTTP 精确核对；原 R7 不重跑，逐轨迹 Root 审查不当独立 Judge。保存资料仍为 17 论文 / 12 项目组、715 唯一文件 / 114 本地链接，此阶段没有新增检索资源。

回滚到 Root 接入前 `6f952b6d52fba025568ace263a32d195e1e36423` 可退出本实现；原 main 回滚身份 `95bf708bfd8aac9f7855485166e3bf739928b949` 保持。当前源码接受仅供后续研究，不升级 D4 或 Product 状态。
